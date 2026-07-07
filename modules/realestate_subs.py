"""부동산 '분양' 탭 — 한국부동산원 청약홈 분양정보(청약 임박·진행 우선).

엔진(realestate_subscriptions)이 저장한 스냅샷을 읽어 D-day 배지·긴급 하이라이트
카드로 렌더한다. 실패/미수집 시 샘플 폴백.
"""

import streamlit as st

from modules.ui import foot_row
from modules.realestate_common import _load_re_snapshot, _naver_n


# ── 분양 단지 (청약홈 분양정보 — 현재 샘플 · 폴백) ───────────────
#   (단지명, 시군구, 주소, 유형, 공급세대, 청약시작 'MM.DD', 청약종료, 입주예정 'YY.MM', seoul|gg)
#   실연결: 한국부동산원 청약홈 분양정보 조회 서비스(data.go.kr/15098547) — 별도 활용신청 필요.
_SAMPLE_SUBS = [
    ("래미안 OO포레", "서초구", "서울 서초구 방배동", "민영", 689, "06.16", "06.18", "28.09", "seoul"),
    ("OO자이 디에이치", "강동구", "서울 강동구 천호동", "민영", 1248, "06.23", "06.25", "28.12", "seoul"),
    ("광명 OO푸르지오", "광명시", "경기 광명시 광명동", "민영", 1051, "06.17", "06.19", "28.06", "gg"),
    ("수원 OO트리니티", "수원시", "경기 수원시 영통구", "민영", 842, "06.30", "07.02", "28.10", "gg"),
    ("용인 OO센트럴", "용인시", "경기 용인시 처인구", "민영", 1395, "07.07", "07.09", "29.02", "gg"),
    ("은평 OO엘리프", "은평구", "서울 은평구 대조동", "민영", 423, "05.26", "05.28", "27.11", "seoul"),
    ("화성동탄 OO리슈빌", "화성시", "경기 화성시 동탄2", "민영", 614, "05.19", "05.21", "27.08", "gg"),
]


# 청약홈 APT 분양정보 목록 — 개별 공고 url이 없을 때(샘플·구 스냅샷) 폴백 이동지.
_APPLYHOME_LIST = "https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancListView.do"


def fetch_subscriptions():
    """분양 단지 리스트. 세션(직전 갱신)→DB 스냅샷→내장 샘플 폴백.
       DB/세션 값이면 실데이터, _SAMPLE_SUBS 객체면 샘플(렌더에서 identity로 구분)."""
    s = st.session_state.get("re_subs")
    if s:
        return s
    snap = _load_re_snapshot()
    if snap:
        subs = snap.get("subscriptions")
        if subs:
            return subs
    return _SAMPLE_SUBS


def _sub_window(start, end):
    """'MM.DD' 청약 기간 → (시작date, 종료date). 연말연초 이월 보정. 실패 시 (None, None)."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    try:
        y = today.year
        s = datetime.strptime(f"{y}.{start}", "%Y.%m.%d").date()
        e = datetime.strptime(f"{y}.{end}", "%Y.%m.%d").date()
    except Exception:
        return None, None
    try:
        if e < today - timedelta(days=300):       # 사실상 내년 건(연초)
            s = s.replace(year=s.year + 1)
            e = e.replace(year=e.year + 1)
        elif s > today + timedelta(days=300):     # 사실상 작년 건(연말)
            s = s.replace(year=s.year - 1)
            e = e.replace(year=e.year - 1)
    except ValueError:
        pass
    return s, e


def _sub_status(start, end):
    """청약 기간으로 예정/분양중/마감 분류 (KST 기준). (라벨, 정렬순)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    s, e = _sub_window(start, end)
    if s is None:
        return "예정", 1
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    if today < s:
        return "예정", 1
    if s <= today <= e:
        return "분양중", 0
    return "마감", 2


def _sub_dday(s_date, e_date, status):
    """상태별 D-day 배지 텍스트. 예정=시작까지, 분양중=마감까지."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    if s_date is None:
        return status
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    if status == "예정":
        n = (s_date - today).days
        return "D-DAY" if n <= 0 else f"D-{n}"
    if status == "분양중":
        n = (e_date - today).days
        return "오늘 마감" if n <= 0 else f"마감 D-{n}"
    return "마감"


# ── 메인 ────────────────────────────────────────────────────────
def _render_subscriptions():
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    WD = ["월", "화", "수", "목", "금", "토", "일"]

    region = st.segmented_control(
        "지역", ["수도권", "서울", "경기"], default="수도권",
        key="re_sub_region", label_visibility="collapsed")
    rmap = {"서울": "seoul", "경기": "gg"}
    subs = fetch_subscriptions()
    live = subs is not _SAMPLE_SUBS

    items = []
    for row in subs:
        try:
            nm, gu, addr, typ, nse, s, e, mv, sd = row[:9]
        except (ValueError, TypeError):
            continue
        url = row[9] if len(row) > 9 else ""   # 10-튜플=청약홈 공고, 9-튜플=폴백
        if region in rmap and sd != rmap[region]:
            continue
        status, order = _sub_status(s, e)
        sdt, edt = _sub_window(s, e)
        items.append({"order": order, "s": s, "e": e, "sdt": sdt, "edt": edt,
                      "status": status, "dday": _sub_dday(sdt, edt, status),
                      "nm": nm, "gu": gu, "addr": addr, "typ": typ,
                      "nse": nse, "mv": mv, "sd": sd,
                      "url": (url or _APPLYHOME_LIST)})
    items.sort(key=lambda x: (x["order"], x["s"]))
    if not items:
        st.caption("해당 지역 분양 단지가 없어요.")
        return

    def _units(nse):
        try:
            return f"{int(nse):,}세대"
        except (ValueError, TypeError):
            return "-세대"

    # ── 청약 임박 하이라이트 (진행 중 + 7일 내 시작) ──
    def _urgent(it):
        if it["status"] == "분양중":
            return True
        if it["status"] == "예정" and it["sdt"] is not None:
            return 0 <= (it["sdt"] - today).days <= 7
        return False
    hot = [it for it in items if _urgent(it)]
    hot.sort(key=lambda it: (0 if it["status"] == "분양중" else 1, it["sdt"] or today))
    if hot:
        cards = ""
        for it in hot[:3]:
            reg_kr = "서울" if it["sd"] == "seoul" else "경기"
            nmap = _naver_n((it["addr"] + " " + it["nm"]).strip())
            cards += (f'<div class="re-hl-card">'
                      f'<span class="re-hl-dday">{it["dday"]}</span>'
                      f'<div class="re-hl-nm">{it["nm"]}</div>'
                      f'<div class="re-hl-meta">{reg_kr} {it["gu"]} · {it["typ"]} · {_units(it["nse"])}</div>'
                      f'<div class="re-hl-when">청약 {it["s"]}~{it["e"]} · 입주 {it["mv"]}</div>'
                      f'<div class="re-hl-acts">'
                      f'<a class="re-go-btn gold" href="{it["url"]}" target="_blank" rel="noopener">공고 ↗</a>'
                      f'{nmap}'
                      f'</div></div>')
        st.markdown('<div class="re-hl-sec">청약 임박 <span>진행 중 · 7일 내 시작</span></div>',
                    unsafe_allow_html=True)
        st.markdown(f'<div class="re-hl">{cards}</div>', unsafe_allow_html=True)

    # ── 향후 2주 청약 일정 타임라인 (시작/마감 이벤트일) ──
    ev = {}
    for it in items:
        if it["sdt"] is None:
            continue
        for d, kind in ((it["sdt"], "s"), (it["edt"], "e")):
            if today <= d <= today + timedelta(days=13):
                ev.setdefault(d, []).append((it["nm"], kind))
    if ev:
        cols = ""
        for d in sorted(ev.keys())[:8]:
            evs = ev[d]
            kind = "s" if any(k == "s" for _, k in evs) else "e"
            more = f" 외 {len(evs)-1}" if len(evs) > 1 else ""
            tag = "시작" if kind == "s" else "마감"
            cols += (f'<div class="re-tl-col"><div class="re-tl-d">{WD[d.weekday()]} {d.day}</div>'
                     f'<div class="re-tl-dot {kind}"></div>'
                     f'<div class="re-tl-c">{evs[0][0]}{more}<br>{tag}</div></div>')
        st.markdown('<div class="re-hl-sec">향후 2주 청약 일정 '
                    '<span>시작 ●초록 · 마감 ●빨강</span></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="re-tl">{cols}</div>', unsafe_allow_html=True)

    # ── 전체 리스트 (D-day 배지) ──
    st.markdown('<div class="re-hl-sec">전체 분양 단지</div>', unsafe_allow_html=True)
    bdg = {"분양중": ("#FCEBEB", "#A32D2D"), "예정": ("#EAF1EA", "#3F6F49"),
           "마감": ("#F0F1EC", "#8A8C82")}
    html = ""
    for it in items:
        bg, fg = bdg[it["status"]]
        reg_kr = "서울" if it["sd"] == "seoul" else "경기"
        nmap = _naver_n((it["addr"] + " " + it["nm"]).strip())
        html += (f'<div class="re-sub-card">'
                 f'<span class="re-sub-bdg" style="background:{bg};color:{fg}">{it["dday"]}</span>'
                 f'<div style="flex:1;min-width:0"><div class="re-sub-nm">{it["nm"]}</div>'
                 f'<div class="re-sub-meta">{reg_kr} {it["gu"]} · {it["typ"]} · '
                 f'{_units(it["nse"])} · {it["addr"]}</div>'
                 f'<div class="re-sub-when">청약 {it["s"]}~{it["e"]} · 입주 {it["mv"]}</div></div>'
                 f'<div class="re-sub-acts">'
                 f'<a class="re-go-btn" href="{it["url"]}" target="_blank" rel="noopener">공고 ↗</a>'
                 f'{nmap}'
                 f'</div></div>')
    st.markdown(html, unsafe_allow_html=True)
    if live:
        st.markdown(foot_row(
            "청약홈 · data.go.kr",
            "'공고 ↗'는 청약홈 해당 공고, 초록 N은 네이버 검색으로 이동 · "
            "D-day는 청약 시작일(예정)·마감일(진행 중) 기준 자동 계산 · "
            "진행/임박 우선"), unsafe_allow_html=True)
    else:
        st.markdown(foot_row(
            "청약홈 · 샘플",
            "'갱신'을 누르면 실데이터(청약홈 분양정보 활용신청 필요) · "
            "'공고 ↗'는 청약홈(샘플은 공고 목록), 초록 N은 네이버 검색으로 이동 · "
            "D-day는 청약 시작·마감일 기준 자동 계산"), unsafe_allow_html=True)
