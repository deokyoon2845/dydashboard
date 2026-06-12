"""주요 지수 데이터를 Yahoo Finance(yfinance)에서 가져오는 모듈."""

import yfinance as yf
import streamlit as st
from datetime import datetime, timedelta

# 카테고리별 지수 정의: 표시이름 -> 야후 티커
# 항목을 추가/수정하려면 여기만 고치면 됩니다.
INDEX_GROUPS = {
    "국내": {
        "코스피": "^KS11",
        "코스닥": "^KQ11",
    },
    "미국": {
        "S&P 500": "^GSPC",
        "나스닥": "^IXIC",
        "다우": "^DJI",
        "필라델피아 반도체": "^SOX",
    },
    "환율": {
        "원/달러": "KRW=X",
        "원/100엔": "JPYKRW=X",   # 1엔당 원화 × 100 (한국 관행 표기)
        "원/유로": "EURKRW=X",
        "원/위안": "CNYKRW=X",
        "달러 인덱스": "DX-Y.NYB",
    },
    "변동성·원자재": {
        "VIX": "^VIX",
        "금 ($/oz)": "GC=F",
        "WTI 유가 ($/bbl)": "CL=F",
    },
}

# 표시 배율: 100엔당 원화 표기를 위해 JPYKRW=X 는 ×100
_SCALE = {"JPYKRW=X": 100.0}

# 색 반전 티커: 하락이 시장에 '긍정'인 지표 (예: 공포지수 VIX)
_INVERT_COLOR = {"^VIX"}


@st.cache_data(ttl=600)  # 10분 동안 결과 재사용 -> 야후 과다 호출 방지
def fetch_index(ticker: str):
    """티커 1개의 현재값/등락/최근 추이를 가져온다. 실패하면 None을 반환."""
    try:
        df = yf.Ticker(ticker).history(period="1mo", interval="1d")
        if df.empty or len(df) < 2:
            return None

        close = df["Close"].dropna()

        # 표시 배율 적용 (예: 원/100엔)
        scale = _SCALE.get(ticker, 1.0)
        if scale != 1.0:
            close = close * scale

        current = float(close.iloc[-1])   # 가장 최근 종가
        prev = float(close.iloc[-2])      # 그 전 거래일 종가
        change = current - prev
        pct = (change / prev) * 100 if prev else 0.0

        # 데이터의 실제 기준일 (마지막 거래일) — tz 문제를 피하려 문자열로 저장
        try:
            asof = close.index[-1].strftime("%Y-%m-%d")
        except Exception:
            asof = None

        return {
            "current": current,
            "change": change,
            "pct": pct,
            "series": close,  # 차트에 쓸 최근 1개월 종가 흐름
            "asof": asof,
            "invert_color": ticker in _INVERT_COLOR,  # 하락=긍정 색 표시
        }
    except Exception:
        # 야후가 일시적으로 막거나 티커가 잘못된 경우
        return None


@st.cache_data(ttl=1800)  # 30분 캐시 — pykrx 호출 비용 고려
def fetch_supply_demand_summary():
    """외국인·기관 순매수 상위 5종목 (최근 거래일).
    
    반환값: {
        "코스피": {"외국인": [("삼성전자", +1200), ...], "기관": [...], "date": "2024-01-15"},
        "코스닥": { ... }
    }
    실패 시 빈 dict 반환.
    """
    result = {}
    try:
        from pykrx import stock
        end = datetime.now()
        start = end - timedelta(days=10)
        start_str = start.strftime("%Y%m%d")
        end_str = end.strftime("%Y%m%d")

        for mkt, label in (("KOSPI", "코스피"), ("KOSDAQ", "코스닥")):
            try:
                df = stock.get_market_trading_value_by_ticker(
                    start_str, end_str, mkt
                )
                if df is None or df.empty:
                    continue

                frg_col = next((c for c in df.columns if "외국인" in c), None)
                ins_col = next((c for c in df.columns if "기관" in c), None)
                mkt_result = {"date": end_str[:4] + "-" + end_str[4:6] + "-" + end_str[6:]}

                for col_key, col in (("외국인", frg_col), ("기관", ins_col)):
                    if col is None:
                        continue
                    top = df.nlargest(5, col)
                    items = []
                    for ticker, row in top.iterrows():
                        try:
                            name = stock.get_market_ticker_name(ticker)
                        except Exception:
                            name = ticker
                        val = int(row[col] / 1e8)  # 억원
                        items.append((name, val))
                    mkt_result[col_key] = items

                result[label] = mkt_result
            except Exception:
                continue
    except Exception:
        pass
    return result


def sparkline_points(series, width=100, height=28, pad=3, n=20):
    """종가 흐름을 SVG polyline 좌표 문자열로 변환 (최근 n개)."""
    vals = list(series)[-n:]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    last = len(vals) - 1
    pts = []
    for i, v in enumerate(vals):
        x = (i / last) * width
        y = height - pad - ((v - lo) / rng) * (height - 2 * pad)
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


@st.cache_data(ttl=3600)
def fetch_history(ticker: str, period: str = "3mo"):
    """일별 종가 Series (정규화된 날짜 인덱스). 실패 시 None."""
    try:
        df = yf.Ticker(ticker).history(period=period, interval="1d")
        if df.empty:
            return None
        close = df["Close"].dropna()
        idx = close.index
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        close.index = idx.normalize()
        return close
    except Exception:
        return None
