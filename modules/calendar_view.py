"""[뷰어] 다가오는 주요 일정 — FOMC·금통위·CPI·실적 D-day 표시."""

import streamlit as st

from engine.calendar_events import upcoming_events, fetch_next_earnings

_CAT_CLASS = {"미국": "cal-us", "한국": "cal-kr", "실적": "cal-earn"}


@st.cache_data(ttl=3600)
def _load_all(days: int = 30):
    """고정 일정 + 실적일 합쳐서 반환 (1시간 캐시)."""
    events = upcoming_events(days)
    try:
        events += [e for e in fetch_next_earnings() if e["dday"] <= days]
    except Exception:
        pass
    events.sort(key=lambda e: (e["dday"], e.get("category", "")))
    return events


def render_calendar(days: int = 30):
    events = _load_all(days)
    if not events:
        return

    st.markdown('<div class="mkt-group">📅 다가오는 주요 일정</div>', unsafe_allow_html=True)

    rows = []
    for ev in events:
        dday = ev["dday"]
        if dday == 0:
            dd_html = '<span class="cal-dday cal-today">오늘</span>'
        elif dday <= 3:
            dd_html = f'<span class="cal-dday cal-soon">D-{dday}</span>'
        else:
            dd_html = f'<span class="cal-dday">D-{dday}</span>'
        cat = ev.get("category", "")
        cat_cls = _CAT_CLASS.get(cat, "")
        note = ev.get("note", "")
        note_html = f'<span class="cal-note">{note}</span>' if note else ""
        try:
            mmdd = ev["date"][5:].replace("-", "/")
        except Exception:
            mmdd = ev.get("date", "")
        rows.append(
            f'<div class="cal-row">{dd_html}'
            f'<span class="cal-date">{mmdd}</span>'
            f'<span class="cal-name">{ev["name"]}</span>'
            f'<span class="cal-cat {cat_cls}">{cat}</span>'
            f'{note_html}</div>'
        )

    st.markdown(f'<div class="cal-wrap">{"".join(rows)}</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="data-asof">FOMC·금통위·CPI는 공식 발표 일정 (연 1회 수동 갱신) · '
        '실적일은 yfinance 추정으로 변동 가능</div>',
        unsafe_allow_html=True)
