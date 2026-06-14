"""금리 카드 — 미 국채 수익률 (yfinance, 지수 현황 탭에 표시).

야후의 CBOE 금리 인덱스를 쓴다 (Close 값이 % 그대로):
  ^IRX=13주(3개월), ^FVX=5년, ^TNX=10년, ^TYX=30년
한국 국고채 수익률은 yfinance에 없어서, 한·미 금리차는 추후 한국은행(ECOS) 등
별도 소스를 붙여야 한다. 우선 미 금리 + 장단기차(10년−3개월)부터 제공.
"""

import streamlit as st
import yfinance as yf

# 표시 순서대로
_RATE_TICKERS = [
    ("미 3개월", "^IRX"),
    ("미 5년", "^FVX"),
    ("미 10년", "^TNX"),
    ("미 30년", "^TYX"),
]


@st.cache_data(ttl=900)
def _fetch_rate(ticker: str):
    """현재 수익률(%)과 전일 대비 변화(%p)를 반환. 실패 시 None."""
    try:
        hist = yf.Ticker(ticker).history(period="7d")
        if hist.empty:
            return None
        closes = hist["Close"].dropna()
        if len(closes) < 1:
            return None
        cur = float(closes.iloc[-1])
        prev = float(closes.iloc[-2]) if len(closes) >= 2 else cur
        return {"cur": cur, "chg": cur - prev}
    except Exception:
        return None


def render_rates():
    st.markdown('<div class="mkt-group">📈 금리 · 미 국채 수익률</div>',
                unsafe_allow_html=True)

    data = {name: _fetch_rate(tk) for name, tk in _RATE_TICKERS}

    cards = ""
    for name, _tk in _RATE_TICKERS:
        d = data[name]
        if not d:
            cards += (f'<div class="mkt-card"><div class="mkt-name">{name}</div>'
                      f'<div class="mkt-na">데이터 없음</div></div>')
            continue
        bp = d["chg"] * 100  # %p → bp(베이시스포인트)
        up = d["chg"] >= 0
        cls = "up" if up else "down"
        arrow = "▲" if d["chg"] > 0 else ("▼" if d["chg"] < 0 else "▬")
        cards += (f'<div class="mkt-card"><div class="mkt-name">{name}</div>'
                  f'<div class="mkt-val">{d["cur"]:.2f}%</div>'
                  f'<div class="mkt-chg {cls}">{arrow} {bp:+.0f}bp</div></div>')
    st.markdown(f'<div class="mkt-grid">{cards}</div>', unsafe_allow_html=True)

    # 장단기 금리차 (10년 − 3개월): 음수면 '금리 역전' = 경기침체 경고 신호
    t10, t3 = data.get("미 10년"), data.get("미 3개월")
    if t10 and t3:
        spread = t10["cur"] - t3["cur"]
        if spread >= 0:
            note = "정상 (우상향)"
        else:
            note = "역전 — 경기침체 경고 신호로 읽히는 구간"
        st.caption(f"미 10년−3개월 장단기 금리차: {spread:+.2f}%p · {note} "
                   f"· 데이터: yfinance · 약 15분 지연")
    else:
        st.caption("데이터: yfinance · 약 15분 지연")
