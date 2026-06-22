"""[엔진] 정량 시장 스냅샷 — AI 리포트 분석에 주입할 '실제 시장 데이터'.

채널의 '의견'을 실제 지수·수급·과열도 데이터와 교차 검증할 수 있게 합니다.
각 항목은 독립적으로 실패해도 나머지는 수집됩니다 (스트림릿 의존 없음).
"""

from datetime import datetime, timedelta
import json

import requests

_INDEX_TARGETS = {
    "코스피": "^KS11", "코스닥": "^KQ11",
    "S&P500": "^GSPC", "나스닥": "^IXIC", "필라델피아 반도체": "^SOX",
    "원/달러": "KRW=X", "VIX": "^VIX",
}
_RSI_TARGETS = {"코스피": "^KS11", "코스닥": "^KQ11", "나스닥": "^IXIC"}

# 야후 티커 → 네이버 금융 지수 심볼 (한국 지수 공식 종가 보정용)
_KR_NAVER_SYMBOL = {"^KS11": "KOSPI", "^KQ11": "KOSDAQ"}

# 미국 섹터 ETF — 간밤 미국장 흐름 파악용
_US_SECTOR_TARGETS = {
    "기술(XLK)": "XLK",
    "반도체(SOXX)": "SOXX",
    "에너지(XLE)": "XLE",
    "금융(XLF)": "XLF",
    "헬스케어(XLV)": "XLV",
    "미 10년물 금리": "^TNX",
}


def _history(ticker, period="3mo"):
    import yfinance as yf
    df = yf.Ticker(ticker).history(period=period, interval="1d")
    return df["Close"].dropna()


def _naver_kr_daily(symbol: str) -> list:
    """네이버 금융에서 코스피/코스닥 최근(약 40일) 일별 (날짜ISO, 종가)를 오래된→최신 순으로.
    symbol: 'KOSPI'|'KOSDAQ'. 실패 시 [].

    ★야후(^KS11·^KQ11) 일봉은 최근 거래일을 며칠씩 늦게 주거나 엉뚱한 종가를 주는 일이
      잦아, 마지막 두 종가를 차분하면 등락률이 크게 틀어진다(예: 코스닥 -3% → -6%대).
      KRX 공식 종가는 네이버가 클라우드에서도 안정적으로 주므로 이걸로 등락률을 계산한다.
      (뷰어 modules/indices.py의 _merge_naver_tail과 동일한 소스 — 엔진은 streamlit 비의존이라
       별도 구현.)"""
    try:
        end = datetime.now()
        start = end - timedelta(days=40)
        url = ("https://api.finance.naver.com/siseJson.naver"
               f"?symbol={symbol}&requestType=1"
               f"&startTime={start:%Y%m%d}&endTime={end:%Y%m%d}&timeframe=day")
        r = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        # 헤더 행에 작은따옴표가 섞여 옴 → 큰따옴표로 치환 후 파싱
        rows = json.loads(r.text.strip().replace("'", '"'))
        out = []
        for row in rows[1:]:  # 0번째는 헤더(['날짜','시가',...])
            if not row or len(row) < 5:
                continue
            d = str(row[0]).strip()
            if len(d) < 8:
                continue
            try:
                out.append((f"{d[:4]}-{d[4:6]}-{d[6:8]}", float(row[4])))  # 종가
            except (ValueError, TypeError):
                continue
        out.sort(key=lambda x: x[0])
        return out
    except Exception:
        return []


def fetch_index_lines():
    lines = []
    for name, tk in _INDEX_TARGETS.items():
        line = None
        # 코스피·코스닥: 야후 일봉이 부정확/지연 → 네이버 공식 종가로 등락률 계산.
        if tk in _KR_NAVER_SYMBOL:
            daily = _naver_kr_daily(_KR_NAVER_SYMBOL[tk])
            if len(daily) >= 2:
                prev = daily[-2][1]
                d_iso, cur = daily[-1]
                pct = (cur / prev - 1) * 100 if prev else 0.0
                d = f"{d_iso[5:7]}/{d_iso[8:10]}"
                line = f"- {name}: {cur:,.2f} ({pct:+.2f}%, {d} 종가)"
        # 네이버 실패(또는 해외 지수)면 야후로 폴백 — 무회귀.
        if line is None:
            try:
                close = _history(tk, "10d")
                if len(close) < 2:
                    continue
                cur, prev = float(close.iloc[-1]), float(close.iloc[-2])
                pct = (cur / prev - 1) * 100
                d = close.index[-1].strftime("%m/%d")
                line = f"- {name}: {cur:,.2f} ({pct:+.2f}%, {d} 종가)"
            except Exception:
                continue
        lines.append(line)
    return lines


def fetch_us_sector_lines():
    """간밤 미국장 섹터 ETF 및 금리 등락 (최근 거래일 기준)."""
    lines = []
    for name, tk in _US_SECTOR_TARGETS.items():
        try:
            close = _history(tk, "10d")
            if len(close) < 2:
                continue
            cur, prev = float(close.iloc[-1]), float(close.iloc[-2])
            pct = (cur / prev - 1) * 100
            d = close.index[-1].strftime("%m/%d")
            # 금리는 포인트(bp) 단위로 표기
            if tk == "^TNX":
                diff = cur - prev
                lines.append(f"- {name}: {cur:.2f}% ({diff:+.2f}bp, {d})")
            else:
                lines.append(f"- {name}: {cur:.2f} ({pct:+.2f}%, {d})")
        except Exception:
            continue
    return lines


def fetch_rsi_lines():
    lines = []
    for name, tk in _RSI_TARGETS.items():
        try:
            close = _history(tk)
            if len(close) < 15:
                continue
            delta = close.diff()
            gain = delta.clip(lower=0)
            loss = (-delta).clip(lower=0)
            ag = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean().iloc[-1]
            al = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean().iloc[-1]
            rsi = 100.0 if al == 0 else float(100 - 100 / (1 + ag / al))
            state = "과매수" if rsi >= 70 else ("과매도" if rsi <= 30 else "중립")
            lines.append(f"- {name} RSI(14): {rsi:.0f} ({state})")
        except Exception:
            continue
    return lines


def fetch_adr_lines():
    lines = []
    try:
        from pykrx import stock
        d = datetime.now()
        for _ in range(7):
            ds = d.strftime("%Y%m%d")
            done = []
            for mkt, label in (("KOSPI", "코스피"), ("KOSDAQ", "코스닥")):
                try:
                    df = stock.get_market_ohlcv(ds, market=mkt)
                    if df is not None and not df.empty and "등락률" in df.columns:
                        up = int((df["등락률"] > 0).sum())
                        down = int((df["등락률"] < 0).sum())
                        adr = (up / down * 100) if down else 0
                        done.append(f"- {label} 등락비율(ADR): {adr:.0f} (상승 {up} / 하락 {down}, {ds[:4]}-{ds[4:6]}-{ds[6:]} 기준)")
                except Exception:
                    continue
            if done:
                return done
            d -= timedelta(days=1)
    except Exception:
        pass
    return lines


def fetch_supply_demand_lines():
    """외국인·기관 순매수 (최근 거래일, 억원)."""
    lines = []
    try:
        from pykrx import stock
        end = datetime.now()
        start = end - timedelta(days=10)
        for mkt, label in (("KOSPI", "코스피"), ("KOSDAQ", "코스닥")):
            try:
                df = stock.get_market_trading_value_by_date(
                    start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), mkt)
                if df is None or df.empty:
                    continue
                row = df.iloc[-1]
                ds = df.index[-1].strftime("%Y-%m-%d") if hasattr(df.index[-1], "strftime") else ""
                frg_col = next((c for c in df.columns if "외국인" in c), None)
                ins_col = next((c for c in df.columns if "기관" in c), None)
                parts = []
                if frg_col is not None:
                    parts.append(f"외국인 {row[frg_col]/1e8:+,.0f}억")
                if ins_col is not None:
                    parts.append(f"기관 {row[ins_col]/1e8:+,.0f}억")
                if parts:
                    lines.append(f"- {label} 수급({ds}): " + " · ".join(parts))
            except Exception:
                continue
    except Exception:
        pass
    return lines


def fetch_top_supply_demand_lines():
    """외국인·기관 순매수 상위 5종목 (최근 거래일, 억원).
    
    AI 프롬프트에 '실제 수급이 붙은 종목' 정보로 주입됩니다.
    """
    lines = []
    try:
        from pykrx import stock
        end = datetime.now()
        start = end - timedelta(days=10)

        for mkt, label in (("KOSPI", "코스피"), ("KOSDAQ", "코스닥")):
            try:
                # 종목별 투자자별 순매수 금액
                df = stock.get_market_trading_value_by_ticker(
                    start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), mkt
                )
                if df is None or df.empty:
                    continue

                frg_col = next((c for c in df.columns if "외국인" in c), None)
                ins_col = next((c for c in df.columns if "기관" in c), None)

                if frg_col is not None:
                    top = df.nlargest(5, frg_col)
                    names = []
                    for ticker, row in top.iterrows():
                        try:
                            name = stock.get_market_ticker_name(ticker)
                        except Exception:
                            name = ticker
                        val = row[frg_col] / 1e8
                        names.append(f"{name}({val:+,.0f}억)")
                    if names:
                        lines.append(f"- {label} 외국인 순매수 상위: " + ", ".join(names))

                if ins_col is not None:
                    top = df.nlargest(5, ins_col)
                    names = []
                    for ticker, row in top.iterrows():
                        try:
                            name = stock.get_market_ticker_name(ticker)
                        except Exception:
                            name = ticker
                        val = row[ins_col] / 1e8
                        names.append(f"{name}({val:+,.0f}억)")
                    if names:
                        lines.append(f"- {label} 기관 순매수 상위: " + ", ".join(names))

            except Exception:
                continue
    except Exception:
        pass
    return lines


def build_snapshot_text() -> str:
    """주입용 정량 스냅샷 텍스트. 수집 실패 항목은 자동 생략."""
    blocks = []

    idx = fetch_index_lines()
    if idx:
        blocks.append("[주요 지수·환율 — 직전 거래일 종가 기준]\n" + "\n".join(idx))

    us_sector = fetch_us_sector_lines()
    if us_sector:
        blocks.append("[간밤 미국장 섹터 흐름 — 직전 거래일 기준]\n" + "\n".join(us_sector))

    sd = fetch_supply_demand_lines()
    if sd:
        blocks.append("[투자자 수급]\n" + "\n".join(sd))

    top_sd = fetch_top_supply_demand_lines()
    if top_sd:
        blocks.append("[수급 상위 종목 (외국인·기관 순매수 Top5)]\n" + "\n".join(top_sd))

    adr = fetch_adr_lines()
    if adr:
        blocks.append("[시장 폭(breadth)]\n" + "\n".join(adr))

    rsi = fetch_rsi_lines()
    if rsi:
        blocks.append("[과열/침체 지표]\n" + "\n".join(rsi))

    return "\n\n".join(blocks)
