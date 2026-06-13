"""전략·시황 보고서 뷰어 — 하루 단위(장전·장마감 후) 레이아웃, 미니멀 미스트.

레이아웃 (render_reports):
  최상단 기준일(YYYY.MM.DD(요일))
  ⓪ 오늘의 한 줄 TL;DR (장전→장후 mood 흐름 + 최신 헤드라인)
  ① 오늘의 시장 동력 매트릭스 (단기/장기 × 상승/하락 · 최신 보고서 기준)
  ② 좌 장전 / 우 장마감 후 (없으면 '생성 전' 자리지킴)
     └ 각 카드 안: 헤드라인 · 관전/결산 · 교차 검증(cross_check) · 본문 섹션
       · 취합된 텔레그램 원문(source_messages) 조회   ← 신규
  ③ 주목 테마 (전체 폭)
render_reports_manage = 지난 보고서(날짜) 탐색 + 삭제 (하단 배치용)

영구 저장: 각 보고서의 '💾 JSON 저장' 버튼으로 받은 파일을 깃허브 reports/ 에 올리면
리부트에도 보존되고 추세 탭 타임라인에도 자동 반영됨.
"""

import html
import json
import re
from datetime import date
from pathlib import Path

import streamlit as st

from modules.stocks import naver_stock_url
from modules.mood import MOOD_KO, mood_css

REPORTS_DIR = Path("reports")
MOOD_CLS = {"positive": "mood-pos", "neutral": "mood-neu", "cautious": "mood-cau"}
_WD = "월화수목금토일"

_RPT_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Hanken+Grotesk:wght@400;500;600;700&family=Noto+Sans+KR:wght@400;500;700&display=swap');
.rpt-wrap{font-family:'Hanken Grotesk','Noto Sans KR',sans-serif;}
.mood-badge{font-size:10.5px;font-weight:700;letter-spacing:.06em;padding:3px 11px;border-radius:20px;display:inline-block;}
__MOOD_BADGE_CSS__
.rpt2-bar{height:3px;width:34px;background:var(--sage,#A7BBA9);border-radius:3px;margin:0 0 10px;}
.rpt2-date{font-family:'Fraunces','Noto Sans KR',serif;font-size:15px;font-weight:600;color:var(--sage-deep,#7E9A83);letter-spacing:.02em;}
.rpt2-title{font-family:'Fraunces','Noto Sans KR',serif;font-size:30px;font-weight:600;line-height:1.3;color:var(--ink,#34352f);margin:2px 0 16px;}
.rpt2-grp{font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted,#9a9b92);margin:22px 0 12px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
.rpt2-grp .sub{font-weight:600;text-transform:none;letter-spacing:0;color:var(--muted,#9a9b92);font-size:11px;}
.rpt2-grp .tag{font-size:10.5px;font-weight:700;letter-spacing:.02em;text-transform:none;padding:2px 9px;border-radius:20px;}
.tag-pred{background:var(--tint-up,#FBF2F2);color:var(--up,#B65F5A);}
.tag-upd{background:#e1f5ee;color:#0f6e56;}

/* ⓪ 오늘의 한 줄 TL;DR (상단) */
.rpt-tldr{background:#fff;border:1px solid var(--line,#ECEDE7);border-left:4px solid var(--sage,#A7BBA9);border-radius:0 16px 16px 0;padding:15px 19px;margin:4px 0 6px;}
.rpt-tldr .top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px;}
.rpt-tldr .lab{font-size:10.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted,#9a9b92);}
.tldr-step{display:inline-flex;align-items:center;gap:5px;}
.tldr-steplab{font-size:11px;font-weight:700;color:var(--muted,#9a9b92);}
.tldr-arrow{color:var(--muted,#9a9b92);font-size:11px;font-weight:700;}
.rpt-tldr .hl{font-family:'Fraunces','Noto Sans KR',serif;font-size:19px;font-weight:600;line-height:1.42;color:var(--ink,#34352f);}
.rpt-tldr .kt{font-size:12.5px;color:var(--muted,#9a9b92);line-height:1.62;margin-top:7px;}

/* 시장 동력 매트릭스 (재디자인) — 시계열 열 좁게, 상승/하락 열 넓게 */
.dvm{display:grid;grid-template-columns:0.58fr 1.21fr 1.21fr;background:#fff;
  border:1px solid var(--line,#ECEDE7);border-radius:16px;overflow:hidden;}
/* 헤더 행 */
.dvm-h{font-size:12.5px;font-weight:700;padding:11px 16px;display:flex;align-items:center;gap:6px;
  border-bottom:1px solid var(--line,#ECEDE7);}
.dvm-h em{font-style:normal;font-size:10px;font-weight:600;color:var(--muted,#9a9b92);margin-left:2px;}
.dvm-h0{background:var(--summary-bg,#F6F7F2);color:var(--muted,#9a9b92);font-size:11px;
  letter-spacing:.04em;text-transform:uppercase;}
.dvm-hup{background:var(--tint-up,#FBF2F2);color:var(--up,#B65F5A);}
.dvm-hdown{background:var(--tint-down,#F1F5F9);color:var(--down,#5A7CA0);}
/* 시계열 라벨 칸 (좁게) */
.dvm-tf{padding:14px 16px;border-bottom:1px solid var(--line,#ECEDE7);background:var(--summary-bg,#F6F7F2);
  display:flex;flex-direction:column;justify-content:center;}
.tf-name{font-size:15px;font-weight:700;color:var(--ink,#34352f);}
.tf-name em{display:block;font-style:normal;font-size:10px;color:var(--muted,#9a9b92);
  font-weight:600;margin:2px 0 0;letter-spacing:.02em;}
.tf-sub{font-size:10.5px;color:var(--muted,#9a9b92);margin-top:6px;line-height:1.4;}
/* 내용 칸 — 항목들을 세로로 쌓되 넉넉한 폭 */
.dvm-cell{padding:11px 14px;border-bottom:1px solid var(--line,#ECEDE7);
  border-left:1px solid var(--line,#ECEDE7);display:flex;flex-direction:column;gap:8px;}
/* 개별 항목: 좌측 컬러바 + 라벨(칩) + 설명, 한 카드로 */
.dvi{position:relative;padding:8px 11px 8px 13px;border-radius:9px;background:var(--summary-bg,#F6F7F2);
  border:1px solid var(--line,#ECEDE7);}
.dvi::before{content:"";position:absolute;left:0;top:8px;bottom:8px;width:3px;border-radius:3px;}
.dvi.up::before{background:var(--up,#B65F5A);}
.dvi.down::before{background:var(--down,#5A7CA0);}
.dvi-lab{display:inline-block;font-size:11px;font-weight:700;padding:1px 8px;border-radius:6px;
  margin-bottom:4px;}
.dvi.up .dvi-lab{background:var(--tint-up,#FBF2F2);color:var(--up,#B65F5A);}
.dvi.down .dvi-lab{background:var(--tint-down,#F1F5F9);color:var(--down,#5A7CA0);}
.dvi-desc{font-size:12.5px;line-height:1.55;color:var(--ink,#34352f);}
.dvi-empty{font-size:12px;color:var(--muted,#9a9b92);padding:4px 2px;}
.dvm-celldir{display:none;}
.dvm > *:nth-last-child(-n+3){border-bottom:none;}
@media(max-width:640px){
  .dvm{grid-template-columns:1fr;}
  .dvm-h{display:none;}
  .dvm-tf{background:#fff;padding-bottom:4px;border-bottom:none;}
  .tf-name{font-size:14px;}
  .dvm-cell{border-left:none;padding-top:4px;}
  .dvm > *:nth-last-child(-n+3){border-bottom:1px solid var(--line,#ECEDE7);}
  .dvm > *:last-child{border-bottom:none;}
  .dvm-celldir{display:flex;align-items:center;gap:5px;font-size:11px;font-weight:700;margin-bottom:4px;}
  .dvm-celldir.up{color:var(--up,#B65F5A);} .dvm-celldir.down{color:var(--down,#5A7CA0);}
}

/* 장전/장후 카드 */
.rc{background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);border-radius:16px;padding:18px 18px 14px;}
.rc-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:6px;}
.rc-kind{font-size:13.5px;font-weight:700;color:var(--ink,#34352f);}
.rc-win{font-size:11px;color:var(--muted,#9a9b92);margin-bottom:12px;}
.rc-win b{color:var(--sage-deep,#7E9A83);}
.rc-headline{font-family:'Fraunces','Noto Sans KR',serif;font-size:18px;font-weight:600;line-height:1.45;letter-spacing:-.01em;color:var(--ink,#34352f);margin-bottom:12px;}
.rc-ktlab{font-size:10.5px;font-weight:700;letter-spacing:.06em;color:var(--sage-deep,#7E9A83);margin-bottom:5px;text-transform:uppercase;}
.rc-ktbox{font-size:13.5px;line-height:1.75;color:var(--ink,#34352f);background:var(--summary-bg,#F6F7F2);border-left:3px solid var(--sage,#A7BBA9);padding:12px 15px;border-radius:0 11px 11px 0;margin-bottom:16px;}
.rc-sectitle{font-size:13.5px;font-weight:700;color:var(--ink,#34352f);border-bottom:1.5px solid var(--sage,#A7BBA9);padding-bottom:4px;margin:14px 0 6px;}
.rc-secbody{font-size:13px;line-height:1.75;color:var(--ink,#34352f);margin-bottom:6px;}
.rc-src{margin-top:14px;padding-top:10px;border-top:1px solid var(--line,#ECEDE7);display:flex;flex-wrap:wrap;gap:6px;align-items:center;}
.src-pill{background:var(--pill-bg,#F1F2EC);color:var(--pill-ink,#5d6258);border:1px solid var(--line,#ECEDE7);font-size:11px;font-weight:600;padding:3px 9px;border-radius:7px;}
.rc-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;min-height:280px;color:var(--muted,#9a9b92);border:1.5px dashed var(--line,#ECEDE7);border-radius:14px;background:#fdfdfb;}
.rc-empty .ico{font-size:34px;opacity:.55;}
.rc-empty .msg{font-size:14px;font-weight:700;color:var(--ink,#34352f);margin-top:12px;}
.rc-empty .hint{font-size:12px;margin-top:6px;}
.rc-empty .eta{font-size:11.5px;margin-top:10px;background:var(--pill-bg,#F1F2EC);color:var(--pill-ink,#5d6258);border:1px solid var(--line,#ECEDE7);padding:3px 11px;border-radius:20px;}

/* 교차 검증 (장전/장후 카드 내부) */
.rcc{margin:14px 0 12px;padding-top:14px;border-top:1px solid var(--line,#ECEDE7);}
.rcc-lab{font-size:10.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--sage-deep,#7E9A83);margin-bottom:7px;}
.rcc-grid{display:flex;gap:9px;flex-wrap:wrap;}
.rcc-col{flex:1;min-width:185px;border:1px solid var(--line,#ECEDE7);border-radius:11px;padding:10px 13px;background:#fff;}
.rcc-col.mv{border-top:3px solid var(--sage,#A7BBA9);}
.rcc-col.df{border-top:3px solid var(--down,#5A7CA0);}
.rcc-col .h{font-size:11px;font-weight:700;margin-bottom:4px;}
.rcc-col.mv .h{color:var(--sage-deep,#7E9A83);}
.rcc-col.df .h{color:var(--down,#5A7CA0);}
.rcc-col .t{font-size:12.5px;line-height:1.62;color:var(--ink,#34352f);}
.rcc-verdict{margin-top:9px;background:var(--summary-bg,#F6F7F2);border-radius:9px;padding:10px 13px;font-size:12.5px;line-height:1.62;color:var(--ink,#34352f);}
.rcc-vbadge{font-size:10.5px;font-weight:700;padding:2px 9px;border-radius:20px;background:var(--pill-bg,#F1F2EC);color:var(--pill-ink,#5d6258);margin-right:7px;border:1px solid var(--line,#ECEDE7);}

/* 취합된 텔레그램 원문 (검증용) — PDF/JSON 버튼 위 expander */
.srcmsg-cap{font-size:11.5px;color:var(--muted,#9a9b92);line-height:1.6;margin-bottom:10px;}
.srcmsg-wrap{display:flex;flex-direction:column;gap:9px;max-height:460px;overflow-y:auto;padding-right:4px;}
.srcmsg{border:1px solid var(--line,#ECEDE7);border-left:3px solid var(--sage,#A7BBA9);border-radius:0 10px 10px 0;padding:9px 13px;background:#fff;}
.srcmsg-head{display:flex;align-items:baseline;justify-content:space-between;gap:8px;margin-bottom:5px;}
.srcmsg-ch{font-size:11.5px;font-weight:700;color:var(--sage-deep,#7E9A83);word-break:break-all;}
.srcmsg-dt{font-size:10.5px;color:var(--muted,#9a9b92);white-space:nowrap;flex:none;}
.srcmsg-tx{font-size:12.5px;line-height:1.62;color:var(--ink,#34352f);white-space:pre-wrap;}

/* 주목 테마 (하단 전체 폭) */
.rpt-theme-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;}
@media(max-width:900px){.rpt-theme-grid{grid-template-columns:repeat(2,1fr);}}
@media(max-width:560px){.rpt-theme-grid{grid-template-columns:1fr;}}
.theme-card{background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);border-left:3px solid var(--sage,#A7BBA9);border-radius:0 13px 13px 0;padding:13px 16px 11px;}
.theme-name{font-size:14px;font-weight:700;color:var(--ink,#34352f);margin-bottom:5px;}
.theme-detail{font-size:13px;line-height:1.7;color:var(--ink,#34352f);margin-bottom:8px;}
.theme-tickers{font-size:11.5px;color:var(--muted,#9a9b92);}
.theme-tickers a{color:var(--sage-deep,#7E9A83);font-weight:600;text-decoration:none;background:var(--pill-bg,#F1F2EC);padding:2px 8px;border-radius:6px;border:1px solid var(--line,#ECEDE7);margin-right:4px;}
.rpt-side-empty{color:var(--muted,#9a9b92);font-size:13px;padding:8px 0;}
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


def _infer_kind_from_name(path: Path) -> str:
    """파일명 HHMM으로 장전/장후 추정 (구형 보고서 호환). 오전=장전, 오후=장후."""
    m = re.search(r"_(\d{2})(\d{2})", path.stem)
    if m:
        return "pre" if int(m.group(1)) < 12 else "post"
    return "post"


def _kind_of(path: Path, data: dict) -> str:
    k = (data or {}).get("report_kind")
    return k if k in ("pre", "post") else _infer_kind_from_name(path)


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


def _fmt_date_ko(d: date) -> str:
    return f"{d.strftime('%Y.%m.%d')}({_WD[d.weekday()]})"


def _selected_date(files) -> date:
    """표시할 날짜. ?rpt= 또는 날짜 선택으로 고정된 보고서가 있으면 그 날짜, 없으면 오늘.
    오늘 보고서가 없으면 가장 최근 보고서 날짜로."""
    pk = st.session_state.get("rpt_picked_path")
    if pk and Path(pk).exists():
        return _report_date(Path(pk))
    today = date.today()
    dates = {_report_date(f) for f in files}
    if today in dates:
        return today
    return max(dates) if dates else today


def _find_for_date(files, d: date):
    """해당 날짜의 (장전, 장후) = ((path, data) 또는 (None, None))."""
    pres, posts = [], []
    for f in files:
        if _report_date(f) != d:
            continue
        try:
            data = _load(f)
        except Exception:
            continue
        bucket = pres if _kind_of(f, data) == "pre" else posts
        bucket.append((f, data))
    pres.sort(key=lambda x: x[0].name, reverse=True)
    posts.sort(key=lambda x: x[0].name, reverse=True)
    pre = pres[0] if pres else (None, None)
    post = posts[0] if posts else (None, None)
    return pre, post


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


# ── 렌더링: 오늘의 한 줄 TL;DR ───────────────────────────────

def _render_tldr(pre_data, post_data, latest, latest_kind):
    """장전→장후 mood 흐름 + 최신 헤드라인 한 줄. 날짜 제목 바로 아래에 표시."""
    if not latest:
        return
    headline = html.escape(str(latest.get("headline", "")).strip())
    if not headline:
        return

    kt = html.escape(str(latest.get("key_takeaway", "")).strip())

    def _step(label, d):
        m = d.get("mood", "neutral")
        cls = MOOD_CLS.get(m, "mood-neu")
        ko = MOOD_KO.get(m, m)
        return (f'<span class="tldr-step"><span class="tldr-steplab">{label}</span>'
                f'<span class="mood-badge {cls}">{ko.upper()}</span></span>')

    steps = []
    if pre_data:
        steps.append(_step("장전", pre_data))
    if post_data:
        steps.append(_step("장후", post_data))
    pills = '<span class="tldr-arrow">→</span>'.join(steps)

    kt_html = f'<div class="kt">{kt}</div>' if kt else ""
    st.markdown(
        f'<div class="rpt-tldr">'
        f'<div class="top"><span class="lab">오늘의 한 줄</span>{pills}</div>'
        f'<div class="hl">{headline}</div>'
        f'{kt_html}'
        f'</div>', unsafe_allow_html=True)


# ── 렌더링: 시장 동력 매트릭스 ───────────────────────────────

def _matrix_has_content(md: dict) -> bool:
    if not md:
        return False
    for tf in ("short_term", "long_term"):
        for dr in ("up", "down"):
            if ((md.get(tf) or {}).get(dr)):
                return True
    return False


def _cell_html(items, direction, dir_label):
    head = f'<div class="dvm-celldir {direction}">{dir_label}</div>'
    items = items or []
    if not items:
        return head + '<div class="dvi-empty">해당 요인 없음</div>'
    rows = ""
    for it in items:
        if not isinstance(it, dict):
            continue
        lab = html.escape(str(it.get("label", "")).strip())
        desc = html.escape(str(it.get("desc", "")).strip())
        if not lab and not desc:
            continue
        lab_html = f'<span class="dvi-lab">{lab}</span>' if lab else ""
        desc_html = f'<div class="dvi-desc">{desc}</div>' if desc else ""
        rows += f'<div class="dvi {direction}">{lab_html}{desc_html}</div>'
    return head + (rows or '<div class="dvi-empty">해당 요인 없음</div>')


def _render_matrix(data: dict, kind: str):
    md = data.get("market_drivers") or {}
    if not _matrix_has_content(md):
        return
    st_ = md.get("short_term") or {}
    lt = md.get("long_term") or {}

    tag = ('<span class="tag tag-pred">장전 보고서 기준 · 개장 전 예측</span>' if kind == "pre"
           else '<span class="tag tag-upd">장마감 후 보고서 기준 · 결과 반영</span>')
    st.markdown(
        f'<div class="rpt2-grp">📊 오늘의 시장 동력 매트릭스 '
        f'<span class="sub">Market Driver Matrix</span> {tag}</div>',
        unsafe_allow_html=True)

    grid = (
        '<div class="dvm">'
        '<div class="dvm-h dvm-h0">🕒 시계열</div>'
        '<div class="dvm-h dvm-hup">📈 상승 · 모멘텀 <em>Upward</em></div>'
        '<div class="dvm-h dvm-hdown">📉 하락 · 리스크 <em>Downward</em></div>'
        '<div class="dvm-tf"><div class="tf-name">단기 <em>Short-term</em></div>'
        '<div class="tf-sub">수급 · 심리 · 노이즈</div></div>'
        f'<div class="dvm-cell">{_cell_html(st_.get("up"), "up", "📈 상승 · 모멘텀")}</div>'
        f'<div class="dvm-cell">{_cell_html(st_.get("down"), "down", "📉 하락 · 리스크")}</div>'
        '<div class="dvm-tf"><div class="tf-name">장기 <em>Long-term</em></div>'
        '<div class="tf-sub">거시 · 실적 · 정책</div></div>'
        f'<div class="dvm-cell">{_cell_html(lt.get("up"), "up", "📈 상승 · 모멘텀")}</div>'
        f'<div class="dvm-cell">{_cell_html(lt.get("down"), "down", "📉 하락 · 리스크")}</div>'
        '</div>'
    )
    st.markdown(grid, unsafe_allow_html=True)


# ── 렌더링: 교차 검증 (cross_check) ──────────────────────────

def _cross_check_html(data: dict) -> str:
    """시장 시각(텔레그램) vs 실제 데이터(정량) → 판정 + 통찰.
    cross_check 필드가 없으면 빈 문자열 반환(표시 안 함)."""
    cc = data.get("cross_check") or {}
    mv = html.escape(str(cc.get("market_view", "")).strip())
    df = html.escape(str(cc.get("data_fact", "")).strip())
    vd = html.escape(str(cc.get("verdict", "")).strip())
    ins = html.escape(str(cc.get("insight", "")).strip())
    if not (mv or df):
        return ""

    verdict_html = ""
    if vd or ins:
        badge = f'<span class="rcc-vbadge">판정 · {vd}</span>' if vd else ""
        verdict_html = f'<div class="rcc-verdict">{badge}{ins}</div>'

    return (
        '<div class="rcc">'
        '<div class="rcc-lab">🔎 교차 검증 · 시각 vs 데이터</div>'
        '<div class="rcc-grid">'
        f'<div class="rcc-col mv"><div class="h">시장 시각 · 텔레그램</div>'
        f'<div class="t">{mv or "—"}</div></div>'
        f'<div class="rcc-col df"><div class="h">실제 데이터 · 정량</div>'
        f'<div class="t">{df or "—"}</div></div>'
        '</div>'
        f'{verdict_html}'
        '</div>'
    )


# ── 렌더링: 취합된 텔레그램 원문 (검증용) ────────────────────

def _render_source_messages(data: dict, kind: str, path: Path):
    """이 보고서가 취합한 텔레그램 원문(채널명·작성시각·본문) — 검증용 조회.
    source_messages 필드가 없으면(구형 보고서) 표시하지 않음.
    PDF/JSON 다운로드 버튼 바로 위에 배치한다."""
    msgs = data.get("source_messages") or []
    if not msgs:
        return

    # 채널별 건수 요약 (어느 채널에서 몇 건 들어왔는지 한눈에)
    from collections import Counter
    chan_counts = Counter(str(m.get("channel", "")).strip() or "(미상)" for m in msgs)
    n_chan = len(chan_counts)

    with st.expander(f"📨 취합된 텔레그램 원문 {len(msgs)}건 · 채널 {n_chan}곳 — 검증용"):
        st.markdown(
            '<div class="srcmsg-cap">이 보고서 생성에 실제로 들어간 메시지 전문입니다. '
            '보고서 내용에 누락·왜곡·오류가 있는지 원문과 직접 대조해 검증하세요. '
            '(작성시각 오름차순)</div>', unsafe_allow_html=True)

        rows = ""
        for m in msgs:
            ch = html.escape(str(m.get("channel", "")).strip() or "(미상)")
            dt = html.escape(str(m.get("date", "")).strip()[:16])
            tx = html.escape(str(m.get("text", "")).strip())
            rows += (
                '<div class="srcmsg">'
                f'<div class="srcmsg-head"><span class="srcmsg-ch">{ch}</span>'
                f'<span class="srcmsg-dt">{dt}</span></div>'
                f'<div class="srcmsg-tx">{tx}</div>'
                '</div>')
        st.markdown(f'<div class="srcmsg-wrap">{rows}</div>', unsafe_allow_html=True)


# ── 렌더링: 장전/장후 카드 ───────────────────────────────────

def _render_report_card(data: dict, kind: str, path: Path):
    icon = "🌅" if kind == "pre" else "🌆"
    kind_ko = "장전 보고서" if kind == "pre" else "장마감 후 보고서"
    kt_lab = "오늘의 관전" if kind == "pre" else "오늘의 결산"

    mood = data.get("mood", "neutral")
    mood_ko = MOOD_KO.get(mood, mood)
    mood_cls = MOOD_CLS.get(mood, "mood-neu")

    since = data.get("analysis_since", "")
    until = data.get("analysis_until", "")
    gen = data.get("generated_at", "")
    n = data.get("messages_count", 0)
    headline = data.get("headline", "")
    kt = data.get("key_takeaway", "")

    if since and until:
        win = f'분석 <b>{since} ~ {until}</b>' + (f' · 생성 {gen}' if gen else "")
    else:
        win = (f'생성 {gen}' if gen else "")

    secs_html = ""
    for sec in data.get("sections", []):
        t = sec.get("title", "")
        b = sec.get("body", "")
        if not t and not b:
            continue
        secs_html += f'<div class="rc-sectitle">{t}</div><div class="rc-secbody">{b}</div>'

    src_bits = []
    if n:
        src_bits.append(f"{n}개 메시지")
    if data.get("data_enriched"):
        src_bits.append("정량 스냅샷")
    sc = data.get("source_channels") or []
    if sc:
        src_bits.append(f"채널 {len(sc)}곳")
    src_html = "".join(f'<span class="src-pill">{html.escape(str(b))}</span>' for b in src_bits)

    kt_html = (f'<div class="rc-ktlab">{kt_lab}</div><div class="rc-ktbox">{kt}</div>'
               if kt else "")
    cc_html = _cross_check_html(data)   # 교차 검증 (본문 섹션 다음, 출처 칩 바로 위)
    st.markdown(
        f'<div class="rc">'
        f'<div class="rc-head"><span class="rc-kind">{icon} {kind_ko}</span>'
        f'<span class="mood-badge {mood_cls}">{mood_ko.upper()}</span></div>'
        f'<div class="rc-win">{win}</div>'
        f'<div class="rc-headline">{headline}</div>'
        f'{kt_html}{secs_html}{cc_html}'
        f'<div class="rc-src">{src_html}</div>'
        f'</div>', unsafe_allow_html=True)

    # 취합된 텔레그램 원문 조회 (검증용) — PDF/JSON 버튼 위
    _render_source_messages(data, kind, path)

    # PDF · JSON 다운로드 (JSON = 깃허브 영구 저장용)
    b1, b2 = st.columns(2)
    with b1:
        try:
            from modules.report_pdf import build_pdf
            st.download_button("📄 PDF", data=build_pdf(data),
                               file_name=f"{path.stem}.pdf", mime="application/pdf",
                               key=f"pdf_{kind}_{path.stem}", use_container_width=True)
        except Exception:
            st.caption("PDF 생성 불가")
    with b2:
        st.download_button(
            "💾 JSON 저장", data=json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name=path.name, mime="application/json",
            key=f"json_{kind}_{path.stem}", use_container_width=True)
    st.caption("💾 받은 JSON을 깃허브 `reports/` 에 올리면 리부트에도 보존되고 타임라인에도 자동 반영돼요.")


def _render_placeholder(kind: str):
    if kind == "pre":
        icon, msg = "🌅", "장전 보고서 생성 전"
        hint, eta = "장 시작 전 아침에 생성됩니다.", "오전 7:50 예정 · 전일 15:30 ~ 07:50"
    else:
        icon, msg = "🌆", "장마감 후 보고서 생성 전"
        hint, eta = "장 마감 후 생성됩니다.", "오후 5:00 예정 · 07:50 ~ 17:00"
    st.markdown(
        f'<div class="rc-empty"><div class="ico">{icon}</div>'
        f'<div class="msg">{msg}</div><div class="hint">{hint}</div>'
        f'<div class="eta">{eta}</div></div>', unsafe_allow_html=True)


# ── 렌더링: 주목 테마 (하단 전체 폭) ─────────────────────────

def _render_themes(data: dict):
    themes = data.get("themes", []) if data else []
    st.markdown('<div class="rpt2-grp">🎯 주목 테마</div>', unsafe_allow_html=True)
    if not themes:
        st.markdown('<div class="rpt-side-empty">이 보고서에는 테마 정보가 없어요.</div>',
                    unsafe_allow_html=True)
        return
    cards = ""
    for th in themes:
        name = th.get("name", "")
        detail = th.get("detail", "")
        tickers = [t.strip() for t in (th.get("tickers") or "").split(",") if t.strip()]
        tk_html = "".join(
            f'<a href="{naver_stock_url(t)}" target="_blank">{html.escape(t)}</a>'
            for t in tickers)
        cards += (
            f'<div class="theme-card">'
            f'<div class="theme-name">{name}</div>'
            f'<div class="theme-detail">{detail}</div>'
            + (f'<div class="theme-tickers">관련: {tk_html}</div>' if tk_html else "")
            + '</div>')
    st.markdown(f'<div class="rpt-theme-grid">{cards}</div>', unsafe_allow_html=True)


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


# ── 메인: 리포트 표시 (탭 상단) ──────────────────────────────

def render_reports():
    """기준일(기본=오늘)의 장전·장후를 하루 단위로 표시."""
    st.markdown(_RPT_CSS, unsafe_allow_html=True)
    files = list_reports()

    sel_date = _selected_date(files)
    st.markdown('<div class="rpt2-bar"></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="rpt2-date">{_fmt_date_ko(sel_date)}</div>'
                f'<div class="rpt2-title">전략·시황 보고서</div>', unsafe_allow_html=True)

    if not files:
        st.markdown(
            '<div class="rc-empty"><div class="ico">📰</div>'
            '<div class="msg">아직 생성된 리포트가 없어요</div>'
            '<div class="hint">아래 🌅 장전 / 🌆 장마감 후 버튼으로 첫 리포트를 만들어보세요</div></div>',
            unsafe_allow_html=True)
        return

    (pre_path, pre_data), (post_path, post_data) = _find_for_date(files, sel_date)
    latest = post_data or pre_data
    latest_kind = "post" if post_data else "pre"

    # ⓪ 오늘의 한 줄 TL;DR (최신 보고서 기준)
    _render_tldr(pre_data, post_data, latest, latest_kind)

    # ① 시장 동력 매트릭스 (최신 보고서 기준)
    if latest:
        _render_matrix(latest, latest_kind)

    # ② 좌 장전 / 우 장마감 후
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    left, right = st.columns(2, gap="large")
    with left:
        if pre_data:
            _render_report_card(pre_data, "pre", pre_path)
        else:
            _render_placeholder("pre")
    with right:
        if post_data:
            _render_report_card(post_data, "post", post_path)
        else:
            _render_placeholder("post")

    # ③ 주목 테마 (전체 폭)
    _render_themes(latest)


# ── 메인: 리포트 관리 (탭 하단) ──────────────────────────────

def render_reports_manage():
    """지난 보고서(날짜) 탐색 + 삭제. render_reports() 아래쪽에 배치."""
    files = list_reports()
    if not files:
        return

    dates = sorted({_report_date(f) for f in files}, reverse=True)
    today = date.today()
    sel = _selected_date(files)

    with st.expander(f"🗂 지난 보고서 보기 ({len(dates)}일치)", expanded=(sel != today)):
        idx = dates.index(sel) if sel in dates else 0
        chosen_i = st.selectbox(
            "날짜 선택", options=range(len(dates)), index=idx,
            format_func=lambda i: _fmt_date_ko(dates[i]),
            key="rpt_date_pick")
        chosen_date = dates[chosen_i]
        if chosen_date != sel:
            (pre_p, _), (post_p, _) = _find_for_date(files, chosen_date)
            anchor = post_p or pre_p
            if anchor is not None:
                st.session_state["rpt_picked_path"] = str(anchor)
                st.rerun()
        if sel != today and st.button("↩ 오늘로", key="rpt_to_today"):
            st.session_state["rpt_picked_path"] = None
            st.rerun()

    _render_delete_ui(files)
