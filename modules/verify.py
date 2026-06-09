"""감성 vs 실제 지수 검증: 채널 감성이 지수 움직임과 맞았는지 평가."""

import altair as alt
import pandas as pd
import streamlit as st

from modules.indices import INDEX_GROUPS, fetch_history
from modules.trends import _sentiment_series

# 검증 대상 후보 (표시명 -> 티커): 국내·미국 지수
_CANDIDATES = {}
for _g in ("국내", "미국"):
    _CANDIDATES.update(INDEX_GROUPS.get(_g, {}))


def _returns_frame(ticker):
    close = fetch_history(ticker)
    if close is None or len(close) < 3:
        return None
    df = close.to_frame("close")
    df["ret"] = df["close"].pct_change() * 100        # 같은날 등락률(%)
    df["ret_next"] = df["ret"].shift(-1)              # 익일 등락률(%)
    return df


def _hit_rate(sent, ret):
    """감성 부호와 등락 부호가 일치한 비율 (감성 0·결측은 제외)."""
    hit = n = 0
    for s, r in zip(sent, ret):
        if s == 0 or pd.isna(r):
            continue
        n += 1
        if (s > 0 and r > 0) or (s < 0 and r < 0):
            hit += 1
    return hit, n


def render_verify():
    st.divider()
    st.markdown('<div class="mkt-group">감성 vs 실제 지수 검증</div>', unsafe_allow_html=True)

    series = _sentiment_series()
    if len(series) < 3:
        st.caption("리포트가 며칠 더 쌓이면, 채널 감성이 실제 지수와 맞았는지 비교해드려요.")
        return

    name = st.selectbox("기준 지수", list(_CANDIDATES.keys()), key="vf_idx")
    ticker = _CANDIDATES[name]

    rdf = _returns_frame(ticker)
    if rdf is None:
        st.caption("지수 데이터를 가져오지 못했어요. 잠시 후 다시 시도해주세요.")
        return

    sdf = pd.DataFrame(series, columns=["date", "sentiment"]).groupby("date", as_index=False).mean()
    sdf["date"] = pd.to_datetime(sdf["date"]).dt.normalize()
    merged = sdf.merge(rdf[["ret", "ret_next"]], left_on="date", right_index=True, how="inner")

    if merged.empty:
        st.caption("리포트 날짜와 지수 거래일이 겹치지 않아 비교할 수 없어요.")
        return

    hs, ns = _hit_rate(merged["sentiment"], merged["ret"])
    hn, nn = _hit_rate(merged["sentiment"], merged["ret_next"])

    c1, c2, c3 = st.columns(3)
    c1.metric("표본", f"{len(merged)}일")
    c2.metric("같은날 방향 적중", f"{hs / ns * 100:.0f}%" if ns else "—", help=f"{hs}/{ns}일")
    c3.metric("익일 방향 적중", f"{hn / nn * 100:.0f}%" if nn else "—", help=f"{hn}/{nn}일")

    if len(merged) < 5:
        st.caption("⚠️ 표본이 적어 적중률은 참고만 하세요 (며칠 더 쌓이면 신뢰도↑).")

    # 막대=감성 / 선=지수 같은날 등락률
    dark = st.session_state.get("dark", False)
    up = "#F0A3AB" if dark else "#B65F5A"
    down = "#94B6EA" if dark else "#5A7CA0"
    sage = "#A8D8C0" if dark else "#7E9A83"
    axis_c = "#9A9CAB" if dark else "#9a9b92"

    mdf = merged.rename(columns={"ret": "지수등락"})
    base = alt.Chart(mdf).encode(
        x=alt.X("date:T", axis=alt.Axis(title=None, format="%m/%d", labelColor=axis_c, grid=False))
    )
    bars = base.mark_bar(opacity=0.55).encode(
        y=alt.Y("sentiment:Q", scale=alt.Scale(domain=[-1, 1]),
                axis=alt.Axis(title="감성", labelColor=axis_c)),
        color=alt.condition(alt.datum.sentiment >= 0, alt.value(up), alt.value(down)),
    )
    line = base.mark_line(point=True, color=sage, strokeWidth=2).encode(
        y=alt.Y("지수등락:Q", axis=alt.Axis(title="지수 %", labelColor=axis_c))
    )
    chart = (alt.layer(bars, line).resolve_scale(y="independent")
             .properties(height=240, background="transparent").configure_view(strokeWidth=0))
    st.altair_chart(chart, use_container_width=True)

    st.caption(f"막대 = 채널 감성 / 선 = {name} 같은날 등락률. "
               "표본이 적으면 신뢰도가 낮습니다. ※ 검증용 참고치이며 투자 권유가 아닙니다.")
