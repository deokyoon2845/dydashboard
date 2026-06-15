"""금리 카드 — 미 국채 수익률 + 한국 국고채 수익률 (지수 현황 탭).

미국: 야후 CBOE 금리 인덱스 (Close = % 그대로)
  ^IRX=13주(3개월), ^FVX=5년, ^TNX=10년, ^TYX=30년
한국: 한국은행 ECOS 국고채 2년·3년·10년 (ECOS_API_KEY 필요).
      ECOS 호출 로직은 rate_gap.py의 헬퍼를 재사용한다(중복 방지).

2026-06: 수익률 카드를 히트맵 타일로 표시 — 전일 대비 변화 '방향'으로 색칠
  (상승=빨강 / 하락=파랑, ±10bp에서 최대 채도). 정적 카드보다 커브 전반의
  '오늘 움직임'이 한눈에 들어온다. 지수 히트맵과 같은 .heat-tile 스타일 사용.
"""

import streamlit as st
import yfinance as yf

# ECOS 호출 헬퍼 재사용 (rate_gap.py 정의)
from modules.rate_gap import _cfg, _ecos_items, _ecos_latest, _find_code

# 미 국채 (표시 순서대로)
_RATE_TICKERS = [
    ("미 3개월", "^IRX"),   # 13주 T-bill = 3개월 (장단기차 10년−3개월에 사용)
    ("미 5년", "^FVX"),
    ("미 10년", "^TNX"),
    ("미 30년", "^TYX"),
]

# 한국 국고채 (ECOS 항목 이름 키워드, 표시 라벨)
_KR_TENORS = [
    ("한 2년", ("국고채", "2년")),
    ("한 3년", ("국고채", "3년")),
    ("한 10년", ("국고채", "10년")),
]


def _rate_heat_color(bp):
    """전일 대비 변화(bp) 방향 색. 상승=빨강(--up)/하락=파랑(--down). ±10bp에서 최대 채도."""
    if bp is None:
        return "#F6F7F2", "#34352f"
    t = max(-1.0, min(1.0, bp / 10.0))
    base = (246, 247, 242)            # --summary-bg
    up = (182, 95, 90)                # --up #B65F5A
    down = (90, 124, 160)             # --down #5A7CA0
    tgt = up if t >= 0 else down
    k = abs(t)
    r = round(base[0] + (tgt[0] - base[0]) * k)
    g = round(base[1] + (tgt[1] - base[1]) * k)
    b = round(base[2] + (tgt[2] - base[2]) * k)
    txt = "#ffffff" if k > 0.55 else "#34352f"
    return f"rgb({r},{g},{b})", txt


def _rate_tile(name, cur, bp):
    """수익률 히트맵 타일. cur=수익률(%), bp=전일대비(bp). cur가 None이면 '데이터 없음'."""
    if cur is None:
        return (f'<div class="heat-tile" style="background:#F6F7F2;color:#9a9b92;">'
                f'<div class="heat-name">{name}</div>'
                f'<div class="heat-val" style="font-size:14px;">데이터 없음</div></div>')
    bg, txt = _rate_heat_color(bp)
    chg = bp or 0
    arrow = "▲" if chg > 0 else ("▼" if chg < 0 else "▬")
    bp_html = (f'<div class="heat-pct" style="color:{txt};">{arrow} {bp:+.0f}bp</div>'
               if bp is not None else "")
    return (f'<div class="heat-tile" style="background:{bg};">'
            f'<div class="heat-name" style="color:{txt};opacity:.92;">{name}</div>'
            f'<div class="heat-val" style="color:{txt};">{cur:.2f}%</div>'
            f'{bp_html}</div>')


@st.cache_data(ttl=900)
def _fetch_rate(ticker: str):
    """미 국채: 현재 수익률(%)과 전일 대비 변화(%p). 실패 시 None."""
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


def _fetch_kr_yields(key):
    """한국 국고채 2년·3년·10년: {라벨: {'cur','bp'} or None}. ECOS 헬퍼 재사용."""
    items = _ecos_items(key)
    out = {}
    for label, kw in _KR_TENORS:
        code = _find_code(items, *kw)
        vals = _ecos_latest(key, code) if code else []
        if vals:
            cur = vals[-1][1]
            prev = vals[-2][1] if len(vals) >= 2 else cur
            out[label] = {"cur": cur, "bp": (cur - prev) * 100}  # %p → bp
        else:
            out[label] = None
    return out


def render_rates():
    # ── 미 국채 수익률 (히트맵 타일) ──
    st.markdown('<div class="mkt-group">📈 금리 · 미 국채 수익률</div>',
                unsafe_allow_html=True)

    data = {name: _fetch_rate(tk) for name, tk in _RATE_TICKERS}

    tiles = ""
    for name, _tk in _RATE_TICKERS:
        d = data[name]
        tiles += _rate_tile(name, d["cur"], d["chg"] * 100) if d else _rate_tile(name, None, None)
    st.markdown(f'<div class="mkt-grid">{tiles}</div>', unsafe_allow_html=True)

    # 장단기 금리차 (10년 − 3개월): 음수면 '금리 역전' = 경기침체 경고 신호
    t10, t3 = data.get("미 10년"), data.get("미 3개월")
    if t10 and t3:
        spread = t10["cur"] - t3["cur"]
        note = "정상 (우상향)" if spread >= 0 else "역전 — 경기침체 경고 신호로 읽히는 구간"
        st.caption(f"미 10년−3개월 장단기 금리차: {spread:+.2f}%p · {note} · "
                   f"색 = 전일 대비 변화(상승 빨강/하락 파랑, ±10bp 최대) · "
                   f"데이터: yfinance · 약 15분 지연")
    else:
        st.caption("색 = 전일 대비 변화(상승 빨강/하락 파랑) · 데이터: yfinance · 약 15분 지연")

    # ── 한국 국고채 수익률 (ECOS · 히트맵 타일) ──
    st.markdown('<div class="mkt-group" style="margin-top:18px;">🇰🇷 한국 국고채 수익률</div>',
                unsafe_allow_html=True)
    key = _cfg("ECOS_API_KEY")
    if not key:
        st.caption("한국 국고채는 ECOS_API_KEY가 필요해요. Secrets에 키를 넣으면 표시됩니다.")
        return

    kr = _fetch_kr_yields(key)
    tiles = ""
    for label, _kw in _KR_TENORS:
        d = kr.get(label)
        tiles += _rate_tile(label, d["cur"], d["bp"]) if d else _rate_tile(label, None, None)
    st.markdown(f'<div class="mkt-grid">{tiles}</div>', unsafe_allow_html=True)

    # 한국 장단기 금리차 (10년 − 2년)
    k10, k2 = kr.get("한 10년"), kr.get("한 2년")
    if k10 and k2:
        ks = k10["cur"] - k2["cur"]
        note = "정상 (우상향)" if ks >= 0 else "역전"
        st.caption(f"한 10년−2년 장단기 금리차: {ks:+.2f}%p · {note} · "
                   f"색 = 전일 대비 변화 · 데이터: 한국은행 ECOS")
    else:
        st.caption("색 = 전일 대비 변화(상승 빨강/하락 파랑) · 데이터: 한국은행 ECOS")
