"""[뷰어] 증시 › IPO 탭 (A안 · 컴팩트 리스트 + 필터/정렬).

구성
  ① 향후 IPO 일정 : D-day 스트립 — 회사소개 + 상장 예상구간(추정) + N(네이버) 아이콘
  ② 필터/정렬 바  : 시장(전체/코스피/코스닥) · 섹터 · 정렬(상장일/시총/등락/상장후수익률)
  ③ 최근 상장 종목 : 한 종목 = 한 행
        행에 항상: 종목·시장·섹터·N아이콘 · 상장일 · 현재가(+상장일比) · 현재시총(+PER) · 추이
        펼치면: PER·PBR·PSR · 매출·영업이익·당기순이익 · 상장일종가↔현재 · 섹터·보호예수 · 회사소개 · 큰 차트

상장일比 = 상장 첫날 종가 대비 현재가 수익률(공모가는 무료 API 부재로 대체 지표).
추이 스파크라인 = 상장후 전체(엔진 저장 spark 우선, 없으면 라이브 1회 폴백).
큰 차트 = 네이버 siseJson(일별) · 면적+선 · 십자선 · 보름 눈금 · 꽉찬 세로축.

데이터
  · 목록·메타·spark·재무·밸류 : Supabase ipo_snapshots(엔진). 없으면 임베드 샘플 폴백
  · N 아이콘 : 네이버 증권 종목페이지(finance.naver.com/item)
  · 큰 차트 시세 : 뷰어 직접 — 네이버 siseJson, 실패 시 yfinance
"""

import html
import json
from datetime import date, datetime, timedelta

import altair as alt
import pandas as pd
import requests
import streamlit as st

from modules.stocks import naver_stock_url
from modules.ui import tab_header

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
_UP_C, _DOWN_C = "#B65F5A", "#5A7CA0"
_AXIS_C, _GRID_C = "#9a9b92", "#ECEDE7"

# ── 임베드 샘플 (DB 미구성 시 폴백 · 전부 예시) ──────────────────
_SAMPLE = {
    "asof": "샘플",
    "recent": [
        {"name": "시프트업", "code": "462870", "market": "코스피", "sector": "소프트웨어·IT서비스",
         "listed": "2024.07.11", "cap": "3.2조", "cap_won": 3.2e12,
         "price": "62,400", "price_won": 62400, "pct": 1.8,
         "revenue": "1,686억", "op_income": "1,110억", "net_income": "846억",
         "per": 38.5, "pbr": 12.1, "psr": 19.0,
         "lockup": "미해제 2건 · 최근 해제 2025.01.11",
         "intro": "서브컬처 게임 ‘니케’·‘스텔라 블레이드’ 개발사.",
         "spark": [60000, 62500, 58000, 55500, 57800, 61200, 63400, 60100, 59000, 62400]},
        {"name": "더본코리아", "code": "475560", "market": "코스피", "sector": "숙박·음식",
         "listed": "2024.11.06", "cap": "5,400억", "cap_won": 5.4e11,
         "price": "38,200", "price_won": 38200, "pct": 0.9,
         "revenue": "4,107억", "op_income": "409억", "net_income": "327억",
         "per": 16.5, "pbr": 3.4, "psr": 1.3,
         "lockup": "미해제 1건 · 최근 해제 2025.05.06",
         "intro": "빽다방·홍콩반점 등 외식 브랜드 운영.",
         "spark": [34000, 41000, 38500, 36000, 39200, 42100, 40500, 38200]},
        {"name": "셀비온", "code": "308430", "market": "코스닥", "sector": "제약·바이오",
         "listed": "2024.10.21", "cap": "2,600억", "cap_won": 2.6e11,
         "price": "13,900", "price_won": 13900, "pct": 2.0,
         "revenue": "12억", "op_income": "-95억", "net_income": "-88억",
         "per": None, "pbr": 8.7, "psr": 216.7,
         "lockup": "미해제 4건 · 최근 해제 2025.04.21",
         "intro": "방사성 동위원소 기반 항암 치료제 개발.",
         "spark": [13000, 14200, 12500, 11800, 12900, 13600, 14100, 13900]},
    ],
    "upcoming": [
        {"name": "○○바이오", "dday": "D-3", "state": "청약 06.29~30", "under": "한국투자증권",
         "est_listing": "07.12~07.26 예상", "soon": True,
         "intro": "항암 신약 타깃 단백질 분해(TPD) 플랫폼. 코스닥 예정."},
        {"name": "◇◇소프트", "dday": "접수", "state": "증권신고서 접수 06.18", "under": "삼성증권",
         "est_listing": "07.16~07.30 예상", "soon": False,
         "intro": "기업용 생성형 AI 에이전트 플랫폼. 코스닥 기술특례."},
    ],
}

_CSS = """
<style>
.ipo-bar{height:3px;width:30px;background:var(--sage,#A7BBA9);border-radius:3px;margin:0 0 12px;}
.ipo-sec{font-size:13px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;
  color:var(--sage-deep,#7E9A83);margin:24px 0 12px;display:flex;align-items:center;gap:8px;}
.ipo-sec:before{content:"";width:14px;height:2px;background:var(--sage,#A7BBA9);border-radius:2px;}
.ipo-sec .mut{font-weight:600;font-size:11px;text-transform:none;letter-spacing:0;color:var(--muted,#9a9b92);}
/* 향후 일정 스트립 */
.ipo-strip{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;padding:2px 2px 10px;}
.ipo-strip::-webkit-scrollbar{height:5px;} .ipo-strip::-webkit-scrollbar-thumb{background:var(--line,#ECEDE7);border-radius:5px;}
.ipo-up{min-width:0;background:var(--summary-bg,#F6F7F2);
  border:1px solid var(--line,#ECEDE7);border-radius:12px;padding:11px 13px;}
.ipo-up .nm{font-size:13px;font-weight:800;display:flex;justify-content:space-between;gap:8px;align-items:center;}
.ipo-up .sub{font-size:10.5px;color:var(--muted,#9a9b92);margin-top:5px;line-height:1.5;}
.ipo-up .ds{font-size:11px;color:var(--pill-ink,#5d6258);margin-top:7px;line-height:1.5;word-break:keep-all;
  border-top:1px dashed var(--line,#ECEDE7);padding-top:6px;}
.ipo-up .est{font-size:10.5px;color:var(--sage-deep,#7E9A83);font-weight:700;margin-top:6px;}
.dday{font-size:10.5px;font-weight:800;color:#fff;background:var(--sage-deep,#7E9A83);
  padding:3px 8px;border-radius:6px;flex:none;}
.dday.soon{background:#C2410C;} .dday.tbd{background:#B7BCB3;}
/* 최근 상장 — 컴팩트 리스트 행 */
.ipo-row{background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);border-radius:11px;
  padding:10px 14px;display:grid;grid-template-columns:1.7fr .82fr 1.25fr 1.25fr 66px;
  gap:10px;align-items:center;margin-bottom:-6px;}
.ipo-row .nm{font-size:14px;font-weight:800;line-height:1.25;}
.ipo-row .nm a{color:var(--ink,#34352f);text-decoration:none;}
.ipo-row .nm a:hover{text-decoration:underline;}
.ipo-row .nm .meta{font-size:10px;font-weight:700;color:var(--muted,#9a9b92);margin-top:3px;
  display:flex;align-items:center;gap:5px;flex-wrap:wrap;}
.ipo-row .dt{font-size:12px;color:var(--pill-ink,#5d6258);font-weight:600;}
.cmp{text-align:right;line-height:1.3;}
.cmp .now{font-size:13.5px;font-weight:800;}
.cmp .now small{font-size:10px;font-weight:600;color:var(--muted,#9a9b92);margin-left:2px;}
.cmp .was{font-size:10.5px;font-weight:600;color:var(--muted,#9a9b92);margin-top:1px;}
.cmp .was b{font-weight:800;}
.ipo-row .sp{text-align:right;line-height:0;}
.mk{font-size:10px;font-weight:700;padding:1px 6px;border-radius:5px;}
.mk.kospi{background:#EBF1F5;color:#3E6488;} .mk.kosdaq{background:#F0E9F3;color:#6B4A7C;}
.sct{font-size:10px;font-weight:700;padding:1px 6px;border-radius:5px;
  background:#EDF1EA;color:#5C7060;}
.nv{display:inline-flex;align-items:center;justify-content:center;width:15px;height:15px;
  border-radius:4px;background:#03C75A;color:#fff;font-size:10px;font-weight:900;
  text-decoration:none;margin-left:5px;vertical-align:1px;line-height:1;}
.nv:hover{filter:brightness(.92);}
.up{color:var(--up,#B65F5A);} .down{color:var(--down,#5A7CA0);}
.sp .na{font-size:11px;color:var(--muted,#9a9b92);}
/* 펼침 상세 */
.ipo-cmp2{display:grid;grid-template-columns:auto auto 1fr;gap:7px 14px;align-items:baseline;
  font-size:13px;margin:2px 0 2px;}
.ipo-cmp2 .k{color:var(--muted,#9a9b92);font-weight:700;white-space:nowrap;}
.ipo-cmp2 .pair{font-weight:700;}
.ipo-cmp2 .pair .arw{color:var(--muted,#9a9b92);margin:0 6px;}
.ipo-cmp2 .ret{font-weight:800;}
.ipo-meta{display:grid;grid-template-columns:auto 1fr;gap:6px 12px;font-size:12.5px;align-items:baseline;margin-top:8px;}
.ipo-mx{display:flex;flex-wrap:wrap;gap:7px;margin:9px 0 2px;}
.ipo-mx .cell{flex:1 1 76px;background:var(--summary-bg,#F6F7F2);border:1px solid var(--line,#ECEDE7);
  border-radius:8px;padding:6px 9px;text-align:center;}
.ipo-mx .cell .k{font-size:10px;font-weight:700;color:var(--muted,#9a9b92);}
.ipo-mx .cell .v{font-size:13.5px;font-weight:800;margin-top:2px;}
.ipo-mx .cell .v.na{color:var(--muted,#9a9b92);font-weight:700;}
.ipo-meta .k{color:var(--muted,#9a9b92);font-weight:600;white-space:nowrap;}
.ipo-meta .v{font-weight:700;color:var(--ink,#34352f);}
.ipo-intro{font-size:12px;color:var(--pill-ink,#5d6258);line-height:1.6;margin-top:11px;
  background:var(--summary-bg,#F6F7F2);border:1px solid var(--line,#ECEDE7);border-radius:9px;padding:9px 11px;word-break:keep-all;}
.ipo-cna{font-size:12px;color:var(--muted,#9a9b92);padding:14px 2px;}
@media(max-width:680px){
  .ipo-row{grid-template-columns:1.6fr 1.2fr 1.2fr 58px;}
  .ipo-row .dt{display:none;}
}
</style>
"""

_SORTS = ["상장일순", "시총순", "등락순", "상장후수익률순"]


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


# ── 미니 스파크라인 ────────────────────────────────────────────
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
    """상장일 종가 대비 현재가 수익률(%). 공모가 무료소스 부재로 이 지표로 대체."""
    sp = _get_spark(s)
    if len(sp) < 2 or not sp[0]:
        return None
    cur = s.get("price_won") or sp[-1]
    try:
        return (float(cur) / float(sp[0]) - 1) * 100
    except (TypeError, ZeroDivisionError, ValueError):
        return None


def _row_spark(s: dict) -> str:
    return _spark_svg(_get_spark(s))


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


# ── 행 HTML ────────────────────────────────────────────────────
def _mk_chip(market: str) -> str:
    k = "kosdaq" if "닥" in (market or "") else "kospi"
    return f'<span class="mk {k}">{"코스닥" if k == "kosdaq" else "코스피"}</span>'


def _ret_cls(v):
    return "up" if (v is not None and v >= 0) else "down"


def _price_cell(s: dict) -> str:
    """현재가(상단) + 상장일 종가 대비 수익률(하단)."""
    now = f'<div class="now">{html.escape(str(s.get("price", "-")))}<small>원</small></div>'
    sr = _since_return(s)
    if sr is not None:
        was = f'<div class="was">상장일比 <b class="{_ret_cls(sr)}">{"+" if sr >= 0 else ""}{sr:.1f}%</b></div>'
    else:
        pct = s.get("pct")
        was = (f'<div class="was">전일 <b class="{_ret_cls(pct)}">{"+" if pct >= 0 else ""}{pct:.1f}%</b></div>'
               if isinstance(pct, (int, float)) else '<div class="was">—</div>')
    return f'<div class="cmp">{now}{was}</div>'


def _cap_cell(s: dict) -> str:
    now = f'<div class="now">{html.escape(str(s.get("cap", "-")))}</div>'
    per = s.get("per")
    was = (f'<div class="was">PER {per:.1f}</div>' if isinstance(per, (int, float))
           else '<div class="was">현재시총</div>')
    return f'<div class="cmp">{now}{was}</div>'


def _row_html(s: dict) -> str:
    nm = html.escape(s.get("name", ""))
    sector = s.get("sector")
    sct = f'<span class="sct">{html.escape(sector)}</span>' if sector else ""
    item = _naver_item_url(s.get("code", "")) or naver_stock_url(s.get("name", ""))
    nv = f'<a class="nv" href="{html.escape(item)}" target="_blank" rel="noopener" title="네이버 증권에서 보기">N</a>'
    return (
        '<div class="ipo-row">'
        f'<div class="nm"><a href="{html.escape(item)}" target="_blank" rel="noopener">{nm}</a>{nv}'
        f'<div class="meta">{_mk_chip(s.get("market",""))}{sct}</div></div>'
        f'<div class="dt">{html.escape(str(s.get("listed","-")))}</div>'
        f'{_price_cell(s)}{_cap_cell(s)}'
        f'<div class="sp">{_row_spark(s)}</div>'
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
    elif sort == "등락순":
        out.sort(key=lambda r: r["pct"] if isinstance(r.get("pct"), (int, float)) else -1e9, reverse=True)
    elif sort == "상장후수익률순":
        keyed = [(r, _since_return(r)) for r in out]
        keyed.sort(key=lambda t: t[1] if t[1] is not None else -1e9, reverse=True)
        out = [r for r, _ in keyed]
    else:  # 상장일순
        out.sort(key=lambda r: r.get("listed", ""), reverse=True)
    return out


# ── 메인 렌더 ─────────────────────────────────────────────────
def render_ipo_tab():
    data = load_ipo()
    recent = data.get("recent") or []
    upcoming = data.get("upcoming") or []
    cap_txt = f"기준 {data.get('asof','')} · 최근 2년 내 상장(시총 5,000억원 이상)"
    if data.get("_sample"):
        cap_txt = "샘플 데이터 — 엔진 첫 실행 후 실데이터로 대체돼요 · " + cap_txt

    # 초록 바 + 제목 + 캡션(다른 탭과 동일 배치). 탭 CSS는 바와 한 블록으로 합침.
    tab_header("IPO", caption=cap_txt, css=_CSS)

    # ① 향후 IPO 일정
    st.markdown('<div class="ipo-sec">향후 IPO 일정 '
                '<span class="mut">· 회사소개 · 상장 예상구간은 접수일 기준 추정</span></div>',
                unsafe_allow_html=True)
    if upcoming:
        cards = ""
        for u in upcoming:
            dday = u.get("dday", "") or "접수"
            cls = "soon" if u.get("soon") else ("tbd" if dday == "접수" else "")
            sub = " · ".join(x for x in [u.get("state", ""), u.get("under", "")] if x)
            est = u.get("est_listing", "")
            nv = (f'<a class="nv" href="{html.escape(naver_stock_url(u.get("name","")))}" '
                  f'target="_blank" rel="noopener" title="네이버 증권에서 검색">N</a>')
            cards += (
                '<div class="ipo-up"><div class="nm">'
                f'<span>{html.escape(u.get("name",""))}{nv}</span>'
                f'<span class="dday {cls}">{html.escape(dday)}</span></div>'
                f'<div class="sub">{html.escape(sub)}</div>'
                f'<div class="ds">{html.escape(u.get("intro",""))}</div>'
                + (f'<div class="est">📅 상장 {html.escape(est)}</div>' if est else "")
                + '</div>'
            )
        st.markdown(f'<div class="ipo-strip">{cards}</div>', unsafe_allow_html=True)
    else:
        st.caption("확정된 향후 일정이 없어요.")

    # ② 최근 상장 — 필터/정렬
    st.markdown('<div class="ipo-sec">최근 상장 종목 '
                '<span class="mut">· 현재가 옆 상장일比=상장일 종가 대비 · 추이=상장후 전체 · N=네이버</span></div>',
                unsafe_allow_html=True)
    if not recent:
        st.markdown('<div class="ipo-cna">표시할 종목이 없어요.</div>', unsafe_allow_html=True)
        return

    sectors = sorted({(r.get("sector") or "기타") for r in recent})
    c1, c2, c3, c4 = st.columns([1.25, 1.2, 1.35, 1.1])
    market = c1.radio("시장", ["전체", "코스피", "코스닥"], horizontal=True, key="ipo_mkt")
    sector = c2.selectbox("섹터", ["전체"] + sectors, key="ipo_sct")
    sort = c3.radio("정렬", _SORTS, horizontal=True, key="ipo_sort")
    mode = c4.radio("차트 기간", ["상장후", "3개월", "6개월", "1년"], key="ipo_mode")

    rows = _apply(recent, market, sector, sort)
    st.caption(f"{len(rows)}종목")
    if not rows:
        st.markdown('<div class="ipo-cna">조건에 맞는 종목이 없어요.</div>', unsafe_allow_html=True)
        return

    for s in rows:
        st.markdown(_row_html(s), unsafe_allow_html=True)
        with st.expander("차트·상세 보기"):
            _ipo_chart(s.get("name", ""), s.get("listed", ""), mode)
            st.markdown(_detail_html(s), unsafe_allow_html=True)

    st.caption("현재가 옆 ‘상장일比’=상장 첫날 종가 대비 · 시총 옆 PER. 펼치면 PER·PBR·PSR과 매출·영업이익·당기순이익(DART 최근 연간). "
               "추이=상장후 전체. 큰 차트=네이버 일별(약 15분 지연). N 아이콘·종목명=네이버 증권. 공모가·회사소개는 무료 소스 부재로 미표시.")


def _detail_html(s: dict) -> str:
    sr = _since_return(s)
    sp = _get_spark(s)
    base_close = f"{int(sp[0]):,}원" if sp else "–"
    ret_html = (f'<span class="ret {_ret_cls(sr)}">{"+" if sr >= 0 else ""}{sr:.1f}%</span>'
                if sr is not None else "<span></span>")
    price_pair = (f'<span class="pair">{base_close}'
                  f'<span class="arw">→</span>{html.escape(str(s.get("price","-")))}원</span>')

    def _num(v, fmt):
        return f'<div class="v">{fmt.format(v)}</div>' if isinstance(v, (int, float)) else '<div class="v na">적자·N/A</div>'

    def _amt(v):
        v = str(v or "")
        cls = "v"
        if v.startswith("-"):
            cls = "v"  # 적자도 검정 유지(라벨로 구분); 색 강조는 생략
        return f'<div class="{cls}">{html.escape(v) if v else "–"}</div>'

    valuation = (
        '<div class="ipo-mx">'
        f'<div class="cell"><div class="k">PER</div>{_num(s.get("per"), "{:.1f}")}</div>'
        f'<div class="cell"><div class="k">PBR</div>{_num(s.get("pbr"), "{:.2f}")}</div>'
        f'<div class="cell"><div class="k">PSR</div>{_num(s.get("psr"), "{:.2f}")}</div>'
        '</div>'
    )
    financials = (
        '<div class="ipo-mx">'
        f'<div class="cell"><div class="k">매출액</div>{_amt(s.get("revenue"))}</div>'
        f'<div class="cell"><div class="k">영업이익</div>{_amt(s.get("op_income"))}</div>'
        f'<div class="cell"><div class="k">당기순이익</div>{_amt(s.get("net_income"))}</div>'
        '</div>'
    )
    return (
        valuation + financials +
        '<div class="ipo-cmp2">'
        f'<span class="k">상장일종가→현재</span>{price_pair}{ret_html}'
        '</div>'
        '<div class="ipo-meta">'
        f'<span class="k">상장일</span><span class="v">{html.escape(str(s.get("listed","-")))}</span>'
        f'<span class="k">섹터</span><span class="v">{html.escape(str(s.get("sector") or "-"))}</span>'
        f'<span class="k">보호예수</span><span class="v">{html.escape(str(s.get("lockup") or "-"))}</span>'
        '</div>'
        f'<div class="ipo-intro">{html.escape(str(s.get("intro") or "회사소개 정보가 아직 없어요."))}</div>'
    )
