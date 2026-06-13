"""[뷰어] 다가오는 주요 일정 — 월간 달력 그리드.

- 데스크톱: 7열 월간 캘린더 (이벤트 칩을 날짜 칸에 표시, 이전 달~+2개월 탐색)
- 모바일(640px 이하): 기존 D-day 리스트로 자동 폴백
- 데이터: engine.calendar_events (고정 일정 + yfinance 실적)
- 지난 일정도 달력에 표시(흐리게) · 오늘은 빨간 동그라미 + 'Today' 뱃지
"""

import calendar as _pycal
import html as _html
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import streamlit as st

from engine.calendar_events import upcoming_events, fetch_next_earnings

_CAL_PATH = Path("data/calendar.json")
_CAT_CHIP = {"미국": "calm-us", "한국": "calm-kr", "실적": "calm-earn", "기타": "calm-etc"}
_CAT_CLASS = {"미국": "cal-us", "한국": "cal-kr", "실적": "cal-earn"}  # 모바일 리스트용
_WD_HEAD = ["일", "월", "화", "수", "목", "금", "토"]
_MAX_MONTH_AHEAD = 2   # 이번 달 + 2개월까지 탐색
_MAX_MONTH_BACK = 2    # 이번 달 - 2개월까지 탐색 (지난 일정 확인용)
_PAST_DAYS = 120       # 지난 일정 로드 범위 (달력에서 과거 칸 채우기용)

_CAL_CSS = """
<style>
/* ── 달력 공통 ─────────────────────────────── */
.calm-outer{background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);border-radius:14px;padding:12px 14px 14px;}
.calm-navtitle{font-family:'Fraunces','Noto Sans KR',Georgia,serif;font-size:16px;font-weight:600;
  color:var(--ink,#34352f);text-align:center;padding-top:6px;}
.calm-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:3px;}
.calm-wd{font-size:10px;font-weight:700;color:var(--muted,#9a9b92);text-align:center;padding:2px 0 4px;}
.calm-wd.sun{color:var(--up,#B65F5A);} .calm-wd.sat{color:var(--down,#5A7CA0);}
.calm-cell{position:relative;min-height:52px;border:1px solid var(--line,#ECEDE7);border-radius:7px;padding:3px 4px;
  background:var(--card,#fff);overflow:hidden;}
.calm-cell.calm-empty{border:none;background:transparent;}
.calm-cell.calm-past{opacity:.45;}
/* 오늘: 빨간 동그라미 테두리 + Today 뱃지 */
.calm-cell.calm-today{border:2px solid var(--up,#B65F5A);padding:2px 3px;box-shadow:0 0 0 2px var(--tint-up,#FBF2F2);}
.calm-day{font-size:10px;font-weight:700;color:var(--muted,#9a9b92);line-height:1.2;
  display:flex;align-items:center;gap:3px;}
.calm-day.sun{color:var(--up,#B65F5A);} .calm-day.sat{color:var(--down,#5A7CA0);}
.calm-today .calm-daynum{display:inline-flex;align-items:center;justify-content:center;
  width:16px;height:16px;border-radius:50%;background:var(--up,#B65F5A);color:#fff;font-weight:700;}
.calm-todaylab{font-size:8px;font-weight:800;letter-spacing:.02em;color:var(--up,#B65F5A);
  text-transform:uppercase;}
.calm-chip{display:block;font-size:9px;font-weight:700;line-height:1.3;margin-top:2px;padding:1px 4px;
  border-radius:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:default;}
/* ── 모바일 달력 칩 크기 조정 ── */
@media(max-width:480px){
  .calm-cell{min-height:40px;padding:2px 3px;}
  .calm-chip{font-size:8px;padding:1px 3px;}
  .calm-day{font-size:9px;}
  .calm-todaylab{display:none;}
}
.calm-us{background:var(--tint-down,#F1F5F9);color:#2C5F7C;}
.calm-kr{background:var(--tint-up,#FBF2F2);color:#B65F5A;}
.calm-earn{background:var(--summary-bg,#F6F7F2);color:var(--sage-deep,#7E9A83);}
.calm-etc{background:var(--pill-bg,#F1F2EC);color:var(--pill-ink,#5d6258);}
.calm-next{font-size:12px;color:var(--muted,#9a9b92);margin:4px 2px 8px;}
.calm-next b{color:var(--ink,#34352f);}
</style>
"""


@st.cache_data(ttl=3600)
def _load_all(days: int = 90, past_days: int = _PAST_DAYS):
    """고정 일정(과거 포함) + 실적일 합쳐서 반환 (1시간 캐시).
    past_days만큼 지난 일정도 포함 → 달력에서 지난 칸도 채워짐."""
    events = upcoming_events(days, past_days=past_days)
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
    """달력 본체(요일 헤더 + 날짜 칸)만 렌더. 월 이동 ◀▶ 와 제목은 상단 네이티브 행에서 처리."""
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
            is_today = (d == today)
            if is_today:
                classes.append("calm-today")
            elif d < today:
                classes.append("calm-past")
            day_cls = "calm-day" + (" sun" if i == 0 else (" sat" if i == 6 else ""))
            # 오늘이면 숫자에 빨간 동그라미 + Today 라벨
            if is_today:
                day_inner = (f'<span class="calm-daynum">{day}</span>'
                             f'<span class="calm-todaylab">Today</span>')
            else:
                day_inner = f'{day}'
            chips = "".join(_chip_html(ev) for ev in ev_by_date.get(d.strftime("%Y-%m-%d"), []))
            cells.append(f'<div class="{" ".join(classes)}">'
                         f'<div class="{day_cls}">{day_inner}</div>{chips}</div>')

    return (f'<div class="calm-outer">'
            f'<div class="calm-grid">{head}{"".join(cells)}</div>'
            f'</div>')


def _mobile_list_html(events) -> str:
    """모바일 폴백: D-day 리스트 (app.py의 cal-* CSS 재사용). 다가오는 일정만."""
    rows = []
    for ev in events:
        if ev["dday"] < 0 or ev["dday"] > 30:
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

    # 가장 임박한 '다가오는' 일정 한 줄 (과거 제외)
    upcoming = [e for e in events if e["dday"] >= 0]
    if upcoming:
        nxt = upcoming[0]
        dd = "오늘" if nxt["dday"] == 0 else f"D-{nxt['dday']}"
        st.markdown(
            f'<div class="calm-next">다음 일정: <b>{dd} {_html.escape(nxt["name"])}</b>'
            f' ({nxt["date"][5:].replace("-", "/")})</div>', unsafe_allow_html=True)

    # 월 상태
    if "cal_month_off" not in st.session_state:
        st.session_state["cal_month_off"] = 0
    off = st.session_state["cal_month_off"]
    today = date.today()
    y, m = _add_months(today.replace(day=1), off)

    # ── 상단 월 이동: ◀  YYYY년 M월  ▶ (네이티브 버튼 한 세트) ──
    nav_prev, nav_title, nav_next = st.columns([1, 6, 1])
    with nav_prev:
        if st.button("◀", key="cal_prev", disabled=(off <= -_MAX_MONTH_BACK),
                     use_container_width=True):
            st.session_state["cal_month_off"] = off - 1
            st.rerun()
    with nav_title:
        st.markdown(f'<div class="calm-navtitle">{y}년 {m}월</div>', unsafe_allow_html=True)
    with nav_next:
        if st.button("▶", key="cal_next", disabled=(off >= _MAX_MONTH_AHEAD),
                     use_container_width=True):
            st.session_state["cal_month_off"] = off + 1
            st.rerun()

    # 달력 그리드 HTML (요일 헤더 + 날짜 칸)
    ev_by_date = _events_by_date(events)
    grid = _month_grid_html(y, m, ev_by_date, today)
    st.markdown(grid, unsafe_allow_html=True)

    st.markdown(
        '<div class="data-asof">FOMC·금통위·CPI·고용·PPI·GDP·소매판매는 공식 발표 일정 (연 1회 수동 갱신) · '
        '실적일은 yfinance 추정으로 변동 가능 · 지난 일정도 흐리게 표시</div>',
        unsafe_allow_html=True)

    _render_event_editor()


# ── 내 일정 추가·관리 ────────────────────────────────────────

def _load_cal_raw() -> dict:
    try:
        return json.loads(_CAL_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"events": [], "earnings_tickers": {}}


def _save_cal_raw(data: dict):
    _CAL_PATH.parent.mkdir(exist_ok=True)
    _CAL_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _render_event_editor():
    """사용자 일정 추가/삭제. data/calendar.json의 events에 custom=True로 저장."""
    with st.expander("➕ 내 일정 추가·관리"):
        st.caption("⚠️ 여기서 추가한 일정은 서버 재시작(Reboot·재배포) 시 사라질 수 있어요. "
                   "영구 보관이 필요한 일정은 깃허브 저장소의 data/calendar.json에 직접 추가하세요.")

        c1, c2 = st.columns(2)
        with c1:
            d = st.date_input("날짜", min_value=date.today(), key="calx_date")
        with c2:
            cat = st.selectbox("카테고리", ["한국", "미국", "실적", "기타"], key="calx_cat")
        name = st.text_input("일정 이름", placeholder="예: 삼성전자 실적 발표, 선물옵션 만기",
                             key="calx_name")
        note = st.text_input("메모 (선택)", placeholder="예: 장 마감 후 발표", key="calx_note")

        if st.button("일정 추가", key="calx_add"):
            if not name.strip():
                st.warning("일정 이름을 입력해주세요.")
            else:
                raw = _load_cal_raw()
                raw.setdefault("events", []).append({
                    "date": d.strftime("%Y-%m-%d"),
                    "name": name.strip(),
                    "category": cat,
                    "note": note.strip(),
                    "custom": True,
                })
                _save_cal_raw(raw)
                _load_all.clear()          # 일정 캐시 무효화 → 달력 즉시 반영
                st.success("일정을 추가했어요.")
                st.rerun()

        customs = [(i, ev) for i, ev in enumerate(_load_cal_raw().get("events", []))
                   if ev.get("custom")]
        if customs:
            st.markdown("**내가 추가한 일정**")
            for i, ev in customs:
                cc1, cc2 = st.columns([5, 1])
                cc1.markdown(f"- {ev.get('date', '')} · {ev.get('name', '')} "
                             f"({ev.get('category', '')})"
                             + (f" — {ev['note']}" if ev.get("note") else ""))
                if cc2.button("삭제", key=f"calx_del_{i}"):
                    raw = _load_cal_raw()
                    evs = raw.get("events", [])
                    if 0 <= i < len(evs) and evs[i].get("custom"):
                        evs.pop(i)
                        _save_cal_raw(raw)
                        _load_all.clear()
                        st.rerun()
