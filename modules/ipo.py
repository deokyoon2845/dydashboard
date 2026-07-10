"""[뷰어] 증시 › IPO 탭 (개편판 · 이번 달 파이프라인 + 비교 테이블).

구성
  ① 요약 스트립   : 최근 1년 종목수 · 공모가比 평균 · 공모가 상회 비율 · 최고 종목
  ② 이번 달 IPO   : ⓐ상장·청약 예정(estkRs: 공모가·청약일·납입일·주관사, 실패 시 '접수' 폴백)
                    ⓑ이달 상장 NEW(공모가→현재 · 시총) — 예정과 구분된 두 그룹
  ③ 최근 상장 비교: 종목당 한 행의 비교 테이블(A안)
        컬럼: 종목·업종 · 상장일 · 시총 · 공모가→현재 · PER · PBR · PSR · 매출 · 영업이익 · 순이익
        정렬: 필 바(상장일/시총/수익률/PER) — 헤더 클릭 정렬은 iframe 필요라 배제(신뢰성)
        펼치면: 회사소개 + 큰 차트 (밸류·재무 블록은 행으로 승격되어 제거)

주 수익률 = 공모가比(현재가/공모가−1). 공모가 파싱 실패 종목은 상장일종가比로 폴백 표기.
추이 스파크라인은 행에서 제거(컬럼 공간) — 모바일 지표 밴드·펼침 차트가 대신한다.

데이터
  · 목록·메타·재무·밸류·공모가·향후일정 : Supabase ipo_snapshots(엔진). 없으면 임베드 샘플 폴백
  · N 아이콘 : 네이버 증권 종목페이지(finance.naver.com/item)
  · 큰 차트 시세 : 뷰어 직접 — 네이버 siseJson, 실패 시 yfinance
"""

import html
import json
from datetime import date, datetime, timedelta, timezone

import altair as alt
import pandas as pd
import requests
import streamlit as st

from modules.stocks import naver_stock_url

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
_UP_C, _DOWN_C = "#B65F5A", "#5A7CA0"
_AXIS_C, _GRID_C = "#9a9b92", "#ECEDE7"
_KST = timezone(timedelta(hours=9))

# ── 임베드 샘플 (DB 미구성 시 폴백 · 전부 예시) ──────────────────
_SAMPLE = {
    "asof": "샘플",
    "recent": [
        {"name": "시프트업", "code": "462870", "market": "코스피", "sector": "소프트웨어·IT서비스",
         "listed": "2024.07.11", "cap": "3.2조", "cap_won": 3.2e12,
         "price": "62,400", "price_won": 62400, "pct": 1.8,
         "ipo_price": "60,000", "ipo_price_won": 60000, "ipo_return": 4.0,
         "revenue": "1,686억", "op_income": "1,110억", "net_income": "846억",
         "per": 38.5, "pbr": 12.1, "psr": 19.0,
         "est_per": 21.3, "eps": "2,930", "eps_won": 2930,
         "lockup": "기관 의무보유 확약 41.6%",
         "intro": "서브컬처 게임 ‘니케’·‘스텔라 블레이드’ 개발사.",
         "spark": [60000, 62500, 58000, 55500, 57800, 61200, 63400, 60100, 59000, 62400]},
        {"name": "더본코리아", "code": "475560", "market": "코스피", "sector": "숙박·음식",
         "listed": "2024.11.06", "cap": "5,400억", "cap_won": 5.4e11,
         "price": "38,200", "price_won": 38200, "pct": 0.9,
         "ipo_price": "34,000", "ipo_price_won": 34000, "ipo_return": 12.4,
         "revenue": "4,107억", "op_income": "409억", "net_income": "327억",
         "per": 16.5, "pbr": 3.4, "psr": 1.3,
         "lockup": "최대주주 의무보유 6개월",
         "intro": "빽다방·홍콩반점 등 외식 브랜드 운영.",
         "spark": [34000, 41000, 38500, 36000, 39200, 42100, 40500, 38200]},
        {"name": "셀비온", "code": "308430", "market": "코스닥", "sector": "제약·바이오",
         "listed": "2024.10.21", "cap": "2,600억", "cap_won": 2.6e11,
         "price": "13,900", "price_won": 13900, "pct": 2.0,
         "ipo_price": "12,200", "ipo_price_won": 12200, "ipo_return": 13.9,
         "revenue": "12억", "op_income": "-95억", "net_income": "-88억",
         "per": None, "pbr": 8.7, "psr": 216.7,
         "lockup": "기관 의무보유 확약 8.3%",
         "intro": "방사성 동위원소 기반 항암 치료제 개발.",
         "spark": [13000, 14200, 12500, 11800, 12900, 13600, 14100, 13900]},
    ],
    "upcoming": [
        {"name": "○○바이오", "dday": "D-3", "state": "청약 06.29~30", "under": "한국투자증권",
         "sub": "06.29~06.30", "pay": "07.02", "price": "18,500", "soon": True,
         "intro": "항암 신약 타깃 단백질 분해(TPD) 플랫폼. 코스닥 예정."},
        {"name": "◇◇소프트", "dday": "접수", "state": "증권신고서 접수 06.18", "under": "",
         "sub": "", "pay": "", "price": "", "soon": False,
         "est_listing": "07.16~07.30 예상",
         "intro": "기업용 생성형 AI 에이전트 플랫폼. 코스닥 기술특례."},
    ],
}

_CSS = """
<style>
/* 탭 상단 바는 표준 크롬(tab_header)의 .accent-bar(전역 CSS)를 사용 — 자체 바 제거 */
.ipo-sec{font-size:13px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;
  color:var(--sage-deep,#7E9A83);margin:24px 0 12px;display:flex;align-items:center;gap:8px;}
.ipo-sec:before{content:"";width:14px;height:2px;background:var(--sage,#A7BBA9);border-radius:2px;}
.ipo-sec .mut{font-weight:600;font-size:11px;text-transform:none;letter-spacing:0;color:var(--muted,#9a9b92);}
.up{color:var(--up,#B65F5A);} .down{color:var(--down,#5A7CA0);} .na{color:#B7BCB3;}
/* ── ① 요약 스트립 ── */
.ipo-sum{display:flex;gap:20px;flex-wrap:wrap;background:var(--summary-bg,#F6F7F2);
  border:1px solid var(--line,#ECEDE7);border-radius:12px;padding:11px 16px;margin:2px 0 6px;}
.ipo-sum .it{font-size:11.5px;color:var(--pill-ink,#5d6258);}
.ipo-sum .it b{font-size:14px;font-weight:800;color:var(--ink,#34352f);margin-left:6px;
  font-variant-numeric:tabular-nums;}
.ipo-sum .it b.up{color:var(--up,#B65F5A);} .ipo-sum .it b.down{color:var(--down,#5A7CA0);}
/* ── ② 이번 달 파이프라인 ── */
.ipo-grp{font-size:11px;font-weight:700;color:var(--pill-ink,#5d6258);margin:14px 0 8px;
  display:flex;align-items:center;gap:6px;flex-wrap:wrap;}
.ipo-grp .dot{width:7px;height:7px;border-radius:50%;background:var(--sage-deep,#7E9A83);flex:none;}
.ipo-grp.new .dot{background:var(--up,#B65F5A);}
.ipo-grp .mut{color:var(--muted,#9a9b92);font-weight:600;}
.ipo-strip{display:flex;flex-wrap:wrap;gap:10px;padding:0 0 4px;}
.ipo-up{flex:1 1 230px;min-width:230px;max-width:330px;background:var(--card,#fff);
  border:1px solid var(--line,#ECEDE7);border-radius:12px;padding:12px 14px;}
.ipo-up.soft{background:var(--summary-bg,#F6F7F2);}
.ipo-up .nm{font-size:13px;font-weight:800;display:flex;justify-content:space-between;gap:8px;align-items:center;}
.ipo-up .nm .t{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.ipo-up .rows{margin-top:9px;display:flex;flex-direction:column;gap:4px;}
.ipo-up .r{display:flex;justify-content:space-between;gap:8px;font-size:11.5px;}
.ipo-up .r .k{color:var(--muted,#9a9b92);flex:none;} .ipo-up .r .v{font-weight:700;color:var(--pill-ink,#5d6258);
  text-align:right;font-variant-numeric:tabular-nums;}
.ipo-up .ds{font-size:11px;color:var(--pill-ink,#5d6258);margin-top:9px;line-height:1.5;word-break:keep-all;
  border-top:1px dashed var(--line,#ECEDE7);padding-top:7px;}
.dday{font-size:10.5px;font-weight:800;color:#fff;background:var(--sage-deep,#7E9A83);
  padding:3px 8px;border-radius:6px;flex:none;}
.dday.soon{background:#C2410C;} .dday.tbd{background:#B7BCB3;} .dday.new{background:var(--up,#B65F5A);}
/* ── ③ 최근 상장 비교 테이블(A안) — CSS grid 행 ── */
.ipo-head,.ipo-row{display:grid;gap:7px;align-items:center;
  grid-template-columns:minmax(138px,1.5fr) 58px 54px 110px 42px 50px 44px 44px 58px 60px 60px 60px;}
.ipo-head{padding:8px 6px;font-size:10px;font-weight:700;color:var(--muted,#9a9b92);
  letter-spacing:.03em;border-bottom:1px solid var(--line,#ECEDE7);background:var(--bg,#FCFCFA);}
/* 헤더 고정(sticky) — 행이 많아도 어떤 지표 컬럼인지 유지(2026-07).
   sticky 요소는 부모 박스 안에 갇히므로 .ipo-head 자체가 아니라, 테이블 전체를 감싼
   keyed 컨테이너(st-key-ipo_tbl) 안에서 헤더를 담은 요소 컨테이너에 :has()로 건다.
   :has() 미지원 브라우저에선 그냥 기존처럼 안 붙을 뿐(기능 저하 없음). */
.st-key-ipo_tbl [data-testid="stElementContainer"]:has(.ipo-head),
.st-key-ipo_tbl [data-testid="element-container"]:has(.ipo-head){
  position:sticky;top:3.75rem;z-index:6;background:var(--bg,#FCFCFA);}
.ipo-head span{text-align:right;} .ipo-head span:first-child{text-align:left;}
.ipo-row{padding:11px 6px;border-bottom:1px solid var(--line,#ECEDE7);transition:background .15s ease;}
.ipo-row:hover{background:#fbfbf8;}
.ipo-row .nmcell{min-width:0;}
.ipo-row .nmcell .nm{font-size:13px;font-weight:800;line-height:1.2;display:flex;align-items:center;}
.ipo-row .nmcell .nm a{color:var(--ink,#34352f);text-decoration:none;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis;}
.ipo-row .nmcell .nm a:hover{text-decoration:underline;}
.ipo-row .nmcell .sub{display:flex;align-items:center;gap:6px;margin-top:4px;min-width:0;}
.ipo-row .nmcell .sct{font-size:10px;color:var(--muted,#9a9b92);font-weight:600;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.nv{flex:none;width:15px;height:15px;border-radius:4px;background:#03C75A;color:#fff;font-size:9.5px;
  font-weight:800;display:inline-flex;align-items:center;justify-content:center;margin-left:6px;
  text-decoration:none;line-height:1;}
.mk{flex:none;font-size:9px;font-weight:700;padding:2px 6px;border-radius:5px;line-height:1;}
.mk.kospi{background:#EEF2F6;color:#5A7CA0;} .mk.kosdaq{background:#F6EFEA;color:#B65F5A;}
.ipo-row .num{font-size:11.5px;text-align:right;font-variant-numeric:tabular-nums;color:var(--pill-ink,#5d6258);}
.ipo-row .num b{font-weight:700;color:var(--ink,#34352f);}
.ipo-row .num .neg{color:var(--down,#5A7CA0);}
.ipo-row .dt{font-size:11px;color:var(--pill-ink,#5d6258);text-align:right;font-variant-numeric:tabular-nums;}
.ipo-row .retcell{text-align:right;}
.ipo-row .retcell .pct{font-size:13px;font-weight:800;font-variant-numeric:tabular-nums;}
.ipo-row .retcell .base{display:block;font-size:9.5px;color:var(--muted,#9a9b92);margin-top:2px;
  font-variant-numeric:tabular-nums;white-space:nowrap;}
/* 모바일 지표 밴드 — 데스크톱에선 숨김 */
.ipo-row .mband{display:none;}
/* 세그먼트(정렬 등) 선택 색 — 기존 유지 */
div[data-testid="stSegmentedControl"] button[aria-checked="true"] p,
div[data-testid="stSegmentedControl"] button[kind="segmented_controlActive"] p,
div[data-testid="stSegmentedControl"] button[data-testid="stBaseButton-segmented_controlActive"] p{
  color:var(--sage-deep,#7E9A83)!important;}
.ipo-cna{font-size:12px;color:var(--muted,#9a9b92);padding:14px 4px;}
@media(max-width:680px){
  /* 테이블 → 2컬럼(종목 · 수익률) + 지표 밴드 */
  .ipo-head{display:none;}
  .ipo-row{grid-template-columns:minmax(0,1fr) 118px;}
  .ipo-row .dt,.ipo-row .num{display:none;}
  .ipo-row .mband{display:flex;flex-wrap:wrap;gap:5px;grid-column:1 / -1;margin-top:8px;}
  .ipo-row .mband .chip{font-size:10px;background:var(--summary-bg,#F6F7F2);
    border:1px solid var(--line,#ECEDE7);border-radius:6px;padding:3px 8px;color:var(--pill-ink,#5d6258);}
  .ipo-row .mband .chip b{font-weight:800;color:var(--ink,#34352f);margin-left:4px;
    font-variant-numeric:tabular-nums;}
  .ipo-row .mband .chip b.neg{color:var(--down,#5A7CA0);}
  /* 섹션 설명문(mut)을 제목 아래 줄로 */
  .ipo-sec{flex-wrap:wrap;}
  .ipo-sec .mut{flex-basis:100%;margin-left:22px;}
  /* 파이프라인 카드 2열 */
  .ipo-strip{gap:8px;}
  .ipo-up{flex:1 1 calc(50% - 4px);min-width:0;max-width:none;padding:9px 10px;}
  .ipo-up .nm{gap:6px;}
  .ipo-sum{gap:10px 16px;}
}
</style>
"""

_SORTS = ["상장일순", "시총순", "수익률순", "PER순"]


def _naver_item_url(code: str) -> str:
    c = "".join(ch for ch in str(code or "") if ch.isdigit())[:6]
    return f"https://finance.naver.com/item/main.naver?code={c}" if len(c) == 6 else ""


# ── DB 로드 ────────────────────────────────────────────────────
def load_ipo() -> dict:
    try:
        from modules import db
        if db.supabase_configured() and hasattr(db, "load_ipo"):
            row = db.load_ipo()
            if row and (row.get("recent") or row.get("upcoming")):
                row["_sample"] = False
                return row
    except Exception:
        pass
    s = dict(_SAMPLE)
    s["_sample"] = True
    return s


# ── 종목명 → (코드, 접미사) ────────────────────────────────────
@st.cache_data(ttl=86400)
def _resolve_code(name: str):
    q = (name or "").strip()
    if not q:
        return None, None
    try:
        r = requests.get("https://ac.stock.naver.com/ac",
                         params={"q": q, "target": "stock,etf", "where": "nexearch"},
                         headers=_UA, timeout=4)
        r.raise_for_status()
        items = (r.json() or {}).get("items") or []
    except Exception:
        return None, None
    nq = "".join(q.split()).casefold()
    first = best = None
    for it in items:
        code = mkt = nm = None
        if isinstance(it, dict):
            code = it.get("code") or it.get("cd")
            mkt = (it.get("typeCode") or it.get("type") or it.get("typeName") or "")
            nm = it.get("name") or it.get("nm")
        elif isinstance(it, (list, tuple)) and it:
            flat = it[0] if (it and isinstance(it[0], (list, tuple))) else it
            code = flat[0] if len(flat) > 0 else None
            nm = flat[1] if len(flat) > 1 else None
            mkt = flat[2] if len(flat) > 2 else ""
        if not code:
            continue
        code = str(code).strip().zfill(6)
        suffix = ".KQ" if "KOSDAQ" in str(mkt).upper() else ".KS"
        cand = (code, suffix)
        first = first or cand
        if nm and "".join(str(nm).split()).casefold() == nq:
            best = cand
            break
    return best or first or (None, None)


# ── 일별 시세 ──────────────────────────────────────────────────
@st.cache_data(ttl=900)
def _daily(code: str, suffix: str, days: int):
    df = _naver_daily(code, days)
    if df is not None and len(df) >= 2:
        return df
    return _yf_daily(code, suffix, days)


def _naver_daily(code: str, days: int):
    try:
        end = date.today().strftime("%Y%m%d")
        start = (date.today() - timedelta(days=days + 5)).strftime("%Y%m%d")
        url = ("https://api.finance.naver.com/siseJson.naver"
               f"?symbol={code}&requestType=1&startTime={start}&endTime={end}&timeframe=day")
        r = requests.get(url, headers=_UA, timeout=6)
        r.raise_for_status()
        rows = json.loads(r.text.strip().replace("'", '"'))
        out = []
        for x in rows[1:]:
            if not x or len(x) < 5:
                continue
            try:
                d = pd.to_datetime(str(x[0]), errors="coerce")
                c = float(x[4])
            except (ValueError, TypeError):
                continue
            if pd.notna(d):
                out.append((d, c))
        if len(out) < 2:
            return None
        return pd.DataFrame(out, columns=["날짜", "종가"]).sort_values("날짜")
    except Exception:
        return None


def _yf_daily(code: str, suffix: str, days: int):
    try:
        from modules.indices import fetch_history
    except Exception:
        return None
    for tk in (f"{code}{suffix}", f"{code}{'.KQ' if suffix == '.KS' else '.KS'}"):
        try:
            s = fetch_history(tk)
            ser = s["Close"] if hasattr(s, "columns") and "Close" in getattr(s, "columns", []) else s
            ser = pd.Series(ser).dropna()
            if len(ser) >= 2:
                idx = pd.to_datetime(ser.index, errors="coerce")
                df = pd.DataFrame({"날짜": idx, "종가": ser.values}).dropna()
                cut = pd.Timestamp(date.today() - timedelta(days=days + 5))
                df = df[df["날짜"] >= cut]
                if len(df) >= 2:
                    return df.sort_values("날짜")
        except Exception:
            continue
    return None


def _days_since(listed: str) -> int:
    try:
        d = datetime.strptime(str(listed), "%Y.%m.%d").date()
        return max((date.today() - d).days, 7)
    except Exception:
        return 366


# ── 미니 스파크라인 (모바일·펼침 폴백용으로 잔존) ────────────────
def _spark_svg(vals, w=66, h=26) -> str:
    vals = [float(v) for v in (vals or []) if v is not None]
    if len(vals) < 2:
        return '<span class="na">—</span>'
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    n = len(vals)
    step = (w - 4) / (n - 1)
    pts = [(2 + i * step, h - 3 - ((v - lo) / rng) * (h - 6)) for i, v in enumerate(vals)]
    col = _UP_C if vals[-1] >= vals[0] else _DOWN_C
    d = " ".join(("M" if i == 0 else "L") + f"{x:.1f} {y:.1f}" for i, (x, y) in enumerate(pts))
    area = d + f" L {pts[-1][0]:.1f} {h} L {pts[0][0]:.1f} {h} Z"
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<path d="{area}" fill="{col}" opacity="0.12"/>'
            f'<path d="{d}" fill="none" stroke="{col}" stroke-width="1.5"/></svg>')


@st.cache_data(ttl=1800)
def _live_spark(name: str, days: int):
    code, suffix = _resolve_code(name)
    if not code:
        return []
    df = _daily(code, suffix or ".KS", days)
    if df is None or df.empty:
        return []
    vals = list(df["종가"].values)
    if len(vals) <= 60:
        return [round(float(v), 2) for v in vals]
    step = (len(vals) - 1) / 59
    return [round(float(vals[round(i * step)]), 2) for i in range(60)]


def _get_spark(s: dict):
    """상장후 일별 종가(다운샘플). 엔진 저장값 우선, 없으면 라이브 1회(캐시)."""
    sp = s.get("spark") or []
    if not sp:
        sp = _live_spark(s.get("name", ""), _days_since(s.get("listed", "")))
    return sp or []


def _since_return(s: dict):
    """상장일 종가 대비 현재가 수익률(%). 공모가 파싱 실패 종목의 폴백 지표."""
    sp = _get_spark(s)
    if len(sp) < 2 or not sp[0]:
        return None
    cur = s.get("price_won") or sp[-1]
    try:
        return (float(cur) / float(sp[0]) - 1) * 100
    except (TypeError, ZeroDivisionError, ValueError):
        return None


def _peak_drawdown(s: dict):
    """(미사용 보존) 상장후 최고가 대비 낙폭(%)·최고가 — 추후 '고점比' 컬럼 후보.
    반환: (dd_pct<=0, peak_won) · 산출 불가 시 (None, None)."""
    sp = [float(v) for v in (_get_spark(s) or []) if v is not None]
    if len(sp) < 2:
        return None, None
    peak = max(sp)
    if peak <= 0:
        return None, None
    try:
        cur = float(s.get("price_won") or sp[-1])
    except (TypeError, ValueError):
        return None, None
    return (cur / peak - 1) * 100, peak


# ── 큰 차트 ────────────────────────────────────────────────────
def _ipo_chart(name: str, listed: str, mode: str):
    days = _days_since(listed) if mode == "상장후" else {"3개월": 92, "6개월": 183, "1년": 366}[mode]
    code, suffix = _resolve_code(name)
    if not code:
        st.markdown('<div class="ipo-cna">시세를 찾지 못했어요 (상장명 확인 필요).</div>', unsafe_allow_html=True)
        return
    df = _daily(code, suffix or ".KS", days)
    if df is None or df.empty:
        st.markdown('<div class="ipo-cna">차트 데이터를 불러오지 못했어요(휴장·일시 오류일 수 있어요).</div>', unsafe_allow_html=True)
        return

    lo, hi = float(df["종가"].min()), float(df["종가"].max())
    if hi <= lo:
        hi = lo + 1.0
    x_enc = alt.X("날짜:T", axis=alt.Axis(
        title=None, format="%m/%d", labelColor=_AXIS_C, grid=False,
        tickCount={"interval": "day", "step": 15},
        domain=True, domainColor=_GRID_C, ticks=True, tickColor=_GRID_C, labelAngle=0))
    y_enc = alt.Y("종가:Q", scale=alt.Scale(domain=[lo, hi], nice=False, zero=False, clamp=True),
                  axis=alt.Axis(title=None, format=",.0f", labelColor=_AXIS_C,
                                gridColor=_GRID_C, domain=True, domainColor=_GRID_C))
    tip = [alt.Tooltip("날짜:T", format="%Y-%m-%d"), alt.Tooltip("종가:Q", format=",.0f")]
    line_c = _UP_C if df["종가"].iloc[-1] >= df["종가"].iloc[0] else _DOWN_C

    df_a = df.copy()
    df_a["바닥"] = lo
    area = alt.Chart(df_a).mark_area(color=line_c, opacity=0.10).encode(
        x=x_enc, y=y_enc, y2=alt.Y2("바닥:Q"), tooltip=tip)
    line = alt.Chart(df).mark_line(color=line_c, strokeWidth=2).encode(x=x_enc, y=y_enc, tooltip=tip)
    try:
        hover = alt.selection_point(fields=["날짜"], nearest=True, on="mouseover", empty=False)
        sel = alt.Chart(df).mark_point().encode(x=x_enc, opacity=alt.value(0)).add_params(hover)
        vrule = alt.Chart(df).mark_rule(color=_AXIS_C, strokeDash=[3, 3]).encode(x=x_enc).transform_filter(hover)
        pts = alt.Chart(df).mark_point(size=60, color=line_c, filled=True).encode(
            x=x_enc, y=y_enc, opacity=alt.condition(hover, alt.value(1), alt.value(0)))
        txt = alt.Chart(df).mark_text(align="left", dx=8, dy=-10, fontSize=12, fontWeight="bold",
                                      color=line_c).encode(
            x=x_enc, y=y_enc, text=alt.condition(hover, alt.Text("종가:Q", format=",.0f"), alt.value("")))
        chart = (alt.layer(area, line, sel, vrule, pts, txt)
                 .properties(height=240, background="transparent").configure_view(strokeWidth=0))
    except Exception:
        chart = (alt.layer(area, line).properties(height=240, background="transparent")
                 .configure_view(strokeWidth=0))
    st.altair_chart(chart, use_container_width=True)


# ── 공통 포맷 헬퍼 ─────────────────────────────────────────────
def _mk_chip(market: str) -> str:
    k = "kosdaq" if "닥" in (market or "") else "kospi"
    return f'<span class="mk {k}">{"코스닥" if k == "kosdaq" else "코스피"}</span>'


def _ret_cls(v):
    return "up" if (v is not None and v >= 0) else "down"


def _ret_main(s: dict):
    """대표 수익률(%): 공모가比 우선, 없으면 상장일종가比."""
    r = s.get("ipo_return")
    if isinstance(r, (int, float)):
        return r
    return _since_return(s)


def _pct_txt(v):
    return f"{'+' if v >= 0 else ''}{v:.1f}%"


def _ret_pair(s: dict):
    """(수익률, 기준라벨, 시작가문자열). 공모가比 우선 · 상장일종가比 폴백."""
    r = s.get("ipo_return")
    if isinstance(r, (int, float)) and s.get("ipo_price"):
        return r, "공모", str(s["ipo_price"])
    sr = _since_return(s)
    if sr is not None:
        sp = _get_spark(s)
        seed = f"{int(sp[0]):,}" if sp else "–"
        return sr, "상장일", seed
    return None, "", ""


def _val_num(v, fmt, alt_txt="—"):
    """PER/PBR/PSR 셀 — 숫자면 포맷, 아니면 대체 텍스트."""
    if isinstance(v, (int, float)):
        return f"<b>{fmt.format(v)}</b>"
    return f'<span class="na">{alt_txt}</span>'


def _amt_num(v):
    """매출·이익 셀 — 엔진 포맷 문자열('1,686억'·'-95억') 그대로, 음수는 파랑."""
    t = str(v or "").strip()
    if not t:
        return '<span class="na">—</span>'
    cls = ' class="neg"' if t.startswith("-") else ""
    return f"<b{cls}>{html.escape(t)}</b>"


def _per_cell(s: dict) -> str:
    """PER: 순이익 적자면 '적자', 미수집이면 '—'."""
    if isinstance(s.get("per"), (int, float)):
        return f"<b>{s['per']:.1f}</b>"
    if str(s.get("net_income") or "").strip().startswith("-"):
        return '<span class="na">적자</span>'
    return '<span class="na">—</span>'


# ── ① 요약 스트립 ─────────────────────────────────────────────
def _sum_strip_html(recent) -> str:
    n = len(recent)
    rets = [(r, r.get("ipo_return")) for r in recent
            if isinstance(r.get("ipo_return"), (int, float))]
    items = [f'<span class="it">최근 1년 상장<b>{n}종목</b></span>']
    if rets:
        vals = [v for _, v in rets]
        avg = sum(vals) / len(vals)
        above = sum(1 for v in vals if v > 0)
        items.append(f'<span class="it">공모가比 평균<b class="{_ret_cls(avg)}">{_pct_txt(avg)}</b></span>')
        items.append(f'<span class="it">공모가 상회<b>{above} / {len(vals)}</b></span>')
        best_r, best_v = max(rets, key=lambda t: t[1])
        items.append(f'<span class="it">최고<b class="{_ret_cls(best_v)}">'
                     f'{html.escape(best_r.get("name",""))} {_pct_txt(best_v)}</b></span>')
    return f'<div class="ipo-sum">{"".join(items)}</div>'


# ── ② 이번 달 파이프라인 카드 ─────────────────────────────────
def _upcoming_card_html(u: dict) -> str:
    dday = u.get("dday", "") or "접수"
    cls = "soon" if u.get("soon") else ("tbd" if dday == "접수" else "")
    nv = (f'<a class="nv" href="{html.escape(naver_stock_url(u.get("name","")))}" '
          f'target="_blank" rel="noopener" title="네이버 증권에서 검색">N</a>')
    rows = ""
    if u.get("price"):
        rows += ('<div class="r"><span class="k">공모가(예정)</span>'
                 f'<span class="v">{html.escape(str(u["price"]))}원</span></div>')
    if u.get("sub"):
        rows += f'<div class="r"><span class="k">청약일</span><span class="v">{html.escape(u["sub"])}</span></div>'
    if u.get("pay"):
        rows += f'<div class="r"><span class="k">납입일</span><span class="v">{html.escape(u["pay"])}</span></div>'
    if u.get("under"):
        rows += f'<div class="r"><span class="k">주관</span><span class="v">{html.escape(u["under"])}</span></div>'
    soft = ""
    if not rows:                          # estkRs 폴백 — 접수 정보만
        soft = " soft"
        rows = (f'<div class="r"><span class="k">접수</span>'
                f'<span class="v">{html.escape(u.get("state",""))}</span></div>')
        if u.get("est_listing"):
            rows += (f'<div class="r"><span class="k">상장</span>'
                     f'<span class="v">{html.escape(u["est_listing"])}</span></div>')
        rows += '<div class="r"><span class="k">일정</span><span class="v na">미확정</span></div>'
    intro = str(u.get("intro") or "").strip()
    link = str(u.get("dart_url") or "").strip()
    if link:
        intro_body = html.escape(intro) + (" · " if intro else "")
        intro_body += (f'<a href="{html.escape(link)}" target="_blank" rel="noopener" '
                       'style="color:inherit;">공시↗</a>')
    else:
        intro_body = html.escape(intro)
    ds = f'<div class="ds">{intro_body}</div>' if intro_body else ""
    return (f'<div class="ipo-up{soft}"><div class="nm"><span class="t">'
            f'{html.escape(u.get("name",""))}{nv}</span>'
            f'<span class="dday {cls}">{html.escape(dday)}</span></div>'
            f'<div class="rows">{rows}</div>{ds}</div>')


def _newlisted_card_html(s: dict) -> str:
    item = _naver_item_url(s.get("code", "")) or naver_stock_url(s.get("name", ""))
    nv = f'<a class="nv" href="{html.escape(item)}" target="_blank" rel="noopener" title="네이버 증권에서 보기">N</a>'
    listed = str(s.get("listed", ""))
    mmdd = listed[5:] if len(listed) == 10 else listed
    r, base_k, seed = _ret_pair(s)
    if r is not None:
        rows = (f'<div class="r"><span class="k">{base_k}가 → 현재</span>'
                f'<span class="v">{html.escape(seed)} → {html.escape(str(s.get("price","-")))}원 '
                f'<b class="{_ret_cls(r)}">{_pct_txt(r)}</b></span></div>')
    else:
        rows = (f'<div class="r"><span class="k">현재가</span>'
                f'<span class="v">{html.escape(str(s.get("price","-")))}원</span></div>')
    rows += (f'<div class="r"><span class="k">시총</span>'
             f'<span class="v">{html.escape(str(s.get("cap","-")))}</span></div>')
    intro = str(s.get("intro") or "").strip()
    ds = f'<div class="ds">{html.escape(intro)}</div>' if intro else ""
    return (f'<div class="ipo-up"><div class="nm"><span class="t">'
            f'{html.escape(s.get("name",""))}{nv}</span>'
            f'<span class="dday new">NEW · {html.escape(mmdd)}</span></div>'
            f'<div class="rows">{rows}</div>{ds}</div>')


# ── ③ 비교 테이블 행 ──────────────────────────────────────────
def _row_html(s: dict) -> str:
    nm = html.escape(s.get("name", ""))
    sector = s.get("sector")
    sct = f'<span class="sct">{html.escape(sector)}</span>' if sector else ""
    item = _naver_item_url(s.get("code", "")) or naver_stock_url(s.get("name", ""))
    nv = f'<a class="nv" href="{html.escape(item)}" target="_blank" rel="noopener" title="네이버 증권에서 보기">N</a>'

    listed = str(s.get("listed", "-"))
    dt = f'<div class="dt">{html.escape(listed[2:] if len(listed) == 10 else listed)}</div>'
    cap = f'<div class="num"><b>{html.escape(str(s.get("cap","-")))}</b></div>'

    r, base_k, seed = _ret_pair(s)
    if r is not None:
        cur = html.escape(str(s.get("price", "-")))
        ret = (f'<div class="retcell"><span class="pct {_ret_cls(r)}">{_pct_txt(r)}</span>'
               f'<span class="base">{base_k} {html.escape(seed)} → {cur}</span></div>')
    else:
        ret = '<div class="retcell"><span class="na">—</span></div>'

    per = f'<div class="num">{_per_cell(s)}</div>'
    eper = f'<div class="num">{_val_num(s.get("est_per"), "{:.1f}")}</div>'
    pbr = f'<div class="num">{_val_num(s.get("pbr"), "{:.2f}")}</div>'
    psr = f'<div class="num">{_val_num(s.get("psr"), "{:.2f}")}</div>'
    eps = f'<div class="num">{_amt_num(s.get("eps"))}</div>'
    rev = f'<div class="num">{_amt_num(s.get("revenue"))}</div>'
    op = f'<div class="num">{_amt_num(s.get("op_income"))}</div>'
    net = f'<div class="num">{_amt_num(s.get("net_income"))}</div>'

    # 모바일 밴드 — 숨겨진 숫자 컬럼을 칩으로
    def _chip(k, body):
        return f'<span class="chip">{k}{body}</span>'
    mband = ('<div class="mband">'
             + _chip("상장", f"<b>{html.escape(listed[2:] if len(listed)==10 else listed)}</b>")
             + _chip("시총", f"<b>{html.escape(str(s.get('cap','-')))}</b>")
             + _chip("PER", _per_cell(s))
             + _chip("추정PER", _val_num(s.get("est_per"), "{:.1f}"))
             + _chip("PBR", _val_num(s.get("pbr"), "{:.2f}"))
             + _chip("PSR", _val_num(s.get("psr"), "{:.2f}"))
             + _chip("EPS", _amt_num(s.get("eps")))
             + _chip("매출", _amt_num(s.get("revenue")))
             + _chip("영업익", _amt_num(s.get("op_income")))
             + _chip("순익", _amt_num(s.get("net_income")))
             + '</div>')

    return (
        '<div class="ipo-row">'
        f'<div class="nmcell"><div class="nm"><a href="{html.escape(item)}" target="_blank" rel="noopener">{nm}</a>{nv}</div>'
        f'<div class="sub">{_mk_chip(s.get("market",""))}{sct}</div></div>'
        f'{dt}{cap}{ret}{per}{eper}{pbr}{psr}{eps}{rev}{op}{net}'
        f'{mband}'
        '</div>'
    )


# ── 정렬/필터 ──────────────────────────────────────────────────
def _apply(recent, market, sector, sort):
    out = list(recent)
    if market != "전체":
        out = [r for r in out if r.get("market") == market]
    if sector != "전체":
        out = [r for r in out if (r.get("sector") or "기타") == sector]
    if sort == "시총순":
        out.sort(key=lambda r: r.get("cap_won") or 0, reverse=True)
    elif sort == "수익률순":
        keyed = [(r, _ret_main(r)) for r in out]
        keyed.sort(key=lambda t: t[1] if t[1] is not None else -1e9, reverse=True)
        out = [r for r, _ in keyed]
    elif sort == "PER순":               # 저PER 먼저 · 적자/미수집은 뒤
        out.sort(key=lambda r: r["per"] if isinstance(r.get("per"), (int, float)) else 1e9)
    else:  # 상장일순
        out.sort(key=lambda r: r.get("listed", ""), reverse=True)
    return out


# ── 메인 렌더 ─────────────────────────────────────────────────
def render_ipo_tab():
    # 데이터를 먼저 읽어 캡션을 만든 뒤, 표준 크롬(tab_header)으로 연다.
    data = load_ipo()
    recent = data.get("recent") or []
    upcoming = data.get("upcoming") or []
    cap_txt = f"기준 {data.get('asof','')} · 최근 1년 내 상장(시총 2,000억원 이상)"
    if data.get("_sample"):
        cap_txt = "샘플 데이터 — 엔진 첫 실행 후 실데이터로 대체돼요 · " + cap_txt

    from modules.ui import tab_header
    tab_header("IPO", caption=cap_txt, css=_CSS)

    # ① 요약 스트립
    if recent:
        st.markdown(_sum_strip_html(recent), unsafe_allow_html=True)

    # ② 이번 달 IPO — 예정 + 이달 상장(구분)
    st.markdown('<div class="ipo-sec">이번 달 IPO '
                '<span class="mut">· 상장·청약 예정 + 이달 상장 신규</span></div>',
                unsafe_allow_html=True)

    st.markdown('<div class="ipo-grp"><span class="dot"></span>상장·청약 예정 '
                '<span class="mut">· DART 증권신고서 — 일정 미확정은 접수 카드</span></div>',
                unsafe_allow_html=True)
    if upcoming:
        cards = "".join(_upcoming_card_html(u) for u in upcoming)
        st.markdown(f'<div class="ipo-strip">{cards}</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="ipo-cna">확정된 향후 일정이 없어요.</div>', unsafe_allow_html=True)

    this_month = datetime.now(_KST).strftime("%Y.%m")
    new_listed = [s for s in recent if str(s.get("listed", "")).startswith(this_month)]
    st.markdown('<div class="ipo-grp new"><span class="dot"></span>이달 상장 '
                '<span class="mut">· 첫 달 집중 트래킹 — 아래 목록에도 포함</span></div>',
                unsafe_allow_html=True)
    if new_listed:
        cards = "".join(_newlisted_card_html(s) for s in new_listed)
        st.markdown(f'<div class="ipo-strip">{cards}</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="ipo-cna">이번 달 상장한 종목이 아직 없어요.</div>', unsafe_allow_html=True)

    # ③ 최근 상장 비교 테이블
    st.markdown('<div class="ipo-sec">최근 상장 종목 '
                '<span class="mut">· 수익률=공모가比(없으면 상장일比) · 펼치면 차트·회사소개 · N=네이버</span></div>',
                unsafe_allow_html=True)
    if not recent:
        st.markdown('<div class="ipo-cna">표시할 종목이 없어요.</div>', unsafe_allow_html=True)
        return

    sectors = sorted({(r.get("sector") or "기타") for r in recent})
    _SORT_SHORT = {"상장일순": "상장일", "시총순": "시총", "수익률순": "수익률", "PER순": "PER"}
    _MODE_SHORT = {"상장후": "상장후", "3개월": "3M", "6개월": "6M", "1년": "1Y"}
    c1, c2, c3, c4 = st.columns([1.0, 1.2, 1.7, 1.25])
    with c1:
        market = st.segmented_control(
            "시장", ["전체", "코스피", "코스닥"],
            default="전체", key="ipo_mkt") or "전체"
    with c2:
        sector = st.selectbox("섹터", ["전체"] + sectors, key="ipo_sct")
    with c3:
        # 정렬 옵션 개편(등락순→PER순) — 구 세션값 충돌 방지 위해 키 교체
        sort = st.segmented_control(
            "정렬", _SORTS, default="상장일순",
            format_func=lambda x: _SORT_SHORT.get(x, x), key="ipo_sort2") or "상장일순"
    with c4:
        mode = st.segmented_control(
            "차트 기간", ["상장후", "3개월", "6개월", "1년"], default="상장후",
            format_func=lambda x: _MODE_SHORT.get(x, x), key="ipo_mode") or "상장후"

    rows = _apply(recent, market, sector, sort)
    st.caption(f"{len(rows)}종목")
    if not rows:
        st.markdown('<div class="ipo-cna">조건에 맞는 종목이 없어요.</div>', unsafe_allow_html=True)
        return

    # 헤더+행 전체를 keyed 컨테이너로 감싸 스티키 헤더의 이동 범위를 테이블로 확장.
    try:
        _tbl = st.container(key="ipo_tbl")
    except TypeError:                 # 구버전 Streamlit 폴백(스코프만 생략, 동작은 정상)
        _tbl = st.container()
    with _tbl:
        st.markdown(
            '<div class="ipo-head"><span>종목 · 업종</span>'
            '<span>상장일</span><span>시총</span><span>공모가→현재</span>'
            '<span>PER</span><span>추정PER</span><span>PBR</span><span>PSR</span>'
            '<span>EPS</span>'
            '<span>매출</span><span>영업이익</span><span>순이익</span></div>',
            unsafe_allow_html=True)
        for s in rows:
            st.markdown(_row_html(s), unsafe_allow_html=True)
            with st.expander("차트·상세 보기"):
                intro = str(s.get("intro") or "").strip()
                if intro:
                    st.markdown(f'<div class="ipo-cna" style="padding:2px 4px 10px;color:var(--pill-ink,#5d6258);">'
                                f'{html.escape(intro)}</div>', unsafe_allow_html=True)
                _ipo_chart(s.get("name", ""), s.get("listed", ""), mode)

    st.caption("수익률 = 공모가 대비 현재가(공모가는 DART 파싱 · 실패 종목은 상장일 종가 대비로 폴백 표기). "
               "PER·PBR·PSR·매출·영업이익·순이익은 DART 최근 연간 기준이고 시총은 최신 스냅샷. "
               "추정PER·EPS(원)는 네이버 증권 컨센서스 — 추정치가 없는 종목은 '—'. "
               "PER '적자'는 순이익 마이너스, '—'는 미수집. 정렬은 상단 필 바(PER은 낮은 순). "
               "향후 일정의 공모가(예정)·청약·납입·주관은 DART 증권신고서 주요정보 기준 — "
               "정정신고로 바뀔 수 있어요. 큰 차트=네이버 일별(약 15분 지연). N 아이콘·종목명=네이버 증권.")
