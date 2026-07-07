"""부동산 '실거래' 탭 — 월간·주간·오늘 시장 밴드 · 지역 급지 보드 · 주목 단지.

국토부 실거래(직거래 기본 제외) 스냅샷을 읽어 시장 방향 요약(주간/오늘),
평당가 10급지 동적 보드(티어 시총 TOP20 + 신고가·괴리 알림), 주목단지 카드를 그린다.
급지 보드 미니지도는 realestate_geo의 _GEO 도형을 재사용한다.
(_render_cap_gainers/_render_cap_leaders는 시총 서브탭 삭제로 현재 미호출 잔존.)
"""

import streamlit as st
import streamlit.components.v1 as components

from modules.ui import foot_row
from modules.realestate_geo import _GEO, _LOCAL_GEO
from modules.realestate_common import (_load_re_snapshot, _load_recent_re_snapshots,
                                        _resolved_metrics, _naver_n)


# (유형,배경,글자색,단지,지역,면적,가격,변동,거래유형,제외,거래일ISO,세대수,빈도,신호강도%)
_SAMPLE_ANOMALIES = [
    ("신고가", "#FCEBEB", "#A32D2D", "래미안원베일리", "서초구", "84㎡", "58.0억", "+3.2%", "중개", False, "2026-06-20", 2990, 18, 3.2),
    ("신고가", "#FCEBEB", "#A32D2D", "힐스테이트판교엘포레", "성남시", "84㎡", "24.5억", "+2.6%", "중개", False, "2026-06-19", 1185, 14, 2.6),
    ("거래량 급증", "#FAEEDA", "#854F0B", "파크리오", "송파구", "전체", "12건/4주", "+148%", "-", False, "2026-06-20", 6864, 40, 148.0),
    ("급등", "#FCEBEB", "#A32D2D", "광교중흥S클래스", "수원시", "84㎡", "17.8억", "+8.1%", "중개", False, "2026-06-18", 2231, 16, 8.1),
    ("신저가", "#E6F1FB", "#0C447C", "상계주공7", "노원구", "59㎡", "6.1억", "-4.0%", "중개", False, "2026-06-19", 2634, 22, 4.0),
    ("급락", "#E6F1FB", "#0C447C", "은마", "강남구", "84㎡", "26.0억", "-7.5%", "직거래", True, "2026-06-17", 4424, 20, 7.5),
]


def fetch_anomalies():
    """특이거래 리스트. 세션 → DB 스냅샷 → 샘플."""
    a = st.session_state.get("re_anoms")
    if a:
        return a
    snap = _load_re_snapshot()
    if snap and snap.get("anomalies"):
        return snap["anomalies"]
    return _SAMPLE_ANOMALIES


# ── 주목 단지(최근 거래 활발·상승 · 국토부 실거래) ────────────────────────
_SAMPLE_HOT = [
    {"apt": "파크리오", "gu": "송파구", "sd": "seoul", "addr": "송파구 잠실동",
     "units": 6864, "builder": "대우건설", "recent": 14, "prev": 6, "vol_chg": 133, "vol_mult": 4.7,
     "chg": 2.1, "freq": 40, "p59_eok": "18.4억", "p84_eok": "24.8억",
     "jr": 54, "gap_eok": 11.4, "spark": [2620,2635,2628,2650,2662,2671,2688]},
    {"apt": "헬리오시티", "gu": "송파구", "sd": "seoul", "addr": "송파구 가락동",
     "units": 9510, "builder": "현대건설", "recent": 12, "prev": 7, "vol_chg": 71, "vol_mult": 3.4,
     "chg": 1.6, "freq": 51, "p59_eok": "17.6억", "p84_eok": "23.5억",
     "jr": 57, "gap_eok": 10.1, "spark": [2470,2485,2478,2492,2505,2511,2503]},
    {"apt": "잠실엘스", "gu": "송파구", "sd": "seoul", "addr": "송파구 잠실동",
     "units": 5678, "builder": "삼성물산", "recent": 9, "prev": 5, "vol_chg": 80, "vol_mult": 3.6,
     "chg": 2.4, "freq": 33, "p59_eok": "19.5억", "p84_eok": "27.0억",
     "jr": 58, "gap_eok": 11.3, "spark": [2833,2857,2845,2869,2893,2917,2940]},
    {"apt": "래미안원베일리", "gu": "서초구", "sd": "seoul", "addr": "서초구 반포동",
     "units": 2990, "builder": "삼성물산", "recent": 7, "prev": 3, "vol_chg": 133, "vol_mult": 4.7,
     "chg": 3.2, "freq": 18, "p59_eok": None, "p84_eok": "58.0억",
     "jr": 49, "gap_eok": 29.6, "spark": [6900,6980,6940,7010,7120]},
    {"apt": "고덕그라시움", "gu": "강동구", "sd": "seoul", "addr": "강동구 고덕동",
     "units": 4932, "builder": "대우건설", "recent": 8, "prev": 6, "vol_chg": 33, "vol_mult": 2.7,
     "chg": 0.9, "freq": 29, "p59_eok": "13.4억", "p84_eok": "17.2억",
     "jr": 62, "gap_eok": 6.5, "spark": [2040,2055,2048,2061,2058]},
    {"apt": "광교중흥S클래스", "gu": "수원시", "sd": "gg", "addr": "수원시 하동",
     "units": 2231, "builder": "중흥토건", "recent": 6, "prev": 4, "vol_chg": 50, "vol_mult": 3.0,
     "chg": 1.4, "freq": 16, "p59_eok": "13.2억", "p84_eok": "17.8억",
     "jr": 66, "gap_eok": 6.1, "spark": [1760,1772,1768,1781,1795]},
]


def _synth_sample_deals(h, days=90, n=18):
    """샘플 주목단지용 건별 거래 합성 — spark(㎡당가 추세)를 따라 59·84㎡ 거래를
    최근 days일에 분산 배치. 엔진 deals(실데이터)가 오기 전에도 카드 대형 차트가
    샘플 모드에서 그려지게 한다. 반환 [{d,p,a}]."""
    import math
    from datetime import date as _date, timedelta as _td
    spark = [v for v in (h.get("spark") or []) if isinstance(v, (int, float))]
    if len(spark) < 2:
        return []

    def _eok_to_manwon(s):
        try:
            return float(str(s).replace("억", "")) * 1e4
        except (TypeError, ValueError):
            return None

    p59 = _eok_to_manwon(h.get("p59_eok"))
    p84 = _eok_to_manwon(h.get("p84_eok"))
    if p59 is None and p84 is None:
        return []
    today = _date.today()
    last = spark[-1] or 1
    out = []
    for i in range(n):
        f = i / (n - 1)
        idx = f * (len(spark) - 1)
        j = int(idx)
        t = idx - j
        v = (spark[j] if j >= len(spark) - 1
             else spark[j] * (1 - t) + spark[j + 1] * t)
        wob = math.sin(i * 2.3) * 0.012
        if p84 is not None and (i % 3 != 0 or p59 is None):
            base, a = p84, 84.9
        else:
            base, a = p59, 59.9
        dt = today - _td(days=round((1 - f) * days))
        out.append({"d": dt.isoformat(),
                    "p": round(base * (v / last) * (1 + wob)), "a": a})
    return out


for _h in _SAMPLE_HOT:
    _h.setdefault("deals", _synth_sample_deals(_h))


def fetch_hot_complexes():
    """주목 단지 리스트. 세션/DB metrics의 '_hot' → 샘플 폴백."""
    m = _resolved_metrics()
    if isinstance(m, dict) and m.get("_hot"):
        return m["_hot"]
    return _SAMPLE_HOT


# ── 구별 시가총액 상위 단지 (시총=최근 실거래가×세대수 · 국토부+공동주택) ──────
#   엔진(collect_hot_complexes with_cap)이 metrics['_caplead']에 실어 보냄(스키마 무변경).
#   엔트리: {apt,gu,sd,units,builder,price_eok,cap_eok,cap_fmt,p59_eok,p84_eok,dong,addr,...}
#   (apt,gu,units,cap_eok,price_eok,builder,dong)
_CAPLEAD_ROWS = [
    ("래미안원베일리", "서초구", 2990, 173420, "58.0억", "삼성물산", "반포동"),
    ("헬리오시티", "송파구", 9510, 161670, "17.0억", "현대건설", "가락동"),
    ("반포자이", "서초구", 3410, 143220, "42.0억", "GS건설", "반포동"),
    ("파크리오", "송파구", 6864, 123552, "18.0억", "대우건설", "잠실동"),
    ("은마", "강남구", 4424, 115024, "26.0억", None, "대치동"),
    ("잠실엘스", "송파구", 5678, 110721, "19.5억", "삼성물산", "잠실동"),
    ("래미안퍼스티지", "서초구", 2444, 109980, "45.0억", "삼성물산", "반포동"),
    ("리센츠", "송파구", 5563, 105697, "19.0억", None, "잠실동"),
    ("개포자이프레지던스", "강남구", 3375, 104625, "31.0억", "GS건설", "개포동"),
    ("아크로리버파크", "서초구", 1612, 88660, "55.0억", "대림산업", "반포동"),
    ("고덕그라시움", "강동구", 4932, 84830, "17.2억", "대우건설", "고덕동"),
    ("마포래미안푸르지오", "마포구", 3885, 73815, "19.0억", "삼성물산", "아현동"),
    ("트리지움", "송파구", 3696, 68376, "18.5억", None, "잠실동"),
    ("고덕아르테온", "강동구", 4057, 68158, "16.8억", "현대건설", "상일동"),
    ("래미안블레스티지", "강남구", 1957, 58710, "30.0억", "삼성물산", "개포동"),
    ("고덕래미안힐스테이트", "강동구", 3658, 58528, "16.0억", "삼성물산", "고덕동"),
    ("래미안첼리투스", "용산구", 1140, 51300, "45.0억", "삼성물산", "이촌동"),
    ("래미안대치팰리스", "강남구", 1278, 48564, "38.0억", "삼성물산", "대치동"),
    ("디에이치아너힐즈", "강남구", 1320, 44880, "34.0억", "현대건설", "개포동"),
    ("e편한세상옥수파크힐스", "성동구", 1976, 41496, "21.0억", "대림산업", "옥수동"),
    ("광교중흥에스클래스", "수원시", 2231, 39712, "17.8억", "중흥토건", "하동"),
    ("용산센트럴파크", "용산구", 1140, 37620, "33.0억", None, "한강로"),
    ("마포프레스티지자이", "마포구", 1694, 35574, "21.0억", "GS건설", "염리동"),
    ("래미안옥수리버젠", "성동구", 1511, 33242, "22.0억", "삼성물산", "옥수동"),
    ("반포래미안아이파크", "서초구", 829, 33160, "40.0억", "삼성물산", "잠원동"),
    ("래미안솔베뉴", "강동구", 1900, 27550, "14.5억", "삼성물산", "명일동"),
    ("고덕센트럴아이파크", "강동구", 1745, 27048, "15.5억", "현대산업", "상일동"),
    ("광교자연앤힐스테이트", "수원시", 1764, 26460, "15.0억", "현대건설", "이의동"),
    ("영통아이파크캐슬", "수원시", 2666, 25327, "9.5억", "현대산업", "망포동"),
    ("신촌그랑자이", "마포구", 1248, 24960, "20.0억", "GS건설", "대흥동"),
    ("상계주공7", "노원구", 2634, 18438, "7.0억", None, "상계동"),
    ("광교호반베르디움", "수원시", 1330, 17290, "13.0억", "호반건설", "이의동"),
    ("광교더샵", "수원시", 686, 10976, "16.0억", "포스코", "원천동"),
    ("미아뉴타운두산위브", "강북구", 1370, 10960, "8.0억", "두산", "미아동"),
    ("창동주공19", "도봉구", 1764, 10584, "6.0억", None, "창동"),
    ("불암현대", "노원구", 825, 5363, "6.5억", None, "중계동"),
]


_SAMPLE_CAPLEAD = [
    {"apt": a, "gu": g, "units": u, "cap_eok": c, "price_eok": p,
     "builder": b, "dong": d}
    for (a, g, u, c, p, b, d) in _CAPLEAD_ROWS
]


def fetch_cap_leaders():
    """구별 시가총액 상위 단지. 세션/DB metrics의 '_caplead' → 샘플 폴백."""
    m = _resolved_metrics()
    if isinstance(m, dict) and m.get("_caplead"):
        return m["_caplead"]
    return _SAMPLE_CAPLEAD


# ── 작년말 대비 시총(=매매가) 상승률 상위 단지 (전년 12월 vs 현재 평단가) ──────
#   엔진(collect_hot_complexes with_gain)이 metrics['_capgain']에 실어 보냄.
#   (apt, gu, units, yoy%, price_eok, cap_fmt, dong)
_CAPGAIN_ROWS = [
    ("잠실엘스", "송파구", 5678, 18.5, "19.5억", "11.1조", "잠실동"),
    ("헬리오시티", "송파구", 9510, 16.2, "17.0억", "16.2조", "가락동"),
    ("래미안원베일리", "서초구", 2990, 14.8, "58.0억", "17.3조", "반포동"),
    ("e편한세상옥수파크힐스", "성동구", 1976, 13.9, "21.0억", "4.1조", "옥수동"),
    ("광장현대파크빌", "광진구", 1170, 12.6, "20.5억", "2.4조", "광장동"),
    ("마포래미안푸르지오", "마포구", 3885, 11.4, "19.0억", "7.4조", "아현동"),
    ("고덕그라시움", "강동구", 4932, 10.2, "17.2억", "8.5조", "고덕동"),
    ("래미안대치팰리스", "강남구", 1278, 9.5, "38.0억", "4.9조", "대치동"),
    ("광교중흥에스클래스", "수원시", 2231, 8.1, "17.8억", "4.0조", "하동"),
    ("파크리오", "송파구", 6864, 7.3, "18.0억", "12.4조", "잠실동"),
]


_SAMPLE_CAPGAIN = [
    {"apt": a, "gu": g, "units": u, "yoy": y, "mom": round(y * 0.28, 1),
     "price_eok": p, "cap_fmt": cf, "dong": d}
    for (a, g, u, y, p, cf, d) in _CAPGAIN_ROWS
]


def fetch_cap_gainers():
    """작년말 대비 시총 상승률 상위 단지. 세션/DB metrics의 '_capgain' → 샘플 폴백."""
    m = _resolved_metrics()
    if isinstance(m, dict) and m.get("_capgain"):
        return m["_capgain"]
    return _SAMPLE_CAPGAIN


_GANGNAM3 = {"강남구", "서초구", "송파구"}


def _chg_abs(chg):
    """'+8.1%'·'-4.0%'·'+148%'·'×2.5'(거래량 배수) → 절대 크기(정렬·강조용)."""
    try:
        s = (str(chg).replace("%", "").replace("+", "")
             .replace("평소", "").replace("×", "").strip())
        return abs(float(s))
    except Exception:
        return 0.0


def _hot_spark_svg(vals, w=68, h=22):
    """단지 가격 추이 미니 스파크라인(P2) — ㎡당가 시퀀스 → polyline SVG.
    추세 방향색(상승 red·하락 blue·보합 sage). 점<2면 빈 문자열."""
    vals = [v for v in (vals or []) if isinstance(v, (int, float))]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        x = round(1 + i / (n - 1) * (w - 2), 1)
        y = round(h - 1 - (v - lo) / rng * (h - 3), 1)
        pts.append(f"{x},{y}")
    col = ("#B65F5A" if vals[-1] > vals[0]
           else "#5A7CA0" if vals[-1] < vals[0] else "#7E9A83")
    lx, ly = pts[-1].split(",")
    return (f'<span class="re-hc-spk"><span class="lab">추이</span>'
            f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<polyline fill="none" stroke="{col}" stroke-width="1.6" '
            f'stroke-linecap="round" stroke-linejoin="round" '
            f'points="{" ".join(pts)}"/>'
            f'<circle cx="{lx}" cy="{ly}" r="1.9" fill="{col}"/></svg></span>')


_DEAL_COL = {"g59": "#5A7CA0", "g84": "#B65F5A", "etc": "#c9cabf"}


_DEAL_LAB = {"g59": "59㎡", "g84": "84㎡", "etc": "기타"}


def _deal_eok(v):
    """만원 → '26.7억' 표기(정수면 소수점 생략)."""
    s = f"{v / 1e4:.1f}"
    return (s[:-2] if s.endswith(".0") else s) + "억"


def _hot_deal_chart_svg(deals, w=440, h=190):
    """주목 단지 대형 실거래 차트 — 점 1개=실거래 1건(가로 시점 × 세로 거래가),
    59㎡ 파랑·84㎡ 빨강·기타 회색, 평형별 연결선, 마지막 거래 금액 라벨,
    축 눈금(월/일·억)·축 제목 포함 SVG. 반환 (svg, 존재 평형그룹 리스트) — 유효점<2면 ("", [])."""
    from datetime import date as _date, timedelta as _td
    pts = []
    for r in (deals or []):
        if not isinstance(r, dict):
            continue
        try:
            y, m, dd = str(r.get("d", ""))[:10].split("-")
            dt = _date(int(y), int(m), int(dd))
            p = float(r.get("p"))
            a = float(r.get("a") or 0)
        except (ValueError, TypeError):
            continue
        if p <= 0:
            continue
        g = ("g59" if 49.0 <= a < 63.0
             else "g84" if 74.0 <= a <= 90.0 else "etc")
        pts.append((dt, p, g))
    if len(pts) < 2:
        return "", []
    pts.sort(key=lambda t: t[0])
    d0, d1 = pts[0][0], pts[-1][0]
    span = max((d1 - d0).days, 1)
    pmin = min(p for _, p, _ in pts)
    pmax = max(p for _, p, _ in pts)
    pad = (pmax - pmin) * 0.10 or max(pmax * 0.02, 1)
    ylo, yhi = pmin - pad, pmax + pad
    L, R, T, B = 50, 14, 14, 36                   # 플롯 여백(좌=금액눈금, 하=시점축)

    def _px(dt):
        return L + (dt - d0).days / span * (w - L - R)

    def _py(p):
        return T + (yhi - p) / (yhi - ylo) * (h - T - B)

    # y 그리드 4줄 + 금액 눈금(억)
    body = ""
    for i in range(4):
        v = ylo + (yhi - ylo) * (i + 0.5) / 4
        yy = _py(v)
        body += (f'<line x1="{L}" y1="{yy:.1f}" x2="{w - R}" y2="{yy:.1f}" '
                 f'stroke="#ECEDE6" stroke-width="1"/>'
                 f'<text x="{L - 5}" y="{yy + 3:.1f}" font-size="9.5" '
                 f'fill="#A9AB9F" text-anchor="end">{_deal_eok(v)}</text>')
    # x축선 + 시점 눈금(스팬 45일↑면 월 경계 '5월', 아니면 4등분 'M.D')
    ax_y = h - B + 2
    body += f'<line x1="{L}" y1="{ax_y}" x2="{w - R}" y2="{ax_y}" stroke="#DDDED6"/>'
    ticks = []
    if span >= 45:
        y_, m_ = d0.year, d0.month + 1
        if m_ > 12:
            y_, m_ = y_ + 1, 1
        cur = _date(y_, m_, 1)
        while cur <= d1:
            ticks.append((cur, f"{cur.month}월"))
            y_, m_ = cur.year, cur.month + 1
            if m_ > 12:
                y_, m_ = y_ + 1, 1
            cur = _date(y_, m_, 1)
    if len(ticks) < 2:
        ticks = [(d0 + _td(days=round(span * i / 3)),) for i in range(4)]
        ticks = [(dt, f"{dt.month}.{dt.day}") for (dt,) in ticks]
    for dt, lab in ticks:
        body += (f'<text x="{_px(dt):.1f}" y="{ax_y + 12}" font-size="9.5" '
                 f'fill="#A9AB9F" text-anchor="middle">{lab}</text>')
    # 축 제목
    body += (f'<text x="{(L + w - R) / 2:.0f}" y="{h - 4}" font-size="9" '
             f'fill="#C2C3B9" text-anchor="middle">시점(거래일)</text>'
             f'<text x="10" y="{(T + h - B) / 2:.0f}" font-size="9" fill="#C2C3B9" '
             f'text-anchor="middle" transform="rotate(-90 10 {(T + h - B) / 2:.0f})">'
             f'거래가(억)</text>')
    # 평형별 연결선(59·84) + 점 + 마지막 거래 금액 라벨
    groups = [g for g in ("g59", "g84", "etc")
              if any(p[2] == g for p in pts)]
    for g in groups:
        gp = [(x, p) for x, p, gg in pts if gg == g]
        col = _DEAL_COL[g]
        if g != "etc" and len(gp) >= 2:
            poly = " ".join(f"{_px(dt):.1f},{_py(p):.1f}" for dt, p in gp)
            body += (f'<polyline fill="none" stroke="{col}" stroke-width="1.5" '
                     f'stroke-opacity=".55" stroke-linecap="round" '
                     f'stroke-linejoin="round" points="{poly}"/>')
        for k, (dt, p) in enumerate(gp):
            last = (k == len(gp) - 1)
            body += (f'<circle cx="{_px(dt):.1f}" cy="{_py(p):.1f}" '
                     f'r="{3.8 if last and g != "etc" else 3.1}" '
                     f'fill="{col}" fill-opacity=".85"/>')
        if g != "etc":
            dt, p = gp[-1]
            tx = min(max(_px(dt), L + 22), w - 30)
            ty = _py(p) + (-8 if g == "g84" else 14)
            ty = min(max(ty, T + 8), h - B - 3)
            body += (f'<text x="{tx:.1f}" y="{ty:.1f}" font-size="10" '
                     f'font-weight="800" fill="{col}" text-anchor="middle">'
                     f'{_deal_eok(p)}</text>')
    svg = (f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
           f'font-family="Pretendard,-apple-system,sans-serif" '
           f'preserveAspectRatio="xMidYMid meet">{body}</svg>')
    return svg, groups


_WD_KR = ["월", "화", "수", "목", "금", "토", "일"]


def _anom_norm(rec):
    """특이거래 레코드를 15필드로 정규화(구 10~14필드 스냅샷 호환). 실패 시 None.
       (유형,배경,글자색,단지,지역,면적,가격,변동,거래유형,제외,거래일ISO|None,
        세대수|None, 빈도|None, 신호강도%|None, 평형별1년밴드|None)"""
    try:
        rec = list(rec)
    except TypeError:
        return None
    if len(rec) < 10:
        return None
    return (tuple(rec[:10])
            + (rec[10] if len(rec) >= 11 else None,)   # 거래일ISO
            + (rec[11] if len(rec) >= 12 else None,)    # 세대수
            + (rec[12] if len(rec) >= 13 else None,)    # 빈도(12개월 거래수)
            + (rec[13] if len(rec) >= 14 else None,)    # 신호강도%(sigstr)
            + (rec[14] if len(rec) >= 15 else None,))   # 평형별 1년 밴드(신고가)


def _anom_date(d):
    """'YYYY-MM-DD' → date. 실패 시 None."""
    from datetime import date as _date
    try:
        y, m, dd = str(d).split("-")[:3]
        return _date(int(y), int(m), int(dd))
    except Exception:
        return None


def _anom_daylabel(d):
    dt = _anom_date(d)
    return f"{dt.month:02d}.{dt.day:02d} ({_WD_KR[dt.weekday()]})" if dt else "날짜 미상"


_ANOM_PRESETS = {
    "느슨": {"freq": 5, "jump": 7.0, "margin": 0.3, "surge": 1.6, "days": 45},
    "표준": {"freq": 8, "jump": 10.0, "margin": 1.0, "surge": 2.0, "days": 30},
    "엄격": {"freq": 14, "jump": 13.0, "margin": 2.0, "surge": 3.0, "days": 21},
}


_CAPGAIN_HTML = r'''<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
:root{--bg:#FCFCFA;--card:#fff;--ink:#34352f;--muted:#9a9b92;--line:#ECEDE7;
 --sage2:#7E9A83;--up:#B65F5A;--upT:#FBEEED;--dn:#5A7CA0;--dnT:#EDF1F5;--sum:#F6F7F2;--kf:'Pretendard',-apple-system,sans-serif;}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--kf);font-size:14px;-webkit-font-smoothing:antialiased}
.box{padding:2px 1px 8px}
.note{font-size:11px;color:var(--muted);line-height:1.55;margin:11px 2px 0}
.flat{background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.fr{display:grid;grid-template-columns:26px 1fr auto;align-items:center;gap:11px;padding:11px 14px;border-bottom:1px solid var(--line)}
.fr:last-child{border-bottom:none}.fr:hover{background:var(--sum)}
.rank{font-size:15px;font-weight:800;color:var(--sage2);text-align:center}
.fr.top1 .rank{color:var(--up)}
.gu-badge{display:inline-block;font-size:10px;font-weight:800;color:var(--sage2);background:#EEF3EF;border-radius:5px;padding:1px 6px;margin-right:6px;vertical-align:middle}
.nm{font-size:13.5px;font-weight:700;color:var(--ink);line-height:1.25}
.nm small{display:block;font-size:11px;font-weight:600;color:var(--muted);margin-top:2px}
.yoy{text-align:right;white-space:nowrap}
.yoy b{font-size:17px;font-weight:800;letter-spacing:-.02em;border-radius:7px;padding:2px 8px}
.yoy b.up{color:var(--up);background:var(--upT)} .yoy b.dn{color:var(--dn);background:var(--dnT)}
.yoy small{display:block;font-size:10.5px;font-weight:600;color:var(--muted);margin-top:3px}
.empty{font-size:12px;color:var(--muted);padding:18px 6px}
.nv{display:inline-flex;align-items:center;justify-content:center;width:15px;height:15px;flex:none;border-radius:4px;background:#03C75A;color:#fff;font-size:10px;font-weight:900;text-decoration:none;margin-left:5px;vertical-align:1px;line-height:1}.nv:hover{filter:brightness(.92)}
.mapln:hover{background:#EEF3EF;border-color:#A7BBA9}
</style></head><body><div class="box">
  <div class="flat" id="flat"></div>
  <div class="note">__NOTE__</div>
</div>
<script>
const GAIN=__GAIN__;
function mapLink(c){var q=encodeURIComponent(((c.dong||c.gu||"")+" "+c.apt).trim());
 return '<a class="nv" href="https://search.naver.com/search.naver?query='+q+'" target="_blank" rel="noopener" onclick="event.stopPropagation()" title="네이버 검색에서 보기">N</a>';}
function flat(){
 if(!GAIN||!GAIN.length){document.getElementById("flat").innerHTML='<div class="empty">데이터가 아직 없어요. 매일 아침 자동 수집 후 표시됩니다.</div>';return;}
 document.getElementById("flat").innerHTML=GAIN.map(function(c,i){
  var meta=c.units?(c.units.toLocaleString()+'세대 · '+c.dong):c.dong;
  var sub='현재 '+(c.peok||'—')+(c.cap?' · 시총 '+c.cap:'');
  var pos=c.val>=0;
  return '<div class="fr'+(i===0?' top1':'')+'"><div class="rank">'+(i+1)+'</div>'
   +'<div class="nm"><span class="gu-badge">'+c.gu+'</span>'+c.apt+'<small>'+meta+'</small></div>'
   +'<div class="yoy"><b class="'+(pos?'up':'dn')+'">'+(pos?'+':'')+c.val.toFixed(1)+'%</b><small>'+sub+'</small>'+mapLink(c)+'</div></div>';}).join("");}
flat();
(function(){function f(){try{var h=Math.ceil(document.body.getBoundingClientRect().height)+2;var fe=window.frameElement;if(!fe)return;fe.style.height=h+"px";fe.setAttribute("height",h);var p=fe.parentElement;for(var i=0;i<3&&p&&p!==document.body;i++){if(p.style&&p.style.height&&p.style.height!=="auto")p.style.height="auto";p=p.parentElement;}}catch(e){}}window.addEventListener("load",f);setTimeout(f,150);setTimeout(f,600);setTimeout(f,1500);window.addEventListener("resize",f);try{new ResizeObserver(f).observe(document.body);}catch(e){}})();
</script></body></html>'''


# (시총 서브탭 삭제로 아래 _render_cap_gainers/_render_cap_leaders는 현재 미호출 —
#  fetch_cap_leaders는 지역 보드가 계속 사용하므로 데이터 파이프라인은 유지, 재사용 대비 보존)
def _render_cap_gainers(metric="ytd", top=10):
    """시총(=평단가) 상승률 보드 — metric='ytd'(작년말 대비) 또는 'mom'(3개월 모멘텀)."""
    import json as _json
    from datetime import date
    fld = "yoy" if metric == "ytd" else "mom"
    rows = []
    for c in (fetch_cap_gainers() or []):
        if not isinstance(c, dict):
            continue
        v = c.get(fld)
        gu = c.get("gu")
        apt = c.get("apt")
        if v is None or not gu or not apt:
            continue
        rows.append({"apt": apt, "gu": gu, "val": float(v),
                     "units": c.get("units"), "peok": c.get("price_eok") or "",
                     "cap": c.get("cap_fmt") or "", "dong": c.get("dong") or ""})
    if not rows:
        st.caption("데이터가 아직 없어요. 매일 아침 자동 수집 후 표시됩니다.")
        return
    rows.sort(key=lambda r: r["val"], reverse=True)
    rows = rows[:top]
    is_sample = fetch_cap_gainers() is _SAMPLE_CAPGAIN
    src = ("국토부 실거래 평단가" if not is_sample
           else "샘플 · 아침 수집 후 실데이터로 교체")
    if metric == "ytd":
        base = f"{date.today().year - 1}.12"
        note = (f'※ <b>작년말({base}) 대비</b> 면적정규화 평단가(㎡당가) 상승률. '
                f'세대수 불변이라 시총 상승률과 동일. 작년말·현재 모두 거래가 있는 단지만'
                f'(표본 부족·하락 단지 제외) · 매일 아침 갱신.')
        cap = "작년말 대비 평단가 상승률 · 시총 상승률과 동일(세대수 불변)"
    else:
        note = ('※ <b>3개월 전 대비</b> 평단가 모멘텀(최근 vs 3개월 전 ㎡당가). '
                'YTD가 누적 상승폭이라면 모멘텀은 <b>최근 가속/감속</b> 신호 · '
                '3개월 전·현재 모두 거래가 있는 단지만 · 매일 아침 갱신.')
        cap = "최근 3개월 모멘텀(3개월 전 대비 평단가) · 가속/감속 선행신호"
    height = 70 + len(rows) * 74 + 80
    html = (_CAPGAIN_HTML
            .replace("__GAIN__", _json.dumps(rows, ensure_ascii=False))
            .replace("__NOTE__", note))
    components.html(html, height=height, scrolling=False)
    st.markdown(foot_row(src, cap), unsafe_allow_html=True)


_CAPLEAD_HTML = r'''<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
:root{--bg:#FCFCFA;--card:#fff;--ink:#34352f;--muted:#9a9b92;--line:#ECEDE7;--line2:#DEDED7;
 --sage2:#7E9A83;--up:#B65F5A;--sum:#F6F7F2;--kf:'Pretendard',-apple-system,sans-serif;}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--kf);font-size:14px;-webkit-font-smoothing:antialiased}
.box{padding:2px 1px 8px}
.sec{font-size:11.5px;font-weight:700;letter-spacing:.04em;color:var(--muted);text-transform:uppercase;margin:0 2px 11px;display:flex;align-items:center;gap:9px}
.sec::after{content:"";flex:1;height:1px;background:var(--line)}
.sec.mt{margin-top:22px}
.note{font-size:11px;color:var(--muted);line-height:1.55;margin:11px 2px 0}
.flat{background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.fr{display:grid;grid-template-columns:26px 1fr auto;align-items:center;gap:11px;padding:11px 14px;border-bottom:1px solid var(--line)}
.fr:last-child{border-bottom:none}.fr:hover{background:var(--sum)}
.rank{font-size:15px;font-weight:800;color:var(--sage2);text-align:center}
.fr.top1 .rank,.rkrow.top1 .rank{color:var(--up)}
.gu-badge{display:inline-block;font-size:10px;font-weight:800;color:var(--sage2);background:#EEF3EF;border-radius:5px;padding:1px 6px;margin-right:6px;vertical-align:middle}
.nm{font-size:13.5px;font-weight:700;color:var(--ink);line-height:1.25}
.nm small{display:block;font-size:11px;font-weight:600;color:var(--muted);margin-top:2px}
.cap{text-align:right;white-space:nowrap}
.cap b{font-size:16px;font-weight:800;letter-spacing:-.02em;color:var(--ink)}
.cap small{display:block;font-size:10.5px;font-weight:600;color:var(--muted);margin-top:2px}
.picker{display:flex;align-items:center;gap:9px;margin-bottom:13px;flex-wrap:wrap}
.picker label{font-size:12px;font-weight:800;color:var(--sage2)}
.picker select{font-family:var(--kf);font-size:13px;font-weight:700;color:var(--ink);padding:7px 11px;border:1px solid var(--line2);border-radius:9px;background:#fff}
.sum-line{font-size:11.5px;color:var(--muted);font-weight:600}.sum-line b{color:var(--ink);font-weight:800}
.rk{background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.rkrow{display:grid;grid-template-columns:30px 1fr auto;align-items:center;gap:12px;padding:13px 15px;border-bottom:1px solid var(--line)}
.rkrow:last-child{border-bottom:none}.rkrow:hover{background:var(--sum)}
.rkrow .rank{font-size:17px}.rkrow .nm{font-size:14px;font-weight:800}.rkrow .cap b{font-size:18px}
.jr-mini{display:flex;align-items:center;gap:8px;margin-top:6px}
.jr-mini .jg{flex:1;min-width:0;max-width:158px}
.jr-mini .jl{display:flex;justify-content:space-between;font-size:9.5px;font-weight:700;color:var(--muted);margin-bottom:3px}
.jr-mini .jl b{color:var(--sage2);font-weight:800}
.jr-mini .jb{height:6px;border-radius:3px;background:#EBECE6;overflow:hidden}
.jr-mini .jb i{display:block;height:100%;background:#A7BBA9}
.jr-mini .gp{font-size:10.5px;font-weight:700;color:#6f7068;white-space:nowrap}
.jr-mini .gp b{color:var(--ink);font-weight:800}
.empty{font-size:12px;color:var(--muted);padding:18px 6px}
.nv{display:inline-flex;align-items:center;justify-content:center;width:15px;height:15px;flex:none;border-radius:4px;background:#03C75A;color:#fff;font-size:10px;font-weight:900;text-decoration:none;margin-left:5px;vertical-align:1px;line-height:1}.nv:hover{filter:brightness(.92)}
.mapln:hover{background:#EEF3EF;border-color:#A7BBA9}
</style></head><body><div class="box">
  <div class="sec">수도권 시가총액 TOP 10</div>
  <div class="flat" id="flat"></div>
  <div class="sec mt">구별 · 그룹별로 보기</div>
  <div class="picker"><label>지역</label><select id="sel" onchange="fill()"></select>
    <span class="sum-line" id="sumline"></span></div>
  <div class="rk" id="rk"></div>
  <div class="note">※ <b>시가총액(추정)</b> = 최근 실거래가(최근 거래 없으면 최근 대표가) × 세대수. <b>주요 단지 유니버스</b>(지역별 세대수 상위 단지)를 대상으로 집계해 조용한 대단지도 빠지지 않아요. 강남3구·마용성 같은 그룹은 합산 재정렬 TOP10, 개별 구는 TOP5 · 매일 아침 갱신.</div>
</div>
<script>
const CAP=__CAP__;
const GROUPS={"강남3구":["강남구","서초구","송파구"],"마용성":["마포구","용산구","성동구"],"노도강":["노원구","도봉구","강북구"]};
function capFmt(e){return e>=10000?(e/10000).toFixed(1)+"조":Math.round(e).toLocaleString()+"억";}
function mapLink(c){var q=encodeURIComponent(((c.dong||c.gu||"")+" "+c.apt).trim());
 return '<a class="nv" href="https://search.naver.com/search.naver?query='+q+'" target="_blank" rel="noopener" onclick="event.stopPropagation()" title="네이버 검색에서 보기">N</a>';}
function jrHtml(c){if(c.jr==null)return"";var w=Math.min(Math.round(c.jr),100);
 var gp=(c.gap!=null)?'<span class="gp">갭 <b>'+c.gap+'억</b></span>':'';
 return '<div class="jr-mini"><div class="jg"><div class="jl"><span>전세가율</span><b>'+Math.round(c.jr)+'%</b></div><div class="jb"><i style="width:'+w+'%"></i></div></div>'+gp+'</div>';}
const byGu={};CAP.forEach(function(c){(byGu[c.gu]=byGu[c.gu]||[]).push(c);});
const GUS=Object.keys(byGu).sort(function(a,b){
 return Math.max.apply(null,byGu[b].map(function(c){return c.cap;}))-Math.max.apply(null,byGu[a].map(function(c){return c.cap;}));});
function rowsRK(list,limit){return list.slice(0,limit).map(function(c,i){
 var badge=c._grp?'<span class="gu-badge">'+c.gu+'</span>':'';
 var meta=c.units.toLocaleString()+'세대 · '+(c.b?c.b+' · ':'')+c.dong;
 return '<div class="rkrow'+(i===0?' top1':'')+'"><div class="rank">'+(i+1)+'</div>'
  +'<div class="nm">'+badge+c.apt+'<small>'+meta+'</small>'+jrHtml(c)+'</div>'
  +'<div class="cap"><b>'+capFmt(c.cap)+'</b><small>최근 '+(c.peok||'—')+'</small>'+mapLink(c)+'</div></div>';}).join("");}
function fill(){var v=document.getElementById("sel").value,list,limit,label;
 if(GROUPS[v]){list=[];GROUPS[v].forEach(function(g){(byGu[g]||[]).forEach(function(c){var x=Object.assign({},c);x._grp=1;list.push(x);});});
  list.sort(function(a,b){return b.cap-a.cap;});limit=10;
  var su=list.slice(0,limit).reduce(function(s,c){return s+c.cap;},0);
  label='<b>'+v+'</b> 합산 · '+GROUPS[v].join("·")+' · 표시 시총합 <b>'+(su/10000).toFixed(1)+'조</b>';}
 else{list=(byGu[v]||[]).slice().sort(function(a,b){return b.cap-a.cap;});limit=5;label='<b>'+v+'</b> 시총 TOP5';}
 document.getElementById("rk").innerHTML=list.length?rowsRK(list,limit):'<div class="empty">해당 지역 유니버스 단지가 없어요.</div>';
 document.getElementById("sumline").innerHTML=label;}
function flat(){var all=CAP.slice().sort(function(a,b){return b.cap-a.cap;}).slice(0,10);
 document.getElementById("flat").innerHTML=all.length?all.map(function(c,i){
  return '<div class="fr'+(i===0?' top1':'')+'"><div class="rank">'+(i+1)+'</div>'
   +'<div class="nm"><span class="gu-badge">'+c.gu+'</span>'+c.apt+'<small style="font-weight:600;color:var(--muted)">'+c.units.toLocaleString()+'세대 · '+c.dong+'</small>'+jrHtml(c)+'</div>'
   +'<div class="cap"><b>'+capFmt(c.cap)+'</b><small>최근 '+(c.peok||'—')+'</small>'+mapLink(c)+'</div></div>';}).join("")
  :'<div class="empty">시총 데이터가 아직 없어요. 매일 아침 자동 수집 후 표시됩니다.</div>';}
(function(){var sel=document.getElementById("sel");
 var h='<optgroup label="그룹">'+Object.keys(GROUPS).map(function(g){return '<option>'+g+'</option>';}).join("")+'</optgroup>';
 h+='<optgroup label="자치구·시">'+GUS.map(function(g){return '<option>'+g+'</option>';}).join("")+'</optgroup>';
 sel.innerHTML=h;sel.value=GROUPS["강남3구"]?"강남3구":(GUS[0]||"");flat();fill();})();
(function(){function f(){try{var h=Math.ceil(document.body.getBoundingClientRect().height)+2;var fe=window.frameElement;if(!fe)return;fe.style.height=h+"px";fe.setAttribute("height",h);var p=fe.parentElement;for(var i=0;i<3&&p&&p!==document.body;i++){if(p.style&&p.style.height&&p.style.height!=="auto")p.style.height="auto";p=p.parentElement;}}catch(e){}}window.addEventListener("load",f);setTimeout(f,150);setTimeout(f,600);setTimeout(f,1500);window.addEventListener("resize",f);try{new ResizeObserver(f).observe(document.body);}catch(e){}})();
</script></body></html>'''


def _render_cap_leaders():
    """구별·그룹별 시가총액 상위 단지 보드(수도권 TOP10 + 구/그룹 셀렉터)."""
    import json as _json
    rows = []
    for c in (fetch_cap_leaders() or []):
        if not isinstance(c, dict):
            continue
        cap = c.get("cap_eok")
        units = c.get("units")
        gu = c.get("gu")
        apt = c.get("apt")
        if not (cap and units and gu and apt):
            continue
        rows.append({"apt": apt, "gu": gu, "units": int(units),
                     "cap": int(cap), "peok": c.get("price_eok") or "",
                     "b": c.get("builder") or "", "dong": c.get("dong") or "",
                     "jr": c.get("jr"), "gap": c.get("gap_eok")})
    if not rows:
        st.caption("시총 데이터가 아직 없어요. 매일 아침 자동 수집 후 표시됩니다.")
        return
    n_gu = len(set(r["gu"] for r in rows))
    height = 110 + min(len(rows), 10) * 96 + 110 + 10 * 100 + 90
    html = _CAPLEAD_HTML.replace("__CAP__", _json.dumps(rows, ensure_ascii=False))
    components.html(html, height=height, scrolling=False)
    src = ("국토부 실거래 × 세대수" if fetch_cap_leaders() is not _SAMPLE_CAPLEAD
           else "샘플 · 아침 수집 후 실데이터로 교체")
    st.markdown(foot_row(
        src, f"시총=최근 실거래가(없으면 대표가)×세대수 · "
             f"주요 단지 유니버스 {n_gu}개 지역"), unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════
#  지역 보드('지역' 서브탭) — 평당가 10급지 동적 그루핑 + TOP20 행 알림
#  · 데이터: fetch_cap_leaders(유니버스 전 단지 · 엔진이 chg/last_deal/pavg 동봉).
#  · 리전(원자 단위): 서울 25개 자치구 + 경기 핵심(과천·분당·판교·위례·광교·광명·
#    동탄·평촌·수지·용인)·일산·다산·별내 + 인천 송도·청라. 동네 단위(판교·위례 등)는
#    법정동(dong) 매칭으로 시군구에서 분리. 미열거 지역(구성남·미사·덕양 등)은 '기타'.
#  · 티어 배정(동적): 리전 평당가 = 소속 단지 평당가(대표가÷대표면적×3.3058)의 중위.
#    경계 [9천/6천/5천/4천/3천만원] 고정 → 1~6급지. 대표가는 유니버스(월 리빌드)에서
#    오므로 배정은 사실상 월 단위로 갱신되고, 최근 거래 단지는 최신가가 반영된다.
#  · 최적화: 뷰어 파이썬이 리전→티어 배정·요약·시총 TOP20 컷까지 끝내고 iframe엔
#    타일 요약 + 티어당 20단지만 실음(유니버스 전체 JSON 미탑재).
# ════════════════════════════════════════════════════════════════
_TIER_BOUNDS = [12000, 10000, 8000, 6500, 5500,
                4500, 4000, 3500, 3000]              # 평당 만원 · 내림차순 경계


_TIER_META = [
    ("t1", "1급지", "강남3구 · 고정"),
    ("t2", "2급지", "평당 1.0억↑"),
    ("t3", "3급지", "8천만~1억"),
    ("t4", "4급지", "6.5~8천만"),
    ("t5", "5급지", "5.5~6.5천만"),
    ("t6", "6급지", "4.5~5.5천만"),
    ("t7", "7급지", "4~4.5천만"),
    ("t8", "8급지", "3.5~4천만"),
    ("t9", "9급지", "3~3.5천만"),
    ("t10", "10급지", "3천만 미만"),
    ("etc", "기타", "미분류 유니버스 지역"),
]


# ── 동네 단위 법정동 리스트 (시군구 → 리전 분리 재료) ──
_PANGYO_DONGS = {"판교동", "백현동", "삼평동", "운중동", "대장동"}


_BUNDANG_DONGS = {"분당동", "수내동", "정자동", "서현동", "이매동", "야탑동",
                  "금곡동", "구미동", "동원동", "석운동", "하산운동", "궁내동", "율동"}


_WIRYE_DONGS_SN = {"창곡동"}          # 위례(성남 수정구)


_WIRYE_DONGS_HN = {"학암동"}          # 위례(하남)


_GWANGGYO_DONGS = {"이의동", "원천동", "하동"}          # 광교(수원 — 용인 상현동은 수지로)


_SUJI_DONGS = {"풍덕천동", "죽전동", "동천동", "고기동", "신봉동", "성복동", "상현동"}


_DONGTAN_DONGS = {"반송동", "석우동", "능동",
                  "청계동", "영천동", "오산동", "목동", "산척동",
                  "장지동", "송동", "방교동", "신동", "중동"}


_MANAN_DONGS = {"안양동", "석수동", "박달동"}            # 안양 만안구(≠평촌)


_ILSAN_DONGS = {"장항동", "마두동", "백석동", "풍동", "식사동", "중산동", "정발산동",
                "산황동", "사리현동", "성석동", "설문동", "문봉동", "지영동",
                "일산동", "주엽동", "탄현동", "대화동", "덕이동", "가좌동",
                "구산동", "법곳동"}


_DASAN_DONGS = {"다산동", "도농동", "지금동"}            # 다산신도시(진건·지금)


_BYEOLNAE_DONGS = {"별내동"}


# 서울 안에서 소속 구 평균을 크게 웃돌아 별도 리전으로 분리 관리하는 동네들.
#   목동 신시가지 8~14단지는 법정동상 신정동이라 목동·신정동을 묶는다.
_SEOUL_DONG_SPLIT = {
    "영등포구": ({"여의도동"}, "여의도"),
    "양천구": ({"목동", "신정동"}, "목동"),
    "성동구": ({"성수동1가", "성수동2가"}, "성수"),
    "용산구": ({"이촌동"}, "이촌"),
    "송파구": ({"잠실동", "신천동"}, "잠실"),
}


def _region_of_cx(gu, dong):
    """(지역, 법정동) → 리전명. 열거 밖 지역·동 미상 애매 케이스는 None(→기타)."""
    if gu.endswith("구") and gu not in ("연수구", "인천서구"):
        sp = _SEOUL_DONG_SPLIT.get(gu)
        if sp and dong in sp[0]:
            return sp[1]                               # 여의도·목동·성수·이촌·잠실 분리
        return gu                                      # 서울 자치구는 구 자체가 리전
    if gu == "과천시":
        return "과천"
    if gu == "광명시":
        return "광명"
    if gu == "성남시":
        if dong in _PANGYO_DONGS:
            return "판교"
        if dong in _WIRYE_DONGS_SN:
            return "위례"
        if dong in _BUNDANG_DONGS:
            return "분당"
        return None                                    # 구성남 등
    if gu == "하남시":
        return "위례" if dong in _WIRYE_DONGS_HN else None   # 미사 등
    if gu == "용인시":
        if not dong:
            return None
        return "수지" if dong in _SUJI_DONGS else "용인"
    if gu == "수원시":
        return "광교" if dong in _GWANGGYO_DONGS else None
    if gu == "화성시":
        return "동탄" if dong in _DONGTAN_DONGS else None
    if gu == "안양시":
        return None if (not dong or dong in _MANAN_DONGS) else "평촌"
    if gu == "고양시":
        return "일산" if dong in _ILSAN_DONGS else None      # 덕양 등
    if gu == "남양주시":
        if dong in _DASAN_DONGS:
            return "다산"
        if dong in _BYEOLNAE_DONGS:
            return "별내"
        return None
    if gu == "연수구":
        return "송도" if dong == "송도동" else None
    if gu == "인천서구":
        return "청라" if dong == "청라동" else None
    return None


def _cx_pyeong(c):
    """caplead 엔트리 → 평당가(만원). 대표가(price 만원)÷대표면적(㎡)×3.3058. 실패 None."""
    try:
        area = float(str(c.get("area") or "").replace("㎡", "").strip())
        price = float(c.get("price") or 0)
        if area <= 0 or price <= 0:
            return None
        return price / area * 3.3058
    except Exception:
        return None


_REGION_BOARD_HTML = r'''<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
:root{--bg:#FCFCFA;--card:#fff;--ink:#34352f;--muted:#9a9b92;--line:#ECEDE7;--line2:#DEDED7;
 --sage:#A7BBA9;--sage2:#7E9A83;--up:#B65F5A;--dn:#5A7CA0;--sum:#F6F7F2;
 --kf:'Pretendard',-apple-system,sans-serif;}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--kf);font-size:14px;
 -webkit-font-smoothing:antialiased}
.box{padding:2px 1px 8px}
.up{color:var(--up)}.dn{color:var(--dn)}
.gt-wrap{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-bottom:9px}
.gt-col{display:flex;flex-direction:column;gap:9px}
#gtEtc{margin-bottom:12px}
@media(max-width:680px){.gt-wrap{grid-template-columns:1fr}}
.dt{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:12px 14px;margin-bottom:12px}
.dt-map svg{width:100%;height:auto;display:block}
.dt-info{margin-top:10px}
.dt-map path{fill:#EFF0EA;stroke:#fff;stroke-width:1.2}
.dt-map path.sh{fill:var(--sage)}
.dt-h{font-size:13px;font-weight:800}
.dt-h em{font-style:normal;font-size:10.5px;font-weight:700;color:var(--muted);margin-left:7px}
.dt-rgs{font-size:10.5px;font-weight:600;color:#6f7068;margin-top:5px;line-height:1.55}
.dt-rgs b{color:#5d6258}
.dt-top3{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}
.dt-top3 span{font-size:11px;font-weight:700;color:var(--ink);background:#F7F8F4;
 border:1px solid var(--line);border-radius:7px;padding:4px 9px;white-space:nowrap}
.dt-top3 span i{font-style:normal;color:var(--sage2);font-weight:800;margin-right:5px}
.dt-top3 span b{font-weight:800}
.dt-note{font-size:9.5px;color:#B7B8B0;font-weight:600;margin-top:7px}
.gt{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:11px 13px;
 cursor:pointer;transition:transform .14s,box-shadow .14s,border-color .14s}
.gt:hover{transform:translateY(-2px);box-shadow:0 6px 16px rgba(52,53,47,.08);border-color:var(--sage)}
.gt.on{border-color:var(--sage2);box-shadow:inset 0 0 0 1.5px var(--sage2)}
.gt-top{display:flex;align-items:baseline;justify-content:space-between;gap:6px}
.gt-nm{font-size:13px;font-weight:800;letter-spacing:-.01em}
.gt-rng{font-size:9px;font-weight:700;color:var(--muted);white-space:nowrap}
.gt-rg{font-size:9.5px;font-weight:600;color:#6f7068;margin-top:3px;line-height:1.45;
 display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:27px}
.gt-chg{font-size:16px;font-weight:800;letter-spacing:-.02em;margin-top:6px}
.gt-chg.fl{color:var(--muted);font-size:13px}
.gt-bar{display:flex;height:5px;border-radius:3px;overflow:hidden;background:#EFF0EA;margin-top:6px}
.gt-bar .u{background:var(--up)}.gt-bar .d{background:var(--dn)}
.gt-ud{font-size:9.5px;font-weight:700;color:var(--muted);margin-top:4px;display:flex;justify-content:space-between}
.cx-head{display:flex;align-items:baseline;justify-content:space-between;gap:8px;margin:4px 2px 8px;flex-wrap:wrap}
.cx-title{font-size:13px;font-weight:800}
.cx-title em{font-style:normal;font-size:11px;font-weight:600;color:var(--muted);margin-left:7px}
.cx-rgs{font-size:10.5px;font-weight:600;color:var(--muted);width:100%;margin-top:2px;line-height:1.5}
.cx-rgs b{color:#5d6258;font-weight:700}
.cx-cap{font-size:10.5px;color:var(--muted);font-weight:700;white-space:nowrap}
.cx{background:var(--card);border:1px solid var(--line);border-radius:13px;overflow:hidden}
.cx-row{display:grid;grid-template-columns:26px 1fr auto;align-items:flex-start;gap:11px;
 padding:11px 14px;border-bottom:1px solid var(--line)}
.cx-row:last-child{border-bottom:none}
.cx-row:hover{background:var(--sum)}
.rank{font-size:13.5px;font-weight:800;color:var(--sage2);text-align:center;margin-top:1px}
.cx-row.top1 .rank{color:var(--up)}
.rg-bdg{display:inline-block;font-size:9.5px;font-weight:800;color:var(--sage2);background:#EEF3EF;
 border-radius:5px;padding:1px 6px;margin-right:6px;vertical-align:1px}
.cx-nm{font-size:13px;font-weight:700;line-height:1.3;min-width:0}
.cx-nm .nv{display:inline-flex;align-items:center;justify-content:center;width:14px;height:14px;
 border-radius:4px;background:#03C75A;color:#fff;font-size:9.5px;font-weight:900;line-height:1;
 margin-left:5px;vertical-align:1px;text-decoration:none}
.cx-nm .nv:hover{filter:brightness(.92)}
.cx-nm small{display:block;font-size:10.5px;font-weight:600;color:var(--muted);margin-top:2px}
.pv{display:flex;flex-wrap:wrap;gap:5px;margin-top:7px}
.pv span{font-size:11px;font-weight:800;color:var(--ink);background:#F7F8F4;
 border:1px solid var(--line);border-radius:7px;padding:3px 8px;white-space:nowrap}
.pv span i{font-style:normal;font-weight:700;color:var(--muted);font-size:9.5px;margin-right:4px}
.pv span small{font-weight:600;color:#B7B8B0;font-size:9px;margin-left:3px}
.pv .none{color:#B7B8B0;background:#FAFAF7;font-weight:700}
.al{margin-top:8px;display:flex;flex-direction:column;gap:4px;border-top:1px dashed #EDEEE7;padding-top:8px}
.al-i{font-size:11px;font-weight:700;color:#5d6258;display:flex;gap:7px;align-items:baseline;flex-wrap:wrap}
.al-i .b{font-size:9.5px;font-weight:800;border-radius:5px;padding:1.5px 7px;white-space:nowrap}
.al-i .b.hi{background:var(--up);color:#fff}
.al-i .b.up{background:#FBEEED;color:var(--up);border:1px solid #EFD3D0}
.al-i .b.dn{background:#EAF0F7;color:var(--dn);border:1px solid #D3DEEC}
.al-i .dt{color:var(--muted);font-weight:600;font-size:10.5px}
.al-i b.p{font-weight:800;color:var(--ink)}
.al-more{font-size:10px;font-weight:700;color:var(--muted)}
.cx-r{text-align:right;white-space:nowrap}
.cx-chg b{font-size:13.5px;font-weight:800}
.cx-chg .stale{color:#B7B8B0;font-weight:800}
.cx-r small{display:block;font-size:9.5px;font-weight:700;color:var(--muted);margin-top:2px}
.empty{font-size:12px;color:var(--muted);padding:18px 14px}
@media(max-width:680px){.cx-row{grid-template-columns:22px 1fr auto;gap:8px;padding:10px 11px}}
</style></head><body><div class="box">
  <div class="gt-wrap"><div class="gt-col" id="gtColL"></div><div class="gt-col" id="gtColR"></div></div>
  <div id="gtEtc"></div>
  <div class="dt"><div class="dt-map" id="dtMap"></div>
    <div class="dt-info"><div class="dt-h" id="dtH"></div><div class="dt-rgs" id="dtRgs"></div>
      <div class="dt-top3" id="dtT3"></div>
      <div class="dt-note">지도 음영 = 시·군·구 단위 근사 · 인천 포함(송도=연수구·청라=서구)</div></div></div>
  <div class="cx-head"><span class="cx-title" id="cxTitle"></span>
    <span class="cx-cap">시총 TOP 20 · 평형 3개월 평균 · 🔺신고가·▲▼±5% 알림</span></div>
  <div class="cx" id="cxList"></div>
</div>
<script>
const G=__G__,GEO=__GEO__,TG=__TG__;
document.getElementById("dtMap").innerHTML=
 '<svg viewBox="-115 215 1210 865" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="\uae09\uc9c0 \uc9c0\uc5ed \uc9c0\ub3c4">'
 +GEO.map(function(s){return '<path data-n="'+s.n+'" d="'+s.d+'"/>';}).join("")+'</svg>';
let sel=null;
for(const g of G){if(g.n){sel=g.k;break;}}
const pct=c=>(c>=0?"+":"")+c.toFixed(1)+"%";
const pyf=p=>p>=10000?(p/10000).toFixed(1).replace(/\.0$/,"")+"억":Math.round(p/1000)/10+"천만";
function bar(g){const t=(g.up+g.dn+g.fl)||1;
 return '<div class="gt-bar"><span class="u" style="width:'+(g.up/t*100)+'%"></span>'
  +'<span class="d" style="width:'+(g.dn/t*100)+'%"></span></div>';}
function pvHTML(c){
 if(!c.pavg||!c.pavg.length)
  return '<div class="pv"><span class="none">\ucd5c\uadfc 3\uac1c\uc6d4 \uac70\ub798 \uc5c6\uc74c \u00b7 \ub300\ud45c\uac00 '+(c.p||"\u2014")+'</span></div>';
 return '<div class="pv">'+c.pavg.map(function(b){
  return '<span><i>'+b.area+'\u33a1</i>'+b.avg+'\uc5b5<small>'+b.n+'\uac74</small></span>';}).join("")+'</div>';}
function chgHTML(c){
 if(c.chg==null)return '<span class="cx-chg"><b class="stale">\u2014</b></span><small>\uac70\ub798 \ub738</small>';
 var cls=c.chg>=0?"up":"dn";
 return '<span class="cx-chg"><b class="'+cls+'">'+pct(c.chg)+'</b></span><small>30\uc77c\u6bd4</small>';}
function alHTML(c){
 if(!c.al||!c.al.length)return "";
 var items=c.al.slice(0,3).map(function(a){
  var bdg=a.t==="hi"
   ?'<span class="b hi">\ud83d\udd3a \uc2e0\uace0\uac00'+(a.v!=null?" +"+a.v+"%":"")+'</span>'
   :(a.t==="up"?'<span class="b up">\u25b2 \ud3c9\uade0+'+a.v+'%</span>'
               :'<span class="b dn">\u25bc \ud3c9\uade0'+a.v+'%</span>');
  return '<div class="al-i">'+bdg+'<span class="dt">'+a.d+'</span>'
   +'<span>'+a.area+'\u33a1</span><b class="p">'+a.p+'</b></div>';}).join("");
 var more=c.al.length>3?'<div class="al-more">+'+(c.al.length-3)+'\uac74 \ub354</div>':"";
 return '<div class="al">'+items+more+'</div>';}
function nv(c){var q=encodeURIComponent(((c.dong?c.gu+" "+c.dong:c.gu)+" "+c.apt).trim());
 return '<a class="nv" href="https://search.naver.com/search.naver?query='+q
  +'" target="_blank" rel="noopener" onclick="event.stopPropagation()">N</a>';}
function card(g){
 var chg=(g.chg==null)?'<div class="gt-chg fl">\u2014</div>'
  :'<div class="gt-chg '+(g.chg>=0?"up":"dn")+'">'+pct(g.chg)+'</div>';
 var rgs=g.regions.length?g.regions.map(function(r){return r.nm;}).join("\u00b7"):"\u2014";
 return '<div class="gt '+(g.k===sel?"on":"")+'" data-k="'+g.k+'">'
  +'<div class="gt-top"><span class="gt-nm">'+g.nm+'</span><span class="gt-rng">'+g.rng+'</span></div>'
  +'<div class="gt-rg" title="'+rgs+'">'+rgs+'</div>'+chg+bar(g)
  +'<div class="gt-ud"><span class="up">\u25b2'+g.up+'</span><span>'+g.n+'\ub2e8\uc9c0</span>'
  +'<span class="dn">\u25bc'+g.dn+'</span></div></div>';}
function draw(){
 var main=G.filter(function(x){return x.k!=="etc";});
 var etc=G.find(function(x){return x.k==="etc";});
 document.getElementById("gtColL").innerHTML=main.slice(0,5).map(card).join("");
 document.getElementById("gtColR").innerHTML=main.slice(5,10).map(card).join("");
 document.getElementById("gtEtc").innerHTML=etc?card(etc):"";
 document.querySelectorAll(".gt").forEach(function(el){el.onclick=function(){sel=el.dataset.k;draw();};});
 var g=G.find(function(x){return x.k===sel;});if(!g)return;
 // 상세 패널 — 미니지도 음영 + 구성 + TOP3
 var shade={};
 if(g.k!=="etc")g.regions.forEach(function(r){(TG[r.nm]||[r.nm]).forEach(function(n){shade[n]=1;});});
 document.querySelectorAll("#dtMap path").forEach(function(p){
  p.classList.toggle("sh",!!shade[p.dataset.n]);});
 document.getElementById("dtH").innerHTML=g.nm+'<em>'+g.rng
  +(g.cap?' \u00b7 \ud2f0\uc5b4 \uc2dc\ucd1d '+g.cap:'')+'</em>';
 document.getElementById("dtRgs").innerHTML=g.regions.length
  ?'\uad6c\uc131: '+g.regions.map(function(r){return '<b>'+r.nm+'</b> '+pyf(r.py);}).join(' \u00b7 ')
  :'\uad6c\uc131 \uc9c0\uc5ed \uc5c6\uc74c';
 document.getElementById("dtT3").innerHTML=g.rows.length
  ?g.rows.slice(0,3).map(function(c,i){
    return '<span><i>'+(i+1)+'</i>'+c.apt+' <b>'+(c.p?c.p+'\uc5b5':c.cap)+'</b></span>';}).join("")
  :'<span class="none">\ub2e8\uc9c0 \uc5c6\uc74c</span>';
 document.getElementById("cxTitle").innerHTML=g.nm+' \uc8fc\uc694 \ub2e8\uc9c0<em>'+g.rng
  +(g.cap?' \u00b7 \ud2f0\uc5b4 \uc2dc\ucd1d '+g.cap:'')+'</em>';
 document.getElementById("cxList").innerHTML=g.rows.length?g.rows.map(function(c,i){
  return '<div class="cx-row'+(i===0?" top1":"")+'"><div class="rank">'+(i+1)+'</div>'
   +'<div class="cx-nm"><span class="rg-bdg">'+c.rg+'</span>'+c.apt+nv(c)
   +'<small>'+c.gu+(c.dong?" "+c.dong:"")+' \u00b7 '+c.units.toLocaleString()+'\uc138\ub300'
   +(c.py?' \u00b7 \ud3c9\ub2f9 '+pyf(c.py):'')
   +' \u00b7 \uc2dc\ucd1d '+c.cap+'</small>'+pvHTML(c)+alHTML(c)+'</div>'
   +'<div class="cx-r">'+chgHTML(c)
   +(c.dd?'<small>\ucd5c\uadfc '+c.dd+'</small>':'')+'</div></div>';}).join("")
  :'<div class="empty">\uc774 \ud2f0\uc5b4\uc5d0 \ubc30\uc815\ub41c \ub2e8\uc9c0\uac00 \uc5c6\uc5b4\uc694.</div>';
 _fit();}
draw();
function _fit(){try{var h=Math.ceil(document.body.getBoundingClientRect().height)+2;
 var fe=window.frameElement;if(!fe)return;fe.style.height=h+"px";fe.setAttribute("height",h);
 var p=fe.parentElement;for(var i=0;i<3&&p&&p!==document.body;i++){
  if(p.style&&p.style.height&&p.style.height!=="auto")p.style.height="auto";p=p.parentElement;}}catch(e){}}
window.addEventListener("load",_fit);setTimeout(_fit,150);setTimeout(_fit,600);setTimeout(_fit,1500);
window.addEventListener("resize",_fit);try{new ResizeObserver(_fit).observe(document.body);}catch(e){}
</script></body></html>'''


def _eok_s(manwon):
    """만원 → '18.2억' (뷰어 알림용 간이 포맷)."""
    v = manwon / 1e4
    s = f"{v:.1f}".rstrip("0").rstrip(".")
    return f"{s}억"


def _hi_alert_index(days=30):
    """anomalies(엔진 신고가 스캔) → (gu, apt)별 최근 N일 신고가 목록(직거래 제외).
    지역 보드 TOP20 행 알림에 병합할 재료. [{'d':'MM.DD','area':㎡,'p':가격,'v':마진%}]"""
    from datetime import date as _date, timedelta as _td
    cut = _date.today() - _td(days=days)
    idx = {}
    for r in fetch_anomalies() or []:
        na = _anom_norm(r)
        if not na or na[0] != "신고가" or na[9]:       # 신고가만 · 직거래 제외
            continue
        dt = _anom_date(na[10])
        if not dt or dt < cut:
            continue
        idx.setdefault((na[4], na[3]), []).append({
            "d": f"{dt.month:02d}.{dt.day:02d}",
            "area": _area_int(na[5]),
            "p": na[6],
            "v": (round(na[13], 1) if isinstance(na[13], (int, float)) else None),
        })
    return idx


def _cx_alerts(c, hi_idx):
    """단지 알림 병합 — 신고가(hi_idx) 우선 + 평균 ±5% 괴리(caplead.alerts).
    같은 (일자, 평형)이 신고가로 이미 있으면 괴리 알림은 중복 제거. 날짜 내림차순."""
    als = []
    for h in hi_idx.get((c["gu"], c["apt"]), []):
        als.append({"d": h["d"], "t": "hi", "area": h["area"],
                    "p": h["p"], "v": h["v"]})
    seen = {(a["d"], a["area"]) for a in als}
    for a in (c.get("alerts") or []):
        d = str(a.get("d") or "")[5:10].replace("-", ".")
        area = a.get("area")
        if not d or (d, area) in seen:
            continue
        als.append({"d": d, "t": a.get("t"), "area": area,
                    "p": _eok_s(a["price"]), "v": a.get("dev")})
    als.sort(key=lambda x: x["d"], reverse=True)
    return als or None


# 지역 보드 미니지도 — 리전명 → 도형명(시·군·구 근사). 미열거 리전은 이름 그대로 조회.
# 인천(송도=연수구·청라=서구)은 _LOCAL_GEO['incheon']을 경기 좌표계로 변환해 병합(_BOARD_GEO).
_TIER_GEO_MAP = {
    "강남3구": ["강남구", "서초구", "송파구"],
    "여의도": ["영등포구"], "목동": ["양천구"], "성수": ["성동구"], "이촌": ["용산구"],
    "판교": ["성남시"], "분당": ["성남시"], "위례": ["성남시", "하남시"],
    "수지": ["용인시"], "용인": ["용인시"], "광교": ["수원시"], "동탄": ["화성시"],
    "평촌": ["안양시"], "일산": ["고양시"], "다산": ["남양주시"], "별내": ["남양주시"],
    "과천": ["과천시"], "광명": ["광명시"],
    "송도": ["인천연수구"], "청라": ["인천서구"],
}


def _build_board_geo():
    """급지 미니지도 도형 = _GEO(서울+경기) + 인천 8개 구.
    인천 로컬 도형(_LOCAL_GEO['incheon'])은 드릴다운용 별도 좌표계라, 실제 위경도 앵커
    (계양·부평·연수)로 산출한 affine(scale 0.47, offset −431.6/−76.7)을 적용해 경기
    좌표계에 정합시킨다(부천·시흥 서쪽·김포 남쪽 실제 위치와 일치 검증됨).
    이름은 서울 중구 등과 충돌하지 않게 '인천' 접두(예: 인천연수구·인천서구)."""
    import re as _re
    S, TX, TY = 0.47, -431.6, -76.7

    def _xf(d):
        return _re.sub(
            r"(-?\d+\.?\d*),(-?\d+\.?\d*)",
            lambda m: (f"{float(m.group(1)) * S + TX:.1f},"
                       f"{float(m.group(2)) * S + TY:.1f}"), d)

    out = [{"n": s["n"], "d": s["d"]} for s in _GEO]
    for s in (_LOCAL_GEO.get("incheon") or []):
        out.append({"n": "인천" + s["n"], "d": _xf(s["d"])})
    return out


_BOARD_GEO = _build_board_geo()


def _tier_of(py):
    """평당가(만원) → 티어 키. None → 'etc'."""
    if py is None:
        return "etc"
    for i, b in enumerate(_TIER_BOUNDS):
        if py >= b:
            return f"t{i + 1}"
    return "t10"


def _region_board_payload():
    """fetch_cap_leaders → 6티어(+기타) 페이로드. 반환 (그룹 리스트, live 여부).
    그룹: {k,nm,rng,regions:[{nm,py}],chg,up,dn,fl,n,cap,rows[≤20]}.
      · 리전 평당가 = 소속 단지 평당가(대표가÷대표면적×3.3058) 중위 → 티어 배정(동적)
      · 그룹 chg = 최근 3개월 거래 有 단지들의 30일 등락 평균 · ▲▼ = 상승/하락 단지 수
      · rows: 티어 내 시총순 TOP20 — rg(리전 배지)/pavg(평형별 3개월 평균)/chg/dd"""
    import statistics as _stats
    src = fetch_cap_leaders() or []
    live = src is not _SAMPLE_CAPLEAD
    hi_idx = _hi_alert_index()      # 신고가(30일·직거래 제외) — TOP20 행 알림 병합용
    # 1) 단지 → 리전 배정 + 리전 평당가 표본 수집
    by_region, py_pool = {}, {}
    for c in src:
        if not isinstance(c, dict):
            continue
        if not (c.get("apt") and c.get("gu") and c.get("units")):
            continue
        rg = _region_of_cx(c["gu"], c.get("dong") or "") or "__etc__"
        if c["gu"] in _GANGNAM3:
            rg = "강남3구"   # 지역 보드 한정 통합 — 잠실·신천 분리도 여기서는 흡수(1급지 고정)
        by_region.setdefault(rg, []).append(c)
        py = _cx_pyeong(c)
        if py:
            py_pool.setdefault(rg, []).append(py)
    # 2) 리전 평당가(중위) → 티어 배정
    region_py = {rg: _stats.median(v) for rg, v in py_pool.items() if v}
    buckets = {k: [] for k, _, _ in _TIER_META}
    tier_regions = {k: [] for k, _, _ in _TIER_META}
    for rg, lst in by_region.items():
        if rg == "__etc__":
            tk = "etc"
        elif rg == "강남3구":
            tk = "t1"                              # 1급지 = 강남3구 고정
        else:
            tk = _tier_of(region_py.get(rg))
            if tk == "t1":
                tk = "t2"                          # 1급지는 강남3구 전용 → 타지역은 2급지로
        for c in lst:
            c["_rg"] = "기타" if rg == "__etc__" else rg
        buckets[tk].extend(lst)
        if rg != "__etc__":
            tier_regions[tk].append({"nm": rg, "py": round(region_py.get(rg, 0))})
    # 3) 티어별 요약 + 시총 TOP20
    out = []
    for k, nm, rng in _TIER_META:
        lst = buckets[k]
        chgs = [c["chg"] for c in lst if isinstance(c.get("chg"), (int, float))]
        up = sum(1 for v in chgs if v > 0)
        dn = sum(1 for v in chgs if v < 0)
        cap_sum = sum(c.get("cap_manwon") or (c.get("cap_eok") or 0) * 1e4
                      for c in lst)
        rows = []
        for c in sorted(lst, key=lambda x: x.get("cap_manwon")
                        or (x.get("cap_eok") or 0) * 1e4, reverse=True)[:20]:
            dd = str(c.get("last_deal") or "")[5:10].replace("-", ".")
            gu_disp = "인천 서구" if c["gu"] == "인천서구" else c["gu"]
            _py = _cx_pyeong(c)
            rows.append({
                "apt": c["apt"], "gu": gu_disp, "dong": c.get("dong") or "",
                "rg": c.get("_rg") or gu_disp,
                "units": int(c["units"]), "cap": c.get("cap_fmt") or "",
                "py": round(_py) if _py else None,
                "p": c.get("price_eok") or "", "pavg": c.get("pavg"),
                "chg": (c["chg"] if isinstance(c.get("chg"), (int, float))
                        else None),
                "dd": dd or None,
                "al": _cx_alerts(c, hi_idx),
            })
        out.append({
            "k": k, "nm": nm, "rng": rng, "n": len(lst),
            "regions": sorted(tier_regions[k], key=lambda r: r["py"],
                              reverse=True),
            "chg": (round(sum(chgs) / len(chgs), 1) if chgs else None),
            "up": up, "dn": dn, "fl": len(lst) - up - dn,
            "cap": _fmt_cap(cap_sum) if cap_sum else "",
            "rows": rows,
        })
    return out, live


def _fmt_cap(manwon):
    """시가총액(만원) → '19.0조'/'5,200억' (엔진 _fmt_cap과 동일 규칙 · 뷰어 로컬 복제)."""
    jo = manwon / 1e8
    if jo >= 1:
        return f"{jo:.1f}조"
    return f"{round(manwon / 1e4):,}억"


def _render_region_board():
    """'지역' 서브탭 — 평당가 6급지 타일(구성 리전·평균 등락·▲▼비율) + 선택 티어
    시총 TOP20 (리전 배지 · 평형 3개월 평균가 칩 · 30일 등락 · 최근 거래일)."""
    import json as _json
    groups, live = _region_board_payload()
    if not any(g["n"] for g in groups):
        st.caption("지역 보드 데이터가 아직 없어요. 매일 아침 자동 수집 후 표시됩니다.")
        return
    html = (_REGION_BOARD_HTML
            .replace("__G__", _json.dumps(groups, ensure_ascii=False))
            .replace("__GEO__", _json.dumps(_BOARD_GEO, ensure_ascii=False))
            .replace("__TG__", _json.dumps(_TIER_GEO_MAP, ensure_ascii=False)))
    # 높이: 좌우 5단 타일 + 상세 패널(지도) + 리스트 20행 — iframe 내 _fit이 실측 보정
    components.html(html, height=2600, scrolling=False)
    src = ("국토부 실거래 × 유니버스" if live
           else "샘플 · 아침 수집 후 실데이터로 교체")
    st.markdown(foot_row(
        src, "1급지=강남3구(강남·서초·송파, 잠실 포함) 고정 — 평당 1.2억↑ 타지역은 "
             "2급지로 배정 · 나머지 급지=리전 평당가(단지 대표가÷대표면적×3.3058 중위)로 "
             "동적 배정 · "
             "경계 9천/6천/5천/4천/3천만원 고정 · 대표가는 유니버스 월 리빌드 주기로 갱신 · "
             "리전=서울 자치구 + 판교·위례·광교·수지·동탄·평촌·일산·다산·별내·송도·청라 등 "
             "법정동 분리(위례=성남 창곡+하남 학암, 송파 장지동은 송파구 유지 · "
             "광교=수원 3개동, 상현동은 수지) · 미열거 지역=기타 · "
             "그룹 등락=3개월 내 거래 단지의 30일比 평균 · 단지=티어 내 시총 TOP20 · "
             "평형칩=평형별 3개월 평균(건수) · 알림=🔺평형별 신고가(직전 6개월 최고 "
             "초과·마진%)와 ▲▼평형 3개월 평균 대비 ±5% 이상 괴리 거래(최근 30일·"
             "직거래 제외·평균은 자기 거래 포함이라 소폭 보수적) · 송도·청라·다산·"
             "별내는 다음 유니버스 리빌드부터 편입"),
        unsafe_allow_html=True)


def _render_hot_complexes():
    """주목 단지 보드 — 최근 거래 활발·상승(국토부 실거래) + 단지정보(세대수·시공사·소재지)
    + 면적별(59·84㎡) 최근 실거래가 + '네이버페이부동산' 링크."""
    hot = [h for h in (fetch_hot_complexes() or []) if isinstance(h, dict)]
    if not hot:
        return
    st.markdown('<div class="re-grp">주목 단지'
                '<span class="sub">주요 단지 중 가격·거래가 움직이는 대장주 · 국토부 실거래</span></div>',
                unsafe_allow_html=True)

    def _pp(lbl, val):
        if val:
            return f'<span class="re-hc-pp"><i>{lbl}</i>{val}</span>'
        return f'<span class="re-hc-pp dim"><i>{lbl}</i>–</span>'

    body = ""
    for i, h in enumerate(hot[:15], 1):
        sd = "서울" if h.get("sd") == "seoul" else "경기"
        chg = h.get("chg") or 0
        chg_cls = "up" if chg >= 0 else "dn"
        mult = h.get("vol_mult")
        if isinstance(mult, (int, float)):
            mcls = "up" if mult >= 1.5 else "dn" if mult < 0.8 else "mut"
            vol_s = f'<span class="{mcls}">평소 <b>×{mult}</b></span>'
        else:
            vol_s = '<span class="mut">신규 거래 집중</span>'
        apt = h.get("apt", "")
        addr = (h.get("addr") or f"{sd} {h.get('gu', '')}").strip()
        meta = [addr]
        u = h.get("units")
        if isinstance(u, (int, float)) and u:
            meta.append(f"{int(u):,}세대")
        if h.get("builder"):
            meta.append(str(h["builder"]))
        meta_s = " · ".join(m for m in meta if m)
        prices = _pp("59㎡", h.get("p59_eok")) + _pp("84㎡", h.get("p84_eok"))
        # 우측 대형 실거래 차트(건별 deals) — 없거나 점<2면 기존 미니 스파크 폴백(구 스냅샷 호환)
        chart_svg, groups = _hot_deal_chart_svg(h.get("deals"))
        if chart_svg:
            leg = "".join(
                f'<span><i style="background:{_DEAL_COL[g]}"></i>{_DEAL_LAB[g]}</span>'
                for g in groups)
            right = (f'<div class="re-hc-chart"><div class="re-hc-leg">{leg}</div>'
                     f'{chart_svg}'
                     f'<div class="re-hc-note">점 1개=실거래 1건 · 최근 3개월 · '
                     f'직거래 제외</div></div>')
            spark, card_cls = "", "re-hc has-chart"
        else:
            right = ""
            spark, card_cls = _hot_spark_svg(h.get("spark")), "re-hc"
        jr = h.get("jr")
        if isinstance(jr, (int, float)):
            gap = h.get("gap_eok")
            gap_s = (f'<span class="re-hc-gap">갭 <b>{gap}억</b></span>'
                     if isinstance(gap, (int, float)) else "")
            jbox = (
                f'<div class="re-hc-jbox">'
                f'<div class="re-hc-jg"><div class="re-hc-jlab">'
                f'<span>전세가율</span><b>{int(round(jr))}%</b></div>'
                f'<div class="re-hc-jbar"><i style="width:{min(int(round(jr)), 100)}%">'
                f'</i></div></div>{gap_s}</div>')
        else:
            jbox = ""
        mq = (addr + " " + apt).strip() if addr else apt
        body += (
            f'<div class="{card_cls}"><span class="re-hc-rk">{i}</span>'
            f'<div class="re-hc-main">'
            f'<div class="re-hc-top"><span class="re-hc-nm">{apt}</span>'
            f'<span class="re-hc-chg {chg_cls}">{"+" if chg >= 0 else ""}{chg}%</span></div>'
            f'<div class="re-hc-meta">{meta_s}</div>'
            f'<div class="re-hc-stat">최근 {h.get("recent", 0)}건 · {vol_s} · '
            f'3개월 {h.get("freq", 0)}건</div>'
            f'<div class="re-hc-prices">{prices}{spark}</div>{jbox}</div>'
            f'{right}{_naver_n(mq)}</div>')
    st.markdown(f'<div class="re-hcwrap">{body}</div>', unsafe_allow_html=True)
    st.markdown(foot_row(
        "국토부 실거래 · 직거래 제외",
        "주요 단지 유니버스 중 가격 모멘텀(3개월 등락)+거래 가속이 큰 대장주 순 · "
        "'평소 ×N'=최근 30일 거래밀도÷직전 60일 평균(기간 정규화) · "
        "59·84㎡는 각 면적대 최근 실거래가 · 전세가율=전세 ㎡당가÷매매 ㎡당가 · "
        "갭=(매매−전세)×대표면적 · 차트=최근 3개월 건별 실거래(점 1개=1건, "
        "59㎡ 파랑·84㎡ 빨강·기타 회색 · 선=평형별 시간순 연결 · 라벨=평형별 마지막 거래가) · "
        "N 아이콘(초록)으로 네이버 검색"), unsafe_allow_html=True)


def _area_int(area):
    """'45㎡' / 45.0 / '45' → 45(int). 실패 시 None."""
    try:
        return int(float(str(area).replace("㎡", "").strip()))
    except Exception:
        return None


# ── 시장 요약 밴드(아파트 탭 상단 공통 1열) ─────────────────────────
#   특이거래 탭 기본(표준 민감도·수도권·직거래제외)과 동일 필터로 신고가/신저가
#   건수를 세어 '상승압력'을 만들고, 주목단지로 거래활발 단지수·평균 상승률을 보탠다.
#   엔진/스키마 무변경 — 기존 fetch_anomalies·fetch_hot_complexes 재집계.
_MARKET_BAND_HTML = r'''<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
:root{--bg:#FCFCFA;--ink:#34352f;--muted:#9a9b92;--line:#E4E5DE;--track:#DCE2EA;
 --up:#B65F5A;--dn:#5A7CA0;--kf:'Pretendard',-apple-system,sans-serif;}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--kf);-webkit-font-smoothing:antialiased}
.stack{display:flex;flex-direction:column;gap:10px}
.band{background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:16px 20px;display:flex;align-items:center;gap:24px;flex-wrap:wrap}
.hero{min-width:188px}
.cap{font-size:11px;font-weight:700;letter-spacing:.04em;color:var(--muted);text-transform:uppercase;margin-bottom:7px}
.dir{display:flex;align-items:baseline;gap:8px;margin-bottom:9px}
.dir .ar{font-size:15px}.dir .t{font-size:19px;font-weight:800;letter-spacing:-.02em;color:var(--ink)}
.dir .p{font-size:14px;font-weight:800}
.pbar{height:9px;border-radius:5px;background:var(--track);overflow:hidden}
.pbar .up{display:block;height:100%;background:var(--up)}
.nums{font-size:11px;font-weight:700;margin-top:6px;display:flex;justify-content:space-between}
.grid{flex:1;display:grid;grid-template-columns:repeat(4,1fr);gap:14px;min-width:258px}
.kl{font-size:11px;font-weight:700;color:var(--muted);margin-bottom:4px}
.kv{font-size:18px;font-weight:800;color:var(--ink);letter-spacing:-.02em}
.kv small{font-size:11px;font-weight:700;color:var(--muted);margin-left:2px}
.cap b{color:#7E9A83}
.kl small{font-size:9.5px;font-weight:700;color:#b6b7ae;margin-left:2px}
</style></head><body>
<div class="stack">__BANDS__</div>
<script>
(function(){function _fit(){try{var h=Math.ceil(document.body.getBoundingClientRect().height)+2;var fe=window.frameElement;if(!fe)return;fe.style.height=h+"px";fe.setAttribute("height",h);var p=fe.parentElement;for(var i=0;i<3&&p&&p!==document.body;i++){if(p.style&&p.style.height&&p.style.height!=="auto")p.style.height="auto";p=p.parentElement;}}catch(e){}}window.addEventListener("load",_fit);setTimeout(_fit,150);setTimeout(_fit,600);setTimeout(_fit,1500);window.addEventListener("resize",_fit);try{new ResizeObserver(_fit).observe(document.body);}catch(e){}})();
</script>
</body></html>'''


_BAND_DIV = r'''<div class="band">
  <div class="hero">
    <div class="cap">__CAPTION__</div>
    <div class="dir"><span class="ar" style="color:__DCOL__">__ARROW__</span><span class="t">__DLABEL__</span><span class="p" style="color:__DCOL__">__PCT__%</span></div>
    <div class="pbar"><span class="up" style="width:__PCT__%"></span></div>
    <div class="nums"><span style="color:var(--up)">신고가 __HI__</span><span style="color:var(--dn)">신저가 __LO__</span></div>
  </div>
  <div class="grid">
    <div><div class="kl">__KL1__</div><div class="kv" style="color:var(--up)">__HI__<small>건</small></div></div>
    <div><div class="kl">__KL2__</div><div class="kv" style="color:var(--dn)">__LO__<small>건</small></div></div>
    <div><div class="kl">__KL3__</div><div class="kv">__ACT__<small>단지</small></div></div>
    <div><div class="kl">__KL4__</div><div class="kv" style="color:__GCOL__">__GAIN__</div></div>
  </div>
</div>'''


def _summary_core(anoms_raw, hot_raw, asof_dt):
    """스냅샷 원천(anomalies, metrics._hot)에서 5개 지표 집계 — 특이거래 표준 프리셋
    (직거래제외)과 일치하는 신고가/신저가 건수 + 주목단지 거래활발 단지수·평균 상승률.
    asof_dt=표시 기간(P['days']) 필터 기준일. 반환 {hi,lo,act,avg,latest} 또는 None(표본 0)."""
    P = _ANOM_PRESETS["표준"]

    def _pass(r):
        typ, d, freq, sig = r[0], r[10], r[12], r[13]
        if isinstance(freq, (int, float)) and freq < P["freq"]:
            return False
        dt = _anom_date(d)
        if dt and (asof_dt - dt).days > P["days"]:
            return False
        if isinstance(sig, (int, float)):
            if typ in ("급등", "급락") and sig < P["jump"]:
                return False
            if typ in ("신고가", "신저가") and sig < P["margin"]:
                return False
            if typ == "거래량 급증" and sig < P["surge"]:
                return False
        return True

    normed = [na for na in (_anom_norm(r) for r in (anoms_raw or [])) if na]
    pool = [r for r in normed if not r[9] and _pass(r)]
    hi = sum(1 for r in pool if r[0] == "신고가")
    lo = sum(1 for r in pool if r[0] == "신저가")
    _tx = [dt for dt in (_anom_date(r[10]) for r in pool) if dt]
    latest = max(_tx) if _tx else None
    hot = [h for h in (hot_raw or []) if isinstance(h, dict)]
    act = len(hot)
    chgs = [h.get("chg") for h in hot if isinstance(h.get("chg"), (int, float))]
    avg = round(sum(chgs) / len(chgs), 1) if chgs else None
    if hi + lo == 0 and act == 0:
        return None
    return {"hi": hi, "lo": lo, "act": act, "avg": avg, "latest": latest}


def _market_summary():
    """오늘의 요약 밴드 집계(최신 스냅샷 기준). 반환 dict 또는 None(표본 0)."""
    from datetime import date as _date
    today = _date.today()
    s = _summary_core(fetch_anomalies(), fetch_hot_complexes(), today)
    if not s:
        return None
    s["today"] = today
    return s


def _band_div(caption, hi, lo, act, avg,
              kl=("신고가", "신저가", "거래활발", "평균 상승률")):
    """요약 밴드 1단(div) 채우기 — 월간/주간/오늘 공용. 방향 배지·색은 hi/lo에서 계산."""
    tot = hi + lo
    pct = round(hi / tot * 100) if tot else 50
    if pct >= 60:
        dlabel, arrow, dcol = "상승 우세", "▲", "#B65F5A"
    elif pct <= 40:
        dlabel, arrow, dcol = "하락 우세", "▼", "#5A7CA0"
    else:
        dlabel, arrow, dcol = "혼조", "◆", "#7E9A83"
    if avg is None:
        gain, gcol = "–", "#9a9b92"
    else:
        gcol = "#B65F5A" if avg >= 0 else "#5A7CA0"
        gain = f'{"+" if avg >= 0 else ""}{avg}<small>%</small>'
    return (_BAND_DIV
            .replace("__CAPTION__", caption)
            .replace("__KL1__", kl[0]).replace("__KL2__", kl[1])
            .replace("__KL3__", kl[2]).replace("__KL4__", kl[3])
            .replace("__DLABEL__", dlabel)
            .replace("__ARROW__", arrow)
            .replace("__DCOL__", dcol)
            .replace("__PCT__", str(pct))
            .replace("__HI__", str(hi))
            .replace("__LO__", str(lo))
            .replace("__ACT__", str(act))
            .replace("__GCOL__", gcol)
            .replace("__GAIN__", gain))


def _band_fill(caption, hi, lo, act, avg,
               kl=("신고가", "신저가", "거래활발", "평균 상승률")):
    """단일 밴드 문서 HTML(구 인터페이스 호환) — _band_div 1단을 문서 틀에 실어 반환."""
    return _MARKET_BAND_HTML.replace(
        "__BANDS__", _band_div(caption, hi, lo, act, avg, kl))


def _market_window_summary(win_days):
    """N일 창 요약 밴드 집계(주간=7·월간=30 공용) — 최신 스냅샷의 특이거래를
    '최신 거래일 기준 최근 N일' 창으로 재집계해 신고가·신저가 합을 만든다(일별 스냅샷
    hi/lo를 그냥 더하면 같은 거래가 여러 날 반복 계산되므로 사용하지 않음).
    거래활발·평균 상승률은 최근 N일 일별 스냅샷 평균(이력 없으면 현재 스냅샷 값 폴백).
    반환 dict 또는 None. ※월간(30일)은 엔진 특이거래 표시창(45일) 안이라 커버 가능."""
    from datetime import timedelta as _td
    P = _ANOM_PRESETS["표준"]

    def _pass_nodate(r):
        typ, freq, sig = r[0], r[12], r[13]
        if isinstance(freq, (int, float)) and freq < P["freq"]:
            return False
        if isinstance(sig, (int, float)):
            if typ in ("급등", "급락") and sig < P["jump"]:
                return False
            if typ in ("신고가", "신저가") and sig < P["margin"]:
                return False
            if typ == "거래량 급증" and sig < P["surge"]:
                return False
        return True

    normed = [na for na in (_anom_norm(r) for r in (fetch_anomalies() or [])) if na]
    pool = [(r, _anom_date(r[10])) for r in normed if not r[9] and _pass_nodate(r)]
    pool = [(r, dt) for r, dt in pool if dt]
    if not pool:
        return None
    latest = max(dt for _, dt in pool)
    start = latest - _td(days=win_days - 1)
    wk = [r for r, dt in pool if dt >= start]
    hi = sum(1 for r in wk if r[0] == "신고가")
    lo = sum(1 for r in wk if r[0] == "신저가")

    acts, avgs = [], []
    for row in (_load_recent_re_snapshots(win_days) or []):
        hot = [h for h in ((row.get("metrics") or {}).get("_hot") or [])
               if isinstance(h, dict)]
        if not hot:
            continue
        acts.append(len(hot))
        chgs = [h.get("chg") for h in hot
                if isinstance(h.get("chg"), (int, float))]
        if chgs:
            avgs.append(sum(chgs) / len(chgs))
    if not acts:                                  # 스냅샷 이력 없음 → 현재값 폴백
        hot = [h for h in (fetch_hot_complexes() or []) if isinstance(h, dict)]
        if hot:
            acts = [len(hot)]
            chgs = [h.get("chg") for h in hot
                    if isinstance(h.get("chg"), (int, float))]
            if chgs:
                avgs = [sum(chgs) / len(chgs)]
    act = round(sum(acts) / len(acts)) if acts else 0
    avg = round(sum(avgs) / len(avgs), 1) if avgs else None
    if hi + lo == 0 and act == 0:
        return None
    return {"hi": hi, "lo": lo, "act": act, "avg": avg,
            "start": start, "latest": latest, "ndays": len(acts)}


def _market_week_summary():
    """주간(7일 창) 요약 — _market_window_summary(7) 래퍼(기존 인터페이스 유지)."""
    return _market_window_summary(7)


def _market_month_summary():
    """월간(30일 창) 요약 — _market_window_summary(30) 래퍼."""
    return _market_window_summary(30)


def _render_market_week_band():
    """(구) 주간 요약 밴드 단독 렌더 — 통합 렌더러(_render_market_bands) 도입 후 미사용
    호환 유지용. 데이터 없으면 조용히 생략."""
    s = _market_week_summary()
    if not s:
        return
    d0, d1 = s["start"], s["latest"]
    caption = (f'<b>주간</b> 아파트 시장 · {d0.month}.{d0.day}→{d1.month}.{d1.day} · '
               '최신거래일 기준 7일')
    html = _band_fill(
        caption, s["hi"], s["lo"], s["act"], s["avg"],
        kl=("신고가 <small>7일 합</small>", "신저가 <small>7일 합</small>",
            "거래활발 <small>주간 평균</small>", "평균 상승률 <small>주간 평균</small>"))
    components.html(html, height=210, scrolling=False)


def _render_market_band():
    """'아파트' 탭 상단 시장 요약 밴드(헤드라인 방향 배지) — 주간 밴드 아래 스택 2단(오늘).
    foot는 여기서 한 번만(주간+오늘 공통 설명)."""
    s = _market_summary()
    if not s:
        return
    _ref = s.get("latest")
    datestr = (f'{_ref.month}.{_ref.day} 최신거래 기준' if _ref
               else f'{s["today"].month}.{s["today"].day} 기준')
    html = _band_fill(f'오늘의 아파트 시장 · {datestr}',
                      s["hi"], s["lo"], s["act"], s["avg"])
    components.html(html, height=210, scrolling=False)
    st.markdown(foot_row(
        "특이거래 기준과 동일 집계",
        "상승압력=신고가÷(신고가+신저가) · 표준 민감도·직거래 제외 · "
        "주간 신고가·신저가=최신 거래일 기준 7일 창 합산(일별 합산 중복 없음) · "
        "거래활발·평균 상승률(주간)=최근 7일 스냅샷 평균 · "
        "거래활발=주목단지 랭킹 단지수 · 평균 상승률=주목단지 평균"),
        unsafe_allow_html=True)


def _render_market_bands():
    """월간·주간·오늘 시장 밴드 3단 통합 렌더 — 단일 iframe(단 간격 10px).
    개별 iframe 3장으로 쌓으면 Streamlit 요소 기본 여백 때문에 밴드 사이가 벌어져
    한 문서로 합쳤다(주간·오늘 사이 여백 축소 + 월간 신설). 표본 없는 단은 생략,
    전부 없으면 아무것도 그리지 않는다. foot는 여기서 한 번만(3단 공통 설명)."""
    divs = []
    m = _market_month_summary()
    if m:
        d0, d1 = m["start"], m["latest"]
        divs.append(_band_div(
            f'<b>월간</b> 아파트 시장 · {d0.month}.{d0.day}→{d1.month}.{d1.day} · '
            '최신거래일 기준 30일',
            m["hi"], m["lo"], m["act"], m["avg"],
            kl=("신고가 <small>30일 합</small>", "신저가 <small>30일 합</small>",
                "거래활발 <small>월간 평균</small>", "평균 상승률 <small>월간 평균</small>")))
    w = _market_week_summary()
    if w:
        d0, d1 = w["start"], w["latest"]
        divs.append(_band_div(
            f'<b>주간</b> 아파트 시장 · {d0.month}.{d0.day}→{d1.month}.{d1.day} · '
            '최신거래일 기준 7일',
            w["hi"], w["lo"], w["act"], w["avg"],
            kl=("신고가 <small>7일 합</small>", "신저가 <small>7일 합</small>",
                "거래활발 <small>주간 평균</small>", "평균 상승률 <small>주간 평균</small>")))
    t = _market_summary()
    if t:
        _ref = t.get("latest")
        datestr = (f'{_ref.month}.{_ref.day} 최신거래 기준' if _ref
                   else f'{t["today"].month}.{t["today"].day} 기준')
        divs.append(_band_div(f'오늘의 아파트 시장 · {datestr}',
                              t["hi"], t["lo"], t["act"], t["avg"]))
    if not divs:
        return
    html = _MARKET_BAND_HTML.replace("__BANDS__", "".join(divs))
    # 초기 높이=단수×150+여백 — iframe 내 _fit이 실측 보정(부모 래퍼 높이까지 해제)
    components.html(html, height=len(divs) * 155 + 20, scrolling=False)
    st.markdown(foot_row(
        "특이거래 기준과 동일 집계",
        "상승압력=신고가÷(신고가+신저가) · 표준 민감도·직거래 제외 · "
        "월간·주간 신고가·신저가=최신 거래일 기준 30일/7일 창 합산(일별 합산 중복 없음) · "
        "거래활발·평균 상승률(월간·주간)=해당 기간 스냅샷 평균 · "
        "거래활발=주목단지 랭킹 단지수 · 평균 상승률=주목단지 평균"),
        unsafe_allow_html=True)
