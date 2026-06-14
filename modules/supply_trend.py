"""수급 추세 — 외국인·기관 일별 순매수 (네이버 금융).

KRX(pykrx)가 클라우드에서 차단되어, 네이버 금융 '투자자별 매매동향'을 대신 쓴다.
finance.naver.com/sise/investorDealTrendDay.naver 한 페이지에 최근 ~20거래일치가 있다.

비공식 스크래핑이라 네이버가 페이지 구조를 바꾸면 깨질 수 있다.
그 경우 빈 상태(안내 문구)로 안전하게 떨어지고 앱은 멈추지 않는다.

※ read_html 사용을 위해 requirements.txt에 lxml 이 필요하다.
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


def render_supply_trend():
    st.markdown('<div class="mkt-group">💰 외국인·기관 수급 추세 (코스피)</div>',
                unsafe_allow_html=True)

    df = _fetch_investor("01")  # 코스피
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

    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(
        color="#9a9b92", strokeDash=[3, 3]).encode(y="y:Q")
    line = alt.Chart(long).mark_line(strokeWidth=2, point=True).encode(
        x=alt.X("날짜:T", axis=alt.Axis(title=None, format="%m/%d", labelColor="#9a9b92")),
        y=alt.Y("누적:Q", axis=alt.Axis(title=None, labelColor="#9a9b92", gridColor="#ECEDE7")),
        color=alt.Color("구분:N",
                        scale=alt.Scale(domain=["외국인 누적", "기관 누적"],
                                        range=["#B65F5A", "#5A7CA0"]),
                        legend=alt.Legend(title=None, orient="top")),
        tooltip=[alt.Tooltip("날짜:T", format="%Y-%m-%d"),
                 "구분:N", alt.Tooltip("누적:Q", format=",.0f")],
    )
    chart = (zero + line).properties(height=240, background="transparent") \
                         .configure_view(strokeWidth=0)
    st.altair_chart(chart, use_container_width=True)
    st.caption("최근 15거래일 외국인·기관 누적 순매수(억원, 우상향=순매수 지속) · "
               "데이터: 네이버 금융 · 단위는 추정치")
