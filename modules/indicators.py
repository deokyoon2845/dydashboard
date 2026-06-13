"""시장 지표(체온계): 공포·탐욕 지수 + VIX 차트 · RSI."""

import altair as alt
import pandas as pd
import streamlit as st

from modules.indices import fetch_history

_RSI_TARGETS = {"코스피": "^KS11", "코스닥": "^KQ11", "S&P500": "^GSPC", "나스닥": "^IXIC"}

_RATING_KO = {
    "extreme fear": "극단적 공포", "fear": "공포", "neutral": "중립",
    "greed": "탐욕", "extreme greed": "극단적 탐욕",
}


def compute_rsi(ticker, period=14):
    """지수 종가로 RSI(기본 14). 실패 시 None."""
    close = fetch_history(ticker)
    if close is None or len(close) < period + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    g, l = avg_gain.iloc[-1], avg_loss.iloc[-1]
    if l == 0:
        return 100.0
    return float(100 - 100 / (1 + g / l))


@st.cache_data(ttl=1800)
def fetch_cnn_fng():
    """CNN 공포·탐욕 지수(미국). 비공식 API."""
    try:
        import requests
        r = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                     "Accept": "application/json"},
            timeout=10,
        )
        r.raise_for_status()
        fg = r.json().get("fear_and_greed", {})
        if fg.get("score") is None:
            return None
        return {"score": round(float(fg["score"])), "rating": fg.get("rating", ""),
                "asof": _fng_asof(fg.get("timestamp"))}
    except Exception:
        return None


def _fng_asof(ts):
    """CNN timestamp(ISO 또는 ms)를 KST 'YYYY-MM-DD HH:MM'로."""
    if ts is None:
        return None
    try:
        from datetime import datetime, timezone, timedelta
        kst = timezone(timedelta(hours=9))
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt.astimezone(kst).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)[:16]


def _rsi_state(v):
    if v >= 70:
        return "과매수", "up"
    if v <= 30:
        return "과매도", "down"
    return "중립", ""


def _rsi_asof():
    """RSI 대상 지수들의 가장 최근 종가일 (YYYY-MM-DD)."""
    dates = []
    for tk in _RSI_TARGETS.values():
        c = fetch_history(tk)
        if c is not None and len(c):
            try:
                dates.append(c.index[-1].strftime("%Y-%m-%d"))
            except Exception:
                pass
    return max(dates) if dates else "—"


# ── VIX 6개월 차트 (우측) ────────────────────────────────────

_VIX_CSS = """
<style>
/* 공포탐욕 게이지 인디케이터: 막대 → 동그라미 */
.gauge{position:relative;height:8px;border-radius:5px;
  background:linear-gradient(90deg,#5A7CA0 0%,#A7BBA9 50%,#B65F5A 100%);margin:14px 0 7px;}
.gauge .dot{position:absolute;top:50%;width:16px;height:16px;border-radius:50%;
  background:#fff;border:3px solid var(--ink,#34352f);
  transform:translate(-50%,-50%);box-shadow:0 1px 3px rgba(0,0,0,.25);}
/* 지표 2단(공포탐욕 | VIX 차트) */
.tmpr-2col{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:10px;align-items:stretch;}
@media(max-width:760px){.tmpr-2col{grid-template-columns:1fr;}}
.tmpr-card{background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);border-radius:16px;
  padding:14px 16px 12px;}
.vix-head{display:flex;align-items:baseline;gap:8px;margin-bottom:2px;}
.vix-val{font-size:21px;font-weight:700;color:var(--ink,#34352f);letter-spacing:-.02em;}
.vix-chg{font-size:12.5px;font-weight:700;}
.vix-chg.up{color:var(--up,#B65F5A);} .vix-chg.down{color:var(--down,#5A7CA0);}
.vix-note{font-size:10.5px;color:var(--muted,#9a9b92);margin-top:6px;}
</style>
"""


def _vix_chart_card():
    """우측: VIX 6개월 라인 차트 (코스피 대형 차트와 동일한 룩, y축 min~max)."""
    close = fetch_history("^VIX", "6mo")
    if close is None or len(close) < 2:
        st.markdown(
            '<div class="tmpr-card"><div class="mkt-name">VIX · 변동성 지수 (6개월)</div>'
            '<div class="mkt-na">데이터 없음</div></div>', unsafe_allow_html=True)
        return

    df = pd.DataFrame({"날짜": pd.to_datetime(close.index),
                       "VIX": pd.to_numeric(close.values, errors="coerce")}).dropna()
    if len(df) < 2:
        st.markdown('<div class="tmpr-card"><div class="mkt-name">VIX (6개월)</div>'
                    '<div class="mkt-na">데이터 부족</div></div>', unsafe_allow_html=True)
        return

    cur = float(df["VIX"].iloc[-1])
    prev = float(df["VIX"].iloc[-2])
    change = cur - prev
    pct = (change / prev) * 100 if prev else 0.0
    # VIX는 하락이 시장에 우호적 → 색 반전(하락=파랑/안정, 상승=빨강/경계)
    up = change >= 0
    chg_cls = "up" if up else "down"
    arrow = "▲" if change > 0 else ("▼" if change < 0 else "▬")
    line_c = "#B65F5A" if up else "#5A7CA0"

    # y축: 0부터가 아니라 표시 구간의 최솟값~최댓값 (약간의 패딩)
    lo, hi = float(df["VIX"].min()), float(df["VIX"].max())
    pad = (hi - lo) * 0.08 or 1.0
    y_dom = [lo - pad, hi + pad]

    st.markdown(
        f'<div class="tmpr-card" style="padding-bottom:6px;">'
        f'<div class="mkt-name">VIX · 변동성 지수 (6개월)</div>'
        f'<div class="vix-head"><span class="vix-val">{cur:,.2f}</span>'
        f'<span class="vix-chg {chg_cls}">{arrow} {change:+,.2f} ({pct:+.2f}%)</span></div>',
        unsafe_allow_html=True)

    chart = alt.Chart(df).mark_area(
        color=line_c, opacity=0.13,
        line={"color": line_c, "strokeWidth": 2},
    ).encode(
        x=alt.X("날짜:T", axis=alt.Axis(title=None, format="%m/%d",
                                       labelColor="#9a9b92", grid=False)),
        y=alt.Y("VIX:Q", scale=alt.Scale(domain=y_dom, nice=False, clamp=True),
                axis=alt.Axis(title=None, labelColor="#9a9b92", gridColor="#ECEDE7",
                              format=",.0f")),
        tooltip=[alt.Tooltip("날짜:T", format="%Y-%m-%d"),
                 alt.Tooltip("VIX:Q", format=",.2f")],
    ).properties(height=150, background="transparent").configure_view(strokeWidth=0)
    st.altair_chart(chart, use_container_width=True)
    st.markdown('<div class="vix-note">VIX↑ = 변동성·공포 확대 · VIX↓ = 시장 안정 · '
                'y축은 표시 구간 최소~최대</div></div>', unsafe_allow_html=True)


def _fng_card(fng):
    """좌측: 공포·탐욕 지수 카드 (게이지 인디케이터 = 동그라미)."""
    if not fng:
        st.markdown(
            '<div class="tmpr-card"><div class="mkt-name">공포·탐욕 지수 · CNN (미국 기준)</div>'
            '<div class="mkt-na">불러오지 못했어요 (CNN 비공식 API)</div></div>',
            unsafe_allow_html=True)
        return
    ko = _RATING_KO.get((fng["rating"] or "").lower(), fng["rating"])
    asof = f' · 기준 {fng["asof"]} KST' if fng.get("asof") else ""
    score = max(0, min(100, fng["score"]))
    st.markdown(
        f'<div class="tmpr-card">'
        f'<div class="mkt-name">공포·탐욕 지수 · CNN (미국 기준)</div>'
        f'<div style="display:flex;align-items:baseline;gap:8px;margin-top:2px;">'
        f'<span class="mkt-val">{fng["score"]}</span>'
        f'<span style="font-weight:700;color:var(--muted);">/ 100 · {ko}</span></div>'
        f'<div class="gauge"><span class="dot" style="left:{score}%"></span></div>'
        f'<div style="font-size:10.5px;color:var(--muted);">공포(파랑) ↔ 탐욕(빨강) · '
        f'비공식 API{asof}</div>'
        f'</div>', unsafe_allow_html=True)


def render_indicators():
    st.markdown(_VIX_CSS, unsafe_allow_html=True)
    st.markdown('<div class="mkt-group">시장 지표 (체온계)</div>', unsafe_allow_html=True)

    # 공포·탐욕(좌) + VIX 6개월 차트(우) — 2단
    fng = fetch_cnn_fng()
    left, right = st.columns(2, gap="medium")
    with left:
        _fng_card(fng)
    with right:
        _vix_chart_card()

    # RSI
    rcards = []
    for name, tk in _RSI_TARGETS.items():
        v = compute_rsi(tk)
        if v is None:
            rcards.append(f'<div class="mkt-card"><div class="mkt-name">{name} RSI</div>'
                          f'<div class="mkt-na">데이터 없음</div></div>')
            continue
        state, tone = _rsi_state(v)
        tint = {"up": "mkt-up", "down": "mkt-down", "": ""}[tone]
        pos = max(0, min(100, v))
        rcards.append(
            f'<div class="mkt-card {tint}"><div class="mkt-name">{name} RSI(14)</div>'
            f'<div style="display:flex;align-items:baseline;gap:6px;">'
            f'<span class="mkt-val">{v:.0f}</span>'
            f'<span class="mkt-chg {tone}" style="margin:0;">{state}</span></div>'
            f'<div class="rsi-gauge"><span class="t30"></span><span class="t70"></span>'
            f'<i class="{tone}" style="left:{pos}%"></i></div></div>')
    st.markdown(f'<div class="mkt-grid">{"".join(rcards)}</div>', unsafe_allow_html=True)
    st.caption(f"RSI ≥70 과매수 · ≤30 과매도 (종가 14일 · 기준 {_rsi_asof()}). 데이터: yfinance · CNN.")
