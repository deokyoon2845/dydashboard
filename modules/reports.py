"""시황 리포트 뷰어 + 아카이브 (검색·기간 필터 + 클릭 가능한 종목)."""

import re
from datetime import date
from pathlib import Path

import streamlit as st

from modules.stocks import stock_pills_html

REPORTS_DIR = Path("reports")


def list_reports():
    if not REPORTS_DIR.exists():
        return []
    return sorted(REPORTS_DIR.glob("*.md"), reverse=True)


def _label(path: Path) -> str:
    name = path.stem
    try:
        d, t = name.split("_")
        return f"{d} {t[:2]}:{t[2:]}"
    except ValueError:
        return name


def _report_date(path: Path) -> date:
    try:
        y, m, d = path.stem.split("_")[0].split("-")
        return date(int(y), int(m), int(d))
    except Exception:
        return date.today()


def _parse(text: str):
    """(메타, 한줄요약, 본문) 분리."""
    if "\n---\n" in text:
        header, body = text.split("\n---\n", 1)
    else:
        header, body = "", text
    meta_vals = re.findall(r"-\s*\*\*[^*]+\*\*:\s*(.+)", header)
    meta = " · ".join(v.strip() for v in meta_vals)
    summary = ""
    m = re.search(r"##\s*[^\n]*요약[^\n]*\n+(.+?)(?=\n##|\Z)", body, re.S)
    if m:
        summary = m.group(1).strip()
        body = (body[: m.start()] + body[m.end():]).strip()
    return meta, summary, body.strip()


def _extract_stocks(text: str):
    """'언급된 종목·섹터' 섹션에서 종목명 리스트 추출."""
    m = re.search(r"##\s*언급[^\n]*종목[^\n]*\n+(.+?)(?=\n##|\Z)", text, re.S)
    if not m:
        return []
    parts = re.split(r"[,\u00b7\n/]", m.group(1))
    out = []
    for p in parts:
        p = p.strip().strip("-•*· ").strip()
        if p and len(p) <= 20 and not p.startswith("#"):
            out.append(p)
    return out


def _strip_section(body: str, keyword: str) -> str:
    return re.sub(rf"##\s*[^\n]*{keyword}[^\n]*\n+.+?(?=\n##|\Z)", "", body, flags=re.S).strip()


def _label_with_summary(path: Path) -> str:
    base = _label(path)
    try:
        _, summary, _ = _parse(path.read_text(encoding="utf-8"))
        if summary:
            return f"{base} — {summary[:28]}…"
    except Exception:
        pass
    return base


def _filter(files, keyword, date_range):
    keyword = (keyword or "").strip().lower()
    start = end = None
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start, end = date_range
    out = []
    for f in files:
        d = _report_date(f)
        if start and d < start:
            continue
        if end and d > end:
            continue
        if keyword and keyword not in f.read_text(encoding="utf-8").lower():
            continue
        out.append(f)
    return out


def render_reports():
    files = list_reports()
    if not files:
        st.markdown(
            '<div class="empty"><div class="ico">📰</div>'
            '<div class="msg">아직 생성된 리포트가 없어요</div>'
            '<div class="hint">위 "📝 리포트 생성" 버튼으로 첫 리포트를 만들어보세요</div></div>',
            unsafe_allow_html=True,
        )
        return

    c1, c2 = st.columns([2, 1])
    with c1:
        keyword = st.text_input("🔍 키워드 검색", placeholder="예: 반도체, CPI, 환율", key="rpt_kw")
    with c2:
        dates = [_report_date(f) for f in files]
        lo, hi = min(dates), max(dates)
        date_range = st.date_input("기간", value=(lo, hi), min_value=lo, max_value=hi, key="rpt_dates")

    filtered = _filter(files, keyword, date_range)
    if not filtered:
        st.warning("조건에 맞는 리포트가 없습니다.")
        return

    st.caption(f"{len(filtered)}개 리포트")
    idx = st.selectbox("리포트 선택", options=range(len(filtered)),
                       format_func=lambda i: _label_with_summary(filtered[i]), key="rpt_pick")

    full = filtered[idx].read_text(encoding="utf-8")
    meta, summary, body = _parse(full)

    st.markdown('<div class="rpt-bar"></div>', unsafe_allow_html=True)
    st.markdown('<div class="rpt-title">시황 분석 보고서</div>', unsafe_allow_html=True)
    if meta:
        st.markdown(f'<div class="rpt-meta">{meta}</div>', unsafe_allow_html=True)
    if summary:
        st.markdown(f'<div class="rpt-summary">{summary}</div>', unsafe_allow_html=True)

    stocks = _extract_stocks(full)
    if stocks:
        st.markdown('<div class="rpt-meta" style="margin-top:10px;">언급 종목 (클릭 시 시세)</div>'
                    f'<div style="margin-top:5px;">{stock_pills_html(stocks)}</div>',
                    unsafe_allow_html=True)
        body = _strip_section(body, "종목")

    st.markdown(body)
