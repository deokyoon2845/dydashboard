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


def _scoreboard_hero(scores):
    """원형 게이지 + 최근 예측 ○× 스트립 HTML."""
    acc = scores.get("accuracy")
    total = scores.get("total", 0)
    hits = scores.get("hits", 0)
    acc_val = acc if acc is not None else 0

    # 게이지 색: mood 팔레트와 통일 (60%↑ 긍정 / 50~60 중립 / 미만 주의)
    from modules.mood import mood_main
    dark = st.session_state.get("dark", False)
    if acc is None:
        ring = "var(--muted)"
    elif acc_val >= 60:
        ring = mood_main("positive", dark)
    elif acc_val >= 50:
        ring = mood_main("neutral", dark)
    else:
        ring = mood_main("cautious", dark)
    acc_txt = f"{acc_val:.0f}%" if acc is not None else "—"

    # 최근 24건 ○× 스트립 (최신이 오른쪽)
    recs = scores.get("records", [])[-24:]
    chips = "".join(
        f'<span class="ox {"ox-hit" if r.get("hit") else "ox-miss"}" '
        f'title="{r.get("date","")} · {r.get("mood","")} · 익일 {r.get("next_ret","")}%">'
        f'{"○" if r.get("hit") else "✕"}</span>'
        for r in recs)

    return f"""
<div class="sb-hero">
  <div class="sb-gauge" style="background:conic-gradient({ring} {acc_val*3.6:.0f}deg, var(--line) 0);">
    <div class="sb-inner"><div class="sb-acc">{acc_txt}</div><div class="sb-acclbl">적중률</div></div>
  </div>
  <div class="sb-side">
    <div class="sb-stats">
      <div><span class="sb-num">{total}</span><span class="sb-lbl">채점</span></div>
      <div><span class="sb-num" style="color:{mood_main('positive', dark)};">{hits}</span><span class="sb-lbl">적중</span></div>
      <div><span class="sb-num" style="color:{mood_main('cautious', dark)};">{total-hits}</span><span class="sb-lbl">빗나감</span></div>
    </div>
    <div class="sb-strip">{chips}</div>
    <div class="sb-cap">최근 {len(recs)}건 · ○ 적중 / ✕ 빗나감 (최신이 오른쪽)</div>
  </div>
</div>
"""


_SB_CSS = """
<style>
.sb-hero{display:flex;gap:20px;align-items:center;flex-wrap:wrap;background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);border-radius:16px;padding:18px 20px;margin-bottom:6px;}
.sb-gauge{width:104px;height:104px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex:none;}
.sb-inner{width:78px;height:78px;border-radius:50%;background:var(--card,#fff);display:flex;flex-direction:column;align-items:center;justify-content:center;}
.sb-acc{font-family:'Fraunces','Noto Sans KR',serif;font-size:26px;font-weight:600;color:var(--ink,#34352f);line-height:1;}
.sb-acclbl{font-size:10px;color:var(--muted,#9a9b92);margin-top:3px;}
.sb-side{flex:1;min-width:200px;}
.sb-stats{display:flex;gap:22px;margin-bottom:11px;}
.sb-num{font-size:21px;font-weight:700;color:var(--ink,#34352f);}
.sb-lbl{font-size:11px;color:var(--muted,#9a9b92);margin-left:5px;}
.sb-strip{display:flex;flex-wrap:wrap;gap:3px;margin-bottom:6px;}
.ox{width:18px;height:18px;border-radius:5px;display:inline-flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;}
.ox-hit{background:#E1F5EE;color:#0F6E56;} .ox-miss{background:#FBEADF;color:#9C4318;}
.app.dark .ox-hit{background:#0C4435;color:#9FE1CB;} .app.dark .ox-miss{background:#4F2E18;color:#F0B58C;}
.sb-cap{font-size:10.5px;color:var(--muted,#9a9b92);}
</style>
"""


def render_verify():
    st.divider()

    # ── 예측 성적표 (히어로 시각화) ──
    st.markdown('<div class="mkt-group">리포트 예측 성적표</div>', unsafe_allow_html=True)
    st.markdown(_SB_CSS, unsafe_allow_html=True)
    try:
        from engine.predictions import load_scores, update_scores
        scores = load_scores()
        if scores and scores.get("total"):
            st.markdown(_scoreboard_hero(scores), unsafe_allow_html=True)
            st.caption(f"마지막 채점 {scores.get('updated','')} · positive→상승 / cautious→하락 예측, 익일 코스피 기준")
            if scores["total"] < 20:
                st.caption("⚠️ 표본 20건 미만 — 통계적 신뢰도가 낮으니 참고용으로만 보세요.")
        else:
            st.caption("아직 채점된 예측이 없어요. 리포트가 쌓이고 다음 거래일이 지나면 자동 채점됩니다.")
        if st.button("🔄 지금 채점 갱신", key="pred_rescore"):
            with st.spinner("채점 중..."):
                r = update_scores()
            if r.get("ok"):
                st.success(f"채점 완료 · {r['total']}건 · 적중률 {r.get('accuracy')}%")
                st.rerun()
            else:
                st.warning(f"채점 실패 · {r.get('reason')}")
    except Exception as e:
        st.caption(f"예측 채점 모듈을 불러오지 못했어요: {e}")

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
