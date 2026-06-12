"""전략·시황 보고서 뷰어 — 삭제·PDF 다운로드 지원, 미니멀 미스트 디자인.

레이아웃: render_reports() = 리포트 표시 (좌 2/3 본문 · 우 1/3 내 종목/주목 테마)
        render_reports_manage() = 지난 리포트 보기 + 삭제 UI (하단 배치용)
"""

import json
import re
from datetime import date
from pathlib import Path

import streamlit as st

from modules.stocks import naver_stock_url
from modules.mood import MOOD_KO, mood_css

REPORTS_DIR = Path("reports")

MOOD_CLS = {"positive": "mood-pos", "neutral": "mood-neu", "cautious": "mood-cau"}

_RPT_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Hanken+Grotesk:wght@400;600;700&family=Noto+Sans+KR:wght@400;500;700&display=swap');
.rpt-wrap{font-family:'Hanken Grotesk','Noto Sans KR',sans-serif;}
.rpt-toprow{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-wrap:wrap;gap:6px;}
.mood-badge{font-size:10.5px;font-weight:700;letter-spacing:.07em;padding:4px 11px;border-radius:20px;display:inline-block;}
__MOOD_BADGE_CSS__
.rpt-topmeta{font-size:11.5px;color:var(--muted,#9a9b92);}
.rpt-accent{height:3px;width:32px;background:var(--sage,#A7BBA9);border-radius:3px;margin:0 0 12px;}
.rpt-headline{font-family:'Fraunces','Noto Sans KR',Georgia,serif;font-size:21px;font-weight:600;letter-spacing:-.02em;color:var(--ink,#34352f);line-height:1.45;margin:6px 0 18px;}
.rpt-kt-wrap{margin-bottom:26px;}
.rpt-kt-label{font-size:10.5px;font-weight:700;letter-spacing:.07em;color:var(--sage-deep,#7E9A83);margin-bottom:6px;text-transform:uppercase;}
.rpt-kt-box{font-size:14.5px;line-height:1.85;color:var(--ink,#34352f);background:var(--summary-bg,#F6F7F2);border-left:3px solid var(--sage,#A7BBA9);padding:14px 18px;border-radius:0 12px 12px 0;}
.rpt-sec{margin:20px 0 0;}
.rpt-sec-title{font-size:15.5px;font-weight:700;color:var(--ink,#34352f);border-bottom:2px solid var(--sage,#A7BBA9);padding-bottom:5px;margin-bottom:9px;}
.rpt-sec-body{font-size:14px;line-height:1.9;color:var(--ink,#34352f);margin:0;}
.rpt-group-label{font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted,#9a9b92);margin:0 0 12px;padding-bottom:6px;border-bottom:1px solid var(--line,#ECEDE7);}
.rpt-side .rpt-group-label{margin-top:4px;}
.rpt-side .rpt-group-label + .theme-card{margin-top:0;}
.theme-card{background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);border-left:3px solid var(--sage,#A7BBA9);border-radius:0 13px 13px 0;padding:13px 16px 11px;margin-bottom:10px;}
.theme-name{font-size:14px;font-weight:700;color:var(--ink,#34352f);margin-bottom:5px;}
.theme-detail{font-size:13px;line-height:1.75;color:var(--ink,#34352f);margin-bottom:8px;}
.theme-tickers{font-size:11.5px;color:var(--muted,#9a9b92);}
.theme-tickers a{color:var(--sage-deep,#7E9A83);font-weight:600;text-decoration:none;background:var(--pill-bg,#F1F2EC);padding:2px 8px;border-radius:6px;border:1px solid var(--line,#ECEDE7);margin-right:4px;}
.rpt-side-gap{height:20px;}
</style>
"""

_RPT_CSS = _RPT_CSS.replace("__MOOD_BADGE_CSS__", mood_css("mood"))


# ── 파일 목록 / 유틸 ──────────────────────────────────────────

def list_reports():
    if not REPORTS_DIR.exists():
        return []
    files = sorted(REPORTS_DIR.glob("*.json"), reverse=True)
    if not files:
        files = sorted(REPORTS_DIR.glob("*.md"), reverse=True)
    return files


def _report_date(path: Path) -> date:
    try:
        y, m, d = path.stem.split("_")[0].split("-")
        return date(int(y), int(m), int(d))
    except Exception:
        return date.today()


def _load(path: Path) -> dict:
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    text = path.read_text(encoding="utf-8")
    m = re.search(r"##\s*한 줄 요약\n+(.+?)(?=\n##|\Z)", text, re.S)
    return {
        "headline": m.group(1).strip() if m else path.stem,
        "key_takeaway": "",
        "sections": [{"title": "보고서 본문", "body": text}],
        "themes": [], "keywords": [],
        "mood": "neutral", "generated_at": "",
        "messages_count": 0,
    }


def _label(path: Path) -> str:
    name = path.stem
    try:
        d, t = name.split("_")
        return f"{d} {t[:2]}:{t[2:]}"
    except ValueError:
        return name


def _label_with_headline(path: Path) -> str:
    base = _label(path)
    try:
        data = _load(path)
        hl = data.get("headline", "")
        if hl:
            return f"{base} — {hl[:30]}{'…' if len(hl) > 30 else ''}"
    except Exception:
        pass
    return base


def _extract_stocks(text: str) -> list:
    """종목명 추출 — JSON·구형 MD 양쪽 지원. (외부 모듈 호환용)"""
    try:
        data = json.loads(text)
        stocks = set()
        for th in data.get("themes", []):
            for t in (th.get("tickers") or "").split(","):
                if t.strip():
                    stocks.add(t.strip())
        for kw in data.get("keywords", []):
            for t in (kw.get("related") or "").split(","):
                if t.strip():
                    stocks.add(t.strip())
        return sorted(stocks)
    except Exception:
        pass
    m = re.search(r"##\s*언급[^\n]*종목[^\n]*\n+(.+?)(?=\n##|\Z)", text, re.S)
    if not m:
        return []
    parts = re.split(r"[,·\n/]", m.group(1))
    return [p.strip().strip("-•*· ").strip()
            for p in parts
            if p.strip() and len(p.strip()) <= 20 and not p.strip().startswith("#")]


def _selected_report(files):
    """현재 선택된 리포트 (기본 = 최신). render_reports / render_reports_manage 공용."""
    selected = files[0]
    picked_key = st.session_state.get("rpt_picked_path")
    if picked_key and Path(picked_key).exists() and Path(picked_key) in files:
        selected = Path(picked_key)
    return selected


# ── 렌더링: 본문 (좌측 2/3) ──────────────────────────────────

def _render_report_main(data: dict):
    """헤드라인 · 오늘의 관전 · 본문 섹션."""
    mood     = data.get("mood", "neutral")
    mood_ko  = MOOD_KO.get(mood, mood)
    mood_cls = MOOD_CLS.get(mood, "mood-neu")
    gen_at   = data.get("generated_at", "")
    n_msg    = data.get("messages_count", 0)
    headline = data.get("headline", "전략·시황 보고서")

    meta_right = gen_at + (f" · {n_msg}개 메시지" if n_msg else "")
    st.markdown(
        f'<div class="rpt-wrap">'
        f'<div class="rpt-accent"></div>'
        f'<div class="rpt-toprow">'
        f'  <span class="mood-badge {mood_cls}">{mood_ko.upper()}</span>'
        f'  <span class="rpt-topmeta">{meta_right}</span>'
        f'</div>'
        f'<div class="rpt-headline">{headline}</div>'
        f'</div>', unsafe_allow_html=True)

    kt = data.get("key_takeaway", "")
    if kt:
        st.markdown(
            f'<div class="rpt-kt-wrap">'
            f'<div class="rpt-kt-label">오늘의 관전</div>'
            f'<div class="rpt-kt-box">{kt}</div>'
            f'</div>', unsafe_allow_html=True)

    for sec in data.get("sections", []):
        title = sec.get("title", "")
        body  = sec.get("body", "")
        if not title and not body:
            continue
        st.markdown(
            f'<div class="rpt-sec">'
            f'<div class="rpt-sec-title">{title}</div>'
            f'<div class="rpt-sec-body">{body}</div>'
            f'</div>', unsafe_allow_html=True)


# ── 렌더링: 사이드 (우측 1/3) ────────────────────────────────

def _render_report_side(data: dict):
    """내 종목 · 주목 테마."""
    rendered = False

    wl = data.get("watchlist_mentions", [])
    if wl:
        st.markdown('<div class="rpt-side">'
                    '<div class="rpt-group-label">⭐ 내 종목</div></div>',
                    unsafe_allow_html=True)
        for w in wl:
            stock = w.get("stock", "")
            summary = w.get("summary", "")
            if not stock:
                continue
            st.markdown(
                f'<div class="theme-card">'
                f'<div class="theme-name"><a href="{naver_stock_url(stock)}" target="_blank" '
                f'style="color:inherit;text-decoration:none;">{stock}</a></div>'
                f'<div class="theme-detail">{summary}</div>'
                f'</div>', unsafe_allow_html=True)
        rendered = True

    themes = data.get("themes", [])
    if themes:
        if rendered:
            st.markdown('<div class="rpt-side-gap"></div>', unsafe_allow_html=True)
        st.markdown('<div class="rpt-side">'
                    '<div class="rpt-group-label">주목 테마</div></div>',
                    unsafe_allow_html=True)
        for th in themes:
            name    = th.get("name", "")
            detail  = th.get("detail", "")
            tickers = [t.strip() for t in (th.get("tickers") or "").split(",") if t.strip()]
            tickers_html = "".join(
                f'<a href="{naver_stock_url(t)}" target="_blank">{t}</a>'
                for t in tickers)
            st.markdown(
                f'<div class="theme-card">'
                f'<div class="theme-name">{name}</div>'
                f'<div class="theme-detail">{detail}</div>'
                + (f'<div class="theme-tickers">관련: {tickers_html}</div>' if tickers_html else "")
                + '</div>', unsafe_allow_html=True)
        rendered = True

    if not rendered:
        st.caption("이 리포트에는 내 종목·테마 정보가 없어요.")


# ── 삭제 UI ─────────────────────────────────────────────────

def _render_delete_ui(files):
    with st.expander("🗑️ 리포트 삭제"):
        labels = {str(f): _label_with_headline(f) for f in files}
        to_delete = st.multiselect(
            "삭제할 리포트 선택",
            options=[str(f) for f in files],
            format_func=lambda s: labels[s],
            key="rpt_del_sel")

        if to_delete:
            st.warning(f"{len(to_delete)}개 리포트를 삭제합니다. 되돌릴 수 없어요.")
            confirm = st.checkbox("삭제를 확인합니다", key="rpt_del_confirm")
            if st.button("선택한 리포트 삭제", type="primary", disabled=not confirm):
                removed = 0
                for s in to_delete:
                    try:
                        Path(s).unlink()
                        removed += 1
                    except Exception as e:
                        st.error(f"삭제 실패: {Path(s).name} ({e})")
                st.success(f"{removed}개 삭제 완료")
                st.rerun()


# ── 메인: 리포트 표시 (탭 상단 배치용) ───────────────────────

def render_reports():
    """최신(또는 선택된) 리포트를 좌 2/3 본문 · 우 1/3 사이드로 표시."""
    st.markdown(_RPT_CSS, unsafe_allow_html=True)

    files = list_reports()
    if not files:
        st.markdown(
            '<div class="empty"><div class="ico">📰</div>'
            '<div class="msg">아직 생성된 리포트가 없어요</div>'
            '<div class="hint">📝 아래 리포트 생성 버튼으로 첫 리포트를 만들어보세요</div></div>',
            unsafe_allow_html=True)
        return

    selected = _selected_report(files)
    is_latest = (selected == files[0])

    try:
        data = _load(selected)
    except Exception as e:
        st.error(f"리포트를 불러오지 못했어요: {e}")
        return

    # 최신/과거 표시 배지 + PDF 다운로드 (한 줄 정렬)
    badge = "최신" if is_latest else f"과거 · {_label(selected)}"
    meta_col, pdf_col = st.columns([3, 1])
    with meta_col:
        st.caption(f"📄 {badge} 리포트")
    with pdf_col:
        try:
            from modules.report_pdf import build_pdf
            pdf_bytes = build_pdf(data)
            st.download_button(
                "📄 PDF",
                data=pdf_bytes,
                file_name=f"{selected.stem}.pdf",
                mime="application/pdf",
                key="rpt_pdf_dl",
                use_container_width=True)
        except Exception as e:
            st.caption(f"PDF 불가: {e}")

    # 좌 2/3 본문 · 우 1/3 내 종목/주목 테마 (모바일에선 자동 세로 스택)
    left, right = st.columns([2, 1], gap="large")
    with left:
        _render_report_main(data)
    with right:
        _render_report_side(data)


# ── 메인: 리포트 관리 (탭 하단 배치용) ───────────────────────

def render_reports_manage():
    """지난 리포트 보기 + 삭제 UI. render_reports() 아래쪽에 배치."""
    files = list_reports()
    if not files:
        return

    selected = _selected_report(files)
    is_latest = (selected == files[0])
    picked_key = st.session_state.get("rpt_picked_path")

    # 과거 리포트 탐색 (접이식)
    if len(files) > 1:
        with st.expander(f"🗂 지난 리포트 보기 ({len(files)}개)"):
            dates = [_report_date(f) for f in files]
            lo, hi = min(dates), max(dates)
            date_range = st.date_input("기간", value=(lo, hi),
                                       min_value=lo, max_value=hi, key="rpt_dates")
            start = end = None
            if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
                start, end = date_range
            filtered = [f for f in files
                        if (not start or _report_date(f) >= start)
                        and (not end or _report_date(f) <= end)]
            if filtered:
                cur_idx = filtered.index(selected) if selected in filtered else 0
                idx = st.selectbox(
                    "리포트 선택", options=range(len(filtered)), index=cur_idx,
                    format_func=lambda i: _label_with_headline(filtered[i]),
                    key="rpt_pick")
                chosen = filtered[idx]
                if str(chosen) != picked_key:
                    st.session_state["rpt_picked_path"] = str(chosen)
                    if chosen != selected:
                        st.rerun()
                if not is_latest and st.button("↩ 최신 리포트로", key="rpt_to_latest"):
                    st.session_state["rpt_picked_path"] = str(files[0])
                    st.rerun()
            else:
                st.caption("해당 기간에 리포트가 없습니다.")

    # 삭제 UI
    _render_delete_ui(files)
