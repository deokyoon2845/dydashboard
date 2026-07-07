"""부동산 시장 모니터링 탭 — 라우터.

부동산 탭 본문은 서브탭별 모듈로 분리되어 있고(증시 탭과 동일 패턴), 이 파일은
segmented_control 라우팅만 담당한다. app.py는 여기의 render_realestate만 import한다.

  · 사이클  → modules/realestate_cycle.py   (KB·ECOS·KOSIS 지표 v2)
  · 지도    → modules/realestate_map.py     (choropleth + 워치리스트·스트릭)
  · 실거래  → modules/realestate_deals.py   (시장 밴드·급지 보드·주목단지)
  · 분양    → modules/realestate_subs.py    (청약홈 분양정보)
  · 테마    → modules/realestate_keywords_view.py (기존 분리 모듈)
  · 공용    → modules/realestate_common.py  (스냅샷 로더·_RE_CSS·인증/수집)
  · 지오    → modules/realestate_geo.py     (SVG 경계 자산 — 지도·급지 보드 공용)

렌더 방식·설계 원칙(뷰어/데이터 계층 분리, iframe 렌더 이유 등)은 각 탭 모듈
docstring에 있다. 서브탭 import는 분기 안에서 lazy로 수행 — 선택된 탭만 실제
실행·파싱된다(st.tabs 전량 실행 문제를 피해 온 기존 lazy 구조 유지).
"""

import streamlit as st

from modules.ui import tab_header   # 표준 탭 크롬
from modules.realestate_common import (_RE_CSS, _re_authed, _re_collect_asof,
                                        _run_collection)


def render_realestate():
    """부동산 탭 본문 — 사이클 / 지도 / 실거래 / 분양 / 테마 서브탭.

    증시 탭과 동일 구조로 통일: 서브탭을 먼저 두고, 각 서브탭을 표준 크롬
    tab_header(제목·캡션·_RE_CSS 합본 주입)로 연다 — 전 탭 헤더 문법 일원화.
    갱신/진단은 주 화면인 '지도' 탭 안에 위치하고, 나머지 탭은 같은 세션/스냅샷을 읽는다.
    """
    # ── lazy 서브탭: 선택된 탭만 실제 실행(매 렌더마다 5개 탭이 다 도는 부담 제거) ──
    #   부동산은 최대 규모 모듈이라 효과가 크다. 증시 상단탭과 동일한 st.segmented_control.
    #   단, _RE_CSS(부동산 전용 스타일)는 예전엔 항상 실행되던 '사이클' 탭에서만 주입됐으므로,
    #   어느 탭으로 바로 진입해도 스타일이 붙도록 각 분기에서 주입한다(한 렌더에 한 분기만
    #   실행 → 중복 없음, accent-bar와 한 블록으로 합쳐 세로 간격도 유지).
    _re_maintab = st.segmented_control(
        "부동산 탭", ["사이클", "지도", "실거래", "분양", "테마"], default="사이클",
        key="re_maintab", label_visibility="collapsed",
    ) or "사이클"   # 선택 해제(None) 시 기본값으로 폴백

    if _re_maintab == "사이클":
        from modules.realestate_cycle import (_render_indicator_charts,
                                              _resolved_indicator_series)
        _cyc_asof = _re_collect_asof()
        if _cyc_asof:
            _cyc_cap = ("부동산 사이클·선행지표 — 매수우위·매매전망·선도50·전세수급"
                        f"(KB 주간·월간) · 기준 {_cyc_asof} KST · "
                        "항목별 갱신주기 상이 · 매일 아침 자동 갱신")
        else:
            _cyc_cap = ("부동산 사이클·선행지표 — KB 주간·월간 지수 기반 · "
                        "현재 샘플(아침 자동 수집 후 실데이터로 채워집니다)")
        tab_header("부동산 시장 지표", caption=_cyc_cap, css=_RE_CSS)
        _render_indicator_charts(_resolved_indicator_series())

    elif _re_maintab == "지도":
        from modules.realestate_common import _render_collect_controls
        from modules.realestate_map import (_render_map, _render_streak_section,
                                            _render_watchlist_band)
        tab_header("가격지도", css=_RE_CSS)
        _render_collect_controls()
        _render_watchlist_band()
        _render_streak_section()
        _render_map()

    elif _re_maintab == "실거래":
        from modules.realestate_deals import (_render_hot_complexes,
                                              _render_market_bands,
                                              _render_region_board)
        tab_header("아파트 실거래",
                   caption="아파트 단지·실거래 종합 — 시장 방향(월간·주간·오늘)·지역 급지·주목단지 · "
                           "국토부 실거래 기준 · 직거래 기본 제외",
                   css=_RE_CSS)
        # 월간|주간|오늘 3단 통합 — 같은 양식 밴드를 단일 iframe에 스택(단 간격 10px).
        _render_market_bands()
        st_rg, st_hot = st.tabs(["지역", "주목 단지"])
        with st_rg:
            st.markdown('<div class="re-grp">지역 급지별 매매 현황'
                        '<span class="sub">평당가 10급지 동적 배정 · 여의도·목동·성수·'
                        '이촌·잠실 분리 · 티어당 시총 TOP20 + 신고가·괴리 알림</span></div>',
                        unsafe_allow_html=True)
            _render_region_board()
        with st_hot:
            _render_hot_complexes()

    elif _re_maintab == "분양":
        from modules.realestate_subs import _render_subscriptions
        tab_header("분양 단지",
                   caption="한국부동산원 청약홈 분양정보 · 청약 임박·진행 우선 · "
                           "매일 아침 자동 갱신 · 최근·다음 시각은 하단 🕐 자동 갱신 현황",
                   css=_RE_CSS)
        if _re_authed():
            if st.button(
                    "🔄 최신 분양정보 불러오기", key="re_sub_refresh",
                    help="매일 아침 GitHub Actions가 청약홈 분양정보를 수집해 DB에 저장합니다. "
                         "이 버튼은 그 최신본을 즉시 다시 불러옵니다.",
                    use_container_width=True):
                with st.spinner("DB에서 최신 분양정보 불러오는 중..."):
                    _run_collection()
                st.success("최신 분양정보를 불러왔어요.")
                st.rerun()
        _render_subscriptions()

    else:  # 테마
        # _RE_CSS를 먼저 주입(이 탭으로 바로 진입해도 부동산 스타일 유지).
        # 키워드 뷰어가 자체적으로 accent-bar + 제목을 그린다(증시 키워드 탭과 동일).
        st.markdown(_RE_CSS, unsafe_allow_html=True)
        from modules.realestate_keywords_view import render_realestate_keywords
        render_realestate_keywords()
