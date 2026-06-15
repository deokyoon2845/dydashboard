"""시장 폭(Breadth) — 거래대금 + 등락 종목 수.

pykrx가 클라우드(해외 IP)에서 차단되어 외부 페이지 스크래핑으로 대체한다.
소스를 순서대로 시도하고, 모두 실패하면 None(섹션 생략):
  1) 네이버 지수 일별 시세 페이지 (거래대금) + 네이버 sise 메인 (등락 종목 수)
  2) 다음(Daum) 금융 모바일 페이지 (거래대금 + 등락 종목 수)

DEBUG=True로 두면 실패 시 화면에 진단 정보를 표시한다(원인 파악용).
원인 확인이 끝나면 DEBUG=False로 되돌린다.
"""

import re

import requests
import streamlit as st

DEBUG = True  # ← 진단이 끝나면 False로 변경

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_HEADERS = {"User-Agent": _UA}
_HEADERS_DAUM = {
    "User-Agent": _UA,
    "Referer": "https://finance.daum.net/domestic",
    "Accept": "application/json, text/plain, */*",
}

_NAVER_CODE = {"코스피": "KOSPI", "코스닥": "KOSDAQ"}
_DAUM_SYMBOL = {"코스피": "KOSPI", "코스닥": "KOSDAQ"}

# 진단 로그 (DEBUG일 때 화면에 표시)
_diag = []


def _log(msg):
    if DEBUG:
        _diag.append(str(msg))


def _to_int(x):
    try:
        v = re.sub(r"[^\d]", "", str(x))
        return int(v) if v else None
    except Exception:
        return None


# ── 소스 1-a: 네이버 지수 일별 시세 (거래대금) ────────────────

def _naver_trade_value(market_label: str):
    """finance.naver.com/sise/sise_index_day.naver — 일별 거래대금(백만원).
    최근 행의 '거래대금' 컬럼을 억원으로 환산해 반환. 실패 시 None."""
    code = _NAVER_CODE.get(market_label)
    if not code:
        return None
    url = f"https://finance.naver.com/sise/sise_index_day.naver?code={code}"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=12)
        r.encoding = "euc-kr"
        html = r.text
    except Exception as e:
        _log(f"[naver value] 요청 실패: {e}")
        return None

    # 일별 표의 숫자들. '거래대금' 헤더가 있고 행마다 천 단위 숫자가 늘어선다.
    # 가장 최근(첫) 데이터 행의 거래대금(백만원)을 잡는다.
    try:
        import pandas as pd
        from io import StringIO
        tables = pd.read_html(StringIO(html))
        for tb in tables:
            cols = [str(c) for c in tb.columns]
            val_col = next((c for c in cols if "거래대금" in c), None)
            if val_col is None:
                continue
            ser = tb[val_col].dropna()
            for v in ser:
                millions = _to_int(v)
                if millions and millions > 1000:  # 의미있는 값
                    return round(millions / 100)  # 백만→억
        _log("[naver value] 거래대금 컬럼/값 없음")
    except Exception as e:
        _log(f"[naver value] 파싱 실패: {e}")
    return None


# ── 소스 1-b: 네이버 sise 메인 (등락 종목 수) ─────────────────

def _naver_updown(market_label: str):
    """finance.naver.com/sise/ — 상승/보합/하락 종목 수. 실패 시 (0,0,0)."""
    # 코스피/코스닥 각각 별도 영역. 메인 페이지 텍스트에서 라벨 근처 숫자.
    url = "https://finance.naver.com/sise/"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=12)
        r.encoding = "euc-kr"
        html = r.text
    except Exception as e:
        _log(f"[naver updown] 요청 실패: {e}")
        return 0, 0, 0

    start = html.find(market_label)
    seg = html[start:start + 6000] if start >= 0 else html
    up = re.search(r"상승[^\d]{0,30}?([\d,]+)", seg)
    flat = re.search(r"보합[^\d]{0,30}?([\d,]+)", seg)
    down = re.search(r"하락[^\d]{0,30}?([\d,]+)", seg)
    u = _to_int(up.group(1)) if up else 0
    f = _to_int(flat.group(1)) if flat else 0
    d = _to_int(down.group(1)) if down else 0
    # 한 자릿수만 잡히면(=잘못 파싱) 무효 처리
    if (u or 0) + (d or 0) < 2:
        _log(f"[naver updown] 비정상 값 up={u} flat={f} down={d}")
        return 0, 0, 0
    return u or 0, f or 0, d or 0


# ── 소스 2: 다음 모바일 페이지 (거래대금 + 등락) ──────────────

def _daum_mobile(market_label: str):
    """m.finance.daum.net/domestic 텍스트 파싱. 실패 시 None."""
    try:
        r = requests.get("https://m.finance.daum.net/domestic",
                         headers=_HEADERS, timeout=12)
        text = r.text
    except Exception as e:
        _log(f"[daum] 요청 실패: {e}")
        return None

    start = text.find(market_label)
    seg = text[start:start + 4000] if start >= 0 else text

    res = {"value_eok": None, "advance": 0, "flat": 0, "decline": 0, "asof": None}
    m = re.search(r"거래금\s*([\d,]+)\s*백만", seg)
    if m:
        mil = _to_int(m.group(1))
        if mil:
            res["value_eok"] = round(mil / 100)
    mu = re.search(r"상승[▲\s]*([\d,]+)", seg)
    mf = re.search(r"보합[▬\s]*([\d,]+)", seg)
    md = re.search(r"하락[▼\s]*([\d,]+)", seg)
    res["advance"] = (_to_int(mu.group(1)) if mu else 0) or 0
    res["flat"] = (_to_int(mf.group(1)) if mf else 0) or 0
    res["decline"] = (_to_int(md.group(1)) if md else 0) or 0

    if res["value_eok"] is None and (res["advance"] + res["decline"]) == 0:
        _log(f"[daum] 값 없음 (페이지 길이 {len(text)}, '{market_label}' "
             f"위치 {start})")
        return None
    return res


@st.cache_data(ttl=600)
def fetch_breadth(market_label: str):
    """거래대금·등락 종목 수. 네이버 우선, 실패 시 다음. 모두 실패 시 None."""
    # 1) 네이버
    val = _naver_trade_value(market_label)
    up, flat, down = _naver_updown(market_label)
    if val is not None or (up + down) >= 2:
        return {"value_eok": val, "advance": up, "flat": flat,
                "decline": down, "asof": None}

    # 2) 다음
    daum = _daum_mobile(market_label)
    if daum:
        return daum

    _log(f"[{market_label}] 모든 소스 실패")
    return None


# ── 렌더링 ───────────────────────────────────────────────────

def _fmt_value(eok) -> str:
    if eok is None:
        return "—"
    if eok >= 10000:
        return f"{eok:,}억 ({eok/10000.0:,.1f}조)"
    return f"{eok:,}억"


def _breadth_bar_html(adv, flat, dec):
    total = adv + flat + dec
    if total <= 0:
        return ""
    a, f, dd = adv / total * 100, flat / total * 100, dec / total * 100
    segs = ""
    if a > 0:
        segs += f'<div class="breadth-seg-up" style="width:{a:.1f}%;">{adv:,}</div>'
    if f > 0:
        segs += (f'<div class="breadth-seg-flat" style="width:{f:.1f}%;">'
                 f'{flat if f > 6 else ""}</div>')
    if dd > 0:
        segs += f'<div class="breadth-seg-down" style="width:{dd:.1f}%;">{dec:,}</div>'
    return f'<div class="breadth-bar">{segs}</div>'


def _market_card(label, data):
    if not data:
        return (f'<div class="breadth-card"><div class="breadth-mkt">{label}</div>'
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
    return (f'<div class="breadth-card"><div class="breadth-mkt">{label}{asof}</div>'
            f'{val_html}<div style="height:10px"></div>{bar}{legend}</div>')


def render_market_breadth():
    _diag.clear()
    kospi = fetch_breadth("코스피")
    kosdaq = fetch_breadth("코스닥")

    if not kospi and not kosdaq:
        if DEBUG and _diag:
            with st.expander("⚠️ 거래대금·등락 종목 수 — 진단 정보 (DEBUG)"):
                for line in _diag:
                    st.caption(line)
        return

    st.markdown('<div class="mkt-group">📊 거래대금 · 등락 종목 수</div>',
                unsafe_allow_html=True)
    cards = _market_card("코스피", kospi) + _market_card("코스닥", kosdaq)
    st.markdown(f'<div class="breadth-grid">{cards}</div>', unsafe_allow_html=True)
    st.caption("거래대금·등락 종목 수 · 데이터: 네이버/다음 금융 · 장중 약 15~20분 지연 · "
               "상승/보합/하락 막대는 전 종목 비율")

    if DEBUG and _diag:
        with st.expander("ℹ️ 일부 소스 폴백 발생 (DEBUG)"):
            for line in _diag:
                st.caption(line)
