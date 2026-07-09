"""[엔진 진입점] 실적·IR 캘린더 수집 — DART 공시 → Supabase(engine_cache) 저장.

FnGuide 캘린더의 '잠정실적발표 / IR|실적발표 / IR|경영현황'에 해당하는 일정을
DART 공시에서 직접 수집한다(프로브 v1·v2로 검증 완료).

  · 잠정실적발표  = 공정공시(I002) 중 「영업(잠정)실적」 — 발표일(rcept_dt) 당일 이벤트
  · IR 일정       = 수시공시(I001)·안내공시(I003) 중 「기업설명회(IR)개최」
                    → 원문(document.xml)에서 개최 시작일·실시목적·실시방법 파싱
                    → 목적에 '실적' 포함이면 IR|실적발표, 아니면 IR|경영현황
                    → 개최 시작일(미래 가능) 이벤트

대상 종목(과다 방지): 시총 상위 CAL_TOP_N(기본 200) ∪ 주도주(leaders 최신) ∪ 워치리스트.
  · 시총 순위 = data.go.kr 주식시세(getStockPriceInfo)의 mrktTotAmt (T+1, 빈 날은 소급 탐색)
  · 워치리스트는 종목명 저장이므로 stock_master(name→code)로 해석

저장: engine_cache(cache_key='cal_disclosures') payload = {"events": [...], "asof": ...}
  이벤트: {date, code, name, kind(earn|ir_earn|ir_biz), note, rcept_no}
  실행마다 기존 payload와 rcept_no 기준 병합(멱등) → 과거 60일 이전은 정리.
  뷰어(modules/calendar_view.py)가 이 캐시를 읽어 달력에 칩으로 표시한다.

실행: python -m engine.calendar_collect   (GitHub Actions calendar.yml, 평일 2슬롯)
키: DART_API_KEY · DATA_GO_KR_KEY(또는 MOLIT_API_KEY) · SUPABASE_URL/KEY
환경: CAL_LOOKBACK_DAYS(기본 3, 최초 백필 시 30 권장) · CAL_TOP_N(기본 200)
"""

import io
import os
import re
import sys
import time
import traceback
import zipfile
from datetime import date, datetime, timedelta

import requests

_UA = {"User-Agent": "Mozilla/5.0 (compatible; DYMonitoring-Calendar/1.0)"}

_DATAGO = "https://apis.data.go.kr/1160100/service"
_PRICE = f"{_DATAGO}/GetStockSecuritiesInfoService/getStockPriceInfo"

_DART = "https://opendart.fss.or.kr/api"
_DART_LIST = f"{_DART}/list.json"
_DART_DOC = f"{_DART}/document.xml"

CACHE_KEY = "cal_disclosures"
_EARN_PAT = re.compile(r"잠정실적|영업\s*\(잠정\)\s*실적")
_IR_PAT = re.compile(r"기업설명회|IR\s*개최")
_DATE_PAT = re.compile(r"\d{4}-\d{2}-\d{2}")

KEEP_PAST_DAYS = 60        # 과거 이벤트 보존(달력 지난 칸 표시용)
KEEP_FUTURE_DAYS = 180     # 미래 이벤트 상한(파싱 오류 방어)
MAX_EVENTS = 800           # payload 총량 상한
MAX_DOC_FETCH = 60         # 1회 실행당 IR 원문 조회 상한(시간 방어)


def _log(msg):
    print(f"[cal_collect] {msg}", flush=True)


def _dartk() -> str:
    return (os.environ.get("DART_API_KEY") or "").strip()


def _dk() -> str:
    return (os.environ.get("DATA_GO_KR_KEY") or os.environ.get("MOLIT_API_KEY") or "").strip()


def _lookback() -> int:
    try:
        return max(1, min(60, int(os.environ.get("CAL_LOOKBACK_DAYS", "3"))))
    except ValueError:
        return 3


def _top_n() -> int:
    try:
        return max(10, min(1000, int(os.environ.get("CAL_TOP_N", "200"))))
    except ValueError:
        return 200


def _digits(x, n=None):
    s = re.sub(r"[^0-9]", "", str(x or ""))
    return s[:n] if n else s


def _get_json(url, params, timeout=30, retries=3):
    """GET → JSON. 타임아웃·연결오류만 재시도."""
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, headers=_UA, timeout=timeout)
            r.raise_for_status()
            txt = r.text.strip()
            if txt.startswith("<"):
                raise RuntimeError(f"비-JSON 응답: {txt[:120]}")
            return r.json()
        except (requests.Timeout, requests.ConnectionError) as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


# ── 대상 종목(universe): 시총 상위 N ∪ 주도주 ∪ 워치리스트 ──────────

def _top_by_mcap(key, n):
    """data.go.kr 주식시세 최신 basDt의 시가총액(mrktTotAmt) 상위 n 종목코드."""
    if not key:
        _log("DATA_GO_KR_KEY 없음 → 시총 상위 생략")
        return set()
    today = date.today()
    for probe in range(0, 9):
        basdt = (today - timedelta(days=probe)).strftime("%Y%m%d")
        rows, page = {}, 1
        try:
            while page <= 3:
                data = _get_json(_PRICE, {"serviceKey": key, "resultType": "json",
                                          "numOfRows": 5000, "pageNo": page,
                                          "basDt": basdt})
                body = (data.get("response") or {}).get("body") or {}
                it = ((body.get("items") or {}).get("item")) or []
                if isinstance(it, dict):
                    it = [it]
                for x in it:
                    code = _digits(x.get("srtnCd"), 6)
                    try:
                        cap = float(x.get("mrktTotAmt") or 0)
                    except (TypeError, ValueError):
                        cap = 0
                    if code and cap > 0:
                        rows[code] = max(cap, rows.get(code, 0))
                total = int(body.get("totalCount") or 0)
                if not it or page * 5000 >= total:
                    break
                page += 1
        except Exception as e:
            _log(f"시세 basDt={basdt} 오류: {str(e)[:80]}")
            continue
        if rows:
            top = sorted(rows.items(), key=lambda kv: kv[1], reverse=True)[:n]
            _log(f"시총 상위 {len(top)}종목 확보 (basDt={basdt}, 전체 {len(rows)})")
            return {c for c, _ in top}
    _log("시총 상위 조회 실패(빈 응답)")
    return set()


def _leaders_codes(db) -> set:
    try:
        payload = db.load_leaders() or {}
        codes = {_digits(s.get("code"), 6) for s in (payload.get("stocks") or [])}
        codes.discard("")
        _log(f"주도주 {len(codes)}종목")
        return codes
    except Exception as e:
        _log(f"주도주 로드 실패: {str(e)[:80]}")
        return set()


def _watchlist_codes(db) -> set:
    """워치리스트(종목명) → stock_master(name→code) 해석."""
    try:
        from modules.watchlist import load_watchlist
        names = [str(x).strip() for x in (load_watchlist() or []) if str(x).strip()]
    except Exception:
        names = []
    if not names:
        return set()
    try:
        master = db.load_stock_master() or []
    except Exception:
        master = []
    n2c = {str(r.get("name", "")).strip(): _digits(r.get("code"), 6) for r in master}
    codes = {n2c[n] for n in names if n2c.get(n)}
    _log(f"워치리스트 {len(names)}건 중 코드 해석 {len(codes)}건")
    return codes


def build_universe(db):
    """(대상 종목코드 set, code→종목명 dict). 종목명은 stock_master 우선."""
    uni = _top_by_mcap(_dk(), _top_n())
    uni |= _leaders_codes(db)
    uni |= _watchlist_codes(db)
    names = {}
    try:
        for r in (db.load_stock_master() or []):
            c = _digits(r.get("code"), 6)
            if c:
                names[c] = str(r.get("name", "")).strip()
    except Exception:
        pass
    _log(f"대상 종목 합계 {len(uni)}종목")
    return uni, names


# ── DART 공시 검색 ──────────────────────────────────────────────

def _dart_scan(key, bgn, end, detail, pat, max_pages=40):
    """list.json 분류(detail) 스캔 → report_nm이 pat에 매칭되는 행 목록."""
    hits = []
    for cls in ("Y", "K"):
        page = 1
        while page <= max_pages:
            try:
                data = _get_json(_DART_LIST, {
                    "crtfc_key": key, "bgn_de": bgn, "end_de": end,
                    "pblntf_detail_ty": detail, "corp_cls": cls,
                    "page_no": page, "page_count": 100})
            except Exception as e:
                _log(f"  {detail}/{cls} p{page} 실패: {str(e)[:80]}")
                break
            if str(data.get("status")) != "000":
                break
            rows = data.get("list") or []
            hits += [x for x in rows if pat.search(str(x.get("report_nm", "")))]
            total = int(data.get("total_count") or 0)
            if page * 100 >= total or not rows:
                break
            page += 1
    return hits


def _fmt_rcept(rcept_dt) -> str:
    s = _digits(rcept_dt, 8)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 else ""


# ── IR 원문 파싱: 개최 시작일·목적·방법 ─────────────────────────

def _dart_doc_flat(key, rcept_no, cap=300_000) -> str:
    """document.xml(zip) → 태그·엔티티·공백 제거 평문. 실패 시 ''."""
    r = requests.get(_DART_DOC, params={"crtfc_key": key, "rcept_no": rcept_no},
                     headers=_UA, timeout=40)
    r.raise_for_status()
    if r.content[:2] != b"PK":
        return ""
    z = zipfile.ZipFile(io.BytesIO(r.content))
    body = ""
    for nm in z.namelist():
        raw = z.read(nm)
        for enc in ("utf-8", "cp949", "euc-kr"):
            try:
                body += raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if len(body) > cap:
            break
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"&[a-zA-Z#0-9]+;", " ", body)
    return re.sub(r"\s+", "", body)


def parse_ir_doc(flat: str) -> dict:
    """IR 공시 평문 → {start, end, purpose, method}. 프로브 검증 구조:
    '…일시…시작일종료일시작시간종료시간2026-08-062026-08-0614:0015:00…
     실시목적…실시방법…주요내용…'"""
    out = {"start": "", "end": "", "purpose": "", "method": ""}
    if not flat:
        return out
    # 개최일: '일시' 라벨 이후 첫 두 개의 YYYY-MM-DD (없으면 문서 앞부분에서)
    p = flat.find("일시")
    seg = flat[p:p + 400] if p >= 0 else flat[:2000]
    dates = _DATE_PAT.findall(seg) or _DATE_PAT.findall(flat[:4000])
    if dates:
        out["start"] = dates[0]
        out["end"] = dates[1] if len(dates) > 1 else dates[0]
    m = re.search(r"실시목적(.*?)(?:\d\.|실시방법)", flat)
    if m:
        out["purpose"] = m.group(1)[:60]
    m = re.search(r"실시방법(.*?)(?:\d\.|주요내용)", flat)
    if m:
        out["method"] = m.group(1)[:24]
    return out


def _valid_event_date(s: str, today: date) -> bool:
    try:
        d = datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return False
    return (today - timedelta(days=KEEP_PAST_DAYS)
            <= d <= today + timedelta(days=KEEP_FUTURE_DAYS))


# ── 수집 본체 ──────────────────────────────────────────────────

def collect(db) -> list:
    key = _dartk()
    if not key:
        raise RuntimeError("DART_API_KEY가 없어요.")
    uni, names = build_universe(db)
    if not uni:
        raise RuntimeError("대상 종목(universe)이 비어 있음 — 시세·leaders·워치리스트 모두 실패.")

    today = date.today()
    bgn = (today - timedelta(days=_lookback())).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    events = []

    # ① 잠정실적발표 (공정공시 I002) — 발표일 당일 이벤트
    earn = _dart_scan(key, bgn, end, "I002", _EARN_PAT)
    n_e = 0
    for x in earn:
        code = _digits(x.get("stock_code"), 6)
        if not code or code not in uni:
            continue
        d = _fmt_rcept(x.get("rcept_dt"))
        if not _valid_event_date(d, today):
            continue
        nm = names.get(code) or str(x.get("corp_name", "")).strip()
        events.append({"date": d, "code": code, "name": nm, "kind": "earn",
                       "note": "잠정실적 발표 (DART 공정공시)",
                       "rcept_no": str(x.get("rcept_no", ""))})
        n_e += 1
    _log(f"잠정실적: 검색 {len(earn)}건 → 대상 {n_e}건")

    # ② IR 개최 (수시 I001 + 안내 I003) — 원문에서 개최 시작일·목적 파싱
    ir = _dart_scan(key, bgn, end, "I001", _IR_PAT) + _dart_scan(key, bgn, end, "I003", _IR_PAT)
    seen, n_ir, n_doc = set(), 0, 0
    for x in ir:
        rcept = str(x.get("rcept_no", ""))
        code = _digits(x.get("stock_code"), 6)
        if not rcept or rcept in seen or not code or code not in uni:
            continue
        seen.add(rcept)
        if n_doc >= MAX_DOC_FETCH:
            _log(f"IR 원문 조회 상한({MAX_DOC_FETCH}) 도달 — 이후는 다음 실행에서")
            break
        try:
            flat = _dart_doc_flat(key, rcept)
            n_doc += 1
        except Exception as e:
            _log(f"IR 원문 실패 {rcept}: {str(e)[:70]}")
            continue
        info = parse_ir_doc(flat)
        d = info["start"] or _fmt_rcept(x.get("rcept_dt"))
        if not _valid_event_date(d, today):
            continue
        kind = "ir_earn" if "실적" in info["purpose"] else "ir_biz"
        label = "IR·실적발표" if kind == "ir_earn" else "IR·경영현황"
        note = label + (f" — {info['method']}" if info["method"] else "")
        if info["end"] and info["end"] != d:
            note += f" (~{info['end'][5:].replace('-', '/')})"
        nm = names.get(code) or str(x.get("corp_name", "")).strip()
        events.append({"date": d, "code": code, "name": nm, "kind": kind,
                       "note": note, "rcept_no": rcept})
        n_ir += 1
        time.sleep(0.25)
    _log(f"IR: 검색 {len(ir)}건 → 원문 {n_doc}건 조회 → 대상 {n_ir}건")
    return events


def merge_and_save(db, new_events: list) -> int:
    """기존 캐시와 rcept_no 기준 병합(멱등) → 보존기간 정리 → 저장."""
    today = date.today()
    old = (db.cache_get(CACHE_KEY) or {}).get("events") or []
    by_rcept = {e.get("rcept_no"): e for e in old if e.get("rcept_no")}
    for e in new_events:
        by_rcept[e["rcept_no"]] = e          # 신규가 기존을 덮음(재수집 시 최신 파싱 반영)
    merged = [e for e in by_rcept.values() if _valid_event_date(e.get("date", ""), today)]
    merged.sort(key=lambda e: (e.get("date", ""), e.get("kind", ""), e.get("name", "")))
    merged = merged[-MAX_EVENTS:]
    ok = db.cache_set(CACHE_KEY, {
        "events": merged,
        "asof": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    if not ok:
        raise RuntimeError("engine_cache 저장 실패")
    return len(merged)


def main():
    try:
        from modules import db
    except Exception as e:
        _log(f"db 모듈 로드 실패: {e}")
        return 1
    if not db.supabase_configured():
        _log("SUPABASE 미설정 — 저장 불가(키 확인).")
        return 1
    try:
        new_events = collect(db)
    except Exception:
        _log("수집 실패:")
        traceback.print_exc()
        return 1
    try:
        total = merge_and_save(db, new_events)
        _log(f"저장 완료 — 신규 {len(new_events)}건 병합, 총 {total}건 보유")
        return 0
    except Exception:
        _log("저장 실패:")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
