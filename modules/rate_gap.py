"""한·미 금리차 카드 — 단기(미2년−한3년)·장기(미10년−한10년).

데이터 소스:
- 미국: FRED 공개 CSV (API 키 불필요) — DGS2(2년), DGS10(10년)
- 한국: 한국은행 ECOS API (ECOS_API_KEY 필요) — 국고채 3년·10년
        통계표 817Y002 '시장금리(일별)'

ECOS 항목코드는 시점에 따라 바뀔 수 있어, 항목 '이름'으로 코드를 찾아 쓴다.
모든 외부 호출은 실패해도 빈 값으로 떨어지며 앱을 멈추지 않는다.

2026-06 추가: 금리차 해석 팝오버(st.popover) — 구버전이면 조용히 생략.
"""

import os
from datetime import datetime, timedelta

import requests
import streamlit as st

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
    """FRED 시계열의 (날짜, 값) 리스트(최근 약 40일). 실패 시 []."""
    start = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d")
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
    """ECOS 항목의 (날짜, 값) 리스트. 실패 시 []."""
    if not item_code:
        return []
    end = datetime.now()
    start = end - timedelta(days=20)
    url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/100/"
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

    us2 = _last(_fred_latest("DGS2"))
    us10 = _last(_fred_latest("DGS10"))
    kr_s = _last(_ecos_latest(key, kr_short_code))
    kr_l = _last(_ecos_latest(key, kr_long_code))

    def _gap_card(label, us, kr, us_lbl, kr_lbl):
        if not us or not kr:
            return (f'<div class="mkt-card"><div class="mkt-name">{label}</div>'
                    f'<div class="mkt-na">데이터 없음</div></div>')
        gap = us[1] - kr[1]
        sign = "미국 우위" if gap >= 0 else "한국 우위"
        return (f'<div class="mkt-card"><div class="mkt-name">{label}</div>'
                f'<div class="mkt-val">{gap:+.2f}%p</div>'
                f'<div class="mkt-chg" style="color:#9a9b92">{sign}</div>'
                f'<div style="font-size:.72rem;color:#9a9b92;margin-top:3px">'
                f'{us_lbl} {us[1]:.2f}% · {kr_lbl} {kr[1]:.2f}%</div></div>')

    cards = ""
    cards += _gap_card(f"단기 (미2년−{kr_short_label.replace('한 ','한')})",
                       us2, kr_s, "미 2년", kr_short_label)
    cards += _gap_card("장기 (미10년−한10년)", us10, kr_l, "미 10년", "한 10년")
    st.markdown(f'<div class="mkt-grid">{cards}</div>', unsafe_allow_html=True)

    st.caption("금리차 = 미국 − 한국 · 양수(미국 우위)일수록 외국인 자금 유출·"
               "원화 약세 압력으로 읽히는 구간 · 미국: FRED · 한국: 한국은행 ECOS")
