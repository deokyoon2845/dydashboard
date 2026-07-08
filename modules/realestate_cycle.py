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
ECOS_MORTGAGE_STAT = "722Y001"   # 예금은행 가중평균금리(신규취급액 기준)


ECOS_MORTGAGE_ITEM = "BECABA03"  # 주택담보대출 ← 값이 안 맞으면 이 item 코드만 확인/교체


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
_INDV2_CORE = ("buy", "outlook")


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
(function(){function _fit(){try{var h=Math.ceil(document.body.getBoundingClientRect().height)+2;if(window.frameElement){window.frameElement.style.height=h+"px";window.frameElement.setAttribute("height",h);}}catch(e){}}window.addEventListener("load",_fit);setTimeout(_fit,150);setTimeout(_fit,600);setTimeout(_fit,1500);window.addEventListener("resize",_fit);try{new ResizeObserver(_fit).observe(document.body);}catch(e){}})();
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
.pc-mom{font-size:10.5px;font-weight:800;margin:0 0 2px}
.pc-mom.up{color:var(--up)}.pc-mom.dn{color:var(--dn)}.pc-mom.fl{color:var(--muted)}
.pc-mom small{font-weight:600;color:var(--muted);font-size:9px;margin-left:2px}
@media(max-width:680px){.core{grid-template-columns:1fr}.row{grid-template-columns:1.3fr 96px 74px}.r-mid{display:none}.price{grid-template-columns:1fr}}
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
  <div class="sec">핵심 3 · 지금 시장을 설명하는 지표</div>
  <div class="core" id="core"></div>
  <div class="sec">그룹별 지표</div>
  <div id="groups"></div>
  <div class="foot" id="foot"></div>
</div>
<script>
const IND=__IND__,PEND=__PEND__,G=__G__;
const PRICE=__PRICE__;
const ASOF=new Date("__ASOF__T00:00:00");
const MON=["1월","2월","3월","4월","5월","6월","7월","8월","9월","10월","11월","12월"];
const GORDER=["lead","coin","supply"];
const CORE=["buy","outlook"];
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
function renderCore(){const host=document.getElementById("core");
 host.innerHTML=CORE.map(function(k){const m=byK(k);return m?coreCard(m):coreMissCard(k);}).join("");}
function renderGroups(){let html="";
 for(const gk of GORDER){const ms=IND.filter(m=>m.g===gk&&CORE.indexOf(m.k)<0);const ps=PEND.filter(p=>p.g===gk&&CORE.indexOf(p.k)<0);
  if(!ms.length&&!ps.length)continue;
  html+='<div class="grp"><div class="glab">'+G[gk].name+' <em>'+G[gk].desc+'</em></div>'
   +'<div class="rows">'+ms.map(rowHTML).join("")+ps.map(pendRow).join("")+'</div></div>';}
 document.getElementById("groups").innerHTML=html;}
function priceDelta(arr){if(!arr||arr.length<2)return null;
 const cur=arr[arr.length-1],prev=arr[arr.length-2],d=cur-prev;if(!prev)return null;
 const pct=d/prev*100,cls=Math.abs(pct)<0.05?"fl":pct>0?"up":"dn";
 return {cls,pct:(pct>0?"+":pct<0?"−":"±")+Math.abs(pct).toFixed(1),amt:(d>0?"+":d<0?"−":"±")+Math.abs(d).toFixed(2)};}
function priceCard(p){const med=p.med||[],mean=p.mean||[];
 const lastMed=med.length?med[med.length-1]:null;
 const lastMean=mean.length?mean[mean.length-1]:null;
 const m={col:"#7E9A83",baseline:null,base:lastMed,unit:"억",cad:"month",real:med.length?med:mean};
 const pts=makeSeries(m);const dm=priceDelta(med.length?med:mean);
 let big="";
 if(lastMed!=null)big='<div class="pc-val">'+lastMed.toFixed(1)+'<span class="u">억</span><span class="lab">중위</span></div>';
 else if(lastMean!=null)big='<div class="pc-val">'+lastMean.toFixed(1)+'<span class="u">억</span><span class="lab">평균</span></div>';
 const mom=dm?'<div class="pc-mom '+dm.cls+'">전월 '+arrow(dm.cls)+' '+dm.pct+'%<small>'+dm.amt+'억</small></div>':'';
 const meanLine=(lastMean!=null&&lastMed!=null)?'<div class="pc-mean">평균 <b>'+lastMean.toFixed(1)+'억</b></div>':'';
 const chart=pts.length>1?miniChart(m,pts):'';
 return '<div class="pc"><div class="pc-top"><span class="pc-reg">'+p.lab+'</span>'
  +'<span class="pc-tag">아파트 매매 · 월간(KB)</span></div>'+big+mom+meanLine+chart+'</div>';}
function renderPrice(){if(!PRICE||!PRICE.length)return;
 document.getElementById("price").innerHTML=PRICE.map(priceCard).join("");
 document.getElementById("priceSec").style.display="";}
function renderCycle(){const order=["침체기","회복기","상승기","둔화기"];
 const subs={"침체기":"가격↓ 거래↓","회복기":"심리·거래 반등","상승기":"가격·심리 강세","둔화기":"상승폭 축소"};
 const lead=IND.filter(m=>m.g==="lead"||m.k==="jsup");
 const CYCSHORT={buy:"매수우위",outlook:"매매전망",lead50:"선도50",jsup:"전세수급"};
 function cycScore(mb){let sc=0,n=0;lead.forEach(function(m){const r=m.real||[];const off=mb*(m.cad==="month"?1:4);
   if(r.length>off+2){const mm=Object.assign({},m,{real:off?r.slice(0,r.length-off):r});sc+=signal(mm,makeSeries(mm)).score;n++;}});
  return n?sc/n:0;}
 const sc=cycScore(0);
 let cur=lead.length?(sc>0.05?"상승기":sc>0.0?"회복기":sc>-0.05?"둔화기":"침체기"):"회복기";
 document.getElementById("nowStage").textContent=cur;
 document.getElementById("stages").innerHTML=order.map(s=>'<div class="stage '+(s===cur?"on":"")+'">'+s+'<small>'+subs[s]+'</small></div>').join("");
 // 판정 근거 — 기여 칩(방향 + 미니 스파크) + 종합 강도/추세
 const leadByK={};lead.forEach(function(m){leadByK[m.k]=m;});
 const sigs=lead.map(function(m){return {k:m.k,nm:CYCSHORT[m.k]||m.lab,c:signal(m,makeSeries(m)).cls,m:m};});
 const chips=sigs.map(function(x){
   return '<span class="why-chip '+x.c+'"><span class="wc-hd">'+arrow(x.c)+' '+x.nm+'</span>'
    +chipSpark(x.m)+'</span>';}).join("");
 const ups=sigs.filter(x=>x.c==="up").length,dns=sigs.filter(x=>x.c==="dn").length;
 let mix;if(lead.length&&ups===lead.length)mix='모두 <b class="up">상승 기여</b>';
  else if(lead.length&&dns===lead.length)mix='모두 <b class="dn">하락 기여</b>';
  else mix=ups+'개 <b class="up">상승</b> · '+dns+'개 <b class="dn">하락</b>'+((lead.length-ups-dns)?' · '+(lead.length-ups-dns)+'개 보합':'');
 const dlt=sc-cycScore(1);
 const traj=Math.abs(dlt)<0.005?'<b>유지</b>':(dlt>0?'<b class="up">강화 ↗</b>':'<b class="dn">약화 ↘</b>');
 const scStr=(sc>=0?"+":"−")+Math.abs(sc).toFixed(2);
 document.getElementById("cycWhy").innerHTML='<div class="why-lab">판정 근거 — 선행·심리 '+lead.length+'지표</div>'
  +'<div class="why-chips">'+chips+'</div>'
  +'<div class="why-summ">'+mix+' → 종합 강도 <b>'+scStr+'</b> · 직전 대비 '+traj+'</div>';
 // 종합 강도 위치 게이지(임계 −.05 / 0 / +.05 표시 + needle)
 function stageOf(s){return s>0.05?"상승기":s>0?"회복기":s>-0.05?"둔화기":"침체기";}
 const Z=[["침체기","침체","#5A7CA0",0,33.33],["둔화기","둔화","#A9C0DA",33.33,50],
          ["회복기","회복","#E9BDB8",50,66.67],["상승기","상승","#C16C64",66.67,100]];
 // 구역(침체|둔화|회복|상승) 비율은 33/50/67 그대로 두고, 바깥(침체·상승)이
 // 넓은 점수 범위를 흡수하도록 piecewise 매핑(임계 ±T=±.05 · 양끝 ±GO=±.50).
 const T=0.05,GO=0.50;
 function gPos(s){
   if(s<=-GO)return 0;
   if(s< -T)return (s+GO)/(GO-T)*33.33;      // 침체: -GO..-T → 0..33.33
   if(s<  0)return 33.33+(s+T)/T*16.67;      // 둔화: -T..0  → 33.33..50
   if(s<  T)return 50+s/T*16.67;             // 회복: 0..T   → 50..66.67
   if(s< GO)return 66.67+(s-T)/(GO-T)*33.33; // 상승: T..GO  → 66.67..100
   return 100;}
 const nx=gPos(sc);
 const zoneDivs=Z.map(z=>'<div class="cg-zone" style="width:'+(z[4]-z[3]).toFixed(2)+'%;background:'+z[2]+'"></div>').join("");
 const ticks='<span style="left:33.33%">−.05</span><span style="left:50%">0</span><span style="left:66.67%">+.05</span>';
 const zlabs=Z.map(z=>'<span class="'+(z[0]===cur?"on":"")+'" style="left:'+((z[3]+z[4])/2).toFixed(2)+'%">'+z[1]+'</span>').join("");
 // 강도 추이(최근 12개월) — 모멘텀 꺾임/전환 임박을 게이지 바로 위에서 보여준다.
 const strTrend=strengthChart(cycScore,12,T);
 const trendCap=Math.abs(dlt)<0.005?'최근 <b>유지</b>':(dlt>0?'최근 <b class="up">강화 ↗</b>':'최근 <b class="dn">약화 ↘</b>');
 document.getElementById("cycGauge").innerHTML=
   '<div class="cg-lab">종합 강도 추이 — 최근 12개월 · 0선 위=상승 우세 / 아래=하락 우세</div>'
   +(strTrend?'<div class="str-wrap">'+strTrend+'<div class="str-cap">'+trendCap+' · 현재 <b>'+scStr+'</b></div></div>':'')
   +'<div class="cg-lab" style="margin-top:9px">현재 위치 — 임계 ±0.05 기준 국면 판정</div>'
   +'<div class="cg-wrap"><div class="cg-track">'+zoneDivs+'</div><div class="cg-needle" style="left:'+nx.toFixed(1)+'%"></div></div>'
   +'<div class="cg-ticks">'+ticks+'</div><div class="cg-zlab">'+zlabs+'</div>';
 // 현재 국면 지속 개월수 + 직전 국면(궤적)
 let hold=0,prev=cur;
 for(let mb=1;mb<=24;mb++){const ps=cycScore(mb);const st=stageOf(ps);if(st!==cur){prev=st;break;}hold=mb;}
 const trajLine=hold>0
   ?'현재 <b>'+cur+'</b> '+(hold+1)+'개월차'+(prev!==cur?'(직전 '+prev+'에서 전환)':'')+'. '
   :'현재 <b>'+cur+'</b>. ';
 document.getElementById("cycRead").innerHTML=trajLine+'국면 전환은 매수우위·전망지수가 기준 100을 위아래로 넘을 때 먼저 신호가 나와요.';}
function renderFoot(){const soon=PEND.filter(p=>p.st==="soon");
 let s='미니차트는 최근 1년(가로축 월 단위)';
 if(soon.length)s+=' · 연결예정 '+soon.length+'종('+soon.map(p=>p.lab).join("·")+')';
 document.getElementById("foot").innerHTML=s;}
renderCycle();renderPrice();renderCore();renderGroups();renderFoot();
(function(){function _fit(){try{var h=Math.ceil(document.body.getBoundingClientRect().height)+2;if(window.frameElement){window.frameElement.style.height=h+"px";window.frameElement.setAttribute("height",h);}}catch(e){}}window.addEventListener("load",_fit);setTimeout(_fit,150);setTimeout(_fit,600);setTimeout(_fit,1500);window.addEventListener("resize",_fit);try{new ResizeObserver(_fit).observe(document.body);}catch(e){}})();
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


def _indicator_chart_component(ind, pend, price, asof):
    import json as _json
    return (_INDV2_HTML
            .replace("__IND__", _json.dumps(ind, ensure_ascii=False))
            .replace("__PEND__", _json.dumps(pend, ensure_ascii=False))
            .replace("__PRICE__", _json.dumps(price, ensure_ascii=False))
            .replace("__G__", _json.dumps(_INDV2_GROUPS, ensure_ascii=False))
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
    # 새 레이아웃 기준 높이 산정(클리핑 방지) — 헤더 + (가격블록) + 핵심 + 그룹 행들.
    _CORE = _INDV2_CORE
    core_n = len(_CORE)   # 핵심 카드(매수우위·매매전망)
    row_groups = {m["g"] for m in ind if m["k"] not in _CORE} | {p["g"] for p in pend}
    row_n = sum(1 for m in ind if m["k"] not in _CORE) + len(pend)
    height = (390                      # 사이클 헤더 + 판정근거(칩 스파크) + 강도 추이차트 + 위치 게이지
              + (60 + len(price) * 210 if price else 0)  # 현재 매매가격 블록(모바일 적층 여유)
              + 70                      # 핵심 섹션 라벨
              + ceil(max(core_n, 1) / 3) * 292   # 핵심 카드(미니차트+수위게이지)
              + 50                      # 그룹 섹션 라벨
              + len(row_groups) * 38    # 그룹 헤더들
              + row_n * 72              # 행들(스파크 시점축·Δ·수위게이지)
              + 80)                     # 푸터 여유
    components.html(_indicator_chart_component(ind, pend, price, asof),
                    height=height, scrolling=False)
    src = "KB 실데이터" if live else "샘플 · 아침 수집 후 실데이터로 교체"
    st.markdown(foot_row(
        src, "핵심(매수우위·매매전망) + 선행/동행/수급·심리 그룹 · "
             "미니차트 최근 1년(월 단위 축)"), unsafe_allow_html=True)


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
