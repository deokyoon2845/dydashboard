"""종목명 → 당일 등락률 인라인 조회 (pykrx 기반, 캐시)."""

import streamlit as st


@st.cache_data(ttl=1800)
def _name_to_ticker_map():
    """KOSPI+KOSDAQ 종목명 → 종목코드 딕셔너리 (최근 거래일 기준)."""
    try:
        from datetime import datetime, timedelta
        from pykrx import stock
        d = datetime.now()
        for _ in range(7):
            ds = d.strftime("%Y%m%d")
            mapping = {}
            for mkt in ("KOSPI", "KOSDAQ"):
                try:
                    tickers = stock.get_market_ticker_list(ds, market=mkt)
                except Exception:
                    tickers = []
                for t in tickers:
                    try:
                        nm = stock.get_market_ticker_name(t)
                        if nm:
                            mapping[nm] = t
                    except Exception:
                        continue
            if mapping:
                return mapping
            d -= timedelta(days=1)
    except Exception:
        pass
    return {}


def code_for_name(name: str):
    """종목명 → 6자리 코드(없으면 None). 캐시된 KRX 사전을 사용."""
    if not name:
        return None
    try:
        return _name_to_ticker_map().get(name.strip())
    except Exception:
        return None


@st.cache_data(ttl=600)
def fetch_stock_change(name: str):
    """종목명의 당일 등락률(%) 반환. 실패 시 None."""
    try:
        from datetime import datetime, timedelta
        from pykrx import stock
        mapping = _name_to_ticker_map()
        code = mapping.get(name.strip())
        if not code:
            return None
        d = datetime.now()
        for _ in range(7):
            ds = d.strftime("%Y%m%d")
            try:
                df = stock.get_market_ohlcv(ds, ds, code)
                if df is not None and not df.empty:
                    pct = float(df["등락률"].iloc[-1])
                    return {"code": code, "pct": pct}
            except Exception:
                pass
            d -= timedelta(days=1)
    except Exception:
        pass
    return None
