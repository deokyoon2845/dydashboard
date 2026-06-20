"""한·미 금리차 카드 — 단기(미2년−한3년)·장기(미10년−한10년).

데이터 소스:
- 미국: FRED 공개 CSV (API 키 불필요) — DGS2(2년), DGS10(10년)
- 한국: 한국은행 ECOS API (ECOS_API_KEY 필요) — 국고채 3년·10년
        통계표 817Y002 '시장금리(일별)'

ECOS 항목코드는 시점에 따라 바뀔 수 있어, 항목 '이름'으로 코드를 찾아 쓴다.
모든 외부 호출은 실패해도 빈 값으로 떨어지며 앱을 멈추지 않는다.

2026-06 추가: 금리차 해석 팝오버(st.popover) — 구버전이면 조용히 생략.
2026-06 추가: 금리차 카드에 3개월(미국−한국) 추이 미니차트(하단 보름 눈금 + 월 라벨).
  FRED·ECOS 조회 창을 ~100일로 늘리고, 날짜 정합(ffill) 후 (미−한) 시계열로 표시.
"""

import os
from datetime import datetime, timedelta

import pandas as pd
import requests
import streamlit as st

# 보름축 미니차트 헬퍼 재사용 (indices.py 정의)
from modules.indices import sparkline_axis_html

ECOS_TABLE = "817Y002"   # 시장금리(일별)


def _cfg(key: str, default: str = "") -> str:
    v = os.environ.get(key)
    if v:
        return v
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


# ── 미국: FRED (키 불필요) ─────────────────────────────────
@st.cache_data(ttl=3600)
def _fred_latest(series_id: str):
    """FRED 시계열의 (날짜, 값) 리스트(최근 약 100일, 오름차순). 실패 시 []."""
    start = (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%d")
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}"
    try:
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        out = []
        for ln in r.text.strip().splitlines()[1:]:  # 첫 줄은 헤더
            parts = ln.split(",")
            if len(parts) < 2:
                continue
            d, v = parts[0], parts[1].strip()
            if v not in (".", ""):       # FRED 결측치는 "."
                out.append((d, float(v)))
        return out
    except Exception:
        return []


# ── 한국: ECOS ─────────────────────────────────────────────
@st.cache_data(ttl=86400)
def _ecos_items(key: str):
    """817Y002의 {항목이름: 항목코드} 매핑. 실패 시 {}."""
    url = f"https://ecos.bok.or.kr/api/StatisticItemList/{key}/json/kr/1/300/{ECOS_TABLE}"
    try:
        r = requests.get(url, timeout=12)
        rows = r.json().get("StatisticItemList", {}).get("row", [])
        return {row.get("ITEM_NAME", ""): row.get("ITEM_CODE", "") for row in rows}
    except Exception:
        return {}


def _find_code(items: dict, *keywords):
    """항목 이름에 keywords가 모두 들어간 첫 항목코드."""
    for name, code in items.items():
        if name and all(k in name for k in keywords):
            return code
    return None


@st.cache_data(ttl=3600)
def _ecos_latest(key: str, item_code):
    """ECOS 항목의 (날짜, 값) 리스트(최근 약 100일, 오름차순). 실패 시 []."""
    if not item_code:
        return []
    end = datetime.now()
    start = end - timedelta(days=100)
    url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/300/"
           f"{ECOS_TABLE}/D/{start:%Y%m%d}/{end:%Y%m%d}/{item_code}")
    try:
        r = requests.get(url, timeout=12)
        rows = r.json().get("StatisticSearch", {}).get("row", [])
        out = []
        for row in rows:
            v = row.get("DATA_VALUE")
            t = row.get("TIME")
            if v not in (None, "", "."):
                out.append((t, float(v)))
        out.sort()
        return out
    except Exception:
        return []


def _last(vals):
    return vals[-1] if vals else None


def _to_series(vals, ecos=False):
    """[(날짜, 값)] → 날짜 인덱스 pd.Series(오름차순). ecos=True면 YYYYMMDD 포맷 처리."""
    idx, data = [], []
    for d, v in vals:
        s = str(d)
        if ecos and len(s) == 8:
            s = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        try:
            idx.append(pd.Timestamp(s))
            data.append(float(v))
        except Exception:
            continue
    if not idx:
        return pd.Series(dtype=float)
    return pd.Series(data, index=pd.DatetimeIndex(idx)).sort_index()


def _gap_series(us_vals, kr_vals):
    """미국·한국 (날짜,값) 리스트를 날짜 정합(ffill)해 (미−한) 금리차 Series 반환. 부족 시 None."""
    us = _to_series(us_vals)
    kr = _to_series(kr_vals, ecos=True)
    if us.empty or kr.empty:
        return None
    allidx = us.index.union(kr.index)
    us = us.reindex(allidx).ffill()
    kr = kr.reindex(allidx).ffill()
    gap = (us - kr).dropna()
    return gap if len(gap) >= 2 else None


def _gap_help():
    """한·미 금리차 해석 팝오버. st.popover 미지원(구버전)이면 조용히 생략."""
    if not hasattr(st, "popover"):
        return
    with st.popover("ⓘ 금리차 보는 법"):
        st.markdown(
            "**한·미 금리차 = 미국 금리 − 한국 금리**  \n"
            "양수(미국 우위)일수록 더 높은 금리를 좇아 외국인 자금이 미국으로 이동하기 쉬워 "
            "**외국인 자금 유출·원화 약세** 압력으로 읽혀요. "
            "음수(한국 우위)면 반대로 원화에 우호적인 구간입니다.\n\n"
            "단기는 미2년−한2/3년, 장기는 미10년−한10년 국고채 기준이에요.  \n"
            "미국: FRED(미 재무부 금리) · 한국: 한국은행 ECOS."
        )


# ── 렌더 ────────────────────────────────────────────────────
def render_rate_gap():
    # 헤더 + 설명 팝오버
    hc1, hc2 = st.columns([4, 1])
    with hc1:
        st.markdown('<div class="mkt-group">🇰🇷🇺🇸 한·미 금리차</div>',
                    unsafe_allow_html=True)
    with hc2:
        _gap_help()

    key = _cfg("ECOS_API_KEY")
    if not key:
        st.caption("한국 국고채 데이터를 위해 ECOS_API_KEY가 필요해요. "
                   "Secrets에 키를 넣으면 표시됩니다. (미국 금리는 키 없이 동작)")
        return

    items = _ecos_items(key)
    # 한국 단기 대표는 국고채 3년 (2년물이 있으면 우선 사용)
    kr_short_code = _find_code(items, "국고채", "2년") or _find_code(items, "국고채", "3년")
    kr_short_label = "한 2년" if _find_code(items, "국고채", "2년") else "한 3년"
    kr_long_code = _find_code(items, "국고채", "10년")

    # 헤드라인용 최신값 + 미니차트용 전체 시계열
    us2_v = _fred_latest("DGS2")
    us10_v = _fred_latest("DGS10")
    krs_v = _ecos_latest(key, kr_short_code)
    krl_v = _ecos_latest(key, kr_long_code)

    us2, us10 = _last(us2_v), _last(us10_v)
    kr_s, kr_l = _last(krs_v), _last(krl_v)

    short_series = _gap_series(us2_v, krs_v)
    long_series = _gap_series(us10_v, krl_v)

    def _gap_spark(series):
        # 금리차 카드는 흰 배경(.mkt-card) → 세이지 선 + 무채색 라벨
        return sparkline_axis_html(series, "#7E9A83", height=38, n_days=92,
                                   label_color="#9a9b92")

    def _gap_card(label, us, kr, us_lbl, kr_lbl, series=None):
        if not us or not kr:
            return (f'<div class="mkt-card"><div class="mkt-name">{label}</div>'
                    f'<div class="mkt-na">데이터 없음</div></div>')
        gap = us[1] - kr[1]
        sign = "미국 우위" if gap >= 0 else "한국 우위"
        spark = _gap_spark(series)
        return (f'<div class="mkt-card"><div class="mkt-name">{label}</div>'
                f'<div class="mkt-val">{gap:+.2f}%p</div>'
                f'<div class="mkt-chg" style="color:#9a9b92">{sign}</div>'
                f'<div style="font-size:.72rem;color:#9a9b92;margin-top:3px">'
                f'{us_lbl} {us[1]:.2f}% · {kr_lbl} {kr[1]:.2f}%</div>{spark}</div>')

    cards = ""
    cards += _gap_card(f"단기 (미2년−{kr_short_label.replace('한 ','한')})",
                       us2, kr_s, "미 2년", kr_short_label, short_series)
    cards += _gap_card("장기 (미10년−한10년)", us10, kr_l, "미 10년", "한 10년", long_series)
    st.markdown(f'<div class="mkt-grid">{cards}</div>', unsafe_allow_html=True)

    st.caption("금리차 = 미국 − 한국 · 양수(미국 우위)일수록 외국인 자금 유출·"
               "원화 약세 압력으로 읽히는 구간 · 미니차트 = 3개월 추이(눈금=보름) · "
               "미국: FRED · 한국: 한국은행 ECOS")
