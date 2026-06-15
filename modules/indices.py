"""주요 지수 데이터를 Yahoo Finance(yfinance)에서 가져오는 모듈.

2026-06 보강: 코스피·코스닥(^KS11·^KQ11)은 야후가 최근 거래일을 며칠씩 늦게 주는
  문제가 있어, 네이버 금융 일별 시세로 '최근 거래일 꼬리'를 보강한다.
  - fetch_index / fetch_history 가 한국 지수일 때만 _merge_naver_tail()을 거친다.
  - 네이버가 실패하면 기존 야후 데이터를 그대로 쓴다(무회귀, graceful degradation).
"""

import json
import yfinance as yf
import pandas as pd
import requests
import streamlit as st
from datetime import datetime, timedelta, time as dtime

try:
    from zoneinfo import ZoneInfo
    _KST = ZoneInfo("Asia/Seoul")
except Exception:  # 파이썬<3.9 등 폴백
    _KST = None

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
        "달러 인덱스": "DX-Y.NYB",
    },
    "변동성·원자재": {
        # VIX는 시장 지표(체온계) 섹션에서 별도 차트로 표시 → 여기서는 제외
        "금 ($/oz)": "GC=F",
        "은 ($/oz)": "SI=F",
        "구리 ($/lb)": "HG=F",
        "WTI 유가 ($/bbl)": "CL=F",
    },
    "암호화폐": {
        # 달러($) 기준 · 24시간 거래 (업비트 원화 시세와는 다를 수 있음)
        "비트코인 ($)": "BTC-USD",
        "이더리움 ($)": "ETH-USD",
    },
}

# 표시 배율: 100엔당 원화 표기를 위해 JPYKRW=X 는 ×100
_SCALE = {"JPYKRW=X": 100.0}

# 색 반전 티커: 하락이 시장에 '긍정'인 지표 (예: 공포지수 VIX)
_INVERT_COLOR = {"^VIX"}

# 조회 기간 (기본 1개월, 국내 지수는 6개월 추세를 카드에 표시)
_PERIOD = {"^KS11": "6mo", "^KQ11": "6mo"}

# 야후 티커 → 네이버 금융 지수 심볼 (한국 지수 최근일 보강용)
_KR_NAVER_SYMBOL = {"^KS11": "KOSPI", "^KQ11": "KOSDAQ"}


# ── 장 운영시간 헬퍼 (자동 새로고침 기본값 판단용) ──────────────

def is_kr_market_open() -> bool:
    """한국 정규장(평일 09:00~15:30 KST) 여부.
    토·일은 휴장으로 처리. (공휴일은 별도 거르지 않음 — 필요 시 pykrx 영업일로 확장)
    """
    now = datetime.now(_KST) if _KST else datetime.now()
    if now.weekday() >= 5:  # 5=토, 6=일
        return False
    return dtime(9, 0) <= now.time() <= dtime(15, 30)


# ── 한국 지수 네이버 보강 ───────────────────────────────────────
# 야후(yfinance)는 ^KS11·^KQ11의 가장 최근 거래일을 며칠씩 늦게 주는 일이 잦다
# (미국 지수는 정상). 그래서 코스피·코스닥 최근 종가를 네이버 금융 일별 시세로
# 받아와 야후 시계열의 '꼬리'를 보강한다. 네이버는 클라우드에서도 안정적으로 응답.

@st.cache_data(ttl=600)  # 10분 캐시 — 네이버 과다 호출 방지
def _kr_index_recent_naver(symbol: str) -> dict:
    """네이버 금융에서 코스피/코스닥 최근(약 한 달치) 일별 종가를 가져온다.
    symbol: 'KOSPI' | 'KOSDAQ'. 반환: {'YYYY-MM-DD': 종가(float)} · 실패 시 {}."""
    try:
        end = datetime.now(_KST) if _KST else datetime.now()
        start = end - timedelta(days=40)
        url = ("https://api.finance.naver.com/siseJson.naver"
               f"?symbol={symbol}&requestType=1"
               f"&startTime={start:%Y%m%d}&endTime={end:%Y%m%d}&timeframe=day")
        r = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        # 응답이 표준 JSON이 아니라 헤더 행에 작은따옴표가 섞여 옴 → 큰따옴표로 치환 후 파싱
        rows = json.loads(r.text.strip().replace("'", '"'))
        out = {}
        for row in rows[1:]:  # 0번째 행은 헤더(['날짜','시가',...])
            if not row or len(row) < 5:
                continue
            d = str(row[0]).strip()
            if len(d) < 8:
                continue
            try:
                key = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
                out[key] = float(row[4])  # 종가
            except (ValueError, TypeError):
                continue
        return out
    except Exception:
        return {}


def _merge_naver_tail(close, ticker: str):
    """야후 종가 Series에 네이버 최근 종가를 병합해 최근 거래일을 보강한다.
    한국 지수(^KS11·^KQ11)에만 적용 · 그 외 티커는 원본을 그대로 반환.
    실패하면 원본(close)을 그대로 돌려줘 무회귀를 보장한다."""
    sym = _KR_NAVER_SYMBOL.get(ticker)
    if not sym:
        return close
    recent = _kr_index_recent_naver(sym)
    if not recent:
        return close
    try:
        merged = {}
        if close is not None:
            for ts, v in close.items():
                t = pd.Timestamp(ts)
                if t.tzinfo is not None:
                    t = t.tz_localize(None)
                merged[t.normalize()] = float(v)
        for k, v in recent.items():
            merged[pd.Timestamp(k)] = float(v)  # 네이버가 최신 → 우선 반영
        if not merged:
            return close
        return pd.Series(merged).sort_index()
    except Exception:
        return close


@st.cache_data(ttl=600)  # 10분 동안 결과 재사용 -> 야후 과다 호출 방지
def fetch_index(ticker: str):
    """티커 1개의 현재값/등락/최근 추이를 가져온다. 실패하면 None을 반환."""
    try:
        period = _PERIOD.get(ticker, "1mo")
        df = yf.Ticker(ticker).history(period=period, interval="1d")
        if df.empty or len(df) < 2:
            return None

        close = df["Close"].dropna()

        # 표시 배율 적용 (예: 원/100엔)
        scale = _SCALE.get(ticker, 1.0)
        if scale != 1.0:
            close = close * scale

        # 한국 지수(코스피·코스닥): 야후가 최근 거래일을 늦게 주므로 네이버로 보강
        close = _merge_naver_tail(close, ticker)
        if close is None or len(close) < 2:
            return None

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
            "series": close,  # 차트에 쓸 종가 흐름 (기간은 _PERIOD 기준)
            "asof": asof,
            "invert_color": ticker in _INVERT_COLOR,  # 하락=긍정 색 표시
            "spark_n": 130 if period == "6mo" else 20,  # 카드 차트에 쓸 포인트 수
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
    """일별 종가 Series (정규화된 날짜 인덱스). 실패 시 None.
    한국 지수는 네이버로 최근 거래일을 보강한다(야후 지연 대응)."""
    close = None
    try:
        df = yf.Ticker(ticker).history(period=period, interval="1d")
        if not df.empty:
            close = df["Close"].dropna()
            idx = close.index
            if getattr(idx, "tz", None) is not None:
                idx = idx.tz_localize(None)
            close.index = idx.normalize()
    except Exception:
        close = None

    # 한국 지수(^KS11·^KQ11)면 네이버 최근 종가로 꼬리 보강
    merged = _merge_naver_tail(close, ticker)
    if merged is not None and len(merged):
        return merged
    return close


@st.cache_data(ttl=120)  # 장중 갱신을 위해 2분 캐시 (일봉보다 짧게)
def fetch_intraday(ticker: str, interval: str = "5m"):
    """당일(휴장 시 직전 거래일) 분봉 종가 Series.

    1일 차트용. yfinance 분봉을 받아 '가장 최근 거래일 하루치'만 잘라 반환한다.
    - 당일 데이터가 비어 있으면(개장 전·휴장) 최근 5일에서 마지막 거래일을 사용.
    - 인덱스는 KST(tz-naive)로 변환해 시:분이 그대로 보이게 한다.

    반환: {"series": pd.Series(시각→종가), "asof": "YYYY-MM-DD",
           "current": float, "change": float, "pct": float,
           "prev_close": float|None, "base_is_prev": bool}  실패 시 None.
    등락(change·pct)은 '전일 종가' 대비로 계산하며, 전일 종가를 못 구하면
    당일 시가로 폴백한다(base_is_prev=False).
    """
    try:
        # 최근 5거래일 범위를 받아 안전하게 마지막 거래일만 슬라이스
        df = yf.Ticker(ticker).history(period="5d", interval=interval)
        if df.empty:
            # 분봉이 막힌 티커 폴백: 1분봉 1일 재시도
            df = yf.Ticker(ticker).history(period="1d", interval="1m")
        if df.empty:
            return None

        close = df["Close"].dropna()
        if close.empty:
            return None

        # 인덱스를 KST로 변환 (분봉은 보통 tz-aware로 옴)
        idx = close.index
        try:
            if getattr(idx, "tz", None) is not None and _KST is not None:
                idx = idx.tz_convert(_KST).tz_localize(None)
            elif getattr(idx, "tz", None) is not None:
                idx = idx.tz_localize(None)
        except Exception:
            pass
        close.index = idx

        # 표시 배율 적용 (예: 원/100엔)
        scale = _SCALE.get(ticker, 1.0)
        if scale != 1.0:
            close = close * scale

        # 가장 최근 거래일 하루치만 추출
        last_day = close.index[-1].date()
        day_series = close[[d.date() == last_day for d in close.index]]
        if len(day_series) < 2:
            # 하루치가 너무 적으면 전체 분봉이라도 반환
            day_series = close

        current = float(day_series.iloc[-1])

        # 1일 등락 기준 = '전일 종가' 대비 (시가 대비가 아님).
        # 일봉을 별도로 받아 last_day 직전 거래일의 종가를 base로 사용한다.
        base = None
        try:
            daily = yf.Ticker(ticker).history(period="7d", interval="1d")
            if not daily.empty:
                dclose = daily["Close"].dropna()
                # 배율 동일 적용
                if scale != 1.0:
                    dclose = dclose * scale
                # 인덱스를 날짜로 비교 (tz 영향 제거)
                dates = [ix.date() for ix in dclose.index]
                # last_day 이전(미만)의 가장 마지막 종가 = 전일 종가
                prev_idx = [i for i, dd in enumerate(dates) if dd < last_day]
                if prev_idx:
                    base = float(dclose.iloc[prev_idx[-1]])
        except Exception:
            base = None

        # 전일 종가를 못 구하면 당일 첫 분봉(시가)으로 안전 폴백
        base_is_prev = base is not None
        if base is None:
            base = float(day_series.iloc[0])

        change = current - base
        pct = (change / base) * 100 if base else 0.0

        return {
            "series": day_series,
            "asof": last_day.strftime("%Y-%m-%d"),
            "current": current,
            "change": change,
            "pct": pct,
            "prev_close": base if base_is_prev else None,
            "base_is_prev": base_is_prev,  # True면 전일 종가 기준, False면 시가 폴백
            "invert_color": ticker in _INVERT_COLOR,
        }
    except Exception:
        return None
