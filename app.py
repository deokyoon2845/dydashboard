"""시장 현황 대시보드 - Streamlit 메인 앱 (라이트 단일 테마, 통일 헤더)."""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

from modules.indices import (
    INDEX_GROUPS, fetch_index, sparkline_points,
    fetch_supply_demand_summary, fetch_history, fetch_intraday,
    is_kr_market_open,
)
from modules.calendar_view import render_calendar
from modules.timeline_view import render_timeline
from modules.indicators import render_indicators
from modules.reports import render_reports, render_reports_manage
from modules.keywords_view import render_keywords
from modules.watchlist_brief import render_watchlist_tab
from modules.usage import total_cost_usd
from modules.ticker_tape import render_ticker_tape

load_dotenv()
st.set_page_config(page_title="DY Monitoring", page_icon="📈", layout="wide")

# ── 타임라인 카드 클릭(?rpt=파일명) → 해당 보고서 선택 ──
try:
    _rpt_param = st.query_params.get("rpt")
except Exception:
    _rpt_param = None
if _rpt_param:
    _slug = _rpt_param.rsplit("/", 1)[-1].replace(".json", "").replace(".md", "")
    st.session_state["rpt_picked_path"] = f"{_slug}.json"
    st.session_state["rpt_jump_notice"] = _rpt_param
    try:
        del st.query_params["rpt"]
    except Exception:
        pass

# ── 색 변수 (라이트 단일 테마) ──
LIGHT_VARS = """
:root{
  --bg:#FCFCFA; --card:#ffffff; --ink:#34352f; --muted:#9a9b92; --line:#ECEDE7;
  --sage:#A7BBA9; --sage-deep:#7E9A83; --up:#B65F5A; --down:#5A7CA0;
  --summary-bg:#F6F7F2; --pill-bg:#F1F2EC; --pill-ink:#5d6258;
  --tint-up:#FBF2F2; --tint-down:#F1F5F9; --pill-hover:#E6EBE2;
}
"""

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Hanken+Grotesk:wght@400;500;600&family=Noto+Sans+KR:wght@400;500;700&display=swap');
__VARS__
html, body, [data-testid="stAppViewContainer"] { font-family: 'Hanken Grotesk','Noto Sans KR',sans-serif; }
.block-container { max-width: 1400px; padding-top: 3.5rem; }
[data-testid="stMainBlockContainer"] { padding-top: 3.5rem !important; }
.stMainBlockContainer { padding-top: 3.5rem !important; }
h1,h2,h3 { font-family: 'Fraunces','Noto Sans KR',serif !important; letter-spacing:-.01em; color:var(--ink); }
h1 { font-size:1.875rem !important; font-weight:600 !important; line-height:1.3 !important; margin:0 0 .4rem !important; }
.stTabs [data-baseweb="tab-list"] { gap:4px; flex-wrap:wrap; }
.stTabs [data-baseweb="tab"] { white-space:nowrap; padding:8px 14px; height:auto; min-width:max-content; }
.stTabs [data-baseweb="tab"] p { font-size:15px; margin:0; white-space:nowrap; }
.stButton > button { border-radius:9px; padding:6px 16px; font-weight:600; }
.stButton { margin-bottom:4px; }
[data-testid="stExpander"] { border-radius:10px; margin-bottom:8px; }
.app-name { font-family:'Fraunces','Noto Sans KR',serif; font-size:18px; font-weight:600; color:var(--ink); }
.app-upd { font-size:11.5px; color:var(--muted); }
.accent-bar { height:3px; width:30px; background:var(--sage); border-radius:3px; margin:0 0 12px; }
.mkt-group { font-size:12px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); margin:16px 0 10px; }
.grp-asof { font-weight:600; font-size:10.5px; letter-spacing:0; text-transform:none; color:var(--muted); opacity:.8; margin-left:8px; }
.grp-divider { border:none; border-top:1px solid var(--line); margin:22px 0 0; }
.mkt-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; }
@media (max-width:980px){ .mkt-grid{ grid-template-columns:repeat(3,1fr);} }
@media (max-width:640px){ .mkt-grid{ grid-template-columns:repeat(2,1fr);} }
.mkt-card { background:var(--card); border:1px solid var(--line); border-radius:16px; padding:14px 14px 12px; }
.mkt-card.mkt-up { background:var(--tint-up); }
.mkt-card.mkt-down { background:var(--tint-down); }
.mkt-name { font-size:12.5px; font-weight:600; color:var(--muted); }
.mkt-val { font-size:21px; font-weight:700; color:var(--ink); margin-top:4px; letter-spacing:-.02em; }
.mkt-chg { font-size:12.5px; font-weight:700; margin-top:2px; }
.mkt-chg.up { color:var(--up); }
.mkt-chg.down { color:var(--down); }
.mkt-spark { width:100%; height:28px; display:block; margin-top:8px; }
.mkt-na { color:var(--muted); font-size:13px; margin-top:6px; }
.gauge { position:relative; height:8px; border-radius:5px; background:linear-gradient(90deg,#5A7CA0 0%,#A7BBA9 50%,#B65F5A 100%); margin:9px 0 5px; }
.gauge i { position:absolute; top:-4px; width:3px; height:16px; background:var(--ink); border-radius:2px; transform:translateX(-50%); }
.data-asof { font-size:11px; color:var(--muted); margin:2px 0 6px; }
.rsi-gauge { position:relative; height:6px; border-radius:4px; background:var(--line); margin:8px 0 2px; }
.rsi-gauge .t30, .rsi-gauge .t70 { position:absolute; top:-2px; width:1px; height:10px; background:var(--muted); opacity:.5; }
.rsi-gauge .t30 { left:30%; } .rsi-gauge .t70 { left:70%; }
.rsi-gauge i { position:absolute; top:-3px; width:8px; height:12px; border-radius:3px; transform:translateX(-50%); background:var(--muted); }
.rsi-gauge i.up { background:var(--up); } .rsi-gauge i.down { background:var(--down); }

/* ── 히트맵 타일 (미니차트 포함 버전) ── */
.heat-tile { border:1px solid rgba(52,53,47,.06); border-radius:16px; padding:14px 14px 12px; }
.heat-name { font-size:12.5px; font-weight:600; }
.heat-val { font-size:18px; font-weight:700; margin-top:3px; letter-spacing:-.02em; }
.heat-pct { font-size:12.5px; font-weight:700; margin-top:2px; }
.heat-spark { width:100%; height:28px; display:block; margin-top:8px; }

.supply-wrap { background:var(--summary-bg); border:1px solid var(--line); border-radius:14px; padding:14px 16px; margin-bottom:10px; }
.supply-mkt { font-size:12px; font-weight:700; letter-spacing:.05em; color:var(--muted); margin-bottom:10px; }
.supply-row { display:flex; justify-content:space-between; align-items:center; padding:5px 0; border-bottom:1px solid var(--line); }
.supply-row:last-child { border-bottom:none; }
.supply-type { font-size:11px; font-weight:700; color:var(--sage-deep); width:52px; flex:none; }
.supply-stocks { font-size:12.5px; color:var(--ink); flex:1; }
.supply-stock-item { display:inline-block; margin-right:6px; }
.supply-val-pos { color:var(--up); font-weight:700; }
.supply-val-neg { color:var(--down); font-weight:700; }
.supply-note { font-size:11px; color:var(--muted); margin-top:8px; }
.cal-wrap { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:6px 16px; }
.cal-row { display:flex; align-items:center; gap:10px; padding:9px 0; border-bottom:1px solid var(--line); flex-wrap:wrap; }
.cal-row:last-child { border-bottom:none; }
.cal-dday { font-size:11.5px; font-weight:700; background:var(--pill-bg); color:var(--pill-ink); border:1px solid var(--line); padding:2px 8px; border-radius:7px; width:46px; text-align:center; flex:none; }
.cal-dday.cal-soon { background:var(--tint-up); color:var(--up); border-color:var(--up); }
.cal-dday.cal-today { background:var(--up); color:#fff; border-color:var(--up); }
.cal-date { font-size:12px; font-weight:600; color:var(--muted); width:42px; flex:none; }
.cal-name { font-size:13.5px; font-weight:600; color:var(--ink); }
.cal-cat { font-size:10.5px; font-weight:700; padding:2px 7px; border-radius:6px; background:var(--pill-bg); color:var(--pill-ink); flex:none; }
.cal-cat.cal-us { background:var(--tint-down); color:var(--down); }
.cal-cat.cal-kr { background:var(--tint-up); color:var(--up); }
.cal-cat.cal-earn { background:var(--summary-bg); color:var(--sage-deep); }
.cal-note { font-size:11.5px; color:var(--muted); }
.rpt-bar { height:3px; width:34px; background:var(--sage); border-radius:3px; margin:8px 0 8px; }
.rpt-toprow { display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; }
.mood-badge { font-size:11px; font-weight:700; letter-spacing:.06em; padding:4px 10px; border-radius:20px; }
.mood-pos { background:#e1f5ee; color:#0f6e56; }
.mood-neu { background:#F1F2EC; color:#5d6258; }
.mood-cau { background:#FAEEDA; color:#854F0B; }
.rpt-topmeta { font-size:11.5px; color:var(--muted); }
.rpt-headline { font-family:'Fraunces','Noto Sans KR',serif; font-size:22px; font-weight:600; letter-spacing:-.02em; color:var(--ink); margin-bottom:14px; }
.rpt-kt-label { font-size:11px; font-weight:700; letter-spacing:.06em; color:var(--sage-deep); margin-bottom:5px; }
.rpt-kt-box { font-size:15px; line-height:1.75; color:var(--ink); background:var(--summary-bg); border-left:3px solid var(--sage); padding:13px 17px; border-radius:0 10px 10px 0; margin-bottom:20px; }
.rpt-sec-title { font-size:16px; font-weight:700; color:var(--ink); border-bottom:1.5px solid var(--sage); padding-bottom:5px; margin:22px 0 8px; }
.rpt-sec-body { font-size:14.5px; line-height:1.8; color:var(--ink); margin-bottom:8px; }
.rpt-group-label { font-size:12px; font-weight:700; letter-spacing:.05em; color:var(--muted); margin:22px 0 10px; }
.theme-card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; margin-bottom:10px; }
.theme-name { font-size:14.5px; font-weight:700; color:var(--ink); margin-bottom:5px; }
.theme-detail { font-size:13.5px; line-height:1.7; color:var(--ink); margin-bottom:8px; }
.theme-tickers { font-size:12.5px; color:var(--muted); }
.rpt-sources { margin-top:22px; padding-top:12px; border-top:1px solid var(--line); font-size:12px; color:var(--muted); display:flex; flex-wrap:wrap; gap:6px; align-items:center; }
.src-pill { background:var(--pill-bg); color:var(--pill-ink); border:1px solid var(--line); font-size:11.5px; font-weight:600; padding:3px 9px; border-radius:7px; }
[data-testid="stMarkdownContainer"] ul li::marker { color:var(--sage); }
.sect-wrap { display:flex; flex-direction:column; gap:6px; }
.sect-row { display:grid; grid-template-columns:120px 1fr 64px; align-items:center; gap:10px; }
.sect-name { font-size:12.5px; font-weight:600; color:var(--ink); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.sect-track { position:relative; height:18px; background:var(--summary-bg); border-radius:5px; overflow:hidden; }
.sect-fill { position:absolute; top:0; bottom:0; border-radius:5px; }
.sect-fill.up { right:50%; background:var(--up); }
.sect-fill.down { left:50%; background:var(--down); }
.sect-mid { position:absolute; left:50%; top:0; bottom:0; width:1px; background:var(--line); }
.sect-pct { font-size:12px; font-weight:700; text-align:right; }
.sect-pct.up { color:var(--up); } .sect-pct.down { color:var(--down); }
.breadth-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:12px; }
@media (max-width:640px){ .breadth-grid{ grid-template-columns:1fr; } }
.breadth-card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:14px 16px; }
.breadth-mkt { font-size:12px; font-weight:700; letter-spacing:.04em; color:var(--muted); margin-bottom:9px; }
.breadth-bar { display:flex; height:22px; border-radius:6px; overflow:hidden; font-size:11px; font-weight:700; color:#fff; }
.breadth-seg-up { background:var(--up); display:flex; align-items:center; justify-content:center; }
.breadth-seg-flat { background:var(--muted); display:flex; align-items:center; justify-content:center; }
.breadth-seg-down { background:var(--down); display:flex; align-items:center; justify-content:center; }
.breadth-legend { font-size:11px; color:var(--muted); margin-top:7px; display:flex; gap:12px; flex-wrap:wrap; }
.breadth-legend b.up { color:var(--up); } .breadth-legend b.down { color:var(--down); }
.breadth-val { font-size:19px; font-weight:700; color:var(--ink); letter-spacing:-.02em; }
.breadth-sub { font-size:11.5px; color:var(--muted); margin-top:2px; }
.valu-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; }
@media (max-width:760px){ .valu-grid{ grid-template-columns:repeat(2,1fr);} }
.valu-card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:13px 15px; }
.valu-lab { font-size:11.5px; font-weight:600; color:var(--muted); }
.valu-val { font-size:20px; font-weight:700; color:var(--ink); margin-top:3px; letter-spacing:-.02em; }
.valu-sub { font-size:11px; color:var(--muted); margin-top:2px; }
.pill { display:inline-block; font-size:11.5px; font-weight:600; background:var(--pill-bg); color:var(--pill-ink); border:1px solid var(--line); padding:3px 9px; border-radius:7px; margin:0 5px 5px 0; }
.pill-link { text-decoration:none; transition:background .15s, border-color .15s; }
.pill-link:hover { background:var(--pill-hover); border-color:var(--sage); }
.kw-row { display:flex; gap:12px; padding:12px 0; border-bottom:1px solid var(--line); }
.kw-rank { font-family:'Fraunces','Noto Sans KR',serif; font-size:21px; font-weight:600; color:var(--sage-deep); width:26px; flex:none; text-align:center; }
.kw-mid { flex:1; min-width:0; }
.kw-kw { font-size:15.5px; font-weight:700; color:var(--ink); }
.kw-news { margin-top:4px; }
.kw-news a { display:inline-flex; align-items:center; gap:4px; font-size:13px; color:var(--sage-deep); text-decoration:none; font-weight:600; }
.kw-news a:hover { text-decoration:underline; }
.empty { text-align:center; color:var(--muted); padding:34px 16px; }
.empty .ico { font-size:32px; }
.empty .msg { font-size:14px; margin-top:10px; color:var(--ink); }
.empty .hint { font-size:12px; margin-top:5px; color:var(--muted); }

/* ═══ 마이크로 인터랙션 ═══ */
@keyframes mm-fade-up {
  from { opacity:0; transform:translateY(10px); }
  to   { opacity:1; transform:translateY(0); }
}
.mkt-card, .heat-tile, .kw-row, .theme-card, .supply-wrap, .cal-wrap, .rpt-kt-box {
  animation: mm-fade-up .5s cubic-bezier(.22,.61,.36,1) both;
}
.mkt-grid .mkt-card:nth-child(1){ animation-delay:.02s; }
.mkt-grid .mkt-card:nth-child(2){ animation-delay:.06s; }
.mkt-grid .mkt-card:nth-child(3){ animation-delay:.10s; }
.mkt-grid .mkt-card:nth-child(4){ animation-delay:.14s; }
.mkt-grid .mkt-card:nth-child(5){ animation-delay:.18s; }
.mkt-grid .mkt-card:nth-child(6){ animation-delay:.22s; }
.mkt-grid .mkt-card:nth-child(7){ animation-delay:.26s; }
.mkt-grid .mkt-card:nth-child(8){ animation-delay:.30s; }
.kw-row:nth-child(1){ animation-delay:.03s; }
.kw-row:nth-child(2){ animation-delay:.07s; }
.kw-row:nth-child(3){ animation-delay:.11s; }
.kw-row:nth-child(4){ animation-delay:.15s; }
.kw-row:nth-child(5){ animation-delay:.19s; }
.kw-row:nth-child(6){ animation-delay:.23s; }
.kw-row:nth-child(7){ animation-delay:.27s; }
.mkt-card, .heat-tile, .theme-card, .cal-wrap, .supply-wrap {
  transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease;
}
.mkt-card:hover, .heat-tile:hover, .theme-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 18px rgba(52,53,47,.08);
  border-color: var(--sage);
}
.cal-wrap:hover, .supply-wrap:hover {
  box-shadow: 0 4px 14px rgba(52,53,47,.06);
}
.kw-news a { transition: color .15s ease, transform .15s ease; }
.kw-news a:hover { transform: translateX(2px); }
@keyframes mm-bar-grow {
  from { transform: scaleX(0); }
  to   { transform: scaleX(1); }
}
@keyframes mm-marker-in {
  from { opacity:0; transform:translateX(-50%) scaleY(.3); }
  to   { opacity:1; transform:translateX(-50%) scaleY(1); }
}
.gauge, .rsi-gauge {
  transform-origin: left center;
  animation: mm-bar-grow .7s cubic-bezier(.22,.61,.36,1) both;
}
.gauge i, .rsi-gauge i {
  animation: mm-marker-in .5s ease .55s both;
}
@keyframes mm-pulse {
  0%   { opacity:.55; }
  40%  { opacity:1; }
  100% { opacity:1; }
}
.mkt-chg { animation: mm-pulse .9s ease both; }
.pill, .src-pill {
  transition: background .15s ease, border-color .15s ease,
              transform .15s ease, box-shadow .15s ease;
}
.pill:hover, .src-pill:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(52,53,47,.07);
}
.stButton > button {
  transition: transform .12s ease, box-shadow .15s ease,
              background .15s ease, border-color .15s ease !important;
}
.stButton > button:hover {
  transform: translateY(-1px);
  box-shadow: 0 3px 10px rgba(52,53,47,.10);
}
.stButton > button:active { transform: translateY(0); }
@media (prefers-reduced-motion: reduce) {
  .mkt-card, .heat-tile, .kw-row, .theme-card, .supply-wrap, .cal-wrap,
  .rpt-kt-box, .gauge, .rsi-gauge, .gauge i, .rsi-gauge i,
  .mkt-chg {
    animation: none !important;
  }
  * { transition: none !important; }
}
</style>
"""
st.markdown(CSS.replace("__VARS__", LIGHT_VARS), unsafe_allow_html=True)

# ── 상단 헤더 ──
now = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")
st.markdown(
    f'<div class="app-name">DY Monitoring</div>'
    f'<div class="app-upd">조회 {now} KST · 데이터 기준일은 항목별 표기</div>',
    unsafe_allow_html=True,
)
st.markdown('<hr style="border:none;border-top:1px solid var(--line);margin:6px 0 14px;">',
            unsafe_allow_html=True)

render_ticker_tape()


# ── 지수 카드 HTML ──
def _card_html(name, data):
    if data is None:
        return (f'<div class="mkt-card"><div class="mkt-name">{name}</div>'
                f'<div class="mkt-na">데이터 없음</div></div>')
    is_up = data["change"] >= 0
    good = (not is_up) if data.get("invert_color") else is_up
    cls = "up" if good else "down"
    tint = "mkt-up" if good else "mkt-down"
    v = "--up" if good else "--down"
    arrow = "▲" if data["change"] > 0 else ("▼" if data["change"] < 0 else "▬")
    pts = sparkline_points(data["series"], n=data.get("spark_n", 20))
    spark = ""
    if pts:
        spark = (f'<svg class="mkt-spark" viewBox="0 0 100 28" preserveAspectRatio="none">'
                 f'<polygon points="{pts} 100,28 0,28" style="fill:var({v});opacity:.10"/>'
                 f'<polyline points="{pts}" style="fill:none;stroke:var({v});stroke-width:1.6"/></svg>')
    return (f'<div class="mkt-card {tint}"><div class="mkt-name">{name}</div>'
            f'<div class="mkt-val mm-count" data-target="{data["current"]:.4f}">'
            f'{data["current"]:,.2f}</div>'
            f'<div class="mkt-chg {cls}">{arrow} {data["change"]:+,.2f} ({data["pct"]:+.2f}%)</div>'
            f'{spark}</div>')


# ── 히트맵 타일 색 ──
def _heat_color(pct):
    if pct is None:
        return "#F6F7F2", "#34352f"
    t = max(-1.0, min(1.0, pct / 3.0))
    base = (246, 247, 242)
    up = (182, 95, 90)
    down = (90, 124, 160)
    tgt = up if t >= 0 else down
    k = abs(t)
    r = round(base[0] + (tgt[0] - base[0]) * k)
    g = round(base[1] + (tgt[1] - base[1]) * k)
    b = round(base[2] + (tgt[2] - base[2]) * k)
    txt = "#ffffff" if k > 0.55 else "#34352f"
    return f"rgb({r},{g},{b})", txt


# ── 히트맵 타일 HTML (6개월 미니차트 포함) ──
def _heat_html(datas, histories=None):
    """히트맵 타일 그리드.

    histories: {표시이름: pd.Series(날짜→종가)}
    있으면 타일 하단에 6개월 SVG sparkline을 그려 추이를 보여준다.
    없으면 기존처럼 숫자만 표시.
    """
    histories = histories or {}
    tiles = ""
    for name, d in datas.items():
        if d is None:
            tiles += (f'<div class="heat-tile" style="background:#F6F7F2;color:#9a9b92;">'
                      f'<div class="heat-name">{name}</div>'
                      f'<div class="heat-val" style="font-size:14px;">데이터 없음</div></div>')
            continue

        pct = d.get("pct", 0.0)
        bg, txt = _heat_color(pct)
        arrow = "▲" if d["change"] > 0 else ("▼" if d["change"] < 0 else "▬")

        # 6개월 SVG sparkline
        spark = ""
        series = histories.get(name)
        if series is not None and len(series) >= 2:
            pts = sparkline_points(series, n=130)
            if pts:
                spark = (
                    f'<svg class="heat-spark" viewBox="0 0 100 28" preserveAspectRatio="none">'
                    f'<polygon points="{pts} 100,28 0,28" '
                    f'style="fill:{txt};opacity:.13"/>'
                    f'<polyline points="{pts}" '
                    f'style="fill:none;stroke:{txt};stroke-width:1.6;opacity:.65"/>'
                    f'</svg>'
                )

        tiles += (
            f'<div class="heat-tile" style="background:{bg};">'
            f'<div class="heat-name" style="color:{txt};opacity:.92;">{name}</div>'
            f'<div class="heat-val" style="color:{txt};">{d["current"]:,.2f}</div>'
            f'<div class="heat-pct" style="color:{txt};">{arrow} {pct:+.2f}%</div>'
            f'{spark}'
            f'</div>'
        )
    return f'<div class="mkt-grid">{tiles}</div>'


# ── 수급 상위 종목 HTML ──
def _supply_html(supply_data: dict) -> str:
    if not supply_data:
        return ""
    parts = []
    for mkt_label, mkt_data in supply_data.items():
        rows_html = ""
        for investor in ("외국인", "기관"):
            items = mkt_data.get(investor, [])
            if not items:
                continue
            stocks_html = ""
            for name, val in items:
                val_cls = "supply-val-pos" if val >= 0 else "supply-val-neg"
                stocks_html += (f'<span class="supply-stock-item">'
                                f'{name} <span class="{val_cls}">{val:+,}억</span>'
                                f'</span>')
            rows_html += (f'<div class="supply-row">'
                          f'<span class="supply-type">{investor}</span>'
                          f'<span class="supply-stocks">{stocks_html}</span>'
                          f'</div>')
        if rows_html:
            parts.append(
                f'<div class="supply-wrap">'
                f'<div class="supply-mkt">{mkt_label} · 순매수 상위 5종목</div>'
                f'{rows_html}'
                f'<div class="supply-note">⚠️ 전일 확정 데이터 · 당일 수급과 다를 수 있음</div>'
                f'</div>'
            )
    return "".join(parts)


# ── 국내 지수 대형 차트 ──
_KRX_PERIODS = {"1일": 1, "1개월": 31, "3개월": 92, "6개월": 183, "1년": 366}


def _big_index_chart_intraday(name: str, ticker: str):
    d = fetch_intraday(ticker, "5m")
    if not d or d.get("series") is None or len(d["series"]) < 2:
        st.caption(f"{name} 분봉 데이터를 불러오지 못했어요. "
                   f"(한국 지수 분봉은 지연·누락될 수 있어요. 다른 기간을 선택해 보세요.)")
        return

    s = d["series"]
    df = pd.DataFrame({"시각": pd.to_datetime(s.index),
                       "종가": pd.to_numeric(s.values, errors="coerce")}).dropna()
    if len(df) < 2:
        st.caption(f"{name} 분봉 데이터가 부족해요.")
        return

    cur = d["current"]
    change = d["change"]
    pct = d["pct"]
    day_up = change >= 0
    prev_close = d.get("prev_close")
    base_is_prev = d.get("base_is_prev", False)

    up_c, down_c = "#B65F5A", "#5A7CA0"
    line_c = up_c if day_up else down_c
    axis_c, grid_c = "#9a9b92", "#ECEDE7"

    base_label = "전일 종가 대비" if base_is_prev else "시가 대비"
    arrow = "▲" if change > 0 else ("▼" if change < 0 else "▬")
    chg_cls = "up" if day_up else "down"
    st.markdown(
        f'<div style="margin-bottom:2px;">'
        f'<span class="mkt-name">{name} · {d.get("asof","")} ({base_label})</span><br>'
        f'<span class="mkt-val" style="font-size:24px;">{cur:,.2f}</span> '
        f'<span class="mkt-chg {chg_cls}">{arrow} {change:+,.2f} ({pct:+.2f}%)</span>'
        f'</div>', unsafe_allow_html=True)

    lo_v, hi_v = float(df["종가"].min()), float(df["종가"].max())
    span = (hi_v - lo_v) or (hi_v * 0.01) or 1.0

    show_baseline = False
    if base_is_prev and prev_close is not None and prev_close > 0:
        if (lo_v - 1.5 * span) <= prev_close <= (hi_v + 1.5 * span):
            lo_v = min(lo_v, prev_close)
            hi_v = max(hi_v, prev_close)
            show_baseline = True

    pad_v = (hi_v - lo_v) * 0.10 or (hi_v * 0.01) or 1.0
    y_dom = [lo_v - pad_v, hi_v + pad_v]

    x_enc = alt.X("시각:T", axis=alt.Axis(title=None, format="%H:%M",
                                          labelColor=axis_c, grid=False))
    y_enc = alt.Y("종가:Q", scale=alt.Scale(domain=y_dom, nice=False, clamp=True, zero=False),
                  axis=alt.Axis(title=None, labelColor=axis_c, gridColor=grid_c,
                                format=",.0f"))
    tip = [alt.Tooltip("시각:T", format="%H:%M"),
           alt.Tooltip("종가:Q", format=",.2f")]

    y_floor = y_dom[0]
    df_a = df.copy()
    df_a["바닥"] = y_floor
    area = alt.Chart(df_a).mark_area(color=line_c, opacity=0.10).encode(
        x=x_enc, y=y_enc, y2=alt.Y2("바닥:Q"), tooltip=tip)

    layers = [area]
    line_layer = alt.Chart(df).mark_line(color=line_c, strokeWidth=2).encode(
        x=x_enc, y=y_enc, tooltip=tip)
    layers.append(line_layer)
    if show_baseline:
        baseline = alt.Chart(pd.DataFrame({"y": [prev_close]})).mark_rule(
            color=axis_c, strokeDash=[4, 4], opacity=0.7).encode(y="y:Q")
        layers.insert(0, baseline)

    try:
        hover = alt.selection_point(fields=["시각"], nearest=True,
                                    on="mouseover", empty=False)
        selectors = alt.Chart(df).mark_point().encode(
            x=x_enc, opacity=alt.value(0)).add_params(hover)
        rule = alt.Chart(df).mark_rule(color=axis_c, strokeDash=[3, 3]).encode(
            x=x_enc).transform_filter(hover)
        hpoints = alt.Chart(df).mark_point(size=60, color=line_c, filled=True).encode(
            x=x_enc, y=y_enc,
            opacity=alt.condition(hover, alt.value(1), alt.value(0)))
        chart = (alt.layer(*layers, selectors, rule, hpoints)
                 .properties(height=260, background="transparent")
                 .configure_view(strokeWidth=0))
    except Exception:
        chart = (alt.layer(*layers)
                 .properties(height=260, background="transparent")
                 .configure_view(strokeWidth=0))

    st.altair_chart(chart, use_container_width=True)


def _big_index_chart(name: str, ticker: str, days: int):
    close = fetch_history(ticker, "1y")
    if close is None or len(close) < 2:
        st.caption(f"{name} 데이터를 불러오지 못했어요. (잠시 후 새로고침)")
        return

    df = pd.DataFrame({"날짜": pd.to_datetime(close.index),
                       "종가": pd.to_numeric(close.values, errors="coerce")}).dropna()
    if len(df) < 2:
        st.caption(f"{name} 데이터가 부족해요.")
        return

    cutoff = df["날짜"].max() - pd.Timedelta(days=days)
    seg = df[df["날짜"] >= cutoff]
    if len(seg) < 2:
        seg = df

    cur, prev = float(seg["종가"].iloc[-1]), float(seg["종가"].iloc[-2])
    change = cur - prev
    pct = (change / prev) * 100 if prev else 0.0
    day_up = change >= 0
    period_up = cur >= float(seg["종가"].iloc[0])

    up_c, down_c = "#B65F5A", "#5A7CA0"
    line_c = up_c if period_up else down_c
    axis_c, grid_c = "#9a9b92", "#ECEDE7"

    arrow = "▲" if change > 0 else ("▼" if change < 0 else "▬")
    chg_cls = "up" if day_up else "down"
    st.markdown(
        f'<div style="margin-bottom:2px;">'
        f'<span class="mkt-name">{name}</span><br>'
        f'<span class="mkt-val" style="font-size:24px;">{cur:,.2f}</span> '
        f'<span class="mkt-chg {chg_cls}">{arrow} {change:+,.2f} ({pct:+.2f}%)</span>'
        f'</div>', unsafe_allow_html=True)

    lo_v, hi_v = float(seg["종가"].min()), float(seg["종가"].max())
    pad_v = (hi_v - lo_v) * 0.08 or 1.0
    y_dom = [lo_v - pad_v, hi_v + pad_v]

    x_enc = alt.X("날짜:T", axis=alt.Axis(title=None, format="%m/%d",
                                          labelColor=axis_c, grid=False))
    y_enc = alt.Y("종가:Q", scale=alt.Scale(domain=y_dom, nice=False, clamp=True, zero=False),
                  axis=alt.Axis(title=None, labelColor=axis_c, gridColor=grid_c,
                                format=",.0f"))
    tip = [alt.Tooltip("날짜:T", format="%Y-%m-%d"),
           alt.Tooltip("종가:Q", format=",.2f")]

    seg_a = seg.copy()
    seg_a["바닥"] = y_dom[0]
    area = alt.Chart(seg_a).mark_area(color=line_c, opacity=0.13).encode(
        x=x_enc, y=y_enc, y2=alt.Y2("바닥:Q"), tooltip=tip)
    line_main = alt.Chart(seg).mark_line(color=line_c, strokeWidth=2).encode(
        x=x_enc, y=y_enc, tooltip=tip)

    try:
        hover = alt.selection_point(fields=["날짜"], nearest=True,
                                    on="mouseover", empty=False)
        zoom = alt.selection_interval(bind="scales", encodings=["x"])
        selectors = alt.Chart(seg).mark_point().encode(
            x=x_enc, opacity=alt.value(0)).add_params(hover)
        rule = alt.Chart(seg).mark_rule(color=axis_c, strokeDash=[3, 3]).encode(
            x=x_enc).transform_filter(hover)
        hpoints = alt.Chart(seg).mark_point(size=60, color=line_c, filled=True).encode(
            x=x_enc, y=y_enc,
            opacity=alt.condition(hover, alt.value(1), alt.value(0)))
        htext = alt.Chart(seg).mark_text(
            align="left", dx=8, dy=-10, fontSize=12, fontWeight="bold",
            color=line_c).encode(
            x=x_enc, y=y_enc,
            text=alt.condition(hover, alt.Text("종가:Q", format=",.2f"),
                               alt.value("")))
        chart = (alt.layer(area, line_main, selectors, rule, hpoints, htext)
                 .add_params(zoom)
                 .properties(height=260, background="transparent")
                 .configure_view(strokeWidth=0))
    except Exception:
        chart = (alt.layer(area, line_main)
                 .properties(height=260, background="transparent")
                 .configure_view(strokeWidth=0))

    st.altair_chart(chart, use_container_width=True)


def _render_domestic_charts():
    period_label = st.radio(
        "조회 기간", list(_KRX_PERIODS.keys()), index=3, horizontal=True,
        key="krx_chart_period", label_visibility="collapsed")

    is_intraday = (period_label == "1일")
    days = _KRX_PERIODS[period_label]

    c1, c2 = st.columns(2, gap="medium")
    with c1:
        if is_intraday:
            _big_index_chart_intraday("코스피", "^KS11")
        else:
            _big_index_chart("코스피", "^KS11", days)
    with c2:
        if is_intraday:
            _big_index_chart_intraday("코스닥", "^KQ11")
        else:
            _big_index_chart("코스닥", "^KQ11", days)

    if is_intraday:
        st.caption("당일(휴장 시 직전 거래일) 5분봉 · 전일 종가 대비 등락(회색 점선=전일 종가) · "
                   "yfinance 기준 약 15분 지연이며 한국 지수 분봉은 일부 누락될 수 있어요.")
    else:
        st.caption("차트 위에서 마우스를 올리면 해당일 값이 표시되고, "
                   "가로 스크롤·드래그로 기간을 확대할 수 있어요.")


# ── 지수 현황 본문 ──
def _render_indices_body():
    group_data, group_asof = {}, {}
    for group_name, tickers in INDEX_GROUPS.items():
        datas = {name: fetch_index(t) for name, t in tickers.items()}
        group_data[group_name] = datas
        asofs = [d["asof"] for d in datas.values() if d and d.get("asof")]
        group_asof[group_name] = max(asofs) if asofs else None

    distinct = {a for a in group_asof.values() if a}
    unified = len(distinct) == 1
    if unified:
        st.markdown(
            f'<div class="data-asof">데이터 기준 {next(iter(distinct))} · '
            f'해외 지수·환율은 직전 거래일 종가</div>', unsafe_allow_html=True)

    krx_head = '<div class="mkt-group">국내'
    if not unified and group_asof.get("국내"):
        krx_head += f'<span class="grp-asof">기준 {group_asof["국내"]}</span>'
    krx_head += "</div>"
    st.markdown(krx_head, unsafe_allow_html=True)
    _render_domestic_charts()

    from modules.supply_trend import render_supply_trend
    render_supply_trend()

    st.markdown('<hr class="grp-divider">', unsafe_allow_html=True)
    from modules.market_breadth import render_market_breadth
    render_market_breadth()

    st.markdown('<hr class="grp-divider">', unsafe_allow_html=True)
    from modules.sectors import render_sectors
    render_sectors()

    st.markdown('<hr class="grp-divider">', unsafe_allow_html=True)
    render_indicators()
    render_calendar()

    # ── 히트맵 그룹 (미국·환율·원자재·암호화폐) + 6개월 미니차트 ──
    st.markdown('<hr class="grp-divider">', unsafe_allow_html=True)
    st.caption("🌡️ 히트맵 · 타일 색 = 등락률 (빨강 상승 / 파랑 하락, ±3%에서 최대 채도) · 미니차트 = 6개월 추이")
    for group_name, datas in group_data.items():
        if group_name == "국내":
            continue
        st.markdown('<hr class="grp-divider">', unsafe_allow_html=True)
        head = f'<div class="mkt-group">{group_name}'
        if not unified and group_asof[group_name]:
            head += f'<span class="grp-asof">기준 {group_asof[group_name]}</span>'
        head += "</div>"
        st.markdown(head, unsafe_allow_html=True)

        # 6개월 히스토리 수집 (fetch_history는 3600s 캐시 → 추가 API 비용 없음)
        histories = {}
        for item_name, ticker in INDEX_GROUPS[group_name].items():
            try:
                hist = fetch_history(ticker, "6mo")
                if hist is not None and len(hist) >= 2:
                    histories[item_name] = hist
            except Exception:
                pass

        st.markdown(_heat_html(datas, histories), unsafe_allow_html=True)

    supply = fetch_supply_demand_summary()
    if supply:
        st.markdown('<hr class="grp-divider">', unsafe_allow_html=True)
        st.markdown('<div class="mkt-group">💰 수급 상위 종목</div>', unsafe_allow_html=True)
        st.markdown(_supply_html(supply), unsafe_allow_html=True)

    st.markdown('<hr class="grp-divider">', unsafe_allow_html=True)
    from modules.rates import render_rates
    render_rates()
    st.markdown('<hr class="grp-divider">', unsafe_allow_html=True)
    from modules.rate_gap import render_rate_gap
    render_rate_gap()


# ── 지수 현황 탭 ──
def render_indices():
    st.markdown('<div class="accent-bar"></div>', unsafe_allow_html=True)
    st.title("주요 지수 현황")
    st.caption("데이터: Yahoo Finance · 일별 종가 기준 · 약 15분 지연")

    if st.button("🔄 새로고침"):
        st.cache_data.clear()
        st.rerun()

    has_frag = hasattr(st, "fragment")
    market_open = is_kr_market_open()
    every = 600 if (has_frag and market_open) else None

    if market_open:
        st.caption("🟢 장중 자동 새로고침 켜짐 · 약 10분 주기 (데이터는 약 15분 지연)")
    else:
        st.caption("⏸ 장외 시간 · 다음 개장(평일 09:00 KST)부터 자동 새로고침이 작동해요.")

    if every:
        st.fragment(_render_indices_body, run_every=every)()
    else:
        _render_indices_body()


# ── 사용량 · 비용 ──
def render_usage_section():
    last = st.session_state.get("last_gen")
    if not (last and last.get("ok")):
        return

    st.markdown('<div class="mkt-group">사용량 · 비용</div>', unsafe_allow_html=True)
    rate_data = fetch_index("KRW=X")
    rate = rate_data["current"] if rate_data else None

    def to_krw(usd):
        return f" ≈ {usd * rate:,.0f}원" if rate else ""

    u, c = last["usage"], last["cost_usd"]
    c1, c2, c3 = st.columns(3)
    c1.metric("입력 토큰", f"{u['input_tokens']:,}")
    c2.metric("출력 토큰", f"{u['output_tokens']:,}")
    c3.metric("본 리포트 생성 비용", f"${c:.4f}", help=to_krw(c).strip())
    st.caption("※ 토큰 단가 기반 추정치입니다. 실제 청구액은 Anthropic 콘솔(Billing)에서 확인하세요.")


# ── 생성 권한 확인 ──
def _can_generate():
    try:
        pw_required = st.secrets.get("APP_PASSWORD", "")
    except Exception:
        pw_required = ""

    if not pw_required:
        return True
    if st.session_state.get("gen_authed"):
        return True

    with st.expander("🔒 리포트 생성은 잠겨 있어요 (소유자 전용)", expanded=False):
        st.caption("이 대시보드는 자유롭게 둘러볼 수 있어요. 리포트 생성만 소유자 비밀번호가 필요합니다.")
        pw = st.text_input("비밀번호", type="password", key="gen_pw")
        if st.button("잠금 해제", key="gen_unlock"):
            if pw == pw_required:
                st.session_state["gen_authed"] = True
                st.success("잠금 해제됐어요. 이제 리포트를 생성할 수 있어요.")
                st.rerun()
            else:
                st.error("비밀번호가 일치하지 않아요.")
    return False


# ── 전략·시황 보고서 탭 ──
def render_report_tab():
    jumped = st.session_state.pop("rpt_jump_notice", None)
    if jumped:
        st.info("📍 추세 타임라인에서 선택한 날짜의 보고서를 보고 있어요. "
                "오늘로 돌아가려면 아래 '지난 보고서 보기'에서 '↩ 오늘로'를 누르세요.")

    render_reports()

    # ── 타임라인 (최근 5거래일 보고서 흐름) ──
    # 'DB에 저장돼요…' 안내 문구(=render_reports의 마지막 캡션) 바로 아래에 표시.
    render_timeline()

    st.divider()

    flash = st.session_state.pop("gen_flash", None)
    if flash:
        st.success(flash)

    authed = _can_generate()
    st.markdown('<div class="mkt-group">📝 리포트 관리</div>', unsafe_allow_html=True)
    gc1, gc2 = st.columns(2)
    with gc1:
        pre_clicked = st.button(
            "🌅 장전 보고서 생성", disabled=not authed, use_container_width=True,
            help="전일 15:30 ~ 지금 (월요일이면 금요일 15:30부터) 메시지 분석")
    with gc2:
        post_clicked = st.button(
            "🌆 장마감 후 보고서 생성", disabled=not authed, use_container_width=True,
            help="당일 07:50 ~ 지금 메시지 분석")

    if (pre_clicked or post_clicked) and authed:
        kind = "pre" if pre_clicked else "post"
        kind_ko = "장전" if kind == "pre" else "장마감 후"
        with st.spinner(f"{kind_ko} 보고서 생성 중... 텔레그램 수집 → Claude 분석 "
                        f"(메시지가 많으면 시간이 걸립니다)"):
            try:
                from engine.generate import generate_report
                res = generate_report(kind=kind)
            except Exception as e:
                res = {"ok": False, "reason": str(e)}
        st.session_state["last_gen"] = res
        if res.get("ok"):
            st.session_state["gen_flash"] = (
                f"{kind_ko} 보고서 생성 완료 · {res['messages']}개 메시지 분석")
            st.session_state["rpt_picked_path"] = None
            st.rerun()
        else:
            st.warning(f"{kind_ko} 생성 실패 · {res.get('reason')}")

    render_reports_manage()
    st.divider()
    render_usage_section()


# ── 카운트업 스크립트 ──
def _inject_countup():
    components.html(
        """
        <script>
        (function(){
          const doc = window.parent && window.parent.document
                      ? window.parent.document : document;
          const reduce = window.matchMedia &&
              window.matchMedia('(prefers-reduced-motion: reduce)').matches;
          function fmt(n){
            return n.toLocaleString('en-US',
              {minimumFractionDigits:2, maximumFractionDigits:2});
          }
          function animate(el){
            if (el.dataset.mmDone === '1') return;
            const target = parseFloat(el.dataset.target);
            if (isNaN(target)) return;
            el.dataset.mmDone = '1';
            if (reduce){ el.textContent = fmt(target); return; }
            const dur = 700, t0 = performance.now();
            const start = target * 0.92;
            function step(now){
              const p = Math.min((now - t0) / dur, 1);
              const e = 1 - Math.pow(1 - p, 3);
              el.textContent = fmt(start + (target - start) * e);
              if (p < 1) requestAnimationFrame(step);
              else el.textContent = fmt(target);
            }
            requestAnimationFrame(step);
          }
          function scan(){
            doc.querySelectorAll('.mkt-val.mm-count[data-target]')
               .forEach(animate);
          }
          scan();
          const mo = new MutationObserver(scan);
          mo.observe(doc.body, {childList:true, subtree:true});
          setTimeout(function(){ mo.disconnect(); }, 4000);
        })();
        </script>
        """,
        height=0,
    )


# ── 탭 ──
_inject_countup()
tab_idx, tab_rep, tab_kw = st.tabs(
    ["지수", "시황", "키워드"]
)
with tab_idx:
    render_indices()
with tab_rep:
    render_report_tab()
with tab_kw:
    render_keywords()
    st.divider()
    render_watchlist_tab()
