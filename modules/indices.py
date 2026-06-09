"""주요 지수 데이터를 Yahoo Finance(yfinance)에서 가져오는 모듈."""

import yfinance as yf
import streamlit as st

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
        "엔/달러": "JPY=X",
        "달러 인덱스": "DX-Y.NYB",
    },
    "변동성·원자재": {
        "VIX": "^VIX",
        "금": "GC=F",
        "WTI 유가": "CL=F",
    },
}


@st.cache_data(ttl=600)  # 10분 동안 결과 재사용 -> 야후 과다 호출 방지
def fetch_index(ticker: str):
    """티커 1개의 현재값/등락/최근 추이를 가져온다. 실패하면 None을 반환."""
    try:
        df = yf.Ticker(ticker).history(period="1mo", interval="1d")
        if df.empty or len(df) < 2:
            return None

        close = df["Close"].dropna()
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
        }
    except Exception:
        # 야후가 일시적으로 막거나 티커가 잘못된 경우
        return None


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
