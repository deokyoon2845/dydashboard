"""[뷰어] 다가오는 주요 일정 — 월간 달력 그리드.

- 데스크톱: 7열 월간 캘린더 (이벤트 칩을 날짜 칸에 표시, 이번 달~+2개월 탐색)
- 모바일(640px 이하): 기존 D-day 리스트로 자동 폴백
- 데이터: engine.calendar_events (고정 일정 + yfinance 실적일)
"""

import calendar as _pycal
import html as _html
from datetime import date, datetime, timedelta

import streamlit as st

from engine.calendar_events import upcoming_events, fetch_next_earnings

_CAT_CHIP = {"미국": "calm-us", "한국": "calm-kr", "실적": "calm-earn"}
_CAT_CLASS = {"미국": "cal-us", "한국": "cal-kr", "실적": "cal-earn"}  # 모바일 리스트용
_WD_HEAD = ["일", "월", "화", "수", "목", "금", "토"]
_MAX_MONTH_AHEAD = 2  # 이번 달 + 2개월까지 탐색

_CAL_CSS = """
<style>
.calm-wrap{background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);border-radius:14px;padding:12px 14px 14px;}
.calm-title{font-family:'Fraunces','Noto Sans KR',Georgia,serif;font-size:15px;font-weight:600;
  color:var(--ink,#34352f);text-align:center;line-height:2.1;}
.calm-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;}
.calm-wd{font-size:10.5px;font-weight:700;color:var(--muted,#9a9b92);text-align:center;padding:3px 0 5px;}
.calm-wd.sun{color:var(--up,#B65F5A);} .calm-wd.sat{color:var(--down,#5A7CA0);}
.calm-cell{min-height:60px;border:1px solid var(--line,#ECEDE7);border-radius:8px;padding:4px 5px;
  background:var(--card,#fff);overflow:hidden;}
.calm-cell.calm-empty{border:none;background:transparent;}
.calm-cell.calm-past{opacity:.4;}
.calm-cell.calm-today{border-color:var(--sage-deep,#7E9A83);border-width:2px;padding:3px 4px;}
.calm-day{font-size:11px;font-weight:700;color:var(--muted,#9a9b92);line-height:1;}
.calm-day.sun{color:var(--up,#B65F5A);} .calm-day.sat{color:var(--down,#5A7CA0);}
.calm-today .calm-day{color:var(--sage-deep,#7E9A83);}
.calm-chip{display:block;font-size:9.5px;font-weight:700;line-height:1.35;margin-top:3px;padding:2px 5px;
  border-radius:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:default;}
.calm-us{background:var(--tint-down,#F1F5F9);color:#2C5F7C;}
.calm-kr{background:var(--tint-up,#FBF2F2);color:#B65F5A;}
.calm-earn{background:var(--summary-bg,#F6F7F2);color:var(--sage-deep,#7E9A83);}
.app.dark .calm-us{color:#9CC4DC;} .app.dark .calm-kr{color:#F0A3AB;}
.calm-next{font-size:12px;color:var(--muted,#9a9b92);margin:4px 2px 8px;}
.calm-next b{color:var(--ink,#34352f);}
.calm-mobile{display:none;}
@media(max-width:640px){
  .calm-desktop{display:none;}
  .calm-mobile{display:block;}
}
</style>
"""


@st.cache_data(ttl=3600)
def _load_all(days: int = 90):
    """고정 일정 + 실적일 합쳐서 반환 (1시간 캐시)."""
    events = upcoming_events(days)
    try:
        events += [e for e in fetch_next_earnings() if e["dday"] <= days]
    except Exception:
        pass
    events.sort(key=lambda e: (e["dday"], e.get("category", "")))
    return events


def _events_by_date(events) -> dict:
    out = {}
    for ev in events:
        out.setdefault(ev.get("date", ""), []).append(ev)
    return out


def _add_months(d: date, n: int) -> tuple:
    y, m = d.year, d.month + n
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return y, m


def _chip_html(ev) -> str:
    cls = _CAT_CHIP.get(ev.get("category", ""), "calm-earn")
    name = _html.escape(str(ev.get("name", "")))
    note = _html.escape(str(ev.get("note", "")))
    tip = f"{name}" + (f" — {note}" if note else "")
    return f'<span class="calm-chip {cls}" title="{tip}">{name}</span>'


def _month_grid_html(year: int, month: int, ev_by_date: dict, today: date) -> str:
    cal = _pycal.Calendar(firstweekday=6)  # 일요일 시작
    weeks = cal.monthdayscalendar(year, month)

    head = "".join(
        f'<div class="calm-wd{" sun" if i == 0 else (" sat" if i == 6 else "")}">{w}</div>'
        for i, w in enumerate(_WD_HEAD))

    cells = []
    for week in weeks:
        for i, day in enumerate(week):
            if day == 0:
                cells.append('<div class="calm-cell calm-empty"></div>')
                continue
            d = date(year, month, day)
            classes = ["calm-cell"]
            if d == today:
                classes.append("calm-today")
            elif d < today:
                classes.append("calm-past")
            day_cls = "calm-day" + (" sun" if i == 0 else (" sat" if i == 6 else ""))
            chips = "".join(_chip_html(ev) for ev in ev_by_date.get(d.strftime("%Y-%m-%d"), []))
            cells.append(f'<div class="{" ".join(classes)}">'
                         f'<div class="{day_cls}">{day}</div>{chips}</div>')

    return (f'<div class="calm-wrap">'
            f'<div class="calm-title">{year}년 {month}월</div>'
            f'<div class="calm-grid">{head}{"".join(cells)}</div>'
            f'</div>')


def _mobile_list_html(events) -> str:
    """모바일 폴백: 기존 D-day 리스트 (app.py의 cal-* CSS 재사용)."""
    rows = []
    for ev in events:
        if ev["dday"] > 30:
            continue
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
        note_html = f'<span class="cal-note">{_html.escape(note)}</span>' if note else ""
        try:
            mmdd = ev["date"][5:].replace("-", "/")
        except Exception:
            mmdd = ev.get("date", "")
        rows.append(
            f'<div class="cal-row">{dd_html}'
            f'<span class="cal-date">{mmdd}</span>'
            f'<span class="cal-name">{_html.escape(ev["name"])}</span>'
            f'<span class="cal-cat {cat_cls}">{cat}</span>'
            f'{note_html}</div>'
        )
    return f'<div class="cal-wrap">{"".join(rows)}</div>' if rows else ""


def render_calendar(days: int = 90):
    events = _load_all(days)
    if not events:
        return

    st.markdown(_CAL_CSS, unsafe_allow_html=True)
    st.markdown('<div class="mkt-group">📅 다가오는 주요 일정</div>', unsafe_allow_html=True)

    # 가장 임박한 일정 한 줄 (달력에서 D-day 감각이 약해지는 것 보완)
    nxt = events[0]
    dd = "오늘" if nxt["dday"] == 0 else f"D-{nxt['dday']}"
    st.markdown(
        f'<div class="calm-next">다음 일정: <b>{dd} {_html.escape(nxt["name"])}</b>'
        f' ({nxt["date"][5:].replace("-", "/")})</div>', unsafe_allow_html=True)

    # 월 탐색 (이번 달 ~ +2개월)
    if "cal_month_off" not in st.session_state:
        st.session_state["cal_month_off"] = 0
    off = st.session_state["cal_month_off"]

    today = date.today()
    y, m = _add_months(today.replace(day=1), off)

    c1, c2, c3 = st.columns([1, 6, 1])
    with c1:
        if st.button("◀", key="cal_prev", disabled=(off <= 0), use_container_width=True):
            st.session_state["cal_month_off"] = off - 1
            st.rerun()
    with c3:
        if st.button("▶", key="cal_next", disabled=(off >= _MAX_MONTH_AHEAD),
                     use_container_width=True):
            st.session_state["cal_month_off"] = off + 1
            st.rerun()

    ev_by_date = _events_by_date(events)
    grid = _month_grid_html(y, m, ev_by_date, today)
    mobile = _mobile_list_html(events)

    st.markdown(
        f'<div class="calm-desktop">{grid}</div>'
        f'<div class="calm-mobile">{mobile}</div>',
        unsafe_allow_html=True)
    st.markdown(
        '<div class="data-asof">FOMC·금통위·CPI는 공식 발표 일정 (연 1회 수동 갱신) · '
        '실적일은 yfinance 추정으로 변동 가능 · 칩에 마우스를 올리면 상세 표시</div>',
        unsafe_allow_html=True)
