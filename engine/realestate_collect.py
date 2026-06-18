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


# ── 인증키 ──────────────────────────────────────────────────────
def _get_key():
    for k in ("MOLIT_API_KEY", "PUBLIC_DATA_API_KEY", "DATA_GO_KR_KEY"):
        v = os.environ.get(k)
        if v:
            return v
    try:
        import streamlit as st
        for k in ("MOLIT_API_KEY", "PUBLIC_DATA_API_KEY", "DATA_GO_KR_KEY"):
            if k in st.secrets:
                return st.secrets[k]
    except Exception:
        pass
    return None


def _api():
    from PublicDataReader import TransactionPrice
    key = _get_key()
    if not key:
        raise RuntimeError("공공데이터포털 서비스키가 없어요 (MOLIT_API_KEY).")
    return TransactionPrice(key)


# ── 실거래 조회 + 정규화 ────────────────────────────────────────
def _to_int(x):
    try:
        return int(str(x).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _fetch(api, code, ym, trade_type):
    """단일 시군구·월 조회 → 표준 레코드 리스트. 실패 시 []."""
    try:
        df = api.get_data(property_type="아파트", trade_type=trade_type,
                          sigungu_code=code, year_month=ym)
    except Exception:
        return []
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
    api = _api()
    asof = asof or date.today()
    yms = _months_back(asof, 2)        # 당월 + 직전월

    w_now0 = asof - timedelta(days=WINDOW_DAYS - 1)
    w_prev0 = asof - timedelta(days=2 * WINDOW_DAYS - 1)
    jr_from = asof - timedelta(days=JR_DAYS - 1)

    result = {}
    for name, codes in SIGUNGU_CODES.items():
        sales, jeonse = [], []
        for code in codes:
            for ym in yms:
                sales += _fetch(api, code, ym, "매매")
                jeonse += _fetch(api, code, ym, "전월세")
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
    api = _api()
    asof = asof or date.today()
    yms = _months_back(asof, months)
    recent0 = asof - timedelta(days=WINDOW_DAYS - 1)
    prev_weeks = max((months * 30) / WINDOW_DAYS - 1, 1)

    items = []
    for name, codes in SIGUNGU_CODES.items():
        rows = []
        for code in codes:
            for ym in yms:
                rows += _fetch(api, code, ym, "매매")
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
