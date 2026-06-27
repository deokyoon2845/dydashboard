"""[엔진] 증시 IPO 탭 데이터 수집 → dict 반환 (저장은 ipo_run이 담당).

설계(★silent-fail 방지 · 엔진-퍼스트)
  · 스파인(목록·시총·현재가·등락) = 금융위 주식시세정보(getStockPriceInfo) 스냅샷.
  · 정밀 매핑(핵심) = KRX상장종목정보(getItemInfo)로 단축코드→법인등록번호(crno)+법인명.
        종목명(브랜드) 매칭의 절반 실패 문제를 crno 정조회로 해결.
  · 상장일·회사소개 = 기업기본정보(getCorpOutline_V2)를 crno로 정조회.
        enpKrxLstgDt/enpKosdaqLstgDt · enpMainBizNm.
  · 보호예수 = 주식발행정보 V3(의무보호예수반환정보)를 crno로 조회.
        오퍼레이션명이 명세 미노출 → base 3종 × 후보 op 자동탐지 + 첫 응답/오류 로깅.
  · 추이 스파크라인 = 상장일~최신 일별 종가(isinCd 필터)를 다운샘플(약 60p).
        시세 API의 srtnCd 필터가 무시되는 이슈 → isinCd(고유)로 교체. 실패 시 빈 배열
        → 뷰어가 라이브(네이버)로 폴백.
  · 섹터 = DART corpCode.xml(단축코드→corp_code) + company.json(induty_code) → KSIC 라벨.
  · 향후 IPO = DART 증권신고서(지분증권·미상장) + 기업소개 + 상장 예상구간(추정).

  ※ 공모가·공모시총 = 주식발행정보 V3 ②주식발행내역(발행가)에서 채울 예정.
     해당 V3 op명 확정 전까지 빈 값(자리만 유지). 현재가·현재시총은 시세 스냅샷으로 즉시 채움.

키: DATA_GO_KR_KEY(없으면 MOLIT_API_KEY) · DART_API_KEY
"""

import io
import os
import re
import sys
import time
import traceback
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

import requests

_UA = {"User-Agent": "Mozilla/5.0 (compatible; DYMonitoring-IPO/1.0)"}

_DATAGO = "https://apis.data.go.kr/1160100/service"
_PRICE = f"{_DATAGO}/GetStockSecuritiesInfoService/getStockPriceInfo"
_CORP = f"{_DATAGO}/GetCorpBasicInfoService_V2/getCorpOutline_V2"       # 기업기본정보(승인)
_KRX = f"{_DATAGO}/GetKrxListedInfoService/getItemInfo"                 # KRX상장종목정보(승인)

# 보호예수: 주식발행정보 V3 — base/op 불확실 → 자동탐지(첫 성공 1개 캐시)
_LOCK_BASES = [
    "https://apis.data.go.kr/1160100/service/GetStocIssuInfoService_V3",
    "https://apis.data.go.kr/1160100/GetStocIssuInfoService_V3",
    "https://apis.data.go.kr/1160100/service/GetStocIssuInfoService",
]
_LOCK_OPS = [
    "getOblgItemDpsRtrInfo", "getMandatoryDpsRtrInfo", "getOblgDpsRtrInfo",
    "getStockOblgDpsRtrInfo", "getMnatryHldDpsRtrInfo", "getOblgRtrInfo",
    "getHldDpsRtrInfo", "getMandatoryHoldDepositReturnInfo", "getDpsRtrInfo",
]

_DART = "https://opendart.fss.or.kr/api"
_DART_LIST = f"{_DART}/list.json"
_DART_CORPCODE = f"{_DART}/corpCode.xml"   # 전체 corp_code↔stock_code 매핑(zip)
_DART_COMPANY = f"{_DART}/company.json"    # 회사개황(induty_code=업종코드)

# KSIC(표준산업분류) 2자리 prefix → 섹터 라벨 (제조업은 세분)
_KSIC = {
    "01": "농업·임업·어업", "02": "농업·임업·어업", "03": "농업·임업·어업",
    "05": "광업", "06": "광업", "07": "광업", "08": "광업",
    "10": "식음료", "11": "식음료", "12": "식음료",
    "13": "섬유·의류", "14": "섬유·의류", "15": "섬유·의류",
    "16": "목재·종이", "17": "목재·종이", "18": "인쇄·기록매체",
    "19": "석유·화학", "20": "석유·화학", "21": "제약·바이오",
    "22": "고무·플라스틱", "23": "비금속광물",
    "24": "철강·금속", "25": "금속가공",
    "26": "반도체·전자부품", "27": "의료·정밀·광학", "28": "전기장비",
    "29": "기계·장비", "30": "운송장비", "31": "운송장비",
    "32": "기타제조", "33": "기타제조", "34": "기타제조",
    "35": "전기·가스", "36": "수도·환경", "37": "수도·환경",
    "38": "수도·환경", "39": "수도·환경",
    "41": "건설", "42": "건설",
    "45": "도소매·유통", "46": "도소매·유통", "47": "도소매·유통",
    "49": "운수·물류", "50": "운수·물류", "51": "운수·물류", "52": "운수·물류",
    "55": "숙박·음식", "56": "숙박·음식",
    "58": "출판·콘텐츠", "59": "미디어·콘텐츠", "60": "미디어·콘텐츠",
    "61": "통신", "62": "소프트웨어·IT서비스", "63": "소프트웨어·IT서비스",
    "64": "금융", "65": "보험", "66": "금융서비스",
    "68": "부동산",
    "70": "전문서비스", "71": "전문서비스", "72": "연구개발", "73": "전문서비스",
    "74": "사업서비스", "75": "사업서비스", "76": "사업서비스",
    "85": "교육", "86": "헬스케어", "87": "헬스케어",
    "90": "예술·여가", "91": "예술·여가",
}


def _ksic_label(code: str) -> str:
    c = _digits(code)
    return _KSIC.get(c[:2], "")

CAP_MIN = 500_000_000_000          # 5,000억 (원) — 종목 과다 방지(2,000억은 200_000_000_000)
RECENT_DAYS = 731                  # 최근 2년(+1)
MAX_RECENT = 40
SPARK_POINTS = 60
_EXCLUDE = ("스팩", "기업인수목적")


def _dk() -> str:
    return (os.environ.get("DATA_GO_KR_KEY") or os.environ.get("MOLIT_API_KEY") or "").strip()


def _dartk() -> str:
    return (os.environ.get("DART_API_KEY") or "").strip()


def _log(msg):
    print(f"[ipo] {msg}", flush=True)


def _get(url, params, timeout=30, retries=3):
    """GET → JSON. 타임아웃·연결오류만 재시도(HTTP 4xx/비-JSON은 즉시 전파)."""
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


def _resultcode(data):
    hdr = (data.get("response") or {}).get("header") or {}
    return str(hdr.get("resultCode", "")), str(hdr.get("resultMsg", ""))


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
    if won >= 1_0000_0000_0000:
        s = f"{won / 1_0000_0000_0000:.1f}조"
        return s.replace(".0조", "조")
    return f"{round(won / 1_0000_0000):,}억"


def _fmt_date(yyyymmdd):
    s = str(yyyymmdd or "")
    return f"{s[:4]}.{s[4:6]}.{s[6:8]}" if len(s) >= 8 else ""


def _digits(x, n=None):
    s = re.sub(r"[^0-9]", "", str(x or ""))
    return s[:n] if n else s


def _downsample(vals, n=SPARK_POINTS):
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


# ── KRX상장종목정보: 단축코드 → {crno, corpNm, isin, market} ──
def _krx_map(key, basdt):
    out = {}
    for probe in range(0, 8):
        d = (datetime.strptime(basdt, "%Y%m%d").date() - timedelta(days=probe)).strftime("%Y%m%d")
        page = 1
        try:
            while page <= 12:
                it, body = _items(_get(_KRX, {"serviceKey": key, "resultType": "json",
                                              "numOfRows": 5000, "pageNo": page, "basDt": d}))
                for x in it:
                    s = _digits(x.get("srtnCd"), 6)
                    if not s:
                        continue
                    out[s] = {
                        "crno": _digits(x.get("crno")),
                        "corpNm": str(x.get("corpNm") or "").strip(),
                        "isin": str(x.get("isinCd") or "").strip(),
                        "market": str(x.get("mrktCtg") or "").strip(),
                    }
                total = int(body.get("totalCount") or 0)
                if not it or page * 5000 >= total:
                    break
                page += 1
        except Exception as e:
            _log(f"KRX상장종목정보 basDt={d} 조회 오류: {str(e)[:80]}")
            continue
        if out:
            _log(f"KRX상장종목정보 매핑 basDt={d} {len(out)}종목")
            return out
    _log("KRX상장종목정보 매핑 실패(빈 응답) → crno 매핑 없이 종목명 폴백.")
    return out


# ── 기업기본정보(getCorpOutline): crno 정조회(우선) / 종목명 폴백 ──
_corp_fail = 0
_corp_disabled = False


def _corp_outline(key, crno=None, corp_nm=None):
    global _corp_fail, _corp_disabled
    if _corp_disabled:
        return None
    params = {"serviceKey": key, "resultType": "json", "numOfRows": 3, "pageNo": 1}
    if crno:
        params["crno"] = crno
    elif corp_nm:
        params["corpNm"] = corp_nm
    else:
        return None
    try:
        it, _ = _items(_get(_CORP, params))
        _corp_fail = 0
    except Exception as e:
        if ("403" in str(e)) or ("비-JSON" in str(e)) or ("SERVICE_KEY" in str(e).upper()):
            _corp_fail += 1
            if _corp_fail >= 4:
                _corp_disabled = True
                _log(f"기업기본정보 연속 인증오류 4회 → 회사소개·상장일 생략. {str(e)[:80]}")
        return None
    if crno:                            # crno 정조회는 첫 항목이 그 법인
        return it[0] if it else None
    nq = "".join(str(corp_nm).split())
    for x in it:
        cn = "".join(str(x.get("corpNm", "")).split())
        if cn == nq or (nq and nq in cn):
            return x
    return it[0] if it else None


# ── 보호예수: 주식발행정보 V3 자동탐지(base×op) + raw 로깅 ──
_lock_op = "unset"


def _discover_lock_op(key, sample_crno):
    global _lock_op
    if _lock_op != "unset":
        return _lock_op
    if not sample_crno:
        return None
    errs, tried = [], 0
    for base in _LOCK_BASES:
        for op in _LOCK_OPS:
            url = f"{base}/{op}"
            try:
                data = _get(url, {"serviceKey": key, "resultType": "json",
                                  "numOfRows": 5, "pageNo": 1, "crno": sample_crno})
            except Exception as e:
                tried += 1
                if len(errs) < 4:
                    errs.append(f"{op}: {str(e)[:60]}")
                continue
            rc, msg = _resultcode(data)
            if rc and rc not in ("00", "0", "000"):
                tried += 1
                if len(errs) < 4:
                    errs.append(f"{op}: rc={rc} {msg[:40]}")
                continue
            it, _ = _items(data)
            _lock_op = url
            tag = url.split("/1160100/")[-1]
            keys = sorted((it[0] if it else {}).keys())
            _log(f"보호예수 op 확인: {tag}")
            _log(f"보호예수 응답 키: {keys}")
            _log(f"보호예수 샘플: {str(it[0])[:300] if it else '(빈 응답 — 이 crno엔 보호예수 미등록일 수 있음)'}")
            return url
    _lock_op = None
    _log(f"보호예수 op 자동탐지 실패({tried}회). 첫 오류: " + " | ".join(errs))
    _log("→ Swagger '의무보호예수반환정보 조회' 영문 op명을 알려주면 고정할게.")
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
    hinted, fallback = [], []
    for x in it:
        for k, v in x.items():
            s = _digits(v)
            if len(s) == 8 and "19000101" < s < "21001231" and s >= today:
                (hinted if _DATE_KEY_HINT.search(str(k)) else fallback).append(s)
    future = sorted(hinted) or sorted(fallback)
    if future:
        return f"미해제 {len(future)}건 · 최근 해제 {_fmt_date(future[0])}"
    return f"보호예수 {len(it)}건 등록"


# ── 추이: isinCd 필터 일별 종가 시리즈 ──
def _daily_series(key, isin, srtn, start_basdt, end_basdt):
    """isinCd 우선(고유) 필터로 일별 종가. 다른 종목 섞이면 [] 반환."""
    for fk, fv in [("isinCd", isin), ("srtnCd", srtn)]:
        if not fv:
            continue
        rows, page, ok = [], 1, True
        while page <= 3:
            try:
                it, body = _items(_get(_PRICE, {"serviceKey": key, "resultType": "json",
                                                "numOfRows": 600, "pageNo": page, fk: fv,
                                                "beginBasDt": start_basdt, "endBasDt": end_basdt}))
            except Exception:
                ok = False
                break
            if not it:
                break
            if {_digits(x.get("srtnCd"), 6) for x in it} - {_digits(srtn, 6)}:
                ok = False                # 다른 종목 섞임 → 이 필터 무효
                break
            for x in it:
                d = x.get("basDt")
                c = _f(x.get("clpr"))
                if d and c is not None:
                    rows.append((str(d), c))
            total = int(body.get("totalCount") or 0)
            if page * 600 >= total:
                break
            page += 1
        if ok and rows:
            rows.sort(key=lambda r: r[0])
            return rows
    return []


# ── DART 섹터: corpCode.xml(단축코드→corp_code) + company.json(업종코드) ──
_corpcode_map = None       # {stock_code(6): corp_code(8)}
_sector_cache = {}         # corp_code → 섹터 라벨


def _dart_corpcode_map(key):
    global _corpcode_map
    if _corpcode_map is not None:
        return _corpcode_map
    _corpcode_map = {}
    if not key:
        return _corpcode_map
    try:
        r = requests.get(_DART_CORPCODE, params={"crtfc_key": key}, headers=_UA, timeout=60)
        r.raise_for_status()
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        root = ET.fromstring(zf.read(zf.namelist()[0]))
        for c in root.iter("list"):
            sc = (c.findtext("stock_code") or "").strip()
            cc = (c.findtext("corp_code") or "").strip()
            if sc and len(sc) == 6 and cc:
                _corpcode_map[sc] = cc
        _log(f"DART corpCode 매핑 {len(_corpcode_map)}종목")
    except Exception as e:
        _log(f"DART corpCode 매핑 실패(섹터 생략): {str(e)[:80]}")
    return _corpcode_map


def _dart_sector(key, stock_code):
    if not key:
        return ""
    cc = _dart_corpcode_map(key).get(_digits(stock_code, 6))
    if not cc:
        return ""
    if cc in _sector_cache:
        return _sector_cache[cc]
    sector = ""
    try:
        r = requests.get(_DART_COMPANY, params={"crtfc_key": key, "corp_code": cc},
                         headers=_UA, timeout=15)
        r.raise_for_status()
        data = r.json()
        if str(data.get("status")) == "000":
            sector = _ksic_label(data.get("induty_code"))
    except Exception:
        sector = ""
    _sector_cache[cc] = sector
    return sector


# ── DART: 향후 IPO ──
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
            est = ""
            try:
                d0 = datetime.strptime(str(rcept), "%Y%m%d").date()
                est = f"{(d0 + timedelta(days=28)):%m.%d}~{(d0 + timedelta(days=42)):%m.%d} 예상"
            except Exception:
                pass
            out.append({
                "name": nm,
                "state": f"증권신고서 접수 {_fmt_date(rcept)}",
                "est_listing": est,
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

    krx = _krx_map(key, basdt)          # 단축코드 → crno/법인명/isin

    past_target = date(int(basdt[:4]) - 2, int(basdt[4:6]), int(basdt[6:8]))
    past_basdt = _nearest_past_basdt(key, past_target)
    past_codes = set()
    if past_basdt:
        past_codes = {_digits(x.get("srtnCd"), 6) for x in _snapshot(key, past_basdt)}
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
        if past_codes and _digits(x.get("srtnCd"), 6) in past_codes:
            continue
        cands.append(x)
    _log(f"시총≥{_fmt_cap(CAP_MIN)} & 최근상장 후보 {len(cands)}종목")

    recent = []
    n_listed = n_intro = n_lock = n_spark = n_crno = n_sect = 0
    cutoff = (date.today() - timedelta(days=RECENT_DAYS)).strftime("%Y%m%d")
    win_start = (date.today() - timedelta(days=RECENT_DAYS + 90)).strftime("%Y%m%d")
    for x in cands:
        srtn = _digits(x.get("srtnCd"), 6)
        nm = str(x.get("itmsNm", ""))
        mkt = "코스피" if str(x.get("mrktCtg", "")).upper() == "KOSPI" else "코스닥"
        cap = _f(x.get("mrktTotAmt"))
        isin = str(x.get("isinCd") or "").strip()

        km = krx.get(srtn) or {}
        crno = km.get("crno") or ""
        corp_nm = km.get("corpNm") or nm
        isin = isin or km.get("isin") or ""
        if crno:
            n_crno += 1

        outline = _corp_outline(key, crno=crno) if crno else _corp_outline(key, corp_nm=corp_nm)
        intro = (outline or {}).get("enpMainBizNm") or ""
        lstg = ""
        if outline:
            lstg = ((outline.get("enpKosdaqLstgDt") if mkt == "코스닥" else outline.get("enpKrxLstgDt"))
                    or outline.get("enpKrxLstgDt") or outline.get("enpKosdaqLstgDt") or "")
        lstg = _digits(lstg, 8)

        series = _daily_series(key, isin, srtn, win_start, basdt)
        if series and not lstg:
            lstg = series[0][0]
        if lstg and lstg < cutoff:
            continue

        spark = _downsample([c for d, c in series if (not lstg) or d >= lstg]) if series else []
        n_listed += 1 if lstg else 0
        n_intro += 1 if intro else 0
        n_spark += 1 if spark else 0
        lock = _lockup(key, crno)
        n_lock += 1 if lock else 0
        sector = _dart_sector(_dartk(), srtn)
        if sector:
            n_sect += 1

        cur_price = _f(x.get("clpr"))
        shares = _f(x.get("lstgStCnt"))     # 상장주식수 → 공모시총 계산용

        recent.append({
            "name": nm, "code": srtn, "market": mkt, "sector": sector,
            "listed": _fmt_date(lstg), "_lstg": lstg,
            "cap": _fmt_cap(cap), "cap_won": cap,
            "price": f"{int(cur_price or 0):,}", "price_won": cur_price,
            "pct": _f(x.get("fltRt")), "shares": shares,
            # 공모가·공모시총 — 주식발행정보 V3(②주식발행내역) op 확정 시 채움
            "ipo_price": "", "ipo_price_won": None,
            "offer_cap": "", "offer_cap_won": None, "ipo_return": None,
            "lockup": lock, "intro": intro, "spark": spark,
        })
        time.sleep(0.05)

    recent.sort(key=lambda r: r.get("_lstg") or "", reverse=True)
    recent = recent[:MAX_RECENT]
    for r in recent:
        r.pop("_lstg", None)

    upcoming = _dart_upcoming(_dartk())
    for u in upcoming:
        o = _corp_outline(key, corp_nm=u["name"])
        if o and o.get("enpMainBizNm"):
            u["intro"] = o["enpMainBizNm"]

    _log(f"완료: 최근상장 {len(recent)}종목 "
         f"(crno {n_crno} · 상장일 {n_listed} · 섹터 {n_sect} · 회사소개 {n_intro} · 보호예수 {n_lock} · 추이 {n_spark}) "
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
