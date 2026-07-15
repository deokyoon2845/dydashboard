"""부동산 '사이클' 탭 — KB 주간·월간 선행지표 + 사이클 위치 게이지.

KB(매수우위·매매전망·선도50·전세수급)·ECOS(주담대금리)·KOSIS(미분양) 지표를 모아
지표 v2 카드(그룹 신호·게이지)로 렌더한다. 데이터 폴백: DB 스냅샷 → 샘플.
(_TREND_*·_render_indicators 등 일부는 이전 버전 잔존 — 현재 미호출·삭제 후보.)
"""

import streamlit as st
import streamlit.components.v1 as components

from modules.ui import foot_row
from modules.realestate_common import _load_re_snapshot, _resolved_metrics


# ── 지표 (그룹 · 델타 · 기준선) ─────────────────────────────────
#   각 카드 dict: group/label/value/kind/col/series/note/dunit/baseline
#   거래량은 세션 re_metrics 합산, 금리는 한은 ECOS에서 실값을 끌어오고
#   실패하면 샘플 시리즈로 폴백한다(화면이 절대 비거나 깨지지 않게).
ECOS_MORTGAGE_STAT = "121Y006"   # 예금은행 가중평균금리(신규취급액 기준)
                                 # ※구값 722Y001은 기준금리 표 — probe(2026-07-09)로 교정


ECOS_MORTGAGE_ITEM = "BECBLA0302"  # 주택담보대출 · probe 실데이터 검증 완료


_RATE_SAMPLE = [4.35, 4.28, 4.20, 4.12, 4.05, 3.98, 3.92]


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_mortgage_rate():
    """한은 ECOS 주담대 가중평균금리(월, 최근 7개). 실패 시 None → 샘플 폴백. (1h 캐시)"""
    try:
        import requests
        from datetime import datetime
        key = ""
        try:
            key = st.secrets.get("ECOS_API_KEY", "")
        except Exception:
            key = ""
        if not key:
            return None
        end = datetime.now().strftime("%Y%m")
        start = f"{int(end[:4]) - 1}{end[4:]}"
        url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/24/"
               f"{ECOS_MORTGAGE_STAT}/M/{start}/{end}/{ECOS_MORTGAGE_ITEM}")
        r = requests.get(url, timeout=8)
        rows = r.json().get("StatisticSearch", {}).get("row", [])
        vals = [float(x["DATA_VALUE"]) for x in rows if x.get("DATA_VALUE")]
        return vals[-7:] if len(vals) >= 2 else None
    except Exception:
        return None


def _kb_value_series(df, decimals=1, points=7):
    """KB Kbland 결과 df → 값 시리즈(날짜 정렬·값 컬럼 자동탐색).
       points=N이면 최근 N개, None이면 전체. 실패 시 None."""
    import pandas as pd
    if df is None or len(df) == 0:
        return None
    if "날짜" in df.columns:
        df = df.sort_values("날짜")
    valcol = None
    for c in reversed(list(df.columns)):
        if c == "지역코드":
            continue
        s = pd.to_numeric(df[c], errors="coerce")
        if s.notna().sum() >= 2:
            valcol = c
            df = df.assign(**{c: s})
            break
    if valcol is None:
        return None
    vals = [float(v) for v in df[valcol].tolist() if v == v]
    if len(vals) < 2:
        return None
    if points is not None:
        vals = vals[-points:]
    return [round(v, decimals) for v in vals]


@st.cache_data(ttl=21600, show_spinner=False)
def _fetch_kb_buy_superiority():
    """KB 주간 매수우위지수(서울). 키 불필요. 실패 시 None → 샘플. (6h 캐시)"""
    try:
        from PublicDataReader import Kbland
        df = Kbland().get_market_trend(
            메뉴코드="01", 월간주간구분코드="02", 지역코드="11", 기간="1")
        return _kb_value_series(df, 1)
    except Exception:
        return None


@st.cache_data(ttl=21600, show_spinner=False)
def _fetch_kb_sales_index():
    """KB 주간 아파트 매매가격지수(서울). 키 불필요. 실패 시 None → 샘플."""
    try:
        from PublicDataReader import Kbland
        df = Kbland().get_price_index(
            월간주간구분코드="02", 매물종별구분="01", 매매전세코드="01",
            지역코드="11", 기간="1")
        return _kb_value_series(df, 2)
    except Exception:
        return None


@st.cache_data(ttl=21600, show_spinner=False)
def _fetch_kb_jeonse_ratio():
    """KB 아파트 전세가격비율(서울, 월간). 키 불필요. 실패 시 None → 샘플."""
    try:
        from PublicDataReader import Kbland
        df = Kbland().get_jeonse_price_ratio("01", 지역코드="11", 기간="1")
        return _kb_value_series(df, 1)
    except Exception:
        return None


@st.cache_data(ttl=21600, show_spinner=False)
def _fetch_kb_jeonse_index():
    """KB 주간 아파트 전세가격지수(서울). 키 불필요. 실패 시 None → 샘플."""
    try:
        from PublicDataReader import Kbland
        df = Kbland().get_price_index(
            월간주간구분코드="02", 매물종별구분="01", 매매전세코드="02",
            지역코드="11", 기간="1")
        return _kb_value_series(df, 2)
    except Exception:
        return None


# ── 차트 추이용 전체 시리즈 (주간 · 최근값 다수) ──────────────────
#   KB가 주는 만큼만 실데이터로 사용 · 부족하면 컴포넌트에서 합성 폴백.
@st.cache_data(ttl=21600, show_spinner=False)
def _fetch_kb_sales_index_full():
    try:
        from PublicDataReader import Kbland
        df = Kbland().get_price_index(
            월간주간구분코드="02", 매물종별구분="01", 매매전세코드="01",
            지역코드="11", 기간="1")
        return _kb_value_series(df, 2, points=None)
    except Exception:
        return None


@st.cache_data(ttl=21600, show_spinner=False)
def _fetch_kb_jeonse_index_full():
    try:
        from PublicDataReader import Kbland
        df = Kbland().get_price_index(
            월간주간구분코드="02", 매물종별구분="01", 매매전세코드="02",
            지역코드="11", 기간="1")
        return _kb_value_series(df, 2, points=None)
    except Exception:
        return None


@st.cache_data(ttl=21600, show_spinner=False)
def _fetch_kb_buy_superiority_full():
    try:
        from PublicDataReader import Kbland
        df = Kbland().get_market_trend(
            메뉴코드="01", 월간주간구분코드="02", 지역코드="11", 기간="1")
        return _kb_value_series(df, 1, points=None)
    except Exception:
        return None


# KOSIS 미분양주택현황(시도/시군구) DT_1YL202001E · 항목=미분양현황 · objL1=전국
_KOSIS_UNSOLD = {"org": "101", "tbl": "DT_1YL202001E",
                 "itm": "13103871087T1", "obj": "13102871087A.0002"}


@st.cache_data(ttl=21600, show_spinner=False)
def _fetch_kosis_unsold():
    """KOSIS 전국 미분양(월, 최근 7개) → 만호 단위. KOSIS_API_KEY 필요. 실패 시 None → 샘플."""
    try:
        import pandas as pd
        key = ""
        try:
            key = st.secrets.get("KOSIS_API_KEY", "")
        except Exception:
            key = ""
        if not key:
            return None
        from PublicDataReader import Kosis
        df = Kosis(key).get_data(
            "통계자료", orgId=_KOSIS_UNSOLD["org"], tblId=_KOSIS_UNSOLD["tbl"],
            itmId=_KOSIS_UNSOLD["itm"], objL1=_KOSIS_UNSOLD["obj"],
            prdSe="M", newEstPrdCnt="14")
        if df is None or len(df) == 0:
            return None
        pcol = next((c for c in df.columns if "시점" in c or c.upper() == "PRD_DE"), None)
        vcol = next((c for c in df.columns if "수치" in c or c.upper() == "DT"), None)
        if vcol is None:
            for c in reversed(list(df.columns)):
                if pd.to_numeric(df[c], errors="coerce").notna().sum() >= 2:
                    vcol = c
                    break
        if vcol is None:
            return None
        if pcol:
            df = df.sort_values(pcol)
        vals = [v for v in pd.to_numeric(df[vcol], errors="coerce").tolist() if v == v]
        out = [round(v / 10000, 1) for v in vals[-7:]]
        return out if len(out) >= 2 else None
    except Exception:
        return None


def _live_volume():
    """수도권 주간 실거래 (총건수, 전주비 평균%). 세션→DB 스냅샷, 없으면 None."""
    m = _resolved_metrics()
    if not m:
        return None
    try:
        total = int(sum(r.get("v", 0) for r in m.values()))
        vcs = [r["vc"] for r in m.values() if "vc" in r]
        avg_vc = round(sum(vcs) / len(vcs), 1) if vcs else 0.0
        return total, avg_vc
    except Exception:
        return None


def fetch_indicators():
    """그룹별 지표 카드 리스트. 거래량·금리는 실값 우선, 나머지는 샘플(연결 예정)."""
    vol = _live_volume()
    if vol:
        v_total, v_vc = vol
        vol_card = {"group": "선행·심리", "label": "주간 실거래량(수도권)",
                    "value": f"{v_total:,}건", "kind": "bar", "col": "#7E9A83",
                    "series": [int(v_total * x) for x in (.82, .78, .9, .85, .94, .97, 1.0)],
                    "note": "국토부 실거래 합산 · 전주비 "
                            + (f"+{v_vc}%" if v_vc >= 0 else f"{v_vc}%"),
                    "dunit": "건", "baseline": None}
    else:
        vol_card = {"group": "선행·심리", "label": "주간 실거래량(수도권)",
                    "value": "2,594건", "kind": "bar", "col": "#7E9A83",
                    "series": [2120, 2030, 2350, 2210, 2440, 2510, 2594],
                    "note": "국토부 실거래 · '갱신' 누르면 실값(현재 샘플)",
                    "dunit": "건", "baseline": None}

    rate_live = _fetch_mortgage_rate()
    rate = rate_live or _RATE_SAMPLE
    rate_card = {"group": "금융", "label": "주담대 금리(가중평균)",
                 "value": f"{rate[-1]:.2f}%", "kind": "line", "col": "#5A7CA0",
                 "series": rate, "dunit": "%p", "baseline": None,
                 "note": "한은 ECOS · 신규취급 가중평균" if rate_live
                         else "한은 ECOS · 키/코드 확인 전 샘플"}

    kb_live = _fetch_kb_buy_superiority()
    kb_series = kb_live or [44, 46, 49, 52, 55, 57, 58.4]
    kb_card = {"group": "선행·심리", "label": "매수우위지수",
               "value": f"{kb_series[-1]:.1f}", "kind": "line", "col": "#7E9A83",
               "series": kb_series, "dunit": "p", "baseline": 100,
               "note": "KB 주간 · 100=중립" if kb_live
                       else "KB 주간 · 100=중립(현재 샘플)"}

    unsold_live = _fetch_kosis_unsold()
    unsold = unsold_live or [7.2, 7, 6.8, 6.6, 6.4, 6.2, 6.1]
    unsold_card = {"group": "공급·펀더멘털", "label": "미분양(전국)",
                   "value": f"{unsold[-1]:.1f}만", "kind": "bar", "col": "#B65F5A",
                   "series": unsold, "dunit": "만", "baseline": None,
                   "note": "KOSIS 미분양현황 · 월간 · 적을수록 수급 양호" if unsold_live
                           else "KOSIS 미분양현황 · 키/표 확인 전 샘플"}

    mi_live = _fetch_kb_sales_index()
    mi = mi_live or [95.6, 95.7, 95.9, 96.0, 96.1, 96.2, 96.3]
    if mi_live and len(mi) >= 2 and mi[-2]:
        _wk = (mi[-1] / mi[-2] - 1) * 100
        mi_note = f"KB 주간 아파트 매매가격지수(서울) · 주간 {_wk:+.2f}%"
    else:
        mi_note = "KB 주간 매매가격지수(서울) · 확인 전 샘플"
    mi_card = {"group": "가격(동행)", "label": "매매 주간지수(서울)",
               "value": f"{mi[-1]:.1f}", "kind": "line", "col": "#B65F5A",
               "series": mi, "dunit": "p", "baseline": None, "note": mi_note}

    jr_live = _fetch_kb_jeonse_ratio()
    jr = jr_live or [57, 56.5, 56, 55.5, 55.1, 54.9, 54.8]
    jr_card = {"group": "가격(동행)", "label": "전세가율(서울 아파트)",
               "value": f"{jr[-1]:.1f}%", "kind": "line", "col": "#5A7CA0",
               "series": jr, "dunit": "%p", "baseline": None,
               "note": "KB 월간 · 갭·전세 레버리지" if jr_live
                       else "KB 전세가격비율 · 확인 전 샘플"}

    return [
        kb_card,
        vol_card,
        mi_card,
        jr_card,
        unsold_card,
        {"group": "공급·펀더멘털", "label": "인구·세대수(수도권)", "value": "13,420천", "kind": "bar",
         "col": "#A7BBA9", "series": [13380, 13390, 13400, 13405, 13410, 13418, 13420],
         "note": "KOSIS 주민등록인구 · 표 확정 후 연결(현재 샘플)", "dunit": "천", "baseline": None},
        rate_card,
    ]


# ── 지표 시계열 (엔진 collect_indicators가 DB에 저장하는 새 형식) ──────────
#   각 항목: {key,label,sub,unit,col,series[...]} · 가격지수는 전부 KB(신뢰 소스).
#   메타(차트 표시용): short=카드 라벨 · cadence=주/월 · baseline=중립선 · dp=델타 단위
_IND_META = {
    "sale":    ("매매지수", "week", 100, "%"),
    "jeonse":  ("전세지수", "week", 100, "%"),
    "lead50":  ("선도50지수", "week", 100, "%"),
    "buy":     ("매수우위", "week", 100, "p"),
    "jsup":    ("전세수급", "week", 100, "p"),
    "outlook": ("매매전망", "month", 100, "p"),
    "jr":      ("전세가율", "month", 100, "p"),
}


# baseline(중립선 100)이 의미 있는 심리지표만 — 매수우위·전세수급·매매전망
_IND_BASELINE = {"buy": 100, "jsup": 100, "outlook": 100}


# ── 지표 탭 v2: 의미 레이어(사이클·그룹·신호·해석) 메타 ───────────────
#   g=그룹 · baseline=중립선(없으면 None) · inv=역행(낮을수록 시장 긍정) · interp=한 줄 해석
_INDV2_GROUPS = {
    "lead":   {"name": "선행지표", "desc": "먼저 움직인다 — 방향 신호"},
    "coin":   {"name": "동행지표", "desc": "지금 가격·거래"},
    "supply": {"name": "수급·심리", "desc": "전세·갭·기대"},
}


_INDV2_DEF = {
    "buy":      {"g": "lead", "cad": "week", "baseline": 100, "inv": False,
                 "interp": "100 넘으면 매수자 우위·과열권. 매수 심리의 선행 신호."},
    "outlook":  {"g": "lead", "cad": "month", "baseline": 100, "inv": False,
                 "interp": "100 위 = 상승 기대 우세. 향후 가격 방향의 선행."},
    "lead50":   {"g": "lead", "cad": "week", "baseline": None, "inv": False,
                 "interp": "상급지 50단지가 시장을 선도—먼저 반등/하락(매매지수와 강상관)."},
    "sale":     {"g": "coin", "cad": "week", "baseline": None, "inv": False,
                 "interp": "실제 매매가 레벨. 시장의 '현재값'."},
    "jeonse":   {"g": "coin", "cad": "week", "baseline": None, "inv": False,
                 "interp": "전세가 레벨. 오르면 매매 하방을 받쳐줌."},
    "jsup":     {"g": "supply", "cad": "week", "baseline": 100, "inv": False,
                 "interp": "100 위 = 전세 공급부족(수요>공급). 전세·매매 동반 자극."},
    "jr":       {"g": "supply", "cad": "month", "baseline": None, "inv": False,
                 "interp": "전세/매매 비율. 높을수록 갭 부담↓·하방 지지↑."},
    "joutlook": {"g": "supply", "cad": "month", "baseline": 100, "inv": False,
                 "interp": "전세 상승 기대. 전세 불안의 선행 신호."},
}


# 카드 표시 순서(그룹 보기 내 정렬). 선도50은 선행 보조로 매매전망 뒤에 둠.
_INDV2_ORDER = ["buy", "outlook", "lead50", "sale", "jeonse",
                "jsup", "jr", "joutlook"]


# 핵심(상단 강조 카드).
_INDV2_CORE = ("outlook",)  # 핵심 카드 섹션 삭제(2026-07)로 현재 미사용 — 보존


# 연결예정 슬롯 — 데이터 소스 자체가 아직 미연결(진짜 '연결예정'). 가짜 데이터 없음.
# (경매 낙찰가율·입주물량 제거 — 2026-07)
_INDV2_PENDING = []


# 엔진 연결 전(또는 DB 비었을 때) 샘플 — 현재 상승장 반영(가짜로 하락처럼 안 보이게)
_IND_SAMPLE = [
    {"key": "sale", "label": "매매가격지수", "sub": "서울 · 주간(KB)", "unit": "", "col": "#B65F5A",
     "series": [94.1, 94.3, 94.6, 94.9, 95.1, 95.4, 95.6, 95.9, 96.1, 96.4,
                96.6, 96.9, 97.1, 97.3, 97.5, 97.7, 97.9, 98.0, 98.1, 98.2]},
    {"key": "jeonse", "label": "전세가격지수", "sub": "서울 · 주간(KB)", "unit": "", "col": "#5A7CA0",
     "series": [95.0, 95.2, 95.4, 95.6, 95.8, 96.0, 96.1, 96.3, 96.4, 96.6,
                96.7, 96.8, 96.9, 97.0, 97.1, 97.2, 97.3, 97.3, 97.4, 97.4]},
    {"key": "lead50", "label": "선도아파트50지수", "sub": "전국 · 주간(KB) · 상위 50개 단지", "unit": "", "col": "#A35F5A",
     "series": [94.8, 95.2, 95.7, 96.2, 96.6, 97.1, 97.6, 98.0, 98.5, 98.9,
                99.3, 99.8, 100.2, 100.5, 100.9, 101.2, 101.5, 101.8, 102.0, 102.2]},
    {"key": "buy", "label": "매수우위지수", "sub": "서울 · 주간(KB) · 100=중립", "unit": "", "col": "#B89A5C",
     "series": [34, 37, 41, 44, 47, 50, 53, 56, 58, 61, 63, 66, 68, 70, 72, 73, 75, 76, 77, 77]},
    {"key": "jsup", "label": "전세수급지수", "sub": "서울 · 주간(KB) · 100=균형", "unit": "", "col": "#6E8FA8",
     "series": [108, 111, 114, 117, 120, 123, 126, 128, 131, 133, 135, 137, 139, 140, 142, 143, 144, 145, 145, 146]},
    {"key": "outlook", "label": "매매가격전망지수", "sub": "서울 · 월간(KB) · 100=중립", "unit": "", "col": "#C2A05A",
     "series": [96, 98, 101, 104, 107, 109, 112, 114, 116, 117, 118, 119]},
    {"key": "joutlook", "label": "전세가격전망지수", "sub": "서울 · 월간(KB) · 100=중립", "unit": "", "col": "#8AA0B5",
     "series": [97, 99, 101, 103, 105, 107, 108, 110, 111, 111, 112, 112]},
    {"key": "jr", "label": "전세가율", "sub": "서울 · 월간(KB)", "unit": "%", "col": "#7E9A83",
     "series": [51.4, 51.7, 52.0, 52.3, 52.6, 52.9, 53.1, 53.3, 53.5, 53.7, 53.8, 53.9]},
    # 서울·수도권 매매 중위/평균가격(억) — 지표탭 '현재 매매가격' 블록용(카드 아님)
    {"key": "med_seoul", "label": "서울 아파트 매매 중위가격", "sub": "서울 · 월간(KB)", "unit": "억", "col": "#7E9A83",
     "series": [9.8, 9.9, 10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9]},
    {"key": "mean_seoul", "label": "서울 아파트 매매 평균가격", "sub": "서울 · 월간(KB)", "unit": "억", "col": "#7E9A83",
     "series": [12.6, 12.7, 12.8, 12.9, 13.0, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7]},
    {"key": "med_sudo", "label": "수도권 아파트 매매 중위가격", "sub": "수도권 · 월간(KB)", "unit": "억", "col": "#7E9A83",
     "series": [6.20, 6.25, 6.30, 6.35, 6.40, 6.45, 6.50, 6.55, 6.60, 6.65, 6.70, 6.75]},
    {"key": "mean_sudo", "label": "수도권 아파트 매매 평균가격", "sub": "수도권 · 월간(KB)", "unit": "억", "col": "#7E9A83",
     "series": [7.00, 7.05, 7.10, 7.15, 7.20, 7.25, 7.30, 7.35, 7.40, 7.45, 7.50, 7.55]},
]


def _resolved_indicator_series():
    """지표 시계열: 세션 → DB 스냅샷(새 형식 list[{...,'series'}]) → 샘플.
    옛 형식/None이면 샘플로 폴백(화면이 비거나 가짜 하락으로 보이지 않게)."""
    s = st.session_state.get("re_indseries")
    if s:
        return s
    snap = _load_re_snapshot()
    inds = (snap or {}).get("indicators") if snap else None
    if (isinstance(inds, list) and inds and isinstance(inds[0], dict)
            and "series" in inds[0]):
        return inds
    return _IND_SAMPLE


# ── 종합 강도 v5 — 5지표(정책 포함) z-score 가중 결합 · 2016 창 재실측(2026-07-14) ──
#   설계 근거: engine/starts_probe — 평가창을 2016.1~로 확장 재실측(n=126 ·
#   정권 전환 3회 포함: 박근혜→문재인→윤석열→이재명).
#   백테스트 성능: corr +0.843 · 방향 적중률 79%.
#
#   v4 → v5 변경:
#   · [신규] 정책레짐 더미 25% — 민주 정권 +1.0 / 보수 −0.3(사용자 가설: 규제·공급억제
#     기조가 가격 압력·양극화로). 단독 corr +0.61(lag 0). 가중 25%는 고정가중 스윕
#     (10~50%)에서 corr·적중률 무손실 최대치 — 40%는 적중률 −9%p라 기각(편집 스펙).
#   · 나머지 4지표는 75%를 2016 창 실측 |corr| 비례로 배분(v4 파이프라인 동일):
#     월간화 → 3개월 이동평균 → z-score(자체 창) → lag 시프트 → 부호×가중 합.
#   · 매수우위는 장기 시리즈(buy_l · 2016~) 우선 사용, 백테스트 창 78→127개월(동적).
#   착공 주의: ECOS 전국 YoY(lag29 · corr −0.80) 유지 — 소스가 2019.4~뿐이라 lag 반영
#   기여는 2021.9부터(단일 하락 사이클 의존)·YoY 기저효과 존재. KOSIS 서울+경기 대안
#   (레벨형·YoY)은 실측에서 선행성이 재현되지 않아 기각(starts_probe 2026-07-14).
#
#   점수 스케일(v4와 동일): score = clip((합성 − μ) ÷ 2σ, ±1) — μ·σ는 백테스트 창
#   기준(0 = 2016년 이후 평균 국면) · 임계 ±0.15 = ±0.3σ · 게이지·차트 축 재사용.
_V5_DEF = [
    # (지표키, 표시명, 가중, 부호, lag개월) — 가중은 최종 확정치(합=1.00)
    ("policy",   "정책레짐",    0.25, +1, 0),
    ("buy",      "매수우위",    0.22, +1, 0),
    ("starts",   "착공",       0.22, -1, 29),
    ("jeonse",   "전세지수YoY", 0.16, +1, 0),
    ("mortgage", "주담대Δ6M",  0.15, -1, 15),
]
_V5_T = 0.15           # 국면 판정 임계(점수 스케일 · ±0.3σ 상당) — JS(0.15)와 동기화
_V5_SIG_MULT = 2.0     # score = clip((합성−μ) ÷ (σ×이 값), ±1)
_V5_START = "201601"   # 백테스트 창 시작(표시 클립 _clip_2016과 동기)

# 정권 레짐 캘린더 — (시작YYYYMM, 끝YYYYMM|None=현재, 값). 정권 교체 시 여기만 갱신.
_REGIMES = [
    ("201302", "201704", -0.3),   # 박근혜~권한대행(보수)
    ("201705", "202204", +1.0),   # 문재인(민주)
    ("202205", "202505", -0.3),   # 윤석열~권한대행(보수)
    ("202506", None,     +1.0),   # 이재명(민주)
]


def _clip1(x):
    return max(-1.0, min(1.0, x))


# ── 월간 시계열 유틸 — dict {YYYYMM: float} 기반(probe와 동일 프리미티브) ──
def _ym_add(ym, k):
    y, m = int(str(ym)[:4]), int(str(ym)[4:6])
    t = y * 12 + (m - 1) + k
    return f"{t // 12}{t % 12 + 1:02d}"


def _ym_now():
    from datetime import date
    return date.today().strftime("%Y%m")


def _mon_labels(n):
    """현재월 기준 거꾸로 n개 YYYYMM(과거→현재) — 무일자 '월간' 시계열 라벨.
    30일 간격 역산(_dates_back)은 5년에 ~1개월 드리프트라 월 단위 조인엔 부적합."""
    cur = _ym_now()
    return [_ym_add(cur, -(n - 1 - i)) for i in range(n)]


def _weekly_to_monthly(vals):
    """무일자 '주간' 시계열 → {YYYYMM: 월평균}. 7일 역산 라벨로 버킷."""
    from datetime import date, timedelta
    t = date.today()
    out = {}
    n = len(vals)
    for i, v in enumerate(vals):
        if v is None:
            continue
        ym = (t - timedelta(days=7 * (n - 1 - i))).strftime("%Y%m")
        out.setdefault(ym, []).append(float(v))
    return {k: sum(a) / len(a) for k, a in out.items()}


def _d_ma3(s):
    """{ym:v} → 3개월 이동평균(가용분 평균 — 창 초입도 값 유지)."""
    out = {}
    for ym in s:
        w = [s[_ym_add(ym, -i)] for i in range(3) if _ym_add(ym, -i) in s]
        out[ym] = sum(w) / len(w)
    return out


def _d_z(s, min_n=12):
    """{ym:v} → z-score(자체 창 전체 기준). 표본 부족·상수 시계열이면 {}."""
    vals = list(s.values())
    if len(vals) < min_n:
        return {}
    mu = sum(vals) / len(vals)
    sd = (sum((v - mu) ** 2 for v in vals) / len(vals)) ** 0.5
    if not sd:
        return {}
    return {k: (v - mu) / sd for k, v in s.items()}


def _d_yoy(s):
    out = {}
    for ym, v in s.items():
        p = s.get(_ym_add(ym, -12))
        if p:
            out[ym] = (v / p - 1) * 100
    return out


def _policy_series(start="201501"):
    """정권 더미 {YYYYMM: 값} — probe와 동일하게 2015.1부터 생성(z 창 일치)."""
    cur = _ym_now()
    out, ym = {}, start
    while ym <= cur:
        v = 0.0
        for a, b, val in _REGIMES:
            if ym >= a and (b is None or ym <= b):
                v = val
        out[ym] = v
        ym = _ym_add(ym, 1)
    return out


def _v5_months():
    """백테스트 개월 수 — 2016.1부터 현재월까지(동적 · 매월 1 증가)."""
    cur = _ym_now()
    return (int(cur[:4]) - 2016) * 12 + int(cur[4:6])


def _v5_components(data):
    """indicators 리스트 → v5 성분 [(key, nm, w, sign, lag, zdict)].
    · 정책레짐: 내부 캘린더(_REGIMES)에서 생성 — 스냅샷 비의존·항상 가용
    · 매수우위: buy_l(장기 · 2016~) 우선, 없으면 buy(2020~) 폴백 — 주간→월평균→레벨−100
    · 전세지수 YoY: jeonse_m(월간·장기) 우선, 없으면 주간 jeonse 폴백
    · 착공: 엔진 series(주거용 YoY·3M평균 · dates 포함) 그대로
    · 주담대: 금리 레벨(dates 포함) → 6개월 변화(pp)"""
    by = {it.get("key"): it for it in (data or [])}

    def _vals(k):
        return [None if v is None else float(v)
                for v in ((by.get(k) or {}).get("series") or [])]

    def _dated(k):
        it = by.get(k) or {}
        out = {}
        for dd, vv in zip(it.get("dates") or [], it.get("series") or []):
            dd = str(dd)
            if vv is not None and len(dd) >= 6 and "Q" not in dd:
                out[dd[:6]] = float(vv)
        return out

    _bl = _vals("buy_l") or _vals("buy")
    buy = {k: v - 100.0 for k, v in _weekly_to_monthly(_bl).items()}
    _jm = [v for v in _vals("jeonse_m") if v is not None]
    jlev = (dict(zip(_mon_labels(len(_jm)), _jm)) if len(_jm) >= 24
            else _weekly_to_monthly(_vals("jeonse")))
    raw = {"policy": _policy_series(), "buy": buy, "jeonse": _d_yoy(jlev),
           "starts": _dated("starts"), "mortgage": {}}
    mort = _dated("mortgage")
    for ym, v in mort.items():
        p = mort.get(_ym_add(ym, -6))
        if p is not None:
            raw["mortgage"][ym] = v - p
    comps = []
    for key, nm, w, sign, lag in _V5_DEF:
        z = _d_z(_d_ma3(raw.get(key) or {}))
        if z:
            comps.append((key, nm, w, sign, lag, z))
    return comps


def _v5_score_series(data, months=None):
    """월별 종합 강도 v5 배열(scarr[mb]=mb개월 전 점수 · 0=현재)과 현재 기여 칩.
    가용 성분만 가중 재정규화 · 시점별 성분 2개 미만이면 None(궤적 선 분절).
    성분 2개 미만 상시 or 현재 시점 판정 불가면 ([], []) — JS 구 방식 폴백."""
    months = months or _v5_months()
    comps = _v5_components(data)
    if len(comps) < 2:
        return [], []
    cur = _ym_now()
    rawarr = []
    for mb in range(months):
        ym = _ym_add(cur, -mb)
        num = den = 0.0
        n = 0
        for key, nm, w, sign, lag, z in comps:
            v = z.get(_ym_add(ym, -lag))
            if v is None:
                continue
            num += sign * w * v
            den += w
            n += 1
        rawarr.append(num / den if (n >= 2 and den) else None)
    vals = [v for v in rawarr if v is not None]
    if rawarr[0] is None or len(vals) < 12:
        return [], []
    mu = sum(vals) / len(vals)
    sd = (sum((v - mu) ** 2 for v in vals) / len(vals)) ** 0.5
    if not sd:
        return [], []
    scale = sd * _V5_SIG_MULT
    scarr = [None if v is None else round(_clip1((v - mu) / scale), 3)
             for v in rawarr]
    while scarr and scarr[-1] is None:     # 꼬리 결측 정리
        scarr.pop()
    chips = []
    for key, nm, w, sign, lag, z in comps:
        v = z.get(_ym_add(cur, -lag))
        if v is None:
            continue
        sig = sign * v                      # 성분 기여(z 스케일 · 가중 전)
        cls = "up" if sig > 0.15 else ("dn" if sig < -0.15 else "flat")
        chips.append({"nm": nm + (f"·lag{lag}" if lag else ""), "c": cls,
                      "v": f'{"+" if sig >= 0 else "−"}{abs(sig):.2f}',
                      "w": int(round(w * 100))})
    return scarr, chips


# v5 산식·가중치 스펙 — 배지(details) 안 표 렌더용. 산식 상수를 바꾸면 여기도 동기화.
_V5_SPEC = [
    ("정책레짐", "25%", "정권 더미 — 민주 <b>+1.0</b> / 보수 <b>−0.3</b>"
     "(박근혜→문재인→윤석열→이재명 · 교체월 반영) · lag 0 · 부호 + — 단독 corr +0.61 · "
     "가중 25%는 고정가중 스윕(10~50%)의 <b>무손실 최대치</b>(40%는 적중률 −9%p로 기각) · "
     "가설: 규제·공급억제 기조가 가격 압력·양극화로 이어진다는 편집 스펙"),
    ("매수우위", "22%", "매수우위지수 <b>레벨−100</b>(주간→월평균 · 2016~ 장기) · "
     "lag 0 · 부호 + — 심리 동행 최강"),
    ("착공", "22%", "주거용 착공 YoY(3개월 평균 · ECOS 전국) · <b>lag 29개월</b>"
     "(착공→입주 공급 시차) · 부호 − · corr −0.80 — <b>주의</b>: 소스가 2019.4~뿐이라 "
     "lag 반영 기여는 2021.9부터(단일 하락 사이클 의존) · YoY 기저효과 존재 · "
     "KOSIS 서울+경기 대안(레벨형·YoY)은 실측에서 선행성 미재현으로 기각"),
    ("전세지수", "16%", "KB 전세가격지수(월간) <b>전년동월비</b> · lag 0 · 부호 + — "
     "전세→매매 전이 경로"),
    ("주담대", "15%", "주담대 금리의 <b>6개월 변화(pp)</b> · <b>lag 15개월</b>"
     "(금리 충격 파급 시차) · 부호 −"),
]


def _v5_spec_foot_row():
    """'종합 강도 v5 산식·가중치' 배지 — foot_row와 동일한 details 배지 골격에
    표(지표·가중·산식)를 담는다. foot_badge는 detail을 HTML 이스케이프하므로
    표를 쓰려면 같은 클래스(.ui-foot 계열)로 직접 조립해야 한다."""
    rows = "".join(
        f'<tr><td style="padding:5px 10px 5px 0;font-weight:700;color:#5d6258;'
        f'white-space:nowrap;vertical-align:top">{nm}</td>'
        f'<td style="padding:5px 10px 5px 0;font-weight:700;color:#7E9A83;'
        f'white-space:nowrap;vertical-align:top">{w}</td>'
        f'<td style="padding:5px 0;vertical-align:top">{desc}</td></tr>'
        for nm, w, desc in _V5_SPEC)
    table = ('<table style="border-collapse:collapse;width:100%;font-size:11.5px;'
             'line-height:1.55"><thead><tr>'
             '<th style="text-align:left;padding:0 10px 6px 0;font-weight:800;'
             'color:#34352f;border-bottom:1px solid #E4E5DE">지표</th>'
             '<th style="text-align:left;padding:0 10px 6px 0;font-weight:800;'
             'color:#34352f;border-bottom:1px solid #E4E5DE">가중</th>'
             '<th style="text-align:left;padding:0 0 6px;font-weight:800;'
             'color:#34352f;border-bottom:1px solid #E4E5DE">산식</th>'
             '</tr></thead><tbody>' + rows + '</tbody></table>')
    foot = ('<div style="margin-top:7px;padding-top:7px;border-top:1px dashed #E4E5DE">'
            '종합 강도 v5 = 5지표를 <b>3개월 평활 → z-score → lag 시프트</b> 후 '
            '부호×가중 합산하고, 백테스트 창(2016.1~) 평균·표준편차로 정규화한 점수'
            '(0 = 2016년 이후 평균 국면 · ±1 = ±2σ) · 국면 임계 ±0.15(≈0.3σ) · '
            '결측 성분은 제외하고 가중 재정규화(착공은 2021.9부터 기여) · '
            '근거: starts_probe 2026-07-14 — 타깃=서울 매매지수 3개월 변화율 · '
            '창 2016.1~(정권 전환 3회 · n=126) · <b>corr +0.843 · 방향 적중률 79%</b> · '
            '정책 25%는 편집 스펙(실측가중은 18%) · 검토 후 기각 — KOSIS 서울+경기 착공'
            '(선행성 미재현) · M2(단일 사이클 과적합) · GDP(약함) · 전세가율(경계 인공물)</div>')
    return ('<div class="ui-fx ui-foot-row"><details class="ui-foot">'
            '<summary><span class="pill">종합 강도 v5 산식·가중치'
            '<span class="ic" aria-hidden="true">i</span></span></summary>'
            f'<div class="b">{table}{foot}</div></details></div>')


# 거시 4종 샘플(엔진 미수집 시 폴백 · 전부 예시 — 실데이터 수집 후 자동 교체)
_MACRO_SAMPLE = [
    {"key": "mortgage", "label": "주담대 금리", "sub": "예금은행 신규취급 가중평균 · 월간(ECOS) · 샘플",
     "unit": "%", "col": "#B65F5A",
     "series": [4.62, 4.55, 4.48, 4.44, 4.40, 4.38, 4.35, 4.30, 4.28, 4.31, 4.32, 4.32],
     "dates": ["202507", "202508", "202509", "202510", "202511", "202512",
               "202601", "202602", "202603", "202604", "202605", "202606"],
     "pair": {"label": "기준금리", "col": "#9a9b92",
              "series": [3.0, 3.0, 2.75, 2.75, 2.75, 2.5, 2.5, 2.5, 2.5, 2.5, 2.5, 2.5],
              "dates": ["202507", "202508", "202509", "202510", "202511", "202512",
                        "202601", "202602", "202603", "202604", "202605", "202606"]}},
    {"key": "m2", "label": "M2 증가율", "sub": "평잔·원계열 전년동월비 · 월간(ECOS) · 샘플",
     "unit": "%", "col": "#7E9A83",
     "series": [5.1, 5.3, 5.6, 5.8, 6.0, 6.1, 6.2, 6.1, 6.2, 6.3, 6.2, 6.2],
     "dates": ["202507", "202508", "202509", "202510", "202511", "202512",
               "202601", "202602", "202603", "202604", "202605", "202606"]},
    {"key": "gdp", "label": "GDP 성장률", "sub": "실질·계절조정·전기비 · 분기(ECOS) · 샘플",
     "unit": "%", "col": "#5A7CA0",
     "series": [0.6, 1.4, -0.1, 1.8],
     "dates": ["2025Q2", "2025Q3", "2025Q4", "2026Q1"]},
    {"key": "starts", "label": "주택 착공", "sub": "주거용 착공 YoY·3개월 평균 · 월간(ECOS) · 샘플",
     "unit": "%", "col": "#B89A5C",
     "series": [-22, -20, -19, -17, -16, -18, -19, -18, -17, -18, -18, -18],
     "dates": ["202507", "202508", "202509", "202510", "202511", "202512",
               "202601", "202602", "202603", "202604", "202605", "202606"]},
]


def _phase_from_series(data):
    """지표 시계열로 규칙기반 '시장 국면' 한 줄(비용 0)."""
    by = {it.get("key"): [v for v in (it.get("series") or []) if v is not None]
          for it in data}

    def tr(k):
        s = by.get(k) or []
        return (s[-1] - s[-2]) if len(s) >= 2 else 0

    seg = ["가격 " + ("상승" if tr("sale") > 0 else "하락" if tr("sale") < 0 else "보합")]
    if by.get("buy"):
        seg.append("심리 " + ("매수우위" if by["buy"][-1] >= 100 else "매도우위"))
    spans = '<span style="color:#C9CBC2;margin:0 2px">·</span>'.join(
        f'<span class="seg">{s}</span>' for s in seg)
    return f'<div class="re-phase"><b>시장 국면</b>{spans}</div>'


def _spark_svg(series, col, kind, baseline=None):
    w, h = 240, 46
    lo, hi = min(series), max(series)
    if baseline is not None:
        lo, hi = min(lo, baseline), max(hi, baseline)
    rng = (hi - lo) or 1

    def y(v):
        return h - 4 - (v - lo) / rng * (h - 8)

    if kind == "bar":
        mx = max(series) or 1
        bw = w / len(series)
        rects = "".join(
            f'<rect x="{i*bw+1:.1f}" y="{h-(v/mx)*(h-6):.1f}" '
            f'width="{bw-3:.1f}" height="{(v/mx)*(h-6):.1f}" fill="{col}" '
            f'opacity="{1 if i == len(series)-1 else 0.5:.1f}" rx="1"/>'
            for i, v in enumerate(series))
        return f'<svg class="re-spark" viewBox="0 0 {w} {h}">{rects}</svg>'

    pts = " ".join(f"{i/(len(series)-1)*w:.1f},{y(v):.1f}" for i, v in enumerate(series))
    base = ""
    if baseline is not None:
        by = y(baseline)
        base = (f'<line x1="0" y1="{by:.1f}" x2="{w}" y2="{by:.1f}" '
                f'stroke="#C9CBC2" stroke-width="1" stroke-dasharray="3 3"/>')
    dot = f'<circle cx="{w}" cy="{y(series[-1]):.1f}" r="2.6" fill="{col}"/>'
    return (f'<svg class="re-spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
            f'{base}<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2"/>'
            f'{dot}</svg>')


# ── 지도 탭 추이 차트 (코스피·코스닥 양식 · 매매·전세·전세가율 3종) ──────────
#   증시 '지수' 탭의 대형 차트(_big_index_chart)와 같은 룩: 영역+선 + 호버 십자선.
#   B안 = 포커스(큰 차트 1개) + 미니카드 3개(클릭 시 위에서 크게). 기간 2020~.
#   데이터는 지표와 동일한 DB 시계열(sale/jeonse/jr)을 재사용한다(별도 수집 없음).
#   매매·전세=KB 주간, 전세가율=KB 월간 → 카드마다 '주간/월간' 칩으로 명시(단위 통일).
_TREND_META = {
    "sale":   {"cad": "week",  "dp": "idx", "col": "#B65F5A", "sub": "서울 · KB"},
    "jeonse": {"cad": "week",  "dp": "idx", "col": "#5A7CA0", "sub": "서울 · KB"},
    "jr":     {"cad": "month", "dp": "pp",  "col": "#6E8FA8", "sub": "서울 · KB"},
}


_TREND_ORDER = ["sale", "jeonse", "jr"]


def _trend_series_3(data):
    """지표 시계열(list[{key,label,...,series}])에서 매매·전세·전세가율 3종만
    추려 추이 차트용 dict 리스트로 변환. 시계열 2개 미만은 제외."""
    by = {it.get("key"): it for it in (data or [])}
    out = []
    for k in _TREND_ORDER:
        it = by.get(k)
        if not it:
            continue
        series = [float(v) for v in (it.get("series") or []) if v is not None]
        if len(series) < 2:
            continue
        meta = _TREND_META[k]
        out.append({
            "k": k,
            "lab": it.get("label", k),
            "sub": meta["sub"],
            "cad": meta["cad"],
            "dp": meta["dp"],
            "unit": it.get("unit", ""),
            "col": it.get("col", meta["col"]),
            "real": [round(v, 2) for v in series],
        })
    return out


def _trend_component(inds, asof):
    import json as _json
    return (_TREND_HTML
            .replace("__INDS__", _json.dumps(inds, ensure_ascii=False))
            .replace("__ASOF__", asof))


def _render_trend_charts(data):
    """지도 탭 하단 추이 섹션. 데이터 없으면 캡션만."""
    from datetime import date
    inds = _trend_series_3(data)
    if not inds:
        st.caption("추이 데이터가 아직 없어요. 매일 아침 자동 수집 후 표시됩니다.")
        return
    asof = date.today().strftime("%Y-%m-%d")
    components.html(_trend_component(inds, asof), height=508, scrolling=False)
    st.markdown(foot_row(
        "KB 주간·월간",
        "매매·전세가격지수(KB 주간) · 전세가율(KB 월간) · 카드를 누르면 위에서 크게 · "
        "기간 토글 동기화 · 코스피·코스닥 차트와 동일 양식"), unsafe_allow_html=True)


_TREND_HTML = r'''<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
:root{--bg:#FCFCFA;--card:#fff;--ink:#34352f;--muted:#9a9b92;--line:#ECEDE7;--line2:#DEDED7;
 --sage:#A7BBA9;--sage2:#7E9A83;--up:#B65F5A;--dn:#5A7CA0;
 --kfont:'Pretendard',-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--kfont);font-size:14px;
 -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
.box{padding:2px 1px 6px}
.top{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px;margin-bottom:11px}
.top .cap{font-size:12px;color:var(--muted)}
.seg{display:inline-flex;border:1px solid var(--line2);border-radius:8px;overflow:hidden;background:var(--card)}
.seg button{border:none;background:none;padding:6px 13px;font-size:12px;color:var(--muted);cursor:pointer;
 border-right:1px solid var(--line);font-family:var(--kfont)}
.seg button:last-child{border-right:none}
.seg button.on{background:#EEF1EC;color:var(--ink);font-weight:700}
.cad{display:inline-block;font-size:10px;font-weight:800;letter-spacing:.02em;border-radius:6px;padding:2px 6px}
.cad.month{background:#EEF1EC;color:#5E7363}.cad.week{background:#F3EEE6;color:#8A6E45}
.delta{font-size:12px;font-weight:800;padding:3px 9px;border-radius:7px;white-space:nowrap}
.delta.up{color:var(--up);background:#FBEEED}.delta.dn{color:var(--dn);background:#EAF0F7}.delta.fl{color:var(--muted);background:#F1F2EC}
.hero{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:15px 17px 11px;margin-bottom:13px}
.hero-head{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;margin-bottom:5px}
.hero-lab{font-size:12.5px;font-weight:600;color:var(--muted);display:flex;gap:7px;align-items:center}
.hero-val{font-size:30px;font-weight:800;letter-spacing:-.03em;line-height:1;margin-top:3px}
.hero-val .u{font-size:14px;font-weight:600;color:var(--muted);margin-left:3px}
.minirow{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.mini{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:10px 12px 7px;cursor:pointer;
 transition:transform .16s,box-shadow .16s,border-color .16s}
.mini:hover{transform:translateY(-2px);box-shadow:0 6px 16px rgba(52,53,47,.08);border-color:var(--sage)}
.mini.on{border-color:var(--sage2);box-shadow:inset 0 0 0 1.5px var(--sage2)}
.mini .ml{font-size:11px;font-weight:600;color:var(--muted);display:flex;gap:5px;align-items:center}
.mini .mv{font-size:16px;font-weight:800;letter-spacing:-.02em;margin:3px 0 4px}
.mini .mv .u{font-size:9.5px;color:var(--muted);margin-left:1px}
.mini .delta{font-size:10px;padding:1px 6px}
.chart{position:relative;width:100%}
.chart svg{display:block;width:100%;overflow:visible}
.axis{font-size:9.5px;fill:var(--muted);font-family:var(--kfont)}
.tip{position:absolute;pointer-events:none;background:#fff;border:1px solid var(--line2);border-radius:8px;
 padding:6px 9px;font-size:11.5px;box-shadow:0 6px 18px rgba(52,53,47,.13);opacity:0;transform:translateY(3px);
 transition:opacity .12s,transform .12s;white-space:nowrap;z-index:6}
.tip b{font-weight:800}.tip .d{color:var(--muted);font-size:10.5px}
@media(max-width:680px){.minirow{grid-template-columns:repeat(3,1fr)}}
</style></head><body><div class="box">
  <div class="top">
    <div class="cap">KB 가격지수 실데이터 · 마우스 올리면 십자선 · 기간 2020~</div>
    <div class="seg" id="period">
      <button data-p="1Y">1년</button><button data-p="3Y">3년</button><button data-p="ALL" class="on">전체</button>
    </div>
  </div>
  <div class="hero">
    <div class="hero-head">
      <div><div class="hero-lab" id="hLab"></div><div class="hero-val" id="hVal"></div></div>
      <div class="delta" id="hDelta"></div>
    </div>
    <div class="chart" id="hChart"></div>
  </div>
  <div class="minirow" id="miniRow"></div>
</div>
<script>
const IND=__INDS__;
const ASOF=new Date("__ASOF__T00:00:00");
const MON=["1월","2월","3월","4월","5월","6월","7월","8월","9월","10월","11월","12월"];
const DAYS={"1Y":365,"3Y":1095,"ALL":1e9};
let period="ALL",focusK=IND.length?IND[0].k:null;
function byK(k){return IND.find(d=>d.k===k);}
function makeSeries(ind,p){
 const step=ind.cad==="month"?30:7;
 const need=p==="ALL"?ind.real.length:Math.min(ind.real.length,Math.round(DAYS[p]/step)+1);
 const vals=ind.real.slice(-need);
 return vals.map((v,i)=>({t:new Date(ASOF.getTime()-(vals.length-1-i)*step*86400000),v}));
}
function fmtV(ind,v){return (Math.round(v*10)/10).toFixed(1);}
function deltaTxt(ind,pts){const a=pts[0].v,b=pts[pts.length-1].v;
 if(ind.dp==="pp"){const d=b-a;return{cls:d>0.05?"up":d<-0.05?"dn":"fl",txt:(d>=0?"+":"")+(Math.round(d*10)/10)+"p"};}
 const d=(b-a)/a*100;return{cls:d>0.05?"up":d<-0.05?"dn":"fl",txt:(d>=0?"+":"")+(Math.round(d*10)/10)+"%"};}
function drawChart(host,ind,pts,h,longR){
 const W=600,PAD={l:4,r:4,t:8,b:18};
 const xs=i=>PAD.l+i/(pts.length-1)*(W-PAD.l-PAD.r);
 const lo=Math.min.apply(null,pts.map(p=>p.v)),hi=Math.max.apply(null,pts.map(p=>p.v));
 const span=(hi-lo)||1;const y0=lo-span*0.12,y1=hi+span*0.12;
 const ys=v=>PAD.t+(1-(v-y0)/(y1-y0))*(h-PAD.t-PAD.b);
 const col=ind.col;
 let path=pts.map((p,i)=>(i?"L":"M")+xs(i).toFixed(1)+" "+ys(p.v).toFixed(1)).join(" ");
 let area=path+" L"+xs(pts.length-1).toFixed(1)+" "+(h-PAD.b)+" L"+xs(0).toFixed(1)+" "+(h-PAD.b)+" Z";
 let tk="",last=null;
 pts.forEach((p,i)=>{const key=longR?p.t.getFullYear():p.t.getMonth();
  if(key!==last){last=key;const x=xs(i);if(x>12&&x<W-12){
   const lab=longR?("'"+String(p.t.getFullYear()).slice(2)):MON[p.t.getMonth()];
   tk+='<text class="axis" x="'+x.toFixed(1)+'" y="'+(h-5)+'" text-anchor="middle">'+lab+'</text>';}}});
 host.innerHTML='<svg viewBox="0 0 '+W+' '+h+'" preserveAspectRatio="none" style="height:'+h+'px">'
  +'<path d="'+area+'" fill="'+col+'" opacity="0.11"/>'
  +'<path d="'+path+'" fill="none" stroke="'+col+'" stroke-width="2" stroke-linejoin="round"/>'
  +'<line class="vx" x1="0" x2="0" y1="'+PAD.t+'" y2="'+(h-PAD.b)+'" stroke="#B9BBB0" stroke-width="1" stroke-dasharray="3 3" opacity="0"/>'
  +'<circle class="cp" r="3.4" fill="'+col+'" opacity="0"/>'+tk+'</svg>';
 const svg=host.querySelector("svg"),vx=host.querySelector(".vx"),cp=host.querySelector(".cp");
 let tip=host.querySelector(".tip");if(!tip){tip=document.createElement("div");tip.className="tip";host.appendChild(tip);}
 svg.onmousemove=e=>{const r=svg.getBoundingClientRect();const px=(e.clientX-r.left)/r.width*W;
  let i=Math.round((px-PAD.l)/((W-PAD.l-PAD.r))*(pts.length-1));i=Math.max(0,Math.min(pts.length-1,i));
  const x=xs(i),yv=ys(pts[i].v);
  vx.setAttribute("x1",x);vx.setAttribute("x2",x);vx.setAttribute("opacity","1");
  cp.setAttribute("cx",x);cp.setAttribute("cy",yv);cp.setAttribute("opacity","1");
  const d=pts[i].t;tip.innerHTML="<b>"+fmtV(ind,pts[i].v)+ind.unit+"</b> <span class=\"d\">"+d.getFullYear()+"."+String(d.getMonth()+1).padStart(2,"0")+"</span>";
  tip.style.opacity="1";tip.style.transform="translateY(0)";
  let tx=(x/W)*r.width+10;if(tx>r.width-110)tx-=120;tip.style.left=tx+"px";tip.style.top=(yv/h*r.height-30)+"px";};
 svg.onmouseleave=()=>{vx.setAttribute("opacity","0");cp.setAttribute("opacity","0");tip.style.opacity="0";};
}
function render(){
 const longR=period!=="1Y";
 document.getElementById("miniRow").innerHTML=IND.map(ind=>{const pts=makeSeries(ind,period);const dt=deltaTxt(ind,pts);
  return '<div class="mini '+(ind.k===focusK?"on":"")+'" data-k="'+ind.k+'"><div class="ml"><span class="cad '+ind.cad+'">'+(ind.cad==="month"?"월간":"주간")+'</span>'+ind.lab+'</div>'
   +'<div class="mv">'+fmtV(ind,ind.real[ind.real.length-1])+'<span class="u">'+ind.unit+'</span></div>'
   +'<div class="delta '+dt.cls+'">'+dt.txt+'</div></div>';}).join("");
 document.querySelectorAll(".mini").forEach(el=>el.onclick=()=>{focusK=el.dataset.k;render();});
 const ind=byK(focusK);if(!ind)return;const pts=makeSeries(ind,period);const dt=deltaTxt(ind,pts);
 document.getElementById("hLab").innerHTML='<span class="cad '+ind.cad+'">'+(ind.cad==="month"?"월간":"주간")+'</span>'+ind.lab+' · '+ind.sub;
 document.getElementById("hVal").innerHTML=fmtV(ind,ind.real[ind.real.length-1])+'<span class="u">'+ind.unit+'</span>';
 const hd=document.getElementById("hDelta");hd.className="delta "+dt.cls;hd.textContent=dt.txt;
 drawChart(document.getElementById("hChart"),ind,pts,210,longR);
}
document.querySelectorAll("#period button").forEach(b=>b.onclick=()=>{
 document.querySelectorAll("#period button").forEach(x=>x.classList.remove("on"));b.classList.add("on");period=b.dataset.p;render();});
render();
(function(){function _fit(){try{var h=Math.ceil(document.body.getBoundingClientRect().height)+2;if(window.frameElement){window.frameElement.style.height=h+"px";window.frameElement.setAttribute("height",h);var pe=window.frameElement.parentElement;if(pe&&pe.getBoundingClientRect().height<h){pe.style.height=h+"px";}}}catch(e){}}window.addEventListener("load",_fit);setTimeout(_fit,150);setTimeout(_fit,600);setTimeout(_fit,1500);window.addEventListener("resize",_fit);try{new ResizeObserver(_fit).observe(document.body);}catch(e){}})();
</script></body></html>'''


_GROUP_ORDER = [
    ("선행·심리", "시장 방향이 먼저 움직이는 신호"),
    ("가격(동행)", "현재 가격 수준"),
    ("공급·펀더멘털", "중기 수급"),
    ("금융", "구매력·자금조달"),
]


def _delta_html(series, dunit):
    """직전값 대비 변화 → 화살표 칩(빨강=상승/파랑=하락)."""
    if not series or len(series) < 2:
        return ""
    d = series[-1] - series[-2]
    cls = "up" if d > 5e-4 else ("dn" if d < -5e-4 else "fl")
    arr = "▲" if cls == "up" else ("▼" if cls == "dn" else "–")
    mag = abs(d)
    txt = f"{mag:,.0f}" if dunit == "건" else (f"{mag:.2f}".rstrip("0").rstrip("."))
    return f'<span class="re-delta {cls}">{arr} {txt}{dunit}</span>'


def _market_phase(cards):
    """지표 시리즈로 규칙기반 '시장 국면' 한 줄 요약(비용 0)."""
    by = {c["label"]: c for c in cards}

    def trend(label):
        s = by.get(label, {}).get("series")
        return (s[-1] - s[-2]) if s and len(s) >= 2 else 0

    seg = []
    if "주간 실거래량(수도권)" in by:
        d = trend("주간 실거래량(수도권)")
        seg.append("거래 " + ("회복세" if d > 0 else "둔화" if d < 0 else "보합"))
    if "매매 주간지수(서울)" in by:
        d = trend("매매 주간지수(서울)")
        seg.append("가격 " + ("상승" if d > 0 else "하락" if d < 0 else "보합"))
    if "매수우위지수" in by:
        v = by["매수우위지수"]["series"][-1]
        seg.append("심리 " + ("매수우위" if v >= 100 else "매도우위"))
    if "미분양(전국)" in by:
        d = trend("미분양(전국)")
        seg.append("공급 부담 " + ("완화" if d < 0 else "확대" if d > 0 else "보합"))
    if "주담대 금리(가중평균)" in by:
        d = trend("주담대 금리(가중평균)")
        seg.append("금리 " + ("하락" if d < 0 else "상승" if d > 0 else "보합"))
    spans = '<span style="color:#C9CBC2;margin:0 2px">·</span>'.join(
        f'<span class="seg">{s}</span>' for s in seg)
    return f'<div class="re-phase"><b>시장 국면</b>{spans}</div>'


# ── 지표 추이 차트 (포커스 + 스몰멀티플 · 기간 1M/3M/1Y/5Y) ───────
_INDV2_HTML = r'''<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
:root{--bg:#FCFCFA;--card:#fff;--ink:#34352f;--muted:#9a9b92;--line:#ECEDE7;--line2:#DEDED7;
 --sage:#A7BBA9;--sage2:#7E9A83;--up:#B65F5A;--upT:#FBEEED;--dn:#5A7CA0;--dnT:#EAF0F7;--sum:#F6F7F2;
 --kfont:'Pretendard',-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--kfont);font-size:14px;-webkit-font-smoothing:antialiased}
.box{padding:2px 1px 6px}
.cycle{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:15px 17px;margin-bottom:15px}
.cyc-top{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin-bottom:11px}
.cyc-top .t{font-size:13px;font-weight:800}
.cyc-top .now{font-size:12px;color:var(--muted)}.cyc-top .now b{color:var(--up)}
.stages{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:9px}
.stage{text-align:center;font-size:12px;font-weight:700;color:var(--muted);padding:9px 4px;border-radius:10px;background:#F4F5F0;border:1px solid transparent}
.stage.on{background:#FBEEED;color:var(--up);border-color:#E7C9C5}
.stage small{display:block;font-size:9.5px;font-weight:600;color:var(--muted);margin-top:1px}
.stage.on small{color:#B07A75}
.cyc-read{font-size:11px;color:var(--muted);line-height:1.5;margin-top:9px;padding-top:8px;border-top:1px solid var(--line)}.cyc-read b{color:var(--ink)}
.cyc-why{margin-top:10px}
.why-lab{font-size:9.5px;font-weight:700;color:var(--sage2);margin-bottom:6px}
.why-chips{display:flex;flex-wrap:wrap;gap:6px}
.why-chip{display:inline-flex;flex-direction:column;align-items:flex-start;gap:3px;font-size:11px;font-weight:700;padding:5px 9px 6px;border-radius:10px;border:1px solid var(--line);background:var(--card)}
.why-chip.up{color:var(--up)}.why-chip.dn{color:var(--dn)}.why-chip.fl{color:var(--muted)}
.why-chip .wc-hd{display:inline-flex;align-items:center;gap:3px}
.why-chip .chip-spk{width:54px;height:16px;display:block}
.why-summ{font-size:10.5px;color:var(--muted);margin-top:8px;line-height:1.55}
.why-summ b{font-weight:800;color:var(--ink)}.why-summ b.up{color:var(--up)}.why-summ b.dn{color:var(--dn)}
.cyc-gauge{margin-top:11px}
.str-wrap{margin:2px 0 4px}
.str-chart{width:100%;height:auto;display:block}
.str-chart .sc-ax{fill:#b6b7ae;font-size:8px;font-weight:700}
.str-cap{font-size:10px;color:var(--muted);margin-top:2px}
.str-cap b{font-weight:800;color:var(--ink)}.str-cap b.up{color:var(--up)}.str-cap b.dn{color:var(--dn)}
.cg-lab{font-size:9.5px;font-weight:700;color:var(--sage2);margin-bottom:7px}
.cg-wrap{position:relative}
.cg-track{display:flex;height:9px;border-radius:5px;overflow:hidden}
.cg-zone{height:100%}
.cg-needle{position:absolute;top:-3px;width:2.5px;height:15px;background:var(--ink);border-radius:2px;transform:translateX(-50%);box-shadow:0 0 0 2px var(--card)}
.cg-ticks{position:relative;height:12px;margin-top:3px}
.cg-ticks span{position:absolute;font-size:8.5px;font-weight:700;color:var(--muted);transform:translateX(-50%);white-space:nowrap}
.cg-zlab{position:relative;height:13px;margin-top:0}
.cg-zlab span{position:absolute;transform:translateX(-50%);font-size:9px;font-weight:700;color:var(--muted);white-space:nowrap}
.cg-zlab span.on{color:var(--ink)}
.sec{font-size:11.5px;font-weight:700;letter-spacing:.04em;color:var(--muted);text-transform:uppercase;margin:18px 2px 11px;display:flex;align-items:center;gap:9px}
.sec::after{content:"";flex:1;height:1px;background:var(--line)}
.core{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px}
.cc{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:13px 14px 11px;transition:border-color .15s,transform .15s,box-shadow .15s}
.cc:hover{border-color:var(--sage);transform:translateY(-1px);box-shadow:0 6px 16px rgba(52,53,47,.07)}
.cc-top{display:flex;align-items:center;justify-content:space-between;gap:6px}
.cc-name{font-size:12.5px;font-weight:800;color:var(--ink)}
.cc-sub{font-size:10px;font-weight:600;color:var(--muted);margin-top:2px}
.cc-val{font-size:23px;font-weight:800;letter-spacing:-.02em;margin:7px 0 2px}
.cc-val .u{font-size:12px;font-weight:600;color:var(--muted);margin-left:2px}
.cc-val .cc-bl{font-size:9.5px;color:var(--muted);font-weight:700;margin-left:6px}
.dchip{display:inline-flex;align-items:baseline;gap:3px;font-size:11px;font-weight:800;padding:2px 7px;border-radius:7px;margin-left:7px;vertical-align:2px}
.dchip.up{color:var(--up);background:var(--upT)}.dchip.dn{color:var(--dn);background:var(--dnT)}.dchip.fl{color:var(--muted);background:#F1F2EC}
.dchip .lab{font-weight:600;font-size:9px;opacity:.85}
.r-d{display:block;font-size:9.5px;font-weight:800;margin-top:1px}
.r-d.up{color:var(--up)}.r-d.dn{color:var(--dn)}.r-d.fl{color:var(--muted)}
.r-d .lab{color:var(--muted);font-weight:600;font-size:8.5px;margin-left:2px}
.cc-interp{font-size:11px;color:var(--muted);line-height:1.5;margin-top:7px}
.mini{width:100%;height:auto;display:block;margin:7px 0 2px;overflow:visible}
.mc-ax{font-size:9px;fill:var(--muted)}
.sig{display:inline-flex;align-items:center;gap:4px;font-size:10.5px;font-weight:800;padding:2px 8px;border-radius:20px;white-space:nowrap}
.sig.up{color:var(--up);background:var(--upT)}.sig.dn{color:var(--dn);background:var(--dnT)}.sig.fl{color:var(--muted);background:#F1F2EC}
.sig.sm{font-size:10px;padding:2px 7px}
.sig .inv{font-size:8.5px;font-weight:700;color:var(--muted);background:#fff;border:1px solid var(--line2);border-radius:4px;padding:0 3px;margin-left:2px}
.grp{margin-top:15px}
.glab{font-size:12px;font-weight:800;color:var(--sage2);margin:0 2px 8px;display:flex;align-items:baseline;gap:7px}
.glab em{font-style:normal;font-size:11px;font-weight:600;color:var(--muted)}
.rows{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.row{display:grid;grid-template-columns:1.5fr 90px 1fr 78px;align-items:center;gap:10px;padding:9px 13px;border-bottom:1px solid var(--line)}
.row:last-child{border-bottom:none}
.row.pend{background:var(--sum)}
.r-name{font-size:12.5px;font-weight:700;color:var(--ink)}
.r-name small{display:block;font-size:10px;font-weight:500;color:var(--muted);margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.r-val{font-size:13px;font-weight:800;text-align:right}.r-val .u{font-size:10px;color:var(--muted);font-weight:600;margin-left:1px}
.r-spark{width:100%;height:36px;display:block}
.r-mid{display:block;min-width:0}
.ig{margin-top:9px}
.ig-lab{display:flex;justify-content:space-between;align-items:baseline;font-size:9.5px;color:var(--muted);margin-bottom:3px}
.ig-lab b{color:var(--ink);font-weight:800;font-size:10px}
.ig-track{position:relative;height:7px;background:#EFF0EA;border-radius:4px}
.ig-1y{position:absolute;top:0;bottom:0;background:#D6DFD3;border-radius:4px}
.ig-base{position:absolute;top:-2px;bottom:-2px;width:1.5px;background:#B9BBB0}
.ig-mk{position:absolute;top:50%;width:11px;height:11px;border-radius:50%;border:2px solid #fff;transform:translate(-50%,-50%);box-shadow:0 0 0 1px rgba(52,53,47,.08)}
.ig-ends{display:flex;justify-content:space-between;font-size:8.5px;color:#B7B8B0;margin-top:2px;font-weight:600}
.rg{margin-top:4px;padding:0 1px}
.rg-track{position:relative;height:5px;background:#EFF0EA;border-radius:3px}
.rg-1y{position:absolute;top:0;bottom:0;background:#D6DFD3;border-radius:3px}
.rg-base{position:absolute;top:-1px;bottom:-1px;width:1.5px;background:#C2C4B9}
.rg-mk{position:absolute;top:50%;width:8px;height:8px;border-radius:50%;border:1.5px solid #fff;transform:translate(-50%,-50%)}
.rsig{display:flex;flex-direction:column;align-items:flex-end;gap:2px}
.rg-pct{font-size:8.5px;color:var(--muted);font-weight:700;white-space:nowrap}
.pend-tag{display:inline-flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;color:var(--muted);background:#fff;border:1px dashed var(--line2);padding:3px 8px;border-radius:7px}
.row.pend.chk{background:#FCF7EC}
.chk-tag{display:inline-flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;color:#9A7B43;background:#FBF5E6;border:1px solid #E7D8B4;padding:3px 8px;border-radius:7px}
.cc.cc-miss{border-style:dashed;background:var(--sum)}
.cc.cc-miss .cc-val{color:var(--muted);font-weight:700}
.foot{font-size:11px;color:var(--muted);margin:14px 2px 2px;line-height:1.5}
.price{display:grid;grid-template-columns:repeat(2,1fr);gap:11px}
.pc{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:13px 15px 11px}
.pc-top{display:flex;align-items:baseline;justify-content:space-between;gap:8px}
.pc-reg{font-size:13px;font-weight:800;color:var(--ink)}
.pc-tag{font-size:10px;font-weight:700;color:var(--muted);white-space:nowrap}
.pc-val{font-size:25px;font-weight:800;letter-spacing:-.02em;margin:8px 0 1px;color:var(--ink)}
.pc-val .u{font-size:12px;font-weight:600;color:var(--muted);margin-left:1px}
.pc-val .lab{font-size:10px;font-weight:800;color:var(--sage2);background:#EEF3EF;border-radius:5px;padding:1px 5px;margin-left:7px;vertical-align:middle}
.pc-mean{font-size:11.5px;color:var(--muted);font-weight:600}
.pc-mean b{color:var(--ink);font-weight:800}
.pc-leg{display:flex;gap:11px;margin-top:7px;font-size:10px;font-weight:700;color:var(--muted)}
.pc-leg i{display:inline-block;width:14px;height:0;vertical-align:middle;margin-right:4px;border-top:2.2px solid var(--sage2)}
.pc-leg i.dash{border-top:2.2px dashed #B65F5A}
.pc-mom{font-size:10.5px;font-weight:800;margin:0 0 2px}
.pc-mom.up{color:var(--up)}.pc-mom.dn{color:var(--dn)}.pc-mom.fl{color:var(--muted)}
.pc-mom small{font-weight:600;color:var(--muted);font-size:9px;margin-left:2px}
@media(max-width:680px){.core{grid-template-columns:1fr}.row{grid-template-columns:1.3fr 96px 74px}.r-mid{display:none}.price{gap:8px}}
</style></head><body><div class="box">
  <div class="cycle">
    <div class="cyc-top"><span class="t">부동산 사이클 위치</span>
      <span class="now">선행·심리 종합 → 현재 <b id="nowStage"></b></span></div>
    <div class="stages" id="stages"></div>
    <div class="cyc-why" id="cycWhy"></div>
    <div class="cyc-gauge" id="cycGauge"></div>
    <div class="cyc-read" id="cycRead"></div>
  </div>
  <div class="sec" id="priceSec" style="display:none">현재 아파트 매매가격</div>
  <div class="price" id="price"></div>
  <div class="foot" id="foot"></div>
</div>
<script>
const IND=__IND__,PEND=__PEND__,G=__G__;
const SCARR=__SCARR__,V3SIG=__V3SIG__;
const PRICE=__PRICE__;
const ASOF=new Date("__ASOF__T00:00:00");
const MON=["1월","2월","3월","4월","5월","6월","7월","8월","9월","10월","11월","12월"];
const GORDER=["lead","coin","supply"];
const CORE=["outlook"];
function byK(k){return IND.find(d=>d.k===k);}
function makeSeries(m){const step=m.cad==="month"?30:7;
 const need=Math.min(m.real.length,Math.round(365/step)+1);
 const vals=m.real.slice(-need);
 return vals.map((v,i)=>({t:new Date(ASOF.getTime()-(vals.length-1-i)*step*86400000),v}));}
function fmtV(m,v){const b=Math.abs(m.base||v);if(b>=1000)return Math.round(v).toLocaleString();
 if(b<10)return (Math.round(v*100)/100).toFixed(2);return (Math.round(v*10)/10).toFixed(1);}
function signal(m,pts){const a=pts[0].v,b=pts[pts.length-1].v;let dir=(b-a)/Math.abs(a||1);
 if(m.inv)dir=-dir;
 if(m.baseline!=null){const lvl=(b-m.baseline)/m.baseline;dir=dir*0.6+lvl*0.8;}
 const cls=dir>0.012?"up":dir<-0.012?"dn":"fl";
 return {cls,txt:cls==="up"?"상승 신호":cls==="dn"?"하락 신호":"중립",score:dir};}
function arrow(c){return c==="up"?"▲":c==="dn"?"▼":"●";}
function shortTxt(c){return c==="up"?"상승":c==="dn"?"하락":"중립";}
function monthTicks(pts){let ticks=[],lastM=null;
 pts.forEach((p,i)=>{const mo=p.t.getMonth();if(mo!==lastM){ticks.push({i,mo});lastM=mo;}});
 if(ticks.length>7){const st=Math.ceil(ticks.length/7);ticks=ticks.filter((_,j)=>j%st===0);}
 return ticks;}
function miniChart(m,pts){const W=280,H=64,P={l:4,r:6,t:8,b:17};
 const xs=i=>P.l+i/(pts.length-1)*(W-P.l-P.r);
 const vv=pts.map(p=>p.v);let lo=Math.min.apply(null,vv),hi=Math.max.apply(null,vv);
 if(m.baseline!=null){lo=Math.min(lo,m.baseline);hi=Math.max(hi,m.baseline);}
 const sp=(hi-lo)||1,y0=lo-sp*0.16,y1=hi+sp*0.16;
 const ys=v=>P.t+(1-(v-y0)/(y1-y0))*(H-P.t-P.b);
 const path=pts.map((p,i)=>(i?"L":"M")+xs(i).toFixed(1)+" "+ys(p.v).toFixed(1)).join(" ");
 const area=path+" L"+xs(pts.length-1).toFixed(1)+" "+(H-P.b)+" L"+xs(0).toFixed(1)+" "+(H-P.b)+" Z";
 let bl="";if(m.baseline!=null){const by=ys(m.baseline).toFixed(1);
  bl='<line x1="'+P.l+'" y1="'+by+'" x2="'+(W-P.r)+'" y2="'+by+'" stroke="#C9CBC2" stroke-width="1" stroke-dasharray="4 4"/>';}
 const ax='<line x1="'+P.l+'" y1="'+(H-P.b)+'" x2="'+(W-P.r)+'" y2="'+(H-P.b)+'" stroke="var(--line2)" stroke-width="1"/>';
 let tk=monthTicks(pts).map(t=>{const x=xs(t.i);
  return '<line x1="'+x.toFixed(1)+'" x2="'+x.toFixed(1)+'" y1="'+(H-P.b)+'" y2="'+(H-P.b+3)+'" stroke="#C9CBC2" stroke-width="1"/>'
   +'<text class="mc-ax" x="'+x.toFixed(1)+'" y="'+(H-3)+'" text-anchor="middle">'+MON[t.mo]+'</text>';}).join("");
 return '<svg class="mini" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="xMidYMid meet">'
  +'<path d="'+area+'" fill="'+m.col+'" opacity="0.10"/>'+bl+ax
  +'<path d="'+path+'" fill="none" stroke="'+m.col+'" stroke-width="1.9" stroke-linejoin="round" stroke-linecap="round"/>'
  +tk+'</svg>';}
function deltaOf(m){const r=m.real||[];if(r.length<2)return null;
 const d=r[r.length-1]-r[r.length-2],b=Math.abs(m.base||0),a=Math.abs(d);
 const s=b>=1000?Math.round(a).toLocaleString():b<10?(Math.round(a*100)/100).toFixed(2):(Math.round(a*10)/10).toFixed(1);
 const cls=a<1e-9?"fl":d>0?"up":"dn";
 return {cls,abs:s,signed:(d>0?"+":d<0?"−":"±")+s,lab:m.cad==="month"?"전월":"전주"};}
function arrowD(c){return c==="up"?"▲":c==="dn"?"▼":"±";}
// ── 사이클 판정근거 강화용 헬퍼 ───────────────────────────────────
//  (1) 지표 칩에 붙일 초소형 스파크(라벨 없이 선만) — '왜 이 방향인지' 시각 근거.
function chipSpark(m){const pts=makeSeries(m);if(pts.length<2)return "";
 const W=54,H=16,vv=pts.map(p=>p.v);let lo=Math.min.apply(null,vv),hi=Math.max.apply(null,vv);
 if(m.baseline!=null){lo=Math.min(lo,m.baseline);hi=Math.max(hi,m.baseline);}
 const sp=(hi-lo)||1,y0=lo-sp*0.12,y1=hi+sp*0.12;
 const xs=i=>1+i/(pts.length-1)*(W-2),ys=v=>1+(1-(v-y0)/((y1-y0)||1))*(H-2);
 const path=pts.map((p,i)=>(i?"L":"M")+xs(i).toFixed(1)+" "+ys(p.v).toFixed(1)).join(" ");
 let bl="";if(m.baseline!=null){const by=ys(m.baseline).toFixed(1);
  bl='<line x1="1" y1="'+by+'" x2="'+(W-1)+'" y2="'+by+'" stroke="#CDCFC6" stroke-width="0.8" stroke-dasharray="3 3"/>';}
 const col=signal(m,pts).cls==="up"?"var(--up)":signal(m,pts).cls==="dn"?"var(--dn)":"#9a9b92";
 return '<svg class="chip-spk" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none">'+bl
  +'<path d="'+path+'" fill="none" stroke="'+col+'" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>';}
//  (2) 종합 강도 추이 미니차트(시안1·격자 스타일) — cycScore(mb)를 최근 n개월 돌려
//      만든 강도 시계열. 옅은 y축 격자 + 눈금 라벨 + 0 기준선(점선) + 각 점 마커 +
//      x축 시점 라벨(전역 ASOF 기준 월간 재구성). 라인색은 현재값 부호(상승 빨강/하락 파랑).
function strengthChart(scoreAt,n,T){
 const seq=[];for(let mb=n-1;mb>=0;mb--)seq.push(scoreAt(mb));  // 과거→현재
 if(seq.length<2)return "";
 const W=560,H=190,P={l:42,r:12,t:18,b:28};
 // y축: 0 대칭 + 데이터·중립대(±T)를 담는 '보기 좋은' 눈금 스텝 선정.
 const amp=Math.max(Math.abs(Math.min.apply(null,seq)),Math.abs(Math.max.apply(null,seq)),T*1.6,0.03);
 const steps=[0.05,0.1,0.2,0.5,1];let step=steps[steps.length-1];
 for(const s of steps){if(amp/s<=2.2){step=s;break;}}   // 위아래 2눈금 내로
 const top=Math.ceil(amp/step)*step,y0=-top,y1=top;
 const xs=i=>P.l+(seq.length<=1?0:i/(seq.length-1)*(W-P.l-P.r));
 const ys=v=>P.t+(1-(v-y0)/((y1-y0)||1))*(H-P.t-P.b);
 // 격자 + y눈금 라벨(위→아래로 top..-top, step 간격)
 const dp=step<0.1?2:step<1?1:0;   // 0.05→2자리, 0.1/0.2/0.5→1자리, 1→0자리
 let grid="",ylab="";
 for(let v=top;v>=-top-1e-9;v-=step){
  const y=ys(v),z=Math.abs(v)<1e-9;
  grid+='<line x1="'+P.l+'" y1="'+y.toFixed(1)+'" x2="'+(W-P.r)+'" y2="'+y.toFixed(1)+'" stroke="'
       +(z?"#B9BBB0":"#EDEEE8")+'" stroke-width="1"'+(z?' stroke-dasharray="4 3"':'')+'/>';
  const txt=z?"0":((v>0?"+":"−")+Math.abs(v).toFixed(dp));
  ylab+='<text class="sc-ax" x="'+(P.l-6)+'" y="'+(y+3).toFixed(1)+'" text-anchor="end"'
       +(z?' style="fill:#8a8b82"':'')+'>'+txt+'</text>';
 }
 // x축 시점 라벨(전역 ASOF에서 월간 30일 스텝으로 역산 · 처음/중간/끝 3개)
 const MONS=(typeof ASOF!=="undefined")?ASOF:new Date();
 function dlab(i){const d=new Date(MONS.getTime()-(seq.length-1-i)*30*86400000);
  return "'"+String(d.getFullYear()).slice(2)+"."+(d.getMonth()+1);}
 const mid=Math.floor((seq.length-1)/2);
 const xlab='<text class="sc-ax" x="'+xs(0).toFixed(1)+'" y="'+(H-9)+'" text-anchor="start">'+dlab(0)+'</text>'
  +'<text class="sc-ax" x="'+xs(mid).toFixed(1)+'" y="'+(H-9)+'" text-anchor="middle">'+dlab(mid)+'</text>'
  +'<text class="sc-ax" x="'+xs(seq.length-1).toFixed(1)+'" y="'+(H-9)+'" text-anchor="end">'+dlab(seq.length-1)+'</text>';
 // 라인 + 각 점 마커(현재값 부호 색)
 const cur=seq[seq.length-1];const col=cur>=0?"#B65F5A":"#5A7CA0";
 const line=seq.map((v,i)=>(i?"L":"M")+xs(i).toFixed(1)+" "+ys(v).toFixed(1)).join(" ");
 let dots="";
 seq.forEach((v,i)=>{const last=i===seq.length-1;
  dots+='<circle cx="'+xs(i).toFixed(1)+'" cy="'+ys(v).toFixed(1)+'" r="'+(last?4:2.8)+'" fill="'+col+'"'
   +(last?' stroke="#FCFCFA" stroke-width="1.6"':'')+'/>';});
 return '<svg class="str-chart" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="xMidYMid meet">'
  +grid+ylab
  +'<path d="'+line+'" fill="none" stroke="'+col+'" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
  +dots+xlab+'</svg>';}
function sparkSVG(m,pts){const W=200,H=38,P={l:3,r:3,t:3,b:13};
 const xs=i=>P.l+(pts.length<=1?0:i/(pts.length-1)*(W-P.l-P.r));
 const vv=pts.map(p=>p.v);let lo=Math.min.apply(null,vv),hi=Math.max.apply(null,vv);
 const sp=(hi-lo)||1,pd=sp*0.14,y0=lo-pd,y1=hi+pd;
 const ys=v=>P.t+(1-(v-y0)/((y1-y0)||1))*(H-P.t-P.b);
 const path=pts.map((p,i)=>(i?"L":"M")+xs(i).toFixed(1)+" "+ys(p.v).toFixed(1)).join(" ");
 const ax='<line x1="'+P.l+'" y1="'+(H-P.b)+'" x2="'+(W-P.r)+'" y2="'+(H-P.b)+'" stroke="var(--line2)" stroke-width="1"/>';
 let tks=monthTicks(pts);
 if(tks.length>3)tks=[tks[0],tks[Math.floor((tks.length-1)/2)],tks[tks.length-1]];
 const tk=tks.map(function(t,j){const x=xs(t.i),an=j===0?"start":j===tks.length-1?"end":"middle";
   return '<line x1="'+x.toFixed(1)+'" x2="'+x.toFixed(1)+'" y1="'+(H-P.b)+'" y2="'+(H-P.b+2.5)+'" stroke="#C9CBC2"/>'
    +'<text class="mc-ax" x="'+x.toFixed(1)+'" y="'+(H-2)+'" text-anchor="'+an+'">'+MON[t.mo]+'</text>';}).join("");
 return '<svg class="r-spark" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="xMidYMid meet">'
  +ax+'<path d="'+path+'" fill="none" stroke="'+m.col+'" stroke-width="1.7" stroke-linejoin="round" stroke-linecap="round"/>'+tk+'</svg>';}
function gaugeOf(m){const r=m.real||[];if(r.length<3)return null;
 const lo=Math.min.apply(null,r),hi=Math.max.apply(null,r);if(hi-lo<1e-9)return null;
 const cur=r[r.length-1],pos=Math.max(0,Math.min(1,(cur-lo)/(hi-lo)));
 const yr=makeSeries(m).map(p=>p.v),ylo=Math.min.apply(null,yr),yhi=Math.max.apply(null,yr);
 const top=Math.round((1-pos)*100);
 const tag=pos>=0.99?"전 기간 최고":pos<=0.01?"전 기간 최저":"상위 "+top+"%";
 const baseP=(m.baseline!=null&&m.baseline>=lo&&m.baseline<=hi)?((m.baseline-lo)/(hi-lo))*100:null;
 return {lo,hi,pos:pos*100,tag,baseP,y1l:((ylo-lo)/(hi-lo))*100,y1r:((hi-yhi)/(hi-lo))*100};}
function gaugeHTML(m,g){const base=g.baseP!=null?'<div class="ig-base" style="left:'+g.baseP.toFixed(1)+'%"></div>':'';
 return '<div class="ig"><div class="ig-lab"><span>수위 <b>'+g.tag+'</b></span><span>전 기간 범위</span></div>'
  +'<div class="ig-track"><div class="ig-1y" style="left:'+g.y1l.toFixed(1)+'%;right:'+g.y1r.toFixed(1)+'%"></div>'
  +base+'<div class="ig-mk" style="left:'+g.pos.toFixed(1)+'%;background:'+m.col+'"></div></div>'
  +'<div class="ig-ends"><span>'+fmtV(m,g.lo)+'</span><span>'+fmtV(m,g.hi)+'</span></div></div>';}
function rowGauge(m,g){const base=g.baseP!=null?'<div class="rg-base" style="left:'+g.baseP.toFixed(1)+'%"></div>':'';
 return '<div class="rg"><div class="rg-track"><div class="rg-1y" style="left:'+g.y1l.toFixed(1)+'%;right:'+g.y1r.toFixed(1)+'%"></div>'
  +base+'<div class="rg-mk" style="left:'+g.pos.toFixed(1)+'%;background:'+m.col+'"></div></div></div>';}
function coreCard(m){const pts=makeSeries(m);const s=signal(m,pts);const d=deltaOf(m);const g=gaugeOf(m);
 const bl=m.baseline!=null?'<span class="cc-bl">기준 '+m.baseline+'</span>':'';
 const inv=m.inv?'<span class="inv">역행</span>':'';
 const dc=d?'<span class="dchip '+d.cls+'">'+arrowD(d.cls)+' '+d.abs+'<span class="lab">'+d.lab+'</span></span>':'';
 const sub=m.sub?'<div class="cc-sub">'+m.sub+'</div>':'';
 return '<div class="cc"><div class="cc-top"><span class="cc-name">'+m.lab+'</span>'
  +'<span class="sig '+s.cls+'">'+arrow(s.cls)+' '+s.txt+inv+'</span></div>'+sub
  +'<div class="cc-val">'+fmtV(m,m.base)+'<span class="u">'+m.unit+'</span>'+bl+dc+'</div>'
  +miniChart(m,pts)+(g?gaugeHTML(m,g):'')+'<div class="cc-interp">'+m.interp+'</div></div>';}
function rowHTML(m){const pts=makeSeries(m);const s=signal(m,pts);const d=deltaOf(m);const g=gaugeOf(m);
 const dr=d?'<span class="r-d '+d.cls+'">'+d.signed+'<span class="lab">'+d.lab+'</span></span>':'';
 const pct=g?'<span class="rg-pct">'+g.tag+'</span>':'';
 return '<div class="row"><span class="r-name">'+m.lab+'<small>'+m.sub+'</small></span>'
  +'<span class="r-val">'+fmtV(m,m.base)+'<span class="u">'+m.unit+'</span>'+dr+'</span>'
  +'<span class="r-mid">'+sparkSVG(m,pts)+(g?rowGauge(m,g):'')+'</span>'
  +'<span class="rsig"><span class="sig sm '+s.cls+'">'+arrow(s.cls)+' '+shortTxt(s.cls)+'</span>'+pct+'</span></div>';}
function pendRow(p){const chk=(p.st==="check");
 return '<div class="row pend'+(chk?" chk":"")+'"><span class="r-name">'+p.lab+'<small>'+p.note+'</small></span>'
  +'<span class="r-val">—</span><span></span><span class="'+(chk?"chk-tag":"pend-tag")+'">'+(chk?"점검 필요":"연결예정")+'</span></div>';}
const CORELAB={buy:"매수우위지수",outlook:"매매가격전망지수"};
function coreMissCard(k){return '<div class="cc cc-miss"><div class="cc-top"><span class="cc-name">'+(CORELAB[k]||k)+'</span>'
 +'<span class="chk-tag">점검 필요</span></div><div class="cc-val">—</div>'
 +'<div class="cc-interp">소스 수집 실패 — 데이터가 들어오면 자동으로 채워집니다.</div></div>';}
function renderCore(){/* 매매전망 카드 섹션 삭제(2026-07) — 미호출 보존 */
 const host=document.getElementById("core");if(!host)return;
 host.innerHTML=CORE.map(function(k){const m=byK(k);return m?coreCard(m):coreMissCard(k);}).join("");}
function renderGroups(){/* 그룹별 지표 섹션 삭제(거시 6차트와 중복) — 미호출 보존 */
 if(!document.getElementById("groups"))return;let html="";
 for(const gk of GORDER){const ms=IND.filter(m=>m.g===gk&&CORE.indexOf(m.k)<0);const ps=PEND.filter(p=>p.g===gk&&CORE.indexOf(p.k)<0);
  if(!ms.length&&!ps.length)continue;
  html+='<div class="grp"><div class="glab">'+G[gk].name+' <em>'+G[gk].desc+'</em></div>'
   +'<div class="rows">'+ms.map(rowHTML).join("")+ps.map(pendRow).join("")+'</div></div>';}
 document.getElementById("groups").innerHTML=html;}
function priceDelta(arr){if(!arr||arr.length<2)return null;
 const cur=arr[arr.length-1],prev=arr[arr.length-2],d=cur-prev;if(!prev)return null;
 const pct=d/prev*100,cls=Math.abs(pct)<0.05?"fl":pct>0?"up":"dn";
 return {cls,pct:(pct>0?"+":pct<0?"−":"±")+Math.abs(pct).toFixed(1),amt:(d>0?"+":d<0?"−":"±")+Math.abs(d).toFixed(2)};}
function priceChart(med,mean){ // 최근 1년 이중선 — 중위 실선(면적)·평균 점선(우측 정렬)
 // (2026-07 v2) 280×120 → 560×150 가로형 재설계:
 //  ① 세로축 억 단위 3눈금(하단·중간·상단) + 옅은 가이드선 추가 — 좌측 패딩 36 확보.
 //  ② 비율 0.43→0.27로 완화 — .mini(height:auto)가 카드 폭에 비례해 과도하게 커지며
 //     파이썬 선언 높이(구 235px/행)를 넘겨 다음 섹션(거시 상세 추이)과 겹치던 문제 해소.
 //     선언 예산도 320px/행으로 동기화(아래 _render_indicator_charts).
 const W=560,H=150,P={l:36,r:10,t:10,b:22},N=13;
 const a=med.slice(-N),b=(mean||[]).slice(-N);
 if(a.length<2)return "";
 const pts=a.map((v,i)=>({t:new Date(ASOF.getTime()-(a.length-1-i)*30*86400000),v}));
 let lo=Math.min.apply(null,a),hi=Math.max.apply(null,a);
 if(b.length){lo=Math.min(lo,Math.min.apply(null,b));hi=Math.max(hi,Math.max.apply(null,b));}
 const sp=(hi-lo)||1,y0=lo-sp*0.08,y1=hi+sp*0.08;  // 여백 0.16→0.08 — 진폭 확보
 const xs=i=>P.l+i/(a.length-1)*(W-P.l-P.r);
 const ys=v=>P.t+(1-(v-y0)/(y1-y0))*(H-P.t-P.b);
 const path=a.map((v,i)=>(i?"L":"M")+xs(i).toFixed(1)+" "+ys(v).toFixed(1)).join(" ");
 const area=path+" L"+xs(a.length-1).toFixed(1)+" "+(H-P.b)+" L"+xs(0).toFixed(1)+" "+(H-P.b)+" Z";
 const off=a.length-b.length;              // 같은 월간 · 꼬리(최신월) 기준 정렬
 const mp=b.map((v,j)=>({i:j+off,v})).filter(p=>p.i>=0&&p.i<a.length);
 const path2=mp.map((p,k)=>(k?"L":"M")+xs(p.i).toFixed(1)+" "+ys(p.v).toFixed(1)).join(" ");
 // 세로축 — 데이터 최저·중간·최고 3눈금(중위~평균 통합 범위) · 억 단위 라벨 + 가이드선
 const fmtY=v=>(v>=100?v.toFixed(0):v.toFixed(1))+'억';
 const yt=[lo,(lo+hi)/2,hi].map(v=>{const y=ys(v);
  return '<line x1="'+P.l+'" x2="'+(W-P.r)+'" y1="'+y.toFixed(1)+'" y2="'+y.toFixed(1)+'" stroke="#ECEDE7" stroke-width="1" stroke-dasharray="2 3"/>'
   +'<text class="mc-ax" style="font-size:11px" x="'+(P.l-5)+'" y="'+(y+3.5).toFixed(1)+'" text-anchor="end">'+fmtY(v)+'</text>';}).join("");
 const ax='<line x1="'+P.l+'" y1="'+(H-P.b)+'" x2="'+(W-P.r)+'" y2="'+(H-P.b)+'" stroke="var(--line2)" stroke-width="1"/>';
 const tk=monthTicks(pts).map(t=>{const x=xs(t.i);
  return '<line x1="'+x.toFixed(1)+'" x2="'+x.toFixed(1)+'" y1="'+(H-P.b)+'" y2="'+(H-P.b+3)+'" stroke="#C9CBC2" stroke-width="1"/>'
   +'<text class="mc-ax" style="font-size:11px" x="'+x.toFixed(1)+'" y="'+(H-6)+'" text-anchor="middle">'+MON[t.mo]+'</text>';}).join("");
 return '<svg class="mini" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="xMidYMid meet">'
  +'<path d="'+area+'" fill="#7E9A83" opacity="0.10"/>'+yt+ax
  +(mp.length>1?'<path d="'+path2+'" fill="none" stroke="#B65F5A" stroke-width="2.8" stroke-dasharray="7 5" stroke-linejoin="round" stroke-linecap="round" opacity="0.85"/>':'')
  +'<path d="'+path+'" fill="none" stroke="#7E9A83" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/>'
  +tk+'</svg>';}
function priceCard(p){const med=p.med||[],mean=p.mean||[];
 const lastMed=med.length?med[med.length-1]:null;
 const lastMean=mean.length?mean[mean.length-1]:null;
 const dm=priceDelta(med.length?med:mean);
 let big="";
 if(lastMed!=null)big='<div class="pc-val">'+lastMed.toFixed(1)+'<span class="u">억</span><span class="lab">중위</span></div>';
 else if(lastMean!=null)big='<div class="pc-val">'+lastMean.toFixed(1)+'<span class="u">억</span><span class="lab">평균</span></div>';
 const mom=dm?'<div class="pc-mom '+dm.cls+'">전월 '+arrow(dm.cls)+' '+dm.pct+'%<small>'+dm.amt+'억</small></div>':'';
 // 평균−중위 격차 — 평균은 고가 구간에 민감해 격차 확대=상급지(고가) 주도 상승 신호.
 const gap=(lastMean!=null&&lastMed!=null)?lastMean-lastMed:null;
 const meanLine=gap!=null?'<div class="pc-mean">평균 <b>'+lastMean.toFixed(1)+'억</b> · 중위와 격차 <b>'
  +(gap>=0?"+":"−")+Math.abs(gap).toFixed(1)+'억</b></div>':'';
 const dual=med.length>1&&mean.length>1;
 const chart=dual?priceChart(med,mean)
  :(function(){const m={col:"#7E9A83",baseline:null,base:lastMed!=null?lastMed:lastMean,unit:"억",cad:"month",real:med.length?med:mean};
    const pts=makeSeries(m);return pts.length>1?miniChart(m,pts):"";})();
 const leg=dual?'<div class="pc-leg"><span><i></i>중위</span><span><i class="dash"></i>평균</span><span style="margin-left:auto;font-weight:600">격차 확대=고가 주도</span></div>':'';
 return '<div class="pc"><div class="pc-top"><span class="pc-reg">'+p.lab+'</span>'
  +'<span class="pc-tag">아파트 매매 · 월간(KB)</span></div>'+big+mom+meanLine+chart+leg+'</div>';}
function renderPrice(){if(!PRICE||!PRICE.length)return;
 document.getElementById("price").innerHTML=PRICE.map(priceCard).join("");
 document.getElementById("priceSec").style.display="";}
function renderCycle(){const order=["침체기","회복기","상승기","둔화기"];
 const subs={"침체기":"가격↓ 거래↓","회복기":"심리·거래 반등","상승기":"가격·심리 강세","둔화기":"상승폭 축소"};
 const lead=IND.filter(m=>m.g==="lead"||m.k==="jsup");
 const CYCSHORT={buy:"매수우위",outlook:"매매전망",lead50:"선도50",jsup:"전세수급"};
 function cycScoreOld(mb){let sc=0,n=0;lead.forEach(function(m){const r=m.real||[];const off=mb*(m.cad==="month"?1:4);
   if(r.length>off+2){const mm=Object.assign({},m,{real:off?r.slice(0,r.length-off):r});sc+=signal(mm,makeSeries(mm)).score;n++;}});
  return n?sc/n:0;}
 // 종합 강도 v5: 파이썬에서 5지표(정책레짐·매수우위·착공·전세지수·주담대) z-가중·lag
 // 반영으로 사전계산한 SCARR(월별)을 사용. 불가 시 SCARR=[] → 구 방식 자동 폴백.
 const V3=SCARR&&SCARR.length>0;
 function cycScore(mb){if(V3&&mb<SCARR.length&&SCARR[mb]!=null)return SCARR[mb];return V3?0:cycScoreOld(mb);}
 const T=V3?0.15:0.05, GO=V3?1.00:0.50;
 const sc=cycScore(0);
 let cur=(V3||lead.length)?(sc>T?"상승기":sc>0.0?"회복기":sc>-T?"둔화기":"침체기"):"회복기";
 document.getElementById("nowStage").textContent=cur;
 document.getElementById("stages").innerHTML=order.map(s=>'<div class="stage '+(s===cur?"on":"")+'">'+s+'<small>'+subs[s]+'</small></div>').join("");
 // 판정 근거 — v5면 5지표 z-가중 기여 칩(신호값·가중치·lag), 아니면 구 선행지표 칩
 const leadByK={};lead.forEach(function(m){leadByK[m.k]=m;});
 let chips,whyLab,mix;
 if(V3){
   chips=V3SIG.map(function(x){
     return '<span class="why-chip '+x.c+'"><span class="wc-hd">'+arrow(x.c)+' '+x.nm
      +' <b>'+x.v+'</b><small style="color:#b6b7ae;font-weight:700"> ×'+x.w+'%</small></span></span>';}).join("");
   whyLab='판정 근거 — 종합 강도 v5 · 5지표 z-가중(정책25·매수우위22·착공22·전세지수16·주담대15) · lag 실측 반영';
   const ups=V3SIG.filter(x=>x.c==="up").length,dns=V3SIG.filter(x=>x.c==="dn").length;
   mix=ups+'개 <b class="up">상승 기여</b> · '+dns+'개 <b class="dn">하락 기여</b>'
    +((V3SIG.length-ups-dns)?' · '+(V3SIG.length-ups-dns)+'개 중립':'');
 }else{
   const sigs=lead.map(function(m){return {k:m.k,nm:CYCSHORT[m.k]||m.lab,c:signal(m,makeSeries(m)).cls,m:m};});
   chips=sigs.map(function(x){
     return '<span class="why-chip '+x.c+'"><span class="wc-hd">'+arrow(x.c)+' '+x.nm+'</span>'
      +chipSpark(x.m)+'</span>';}).join("");
   whyLab='판정 근거 — 선행·심리 '+lead.length+'지표';
   const ups=sigs.filter(x=>x.c==="up").length,dns=sigs.filter(x=>x.c==="dn").length;
   if(lead.length&&ups===lead.length)mix='모두 <b class="up">상승 기여</b>';
    else if(lead.length&&dns===lead.length)mix='모두 <b class="dn">하락 기여</b>';
    else mix=ups+'개 <b class="up">상승</b> · '+dns+'개 <b class="dn">하락</b>'+((lead.length-ups-dns)?' · '+(lead.length-ups-dns)+'개 보합':'');
 }
 const dlt=sc-cycScore(1);
 const traj=Math.abs(dlt)<0.005?'<b>유지</b>':(dlt>0?'<b class="up">강화 ↗</b>':'<b class="dn">약화 ↘</b>');
 const scStr=(sc>=0?"+":"−")+Math.abs(sc).toFixed(2);
 document.getElementById("cycWhy").innerHTML='<div class="why-lab">'+whyLab+'</div>'
  +'<div class="why-chips">'+chips+'</div>'
  +'<div class="why-summ">'+mix+' → 종합 강도 <b>'+scStr+'</b> · 직전 대비 '+traj+'</div>';
 // 종합 강도 위치 게이지(임계 ±T 표시 + needle)
 function stageOf(s){return s>T?"상승기":s>0?"회복기":s>-T?"둔화기":"침체기";}
 const Z=[["침체기","침체","#5A7CA0",0,33.33],["둔화기","둔화","#A9C0DA",33.33,50],
          ["회복기","회복","#E9BDB8",50,66.67],["상승기","상승","#C16C64",66.67,100]];
 // 구역(침체|둔화|회복|상승) 비율은 33/50/67 그대로 두고, 바깥(침체·상승)이
 // 넓은 점수 범위를 흡수하도록 piecewise 매핑(임계 ±T · 양끝 ±GO — v3는 .15/1.0).
 function gPos(s){
   if(s<=-GO)return 0;
   if(s< -T)return (s+GO)/(GO-T)*33.33;      // 침체: -GO..-T → 0..33.33
   if(s<  0)return 33.33+(s+T)/T*16.67;      // 둔화: -T..0  → 33.33..50
   if(s<  T)return 50+s/T*16.67;             // 회복: 0..T   → 50..66.67
   if(s< GO)return 66.67+(s-T)/(GO-T)*33.33; // 상승: T..GO  → 66.67..100
   return 100;}
 const nx=gPos(sc);
 const TS=T.toFixed(2).replace(/^0/,"");
 const zoneDivs=Z.map(z=>'<div class="cg-zone" style="width:'+(z[4]-z[3]).toFixed(2)+'%;background:'+z[2]+'"></div>').join("");
 const ticks='<span style="left:33.33%">−'+TS+'</span><span style="left:50%">0</span><span style="left:66.67%">+'+TS+'</span>';
 const zlabs=Z.map(z=>'<span class="'+(z[0]===cur?"on":"")+'" style="left:'+((z[3]+z[4])/2).toFixed(2)+'%">'+z[1]+'</span>').join("");
 // (12개월 강도 추이 차트 삭제 — 하단 '종합 강도 궤적(2020~)' 차트로 일원화 · 2026-07)
 document.getElementById("cycGauge").innerHTML=
   '<div class="cg-lab">현재 위치 — 임계 ±'+TS+' 기준 국면 판정'+(V3?' · v5':'')+' · 전체 궤적은 하단 거시 섹션</div>'
   +'<div class="cg-wrap"><div class="cg-track">'+zoneDivs+'</div><div class="cg-needle" style="left:'+nx.toFixed(1)+'%"></div></div>'
   +'<div class="cg-ticks">'+ticks+'</div><div class="cg-zlab">'+zlabs+'</div>';
 // 현재 국면 지속 개월수 + 직전 국면(궤적)
 let hold=0,prev=cur;
 for(let mb=1;mb<=24;mb++){const ps=cycScore(mb);const st=stageOf(ps);if(st!==cur){prev=st;break;}hold=mb;}
 const trajLine=hold>0
   ?'현재 <b>'+cur+'</b> '+(hold+1)+'개월차'+(prev!==cur?'(직전 '+prev+'에서 전환)':'')+'. '
   :'현재 <b>'+cur+'</b>. ';
 document.getElementById("cycRead").innerHTML=trajLine+(V3
   ?'국면 전환은 종합 강도가 임계 ±'+TS+'를 위아래로 넘을 때 신호가 나와요 — 5지표 기여는 위 판정 근거, 전체 궤적은 하단 거시 섹션 참고.'
   :'국면 전환은 매수우위·전망지수가 기준 100을 위아래로 넘을 때 먼저 신호가 나와요.');}
function renderFoot(){const soon=PEND.filter(p=>p.st==="soon");
 let s='미니차트는 최근 1년(가로축 월 단위)';
 if(soon.length)s+=' · 연결예정 '+soon.length+'종('+soon.map(p=>p.lab).join("·")+')';
 document.getElementById("foot").innerHTML=s;}
renderCycle();renderPrice();renderFoot();
(function(){function _fit(){try{var h=Math.ceil(document.body.getBoundingClientRect().height)+2;if(window.frameElement){window.frameElement.style.height=h+"px";window.frameElement.setAttribute("height",h);var pe=window.frameElement.parentElement;if(pe&&pe.getBoundingClientRect().height<h){pe.style.height=h+"px";}}}catch(e){}}window.addEventListener("load",_fit);setTimeout(_fit,150);setTimeout(_fit,600);setTimeout(_fit,1500);window.addEventListener("resize",_fit);try{new ResizeObserver(_fit).observe(document.body);}catch(e){}})();
</script></body></html>'''


def _indicators_v2_payload(data):
    """지표 시계열(list[{key,...,series}]) → 그룹·신호·해석 메타가 붙은 카드 리스트(live)와
    연결예정 슬롯(pend) 두 가지로 변환. 시계열 2개 미만은 제외."""
    by = {it.get("key"): it for it in (data or [])}
    ind = []
    for k in _INDV2_ORDER:
        it = by.get(k)
        if not it:
            continue
        series = [float(v) for v in (it.get("series") or []) if v is not None]
        if len(series) < 2:
            continue
        meta = _INDV2_DEF[k]
        ind.append({
            "k": k, "g": meta["g"], "lab": it.get("label", k),
            "sub": it.get("sub", ""), "cad": meta["cad"],
            "unit": it.get("unit", ""), "col": it.get("col", "#7E9A83"),
            "baseline": meta["baseline"], "inv": meta["inv"],
            "interp": meta["interp"], "base": round(series[-1], 2),
            "real": [round(v, 2) for v in series],
        })
    # pend 슬롯 = 연결예정(소스 자체 미연결). 라이브에 들어오면 자동으로 라이브 전환.
    live_keys = {d["k"] for d in ind}
    pend = [{**p, "st": "soon"} for p in _INDV2_PENDING if p["k"] not in live_keys]
    return ind, pend


def _price_block_payload(data):
    """지표 시계열 list에서 med/mean_seoul·sudo 4키를 묶어 '현재 매매가격' 블록용
    region 카드 리스트로 변환. 둘 다 없는 지역은 생략(빈 블록은 뷰에서 숨김)."""
    by = {it.get("key"): it for it in (data or [])}
    regions = [("seoul", "서울", "med_seoul", "mean_seoul"),
               ("sudo", "수도권", "med_sudo", "mean_sudo")]
    out = []
    for rk, label, mk_med, mk_mean in regions:
        med = [float(v) for v in ((by.get(mk_med) or {}).get("series") or [])
               if v is not None]
        mean = [float(v) for v in ((by.get(mk_mean) or {}).get("series") or [])
                if v is not None]
        if not med and not mean:
            continue
        out.append({"key": rk, "lab": label,
                    "med": [round(v, 2) for v in med],
                    "mean": [round(v, 2) for v in mean]})
    return out


def _indicator_chart_component(ind, pend, price, asof, scarr=None, v3sig=None):
    import json as _json
    return (_INDV2_HTML
            .replace("__IND__", _json.dumps(ind, ensure_ascii=False))
            .replace("__PEND__", _json.dumps(pend, ensure_ascii=False))
            .replace("__PRICE__", _json.dumps(price, ensure_ascii=False))
            .replace("__G__", _json.dumps(_INDV2_GROUPS, ensure_ascii=False))
            .replace("__SCARR__", _json.dumps(scarr or [], ensure_ascii=False))
            .replace("__V3SIG__", _json.dumps(v3sig or [], ensure_ascii=False))
            .replace("__ASOF__", asof))


def _render_indicator_charts(data):
    """지표 탭 v2 — 사이클 위치 + 핵심 3 강조 카드 + 그룹별 컴팩트 행(미니차트 1년·월축).
    데이터는 엔진(매일 아침 수집) 가격지수 시계열을 그대로 쓰고, 미연결 항목은 '연결예정'으로 표시."""
    from datetime import date
    from math import ceil
    live = data is not _IND_SAMPLE
    ind, pend = _indicators_v2_payload(data)
    if not ind:
        st.caption("지표 데이터가 아직 없어요. 매일 아침 자동 수집 후 표시됩니다.")
        return
    asof = date.today().strftime("%Y-%m-%d")
    price = _price_block_payload(data)
    # 종합 강도 v5 — 5지표(정책 포함) z-가중·lag 반영(파이썬 사전계산). 불가 시 빈 배열 → JS 구 방식 폴백.
    _scarr, _v3sig = _v5_score_series(data)
    # 새 레이아웃 기준 높이 산정(클리핑 방지) — 헤더 + (가격블록) + 핵심 + 그룹 행들.

    # 높이는 데스크톱 실측(가격 카드 2열)에 맞춰 타이트하게 잡는다 — 과대 잡으면
    # 다음 섹션과 사이에 큰 공백이 생긴다(2026-07 축소). 모바일 적층으로 내용이
    # 더 길어지면 iframe 내부 _fit 스크립트가 frameElement 높이를 키워 보정한다.
    height = (300                      # 사이클 헤더 + 판정근거 칩 + 위치 게이지
              + (55 + 320 * ceil(len(price) / 2) if price else 0)  # 가격 카드(2열 · 560×150 차트+세로축 라벨, 2026-07 재실측)
              + 35)                    # 푸터 캡션
    components.html(_indicator_chart_component(ind, pend, price, asof,
                                               _scarr, _v3sig),
                    height=height, scrolling=False)
    src = "KB 실데이터" if live else "샘플 · 아침 수집 후 실데이터로 교체"
    st.markdown(foot_row(
        src, "사이클 위치·매매가격·매매전망 — 상세 지표는 아래 거시 상세 추이(메인) 참고"),
        unsafe_allow_html=True)
    _render_macro_section(data, _scarr)


def _render_indicators(cards=None):
    if cards is None:
        cards = fetch_indicators()
    st.markdown(_market_phase(cards), unsafe_allow_html=True)
    html = ""
    for gtitle, gsub in _GROUP_ORDER:
        members = [c for c in cards if c["group"] == gtitle]
        if not members:
            continue
        html += f'<div class="re-grp">{gtitle}<span class="sub">{gsub}</span></div>'
        inner = ""
        for c in members:
            base_tag = (f'<span class="re-base">기준 {c["baseline"]}</span>'
                        if c.get("baseline") is not None else "")
            inner += (f'<div class="re-card"><div class="re-lab">{c["label"]}</div>'
                      f'<div class="re-val">{c["value"]}'
                      f'{_delta_html(c["series"], c.get("dunit", ""))}{base_tag}</div>'
                      f'{_spark_svg(c["series"], c["col"], c["kind"], c.get("baseline"))}'
                      f'<div class="re-note">{c["note"]}</div></div>')
        html += f'<div class="re-grid">{inner}</div>'
    st.markdown(html, unsafe_allow_html=True)
    st.caption("소스: KB · 부동산원 R-ONE · 통계청 KOSIS · 법원경매 · 국토부 · 한은 ECOS — "
               "매수우위·매매지수·전세가율(KB)·거래량(실거래)·미분양(KOSIS)·금리(ECOS) 실연결, "
               "나머지는 연결 예정(샘플). 항목별 갱신주기 상이. ▲빨강=상승 / ▼파랑=하락(직전값 대비)")


# ── 거시 상세 추이 — 코스피·코스닥 차트와 동일 양식(대형 SVG·십자선·기간 라디오) ──
#   6차트: 주담대(+기준금리 병기)·착공·매수우위·M2·GDP·전세가율 · 2020.1~ 전체 추이.
#   데이터: 엔진 indicators(macro는 dates 포함) · 미수집 항목은 _MACRO_SAMPLE 폴백.
_MACRO_PERIODS = {"1년": 12, "3년": 36, "전체(2016~)": None}


def _dates_back(n, step_days):
    """날짜 없는 KB 시계열용 — 오늘부터 step_days 간격 역산 라벨(YYYYMM 근사)."""
    from datetime import date, timedelta
    t = date.today()
    return [(t - timedelta(days=step_days * (n - 1 - i))).strftime("%Y%m")
            for i in range(n)]


def _dlabel(d):
    """YYYYMM→'YY.MM' · YYYYQn→'YYQn'."""
    d = str(d)
    if "Q" in d:
        return d[2:]
    return f"{d[2:4]}.{d[4:6]}" if len(d) >= 6 else d


def _slice_period(dates, vals, months, per_month):
    if months is None:
        return dates, vals
    n = max(2, int(round(months * per_month)))
    return dates[-n:], vals[-n:]


def _clip_2016(dates, vals):
    """'전체(2016~)' 표시용 — 장기 백필(2013~2015 · v5 lag·YoY 입력) 지표도 화면은
    2016년부터. YYYYMM·YYYYQn 모두 문자열 비교로 '2016' 이상만 통과
    (고정폭 연도 접두라 사전순 비교가 시간순과 일치)."""
    keep = [(d, v) for d, v in zip(dates, vals) if str(d) >= "2016"]
    return [d for d, _ in keep], [v for _, v in keep]


# 우측 보조축(rpair) 스펙 — 주 지표(비율) 옆에 절대 수준을 병기(2026-07).
#   key → [(소스키, 범례 라벨, 색, 단위, 소수)] · 소스키 시리즈는 엔진 payload에서 찾는다.
#   gdp는 소스키 대신 전기비 체인링크로 뷰어에서 유도("__gdp_chain__" 센티널).
_MACRO_RPAIRS = {
    "starts": [("starts_lv", "착공량 3M평균", "#8B8D82", "만호", 2)],
    "m2":     [("m2_lv", "M2 평잔", "#8B8D82", "조", 0)],
    "gdp":    [("__gdp_chain__", "GDP 수준(16Q1=100)", "#8B8D82", "", 1)],
    "jr":     [("sale_m", "매매지수", "#B65F5A", "", 1),
               ("jeonse_m", "전세지수", "#5A7CA0", "", 1)],
}


def _gdp_chain(dates, vals):
    """전기비(%) → 수준 지수(첫 분기=100 체인링크). 새 ECOS 코드 없이
    기존 성장률 시계열만으로 GDP '수준'의 궤적을 복원한다(스케일만 다름)."""
    out, lvl = [], 100.0
    for i, g in enumerate(vals):
        if i > 0:
            lvl *= (1.0 + g / 100.0)
        out.append(round(lvl, 2))
    return list(dates), out


def _macro_chart_payload(data, months):
    """차트 6개 payload. 각: {lab,sub,unit,col,dec,dates,vals,pair?,rpair?}
    rpair = 우측 보조축 라인 목록(절대 수준 병기 · _MACRO_RPAIRS)."""
    by = {it.get("key"): it for it in (data or [])}
    for s in _MACRO_SAMPLE:                    # 엔진 미수집 키만 샘플로 보충
        by.setdefault(s["key"], s)
    out = []
    spec = [("mortgage", 1, 2), ("starts", 1, 1), ("buy", 4.345, 0),
            ("m2", 1, 1), ("gdp", 1 / 3, 1), ("jr", 1, 1)]
    for key, per_month, dec in spec:
        it = by.get(key)
        if key == "buy":                    # [v5] 거시 카드는 장기(2016~) 우선
            it = by.get("buy_l") or it
        if not it:
            continue
        vals = [float(v) for v in (it.get("series") or []) if v is not None]
        if len(vals) < 2:
            continue
        dates = [str(d) for d in (it.get("dates") or [])]
        if len(dates) != len(vals):             # KB 시계열(날짜 없음) — 역산
            step = 7 if key == "buy" else 30
            dates = _dates_back(len(vals), step)
        if months is None:                  # '전체(2016~)' — 장기 백필 표시 클립
            dates, vals = _clip_2016(dates, vals)
        d2, v2 = _slice_period(dates, vals, months, per_month)
        ch = {"lab": it.get("label", key), "sub": it.get("sub", ""),
              "unit": it.get("unit", ""), "col": it.get("col", "#7E9A83"),
              "dec": dec, "dates": [_dlabel(x) for x in d2],
              "vals": [round(v, 2) for v in v2]}
        pr = it.get("pair")
        if isinstance(pr, dict):
            pd_, pv_ = [str(x) for x in (pr.get("dates") or [])], \
                       [float(v) for v in (pr.get("series") or []) if v is not None]
            if months is None:
                pd_, pv_ = _clip_2016(pd_, pv_)
            if len(pd_) == len(pv_) and len(pv_) >= 2:
                pd2, pv2 = _slice_period(pd_, pv_, months, per_month)
                ch["pair"] = {"lab": pr.get("label", ""), "col": pr.get("col", "#9a9b92"),
                              "dates": [_dlabel(x) for x in pd2],
                              "vals": [round(v, 2) for v in pv2]}
        # 우측 보조축 라인(rpair) — 절대 수준 병기. 소스가 없으면 그 라인만
        # 조용히 생략(엔진 첫 수집 전 starts_lv·m2_lv 부재 대응 · 무회귀).
        rlines = []
        for skey, rlab, rcol, runit, rdec in _MACRO_RPAIRS.get(key, []):
            if skey == "__gdp_chain__":            # GDP 수준 = 전기비 체인링크
                rd, rv = _gdp_chain(dates, vals) if key == "gdp" else ([], [])
            else:
                rit = by.get(skey)
                if not rit:
                    continue
                rv = [float(v) for v in (rit.get("series") or []) if v is not None]
                rd = [str(x) for x in (rit.get("dates") or [])]
                if len(rd) != len(rv):             # KB 시계열(날짜 없음) — 월간 역산
                    rd = _dates_back(len(rv), 30)
                if months is None:
                    rd, rv = _clip_2016(rd, rv)
            if len(rv) < 2:
                continue
            rd2, rv2 = _slice_period(rd, rv, months, per_month)
            rlines.append({"lab": rlab, "col": rcol, "unit": runit, "dec": rdec,
                           "dates": [_dlabel(x) for x in rd2],
                           "vals": [round(v, 2) for v in rv2]})
        if rlines:
            ch["rpair"] = rlines
        out.append(ch)
    return out


_MACRO_HTML = r'''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css">
<style>
html,body{margin:0;background:transparent;font-family:Pretendard,'Noto Sans KR',sans-serif;
 color:#34352f;-webkit-font-smoothing:antialiased}
.mgrid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:680px){.mgrid{grid-template-columns:1fr}}
.mc{background:#FCFCFA;border:1px solid #E4E5DE;border-radius:12px;padding:14px 16px 8px}
.mc-lab{font-size:12.5px;font-weight:700;color:#9a9b92}
.mc-big{display:flex;align-items:baseline;gap:8px;margin:3px 0 1px;flex-wrap:wrap}
.mc-val{font-size:23px;font-weight:800;letter-spacing:-.02em}
.mc-val small{font-size:12px;font-weight:700;color:#9a9b92;margin-left:1px}
.mc-d{font-size:12px;font-weight:800}
.mc-d.up{color:#B65F5A}.mc-d.dn{color:#5A7CA0}.mc-d.fl{color:#9a9b92}
.mc-sub{font-size:10.5px;font-weight:600;color:#b6b7ae;margin-bottom:4px}
.mc-leg{font-size:10.5px;font-weight:700;color:#9a9b92;display:flex;gap:10px;margin:2px 0 2px}
.mc-leg i{display:inline-block;width:14px;height:3px;border-radius:2px;margin-right:4px;vertical-align:middle}
svg{display:block;width:100%;height:210px;overflow:visible}
text{font-family:Pretendard,sans-serif}
</style></head><body>
<div class="mgrid" id="grid"></div>
<script>
var CH=__CH__;
function card(c,gi){
 var last=c.vals[c.vals.length-1],prev=c.vals[c.vals.length-2];
 var d=last-prev,cls=d>0?"up":(d<0?"dn":"fl"),ar=d>0?"▲":(d<0?"▼":"–");
 var ds=(d>=0?"+":"")+d.toFixed(c.dec);
 var legItems=[];
 if(c.pair||c.rpair)legItems.push('<span><i style="background:'+c.col+'"></i>'+c.lab+'</span>');
 if(c.pair)legItems.push('<span><i style="background:'+c.pair.col+'"></i>'+c.pair.lab+
  ' <b>'+c.pair.vals[c.pair.vals.length-1].toFixed(c.dec)+c.unit+'</b></span>');
 if(c.rpair)c.rpair.forEach(function(rp){legItems.push(
  '<span><i style="background:'+rp.col+';height:2px"></i>'+rp.lab+'(우) <b>'+
  rp.vals[rp.vals.length-1].toFixed(rp.dec)+rp.unit+'</b></span>');});
 var leg=legItems.length?'<div class="mc-leg">'+legItems.join('')+'</div>':"";
 return '<div class="mc"><div class="mc-lab">'+c.lab+'</div>'
  +'<div class="mc-big"><span class="mc-val" style="color:'+c.col+'">'+last.toFixed(c.dec)
  +'<small>'+c.unit+'</small></span>'
  +'<span class="mc-d '+cls+'">'+ar+' '+ds+c.unit+' (직전 대비)</span></div>'
  +'<div class="mc-sub">'+c.sub+'</div>'+leg+'<div id="ch'+gi+'"></div></div>';}
function draw(gi){
 var c=CH[gi],host=document.getElementById("ch"+gi);
 var W=Math.max(260,host.clientWidth||320),H=210;
 var ml=44,mr=(c.rpair?48:10),mt=10,mb=22,pw=W-ml-mr,ph=H-mt-mb;
 var ys=c.vals.slice(),lo=Math.min.apply(null,ys),hi=Math.max.apply(null,ys);
 if(c.pair){lo=Math.min(lo,Math.min.apply(null,c.pair.vals));hi=Math.max(hi,Math.max.apply(null,c.pair.vals));}
 var pad=(hi-lo)*0.12||Math.abs(hi)*0.02||1;lo-=pad;hi+=pad;var sp=(hi-lo)||1,n=ys.length;
 var rlo=0,rhi=1,rsp=1,rdec=0;
 if(c.rpair){rlo=Infinity;rhi=-Infinity;rdec=c.rpair[0].dec;
  c.rpair.forEach(function(rp){rp.vals.forEach(function(v){if(v<rlo)rlo=v;if(v>rhi)rhi=v;});});
  var rpad=(rhi-rlo)*0.12||Math.abs(rhi)*0.02||1;rlo-=rpad;rhi+=rpad;rsp=(rhi-rlo)||1;}
 function Yr(v){return mt+(1-(v-rlo)/rsp)*ph;}
 function X(i,m){var k=m?m.length:n;return ml+(k>1?i/(k-1):0)*pw;}
 function Y(v){return mt+(1-(v-lo)/sp)*ph;}
 function path(a){return 'M'+a.map(function(v,i){return X(i,a).toFixed(1)+','+Y(v).toFixed(1);}).join(' L');}
 var line=path(ys);
 var area=line+' L'+X(n-1).toFixed(1)+','+(mt+ph).toFixed(1)+' L'+X(0).toFixed(1)+','+(mt+ph).toFixed(1)+' Z';
 var hx=c.col.replace('#',''),R=parseInt(hx.substr(0,2),16),G=parseInt(hx.substr(2,2),16),B=parseInt(hx.substr(4,2),16);
 var yg='';
 for(var k=0;k<5;k++){var v=lo+sp*k/4,y=Y(v).toFixed(1);
  yg+='<line x1='+ml+' y1='+y+' x2='+(ml+pw)+' y2='+y+' stroke="#ECEDE7"/>';
  yg+='<text x='+(ml-7)+' y='+(parseFloat(y)+3.5).toFixed(1)+' text-anchor="end" font-size="10.5" fill="#9a9b92">'+v.toFixed(c.dec)+'</text>';
  if(c.rpair){var rv=rlo+rsp*k/4;
   yg+='<text x='+(ml+pw+6)+' y='+(parseFloat(y)+3.5).toFixed(1)+' text-anchor="start" font-size="10" fill="#b6b7ae">'+rv.toFixed(rdec)+'</text>';}}
 var zero='';
 if(lo<0&&hi>0)zero='<line x1='+ml+' y1='+Y(0).toFixed(1)+' x2='+(ml+pw)+' y2='+Y(0).toFixed(1)+' stroke="#9a9b92" stroke-dasharray="4 4" opacity="0.55"/>';
 var xg='',step=Math.max(1,Math.floor(n/5));
 for(var i=0;i<n;i+=step){xg+='<text x='+X(i).toFixed(1)+' y='+(H-6)+' text-anchor="middle" font-size="10.5" fill="#9a9b92">'+c.dates[i]+'</text>';}
 var pline='';
 if(c.pair)pline='<path d="'+path(c.pair.vals)+'" fill="none" stroke="'+c.pair.col+'" stroke-width="2" stroke-dasharray="5 4" stroke-linejoin="round"/>';
 if(c.rpair)c.rpair.forEach(function(rp){
  var d='M'+rp.vals.map(function(v,i){return X(i,rp.vals).toFixed(1)+','+Yr(v).toFixed(1);}).join(' L');
  pline+='<path d="'+d+'" fill="none" stroke="'+rp.col+'" stroke-width="1.6" opacity="0.9" stroke-linejoin="round"/>';});
 var svg='<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">'
  +'<defs><linearGradient id="g'+gi+'" x1="0" y1="0" x2="0" y2="1">'
  +'<stop offset="0" stop-color="rgba('+R+','+G+','+B+',0.18)"/><stop offset="1" stop-color="rgba('+R+','+G+','+B+',0)"/></linearGradient></defs>'
  +yg+zero+'<path d="'+area+'" fill="url(#g'+gi+')"/>'
  +'<path d="'+line+'" fill="none" stroke="'+c.col+'" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>'
  +pline+xg
  +'<g id="cr'+gi+'" style="display:none"><line id="vl'+gi+'" y1='+mt+' y2='+(mt+ph)+' stroke="#9a9b92" stroke-dasharray="3 3"/>'
  +'<circle id="dt'+gi+'" r="3.6" fill="'+c.col+'"/>'
  +'<g><rect id="tb'+gi+'" rx="4" height="18" fill="#34352f"/><text id="tt'+gi+'" font-size="10.5" font-weight="700" fill="#fff" text-anchor="middle"></text></g></g>'
  +'<rect id="ht'+gi+'" x='+ml+' y='+mt+' width='+pw+' height='+ph+' fill="transparent" style="cursor:crosshair"/></svg>';
 host.innerHTML=svg;
 var root=host.querySelector('svg'),cr=root.querySelector('#cr'+gi),vl=root.querySelector('#vl'+gi),
     dt=root.querySelector('#dt'+gi),tb=root.querySelector('#tb'+gi),tt=root.querySelector('#tt'+gi),ht=root.querySelector('#ht'+gi);
 ht.addEventListener('mousemove',function(e){
  var r=root.getBoundingClientRect(),mx=(e.clientX-r.left)/r.width*W;
  var bi=Math.round((mx-ml)/pw*(n-1));bi=Math.max(0,Math.min(n-1,bi));
  var x=X(bi),y=Y(ys[bi]);cr.style.display='';
  vl.setAttribute('x1',x);vl.setAttribute('x2',x);dt.setAttribute('cx',x);dt.setAttribute('cy',y);
  var s=c.dates[bi]+'  '+ys[bi].toFixed(c.dec)+c.unit;
  if(c.pair&&c.pair.vals.length===n)s+=' · '+c.pair.vals[bi].toFixed(c.dec)+c.unit;
  if(c.rpair)c.rpair.forEach(function(rp){
   var ri=Math.round(bi/(n-1||1)*(rp.vals.length-1));
   s+=' · '+rp.lab+' '+rp.vals[ri].toFixed(rp.dec)+rp.unit;});
  tt.textContent=s;var tw=Math.min(s.length*6.4+14,pw);
  var tx=Math.max(ml+tw/2,Math.min(ml+pw-tw/2,x));
  tb.setAttribute('x',tx-tw/2);tb.setAttribute('y',mt+2);tb.setAttribute('width',tw);
  tt.setAttribute('x',tx);tt.setAttribute('y',mt+15);});
 ht.addEventListener('mouseleave',function(){cr.style.display='none';});}
document.getElementById("grid").innerHTML=CH.map(card).join("");
CH.forEach(function(_,i){draw(i);});
window.addEventListener('resize',function(){CH.forEach(function(_,i){draw(i);});});
(function(){function _fit(){try{var h=Math.ceil(document.body.getBoundingClientRect().height)+2;
 if(window.frameElement){window.frameElement.style.height=h+"px";window.frameElement.setAttribute("height",h);}}catch(e){}}
window.addEventListener("load",_fit);setTimeout(_fit,120);setTimeout(_fit,600);
try{new ResizeObserver(_fit).observe(document.body);}catch(e){}})();
</script></body></html>'''


_BT_HTML = r'''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css">
<style>html,body{margin:0;background:transparent;font-family:Pretendard,sans-serif;color:#34352f}
.bt{background:#FCFCFA;border:1px solid #E4E5DE;border-radius:12px;padding:14px 16px 8px}
.bt-lab{font-size:12.5px;font-weight:700;color:#9a9b92;margin-bottom:2px}
.bt-leg{font-size:10.5px;font-weight:700;color:#9a9b92;display:flex;gap:12px;margin:4px 0}
.bt-leg i{display:inline-block;width:14px;height:3px;border-radius:2px;margin-right:4px;vertical-align:middle}
svg{display:block;width:100%;height:230px;overflow:visible}text{font-family:Pretendard,sans-serif}
</style></head><body>
<div class="bt"><div class="bt-lab">종합 강도 궤적 — 2016.1~ 월별 v5 점수 · 서울 매매지수 3개월 변화율 비교(백테스트__CORR__)</div>
<div class="bt-leg"><span><i style="background:#7E9A83"></i>종합 강도(좌축 · ±0.15 임계)</span>
<span><i style="background:#B65F5A"></i>매매지수 3M 변화율(우축·%)</span></div><div id="bt"></div></div>
<script>
var SC=__SC__,SD=__SD__,SALE=__SALE__,T=0.15;
function draw(){
 var host=document.getElementById("bt"),W=Math.max(300,host.clientWidth||640),H=230;
 var ml=40,mr=44,mt=10,mb=22,pw=W-ml-mr,ph=H-mt-mb,n=SC.length;
 function X(i){return ml+(n>1?i/(n-1):0)*pw;}
 function Ys(v){return mt+(1-(v+1)/2)*ph;}
 var sv=SALE.filter(function(v){return v!==null&&v!==undefined;});
 if(!sv.length)sv=[0,1];
 var slo=Math.min.apply(null,sv),shi=Math.max.apply(null,sv);
 var spad=(shi-slo)*0.08||1;slo-=spad;shi+=spad;
 function Yr(v){return mt+(1-(v-slo)/(shi-slo))*ph;}
 var band='<rect x='+ml+' y='+Ys(T).toFixed(1)+' width='+pw+' height='+(Ys(-T)-Ys(T)).toFixed(1)+' fill="#F1F2EC"/>';
 var yg='';[-1,-0.5,0,0.5,1].forEach(function(v){var y=Ys(v).toFixed(1);
  yg+='<line x1='+ml+' y1='+y+' x2='+(ml+pw)+' y2='+y+' stroke="'+(v===0?'#C9CBC2':'#ECEDE7')+'"'+(v===0?' stroke-dasharray="4 4"':'')+'/>';
  yg+='<text x='+(ml-6)+' y='+(parseFloat(y)+3.5)+' text-anchor="end" font-size="10.5" fill="#9a9b92">'+(v>0?'+':'')+v.toFixed(1)+'</text>';});
 [slo+spad,(slo+shi)/2,shi-spad].forEach(function(v){
  yg+='<text x='+(ml+pw+6)+' y='+(Yr(v)+3.5).toFixed(1)+' text-anchor="start" font-size="10.5" fill="#B65F5A" opacity="0.75">'+v.toFixed(1)+'%</text>';});
 var xg='',step=Math.max(1,Math.floor(n/6));
 for(var i=0;i<n;i+=step){xg+='<text x='+X(i).toFixed(1)+' y='+(H-6)+' text-anchor="middle" font-size="10.5" fill="#9a9b92">'+SD[i]+'</text>';}
 function path(a,Y){var d='',pen=false;          // null 구간은 선을 끊고 재개(M)
  for(var i=0;i<a.length;i++){var v=a[i];
   if(v===null||v===undefined){pen=false;continue;}
   d+=(pen?' L':' M')+X(i).toFixed(1)+','+Y(v).toFixed(1);pen=true;}
  return d.trim();}
 var svg='<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">'
  +band+yg
  +'<path d="'+path(SALE,Yr)+'" fill="none" stroke="#B65F5A" stroke-width="2" opacity="0.85"/>'
  +'<path d="'+path(SC,Ys)+'" fill="none" stroke="#7E9A83" stroke-width="2.4" stroke-linejoin="round"/>'
  +xg+'</svg>';
 host.innerHTML=svg;}
draw();window.addEventListener('resize',draw);
(function(){function _fit(){try{var h=Math.ceil(document.body.getBoundingClientRect().height)+2;
 if(window.frameElement){window.frameElement.style.height=h+"px";window.frameElement.setAttribute("height",h);}}catch(e){}}
window.addEventListener("load",_fit);setTimeout(_fit,120);setTimeout(_fit,600);})();
</script></body></html>'''


def _render_macro_backtest(data, scarr):
    """종합 강도 v5 월별 궤적(2016.1~) vs 서울 '매매지수 3개월 변화율' 오버레이(백테스트).

    v4에서 도입한 타깃 정의(레벨→모멘텀)와 같은 축으로 비교해야 산식·임계 검증이 성립한다 —
    v3까지는 완만한 '레벨'에 지그재그 '강도'를 겹쳐 '안 맞아 보이는' 착시가 있었다
    (2026-07 v4 전환). 두 선의 실측 상관(corr)을 라벨에 함께 표기한다.
    점수(scarr)는 결측(None)을 정렬 그대로 두고 전체 기간을 그린다 — 과거 구간
    결측을 압축하면 월 축이 어긋나고, 매매지수와 교집합으로 자르면 매매지수
    보관 길이(짧을 수 있음)가 점수 궤적까지 잘라버린다(24.06부터만 표시되던
    버그 · 2026-07 수정). 변화율은 가용 구간만 부분 오버레이(선 분절 허용).
    """
    import json as _json
    if not scarr or sum(1 for v in scarr if v is not None) < 12:
        return
    by = {it.get("key"): it for it in (data or [])}
    _sm = [(None if v is None else float(v))
           for v in ((by.get("sale_m") or {}).get("series") or [])]
    if len([v for v in _sm if v is not None]) >= 24:
        sale, step = _sm, 1                # 월간 지수(장기 백필) — 1:1 인덱싱
    else:
        sale = [(None if v is None else float(v))
                for v in ((by.get("sale") or {}).get("series") or [])]
        step = 4                           # 주간 폴백 → 월 샘플링(4주 간격)
    m = len(scarr)
    lev = []                               # lev[mb] = mb개월 전 지수 레벨
    for mb in range(m + 3):
        i = len(sale) - 1 - mb * step
        v = sale[i] if 0 <= i < len(sale) else None
        lev.append(float(v) if v is not None else None)
    chg = []                               # chg[mb] = mb개월 전 3개월 변화율(%)
    for mb in range(m):
        a, b = lev[mb], lev[mb + 3]
        chg.append(round((a / b - 1) * 100, 2)
                   if (a is not None and b) else None)
    # 실측 일치도(corr) — 점수·변화율 동시 가용 월만(12개월 미만이면 미표기)
    pairs = [(s, c) for s, c in zip(scarr, chg)
             if s is not None and c is not None]
    corr_txt = ""
    if len(pairs) >= 12:
        xs = [p[0] for p in pairs]
        ys_ = [p[1] for p in pairs]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys_) / n
        sx = (sum((v - mx) ** 2 for v in xs)) ** 0.5
        sy = (sum((v - my) ** 2 for v in ys_)) ** 0.5
        if sx and sy:
            cv = sum((p - mx) * (q - my) for p, q in zip(xs, ys_)) / (sx * sy)
            corr_txt = f" · 일치도 corr {'+' if cv >= 0 else '−'}{abs(cv):.2f}"
    sc2 = list(scarr)[::-1]                # 과거→현재 · None 유지(선 분절)
    sale2 = chg[::-1]
    dts = _dates_back(len(sc2), 30)
    html = (_BT_HTML
            .replace("__SC__", _json.dumps(sc2))
            .replace("__SD__", _json.dumps([_dlabel(d) for d in dts]))
            .replace("__SALE__", _json.dumps(sale2))
            .replace("__CORR__", corr_txt))
    components.html(html, height=330, scrolling=False)


def _render_macro_section(data, scarr=None):
    """거시 상세 추이 — 6차트(코스피 양식) + 가중치 설명 버튼 + 백테스트."""
    import json as _json
    st.markdown('<div class="re-grp">거시 상세 추이'
                '<span class="sub">주담대·착공·매수우위·M2·GDP·전세가율 — 2016년~ · '
                '종합 강도 v5 입력·참고 지표 · 메인 상세</span></div>', unsafe_allow_html=True)
    # 종합 강도 궤적은 섹션 헤더 바로 아래(2026-07 이동) — 결론(궤적)을 먼저,
    # 근거(6지표 차트)를 그 아래에 두는 편집 순서.
    _render_macro_backtest(data, scarr)
    _c1, _c2 = st.columns([3, 2])
    with _c1:
        period = st.radio("기간", list(_MACRO_PERIODS.keys()), index=2,
                          horizontal=True, key="re_macro_period",
                          label_visibility="collapsed")
    with _c2:
        # 산식·가중치 설명은 'KB 실데이터 ⓘ'와 동일한 foot_row 배지(details 필)로
        # 통일 — 클릭 시 아래로 펼쳐진다. v3(2026-07)부터 산식이 표 형식이라
        # foot_row(평문 이스케이프)를 못 쓰고 동일 클래스로 직접 조립한다.
        st.markdown(_v5_spec_foot_row(), unsafe_allow_html=True)
    months = _MACRO_PERIODS.get(period)
    charts = _macro_chart_payload(data, months)
    if not charts:
        st.caption("거시 지표 데이터가 아직 없어요. 아침 자동 수집 후 표시됩니다.")
        return
    rows = -(-len(charts) // 2)
    components.html(_MACRO_HTML.replace("__CH__",
                                        _json.dumps(charts, ensure_ascii=False)),
                    height=rows * 330 + 20, scrolling=False)
    _live = any((it.get("key") == "mortgage" and "샘플" not in it.get("sub", ""))
                for it in (data or []))
    st.markdown(foot_row(
        "ECOS(한국은행) · KB" if _live else "일부 샘플 · 아침 수집 후 실데이터로 교체",
        "주담대 차트의 점선=한국은행 기준금리(비교용) · 착공=주거용 착공 YoY 3개월 평균"
        "(감소=중기 공급부족 신호) · M2=평잔·원계열 전년동월비 · GDP=분기 전기비 · "
        "가는 실선(우축)=절대 수준 병기 — 착공량 3M평균(만호)·M2 평잔(조원)·"
        "GDP 수준(전기비 누적·16Q1=100)·매매/전세지수(KB 월간, 전세가율 차트) · "
        "십자선 호버로 시점별 값 확인 · 백테스트=종합 강도 v5를 2016년부터 소급 계산해 "
        "매매지수 3개월 변화율과 비교(가중치·임계·lag 검증용)"), unsafe_allow_html=True)
