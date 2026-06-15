"""전략·시황 보고서 뷰어 — 하루 단위(장전·장마감 후) 레이아웃, 미니멀 미스트.

2026-06 재설계: 새 topics 스키마(주제 카드) 지원 + 과거 보고서 폴백.
- 새 보고서(topics 있음): 주제 카드(사실/시장시각[합의·이견]/정량/시사점) + 목적별 꼬리 + 변화 추적
- 과거 보고서(topics 없음): 기존 sections/market_drivers/cross_check 레이아웃 그대로

2026-06 저장소 이전: 보고서를 reports/ 폴더 대신 Supabase DB에서 읽고/쓴다.
  list_reports()는 DB의 보고서를 '가상 경로(Path)'로 반환해, 기존 path 기반 로직을
  그대로 재사용한다. (slug = 파일명 stem = "2026-06-14_0430")

2026-06 레이아웃 개선(⑥⑧): 생성 로직 무변경, 뷰어 순서/위치만 조정.
  - ⑧ 주목 테마를 장전·장후 카드 '위'로 이동 (TL;DR → 테마 → 좌우 카드).
  - ⑥ 취합된 텔레그램 원문을 카드 밖 '맨 아래'로 강등(검증용 메타).
"""

import html
import json
import re
from datetime import date
from pathlib import Path

import streamlit as st

from modules.stocks import naver_stock_url
from modules.mood import MOOD_KO, mood_css
from modules import db

REPORTS_DIR = Path("reports")  # (보존용 — 이제 목록/로드는 DB가 담당)
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

/* ★추가: 보고서 보는 법 팝오버 내부 스타일 (체온계·금리차 팝오버 톤에 맞춤) */
.rpt-help-h{font-family:'Fraunces','Noto Sans KR',serif;font-size:14px;font-weight:600;color:var(--ink,#34352f);margin:2px 0 6px;}
.rpt-help-h.second{margin-top:14px;padding-top:12px;border-top:1px solid var(--line,#ECEDE7);}
.rpt-help-p{font-size:12.5px;line-height:1.7;color:var(--ink,#34352f);margin:0 0 7px;}
.rpt-help-p b{color:var(--sage-deep,#7E9A83);font-weight:700;}
.rpt-help-li{font-size:12.5px;line-height:1.65;color:var(--ink,#34352f);padding-left:14px;position:relative;margin-bottom:6px;}
.rpt-help-li::before{content:"·";position:absolute;left:3px;color:var(--sage,#A7BBA9);font-weight:700;}
.rpt-help-li b{color:var(--sage-deep,#7E9A83);font-weight:700;}
.rpt-help-note{font-size:11.5px;line-height:1.6;color:var(--muted,#9a9b92);background:var(--summary-bg,#F6F7F2);border-radius:8px;padding:8px 11px;margin-top:10px;}

/* ⓪ 오늘의 한 줄 TL;DR (상단) */
.rpt-tldr{background:#fff;border:1px solid var(--line,#ECEDE7);border-left:4px solid var(--sage,#A7BBA9);border-radius:0 16px 16px 0;padding:15px 19px;margin:4px 0 6px;}
.rpt-tldr .top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px;}
.rpt-tldr .lab{font-size:10.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted,#9a9b92);}
.tldr-step{display:inline-flex;align-items:center;gap:5px;}
.tldr-steplab{font-size:11px;font-weight:700;color:var(--muted,#9a9b92);}
.tldr-arrow{color:var(--muted,#9a9b92);font-size:11px;font-weight:700;}
.rpt-tldr .hl{font-family:'Fraunces','Noto Sans KR',serif;font-size:19px;font-weight:600;line-height:1.42;color:var(--ink,#34352f);}
.rpt-tldr .kt{font-size:12.5px;color:var(--muted,#9a9b92);line-height:1.62;margin-top:7px;}
/* 숫자 띠 (snapshot_line) */
.rpt-snap{font-size:12px;font-weight:600;color:var(--sage-deep,#7E9A83);background:var(--summary-bg,#F6F7F2);border-radius:8px;padding:7px 13px;margin-top:9px;display:inline-block;}

/* 시장 동력 매트릭스 (구형 보고서용 — 유지) */
.dvm{display:grid;grid-template-columns:0.58fr 1.21fr 1.21fr;background:#fff;
  border:1px solid var(--line,#ECEDE7);border-radius:16px;overflow:hidden;}
.dvm-h{font-size:12.5px;font-weight:700;padding:11px 16px;display:flex;align-items:center;gap:6px;
  border-bottom:1px solid var(--line,#ECEDE7);}
.dvm-h em{font-style:normal;font-size:10px;font-weight:600;color:var(--muted,#9a9b92);margin-left:2px;}
.dvm-h0{background:var(--summary-bg,#F6F7F2);color:var(--muted,#9a9b92);font-size:11px;
  letter-spacing:.04em;text-transform:uppercase;}
.dvm-hup{background:var(--tint-up,#FBF2F2);color:var(--up,#B65F5A);}
.dvm-hdown{background:var(--tint-down,#F1F5F9);color:var(--down,#5A7CA0);}
.dvm-tf{padding:14px 16px;border-bottom:1px solid var(--line,#ECEDE7);background:var(--summary-bg,#F6F7F2);
  display:flex;flex-direction:column;justify-content:center;}
.tf-name{font-size:15px;font-weight:700;color:var(--ink,#34352f);}
.tf-name em{display:block;font-style:normal;font-size:10px;color:var(--muted,#9a9b92);
  font-weight:600;margin:2px 0 0;letter-spacing:.02em;}
.tf-sub{font-size:10.5px;color:var(--muted,#9a9b92);margin-top:6px;line-height:1.4;}
.dvm-cell{padding:11px 14px;border-bottom:1px solid var(--line,#ECEDE7);
  border-left:1px solid var(--line,#ECEDE7);display:flex;flex-direction:column;gap:8px;}
.dvi{position:relative;padding:8px 11px 8px 13px;border-radius:9px;background:var(--summary-bg,#F6F7F2);
  border:1px solid var(--line,#ECEDE7);}
.dvi::before{content:"";position:absolute;left:0;top:8px;bottom:8px;width:3px;border-radius:3px;}
.dvi.up::before{background:var(--up,#B65F5A);}
.dvi.down::before{background:var(--down,#5A7CA0);}
.dvi-lab{display:inline-block;font-size:11px;font-weight:700;padding:1px 8px;border-radius:6px;margin-bottom:4px;}
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

/* 교차 검증 (구형 보고서용 — 유지) */
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

/* ── 새 주제 카드 (topics 스키마) ── */
.tp-list{display:flex;flex-direction:column;gap:11px;margin-bottom:6px;}
.tp{background:#fff;border:1px solid var(--line,#ECEDE7);border-radius:13px;padding:13px 15px;
  transition:box-shadow .18s ease,border-color .18s ease;}
.tp:hover{box-shadow:0 4px 14px rgba(52,53,47,.06);border-color:var(--sage,#A7BBA9);}
.tp-head{display:flex;align-items:center;gap:8px;margin-bottom:7px;}
.tp-rank{font-family:'Fraunces','Noto Sans KR',serif;font-size:16px;font-weight:600;
  color:var(--sage-deep,#7E9A83);min-width:18px;}
.tp-title{font-size:15px;font-weight:700;color:var(--ink,#34352f);flex:1;word-break:keep-all;}
.tp-imp{font-size:10px;font-weight:700;color:var(--muted,#9a9b92);background:var(--summary-bg,#F6F7F2);
  padding:2px 7px;border-radius:6px;flex:none;}
.tp-fact{font-size:13px;line-height:1.7;color:var(--ink,#34352f);margin-bottom:9px;}
.tp-mv{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:9px;}
.tp-mv-col{flex:1;min-width:170px;border-radius:9px;padding:8px 11px;font-size:12px;line-height:1.55;}
.tp-mv-con{background:#eef4ef;border-left:3px solid var(--sage-deep,#7E9A83);}
.tp-mv-dis{background:#FBF2F2;border-left:3px solid var(--up,#B65F5A);}
.tp-mv-lab{font-size:9.5px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;
  display:block;margin-bottom:3px;}
.tp-mv-con .tp-mv-lab{color:var(--sage-deep,#7E9A83);}
.tp-mv-dis .tp-mv-lab{color:var(--up,#B65F5A);}
.tp-mv-tx{color:var(--ink,#34352f);}
.tp-metrics{font-size:11.5px;color:var(--down,#5A7CA0);background:var(--tint-down,#F1F5F9);
  border-radius:7px;padding:6px 10px;margin-bottom:8px;font-weight:600;}
.tp-impl{font-size:12.5px;line-height:1.62;color:var(--ink,#34352f);
  border-top:1px dashed var(--line,#ECEDE7);padding-top:8px;}
.tp-impl b{color:var(--sage-deep,#7E9A83);font-weight:700;}
.tp-stocks{margin-top:8px;display:flex;flex-wrap:wrap;gap:5px;}
.tp-stk{font-size:11px;font-weight:600;text-decoration:none;background:var(--pill-bg,#F1F2EC);
  color:var(--pill-ink,#5d6258);border:1px solid var(--line,#ECEDE7);padding:2px 8px;border-radius:7px;}
.tp-stk:hover{border-color:var(--sage,#A7BBA9);}

/* 목적별 꼬리 (outlook) */
.ol{background:var(--summary-bg,#F6F7F2);border:1px solid var(--line,#ECEDE7);border-radius:13px;
  padding:13px 16px;margin-top:12px;}
.ol-lab{font-size:10.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
  color:var(--sage-deep,#7E9A83);margin-bottom:8px;}
.ol-list{margin:0;padding-left:18px;}
.ol-list li{font-size:13px;line-height:1.7;color:var(--ink,#34352f);margin-bottom:4px;}
.ol-list li::marker{color:var(--sage,#A7BBA9);}
.ol-rev{font-size:13px;line-height:1.7;color:var(--ink,#34352f);margin-bottom:8px;}
.ol-rev b,.ol-tom b{font-weight:700;color:var(--sage-deep,#7E9A83);}
.ol-tom{font-size:13px;line-height:1.7;color:var(--ink,#34352f);}

/* 변화 추적 (change_tracking) */
.ch{display:flex;gap:9px;flex-wrap:wrap;margin-top:12px;}
.ch-col{flex:1;min-width:180px;border:1px solid var(--line,#ECEDE7);border-radius:11px;padding:10px 13px;background:#fff;}
.ch-lab{font-size:10px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;margin-bottom:6px;}
.ch-new .ch-lab{color:#0f6e56;}
.ch-cont .ch-lab{color:var(--muted,#9a9b92);}
.ch-item{font-size:12px;line-height:1.6;color:var(--ink,#34352f);padding:2px 0;}
.ch-new .ch-item::before{content:"+ ";color:#0f6e56;font-weight:700;}
.ch-cont .ch-item::before{content:"· ";color:var(--muted,#9a9b92);font-weight:700;}

/* 취합된 텔레그램 원문 (검증용) */
.srcmsg-cap{font-size:11.5px;color:var(--muted,#9a9b92);line-height:1.6;margin-bottom:10px;}
.srcmsg-wrap{display:flex;flex-direction:column;gap:9px;max-height:460px;overflow-y:auto;padding-right:4px;}
.srcmsg{border:1px solid var(--line,#ECEDE7);border-left:3px solid var(--sage,#A7BBA9);border-radius:0 10px 10px 0;padding:9px 13px;background:#fff;}
.srcmsg-head{display:flex;align-items:baseline;justify-content:space-between;gap:8px;margin-bottom:5px;}
.srcmsg-ch{font-size:11.5px;font-weight:700;color:var(--sage-deep,#7E9A83);word-break:break-all;}
.srcmsg-dt{font-size:10.5px;color:var(--muted,#9a9b92);white-space:nowrap;flex:none;}
.srcmsg-tx{font-size:12.5px;line-height:1.62;color:var(--ink,#34352f);white-space:pre-wrap;}

/* 주목 테마 (전체 폭) */
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
    # DB의 보고서를 '가상 경로(Path)'로 반환 — 기존 path 기반 로직을 그대로 재사용.
    # slug = 파일명 stem (예: "2026-06-14_0430"), 디스크에 실제 파일은 없음.
    return [Path(f"{slug}.json") for slug in db.list_slugs()]


def _report_date(path: Path) -> date:
    try:
        y, m, d = path.stem.split("_")[0].split("-")
        return date(int(y), int(m), int(d))
    except Exception:
        return date.today()


def _load(path: Path) -> dict:
    # slug(=stem)로 DB에서 보고서 조회. 없으면 안전한 빈 dict 반환.
    data = db.load_by_slug(path.stem)
    if data:
        return data
    return {
        "headline": path.stem, "key_takeaway": "",
        "sections": [], "themes": [], "keywords": [],
        "mood": "neutral", "report_kind": _infer_kind_from_name(path),
        "generated_at": "", "messages_count": 0,
    }


def _infer_kind_from_name(path: Path) -> str:
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
    pk = st.session_state.get("rpt_picked_path")
    # 가상 경로는 디스크에 없으므로 .exists() 대신 '목록에 있는지'로 확인.
    if pk and Path(pk).stem in {f.stem for f in files}:
        return _report_date(Path(pk))
    today = date.today()
    dates = {_report_date(f) for f in files}
    if today in dates:
        return today
    return max(dates) if dates else today


def _find_for_date(files, d: date):
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
        for tp in data.get("topics", []):
            for s in (tp.get("stocks") or []):
                if str(s).strip():
                    stocks.add(str(s).strip())
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


# ── ★수정: 보고서 보는 법 팝오버 (⑥⑧ 새 순서 반영) ─────────

def _render_report_help_popover():
    """제목 옆 ⓘ 보고서 보는 법 팝오버 — 체온계·금리차 팝오버와 동일한 방식.
    내용: (1) 생성 시점, (2) 독자 활용법 — 화면 순서(테마 위, 원문 맨 아래)에 맞춤."""
    with st.popover("ⓘ 보고서 보는 법", use_container_width=True):
        st.markdown(
            '<div class="rpt-help-h">🕒 생성 시점</div>'
            '<div class="rpt-help-li"><b>장전 보고서</b>는 평일 아침(KST 07:50경) '
            '자동 생성돼요. 전일 미국장 마감과 밤사이 시장 시각을 종합해 그날의 시나리오를 제시합니다.</div>'
            '<div class="rpt-help-li"><b>장마감 후 보고서</b>는 한국장 마감 이후 생성돼요. '
            '당일 실제 흐름을 반영해 장전 시나리오가 맞았는지 점검하고 다음날 관전 포인트를 정리합니다.</div>'
            '<div class="rpt-help-li">카드의 <b>분석</b> 시각은 데이터를 취합한 구간, '
            '<b>생성</b> 시각은 보고서가 실제로 만들어진 시점이에요.</div>'
            '<div class="rpt-help-h second">📖 읽는 순서</div>'
            '<div class="rpt-help-li">맨 위 <b>오늘의 한 줄</b>로 그날 시장을 한 문장으로 파악하세요. '
            '장전·장후 분위기 뱃지와 핵심 수치가 함께 붙어 있어요.</div>'
            '<div class="rpt-help-li">바로 아래 <b>주목 테마</b>에서 그날 자금이 쏠린 섹터를 먼저 훑으면 '
            '큰 그림이 잡혀요. 세부 근거는 그 아래 카드에서 확인합니다.</div>'
            '<div class="rpt-help-li"><b>장전 / 장마감 후 카드</b>는 주제별로 나뉘어요. '
            '각 주제의 <b>합의 / 이견</b> 박스는 시장 컨센서스와 반대 시각을 함께 보여주니 '
            '한쪽만 믿지 말고 양쪽을 견주는 용도로 보세요. <b>중요도</b>가 높은 주제부터 보면 '
            '시간이 부족할 때 효율적이에요.</div>'
            '<div class="rpt-help-li">맨 아래 <b>취합된 텔레그램 원문</b>은 보고서 생성에 실제로 '
            '쓰인 메시지 전문이에요. 분석 내용을 원문과 직접 대조해 검증하고 싶을 때 펼쳐 보세요.</div>'
            '<div class="rpt-help-note">⚠️ 본 보고서는 AI가 생성한 분석이며 투자 권유가 아닙니다. '
            '최종 판단과 책임은 투자자 본인에게 있어요.</div>',
            unsafe_allow_html=True)


# ── 렌더링: 오늘의 한 줄 TL;DR ───────────────────────────────

def _lead_text(data: dict) -> str:
    """카드 요약 한 줄: 새 스키마는 첫 주제 fact, 구형은 key_takeaway."""
    topics = data.get("topics") or []
    if topics:
        return str(topics[0].get("fact", "")).strip()
    return str(data.get("key_takeaway", "")).strip()


def _render_tldr(pre_data, post_data, latest, latest_kind):
    if not latest:
        return
    headline = html.escape(str(latest.get("headline", "")).strip())
    if not headline:
        return
    kt = html.escape(_lead_text(latest))
    snap = html.escape(str(latest.get("snapshot_line", "")).strip())

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
    snap_html = f'<div class="rpt-snap">{snap}</div>' if snap else ""
    st.markdown(
        f'<div class="rpt-tldr">'
        f'<div class="top"><span class="lab">오늘의 한 줄</span>{pills}</div>'
        f'<div class="hl">{headline}</div>'
        f'{kt_html}{snap_html}'
        f'</div>', unsafe_allow_html=True)


# ── 렌더링: 시장 동력 매트릭스 (구형 보고서 전용) ────────────

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


# ── 렌더링: 교차 검증 (구형 보고서 전용) ─────────────────────

def _cross_check_html(data: dict) -> str:
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


# ── 렌더링: 새 주제 카드 (topics 스키마) ─────────────────────

def _topics_html(topics: list) -> str:
    cards = []
    for i, tp in enumerate(topics, start=1):
        if not isinstance(tp, dict):
            continue
        title = html.escape(str(tp.get("title", "")).strip())
        if not title:
            continue
        imp = tp.get("importance", "")
        fact = html.escape(str(tp.get("fact", "")).strip())
        mv = tp.get("market_view") or {}
        cons = html.escape(str(mv.get("consensus", "")).strip())
        diss = html.escape(str(mv.get("dissent", "")).strip())
        metrics = html.escape(str(tp.get("metrics", "")).strip())
        impl = html.escape(str(tp.get("implication", "")).strip())
        stocks = [str(s).strip() for s in (tp.get("stocks") or []) if str(s).strip()]

        imp_html = f'<span class="tp-imp">중요도 {imp}</span>' if str(imp) else ""
        fact_html = f'<div class="tp-fact">{fact}</div>' if fact else ""

        mv_cols = ""
        if cons:
            mv_cols += (f'<div class="tp-mv-col tp-mv-con">'
                        f'<span class="tp-mv-lab">합의</span>'
                        f'<span class="tp-mv-tx">{cons}</span></div>')
        if diss:
            mv_cols += (f'<div class="tp-mv-col tp-mv-dis">'
                        f'<span class="tp-mv-lab">이견</span>'
                        f'<span class="tp-mv-tx">{diss}</span></div>')
        mv_html = f'<div class="tp-mv">{mv_cols}</div>' if mv_cols else ""

        metrics_html = f'<div class="tp-metrics">📊 {metrics}</div>' if metrics else ""
        impl_html = f'<div class="tp-impl"><b>시사점</b> · {impl}</div>' if impl else ""

        stocks_html = ""
        if stocks:
            chips = "".join(
                f'<a class="tp-stk" href="{naver_stock_url(s)}" target="_blank" '
                f'rel="noopener">{html.escape(s)}</a>' for s in stocks)
            stocks_html = f'<div class="tp-stocks">{chips}</div>'

        cards.append(
            f'<div class="tp">'
            f'<div class="tp-head"><span class="tp-rank">{i}</span>'
            f'<span class="tp-title">{title}</span>{imp_html}</div>'
            f'{fact_html}{mv_html}{metrics_html}{impl_html}{stocks_html}'
            f'</div>'
        )
    if not cards:
        return ""
    return f'<div class="tp-list">{"".join(cards)}</div>'


def _outlook_html(data: dict, kind: str) -> str:
    ol = data.get("outlook") or {}
    if kind == "pre":
        items = ol.get("pre") or []
        items = [html.escape(str(x).strip()) for x in items if str(x).strip()]
        if not items:
            return ""
        lis = "".join(f'<li>{x}</li>' for x in items)
        return (f'<div class="ol"><div class="ol-lab">🔭 오늘 볼 것</div>'
                f'<ul class="ol-list">{lis}</ul></div>')
    else:
        post = ol.get("post") or {}
        rev = html.escape(str(post.get("review", "")).strip())
        tom = html.escape(str(post.get("tomorrow", "")).strip())
        if not (rev or tom):
            return ""
        rev_html = f'<div class="ol-rev"><b>장전 점검</b> · {rev}</div>' if rev else ""
        tom_html = f'<div class="ol-tom"><b>내일 가설</b> · {tom}</div>' if tom else ""
        return (f'<div class="ol"><div class="ol-lab">🔭 결산 · 내일</div>'
                f'{rev_html}{tom_html}</div>')


def _change_html(data: dict) -> str:
    ch = data.get("change_tracking") or {}
    new = [html.escape(str(x).strip()) for x in (ch.get("new") or []) if str(x).strip()]
    cont = [html.escape(str(x).strip()) for x in (ch.get("continuing") or []) if str(x).strip()]
    if not (new or cont):
        return ""
    cols = ""
    if new:
        items = "".join(f'<div class="ch-item">{x}</div>' for x in new)
        cols += (f'<div class="ch-col ch-new"><div class="ch-lab">오늘 새로 등장</div>'
                 f'{items}</div>')
    if cont:
        items = "".join(f'<div class="ch-item">{x}</div>' for x in cont)
        cols += (f'<div class="ch-col ch-cont"><div class="ch-lab">어제에 이어 지속</div>'
                 f'{items}</div>')
    return f'<div class="ch">{cols}</div>'


# ── 렌더링: 취합된 텔레그램 원문 (검증용) ────────────────────
# ⑥ 변경: _render_report_card 안에서 호출하지 않고, render_reports 맨 아래에서
#         pre/post를 한데 모아 호출한다. (검증용 메타로 강등)

def _render_source_messages(data: dict, kind: str, path: Path):
    msgs = data.get("source_messages") or []
    if not msgs:
        return
    from collections import Counter
    chan_counts = Counter(str(m.get("channel", "")).strip() or "(미상)" for m in msgs)
    n_chan = len(chan_counts)
    kind_ko = "장전" if kind == "pre" else "장마감 후"
    with st.expander(f"📨 [{kind_ko}] 취합된 텔레그램 원문 {len(msgs)}건 · 채널 {n_chan}곳 — 검증용"):
        st.markdown(
            '<div class="srcmsg-cap">이 보고서 생성에 실제로 들어간 메시지 전문입니다. '
            '원문과 직접 대조해 검증하세요. (작성시각 오름차순)</div>', unsafe_allow_html=True)
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


def _render_source_section(pre, post):
    """⑥ 하단 검증용 원문 섹션 — pre/post 둘 다 있으면 각각 expander로."""
    (pre_path, pre_data) = pre
    (post_path, post_data) = post
    has_pre = bool(pre_data and (pre_data.get("source_messages")))
    has_post = bool(post_data and (post_data.get("source_messages")))
    if not (has_pre or has_post):
        return
    st.markdown('<div class="rpt2-grp">🔎 검증용 원문</div>', unsafe_allow_html=True)
    # 최신(장후)을 먼저, 장전을 뒤에.
    if has_post:
        _render_source_messages(post_data, "post", post_path)
    if has_pre:
        _render_source_messages(pre_data, "pre", pre_path)


# ── 렌더링: 장전/장후 카드 ───────────────────────────────────
# ⑥ 변경: 이 함수 안에서 _render_source_messages 호출을 제거.
#         원문은 render_reports 맨 아래 _render_source_section이 담당.

def _render_report_card(data: dict, kind: str, path: Path):
    icon = "🌅" if kind == "pre" else "🌆"
    kind_ko = "장전 보고서" if kind == "pre" else "장마감 후 보고서"

    mood = data.get("mood", "neutral")
    mood_ko = MOOD_KO.get(mood, mood)
    mood_cls = MOOD_CLS.get(mood, "mood-neu")

    since = data.get("analysis_since", "")
    until = data.get("analysis_until", "")
    gen = data.get("generated_at", "")
    n = data.get("messages_count", 0)
    headline = data.get("headline", "")

    if since and until:
        win = f'분석 <b>{since} ~ {until}</b>' + (f' · 생성 {gen}' if gen else "")
    else:
        win = (f'생성 {gen}' if gen else "")

    # 출처 칩
    src_bits = []
    if n:
        src_bits.append(f"{n}개 메시지")
    if data.get("data_enriched"):
        src_bits.append("정량 스냅샷")
    sc = data.get("source_channels") or []
    if sc:
        src_bits.append(f"채널 {len(sc)}곳")
    src_html = "".join(f'<span class="src-pill">{html.escape(str(b))}</span>' for b in src_bits)

    # ── 새 스키마(topics) vs 구형 분기 ──
    topics = data.get("topics") or []
    if topics:
        # 새 양식: 주제 카드 + 목적별 꼬리 + 변화 추적
        body_html = _topics_html(topics)
        outlook_html = _outlook_html(data, kind)
        change_html = _change_html(data)
        st.markdown(
            f'<div class="rc">'
            f'<div class="rc-head"><span class="rc-kind">{icon} {kind_ko}</span>'
            f'<span class="mood-badge {mood_cls}">{mood_ko.upper()}</span></div>'
            f'<div class="rc-win">{win}</div>'
            f'<div class="rc-headline">{html.escape(headline)}</div>'
            f'{body_html}{outlook_html}{change_html}'
            f'<div class="rc-src">{src_html}</div>'
            f'</div>', unsafe_allow_html=True)
    else:
        # 구형 양식: key_takeaway + sections + cross_check
        kt_lab = "오늘의 관전" if kind == "pre" else "오늘의 결산"
        kt = data.get("key_takeaway", "")
        secs_html = ""
        for sec in data.get("sections", []):
            t = sec.get("title", "")
            b = sec.get("body", "")
            if not t and not b:
                continue
            secs_html += f'<div class="rc-sectitle">{t}</div><div class="rc-secbody">{b}</div>'
        kt_html = (f'<div class="rc-ktlab">{kt_lab}</div><div class="rc-ktbox">{kt}</div>'
                   if kt else "")
        cc_html = _cross_check_html(data)
        st.markdown(
            f'<div class="rc">'
            f'<div class="rc-head"><span class="rc-kind">{icon} {kind_ko}</span>'
            f'<span class="mood-badge {mood_cls}">{mood_ko.upper()}</span></div>'
            f'<div class="rc-win">{win}</div>'
            f'<div class="rc-headline">{headline}</div>'
            f'{kt_html}{secs_html}{cc_html}'
            f'<div class="rc-src">{src_html}</div>'
            f'</div>', unsafe_allow_html=True)

    # ⑥ 제거됨: 취합된 텔레그램 원문은 더 이상 카드 안에서 렌더하지 않는다.
    #           (render_reports 맨 아래 _render_source_section이 담당)

    # PDF · JSON 다운로드
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
    st.caption("💾 이 보고서는 생성과 동시에 DB에 저장돼요. 재시작에도 보존되며, JSON은 백업·공유용입니다.")


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


# ── 렌더링: 주목 테마 (전체 폭) ──────────────────────────────

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
                        db.delete_by_slug(Path(s).stem)  # 파일 삭제 → DB 삭제
                        removed += 1
                    except Exception as e:
                        st.error(f"삭제 실패: {Path(s).name} ({e})")
                st.success(f"{removed}개 삭제 완료")
                st.rerun()


# ── 메인: 리포트 표시 (탭 상단) ──────────────────────────────

def render_reports():
    st.markdown(_RPT_CSS, unsafe_allow_html=True)
    files = list_reports()

    sel_date = _selected_date(files)
    st.markdown('<div class="rpt2-bar"></div>', unsafe_allow_html=True)

    # ★변경: 제목 우측에 ⓘ 보고서 보는 법 팝오버 배치
    title_col, help_col = st.columns([0.82, 0.18])
    with title_col:
        st.markdown(f'<div class="rpt2-date">{_fmt_date_ko(sel_date)}</div>'
                    f'<div class="rpt2-title">전략·시황 보고서</div>',
                    unsafe_allow_html=True)
    with help_col:
        _render_report_help_popover()

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

    # ⓪ 오늘의 한 줄 TL;DR
    _render_tldr(pre_data, post_data, latest, latest_kind)

    # ① 시장 동력 매트릭스 (구형 보고서에만 — 새 보고서는 topics가 대체)
    if latest and not (latest.get("topics")):
        _render_matrix(latest, latest_kind)

    # ⑧ 주목 테마 (전체 폭) — 좌우 카드 '위'로 이동
    _render_themes(latest)

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

    # ⑥ 취합된 텔레그램 원문 — 맨 아래 검증용 메타로 강등
    _render_source_section((pre_path, pre_data), (post_path, post_data))


# ── 메인: 리포트 관리 (탭 하단) ──────────────────────────────

def render_reports_manage():
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
