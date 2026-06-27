"""탭 헤더 공통 렌더 — 모든 탭의 '초록 바 · 헤드라인 · 캡션' 배치를 통일한다.

배경:
- 지수·부동산 탭은 이미 [초록 바 → st.title → st.caption] 구조라 이를 표준으로 삼는다.
- 시황·주도주·IPO·키워드 탭은 탭 전용 CSS를 '별도 markdown 블록'으로 주입해
  바 위에 빈 블록 간격이 한 칸 더 생겨 여백이 어긋났다. 그 CSS를 바와 '같은 블록'에
  합쳐 주입하면(부동산 지도 탭이 쓰는 기법) 간격이 표준과 일치한다.
- 시황 탭은 제목을 커스텀 div로 그려 크기·간격이 달랐다. 여기서는 날짜(eyebrow)와
  제목을 한 블록 마스트헤드로 묶어 다른 탭의 h1과 같은 크기로 통일한다.

사용 예:
    tab_header("주요 지수 현황", caption="데이터: …")
    tab_header("IPO", caption=cap_txt, css=_CSS)
    tab_header("전략·시황 보고서", eyebrow="2026.06.26 (금)", css=_RPT_CSS)
"""

import streamlit as st


def tab_header(title: str, caption: str = "", eyebrow: str = "", css: str = ""):
    """탭 상단 헤더를 표준 배치로 그린다.

    title   : 헤드라인(필수)
    caption : 제목 아래 회색 설명(없으면 생략)
    eyebrow : 제목 위 작은 라벨(예: 날짜) — 있으면 바·라벨·제목을 한 블록으로 묶음
    css     : 탭 전용 '<style>…</style>' 문자열. 바와 같은 블록에 합쳐 빈 블록 간격을 없앤다.
    """
    if eyebrow:
        # 바 + 날짜 + 제목을 한 블록으로 → 날짜가 제목에 바로 붙고, 빈 블록 간격도 없음.
        st.markdown(
            css
            + '<div class="accent-bar"></div>'
            + f'<div class="th-eyebrow">{eyebrow}</div>'
            + f'<h1 class="th-title">{title}</h1>',
            unsafe_allow_html=True,
        )
    else:
        # 지수·부동산 탭과 픽셀 일치(초록 바 → st.title). 탭 CSS는 바와 같은 블록에 합침.
        st.markdown(css + '<div class="accent-bar"></div>', unsafe_allow_html=True)
        st.title(title)

    if caption:
        st.caption(caption)
