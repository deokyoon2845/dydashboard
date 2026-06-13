# modules/strategy_extras.py
# ─────────────────────────────────────────────────────────────
# 전략·시황 탭 추가 렌더 함수 3종 (드롭인)
#   render_tldr            : 헤드라인 + mood + 한 줄 요약 (상단 히어로)
#   render_cross_check     : 시장 시각(텔레그램) vs 실제 데이터(정량) 교차 검증
#   render_drivers_matrix  : 단기·장기 × 상승·하락 4분면 매트릭스
#
# 각 함수는 보고서 dict 하나만 받습니다. 해당 필드가 없으면 안전하게 넘어갑니다.
# (옛 형식 보고서에서도 에러 없이 동작)
# 색은 '미니멀 미스트' 라이트 단일 팔레트 고정.
# ─────────────────────────────────────────────────────────────

import streamlit as st

# ── 디자인 토큰 ──────────────────────────────
BG     = "#FCFCFA"
INK    = "#34352f"
SAGE   = "#7E9A83"
SAGE_L = "#A7BBA9"
UP     = "#B65F5A"   # 상승 = 적
DOWN   = "#5A7CA0"   # 하락 = 청
LINE   = "#e7e6e1"
MUTED  = "#8a8a82"

# mood 라벨 → (배경, 글자색, 표시문구)
_MOOD = {
    "긍정": ("#eef3ef", SAGE,  "긍정"),
    "중립": ("#f2f2ef", MUTED, "중립"),
    "주의": ("#f6edec", UP,    "주의"),
    "부정": ("#edf1f5", DOWN,  "부정"),
}


def _pill(text, bg, fg):
    return (f"<span style='display:inline-block;padding:2px 10px;border-radius:999px;"
            f"background:{bg};color:{fg};font-size:12px;font-weight:600;"
            f"font-family:\"Hanken Grotesk\",\"Noto Sans KR\",sans-serif;'>{text}</span>")


# ─────────────────────────────────────────────────────────────
# 1) 상단 TL;DR 히어로
# ─────────────────────────────────────────────────────────────
def render_tldr(report: dict):
    """헤드라인 + mood 배지 + 오늘의 관전 한 줄.
    ※ reports.py에서 이미 헤드라인을 따로 출력 중이면, 중복을 피하려고
       그 헤드라인 줄은 지우고 이 함수로 대체하세요."""
    headline = (report.get("headline") or "").strip()
    if not headline:
        return

    mood = (report.get("mood") or "중립").strip()
    bg, fg, label = _MOOD.get(mood, _MOOD["중립"])

    takeaway = (report.get("key_takeaway") or "").strip()
    if len(takeaway) > 90:                       # 한 줄 요약 느낌으로 컷
        takeaway = takeaway[:88].rstrip() + "…"

    takeaway_html = (
        f"<div style='margin-top:8px;font-size:14px;color:{MUTED};line-height:1.5;'>{takeaway}</div>"
        if takeaway else ""
    )

    html = f"""
    <div style="border:1px solid {LINE};border-left:4px solid {SAGE_L};border-radius:14px;
                padding:18px 20px;background:{BG};margin:4px 0 14px;">
      <div style="margin-bottom:8px;">{_pill(label, bg, fg)}</div>
      <div style="font-family:'Fraunces',Georgia,serif;font-size:22px;line-height:1.3;
                  font-weight:600;color:{INK};">{headline}</div>
      {takeaway_html}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# 2) 교차 검증 카드 (cross_check)
# ─────────────────────────────────────────────────────────────
def render_cross_check(report: dict):
    """시장 시각(텔레그램) vs 실제 데이터(정량) → 판정 + 통찰.
    cross_check 필드가 없으면 아무것도 그리지 않음."""
    cc = report.get("cross_check") or {}
    mv  = (cc.get("market_view") or "").strip()
    df  = (cc.get("data_fact") or "").strip()
    vd  = (cc.get("verdict") or "").strip()
    ins = (cc.get("insight") or "").strip()
    if not (mv or df):
        return

    box = f"border:1px solid {LINE};border-radius:12px;padding:14px 16px;background:#fff;"

    # 판정 + 통찰 블록
    verdict_block = ""
    if vd or ins:
        pill = _pill(f"판정 · {vd}", "#f2f2ef", INK) if vd else ""
        gap  = "&nbsp;&nbsp;" if (vd and ins) else ""
        insight = (f"<span style='font-size:14px;color:{INK};line-height:1.55;'>{ins}</span>"
                   if ins else "")
        verdict_block = (f"<div style='margin-top:10px;padding:12px 14px;border-radius:10px;"
                         f"background:#f7f7f4;'>{pill}{gap}{insight}</div>")

    html = f"""
    <div style="margin:10px 0 16px;">
      <div style="font-size:13px;font-weight:700;color:{INK};margin-bottom:8px;
                  font-family:'Hanken Grotesk','Noto Sans KR',sans-serif;">🔎 교차 검증</div>
      <div style="display:flex;gap:12px;flex-wrap:wrap;">
        <div style="flex:1;min-width:220px;{box}border-top:3px solid {SAGE_L};">
          <div style="font-size:12px;color:{SAGE};font-weight:700;margin-bottom:4px;">시장 시각 · 텔레그램</div>
          <div style="font-size:14px;color:{INK};line-height:1.55;">{mv or '—'}</div>
        </div>
        <div style="flex:1;min-width:220px;{box}border-top:3px solid {DOWN};">
          <div style="font-size:12px;color:{DOWN};font-weight:700;margin-bottom:4px;">실제 데이터 · 정량</div>
          <div style="font-size:14px;color:{INK};line-height:1.55;">{df or '—'}</div>
        </div>
      </div>
      {verdict_block}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# 3) 단기·장기 매트릭스 (market_drivers)
# ─────────────────────────────────────────────────────────────
def render_drivers_matrix(report: dict):
    """단기/장기 × 상승/하락 4분면. market_drivers 필드가 없으면 안내만 표시."""
    md  = report.get("market_drivers") or {}
    stm = md.get("short_term") or {}
    ltm = md.get("long_term") or {}

    has_any = any([stm.get("up"), stm.get("down"), ltm.get("up"), ltm.get("down")])
    if not has_any:
        st.caption("📐 단기·장기 매트릭스는 새 형식 보고서부터 표시됩니다.")
        return

    def cell(items, color, arrow):
        items = items or []
        if not items:
            inner = f"<div style='font-size:13px;color:{MUTED};'>—</div>"
        else:
            rows = ""
            for it in items:
                if isinstance(it, dict):
                    lab = (it.get("label") or "").strip()
                    dsc = (it.get("desc") or "").strip()
                else:
                    lab, dsc = str(it), ""
                desc_html = f"<span style='color:{MUTED};font-size:13px;'> · {dsc}</span>" if dsc else ""
                rows += (f"<div style='margin-bottom:7px;'>"
                         f"<span style='font-weight:700;color:{INK};font-size:14px;'>{lab}</span>"
                         f"{desc_html}</div>")
            inner = rows
        return (f"<div style='flex:1;min-width:200px;border:1px solid {LINE};border-radius:12px;"
                f"padding:14px 16px;background:#fff;border-top:3px solid {color};'>"
                f"<div style='font-size:12px;font-weight:800;color:{color};margin-bottom:8px;'>"
                f"{arrow}</div>{inner}</div>")

    def row(title, data):
        return (f"<div style='margin-bottom:10px;'>"
                f"<div style='font-size:13px;font-weight:700;color:{INK};margin-bottom:6px;'>{title}</div>"
                f"<div style='display:flex;gap:12px;flex-wrap:wrap;'>"
                f"{cell(data.get('up'),   UP,   '▲ 상승 동력')}"
                f"{cell(data.get('down'), DOWN, '▼ 하락 압력')}"
                f"</div></div>")

    html = (f"<div style='margin:10px 0 16px;'>"
            f"<div style='font-size:13px;font-weight:700;color:{INK};margin-bottom:8px;"
            f"font-family:\"Hanken Grotesk\",\"Noto Sans KR\",sans-serif;'>📐 단기·장기 매트릭스</div>"
            f"{row('단기 (수급·이벤트)', stm)}"
            f"{row('장기 (구조·추세)',   ltm)}"
            f"</div>")
    st.markdown(html, unsafe_allow_html=True)
