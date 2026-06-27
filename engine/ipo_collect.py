"""[엔진] 증시 IPO 탭 데이터 수집 → dict 반환 (저장은 ipo_run이 담당).

설계(★silent-fail 방지 · 너 원칙대로)
  · '스파인'(목록·시총·현재가·등락·상장일)은 100% 확정 API인 금융위 주식시세정보만으로 만든다.
      - 최근 2년 신규상장 판별 = 오늘 스냅샷 − 2년전 스냅샷의 종목코드 차집합
      - 시총 필터 = mrktTotAmt ≥ 5,000억
      - 상장일 = 그 종목의 시세 첫 등장일(min basDt). (getCorpOutline가 활성이면 그 값 우선)
  · '살'(회사소개·보호예수)은 best-effort. 활성/엔드포인트가 확인되면 채우고, 아니면 빈값으로
      두되 단계별 커버리지를 로그로 분명히 찍는다(조용히 빈값 위장 금지).
  · 향후 IPO = DART 증권신고서(지분증권) 접수목록(미상장 corp_cls=E).

키(엔진 규칙: 환경변수)
  DATA_GO_KR_KEY (없으면 MOLIT_API_KEY)  · DART_API_KEY

확정 필드(프로브 검증)
  시세정보 item: basDt, srtnCd, isinCd, itmsNm, mrktCtg, clpr, fltRt, lstgStCnt, mrktTotAmt
  DART list:    corp_code, corp_name, stock_code, corp_cls, report_nm, rcept_no, rcept_dt, flr_nm
  getCorpOutline_V2(실측): crno, corpNm, enpMainBizNm, enpKrxLstgDt, enpKosdaqLstgDt, sicNm ...
"""

import os
import sys
import time
import traceback
from datetime import date, datetime, timedelta

import requests

_UA = {"User-Agent": "Mozilla/5.0 (compatible; DYMonitoring-IPO/1.0)"}

_DATAGO = "https://apis.data.go.kr/1160100/service"
_PRICE = f"{_DATAGO}/GetStockSecuritiesInfoService/getStockPriceInfo"
_CORP = f"{_DATAGO}/GetCorpBasicInfoService_V2/getCorpOutline_V2"   # 기업기본정보(활성 필요)
# 주식발행정보 의무보호예수 — 오퍼레이션명이 문서상 불명확 → 1회 자동탐지
_ISSU_SERVICES = ["GetStocIssuInfoService", "GetStockIssuInfoService"]
_LOCK_OPS = ["getMnatryHldDpsRtrInfo", "getMandatoryDpsRtrInfo",
             "getMandatoryDepositReturnInfo", "getOblgDpsRtrInfo", "getHldDpsRtrInfo"]

_DART = "https://opendart.fss.or.kr/api"
_DART_LIST = f"{_DART}/list.json"

CAP_MIN = 200_000_000_000          # 5,000억 (원)
RECENT_DAYS = 731                  # 최근 2년(+1)
MAX_RECENT = 60                    # 뷰어 표시 상한
_EXCLUDE = ("스팩", "기업인수목적")


# ── 키 ──
def _dk() -> str:
    return (os.environ.get("DATA_GO_KR_KEY") or os.environ.get("MOLIT_API_KEY") or "").strip()


def _dartk() -> str:
    return (os.environ.get("DART_API_KEY") or "").strip()


def _log(msg):
    print(f"[ipo] {msg}", flush=True)


# ── data.go.kr 공통 ──
def _get(url, params, timeout=30, retries=3):
    """GET → JSON. 네트워크 타임아웃·연결오류만 재시도(HTTP 4xx/비-JSON은 즉시 전파)."""
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, headers=_UA, timeout=timeout)
            r.raise_for_status()
            txt = r.text.strip()
            if txt.startswith("<"):
                raise RuntimeError(f"비-JSON 응답(인증/권한/파라미터): {txt[:160]}")
            return r.json()
        except (requests.Timeout, requests.ConnectionError) as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def _items(data):
    body = (data.get("response") or {}).get("body") or {}
    it = ((body.get("items") or {}).get("item")) or []
    if isinstance(it, dict):
        it = [it]
    return it, body


def _f(x):
    try:
        return float(str(x).replace(",", "").strip())
    except (ValueError, TypeError, AttributeError):
        return None


def _fmt_cap(won):
    if won is None:
        return "-"
    if won >= 1_0000_0000_0000:          # 1조
        s = f"{won / 1_0000_0000_0000:.1f}조"
        return s.replace(".0조", "조")
    return f"{round(won / 1_0000_0000):,}억"


def _fmt_date(yyyymmdd):
    s = str(yyyymmdd or "")
    return f"{s[:4]}.{s[4:6]}.{s[6:8]}" if len(s) >= 8 else ""


# ── 시세정보: 최신 영업일 / 스냅샷 / 상장일 ──
def _latest_basdt(key):
    """오늘부터 거꾸로 explicit basDt로 조회(인덱스 사용→빠름). 데이터 있는 첫 날 반환.
       basDt 없이 호출하면 전체(수백만건)를 스캔해 느리므로 절대 그렇게 하지 않는다."""
    for i in range(0, 12):
        d = (date.today() - timedelta(days=i)).strftime("%Y%m%d")
        try:
            it, _ = _items(_get(_PRICE, {"serviceKey": key, "resultType": "json",
                                         "numOfRows": 1, "pageNo": 1, "basDt": d}))
        except Exception:
            continue
        if it:
            return d
    return None


def _snapshot(key, basdt, rows=5000):
    out, page = [], 1
    while True:
        it, body = _items(_get(_PRICE, {"serviceKey": key, "resultType": "json",
                                        "numOfRows": rows, "pageNo": page, "basDt": basdt}))
        out.extend(it)
        total = int(body.get("totalCount") or 0)
        if not it or page * rows >= total or page >= 12:
            break
        page += 1
    return out


def _nearest_past_basdt(key, target_date):
    for i in range(0, 9):
        d = (target_date - timedelta(days=i)).strftime("%Y%m%d")
        it, _ = _items(_get(_PRICE, {"serviceKey": key, "resultType": "json",
                                     "numOfRows": 1, "pageNo": 1, "basDt": d}))
        if it:
            return d
    return None


def _listing_date_via_price(key, srtn):
    """그 종목 시세의 첫 등장일(min basDt) ≈ 상장일. srtnCd 필터가 무시되면 None."""
    start = (date.today() - timedelta(days=RECENT_DAYS + 60)).strftime("%Y%m%d")
    end = date.today().strftime("%Y%m%d")
    try:
        it, _ = _items(_get(_PRICE, {"serviceKey": key, "resultType": "json",
                                     "numOfRows": 900, "pageNo": 1, "srtnCd": srtn,
                                     "beginBasDt": start, "endBasDt": end}))
    except Exception:
        return None
    if not it:
        return None
    codes = {str(x.get("srtnCd")) for x in it}
    if codes != {str(srtn)}:            # 필터 미적용(전체가 섞임) → 신뢰 불가
        return None
    ds = [x.get("basDt") for x in it if x.get("basDt")]
    return min(ds) if ds else None


# ── 기업기본정보(getCorpOutline): 회사소개 + 상장일 + crno (활성 필요) ──
_corp_disabled = False


def _corp_outline(key, corp_nm):
    global _corp_disabled
    if _corp_disabled or not corp_nm:
        return None
    try:
        it, _ = _items(_get(_CORP, {"serviceKey": key, "resultType": "json",
                                    "numOfRows": 3, "pageNo": 1, "corpNm": corp_nm}))
    except Exception as e:
        if "403" in str(e) or "비-JSON" in str(e):
            _corp_disabled = True
            _log("기업기본정보 비활성/권한오류 → 회사소개·crno 생략 "
                 f"(활용신청: data.go.kr 15043184). 상세: {str(e)[:80]}")
        return None
    nq = "".join(str(corp_nm).split())
    for x in it:
        nm = "".join(str(x.get("corpNm", "")).split())
        if nm == nq or nq in nm:
            return x
    return it[0] if it else None


# ── 보호예수: 1회 엔드포인트 자동탐지 후 crno로 조회 ──
_lock_endpoint = "unset"   # "unset" | None | "https://.../op"


def _discover_lock_endpoint(key, sample_crno):
    global _lock_endpoint
    if _lock_endpoint != "unset":
        return _lock_endpoint
    for svc in _ISSU_SERVICES:
        for op in _LOCK_OPS:
            url = f"{_DATAGO}/{svc}/{op}"
            try:
                _items(_get(url, {"serviceKey": key, "resultType": "json",
                                  "numOfRows": 1, "pageNo": 1, "crno": sample_crno}))
                _lock_endpoint = url
                _log(f"보호예수 엔드포인트 확인: {svc}/{op}")
                return url
            except Exception:
                continue
    _lock_endpoint = None
    _log("보호예수 엔드포인트 자동탐지 실패 → 이번 수집은 보호예수 생략(후보 5종 모두 오류). "
         "주식발행정보(15043423) 활용신청 여부·오퍼레이션명을 알려주면 확정할게.")
    return None


def _lockup(key, crno):
    if not crno:
        return ""
    url = _discover_lock_endpoint(key, crno)
    if not url:
        return ""
    try:
        it, _ = _items(_get(url, {"serviceKey": key, "resultType": "json",
                                  "numOfRows": 50, "pageNo": 1, "crno": crno}))
    except Exception:
        return ""
    if not it:
        return ""
    today = date.today().strftime("%Y%m%d")
    future = []
    for x in it:
        for k in ("rtrDt", "rtrnDt", "depoRtrDt", "scrsDepoRtrDt", "untilDt", "rlsDt"):
            v = x.get(k)
            if v and str(v) >= today:
                future.append(str(v))
                break
    if future:
        future.sort()
        return f"미해제 {len(future)}건 · 최근 해제 {_fmt_date(future[0])}"
    return f"등록 {len(it)}건"


# ── DART: 향후 IPO(증권신고서 지분증권 · 미상장) ──
def _dart_upcoming(key, days=75):
    if not key:
        _log("DART_API_KEY 없음 → 향후 일정 생략")
        return []
    end = date.today().strftime("%Y%m%d")
    bgn = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
    out, seen, page = [], set(), 1
    while page <= 5:
        try:
            data = _get(_DART_LIST, {"crtfc_key": key, "bgn_de": bgn, "end_de": end,
                                     "pblntf_detail_ty": "C001", "corp_cls": "E",
                                     "page_no": page, "page_count": 100})
        except Exception as e:
            _log(f"DART 향후 목록 실패: {str(e)[:80]}")
            break
        if str(data.get("status")) != "000":
            break
        rows = data.get("list") or []
        for r in rows:
            rn = r.get("report_nm", "")
            if "증권신고서" not in rn or "지분증권" not in rn:
                continue
            nm = r.get("corp_name", "")
            if not nm or nm in seen or any(t in nm for t in _EXCLUDE):
                continue
            seen.add(nm)
            out.append({
                "name": nm,
                "state": f"증권신고서 접수 {_fmt_date(r.get('rcept_dt'))}",
                "dday": "", "under": "", "method": "", "intro": "", "soon": False,
                "dart_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r.get('rcept_no','')}",
            })
        total = int(data.get("total_count") or 0)
        if page * 100 >= total or not rows:
            break
        page += 1
    return out[:12]


# ── 수집 ──
def collect() -> dict:
    key = _dk()
    if not key:
        raise RuntimeError("DATA_GO_KR_KEY(또는 MOLIT_API_KEY)가 없어요.")

    basdt = _latest_basdt(key)
    if not basdt:
        raise RuntimeError("주식시세정보 최신 기준일을 가져오지 못했어요.")
    _log(f"최신 기준일 basDt={basdt}")

    today_snap = _snapshot(key, basdt)
    _log(f"오늘 스냅샷 {len(today_snap)}건")

    past_target = date(int(basdt[:4]) - 2, int(basdt[4:6]), int(basdt[6:8]))
    past_basdt = _nearest_past_basdt(key, past_target)
    past_codes = set()
    if past_basdt:
        past_codes = {str(x.get("srtnCd")) for x in _snapshot(key, past_basdt)}
        _log(f"2년전 스냅샷 basDt={past_basdt} {len(past_codes)}종목")
    else:
        _log("2년전 스냅샷 실패 → 상장일로만 최근성 판정")

    cands = []
    for x in today_snap:
        if str(x.get("mrktCtg", "")).upper() not in ("KOSPI", "KOSDAQ"):
            continue
        cap = _f(x.get("mrktTotAmt"))
        if cap is None or cap < CAP_MIN:
            continue
        nm = str(x.get("itmsNm", ""))
        if any(t in nm for t in _EXCLUDE):
            continue
        if past_codes and str(x.get("srtnCd")) in past_codes:
            continue
        cands.append(x)
    _log(f"시총≥5000억 & 최근상장 후보 {len(cands)}종목")

    recent, n_listed, n_intro, n_lock = [], 0, 0, 0
    cutoff = (date.today() - timedelta(days=RECENT_DAYS)).strftime("%Y%m%d")
    for x in cands:
        srtn = str(x.get("srtnCd"))
        nm = str(x.get("itmsNm", ""))
        mkt = "코스피" if str(x.get("mrktCtg", "")).upper() == "KOSPI" else "코스닥"
        cap = _f(x.get("mrktTotAmt"))

        outline = _corp_outline(key, nm)
        crno = (outline or {}).get("crno") or ""
        intro = (outline or {}).get("enpMainBizNm") or ""
        lstg = ""
        if outline:
            lstg = ((outline.get("enpKosdaqLstgDt") if mkt == "코스닥" else outline.get("enpKrxLstgDt"))
                    or outline.get("enpKrxLstgDt") or outline.get("enpKosdaqLstgDt") or "")
        if not lstg:
            lstg = _listing_date_via_price(key, srtn) or ""
        if lstg and lstg < cutoff:
            continue

        if lstg:
            n_listed += 1
        if intro:
            n_intro += 1
        lock = _lockup(key, crno)
        if lock:
            n_lock += 1

        recent.append({
            "name": nm, "code": srtn, "market": mkt, "sector": mkt,
            "listed": _fmt_date(lstg), "_lstg": lstg,
            "cap": _fmt_cap(cap), "cap_won": cap,
            "price": f"{int(_f(x.get('clpr')) or 0):,}", "pct": _f(x.get("fltRt")),
            "method": "", "ipo_price": "", "valuation": "",
            "lockup": lock, "intro": intro,
        })
        time.sleep(0.05)

    recent.sort(key=lambda r: r.get("_lstg") or "", reverse=True)
    recent = recent[:MAX_RECENT]
    for r in recent:
        r.pop("_lstg", None)

    upcoming = _dart_upcoming(_dartk())
    for u in upcoming:
        o = _corp_outline(key, u["name"])
        if o and o.get("enpMainBizNm"):
            u["intro"] = o["enpMainBizNm"]

    _log(f"완료: 최근상장 {len(recent)}종목 (상장일 {n_listed} · 회사소개 {n_intro} · 보호예수 {n_lock}) "
         f"/ 향후 {len(upcoming)}건")

    return {
        "asof": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "asof_date": date.today().strftime("%Y-%m-%d"),
        "recent": recent,
        "upcoming": upcoming,
    }


if __name__ == "__main__":
    try:
        import json
        print(json.dumps(collect(), ensure_ascii=False)[:5000])
    except Exception:
        traceback.print_exc()
        sys.exit(1)
