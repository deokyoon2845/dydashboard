"""시장 현황 대시보드 - Streamlit 메인 앱 (라이트/다크 + 통일 헤더)."""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
from dotenv import load_dotenv

from modules.indices import INDEX_GROUPS, fetch_index, sparkline_points
from modules.indicators import render_indicators
from modules.reports import render_reports
from modules.keywords_view import render_keywords
from modules.trends import render_trends
from modules.verify import render_verify
from modules.usage import total_cost_usd

load_dotenv()
st.set_page_config(page_title="시장 현황 대시보드", page_icon="📈", layout="wide")

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
.block-container { max-width: 980px; padding-top: 1.6rem; }
h1,h2,h3 { font-family: 'Fraunces','Noto Sans KR',serif !important; letter-spacing:-.01em; color:var(--ink); }

/* 상단 헤더 */
.app-name { font-family:'Fraunces','Noto Sans KR',serif; font-size:18px; font-weight:600; color:var(--ink); }
.app-upd { font-size:11.5px; color:var(--muted); }

/* 지수 카드 */
.accent-bar { height:3px; width:30px; background:var(--sage); border-radius:3px; margin:0 0 12px; }
.mkt-group { font-size:12px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); margin:16px 0 10px; }
.grp-asof { font-weight:600; font-size:10.5px; letter-spacing:0; text-transform:none; color:var(--muted); opacity:.8; margin-left:8px; }
.mkt-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }
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

/* 리포트 */
.rpt-bar { height:3px; width:34px; background:var(--sage); border-radius:3px; margin:8px 0 8px; }
.rpt-title { font-family:'Fraunces','Noto Sans KR',serif; font-size:24px; font-weight:600; letter-spacing:-.01em; color:var(--ink); }
.rpt-meta { font-size:12px; color:var(--muted); margin-top:4px; }
.rpt-summary { font-size:15px; color:var(--ink); background:var(--summary-bg); border-left:3px solid var(--sage); padding:12px 16px; border-radius:0 10px 10px 0; margin:14px 0 6px; }
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
        f'<div class="app-name">📊 시장 현황 대시보드</div>'
        f'<div class="app-upd">조회 {now} KST · 데이터 기준일은 항목별 표기</div>',
        unsafe_allow_html=True,
    )
with hc2:
    st.toggle("🌙 다크", key="dark")
st.markdown('<hr style="border:none;border-top:1px solid var(--line);margin:6px 0 14px;">',
            unsafe_allow_html=True)


# ── 지수 현황 ──
def _card_html(name, data):
    if data is None:
        return (f'<div class="mkt-card"><div class="mkt-name">{name}</div>'
                f'<div class="mkt-na">데이터 없음</div></div>')
    is_up = data["change"] >= 0
    cls = "up" if is_up else "down"
    tint = "mkt-up" if is_up else "mkt-down"
    v = "--up" if is_up else "--down"
    arrow = "▲" if data["change"] > 0 else ("▼" if data["change"] < 0 else "▬")
    pts = sparkline_points(data["series"])
    spark = ""
    if pts:
        spark = (f'<svg class="mkt-spark" viewBox="0 0 100 28" preserveAspectRatio="none">'
                 f'<polygon points="{pts} 100,28 0,28" style="fill:var({v});opacity:.10"/>'
                 f'<polyline points="{pts}" style="fill:none;stroke:var({v});stroke-width:1.6"/></svg>')
    return (f'<div class="mkt-card {tint}"><div class="mkt-name">{name}</div>'
            f'<div class="mkt-val">{data["current"]:,.2f}</div>'
            f'<div class="mkt-chg {cls}">{arrow} {data["change"]:+,.2f} ({data["pct"]:+.2f}%)</div>'
            f'{spark}</div>')


def render_indices():
    st.markdown('<div class="accent-bar"></div>', unsafe_allow_html=True)
    st.title("주요 지수 현황")
    st.caption("데이터: Yahoo Finance · 일별 종가 기준 · 약 15분 지연")
    if st.button("🔄 새로고침"):
        st.cache_data.clear()
        st.rerun()
    render_indicators()

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

    # 3) 그룹별 렌더 (등락률 큰 순 정렬)
    for group_name, datas in group_data.items():
        items = sorted(datas.items(),
                       key=lambda kv: kv[1]["pct"] if kv[1] else -1e9, reverse=True)
        head = f'<div class="mkt-group">{group_name}'
        if not unified and group_asof[group_name]:
            head += f'<span class="grp-asof">기준 {group_asof[group_name]}</span>'
        head += "</div>"
        st.markdown(head, unsafe_allow_html=True)
        cards = "".join(_card_html(name, d) for name, d in items)
        st.markdown(f'<div class="mkt-grid">{cards}</div>', unsafe_allow_html=True)


# ── 사용량 · 비용 · 잔액 ──
def render_usage_section():
    st.markdown('<div class="mkt-group">사용량 · 비용</div>', unsafe_allow_html=True)
    rate_data = fetch_index("KRW=X")
    rate = rate_data["current"] if rate_data else None

    def to_krw(usd):
        return f" ≈ {usd * rate:,.0f}원" if rate else ""

    last = st.session_state.get("last_gen")
    if last and last.get("ok"):
        u, c = last["usage"], last["cost_usd"]
        c1, c2, c3 = st.columns(3)
        c1.metric("이번 입력 토큰", f"{u['input_tokens']:,}")
        c2.metric("이번 출력 토큰", f"{u['output_tokens']:,}")
        c3.metric("이번 예상 비용", f"${c:.4f}", help=to_krw(c).strip())

    total = total_cost_usd()
    st.write(f"**누적 추정 사용액** · ${total:.4f}{to_krw(total)}")

    budget = os.environ.get("ANTHROPIC_BUDGET_KRW")
    if budget and rate:
        try:
            b = float(budget)
            used_krw = total * rate
            st.write(f"**예산** {b:,.0f}원 · **잔액(추정)** {b - used_krw:,.0f}원")
            st.progress(min(max(used_krw / b, 0.0), 1.0) if b > 0 else 0.0)
        except ValueError:
            pass
    st.caption("※ 비용·잔액은 토큰 단가 기반 추정치입니다. 실제는 Anthropic 콘솔(Billing)에서 확인하세요.")


# ── 시황 리포트 탭 ──
def render_report_tab():
    st.markdown('<div class="rpt-bar"></div>', unsafe_allow_html=True)
    st.title("시황 리포트")
    if st.button("📝 리포트 생성 (전일 00:00 ~ 지금)"):
        with st.spinner("텔레그램 수집 → Claude 분석 중... (메시지가 많으면 시간이 걸립니다)"):
            try:
                from engine.generate import generate_report
                res = generate_report()
            except Exception as e:
                res = {"ok": False, "reason": str(e)}
        st.session_state["last_gen"] = res
        if res.get("ok"):
            st.success(f"생성 완료 · {res['messages']}개 메시지 분석")
        else:
            st.warning(f"생성 실패 · {res.get('reason')}")
    render_reports()
    st.divider()
    render_usage_section()


# ── 탭 ──
tab_idx, tab_rep, tab_kw, tab_tr = st.tabs(
    ["📈 지수 현황", "📰 시황 리포트", "🔑 오늘의 키워드", "📊 추세"]
)
with tab_idx:
    render_indices()
with tab_rep:
    render_report_tab()
with tab_kw:
    render_keywords()
with tab_tr:
    render_trends()
    render_verify()
