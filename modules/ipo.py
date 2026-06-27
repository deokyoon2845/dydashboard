"""[뷰어] 증시 › IPO 탭 (A안 · 컴팩트 리스트).

구성
  ① 향후 IPO 일정 : D-day 스트립 — 회사소개 + 상장 예상구간(추정)
  ② 최근 상장 종목 : 한 종목 = 한 행(컴팩트 리스트)
        행에 항상: 종목명·시장칩 · 상장일 · 시총 · 등락 · 보호예수 · 추이(상장후 전체 미니 스파크라인)
        아래 '차트·상세 보기' 펼침 → 큰 차트 + 상장 개요 + 회사소개

추이 미니 스파크라인
  · 상장일~수집일 일별 종가를 엔진이 다운샘플(spark)로 저장 → 즉시 렌더(네트워크 0)
  · 저장값이 없으면 뷰어가 라이브(네이버 siseJson, 상장일~오늘)로 1회 산출(캐시)

큰 차트(펼침)
  · 기간 라디오: 상장후(기본)/3개월/6개월/1년 — 종목별 상장일 기준
  · 면적+선 + 마우스 십자선 · 가로축 보름(15일) 눈금 · 세로축 최솟값~최댓값 꽉차게

데이터
  · 종목 목록·메타·spark : Supabase ipo_snapshots(엔진 적재). 없으면 임베드 샘플 폴백
  · 큰 차트 시세 : 뷰어 직접 — 네이버 자동완성(코드해석)+siseJson(일별), 실패 시 yfinance
  · 종목명 클릭 : 네이버 시세 검색

※ 상장방식·밸류(공모가/PER) 칩은 제외(2025.06 결정 — 금융위 API에 소스 없음).
"""

import html
import json
from datetime import date, datetime, timedelta

import altair as alt
import pandas as pd
import requests
import streamlit as st

from modules.stocks import naver_stock_url

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
_UP_C, _DOWN_C = "#B65F5A", "#5A7CA0"
_AXIS_C, _GRID_C = "#9a9b92", "#ECEDE7"

# ── 임베드 샘플 (DB 미구성 시 폴백 · 전부 예시) ──────────────────
_SAMPLE = {
    "asof": "샘플",
    "recent": [
        {"name": "시프트업", "code": "462870", "market": "코스피", "listed": "2024.07.11",
         "cap": "3.2조", "pct": 1.8, "lockup": "미해제 2건 · 최근 해제 2025.01.11",
         "intro": "서브컬처 게임 ‘니케’·‘스텔라 블레이드’ 개발사. 높은 영업이익률이 강점.",
         "spark": [60000, 62500, 58000, 55500, 57800, 61200, 63400, 60100, 59000, 61800]},
        {"name": "더본코리아", "code": "475560", "market": "코스피", "listed": "2024.11.06",
         "cap": "4,800억", "pct": 0.9, "lockup": "미해제 1건 · 최근 해제 2025.05.06",
         "intro": "빽다방·홍콩반점 등 외식 브랜드 운영. 가맹 확장과 소스·HMR 유통이 축.",
         "spark": [34000, 41000, 38500, 36000, 39200, 42100, 40500, 41800]},
        {"name": "셀비온", "code": "308430", "market": "코스닥", "listed": "2024.10.21",
         "cap": "2,600억", "pct": 2.0, "lockup": "미해제 4건 · 최근 해제 2025.04.21",
         "intro": "방사성 동위원소 기반 항암 치료제 개발. 전립선암 치료제가 핵심 파이프라인.",
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
  color:var(--sage-deep,#7E9A83);margin:26px 0 12px;display:flex;align-items:center;gap:8px;}
.ipo-sec:before{content:"";width:14px;height:2px;background:var(--sage,#A7BBA9);border-radius:2px;}
.ipo-sec .mut{font-weight:600;font-size:11px;text-transform:none;letter-spacing:0;color:var(--muted,#9a9b92);}
/* 향후 일정 스트립 */
.ipo-strip{display:flex;gap:10px;overflow-x:auto;padding:2px 2px 10px;}
.ipo-strip::-webkit-scrollbar{height:5px;} .ipo-strip::-webkit-scrollbar-thumb{background:var(--line,#ECEDE7);border-radius:5px;}
.ipo-up{flex:0 0 auto;min-width:198px;max-width:230px;background:var(--summary-bg,#F6F7F2);
  border:1px solid var(--line,#ECEDE7);border-radius:12px;padding:11px 13px;}
.ipo-up .nm{font-size:13px;font-weight:800;display:flex;justify-content:space-between;gap:8px;align-items:center;}
.ipo-up .sub{font-size:10.5px;color:var(--muted,#9a9b92);margin-top:5px;line-height:1.5;}
.ipo-up .ds{font-size:11px;color:var(--pill-ink,#5d6258);margin-top:7px;line-height:1.5;word-break:keep-all;
  border-top:1px dashed var(--line,#ECEDE7);padding-top:6px;}
.ipo-up .est{font-size:10.5px;color:var(--sage-deep,#7E9A83);font-weight:700;margin-top:6px;}
.dday{font-size:10.5px;font-weight:800;color:#fff;background:var(--sage-deep,#7E9A83);
  padding:3px 8px;border-radius:6px;flex:none;}
.dday.soon{background:#C2410C;}
.dday.tbd{background:#B7BCB3;}
/* 최근 상장 — 컴팩트 리스트 행 */
.ipo-row{background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);border-radius:11px;
  padding:11px 14px;display:grid;grid-template-columns:1.8fr .9fr .8fr 1.15fr 70px;
  gap:10px;align-items:center;margin-bottom:-6px;}
.ipo-row .nm{font-size:14px;font-weight:800;line-height:1.25;}
.ipo-row .nm a{color:var(--ink,#34352f);text-decoration:none;}
.ipo-row .nm a:hover{text-decoration:underline;}
.ipo-row .nm .meta{font-size:10.5px;font-weight:600;color:var(--muted,#9a9b92);margin-top:2px;
  display:flex;align-items:center;gap:5px;}
.ipo-row .dt{font-size:12px;color:var(--pill-ink,#5d6258);font-weight:600;}
.ipo-row .cap{font-size:13.5px;font-weight:800;text-align:right;white-space:nowrap;}
.ipo-row .cap .d{font-size:11px;font-weight:700;margin-left:4px;}
.ipo-row .lk{text-align:right;}
.ipo-row .sp{text-align:right;line-height:0;}
.mk{font-size:10px;font-weight:700;padding:1px 6px;border-radius:5px;}
.mk.kospi{background:#EBF1F5;color:#3E6488;}
.mk.kosdaq{background:#F0E9F3;color:#6B4A7C;}
.lock-chip{font-size:10px;font-weight:700;padding:2px 7px;border-radius:6px;white-space:nowrap;
  background:#F3EEE6;color:#7C5F2C;}
.lk .na{font-size:11px;color:var(--muted,#9a9b92);}
.sp .na{font-size:11px;color:var(--muted,#9a9b92);}
.up{color:var(--up,#B65F5A);} .down{color:var(--down,#5A7CA0);}
/* 펼침 안 상세 메타 */
.ipo-meta{display:grid;grid-template-columns:auto 1fr;gap:6px 12px;font-size:12.5px;align-items:baseline;margin-top:2px;}
.ipo-meta .k{color:var(--muted,#9a9b92);font-weight:600;white-space:nowrap;}
.ipo-meta .v{font-weight:700;color:var(--ink,#34352f);}
.ipo-intro{font-size:12px;color:var(--pill-ink,#5d6258);line-height:1.6;margin-top:11px;
  background:var(--summary-bg,#F6F7F2);border:1px solid var(--line,#ECEDE7);border-radius:9px;padding:9px 11px;word-break:keep-all;}
.ipo-cna{font-size:12px;color:var(--muted,#9a9b92);padding:16px 2px;}
@media(max-width:680px){
  .ipo-row{grid-template-columns:1.6fr 1fr 64px;}
  .ipo-row .dt,.ipo-row .lk{display:none;}
}
</style>
"""


# ── DB 로드 (없으면 샘플) ──────────────────────────────────────
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


# ── 종목명 → (코드, yfinance 접미사) : 네이버 자동완성 ──────────
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


# ── 일별 시세 : 네이버 siseJson 우선 → yfinance 폴백 ────────────
@st.cache_data(ttl=900)
def _daily(code: str, suffix: str, days: int):
    """반환 DataFrame(columns=['날짜','종가']) 또는 None."""
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


# ── 상장일 → 경과일수 ──
def _days_since(listed: str) -> int:
    try:
        d = datetime.strptime(str(listed), "%Y.%m.%d").date()
        return max((date.today() - d).days, 7)
    except Exception:
        return 366


# ── 미니 스파크라인 SVG (저장 spark 우선, 없으면 라이브) ──
def _spark_svg(vals, w=66, h=26) -> str:
    vals = [float(v) for v in (vals or []) if v is not None]
    if len(vals) < 2:
        return '<span class="na">—</span>'
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    n = len(vals)
    step = (w - 4) / (n - 1)
    pts = [(2 + i * step, h - 3 - ((v - lo) / rng) * (h - 6)) for i, v in enumerate(vals)]
    up = vals[-1] >= vals[0]
    col = _UP_C if up else _DOWN_C
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


def _row_spark(s: dict) -> str:
    spark = s.get("spark") or []
    if not spark:                       # 저장값 없으면 라이브 1회(캐시)
        spark = _live_spark(s.get("name", ""), _days_since(s.get("listed", "")))
    return _spark_svg(spark)


# ── 큰 차트 (펼침) : 보름 x · 꽉찬 y ───────────────────────────
def _ipo_chart(name: str, listed: str, mode: str):
    days = _days_since(listed) if mode == "상장후" else {"3개월": 92, "6개월": 183, "1년": 366}[mode]
    code, suffix = _resolve_code(name)
    if not code:
        st.markdown('<div class="ipo-cna">시세를 찾지 못했어요 (상장명 확인 필요).</div>',
                    unsafe_allow_html=True)
        return
    df = _daily(code, suffix or ".KS", days)
    if df is None or df.empty:
        st.markdown('<div class="ipo-cna">차트 데이터를 불러오지 못했어요(휴장·일시 오류일 수 있어요).</div>',
                    unsafe_allow_html=True)
        return

    lo, hi = float(df["종가"].min()), float(df["종가"].max())
    if hi <= lo:
        hi = lo + 1.0

    x_enc = alt.X("날짜:T", axis=alt.Axis(
        title=None, format="%m/%d", labelColor=_AXIS_C, grid=False,
        tickCount={"interval": "day", "step": 15},
        domain=True, domainColor=_GRID_C, ticks=True, tickColor=_GRID_C, labelAngle=0))
    y_enc = alt.Y("종가:Q", scale=alt.Scale(
        domain=[lo, hi], nice=False, zero=False, clamp=True),
        axis=alt.Axis(title=None, format=",.0f", labelColor=_AXIS_C,
                      gridColor=_GRID_C, domain=True, domainColor=_GRID_C))
    tip = [alt.Tooltip("날짜:T", format="%Y-%m-%d"), alt.Tooltip("종가:Q", format=",.0f")]

    up = df["종가"].iloc[-1] >= df["종가"].iloc[0]
    line_c = _UP_C if up else _DOWN_C

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
        txt = alt.Chart(df).mark_text(align="left", dx=8, dy=-10, fontSize=12,
                                      fontWeight="bold", color=line_c).encode(
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
    t = "코스닥" if k == "kosdaq" else "코스피"
    return f'<span class="mk {k}">{t}</span>'


def _row_html(s: dict) -> str:
    pct = s.get("pct")
    pct_html = ""
    if isinstance(pct, (int, float)):
        cls = "up" if pct >= 0 else "down"
        pct_html = f'<span class="d {cls}">{"+" if pct >= 0 else ""}{pct:.1f}%</span>'
    nm = html.escape(s.get("name", ""))
    link = html.escape(naver_stock_url(s.get("name", "")))
    lock = s.get("lockup")
    lock_html = (f'<span class="lock-chip">🔒 {html.escape(_short_lock(lock))}</span>'
                 if lock else '<span class="na">—</span>')
    return (
        '<div class="ipo-row">'
        f'<div class="nm"><a href="{link}" target="_blank" rel="noopener">{nm}</a>'
        f'<div class="meta">{_mk_chip(s.get("market",""))}</div></div>'
        f'<div class="dt">{html.escape(str(s.get("listed","-")))}</div>'
        f'<div class="cap">{html.escape(str(s.get("cap","-")))}{pct_html}</div>'
        f'<div class="lk">{lock_html}</div>'
        f'<div class="sp">{_row_spark(s)}</div>'
        '</div>'
    )


def _short_lock(lock: str) -> str:
    for tok in str(lock).replace(" ", "").split("·"):
        if "미해제" in tok:
            return tok
    return (str(lock)[:12] + "…") if len(str(lock)) > 13 else str(lock)


# ── 메인 렌더 ─────────────────────────────────────────────────
def render_ipo_tab():
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown('<div class="ipo-bar"></div>', unsafe_allow_html=True)
    st.title("IPO")

    data = load_ipo()
    recent = data.get("recent") or []
    upcoming = data.get("upcoming") or []
    asof = data.get("asof", "")
    cap_txt = f"기준 {asof} · 최근 2년 내 상장(시총 5,000억원 이상) · 최신순"
    if data.get("_sample"):
        cap_txt = "샘플 데이터 — 엔진(ipo_run) 첫 실행 후 실데이터로 대체돼요 · " + cap_txt
    st.caption(cap_txt)

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
            cards += (
                '<div class="ipo-up"><div class="nm">'
                f'{html.escape(u.get("name",""))}<span class="dday {cls}">{html.escape(dday)}</span></div>'
                f'<div class="sub">{html.escape(sub)}</div>'
                f'<div class="ds">{html.escape(u.get("intro",""))}</div>'
                + (f'<div class="est">📅 상장 {html.escape(est)}</div>' if est else "")
                + '</div>'
            )
        st.markdown(f'<div class="ipo-strip">{cards}</div>', unsafe_allow_html=True)
    else:
        st.caption("확정된 향후 일정이 없어요.")

    # ② 최근 상장 종목
    st.markdown('<div class="ipo-sec">최근 상장 종목 '
                '<span class="mut">· 추이=상장후 전체 · ‘차트·상세 보기’로 큰 차트가 펼쳐져요</span></div>',
                unsafe_allow_html=True)
    if not recent:
        st.markdown('<div class="ipo-cna">표시할 종목이 없어요.</div>', unsafe_allow_html=True)
        return

    mode = st.radio("차트 기간", ["상장후", "3개월", "6개월", "1년"], index=0, horizontal=True,
                    key="ipo_mode", label_visibility="collapsed")

    for s in recent:
        st.markdown(_row_html(s), unsafe_allow_html=True)
        with st.expander("차트·상세 보기"):
            _ipo_chart(s.get("name", ""), s.get("listed", ""), mode)
            meta = (
                '<div class="ipo-meta">'
                f'<span class="k">상장일</span><span class="v">{html.escape(str(s.get("listed","-")))}</span>'
                f'<span class="k">시가총액</span><span class="v">{html.escape(str(s.get("cap","-")))}</span>'
                f'<span class="k">보호예수</span><span class="v">{html.escape(str(s.get("lockup","-") or "-"))}</span>'
                '</div>'
                f'<div class="ipo-intro">{html.escape(str(s.get("intro","") or "회사소개 정보가 아직 없어요."))}</div>'
            )
            st.markdown(meta, unsafe_allow_html=True)

    st.caption("미니 추이: 상장일~수집일 일별 종가(엔진 저장, 없으면 라이브). "
               "큰 차트: 네이버 siseJson(일별, 약 15분 지연)·면적+선·십자선·보름 눈금·꽉찬 세로축. "
               "종목명 클릭=네이버 시세.")
