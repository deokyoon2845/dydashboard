"""[뷰어] 시황 타임라인 — 보고서 헤드라인·섹션 제목·mood를 시간 흐름으로 표시.

- 데이터: reports/*.json (headline, sections[], mood, report_kind)
- 같은 날 보고서가 여러 개면 ★장마감 후(post)를 우선★ 사용 (그날의 '답안지' 역할).
  post가 없으면 장전(pre) 등 최신 보고서로 폴백.
- ★표시 범위: 항상 최근 5개 날짜(장후 우선). 5개 미만이면 있는 것만.
- 코스피·코스닥 당일 종가 + 등락률 병기
- 리포트 파일이 추가/삭제되면 캐시가 자동 무효화됨 (폴더 시그니처 기반)
- 데스크톱: 가로 화살표 타임라인(지그재그 카드) / 모바일: 세로 타임라인
- 제목은 전략·시황 탭과 동일한 큰 글자 볼드(.rpt2-title) + 표시 중 기준일자 병기.

2026-06 보강: 카드 지수 줄(코스피·코스닥)이 외부 데이터(yfinance/pykrx) 공백으로
  비는 문제를 막기 위해, 그날 보고서가 들고 있는 종가(snapshot_line)를 폴백으로 쓴다.
  → _index_daily_map()에 그 날짜가 없으면 보고서 숫자(idx_self)로 채운다.
모바일은 최신 날짜가 위로 오도록 역순(reversed)으로 렌더 (데스크톱 지그재그는 오름차순 유지).
"""

import html
import re

import streamlit as st

from modules import db
from modules.indices import fetch_history

_REPORT_DIR = "reports"
_TIMELINE_DAYS = 5          # ★항상 최근 5개 날짜 (장후 우선)
_MOOD_MAP = {"positive": ("긍정", "pos", "#2E7D5B"),
             "neutral": ("중립", "neu", "#A7BBA9"),
             "cautious": ("주의", "cau", "#C2410C")}
_SEC_TITLE_KEYS = ("title", "name", "heading", "제목")
_MAX_SECTIONS = 5
_TRUNC = 60

_TL_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Hanken+Grotesk:wght@400;500;600;700&family=Noto+Sans+KR:wght@400;500;700&display=swap');
/* 전략·시황 탭과 동일한 제목 스타일 */
.tl-bar { height:3px; width:34px; background:var(--sage,#A7BBA9); border-radius:3px; margin:0 0 10px; }
.tl-title { font-family:'Fraunces','Noto Sans KR',serif; font-size:30px; font-weight:600;
  line-height:1.3; color:var(--ink,#34352f); margin:2px 0 4px; display:flex; align-items:baseline;
  gap:12px; flex-wrap:wrap; }
.tl-title .dates { font-family:'Hanken Grotesk','Noto Sans KR',sans-serif; font-size:13px;
  font-weight:600; color:var(--muted,#9a9b92); letter-spacing:.01em; }
.tl-sub { font-size:12px; color:var(--muted,#9a9b92); margin:0 0 16px; }

.tl-row { display:grid; gap:8px; align-items:end; }
.tl-row.tl-bottom { align-items:start; }
.tl-card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:9px 10px;
  color:inherit; transition:transform .16s ease, box-shadow .16s ease, border-color .16s ease; }
.tl-card.tl-latest { border-color:#C2410C; border-width:1.5px; }
/* ★ 데스크톱 지그재그 카드 폭 확대 — 양옆 빈 셀로 확장, 헤드라인·요약이 1줄에 들어오도록.
   같은 row에서 카드는 한 칸 건너 배치(빈 div 교차)되므로 폭 175%까지 키워도 인접 카드와
   겹치지 않는다(인접 카드 중심거리 2컬럼). 양끝 카드만 컨테이너 밖으로 새지 않게 정렬 보정.
   (모바일 .tl-mobile 카드는 .tl-row 밖이라 영향 없음) */
.tl-row .tl-card { box-sizing:border-box; width:175%; justify-self:center; }
.tl-row .tl-card.tl-edge-l { justify-self:start; }   /* 첫(가장 과거) 카드: 왼쪽 정렬 */
.tl-row .tl-card.tl-edge-r { justify-self:end; }     /* 마지막(최신) 카드: 오른쪽 정렬 */
/* 마우스 올리면 살짝 떠오르는 입체 효과 (클릭 동작 없음) */
.tl-card:hover { transform:translateY(-3px); box-shadow:0 6px 18px rgba(0,0,0,.10); border-color:var(--sage-deep,#7E9A83); }
.tl-card, .tl-card * { text-decoration:none; }
.tl-dt { font-size:10.5px; font-weight:700; color:var(--muted); margin-bottom:3px; }
.tl-idx { font-size:10px; color:var(--muted); margin-bottom:4px; line-height:1.5; }
.tl-idx b { font-weight:700; color:var(--ink); }
.tl-pct { font-weight:700; }
.tl-pct.up { color:var(--up); } .tl-pct.down { color:var(--down); }
.tl-hl { font-size:11.5px; font-weight:700; line-height:1.45; color:var(--ink); word-break:keep-all; }
.tl-secs { list-style:none; margin:6px 0 0; padding:6px 0 0; border-top:1px solid var(--line); }
.tl-secs li { font-size:10.5px; line-height:1.5; color:var(--muted); padding-left:9px; position:relative; margin-bottom:2px; word-break:keep-all; }
.tl-secs li::before { content:""; position:absolute; left:0; top:6px; width:4px; height:4px; border-radius:50%; background:var(--sage); }
.tl-md { display:inline-block; font-size:10px; font-weight:700; padding:1px 7px; border-radius:6px; margin-top:7px; }
.tl-md.pos { background:#e1f5ee; color:#0f6e56; }
.tl-md.neu { background:var(--pill-bg); color:var(--pill-ink); }
.tl-md.cau { background:#FAEEDA; color:#854F0B; }
.tl-kind { display:inline-block; font-size:9.5px; font-weight:700; padding:1px 6px; border-radius:6px; margin-top:7px; margin-left:5px; background:var(--pill-bg); color:var(--pill-ink); }
.tl-svg { width:100%; display:block; margin:4px 0; }
.tl-mobile { display:none; }
@media (max-width:640px){
  .tl-row, .tl-svg { display:none; }
  .tl-title { font-size:24px; }
  .tl-mobile { display:block; border-left:2px solid var(--line); padding-left:18px; }
  .tl-mobile .tl-card { position:relative; margin-bottom:12px; }
  .tl-mobile .tl-card::before { content:""; position:absolute; left:-25px; top:13px;
    width:11px; height:11px; border-radius:50%; border:2.5px solid var(--bg); background:var(--dot,#A7BBA9); }
}

/* ── 마이크로 인터랙션 (미니멀 미스트) ── */
/* 카드: 과거(왼쪽)→현재(오른쪽) 순서로 떠오름. --i 인덱스로 시차 */
@keyframes tl-fade-up{from{opacity:0;transform:translateY(12px);}to{opacity:1;transform:translateY(0);}}
.tl-card{animation:tl-fade-up .5s cubic-bezier(.22,.61,.36,1) both;
  animation-delay:calc(.45s + var(--i,0) * .12s);}
/* 호버 시엔 등장 transform과 충돌하지 않도록, 등장이 끝난 뒤 hover가 자연히 우선됨 */

/* SVG 트랙 라인: 왼쪽부터 그려짐 (dasharray 트릭) */
.tl-track{stroke-dasharray:var(--len,940);stroke-dashoffset:var(--len,940);
  animation:tl-draw .9s ease forwards;}
@keyframes tl-draw{to{stroke-dashoffset:0;}}
/* 화살촉: 라인이 다 그려진 뒤 등장 */
.tl-arrow{opacity:0;animation:tl-arrow-in .3s ease .85s forwards;}
@keyframes tl-arrow-in{to{opacity:1;}}
/* 노드: 라인 그려지는 동안 순차 등장 (--i 인덱스) */
.tl-node{opacity:0;transform-box:fill-box;transform-origin:center;
  animation:tl-node-in .4s cubic-bezier(.34,1.56,.64,1) forwards;
  animation-delay:calc(.4s + var(--i,0) * .14s);}
@keyframes tl-node-in{from{opacity:0;transform:scale(.2);}to{opacity:1;transform:scale(1);}}
/* 최신 노드: 등장 후 은은한 맥동 링 */
.tl-pulse{transform-box:fill-box;transform-origin:center;
  animation:tl-pulse 2.4s ease-in-out 1.4s infinite;}
@keyframes tl-pulse{
  0%{opacity:.5;transform:scale(1);}
  50%{opacity:0;transform:scale(2.1);}
  100%{opacity:0;transform:scale(2.1);}}

@media(prefers-reduced-motion:reduce){
  .tl-card,.tl-track,.tl-arrow,.tl-node,.tl-pulse{animation:none !important;}
  .tl-card,.tl-node,.tl-arrow{opacity:1 !important;}
  .tl-track{stroke-dashoffset:0 !important;}
  .tl-pulse{display:none !important;}
}
</style>
"""


def _reports_signature() -> str:
    """DB 보고서 목록(slug)의 시그니처.
    보고서가 추가·삭제되면 값이 바뀌어 st.cache_data 캐시가 자동 무효화된다.
    (저장소가 reports/ 폴더 → Supabase DB로 이전돼, 폴더 시그니처 대신 slug 묶음 사용.)
    DB 접근 실패 시 빈 문자열 — 무회귀."""
    try:
        return "|".join(db.list_slugs())
    except Exception:
        return ""


def _infer_kind(fname: str, rep: dict) -> str:
    """보고서 종류. report_kind 필드 우선, 없으면 파일명 HHMM으로 추정(오전=장전, 오후=장후)."""
    k = (rep or {}).get("report_kind")
    if k in ("pre", "post"):
        return k
    m = re.search(r"_(\d{2})(\d{2})", fname)
    if m:
        return "pre" if int(m.group(1)) < 12 else "post"
    return "post"


def _section_titles(report: dict) -> list:
    """카드에 표시할 소제목 목록 추출.

    신형 보고서(topics 스키마)는 중요도 순 topics[].title을, 구형은 sections[].title을 쓴다.
    타임라인 카드에 헤드라인 밑 요약 불릿으로 표시된다.
    """
    # 신형: topics (이미 중요도 내림차순으로 저장됨)
    topics = report.get("topics")
    if isinstance(topics, list) and topics:
        out = []
        for tp in topics[:_MAX_SECTIONS]:
            if not isinstance(tp, dict):
                continue
            title = str(tp.get("title", "")).strip()
            if title:
                if len(title) > _TRUNC:
                    title = title[:_TRUNC] + "…"
                out.append(title)
        if out:
            return out

    # 구형: sections
    out = []
    for sec in report.get("sections", [])[:_MAX_SECTIONS]:
        title = None
        if isinstance(sec, dict):
            for k in _SEC_TITLE_KEYS:
                if sec.get(k):
                    title = str(sec[k])
                    break
        elif isinstance(sec, str):
            title = sec
        if title:
            t = title.strip()
            if len(t) > _TRUNC:
                t = t[:_TRUNC] + "…"
            out.append(t)
    return out


# ── 보고서 자체에서 코스피·코스닥 종가 추출 (외부 데이터 공백 폴백) ──
# 보고서의 snapshot_line 예: "코스피 8,545.98(+5.20%) · 코스닥 1,034.03(+0.48%) · ..."
# yfinance/pykrx가 그 날짜를 못 줄 때, 그날 보고서가 들고 있는 숫자를 카드에 쓴다.
_IDX_RE = {
    "ks": re.compile(r"코스피\s*([\d,]+\.?\d*)\s*\(\s*([+-]?\d+\.?\d*)\s*%\)"),
    "kq": re.compile(r"코스닥\s*([\d,]+\.?\d*)\s*\(\s*([+-]?\d+\.?\d*)\s*%\)"),
}


def _index_from_report(rep: dict) -> dict:
    """보고서 snapshot_line에서 코스피·코스닥 종가·등락률을 추출.
    반환: {'ks_close','ks_pct','kq_close','kq_pct'} 중 찾은 것만 · 없으면 {}."""
    text = str(rep.get("snapshot_line", "") or "")
    rec = {}
    for prefix, pat in _IDX_RE.items():
        m = pat.search(text)
        if not m:
            continue
        try:
            rec[f"{prefix}_close"] = float(m.group(1).replace(",", ""))
            rec[f"{prefix}_pct"] = float(m.group(2))
        except (ValueError, TypeError):
            continue
    return rec


@st.cache_data(ttl=600)
def load_timeline_entries(limit: int, sig: str) -> list:
    """DB(reports 테이블)에서 타임라인 항목 로드. 같은 날짜는 장마감 후(post) 우선,
    날짜 오름차순. 최근 limit개 날짜만 반환(limit보다 적으면 있는 만큼).
    sig: _reports_signature() — 캐시 키 전용(함수 안에서는 사용 안 함).

    ★저장소 이전(2026-06): 예전엔 reports/*.json을 glob했으나, 보고서는 이제 DB에만
      안정적으로 쌓인다(엔진은 GitHub Actions 임시 디스크에 쓰고 레포엔 커밋하지 않음).
      뷰어가 로컬 파일을 보면 'DB엔 있는데 타임라인엔 없는' 날짜가 생긴다(예: 최신 거래일)
      → 시황·PDF 뷰어와 동일하게 DB로 통일.
    """
    try:
        # 하루 최대 2건(장전·장후)이므로 limit*2 + 여유로 충분히 limit개 날짜를 덮는다.
        rows = db.list_recent(limit * 2 + 6)
    except Exception:
        rows = []

    # 날짜 -> 우선 행 1건. rows는 report_date desc, slug desc(=HHMM 늦은 순=post 먼저)로
    # 정렬돼 오므로, 각 날짜에서 '처음 만난 행'이 곧 장마감 후 우선 행이다.
    by_date = {}
    for r in rows:
        d = str(r.get("report_date", "")).strip()
        if not re.match(r"\d{4}-\d{2}-\d{2}", d):
            m = re.match(r"(\d{4}-\d{2}-\d{2})", str(r.get("slug", "")))
            if not m:
                continue
            d = m.group(1)
        if d not in by_date:
            by_date[d] = r

    entries = []
    for d in sorted(by_date.keys())[-limit:]:
        r = by_date[d]
        rep = r.get("data") or {}
        slug = str(r.get("slug", "")) or d
        mood_raw = str(rep.get("mood", "")).lower()
        label, cls, color = _MOOD_MAP.get(mood_raw, _MOOD_MAP["neutral"])
        rk = rep.get("report_kind") or r.get("report_kind")
        kind = rk if rk in ("pre", "post") else _infer_kind(slug, rep)
        entries.append({
            "date": d,
            "report": slug,
            "kind": kind,
            "kind_label": "장마감 후" if kind == "post" else "장전",
            "headline": str(rep.get("headline", "")).strip() or "(헤드라인 없음)",
            "sections": _section_titles(rep),
            "mood_label": label, "mood_cls": cls, "mood_color": color,
            # 외부 데이터가 그 날짜를 못 줄 때 쓸 폴백(보고서 자체 종가)
            "idx_self": _index_from_report(rep),
        })
    return entries


@st.cache_data(ttl=1800)
def _index_daily_map() -> dict:
    """날짜(YYYY-MM-DD) → {'ks_close','ks_pct','kq_close','kq_pct'}.
    코스피·코스닥 일별 종가와 등락률. 1차 yfinance, 빠진 날짜는 pykrx로 보충.
    (indices.fetch_history가 한국 지수는 네이버로 최근일을 보강하므로 여기서도 최신이 들어옴)"""
    out = {}
    for prefix, ticker in (("ks", "^KS11"), ("kq", "^KQ11")):
        try:
            close = fetch_history(ticker, "3mo")
            if close is None or len(close) < 2:
                continue
            pct = close.pct_change() * 100
            for ts, c in close.items():
                key = ts.strftime("%Y-%m-%d")
                rec = out.setdefault(key, {})
                rec[f"{prefix}_close"] = float(c)
                p = pct.get(ts)
                if p == p:  # NaN 방어
                    rec[f"{prefix}_pct"] = float(p)
        except Exception:
            continue
    try:
        from datetime import date, timedelta
        from pykrx import stock as _krx
        end = date.today().strftime("%Y%m%d")
        start = (date.today() - timedelta(days=100)).strftime("%Y%m%d")
        for prefix, code in (("ks", "1001"), ("kq", "2001")):
            try:
                df = _krx.get_index_ohlcv(start, end, code)
                closes = df["종가"].dropna()
                pcts = closes.pct_change() * 100
                for ts, c in closes.items():
                    key = ts.strftime("%Y-%m-%d")
                    rec = out.setdefault(key, {})
                    if f"{prefix}_close" not in rec:
                        rec[f"{prefix}_close"] = float(c)
                        p = pcts.get(ts)
                        if p == p:
                            rec[f"{prefix}_pct"] = float(p)
            except Exception:
                continue
    except Exception:
        pass
    return out


_WD = "월화수목금토일"


def _fmt_date(date: str) -> str:
    """'2026-06-11' → '06/11 (목)'."""
    try:
        from datetime import datetime
        d = datetime.strptime(date, "%Y-%m-%d")
        return f"{d.strftime('%m/%d')} ({_WD[d.weekday()]})"
    except Exception:
        return date


def _fmt_date_short(date: str) -> str:
    """'2026-06-11' → '06.11' (제목 옆 기준일자 병기용)."""
    try:
        from datetime import datetime
        d = datetime.strptime(date, "%Y-%m-%d")
        return d.strftime("%m.%d")
    except Exception:
        return date


def _idx_line_html(rec: dict) -> str:
    """카드 날짜 아래 '코스피 2,750.1 ▲+1.2% · 코스닥 870.5 ▼-0.3%' 한 줄."""
    if not rec:
        return ""
    items = []
    for prefix, label in (("ks", "코스피"), ("kq", "코스닥")):
        close = rec.get(f"{prefix}_close")
        if close is None:
            continue
        pct = rec.get(f"{prefix}_pct")
        pct_html = ""
        if pct is not None:
            cls = "up" if pct >= 0 else "down"
            arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "▬")
            pct_html = f' <span class="tl-pct {cls}">{arrow}{pct:+.2f}%</span>'
        items.append(f'{label} <b>{close:,.2f}</b>{pct_html}')
    if not items:
        return ""
    return f'<div class="tl-idx">{" · ".join(items)}</div>'


def _card_html(e: dict, idx_rec, latest: bool, mobile: bool = False, order: int = 0,
               edge: str = "") -> str:
    secs = "".join(f"<li>{html.escape(s)}</li>" for s in e["sections"])
    secs_html = f'<ul class="tl-secs">{secs}</ul>' if secs else ""
    latest_cls = " tl-latest" if latest else ""
    # 데스크톱 지그재그에서 첫·마지막 카드는 폭 확장 시 컨테이너 밖으로 새지 않게 정렬 보정
    edge_cls = f" tl-edge-{edge}" if (edge and not mobile) else ""
    latest_tag = " · 최신" if latest else ""
    dot = f' style="--dot:{e["mood_color"]}"' if mobile else f' style="--i:{order}"'
    kind_tag = f'<span class="tl-kind">{e.get("kind_label", "")}</span>' if e.get("kind_label") else ""
    inner = (f'<div class="tl-dt">{_fmt_date(e["date"])}{latest_tag}</div>'
             f'{_idx_line_html(idx_rec)}'
             f'<div class="tl-hl">{html.escape(e["headline"])}</div>'
             f'{secs_html}'
             f'<span class="tl-md {e["mood_cls"]}">{e["mood_label"]}</span>{kind_tag}')
    return f'<div class="tl-card{latest_cls}{edge_cls}"{dot}>{inner}</div>'


def _svg_html(entries: list) -> str:
    """트랙 + mood 노드. 노드는 균등 간격. 라인은 왼쪽부터 그려지고 노드는 순차 등장."""
    n = len(entries)
    w = 960
    track_len = w - 20  # 라인 길이(대략) → dasharray 기준
    parts = [f'<svg class="tl-svg" viewBox="0 0 {w} 64" preserveAspectRatio="none">',
             f'<line class="tl-track" style="--len:{track_len}" '
             f'x1="10" y1="40" x2="{w-20}" y2="40" stroke="#D3D1C7" stroke-width="2"/>',
             f'<path class="tl-arrow" d="M{w-20},40 l-12,-7 v14 z" fill="#D3D1C7"/>']
    xs = [(i + 0.5) / n * w for i in range(n)]
    for i, (x, e) in enumerate(zip(xs, entries)):
        is_last = i == n - 1
        r = 11 if is_last else 8
        # 최신 노드: 맥동 링을 노드 뒤에 먼저 그림(같은 색, 점점 커지며 사라짐)
        if is_last:
            parts.append(f'<circle class="tl-pulse" cx="{x:.0f}" cy="40" r="{r}" '
                         f'fill="{e["mood_color"]}"/>')
        parts.append(f'<circle class="tl-node" style="--i:{i}" cx="{x:.0f}" cy="40" r="{r}" '
                     f'fill="{e["mood_color"]}" stroke="var(--bg)" stroke-width="3"/>')
    parts.append("</svg>")
    return "".join(parts)


def render_timeline():
    st.markdown(_TL_CSS, unsafe_allow_html=True)

    # 항상 최근 5개 날짜(장후 우선). 5개 미만이면 있는 것만.
    entries = load_timeline_entries(_TIMELINE_DAYS, _reports_signature())

    # 제목: 전략·시황 탭과 동일한 큰 글자 볼드 + 표시 중 기준일자 병기
    if entries:
        # entries는 날짜 오름차순 → 제목 병기는 최신이 앞으로 오도록 역순 표기
        dates_str = " · ".join(_fmt_date_short(e["date"]) for e in reversed(entries))
        dates_html = f'<span class="dates">{dates_str}</span>'
    else:
        dates_html = ""
    st.markdown('<div class="tl-bar"></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="tl-title">타임라인 {dates_html}</div>',
                unsafe_allow_html=True)
    st.markdown('<div class="tl-sub">최근 5개 거래일의 보고서 흐름 (같은 날은 장마감 후 우선)</div>',
                unsafe_allow_html=True)

    if not entries:
        st.markdown('<div class="empty"><div class="ico">🗓️</div>'
                    '<div class="msg">아직 표시할 보고서가 없어요</div>'
                    '<div class="hint">시황 보고서가 쌓이면 흐름이 그려집니다</div></div>',
                    unsafe_allow_html=True)
        return
    if len(entries) == 1:
        st.caption("보고서가 1개뿐이라 흐름 표시는 2개부터 가능해요. 우선 최신 보고서만 표시합니다.")

    idx_map = _index_daily_map()
    n = len(entries)
    last_i = n - 1

    top_cells, bottom_cells = [], []
    for i, e in enumerate(entries):
        # 외부 지수 데이터(map)가 그 날짜를 못 주면 보고서 자체 종가(idx_self)로 폴백
        idx_rec = idx_map.get(e["date"]) or e.get("idx_self")
        # 첫(가장 과거)·마지막(최신) 카드는 폭 확장 시 화면 밖으로 새지 않게 정렬 보정
        edge = "l" if i == 0 else ("r" if i == last_i else "")
        card = _card_html(e, idx_rec, i == last_i, order=i, edge=edge)
        if i % 2 == 1:
            top_cells.append(card)
            bottom_cells.append("<div></div>")
        else:
            top_cells.append("<div></div>")
            bottom_cells.append(card)
    grid = f"grid-template-columns:repeat({n},1fr);"
    desktop = (f'<div class="tl-row" style="{grid}">{"".join(top_cells)}</div>'
               f'{_svg_html(entries)}'
               f'<div class="tl-row tl-bottom" style="{grid}">{"".join(bottom_cells)}</div>')

    # ★모바일은 최신 날짜가 위로 오도록 역순(reversed)으로 렌더.
    #   데스크톱 지그재그(desktop)는 그대로 오름차순(과거→현재) 유지.
    #   '최신' 배지·테두리는 날짜로 판별하므로 역순이어도 정확히 따라간다.
    latest_date = entries[last_i]["date"]
    mobile_cards = "".join(
        _card_html(e, idx_map.get(e["date"]) or e.get("idx_self"),
                   e["date"] == latest_date, mobile=True, order=i)
        for i, e in enumerate(reversed(entries)))
    mobile = f'<div class="tl-mobile">{mobile_cards}</div>'

    st.markdown(desktop + mobile, unsafe_allow_html=True)
    st.markdown('<div class="data-asof">노드 색 = 보고서 mood (긍정·중립·주의) · '
                '날짜 아래 = 코스피·코스닥 당일 마감 종가와 등락률 · 같은 날은 장마감 후 보고서 우선 표시</div>',
                unsafe_allow_html=True)
