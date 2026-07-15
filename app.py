"""시장 현황 대시보드 - Streamlit 메인 앱 (라이트 단일 테마, 통일 헤더)."""
 
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
 
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
from modules.usage import total_cost_usd
from modules.ticker_tape import render_ticker_tape
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
  /* 섹션 색 (A안 · 2026-07) — 상위 탭(주식/부동산)에 고유색을 주고 하위 탭·3단 탭이
     같은 색조를 상속해 위계를 만든다. 주식=기존 브랜드 세이지 유지, 부동산=클레이(흙·벽돌).
     부동산에 적색 계열을 쓰지 않는 이유: --up(#B65F5A)/--down(#5A7CA0) 시맨틱과 충돌. */
  --stk:#7E9A83; --stk-soft:#A7BBA9; --stk-tint:#EEF3EF; --stk-line:#E1E8E2;
  --re:#B08268;  --re-soft:#C9A48D;  --re-tint:#F6EEE8;  --re-line:#EDDFD4;
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
/* ===== 세그먼트 필 탭 (옵션 B) — 상단=흰 카드 토글 / 하위(중첩)=세이지 필 ===== */
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] { display:none !important; height:0 !important; background:transparent !important; }
/* 콘텐츠 탭(모듈 내부 st.tabs — 부동산 사이클/지도/실거래/분양/테마 등): 세이지 필 세그먼트 바.
   상단 주식·부동산, 주식·부동산 하위탭은 st.segmented_control(lazy)로 분리됨(아래 별도 규칙). */
.stTabs [data-baseweb="tab-list"] {
  gap:3px; flex-wrap:wrap; width:fit-content; max-width:100%;
  background:#F4F6F1; border:1px solid #ECEDE7; border-radius:12px;
  padding:4px; margin-bottom:12px;
}
.stTabs [data-baseweb="tab"] {
  white-space:nowrap; height:auto; min-width:max-content;
  padding:9px 16px; border-radius:9px; background:transparent;
  color:#9a9b92; transition:background .18s,color .18s,box-shadow .18s;
}
.stTabs [data-baseweb="tab"] p { font-size:13.5px; font-weight:700; margin:0; white-space:nowrap; color:inherit; }
.stTabs [data-baseweb="tab"]:hover p { color:#34352f; }
.stTabs [data-baseweb="tab"][aria-selected="true"] { background:#7E9A83; box-shadow:0 2px 6px -1px rgba(126,154,131,.45); }
.stTabs [data-baseweb="tab"][aria-selected="true"] p { color:#FFFFFF; }
.stTabs [data-baseweb="tab"][aria-selected="true"]:hover p { color:#FFFFFF; }
/* 더 깊은 중첩 탭(예: 실거래 안 특이거래/시총/주목단지): 동일 세이지 필 유지 */
[data-baseweb="tab-panel"] [data-baseweb="tab-list"] {
  gap:3px; background:#F4F6F1; border:1px solid #ECEDE7; border-radius:12px;
  padding:4px; margin-bottom:12px;
}
[data-baseweb="tab-panel"] [data-baseweb="tab"] { padding:9px 16px; }
[data-baseweb="tab-panel"] [data-baseweb="tab"] p { font-size:13.5px; }
[data-baseweb="tab-panel"] [data-baseweb="tab"][aria-selected="true"] { background:#7E9A83; box-shadow:0 2px 6px -1px rgba(126,154,131,.45); }
[data-baseweb="tab-panel"] [data-baseweb="tab"][aria-selected="true"] p { color:#FFFFFF; }
[data-baseweb="tab-panel"] [data-baseweb="tab"][aria-selected="true"]:hover p { color:#FFFFFF; }
/* ===== lazy 탭 (st.segmented_control 리스타일 — 선택 탭만 렌더) ===== */
/* 상단 섹션(주식/부동산) — 섹션색 채움 (A안 · 목업 정합 2026-07 재작업)
   목업: 컨테이너 없이 독립 카드 버튼 2개 — 활성=섹션색 채움+흰 글자,
   비활성=흰 카드+라인 테두리. 활성 필 색은 섹션에 따라 달라지는데 Streamlit은
   body에 클래스를 못 붙인다 → 선택값을 읽어 런타임 오버라이드를 주입한다(아래).
   여기 값은 주식(기본·세이지) 기준. */
.st-key-top_section div[data-testid="stSegmentedControl"] [role="radiogroup"],
.st-key-top_section div[data-testid="stSegmentedControl"] > div {
  display:inline-flex; gap:8px; background:transparent; border:none;
  border-radius:0; padding:0; flex-wrap:wrap;
}
.st-key-top_section div[data-testid="stSegmentedControl"] button {
  border:1px solid var(--line) !important; background:#FFFFFF !important;
  box-shadow:none !important;
  color:#5d6258 !important; font-weight:700 !important; padding:9px 20px !important;
  border-radius:12px !important; min-height:0 !important; transition:all .18s ease;
}
.st-key-top_section div[data-testid="stSegmentedControl"] button p { font-weight:700 !important; font-size:14px !important; margin:0 !important; }
.st-key-top_section div[data-testid="stSegmentedControl"] button:hover { color:#34352f !important; }
.st-key-top_section div[data-testid="stSegmentedControl"] button[aria-checked="true"],
.st-key-top_section div[data-testid="stSegmentedControl"] button[kind="segmented_controlActive"],
.st-key-top_section div[data-testid="stSegmentedControl"] button[data-testid="stBaseButton-segmented_controlActive"] {
  background:var(--stk) !important; border-color:var(--stk) !important;
  color:#FFFFFF !important;
  box-shadow:0 2px 7px -1px rgba(126,154,131,.5) !important;
}
.st-key-top_section div[data-testid="stSegmentedControl"] button[aria-checked="true"] p,
.st-key-top_section div[data-testid="stSegmentedControl"] button[kind="segmented_controlActive"] p,
.st-key-top_section div[data-testid="stSegmentedControl"] button[data-testid="stBaseButton-segmented_controlActive"] p { color:#FFFFFF !important; }
/* 2단 메인 탭 — 언더라인 (A안 목업 정합 · 2026-07 재작업):
   주식(시장/글로벌/브리핑/종목/테마) + 부동산(사이클/지도/실거래/분양/테마).
   목업: 필 컨테이너 대신 콘텐츠 폭 베이스라인 위에 텍스트 탭 — 활성은
   섹션색 언더라인(2.5px) + 잉크 텍스트, 비활성은 뮤트. 아이콘은 목업대로 숨김.
   키 stock_subtab2/re_maintab2 유지(세션 충돌 방지 원칙). */
.st-key-stock_subtab2 div[data-testid="stSegmentedControl"] [role="radiogroup"],
.st-key-stock_subtab2 div[data-testid="stSegmentedControl"] > div,
.st-key-re_maintab2 div[data-testid="stSegmentedControl"] [role="radiogroup"],
.st-key-re_maintab2 div[data-testid="stSegmentedControl"] > div {
  display:flex; width:100%; gap:2px; background:transparent; border:none;
  border-bottom:1.5px solid var(--line); border-radius:0; padding:0; flex-wrap:wrap;
}
.st-key-stock_subtab2 div[data-testid="stSegmentedControl"] button,
.st-key-re_maintab2 div[data-testid="stSegmentedControl"] button {
  border:0 !important; background:transparent !important; box-shadow:none !important;
  color:#9a9b92 !important; font-weight:700 !important; padding:9px 14px 10px !important;
  border-radius:8px 8px 0 0 !important; min-height:0 !important;
  border-bottom:2.5px solid transparent !important; margin-bottom:-1.5px !important;
  transition:color .18s ease,border-color .18s ease,background .18s ease;
}
.st-key-stock_subtab2 div[data-testid="stSegmentedControl"] button p,
.st-key-re_maintab2 div[data-testid="stSegmentedControl"] button p { font-weight:700 !important; font-size:13.5px !important; margin:0 !important; }
.st-key-stock_subtab2 div[data-testid="stSegmentedControl"] button:hover { color:#34352f !important; background:var(--stk-tint) !important; }
.st-key-re_maintab2 div[data-testid="stSegmentedControl"] button:hover { color:#34352f !important; background:var(--re-tint) !important; }
/* 활성 — 섹션색 언더라인 + 잉크 텍스트 (주식=세이지 / 부동산=클레이) */
.st-key-stock_subtab2 div[data-testid="stSegmentedControl"] button[aria-checked="true"],
.st-key-stock_subtab2 div[data-testid="stSegmentedControl"] button[kind="segmented_controlActive"],
.st-key-stock_subtab2 div[data-testid="stSegmentedControl"] button[data-testid="stBaseButton-segmented_controlActive"] {
  background:transparent !important; box-shadow:none !important;
  border-bottom-color:var(--stk) !important;
}
.st-key-re_maintab2 div[data-testid="stSegmentedControl"] button[aria-checked="true"],
.st-key-re_maintab2 div[data-testid="stSegmentedControl"] button[kind="segmented_controlActive"],
.st-key-re_maintab2 div[data-testid="stSegmentedControl"] button[data-testid="stBaseButton-segmented_controlActive"] {
  background:transparent !important; box-shadow:none !important;
  border-bottom-color:var(--re) !important;
}
.st-key-stock_subtab2 div[data-testid="stSegmentedControl"] button[aria-checked="true"] p,
.st-key-stock_subtab2 div[data-testid="stSegmentedControl"] button[kind="segmented_controlActive"] p,
.st-key-stock_subtab2 div[data-testid="stSegmentedControl"] button[data-testid="stBaseButton-segmented_controlActive"] p,
.st-key-re_maintab2 div[data-testid="stSegmentedControl"] button[aria-checked="true"] p,
.st-key-re_maintab2 div[data-testid="stSegmentedControl"] button[kind="segmented_controlActive"] p,
.st-key-re_maintab2 div[data-testid="stSegmentedControl"] button[data-testid="stBaseButton-segmented_controlActive"] p { color:#34352f !important; }
/* 탭 아이콘(:material/…) — 상위 탭만 유지(목업), 2단은 텍스트 온리라 숨김 */
.st-key-top_section div[data-testid="stSegmentedControl"] button span[data-testid="stIconMaterial"] { font-size:17px; color:inherit; }
.st-key-stock_subtab2 div[data-testid="stSegmentedControl"] button span[data-testid="stIconMaterial"],
.st-key-re_maintab2 div[data-testid="stSegmentedControl"] button span[data-testid="stIconMaterial"] { display:none !important; }
/* 모바일(≤640px): 아이콘까지 붙으면 서브탭(주식 5개·부동산 4개)이 두 줄로 밀린다.
   아이콘을 숨기고 버튼을 flex 균등분할(full-width)해 한 행에 딱 맞춘다 — 데스크톱은 아이콘 유지. */
@media (max-width:640px){
  .st-key-stock_subtab2 div[data-testid="stSegmentedControl"] [role="radiogroup"],
  .st-key-stock_subtab2 div[data-testid="stSegmentedControl"] > div,
  .st-key-re_maintab2 div[data-testid="stSegmentedControl"] [role="radiogroup"],
  .st-key-re_maintab2 div[data-testid="stSegmentedControl"] > div {
    display:flex !important; width:100%; gap:0; flex-wrap:nowrap; padding:0;
  }
  .st-key-stock_subtab2 div[data-testid="stSegmentedControl"] button,
  .st-key-re_maintab2 div[data-testid="stSegmentedControl"] button {
    flex:1 1 0 !important; min-width:0 !important; padding:8px 2px 9px !important;
    justify-content:center !important; text-align:center;
  }
  .st-key-stock_subtab2 div[data-testid="stSegmentedControl"] button p,
  .st-key-re_maintab2 div[data-testid="stSegmentedControl"] button p { font-size:12.5px !important; }
}
/* 3단(최하위) 탭 — 고스트 언더라인 (B안): 종목(주도주|공모주)·실거래 보기(시세 지도|지역 급지|주목 단지)·
   브리핑 장전|장마감. 필 컨테이너를 없애고 텍스트+밑줄만 남겨 2단(세이지 필)보다 위계를 한 단계 낮춘다. */
.st-key-stock_kind div[data-testid="stSegmentedControl"] [role="radiogroup"],
.st-key-stock_kind div[data-testid="stSegmentedControl"] > div,
.st-key-re_dealtab2 div[data-testid="stSegmentedControl"] [role="radiogroup"],
.st-key-re_dealtab2 div[data-testid="stSegmentedControl"] > div,
.st-key-rpt_kind_seg div[data-testid="stSegmentedControl"] [role="radiogroup"],
.st-key-rpt_kind_seg div[data-testid="stSegmentedControl"] > div {
  display:inline-flex; gap:16px; background:transparent; border:none;
  border-radius:0; padding:0; flex-wrap:wrap;
}
.st-key-stock_kind div[data-testid="stSegmentedControl"] button,
.st-key-re_dealtab2 div[data-testid="stSegmentedControl"] button,
.st-key-rpt_kind_seg div[data-testid="stSegmentedControl"] button {
  border:0 !important; background:transparent !important; box-shadow:none !important;
  color:#9a9b92 !important; padding:3px 2px 7px !important; border-radius:0 !important;
  border-bottom:2px solid transparent !important; min-height:0 !important;
  transition:color .18s ease,border-color .18s ease;
}
.st-key-stock_kind div[data-testid="stSegmentedControl"] button p,
.st-key-re_dealtab2 div[data-testid="stSegmentedControl"] button p,
.st-key-rpt_kind_seg div[data-testid="stSegmentedControl"] button p { font-weight:700 !important; font-size:12.5px !important; margin:0 !important; }
.st-key-stock_kind div[data-testid="stSegmentedControl"] button:hover,
.st-key-re_dealtab2 div[data-testid="stSegmentedControl"] button:hover,
.st-key-rpt_kind_seg div[data-testid="stSegmentedControl"] button:hover { color:#34352f !important; }
.st-key-stock_kind div[data-testid="stSegmentedControl"] button[aria-checked="true"],
.st-key-stock_kind div[data-testid="stSegmentedControl"] button[kind="segmented_controlActive"],
.st-key-stock_kind div[data-testid="stSegmentedControl"] button[data-testid="stBaseButton-segmented_controlActive"],
.st-key-re_dealtab2 div[data-testid="stSegmentedControl"] button[aria-checked="true"],
.st-key-re_dealtab2 div[data-testid="stSegmentedControl"] button[kind="segmented_controlActive"],
.st-key-re_dealtab2 div[data-testid="stSegmentedControl"] button[data-testid="stBaseButton-segmented_controlActive"],
.st-key-rpt_kind_seg div[data-testid="stSegmentedControl"] button[aria-checked="true"],
.st-key-rpt_kind_seg div[data-testid="stSegmentedControl"] button[kind="segmented_controlActive"],
.st-key-rpt_kind_seg div[data-testid="stSegmentedControl"] button[data-testid="stBaseButton-segmented_controlActive"] {
  background:transparent !important; box-shadow:none !important;
  border-bottom:2px solid var(--stk-soft) !important; color:var(--stk) !important;
}
/* 3단도 섹션색 상속 — 실거래 보기(부동산)만 클레이로 덮어쓴다 */
.st-key-re_dealtab2 div[data-testid="stSegmentedControl"] button[aria-checked="true"],
.st-key-re_dealtab2 div[data-testid="stSegmentedControl"] button[kind="segmented_controlActive"],
.st-key-re_dealtab2 div[data-testid="stSegmentedControl"] button[data-testid="stBaseButton-segmented_controlActive"] {
  border-bottom-color:var(--re-soft) !important; color:var(--re) !important;
}
.st-key-stock_kind div[data-testid="stSegmentedControl"] button[aria-checked="true"] p,
.st-key-stock_kind div[data-testid="stSegmentedControl"] button[kind="segmented_controlActive"] p,
.st-key-stock_kind div[data-testid="stSegmentedControl"] button[data-testid="stBaseButton-segmented_controlActive"] p,
.st-key-re_dealtab2 div[data-testid="stSegmentedControl"] button[aria-checked="true"] p,
.st-key-re_dealtab2 div[data-testid="stSegmentedControl"] button[kind="segmented_controlActive"] p,
.st-key-re_dealtab2 div[data-testid="stSegmentedControl"] button[data-testid="stBaseButton-segmented_controlActive"] p,
.st-key-rpt_kind_seg div[data-testid="stSegmentedControl"] button[aria-checked="true"] p,
.st-key-rpt_kind_seg div[data-testid="stSegmentedControl"] button[kind="segmented_controlActive"] p,
.st-key-rpt_kind_seg div[data-testid="stSegmentedControl"] button[data-testid="stBaseButton-segmented_controlActive"] p { color:var(--stk) !important; }
.st-key-re_dealtab2 div[data-testid="stSegmentedControl"] button[aria-checked="true"] p,
.st-key-re_dealtab2 div[data-testid="stSegmentedControl"] button[kind="segmented_controlActive"] p,
.st-key-re_dealtab2 div[data-testid="stSegmentedControl"] button[data-testid="stBaseButton-segmented_controlActive"] p { color:var(--re) !important; }
.stButton > button { border-radius:9px; padding:6px 16px; font-weight:600; }
.stButton { margin-bottom:4px; }
[data-testid="stExpander"] { border-radius:10px; margin-bottom:8px; }
.app-name { font-family:'Fraunces','Noto Sans KR',serif; font-size:18px; font-weight:600; color:var(--ink); }
.app-upd { font-size:11.5px; color:var(--muted); }
.accent-bar { height:3px; width:30px; background:var(--sage); border-radius:3px; margin:0 0 12px; }
.mkt-group { font-size:12px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); margin:12px 0 9px; }  /* C4: 16→12 */
.grp-asof { font-weight:600; font-size:10.5px; letter-spacing:0; text-transform:none; color:var(--muted); opacity:.8; margin-left:8px; }
.grp-divider { border:none; border-top:1px solid var(--line); margin:18px 0 0; }  /* C4: 22→18 */
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

# 각주 배지(A안) 공용 스타일 — ui.foot_badge를 쓰는 모든 탭에서 공유(1회 주입).
from modules.ui import FOOT_CSS, foot_badge, tab_header  # noqa: E402
st.markdown(FOOT_CSS, unsafe_allow_html=True)
 
# ── 상단 헤더 — 배너 클릭 = '오늘의 한 장'(주식 > 시장)으로 ──
# 순수 HTML은 세션을 바꿀 수 없으므로 표준 '로고=홈' 패턴(앱 루트 링크)을 쓴다.
# 리로드 시 기본 탭이 주식 > 시장이라 정확히 오늘의 한 장에 착지한다.
now = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")
st.markdown(
    '<style>.app-home,.app-home:hover,.app-home:visited{text-decoration:none !important;color:inherit;display:inline-block;}'
    '.app-home .app-name{transition:color .15s ease;}'
    '.app-home:hover .app-name{color:var(--sage-deep,#7E9A83);}</style>'
    '<a class="app-home" href="./" target="_self" title="오늘의 한 장으로">'
    '<div class="app-name">DY Monitoring</div></a>'
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
 
 
# ── 히트맵 타일 색 (A안: 틴트 상한) ──
_HEAT_TINT_CAP = 0.38   # 배경 틴트 최대 비율 — 미니멀 미스트 톤 유지(고채도 배경 금지)


def _heat_color(pct):
    """타일 색 3요소: (배경, 본문색, 등락색).

    배경 = 등락률(±3%에서 최대)에 비례한 up/down 틴트를 _HEAT_TINT_CAP까지만 블렌드.
    본문(이름·값) = 항상 잉크(#34352f) — 흰 글자 반전 없음.
    등락색 = %(pct) 텍스트에만 적용해 강조를 한 겹으로 유지(보합·None은 뮤트)."""
    ink, muted = "#34352f", "#9a9b92"
    if pct is None:
        return "#F6F7F2", ink, muted
    t = max(-1.0, min(1.0, pct / 3.0))
    base = (246, 247, 242)
    up = (182, 95, 90)
    down = (90, 124, 160)
    tgt = up if t >= 0 else down
    k = abs(t) * _HEAT_TINT_CAP
    r = round(base[0] + (tgt[0] - base[0]) * k)
    g = round(base[1] + (tgt[1] - base[1]) * k)
    b = round(base[2] + (tgt[2] - base[2]) * k)
    pct_col = "#B65F5A" if pct > 0 else ("#5A7CA0" if pct < 0 else muted)
    return f"rgb({r},{g},{b})", ink, pct_col
 
 
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
        bg, txt, pct_col = _heat_color(pct)
        arrow = "▲" if d["change"] > 0 else ("▼" if d["change"] < 0 else "▬")
 
        # 3개월 미니차트 (하단 보름 눈금 + 월 라벨) — 뮤트 톤(장식 레이어, 등락색과 분리)
        spark = ""
        series = histories.get(name)
        if series is not None and len(series) >= 2:
            spark = sparkline_axis_html(series, "#9a9b92", height=38, n_days=92,
                                        label_color="#9a9b92")
 
        tiles += (
            f'<div class="heat-tile" style="background:{bg};">'
            f'<div class="heat-name" style="color:{txt};opacity:.92;">{name}</div>'
            f'<div class="heat-val" style="color:{txt};">{d["current"]:,.2f}</div>'
            f'<div class="heat-pct" style="color:{pct_col};">{arrow} {pct:+.2f}%</div>'
            f'{spark}'
            f'</div>'
        )
    return f'<div class="mkt-grid">{tiles}</div>'
 
 
# ── 국내 지수 대형 차트 ──
_KRX_PERIODS = {"1일": 1, "1개월": 31, "3개월": 92, "6개월": 183, "1년": 366}
 
 
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
    # 기간 선택 UI를 IPO 탭과 동일한 세그먼트로 통일(C3) — 구버전 Streamlit이면
    # 기존 라디오로 폴백. 위젯 타입이 바뀌므로 세션 키도 교체(구 캐시 충돌 방지 원칙).
    _plist = list(_KRX_PERIODS.keys())
    if hasattr(st, "segmented_control"):
        period_label = st.segmented_control(
            "조회 기간", _plist, default="6개월",
            key="krx_chart_period2", label_visibility="collapsed") or "6개월"
    else:
        period_label = st.radio(
            "조회 기간", _plist, index=3, horizontal=True,
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
    # 조작·범례 안내는 '코스피 · 코스닥' 헤더의 ⓘ 배지로 이동(A안) — 하단 각주 제거.
 
 
# ── 지수 스냅샷 공용 헬퍼 (시장/글로벌 탭 분리 후 양쪽에서 사용 · 2026-07 탭 개편) ──
def _group_snapshots(groups):
    """지정한 지수 그룹만 로드 — lazy 탭에서 다른 탭 몫의 그룹까지 fetch하지 않는다."""
    group_data, group_asof = {}, {}
    for group_name in groups:
        tickers = INDEX_GROUPS.get(group_name)
        if not tickers:
            continue
        datas = {name: fetch_index(t) for name, t in tickers.items()}
        group_data[group_name] = datas
        asofs = [d["asof"] for d in datas.values() if d and d.get("asof")]
        group_asof[group_name] = max(asofs) if asofs else None
    distinct = {a for a in group_asof.values() if a}
    unified = len(distinct) == 1
    return group_data, group_asof, unified, distinct


def _histories(group):
    """3개월 히스토리 수집 (히트맵 미니차트용 · fetch_history 3600s 캐시 → 추가 비용 없음)"""
    out = {}
    for item_name, ticker in INDEX_GROUPS.get(group, {}).items():
        try:
            hist = fetch_history(ticker, "3mo")
            if hist is not None and len(hist) >= 2:
                out[item_name] = hist
        except Exception:
            pass
    return out


def _heat_group(group, group_data, group_asof, unified, divider=True):
    # divider=False: 섹션 배너 바로 아래 첫 그룹 — 배너+구분선 이중 여백 제거(C4).
    if divider:
        st.markdown('<hr class="grp-divider">', unsafe_allow_html=True)
    head = f'<div class="mkt-group">{group}'
    if not unified and group_asof.get(group):
        head += f'<span class="grp-asof">기준 {group_asof[group]}</span>'
    head += "</div>"
    st.markdown(head, unsafe_allow_html=True)
    st.markdown(_heat_html(group_data[group], _histories(group)),
                unsafe_allow_html=True)


# ── 시장 탭 본문 — 국내 증시 · 시장 심리 (글로벌/외환·금리→글로벌 탭, 일정→브리핑 탭) ──
def _render_indices_body():
    _, group_asof, unified, distinct = _group_snapshots(["국내"])
    if unified and distinct:
        st.markdown(
            f'<div class="data-asof">데이터 기준 {next(iter(distinct))}</div>',
            unsafe_allow_html=True)
 
    # ══════════════════ 1. 국내 증시 ══════════════════
    st.markdown('<div class="sect-banner" id="sec-krx">국내 증시</div>', unsafe_allow_html=True)
    krx_head = '<div class="mkt-group ui-fx">코스피 · 코스닥'
    if not unified and group_asof.get("국내"):
        krx_head += f'<span class="grp-asof">기준 {group_asof["국내"]}</span>'
    krx_head += foot_badge(
        "Yahoo Finance · 약 15분 지연",
        "일별 차트: 마우스 hover=십자선으로 시점·값 표시, 가로 스크롤·드래그=기간 확대 · "
        "당일(1일) 차트: 5분봉·전일 종가 대비 등락(회색 점선=전일 종가)·정규장(09:00~15:30)만 "
        "표시되며 일부 누락될 수 있어요")
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
    st.markdown('<div class="sect-banner" id="sec-mood">시장 심리</div>', unsafe_allow_html=True)
    render_indicators()


# ── 글로벌 탭 본문 — 글로벌 지수 · 외환·금리 (시장 탭에서 분리 · 2026-07 탭 개편) ──
_GLOBAL_GROUPS = ("미국", "변동성·원자재", "암호화폐", "환율")


def _render_global_body():
    group_data, group_asof, unified, distinct = _group_snapshots(list(_GLOBAL_GROUPS))
    if unified and distinct:
        st.markdown(
            f'<div class="data-asof">데이터 기준 {next(iter(distinct))} · '
            f'해외 지수·환율은 직전 거래일 종가</div>', unsafe_allow_html=True)
 
    # ══════════════════ 1. 글로벌 지수 ══════════════════
    st.markdown(
        '<div class="sect-banner ui-fx" id="sec-global">글로벌 지수'
        + foot_badge(
            "Yahoo Finance · 종가",
            "🌡️ 히트맵 · 타일 색 = 등락률의 은은한 틴트(빨강 상승 / 파랑 하락, ±3%에서 최대) · "
            "미니차트 = 3개월 추이(하단 눈금 = 보름)")
        + '</div>', unsafe_allow_html=True)
    _first = True
    for g in ("미국", "변동성·원자재", "암호화폐"):
        if g in group_data:
            _heat_group(g, group_data, group_asof, unified, divider=not _first)
            _first = False
 
    # ══════════ 1.5 미국 전일 시장 — 업종·시총 Top50·이슈 종목(엔진 usmkt) ══════════
    #   엔진(engine.usmkt_run · 07:20/08:20 KST)이 저장한 스냅샷만 읽는다.
    #   스냅샷이 없으면 render_us_market()이 조용히 생략 → 기존 화면 무회귀.
    st.markdown('<hr class="grp-divider">', unsafe_allow_html=True)
    from modules.us_market import render_us_market
    render_us_market()

    # ══════════════════ 2. 외환 · 금리 ══════════════════
    st.markdown('<hr class="grp-divider">', unsafe_allow_html=True)
    st.markdown('<div class="sect-banner" id="sec-fx">외환 · 금리</div>', unsafe_allow_html=True)
    if "환율" in group_data:
        _heat_group("환율", group_data, group_asof, unified, divider=False)
 
    st.markdown('<hr class="grp-divider">', unsafe_allow_html=True)
    from modules.rates import render_rates
    render_rates()
 
    st.markdown('<hr class="grp-divider">', unsafe_allow_html=True)
    from modules.rate_gap import render_rate_gap
    render_rate_gap()
 
 
# ── 시장 탭 '오늘의 한 장' + 섹션 점프 내비 ──
# v2 2블록 — ①헤드라인 밴드(보고서 무드·헤드라인·지표 칩) ②시그널 카드(topics 중요도 상위 3).
# (매크로 스파인·합의/이견 블록은 중복/과밀로 제거. 합의·이견은 브리핑 탭에서 확인.)
# 기존 보고서 데이터만 재사용하므로 추가 AI 호출 0. 브리핑 rpt-tldr와 동일한 시각 문법
# (좌측 세이지 액센트·Fraunces 헤드라인·무드 배지)을 공유한다.
_MKT_SECTIONS = [("국내 증시", "sec-krx"), ("시장 심리", "sec-mood")]
# (글로벌 지수·외환·금리는 '글로벌' 탭, 일정은 '브리핑' 탭으로 이동 — 2026-07 탭 개편)

_MKT_HEAD_CSS = """
<style>
.mkt-head{background:#fff;border:1px solid var(--line,#ECEDE7);border-left:4px solid var(--sage,#A7BBA9);
  border-radius:0 16px 16px 0;padding:14px 18px 13px;margin:2px 0 8px;}
.mkt-head .top{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin-bottom:7px;}
.mkt-head .meta{font-size:11px;font-weight:600;color:var(--muted,#9a9b92);}
.mkt-head .hl{font-family:'Fraunces','Noto Sans KR',serif;font-size:17px;font-weight:600;line-height:1.45;
  letter-spacing:-.01em;color:var(--ink,#34352f);}
.mkt-head .chips{display:flex;gap:7px;flex-wrap:wrap;margin-top:9px;}
.mkt-head .chip{display:inline-flex;align-items:baseline;gap:5px;background:var(--summary-bg,#F6F7F2);
  border:1px solid var(--line,#ECEDE7);border-radius:9px;padding:4px 10px;font-size:11px;
  font-weight:600;color:var(--pill-ink,#5d6258);white-space:nowrap;}
.mkt-head .chip b{font-size:11.5px;font-weight:700;}
.mkt-head .chip b.u{color:var(--up,#B65F5A);}
.mkt-head .chip b.d{color:var(--down,#5A7CA0);}
.mkt-head .chip b.n{color:var(--ink,#34352f);}
.mkh-badge{font-size:10px;font-weight:700;letter-spacing:.06em;padding:3px 10px;border-radius:20px;display:inline-block;}
__MKH_MOOD__
.mkt-nav{display:flex;gap:7px;flex-wrap:wrap;margin:0 0 4px;}
.mkt-nav a{font-size:12px;font-weight:700;color:var(--pill-ink,#5d6258);text-decoration:none;
  background:var(--summary-bg,#F6F7F2);border:1px solid var(--line,#ECEDE7);border-radius:9px;padding:6px 12px;
  transition:color .15s ease,border-color .15s ease;}
.mkt-nav a:hover{color:var(--sage-deep,#7E9A83);border-color:var(--sage,#A7BBA9);}
/* 오늘의 한 장 — 블록 라벨·시그널 카드 */
.mkt-head .moods{display:inline-flex;align-items:center;gap:6px;}
.mkt-head .moods .ar{color:var(--muted,#9a9b92);font-size:11px;font-weight:700;}
/* 결론 스트립 — 국면 · 주도 섹터 · 내일 관전 (오늘의 한 장 v2.1) */
.op-strip{display:flex;gap:9px;flex-wrap:wrap;margin:9px 0 0;}
.op-cell{display:flex;align-items:baseline;gap:7px;background:#fff;border:1px solid var(--line,#ECEDE7);
  border-radius:12px;padding:8px 12px;min-width:0;}
.op-cell .k{font-size:9.5px;font-weight:700;letter-spacing:.08em;color:var(--muted,#9a9b92);white-space:nowrap;}
.op-cell .v{font-size:12px;font-weight:700;color:var(--ink,#34352f);}
.op-cell.ph .v{color:var(--sage-deep,#7E9A83);}
.op-cell.watch{flex:1 1 240px;}
.op-cell.watch .v{font-weight:600;font-size:11.5px;line-height:1.55;color:var(--pill-ink,#5d6258);
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.op-lab{font-size:10px;font-weight:700;letter-spacing:.09em;color:var(--muted,#9a9b92);margin:13px 0 7px;}
.op-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;}
.op-card{background:#fff;border:1px solid var(--line,#ECEDE7);border-radius:14px;padding:12px 13px;}
.op-card .top{display:flex;justify-content:space-between;align-items:baseline;gap:8px;}
.op-card .rk{font-family:'Fraunces','Noto Sans KR',serif;font-size:15px;color:var(--sage-deep,#7E9A83);}
.op-card .imp{font-size:9.5px;font-weight:700;color:var(--muted,#9a9b92);background:var(--summary-bg,#F6F7F2);border-radius:7px;padding:2px 7px;white-space:nowrap;}
.op-card .t{font-size:12.5px;font-weight:700;color:var(--ink,#34352f);line-height:1.4;margin:5px 0 6px;}
.op-card .d{font-size:11px;color:var(--muted,#9a9b92);line-height:1.55;}
.op-card .stk{display:flex;gap:5px;flex-wrap:wrap;margin-top:8px;}
.op-card .stk span{font-size:10px;font-weight:600;color:var(--pill-ink,#5d6258);background:var(--summary-bg,#F6F7F2);border:1px solid var(--line,#ECEDE7);border-radius:7px;padding:2px 7px;}
/* 모바일: 시그널 카드는 상위 2개만(3번째 이후 숨김) — 세로 스크롤 절약 */
@media (max-width:640px){ .op-cards .op-card:nth-child(n+3){display:none;} }
/* 앵커 점프 시 섹션 배너가 화면 최상단에 붙지 않도록 여유 + 부드러운 스크롤 */
.sect-banner{scroll-margin-top:4.2rem;}
html{scroll-behavior:smooth;}
/* '브리핑에서 자세히' 버튼 — 링크 톤으로 축소 */
.st-key-mkt_to_brief button{background:transparent !important;border:none !important;box-shadow:none !important;
  color:var(--sage-deep,#7E9A83) !important;font-size:12px !important;font-weight:700 !important;
  padding:0 2px !important;min-height:0 !important;}
.st-key-mkt_to_brief button:hover{color:var(--ink,#34352f) !important;text-decoration:underline;}
.st-key-mkt_to_brief button p{font-size:12px !important;font-weight:700 !important;margin:0 !important;}
</style>"""


@st.cache_data(ttl=600, show_spinner=False)
def _today_page_data():
    """'오늘의 한 장' 데이터 — 최신 일자 보고서(장마감 후 우선) + 같은 날 장전 무드.
    반환: {headline, mood, pre_mood, kind, date, snap, topics[≤3]}
    DB 미설정/보고서 없음/실패 시 None (블록을 조용히 생략)."""
    try:
        from modules.db import supabase_configured, list_recent
        if not supabase_configured():
            return None
        rows = list_recent(6) or []
        if not rows:
            return None
        r0 = rows[0]   # report_date desc → slug desc: 같은 날짜면 장마감 후 우선
        d0 = str(r0.get("report_date") or r0.get("slug", ""))[:10]
        data = r0.get("data") or {}
        headline = str(data.get("headline", "")).strip()
        if not headline:
            return None
        kind0 = data.get("report_kind") or r0.get("report_kind") or "post"
        kind0 = "pre" if kind0 == "pre" else "post"

        # 같은 날짜의 장전 보고서 무드 — ①블록 '장전→장후' 전환 표시용
        pre_mood = None
        if kind0 == "post":
            for r in rows[1:]:
                if str(r.get("report_date") or "")[:10] != d0:
                    break
                rd = r.get("data") or {}
                if (rd.get("report_kind") or r.get("report_kind")) == "pre":
                    pre_mood = rd.get("mood", "neutral")
                    break

        # ②블록: topics 상위 3 (analyze 단계에서 이미 importance 내림차순 정렬됨)
        # 전문 표시 — 카드 높이가 내용에 맞춰 자동으로 늘어나므로 하드 컷 없음.
        topics = []
        for t in (data.get("topics") or [])[:3]:
            if not isinstance(t, dict) or not str(t.get("title", "")).strip():
                continue
            impl = (str(t.get("implication", "")).strip()
                    or str(t.get("fact", "")).strip())
            topics.append({"title": str(t.get("title", "")).strip(),
                           "imp": t.get("importance"),
                           "impl": impl,
                           "stocks": [str(s).strip() for s in
                                      (t.get("stocks") or []) if str(s).strip()][:3]})

        # 결론 스트립: 장마감 후=outlook.post.tomorrow(내일 가설),
        # 장전=outlook.pre 상위 2개(오늘 볼 것) — analyze 스키마 그대로 재사용.
        ol = data.get("outlook") or {}
        if kind0 == "post":
            watch = str(((ol.get("post") or {}).get("tomorrow") or "")).strip()
            watch_label = "내일 관전"
        else:
            pre = [str(x).strip() for x in (ol.get("pre") or []) if str(x).strip()]
            watch = " · ".join(pre[:2])
            watch_label = "오늘 관전"

        return {"headline": headline,
                "mood": data.get("mood", "neutral"),
                "pre_mood": pre_mood,
                "kind": kind0,
                "date": d0,
                "snap": str(data.get("snapshot_line", "")).strip(),
                "watch": watch, "watch_label": watch_label,
                "topics": topics}
    except Exception:
        return None


@st.cache_data(ttl=900, show_spinner=False)
def _leaders_brief():
    """주도 섹터 한 줄 요약 {'sector','count'} — 결론 스트립용.
    leaders 스냅샷의 sectors[0](점수 1위)과 주도주 개수. 없음/실패 시 None."""
    try:
        from modules.db import supabase_configured, load_leaders
        if not supabase_configured():
            return None
        p = load_leaders() or {}
        secs = p.get("sectors") or []
        if not secs:
            return None
        sector = str(secs[0].get("upjong", "")).strip()
        if not sector:
            return None
        return {"sector": sector, "count": len(p.get("stocks") or [])}
    except Exception:
        return None


def _fmt_brief_date(iso: str) -> str:
    """'YYYY-MM-DD' → 'MM.DD(요일)'. 파싱 실패 시 원문 그대로."""
    try:
        from datetime import date as _d
        y, m, d = (int(x) for x in iso.split("-"))
        return f"{m:02d}.{d:02d}({'월화수목금토일'[_d(y, m, d).weekday()]})"
    except Exception:
        return iso


def _snap_chips_html(snap: str) -> str:
    """snapshot_line('코스피 8,088.34(+5.76%) · …') → 방향색 칩. 최대 5개."""
    import html as _html
    chips = ""
    for item in [s.strip() for s in snap.split("·") if s.strip()][:5]:
        lab, _, val = item.rpartition(" ")
        if not lab:                       # 공백 없는 항목은 통째로 라벨 취급
            lab, val = val, ""
        cls = "u" if "+" in val else ("d" if "-" in val else "n")
        val_html = f' <b class="{cls}">{_html.escape(val)}</b>' if val else ""
        chips += f'<span class="chip">{_html.escape(lab)}{val_html}</span>'
    return f'<div class="chips">{chips}</div>' if chips else ""


def _render_market_head():
    """시장 탭 '오늘의 한 장'(v2) — ①헤드라인 밴드(무드 전환)
    ②시그널 카드(topics 상위 3) + 브리핑 점프 + 섹션 내비.
    보고서가 없으면 내비만 그린다(결측 안내 없음)."""
    import html as _html
    from modules.mood import MOOD_KO, mood_css
    st.markdown(_MKT_HEAD_CSS.replace("__MKH_MOOD__", mood_css("mkh")),
                unsafe_allow_html=True)

    page = _today_page_data()

    # ① 헤드라인 밴드 — 무드(장전→장후 전환) + 날짜·종류 + 헤드라인 + 지표 칩
    if page:
        def _badge(m, prefix=""):
            cls = {"positive": "pos", "neutral": "neu",
                   "cautious": "cau"}.get(m, "neu")
            return (f'<span class="mkh-badge mkh-{cls}">'
                    f'{prefix}{MOOD_KO.get(m, "중립").upper()}</span>')
        if page["pre_mood"] and page["kind"] == "post":
            moods = ('<span class="moods">' + _badge(page["pre_mood"], "장전 ")
                     + '<span class="ar">→</span>'
                     + _badge(page["mood"], "장후 ") + '</span>')
        else:
            moods = _badge(page["mood"])
        kind_ko = "장전 보고서" if page["kind"] == "pre" else "장마감 후 보고서"
        st.markdown(
            f'<div class="mkt-head">'
            f'<div class="top">{moods}'
            f'<span class="meta">{_fmt_brief_date(page["date"])} · {kind_ko}</span></div>'
            f'<div class="hl">{_html.escape(page["headline"])}</div>'
            f'{_snap_chips_html(page["snap"])}'
            f'</div>', unsafe_allow_html=True)

    # ①.5 결론 스트립 — 국면(체온계) · 주도 섹터(leaders) · 내일/오늘 관전(outlook).
    # 세 소스 모두 기존 캐시 재사용이라 추가 비용 0 · 실패한 셀은 조용히 생략.
    strip = ""
    try:
        from modules.indicators import phase_brief
        ph = phase_brief()
    except Exception:
        ph = None
    if ph:
        strip += (f'<div class="op-cell ph"><span class="k">국면</span>'
                  f'<span class="v">{_html.escape(ph["phase"])}'
                  f' {ph["score"]:+.2f}</span></div>')
    lb = _leaders_brief()
    if lb:
        cnt = f' · 주도주 {lb["count"]}' if lb.get("count") else ""
        strip += (f'<div class="op-cell"><span class="k">주도 섹터</span>'
                  f'<span class="v">{_html.escape(lb["sector"])}{cnt}</span></div>')
    if page and page.get("watch"):
        strip += (f'<div class="op-cell watch">'
                  f'<span class="k">{_html.escape(page["watch_label"])}</span>'
                  f'<span class="v">{_html.escape(page["watch"])}</span></div>')
    if strip:
        st.markdown(f'<div class="op-strip">{strip}</div>', unsafe_allow_html=True)

    # ② 시그널 카드 — topics 상위 3 · implication 전문 + 종목 칩(높이 자동)
    if page and page["topics"]:
        cards = ""
        for i, t in enumerate(page["topics"], 1):
            imp = t.get("imp")
            imp_s = (f'<span class="imp">중요도 {int(imp)}</span>'
                     if isinstance(imp, (int, float)) else "")
            stk = "".join(f'<span>{_html.escape(s)}</span>' for s in t["stocks"])
            stk_html = f'<div class="stk">{stk}</div>' if stk else ""
            cards += (f'<div class="op-card">'
                      f'<div class="top"><span class="rk">{i}</span>{imp_s}</div>'
                      f'<div class="t">{_html.escape(t["title"])}</div>'
                      f'<div class="d">{_html.escape(t["impl"])}</div>'
                      f'{stk_html}</div>')
        st.markdown('<div class="op-lab">오늘의 시그널</div>'
                    f'<div class="op-cards">{cards}</div>', unsafe_allow_html=True)

    if page:
        if st.button("브리핑에서 자세히 →", key="mkt_to_brief"):
            st.session_state["_stock_subtab_jump"] = "브리핑"
            st.rerun()

    nav = "".join(f'<a href="#{aid}">{lab}</a>' for lab, aid in _MKT_SECTIONS)
    st.markdown(f'<div class="mkt-nav">{nav}</div>', unsafe_allow_html=True)


# ── 지수 현황 탭 ──
def render_indices():
    # 표준 크롬(tab_header) — 출처·지연 안내는 각 섹션 헤더의 ⓘ 배지에 있음(캡션 없음).
    # 헤더 + 새로고침(아이콘만) — 같은 줄 우측(A안 st.columns). 기존 '🔄 새로고침'
    # 글자 버튼(본문 중간)을 제거하고 헤더 우측 정사각 아이콘 버튼으로 승격.
    # ※ st.columns는 모바일에서 세로 적층이 기본 → keyed 컨테이너에 nowrap을 걸어
    #   좁은 화면에서도 [제목 | 🔄]이 한 줄을 유지하게 한다.
    st.markdown(
        '<style>'
        '.st-key-idx_head div[data-testid="stHorizontalBlock"]'
        '{flex-wrap:nowrap !important;align-items:center}'
        '.st-key-idx_head div[data-testid="stHorizontalBlock"]>div{min-width:0}'
        '.st-key-idx_refresh button{width:44px;height:40px;padding:0;'
        'border-radius:10px;font-size:16px;line-height:1}'
        '.st-key-idx_refresh{display:flex;justify-content:flex-end}'
        '</style>'
        '<div class="accent-bar"></div>', unsafe_allow_html=True)
    with st.container(key="idx_head"):
        _hcol, _bcol = st.columns([8, 1])
        with _hcol:
            st.title("주요 지수 현황")
        with _bcol:
            if st.button("🔄", key="idx_refresh", help="지수 데이터 새로고침"):
                st.cache_data.clear()
                st.rerun()

    # '오늘의 한 장' — 헤드라인·스파인·시그널·합의/이견 + 섹션 내비 (본문보다 먼저)
    _render_market_head()

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


# ── 글로벌 탭 (글로벌 지수 · 외환·금리 — 시장 탭에서 분리 · 2026-07 탭 개편) ──
def render_global():
    # 시장 탭과 동일한 표준 크롬: accent-bar + [제목 | 🔄] 한 줄 + 장중 자동 새로고침.
    # (환율·암호화폐는 국내 장중에도 움직이므로 시장 탭과 같은 fragment 주기를 공유한다.)
    st.markdown(
        '<style>'
        '.st-key-glb_head div[data-testid="stHorizontalBlock"]'
        '{flex-wrap:nowrap !important;align-items:center}'
        '.st-key-glb_head div[data-testid="stHorizontalBlock"]>div{min-width:0}'
        '.st-key-glb_refresh button{width:44px;height:40px;padding:0;'
        'border-radius:10px;font-size:16px;line-height:1}'
        '.st-key-glb_refresh{display:flex;justify-content:flex-end}'
        '</style>'
        '<div class="accent-bar"></div>', unsafe_allow_html=True)
    with st.container(key="glb_head"):
        _hcol, _bcol = st.columns([8, 1])
        with _hcol:
            st.title("글로벌 지수 · 외환 금리")
        with _bcol:
            if st.button("🔄", key="glb_refresh", help="지수 데이터 새로고침"):
                st.cache_data.clear()
                st.rerun()

    has_frag = hasattr(st, "fragment")
    market_open = is_kr_market_open()
    every = 600 if (has_frag and market_open) else None

    if market_open:
        st.caption("🟢 장중 자동 새로고침 켜짐 · 약 10분 주기 · 해외 지수는 직전 거래일 종가")
    else:
        st.caption("⏸ 장외 시간 · 다음 개장(평일 09:00 KST)부터 자동 새로고침이 작동해요.")

    if every:
        st.fragment(_render_global_body, run_every=every)()
    else:
        _render_global_body()


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

    # ── 일정 (시장 탭에서 이동 · 2026-07 탭 개편) — DART 실적발표·IR은 브리핑과 성격이 같다 ──
    st.markdown('<hr class="grp-divider">', unsafe_allow_html=True)
    st.markdown('<div class="sect-banner" id="sec-cal">일정</div>', unsafe_allow_html=True)
    render_calendar()

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


# ── 종목 탭 (주도주 | 공모주 — 같은 '개별 종목 발굴' 성격으로 통합 · 2026-07 탭 개편) ──
def render_stock_picks():
    """종목 탭 — 3단 고스트 언더라인 세그먼트(주도주|공모주)로 하위 뷰 전환.
    각 뷰가 자체 표준 크롬(tab_header)을 그리므로 여기서는 라우팅만 담당한다."""
    _kind = st.segmented_control(
        "종목 보기", ["주도주", "공모주"], default="주도주",
        key="stock_kind", label_visibility="collapsed",
    ) or "주도주"   # 선택 해제(None) 시 기본값으로 폴백
    if _kind == "공모주":
        render_ipo_tab()
    else:
        render_leaders()


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
 
 
# ── 자동 갱신 현황 패널 (실제 DB 갱신 시각 + cron 다음 예정) ───────────
#  각 소스의 '최근 갱신'은 Supabase updated_at(KST)에서, '다음 예정'은 워크플로
#  cron의 첫 슬롯에서 계산한다. GitHub cron 지연으로 실제 실행은 최대 1시간(주도주는
#  더) 늦을 수 있어, '예정'은 목표 시각이다.
from datetime import datetime as _dt, timezone as _tz, timedelta as _td
 
_KST_TZ = _tz(_td(hours=9))
_WD = ["월", "화", "수", "목", "금", "토", "일"]
 
# 소스별 '다음 예정' 첫 슬롯(KST). weekday=평일만. None=수동(예정 없음).
#  · 부동산/부동산 키워드 → realestate.yml 첫 슬롯 06:07
#  · 종목마스터 → stock_master.yml 첫 슬롯 06:20
#  · 공모주(IPO) → ipo.yml 14:00
#  · 주도주/증시 키워드 → leaders.yml 평일 첫 슬롯 16:40
#  · 시황 보고서 → 수동 전용
_SCHED = {
    "주도주":       {"h": 16, "m": 40, "weekday": True},
    "증시 키워드":  {"h": 16, "m": 40, "weekday": True},
    "공모주(IPO)":  {"h": 14, "m": 0,  "weekday": False},
    "시황 보고서":  None,
    "종목마스터":   {"h": 6,  "m": 20, "weekday": False},
    "부동산":       {"h": 6,  "m": 7,  "weekday": False},
    "부동산 키워드": {"h": 6,  "m": 7,  "weekday": False},
}
 
 
@st.cache_data(ttl=600, show_spinner=False)
def _collect_status():
    """소스별 최근 갱신(updated_at, KST iso)·카운트 수집(10분 캐시). 미설정이면 None."""
    from modules.db import (supabase_configured, last_updated_kst,
                            load_realestate, load_keywords_latest, list_recent,
                            load_leaders, load_ipo, load_realestate_keywords_latest)
    if not supabase_configured():
        return None
 
    def lu(table):
        dt = last_updated_kst(table)
        return dt.isoformat() if dt else None
 
    out = []
    # ── 증시 ──
    try:
        ld = load_leaders() or {}
        out.append({"src": "주도주", "last": lu("leaders"),
                    "counts": [("종목", len(ld.get("stocks") or [])),
                               ("섹터", len(ld.get("sectors") or []))],
                    "fallback": ["종목"]})
    except Exception as e:
        out.append({"src": "주도주", "error": str(e)[:80]})
    try:
        kw = load_keywords_latest() or {}
        out.append({"src": "증시 키워드", "last": lu("keywords"),
                    "counts": [("키워드", len(kw.get("items") or []))],
                    "fallback": ["키워드"]})
    except Exception as e:
        out.append({"src": "증시 키워드", "error": str(e)[:80]})
    try:
        ip = load_ipo() or {}
        out.append({"src": "공모주(IPO)", "last": lu("ipo_snapshots"),
                    "counts": [("최근", len(ip.get("recent") or [])),
                               ("예정", len(ip.get("upcoming") or []))]})
    except Exception as e:
        out.append({"src": "공모주(IPO)", "error": str(e)[:80]})
    try:
        rep = list_recent(1) or []
        out.append({"src": "시황 보고서", "last": lu("reports"),
                    "counts": [("최근행", len(rep))]})
    except Exception as e:
        out.append({"src": "시황 보고서", "error": str(e)[:80]})
    try:
        out.append({"src": "종목마스터", "last": lu("stock_master"), "counts": []})
    except Exception as e:
        out.append({"src": "종목마스터", "error": str(e)[:80]})
    # ── 부동산 ──
    try:
        r = load_realestate() or {}
        m = r.get("metrics") or {}
        out.append({"src": "부동산", "last": lu("realestate_snapshots"),
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
        rk = load_realestate_keywords_latest() or {}
        out.append({"src": "부동산 키워드", "last": lu("realestate_keywords"),
                    "counts": [("키워드", len(rk.get("items") or []))],
                    "fallback": ["키워드"]})
    except Exception as e:
        out.append({"src": "부동산 키워드", "error": str(e)[:80]})
    return out
 
 
def _fmt_last(iso, now):
    """최근 갱신 iso(KST) → '오늘 16:45' / '어제 07:03' / '6/29 16:45' / '없음'."""
    if not iso:
        return "없음", None
    try:
        dt = _dt.fromisoformat(iso)
    except Exception:
        return "?", None
    age = (now.date() - dt.date()).days
    hm = dt.strftime("%H:%M")
    if age == 0:
        return f"오늘 {hm}", age
    if age == 1:
        return f"어제 {hm}", age
    return f"{dt.month}/{dt.day} {hm}", age
 
 
def _fmt_next(src, now):
    """cron 첫 슬롯에서 다음 예정 시각 계산 → '오늘 16:40' / '내일 06:07' / '월 16:40' / '수동'."""
    cfg = _SCHED.get(src)
    if cfg is None:
        return "수동"
    cand = now.replace(hour=cfg["h"], minute=cfg["m"], second=0, microsecond=0)
    if cand <= now:
        cand += _td(days=1)
    if cfg["weekday"]:
        while cand.weekday() >= 5:      # 토(5)·일(6) 건너뜀
            cand += _td(days=1)
    hm = cand.strftime("%H:%M")
    d = (cand.date() - now.date()).days
    if d == 0:
        return f"오늘 {hm}"
    if d == 1:
        return f"내일 {hm}"
    return f"{_WD[cand.weekday()]} {hm}"
 
 
def _render_status_panel():
    """🕐 자동 갱신 현황 — 소스별 최근 갱신 시각 + 다음 예정 시각(KST)."""
    try:
        rows = _collect_status()
    except Exception as e:
        with st.expander("🕐 자동 갱신 현황", expanded=False):
            st.caption(f"상태 확인 실패: {str(e)[:120]}")
        return
    with st.expander("🕐 자동 갱신 현황", expanded=False):
        if rows is None:
            st.caption("Supabase 미설정 — 갱신 현황을 확인할 수 없어요.")
            return
        now = _dt.now(_KST_TZ)
        lines = []
        for r in rows:
            src = r["src"]
            if r.get("error"):
                lines.append(f"🔴 **{src}** · 로드 실패: {r['error']}")
                continue
            last_txt, age = _fmt_last(r.get("last"), now)
            next_txt = _fmt_next(src, now)
            counts = r.get("counts", [])
            fb = set(r.get("fallback") or [])
            zeros = [k for k, v in counts if k in fb and v == 0]
            # 신선도 판정: 없음→🔴 / 0건 샘플·지연→🟡 / 정상→🟢
            weekday_job = (_SCHED.get(src) or {}).get("weekday")
            manual = _SCHED.get(src) is None
            stale_lim = 3 if weekday_job else 1     # 주도주 계열은 주말 감안 3일
            if r.get("last") is None:
                badge = "🔴"
            elif zeros or (age is not None and not manual and age > stale_lim):
                badge = "🟡"
            else:
                badge = "🟢"
            cnt = " · ".join(f"{k} {v}" for k, v in counts)
            ztxt = f"  ⚠️ {'·'.join(zeros)} 0건(샘플 표시 중)" if zeros else ""
            tail = f" · {cnt}" if cnt else ""
            lines.append(f"{badge} **{src}** · 최근 {last_txt} · 다음 {next_txt}"
                         f"{tail}{ztxt}")
        st.markdown("\n\n".join(lines))
        st.caption("모든 시각 KST · '최근'은 실제 DB 갱신 시각, '다음'은 예약 목표 시각 "
                   "(GitHub 지연으로 실제 실행은 최대 1시간 늦을 수 있어요) · "
                   "🟢신선 🟡지연·일부 0건(샘플) 🔴없음·실패 · 시황 보고서는 수동 생성 · "
                   "10분 캐시")
 
 
 
# ── 탭 (lazy render: 선택된 탭만 실제 실행 → 매 렌더마다 전 탭이 도는 부담 제거) ──
# st.tabs는 탭 전환이 CSS 숨김이라 어느 탭을 보든 모든 탭 본문이 매번 실행된다.
# st.segmented_control + 조건부 렌더로 바꿔, 보고 있는 탭의 render 함수만 호출한다.
# 특히 부동산(render_realestate, 최대 규모)은 '부동산' 선택 시에만 로드된다.
_inject_countup()
 
# 탭 아이콘(:material/…) — format_func로 표시만 바꾸고 값(세션·비교·점프)은 한글 그대로 유지.
_TOP_TAB_ICONS = {"증권": ":material/candlestick_chart:", "부동산": ":material/apartment:"}
_STOCK_TAB_ICONS = {"시장": ":material/monitoring:", "글로벌": ":material/public:",
                    "브리핑": ":material/newspaper:", "종목": ":material/target:",
                    "테마": ":material/tag:"}

# 탭명 변경(주식→증권 · 2026-07): 기존 세션에 '주식' 값이 남아 있으면 새 옵션
# 목록과 충돌한다 → 위젯 생성 '전'에 치환(사용자의 섹션 선택 상태는 보존).
if st.session_state.get("top_section") == "주식":
    st.session_state["top_section"] = "증권"
_top = st.segmented_control(
    "섹션", ["증권", "부동산"], default="증권",
    format_func=lambda _t: f"{_TOP_TAB_ICONS[_t]} {_t}",
    key="top_section", label_visibility="collapsed",
) or "증권"   # 선택 해제(None) 시 기본값으로 폴백
 
# ── 섹션 테마 (A안 · 2026-07) — 상위 탭 선택에 따라 상단 토글 색을 섹션색으로 전환.
#   Streamlit은 body에 클래스를 붙일 수 없어 CSS만으로는 '현재 섹션'을 알 수 없다.
#   → 선택값을 읽어 상단 토글(top_section)에만 오버라이드를 주입한다.
#     하위 탭(stock_subtab2/re_maintab2)·3단 탭은 키가 이미 섹션별로 갈려 있어
#     정적 CSS(:root 변수 --stk/--re)로 처리되므로 여기서 건드리지 않는다.
if _top == "부동산":
    st.markdown(
        '<style>'
        '.st-key-top_section div[data-testid="stSegmentedControl"] button[aria-checked="true"],'
        '.st-key-top_section div[data-testid="stSegmentedControl"] button[kind="segmented_controlActive"],'
        '.st-key-top_section div[data-testid="stSegmentedControl"] button[data-testid="stBaseButton-segmented_controlActive"]'
        '{background:var(--re) !important;border-color:var(--re) !important;'
        'box-shadow:0 2px 7px -1px rgba(176,130,104,.5) !important;}'
        '.st-key-top_section div[data-testid="stSegmentedControl"] button:hover'
        '{color:var(--re) !important;}'
        '</style>', unsafe_allow_html=True)

if _top == "증권":
    # '브리핑에서 자세히' 점프 — 위젯 생성 '전'에 세션값을 바꿔야 한다.
    # default= 대신 세션 사전 시드를 쓰면 위젯 생성 후 값 변경 경고 없이 전환된다.
    # ※ key를 stock_subtab2로 교체(2026-07 탭 개편): 기존 세션에 '주도주'/'공모주' 값이
    #   남아 있으면 새 옵션 목록(시장/글로벌/브리핑/종목/테마)과 충돌하므로 새 키로 시작.
    _jump = st.session_state.pop("_stock_subtab_jump", None)
    if "stock_subtab2" not in st.session_state:
        st.session_state["stock_subtab2"] = "시장"
    if _jump:
        st.session_state["stock_subtab2"] = _jump
    _sub = st.segmented_control(
        "증권 탭", ["시장", "글로벌", "브리핑", "종목", "테마"],
        format_func=lambda _t: f"{_STOCK_TAB_ICONS[_t]} {_t}",
        key="stock_subtab2", label_visibility="collapsed",
    ) or "시장"
    if _sub == "시장":
        render_indices()
    elif _sub == "글로벌":
        render_global()
    elif _sub == "브리핑":
        render_report_tab()
    elif _sub == "종목":
        render_stock_picks()
    elif _sub == "테마":
        render_keywords()
else:  # 부동산
    from modules.realestate import render_realestate
    render_realestate()
 
 
# ── 수집 상태 패널(자동 갱신 현황) 제거 ──
# 접힌 expander가 하위 iframe/컴포넌트 위에 오버레이되어 리스트와 겹치는 문제가 있어
# 전역에서 렌더를 중단한다(_render_status_panel/_collect_status 등 정의는 미호출로 잔존).
