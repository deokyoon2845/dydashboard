"""시장 현황 대시보드 - Streamlit 메인 앱 (탭: 지수 현황 / 시황 리포트)."""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
from dotenv import load_dotenv

from modules.indices import INDEX_GROUPS, fetch_index, sparkline_points
from modules.reports import render_reports
from modules.keywords_view import render_keywords
from modules.usage import total_cost_usd

load_dotenv()  # 로컬 .env (생성 버튼이 텔레그램/Claude 키를 읽기 위함)

st.set_page_config(page_title="시장 현황 대시보드", page_icon="📈", layout="wide")

UP_COLOR = "#B65F5A"   # 상승 = 빨강 (한국식)
DOWN_COLOR = "#5A7CA0"  # 하락 = 파랑

# ── 스타일 (미니멀 미스트) ─────────────────────────
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Hanken+Grotesk:wght@400;500;600&family=Noto+Sans+KR:wght@400;500;700&display=swap');

html, body, [data-testid="stAppViewContainer"] { font-family: 'Hanken Grotesk', 'Noto Sans KR', sans-serif; }
.block-container { max-width: 960px; padding-top: 2rem; }
h1, h2, h3 { font-family: 'Fraunces', 'Noto Sans KR', serif !important; letter-spacing: -0.01em; }

/* 지수 카드 */
.accent-bar { height: 3px; width: 30px; background: #A7BBA9; border-radius: 3px; margin: 0 0 12px; }
.mkt-group { font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: #9aa093; margin: 16px 0 10px; }
.mkt-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
@media (max-width: 640px) { .mkt-grid { grid-template-columns: repeat(2, 1fr); } }
.mkt-card { background: #fff; border: 1px solid #ECEDE7; border-radius: 16px; padding: 14px 14px 12px; }
.mkt-name { font-size: 12.5px; font-weight: 600; color: #9a9b92; }
.mkt-val  { font-size: 21px; font-weight: 700; color: #34352f; margin-top: 4px; letter-spacing: -.02em; }
.mkt-chg  { font-size: 12.5px; font-weight: 700; margin-top: 2px; }
.mkt-chg.up   { color: #B65F5A; }
.mkt-chg.down { color: #5A7CA0; }
.mkt-spark { width: 100%; height: 28px; display: block; margin-top: 8px; }
.mkt-na { color: #c2c2bb; font-size: 13px; margin-top: 6px; }

/* 시황 리포트 (리서치 노트) */
.rpt-bar { height: 3px; width: 34px; background: #A7BBA9; border-radius: 3px; margin: 8px 0 8px; }
.rpt-title { font-family: 'Fraunces','Noto Sans KR',serif; font-size: 24px; font-weight: 600; letter-spacing: -.01em; }
.rpt-meta { font-size: 12px; color: #9a9b92; margin-top: 4px; }
.rpt-summary { font-size: 15px; color: #4a4b43; background: #F6F7F2; border-left: 3px solid #A7BBA9; padding: 12px 16px; border-radius: 0 10px 10px 0; margin: 14px 0 6px; }
[data-testid="stMarkdownContainer"] ul li::marker { color: #A7BBA9; }

/* 종목 pill */
.pill { display: inline-block; font-size: 11.5px; font-weight: 600; background: #F1F2EC; color: #5d6258; border: 1px solid #ECEDE7; padding: 3px 9px; border-radius: 7px; margin: 0 5px 5px 0; }

/* 오늘의 키워드 (랭킹 리스트) */
.kw-row { display: flex; gap: 12px; padding: 12px 0; border-bottom: 1px solid #ECEDE7; }
.kw-rank { font-family: 'Fraunces','Noto Sans KR',serif; font-size: 21px; font-weight: 600; color: #7E9A83; width: 26px; flex: none; text-align: center; }
.kw-mid { flex: 1; min-width: 0; }
.kw-kw { font-size: 15.5px; font-weight: 700; }
.kw-news { margin-top: 4px; }
.kw-news a { display: inline-flex; align-items: center; gap: 4px; font-size: 13px; color: #7E9A83; text-decoration: none; font-weight: 600; }
.kw-news a:hover { text-decoration: underline; }
</style>
""",
    unsafe_allow_html=True,
)


# ── 지수 현황 ──────────────────────────────────────
def _card_html(name, data):
    if data is None:
        return (f'<div class="mkt-card"><div class="mkt-name">{name}</div>'
                f'<div class="mkt-na">데이터 없음</div></div>')
    is_up = data["change"] >= 0
    cls = "up" if is_up else "down"
    color = UP_COLOR if is_up else DOWN_COLOR
    pts = sparkline_points(data["series"])
    spark = (f'<svg class="mkt-spark" viewBox="0 0 100 28" preserveAspectRatio="none">'
             f'<polyline fill="none" stroke="{color}" stroke-width="1.6" points="{pts}"/></svg>'
             if pts else "")
    return (f'<div class="mkt-card"><div class="mkt-name">{name}</div>'
            f'<div class="mkt-val">{data["current"]:,.2f}</div>'
            f'<div class="mkt-chg {cls}">{data["change"]:+,.2f} ({data["pct"]:+.2f}%)</div>'
            f'{spark}</div>')


def render_indices():
    st.markdown('<div class="accent-bar"></div>', unsafe_allow_html=True)
    st.title("주요 지수 현황")
    now = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")
    st.caption(f"기준 시각: {now} (KST) · 데이터: Yahoo Finance · 약 15분 지연")
    if st.button("🔄 새로고침"):
        st.cache_data.clear()
        st.rerun()
    for group_name, tickers in INDEX_GROUPS.items():
        st.markdown(f'<div class="mkt-group">{group_name}</div>', unsafe_allow_html=True)
        cards = "".join(_card_html(name, fetch_index(t)) for name, t in tickers.items())
        st.markdown(f'<div class="mkt-grid">{cards}</div>', unsafe_allow_html=True)


# ── 사용량 · 비용 · 잔액 ───────────────────────────
def render_usage_section():
    st.markdown('<div class="mkt-group">사용량 · 비용</div>', unsafe_allow_html=True)

    rate_data = fetch_index("KRW=X")  # 원/달러
    rate = rate_data["current"] if rate_data else None

    def to_krw(usd):
        return f" ≈ {usd * rate:,.0f}원" if rate else ""

    last = st.session_state.get("last_gen")
    if last and last.get("ok"):
        u, c = last["usage"], last["cost_usd"]
        c1, c2, c3 = st.columns(3)
        c1.metric("이번 입력 토큰", f"{u['input_tokens']:,}")
        c2.metric("이번 출력 토큰", f"{u['output_tokens']:,}")
        c3.metric("이번 예상 비용", f"${c:.4f}", help=f"{to_krw(c).strip()}")

    total = total_cost_usd()
    st.write(f"**누적 추정 사용액** · ${total:.4f}{to_krw(total)}")

    budget = os.environ.get("ANTHROPIC_BUDGET_KRW")
    if budget and rate:
        try:
            b = float(budget)
            used_krw = total * rate
            remain = b - used_krw
            st.write(f"**예산** {b:,.0f}원 · **잔액(추정)** {remain:,.0f}원")
            st.progress(min(max(used_krw / b, 0.0), 1.0) if b > 0 else 0.0)
        except ValueError:
            pass

    st.caption("※ 비용·잔액은 토큰 단가 기반 추정치입니다. 실제 청구·잔액은 "
               "Anthropic 콘솔(Settings → Billing)에서 확인하세요.")


# ── 시황 리포트 탭 ─────────────────────────────────
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


# ── 탭 구성 ────────────────────────────────────────
tab_idx, tab_rep, tab_kw = st.tabs(["📈 지수 현황", "📰 시황 리포트", "🔑 오늘의 키워드"])
with tab_idx:
    render_indices()
with tab_rep:
    render_report_tab()
with tab_kw:
    render_keywords()
