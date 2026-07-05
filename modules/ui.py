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


# ── 각주 배지(A안) — 섹션 각주를 '메타 배지 + ⓘ 접힘 각주'로 승격 ──────────
# 배경: 거의 모든 섹션 하단에 2~3줄 회색 각주(출처·범례·조작법)가 붙어 본문 흐름을
# 끊었다. 핵심 메타(출처·주기)는 헤더 우측 배지로 상시 노출해 신뢰 신호로 승격하고,
# 상세 설명은 순수 HTML <details>로 접는다 — JS·위젯 상태 없이 동작하므로
# st.fragment 자동 갱신 안에서도 안전하고 모바일에서는 탭으로 열린다.
#
# 사용 예 (헤더 행에 합류 — 헤더 div에 ui-fx 클래스 추가):
#     st.markdown('<div class="mkt-group ui-fx">💰 수급 추세'
#                 + foot_badge("네이버 금융 · 15거래일", "긴 설명…") + '</div>',
#                 unsafe_allow_html=True)
# FOOT_CSS는 앱 전역 CSS와 함께 1회 주입한다(app.py).

FOOT_CSS = """
<style>
.ui-fx{display:flex;align-items:center;gap:10px;flex-wrap:wrap;}
.ui-foot{margin-left:auto;min-width:0;}
.ui-foot[open]{flex-basis:100%;}   /* 펼치면 본문이 행 전체 폭을 쓴다(결정적 레이아웃) */
.ui-foot summary{list-style:none;cursor:pointer;display:flex;justify-content:flex-end;align-items:center;gap:6px;
  font-family:'Hanken Grotesk','Noto Sans KR',sans-serif;font-size:10.5px;font-weight:700;letter-spacing:0;
  color:var(--pill-ink,#5d6258);user-select:none;}
.ui-foot summary::-webkit-details-marker{display:none;}
.ui-foot summary .pill{display:inline-flex;align-items:center;gap:6px;background:var(--summary-bg,#F6F7F2);
  border:1px solid var(--line,#ECEDE7);border-radius:9px;padding:4px 10px;white-space:nowrap;
  transition:color .15s ease,border-color .15s ease;}
.ui-foot summary:hover .pill{color:var(--ink,#34352f);border-color:var(--sage,#A7BBA9);}
.ui-foot[open] summary .pill{color:var(--ink,#34352f);border-color:var(--sage,#A7BBA9);}
.ui-foot .ic{display:inline-flex;align-items:center;justify-content:center;width:13px;height:13px;border-radius:50%;
  border:1px solid var(--muted,#9a9b92);color:var(--muted,#9a9b92);font-size:9px;font-style:italic;
  font-family:Georgia,serif;flex:none;}
.ui-foot .b{margin-top:8px;font-family:'Hanken Grotesk','Noto Sans KR',sans-serif;font-size:11.5px;font-weight:400;
  color:var(--muted,#9a9b92);line-height:1.62;letter-spacing:0;background:var(--summary-bg,#F6F7F2);
  border-radius:9px;padding:9px 13px;text-align:left;}
.ui-foot-row{display:flex;justify-content:flex-end;margin:2px 0 6px;}
</style>"""


def foot_badge(meta: str, detail: str) -> str:
    """각주 배지 HTML 조각 — .ui-fx 플렉스 헤더 행의 마지막 자식으로 삽입.

    meta   : 배지에 상시 노출할 핵심 메타(출처·주기 — 예: "네이버 금융 · 15거래일")
    detail : ⓘ 클릭 시 펼쳐질 상세 설명(범례·계산식·조작법 — 기존 각주 본문)
    둘 다 평문(HTML 이스케이프됨)."""
    import html as _h
    return (f'<details class="ui-foot"><summary><span class="pill">{_h.escape(meta)}'
            f'<span class="ic" aria-hidden="true">i</span></span></summary>'
            f'<div class="b">{_h.escape(detail)}</div></details>')


def foot_row(meta: str, detail: str) -> str:
    """헤더 행이 없는 자리(차트 아래 등)에 단독으로 쓰는 우측 정렬 각주 배지 행."""
    return f'<div class="ui-fx ui-foot-row">{foot_badge(meta, detail)}</div>'
