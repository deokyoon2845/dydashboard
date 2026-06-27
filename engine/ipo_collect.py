"""[엔진] 증시 IPO 탭 데이터 수집 → dict 반환 (저장은 ipo_run이 담당).

설계(★silent-fail 방지 · 엔진-퍼스트)
  · '스파인'(목록·시총·현재가·등락·상장일·상장후 추이)은 100% 확정 API인
    금융위 주식시세정보(getStockPriceInfo)만으로 만든다.
      - 최근 2년 신규상장 판별 = 오늘 스냅샷 − 2년전 스냅샷의 종목코드 차집합
      - 시총 필터 = mrktTotAmt ≥ CAP_MIN(기본 5,000억)
      - 상장일 = 기업기본정보 enpKrxLstgDt/enpKosdaqLstgDt → 없으면 시세 첫 등장일
      - 추이 스파크라인 = 상장일~최신 일별 종가(srtnCd 필터)를 다운샘플(약 60p)
  · '살'(회사소개·보호예수)은 활성 API로 채운다.
      - 회사소개·상장일·crno = 기업기본정보(getCorpOutline_V2, 15043184)  ← 승인됨
      - 보호예수 = 주식발행정보 V3(GetStocIssuInfoService_V3, 15043423)   ← 승인됨
        · V3 오퍼레이션명이 공식 명세에 미노출 → 후보 자동탐지 + 첫 성공 응답의
          키/샘플을 로그로 남긴다(필드명 확정용). 조용히 빈값 위장 금지.
  · 향후 IPO = DART 증권신고서(지분증권) 접수목록(미상장 corp_cls=E) + 기업소개.
        상장예정일은 접수일 기준 통상 4~6주 후 '예상'으로 표기(원문 파싱 미사용).

  ※ 상장방식·밸류(공모가/PER)는 금융위 API에 없어 필드 자체를 제외함(2025.06 결정).

키(엔진 규칙: 환경변수)
  DATA_GO_KR_KEY (없으면 MOLIT_API_KEY)  · DART_API_KEY

확정 필드(프로브 검증)
  시세정보 item: basDt, srtnCd, isinCd, itmsNm, mrktCtg, clpr, fltRt, lstgStCnt, mrktTotAmt
  기업기본정보 item: crno, corpNm, enpMainBizNm, enpKrxLstgDt, enpKosdaqLstgDt, sicNm ...
  DART list:    corp_code, corp_name, stock_code, corp_cls, report_nm, rcept_no, rcept_dt, flr_nm
"""

import os
import re
import sys
import time
import traceback
from datetime import date, datetime, timedelta

import requests

_UA = {"User-Agent": "Mozilla/5.0 (compatible; DYMonitoring-IPO/1.0)"}

_DATAGO = "https://apis.data.go.kr/1160100/service"
_PRICE = f"{_DATAGO}/GetStockSecuritiesInfoService/getStockPriceInfo"
_CORP = f"{_DATAGO}/GetCorpBasicInfoService_V2/getCorpOutline_V2"   # 기업기본정보(승인됨)

# 주식발행정보 V3 — Base가 /service/ 없이 바로 서비스명. 오퍼레이션명은 자동탐지.
_ISSU_BASE = "https://apis.data.go.kr/1160100/GetStocIssuInfoService_V3"
# 의무보호예수반환정보 조회 후보 오퍼레이션명(첫 성공 1개를 캐시)
_LOCK_OPS = [
    "getOblgItemDpsRtrInfo", "getMandatoryDpsRtrInfo", "getOblgDpsRtrInfo",
    "getMnatryHldDpsRtrInfo", "getMandatoryDepositReturnInfo",
    "getHldDpsRtrInfo", "getStockOblgDpsRtrInfo", "getOblgRtrInfo",
    "getMandatoryHoldDepositReturnInfo", "getDpsRtrInfo",
]

_DART = "https://opendart.fss.or.kr/api"
_DART_LIST = f"{_DART}/list.json"

CAP_MIN = 500_000_000_000          # 5,000억 (원) — 종목 수 과다 방지(2,000억으로 낮추려면 200_000_000_000)
RECENT_DAYS = 731                  # 최근 2년(+1)
MAX_RECENT = 40                    # 뷰어 표시 상한
SPARK_POINTS = 60                  # 스파크라인 다운샘플 점 수
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


def _downsample(vals, n=SPARK_POINTS):
    """리스트를 균등 간격 n개로 다운샘플(처음·끝 보존)."""
    vals = [v for v in vals if v is not None]
    if len(vals) <= n:
        return [round(float(v), 2) for v in vals]
    step = (len(vals) - 1) / (n - 1)
    out = [vals[round(i * step)] for i in range(n)]
    out[-1] = vals[-1]
    return [round(float(v), 2) for v in out]


# ── 시세정보: 최신 영업일 / 스냅샷 ──
def _latest_basdt(key):
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


def _daily_series(key, srtn, start_basdt, end_basdt):
    """그 종목의 일별 종가 시리즈(srtnCd 필터). 필터 미적용 시 []를 반환(신뢰 불가).
       반환: [(basDt, clpr)] basDt 오름차순."""
    rows, page = [], 1
    while page <= 3:
        try:
            it, body = _items(_get(_PRICE, {"serviceKey": key, "resultType": "json",
                                            "numOfRows": 600, "pageNo": page, "srtnCd": srtn,
                                            "beginBasDt": start_basdt, "endBasDt": end_basdt}))
        except Exception:
            break
        if not it:
            break
        codes = {str(x.get("srtnCd")) for x in it}
        if codes - {str(srtn)}:            # 다른 종목이 섞임 → 필터 미적용
            return []
        for x in it:
            d = x.get("basDt")
            c = _f(x.get("clpr"))
            if d and c is not None:
                rows.append((str(d), c))
        total = int(body.get("totalCount") or 0)
        if page * 600 >= total:
            break
        page += 1
    rows.sort(key=lambda r: r[0])
    return rows


# ── 기업기본정보(getCorpOutline): 회사소개 + 상장일 + crno ──
_corp_fail = 0
_corp_disabled = False


def _corp_outline(key, corp_nm):
    """승인된 기업기본정보. 일시 오류엔 관대하게(연속 4회 인증오류 시에만 비활성)."""
    global _corp_fail, _corp_disabled
    if _corp_disabled or not corp_nm:
        return None
    try:
        it, _ = _items(_get(_CORP, {"serviceKey": key, "resultType": "json",
                                    "numOfRows": 3, "pageNo": 1, "corpNm": corp_nm}))
        _corp_fail = 0
    except Exception as e:
        auth = ("403" in str(e)) or ("비-JSON" in str(e)) or ("SERVICE_KEY" in str(e).upper())
        if auth:
            _corp_fail += 1
            if _corp_fail >= 4:
                _corp_disabled = True
                _log("기업기본정보 연속 인증오류 4회 → 회사소개·상장일·crno 생략. "
                     f"활용신청/키 확인 필요. 상세: {str(e)[:80]}")
        return None
    nq = "".join(str(corp_nm).split())
    for x in it:
        nm = "".join(str(x.get("corpNm", "")).split())
        if nm == nq or nq in nm:
            return x
    return it[0] if it else None


# ── 보호예수: 주식발행정보 V3 · 1회 오퍼레이션 자동탐지 + 첫 성공 응답 로깅 ──
_lock_op = "unset"   # "unset" | None | "https://.../op"


def _discover_lock_op(key, sample_crno):
    global _lock_op
    if _lock_op != "unset":
        return _lock_op
    if not sample_crno:
        return None
    for op in _LOCK_OPS:
        url = f"{_ISSU_BASE}/{op}"
        try:
            it, _ = _items(_get(url, {"serviceKey": key, "resultType": "json",
                                      "numOfRows": 5, "pageNo": 1, "crno": sample_crno}))
        except Exception:
            continue
        _lock_op = url
        keys = sorted((it[0] if it else {}).keys()) if it else []
        sample = (str(it[0])[:300] if it else "(빈 응답)")
        _log(f"보호예수 V3 오퍼레이션 확인: {op}")
        _log(f"보호예수 응답 키: {keys}")
        _log(f"보호예수 샘플: {sample}")
        return url
    _lock_op = None
    _log("보호예수 V3 오퍼레이션 자동탐지 실패(후보 전부 오류). "
         f"Swagger의 '의무보호예수반환정보 조회' 영문 op명을 알려주면 확정할게. 후보: {_LOCK_OPS}")
    return None


_DATE_KEY_HINT = re.compile(r"(rtr|dps|rls|until|hld|반환|해제)", re.I)


def _lockup(key, crno):
    if not crno:
        return ""
    url = _discover_lock_op(key, crno)
    if not url:
        return ""
    try:
        it, _ = _items(_get(url, {"serviceKey": key, "resultType": "json",
                                  "numOfRows": 80, "pageNo": 1, "crno": crno}))
    except Exception:
        return ""
    if not it:
        return ""
    today = date.today().strftime("%Y%m%d")
    # 1순위: 반환/해제 의미 키의 미래 날짜. 없으면 전체 값에서 미래 날짜 스캔.
    hinted, fallback = [], []
    for x in it:
        for k, v in x.items():
            s = re.sub(r"[^0-9]", "", str(v))
            if len(s) == 8 and s.isdigit() and "19000101" < s < "21001231":
                if s >= today:
                    (hinted if _DATE_KEY_HINT.search(str(k)) else fallback).append(s)
    future = sorted(hinted) or sorted(fallback)
    if future:
        return f"미해제 {len(future)}건 · 최근 해제 {_fmt_date(future[0])}"
    return f"보호예수 {len(it)}건 등록"


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
            rcept = r.get("rcept_dt", "")
            # 접수일 기준 통상 4~6주 후 상장 예상(원문 파싱 미사용 · 어디까지나 추정)
            est = ""
            try:
                d0 = datetime.strptime(str(rcept), "%Y%m%d").date()
                est = (f"{(d0 + timedelta(days=28)):%m.%d}~{(d0 + timedelta(days=42)):%m.%d} 예상")
            except Exception:
                pass
            out.append({
                "name": nm,
                "state": f"증권신고서 접수 {_fmt_date(rcept)}",
                "est_listing": est,       # 상장 예상 구간(추정)
                "dday": "접수", "under": "", "intro": "", "soon": False,
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
    _log(f"시총≥{_fmt_cap(CAP_MIN)} & 최근상장 후보 {len(cands)}종목")

    recent, n_listed, n_intro, n_lock, n_spark = [], 0, 0, 0, 0
    cutoff = (date.today() - timedelta(days=RECENT_DAYS)).strftime("%Y%m%d")
    win_start = (date.today() - timedelta(days=RECENT_DAYS + 90)).strftime("%Y%m%d")
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
        lstg = re.sub(r"[^0-9]", "", str(lstg))[:8]

        # 일별 시리즈(상장후 추이 + 상장일 보강) — 한 번 호출로 두 용도
        series = _daily_series(key, srtn, win_start, basdt)
        if series and not lstg:
            lstg = series[0][0]
        if lstg and lstg < cutoff:
            continue

        spark = []
        if series:
            closes = [c for d, c in series if (not lstg) or d >= lstg]
            spark = _downsample(closes)
        if spark:
            n_spark += 1
        if lstg:
            n_listed += 1
        if intro:
            n_intro += 1
        lock = _lockup(key, crno)
        if lock:
            n_lock += 1

        recent.append({
            "name": nm, "code": srtn, "market": mkt,
            "listed": _fmt_date(lstg), "_lstg": lstg,
            "cap": _fmt_cap(cap), "cap_won": cap,
            "price": f"{int(_f(x.get('clpr')) or 0):,}", "pct": _f(x.get("fltRt")),
            "lockup": lock, "intro": intro, "spark": spark,
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

    _log(f"완료: 최근상장 {len(recent)}종목 "
         f"(상장일 {n_listed} · 회사소개 {n_intro} · 보호예수 {n_lock} · 추이 {n_spark}) "
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
