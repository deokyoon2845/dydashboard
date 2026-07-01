"""시장 현황 대시보드 - Streamlit 메인 앱 (라이트 단일 테마, 통일 헤더)."""

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

from modules.indices import (
    INDEX_GROUPS, fetch_index, sparkline_points, sparkline_axis_html,
    fetch_history, fetch_intraday,
    is_kr_market_open,
)
from modules.calendar_view import render_calendar
from modules.timeline_view import render_timeline
from modules.indicators import render_indicators
from modules.reports import render_reports, render_reports_manage
from modules.keywords_view import render_keywords
from modules.leaders import render_leaders
from modules.watchlist_brief import render_watchlist_tab
from modules.usage import total_cost_usd
from modules.ticker_tape import render_ticker_tape
from modules.watchlist_brief import render_watchlist_tab
from modules.ipo import render_ipo_tab

load_dotenv()
st.set_page_config(page_title="DY Monitoring", page_icon="🔭", layout="wide")

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
.sect-banner { font-family:'Fraunces','Noto Sans KR',serif; font-size:15.5px; font-weight:600; color:var(--sage-deep); letter-spacing:.01em; margin:18px 0 14px; display:flex; align-items:center; gap:9px; }
.sect-banner::before { content:""; width:18px; height:3px; background:var(--sage); border-radius:3px; flex:none; }
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

/* ── 미니차트 보름축 (3개월 · 하단 눈금 + 월 라벨) ── */
.spark-wrap { position:relative; margin-top:8px; }
.spark-wrap .heat-spark, .spark-wrap .mkt-spark { margin-top:0; }
.spark-axis { position:relative; height:13px; margin-top:1px; }
.spark-axis span { position:absolute; top:0; font-size:9px; line-height:1; opacity:.6; white-space:nowrap; transform:translateX(-50%); }
.spark-axis span.first { transform:none; left:0 !important; }
.spark-axis span.last { transform:none; left:auto !important; right:0; }

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


# ── 히트맵 타일 HTML (3개월 미니차트 + 보름축 포함) ──
def _heat_html(datas, histories=None):
    """히트맵 타일 그리드.

    histories: {표시이름: pd.Series(날짜→종가)}
    있으면 타일 하단에 3개월 미니차트(하단 보름 눈금 + 월 라벨)를 그려 추이를 보여준다.
    없으면 숫자만 표시.
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

        # 3개월 미니차트 (하단 보름 눈금 + 월 라벨)
        spark = ""
        series = histories.get(name)
        if series is not None and len(series) >= 2:
            spark = sparkline_axis_html(series, txt, height=38, n_days=92,
                                        label_color=txt)

        tiles += (
            f'<div class="heat-tile" style="background:{bg};">'
            f'<div class="heat-name" style="color:{txt};opacity:.92;">{name}</div>'
            f'<div class="heat-val" style="color:{txt};">{d["current"]:,.2f}</div>'
            f'<div class="heat-pct" style="color:{txt};">{arrow} {pct:+.2f}%</div>'
            f'{spark}'
            f'</div>'
        )
    return f'<div class="mkt-grid">{tiles}</div>'


# ── 국내 지수 대형 차트 ──
_KRX_PERIODS = {"1일": 1, "1개월": 31, "3개월": 92, "6개월": 183, "1년": 366}


def _area_gradient(hex_c: str, top: float = 0.20, bottom: float = 0.0):
    """라인 아래 영역용 수직 그라데이션 — 위(라인 쪽)는 진하고 아래로 갈수록 투명.

    hex_c(#RRGGBB) → rgba 스톱으로 변환. 단색 area보다 차분하고 입체감 있는 채우기.
    """
    h = hex_c.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return alt.Gradient(
        gradient="linear", x1=1, x2=1, y1=0, y2=1,    # 수직(위→아래)
        stops=[alt.GradientStop(color=f"rgba({r},{g},{b},{top})", offset=0),
               alt.GradientStop(color=f"rgba({r},{g},{b},{bottom})", offset=1)],
    )


# 지수 메인 차트(코스피·코스닥) 등장 정책 — C안: 통일된 소프트 페이드 1회 + 호버 반응.
# 개별 stagger·카운트업·차트 그리기 애니메이션 없이 컨테이너가 한 번 부드럽게 떠오른다.
# .st-key-idx_domestic_charts 로 지수 차트에만 스코프(다른 탭 차트엔 영향 없음).
_IDX_CHART_CSS = """
<style>
.st-key-idx_domestic_charts [data-testid="stVegaLiteChart"],
.st-key-idx_domestic_charts [data-testid="stArrowVegaLiteChart"],
.st-key-idx_domestic_charts .stVegaLiteChart{
  animation: idxChartFade .42s cubic-bezier(.22,.61,.36,1) both;
  border-radius: 12px;
  transition: box-shadow .22s ease;
}
@keyframes idxChartFade{ from{opacity:0;} to{opacity:1;} }
.st-key-idx_domestic_charts [data-testid="stVegaLiteChart"]:hover,
.st-key-idx_domestic_charts [data-testid="stArrowVegaLiteChart"]:hover,
.st-key-idx_domestic_charts .stVegaLiteChart:hover{
  box-shadow: 0 8px 22px rgba(52,53,47,.07);
}
@media(prefers-reduced-motion:reduce){
  .st-key-idx_domestic_charts [data-testid="stVegaLiteChart"],
  .st-key-idx_domestic_charts [data-testid="stArrowVegaLiteChart"],
  .st-key-idx_domestic_charts .stVegaLiteChart{ animation:none !important; }
}
</style>
"""


def _svg_index_chart(labels, ys, line_color, prev_close=None, height=260):
    """코스피/코스닥 차트를 SVG로 직접 렌더.

    라인이 좌→우로 그려지고 area가 함께 차오르는 단일 등장 애니메이션(0.85s)을
    SVG clip-reveal로 구현해 Altair/Vega의 렌더 지연으로 생기던 '딱딱 끊김'을 없앴다.
    crosshair hover(세로선·점·값 툴팁)와 반응형(폭 변화 시 재계산)을 자체 제공한다.
    """
    hx = line_color.lstrip("#")
    r, g, b = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
    tpl = r'''<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css">
<style>
html,body{margin:0;background:transparent;}
#host{width:100%;height:__H__px;}
svg{display:block;width:100%;height:__H__px;overflow:visible;}
text{font-family:Pretendard,'Noto Sans KR',sans-serif;}
.ic-line{fill:none;stroke:__COLOR__;stroke-width:2;stroke-linejoin:round;stroke-linecap:round;}
</style></head><body><div id="host"></div>
<script>
var YS=__YS__, LB=__LB__, PREV=__PREV__, H=__H__, COLOR="__COLOR__", RGB="__RGB__", first=true;
var REDUCE = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
function draw(){
  var host=document.getElementById('host');
  var W=Math.max(280, host.clientWidth||700);
  var ml=50,mr=14,mt=12,mb=24, pw=W-ml-mr, ph=H-mt-mb;
  var lo=Math.min.apply(null,YS), hi=Math.max.apply(null,YS);
  if(PREV!=null){lo=Math.min(lo,PREV);hi=Math.max(hi,PREV);}
  var pad=(hi-lo)*0.10||hi*0.005||1; lo-=pad; hi+=pad; var sp=(hi-lo)||1, n=YS.length;
  function X(i){return ml+(n>1?i/(n-1):0)*pw;}
  function Y(v){return mt+(1-(v-lo)/sp)*ph;}
  var line='M'+YS.map(function(v,i){return X(i).toFixed(1)+','+Y(v).toFixed(1);}).join(' L');
  var area=line+' L'+X(n-1).toFixed(1)+','+(mt+ph).toFixed(1)+' L'+X(0).toFixed(1)+','+(mt+ph).toFixed(1)+' Z';
  var yg='';
  for(var k=0;k<5;k++){var v=lo+sp*k/4, y=Y(v).toFixed(1);
    yg+='<line x1='+ml+' y1='+y+' x2='+(ml+pw)+' y2='+y+' stroke="#ECEDE7"/>';
    yg+='<text x='+(ml-8)+' y='+(parseFloat(y)+3.5).toFixed(1)+' text-anchor="end" font-size="11" fill="#9a9b92">'+Math.round(v).toLocaleString()+'</text>';}
  var xg='', step=Math.max(1,Math.floor(n/6));
  for(var i=0;i<n;i+=step){xg+='<text x='+X(i).toFixed(1)+' y='+(H-7)+' text-anchor="middle" font-size="11" fill="#9a9b92">'+LB[i]+'</text>';}
  var pv='';
  if(PREV!=null){var py=Y(PREV).toFixed(1);
    pv='<line x1='+ml+' y1='+py+' x2='+(ml+pw)+' y2='+py+' stroke="#9a9b92" stroke-dasharray="4 4" opacity="0.6"/>';}
  var doAnim = first && !REDUCE;
  var aw = doAnim ? '<animate attributeName="width" from="0" to="'+pw+'" dur="0.85s" calcMode="spline" keyTimes="0;1" keySplines="0.22 0.61 0.36 1" fill="freeze"/>' : '';
  var rw = doAnim ? 0 : pw;
  var svg='<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">'
    +'<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="rgba('+RGB+',0.20)"/><stop offset="1" stop-color="rgba('+RGB+',0)"/></linearGradient>'
    +'<clipPath id="rv"><rect x="'+ml+'" y="0" width="'+rw+'" height="'+H+'">'+aw+'</rect></clipPath></defs>'
    +yg+pv
    +'<g clip-path="url(#rv)"><path d="'+area+'" fill="url(#g)"/><path d="'+line+'" class="ic-line"/></g>'
    +xg
    +'<g id="cr" style="display:none"><line id="vl" y1="'+mt+'" y2="'+(mt+ph)+'" stroke="#9a9b92" stroke-dasharray="3 3"/><circle id="dt" r="4" fill="'+COLOR+'"/><g id="tp"><rect id="tb" rx="4" height="18" fill="#34352f"/><text id="tt" font-size="11" font-weight="700" fill="#fff" text-anchor="middle"></text></g></g>'
    +'<rect id="ht" x="'+ml+'" y="'+mt+'" width="'+pw+'" height="'+ph+'" fill="transparent" style="cursor:crosshair"/>'
    +'</svg>';
  host.innerHTML=svg; first=false;
  var root=host.querySelector('svg'),cr=root.querySelector('#cr'),vl=root.querySelector('#vl'),dt=root.querySelector('#dt'),tb=root.querySelector('#tb'),tt=root.querySelector('#tt'),ht=root.querySelector('#ht');
  var P=YS.map(function(v,i){return [X(i),Y(v),v,LB[i]];});
  ht.addEventListener('mousemove',function(e){
    var r=root.getBoundingClientRect(), mx=(e.clientX-r.left)/r.width*W, bi=0, bd=1e9;
    for(var i=0;i<P.length;i++){var dd=Math.abs(P[i][0]-mx);if(dd<bd){bd=dd;bi=i;}}
    var p=P[bi]; cr.style.display='';
    vl.setAttribute('x1',p[0]);vl.setAttribute('x2',p[0]);dt.setAttribute('cx',p[0]);dt.setAttribute('cy',p[1]);
    var txt=p[3]+'  '+p[2].toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
    tt.textContent=txt; var tw=txt.length*6.7+14, tx=Math.max(ml+tw/2,Math.min(ml+pw-tw/2,p[0])), ty=Math.max(mt+13,p[1]-12);
    tb.setAttribute('width',tw);tb.setAttribute('x',tx-tw/2);tb.setAttribute('y',ty-13);tt.setAttribute('x',tx);tt.setAttribute('y',ty);
  });
  ht.addEventListener('mouseleave',function(){cr.style.display='none';});
}
draw(); var rt; window.addEventListener('resize',function(){clearTimeout(rt);rt=setTimeout(draw,150);});
</script></body></html>'''
    return (tpl
            .replace("__YS__", json.dumps([round(float(v), 2) for v in ys]))
            .replace("__LB__", json.dumps(list(labels), ensure_ascii=False))
            .replace("__PREV__", "null" if prev_close is None else repr(float(prev_close)))
            .replace("__H__", str(int(height)))
            .replace("__COLOR__", line_color)
            .replace("__RGB__", "%d,%d,%d" % (r, g, b)))


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
    pv = None
    if base_is_prev and prev_close is not None and prev_close > 0:
        if (lo_v - 1.5 * span) <= prev_close <= (hi_v + 1.5 * span):
            pv = float(prev_close)

    labels = [t.strftime("%H:%M") for t in df["시각"]]
    ys = [float(v) for v in df["종가"]]
    components.html(
        _svg_index_chart(labels, ys, line_c, prev_close=pv, height=260),
        height=272)


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

    labels = [d.strftime("%m/%d") for d in seg["날짜"]]
    ys = [float(v) for v in seg["종가"]]
    components.html(
        _svg_index_chart(labels, ys, line_c, prev_close=None, height=260),
        height=272)


def _render_domestic_charts():
    st.markdown(_IDX_CHART_CSS, unsafe_allow_html=True)
    period_label = st.radio(
        "조회 기간", list(_KRX_PERIODS.keys()), index=3, horizontal=True,
        key="krx_chart_period", label_visibility="collapsed")

    is_intraday = (period_label == "1일")
    days = _KRX_PERIODS[period_label]

    try:
        chart_box = st.container(key="idx_domestic_charts")
    except TypeError:                 # 구버전 Streamlit 폴백(스코프만 생략, 동작은 정상)
        chart_box = st.container()
    with chart_box:
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
                   "정규장(09:00~15:30)만 표시 · yfinance 기준 약 15분 지연이며 일부 누락될 수 있어요.")
    else:
        st.caption("차트 위에 마우스를 올리면 해당 시점·값(세로축)이 십자선으로 표시되고, "
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

    # 3개월 히스토리 수집 (히트맵 미니차트용 · fetch_history 3600s 캐시 → 추가 비용 없음)
    def _histories(group):
        out = {}
        for item_name, ticker in INDEX_GROUPS[group].items():
            try:
                hist = fetch_history(ticker, "3mo")
                if hist is not None and len(hist) >= 2:
                    out[item_name] = hist
            except Exception:
                pass
        return out

    def _heat_group(group):
        st.markdown('<hr class="grp-divider">', unsafe_allow_html=True)
        head = f'<div class="mkt-group">{group}'
        if not unified and group_asof.get(group):
            head += f'<span class="grp-asof">기준 {group_asof[group]}</span>'
        head += "</div>"
        st.markdown(head, unsafe_allow_html=True)
        st.markdown(_heat_html(group_data[group], _histories(group)),
                    unsafe_allow_html=True)

    # ══════════════════ 1. 국내 증시 ══════════════════
    st.markdown('<div class="sect-banner">국내 증시</div>', unsafe_allow_html=True)
    krx_head = '<div class="mkt-group">코스피 · 코스닥'
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

    # ══════════════════ 2. 시장 심리 ══════════════════
    st.markdown('<hr class="grp-divider">', unsafe_allow_html=True)
    st.markdown('<div class="sect-banner">시장 심리</div>', unsafe_allow_html=True)
    render_indicators()

    # ══════════════════ 3. 글로벌 지수 ══════════════════
    st.markdown('<hr class="grp-divider">', unsafe_allow_html=True)
    st.markdown('<div class="sect-banner">글로벌 지수</div>', unsafe_allow_html=True)
    st.caption("🌡️ 히트맵 · 타일 색 = 등락률 (빨강 상승 / 파랑 하락, ±3%에서 최대 채도) · "
               "미니차트 = 3개월 추이 (하단 눈금 = 보름)")
    for g in ("미국", "변동성·원자재", "암호화폐"):
        if g in INDEX_GROUPS:
            _heat_group(g)

    # ══════════════════ 4. 외환 · 금리 ══════════════════
    st.markdown('<hr class="grp-divider">', unsafe_allow_html=True)
    st.markdown('<div class="sect-banner">외환 · 금리</div>', unsafe_allow_html=True)
    if "환율" in INDEX_GROUPS:
        _heat_group("환율")

    st.markdown('<hr class="grp-divider">', unsafe_allow_html=True)
    from modules.rates import render_rates
    render_rates()

    st.markdown('<hr class="grp-divider">', unsafe_allow_html=True)
    from modules.rate_gap import render_rate_gap
    render_rate_gap()

    # ══════════════════ 5. 일정 ══════════════════
    st.markdown('<hr class="grp-divider">', unsafe_allow_html=True)
    st.markdown('<div class="sect-banner">일정</div>', unsafe_allow_html=True)
    render_calendar()


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


# ── 수집 상태 패널(신선도·카운트 — 조용한 실패 방어) ───────────────
@st.cache_data(ttl=600, show_spinner=False)
def _collect_status():
    """소스별 최신 asof·카운트 수집(10분 캐시). DB 미설정이면 None."""
    from datetime import date
    from modules.db import (supabase_configured, load_realestate,
                            load_keywords_latest, list_recent,
                            load_leaders, load_ipo)
    if not supabase_configured():
        return None
    today = date.today()

    def age(d):
        try:
            return (today - date.fromisoformat(str(d)[:10])).days
        except Exception:
            return None

    out = []
    try:
        r = load_realestate() or {}
        m = r.get("metrics") or {}
        ad = (r.get("asof") or "")[:10]
        out.append({"src": "부동산", "asof": ad, "age": age(ad), "limit": 2,
                    "counts": [("주목", len(m.get("_hot") or [])),
                               ("시총", len(m.get("_caplead") or [])),
                               ("상승률", len(m.get("_capgain") or [])),
                               ("특이", len(r.get("anomalies") or [])),
                               ("지표", len(r.get("indicators") or [])),
                               ("분양", len(r.get("subscriptions") or []))],
                    "fallback": ["주목", "시총", "상승률", "지표"]})
    except Exception as e:
        out.append({"src": "부동산", "error": str(e)[:80]})
    try:
        rep = list_recent(1) or []
        rd = (rep[0].get("report_date") if rep else "") or ""
        out.append({"src": "시황 보고서", "asof": rd[:10], "age": age(rd),
                    "limit": None, "counts": [("최근행", len(rep))]})
    except Exception as e:
        out.append({"src": "시황 보고서", "error": str(e)[:80]})
    try:
        kw = load_keywords_latest() or {}
        out.append({"src": "키워드", "asof": (kw.get("kw_date") or "")[:10],
                    "age": age(kw.get("kw_date")), "limit": 3,
                    "counts": [("키워드", len(kw.get("items") or []))],
                    "fallback": ["키워드"]})
    except Exception as e:
        out.append({"src": "키워드", "error": str(e)[:80]})
    try:
        ld = load_leaders() or {}
        key = ld.get("asof_date") or ld.get("asof")
        out.append({"src": "주도주", "asof": (str(key) or "")[:10], "age": age(key),
                    "limit": 3, "counts": [("종목", len(ld.get("stocks") or [])),
                                           ("섹터", len(ld.get("sectors") or []))],
                    "fallback": ["종목"]})
    except Exception as e:
        out.append({"src": "주도주", "error": str(e)[:80]})
    try:
        ip = load_ipo() or {}
        out.append({"src": "IPO", "asof": (ip.get("asof") or "")[:10],
                    "age": age(ip.get("asof")), "limit": 3,
                    "counts": [("최근", len(ip.get("recent") or [])),
                               ("예정", len(ip.get("upcoming") or []))]})
    except Exception as e:
        out.append({"src": "IPO", "error": str(e)[:80]})
    return out


def _age_txt(a):
    if a is None:
        return "?"
    return "오늘" if a == 0 else ("어제" if a == 1 else f"{a}일 전")


def _render_status_panel():
    """🩺 수집 상태 — 소스별 신선도·카운트. 0건 폴백(샘플 표시)을 드러낸다."""
    try:
        rows = _collect_status()
    except Exception as e:
        with st.expander("🩺 수집 상태", expanded=False):
            st.caption(f"상태 확인 실패: {str(e)[:120]}")
        return
    with st.expander("🩺 수집 상태", expanded=False):
        if rows is None:
            st.caption("Supabase 미설정 — 상태를 확인할 수 없어요.")
            return
        lines = []
        for r in rows:
            if r.get("error"):
                lines.append(f"🔴 **{r['src']}** · 로드 실패: {r['error']}")
                continue
            asof = r.get("asof") or ""
            a = r.get("age")
            lim = r.get("limit")
            counts = r.get("counts", [])
            fb = set(r.get("fallback") or [])
            zeros = [k for k, v in counts if k in fb and v == 0]
            if not asof:
                badge = "🔴"
            elif zeros or (lim is not None and a is not None and a > lim):
                badge = "🟡"
            else:
                badge = "🟢"
            cnt = " · ".join(f"{k} {v}" for k, v in counts)
            ztxt = f"  ⚠️ {'·'.join(zeros)} 0건(샘플 표시 중)" if zeros else ""
            lines.append(f"{badge} **{r['src']}** · {asof or '—'} "
                         f"({_age_txt(a)}) · {cnt}{ztxt}")
        st.markdown("\n\n".join(lines))
        st.caption("🟢 신선 · 🟡 지연 또는 일부 0건(샘플 폴백) · 🔴 없음·실패 — "
                   "0건 항목은 수집이 실패해도 화면엔 샘플이 떠서 안 보일 수 있으니 "
                   "여기서 확인하세요. (10분 캐시)")


# ── 탭 ──
_inject_countup()
top_stock, top_re = st.tabs(["주식", "부동산"])

with top_stock:
    tab_idx, tab_rep, tab_ldr, tab_ipo, tab_kw  = st.tabs(["지수", "시황", "주도주", "IPO", "키워드"])
    with tab_idx:
        render_indices()
    with tab_rep:
        render_report_tab()
    with tab_ldr:
        render_leaders()
    with tab_ipo:
        render_ipo_tab()    
    with tab_kw:
        render_keywords()
        st.divider()
        render_watchlist_tab()


with top_re:
    from modules.realestate import render_realestate
    render_realestate()


# ── 수집 상태 패널: 페이지 최하단(모든 탭 콘텐츠 아래)에 배치 ──
# 탭 with 블록 바깥 최상위에 두어, 어느 탭을 보든 본문 맨 아래에 접힌 채로 표시된다.
_render_status_panel()
