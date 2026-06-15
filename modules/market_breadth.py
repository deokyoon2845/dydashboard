"""시장 폭(Breadth) — 거래대금 + 등락 종목 수 (다음 금융).

pykrx가 클라우드(해외 IP)에서 차단되고, 네이버 지수 페이지는 등락 종목 수·거래대금이
JS로 렌더링되어 requests 파싱이 불안정했다. 다음(Daum) 금융은 같은 데이터를
순수 텍스트/JSON으로 제공해 파싱이 안정적이다.

2개 경로를 순서대로 시도하고, 둘 다 실패하면 None을 반환(섹션 생략):
  1) 다음 금융 내부 JSON API (finance.daum.net/api/...) — Referer 헤더 필요
  2) 다음 금융 모바일 페이지(m.finance.daum.net/domestic) 정규식 파싱

다음 모바일 페이지 텍스트 예시(코스피):
  "거래금 52,257,644백만 ... 상한가▲3 · 상승▲756 · 보합18 · 하락▼144 · 하한가▼0"
  → 거래대금 52,257,644백만원 = 522,576억, 상승 756 / 보합 18 / 하락 144
"""

import re

import requests
import streamlit as st

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_HEADERS_JSON = {
    "User-Agent": _UA,
    "Referer": "https://finance.daum.net/domestic",
    "Accept": "application/json, text/plain, */*",
}
_HEADERS_HTML = {"User-Agent": _UA}

# 다음 지수 심볼
_SYMBOL = {"코스피": "KOSPI", "코스닥": "KOSDAQ"}


def _to_int(x):
    try:
        v = re.sub(r"[^\d]", "", str(x))
        return int(v) if v else None
    except Exception:
        return None


# ── 경로 1: 다음 내부 JSON API ────────────────────────────────

def _fetch_via_api(symbol: str):
    """finance.daum.net 지수 JSON. 성공 시 dict, 실패 시 None."""
    candidates = [
        f"https://finance.daum.net/api/domestic/quotes/{symbol}",
        f"https://finance.daum.net/api/quotes/{symbol}",
    ]
    for u in candidates:
        try:
            r = requests.get(u, headers=_HEADERS_JSON, timeout=10)
            if r.status_code != 200:
                continue
            data = r.json()
        except Exception:
            continue

        # 응답 구조가 버전에 따라 다를 수 있어 방어적으로 키를 탐색
        d = data.get("data", data) if isinstance(data, dict) else data
        if not isinstance(d, dict):
            continue

        # 거래대금 (원). accTradePrice 또는 tradePrice 류
        val_won = None
        for k in ("accTradePrice", "tradePrice", "accTradeValue"):
            if d.get(k) not in (None, ""):
                try:
                    val_won = float(d[k])
                    break
                except Exception:
                    pass

        adv = _to_int(d.get("risingIssuesCount") or d.get("upCount"))
        flat = _to_int(d.get("unchangedIssuesCount") or d.get("flatCount"))
        dec = _to_int(d.get("fallingIssuesCount") or d.get("downCount"))

        if val_won is None and adv is None and dec is None:
            continue

        return {
            "value_eok": round(val_won / 1e8) if val_won else None,  # 원→억
            "advance": adv or 0,
            "flat": flat or 0,
            "decline": dec or 0,
            "asof": None,
        }
    return None


# ── 경로 2: 다음 모바일 페이지 정규식 파싱 ────────────────────

def _fetch_via_mobile(market_label: str):
    """m.finance.daum.net/domestic 텍스트에서 해당 시장 블록을 파싱."""
    try:
        r = requests.get("https://m.finance.daum.net/domestic",
                         headers=_HEADERS_HTML, timeout=12)
        text = r.text
    except Exception:
        return None

    # 시장명(코스피/코스닥) 이후 텍스트에서 가장 먼저 나오는 값들을 잡는다.
    start = text.find(market_label)
    seg = text[start:start + 4000] if start >= 0 else text

    result = {"value_eok": None, "advance": 0, "flat": 0, "decline": 0, "asof": None}

    # 거래금 52,257,644백만 → 백만원
    m = re.search(r"거래금\s*([\d,]+)\s*백만", seg)
    if m:
        millions = _to_int(m.group(1))
        if millions is not None:
            result["value_eok"] = round(millions / 100)  # 백만→억

    # 상승▲756 · 보합18 · 하락▼144
    mu = re.search(r"상승[▲\s]*([\d,]+)", seg)
    mf = re.search(r"보합[▬\s]*([\d,]+)", seg)
    md = re.search(r"하락[▼\s]*([\d,]+)", seg)
    if mu:
        result["advance"] = _to_int(mu.group(1)) or 0
    if mf:
        result["flat"] = _to_int(mf.group(1)) or 0
    if md:
        result["decline"] = _to_int(md.group(1)) or 0

    if result["value_eok"] is None and (result["advance"] + result["decline"]) == 0:
        return None
    return result


@st.cache_data(ttl=600)  # 10분 캐시
def fetch_breadth(market_label: str):
    """거래대금·등락 종목 수. API 우선, 실패 시 모바일 페이지. 모두 실패 시 None."""
    symbol = _SYMBOL.get(market_label)
    if symbol:
        via_api = _fetch_via_api(symbol)
        if via_api:
            return via_api
    return _fetch_via_mobile(market_label)


# ── 렌더링 ───────────────────────────────────────────────────

def _fmt_value(eok) -> str:
    """억원 → 보기 좋은 문자열. 1조 이상은 'X.X조' 병기."""
    if eok is None:
        return "—"
    if eok >= 10000:
        jo = eok / 10000.0
        return f"{eok:,}억 ({jo:,.1f}조)"
    return f"{eok:,}억"


def _breadth_bar_html(adv: int, flat: int, dec: int) -> str:
    total = adv + flat + dec
    if total <= 0:
        return ""
    a = adv / total * 100
    f = flat / total * 100
    dd = dec / total * 100
    segs = ""
    if a > 0:
        segs += f'<div class="breadth-seg-up" style="width:{a:.1f}%;">{adv:,}</div>'
    if f > 0:
        segs += (f'<div class="breadth-seg-flat" style="width:{f:.1f}%;">'
                 f'{flat if f > 6 else ""}</div>')
    if dd > 0:
        segs += f'<div class="breadth-seg-down" style="width:{dd:.1f}%;">{dec:,}</div>'
    return f'<div class="breadth-bar">{segs}</div>'


def _market_card(label: str, data) -> str:
    if not data:
        return (f'<div class="breadth-card">'
                f'<div class="breadth-mkt">{label}</div>'
                f'<div class="breadth-sub">데이터를 불러오지 못했어요.</div></div>')

    adv, flat, dec = data["advance"], data["flat"], data["decline"]
    val_html = (f'<div class="breadth-val">{_fmt_value(data["value_eok"])}</div>'
                f'<div class="breadth-sub">거래대금</div>')

    bar = _breadth_bar_html(adv, flat, dec)
    if bar:
        legend = (f'<div class="breadth-legend">'
                  f'<span><b class="up">▲ 상승</b> {adv:,}</span>'
                  f'<span>▬ 보합 {flat:,}</span>'
                  f'<span><b class="down">▼ 하락</b> {dec:,}</span></div>')
    else:
        bar, legend = "", '<div class="breadth-sub">등락 종목 수 정보 없음</div>'

    asof = f' · {data["asof"]}' if data.get("asof") else ""
    return (f'<div class="breadth-card">'
            f'<div class="breadth-mkt">{label}{asof}</div>'
            f'{val_html}'
            f'<div style="height:10px"></div>'
            f'{bar}{legend}</div>')


def render_market_breadth():
    """거래대금 + 등락 종목 수 (코스피·코스닥 2단)."""
    kospi = fetch_breadth("코스피")
    kosdaq = fetch_breadth("코스닥")

    if not kospi and not kosdaq:
        return  # 둘 다 실패하면 섹션 자체를 조용히 생략

    st.markdown('<div class="mkt-group">📊 거래대금 · 등락 종목 수</div>',
                unsafe_allow_html=True)
    cards = _market_card("코스피", kospi) + _market_card("코스닥", kosdaq)
    st.markdown(f'<div class="breadth-grid">{cards}</div>', unsafe_allow_html=True)
    st.caption("거래대금·등락 종목 수 · 데이터: 다음 금융 · 장중 약 15~20분 지연 · "
               "상승/보합/하락 막대는 전 종목 비율")
