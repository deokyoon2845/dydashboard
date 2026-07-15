"""주요 지수 데이터를 Yahoo Finance(yfinance)에서 가져오는 모듈.

2026-06 보강: 코스피·코스닥(^KS11·^KQ11)은 야후가 최근 거래일을 며칠씩 늦게 주는
  문제가 있어, 네이버 금융 일별 시세로 '최근 거래일 꼬리'를 보강한다.
  - fetch_index / fetch_history 가 한국 지수일 때만 _merge_naver_tail()을 거친다.
  - 네이버가 실패하면 기존 야후 데이터를 그대로 쓴다(무회귀, graceful degradation).

2026-06 추가: fetch_intraday(1일 차트)가 NXT(넥스트레이드)·시간외 데이터를 섞어
  마지막 값이 정규장 종가와 어긋나던 문제 수정.
  - 한국 지수는 정규장(09:00~15:30 KST)만 남긴다.
  - 헤더 현재값/전일 종가는 네이버 보강 일봉(공식 종가)으로 맞춰 카드·티커와 일치시킨다.
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

# 한국 정규장 시간 (NXT/시간외 데이터 제외용)
_KR_OPEN = dtime(9, 0)
_KR_CLOSE = dtime(15, 30)


# ── 장 운영시간 헬퍼 (자동 새로고침 기본값 판단용) ──────────────

def is_kr_market_open() -> bool:
    """한국 정규장(평일 09:00~15:30 KST) 여부.
    토·일은 휴장으로 처리. (공휴일은 별도 거르지 않음 — 필요 시 pykrx 영업일로 확장)
    """
    now = datetime.now(_KST) if _KST else datetime.now()
    if now.weekday() >= 5:  # 5=토, 6=일
        return False
    return _KR_OPEN <= now.time() <= _KR_CLOSE


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

        # 데이터의 실제 기준일 (마지막 거래일) — tz 문제를 피하려 문자열로 저장.
        # _bar_date: 야후 '자정 UTC 일봉' 왜곡 보정(미국 지수 기준일 D-1 라벨 버그 수정 · 2026-07)
        try:
            asof = _bar_date(close.index[-1]).strftime("%Y-%m-%d")
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


@st.cache_data(ttl=1800)  # 30분 캐시
def fetch_supply_demand_summary():
    """외국인·기관 거래대금 상위 5종목 (최근 거래일).

    ① Supabase market_flow(엔진 pykrx 수집, 클라우드에서도 동작)
    ② pykrx 직접(로컬 폴백).

    반환값: {
        "코스피": {"외국인": [("삼성전자", +1200), ...], "기관": [...], "date": "2024-01-15"},
        "코스닥": { ... }
    }
    실패 시 빈 dict 반환.
    """
    # ① Supabase 우선 — 엔진(engine/market_flow.py)이 적재한 최신 payload
    try:
        from modules import db
        if db.supabase_configured():
            payload = db.load_market_flow()
            if payload:
                # JSON 저장 시 (name, val)이 [name, val] 리스트로 오므로 튜플로 정규화
                out = {}
                for mkt, data in payload.items():
                    if not isinstance(data, dict):
                        continue
                row = {"date": data.get("date", "")}
                for col in ("외국인", "기관"):
                    items = data.get(col) or []
                    row[col] = [(str(it[0]), it[1]) for it in items if isinstance(it, (list, tuple)) and len(it) >= 2]
                out[mkt] = row
                if out:
                    return out
    except Exception:
        pass

    # ② pykrx 폴백(로컬/엔진)
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


def _biweekly_ticks(dates):
    """오름차순 Timestamp 리스트에서 보름(15일) 간격 눈금의 (index, date) 목록.

    마지막 날짜에서 15일씩 거슬러 올라가며 각 시점에 '가장 가까운 거래일'을
    찾아 인덱스로 매핑한다(거래일은 보통 ~10영업일이 보름에 해당)."""
    if len(dates) < 2:
        return []
    first, last = dates[0], dates[-1]
    raw, t = [], last
    while t >= first:
        raw.append(t)
        t = t - pd.Timedelta(days=15)
    raw.reverse()
    seen, ticks = set(), []
    for tk in raw:
        best, bd = 0, None
        for i, d in enumerate(dates):
            diff = abs((d - tk).days)
            if bd is None or diff < bd:
                bd, best = diff, i
        if best not in seen:
            seen.add(best)
            ticks.append((best, dates[best]))
    return ticks


def sparkline_axis_html(series, color, height=38, n_days=92, label_color=None):
    """3개월 추이 미니차트(B안): 면적+선 + 하단 보름 눈금 + 월 라벨(HTML).

    series : 날짜(DatetimeIndex) 종가/수익률 Series
    color  : 선·면 색 / label_color : 축 라벨 색(없으면 color)
    반환    : '<div class="spark-wrap">…svg…axis…</div>' · 데이터 부족 시 ''.
    날짜 인덱스가 아니면 축 없이 단순 스파크라인만 그린다(무회귀)."""
    if series is None:
        return ""
    try:
        s = series.dropna()
    except Exception:
        return ""
    if len(s) < 2:
        return ""

    # 최근 n_days(달력일)로 슬라이스
    if isinstance(s.index, pd.DatetimeIndex):
        try:
            cutoff = s.index.max() - pd.Timedelta(days=n_days)
            s = s[s.index >= cutoff]
        except Exception:
            pass
    if len(s) < 2:
        return ""

    vals = [float(v) for v in s.values]
    n = len(vals)
    last = n - 1
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    pad = 3.0
    pts = " ".join(
        f"{(i / last * 100):.1f},"
        f"{(height - pad - ((v - lo) / rng) * (height - 2 * pad)):.1f}"
        for i, v in enumerate(vals)
    )
    label_color = label_color or color

    # 보름 눈금 + 월 라벨 (날짜 인덱스가 있을 때만)
    tick_svg, axis_html = "", ""
    if isinstance(s.index, pd.DatetimeIndex):
        dates = []
        for d in s.index:
            ts = pd.Timestamp(d)
            if ts.tzinfo is not None:
                ts = ts.tz_localize(None)
            dates.append(ts)
        ticks = _biweekly_ticks(dates)
        if ticks:
            marks = ""
            for idx_i, _d in ticks:
                x = idx_i / last * 100
                marks += (f'<line x1="{x:.1f}" y1="{height - 3.2:.1f}" '
                          f'x2="{x:.1f}" y2="{height}" stroke="{color}" '
                          f'stroke-width="0.9" opacity="0.5"/>')
            tick_svg = marks
            seen_m, spans = set(), ""
            for k, (idx_i, d) in enumerate(ticks):
                if d.month in seen_m:
                    continue
                seen_m.add(d.month)
                x = idx_i / last * 100
                cls = ' class="first"' if (k == 0 or x < 6) else (
                    ' class="last"' if x > 92 else "")
                spans += (f'<span{cls} style="left:{x:.1f}%;color:{label_color}">'
                          f'{d.month}월</span>')
            if spans:
                axis_html = f'<div class="spark-axis">{spans}</div>'

    svg = (f'<svg class="heat-spark" viewBox="0 0 100 {height}" '
           f'preserveAspectRatio="none" style="height:{height}px;margin-top:0;">'
           f'<polygon points="{pts} 100,{height} 0,{height}" '
           f'style="fill:{color};opacity:.12"/>'
           f'<polyline points="{pts}" '
           f'style="fill:none;stroke:{color};stroke-width:1.6;opacity:.7"/>'
           f'{tick_svg}</svg>')
    return f'<div class="spark-wrap">{svg}{axis_html}</div>'


@st.cache_data(ttl=3600)
def _bar_date(ts):
    """일봉 타임스탬프 → 날짜(tz-naive Timestamp, 자정).

    야후가 일봉을 '자정 UTC'로 찍은 뒤 거래소 tz로 변환해 주는 경우가 있어,
    미국(-4/-5h) 지수는 벽시계가 전일 저녁(19~20시)으로 밀려 기준일이 하루
    당겨 보이는 왜곡이 생긴다(값은 최신인데 라벨만 D-1 · 2026-07 관찰).
    정상적인 일봉은 자정(00:00) 또는 장 시작(09:00~09:30)에 찍히므로,
    'tz-aware + 저녁(17시 이후)' 조합만 다음 날로 롤포워드하면 안전하다.
    한국(+9h)은 자정 UTC → 09:00 KST라 이 보정의 영향을 받지 않는다."""
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        if t.hour >= 17:
            t = t + pd.Timedelta(days=1)
        t = t.tz_localize(None)
    return t.normalize()


def fetch_history(ticker: str, period: str = "3mo"):
    """일별 종가 Series (정규화된 날짜 인덱스). 실패 시 None.
    한국 지수는 네이버로 최근 거래일을 보강한다(야후 지연 대응)."""
    close = None
    try:
        df = yf.Ticker(ticker).history(period=period, interval="1d")
        if not df.empty:
            close = df["Close"].dropna()
            # tz 스트립 + 자정 UTC 왜곡 보정(_bar_date) — 미국 지수 기준일 D-1 라벨 수정
            close.index = pd.DatetimeIndex([_bar_date(t) for t in close.index])
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
    - 한국 지수(^KS11·^KQ11)는 정규장(09:00~15:30 KST)만 남기고
      NXT(넥스트레이드)·시간외 단일가 데이터를 제외한다.
    - 한국 지수의 헤더 현재값/전일 종가는 네이버 보강 일봉(공식 종가)으로 맞춰
      티커테이프·카드와 동일한 값이 되도록 보정한다.

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

        is_kr = ticker in _KR_NAVER_SYMBOL

        # 가장 최근 거래일 하루치만 추출
        last_day = close.index[-1].date()
        day_series = close[[d.date() == last_day for d in close.index]]

        # ── 한국 지수: 정규장(09:00~15:30 KST)만 — NXT/시간외 제외 ──
        if is_kr and len(day_series) >= 1:
            reg = day_series[[_KR_OPEN <= t.time() <= _KR_CLOSE
                              for t in day_series.index]]
            if len(reg) >= 2:
                day_series = reg

        if len(day_series) < 2:
            # 하루치가 너무 적으면 전체 분봉이라도 반환
            day_series = close

        current = float(day_series.iloc[-1])

        # ── 전일 종가(base) 및 당일 헤더값 보정 ──
        base = None
        if is_kr:
            # 네이버 보강 일봉으로 전일 종가 확보 + 당일 헤더값을 공식 종가로 보정.
            # (장중이면 당일 공식 종가가 아직 없어 same 매칭 실패 → 현재값은
            #  정규장 마지막 분봉값을 그대로 사용한다.)
            daily_kr = fetch_history(ticker, "1mo")
            if daily_kr is not None and len(daily_kr):
                dts = [ix.date() for ix in daily_kr.index]
                same = [i for i, dd in enumerate(dts) if dd == last_day]
                if same:
                    current = float(daily_kr.iloc[same[-1]])  # 공식 종가로 헤더 보정
                prev_idx = [i for i, dd in enumerate(dts) if dd < last_day]
                if prev_idx:
                    base = float(daily_kr.iloc[prev_idx[-1]])

        if base is None:
            # 해외 지수 등: yfinance 일봉에서 last_day 직전 거래일 종가 = 전일 종가
            try:
                daily = yf.Ticker(ticker).history(period="7d", interval="1d")
                if not daily.empty:
                    dclose = daily["Close"].dropna()
                    if scale != 1.0:
                        dclose = dclose * scale
                    dates = [ix.date() for ix in dclose.index]
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
