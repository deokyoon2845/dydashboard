"""시장 폭(Breadth) — 거래대금 + 등락 종목 수.

pykrx가 클라우드(해외 IP)에서 차단되어 네이버 비공식 JSON API로 수집한다.

2026-07 재작성 배경:
  네이버 지수 상세(sise_index)·다음 모바일 페이지가 전부 JS 렌더링 SPA로 바뀌어
  정적 HTML 파싱이 불가능해졌다(정규식이 좌측 메뉴의 '상승'만 잡아 up=0 실패,
  다음 페이지는 아예 빈 껍데기). breadth probe로 확정한 단일 JSON 엔드포인트로
  거래대금·등락 종목 수를 '한 번의 호출'로 가져오도록 통일했다.

소스(우선순위):
  1) m.stock.naver.com/api/index/{CODE}/integration   ← 주 소스(둘 다 제공)
     - totalInfos[accumulatedTradingValue] → 거래대금(백만 → 억)
     - upDownStockInfo{riseCount,steadyCount,fallCount,upperCount,lowerCount}
       → 상승(=상승+상한) / 보합 / 하락(=하락+하한)
  2) polling.finance.naver.com/api/realtime/domestic/index/{CODE}  ← 거래대금 폴백
     - accumulatedTradingValueRaw(원) → 거래대금(억). 등락 종목 수는 없음(→ 정보 없음).

등락 합계가 비현실적으로 작으면(<100) 오파싱으로 보고 등락은 버린다(거래대금은 유지).

DEBUG=True로 두면 실패 시 화면에 진단 정보를 표시한다(원인 파악용).
"""

import re

import requests
import streamlit as st

DEBUG = False  # 진단이 필요할 때만 True

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://m.stock.naver.com/",
}

_NAVER_CODE = {"코스피": "KOSPI", "코스닥": "KOSDAQ"}

# 등락 종목 수 합계가 이 값보다 작으면 오파싱으로 보고 버린다.
# (코스피·코스닥은 상장 종목이 수백~천 단위라 한 자릿수는 비정상)
_MIN_BREADTH_TOTAL = 100

# 진단 로그 (DEBUG일 때 화면에 표시)
_diag = []


def _log(msg):
    if DEBUG:
        _diag.append(str(msg))


def _digits(x):
    """문자열에서 숫자만 추려 int로. 실패 시 None. ('4,911,687백만' → 4911687)"""
    try:
        v = re.sub(r"[^\d]", "", str(x))
        return int(v) if v else None
    except Exception:
        return None


def _eok_from_baekman(text):
    """'4,911,687백만' 형태 → 억(int). 실패 시 None."""
    mil = _digits(text)
    return round(mil / 100) if mil else None  # 백만 → 억


# ── 소스 1: 네이버 통합 JSON (거래대금 + 등락 종목 수) ───────────

def _naver_integration(market_label: str):
    """m.stock.naver.com integration — 거래대금·등락 종목 수를 한 번에.
    실패 시 None. 등락만 비정상이면 등락은 0으로 비우고 거래대금은 살린다."""
    code = _NAVER_CODE.get(market_label)
    if not code:
        return None
    url = f"https://m.stock.naver.com/api/index/{code}/integration"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=12)
        data = r.json()
    except Exception as e:
        _log(f"[integration {market_label}] 요청/파싱 실패: {e}")
        return None

    # 거래대금 (totalInfos 안의 accumulatedTradingValue: '…백만')
    value_eok = None
    for it in (data.get("totalInfos") or []):
        if it.get("code") == "accumulatedTradingValue":
            value_eok = _eok_from_baekman(it.get("value"))
            break

    # 등락 종목 수 (상한은 상승에, 하한은 하락에 합산)
    ud = data.get("upDownStockInfo") or {}
    rise = _digits(ud.get("riseCount")) or 0
    upper = _digits(ud.get("upperCount")) or 0
    steady = _digits(ud.get("steadyCount")) or 0
    fall = _digits(ud.get("fallCount")) or 0
    lower = _digits(ud.get("lowerCount")) or 0
    adv, flat, dec = rise + upper, steady, fall + lower

    if adv + dec < _MIN_BREADTH_TOTAL:
        _log(f"[integration {market_label}] 등락 비정상 "
             f"up={adv} flat={flat} down={dec} → 등락 생략")
        adv = flat = dec = 0

    if value_eok is None and (adv + dec) == 0:
        _log(f"[integration {market_label}] 유효 값 없음")
        return None
    return {"value_eok": value_eok, "advance": adv, "flat": flat,
            "decline": dec, "asof": None}


# ── 소스 2: 네이버 폴링 실시간 (거래대금 폴백) ─────────────────

def _naver_polling_value(market_label: str):
    """polling.finance.naver.com — accumulatedTradingValueRaw(원) → 억. 실패 시 None."""
    code = _NAVER_CODE.get(market_label)
    if not code:
        return None
    url = f"https://polling.finance.naver.com/api/realtime/domestic/index/{code}"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=12)
        datas = (r.json() or {}).get("datas") or []
        if not datas:
            _log(f"[polling {market_label}] datas 없음")
            return None
        won = _digits(datas[0].get("accumulatedTradingValueRaw"))
        return round(won / 1e8) if won else None  # 원 → 억
    except Exception as e:
        _log(f"[polling {market_label}] 실패: {e}")
        return None


@st.cache_data(ttl=600)
def fetch_breadth(market_label: str):
    """거래대금·등락 종목 수. 통합 JSON 우선, 실패 시 폴링으로 거래대금만."""
    d = _naver_integration(market_label)
    if d:
        if d["value_eok"] is None:  # 등락은 있는데 거래대금만 비면 폴링으로 보강
            d["value_eok"] = _naver_polling_value(market_label)
        return d

    # 통합 실패 → 거래대금이라도 살린다(등락은 '정보 없음')
    val = _naver_polling_value(market_label)
    if val is not None:
        return {"value_eok": val, "advance": 0, "flat": 0,
                "decline": 0, "asof": None}

    _log(f"[{market_label}] 모든 소스 실패")
    return None


# ── 렌더링 ───────────────────────────────────────────────────

def _fmt_value(eok) -> str:
    if eok is None:
        return "—"
    return f"{eok/10000.0:,.1f}조"


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

    from modules.ui import foot_badge
    st.markdown(
        '<div class="mkt-group ui-fx">📊 거래대금 · 등락 종목 수'
        + foot_badge(
            "네이버 금융 · 15~20분 지연",
            "장중 약 15~20분 지연 · 상승/보합/하락 막대는 전 종목 비율(상한·하한 포함)")
        + '</div>', unsafe_allow_html=True)
    cards = _market_card("코스피", kospi) + _market_card("코스닥", kosdaq)
    st.markdown(f'<div class="breadth-grid">{cards}</div>', unsafe_allow_html=True)
    # 출처·범례는 헤더 ⓘ 배지로 이동(A안) — 하단 각주 제거.

    if DEBUG and _diag:
        with st.expander("ℹ️ 일부 소스 폴백 발생 (DEBUG)"):
            for line in _diag:
                st.caption(line)
