"""추세 탭: 감성 추세(테마 색 차트) + 주간 다이제스트.

2026-06 저장소 이전: 보고서를 reports/ 폴더 파일이 아니라 DB에서 읽는다.
  list_reports()는 가상 경로를 주므로, 파일을 직접 read_text 하지 않고
  reports._load(path)로 DB에서 보고서 dict를 가져온다.
"""

import re
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from modules.reports import list_reports, _report_date, _load

DIGEST_DIR = Path("digests")

# 감성 추세 차트 등장 연출: 차트 영역을 왼쪽→오른쪽으로 공개(clip reveal).
# 데이터는 그대로 그려지고 마스크만 걷히므로 값 왜곡이 없다.
_TREND_CSS = """
<style>
@keyframes tr-reveal{from{clip-path:inset(0 100% 0 0);}to{clip-path:inset(0 0 0 0);}}
/* 추세 차트가 들어가는 첫 vega 차트에만 적용 (감성 추세) */
.tr-anim [data-testid="stVegaLiteChart"]{
  animation:tr-reveal 1.1s cubic-bezier(.22,.61,.36,1) both;}
@media(prefers-reduced-motion:reduce){
  .tr-anim [data-testid="stVegaLiteChart"]{animation:none !important;}}
</style>
"""


def _empty(ico, msg, hint=""):
    st.markdown(
        f'<div class="empty"><div class="ico">{ico}</div>'
        f'<div class="msg">{msg}</div>'
        f'<div class="hint">{hint}</div></div>',
        unsafe_allow_html=True,
    )


_MOOD_SCORE = {"positive": 1.0, "neutral": 0.0, "cautious": -1.0}


def _sentiment_score(data: dict):
    """보고서 dict의 mood → 점수. 인식할 수 없으면 None."""
    if isinstance(data, dict) and data.get("mood") in _MOOD_SCORE:
        return _MOOD_SCORE[data["mood"]]
    return None


def _sentiment_series():
    rows = []
    for f in list_reports():
        try:
            data = _load(f)            # 파일이 아니라 DB에서 보고서 dict 로드
        except Exception:
            continue
        s = _sentiment_score(data)
        if s is not None:
            rows.append((_report_date(f), s))
    rows.sort()
    return rows


def _sentiment_chart(series, dark):
    df = pd.DataFrame(series, columns=["날짜", "점수"]).groupby("날짜", as_index=False).mean()
    sage = "#A8D8C0" if dark else "#7E9A83"
    axis_c = "#9A9CAB" if dark else "#9a9b92"
    grid_c = "#3A3D49" if dark else "#ECEDE7"

    area = alt.Chart(df).mark_area(
        color=sage, opacity=0.22, line={"color": sage, "strokeWidth": 2},
    ).encode(
        x=alt.X("날짜:T", axis=alt.Axis(title=None, format="%m/%d", labelColor=axis_c, grid=False)),
        y=alt.Y("점수:Q", scale=alt.Scale(domain=[-1, 1]),
                axis=alt.Axis(title=None, labelColor=axis_c, gridColor=grid_c)),
    )
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(
        color=axis_c, strokeDash=[3, 3]).encode(y="y:Q")
    return (area + zero).properties(height=220, background="transparent").configure_view(strokeWidth=0)


def _latest_digest():
    if not DIGEST_DIR.exists():
        return None
    files = sorted(DIGEST_DIR.glob("*.md"), reverse=True)
    return files[0].read_text(encoding="utf-8") if files else None


def render_trends():
    st.markdown(_TREND_CSS, unsafe_allow_html=True)
    st.markdown('<div class="rpt-bar"></div>', unsafe_allow_html=True)
    st.title("추세")

    if not list_reports():
        _empty("📊", "리포트가 쌓이면 추세를 보여드려요", "전략·시황 보고서를 먼저 만들어보세요")
        return

    dark = st.session_state.get("dark", False)

    # ── 1. 감성 추세 ──
    st.markdown('<div class="mkt-group">시장 분위기 추세</div>', unsafe_allow_html=True)
    series = _sentiment_series()
    if len(series) >= 2:
        # 차트 등장 연출(clip reveal)을 위해 래퍼 컨테이너로 감싼다.
        with st.container():
            st.markdown('<div class="tr-anim">', unsafe_allow_html=True)
            st.altair_chart(_sentiment_chart(series, dark), use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        st.caption("긍정 +1 · 중립 0 · 부정 −1 (리포트의 '시장 분위기' 기반)")
    elif len(series) == 1:
        st.caption(f"현재 리포트 1개(점수 {series[0][1]:+.1f}). 며칠 쌓이면 추세선이 그려져요.")
    else:
        st.caption("'시장 분위기'를 인식할 수 있는 리포트가 아직 없어요.")

    # ── 2. 주간 다이제스트 ──
    st.divider()
    st.markdown('<div class="mkt-group">주간 다이제스트</div>', unsafe_allow_html=True)
    if st.button("📅 주간 다이제스트 생성 (최근 7일)"):
        with st.spinner("최근 리포트를 종합하는 중..."):
            try:
                from engine.digest import build_weekly_digest
                res = build_weekly_digest(7)
            except Exception as e:
                res = {"ok": False, "reason": str(e)}
        if res.get("ok"):
            st.success(f"{res['reports']}건 종합 완료")
            st.rerun()
        else:
            st.warning(f"실패 · {res.get('reason')}")

    latest = _latest_digest()
    if latest:
        st.markdown(latest)
    else:
        st.caption("아직 다이제스트가 없어요. 위 버튼으로 생성하세요.")
