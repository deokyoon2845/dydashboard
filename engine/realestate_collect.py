"""부동산 데이터 수집 — 국토부 아파트 실거래가(매매·전세) 기반.

수도권 시군구별 아파트 매매/전세 실거래를 받아
  · 지도용 지역 지표: 거래량(v)·거래량 전주비(vc)·매매 주간변화(mm)·전세 주간변화(js)·전세가율(jr)
  · 특이거래: 신고가/신저가·급등/급락 (직거래=증여추정 기본 제외)
를 만든다.

self-contained(별도 DB 누적 불필요):
  - 지역 지표: 당월+직전월 2개월을 받아 '최근 N일 vs 그 전 N일'로 주간 비교를 계산.
  - 특이거래: 최근 ANOM_MONTHS개월 윈도우 내 단지·면적별 최고/최저가·직전거래 대비로 판정.
  ※ 실거래는 계약일 기준이라 최근일은 신고지연으로 표본이 적다(주간 수치는 변동 큼).
    표본이 MIN_N 미만이면 등락은 0(보합)으로 처리한다.

────────────────────────────────────────────────────────────────────────────
[2026-06 개편] PublicDataReader 우회 — requests로 RTMS 엔드포인트 직접 호출.
  이전엔 PublicDataReader.TransactionPrice를 썼는데, HTTP가 200이 아니면
  내부에서 print 한 줄만 찍고 '빈 DataFrame'을 조용히 돌려줬다(예외 없음).
  그래서 600콜이 전부 0건이어도 원인(차단/키범위/표본부족/월형식)을 구분 못 했다.
  ⇒ 이제는 직접 호출해서 HTTP status·resultCode·totalCount·인증에러문구를 그대로 본다.
     · http가 막히면 https로 자동 폴백(데이터포털 http→https 전환 이슈 대응).
     · 성공한 scheme은 _SCHEME에 캐시 → 600콜 동안 재탐색 안 함.
     · 진단(diagnose)은 강남구 1콜만 던져 '진짜 원인 한 줄'을 돌려준다.

키: 공공데이터포털 서비스키. 환경변수/secrets 에서 다음 순서로 찾는다.
    MOLIT_API_KEY → PUBLIC_DATA_API_KEY → DATA_GO_KR_KEY
    (Encoding/Decoding 키 어느 쪽이든 동작 — 내부에서 unquote 후 requests가 재인코딩.)

주의: getRTMSDataSvcAptTradeDev(상세자료)는 기본자료(getRTMSDataSvcAptTrade)와
      별개 활용신청이 필요하다. 키가 '상세자료'에 미승인이면 resultCode 30이 떠서
      이제 진단이 KEY_INVALID로 정확히 알려준다(예전엔 0건으로 뭉뚱그려짐).
"""

import os
import statistics
from datetime import date, timedelta

import requests

try:                                   # verify=False 경고 억제
    requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]
except Exception:
    pass

# ── 시군구 법정동코드 (서울 25 자치구 + 경기 24 시/군, 자치구 있는 시는 구별 코드) ──
SIGUNGU_CODES = {
    "광주시": ["41610"],
    "화성시": ["41590"],
    "김포시": ["41570"],
    "안성시": ["41550"],
    "이천시": ["41500"],
    "파주시": ["41480"],
    "용인시": ["41461", "41463", "41465"],
    "하남시": ["41450"],
    "의왕시": ["41430"],
    "군포시": ["41410"],
    "시흥시": ["41390"],
    "오산시": ["41370"],
    "남양주시": ["41360"],
    "구리시": ["41310"],
    "과천시": ["41290"],
    "고양시": ["41281", "41285", "41287"],
    "안산시": ["41271", "41273"],
    "평택시": ["41220"],
    "광명시": ["41210"],
    "부천시": ["41190"],
    "안양시": ["41171", "41173"],
    "의정부시": ["41150"],
    "성남시": ["41131", "41133", "41135"],
    "수원시": ["41111", "41113", "41115", "41117"],
    "강동구": ["11740"],
    "송파구": ["11710"],
    "강남구": ["11680"],
    "서초구": ["11650"],
    "관악구": ["11620"],
    "동작구": ["11590"],
    "영등포구": ["11560"],
    "금천구": ["11545"],
    "구로구": ["11530"],
    "강서구": ["11500"],
    "양천구": ["11470"],
    "마포구": ["11440"],
    "서대문구": ["11410"],
    "은평구": ["11380"],
    "노원구": ["11350"],
    "도봉구": ["11320"],
    "강북구": ["11305"],
    "성북구": ["11290"],
    "중랑구": ["11260"],
    "동대문구": ["11230"],
    "광진구": ["11215"],
    "성동구": ["11200"],
    "용산구": ["11170"],
    "중구": ["11140"],
    "종로구": ["11110"],
}

_SEOUL = {n for n in SIGUNGU_CODES if n.endswith("구")}

# 파라미터
WINDOW_DAYS = 7        # 주간 비교 창(최근 N일 vs 그 전 N일)
JR_DAYS = 60           # 전세가율 산정 창(표본 확보용으로 더 길게)
MIN_N = 3              # 등락 계산 최소 표본
ANOM_MONTHS = 6        # 특이거래 판정 윈도우(개월)
JUMP_PCT = 7.0         # 급등/급락 임계(직전 거래 대비 %)
VOL_SURGE = 2.0        # 거래량 급증 배수(최근주 vs 윈도우 주평균)

_DIAG_CODE = "11680"   # 진단용 시험 호출 시군구(강남구 — 거래가 늘 있는 편)

# ── RTMS 엔드포인트 (아파트 매매/전월세) ────────────────────────
_RTMS_HOST = "apis.data.go.kr/1613000"
_RTMS_PATH = {
    "매매": "RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev",
    "전월세": "RTMSDataSvcAptRent/getRTMSDataSvcAptRent",
}
_NUM_ROWS = 2000       # 시군구·월당 충분(보통 수백 건) — 99999는 일부 엔드포인트서 불안정
_TIMEOUT = 12
_SCHEMES = ("https", "http")   # https 우선(http 차단 대비) — 성공 scheme은 캐시
_SCHEME = None         # 첫 성공 scheme 캐시(프로세스 단위)


# ── 인증키 ──────────────────────────────────────────────────────
def _get_key():
    for k in ("MOLIT_API_KEY", "PUBLIC_DATA_API_KEY", "DATA_GO_KR_KEY"):
        v = os.environ.get(k)
        if v:
            return v.strip()
    try:
        import streamlit as st
        for k in ("MOLIT_API_KEY", "PUBLIC_DATA_API_KEY", "DATA_GO_KR_KEY"):
            if k in st.secrets:
                return str(st.secrets[k]).strip()
    except Exception:
        pass
    return None


# ── 저수준 호출 + 응답 해석 ─────────────────────────────────────
def _endpoint(trade_type, scheme):
    return f"{scheme}://{_RTMS_HOST}/{_RTMS_PATH[trade_type]}"


def _request(key, code, ym, trade_type, scheme):
    """단일 RTMS 호출 → requests.Response (예외는 호출부에서 처리)."""
    # Encoding/Decoding 키 모두 대응: unquote 후 params로 넘기면 requests가 재인코딩.
    skey = requests.utils.unquote(key)
    params = {"serviceKey": skey, "LAWD_CD": code,
              "DEAL_YMD": ym, "numOfRows": str(_NUM_ROWS), "pageNo": "1"}
    return requests.get(_endpoint(trade_type, scheme), params=params,
                        timeout=_TIMEOUT, verify=False)


def _interpret(res):
    """Response → dict. status/resultCode/totalCount/items/에러문구를 구분해 담는다.

    반환 키:
      http   : HTTP 상태코드
      kind   : OK | EMPTY | AUTH | RESULT | NON200 | PARSE
      items  : 정상일 때 raw item dict 리스트
      total  : totalCount (있으면)
      msg    : 사람이 읽을 원인 문구
      rcode  : resultCode 또는 인증 returnReasonCode
    """
    out = {"http": res.status_code, "kind": "NON200", "items": [],
           "total": None, "msg": "", "rcode": None}
    if res.status_code != 200:
        out["msg"] = f"HTTP {res.status_code}"
        return out
    try:
        import xmltodict
        j = xmltodict.parse(res.text)
    except Exception as e:
        out["kind"] = "PARSE"
        out["msg"] = f"응답 파싱 실패: {e} · 앞부분: {res.text[:120]!r}"
        return out

    # 인증/트래픽 에러 봉투
    if "OpenAPI_ServiceResponse" in j:
        h = (j["OpenAPI_ServiceResponse"] or {}).get("cmmMsgHeader", {}) or {}
        out["kind"] = "AUTH"
        out["rcode"] = h.get("returnReasonCode")
        out["msg"] = f"{h.get('errMsg')} (code {h.get('returnReasonCode')})"
        return out

    body = (j.get("response") or {})
    header = body.get("header", {}) or {}
    rc = header.get("resultCode")
    out["rcode"] = rc
    if rc not in ("00", "000"):
        out["kind"] = "RESULT"
        out["msg"] = f"resultCode {rc}: {header.get('resultMsg')}"
        return out

    b = body.get("body", {}) or {}
    out["total"] = b.get("totalCount")
    items = (b.get("items") or {})
    items = items.get("item") if isinstance(items, dict) else None
    if items is None:
        out["kind"] = "EMPTY"
        return out
    if isinstance(items, dict):
        items = [items]
    out["kind"] = "OK"
    out["items"] = items
    return out


def _classify_exc(exc):
    """requests 예외를 NETWORK / KEY_INVALID / RATE_LIMIT / API_ERROR 로 분류."""
    name = type(exc).__name__.upper()
    txt = str(exc).upper()
    net_names = ("CONNECTIONERROR", "CONNECTTIMEOUT", "READTIMEOUT", "TIMEOUT",
                 "SSLERROR", "CHUNKEDENCODINGERROR", "PROXYERROR", "MAXRETRYERROR")
    if any(n in name for n in net_names):
        return "NETWORK"
    if any(h in txt for h in ("TIMED OUT", "MAX RETRIES", "CONNECTION ABORTED",
                              "FAILED TO ESTABLISH", "NEWCONNECTIONERROR", "SSL")):
        return "NETWORK"
    if any(h in txt for h in ("NOT_REGISTERED", "UNREGISTERED", "INVALID",
                              "ACCESS DENIED", "DENIED")):
        return "KEY_INVALID"
    if any(h in txt for h in ("LIMITED", "EXCEEDS", "LIMIT_EXCEED", "한도")):
        return "RATE_LIMIT"
    return "API_ERROR"


# ── 진단 (강남구 1콜) ───────────────────────────────────────────
def diagnose(asof=None, test_code=_DIAG_CODE):
    """수집 전 단 1회 시험 호출로 연결 상태 점검.

    반환: (status, message)
      status ∈ {"OK","OK_EMPTY","NO_KEY","NETWORK","KEY_INVALID","RATE_LIMIT","API_ERROR"}
      OK / OK_EMPTY 는 '키·네트워크 정상'(수집 진행 가능), 나머지는 치명 오류.
    성공 시 동작 scheme(https/http)을 _SCHEME에 캐시한다.
    """
    global _SCHEME
    key = _get_key()
    if not key:
        return ("NO_KEY",
                "data.go.kr 서비스키가 없어요. Streamlit Secrets에 "
                "MOLIT_API_KEY(또는 PUBLIC_DATA_API_KEY/DATA_GO_KR_KEY)를 추가하세요. "
                "값은 공공데이터포털의 '일반 인증키'를 넣으세요.")

    asof = asof or date.today()
    yms = list(reversed(_months_back(asof, 2)))   # 당월 → 직전월 순
    net_err = None
    empty_detail = None

    for scheme in _SCHEMES:
        scheme_ok = False
        for ym in yms:
            try:
                res = _request(key, test_code, ym, "매매", scheme)
            except Exception as e:
                net_err = f"{scheme}: {e}"
                break   # 이 scheme은 연결 자체가 안 됨 → 다음 scheme
            info = _interpret(res)
            if info["kind"] == "OK":
                _SCHEME = scheme
                return ("OK", f"정상 — 강남구 {ym} 매매 {len(info['items'])}건 확인"
                              f"({scheme}). 수집을 진행할 수 있어요.")
            if info["kind"] == "AUTH":
                code = info.get("rcode")
                if code in ("30", "31", "32"):   # 미등록/만료/IP제한 류
                    return ("KEY_INVALID",
                            "키가 '아파트 매매 실거래가 상세자료(getRTMSDataSvcAptTradeDev)'에 "
                            "미승인/무효예요. data.go.kr에서 해당 서비스 활용신청 승인 여부와 "
                            f"키를 확인하세요. 원문: {info['msg']}")
                if code in ("22",):              # 트래픽 초과
                    return ("RATE_LIMIT", f"호출 한도 초과. 잠시 후 재시도하세요. 원문: {info['msg']}")
                return ("KEY_INVALID", f"인증 오류({scheme}): {info['msg']}")
            if info["kind"] == "RESULT":
                return ("API_ERROR", f"API 오류({scheme}): {info['msg']}")
            if info["kind"] == "EMPTY":
                scheme_ok = True   # 호출은 성공(키·연결 OK), 그 달 표본만 0
                empty_detail = f"{scheme}·{ym}·totalCount={info.get('total')}"
                continue
            if info["kind"] in ("NON200", "PARSE"):
                net_err = f"{scheme}·{ym}: {info['msg']}"
                break   # 이 scheme은 막힘 → 다음 scheme
        if scheme_ok:
            _SCHEME = scheme
            return ("OK_EMPTY",
                    f"호출은 정상인데 최근 2개월 강남구 표본이 0건이에요({empty_detail}). "
                    "키·네트워크는 문제 없어 보여요. 월 초·신고지연일 수 있어요.")

    # 모든 scheme 실패
    return ("NETWORK",
            "data.go.kr 연결에 실패했어요(네트워크/IP 차단/엔드포인트 의심). "
            "Streamlit Cloud에서 막히면 GitHub Actions(서버측) 수집을 쓰세요. "
            f"원문: {net_err}")


def _preflight(asof=None):
    """diagnose 결과가 치명 오류면 RuntimeError 로 즉시 중단(+동작 scheme 확정)."""
    status, msg = diagnose(asof)
    if status not in ("OK", "OK_EMPTY"):
        raise RuntimeError(msg)


# ── 실거래 조회 + 정규화 ────────────────────────────────────────
def _to_int(x):
    try:
        return int(str(x).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _scheme():
    return _SCHEME or "http"


def _fetch(key, code, ym, trade_type, stats=None):
    """단일 시군구·월 조회 → 표준 레코드 리스트.

    키/권한 오류(AUTH)는 즉시 RuntimeError(전수 실패 확정 → 600콜 낭비 방지).
    네트워크 일시오류·해당 월 0건·NON200은 [] 로 건너뛰되 stats에 원인을 남긴다."""
    try:
        res = _request(key, code, ym, trade_type, _scheme())
    except Exception as e:
        kind = _classify_exc(e)
        if stats is not None:
            stats["fail"] = stats.get("fail", 0) + 1
            stats["last_err"] = f"{kind}: {e}"
        if kind == "KEY_INVALID":
            raise RuntimeError(f"실거래 키가 미등록/무효예요. 원문: {e}")
        return []

    info = _interpret(res)
    if stats is not None:
        stats["calls"] = stats.get("calls", 0) + 1

    if info["kind"] == "AUTH":
        # 키 문제는 모든 코드에서 동일 → 즉시 중단
        raise RuntimeError(
            "실거래 키가 '상세자료(getRTMSDataSvcAptTradeDev)'에 미승인/무효예요 "
            f"(data.go.kr 활용신청 확인). 원문: {info['msg']}")
    if info["kind"] in ("RESULT", "NON200", "PARSE"):
        if stats is not None:
            stats["fail"] = stats.get("fail", 0) + 1
            stats["last_err"] = info["msg"]
            stats.setdefault("http", {})[info["http"]] = \
                stats["http"].get(info["http"], 0) + 1
        return []
    if info["kind"] == "EMPTY":
        if stats is not None:
            stats["ok"] = stats.get("ok", 0) + 1
            stats["empty200"] = stats.get("empty200", 0) + 1
        return []

    # OK
    if stats is not None:
        stats["ok"] = stats.get("ok", 0) + 1

    out = []
    for r in info["items"]:
        if str(r.get("cdealType", "")).strip().upper() == "O":   # 취소건 제외
            continue
        try:
            y = int(r.get("dealYear")); m = int(r.get("dealMonth")); d = int(r.get("dealDay"))
            dt = date(y, m, d)
        except (ValueError, TypeError):
            continue
        try:
            area = float(str(r.get("excluUseAr")).strip())
        except (ValueError, TypeError, AttributeError):
            continue
        if trade_type == "매매":
            price = _to_int(r.get("dealAmount"))
        else:  # 전월세: 전세만(월세 0)
            if _to_int(r.get("monthlyRent")) not in (0, None):
                continue
            price = _to_int(r.get("deposit"))
        if not price or not area or area <= 0:
            continue
        trade = str(r.get("dealingGbn", "")).strip()
        out.append({
            "date": dt, "price": price, "area": area,
            "ppa": price / area,                       # 만원/㎡ (구성효과 완화)
            "apt": str(r.get("aptNm", "")).strip(),
            "dong": str(r.get("umdNm", "")).strip(),
            "trade": trade,                            # 중개거래/직거래/''
            "direct": "직" in trade,
        })
    if stats is not None:
        stats["rows"] = stats.get("rows", 0) + len(out)
    return out


def _months_back(asof, n):
    """asof 기준 최근 n개월 YYYYMM 리스트(현재월 포함, 과거→현재)."""
    yms, y, m = [], asof.year, asof.month
    for _ in range(n):
        yms.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            y -= 1; m = 12
    return list(reversed(yms))


def _median_ppa(rows):
    vals = [r["ppa"] for r in rows]
    return statistics.median(vals) if vals else None


def _zero_hint(stats):
    """전수 0건일 때 stats로 '진짜 원인 한 줄'을 만든다."""
    if stats.get("last_err"):
        return f" 최근 오류: {stats['last_err']}"
    http = stats.get("http") or {}
    if http:
        codes = ", ".join(f"HTTP {k}×{v}" for k, v in http.items())
        return f" ({codes} — IP 차단/엔드포인트 의심)."
    if stats.get("empty200"):
        return (f" (HTTP 200·totalCount 0 ×{stats['empty200']} — 해당 월 표본 없음 또는 "
                "키가 '상세자료'에 미승인). '연결 진단'으로 원인을 확인하세요.")
    return " (호출은 됐지만 데이터가 0건 — 차단/한도/표본부족 가능)."


# ════════════════════════════════════════════════════════════════
#  KB부동산 가격지수 — 지도(가격 방향)·지표의 신뢰 소스
#  data-api.kbland.kr 직접 호출(PublicDataReader 우회: 차단/버전 이슈 회피·진단 용이).
#  지역코드에 시도(서울 11 / 경기 41)를 주면 응답에 하위 구·시별 행이 함께 담긴다.
#  ★실거래 median 주간비교(신고지연·표본부족 노이즈)를 폐기하고, 월간 가격지수 증감률을 쓴다.
# ════════════════════════════════════════════════════════════════
_KB_BASE = "https://data-api.kbland.kr/bfmstat/weekMnthlyHuseTrnd"
_KB_URL = {
    "index": f"{_KB_BASE}/priceIndex",            # 가격지수(레벨)
    "change": f"{_KB_BASE}/prcIndxInxrdcRt",      # 가격지수 증감률
    "trend": f"{_KB_BASE}/maktTrnd",              # 매수우위 등 시장동향
    "jratio": f"{_KB_BASE}/dealCntstTnantRato",   # 전세가격비율
}
_KB_SIDO = {"서울": "11", "경기": "41"}


def _kb_get(url, params, timeout=15):
    """KB data-api 호출 → data dict({'날짜리스트','데이터리스트'}). 실패/비정상 시 None.
    정상 resultCode는 '11000'."""
    r = requests.get(url, params=params, timeout=timeout, verify=False,
                     headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    body = (r.json() or {}).get("dataBody", {}) or {}
    if str(body.get("resultCode")) != "11000":
        return None
    return body.get("data")


def _kb_rows(data):
    """data → [{'name','code','dates','vals'}]. vals는 float|None 리스트."""
    if not data:
        return []
    dates = [str(d) for d in (data.get("날짜리스트") or [])]
    out = []
    for row in (data.get("데이터리스트") or []):
        raw = row.get("dataList") or []
        vals = []
        for v in raw[:len(dates)]:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                vals.append(None)
        out.append({"name": str(row.get("지역명", "")).strip(),
                    "code": str(row.get("지역코드", "")).strip(),
                    "dates": dates, "vals": vals})
    return out


def _kb_latest(vals):
    for v in reversed(vals):
        if v is not None:
            return v
    return None


def _match_region(kb_name):
    """KB 지역명 → 내 시군구명(SIGUNGU_CODES 키). 매칭 실패 시 None.
    KB가 '서울 강남구'/'강남구' 식으로 줄 수 있어 포함관계로 가장 긴 일치를 택한다."""
    best = None
    for n in SIGUNGU_CODES:
        if n in kb_name:
            if best is None or len(n) > len(best):
                best = n
    return best


def collect_kb_region_change(월간주간="01"):
    """시군구별 아파트 '가격지수 증감률' 최신값. 반환 {시군구명: {'mm':매매%, 'js':전세%}}.
    (월간주간 01=월간/02=주간. 지도는 월간 권장 — 안정적.)"""
    out = {}
    for sido_code in _KB_SIDO.values():
        for me, key in (("01", "mm"), ("02", "js")):
            data = _kb_get(_KB_URL["change"], {
                "월간주간구분코드": 월간주간, "매물종별구분": "01",
                "매매전세코드": me, "지역코드": sido_code})
            for row in _kb_rows(data):
                name = _match_region(row["name"])
                lv = _kb_latest(row["vals"])
                if name and lv is not None:
                    out.setdefault(name, {})[key] = round(lv, 2)
    return out


def collect_kb_region_jeonse_ratio(월간주간="01"):
    """시군구별 아파트 전세가격비율 최신값. 반환 {시군구명: jr(float)}."""
    out = {}
    for sido_code in _KB_SIDO.values():
        data = _kb_get(_KB_URL["jratio"], {
            "월간주간구분코드": 월간주간, "매물종별구분": "01", "지역코드": sido_code})
        for row in _kb_rows(data):
            name = _match_region(row["name"])
            lv = _kb_latest(row["vals"])
            if name and lv is not None:
                out[name] = round(lv, 1)
    return out


def _kb_seoul_series(url_key, params, points=60):
    """KB 응답에서 '서울' 시도행의 값 시계열(최근 points개). 실패 시 []."""
    data = _kb_get(_KB_URL[url_key], {**params, "지역코드": _KB_SIDO["서울"]})
    rows = _kb_rows(data)
    if not rows:
        return []
    pick = next((r for r in rows if r["name"] in ("서울", "서울특별시")), rows[0])
    vals = [v for v in pick["vals"] if v is not None]
    return [round(v, 2) for v in vals[-points:]]


# ── 미분양(KOSIS)·금리(ECOS) — 엔진에서 수집(뷰어 라이브 호출 제거) ──
def _env_key(*names):
    for n in names:
        v = os.environ.get(n)
        if v:
            return v.strip()
    return None


def _collect_mortgage_rate(points=18):
    """한은 ECOS 주담대 가중평균금리(월, 최근 points개). 실패 시 []."""
    key = _env_key("ECOS_API_KEY")
    if not key:
        return []
    end = date.today().strftime("%Y%m")
    start = f"{int(end[:4]) - 2}{end[4:]}"
    url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/60/"
           f"722Y001/M/{start}/{end}/BECABA03")
    r = requests.get(url, timeout=10)
    rows = (r.json().get("StatisticSearch", {}) or {}).get("row", []) or []
    vals = [round(float(x["DATA_VALUE"]), 2) for x in rows if x.get("DATA_VALUE")]
    return vals[-points:]


def _collect_kosis_unsold(points=18):
    """KOSIS 전국 미분양(월, 최근 points개) → 만호 단위. 실패 시 []."""
    key = _env_key("KOSIS_API_KEY")
    if not key:
        return []
    import pandas as pd
    from PublicDataReader import Kosis
    df = Kosis(key).get_data(
        "통계자료", orgId="101", tblId="DT_1YL202001E",
        itmId="13103871087T1", objL1="13102871087A.0002",
        prdSe="M", newEstPrdCnt=str(points + 2))
    if df is None or len(df) == 0:
        return []
    pcol = next((c for c in df.columns if "시점" in c or c.upper() == "PRD_DE"), None)
    vcol = next((c for c in df.columns if "수치" in c or c.upper() == "DT"), None)
    if vcol is None:
        for c in reversed(list(df.columns)):
            if pd.to_numeric(df[c], errors="coerce").notna().sum() >= 2:
                vcol = c
                break
    if vcol is None:
        return []
    if pcol:
        df = df.sort_values(pcol)
    vals = [v for v in pd.to_numeric(df[vcol], errors="coerce").tolist() if v == v]
    return [round(v / 10000, 1) for v in vals[-points:]]


def collect_indicators():
    """지표 탭용 시계열 6종. 각 항목 {key,label,sub,unit,col,series}.
    가격지수는 전부 KB(신뢰 소스), 미분양 KOSIS, 금리 ECOS. 실패 항목은 자동 생략."""
    inds = []

    def add(key, label, sub, unit, col, series):
        if series and len(series) >= 2:
            inds.append({"key": key, "label": label, "sub": sub,
                         "unit": unit, "col": col, "series": series})

    try:
        add("sale", "매매가격지수", "서울 · 주간(KB)", "", "#B65F5A",
            _kb_seoul_series("index", {"월간주간구분코드": "02", "매물종별구분": "01",
                                       "매매전세코드": "01"}))
    except Exception as e:
        print(f"[realestate] KB 매매지수 실패: {e}")
    try:
        add("jeonse", "전세가격지수", "서울 · 주간(KB)", "", "#5A7CA0",
            _kb_seoul_series("index", {"월간주간구분코드": "02", "매물종별구분": "01",
                                       "매매전세코드": "02"}))
    except Exception as e:
        print(f"[realestate] KB 전세지수 실패: {e}")
    try:
        add("buy", "매수우위지수", "서울 · 주간(KB) · 100=중립", "", "#B89A5C",
            _kb_seoul_series("trend", {"메뉴코드": "01", "월간주간구분코드": "02"}))
    except Exception as e:
        print(f"[realestate] KB 매수우위 실패: {e}")
    try:
        add("jr", "전세가율", "서울 · 월간(KB)", "%", "#7E9A83",
            _kb_seoul_series("jratio", {"월간주간구분코드": "01", "매물종별구분": "01"}))
    except Exception as e:
        print(f"[realestate] KB 전세가율 실패: {e}")
    try:
        add("unsold", "미분양", "전국 · 월간(KOSIS)", "만호", "#8A7C9E",
            _collect_kosis_unsold())
    except Exception as e:
        print(f"[realestate] KOSIS 미분양 실패: {e}")
    try:
        add("rate", "주담대 금리", "월간(한은 ECOS)", "%", "#9a9b92",
            _collect_mortgage_rate())
    except Exception as e:
        print(f"[realestate] ECOS 금리 실패: {e}")
    return inds


# ── 거래량 (국토부 실거래 '건수' — 가격 median 아님, 노이즈 무관) ──
def _collect_rtms_volume(asof, exclude_direct=True):
    """시군구별 주간 거래량(v)·전주비(vc). 실패 시 {} (거래량만 비고 가격지수엔 무영향)."""
    try:
        _preflight(asof)
    except Exception as e:
        print(f"[realestate] 거래량 preflight 실패(거래량만 생략): {e}")
        return {}
    key = _get_key()
    yms = _months_back(asof, 2)
    stats = {"ok": 0, "fail": 0, "rows": 0, "calls": 0, "empty200": 0,
             "http": {}, "last_err": ""}
    w_now0 = asof - timedelta(days=WINDOW_DAYS - 1)
    w_prev0 = asof - timedelta(days=2 * WINDOW_DAYS - 1)
    out = {}
    for name, codes in SIGUNGU_CODES.items():
        sales = []
        for code in codes:
            for ym in yms:
                sales += _fetch(key, code, ym, "매매", stats)
        if exclude_direct:
            sales = [r for r in sales if not r["direct"]]

        def win(rows, a, b):
            return [r for r in rows if a <= r["date"] <= b]

        s_now = win(sales, w_now0, asof)
        s_prev = win(sales, w_prev0, w_now0 - timedelta(days=1))
        v = len(s_now)
        vc = round((v / len(s_prev) - 1) * 100) if s_prev else 0
        out[name] = {"v": v, "vc": vc}
    return out


# ── 지역 지표 (지도) — KB 가격지수(mm/js/jr) + 실거래 건수(v/vc) ──
def collect_region_metrics(asof=None, exclude_direct=True):
    """지역명 -> {'mm','js','v','vc','jr'}.
    가격 방향(mm/js)·전세가율(jr)은 KB 월간 가격지수(신뢰 소스),
    거래량(v/vc)은 국토부 실거래 '건수'. KB를 한 건도 못 받으면 예외(뷰어 샘플 폴백)."""
    asof = asof or date.today()
    kb_change = collect_kb_region_change("01")    # 월간
    if not kb_change:
        raise RuntimeError(
            "KB 가격지수 증감률을 받지 못했어요(지역코드/응답 형식/차단 확인). "
            "data-api.kbland.kr 응답을 점검하세요.")
    try:
        kb_jr = collect_kb_region_jeonse_ratio("01")
    except Exception as e:
        print(f"[realestate] KB 전세가율 실패: {e}")
        kb_jr = {}
    try:
        vol = _collect_rtms_volume(asof, exclude_direct)
    except Exception as e:
        print(f"[realestate] 거래량 수집 실패: {e}")
        vol = {}

    result = {}
    for name in SIGUNGU_CODES:
        ch = kb_change.get(name, {})
        result[name] = {
            "mm": ch.get("mm", 0.0),       # 월간 매매지수 증감률 %
            "js": ch.get("js", 0.0),       # 월간 전세지수 증감률 %
            "jr": kb_jr.get(name),         # 전세가율 %
            "v": vol.get(name, {}).get("v", 0),
            "vc": vol.get(name, {}).get("vc", 0),
        }
    return result


# ── 특이거래 ────────────────────────────────────────────────────
_BG = {"신고가": ("#FCEBEB", "#A32D2D"), "급등": ("#FCEBEB", "#A32D2D"),
       "신저가": ("#E6F1FB", "#0C447C"), "급락": ("#E6F1FB", "#0C447C"),
       "거래량 급증": ("#FAEEDA", "#854F0B"), "거래량 급감": ("#F1EFE8", "#444441")}


def _fmt_eok(manwon):
    return f"{manwon/10000:.1f}억"


def collect_anomalies(asof=None, exclude_direct=True, months=ANOM_MONTHS, limit=40):
    """특이거래 리스트. 뷰어 fetch_anomalies와 동일한 튜플 형식으로 반환.
       (유형, 배경, 글자색, 단지, 지역, 면적, 가격, 변동, 거래유형, 제외여부, 거래일ISO)"""
    asof = asof or date.today()
    _preflight(asof)
    key = _get_key()
    yms = _months_back(asof, months)
    recent0 = asof - timedelta(days=WINDOW_DAYS - 1)
    prev_weeks = max((months * 30) / WINDOW_DAYS - 1, 1)
    stats = {"ok": 0, "fail": 0, "rows": 0, "calls": 0, "empty200": 0,
             "http": {}, "last_err": ""}

    items = []
    for name, codes in SIGUNGU_CODES.items():
        rows = []
        for code in codes:
            for ym in yms:
                rows += _fetch(key, code, ym, "매매", stats)
        if not rows:
            continue

        groups = {}
        for r in rows:
            gkey = (r["apt"], round(r["area"]))
            groups.setdefault(gkey, []).append(r)

        for (apt, area), grp in groups.items():
            grp.sort(key=lambda r: r["date"])
            recent = [r for r in grp if r["date"] >= recent0]
            if not recent:
                continue
            prices = [r["price"] for r in grp]
            hi, lo = max(prices), min(prices)

            for r in recent:
                if exclude_direct and r["direct"]:
                    continue
                area_s = f"{round(area)}㎡"
                base = (apt, name, area_s, _fmt_eok(r["price"]))
                if len(grp) >= 2 and r["price"] >= hi:
                    items.append(("신고가", *_BG["신고가"], *base, "신고", r["trade"] or "-", r["direct"], r["date"].isoformat()))
                elif len(grp) >= 2 and r["price"] <= lo:
                    items.append(("신저가", *_BG["신저가"], *base, "신저", r["trade"] or "-", r["direct"], r["date"].isoformat()))
                idx = grp.index(r)
                if idx > 0:
                    prev_p = grp[idx - 1]["price"]
                    if prev_p:
                        dpct = (r["price"] / prev_p - 1) * 100
                        if dpct >= JUMP_PCT:
                            items.append(("급등", *_BG["급등"], *base, f"+{dpct:.1f}%", r["trade"] or "-", r["direct"], r["date"].isoformat()))
                        elif dpct <= -JUMP_PCT:
                            items.append(("급락", *_BG["급락"], *base, f"{dpct:.1f}%", r["trade"] or "-", r["direct"], r["date"].isoformat()))

        apt_recent, apt_total = {}, {}
        for r in rows:
            apt_total[r["apt"]] = apt_total.get(r["apt"], 0) + 1
            if r["date"] >= recent0:
                apt_recent[r["apt"]] = apt_recent.get(r["apt"], 0) + 1
        for apt, rc in apt_recent.items():
            avg_wk = apt_total[apt] / prev_weeks
            if avg_wk > 0 and rc >= 3 and rc >= VOL_SURGE * avg_wk:
                items.append(("거래량 급증", *_BG["거래량 급증"], apt, name, "전체",
                              f"{rc}건/주", f"+{round((rc/avg_wk-1)*100)}%", "-", False, asof.isoformat()))

    if stats["rows"] == 0:
        raise RuntimeError("특이거래 판정용 실거래를 한 건도 받지 못했어요." + _zero_hint(stats))

    def _mag(it):
        chg = it[7]
        try:
            return abs(float(chg.replace("%", "").replace("+", "").replace("건/주", "")))
        except ValueError:
            return 999
    items.sort(key=_mag, reverse=True)
    seen, dedup = set(), []
    for it in items:
        k = (it[0], it[3], it[5])
        if k in seen:
            continue
        seen.add(k); dedup.append(it)
        if len(dedup) >= limit:
            break
    return dedup
