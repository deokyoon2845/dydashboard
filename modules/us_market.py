# -*- coding: utf-8 -*-
"""글로벌 탭 '미국 전일 시장' — 업종 등락 · 시총 Top50 · 이슈 종목 뉴스.

데이터: 엔진(engine/usmkt_run · 07:20/08:20 KST)이 usmkt_snapshots에 저장한
최신 스냅샷만 읽는다(뷰어 라이브 호출 없음 — 아키텍처 원칙).
행이 없으면 섹션 전체를 조용히 생략해 기존 글로벌 탭 무회귀.

시각 문법은 글로벌 지수 히트맵과 통일: 빨강=상승 / 파랑=하락, ±3%에서 틴트 최대.
순수 HTML/CSS 렌더(JS 없음) — st.markdown 한 번으로 그린다.
"""
import html as _html

import streamlit as st

from modules.db import load_usmkt

_UP, _DN = "#B65F5A", "#5A7CA0"          # 상승·하락(전역 시맨틱)
_MAXP = 3.0                              # 틴트·바 최대치(±3%)


def _tint(chg, a_max=0.22):
    """등락률 → 배경 틴트 rgba (±3%에서 최대, 히트맵과 동일 문법)."""
    if chg is None:
        return "transparent"
    a = min(abs(chg), _MAXP) / _MAXP * a_max
    rgb = "182,95,90" if chg >= 0 else "90,124,160"
    return f"rgba({rgb},{a:.3f})"


def _col(chg):
    return _UP if (chg or 0) >= 0 else _DN


def _pct(chg):
    return f"{chg:+.2f}%" if chg is not None else "—"


def _sector_rows(sectors):
    """업종 11종 — 0 기준 중앙선에서 좌(하락)/우(상승)로 뻗는 바."""
    rows = []
    for s in sorted(sectors, key=lambda x: -(x.get("chg") or 0)):
        chg = s.get("chg") or 0.0
        w = min(abs(chg), _MAXP) / _MAXP * 50           # 반폭 최대 50%
        side = ("left:50%" if chg >= 0 else f"left:{50 - w:.1f}%")
        rows.append(
            f'<div class="usm-srow">'
            f'<span class="usm-snm">{_html.escape(s["nm"])}</span>'
            f'<span class="usm-sbar"><i style="{side};width:{w:.1f}%;'
            f'background:{_col(chg)}"></i></span>'
            f'<span class="usm-schg" style="color:{_col(chg)}">{_pct(chg)}</span>'
            f'</div>')
    return "".join(rows)


def _top50_grid(top50):
    tiles = []
    for i, r in enumerate(top50, 1):
        chg = r.get("chg")
        sus = ' <span class="usm-sus" title="등락 재검증 불가 — 참고용">?</span>' \
              if r.get("suspect") else ""
        tiles.append(
            f'<div class="usm-tile" style="background:{_tint(chg)}">'
            f'<div class="usm-tk">{_html.escape(r["tk"])}'
            f'<span class="usm-rk">{i}</span></div>'
            f'<div class="usm-nm">{_html.escape(r["nm"])}</div>'
            f'<div class="usm-chg" style="color:{_col(chg)}">{_pct(chg)}{sus}</div>'
            f'</div>')
    return "".join(tiles)


def _issue_cards(issues):
    cards = []
    for it in issues:
        chg = it.get("chg")
        links = "".join(
            f'<a class="usm-news" href="{_html.escape(n.get("u") or "#")}" '
            f'target="_blank" rel="noopener">'
            f'{_html.escape(n.get("t") or "")}'
            f'<span class="usm-nsrc">{_html.escape(n.get("src") or "")}</span></a>'
            for n in (it.get("news") or []))
        if not links:
            links = '<div class="usm-nonews">관련 기사 없음</div>'
        cards.append(
            f'<div class="usm-icard" style="border-left-color:{_col(chg)}">'
            f'<div class="usm-ihead"><b>{_html.escape(it["nm"])}</b>'
            f'<span class="usm-itk">{_html.escape(it["tk"])}</span>'
            f'<span class="usm-ichg" style="color:{_col(chg)}">{_pct(chg)}</span>'
            f'</div>{links}</div>')
    return "".join(cards)


_CSS = """
<style>
.usm-wrap{margin:6px 0 2px}
.usm-sub{font-size:12px;color:#8a8d84;margin:2px 0 12px}
.usm-h{font-size:13px;font-weight:800;color:#34352f;margin:16px 0 8px}
/* 업종 바 */
.usm-srow{display:flex;align-items:center;gap:10px;padding:3.5px 0}
.usm-snm{width:86px;font-size:12px;color:#5d6258;font-weight:600;flex:none}
.usm-sbar{flex:1;height:9px;background:#F1F2EC;border-radius:5px;position:relative;overflow:hidden}
.usm-sbar::after{content:"";position:absolute;left:50%;top:0;bottom:0;width:1px;background:#D9DAD2}
.usm-sbar i{position:absolute;top:0;bottom:0;border-radius:5px;opacity:.85}
.usm-schg{width:62px;text-align:right;font-size:12px;font-weight:700;
  font-variant-numeric:tabular-nums;flex:none}
/* 시총 그리드 */
.usm-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:7px}
@media(max-width:760px){.usm-grid{grid-template-columns:repeat(3,1fr)}}
.usm-tile{border:1px solid #E4E5DE;border-radius:9px;padding:8px 9px 7px;min-width:0}
.usm-tk{font-size:12.5px;font-weight:800;color:#34352f;display:flex;
  justify-content:space-between;align-items:baseline}
.usm-rk{font-size:9.5px;font-weight:600;color:#b0b2a8}
.usm-nm{font-size:10.5px;color:#8a8d84;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;margin:1px 0 3px}
.usm-chg{font-size:12px;font-weight:700;font-variant-numeric:tabular-nums}
.usm-sus{color:#b0b2a8;font-weight:600;cursor:help}
/* 이슈 카드 */
.usm-igrid{display:grid;grid-template-columns:repeat(2,1fr);gap:9px}
@media(max-width:760px){.usm-igrid{grid-template-columns:1fr}}
.usm-icard{border:1px solid #E4E5DE;border-left-width:3px;border-radius:9px;
  padding:9px 12px;background:#fff}
.usm-ihead{display:flex;align-items:baseline;gap:7px;margin-bottom:5px;font-size:13px}
.usm-itk{font-size:11px;color:#8a8d84;font-weight:600}
.usm-ichg{margin-left:auto;font-weight:800;font-variant-numeric:tabular-nums}
.usm-news{display:block;font-size:12px;color:#5d6258;text-decoration:none;
  padding:3px 0;line-height:1.45;border-top:1px dashed #EDEEE8}
.usm-news:first-of-type{border-top:none}
.usm-news:hover{color:#34352f;text-decoration:underline}
.usm-nsrc{font-size:10px;color:#b0b2a8;margin-left:6px}
.usm-nonews{font-size:11.5px;color:#b0b2a8;padding:2px 0}
</style>"""


def render_us_market():
    """글로벌 탭에서 호출 — 스냅샷 없으면 조용히 생략(무회귀)."""
    try:
        d = load_usmkt()
    except Exception:
        d = None
    if not d or not (d.get("payload") or {}).get("sectors"):
        return
    p = d["payload"]

    try:
        from modules.ui import foot_badge
        badge = foot_badge(
            "Yahoo Finance · 네이버 뉴스 · 전일 종가",
            "업종 = SPDR 섹터 ETF 11종 · 시총 Top50은 매일 실시간 시가총액으로 재랭킹 · "
            "이슈 = 대형 120종 중 전일 ±4% 이상, 제목에 종목명이 포함된 기사만 연결 · "
            "빨강 상승/파랑 하락, ±3%에서 틴트 최대(글로벌 히트맵과 동일)")
    except Exception:
        badge = ""
    st.markdown(
        f'<div class="sect-banner ui-fx" id="sec-usmkt">미국 전일 시장{badge}</div>',
        unsafe_allow_html=True)

    parts = [_CSS, '<div class="usm-wrap">']
    td = p.get("trade_date") or ""
    parts.append(f'<div class="usm-sub">거래 기준일 {td} (미 동부 마감) · '
                 f'수집 {p.get("asof", "")} KST</div>')

    parts.append('<div class="usm-h">업종별 등락 — SPDR 섹터 ETF</div>')
    parts.append(_sector_rows(p.get("sectors") or []))

    if p.get("top50"):
        parts.append('<div class="usm-h">시총 Top 50</div>')
        parts.append(f'<div class="usm-grid">{_top50_grid(p["top50"])}</div>')

    if p.get("issues"):
        parts.append('<div class="usm-h">이슈 종목 — 전일 ±4% 이상 · 관련 기사</div>')
        parts.append(f'<div class="usm-igrid">{_issue_cards(p["issues"])}</div>')
    elif p.get("movers"):
        mv = p["movers"]
        line = " · ".join(f'{x["nm"]} {_pct(x.get("chg"))}'
                          for x in (mv.get("up") or [])[:3])
        parts.append(f'<div class="usm-sub">±4% 이슈 종목 없음 — '
                     f'상승 상위: {_html.escape(line)}</div>')

    parts.append('</div>')
    st.markdown("".join(parts), unsafe_allow_html=True)
