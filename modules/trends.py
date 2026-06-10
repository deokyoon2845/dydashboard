"""추세 탭: 감성 추세(테마 색 차트) + 반복 등장 종목 + 주간 다이제스트."""

import re
from collections import defaultdict
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from modules.reports import list_reports, _report_date, _extract_stocks
from modules.stocks import stock_pills_html

DIGEST_DIR = Path("digests")


def _empty(ico, msg, hint=""):
    st.markdown(
        f'<div class="empty"><div class="ico">{ico}</div>'
        f'<div class="msg">{msg}</div>'
        f'<div class="hint">{hint}</div></div>',
        unsafe_allow_html=True,
    )


_MOOD_SCORE = {"positive": 1.0, "neutral": 0.0, "cautious": -1.0}


def _sentiment_score(text: str):
    # 신형 JSON 리포트: mood 필드
    try:
        import json as _json
        data = _json.loads(text)
        if isinstance(data, dict) and "mood" in data:
            return _MOOD_SCORE.get(data.get("mood"), 0.0)
    except Exception:
        pass
    # 구형 MD 리포트: '시장 분위기' 섹션 단어 기반
    m = re.search(r"##\s*시장\s*분위기[^\n]*\n+(.+?)(?=\n##|\Z)", text, re.S)
    seg = m.group(1) if m else text
    pos, neg, neu = ("긍정" in seg), ("부정" in seg), ("중립" in seg)
    if not (pos or neg or neu):
        return None
    score = (1 if pos else 0) - (1 if neg else 0)
    if neu and score != 0:
        score *= 0.5
    return float(score)


def _sentiment_series():
    rows = []
    for f in list_reports():
        s = _sentiment_score(f.read_text(encoding="utf-8"))
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


def _stock_stats():
    days, total = defaultdict(set), defaultdict(int)
    for f in list_reports():
        d = _report_date(f)
        for s in _extract_stocks(f.read_text(encoding="utf-8")):
            days[s].add(d)
            total[s] += 1
    rows = [{"stock": s, "days": len(days[s]), "total": total[s]} for s in total]
    rows.sort(key=lambda r: (r["days"], r["total"]), reverse=True)
    return rows


def _latest_digest():
    if not DIGEST_DIR.exists():
        return None
    files = sorted(DIGEST_DIR.glob("*.md"), reverse=True)
    return files[0].read_text(encoding="utf-8") if files else None


def render_trends():
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
        st.altair_chart(_sentiment_chart(series, dark), use_container_width=True)
        st.caption("긍정 +1 · 중립 0 · 부정 −1 (리포트의 '시장 분위기' 기반)")
    elif len(series) == 1:
        st.caption(f"현재 리포트 1개(점수 {series[0][1]:+.1f}). 며칠 쌓이면 추세선이 그려져요.")
    else:
        st.caption("'시장 분위기'를 인식할 수 있는 리포트가 아직 없어요.")

    # ── 2. 반복 등장 종목 ──
    st.markdown('<div class="mkt-group">자주 등장한 종목</div>', unsafe_allow_html=True)
    stats = _stock_stats()
    if stats:
        rows = []
        for r in stats[:10]:
            rows.append(
                '<div style="padding:8px 0;border-bottom:1px solid var(--line);">'
                f'{stock_pills_html([r["stock"]])} '
                f'<span style="font-size:12px;color:var(--muted);">'
                f'{r["days"]}일 등장 · 총 {r["total"]}회</span></div>'
            )
        st.markdown("".join(rows), unsafe_allow_html=True)
    else:
        st.caption("리포트에서 종목을 아직 찾지 못했어요.")

    # ── 3. 주간 다이제스트 ──
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
