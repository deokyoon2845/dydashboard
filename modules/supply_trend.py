"""수급 추세 — 외국인·기관 일별 순매수 (네이버 금융).

KRX(pykrx)가 클라우드에서 차단되어, 네이버 금융 '투자자별 매매동향'을 대신 쓴다.
finance.naver.com/sise/investorDealTrendDay.naver 한 페이지에 최근 ~20거래일치가 있다.

비공식 스크래핑이라 네이버가 페이지 구조를 바꾸면 깨질 수 있다.
그 경우 빈 상태(안내 문구)로 안전하게 떨어지고 앱은 멈추지 않는다.

※ read_html 사용을 위해 requirements.txt에 lxml 이 필요하다.

2026-06 레이아웃: 좌 코스피 / 우 코스닥 2단 구성 (st.columns).
2026-06 인터랙티브: 마우스 hover 크로스헤어, 가로 스크롤·드래그로 x축 확대(줌).
2026-06 범례: Altair 내장 범례 대신 '차트 위 가운데 정렬' 커스텀 HTML 범례로 교체
  (카드와 약간의 여백). 커스텀 범례라 클릭 토글 기능은 제외됨.
2026-07 x축: 눈금 수 제한(tickCount=6) + labelOverlap=greedy — 좁은 컬럼에서
  날짜 라벨이 겹쳐 판독 불가해지는 문제 수정.
2026-07 각주: 하단 공통 캡션을 헤더 우측 '메타 배지 + ⓘ 접힘 각주'(ui.foot_badge)로
  승격 — 본문 각주 소음 제거(A안 파일럿).
"""

import re
from datetime import datetime
from io import StringIO
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import requests
import streamlit as st

_DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{2}$")
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

_C_FRG = "#B65F5A"   # 외국인 = up red
_C_INS = "#5A7CA0"   # 기관 = down blue


def _to_num(x):
    try:
        s = str(x).replace(",", "").replace("+", "").strip()
        if s in ("", "-", "nan", "None"):
            return None
        return float(s)
    except Exception:
        return None


@st.cache_data(ttl=1800)
def _fetch_investor(sosok: str):
    """네이버 투자자별 매매동향 → DataFrame[날짜, 외국인, 기관]. 실패 시 None.

    sosok: '01'=코스피, '02'=코스닥
    값 단위는 네이버 표기(백만원) 기준 — 표시 단계에서 억원으로 환산한다.
    """
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
    url = (f"https://finance.naver.com/sise/investorDealTrendDay.naver"
           f"?bizdate={today}&sosok={sosok}&page=1")
    try:
        r = requests.get(url, headers=_HEADERS, timeout=12)
        r.encoding = "euc-kr"        # 네이버 금융은 euc-kr 인코딩
        tables = pd.read_html(StringIO(r.text))
    except Exception:
        return None

    rows = []
    for tb in tables:
        if tb.shape[1] < 4:
            continue
        for _, row in tb.iterrows():
            first = str(row.iloc[0]).strip()
            if not _DATE_RE.match(first):
                continue
            # 컬럼 순서: 날짜(0), 개인(1), 외국인(2), 기관계(3), ...
            foreign = _to_num(row.iloc[2])
            inst = _to_num(row.iloc[3])
            if foreign is None and inst is None:
                continue
            try:
                d = datetime.strptime(first, "%y.%m.%d")
            except Exception:
                continue
            rows.append({"날짜": d, "외국인": foreign or 0.0, "기관": inst or 0.0})

    if not rows:
        return None
    df = pd.DataFrame(rows).drop_duplicates("날짜").sort_values("날짜")
    return df.reset_index(drop=True)


def _card(label, val_eok, dstr):
    up = val_eok >= 0
    cls = "up" if up else "down"
    arrow = "▲" if val_eok > 0 else ("▼" if val_eok < 0 else "▬")
    state = "순매수" if up else "순매도"
    return (f'<div class="mkt-card"><div class="mkt-name">{label} ({dstr})</div>'
            f'<div class="mkt-val">{arrow} {abs(val_eok):,.0f}억</div>'
            f'<div class="mkt-chg {cls}">{state}</div></div>')


def _market_label(name: str) -> str:
    """각 열(코스피/코스닥) 상단 소제목."""
    return (f'<div style="font-size:13.5px;font-weight:700;color:var(--ink,#34352f);'
            f'letter-spacing:.01em;margin:2px 0 9px;padding-bottom:5px;'
            f'border-bottom:1.5px solid var(--sage,#A7BBA9);display:inline-block;">'
            f'{name}</div>')


def _legend_html() -> str:
    """차트 위 '가운데 정렬' 커스텀 범례. 위(카드)와 여백을 둔다(margin-top)."""
    def chip(color, text):
        return (f'<span style="display:inline-flex;align-items:center;gap:6px;'
                f'font-size:12px;font-weight:600;color:var(--pill-ink,#5d6258);">'
                f'<span style="width:9px;height:9px;border-radius:50%;'
                f'background:{color};display:inline-block;"></span>{text}</span>')
    return (f'<div style="display:flex;justify-content:center;gap:20px;'
            f'flex-wrap:wrap;margin:16px 0 8px;">'
            f'{chip(_C_FRG, "외국인 누적")}{chip(_C_INS, "기관 누적")}</div>')


def _supply_chart(long: pd.DataFrame):
    """누적 순매수 라인 차트. 내장 범례 없음(커스텀 HTML 범례 사용).
    인터랙티브(hover 크로스헤어·x줌), 셀렉션 구성 실패 시 정적 차트로 폴백."""
    # x축 라벨: 절반 폭 컬럼(코스피/코스닥 2단)에서 15개 날짜 라벨이 충돌하므로
    # 눈금 수를 제한하고(greedy) 겹치는 라벨은 건너뛴다. labelFlush=양끝 라벨 정렬.
    x_enc = alt.X("날짜:T", axis=alt.Axis(title=None, format="%m/%d", labelColor="#9a9b92",
                                          tickCount=6, labelOverlap="greedy",
                                          labelFlush=True))
    y_enc = alt.Y("누적:Q", axis=alt.Axis(title=None, labelColor="#9a9b92", gridColor="#ECEDE7"))
    color_enc = alt.Color("구분:N",
                          scale=alt.Scale(domain=["외국인 누적", "기관 누적"],
                                          range=[_C_FRG, _C_INS]),
                          legend=None)   # 내장 범례 끔 → 커스텀 HTML 범례로 대체
    tip = [alt.Tooltip("날짜:T", format="%Y-%m-%d"),
           "구분:N", alt.Tooltip("누적:Q", format=",.0f")]
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(
        color="#9a9b92", strokeDash=[3, 3]).encode(y="y:Q")

    try:
        hover = alt.selection_point(fields=["날짜"], nearest=True,
                                    on="mouseover", empty=False)
        zoom = alt.selection_interval(bind="scales", encodings=["x"])
        line = alt.Chart(long).mark_line(strokeWidth=2, point=True).encode(
            x=x_enc, y=y_enc, color=color_enc, tooltip=tip)
        selectors = alt.Chart(long).mark_point().encode(
            x=x_enc, opacity=alt.value(0)).add_params(hover)
        rule = alt.Chart(long).mark_rule(color="#9a9b92").encode(
            x=x_enc).transform_filter(hover)
        return ((zero + line + selectors + rule)
                .add_params(zoom)
                .properties(height=240, background="transparent")
                .configure_view(strokeWidth=0))
    except Exception:
        line = alt.Chart(long).mark_line(strokeWidth=2, point=True).encode(
            x=x_enc, y=y_enc, color=color_enc, tooltip=tip)
        return ((zero + line)
                .properties(height=240, background="transparent")
                .configure_view(strokeWidth=0))


def _render_market_block(label: str, sosok: str):
    """한 시장(코스피 또는 코스닥)의 소제목 + 카드 + (가운데 범례) + 추세 차트."""
    st.markdown(_market_label(label), unsafe_allow_html=True)

    df = _fetch_investor(sosok)
    if df is None or df.empty:
        st.caption("네이버 금융에서 수급 데이터를 불러오지 못했어요. "
                   "(페이지 구조 변경 또는 일시 오류 — 잠시 후 새로고침)")
        return

    df = df.tail(15).copy()
    # 네이버 표기(백만원) → 억원 (1억원 = 100백만원)
    df["외국인_억"] = df["외국인"] / 100.0
    df["기관_억"] = df["기관"] / 100.0

    # 최근일 카드
    last = df.iloc[-1]
    dstr = last["날짜"].strftime("%m/%d")
    cards = _card("외국인", last["외국인_억"], dstr) + _card("기관", last["기관_억"], dstr)
    st.markdown(f'<div class="mkt-grid">{cards}</div>', unsafe_allow_html=True)

    # 누적 순매수 추세 (방향성: 계속 사는지/파는지)
    df["외국인 누적"] = df["외국인_억"].cumsum()
    df["기관 누적"] = df["기관_억"].cumsum()
    long = df.melt(id_vars="날짜", value_vars=["외국인 누적", "기관 누적"],
                   var_name="구분", value_name="누적")

    # 카드 ↔ 차트 사이: 가운데 정렬 범례 (위 여백 포함)
    st.markdown(_legend_html(), unsafe_allow_html=True)
    st.altair_chart(_supply_chart(long), use_container_width=True)


def render_supply_trend():
    from modules.ui import foot_badge
    st.markdown(
        '<div class="mkt-group ui-fx">💰 외국인·기관 수급 추세'
        + foot_badge(
            "네이버 금융 · 15거래일",
            "최근 15거래일 외국인·기관 누적 순매수(억원, 우상향=순매수 지속) · "
            "단위는 추정치 · 차트 위 마우스 hover=값 표시 / 스크롤·드래그=가로 확대")
        + '</div>', unsafe_allow_html=True)

    # 좌 코스피 / 우 코스닥 — 모바일에서는 Streamlit이 자동으로 세로 적층.
    left, right = st.columns(2, gap="large")
    with left:
        _render_market_block("코스피", "01")
    with right:
        _render_market_block("코스닥", "02")
