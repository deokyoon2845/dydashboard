"""전광판(티커 테이프) — 헤더 아래 고정, 모든 탭에서 표시.

- 지수 5종(코스피·코스닥·원/달러·S&P500·NASDAQ) + 워치리스트 종목
- 각 항목: 이름 · 현재값 · 등락률 · 미니 스파크라인
- CSS 무한 루프 애니메이션 (마우스 올리면 일시정지)
- 시세: yfinance(약 15분 지연) 우선, 한국 종목은 pykrx 폴백
- 종목명→코드 변환: pykrx 전 종목 명단 (1시간 캐시)
"""

from datetime import date, timedelta

import streamlit as st

from modules.indices import fetch_index, sparkline_points
from modules.watchlist import load_watchlist

_INDEX_ITEMS = (
    ("코스피", "^KS11", "{:,.2f}"),
    ("코스닥", "^KQ11", "{:,.2f}"),
    ("원/달러", "KRW=X", "{:,.2f}"),
    ("S&P500", "^GSPC", "{:,.2f}"),
    ("NASDAQ", "^IXIC", "{:,.2f}"),
)

_TAPE_CSS = """
<style>
.tape-wrap{overflow:hidden;border-top:1px solid var(--line,#ECEDE7);border-bottom:1px solid var(--line,#ECEDE7);
  background:var(--card,#fff);margin:0 0 14px;padding:7px 0;}
.tape-track{display:inline-flex;width:max-content;animation:tape-move linear infinite;will-change:transform;}
.tape-wrap:hover .tape-track{animation-play-state:paused;}
@keyframes tape-move{from{transform:translateX(0);}to{transform:translateX(-50%);}}
.tape-seq{display:inline-flex;align-items:center;gap:34px;padding-right:34px;}
.tape-item{display:inline-flex;align-items:center;gap:8px;white-space:nowrap;
  font-family:'Hanken Grotesk','Noto Sans KR',sans-serif;}
.tape-name{font-size:12px;font-weight:700;color:var(--muted,#9a9b92);}
.tape-val{font-size:13px;font-weight:700;color:var(--ink,#34352f);letter-spacing:-.01em;}
.tape-chg{font-size:12px;font-weight:700;}
.tape-chg.up{color:var(--up,#B65F5A);} .tape-chg.down{color:var(--down,#5A7CA0);}
.tape-spark{width:54px;height:20px;display:inline-block;}
@media (max-width:640px){
  .tape-seq{gap:22px;padding-right:22px;}
  .tape-spark{width:44px;height:18px;}
}
</style>
"""


def _norm(s: str) -> str:
    """종목명 비교용 정규화 (공백 제거 + 대소문자 무시)."""
    return "".join(str(s).split()).casefold()


@st.cache_data(ttl=3600)
def _krx_name_map() -> dict:
    """정규화된 종목명 → (종목코드, 'KS'|'KQ'). pykrx 전 종목 명단, 1시간 캐시."""
    out = {}
    try:
        from pykrx import stock as krx
        end = date.today()
        start = end - timedelta(days=10)
        s, e = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
        for mkt, suf in (("KOSPI", "KS"), ("KOSDAQ", "KQ")):
            try:
                df = krx.get_market_price_change_by_ticker(s, e, market=mkt)
                for code, row in df.iterrows():
                    name = str(row.get("종목명", "")).strip()
                    if name:
                        out[_norm(name)] = (str(code), suf)
            except Exception:
                continue
    except Exception:
        pass
    return out


@st.cache_data(ttl=600)
def _krx_quote(code: str):
    """pykrx 폴백 시세: 최근 종가·일간 등락률·스파크라인용 시리즈. 실패 시 None."""
    try:
        from pykrx import stock as krx
        end = date.today()
        start = end - timedelta(days=45)
        df = krx.get_market_ohlcv(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code)
        closes = df["종가"].dropna()
        if len(closes) < 2:
            return None
        cur, prev = float(closes.iloc[-1]), float(closes.iloc[-2])
        return {"current": cur,
                "pct": (cur / prev - 1) * 100 if prev else 0.0,
                "series": [float(x) for x in closes.tail(30)]}
    except Exception:
        return None


def _spark_svg(series, is_up: bool) -> str:
    try:
        pts = sparkline_points(series)
    except Exception:
        pts = ""
    if not pts:
        return ""
    v = "--up" if is_up else "--down"
    return (f'<svg class="tape-spark" viewBox="0 0 100 28" preserveAspectRatio="none">'
            f'<polyline points="{pts}" style="fill:none;stroke:var({v},#888);stroke-width:2"/></svg>')


def _item_html(name: str, cur: float, pct: float, series, fmt: str) -> str:
    is_up = pct >= 0
    cls = "up" if is_up else "down"
    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "▬")
    return (f'<span class="tape-item">'
            f'<span class="tape-name">{name}</span>'
            f'<span class="tape-val">{fmt.format(cur)}</span>'
            f'<span class="tape-chg {cls}">{arrow}{pct:+.2f}%</span>'
            f'{_spark_svg(series, is_up)}'
            f'</span>')


def render_ticker_tape():
    """헤더 아래 전광판 렌더. 데이터가 하나도 없으면 조용히 생략."""
    items = []

    # 1) 주요 지수
    for name, ticker, fmt in _INDEX_ITEMS:
        try:
            d = fetch_index(ticker)
        except Exception:
            d = None
        if d:
            items.append(_item_html(name, d["current"], d["pct"], d.get("series"), fmt))

    # 2) 워치리스트 종목
    wl = load_watchlist()
    if wl:
        nmap = _krx_name_map()
        for nm in wl:
            info = nmap.get(_norm(nm))
            d = None
            if info:
                code, suf = info
                try:
                    d = fetch_index(f"{code}.{suf}")
                except Exception:
                    d = None
                if d is None:
                    d = _krx_quote(code)
            if d:
                items.append(_item_html(
                    nm, d["current"], d["pct"], d.get("series"), "{:,.0f}"))

    if not items:
        return

    seq = f'<div class="tape-seq">{"".join(items)}</div>'
    dur = max(28, 5 * len(items))  # 항목 수에 비례한 속도
    st.markdown(
        _TAPE_CSS
        + f'<div class="tape-wrap">'
          f'<div class="tape-track" style="animation-duration:{dur}s">{seq}{seq}</div>'
          f'</div>',
        unsafe_allow_html=True)
