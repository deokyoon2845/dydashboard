"""부동산 데이터 수집 — 국토부 아파트 실거래가(매매·전세) 기반.

PublicDataReader.TransactionPrice로 수도권 시군구별 아파트 매매/전세 실거래를 받아
  · 지도용 지역 지표: 거래량(v)·거래량 전주비(vc)·매매 주간변화(mm)·전세 주간변화(js)·전세가율(jr)
  · 특이거래: 신고가/신저가·급등/급락 (직거래=증여추정 기본 제외)
를 만든다.

self-contained(별도 DB 누적 불필요):
  - 지역 지표: 당월+직전월 2개월을 받아 '최근 N일 vs 그 전 N일'로 주간 비교를 계산.
  - 특이거래: 최근 ANOM_MONTHS개월 윈도우 내 단지·면적별 최고/최저가·직전거래 대비로 판정.
  ※ 실거래는 계약일 기준이라 최근일은 신고지연으로 표본이 적다(주간 수치는 변동 큼).
    표본이 MIN_N 미만이면 등락은 0(보합)으로 처리한다. 더 정확한 신고가 판정은
    추후 Supabase 이력 누적으로 보강(현재는 윈도우 기반 근사).

키: 공공데이터포털 서비스키. 환경변수/secrets 에서 다음 순서로 찾는다.
    MOLIT_API_KEY → PUBLIC_DATA_API_KEY → DATA_GO_KR_KEY
    (PublicDataReader는 'Decoding(일반 인증키)'를 받는다.)

진단(중요): 수집 전에 diagnose()로 단 1회 시험 호출을 던져
    '키 없음 / 키 미승인·무효 / 네트워크·IP 차단 / 호출 한도 / 정상' 을 구분한다.
    예전엔 _fetch가 모든 예외를 삼켜서, 키가 틀려도 빈 결과가 '성공'처럼 저장됐다.
    이제는 치명 오류(키/차단)는 즉시 예외로 띄우고, 전수 0건이면 저장하지 않는다.

주의: data.go.kr 오픈API는 해외 IP에서도 호출되지만, Streamlit Cloud에서 막히면
      키/운영계정 트래픽 한도(개발계정 ~10,000콜/일)를 점검할 것.
      수집 1회 호출 수 ≈ 지역지표 60코드×2개월×2유형(매매·전세)=240,
      특이거래 60코드×ANOM_MONTHS(매매)= 약 360콜(6개월 기준). 캐시·버튼 수집 권장.
"""

import os
import statistics
from datetime import date, timedelta

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

# 지도 지역명(_GEO의 'n') ↔ 시도구분
_SEOUL = {n for n in SIGUNGU_CODES if n.endswith("구")}

# 파라미터
WINDOW_DAYS = 7        # 주간 비교 창(최근 N일 vs 그 전 N일)
JR_DAYS = 60           # 전세가율 산정 창(표본 확보용으로 더 길게)
MIN_N = 3              # 등락 계산 최소 표본
ANOM_MONTHS = 6        # 특이거래 판정 윈도우(개월)
JUMP_PCT = 7.0         # 급등/급락 임계(직전 거래 대비 %)
VOL_SURGE = 2.0        # 거래량 급증 배수(최근주 vs 윈도우 주평균)

_DIAG_CODE = "11680"   # 진단용 시험 호출 시군구(강남구 — 거래가 늘 있는 편)


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


def _api():
    from PublicDataReader import TransactionPrice
    key = _get_key()
    if not key:
        raise RuntimeError(
            "공공데이터포털 서비스키가 없어요. Streamlit Secrets(또는 GitHub Actions Secret)에 "
            "MOLIT_API_KEY(또는 PUBLIC_DATA_API_KEY/DATA_GO_KR_KEY)를 추가하세요. "
            "값은 공공데이터포털의 'Decoding(일반 인증키)'을 넣으세요.")
    return TransactionPrice(key)


# ── 오류 분류 / 단일 호출 진단 ──────────────────────────────────
def _classify_exc(exc):
    """수집 중 발생한 예외를 NETWORK / KEY_INVALID / RATE_LIMIT / API_ERROR 로 분류."""
    name = type(exc).__name__.upper()
    txt = str(exc).upper()
    net_names = ("CONNECTIONERROR", "CONNECTTIMEOUT", "READTIMEOUT", "TIMEOUT",
                 "SSLERROR", "CHUNKEDENCODINGERROR", "PROXYERROR", "MAXRETRYERROR")
    if any(n in name for n in net_names):
        return "NETWORK"
    if any(h in txt for h in ("TIMED OUT", "MAX RETRIES", "CONNECTION ABORTED",
                              "FAILED TO ESTABLISH", "NEWCONNECTIONERROR", "SSL")):
        return "NETWORK"
    key_hints = ("SERVICE KEY", "SERVICEKEY", "NOT_REGISTERED", "NOT REGISTERED",
                 "REGISTERED ERROR", "UNREGISTERED", "등록되지", "활용신청", "미등록",
                 "INVALID", "ACCESS DENIED", "ACCESS_DENIED", "NO_OPENAPI_SERVICE",
                 "HTTP_ERROR", "권한", "허용되지", "DENIED")
    if any(h in txt for h in key_hints):
        return "KEY_INVALID"
    if any(h in txt for h in ("LIMITED", "요청제한", "트래픽", "EXCEEDS", "LIMIT_EXCEED",
                              "LIMITNUMBER", "한도")):
        return "RATE_LIMIT"
    return "API_ERROR"


def diagnose(asof=None, test_code=_DIAG_CODE):
    """수집 전 단 1회 시험 호출로 연결 상태 점검.

    반환: (status, message)
      status ∈ {"OK","OK_EMPTY","NO_KEY","NO_LIB","NETWORK","KEY_INVALID","RATE_LIMIT","API_ERROR"}
      OK / OK_EMPTY 는 '키·네트워크 정상'(수집 진행 가능), 나머지는 치명 오류.
    """
    key = _get_key()
    if not key:
        return ("NO_KEY",
                "data.go.kr 서비스키가 없어요. Streamlit Secrets에 "
                "MOLIT_API_KEY(또는 PUBLIC_DATA_API_KEY/DATA_GO_KR_KEY)를 추가하세요. "
                "값은 공공데이터포털의 'Decoding(일반 인증키)'을 넣으세요.")
    try:
        from PublicDataReader import TransactionPrice
    except Exception as e:
        return ("NO_LIB",
                f"PublicDataReader import 실패: {e} — requirements.txt에 PublicDataReader가 "
                "있는지, 재배포(Manage app → Reboot)가 됐는지 확인하세요.")

    api = TransactionPrice(key)
    asof = asof or date.today()
    # 당월 → 비면 직전월 순으로 시험(_months_back은 과거→현재라 역순으로 당월 먼저)
    for ym in reversed(_months_back(asof, 2)):
        try:
            df = api.get_data(property_type="아파트", trade_type="매매",
                              sigungu_code=test_code, year_month=ym)
        except Exception as e:
            kind = _classify_exc(e)
            if kind == "NETWORK":
                return ("NETWORK",
                        f"data.go.kr 연결 실패(네트워크/IP 차단 가능). 잠시 후 재시도하거나 "
                        f"GitHub Actions(서버측) 수집을 사용하세요. 원문: {e}")
            if kind == "KEY_INVALID":
                return ("KEY_INVALID",
                        "키가 미등록/무효예요. data.go.kr에서 '국토교통부 아파트 매매/전월세 "
                        "실거래가 상세 자료' 활용신청 승인 여부와, 키 형식(Decoding 일반 인증키)을 "
                        f"확인하세요. 원문: {e}")
            if kind == "RATE_LIMIT":
                return ("RATE_LIMIT", f"호출 한도 초과. 잠시 후 재시도하세요. 원문: {e}")
            return ("API_ERROR", f"API 오류: {e}")
        if df is not None and len(df) > 0:
            return ("OK", f"정상 — 강남구 {ym} 매매 {len(df)}건 확인. 수집을 진행할 수 있어요.")
    return ("OK_EMPTY",
            "호출 자체는 정상인데 최근 2개월 강남구 표본이 0건이에요(월 초·신고지연 가능). "
            "키/네트워크는 문제 없어 보입니다. 그대로 수집을 시도해도 됩니다.")


def _preflight(asof=None):
    """diagnose 결과가 치명 오류면 RuntimeError 로 즉시 중단."""
    status, msg = diagnose(asof)
    if status not in ("OK", "OK_EMPTY"):
        raise RuntimeError(msg)


# ── 실거래 조회 + 정규화 ────────────────────────────────────────
def _to_int(x):
    try:
        return int(str(x).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _fetch(api, code, ym, trade_type, stats=None):
    """단일 시군구·월 조회 → 표준 레코드 리스트.

    예외 처리 변경: 키/권한 오류는 더 이상 삼키지 않고 즉시 예외로 올린다(전수 실패 확정).
    네트워크 일시오류·해당 월 데이터 없음은 [] 로 건너뛰되 stats에 기록한다."""
    try:
        df = api.get_data(property_type="아파트", trade_type=trade_type,
                          sigungu_code=code, year_month=ym)
    except Exception as e:
        kind = _classify_exc(e)
        if stats is not None:
            stats["fail"] = stats.get("fail", 0) + 1
            stats["last_err"] = str(e)
        if kind == "KEY_INVALID":
            # 키 문제는 모든 코드에서 동일하게 실패 → 600콜 돌릴 필요 없이 즉시 중단
            raise RuntimeError(
                "실거래 키가 미등록/무효예요 (data.go.kr 활용신청 승인·키 형식 확인). "
                f"원문: {e}")
        return []   # NETWORK/RATE_LIMIT/일시 오류·해당 월 0건 → 건너뜀
    if stats is not None:
        stats["ok"] = stats.get("ok", 0) + 1
    if df is None or len(df) == 0:
        return []
    out = []
    for r in df.to_dict("records"):
        if str(r.get("해제여부", "")).strip().upper() == "O":   # 취소건 제외
            continue
        try:
            y = int(r.get("계약년도")); m = int(r.get("계약월")); d = int(r.get("계약일"))
            dt = date(y, m, d)
        except (ValueError, TypeError):
            continue
        area = None
        try:
            area = float(r.get("전용면적"))
        except (ValueError, TypeError):
            pass
        if trade_type == "매매":
            price = _to_int(r.get("거래금액"))
        else:  # 전월세: 전세만(월세 0)
            if _to_int(r.get("월세금액")) not in (0, None):
                continue
            price = _to_int(r.get("보증금액"))
        if not price or not area or area <= 0:
            continue
        out.append({
            "date": dt, "price": price, "area": area,
            "ppa": price / area,                       # 만원/㎡ (구성효과 완화)
            "apt": str(r.get("단지명", "")).strip(),
            "dong": str(r.get("법정동", "")).strip(),
            "trade": str(r.get("거래유형", "")).strip(),  # 중개거래/직거래/''
            "direct": "직" in str(r.get("거래유형", "")),
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


# ── 지역 지표 (지도) ────────────────────────────────────────────
def collect_region_metrics(asof=None, exclude_direct=True):
    """지역명 -> {'mm','js','v','vc','jr'}. 실패 시 예외(뷰어에서 샘플 폴백)."""
    asof = asof or date.today()
    _preflight(asof)                   # 키/네트워크 치명 오류면 여기서 즉시 중단
    api = _api()
    yms = _months_back(asof, 2)        # 당월 + 직전월
    stats = {"ok": 0, "fail": 0, "rows": 0, "last_err": ""}

    w_now0 = asof - timedelta(days=WINDOW_DAYS - 1)
    w_prev0 = asof - timedelta(days=2 * WINDOW_DAYS - 1)
    jr_from = asof - timedelta(days=JR_DAYS - 1)

    result = {}
    for name, codes in SIGUNGU_CODES.items():
        sales, jeonse = [], []
        for code in codes:
            for ym in yms:
                sales += _fetch(api, code, ym, "매매", stats)
                jeonse += _fetch(api, code, ym, "전월세", stats)
        if exclude_direct:
            sales = [r for r in sales if not r["direct"]]

        def win(rows, a, b):
            return [r for r in rows if a <= r["date"] <= b]

        s_now = win(sales, w_now0, asof)
        s_prev = win(sales, w_prev0, w_now0 - timedelta(days=1))
        j_now = win(jeonse, w_now0, asof)
        j_prev = win(jeonse, w_prev0, w_now0 - timedelta(days=1))

        # 거래량 + 전주비
        v = len(s_now)
        vc = round((v / len(s_prev) - 1) * 100) if s_prev else 0

        # 매매·전세 주간 변화(중위 단가, 표본 부족 시 보합)
        def chg(now, prev):
            if len(now) < MIN_N or len(prev) < MIN_N:
                return 0.0
            a, b = _median_ppa(now), _median_ppa(prev)
            return round((a / b - 1) * 100, 2) if (a and b) else 0.0

        mm = chg(s_now, s_prev)
        js = chg(j_now, j_prev)

        # 전세가율(최근 JR_DAYS 중위 단가 비율)
        s_jr = _median_ppa(win(sales, jr_from, asof))
        j_jr = _median_ppa(win(jeonse, jr_from, asof))
        jr = round(j_jr / s_jr * 100, 1) if (s_jr and j_jr) else None

        result[name] = {"mm": mm, "js": js, "v": v, "vc": vc, "jr": jr}

    # 전수 0건이면 저장 금지(예전엔 빈 결과가 '성공'으로 둔갑) — 실패로 띄운다.
    if stats["rows"] == 0:
        hint = (f" 최근 오류: {stats['last_err']}" if stats["last_err"]
                else " (호출은 됐지만 데이터가 0건 — 차단/한도/표본부족 가능).")
        raise RuntimeError("실거래를 한 건도 받지 못했어요." + hint)
    return result


# ── 특이거래 ────────────────────────────────────────────────────
_BG = {"신고가": ("#FCEBEB", "#A32D2D"), "급등": ("#FCEBEB", "#A32D2D"),
       "신저가": ("#E6F1FB", "#0C447C"), "급락": ("#E6F1FB", "#0C447C"),
       "거래량 급증": ("#FAEEDA", "#854F0B"), "거래량 급감": ("#F1EFE8", "#444441")}


def _fmt_eok(manwon):
    return f"{manwon/10000:.1f}억"


def collect_anomalies(asof=None, exclude_direct=True, months=ANOM_MONTHS, limit=40):
    """특이거래 리스트. 뷰어 fetch_anomalies와 동일한 튜플 형식으로 반환.
       (유형, 배경, 글자색, 단지, 지역, 면적, 가격, 변동, 거래유형, 제외여부)"""
    asof = asof or date.today()
    _preflight(asof)                   # 키/네트워크 치명 오류면 즉시 중단
    api = _api()
    yms = _months_back(asof, months)
    recent0 = asof - timedelta(days=WINDOW_DAYS - 1)
    prev_weeks = max((months * 30) / WINDOW_DAYS - 1, 1)
    stats = {"ok": 0, "fail": 0, "rows": 0, "last_err": ""}

    items = []
    for name, codes in SIGUNGU_CODES.items():
        rows = []
        for code in codes:
            for ym in yms:
                rows += _fetch(api, code, ym, "매매", stats)
        if not rows:
            continue

        # 단지+전용면적(반올림) 그룹
        groups = {}
        for r in rows:
            key = (r["apt"], round(r["area"]))
            groups.setdefault(key, []).append(r)

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
                # 신고가 / 신저가 (윈도우 내 최고/최저, 표본 2건 이상)
                if len(grp) >= 2 and r["price"] >= hi:
                    items.append(("신고가", *_BG["신고가"], *base, "신고", r["trade"] or "-", r["direct"]))
                elif len(grp) >= 2 and r["price"] <= lo:
                    items.append(("신저가", *_BG["신저가"], *base, "신저", r["trade"] or "-", r["direct"]))
                # 급등/급락 (직전 거래 대비)
                idx = grp.index(r)
                if idx > 0:
                    prev_p = grp[idx - 1]["price"]
                    if prev_p:
                        dpct = (r["price"] / prev_p - 1) * 100
                        if dpct >= JUMP_PCT:
                            items.append(("급등", *_BG["급등"], *base, f"+{dpct:.1f}%", r["trade"] or "-", r["direct"]))
                        elif dpct <= -JUMP_PCT:
                            items.append(("급락", *_BG["급락"], *base, f"{dpct:.1f}%", r["trade"] or "-", r["direct"]))

        # 거래량 급증(단지 단위): 최근주 거래수 vs 윈도우 주평균
        apt_recent, apt_total = {}, {}
        for r in rows:
            apt_total[r["apt"]] = apt_total.get(r["apt"], 0) + 1
            if r["date"] >= recent0:
                apt_recent[r["apt"]] = apt_recent.get(r["apt"], 0) + 1
        for apt, rc in apt_recent.items():
            avg_wk = apt_total[apt] / prev_weeks
            if avg_wk > 0 and rc >= 3 and rc >= VOL_SURGE * avg_wk:
                items.append(("거래량 급증", *_BG["거래량 급증"], apt, name, "전체",
                              f"{rc}건/주", f"+{round((rc/avg_wk-1)*100)}%", "-", False))

    # 데이터 자체를 한 건도 못 받았으면 실패로 띄운다(빈 결과 ≠ 정상 0건).
    if stats["rows"] == 0:
        hint = (f" 최근 오류: {stats['last_err']}" if stats["last_err"]
                else " (호출은 됐지만 데이터가 0건 — 차단/한도/표본부족 가능).")
        raise RuntimeError("특이거래 판정용 실거래를 한 건도 받지 못했어요." + hint)

    # 정렬: 변동 크기·유형 우선, 상위 limit
    def _mag(it):
        chg = it[7]
        try:
            return abs(float(chg.replace("%", "").replace("+", "").replace("건/주", "")))
        except ValueError:
            return 999
    items.sort(key=_mag, reverse=True)
    # 중복 제거(단지+유형)
    seen, dedup = set(), []
    for it in items:
        k = (it[0], it[3], it[5])
        if k in seen:
            continue
        seen.add(k); dedup.append(it)
        if len(dedup) >= limit:
            break
    return dedup
