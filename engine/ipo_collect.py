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
  · 재무·밸류 = DART 다중회사 주요계정(fnlttMultiAcnt)으로 매출·영업이익·당기순이익·자본총계.
        PER=시총/순이익, PBR=시총/자본총계, PSR=시총/매출액 (시총은 시세 스냅샷).
  · 공모가·보호예수 = DART 증권발행실적보고서/투자설명서 원문에서 파싱(LLM 미사용·무료).
        공모가=표의 '모집(매출)가액' 컬럼, 보호예수=의무보유 확약비율/최대주주 기간.
        공모가比 = 현재가/공모가−1.
  · 향후 IPO = DART 증권신고서(지분증권·미상장) 목록 + 주요정보(estkRs·구조화 JSON)로
        청약기일·납입기일·공모가(예정)·주관사 보강. 원문 파싱이 아니라 정식 API라 안정적.
        estkRs 실패 종목은 '접수' 폴백(접수일 + 상장 예상구간 추정)으로 표시.

  ※ 회사소개(enpMainBizNm)는 이 API에서 비어 옴 → 재무·밸류·섹터로 대체.

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

_DART = "https://opendart.fss.or.kr/api"
_DART_LIST = f"{_DART}/list.json"
_DART_CORPCODE = f"{_DART}/corpCode.xml"   # 전체 corp_code↔stock_code 매핑(zip)
_DART_COMPANY = f"{_DART}/company.json"    # 회사개황(induty_code=업종코드)
_DART_FNLT = f"{_DART}/fnlttMultiAcnt.json"  # 다중회사 주요계정(매출·영업이익·순이익·자본총계)
_DART_DOC = f"{_DART}/document.xml"          # 공시원문(zip) — 증권발행실적보고서 공모가 파싱
_DART_ESTK = f"{_DART}/estkRs.json"          # 증권신고서 주요정보(지분증권) — 청약·납입·공모가·인수인

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

CAP_MIN = 200_000_000_000          # 2,000억 (원) — 1년 창과 함께 표본 확대(5,000억은 500_000_000_000)
RECENT_DAYS = 366                  # 최근 1년(+1)
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


def _fmt_signed_cap(won):
    """억/조 단위 + 음수(적자) 부호. None이면 빈 문자열."""
    if won is None:
        return ""
    sign = "-" if won < 0 else ""
    a = abs(won)
    if a >= 1_0000_0000_0000:
        return f"{sign}{a / 1_0000_0000_0000:.1f}조".replace(".0조", "조")
    return f"{sign}{round(a / 1_0000_0000):,}억"


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


# ── DART 재무: 다중회사 주요계정(매출·영업이익·순이익·자본총계) → PER/PBR/PSR 계산용 ──
_FIN_ACC = {"매출액": "revenue", "영업이익": "op", "당기순이익": "net", "자본총계": "equity"}


def _dart_financials(key, corp_codes):
    """{corp_code: {revenue, op, net, equity}} (원). 최근 연간보고서 우선, CFS>OFS."""
    out = {}
    ccs = [c for c in dict.fromkeys(corp_codes) if c]   # 중복 제거
    if not key or not ccs:
        return out
    years = [str(date.today().year - 1), str(date.today().year - 2)]  # 직전·전전 사업연도
    pending = list(ccs)
    for yr in years:
        if not pending:
            break
        for i in range(0, len(pending), 20):
            chunk = pending[i:i + 20]
            try:
                data = _get(_DART_FNLT, {"crtfc_key": key, "corp_code": ",".join(chunk),
                                         "bsns_year": yr, "reprt_code": "11011"})
            except Exception as e:
                _log(f"DART 재무 조회 오류({yr}): {str(e)[:70]}")
                continue
            if str(data.get("status")) != "000":
                continue
            # corp_code별로 CFS 우선 수집(없으면 OFS)
            tmp = {}
            for row in (data.get("list") or []):
                cc = row.get("corp_code")
                acc = _FIN_ACC.get(str(row.get("account_nm", "")).strip())
                if not cc or not acc:
                    continue
                val = _f(row.get("thstrm_amount"))
                if val is None:
                    continue
                fs = str(row.get("fs_div", ""))
                slot = tmp.setdefault(cc, {})
                # CFS가 들어오면 덮어쓰고, 이미 CFS면 OFS는 무시
                if acc not in slot or fs == "CFS":
                    if not (slot.get(acc + "_fs") == "CFS" and fs != "CFS"):
                        slot[acc] = val
                        slot[acc + "_fs"] = fs
            for cc, slot in tmp.items():
                if cc not in out and any(k in slot for k in ("revenue", "op", "net", "equity")):
                    out[cc] = {k: slot.get(k) for k in ("revenue", "op", "net", "equity")}
        pending = [c for c in pending if c not in out]
    _log(f"DART 재무 {len(out)}/{len(ccs)}종목")
    return out


# ── DART 공모가·보호예수: 증권발행실적보고서/투자설명서 원문 파싱 ──
_ipo_diag = {"rcept": 0, "doc": 0, "samples": []}

_PRICE_LABELS = ("모집(매출)가액", "모집(매출)가격", "공모가액", "공모가격",
                 "확정공모가액", "확정발행가액", "발행가액", "주당공모가액",
                 "1주당공모가액", "주당발행가액", "모집가액")
_PRICE_RE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d{4,7})")
_CELL_RE = re.compile(r"<(?:td|th|te|tu|tl)[^>]*>(.*?)</(?:td|th|te|tu|tl)>", re.I | re.S)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.I | re.S)


def _strip(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = re.sub(r"&[a-zA-Z#0-9]+;", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _won(cell, lo=1000, hi=2_000_000):
    """셀 문자열에서 가격(원) 1건. 자간 공백 제거 후 매칭. 범위 밖(액면가·총액)은 제외."""
    s = re.sub(r"\s+", "", cell or "")
    m = _PRICE_RE.search(s)
    if not m:
        return None
    v = int(m.group(1).replace(",", ""))
    return v if lo <= v <= hi else None


def _ipo_from_table(raw):
    """표에서 '모집(매출)가액' 헤더 컬럼을 찾아 같은 열의 데이터 행 값을 읽음."""
    rows = _ROW_RE.findall(raw)
    for ri, row in enumerate(rows):
        cells = [_strip(c) for c in _CELL_RE.findall(row)]
        for ci, c in enumerate(cells):
            cc = c.replace(" ", "")
            if any(lbl in cc for lbl in _PRICE_LABELS):
                # (1) 같은 행 오른쪽 셀 (라벨:값 가로배열)
                for c2 in cells[ci + 1: ci + 3]:
                    v = _won(c2)
                    if v:
                        return v
                # (2) 다음 데이터 행들의 같은 열 (헤더/값 세로배열)
                for row2 in rows[ri + 1: ri + 5]:
                    cells2 = [_strip(c2) for c2 in _CELL_RE.findall(row2)]
                    if ci < len(cells2):
                        v = _won(cells2[ci])
                        if v:
                            return v
    return None


def _ipo_from_inline(text):
    """공백 제거 텍스트에서 '확정공모가액…30,000원' 형태 추출."""
    t = re.sub(r"\s+", "", text or "")
    for a in ("확정공모가액", "확정발행가액", "확정공모가", "공모가액", "공모가격",
              "주당공모가액", "1주당공모가액", "발행가액", "주당모집가액"):
        i = 0
        while True:
            j = t.find(a, i)
            if j < 0:
                break
            m = re.search(r"(\d{1,3}(?:,\d{3})+|\d{4,7})\s*원", t[j: j + 30])
            if m:
                v = int(m.group(1).replace(",", ""))
                if 1000 <= v <= 2_000_000:
                    return v
            i = j + len(a)
    return None


def _parse_ipo_price(raw):
    return _ipo_from_table(raw) or _ipo_from_inline(_strip(raw))


def _parse_lockup(raw):
    """의무보유(보호예수) 요약: 기관 확약비율 우선, 없으면 최대주주 의무보유 기간."""
    t = re.sub(r"\s+", "", _strip(raw))
    for a in ("의무보유를확약", "의무보유확약", "보호예수를확약", "확약비율", "의무보유확약비율"):
        j = t.find(a)
        if j >= 0:
            m = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", t[max(0, j - 20): j + 30])
            if m:
                p = float(m.group(1))
                if 0 < p <= 100:
                    return f"기관 의무보유 확약 {m.group(1)}%"
    for a in ("최대주주",):
        j = t.find(a)
        if j >= 0:
            m = re.search(r"상장(?:일|후)\D{0,8}(\d+)(개월|년)", t[j: j + 80])
            if m:
                return f"최대주주 의무보유 {m.group(1)}{m.group(2)}"
    return None


def _dart_rcept(key, corp_code, listed):
    """상장일 전후 공시에서 증권발행실적보고서(우선)·투자설명서 접수번호 탐색."""
    try:
        ld = datetime.strptime(listed, "%Y%m%d").date() if len(str(listed)) == 8 else date.today()
    except (ValueError, TypeError):
        ld = date.today()
    bgn = (ld - timedelta(days=210)).strftime("%Y%m%d")
    end = (ld + timedelta(days=150)).strftime("%Y%m%d")
    try:
        data = _get(_DART_LIST, {"crtfc_key": key, "corp_code": corp_code,
                                 "bgn_de": bgn, "end_de": end, "page_count": 100})
    except Exception:
        return None, None
    if str(data.get("status")) != "000":
        return None, None
    lst = data.get("list") or []
    base = int(ld.strftime("%Y%m%d"))
    for kind in ("증권발행실적보고서", "투자설명서", "증권신고서"):
        cands = [r for r in lst if kind in str(r.get("report_nm", ""))]
        if cands:
            cands.sort(key=lambda r: abs(int(_digits(r.get("rcept_dt"), 8) or base) - base))
            return cands[0].get("rcept_no"), kind
    return None, None


def _dart_doc_text(key, rcept_no, cap=600_000):
    """공시원문 zip → 텍스트(앞 cap자). EUC-KR/UTF-8 혼재 대응."""
    r = requests.get(_DART_DOC, params={"crtfc_key": key, "rcept_no": rcept_no},
                     headers=_UA, timeout=30)
    r.raise_for_status()
    if r.content[:2] != b"PK":          # zip이 아니면 오류응답(XML)
        return ""
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    parts = []
    for nm in zf.namelist():
        raw = zf.read(nm)
        txt = None
        for enc in ("utf-8", "cp949", "euc-kr"):
            try:
                txt = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        parts.append(txt if txt is not None else raw.decode("utf-8", "ignore"))
        if sum(len(p) for p in parts) > cap:
            break
    return "\n".join(parts)[:cap]


def _dart_ipo_doc(key, corp_code, listed):
    """공모가·보호예수 파싱용 원문 텍스트(진단 카운터 포함)."""
    if not key or not corp_code:
        return ""
    try:
        rcept, kind = _dart_rcept(key, corp_code, listed)
        if not rcept:
            return ""
        _ipo_diag["rcept"] += 1
        raw = _dart_doc_text(key, rcept)
        if not raw:
            return ""
        _ipo_diag["doc"] += 1
        if len(_ipo_diag["samples"]) < 3:
            sx = re.sub(r"\s+", "", _strip(raw))      # 자간 공백 제거
            ntr = len(re.findall(r"<tr", raw, re.I))
            ctx = ""
            for lbl in ("모집(매출)가액", "공모가액", "공모가격", "확정공모가",
                        "발행가액", "주당공모", "공모"):
                p = sx.find(lbl)
                if p >= 0:
                    ctx = f"{lbl}@{p}:{sx[p:p + 110]}"
                    break
            if not ctx:
                ctx = "라벨無:" + sx[:110]
            _ipo_diag["samples"].append(f"{kind}|tr={ntr}|{ctx}")
        return raw
    except Exception as e:
        _log(f"공모가 원문 오류({corp_code}): {str(e)[:60]}")
        return ""


# ── DART: 향후 IPO ──
def _kr_dates(s):
    """문자열에서 날짜들을 date 리스트로(순서 유지).
    'YYYY.MM.DD' · 'YYYY년 MM월 DD일' · 'YYYY-MM-DD' · 'YYYYMMDD' 혼재 대응."""
    txt = str(s or "")
    out = []
    for m in re.finditer(r"(20\d{2})\s*[.년\-/]\s*(\d{1,2})\s*[.월\-/]\s*(\d{1,2})", txt):
        try:
            out.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            pass
    if not out:
        for m in re.finditer(r"(20\d{2})(\d{2})(\d{2})", txt):
            try:
                out.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
            except ValueError:
                pass
    return out


def _dart_estk(key, corp_code, bgn, end):
    """증권신고서 주요정보(지분증권·estkRs) → {sbd, pymd, price, under}. 실패·미조회 시 {}.

    구조화 JSON(그룹: 일반사항/증권의종류/인수인정보 …)이라 원문 파싱보다 안정적.
    정정신고 반영을 위해 일반사항은 마지막 행(최신)을 쓴다. 필드 누락은 관대하게 스킵.
    """
    try:
        data = _get(_DART_ESTK, {"crtfc_key": key, "corp_code": corp_code,
                                 "bgn_de": bgn, "end_de": end})
    except Exception as e:
        _log(f"estkRs 실패({corp_code}): {str(e)[:60]}")
        return {}
    if str(data.get("status")) != "000":
        return {}
    out = {}
    for g in data.get("group") or []:
        title = str(g.get("title") or "")
        rows = g.get("list") or []
        if not rows:
            continue
        if "일반사항" in title and "sbd" not in out:
            r = rows[-1]
            for k in ("sbd", "pymd"):
                v = str(r.get(k) or "").strip()
                if v and v != "-":
                    out[k] = v
        elif "증권의종류" in title and "price" not in out:
            for r in rows:
                p = _f(r.get("slprc"))
                if p and p >= 100:            # 액면가·0원 방지
                    out["price"] = int(p)
                    break
        elif "인수인" in title and "under" not in out:
            best = ""
            for r in rows:
                nm2 = str(r.get("actnmn") or "").strip()
                if not nm2:
                    continue
                if "대표" in str(r.get("actsen") or ""):
                    best = nm2
                    break
                best = best or nm2
            if best:
                out["under"] = best
    return out


def _dart_upcoming(key, days=75):
    """향후 IPO 목록. 증권신고서(지분증권·미상장) 목록 → 종목별 estkRs로 일정 보강.

    카드 필드
      · sub   : 청약기일 'MM.DD~MM.DD'   · pay : 납입기일 'MM.DD'
      · price : 공모가(예정, 콤마 문자열)  · under : 대표주관사
      · dday  : 'D-n'(청약 전) / '청약중' / '상장대기'(청약마감) / '접수'(estkRs 실패 폴백)
    정렬: 청약 시작일 오름차순(임박 먼저) → 일정 미확정(접수)은 뒤.
    """
    if not key:
        _log("DART_API_KEY 없음 → 향후 일정 생략")
        return []
    today_d = date.today()
    end = today_d.strftime("%Y%m%d")
    bgn = (today_d - timedelta(days=days)).strftime("%Y%m%d")
    out, seen, page = [], set(), 1
    n_est = 0
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
            item = {
                "name": nm,
                "state": f"증권신고서 접수 {_fmt_date(rcept)}",
                "est_listing": est,
                "dday": "접수", "under": "", "intro": "", "soon": False,
                "sub": "", "pay": "", "price": "",
                "dart_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r.get('rcept_no','')}",
                "_sub0": "9999-99-99",     # 정렬 키(청약 시작일) — 저장 전 제거
            }
            # ── estkRs 보강(구조화 API) ──
            #  bgn_de는 '최초접수일' 기준 — 정정신고면 최초접수가 더 이르므로 60일 여유.
            cc = str(r.get("corp_code") or "").strip()
            try:
                bgn_e = (datetime.strptime(str(rcept), "%Y%m%d").date()
                         - timedelta(days=60)).strftime("%Y%m%d")
            except Exception:
                bgn_e = bgn
            info = _dart_estk(key, cc, bgn_e, end) if cc else {}
            if info:
                ds = _kr_dates(info.get("sbd"))
                if ds:
                    s0, s1 = ds[0], ds[-1]
                    item["sub"] = f"{s0:%m.%d}" + (f"~{s1:%m.%d}" if s1 != s0 else "")
                    item["_sub0"] = s0.isoformat()
                    if today_d < s0:
                        n = (s0 - today_d).days
                        item["dday"] = f"D-{n}"
                        item["soon"] = n <= 3
                        item["state"] = f"청약 {item['sub']}"
                    elif today_d <= s1:
                        item["dday"] = "청약중"
                        item["soon"] = True
                        item["state"] = f"청약 {item['sub']}"
                    else:
                        item["dday"] = "상장대기"
                        item["state"] = f"청약마감 {item['sub']}"
                pdl = _kr_dates(info.get("pymd"))
                if pdl:
                    item["pay"] = f"{pdl[0]:%m.%d}"
                if info.get("price"):
                    item["price"] = f"{info['price']:,}"
                if info.get("under"):
                    item["under"] = info["under"]
                if item["sub"] or item["price"] or item["under"]:
                    n_est += 1
            time.sleep(0.05)
        total = int(data.get("total_count") or 0)
        if page * 100 >= total or not rows:
            break
        page += 1
    out.sort(key=lambda x: x.get("_sub0", "9999-99-99"))
    for x in out:
        x.pop("_sub0", None)
    _log(f"향후 일정: {len(out)}건 중 estkRs 보강 {n_est}건")
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

    past_target = (date(int(basdt[:4]), int(basdt[4:6]), int(basdt[6:8]))
                   - timedelta(days=RECENT_DAYS))
    past_basdt = _nearest_past_basdt(key, past_target)
    past_codes = set()
    if past_basdt:
        past_codes = {_digits(x.get("srtnCd"), 6) for x in _snapshot(key, past_basdt)}
        _log(f"1년전 스냅샷 basDt={past_basdt} {len(past_codes)}종목")
    else:
        _log("1년전 스냅샷 실패 → 상장일로만 최근성 판정")

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
        sector = _dart_sector(_dartk(), srtn)
        if sector:
            n_sect += 1

        cur_price = _f(x.get("clpr"))
        cc = _dart_corpcode_map(_dartk()).get(srtn) if _dartk() else ""

        recent.append({
            "name": nm, "code": srtn, "market": mkt, "sector": sector,
            "listed": _fmt_date(lstg), "_lstg": lstg, "_cc": cc,
            "cap": _fmt_cap(cap), "cap_won": cap,
            "price": f"{int(cur_price or 0):,}", "price_won": cur_price,
            "pct": _f(x.get("fltRt")),
            # 재무·밸류 — 아래 배치(DART fnlttMultiAcnt)에서 채움
            "revenue": "", "op_income": "", "net_income": "",
            "per": None, "pbr": None, "psr": None,
            # 공모가·보호예수 — 아래 DART 증권발행실적보고서 원문 파싱에서 채움
            "ipo_price": "", "ipo_price_won": None, "ipo_return": None,
            "lockup": "", "intro": intro, "spark": spark,
        })
        time.sleep(0.05)

    recent.sort(key=lambda r: r.get("_lstg") or "", reverse=True)
    recent = recent[:MAX_RECENT]

    # 재무(매출·영업이익·순이익·자본총계) 배치 조회 → PER/PBR/PSR
    fin = _dart_financials(_dartk(), [r.get("_cc") for r in recent if r.get("_cc")])
    n_fin = n_ipop = n_lock = 0
    dk = _dartk()
    for r in recent:
        cc = r.get("_cc")
        lstg = r.get("_lstg") or ""
        # ── 재무·밸류 ──
        f = fin.get(cc)
        if f:
            rev, op, net, eq = f.get("revenue"), f.get("op"), f.get("net"), f.get("equity")
            r["revenue"] = _fmt_signed_cap(rev)
            r["op_income"] = _fmt_signed_cap(op)
            r["net_income"] = _fmt_signed_cap(net)
            cap = r.get("cap_won")
            if cap:
                r["per"] = round(cap / net, 1) if (net and net > 0) else None
                r["pbr"] = round(cap / eq, 2) if (eq and eq > 0) else None
                r["psr"] = round(cap / rev, 2) if (rev and rev > 0) else None
            n_fin += 1
        # ── 공모가 + 보호예수(DART 증권발행실적보고서/투자설명서 원문 1회) ──
        if dk and cc:
            raw = _dart_ipo_doc(dk, cc, lstg)
            if raw:
                ip = _parse_ipo_price(raw)
                if ip:
                    r["ipo_price"] = f"{ip:,}"
                    r["ipo_price_won"] = ip
                    pw = r.get("price_won")
                    if pw:
                        r["ipo_return"] = round((pw / ip - 1) * 100, 1)
                    n_ipop += 1
                lk = _parse_lockup(raw)
                if lk:
                    r["lockup"] = lk
                    n_lock += 1
        r.pop("_lstg", None)
        r.pop("_cc", None)

    _log(f"공모가 진단: rcept {_ipo_diag['rcept']} · 원문 {_ipo_diag['doc']} · 공모가 {n_ipop} · 보호예수 {n_lock}")
    for i, s in enumerate(_ipo_diag["samples"], 1):
        _log(f"  샘플{i}=[{s[:170]}]")

    upcoming = _dart_upcoming(_dartk())
    for u in upcoming:
        o = _corp_outline(key, corp_nm=u["name"])
        if o and o.get("enpMainBizNm"):
            u["intro"] = o["enpMainBizNm"]

    _log(f"완료: 최근상장 {len(recent)}종목 "
         f"(crno {n_crno} · 상장일 {n_listed} · 섹터 {n_sect} · 재무 {n_fin} · 공모가 {n_ipop} · 회사소개 {n_intro} · 보호예수 {n_lock} · 추이 {n_spark}) "
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
