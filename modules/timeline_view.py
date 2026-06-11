"""[뷰어] 시황 타임라인 — 보고서 헤드라인·섹션 제목·mood를 시간 흐름으로 표시.

- 데이터: reports/*.json (headline, sections[], mood)
- 코스피 실제 등락률 병기 (mood의 '답안지' 역할)
- 같은 날 보고서가 여러 개면 최신 것만 사용
- 데스크톱: 가로 화살표 타임라인(지그재그 카드) / 모바일: 세로 타임라인
"""

import glob
import html
import json
import os
import re

import streamlit as st

from modules.indices import fetch_history

_REPORT_DIR = "reports"
_MOOD_MAP = {"positive": ("긍정", "pos", "#2E7D5B"),
             "neutral": ("중립", "neu", "#A7BBA9"),
             "cautious": ("주의", "cau", "#C2410C")}
_SEC_TITLE_KEYS = ("title", "name", "heading", "제목")
_MAX_SECTIONS = 5
_TRUNC = 35

_TL_CSS = """
<style>
.tl-row { display:grid; gap:8px; align-items:end; }
.tl-row.tl-bottom { align-items:start; }
.tl-card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:9px 10px; }
.tl-card.tl-latest { border-color:#C2410C; border-width:1.5px; }
.tl-dt { font-size:10.5px; font-weight:700; color:var(--muted); margin-bottom:3px; }
.tl-pct { font-weight:700; margin-left:4px; }
.tl-pct.up { color:var(--up); } .tl-pct.down { color:var(--down); }
.tl-hl { font-size:11.5px; font-weight:700; line-height:1.45; color:var(--ink); word-break:keep-all; }
.tl-secs { list-style:none; margin:6px 0 0; padding:6px 0 0; border-top:1px solid var(--line); }
.tl-secs li { font-size:10.5px; line-height:1.5; color:var(--muted); padding-left:9px; position:relative; margin-bottom:2px; word-break:keep-all; }
.tl-secs li::before { content:""; position:absolute; left:0; top:6px; width:4px; height:4px; border-radius:50%; background:var(--sage); }
.tl-md { display:inline-block; font-size:10px; font-weight:700; padding:1px 7px; border-radius:6px; margin-top:7px; }
.tl-md.pos { background:#e1f5ee; color:#0f6e56; }
.tl-md.neu { background:var(--pill-bg); color:var(--pill-ink); }
.tl-md.cau { background:#FAEEDA; color:#854F0B; }
.app.dark .tl-md.pos { background:#085041; color:#9fe1cb; }
.app.dark .tl-md.cau { background:#633806; color:#FAC775; }
.tl-svg { width:100%; display:block; margin:4px 0; }
.tl-mobile { display:none; }
@media (max-width:640px){
  .tl-row, .tl-svg { display:none; }
  .tl-mobile { display:block; border-left:2px solid var(--line); padding-left:18px; }
  .tl-mobile .tl-card { position:relative; margin-bottom:12px; }
  .tl-mobile .tl-card::before { content:""; position:absolute; left:-25px; top:13px;
    width:11px; height:11px; border-radius:50%; border:2.5px solid var(--bg); background:var(--dot,#A7BBA9); }
}
</style>
"""


def _section_titles(report: dict) -> list:
    """sections[]에서 제목만 추출 (키 이름이 달라도 방어적으로)."""
    out = []
    for sec in report.get("sections", [])[:_MAX_SECTIONS]:
        title = None
        if isinstance(sec, dict):
            for k in _SEC_TITLE_KEYS:
                if sec.get(k):
                    title = str(sec[k])
                    break
        elif isinstance(sec, str):
            title = sec
        if title:
            t = title.strip()
            if len(t) > _TRUNC:
                t = t[:_TRUNC] + "…"
            out.append(t)
    return out


@st.cache_data(ttl=600)
def load_timeline_entries(limit: int = 7) -> list:
    """reports/*.json에서 타임라인 항목 로드. 같은 날짜는 최신만, 날짜 오름차순."""
    by_date = {}
    for path in glob.glob(os.path.join(_REPORT_DIR, "*.json")):
        fname = os.path.basename(path)
        m = re.search(r"(\d{4}-\d{2}-\d{2})", fname)
        if not m:
            continue
        date = m.group(1)
        # 파일명 숫자 전체를 정렬키로 → 같은 날짜 중 최신 선택
        sort_key = re.sub(r"\D", "", fname)
        if date in by_date and by_date[date][0] >= sort_key:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                rep = json.load(f)
        except Exception:
            continue
        by_date[date] = (sort_key, rep)

    entries = []
    for date in sorted(by_date.keys())[-limit:]:
        rep = by_date[date][1]
        mood_raw = str(rep.get("mood", "")).lower()
        label, cls, color = _MOOD_MAP.get(mood_raw, _MOOD_MAP["neutral"])
        entries.append({
            "date": date,
            "headline": str(rep.get("headline", "")).strip() or "(헤드라인 없음)",
            "sections": _section_titles(rep),
            "mood_label": label, "mood_cls": cls, "mood_color": color,
        })
    return entries


@st.cache_data(ttl=1800)
def _kospi_pct_by_date() -> dict:
    """날짜(YYYY-MM-DD) → 코스피 일간 등락률(%) 매핑."""
    out = {}
    try:
        close = fetch_history("^KS11", "3mo")
        if close is None or len(close) < 2:
            return out
        pct = close.pct_change() * 100
        for ts, v in pct.items():
            try:
                out[ts.strftime("%Y-%m-%d")] = float(v)
            except Exception:
                continue
    except Exception:
        pass
    return out


_WD = "월화수목금토일"


def _fmt_date(date: str) -> str:
    """'2026-06-11' → '06/11 (목)'."""
    try:
        from datetime import datetime
        d = datetime.strptime(date, "%Y-%m-%d")
        return f"{d.strftime('%m/%d')} ({_WD[d.weekday()]})"
    except Exception:
        return date


def _card_html(e: dict, pct, latest: bool, mobile: bool = False) -> str:
    pct_html = ""
    if pct is not None:
        cls = "up" if pct >= 0 else "down"
        arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "▬")
        pct_html = f'<span class="tl-pct {cls}">{arrow}{pct:+.2f}%</span>'
    secs = "".join(f"<li>{html.escape(s)}</li>" for s in e["sections"])
    secs_html = f'<ul class="tl-secs">{secs}</ul>' if secs else ""
    latest_cls = " tl-latest" if latest else ""
    latest_tag = " · 최신" if latest else ""
    dot = f' style="--dot:{e["mood_color"]}"' if mobile else ""
    return (f'<div class="tl-card{latest_cls}"{dot}>'
            f'<div class="tl-dt">{_fmt_date(e["date"])}{latest_tag}{pct_html}</div>'
            f'<div class="tl-hl">{html.escape(e["headline"])}</div>'
            f'{secs_html}'
            f'<span class="tl-md {e["mood_cls"]}">{e["mood_label"]}</span></div>')


def _svg_html(entries: list) -> str:
    """트랙 + 노드 사이 진행 화살표 + mood 노드. 노드는 균등 간격."""
    n = len(entries)
    w = 960
    parts = [f'<svg class="tl-svg" viewBox="0 0 {w} 48" preserveAspectRatio="none">',
             f'<line x1="10" y1="24" x2="{w-20}" y2="24" stroke="#D3D1C7" stroke-width="2"/>',
             f'<path d="M{w-20},24 l-12,-7 v14 z" fill="#D3D1C7"/>']
    xs = [(i + 0.5) / n * w for i in range(n)]
    for i, (x, e) in enumerate(zip(xs, entries)):
        r = 11 if i == n - 1 else 8
        parts.append(f'<circle cx="{x:.0f}" cy="24" r="{r}" fill="{e["mood_color"]}" '
                     f'stroke="var(--bg)" stroke-width="3"/>')
    parts.append("</svg>")
    return "".join(parts)


def render_timeline():
    st.markdown(_TL_CSS, unsafe_allow_html=True)
    st.markdown('<div class="mkt-group">시황 타임라인</div>', unsafe_allow_html=True)

    n_opt = st.selectbox("표시할 보고서 수", ["최근 7개", "최근 14개", "최근 30개"],
                         index=0, key="tl_n", label_visibility="collapsed")
    limit = int(re.search(r"\d+", n_opt).group())

    entries = load_timeline_entries(limit)
    if not entries:
        st.markdown('<div class="empty"><div class="ico">🗓️</div>'
                    '<div class="msg">아직 표시할 보고서가 없어요</div>'
                    '<div class="hint">시황 보고서가 쌓이면 흐름이 그려집니다</div></div>',
                    unsafe_allow_html=True)
        return
    if len(entries) == 1:
        st.caption("보고서가 1개뿐이라 흐름 표시는 2개부터 가능해요. 우선 최신 보고서만 표시합니다.")

    pct_map = _kospi_pct_by_date()
    n = len(entries)
    last_i = n - 1

    # 데스크톱: 지그재그 (짝수 인덱스=아래, 홀수 인덱스=위)
    top_cells, bottom_cells = [], []
    for i, e in enumerate(entries):
        card = _card_html(e, pct_map.get(e["date"]), i == last_i)
        if i % 2 == 1:
            top_cells.append(card)
            bottom_cells.append("<div></div>")
        else:
            top_cells.append("<div></div>")
            bottom_cells.append(card)
    grid = f"grid-template-columns:repeat({n},1fr);"
    desktop = (f'<div class="tl-row" style="{grid}">{"".join(top_cells)}</div>'
               f'{_svg_html(entries)}'
               f'<div class="tl-row tl-bottom" style="{grid}">{"".join(bottom_cells)}</div>')

    # 모바일: 세로 타임라인
    mobile_cards = "".join(_card_html(e, pct_map.get(e["date"]), i == last_i, mobile=True)
                           for i, e in enumerate(entries))
    mobile = f'<div class="tl-mobile">{mobile_cards}</div>'

    st.markdown(desktop + mobile, unsafe_allow_html=True)
    st.markdown('<div class="data-asof">노드 색 = 보고서 mood (긍정·중립·주의) · '
                '날짜 옆 등락률 = 코스피 당일 실제 결과 · 같은 날 보고서는 최신만 표시</div>',
                unsafe_allow_html=True)
