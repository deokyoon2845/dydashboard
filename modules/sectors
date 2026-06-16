"""업종 등락 (섹터 로테이션) — 한국 섹터 ETF의 전일 대비 등락률 (yfinance).

KRX(pykrx)가 막혀도 동작하도록 yfinance ETF 시세로 섹터 흐름을 근사한다.
정확한 KRX 업종지수는 아니지만 '오늘 어느 섹터로 돈이 돌았나'를 보기엔 충분.

섹터를 추가/수정하려면 아래 SECTOR_ETFS만 고치면 된다.
한국 ETF 티커는 '종목코드.KS' 형식. (데이터가 안 잡히는 섹터는 자동으로 빠짐)
"""

import streamlit as st
import yfinance as yf

# 섹터명 → KODEX 섹터 ETF 종목코드(.KS)
SECTOR_ETFS = {
    "반도체": "091160.KS",       # KODEX 반도체
    "2차전지": "305720.KS",      # KODEX 2차전지산업
    "자동차": "091180.KS",       # KODEX 자동차
    "은행": "091170.KS",         # KODEX 은행
    "증권": "102970.KS",         # KODEX 증권
    "바이오": "244580.KS",       # KODEX 바이오
    "철강": "117680.KS",         # KODEX 철강
    "에너지화학": "117460.KS",   # KODEX 에너지화학
    "건설": "117700.KS",         # KODEX 건설
}


@st.cache_data(ttl=900)
def _sector_change(ticker: str):
    """전일 대비 등락률(%). 실패 시 None."""
    try:
        hist = yf.Ticker(ticker).history(period="7d")
        closes = hist["Close"].dropna()
        if len(closes) < 2:
            return None
        cur, prev = float(closes.iloc[-1]), float(closes.iloc[-2])
        if not prev:
            return None
        return (cur / prev - 1) * 100
    except Exception:
        return None


def render_sectors():
    st.markdown('<div class="mkt-group">🔄 업종 등락 (섹터 ETF · 전일 대비)</div>',
                unsafe_allow_html=True)

    rows = []
    for name, tk in SECTOR_ETFS.items():
        pct = _sector_change(tk)
        if pct is not None:
            rows.append((name, pct))

    if not rows:
        st.caption("섹터 데이터를 불러오지 못했어요. (잠시 후 새로고침)")
        return

    # 등락률 내림차순 — 강한 섹터가 위로 (로테이션 한눈에)
    rows.sort(key=lambda x: x[1], reverse=True)
    max_abs = max(abs(p) for _, p in rows) or 1.0

    bars = ""
    for name, pct in rows:
        up = pct >= 0
        color = "var(--up)" if up else "var(--down)"
        arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "▬")
        w = abs(pct) / max_abs * 100  # 막대 폭(%): 최대 등락률 기준 정규화
        bars += (
            '<div style="display:flex;align-items:center;gap:10px;padding:7px 0;'
            'border-bottom:1px solid var(--line)">'
            f'<div style="width:74px;flex:none;font-size:13px;font-weight:600;'
            f'color:var(--ink)">{name}</div>'
            '<div style="flex:1;background:var(--line);border-radius:6px;'
            'height:18px;overflow:hidden">'
            f'<div style="width:{w:.0f}%;height:100%;background:{color};'
            'opacity:.85;border-radius:6px"></div></div>'
            f'<div style="width:66px;flex:none;text-align:right;font-size:13px;'
            f'font-weight:700;color:{color}">{arrow} {pct:+.2f}%</div>'
            '</div>'
        )

    st.markdown(f'<div class="supply-wrap">{bars}</div>', unsafe_allow_html=True)
    st.caption("데이터: yfinance 섹터 ETF · 전일 종가 대비 · "
               "ETF 시세 기반이라 실제 KRX 업종지수와는 차이가 있을 수 있어요")
