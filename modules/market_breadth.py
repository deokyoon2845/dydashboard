"""시장 폭(Breadth) — 거래대금 + 등락 종목 수 (네이버 금융).

pykrx가 클라우드(해외 IP)에서 차단되어, 네이버 금융 지수 페이지를 스크래핑한다.
- 거래대금: finance.naver.com/sise/sise_index.naver?code=KOSPI / KOSDAQ
- 등락 종목 수(상승/보합/하락): 같은 페이지의 '상승·보합·하락' 종목 수

supply_trend.py 와 동일한 방식(requests + euc-kr + 정규식 파싱).
비공식 스크래핑이라 네이버가 구조를 바꾸면 깨질 수 있어, 실패 시 None을 반환하고
호출부가 '안내 문구'로 안전하게 떨어진다(앱은 멈추지 않음).
"""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import streamlit as st

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# 네이버 지수 코드
_CODES = {"코스피": "KOSPI", "코스닥": "KOSDAQ"}


def _clean_int(s) -> int | None:
    """'1,234' / '1,234,567' → int. 실패 시 None."""
    try:
        v = re.sub(r"[^\d]", "", str(s))
        return int(v) if v else None
    except Exception:
        return None


@st.cache_data(ttl=600)  # 10분 캐시 (장중 갱신 고려)
def fetch_breadth(market_label: str):
    """한 시장(코스피/코스닥)의 거래대금·등락 종목 수.

    반환: {
        "value_eok": int|None,        # 거래대금 (억원)
        "advance": int, "flat": int, "decline": int,  # 등락 종목 수
        "asof": "HH:MM" 또는 None,
    }  실패 시 None.
    """
    code = _CODES.get(market_label)
    if not code:
        return None

    url = f"https://finance.naver.com/sise/sise_index.naver?code={code}"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=12)
        r.encoding = "euc-kr"
        html = r.text
    except Exception:
        return None

    result = {"value_eok": None, "advance": 0, "flat": 0, "decline": 0, "asof": None}

    # ── 거래대금 ──
    # 네이버 표기: "거래대금 12,345,678 백만" 형태 (백만원 단위).
    # id="quant" 또는 라벨 '거래대금' 뒤의 숫자를 잡는다.
    try:
        # 패턴 1: 거래대금 라벨 뒤 숫자(백만원)
        m = re.search(r"거래대금[^\d\-]{0,30}([\d,]+)\s*백만", html)
        if not m:
            # 패턴 2: id="quant" 셀
            m = re.search(r'id="quant"[^>]*>\s*([\d,]+)', html)
        if m:
            millions = _clean_int(m.group(1))
            if millions is not None:
                # 백만원 → 억원 (1억 = 100백만)
                result["value_eok"] = round(millions / 100)
    except Exception:
        pass

    # ── 등락 종목 수 (상승/보합/하락) ──
    # 네이버 지수 페이지 상단에 상한/상승/보합/하락/하한 종목 수가 노출된다.
    # 라벨별로 가장 가까운 숫자를 잡는다.
    try:
        def _near(label):
            mm = re.search(label + r"[^\d]{0,40}?([\d,]+)", html)
            return _clean_int(mm.group(1)) if mm else None

        up = _near("상승")
        flat = _near("보합")
        down = _near("하락")
        # 상한/하한이 별도로 잡히면 상승/하락에 합산하지 않는다(상승 수에 이미 포함).
        result["advance"] = up or 0
        result["flat"] = flat or 0
        result["decline"] = down or 0
    except Exception:
        pass

    # ── 기준 시각 (페이지의 장중 시각이 있으면) ──
    try:
        t = re.search(r"(\d{2}:\d{2})", html)
        if t:
            result["asof"] = t.group(1)
    except Exception:
        pass

    # 거래대금도 등락수도 모두 못 구하면 실패로 간주
    if result["value_eok"] is None and (result["advance"] + result["decline"]) == 0:
        return None
    return result


# ── 렌더링 ───────────────────────────────────────────────────

def _fmt_value(eok: int | None) -> str:
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
    d = dec / total * 100
    segs = ""
    if a > 0:
        segs += (f'<div class="breadth-seg-up" style="width:{a:.1f}%;">'
                 f'{adv:,}</div>')
    if f > 0:
        segs += (f'<div class="breadth-seg-flat" style="width:{f:.1f}%;">'
                 f'{flat if f > 6 else ""}</div>')
    if d > 0:
        segs += (f'<div class="breadth-seg-down" style="width:{d:.1f}%;">'
                 f'{dec:,}</div>')
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
        # 둘 다 실패하면 섹션 자체를 조용히 생략 (지저분한 빈 카드 방지)
        return

    st.markdown('<div class="mkt-group">📊 거래대금 · 등락 종목 수</div>',
                unsafe_allow_html=True)
    cards = _market_card("코스피", kospi) + _market_card("코스닥", kosdaq)
    st.markdown(f'<div class="breadth-grid">{cards}</div>', unsafe_allow_html=True)
    st.caption("거래대금·등락 종목 수 · 데이터: 네이버 금융 · 장중 약 15분 지연 · "
               "상승/보합/하락 막대는 전 종목 비율")
