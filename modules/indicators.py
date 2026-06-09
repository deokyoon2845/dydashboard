"""시장 지표(체온계): RSI · ADR(등락비율) · CNN 공포·탐욕 지수."""

import streamlit as st

from modules.indices import fetch_history

_RSI_TARGETS = {"코스피": "^KS11", "코스닥": "^KQ11", "S&P500": "^GSPC", "나스닥": "^IXIC"}

_RATING_KO = {
    "extreme fear": "극단적 공포", "fear": "공포", "neutral": "중립",
    "greed": "탐욕", "extreme greed": "극단적 탐욕",
}


def compute_rsi(ticker, period=14):
    """지수 종가로 RSI(기본 14). 실패 시 None."""
    close = fetch_history(ticker)
    if close is None or len(close) < period + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    g, l = avg_gain.iloc[-1], avg_loss.iloc[-1]
    if l == 0:
        return 100.0
    return float(100 - 100 / (1 + g / l))


@st.cache_data(ttl=1800)
def fetch_adr(market="KOSPI"):
    """등락비율 = 상승종목수/하락종목수×100 (pykrx). 가장 최근 거래일 기준."""
    try:
        from datetime import datetime, timedelta
        from pykrx import stock
        d = datetime.now()
        for _ in range(7):
            ds = d.strftime("%Y%m%d")
            df = stock.get_market_ohlcv(ds, market=market)
            if df is not None and not df.empty and "등락률" in df.columns:
                up = int((df["등락률"] > 0).sum())
                down = int((df["등락률"] < 0).sum())
                adr = round(up / down * 100, 1) if down else None
                return {"adr": adr, "up": up, "down": down, "date": ds}
            d -= timedelta(days=1)
    except Exception:
        return None
    return None


@st.cache_data(ttl=1800)
def fetch_cnn_fng():
    """CNN 공포·탐욕 지수(미국). 비공식 API."""
    try:
        import requests
        r = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                     "Accept": "application/json"},
            timeout=10,
        )
        r.raise_for_status()
        fg = r.json().get("fear_and_greed", {})
        if fg.get("score") is None:
            return None
        return {"score": round(float(fg["score"])), "rating": fg.get("rating", ""),
                "asof": _fng_asof(fg.get("timestamp"))}
    except Exception:
        return None


def _fng_asof(ts):
    """CNN timestamp(ISO 또는 ms)를 KST 'YYYY-MM-DD HH:MM'로."""
    if ts is None:
        return None
    try:
        from datetime import datetime, timezone, timedelta
        kst = timezone(timedelta(hours=9))
        if isinstance(ts, (int, float)):           # ms epoch
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        else:                                       # ISO 문자열
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt.astimezone(kst).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)[:16]


def _rsi_state(v):
    if v >= 70:
        return "과매수", "up"
    if v <= 30:
        return "과매도", "down"
    return "중립", ""


def _rsi_asof():
    """RSI 대상 지수들의 가장 최근 종가일 (YYYY-MM-DD)."""
    dates = []
    for tk in _RSI_TARGETS.values():
        c = fetch_history(tk)
        if c is not None and len(c):
            try:
                dates.append(c.index[-1].strftime("%Y-%m-%d"))
            except Exception:
                pass
    return max(dates) if dates else "—"


def _fmt_ymd(ds):
    """YYYYMMDD -> YYYY-MM-DD."""
    return f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}" if ds and len(ds) == 8 else (ds or "—")


def render_indicators():
    st.markdown('<div class="mkt-group">시장 지표 (체온계)</div>', unsafe_allow_html=True)

    # 공포·탐욕 지수
    fng = fetch_cnn_fng()
    if fng:
        ko = _RATING_KO.get((fng["rating"] or "").lower(), fng["rating"])
        asof = f' · 기준 {fng["asof"]} KST' if fng.get("asof") else ""
        st.markdown(
            f'<div class="mkt-card" style="margin-bottom:10px;">'
            f'<div class="mkt-name">공포·탐욕 지수 · CNN (미국 기준)</div>'
            f'<div style="display:flex;align-items:baseline;gap:8px;">'
            f'<span class="mkt-val">{fng["score"]}</span>'
            f'<span style="font-weight:700;color:var(--muted);">/ 100 · {ko}</span></div>'
            f'<div class="gauge"><i style="left:{fng["score"]}%"></i></div>'
            f'<div style="font-size:10.5px;color:var(--muted);">공포(파랑) ↔ 탐욕(빨강) · 비공식 API{asof}</div>'
            f'</div>', unsafe_allow_html=True)
    else:
        st.caption("공포·탐욕 지수를 불러오지 못했어요 (CNN 비공식 API).")

    # 등락비율 (코스피/코스닥)
    cards = []
    adr_date = None
    for mkt, label in (("KOSPI", "코스피 등락비율"), ("KOSDAQ", "코스닥 등락비율")):
        a = fetch_adr(mkt)
        if a and a["adr"] is not None:
            adr_date = adr_date or a.get("date")
            tone = "up" if a["adr"] >= 100 else "down"
            tint = "mkt-up" if tone == "up" else "mkt-down"
            cards.append(
                f'<div class="mkt-card {tint}"><div class="mkt-name">{label}</div>'
                f'<div class="mkt-val">{a["adr"]:.0f}</div>'
                f'<div class="mkt-chg {tone}">상승 {a["up"]} / 하락 {a["down"]}</div></div>')
        else:
            cards.append(f'<div class="mkt-card"><div class="mkt-name">{label}</div>'
                         f'<div class="mkt-na">데이터 없음</div></div>')
    st.markdown(f'<div class="mkt-grid">{"".join(cards)}</div>', unsafe_allow_html=True)
    if adr_date:
        st.markdown(f'<div class="grp-asof" style="margin:4px 0 0;">등락비율 기준 {_fmt_ymd(adr_date)} (KRX)</div>',
                    unsafe_allow_html=True)

    # RSI
    rcards = []
    for name, tk in _RSI_TARGETS.items():
        v = compute_rsi(tk)
        if v is None:
            rcards.append(f'<div class="mkt-card"><div class="mkt-name">{name} RSI</div>'
                          f'<div class="mkt-na">데이터 없음</div></div>')
            continue
        state, tone = _rsi_state(v)
        tint = {"up": "mkt-up", "down": "mkt-down", "": ""}[tone]
        pos = max(0, min(100, v))
        rcards.append(
            f'<div class="mkt-card {tint}"><div class="mkt-name">{name} RSI(14)</div>'
            f'<div style="display:flex;align-items:baseline;gap:6px;">'
            f'<span class="mkt-val">{v:.0f}</span>'
            f'<span class="mkt-chg {tone}" style="margin:0;">{state}</span></div>'
            f'<div class="rsi-gauge"><span class="t30"></span><span class="t70"></span>'
            f'<i class="{tone}" style="left:{pos}%"></i></div></div>')
    st.markdown('<div style="height:10px;"></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="mkt-grid">{"".join(rcards)}</div>', unsafe_allow_html=True)
    st.caption(f"RSI ≥70 과매수 · ≤30 과매도 (종가 14일 · 기준 {_rsi_asof()}). "
               "ADR=상승/하락 종목수 비율(100↑ 상승 우세). 데이터: yfinance·KRX·CNN.")
