"""[뷰어] 시황 타임라인 — 보고서 헤드라인·섹션 제목·mood를 시간 흐름으로 표시.

- 데이터: reports/*.json (headline, sections[], mood, report_kind)
- 같은 날 보고서가 여러 개면 ★장마감 후(post)를 우선★ 사용 (그날의 '답안지' 역할).
  post가 없으면 장전(pre) 등 최신 보고서로 폴백.
- ★표시 범위: 항상 최근 5개 날짜(장후 우선). 5개 미만이면 있는 것만.
- 코스피·코스닥 당일 종가 + 등락률 병기
- 리포트 파일이 추가/삭제되면 캐시가 자동 무효화됨 (폴더 시그니처 기반)
- 데스크톱: 가로 화살표 타임라인(지그재그 카드) / 모바일: 세로 타임라인
- 제목은 전략·시황 탭과 동일한 큰 글자 볼드(.rpt2-title) + 표시 중 기준일자 병기.
"""

import glob
import html
import json
import os
import re

import streamlit as st

from modules.indices import fetch_history

_REPORT_DIR = "reports"
_TIMELINE_DAYS = 5          # ★항상 최근 5개 날짜 (장후 우선)
_MOOD_MAP = {"positive": ("긍정", "pos", "#2E7D5B"),
             "neutral": ("중립", "neu", "#A7BBA9"),
             "cautious": ("주의", "cau", "#C2410C")}
_SEC_TITLE_KEYS = ("title", "name", "heading", "제목")
_MAX_SECTIONS = 5
_TRUNC = 60

_TL_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Hanken+Grotesk:wght@400;500;600;700&family=Noto+Sans+KR:wght@400;500;700&display=swap');
/* 전략·시황 탭과 동일한 제목 스타일 */
.tl-bar { height:3px; width:34px; background:var(--sage,#A7BBA9); border-radius:3px; margin:0 0 10px; }
.tl-title { font-family:'Fraunces','Noto Sans KR',serif; font-size:30px; font-weight:600;
  line-height:1.3; color:var(--ink,#34352f); margin:2px 0 4px; display:flex; align-items:baseline;
  gap:12px; flex-wrap:wrap; }
.tl-title .dates { font-family:'Hanken Grotesk','Noto Sans KR',sans-serif; font-size:13px;
  font-weight:600; color:var(--muted,#9a9b92); letter-spacing:.01em; }
.tl-sub { font-size:12px; color:var(--muted,#9a9b92); margin:0 0 16px; }

.tl-row { display:grid; gap:8px; align-items:end; }
.tl-row.tl-bottom { align-items:start; }
.tl-card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:9px 10px;
  color:inherit; transition:transform .16s ease, box-shadow .16s ease, border-color .16s ease; }
.tl-card.tl-latest { border-color:#C2410C; border-width:1.5px; }
/* 마우스 올리면 살짝 떠오르는 입체 효과 (클릭 동작 없음) */
.tl-card:hover { transform:translateY(-3px); box-shadow:0 6px 18px rgba(0,0,0,.10); border-color:var(--sage-deep,#7E9A83); }
.tl-card, .tl-card * { text-decoration:none; }
.tl-dt { font-size:10.5px; font-weight:700; color:var(--muted); margin-bottom:3px; }
.tl-idx { font-size:10px; color:var(--muted); margin-bottom:4px; line-height:1.5; }
.tl-idx b { font-weight:700; color:var(--ink); }
.tl-pct { font-weight:700; }
.tl-pct.up { color:var(--up); } .tl-pct.down { color:var(--down); }
.tl-hl { font-size:11.5px; font-weight:700; line-height:1.45; color:var(--ink); word-break:keep-all; }
.tl-secs { list-style:none; margin:6px 0 0; padding:6px 0 0; border-top:1px solid var(--line); }
.tl-secs li { font-size:10.5px; line-height:1.5; color:var(--muted); padding-left:9px; position:relative; margin-bottom:2px; word-break:keep-all; }
.tl-secs li::before { content:""; position:absolute; left:0; top:6px; width:4px; height:4px; border-radius:50%; background:var(--sage); }
.tl-md { display:inline-block; font-size:10px; font-weight:700; padding:1px 7px; border-radius:6px; margin-top:7px; }
.tl-md.pos { background:#e1f5ee; color:#0f6e56; }
.tl-md.neu { background:var(--pill-bg); color:var(--pill-ink); }
.tl-md.cau { background:#FAEEDA; color:#854F0B; }
.tl-kind { display:inline-block; font-size:9.5px; font-weight:700; padding:1px 6px; border-radius:6px; margin-top:7px; margin-left:5px; background:var(--pill-bg); color:var(--pill-ink); }
.tl-svg { width:100%; display:block; margin:4px 0; }
.tl-mobile { display:none; }
@media (max-width:640px){
  .tl-row, .tl-svg { display:none; }
  .tl-title { font-size:24px; }
  .tl-mobile { display:block; border-left:2px solid var(--line); padding-left:18px; }
  .tl-mobile .tl-card { position:relative; margin-bottom:12px; }
  .tl-mobile .tl-card::before { content:""; position:absolute; left:-25px; top:13px;
    width:11px; height:11px; border-radius:50%; border:2.5px solid var(--bg); background:var(--dot,#A7BBA9); }
}
</style>
"""


def _reports_signature() -> str:
    """reports/ 폴더의 (파일명, 수정시각) 시그니처.
    리포트가 추가·삭제·수정되면 값이 바뀌어 st.cache_data 캐시가 자동 무효화된다."""
    parts = []
    for path in sorted(glob.glob(os.path.join(_REPORT_DIR, "*.json"))):
        try:
            parts.append(f"{os.path.basename(path)}:{os.path.getmtime(path):.0f}")
        except OSError:
            continue
    return "|".join(parts)


def _infer_kind(fname: str, rep: dict) -> str:
    """보고서 종류. report_kind 필드 우선, 없으면 파일명 HHMM으로 추정(오전=장전, 오후=장후)."""
    k = (rep or {}).get("report_kind")
    if k in ("pre", "post"):
        return k
    m = re.search(r"_(\d{2})(\d{2})", fname)
    if m:
        return "pre" if int(m.group(1)) < 12 else "post"
    return "post"


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
def load_timeline_entries(limit: int, sig: str) -> list:
    """reports/*.json에서 타임라인 항목 로드. 같은 날짜는 장마감 후(post) 우선, 날짜 오름차순.
    최근 limit개 날짜만 반환(limit보다 적으면 있는 만큼).
    sig: _reports_signature() — 캐시 키 전용(함수 안에서는 사용 안 함)."""
    # 날짜 -> (priority, sort_key, rep, fname) : post 우선, 같으면 최신(HHMM) 우선
    by_date = {}
    for path in glob.glob(os.path.join(_REPORT_DIR, "*.json")):
        fname = os.path.basename(path)
        m = re.search(r"(\d{4}-\d{2}-\d{2})", fname)
        if not m:
            continue
        d = m.group(1)
        sort_key = re.sub(r"\D", "", fname)
        try:
            with open(path, encoding="utf-8") as f:
                rep = json.load(f)
        except Exception:
            continue
        priority = 1 if _infer_kind(fname, rep) == "post" else 0
        cur = by_date.get(d)
        if cur is None or (priority, sort_key) > (cur[0], cur[1]):
            by_date[d] = (priority, sort_key, rep, fname)

    entries = []
    for d in sorted(by_date.keys())[-limit:]:
        _, _, rep, fname = by_date[d]
        mood_raw = str(rep.get("mood", "")).lower()
        label, cls, color = _MOOD_MAP.get(mood_raw, _MOOD_MAP["neutral"])
        kind = _infer_kind(fname, rep)
        entries.append({
            "date": d,
            "report": fname,
            "kind": kind,
            "kind_label": "장마감 후" if kind == "post" else "장전",
            "headline": str(rep.get("headline", "")).strip() or "(헤드라인 없음)",
            "sections": _section_titles(rep),
            "mood_label": label, "mood_cls": cls, "mood_color": color,
        })
    return entries


@st.cache_data(ttl=1800)
def _index_daily_map() -> dict:
    """날짜(YYYY-MM-DD) → {'ks_close','ks_pct','kq_close','kq_pct'}.
    코스피·코스닥 일별 종가와 등락률. 1차 yfinance, 빠진 날짜는 pykrx로 보충."""
    out = {}
    for prefix, ticker in (("ks", "^KS11"), ("kq", "^KQ11")):
        try:
            close = fetch_history(ticker, "3mo")
            if close is None or len(close) < 2:
                continue
            pct = close.pct_change() * 100
            for ts, c in close.items():
                key = ts.strftime("%Y-%m-%d")
                rec = out.setdefault(key, {})
                rec[f"{prefix}_close"] = float(c)
                p = pct.get(ts)
                if p == p:  # NaN 방어
                    rec[f"{prefix}_pct"] = float(p)
        except Exception:
            continue
    try:
        from datetime import date, timedelta
        from pykrx import stock as _krx
        end = date.today().strftime("%Y%m%d")
        start = (date.today() - timedelta(days=100)).strftime("%Y%m%d")
        for prefix, code in (("ks", "1001"), ("kq", "2001")):
            try:
                df = _krx.get_index_ohlcv(start, end, code)
                closes = df["종가"].dropna()
                pcts = closes.pct_change() * 100
                for ts, c in closes.items():
                    key = ts.strftime("%Y-%m-%d")
                    rec = out.setdefault(key, {})
                    if f"{prefix}_close" not in rec:
                        rec[f"{prefix}_close"] = float(c)
                        p = pcts.get(ts)
                        if p == p:
                            rec[f"{prefix}_pct"] = float(p)
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


def _fmt_date_short(date: str) -> str:
    """'2026-06-11' → '06.11' (제목 옆 기준일자 병기용)."""
    try:
        from datetime import datetime
        d = datetime.strptime(date, "%Y-%m-%d")
        return d.strftime("%m.%d")
    except Exception:
        return date


def _idx_line_html(rec: dict) -> str:
    """카드 날짜 아래 '코스피 2,750.1 ▲+1.2% · 코스닥 870.5 ▼-0.3%' 한 줄."""
    if not rec:
        return ""
    items = []
    for prefix, label in (("ks", "코스피"), ("kq", "코스닥")):
        close = rec.get(f"{prefix}_close")
        if close is None:
            continue
        pct = rec.get(f"{prefix}_pct")
        pct_html = ""
        if pct is not None:
            cls = "up" if pct >= 0 else "down"
            arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "▬")
            pct_html = f' <span class="tl-pct {cls}">{arrow}{pct:+.2f}%</span>'
        items.append(f'{label} <b>{close:,.2f}</b>{pct_html}')
    if not items:
        return ""
    return f'<div class="tl-idx">{" · ".join(items)}</div>'


def _card_html(e: dict, idx_rec, latest: bool, mobile: bool = False) -> str:
    secs = "".join(f"<li>{html.escape(s)}</li>" for s in e["sections"])
    secs_html = f'<ul class="tl-secs">{secs}</ul>' if secs else ""
    latest_cls = " tl-latest" if latest else ""
    latest_tag = " · 최신" if latest else ""
    dot = f' style="--dot:{e["mood_color"]}"' if mobile else ""
    kind_tag = f'<span class="tl-kind">{e.get("kind_label", "")}</span>' if e.get("kind_label") else ""
    inner = (f'<div class="tl-dt">{_fmt_date(e["date"])}{latest_tag}</div>'
             f'{_idx_line_html(idx_rec)}'
             f'<div class="tl-hl">{html.escape(e["headline"])}</div>'
             f'{secs_html}'
             f'<span class="tl-md {e["mood_cls"]}">{e["mood_label"]}</span>{kind_tag}')
    return f'<div class="tl-card{latest_cls}"{dot}>{inner}</div>'


def _svg_html(entries: list) -> str:
    """트랙 + mood 노드. 노드는 균등 간격."""
    n = len(entries)
    w = 960
    parts = [f'<svg class="tl-svg" viewBox="0 0 {w} 64" preserveAspectRatio="none">',
             f'<line x1="10" y1="40" x2="{w-20}" y2="40" stroke="#D3D1C7" stroke-width="2"/>',
             f'<path d="M{w-20},40 l-12,-7 v14 z" fill="#D3D1C7"/>']
    xs = [(i + 0.5) / n * w for i in range(n)]
    for i, (x, e) in enumerate(zip(xs, entries)):
        r = 11 if i == n - 1 else 8
        parts.append(f'<circle cx="{x:.0f}" cy="40" r="{r}" fill="{e["mood_color"]}" '
                     f'stroke="var(--bg)" stroke-width="3"/>')
    parts.append("</svg>")
    return "".join(parts)


def render_timeline():
    st.markdown(_TL_CSS, unsafe_allow_html=True)

    # 항상 최근 5개 날짜(장후 우선). 5개 미만이면 있는 것만.
    entries = load_timeline_entries(_TIMELINE_DAYS, _reports_signature())

    # 제목: 전략·시황 탭과 동일한 큰 글자 볼드 + 표시 중 기준일자 병기
    if entries:
        # entries는 날짜 오름차순 → 제목 병기는 최신이 앞으로 오도록 역순 표기
        dates_str = " · ".join(_fmt_date_short(e["date"]) for e in reversed(entries))
        dates_html = f'<span class="dates">{dates_str}</span>'
    else:
        dates_html = ""
    st.markdown('<div class="tl-bar"></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="tl-title">시황 타임라인 {dates_html}</div>',
                unsafe_allow_html=True)
    st.markdown('<div class="tl-sub">최근 5개 거래일의 보고서 흐름 (같은 날은 장마감 후 우선)</div>',
                unsafe_allow_html=True)

    if not entries:
        st.markdown('<div class="empty"><div class="ico">🗓️</div>'
                    '<div class="msg">아직 표시할 보고서가 없어요</div>'
                    '<div class="hint">시황 보고서가 쌓이면 흐름이 그려집니다</div></div>',
                    unsafe_allow_html=True)
        return
    if len(entries) == 1:
        st.caption("보고서가 1개뿐이라 흐름 표시는 2개부터 가능해요. 우선 최신 보고서만 표시합니다.")

    idx_map = _index_daily_map()
    n = len(entries)
    last_i = n - 1

    top_cells, bottom_cells = [], []
    for i, e in enumerate(entries):
        card = _card_html(e, idx_map.get(e["date"]), i == last_i)
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

    mobile_cards = "".join(_card_html(e, idx_map.get(e["date"]), i == last_i, mobile=True)
                           for i, e in enumerate(entries))
    mobile = f'<div class="tl-mobile">{mobile_cards}</div>'

    st.markdown(desktop + mobile, unsafe_allow_html=True)
    st.markdown('<div class="data-asof">노드 색 = 보고서 mood (긍정·중립·주의) · '
                '날짜 아래 = 코스피·코스닥 당일 마감 종가와 등락률 · 같은 날은 장마감 후 보고서 우선 표시</div>',
                unsafe_allow_html=True)
