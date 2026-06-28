"""종목명 → 코드/등락률 조회.

종목명 → 코드: ① Supabase 종목 마스터(stock_master, 클라우드에서도 동작)
              ② pykrx 사전(로컬 폴백). 등락률: pykrx(있을 때).
"""

import streamlit as st


@st.cache_data(ttl=3600)
def _db_name_map():
    """Supabase stock_master → {종목명: 코드} (법인명도 보조키). DB 미설정/실패 시 빈 dict."""
    try:
        from modules import db
        if not db.supabase_configured():
            return {}
        m = {}
        for r in db.load_stock_master():
            code = str(r.get("code") or "").strip()
            if not code:
                continue
            nm = str(r.get("name") or "").strip()
            if nm:
                m.setdefault(nm, code)
            cn = str(r.get("corp_name") or "").strip()
            if cn:
                m.setdefault(cn, code)
        return m
    except Exception:
        return {}


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
    """종목명 → 6자리 코드(없으면 None).
       ① Supabase 종목 마스터(클라우드 동작) → ② pykrx 사전(로컬 폴백)."""
    if not name:
        return None
    key = name.strip()
    try:
        code = _db_name_map().get(key)
        if code:
            return code
    except Exception:
        pass
    try:
        return _name_to_ticker_map().get(key)
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
