"""시황 리포트 뷰어 — 자체 CSS 주입 방식, 미니멀 미스트 디자인."""

import json
import re
from datetime import date
from pathlib import Path

import streamlit as st

from modules.stocks import naver_stock_url

REPORTS_DIR = Path("reports")

MOOD_KO  = {"positive": "긍정", "neutral": "중립", "cautious": "주의"}
MOOD_CLS = {"positive": "mood-pos", "neutral": "mood-neu", "cautious": "mood-cau"}

# ── 보고서 전용 CSS (자체 주입 — app.py 의존 없음) ───────────────
_RPT_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Hanken+Grotesk:wght@400;600;700&family=Noto+Sans+KR:wght@400;500;700&display=swap');
.rpt-wrap{font-family:'Hanken Grotesk','Noto Sans KR',sans-serif;}
.rpt-toprow{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-wrap:wrap;gap:6px;}
.mood-badge{font-size:10.5px;font-weight:700;letter-spacing:.07em;padding:4px 11px;border-radius:20px;display:inline-block;}
.mood-pos{background:#e1f5ee;color:#0f6e56;}
.mood-neu{background:#F1F2EC;color:#5d6258;}
.mood-cau{background:#FAEEDA;color:#854F0B;}
.rpt-topmeta{font-size:11.5px;color:var(--muted,#9a9b92);}
.rpt-accent{height:3px;width:32px;background:var(--sage,#A7BBA9);border-radius:3px;margin:0 0 12px;}
.rpt-headline{font-family:'Fraunces','Noto Sans KR',Georgia,serif;font-size:21px;font-weight:600;letter-spacing:-.02em;color:var(--ink,#34352f);line-height:1.45;margin:6px 0 18px;}
.rpt-kt-wrap{margin-bottom:26px;}
.rpt-kt-label{font-size:10.5px;font-weight:700;letter-spacing:.07em;color:var(--sage-deep,#7E9A83);margin-bottom:6px;text-transform:uppercase;}
.rpt-kt-box{font-size:14.5px;line-height:1.85;color:var(--ink,#34352f);background:var(--summary-bg,#F6F7F2);border-left:3px solid var(--sage,#A7BBA9);padding:14px 18px;border-radius:0 12px 12px 0;}
.rpt-sec{margin:20px 0 0;}
.rpt-sec-title{font-size:15.5px;font-weight:700;color:var(--ink,#34352f);border-bottom:2px solid var(--sage,#A7BBA9);padding-bottom:5px;margin-bottom:9px;}
.rpt-sec-body{font-size:14px;line-height:1.9;color:var(--ink,#34352f);margin:0;}
.rpt-group-label{font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted,#9a9b92);margin:28px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--line,#ECEDE7);}
.theme-card{background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);border-left:3px solid var(--sage,#A7BBA9);border-radius:0 13px 13px 0;padding:13px 16px 11px;margin-bottom:10px;}
.theme-name{font-size:14px;font-weight:700;color:var(--ink,#34352f);margin-bottom:5px;}
.theme-detail{font-size:13px;line-height:1.75;color:var(--ink,#34352f);margin-bottom:8px;}
.theme-tickers{font-size:11.5px;color:var(--muted,#9a9b92);}
.theme-tickers a{color:var(--sage-deep,#7E9A83);font-weight:600;text-decoration:none;background:var(--pill-bg,#F1F2EC);padding:2px 8px;border-radius:6px;border:1px solid var(--line,#ECEDE7);margin-right:4px;}
.rpt-sources{margin-top:24px;padding-top:12px;border-top:1px solid var(--line,#ECEDE7);font-size:11.5px;color:var(--muted,#9a9b92);display:flex;flex-wrap:wrap;gap:5px;align-items:center;}
.src-pill{background:var(--pill-bg,#F1F2EC);color:var(--pill-ink,#5d6258);border:1px solid var(--line,#ECEDE7);font-size:11px;font-weight:600;padding:3px 9px;border-radius:7px;}
</style>
"""


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
        "messages_count": 0, "source_channels": [],
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
    """종목명 추출 — JSON·구형 MD 양쪽 지원. (trends.py 호환용)"""
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


def _filter(files, keyword, date_range):
    kw = (keyword or "").strip().lower()
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
        if kw and kw not in f.read_text(encoding="utf-8").lower():
            continue
        out.append(f)
    return out


# ── 렌더링 ──────────────────────────────────────────────────

def _render_report(data: dict):
    mood     = data.get("mood", "neutral")
    mood_ko  = MOOD_KO.get(mood, mood)
    mood_cls = MOOD_CLS.get(mood, "mood-neu")
    gen_at   = data.get("generated_at", "")
    n_msg    = data.get("messages_count", 0)
    headline = data.get("headline", "시황 분석 보고서")

    # 상단: 감성 배지 + 날짜·메시지수
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

    # 오늘의 관전
    kt = data.get("key_takeaway", "")
    if kt:
        st.markdown(
            f'<div class="rpt-kt-wrap">'
            f'<div class="rpt-kt-label">오늘의 관전</div>'
            f'<div class="rpt-kt-box">{kt}</div>'
            f'</div>', unsafe_allow_html=True)

    # 동적 섹션
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

    # 주목 테마
    themes = data.get("themes", [])
    if themes:
        st.markdown('<div class="rpt-group-label">주목 테마</div>', unsafe_allow_html=True)
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

    # 출처
    sources = data.get("source_channels", [])
    if sources:
        pills = "".join(f'<span class="src-pill">{s}</span>' for s in sources)
        st.markdown(f'<div class="rpt-sources">출처 {pills}</div>', unsafe_allow_html=True)


def render_reports():
    # CSS 자체 주입 (app.py 의존 없음)
    st.markdown(_RPT_CSS, unsafe_allow_html=True)

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
    idx = st.selectbox(
        "리포트 선택",
        options=range(len(filtered)),
        format_func=lambda i: _label_with_headline(filtered[i]),
        key="rpt_pick")

    try:
        data = _load(filtered[idx])
    except Exception as e:
        st.error(f"리포트를 불러오지 못했어요: {e}")
        return

    _render_report(data)
