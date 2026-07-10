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
    """부동산 탭 본문 — 사이클 / 실거래 / 분양 / 테마 서브탭.

    증시 탭과 동일 구조로 통일: 서브탭을 먼저 두고, 각 서브탭을 표준 크롬
    tab_header(제목·캡션·_RE_CSS 합본 주입)로 연다 — 전 탭 헤더 문법 일원화.
    (구)지도 탭은 실거래 탭의 '시세 지도' 뷰로 통합(2026-07) — KB 시세 관점과
    국토부 실거래 관점을 한 탭에서 뷰 전환으로 비교. 갱신/진단도 그 뷰로 이동.
    """
    # ── lazy 서브탭: 선택된 탭만 실제 실행(매 렌더마다 5개 탭이 다 도는 부담 제거) ──
    #   부동산은 최대 규모 모듈이라 효과가 크다. 증시 상단탭과 동일한 st.segmented_control.
    #   단, _RE_CSS(부동산 전용 스타일)는 예전엔 항상 실행되던 '사이클' 탭에서만 주입됐으므로,
    #   어느 탭으로 바로 진입해도 스타일이 붙도록 각 분기에서 주입한다(한 렌더에 한 분기만
    #   실행 → 중복 없음, accent-bar와 한 블록으로 합쳐 세로 간격도 유지).
    # 탭 아이콘(:material/…) — format_func로 표시만 바꾸고 값(세션·비교)은 한글 그대로 유지.
    #   세이지 필 스타일은 app.py 전역 CSS(.st-key-re_maintab2 — 주식 하위탭과 공유)가 담당.
    _re_icons = {"사이클": ":material/cycle:", "실거래": ":material/receipt_long:",
                 "분양": ":material/campaign:", "테마": ":material/tag:"}
    _re_maintab = st.segmented_control(
        "부동산 탭", ["사이클", "실거래", "분양", "테마"], default="사이클",
        format_func=lambda _t: f"{_re_icons[_t]} {_t}",
        key="re_maintab2", label_visibility="collapsed",
    ) or "사이클"   # 선택 해제(None) 시 기본값으로 폴백
    # ※ key를 re_maintab2로 교체(2026-07): 기존 세션에 '지도' 값이 남아 있으면
    #   새 옵션 목록과 충돌하므로 새 키로 시작한다.

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

    elif _re_maintab == "실거래":
        # (구)지도 탭 통합(2026-07): KB 시세 관점(시세 지도)과 국토부 실거래 관점
        # (지역 급지·주목 단지)을 한 탭에서 뷰 전환으로 비교한다.
        from modules.realestate_deals import _render_market_bands
        tab_header("아파트 실거래",
                   caption="아파트 시세·실거래 종합 — 시장 방향(월간·주간·오늘) · "
                           "시세 지도(KB 주간) · 지역 급지·주목단지(국토부 실거래) · "
                           "직거래 기본 제외",
                   css=_RE_CSS)
        # 월간|주간|오늘 3단 통합 — 같은 양식 밴드를 단일 iframe에 스택(단 간격 10px).
        _render_market_bands()
        # 시세 지도|지역 급지|주목 단지 — st.tabs는 패널 높이를 마운트 시점에 고정해
        # iframe이 나중에 커지면(_fit) 아래 요소와 겹치는 문제가 있어 segmented_control
        # 조건부 렌더 유지(미선택 뷰 실행 부담도 제거). 키는 옵션 변경으로 re_dealtab2.
        _re_dealtab = st.segmented_control(
            "실거래 보기", ["시세 지도", "지역 급지", "주목 단지"], default="시세 지도",
            key="re_dealtab2", label_visibility="collapsed",
        ) or "시세 지도"
        if _re_dealtab == "시세 지도":
            # 구 지도 탭 전체 이관 — 수집/진단 컨트롤 · 주목 지역 4카드 ·
            # 가격지수 동향 6카드 · KB 주간 변동률 choropleth(드릴다운).
            from modules.realestate_common import _render_collect_controls
            from modules.realestate_map import (_render_map,
                                                _render_streak_section,
                                                _render_watchlist_band)
            _render_collect_controls()
            _render_watchlist_band()   # 주목 지역 4카드(매매급등·약세·거래활발·괴리)
            _render_streak_section()   # 가격지수 동향 6카드 — 주목 지역 바로 아래
            _render_map()              # 지도 본체는 맨 아래
        elif _re_dealtab == "지역 급지":
            from modules.realestate_deals import _render_region_board
            # 섹션 헤더('지역 급지별 매매 현황')는 보드 iframe 내부(지도 아래)로 이동
            _render_region_board()
        else:
            from modules.realestate_deals import _render_hot_complexes
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
