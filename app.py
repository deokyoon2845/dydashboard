"""시장 현황 대시보드 - Streamlit 메인 앱 (라이트/다크 + 통일 헤더)."""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
from dotenv import load_dotenv

from modules.indices import (
    INDEX_GROUPS, fetch_index, sparkline_points,
    fetch_supply_demand_summary,
)
from modules.calendar_view import render_calendar
from modules.timeline_view import render_timeline
from modules.indicators import render_indicators
from modules.reports import render_reports, render_reports_manage
from modules.keywords_view import render_keywords
from modules.trends import render_trends
from modules.verify import render_verify
from modules.usage import total_cost_usd
from modules.ticker_tape import render_ticker_tape

load_dotenv()
st.set_page_config(page_title="DY Monitoring", page_icon="📈", layout="wide")

if "dark" not in st.session_state:
    st.session_state["dark"] = False
dark = st.session_state["dark"]

# ── 색 변수 ──
LIGHT_VARS = """
:root{
  --bg:#FCFCFA; --card:#ffffff; --ink:#34352f; --muted:#9a9b92; --line:#ECEDE7;
  --sage:#A7BBA9; --sage-deep:#7E9A83; --up:#B65F5A; --down:#5A7CA0;
  --summary-bg:#F6F7F2; --pill-bg:#F1F2EC; --pill-ink:#5d6258;
  --tint-up:#FBF2F2; --tint-down:#F1F5F9; --pill-hover:#E6EBE2;
}
"""
DARK_VARS = """
:root{
  --bg:#24262F; --card:#2E313C; --ink:#E8E8EF; --muted:#9A9CAB; --line:#3A3D49;
  --sage:#A8D8C0; --sage-deep:#A8D8C0; --up:#F0A3AB; --down:#94B6EA;
  --summary-bg:#2A2D38; --pill-bg:#343845; --pill-ink:#C7CAD6;
  --tint-up:#33282C; --tint-down:#262D39; --pill-hover:#3C4150;
}
[data-testid="stAppViewContainer"], [data-testid="stHeader"]{ background: var(--bg) !important; }
[data-testid="stAppViewContainer"]{ color: var(--ink); }
.stButton > button{ background: var(--card) !important; color: var(--ink) !important; border:1px solid var(--line) !important; }
.stTextInput input, .stDateInput input{ background: var(--card) !important; color: var(--ink) !important; }
[data-baseweb="select"] > div{ background: var(--card) !important; color: var(--ink) !important; }
.stTabs [data-baseweb="tab"]{ color: var(--muted); }
[data-testid="stCaptionContainer"], small{ color: var(--muted) !important; }
"""

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Hanken+Grotesk:wght@400;500;600&family=Noto+Sans+KR:wght@400;500;700&display=swap');
__VARS__
html, body, [data-testid="stAppViewContainer"] { font-family: 'Hanken Grotesk','Noto Sans KR',sans-serif; }
.block-container { max-width: 1280px; padding-top: 3.5rem; }
[data-testid="stMainBlockContainer"] { padding-top: 3.5rem !important; }
.stMainBlockContainer { padding-top: 3.5rem !important; }
h1,h2,h3 { font-family: 'Fraunces','Noto Sans KR',serif !important; letter-spacing:-.01em; color:var(--ink); }

/* 탭: 글자 잘림 방지 (줄바꿈 금지 + 넉넉한 패딩) */
.stTabs [data-baseweb="tab-list"] { gap:4px; flex-wrap:wrap; }
.stTabs [data-baseweb="tab"] { white-space:nowrap; padding:8px 14px; height:auto; min-width:max-content; }
.stTabs [data-baseweb="tab"] p { font-size:15px; margin:0; white-space:nowrap; }

/* 버튼: 통일된 정렬·여백 */
.stButton > button { border-radius:9px; padding:6px 16px; font-weight:600; }
.stButton { margin-bottom:4px; }
[data-testid="stExpander"] { border-radius:10px; margin-bottom:8px; }

/* 상단 헤더 */
.app-name { font-family:'Fraunces','Noto Sans KR',serif; font-size:18px; font-weight:600; color:var(--ink); }
.app-upd { font-size:11.5px; color:var(--muted); }

/* 지수 카드 */
.accent-bar { height:3px; width:30px; background:var(--sage); border-radius:3px; margin:0 0 12px; }
.mkt-group { font-size:12px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); margin:16px 0 10px; }
.grp-asof { font-weight:600; font-size:10.5px; letter-spacing:0; text-transform:none; color:var(--muted); opacity:.8; margin-left:8px; }
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

/* 수급 상위 종목 테이블 */
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

/* 다가오는 일정 캘린더 */
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

/* 리포트 */
.rpt-bar { height:3px; width:34px; background:var(--sage); border-radius:3px; margin:8px 0 8px; }
.rpt-toprow { display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; }
.mood-badge { font-size:11px; font-weight:700; letter-spacing:.06em; padding:4px 10px; border-radius:20px; }
.mood-pos { background:#e1f5ee; color:#0f6e56; }
.mood-neu { background:#F1F2EC; color:#5d6258; }
.mood-cau { background:#FAEEDA; color:#854F0B; }
.app.dark .mood-pos { background:#085041; color:#9fe1cb; }
.app.dark .mood-neu { background:#343845; color:#C7CAD6; }
.app.dark .mood-cau { background:#633806; color:#FAC775; }
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

/* pill */
.pill { display:inline-block; font-size:11.5px; font-weight:600; background:var(--pill-bg); color:var(--pill-ink); border:1px solid var(--line); padding:3px 9px; border-radius:7px; margin:0 5px 5px 0; }
.pill-link { text-decoration:none; transition:background .15s, border-color .15s; }
.pill-link:hover { background:var(--pill-hover); border-color:var(--sage); }

/* 키워드 */
.kw-row { display:flex; gap:12px; padding:12px 0; border-bottom:1px solid var(--line); }
.kw-rank { font-family:'Fraunces','Noto Sans KR',serif; font-size:21px; font-weight:600; color:var(--sage-deep); width:26px; flex:none; text-align:center; }
.kw-mid { flex:1; min-width:0; }
.kw-kw { font-size:15.5px; font-weight:700; color:var(--ink); }
.kw-news { margin-top:4px; }
.kw-news a { display:inline-flex; align-items:center; gap:4px; font-size:13px; color:var(--sage-deep); text-decoration:none; font-weight:600; }
.kw-news a:hover { text-decoration:underline; }

/* 빈 상태 */
.empty { text-align:center; color:var(--muted); padding:34px 16px; }
.empty .ico { font-size:32px; }
.empty .msg { font-size:14px; margin-top:10px; color:var(--ink); }
.empty .hint { font-size:12px; margin-top:5px; color:var(--muted); }
</style>
"""
st.markdown(CSS.replace("__VARS__", DARK_VARS if dark else LIGHT_VARS), unsafe_allow_html=True)

# ── 상단 헤더 ──
now = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")
hc1, hc2 = st.columns([5, 1])
with hc1:
    st.markdown(
        f'<div class="app-name">DY Monitoring</div>'
        f'<div class="app-upd">조회 {now} KST · 데이터 기준일은 항목별 표기</div>',
        unsafe_allow_html=True,
    )
with hc2:
    st.toggle("🌙 다크", key="dark")
st.markdown('<hr style="border:none;border-top:1px solid var(--line);margin:6px 0 14px;">',
            unsafe_allow_html=True)

# ── 전광판 (모든 탭 공통, 헤더와 탭 사이) ──
render_ticker_tape()


# ── 지수 카드 HTML ──
def _card_html(name, data):
    if data is None:
        return (f'<div class="mkt-card"><div class="mkt-name">{name}</div>'
                f'<div class="mkt-na">데이터 없음</div></div>')
    is_up = data["change"] >= 0
    # invert_color(예: VIX)는 하락이 시장에 '긍정'이므로 색을 반전 (화살표·수치는 그대로)
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
            f'<div class="mkt-val">{data["current"]:,.2f}</div>'
            f'<div class="mkt-chg {cls}">{arrow} {data["change"]:+,.2f} ({data["pct"]:+.2f}%)</div>'
            f'{spark}</div>')


# ── 수급 상위 종목 HTML ──
def _supply_html(supply_data: dict) -> str:
    if not supply_data:
        return ""
    parts = []
    for mkt_label, mkt_data in supply_data.items():
        date_str = mkt_data.get("date", "")
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


# ── 지수 현황 탭 렌더 ──
def render_indices():
    st.markdown('<div class="accent-bar"></div>', unsafe_allow_html=True)
    st.title("주요 지수 현황")
    st.caption("데이터: Yahoo Finance · 일별 종가 기준 · 약 15분 지연")
    if st.button("🔄 새로고침"):
        st.cache_data.clear()
        st.rerun()
    render_indicators()
    render_calendar()

    # 1) 전체 조회 후 그룹별 기준일 계산
    group_data, group_asof = {}, {}
    for group_name, tickers in INDEX_GROUPS.items():
        datas = {name: fetch_index(t) for name, t in tickers.items()}
        group_data[group_name] = datas
        asofs = [d["asof"] for d in datas.values() if d and d.get("asof")]
        group_asof[group_name] = max(asofs) if asofs else None

    # 2) 모든 그룹의 기준일이 같으면 상단에 한 번만 통합 표기
    distinct = {a for a in group_asof.values() if a}
    unified = len(distinct) == 1
    if unified:
        st.markdown(
            f'<div class="data-asof">데이터 기준 {next(iter(distinct))} · '
            f'해외 지수·환율은 직전 거래일 종가</div>', unsafe_allow_html=True)

    # 3) 그룹별 렌더 (INDEX_GROUPS 정의 순서 그대로)
    for group_name, datas in group_data.items():
        items = list(datas.items())
        head = f'<div class="mkt-group">{group_name}'
        if not unified and group_asof[group_name]:
            head += f'<span class="grp-asof">기준 {group_asof[group_name]}</span>'
        head += "</div>"
        st.markdown(head, unsafe_allow_html=True)
        cards = "".join(_card_html(name, d) for name, d in items)
        st.markdown(f'<div class="mkt-grid">{cards}</div>', unsafe_allow_html=True)

    # 4) 수급 상위 종목
    supply = fetch_supply_demand_summary()
    if supply:
        st.markdown('<div class="mkt-group">💰 수급 상위 종목</div>', unsafe_allow_html=True)
        st.markdown(_supply_html(supply), unsafe_allow_html=True)


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


# ── 생성 권한 확인 (비밀번호) ──
def _can_generate():
    """리포트 생성 권한 확인. Secrets에 APP_PASSWORD가 있으면 인증 요구.

    - APP_PASSWORD 미설정 시: 잠금 없음 (개인 로컬 사용 등)
    - 설정 시: 비밀번호 일치한 세션에서만 생성 허용
    """
    try:
        pw_required = st.secrets.get("APP_PASSWORD", "")
    except Exception:
        pw_required = ""

    # 비밀번호 미설정 → 잠금 없음
    if not pw_required:
        return True

    # 이미 이 세션에서 인증됨
    if st.session_state.get("gen_authed"):
        return True

    # 인증 UI
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
    st.markdown('<div class="rpt-bar"></div>', unsafe_allow_html=True)
    st.title("전략·시황 보고서")

    # 1) 리포트 먼저 표시 (좌 2/3 본문 · 우 1/3 내 종목/주목 테마)
    render_reports()

    # 2) 하단: 생성·관리 영역
    st.divider()

    flash = st.session_state.pop("gen_flash", None)
    if flash:
        st.success(flash)

    authed = _can_generate()
    gen_clicked = st.button("📝 리포트 생성 (전일 15:40 ~ 지금)", disabled=not authed)
    if gen_clicked and authed:
        with st.spinner("텔레그램 수집 → Claude 분석 중... (메시지가 많으면 시간이 걸립니다)"):
            try:
                from engine.generate import generate_report
                res = generate_report()
            except Exception as e:
                res = {"ok": False, "reason": str(e)}
        st.session_state["last_gen"] = res
        if res.get("ok"):
            # 새 리포트가 상단에 바로 보이도록 rerun (성공 메시지는 flash 로 전달)
            st.session_state["gen_flash"] = f"생성 완료 · {res['messages']}개 메시지 분석"
            st.session_state["rpt_picked_path"] = None
            st.rerun()
        else:
            st.warning(f"생성 실패 · {res.get('reason')}")

    from modules.watchlist import render_watchlist_editor
    render_watchlist_editor()

    render_reports_manage()

    st.divider()
    render_usage_section()


# ── 탭 ──
tab_idx, tab_rep, tab_kw, tab_tr = st.tabs(
    ["지수 현황", "전략·시황", "오늘의 키워드", "추세"]
)
with tab_idx:
    render_indices()
with tab_rep:
    render_report_tab()
with tab_kw:
    render_keywords()
with tab_tr:
    render_timeline()
    render_trends()
    render_verify()
