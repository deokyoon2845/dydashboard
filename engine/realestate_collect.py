"""부동산 데이터 수집 — 국토부 아파트 실거래가(매매·전세) 기반.

수도권 시군구별 아파트 매매/전세 실거래를 받아
  · 지도용 지역 지표: 거래량(v)·거래량 전주비(vc)·거래 평소주당평균(vavg)·매매 주간변화(mm)·전세 주간변화(js)·전세가율(jr)
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
import re
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
ANOM_MONTHS = 12       # 특이거래 판정 윈도우(개월) — 신고가=최근12개월 최고 기준
# 실거래량(지표 탭) 월별 시계열 조회 개월 — 코드 60개×개월수만큼 국토부 호출.
# 늘리면 추세가 길어지지만 API 쿼터·수집시간이 비례해 늘어난다(보수적으로 24).
_APT_VOLUME_MONTHS = 24
JUMP_PCT = 7.0         # 급등/급락 임계(직전 거래 대비 %)
VOL_SURGE = 2.0        # 거래량 급증 배수(최근 1개월 vs 평소 월평균)
ANOM_SURGE_MIN_BASE = 0.75   # 거래량 급증 분모(평소 월평균) 하한 — 소표본 폭주(+8200%) 차단
# 특이거래 '생성(엔진)'은 가장 느슨하게 슈퍼셋으로 만들고, 뷰어가 프리셋(느슨/표준/엄격)으로
# 좁힌다. 대상은 '주요 단지 유니버스'로 제한(소형 노이즈 원천 차단, 세대수 API 비의존).
ANOM_GEN = {"freq": 5,          # 최근 12개월 단지 매매건수 ≥ (저유동 보조 컷)
            "jump": 7.0,        # 급등/급락 직전거래 대비 % ≥
            "margin": 0.3,      # 신고가/신저가: 직전 최고/최저 초과 마진 % ≥
            "surge": 1.5,       # 거래량 급증 배수 ≥ (평소 월평균 대비 ×)
            "surge_n": 3,       # 거래량 급증 최근 1개월 절대건수 ≥
            "high_months": 6,   # 신고가/신저가 판정 창(개월) — 6개월 내 최고/최저 대비
            "days": 45}         # 표시 후보 기간(최근 N일 신고분, 신고지연 흡수)

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
    "lead50": f"{_KB_BASE}/leadApt50Indx",         # KB선도아파트50지수
    "median": f"{_KB_BASE}/mdpsPrc",               # 매매중위가격(만원, 지역코드 無→전 지역)
    "avg": f"{_KB_BASE}/avgPrc",                   # 매매평균가격(만원, 지역코드 無→전 지역)
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
    """KB 응답에서 '서울' 시도행의 값 시계열(최근 points개). 실패 시 [].
    (priceIndex·dealCntstTnantRato 등 dataList가 평면 숫자인 엔드포인트용.)"""
    data = _kb_get(_KB_URL[url_key], {**params, "지역코드": _KB_SIDO["서울"]})
    rows = _kb_rows(data)
    if not rows:
        return []
    pick = next((r for r in rows if r["name"] in ("서울", "서울특별시")), rows[0])
    vals = [v for v in pick["vals"] if v is not None]
    return [round(v, 2) for v in vals[-points:]]


# maktTrnd(매수우위·전세수급·전망 등)는 dataList 항목이 dict라 메뉴별 지수 컬럼을 뽑아야 한다.
_KB_MAKT_COL = {"01": "매수우위지수", "02": "매매거래지수", "03": "전세수급지수",
                "04": "전세거래지수", "05": "매매상승하락전망지수",
                "06": "전세상승하락전망지수"}


def _kb_maktrnd_series(메뉴코드, 월간주간="02", 지역="서울", points=60):
    """maktTrnd → 서울 시도행 지수 시계열. dataList 항목(dict)에서 메뉴별 지수만 추출.
    실패 시 []. (05·06 전망지수는 월간만 제공 → 월간주간='01' 권장.)"""
    data = _kb_get(_KB_URL["trend"], {"메뉴코드": 메뉴코드, "월간주간구분코드": 월간주간,
                                      "지역코드": _KB_SIDO.get(지역, "11")})
    if not data:
        return []
    dates = data.get("날짜리스트") or []
    rows = data.get("데이터리스트") or []
    if not rows:
        return []
    col = _KB_MAKT_COL.get(메뉴코드)
    pick = next((r for r in rows
                 if str(r.get("지역명", "")) in ("서울", "서울특별시")), rows[0])
    out = []
    for v in (pick.get("dataList") or [])[:len(dates)]:
        if isinstance(v, dict):
            v = v.get(col)
        try:
            out.append(round(float(v), 2))
        except (TypeError, ValueError):
            continue
    return out[-points:]


def _kb_lead50_series(points=60):
    """KB선도아파트50지수(전국) 시계열. leadApt50Indx 전용 응답('선도50지수리스트')."""
    data = _kb_get(_KB_URL["lead50"], {})
    if not data:
        return []
    out = []
    for v in (data.get("선도50지수리스트") or []):
        try:
            out.append(round(float(v), 2))
        except (TypeError, ValueError):
            continue
    return out[-points:]


# ── 미분양(KOSIS)·금리(ECOS) — 엔진에서 수집(뷰어 라이브 호출 제거) ──
def _env_key(*names):
    for n in names:
        v = os.environ.get(n)
        if v:
            return v.strip()
    return None


# ── 서울·수도권 아파트 매매 중위/평균가격 (KB · 억원 · 지표탭 가격블록) ──────
#   mdpsPrc/avgPrc는 지역코드 파라미터가 없어 전 지역(전국·서울·수도권·시도…)을
#   한 번에 돌려준다 → 응답에서 서울·수도권 행만 골라 만원→억으로 환산한다.
#   (중위가격은 비가법적이라 직접 합성 불가 — KB가 제공하는 '수도권' 집계행을 그대로 사용.
#    수도권 행이 없으면 해당 지역은 비워둔다: 가짜 합성 없음.)
_PRICE_REGIONS = {                       # 결과키: (지역코드, 지역명 후보들)
    "seoul": ("1100000000", ("서울특별시", "서울")),
    "sudo":  (None, ("수도권",)),
}


def _kb_price_pick(rows, code, names, points):
    """rows에서 (지역코드 일치 → 지역명 포함) 행의 값 시계열(만원→억, 최근 points)."""
    pick = None
    if code:
        pick = next((r for r in rows if r.get("code") == code), None)
    if pick is None:
        pick = next((r for r in rows
                     if any(nm in r.get("name", "") for nm in names)), None)
    if pick is None:
        return []
    vals = [v for v in pick["vals"] if v is not None]
    return [round(v / 10000.0, 2) for v in vals[-points:]]   # 만원 → 억


def _collect_price_levels(points=18):
    """{지역키: {'median':[...억], 'mean':[...억]}} (서울·수도권, 월간 최근 points).
    실패/미발견 항목은 생략. 전부 실패 시 {}."""
    out = {}
    for stat_key, metric_key in (("median", "median"), ("avg", "mean")):
        try:
            data = _kb_get(_KB_URL[stat_key],
                           {"매물종별구분": "01", "매매전세코드": "01"})
            rows = _kb_rows(data)
        except Exception as e:
            print(f"[realestate] KB {stat_key} 호출 실패: {e}")
            continue
        if not rows:
            continue
        for rkey, (code, names) in _PRICE_REGIONS.items():
            series = _kb_price_pick(rows, code, names, points)
            if series:
                out.setdefault(rkey, {})[metric_key] = series
    return out



    """한은 ECOS 주담대 가중평균금리(월, 최근 points개). 실패 시 []."""
    key = _env_key("ECOS_API_KEY")
    if not key:
        return []
    end = date.today().strftime("%Y%m")
    # points만큼 거슬러 갈 수 있도록 시작월을 충분히(최대 points+12개월 ≒ years) 잡는다.
    back_years = max(2, (points + 12) // 12)
    start = f"{int(end[:4]) - back_years}{end[4:]}"
    url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/200/"
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


# ── 실거래량(수도권 아파트 매매 '건수') — KOSIS 부동산거래현황(월, 단발 호출) ──
#   RTMS 49개 코드×개월 무거운 스윕 대신 KOSIS 1콜로 2020.1까지 가볍게 확보.
#   이 표는 '거래주체별'이라 (지역×주체)로 여러 행 → 주체 '계/합계'만 남겨 중복합산 방지.
#   수도권 = 서울+인천+경기(시도명 매칭) · 시도명을 못 찾으면 전국으로 폴백.
#   구조 인식 실패/0이면 [] → 뷰어는 '연결예정' 유지(가짜 데이터 없음).
#   [검증] 첫 07:00 수집 로그에 '[realestate] KOSIS 거래량 …'이 찍힌다.
#          tbl/지역 인식이 안 되거나 값 자릿수가 이상하면 아래 _KOSIS_APT_VOL만 교체.
_KOSIS_APT_VOL = {
    "org": "408",                            # 한국부동산원
    "tbl": "DT_408_2006_S0066",              # 거래주체별 아파트매매거래현황(월)
    "sudogwon": ("서울", "인천", "경기"),       # 수도권 합산 대상 시도
    "total_labels": ("계", "합계", "소계", "전체", "총계"),  # 거래주체 '총합' 라벨
}


def _collect_kosis_apt_volume(points=18):
    """KOSIS 월별 아파트 매매 거래량(수도권 합) 건수 시계열(최근 points개, 과거→현재).
    실패/구조불명/0이면 [] (가짜 데이터 없음)."""
    key = _env_key("KOSIS_API_KEY")
    if not key:
        return []
    try:
        import pandas as pd
        from PublicDataReader import Kosis
        api = Kosis(key)
        cfg = _KOSIS_APT_VOL
        df, last_err = None, ""
        # 분류 차원 수를 몰라도 동작하도록 obj 레벨을 단계적으로 확장(KOSIS 에러코드20 회피).
        for extra in ({}, {"objL2": "ALL"}, {"objL2": "ALL", "objL3": "ALL"}):
            try:
                df = api.get_data("통계자료", orgId=cfg["org"], tblId=cfg["tbl"],
                                  itmId="ALL", objL1="ALL", prdSe="M",
                                  newEstPrdCnt=str(points + 3), **extra)
            except Exception as e:
                last_err, df = str(e), None
            if df is not None and len(df):
                break
        if df is None or len(df) == 0:
            print(f"[realestate] KOSIS 거래량 0행 — tbl={cfg['tbl']} err={last_err}")
            return []
        cols = list(df.columns)
        pcol = next((c for c in cols if "시점" in c or c.upper() == "PRD_DE"), None)
        vcol = next((c for c in cols if c in ("수치", "DT") or c.upper() == "DT"), None)
        if vcol is None:
            for c in reversed(cols):
                if pd.to_numeric(df[c], errors="coerce").notna().sum() >= 2:
                    vcol = c
                    break
        nmcols = [c for c in cols if c.endswith("_NM") or c.endswith("명")]
        sido_keys = list(cfg["sudogwon"]) + ["전국"]
        regcol = next((c for c in nmcols
                       if df[c].astype(str).str.contains("|".join(sido_keys)).any()), None)
        if not (pcol and vcol and regcol):
            print(f"[realestate] KOSIS 거래량 컬럼 인식 실패 cols={cols}")
            return []
        df = df.copy()
        df["_v"] = pd.to_numeric(df[vcol], errors="coerce")
        # 지역 외 분류(거래주체 등)는 '계/합계'만 남겨 중복합산 방지.
        for c in [x for x in nmcols if x != regcol]:
            mask = df[c].astype(str).str.contains("|".join(cfg["total_labels"]))
            if mask.any():
                df = df[mask]
        reg = df[regcol].astype(str)
        sel = df[reg.str.contains("|".join(cfg["sudogwon"]))]
        scope = "수도권"
        if sel.empty:
            sel = df[reg.str.contains("전국")]
            scope = "전국"
        if sel.empty:
            print(f"[realestate] KOSIS 거래량 지역 매칭 실패 names={list(reg.unique())[:12]}")
            return []
        g = sel.dropna(subset=["_v"]).groupby(pcol)["_v"].sum().sort_index()
        cur_ym = date.today().strftime("%Y%m")   # 신고지연 과소집계 현재월 제외
        series = [int(round(v)) for p, v in g.items() if str(p) != cur_ym][-points:]
        if not any(v > 0 for v in series):
            print(f"[realestate] KOSIS 거래량 전수 0 — scope={scope}")
            return []
        print(f"[realestate] KOSIS 거래량 OK scope={scope} n={len(series)} 최근={series[-1]}")
        return series
    except Exception as e:
        print(f"[realestate] KOSIS 거래량 실패: {e}")
        return []


def collect_indicators():
    """지표 탭용 시계열. 각 항목 {key,label,sub,unit,col,series}.
    전부 KB(신뢰 소스): 매매·전세·선도50·매수우위·전세수급·매매전망·전세전망·전세가율
    + 서울/수도권 중위·평균가격. 실패 항목은 자동 생략."""
    inds = []
    # 모든 지표 차트가 2020.1월부터 같은 시작점으로 정렬되도록 길이를 통일한다.
    # 시계열은 날짜 없이 값 배열만 반환하고, 뷰어가 ASOF에서 주(7일)·월(30일) 간격으로
    # 거꾸로 날짜를 재구성하므로 '개수'를 2020-01-01→오늘에 맞추면 시작점이 정렬된다.
    _span = (date.today() - date(2020, 1, 1)).days
    WN = _span // 7 + 1       # 주간 지표 개수(KB 주간) — 뷰어 7일 간격 → 2020.1 시작
    MN = _span // 30 + 1      # 월간 지표 개수(KB·KOSIS·ECOS) — 뷰어 30일 간격 → 2020.1 시작

    def add(key, label, sub, unit, col, series):
        if series and len(series) >= 2:
            inds.append({"key": key, "label": label, "sub": sub,
                         "unit": unit, "col": col, "series": series})

    try:
        add("sale", "매매가격지수", "서울 · 주간(KB)", "", "#B65F5A",
            _kb_seoul_series("index", {"월간주간구분코드": "02", "매물종별구분": "01",
                                       "매매전세코드": "01"}, points=WN))
    except Exception as e:
        print(f"[realestate] KB 매매지수 실패: {e}")
    try:
        add("jeonse", "전세가격지수", "서울 · 주간(KB)", "", "#5A7CA0",
            _kb_seoul_series("index", {"월간주간구분코드": "02", "매물종별구분": "01",
                                       "매매전세코드": "02"}, points=WN))
    except Exception as e:
        print(f"[realestate] KB 전세지수 실패: {e}")
    try:
        add("lead50", "선도아파트50지수", "전국 · 주간(KB) · 상위 50개 단지", "", "#A35F5A",
            _kb_lead50_series(points=WN))
    except Exception as e:
        print(f"[realestate] KB 선도50지수 실패: {e}")
    try:
        # maktTrnd는 dataList가 dict라 전용 파서 사용(기존 평면 파싱 버그 수정)
        add("buy", "매수우위지수", "서울 · 주간(KB) · 100=중립", "", "#B89A5C",
            _kb_maktrnd_series("01", "02", points=WN))
    except Exception as e:
        print(f"[realestate] KB 매수우위 실패: {e}")
    try:
        add("jsup", "전세수급지수", "서울 · 주간(KB) · 100=균형", "", "#6E8FA8",
            _kb_maktrnd_series("03", "02", points=WN))
    except Exception as e:
        print(f"[realestate] KB 전세수급 실패: {e}")
    try:
        add("outlook", "매매가격전망지수", "서울 · 월간(KB) · 100=중립", "", "#C2A05A",
            _kb_maktrnd_series("05", "01", points=MN))
    except Exception as e:
        print(f"[realestate] KB 매매전망 실패: {e}")
    try:
        add("joutlook", "전세가격전망지수", "서울 · 월간(KB) · 100=중립", "", "#8AA0B5",
            _kb_maktrnd_series("06", "01", points=MN))
    except Exception as e:
        print(f"[realestate] KB 전세전망 실패: {e}")
    try:
        add("jr", "전세가율", "서울 · 월간(KB)", "%", "#7E9A83",
            _kb_seoul_series("jratio", {"월간주간구분코드": "01", "매물종별구분": "01"},
                             points=MN))
    except Exception as e:
        print(f"[realestate] KB 전세가율 실패: {e}")
    # (미분양·금리·실거래량은 지표 탭에서 제외 — KOSIS/ECOS 수집 중단)
    try:
        # 서울·수도권 매매 중위/평균가격(억) — 지표탭 '현재 매매가격' 블록용.
        # 카드(_INDV2_ORDER)엔 안 들어가고, 뷰어가 이 4개 키를 따로 묶어 블록으로 그린다.
        pl = _collect_price_levels(points=MN)
        _PRICE_META = {
            "med_seoul":  ("seoul", "median", "서울 아파트 매매 중위가격", "서울 · 월간(KB)"),
            "mean_seoul": ("seoul", "mean",   "서울 아파트 매매 평균가격", "서울 · 월간(KB)"),
            "med_sudo":   ("sudo",  "median", "수도권 아파트 매매 중위가격", "수도권 · 월간(KB)"),
            "mean_sudo":  ("sudo",  "mean",   "수도권 아파트 매매 평균가격", "수도권 · 월간(KB)"),
        }
        for k, (rk, mk, lab, sub) in _PRICE_META.items():
            add(k, lab, sub, "억", "#7E9A83", (pl.get(rk) or {}).get(mk) or [])
    except Exception as e:
        print(f"[realestate] KB 중위/평균가격 실패: {e}")
    return inds


# ── 거래량 (국토부 실거래 '건수' — 가격 median 아님, 노이즈 무관) ──
def _collect_apt_volume_series(asof=None, months=24, exclude_direct=True):
    """수도권 아파트 매매 '건수'의 월별 시계열(최근 months개월, 과거→현재).
    검증된 국토부 _fetch 경로를 그대로 재사용한다. 코드 60개 × months개월을 조회하므로
    호출량이 크다(=months를 무리하게 키우면 API 쿼터/시간 부담). 실패·전수 0건이면 []
    → 뷰어는 '연결예정' 슬롯을 유지(가짜 데이터 없음).
    신고 지연(약 30일)으로 '현재월'은 과소집계라 마지막 미완월은 제외한다."""
    asof = asof or date.today()
    try:
        _preflight(asof)
    except Exception as e:
        print(f"[realestate] 실거래량시계열 preflight 실패(생략): {e}")
        return []
    key = _get_key()
    yms = _months_back(asof, months)            # 과거→현재
    counts = {ym: 0 for ym in yms}
    stats = {"ok": 0, "fail": 0, "rows": 0, "calls": 0, "empty200": 0,
             "http": {}, "last_err": ""}
    for name, codes in SIGUNGU_CODES.items():
        for code in codes:
            for ym in yms:
                rows = _fetch(key, code, ym, "매매", stats)
                if exclude_direct:
                    rows = [r for r in rows if not r["direct"]]
                counts[ym] += len(rows)
    cur_ym = asof.strftime("%Y%m")
    series = [counts[ym] for ym in yms if ym != cur_ym]   # 미완 현재월 제외
    # 전수 0건(키 미승인/차단 등)이면 빈 리스트로 — 0으로 채운 '가짜 추세' 방지
    if not any(v > 0 for v in series):
        print(f"[realestate] 실거래량 전수 0건 — 생략."
              f" calls={stats['calls']} http={stats.get('http')}")
        return []
    return series


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
        # 평소 주당 평균(vavg): 현재 주(w_now0~asof) 제외, 그 이전 전체 거래를
        # 실제 보유 기간(주)으로 나눠 산출. 신고지연 큰 최근 주를 빼 안정적.
        base = [r for r in sales if r["date"] < w_now0]
        if base:
            span = (w_now0 - min(r["date"] for r in base)).days
            weeks = max(span / 7.0, 1.0)
            vavg = round(len(base) / weeks, 1)
        else:
            vavg = None
        out[name] = {"v": v, "vc": vc, "vavg": vavg}
    return out


# ── 권역 레벨 (강남3구·서울·경기·수도권) — KB 주간 가격지수 레벨 + 주간 등락 ──
#   priceIndex(레벨)를 시도코드(서울11/경기41)로 호출하면 시도 + 하위 구/시 행이 함께 온다.
#   → 서울·경기 시도, 강남/서초/송파 구 시계열을 한 번에 뽑아 권역 레벨을 만든다.
#   강남3구 = 3개 구 평균, 수도권 = 서울·경기 거래량 가중 블렌드(전용 KB코드 가정 없이 정직하게).
_GROUP_GU3 = ["강남구", "서초구", "송파구"]
_GROUP_KEYS = ["gn3", "seoul", "gg", "all"]
_GROUP_NAME = {"gn3": "강남3구", "seoul": "서울", "gg": "경기", "all": "수도권"}


def _kb_index_byname(me_code, 월간주간, sido_code, points=200):
    """priceIndex(레벨) → {KB지역명: [series]} (해당 시도 + 하위 구/시). 실패 시 {}."""
    try:
        data = _kb_get(_KB_URL["index"], {
            "월간주간구분코드": 월간주간, "매물종별구분": "01",
            "매매전세코드": me_code, "지역코드": sido_code})
    except Exception:
        return {}
    out = {}
    for r in _kb_rows(data):
        vals = [v for v in r["vals"] if v is not None]
        if vals:
            out[r["name"]] = [round(v, 2) for v in vals[-points:]]
    return out


def _pick_series(byname, *cands):
    """{지역명:series}에서 후보명을 포함관계로 찾아 첫 매칭 시계열. 없으면 []."""
    for c in cands:
        if c in byname:
            return byname[c]
    for c in cands:
        for k, v in byname.items():
            if c in k or k in c:
                return v
    return []


def _avg_series(serieses):
    """여러 시계열을 최근(뒤)에서 정렬해 elementwise 평균. 빈 입력 → []."""
    ss = [s for s in serieses if s]
    if not ss:
        return []
    n = min(len(s) for s in ss)
    if n == 0:
        return []
    cols = zip(*[s[-n:] for s in ss])
    return [round(sum(c) / len(c), 2) for c in cols]


def _blend_series(a, b, wa, wb):
    """두 시계열 가중 블렌드(최근 정렬). 한쪽만 있으면 그쪽."""
    a = [v for v in (a or []) if v is not None]
    b = [v for v in (b or []) if v is not None]
    if not a or not b:
        return a or b
    n = min(len(a), len(b))
    a, b = a[-n:], b[-n:]
    tot = (wa + wb) or 1
    return [round((x * wa + y * wb) / tot, 2) for x, y in zip(a, b)]


def _wk_change(series):
    """주간 등락 % = (마지막-직전)/직전×100. 표본 부족이면 0.0."""
    s = [v for v in (series or []) if v is not None]
    if len(s) < 2 or not s[-2]:
        return 0.0
    return round((s[-1] / s[-2] - 1) * 100, 2)


def _seoul_gu_names():
    """SIGUNGU_CODES에서 서울(코드 11…) 시군구명 집합."""
    return {n for n, codes in SIGUNGU_CODES.items()
            if any(str(c).startswith("11") for c in codes)}


def _agg_v_vc_jr(metrics, names):
    """시군구 metrics에서 names 그룹의 (거래량 합, 전주비%, 전세가율 v가중평균)."""
    v_now = 0.0
    v_prev = 0.0
    jr_num = 0.0
    jr_den = 0.0
    for n in names:
        m = metrics.get(n) or {}
        v = m.get("v") or 0
        vc = m.get("vc") or 0
        v_now += v
        denom = 1 + vc / 100.0
        v_prev += (v / denom) if denom else v
        jr = m.get("jr")
        if jr is not None:
            w = v or 1
            jr_num += jr * w
            jr_den += w
    vc_agg = round((v_now / v_prev - 1) * 100) if v_prev else 0
    jr_agg = round(jr_num / jr_den, 1) if jr_den else None
    return int(v_now), vc_agg, jr_agg


def _sigungu_from_byname(byname):
    """{KB 지역명: series} → {내 시군구명: series}.
    경기 자치구 시(예: '성남시 분당구')는 _match_region이 시 단위(성남시)로 접어 통합.
    한 시군구에 여러 KB행이 매칭되면 시-레벨 행을 우선, 없으면 구 시계열 평균(시 통합)."""
    grouped = {}
    for raw, ser in (byname or {}).items():
        if not ser:
            continue
        key = _match_region(str(raw))
        if not key:
            continue
        grouped.setdefault(key, []).append((str(raw).strip(), ser))
    out = {}
    for key, items in grouped.items():
        exact = [s for (nm, s) in items if nm.endswith(key)]
        chosen = exact if exact else [s for (_, s) in items]
        agg = chosen[0] if len(chosen) == 1 else _avg_series(chosen)
        if agg:
            out[key] = agg
    return out


def collect_region_levels(asof=None, metrics=None, points=350):
    """강남3구·서울·경기·수도권 + 개별 시군구의 매매·전세 지수 레벨 + 주간 등락 + 전세가율 + 거래량.

    반환 {'asof', 'groups':{k:{name,sale,sale_wk,jeonse,jeonse_wk,jr,v,vc,[children]}},
          'trend':{k:{sale:[...],jeonse:[...]}}}
    k ∈ gn3/seoul/gg/all(권역) + 개별 시군구명(서울 25개 구 / 경기 시).
    권역 entry에는 children(하위 시군구명 리스트, 매매지수 내림차순)이 붙는다.
    거래량(v/vc)은 주간 기준(시군구는 표본이 작아 변동 큼 — 뷰어에서 '표본 적음' 표시).
    metrics(시군구 dict)가 있으면 v/vc/jr 집계에 재사용. KB 레벨을 못 받으면 None.

    points: 보관할 '주간' 지수 포인트 수(최근값 기준 뒤에서 N개). KB 주간지수는
      기준시점 2022.1.10=100 이므로, 차트를 그 기준점부터 그리려면 N이 그날까지
      거슬러 갈 만큼 커야 한다(2022.1.10→현재 ≈ 232주). 350이면 2020년경까지
      포함(KB가 그 이전 rebased 시계열을 주는 경우)되어 '전체' 토글이 기준점부터 보인다.
      ※ 늘려도 KB 응답에 있는 만큼만 슬라이스되므로 과대해도 안전(여분은 무시).
    """
    asof = asof or date.today()
    metrics = metrics or {}

    su_sale = _kb_index_byname("01", "02", _KB_SIDO["서울"], points)
    su_jeon = _kb_index_byname("02", "02", _KB_SIDO["서울"], points)
    gg_sale = _kb_index_byname("01", "02", _KB_SIDO["경기"], points)
    gg_jeon = _kb_index_byname("02", "02", _KB_SIDO["경기"], points)
    if not (su_sale and gg_sale):
        return None

    seoul_sale = _pick_series(su_sale, "서울", "서울특별시")
    seoul_jeon = _pick_series(su_jeon, "서울", "서울특별시")
    gg_sale_s = _pick_series(gg_sale, "경기", "경기도")
    gg_jeon_s = _pick_series(gg_jeon, "경기", "경기도")
    gn3_sale = _avg_series([_pick_series(su_sale, g) for g in _GROUP_GU3])
    gn3_jeon = _avg_series([_pick_series(su_jeon, g) for g in _GROUP_GU3])

    seoul_gu = _seoul_gu_names()
    gg_si = set(SIGUNGU_CODES) - seoul_gu
    v_seoul = _agg_v_vc_jr(metrics, seoul_gu)[0]
    v_gg = _agg_v_vc_jr(metrics, gg_si)[0]
    ws, wg = (v_seoul or 1), (v_gg or 1)
    all_sale = _blend_series(seoul_sale, gg_sale_s, ws, wg)
    all_jeon = _blend_series(seoul_jeon, gg_jeon_s, ws, wg)

    series = {
        "gn3": (gn3_sale, gn3_jeon, _GROUP_GU3),
        "seoul": (seoul_sale, seoul_jeon, seoul_gu),
        "gg": (gg_sale_s, gg_jeon_s, gg_si),
        "all": (all_sale, all_jeon, set(SIGUNGU_CODES)),
    }
    groups, trend = {}, {}
    for k in _GROUP_KEYS:
        s_sale, s_jeon, names = series[k]
        if not s_sale:
            continue
        v, vc, jr = _agg_v_vc_jr(metrics, names)
        groups[k] = {
            "name": _GROUP_NAME[k],
            "sale": s_sale[-1] if s_sale else None,
            "sale_wk": _wk_change(s_sale),
            "jeonse": s_jeon[-1] if s_jeon else None,
            "jeonse_wk": _wk_change(s_jeon),
            "jr": jr,
            "v": v,
            "vc": vc,
        }
        trend[k] = {"sale": s_sale, "jeonse": s_jeon}
    if not groups:
        return None

    # ── 개별 시군구(서울 구 / 경기 시) 레벨·추이 ─────────────────
    #   시도 byname에 하위 구·시가 이미 함께 담겨 있다. 경기 자치구 시는 시 단위로 통합.
    sale_sg = {**_sigungu_from_byname(su_sale), **_sigungu_from_byname(gg_sale)}
    jeon_sg = {**_sigungu_from_byname(su_jeon), **_sigungu_from_byname(gg_jeon)}
    seoul_children, gg_children = [], []
    for name, s_sale in sale_sg.items():
        if not s_sale:
            continue
        s_jeon = jeon_sg.get(name, [])
        v, vc, jr = _agg_v_vc_jr(metrics, {name})
        groups[name] = {
            "name": name,
            "sale": s_sale[-1],
            "sale_wk": _wk_change(s_sale),
            "jeonse": (s_jeon[-1] if s_jeon else None),
            "jeonse_wk": _wk_change(s_jeon),
            "jr": jr,
            "v": v,
            "vc": vc,
            "leaf": True,
        }
        trend[name] = {"sale": s_sale, "jeonse": s_jeon}
        (seoul_children if name in _SEOUL else gg_children).append(name)

    def _by_sale(n):
        s = groups.get(n, {}).get("sale")
        return s if s is not None else -1.0
    seoul_children.sort(key=_by_sale, reverse=True)
    gg_children.sort(key=_by_sale, reverse=True)
    gn3_children = sorted([n for n in _GROUP_GU3 if n in groups],
                          key=_by_sale, reverse=True)
    if "gn3" in groups:
        groups["gn3"]["children"] = gn3_children
    if "seoul" in groups:
        groups["seoul"]["children"] = seoul_children
    if "gg" in groups:
        groups["gg"]["children"] = gg_children
    if "all" in groups:
        groups["all"]["children"] = []

    return {"asof": asof.strftime("%Y-%m-%d"), "groups": groups, "trend": trend}


# ── 지역 지표 (지도) — KB 가격지수(mm/js/jr) + 실거래 건수(v/vc) ──
# ── 지방 광역시(인천·부산·대구) — KB 시도코드 1회 호출로 하위 구가 함께 온다 ──
#   [중요] 이름 매칭은 '각 시도 응답 안에서만' 한다 → 서울 '중구' ↔ 대구 '중구' 충돌 방지.
#   (가) 정책: 지방은 KB 가격지수만 — 실거래(RTMS) 건수는 수집하지 않는다(지도 '거래' 칸 비움).
#   '이외' = 시 전체 지수로 근사(주요 3구를 뺀 나머지 대용). metrics['_local']로 실어 보냄(스키마 무변경).
_KB_LOCAL = {
    "incheon": {"sido": "28", "name": "인천", "city": ("인천", "인천광역시"),
                "gu": ("중구", "동구", "미추홀구", "연수구", "남동구",
                       "부평구", "계양구", "서구")},
    "busan":   {"sido": "26", "name": "부산", "city": ("부산", "부산광역시"),
                "gu": ("중구", "서구", "동구", "영도구", "부산진구", "동래구",
                       "남구", "북구", "해운대구", "사하구", "금정구", "강서구",
                       "연제구", "수영구", "사상구")},
    "daegu":   {"sido": "27", "name": "대구", "city": ("대구", "대구광역시"),
                "gu": ("중구", "동구", "서구", "남구", "북구", "수성구", "달서구")},
}


def _exact_gu_map(byname):
    """{KB지역명: 값} → {구명(마지막 토큰): 값}. '동구'가 '남동구'에 부분매칭되는
    충돌을 막기 위해 구명 단위 정확매칭용 맵을 만든다(첫 매칭 우선)."""
    out = {}
    for k, v in (byname or {}).items():
        toks = str(k).split()
        gu = toks[-1] if toks else str(k)
        out.setdefault(gu, v)
    return out


def _kb_local_jratio(sido_code):
    """해당 시도 전세가율 {KB지역명: jr}. 실패 시 {}."""
    try:
        data = _kb_get(_KB_URL["jratio"], {
            "월간주간구분코드": "01", "매물종별구분": "01", "지역코드": sido_code})
    except Exception:
        return {}
    out = {}
    for r in _kb_rows(data):
        lv = _kb_latest(r["vals"])
        if lv is not None:
            out[str(r["name"]).strip()] = round(lv, 1)
    return out


def collect_kb_local_metrics(points=350):
    """인천·부산·대구의 주요 3구 + '이외(시 전체 근사)' KB 지표.
    반환 {지역키: {'name', 'gu':{구명:{mm,js,jr,sale,jeonse}}, 'others':{mm,js,jr,sale,jeonse}}}.
    한 시도라도 받으면 그 시도만 채우고, 전부 실패면 {}. (월간 가격지수 기준.)"""
    out = {}
    for rkey, cfg in _KB_LOCAL.items():
        sido = cfg["sido"]
        idx_sale = _kb_index_byname("01", "01", sido, points)   # 월간 매매지수(레벨)
        idx_jeon = _kb_index_byname("02", "01", sido, points)   # 월간 전세지수(레벨)
        jr = _kb_local_jratio(sido)
        if not idx_sale:
            print(f"[realestate] KB 지방 {cfg['name']} 가격지수 0행 — 시도코드 {sido} 확인 필요")
            continue

        def _jr_of(*cands):
            for c in cands:
                for k, v in jr.items():
                    if c in k:
                        return v
            return None

        gu_out = {}
        sale_map = _exact_gu_map(idx_sale)      # 구명 정확매칭(동구↔남동구 충돌 방지)
        jeon_map = _exact_gu_map(idx_jeon)
        jr_map = _exact_gu_map(jr)
        for g in cfg["gu"]:
            sale = sale_map.get(g)
            jeon = jeon_map.get(g)
            if not sale:
                continue
            gu_out[g] = {"mm": _wk_change(sale), "js": _wk_change(jeon),
                         "jr": jr_map.get(g), "sale": sale, "jeonse": jeon}
        city_sale = _pick_series(idx_sale, *cfg["city"])
        city_jeon = _pick_series(idx_jeon, *cfg["city"])
        others = {"mm": _wk_change(city_sale), "js": _wk_change(city_jeon),
                  "jr": _jr_of(*cfg["city"]), "sale": city_sale, "jeonse": city_jeon}
        if gu_out or city_sale:
            out[rkey] = {"name": cfg["name"], "gu": gu_out, "others": others}
            print(f"[realestate] KB 지방 {cfg['name']} OK 구={len(gu_out)}/{len(cfg['gu'])} "
                  f"이외={'O' if city_sale else 'X'}")
    return out


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
            "vavg": vol.get(name, {}).get("vavg"),   # 평소 주당 평균 거래(현재주 제외)
        }

    # ── 권역(강남3구·서울·경기·수도권) 지수 레벨 + 주간 등락 + 추이 ──
    #   DB 스키마 변경 없이 metrics 페이로드에 네임스페이스 키('_groups','_trend')로 실어 보낸다.
    #   (뷰어 _merged_regions는 시군구명만 .get() 하므로 '_'-키는 무시된다. 호환 안전.)
    try:
        lv = collect_region_levels(asof, metrics=result)
        if lv:
            result["_groups"] = lv["groups"]
            result["_trend"] = lv["trend"]
            result["_asof"] = lv["asof"]
    except Exception as e:
        print(f"[realestate] 권역 레벨 수집 실패(생략): {e}")

    # ── 지방 광역시(인천·부산·대구) 지도 데이터 — '_local'로 실어 보냄(스키마 무변경) ──
    try:
        loc = collect_kb_local_metrics()
        if loc:
            result["_local"] = loc
            print(f"[realestate] 지방 지도 {list(loc)} 수집")
    except Exception as e:
        print(f"[realestate] 지방 지도 수집 실패(생략): {e}")
    return result


# ── 특이거래 ────────────────────────────────────────────────────
_BG = {"신고가": ("#FCEBEB", "#A32D2D"), "급등": ("#FCEBEB", "#A32D2D"),
       "신저가": ("#E6F1FB", "#0C447C"), "급락": ("#E6F1FB", "#0C447C"),
       "거래량 급증": ("#FAEEDA", "#854F0B"), "거래량 급감": ("#F1EFE8", "#444441")}


def _fmt_eok(manwon):
    return f"{manwon/10000:.1f}억"


def _fmt_cap(manwon):
    """시가총액(만원) → '19.0조' 또는 '5,200억'. (1조 = 1e8 만원)"""
    jo = manwon / 1e8
    if jo >= 1:
        return f"{jo:.1f}조"
    return f"{round(manwon/1e4):,}억"


# ── 공동주택 세대수 (거래 탭 '1,000세대+' 필터용) ──────────────────
#   data.go.kr 공동주택 '단지 목록제공'(getSigunguAptList3)으로 시군구 단지→kaptCode,
#   '기본 정보'(getAphusBassInfoV3)로 세대수(kaptdaCnt). 키는 MOLIT/PUBLIC_DATA 재사용.
#   ※ 두 서비스 모두 data.go.kr 활용신청 필요(목록 + 기본정보).
#   매칭 실패/미승인이어도 _KNOWN_UNITS(확실한 대단지)로 보강해 필터가 동작하게 한다.
_APT_LIST = "apis.data.go.kr/1613000/AptListService3/getSigunguAptList3"
_APT_INFO = "apis.data.go.kr/1613000/AptBasisInfoServiceV3/getAphusBassInfoV3"


def _norm_apt(s):
    """단지명 정규화(괄호·공백·'아파트' 제거)로 RTMS↔공동주택 매칭률 향상."""
    s = re.sub(r"\(.*?\)", "", str(s or ""))
    s = s.replace("아파트", "")
    return re.sub(r"[\s\-_·.]", "", s).strip().lower()


# 확실한 대단지(≥1,000세대) — API 매칭 실패/미승인 시 폴백·보강
_KNOWN_UNITS = {
    "헬리오시티": 9510, "가락헬리오시티": 9510, "파크리오": 6864, "잠실엘스": 5678,
    "리센츠": 5563, "트리지움": 3696, "잠실주공5단지": 3930, "은마": 4424,
    "올림픽선수기자촌": 5540, "고덕그라시움": 4932, "고덕아르테온": 4057,
    "고덕래미안힐스테이트": 3658, "마포래미안푸르지오": 3885, "래미안원베일리": 2990,
    "반포자이": 3410, "래미안퍼스티지": 2444, "개포자이프레지던스": 3375,
    "디에이치퍼스티어아이파크": 6702, "광교중흥에스클래스": 2231,
    "힐스테이트판교엘포레": 1185, "상계주공7": 2634, "광교자연앤힐스테이트": 1764,
    "동탄역시범더샵센트럴시티": 874, "광명아크로리버하임": 1305,
}
_KNOWN_UNITS = {_norm_apt(k): v for k, v in _KNOWN_UNITS.items() if v >= 1000}


def _dgo_json(host_path, params, timeout=12):
    """data.go.kr GET(JSON, https→http 폴백). response.body dict 반환, 실패 None."""
    key = _get_key()
    if not key:
        return None
    q = {"serviceKey": key, "type": "json", "numOfRows": 1000, "pageNo": 1, **params}
    for scheme in ("https", "http"):
        try:
            r = requests.get(f"{scheme}://{host_path}", params=q, timeout=timeout)
            r.raise_for_status()
            data = r.json()
        except Exception:
            continue
        return (((data or {}).get("response") or {}).get("body")) or {}
    return None


def _dgo_items(body):
    it = ((body or {}).get("items") or {})
    if isinstance(it, dict):
        it = it.get("item", [])
    if isinstance(it, dict):
        it = [it]
    return it or []


def _known_lookup(na):
    if not na:
        return None
    if na in _KNOWN_UNITS:
        return _KNOWN_UNITS[na]
    return next((u for n, u in _KNOWN_UNITS.items() if na in n or n in na), None)


# ── 세대수/시공사 맵 캐시(engine_cache:apt_info) — 7일 TTL, 미스만 재조회 ──
_UNITS_CACHE_KEY = "apt_info"
_UNITS_CACHE_MEMO = None      # 프로세스(런) 내 1회 로드 후 재사용
_UNITS_TTL_DAYS = 7


def _fresh(ts, days):
    """ts('YYYY-MM-DD')가 days일 이내면 True. 파싱 실패/없음 → False."""
    if not ts:
        return False
    try:
        return (date.today() - date.fromisoformat(str(ts)[:10])).days < days
    except Exception:
        return False


def _units_cache_load():
    global _UNITS_CACHE_MEMO
    if _UNITS_CACHE_MEMO is not None:
        return _UNITS_CACHE_MEMO
    cache = {}
    try:
        from modules.db import cache_get
        c = cache_get(_UNITS_CACHE_KEY)
        if isinstance(c, dict):
            cache = {k: v for k, v in c.items() if k != "_updated"}
    except Exception:
        cache = {}
    _UNITS_CACHE_MEMO = cache
    return cache


def _units_cache_save(cache):
    global _UNITS_CACHE_MEMO
    _UNITS_CACHE_MEMO = cache
    try:
        from modules.db import cache_set
        cache_set(_UNITS_CACHE_KEY, cache)
    except Exception:
        pass


# ── 작년말 baseline 캐시(engine_cache:rtms_dec_YYYYMM) — 주1회 재스윕 ──
_DEC_TTL_DAYS = 7


def _load_dec_baseline(ym):
    """전년12월 평단가 baseline 캐시 → {(sgg,apt):(ppa,n)}. 미스/만료/빈값 → None."""
    try:
        from modules.db import cache_get
        c = cache_get(f"rtms_dec_{ym}")
    except Exception:
        return None
    if not isinstance(c, dict) or not _fresh(c.get("_updated"), _DEC_TTL_DAYS):
        return None
    out = {}
    for k, v in c.items():
        if k == "_updated" or not isinstance(v, (list, tuple)) or len(v) != 2:
            continue
        sgg, _, apt = str(k).partition("|")
        try:
            out[(sgg, apt)] = (float(v[0]), int(v[1]))
        except (TypeError, ValueError):
            continue
    return out or None


def _save_dec_baseline(ym, dec):
    if not dec:
        return
    try:
        from modules.db import cache_set
        payload = {f"{sgg}|{apt}": [ppa, n] for (sgg, apt), (ppa, n) in dec.items()}
        cache_set(f"rtms_dec_{ym}", payload)
    except Exception:
        pass


def _apt_units_map(pairs):
    """{(시군구, 단지명): 세대수|None}. _apt_info_map(캐시 경유)에 위임."""
    return {k: v.get("units") for k, v in _apt_info_map(pairs).items()}


def _apt_info_map(pairs):
    """{(시군구,단지명): {'units','builder'}}. engine_cache(apt_info) 7일 TTL —
    신선한 항목은 캐시에서, 미스/만료만 data.go.kr 재조회 후 캐시에 머지(비용 절감)."""
    cache = _units_cache_load()
    out, misses = {}, []
    for sgg, apt in pairs:
        ck = f"{sgg}|{_norm_apt(apt)}"
        c = cache.get(ck)
        if isinstance(c, dict) and _fresh(c.get("ts"), _UNITS_TTL_DAYS):
            out[(sgg, apt)] = {"units": c.get("u"), "builder": c.get("b")}
        else:
            misses.append((sgg, apt))
    if misses:
        fetched = _apt_info_fetch(misses)
        today = date.today().isoformat()
        changed = False
        for k, v in fetched.items():
            out[k] = v
            cache[f"{k[0]}|{_norm_apt(k[1])}"] = {
                "u": v.get("units"), "b": v.get("builder"), "ts": today}
            changed = True
        if changed:
            _units_cache_save(cache)
    return out


def _apt_info_fetch(pairs):
    """{(시군구,단지명): {'units':세대수|None,'builder':시공사|None}} — 실제 API 조회.
    공동주택 목록(getSigunguAptList3)→기본정보(getAphusBassInfoV3, kaptdaCnt·kaptBcompany).
    매칭 실패 시 세대수만 _KNOWN_UNITS 폴백."""
    out = {}
    by_sgg = {}
    for sgg, apt in pairs:
        by_sgg.setdefault(sgg, set()).add(apt)
    info_cache = {}
    for sgg, apts in by_sgg.items():
        codes = SIGUNGU_CODES.get(sgg)
        name2code = {}
        if codes:
            code_list = codes if isinstance(codes, (list, tuple)) else [codes]
            for sgg_code in code_list:
                body = _dgo_json(_APT_LIST, {"sigunguCode": str(sgg_code)[:5]})
                for it in _dgo_items(body):
                    nm = _norm_apt(it.get("kaptName"))
                    kc = str(it.get("kaptCode") or "").strip()
                    if nm and kc:
                        name2code.setdefault(nm, kc)
        for apt in apts:
            na = _norm_apt(apt)
            kc = name2code.get(na) or next(
                (c for n, c in name2code.items() if na and (na in n or n in na)), None)
            units = builder = None
            if kc:
                if kc not in info_cache:
                    b = _dgo_json(_APT_INFO, {"kaptCode": kc})
                    item = (b or {}).get("item") or {}
                    if isinstance(item, list):
                        item = item[0] if item else {}
                    try:
                        u = int(str(item.get("kaptdaCnt")).strip())
                    except (ValueError, TypeError, AttributeError):
                        u = None
                    bc = str(item.get("kaptBcompany") or "").strip() or None
                    info_cache[kc] = {"units": u, "builder": bc}
                units = info_cache[kc].get("units")
                builder = info_cache[kc].get("builder")
            if units is None:
                units = _known_lookup(na)
            out[(sgg, apt)] = {"units": units, "builder": builder}
    return out


def collect_anomalies(asof=None, exclude_direct=True, months=ANOM_MONTHS, limit=150):
    """특이거래 리스트(느슨 슈퍼셋 — 뷰어가 프리셋으로 좁힘).
    대상은 '주요 단지 유니버스'로 제한(소형 노이즈 차단, 세대수 API 비의존). 유니버스
    미확보 시 전체 지역 폴백. 신고가/신저가는 최근 6개월 창, 거래량 급증은 월 단위 배수.
    반환 14-튜플:
      (유형, 배경, 글자색, 단지, 지역, 면적, 가격, 변동, 거래유형, 제외, 거래일ISO,
       세대수|None, 빈도(12개월 거래수),
       신호강도(신고가/신저가=마진%, 급등/급락=변동%, 거래량 급증=평소 대비 배수))
    [호환] 과거 11/12-튜플 스냅샷도 뷰어 _anom_norm이 그대로 정규화한다."""
    asof = asof or date.today()
    _preflight(asof)
    key = _get_key()
    yms = _months_back(asof, months)
    gen = ANOM_GEN
    recent0 = asof - timedelta(days=gen["days"] - 1)          # 표시 후보 기간
    high0 = asof - timedelta(days=gen["high_months"] * 31)    # 신고가/신저가 비교 창
    recent_m0 = asof - timedelta(days=29)                     # 거래량 급증: 최근 1개월
    base_months = max(months - 1, 1)                          # 평소 월평균 산정 개월(최근월 제외)
    stats = {"ok": 0, "fail": 0, "rows": 0, "calls": 0, "empty200": 0,
             "http": {}, "last_err": ""}

    # 대상 = '주요 단지 유니버스'로 제한(소형 노이즈 원천 차단). 미확보 시 전체(하위호환).
    uni = load_universe()
    uni = uni if (isinstance(uni, dict) and uni.get("flat")) else None
    uni_mem = universe_membership(uni) if uni else set()
    regions = universe_scope() if uni_mem else list(SIGUNGU_CODES.keys())

    def _in_uni(gu, apt):
        return (not uni_mem) or (f"{gu}|{_norm_apt(apt)}" in uni_mem)

    items = []
    for name in regions:
        codes = SIGUNGU_CODES.get(name) or []
        rows = []
        for code in codes:
            for ym in yms:
                rows += _fetch(key, code, ym, "매매", stats)
        if not rows:
            continue

        # 단지별 12개월 거래수(유동성 프록시 — 저유동 보조 컷)
        freq = {}
        for r in rows:
            freq[r["apt"]] = freq.get(r["apt"], 0) + 1

        # ── 신고가/신저가·급등/급락 (유니버스 단지, 면적 그룹) ──
        groups = {}
        for r in rows:
            if not _in_uni(name, r["apt"]):        # 유니버스 단지만 탐지
                continue
            groups.setdefault((r["apt"], round(r["area"])), []).append(r)
        for (apt, area), grp in groups.items():
            f = freq.get(apt, 0)
            if f < gen["freq"]:
                continue
            grp.sort(key=lambda r: r["date"])
            recent = [r for r in grp if r["date"] >= recent0]
            if not recent:
                continue
            for r in recent:
                if exclude_direct and r["direct"]:
                    continue
                base = (apt, name, f"{round(area)}㎡", _fmt_eok(r["price"]))
                # 신고가/신저가: 최근 high_months개월 내 직전 최고/최저를 '마진' 초과해야 인정
                prior = [g["price"] for g in grp if high0 <= g["date"] < r["date"]]
                if len(prior) >= 2:
                    p_hi, p_lo = max(prior), min(prior)
                    if r["price"] > p_hi:
                        mg = (r["price"] / p_hi - 1) * 100
                        if mg >= gen["margin"]:
                            items.append(("신고가", *_BG["신고가"], *base, "신고",
                                          r["trade"] or "-", r["direct"],
                                          r["date"].isoformat(), None, f, round(mg, 2)))
                    elif r["price"] < p_lo:
                        mg = (1 - r["price"] / p_lo) * 100
                        if mg >= gen["margin"]:
                            items.append(("신저가", *_BG["신저가"], *base, "신저",
                                          r["trade"] or "-", r["direct"],
                                          r["date"].isoformat(), None, f, round(mg, 2)))
                # 급등/급락: 동일면적 '직전 거래' 대비, 비교거래가 6개월 이내일 때만
                idx = grp.index(r)
                if idx > 0:
                    prev = grp[idx - 1]
                    if prev["price"] and (r["date"] - prev["date"]).days <= 183:
                        dpct = (r["price"] / prev["price"] - 1) * 100
                        if dpct >= gen["jump"]:
                            items.append(("급등", *_BG["급등"], *base, f"+{dpct:.1f}%",
                                          r["trade"] or "-", r["direct"],
                                          r["date"].isoformat(), None, f, round(abs(dpct), 2)))
                        elif dpct <= -gen["jump"]:
                            items.append(("급락", *_BG["급락"], *base, f"{dpct:.1f}%",
                                          r["trade"] or "-", r["direct"],
                                          r["date"].isoformat(), None, f, round(abs(dpct), 2)))

        # ── 거래량 급증 (유니버스 단지, 최근 1개월 vs 평소 월평균 배수) ──
        #   배수 = 최근1개월 건수 ÷ max(평소 월평균, 분모하한). 분모하한·절대건수하한이
        #   소표본 폭주(+8200%)를 차단한다. 주 단위 → 월 단위로 안정화.
        rc_m, total = {}, {}
        for r in rows:
            if not _in_uni(name, r["apt"]):
                continue
            total[r["apt"]] = total.get(r["apt"], 0) + 1
            if r["date"] >= recent_m0:
                rc_m[r["apt"]] = rc_m.get(r["apt"], 0) + 1
        for apt, cm in rc_m.items():
            if freq.get(apt, 0) < gen["freq"] or cm < gen["surge_n"]:
                continue
            base_month = (total[apt] - cm) / base_months
            base_eff = max(base_month, ANOM_SURGE_MIN_BASE)
            mult = cm / base_eff
            if mult >= gen["surge"]:
                items.append(("거래량 급증", *_BG["거래량 급증"], apt, name, "전체",
                              f"{cm}건/월", f"×{mult:.1f}", "-", False,
                              asof.isoformat(), None, freq.get(apt, 0), round(mult, 2)))

    if stats["rows"] == 0:
        raise RuntimeError("특이거래 판정용 실거래를 한 건도 받지 못했어요." + _zero_hint(stats))

    # 신호강도(sigstr=인덱스 13) 큰 순 → 중복 제거 → 상한
    items.sort(key=lambda it: (it[13] if len(it) > 13 and it[13] is not None else 0),
               reverse=True)
    seen, dedup = set(), []
    for it in items:
        k = (it[0], it[3], it[5])
        if k in seen:
            continue
        seen.add(k)
        dedup.append(tuple(it))
        if len(dedup) >= limit:
            break
    return dedup


# ════════════════════════════════════════════════════════════════
#  주요 단지 유니버스 — 지역별 '세대수' TOP-N 을 안정적으로 고정한다.
#
#  왜 필요한가: 시총·주목단지·특이거래가 지금은 '최근 거래 흐름'에 유니버스를
#  맡겨서, 거래가 튀는 소형 단지가 올라오고 조용한 대단지는 빠진다(집계 불안정,
#  소형단지 거래량 급증 +8,200% 같은 노이즈). → 세대수 기준 '주요 단지' 집합을
#  먼저 못박고, 시총·주목단지·특이거래 세 탭이 모두 그 위에서 계산한다.
#
#  스코프: 서울 25개구 전부 + 경기 핵심 9시(과천·성남·하남·광명·안양·용인·수원·화성·고양).
#  방식: 최근 12개월 실거래에 '등장한' 단지가 후보(대단지는 세대 많아 거래도 잦으니
#        조용해도 12개월 안엔 대부분 포착됨). 지역별 거래빈도 상위 후보만 세대수를
#        조회(콜드빌드 비용 상한) → ≥MIN_UNITS 컷 → 세대수 TOP-N 확정.
#  갱신: 세대수는 거의 불변 → engine_cache(re_universe) 30일 TTL. 월 1회만 실질 재빌드
#        (그 외 날은 캐시 반환 → API 0콜). 스윕 전수 실패 시 기존 캐시 유지(빈값 미덮음).
# ════════════════════════════════════════════════════════════════
UNIVERSE_CACHE_KEY = "re_universe"
UNIVERSE_TTL_DAYS = 30       # 재빌드 주기(세대수 정적 → 월 1회면 충분)
UNIVERSE_MONTHS = 12         # 후보 발굴용 실거래 스윕 개월
UNIVERSE_PRICE_MONTHS = 6    # 대표가 산정 우선 윈도우(최근 N개월, 부족 시 12개월 폴백)
UNIVERSE_TOP_N = 15          # 지역별 세대수 상위 N
UNIVERSE_MIN_UNITS = 500     # 최소 세대수 컷(소형 제외)
UNIVERSE_CAND = 25           # 지역별 세대수 조회 후보 상한(거래빈도 상위) — 콜드빌드 비용 상한
UNIVERSE_MIN_FREQ = 3        # 후보 최소 거래빈도(12개월) — 유령/오타 단지 컷

# 경기 핵심 9시(확정). 서울은 SIGUNGU_CODES의 '구'로 끝나는 이름 전부(25개구).
UNIVERSE_GG = ["과천시", "성남시", "하남시", "광명시", "안양시",
               "용인시", "수원시", "화성시", "고양시"]


def universe_scope():
    """유니버스 대상 지역명 리스트(서울 25개구 + 경기 핵심 9시). SIGUNGU_CODES 교집합."""
    seoul = [n for n in SIGUNGU_CODES if n.endswith("구")]
    gg = [g for g in UNIVERSE_GG if g in SIGUNGU_CODES]
    return seoul + gg


def load_universe():
    """engine_cache(re_universe)에서 유니버스 dict 반환(없거나 비면 None). 뷰어·엔진 공용 읽기."""
    try:
        from modules.db import cache_get
        c = cache_get(UNIVERSE_CACHE_KEY)
    except Exception:
        return None
    return c if isinstance(c, dict) and c.get("regions") else None


def universe_membership(uni=None):
    """유니버스 소속 판정용 set → {'지역|단지명norm'}. 미확보 시 빈 set."""
    uni = uni if isinstance(uni, dict) else load_universe()
    if not isinstance(uni, dict):
        return set()
    keys = uni.get("keys")
    if keys:
        return set(keys)
    return {f"{d['gu']}|{_norm_apt(d['apt'])}" for d in uni.get("flat", [])}


def _universe_fresh(cached):
    return (isinstance(cached, dict) and cached.get("regions")
            and _fresh(cached.get("_updated") or cached.get("asof"), UNIVERSE_TTL_DAYS))


def collect_universe(asof=None, force=False):
    """지역별 세대수 TOP-N '주요 단지 유니버스'를 만들어 engine_cache에 저장하고 반환.

    반환 dict:
      {'asof': ISO, 'scope': [지역...],
       'regions': {지역: [row...]},            # 세대수 내림차순. row 필드:
           #   apt,gu,sd,units,builder,dong,freq,
           #   price(만원),price_eok,ppa(㎡당 만원),area(대표전용㎡),last_deal(ISO),
           #   p59,p84(만원|None),jr(전세가율%|None),gap(갭 억|None)
       'flat':    [위 row...],                 # 전 지역 평탄화(세대수 내림차순)
       'keys':    ['지역|단지명norm'...]}         # 소속판정 set 재료
    신선한 캐시가 있으면(force=False) 재빌드 없이 그대로 반환(API 0콜).
    스윕 전수 실패 시 기존 캐시가 있으면 유지(빈 유니버스로 덮지 않음)."""
    asof = asof or date.today()
    if not force:
        cached = load_universe()
        if _universe_fresh(cached):
            return cached

    _preflight(asof)
    key = _get_key()
    yms = _months_back(asof, UNIVERSE_MONTHS)
    seoul_gu = set(_seoul_gu_names())
    scope = universe_scope()
    stats = {"ok": 0, "fail": 0, "rows": 0, "calls": 0, "empty200": 0,
             "http": {}, "last_err": ""}

    # 1) 지역별 후보 발굴 + 대표가 산출 — 12개월 매매 스윕(행 보존) → 거래빈도 상위 후보.
    #    대표가는 최근 UNIVERSE_PRICE_MONTHS개월 우선(없으면 12개월 전체)로 뽑아 '현재가'에 근접.
    price_cut = asof - timedelta(days=UNIVERSE_PRICE_MONTHS * 31)
    region_cands = {}          # 지역 → [단지 dict(가격 포함)]
    for name in scope:
        codes = SIGUNGU_CODES.get(name) or []
        per = {}               # apt → [매매 rows]
        for code in codes:
            for ym in yms:
                for r in _fetch(key, code, ym, "매매", stats):
                    if r.get("direct"):        # 직거래(증여추정) 제외 — 가격 왜곡 방지
                        continue
                    a = r["apt"]
                    if a:
                        per.setdefault(a, []).append(r)
        # 후보: 거래빈도 상위(대단지일수록 잦음) → ≥MIN_FREQ → 상위 CAND
        cand_apts = sorted(((a, len(rs)) for a, rs in per.items() if len(rs) >= UNIVERSE_MIN_FREQ),
                           key=lambda t: t[1], reverse=True)[:UNIVERSE_CAND]
        if not cand_apts:
            continue
        # 전세 스윕(같은 지역·기간) — 후보 전세가율/갭 산출용(월1회 비용이라 OK)
        jeon = {}
        for code in codes:
            for ym in yms:
                for r in _fetch(key, code, ym, "전월세", stats):
                    if r.get("direct"):
                        continue
                    jeon.setdefault(r["apt"], []).append(r["ppa"])
        picked = []
        for a, f in cand_apts:
            rs = per[a]
            rec = [r for r in rs if r["date"] >= price_cut] or rs
            price = statistics.median([r["price"] for r in rec])
            ppa = statistics.median([r["ppa"] for r in rec])
            area = round(statistics.median([r["area"] for r in rec]))
            dcount = {}
            for r in rs:
                if r.get("dong"):
                    dcount[r["dong"]] = dcount.get(r["dong"], 0) + 1
            dnm = max(dcount.items(), key=lambda kv: kv[1])[0] if dcount else ""
            jr = gap = None
            jp = jeon.get(a, [])
            if len(jp) >= 2 and ppa:
                jrv = statistics.median(jp) / ppa * 100
                if 30 <= jrv <= 95:            # 월세혼입·오류 이상치 제외
                    jr = round(jrv)
                    gap = round((ppa - statistics.median(jp)) * area / 1e4, 1) if area else None
            picked.append({
                "apt": a, "gu": name, "freq": f, "dong": dnm,
                "price": price, "price_eok": _fmt_eok(price), "ppa": round(ppa, 1),
                "area": area, "last_deal": max(r["date"] for r in rs).isoformat(),
                "p59": _recent_price_in_band(rs, 49.0, 63.0),
                "p84": _recent_price_in_band(rs, 74.0, 90.0),
                "jr": jr, "gap": gap,
            })
        region_cands[name] = picked

    if stats["rows"] == 0:
        prev = load_universe()      # 전수 실패 → 기존 유니버스라도 유지
        if prev:
            print("[realestate] 유니버스 스윕 전수 0건 — 기존 캐시 유지.")
            return prev
        raise RuntimeError("유니버스 후보 실거래를 한 건도 받지 못했어요." + _zero_hint(stats))

    # 2) 세대수 보강(후보 합집합 1회 조회) → ≥MIN_UNITS 컷 → 지역별 세대수 TOP-N
    pairs = {(name, d["apt"]) for name, lst in region_cands.items() for d in lst}
    info = {}
    try:
        info = _apt_info_map(list(pairs))
    except Exception as e:
        print(f"[realestate] 유니버스 세대수 보강 실패: {e}")

    regions, flat = {}, []
    for name, lst in region_cands.items():
        rows = []
        for d in lst:
            inf = info.get((name, d["apt"])) or {}
            units = inf.get("units")
            if not units or units < UNIVERSE_MIN_UNITS:
                continue
            d["sd"] = "seoul" if name in seoul_gu else "gg"
            d["units"] = int(units)
            d["builder"] = inf.get("builder")
            rows.append(d)
        rows.sort(key=lambda d: d["units"], reverse=True)
        rows = rows[:UNIVERSE_TOP_N]
        if rows:
            regions[name] = rows
            flat.extend(rows)

    flat.sort(key=lambda d: d["units"], reverse=True)
    out = {
        "asof": asof.isoformat(),
        "scope": scope,
        "regions": regions,
        "flat": flat,
        "keys": [f"{d['gu']}|{_norm_apt(d['apt'])}" for d in flat],
    }
    if not flat:
        prev = load_universe()      # 세대수 전멸(보강 실패 등) → 기존 캐시 유지
        if prev:
            print("[realestate] 유니버스 세대수 확보 0단지 — 기존 캐시 유지.")
            return prev
    else:
        try:
            from modules.db import cache_set
            cache_set(UNIVERSE_CACHE_KEY, out)
        except Exception as e:
            print(f"[realestate] 유니버스 캐시 저장 실패(무시): {e}")
    print(f"[realestate] 유니버스 {len(flat)}단지 / {len(regions)}지역 "
          f"(스윕 {stats.get('calls', 0)}콜, {stats.get('rows', 0)}건)")
    return out


# ════════════════════════════════════════════════════════════════
#  주목 단지(거래 활발·상승) — A: 국토부 실거래 기반 / B: 네이버 데이터랩 검색관심도
#  · 약관-clean: 호갱노노·아실·네이버부동산 '인기 리스트'는 공식 API 부재·차단·약관 이슈로 미사용.
#  · A 랭킹: 최근(≈30일) 거래 활발 + 가격 상승 단지. 우리 RTMS 데이터만 사용(안정).
#  · B 오버레이: openapi datalab/search(공식)로 후보 단지명 상대 검색관심도(0~100).
# ════════════════════════════════════════════════════════════════
HOT_MONTHS = 3          # 주목 단지 산정 윈도우(개월) — 특이거래보다 가볍게
HOT_MIN_FREQ = 6        # 후보 컷: 윈도우 내 단지 거래 ≥ (소형 제외)
HOT_RECENT_DAYS = 30    # '최근' 거래 정의(신고지연 흡수)
HOT_VOL_WEIGHT = 4.0    # 주목단지 heat 점수 = chg% + (vol_mult−1)×이 가중치(거래 가속 반영)


def _datalab_interest(names, ref="부동산", months=3):
    """단지명 리스트 → {단지명: 검색관심도 0~100}. 네이버 데이터랩 통합검색어 트렌드(공식).
    1콜 5그룹 제한 → (기준어 1 + 단지 4)씩 배치, 기준어로 정규화해 배치 간 비교 가능하게.
    키(NAVER_CLIENT_ID/SECRET) 없거나 실패하면 {} (B 생략 → A만 표시)."""
    cid = os.environ.get("NAVER_CLIENT_ID")
    csec = os.environ.get("NAVER_CLIENT_SECRET")
    if not (cid and csec) or not names:
        return {}
    import json as _json
    end = date.today()
    start = end - timedelta(days=months * 31)
    url = "https://openapi.naver.com/v1/datalab/search"
    hdr = {"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csec,
           "Content-Type": "application/json"}
    raw = {}
    for i in range(0, len(names), 4):
        batch = names[i:i + 4]
        groups = [{"groupName": "_ref", "keywords": [ref]}]
        groups += [{"groupName": n, "keywords": [n]} for n in batch]
        body = _json.dumps({"startDate": start.isoformat(), "endDate": end.isoformat(),
                            "timeUnit": "month", "keywordGroups": groups},
                           ensure_ascii=False).encode("utf-8")
        try:
            r = requests.post(url, headers=hdr, data=body, timeout=12)
            r.raise_for_status()
            res = (r.json() or {}).get("results", [])
        except Exception as e:
            print(f"[realestate] 데이터랩 호출 실패(배치 생략): {e}")
            continue
        means = {}
        for g in res:
            vals = [d.get("ratio", 0) for d in (g.get("data") or [])]
            means[g.get("title")] = (sum(vals) / len(vals)) if vals else 0.0
        ref_m = means.get("_ref", 0) or 1e-9
        for n in batch:
            raw[n] = means.get(n, 0.0) / ref_m       # 기준어 대비 상대값(배치 간 비교 가능)
    if not raw:
        return {}
    mx = max(raw.values()) or 1e-9
    return {n: round(v / mx * 100) for n, v in raw.items()}      # 0~100 정규화


def _recent_price_in_band(rows, lo, hi):
    """rows 중 전용면적이 [lo,hi) 인 가장 최근 거래의 가격(만원). 없으면 None."""
    cand = [r for r in rows if lo <= r["area"] < hi]
    if not cand:
        return None
    return max(cand, key=lambda r: r["date"])["price"]


def collect_hot_complexes(asof=None, months=HOT_MONTHS, top=20, exclude_direct=True,
                          with_search=False, with_cap=False, cap_per_gu=5, cap_cand=8,
                          cap_overall=50, with_gain=False, gain_top=20):
    """주목 단지 리스트(딕셔너리 배열). 최근 거래 활발 + 상승 단지 랭킹 + (옵션)검색관심도.
    반환 [{apt,gu,sd,recent,prev,vol_chg,price,price_eok,chg,area,freq,search}] (search=0~100|None).
    KB/세대수 비의존 — 국토부 실거래만. 표본 0이면 [].
    with_cap=True면 (hot리스트, 시총리더리스트) 튜플 반환 — 같은 RTMS 스윕·세대수 조회를
    공유해 '구별 시가총액 상위 단지'(시총=중위 실거래가×세대수)를 함께 만든다."""
    asof = asof or date.today()

    def _empty():
        if with_cap and with_gain:
            return [], [], []
        return ([], []) if with_cap else []

    try:
        _preflight(asof)
    except Exception as e:
        print(f"[realestate] 주목단지 preflight 실패(생략): {e}")
        return _empty()
    key = _get_key()
    yms = _months_back(asof, months)
    recent0 = asof - timedelta(days=HOT_RECENT_DAYS - 1)
    seoul_gu = _seoul_gu_names()
    stats = {"ok": 0, "fail": 0, "rows": 0, "calls": 0, "empty200": 0,
             "http": {}, "last_err": ""}
    agg = {}
    for name, codes in SIGUNGU_CODES.items():
        rows = []
        for code in codes:
            for ym in yms:
                rows += _fetch(key, code, ym, "매매", stats)
        if exclude_direct:
            rows = [r for r in rows if not r["direct"]]
        per = {}
        for r in rows:
            per.setdefault(r["apt"], []).append(r)
        for apt, rs in per.items():
            rec = [r for r in rs if r["date"] >= recent0]
            if len(rs) < HOT_MIN_FREQ or len(rec) < 2:        # 소형/저활동 제외
                continue
            prev = [r for r in rs if r["date"] < recent0]
            rec_ppa = statistics.median([r["ppa"] for r in rec])
            prev_ppa = statistics.median([r["ppa"] for r in prev]) if prev else rec_ppa
            chg = round((rec_ppa / prev_ppa - 1) * 100, 1) if prev_ppa else 0.0
            med_price = statistics.median([r["price"] for r in rec])
            area = round(statistics.median([r["area"] for r in rec]))
            agg[(name, apt)] = {
                "apt": apt, "gu": name,
                "sd": "seoul" if name in seoul_gu else "gg",
                "recent": len(rec), "prev": len(prev),
                "vol_chg": round((len(rec) / max(len(prev), 1) - 1) * 100),
                "vol_mult": (
                    round(len(rec) / (len(prev) * HOT_RECENT_DAYS
                                      / (months * 30 - HOT_RECENT_DAYS)), 1)
                    if len(prev) and (months * 30 - HOT_RECENT_DAYS) > 0 else None),
                "price": med_price, "price_eok": _fmt_eok(med_price),
                "chg": chg, "area": f"{area}㎡", "freq": len(rs), "search": None,
                "rec_ppa": rec_ppa, "area_num": area,
                "_rows": rs, "_rec": rec,
            }
    if not agg:
        return _empty()
    from collections import Counter

    # 유니버스 1회 로드 — 주목단지 랭킹 제한 + 시총(cap) 둘 다 재사용(중복 캐시읽기 방지).
    uni = load_universe()
    uni = uni if (isinstance(uni, dict) and uni.get("flat")) else None
    uni_mem = universe_membership(uni) if uni else set()

    # 주목단지 랭킹 — '유니버스 중 움직이는 대장주'.
    #   기존 (최근거래수, 상승률)은 회전율 높은 중소단지를 위로 올렸다. 대신:
    #   ① 유니버스(주요 단지)로 대상 제한 ② heat = 가격 모멘텀(chg%) + 거래 가속(vol_mult>1)
    #      → 규모 아닌 '움직임'으로 정렬(대단지도 스케일 무관하게 비교). 세대수는 동점 tiebreak.
    #   유니버스 미확보/유니버스 단지 최근활동 0이면 기존 정렬로 폴백(하위호환).
    def _heat(d):
        vb = 0.0
        m = d.get("vol_mult")
        if isinstance(m, (int, float)):
            vb = max(m - 1.0, 0.0) * HOT_VOL_WEIGHT
        return round((d.get("chg") or 0) + vb, 2)

    pool = ([d for d in agg.values()
             if f"{d['gu']}|{_norm_apt(d['apt'])}" in uni_mem] if uni_mem else [])
    if pool:
        ranked = sorted(pool, key=lambda d: (_heat(d), d.get("recent", 0),
                                             d.get("freq", 0)), reverse=True)[:top]
        for d in ranked:
            d["heat"] = _heat(d)
    else:
        ranked = sorted(agg.values(),
                        key=lambda d: (d["recent"], d["chg"]), reverse=True)[:top]

    # ── 시총(시가총액) 리더 — '주요 단지 유니버스' 기반(대단지 누락 방지) ──────
    #   유니버스 있으면: 대상=지역별 세대수 TOP-N 유니버스. 세대수·전세가율·갭은 유니버스,
    #     가격은 '오늘 3개월 스윕에 최근 거래 있으면 그 신선가, 없으면 유니버스 대표가'.
    #     → 조용한 대단지도 절대 안 빠지고, 최근 거래 단지는 최신가 반영.
    #   유니버스 없으면(수집 전): 기존 로직(구별 거래빈도 상위 후보 → 세대수 조회)으로 폴백.
    uni_cap = uni if with_cap else None

    cap_cands = []
    if with_cap and not uni_cap:
        bygu = {}
        for d in agg.values():
            bygu.setdefault(d["gu"], []).append(d)
        for lst in bygu.values():
            lst.sort(key=lambda d: (d["freq"], d["recent"]), reverse=True)
            cap_cands.extend(lst[:cap_cand])

    # 단지정보 보강(세대수·시공사) — hot 랭킹 + (폴백 시)시총 후보 합집합 1회 조회
    pairs = {(d["gu"], d["apt"]) for d in ranked}
    if with_cap and not uni_cap:
        pairs |= {(d["gu"], d["apt"]) for d in cap_cands}
    info = {}
    try:
        info = _apt_info_map(list(pairs))
    except Exception as e:
        print(f"[realestate] 단지정보 보강 생략: {e}")

    # 시총 리더 출력(독립 dict) — ranked의 _rows 제거 전에 먼저 만든다.
    cap_leaders = []
    if with_cap and uni_cap:
        # 오늘 스윕(agg) 정규화 인덱스 — 유니버스 단지에 최신가/㎡가/면적/행 매칭
        agg_norm = {(gu, _norm_apt(apt)): v for (gu, apt), v in agg.items()}
        for d in uni_cap["flat"]:
            units = d.get("units")
            if not units:
                continue
            a = agg_norm.get((d["gu"], _norm_apt(d["apt"])))
            price = (a.get("price") if a else None) or d.get("price")
            if not price:
                continue
            rs = (a.get("_rows") if a else None) or []
            p59 = (_recent_price_in_band(rs, 49.0, 63.0) if rs else None) or d.get("p59")
            p84 = (_recent_price_in_band(rs, 74.0, 90.0) if rs else None) or d.get("p84")
            cap_manwon = price * units
            area = d.get("area")
            cap_leaders.append({
                "apt": d["apt"], "gu": d["gu"], "sd": d.get("sd"),
                "units": units, "builder": d.get("builder"),
                "price": price, "price_eok": _fmt_eok(price),
                "area": f"{area}㎡" if area else "",
                "freq": d.get("freq"), "cap_manwon": cap_manwon,
                "cap_eok": round(cap_manwon / 1e4), "cap_fmt": _fmt_cap(cap_manwon),
                "p59_eok": _fmt_eok(p59) if p59 else None,
                "p84_eok": _fmt_eok(p84) if p84 else None,
                "dong": d.get("dong") or "",
                "addr": (d["gu"] + " " + (d.get("dong") or "")).strip(),
                "jr": d.get("jr"), "gap_eok": d.get("gap"),   # 전세가율·갭은 유니버스에서
                "fresh": bool(a),                              # 최근3개월 거래 있음(최신가)
            })
        cap_leaders.sort(key=lambda c: c["cap_manwon"], reverse=True)
    elif with_cap:
        for d in cap_cands:
            inf = info.get((d["gu"], d["apt"]), {})
            units = inf.get("units")
            if not units:
                continue
            rs = d.get("_rows") or []
            cap_manwon = d["price"] * units
            p59 = _recent_price_in_band(rs, 49.0, 63.0)
            p84 = _recent_price_in_band(rs, 74.0, 90.0)
            dong = Counter(r["dong"] for r in rs if r.get("dong")).most_common(1)
            dnm = dong[0][0] if dong else ""
            cap_leaders.append({
                "apt": d["apt"], "gu": d["gu"], "sd": d["sd"],
                "units": units, "builder": inf.get("builder"),
                "price": d["price"], "price_eok": d["price_eok"], "area": d["area"],
                "freq": d["freq"], "cap_manwon": cap_manwon,
                "cap_eok": round(cap_manwon / 1e4), "cap_fmt": _fmt_cap(cap_manwon),
                "p59_eok": _fmt_eok(p59) if p59 else None,
                "p84_eok": _fmt_eok(p84) if p84 else None,
                "dong": dnm, "addr": (d["gu"] + " " + dnm).strip(),
            })
        # 구별 시총 top cap_per_gu(작은 구도 노출 보장) ∪ 전체 시총 top cap_overall
        bygu2 = {}
        for c in cap_leaders:
            bygu2.setdefault(c["gu"], []).append(c)
        pergu = []
        for lst in bygu2.values():
            lst.sort(key=lambda c: c["cap_manwon"], reverse=True)
            pergu.extend(lst[:cap_per_gu])
        overall = sorted(cap_leaders, key=lambda c: c["cap_manwon"],
                         reverse=True)[:cap_overall]
        seen, union = set(), []
        for c in sorted(pergu + overall, key=lambda c: c["cap_manwon"], reverse=True):
            k = (c["gu"], c["apt"])
            if k in seen:
                continue
            seen.add(k)
            union.append(c)
        cap_leaders = union

    # 작년말(전년 12월) 대비 시총(=매매가) 상승률 — 면적정규화 평단가(ppa) 기준.
    #   전년 12월 RTMS 한 달치만 추가 스윕 → 단지별 dec_ppa, 현재 rec_ppa와 비교.
    #   세대수 불변이라 시총 상승률 = 평단가 상승률. 두 시점 모두 거래된 단지만(가짜 없음).
    gain_leaders = []
    if with_gain:
        def _baseline_for(ym):
            """단일월 ㎡당가 중위 기준선(ym) — 캐시 적중 시 스윕 생략."""
            b = _load_dec_baseline(ym)
            if b is not None:
                return b
            b = {}
            for nm, cds in SIGUNGU_CODES.items():
                br = []
                for code in cds:
                    br += _fetch(key, code, ym, "매매", stats)
                if exclude_direct:
                    br = [r for r in br if not r["direct"]]
                per_b = {}
                for r in br:
                    per_b.setdefault(r["apt"], []).append(r)
                for apt, rs2 in per_b.items():
                    ppas = [r["ppa"] for r in rs2 if r.get("ppa")]
                    if len(ppas) >= 2:           # 표본 부족 단지 제외(노이즈)
                        b[(nm, apt)] = (statistics.median(ppas), len(ppas))
            _save_dec_baseline(ym, b)
            return b

        dec_ym = f"{asof.year - 1}12"            # YTD 기준(작년 12월)
        my, mm = asof.year, asof.month - 3        # 모멘텀 기준(3개월 전 그 달)
        while mm <= 0:
            mm += 12
            my -= 1
        mom_ym = f"{my}{mm:02d}"
        dec = _baseline_for(dec_ym)
        mom_base = _baseline_for(mom_ym)

        gpool = {}
        for k, d in agg.items():
            rec_ppa = d.get("rec_ppa")
            if not rec_ppa:
                continue
            yoy = mom = None
            dd = dec.get(k)
            if dd and dd[0]:
                v = (rec_ppa / dd[0] - 1) * 100
                if 0 < v <= 100:                  # 하락·이상치(데이터오류) 제외
                    yoy = round(v, 1)
            mb = mom_base.get(k)
            if mb and mb[0]:
                v = (rec_ppa / mb[0] - 1) * 100
                if -60 <= v <= 60:                # 3개월 변동 이상치 제외(±60%)
                    mom = round(v, 1)
            if yoy is None and mom is None:
                continue
            inf = info.get(k, {})
            units = inf.get("units")
            rs = d.get("_rows") or []
            p84 = _recent_price_in_band(rs, 74.0, 90.0)
            dong = Counter(r["dong"] for r in rs if r.get("dong")).most_common(1)
            dnm = dong[0][0] if dong else ""
            cap_manwon = d["price"] * units if units else None
            gpool[k] = {
                "apt": d["apt"], "gu": d["gu"], "sd": d["sd"],
                "yoy": yoy, "mom": mom, "units": units,
                "builder": inf.get("builder"),
                "price": d["price"], "price_eok": d["price_eok"], "area": d["area"],
                "freq": d["freq"],
                "cap_eok": round(cap_manwon / 1e4) if cap_manwon else None,
                "cap_fmt": _fmt_cap(cap_manwon) if cap_manwon else None,
                "p84_eok": _fmt_eok(p84) if p84 else None,
                "dong": dnm, "addr": (d["gu"] + " " + dnm).strip(),
            }
        top_y = sorted((g for g in gpool.values() if g["yoy"] is not None),
                       key=lambda c: c["yoy"], reverse=True)[:gain_top]
        top_m = sorted((g for g in gpool.values() if g["mom"] is not None),
                       key=lambda c: c["mom"], reverse=True)[:gain_top]
        seen = set()
        for g in top_y + top_m:                   # yoy상위 ∪ mom상위(중복 제거)
            kk = (g["gu"], g["apt"])
            if kk not in seen:
                seen.add(kk)
                gain_leaders.append(g)

    # 전세가율·갭(P1) — 표시 대상 단지가 속한 '구'만 전세 스윕(콜 최소화).
    #   전세가율 = 단지 전세 ㎡당가 중위 ÷ 매매 ㎡당가 중위(rec_ppa).
    #   갭 = (매매 ㎡당 − 전세 ㎡당) × 대표면적 → 억. 표본<2·이상치(30~95% 밖)는 None.
    #   전세 권한 없음/실패는 통째 생략(가짜 없음). 엔진/스키마 무변경 — 새 dict 필드만.
    jr_map = {}
    try:
        show_gus = {d["gu"] for d in ranked}
        if with_cap and not uni_cap:      # 유니버스 cap은 전세가율을 유니버스에서 이미 확보
            show_gus |= {c["gu"] for c in cap_leaders}
        if with_gain:
            show_gus |= {g["gu"] for g in gain_leaders}
        jeon = {}
        for gu in show_gus:
            for code in SIGUNGU_CODES.get(gu, []):
                for ym in yms:
                    for r in _fetch(key, code, ym, "전월세", stats):
                        if exclude_direct and r["direct"]:
                            continue
                        jeon.setdefault((gu, r["apt"]), []).append(r["ppa"])
        for (gu, apt), ppas in jeon.items():
            if len(ppas) < 2:
                continue
            a = agg.get((gu, apt))
            rec_ppa = a.get("rec_ppa") if a else None
            if not rec_ppa:
                continue
            jeon_ppa = statistics.median(ppas)
            jr = jeon_ppa / rec_ppa * 100
            if jr < 30 or jr > 95:        # 월세혼입·데이터오류 등 이상치 제외
                continue
            area_num = a.get("area_num") or 0
            gap_manwon = (rec_ppa - jeon_ppa) * area_num
            jr_map[(gu, apt)] = {
                "jr": round(jr),
                "gap_eok": round(gap_manwon / 1e4, 1) if area_num else None,
            }
    except Exception as e:
        print(f"[realestate] 전세가율·갭 생략: {e}")

    def _apply_jr(d):
        info_jr = jr_map.get((d["gu"], d["apt"]))
        d["jr"] = info_jr["jr"] if info_jr else None
        d["gap_eok"] = info_jr["gap_eok"] if info_jr else None

    for d in ranked:
        _apply_jr(d)
    if with_cap and not uni_cap:          # 유니버스 cap은 jr/gap을 유니버스에서 이미 채움
        for c in cap_leaders:
            _apply_jr(c)
    if with_gain:
        for g in gain_leaders:
            _apply_jr(g)

    # hot 랭킹 보강(세대수·면적별가·소재지) — 여기서 _rows 제거
    for d in ranked:
        rs = d.pop("_rows", []) or []
        d.pop("_rec", None)
        a0 = d.pop("area_num", None) or 0
        # 가격 추이 스파크라인(P2): 대표면적대 거래의 ㎡당가를 거래 시간순으로.
        #   평형 혼합 노이즈를 줄이려 대표면적 ±12% 밴드만(표본<4면 전체 폴백) · 최근 16건.
        seq = sorted(rs, key=lambda r: r["date"])
        band = [r for r in seq if a0 and abs(r["area"] - a0) <= a0 * 0.12]
        if len(band) < 4:
            band = seq
        d["spark"] = [round(r["ppa"]) for r in band][-16:]
        d["p59"] = _recent_price_in_band(rs, 49.0, 63.0)
        d["p84"] = _recent_price_in_band(rs, 74.0, 90.0)
        d["p59_eok"] = _fmt_eok(d["p59"]) if d["p59"] else None
        d["p84_eok"] = _fmt_eok(d["p84"]) if d["p84"] else None
        dong = Counter(r["dong"] for r in rs if r.get("dong")).most_common(1)
        d["dong"] = dong[0][0] if dong else ""
        d["addr"] = (d["gu"] + " " + d["dong"]).strip()
        inf = info.get((d["gu"], d["apt"]), {})
        d["units"] = inf.get("units")
        d["builder"] = inf.get("builder")
    if with_search:
        try:
            si = _datalab_interest([d["apt"] for d in ranked])
            for d in ranked:
                d["search"] = si.get(d["apt"])
        except Exception as e:
            print(f"[realestate] 검색관심도 생략: {e}")
    if with_cap and with_gain:
        return ranked, cap_leaders, gain_leaders
    return (ranked, cap_leaders) if with_cap else ranked
