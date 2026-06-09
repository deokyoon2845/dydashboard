"""시황 리포트 뷰어 — JSON 구조화 포맷 렌더링."""

import json
import re
from datetime import date
from pathlib import Path

import streamlit as st

from modules.stocks import stock_pills_html, naver_stock_url

REPORTS_DIR = Path("reports")

MOOD_KO = {"positive": "긍정", "neutral": "중립", "cautious": "주의"}
MOOD_CLS = {"positive": "mood-pos", "neutral": "mood-neu", "cautious": "mood-cau"}


def list_reports():
    if not REPORTS_DIR.exists():
        return []
    files = sorted(REPORTS_DIR.glob("*.json"), reverse=True)
    if not files:                              # 구형 .md 폴백
        files = sorted(REPORTS_DIR.glob("*.md"), reverse=True)
    return files


def _report_date(path: Path) -> date:
    try:
        y, m, d = path.stem.split("_")[0].split("-")
        return date(int(y), int(m), int(d))
    except Exception:
        return date.today()


def _load(path: Path) -> dict:
    """JSON 또는 구형 .md 파일을 통일된 dict로 로드."""
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    # 구형 .md → 최소 변환
    text = path.read_text(encoding="utf-8")
    summary_m = re.search(r"##\s*한 줄 요약\n+(.+?)(?=\n##|\Z)", text, re.S)
    return {
        "headline": summary_m.group(1).strip() if summary_m else path.stem,
        "key_takeaway": "",
        "sections": [{"title": "보고서 본문", "body": text}],
        "themes": [],
        "keywords": [],
        "mood": "neutral",
        "generated_at": "",
        "messages_count": 0,
        "source_channels": [],
    }


def _label(path: Path) -> str:
    name = path.stem
    try:
        d, t = name.split("_")
        return f"{d} {t[:2]}:{t[2:]}"
    except ValueError:
        return name


def _extract_stocks(text: str) -> list:
    """종목명 리스트 추출 — JSON·구형 MD 양쪽 지원."""
    # JSON 포맷
    try:
        data = json.loads(text)
        stocks = set()
        for th in data.get("themes", []):
            for t in (th.get("tickers") or "").split(","):
                t = t.strip()
                if t: stocks.add(t)
        for kw in data.get("keywords", []):
            for t in (kw.get("related") or "").split(","):
                t = t.strip()
                if t: stocks.add(t)
        return sorted(stocks)
    except Exception:
        pass
    # 구형 MD 포맷
    import re as _re
    m = _re.search(r"##\s*언급[^\n]*종목[^\n]*\n+(.+?)(?=\n##|\Z)", text, _re.S)
    if not m:
        return []
    parts = _re.split(r"[,·\n/]", m.group(1))
    return [p.strip().strip("-•*· ").strip()
            for p in parts if p.strip() and len(p.strip()) <= 20 and not p.strip().startswith("#")]
    base = _label(path)
    try:
        data = _load(path)
        hl = data.get("headline", "")
        if hl:
            return f"{base} — {hl[:30]}{'…' if len(hl)>30 else ''}"
    except Exception:
        pass
    return base


def _filter(files, keyword, date_range):
    kw = (keyword or "").strip().lower()
    start = end = None
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start, end = date_range
    out = []
    for f in files:
        d = _report_date(f)
        if start and d < start: continue
        if end and d > end: continue
        if kw and kw not in f.read_text(encoding="utf-8").lower(): continue
        out.append(f)
    return out


# ── 렌더링 ─────────────────────────────────────────────────────

def _render_report(data: dict):
    mood = data.get("mood", "neutral")
    mood_ko = MOOD_KO.get(mood, mood)
    mood_cls = MOOD_CLS.get(mood, "mood-neu")
    gen_at = data.get("generated_at", "")
    n_msg = data.get("messages_count", 0)
    headline = data.get("headline", "시황 분석 보고서")

    # ── 상단 행: 감성 배지 + 날짜·메시지수
    meta_right = ""
    if gen_at: meta_right += gen_at
    if n_msg:  meta_right += f" · {n_msg}개 메시지"

    st.markdown(
        f'<div class="rpt-toprow">'
        f'<span class="mood-badge {mood_cls}">{mood_ko.upper()}</span>'
        f'<span class="rpt-topmeta">{meta_right}</span>'
        f'</div>', unsafe_allow_html=True)

    # ── 헤드라인
    st.markdown(f'<div class="rpt-headline">{headline}</div>', unsafe_allow_html=True)

    # ── 오늘의 관전 (key_takeaway)
    kt = data.get("key_takeaway", "")
    if kt:
        st.markdown(
            f'<div class="rpt-kt-label">오늘의 관전</div>'
            f'<div class="rpt-kt-box">{kt}</div>',
            unsafe_allow_html=True)

    # ── 동적 섹션
    for sec in data.get("sections", []):
        title = sec.get("title", "")
        body  = sec.get("body", "")
        if not title and not body: continue
        st.markdown(f'<div class="rpt-sec-title">{title}</div>', unsafe_allow_html=True)
        if body:
            st.markdown(f'<div class="rpt-sec-body">{body}</div>', unsafe_allow_html=True)

    # ── 주목 테마
    themes = data.get("themes", [])
    if themes:
        st.markdown('<div class="rpt-group-label">주목 테마</div>', unsafe_allow_html=True)
        for th in themes:
            name    = th.get("name", "")
            detail  = th.get("detail", "")
            tickers = [t.strip() for t in (th.get("tickers") or "").split(",") if t.strip()]
            ticker_html = "".join(
                f'<a class="pill" href="{naver_stock_url(t)}" target="_blank">{t}</a>'
                for t in tickers) if tickers else ""
            st.markdown(
                f'<div class="theme-card">'
                f'<div class="theme-name">{name}</div>'
                f'<div class="theme-detail">{detail}</div>'
                + (f'<div class="theme-tickers">관련: {ticker_html}</div>' if ticker_html else "")
                + f'</div>', unsafe_allow_html=True)

    # ── 출처 채널
    sources = data.get("source_channels", [])
    if sources:
        pills = "".join(f'<span class="src-pill">{s}</span>' for s in sources)
        st.markdown(f'<div class="rpt-sources">출처 {pills}</div>', unsafe_allow_html=True)


def render_reports():
    files = list_reports()
    if not files:
        st.markdown(
            '<div class="empty"><div class="ico">📰</div>'
            '<div class="msg">아직 생성된 리포트가 없어요</div>'
            '<div class="hint">📝 리포트 생성 버튼으로 첫 리포트를 만들어보세요</div></div>',
            unsafe_allow_html=True)
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
                       format_func=lambda i: _label_with_headline(filtered[i]), key="rpt_pick")

    try:
        data = _load(filtered[idx])
    except Exception as e:
        st.error(f"리포트를 불러오지 못했어요: {e}")
        return

    _render_report(data)
