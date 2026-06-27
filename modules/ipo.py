"""[뷰어] 증시 › IPO 탭 (C안 · 대시보드 그리드).

구성
  ① 향후 IPO 일정 : D-day 스트립(가로) — 주관사·상장방식·회사소개·청약일정
  ② 최근 상장 종목 : 2열 그리드 타일(시총·등락·상장일·상장방식·보호예수·밸류 칩)
       각 타일 아래 '차트·상세 보기' 펼침 → 큰 차트 + 상장 개요 + 회사소개

차트(요청 반영)
  · 가로축: 날짜 라벨 표시 + '보름(15일)' 단위 눈금
  · 세로축: 종가 라벨 표시 + 최솟값~최댓값으로 '꽉 차게'(여백 없음, nice=False)
  · 면적+선 + 마우스 십자선(지수/관심종목 차트와 같은 인터랙션)
  · 기간 라디오(1개월/3개월/6개월/1년) 공용 — 모든 종목 차트에 함께 적용

데이터
  · 종목 목록·메타 : Supabase ipo_snapshots(엔진이 적재). 없으면 임베드 샘플로 폴백
        (※ 샘플일 때는 상단에 '샘플 데이터' 안내가 뜬다)
  · 차트 시세      : 뷰어에서 직접 — 네이버 자동완성(코드해석) + 네이버 siseJson(일별),
                     실패 시 yfinance. (Streamlit Cloud는 네이버/yfinance 접근 가능)
  · 종목명 클릭    : 네이버 시세 검색
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
_PERIODS = {"1개월": 31, "3개월": 92, "6개월": 183, "1년": 366}
_UP_C, _DOWN_C = "#B65F5A", "#5A7CA0"
_AXIS_C, _GRID_C = "#9a9b92", "#ECEDE7"

# ── 임베드 샘플 (DB 미구성 시 폴백 · 전부 예시) ──────────────────
_SAMPLE = {
    "asof": "샘플",
    "recent": [
        {"name": "시프트업", "code": "462870", "sector": "게임·콘텐츠", "listed": "2024.07.11",
         "cap": "3.2조", "pct": 1.8, "method": "일반상장",
         "ipo_price": "공모가 60,000원 (밴드 상단)", "valuation": "PER 약 39x",
         "lockup": "최대주주 6M · 기관확약 39%",
         "intro": "서브컬처 게임 ‘니케’·‘스텔라 블레이드’ 개발사. 높은 영업이익률이 강점."},
        {"name": "에이피알", "code": "278470", "sector": "뷰티 디바이스", "listed": "2024.02.27",
         "cap": "2.1조", "pct": -0.7, "method": "일반상장",
         "ipo_price": "공모가 250,000원 (밴드 상단)", "valuation": "PER 약 21x",
         "lockup": "최대주주 6M · 기관확약 28%",
         "intro": "뷰티 디바이스 ‘메디큐브 에이지알’·화장품 운영. 해외 매출 확대가 동력."},
        {"name": "산일전기", "code": "062040", "sector": "전력기기", "listed": "2024.07.30",
         "cap": "9,000억", "pct": -1.1, "method": "일반상장",
         "ipo_price": "공모가 35,000원 (밴드 상단)", "valuation": "PER 약 17x",
         "lockup": "최대주주 6M · 기관확약 35%",
         "intro": "변압기·리액터 제조사. 북미 전력 인프라·데이터센터 전력 수요 수혜."},
        {"name": "더본코리아", "code": "475560", "sector": "외식 프랜차이즈", "listed": "2024.11.06",
         "cap": "4,800억", "pct": 0.9, "method": "일반상장",
         "ipo_price": "공모가 34,000원 (밴드 상단)", "valuation": "PER 약 14x",
         "lockup": "최대주주 6M · 기관확약 22%",
         "intro": "빽다방·홍콩반점 등 외식 브랜드 운영. 가맹 확장과 소스·HMR 유통이 축."},
        {"name": "셀비온", "code": "308430", "sector": "방사성의약품", "listed": "2024.10.21",
         "cap": "2,600억", "pct": 2.0, "method": "기술특례상장",
         "ipo_price": "공모가 13,000원 (밴드 상단 초과)", "valuation": "적자 · PSR 기반",
         "lockup": "최대주주 6M~3Y · 기관확약 12%",
         "intro": "방사성 동위원소 기반 항암 치료제 개발. 전립선암 치료제가 핵심 파이프라인."},
        {"name": "클로봇", "code": "466100", "sector": "로봇 소프트웨어", "listed": "2024.10.28",
         "cap": "2,400억", "pct": 3.2, "method": "기술특례상장",
         "ipo_price": "공모가 13,000원 (밴드 상단 초과)", "valuation": "적자 · 매출성장",
         "lockup": "최대주주 6M~2Y · 기관확약 9%",
         "intro": "자율주행 로봇용 소프트웨어 플랫폼. 이종 로봇 통합 관제가 차별점."},
    ],
    "upcoming": [
        {"name": "○○바이오", "dday": "D-3", "state": "청약 06.29~30", "under": "한국투자증권",
         "method": "기술특례", "soon": True, "intro": "항암 신약 타깃 단백질 분해(TPD) 플랫폼. 코스닥 예정."},
        {"name": "△△로보틱스", "dday": "D-1", "state": "수요예측 마감", "under": "미래에셋증권",
         "method": "일반상장", "soon": True, "intro": "협동로봇·물류 자동화. 공모가 밴드 18,000~22,000원."},
        {"name": "□□에너지솔루션", "dday": "D-9", "state": "청약 07.06~07", "under": "NH투자증권·KB증권",
         "method": "일반상장", "soon": False, "intro": "산업용 ESS·전력변환장치(PCS). 코스피 이전상장."},
        {"name": "◇◇소프트", "dday": "D-15", "state": "수요예측 07.10~11", "under": "삼성증권",
         "method": "기술특례", "soon": False, "intro": "기업용 생성형 AI 에이전트 플랫폼. 코스닥 기술특례."},
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
.ipo-up{flex:0 0 auto;min-width:190px;max-width:230px;background:var(--summary-bg,#F6F7F2);
  border:1px solid var(--line,#ECEDE7);border-radius:12px;padding:11px 13px;}
.ipo-up .nm{font-size:13px;font-weight:800;display:flex;justify-content:space-between;gap:8px;align-items:center;}
.ipo-up .sub{font-size:10.5px;color:var(--muted,#9a9b92);margin-top:4px;line-height:1.55;}
.ipo-up .ds{font-size:11px;color:var(--pill-ink,#5d6258);margin-top:5px;line-height:1.5;word-break:keep-all;}
.dday{font-size:10.5px;font-weight:800;color:#fff;background:var(--sage-deep,#7E9A83);
  padding:3px 8px;border-radius:6px;flex:none;}
.dday.soon{background:#C2410C;}
/* 최근 상장 타일 (요약 — 펼침 위에 항상 보임) */
.ipo-tile{background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);border-radius:13px 13px 0 0;
  border-bottom:none;padding:13px 15px 9px;}
.ipo-tile .top{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;}
.ipo-tile .nm{font-size:14.5px;font-weight:800;}
.ipo-tile .nm a{color:var(--ink,#34352f);text-decoration:none;}
.ipo-tile .nm a:hover{text-decoration:underline;}
.ipo-tile .ss{font-size:11px;color:var(--muted,#9a9b92);margin-top:2px;}
.ipo-tile .cap{font-size:15px;font-weight:800;text-align:right;white-space:nowrap;}
.ipo-tile .cap .d{font-size:11px;font-weight:700;margin-top:1px;}
.ipo-tile .chips{display:flex;gap:5px;flex-wrap:wrap;margin-top:9px;}
.up{color:var(--up,#B65F5A);} .down{color:var(--down,#5A7CA0);}
.chip{font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:6px;white-space:nowrap;}
.chip.tech{background:#F0E9F3;color:#6B4A7C;}
.chip.normal{background:#EBF3EC;color:#4A6B4F;}
.chip.lock{background:#F3EEE6;color:#7C5F2C;}
.chip.val{background:#FDEEE3;color:#C2410C;}
/* 펼침 안 상세 메타 */
.ipo-meta{display:grid;grid-template-columns:auto 1fr;gap:6px 12px;font-size:12.5px;align-items:baseline;margin-top:2px;}
.ipo-meta .k{color:var(--muted,#9a9b92);font-weight:600;white-space:nowrap;}
.ipo-meta .v{font-weight:700;color:var(--ink,#34352f);}
.ipo-intro{font-size:12px;color:var(--pill-ink,#5d6258);line-height:1.6;margin-top:11px;
  background:var(--summary-bg,#F6F7F2);border:1px solid var(--line,#ECEDE7);border-radius:9px;padding:9px 11px;word-break:keep-all;}
.ipo-cna{font-size:12px;color:var(--muted,#9a9b92);padding:16px 2px;}
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
            s = fetch_history(tk)  # 일별 종가 시리즈/DF 가정
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


# ── 커스텀 축 차트 (보름 x · 꽉찬 y) ───────────────────────────
def _ipo_chart(name: str, days: int):
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
        tickCount={"interval": "day", "step": 15},   # ← 보름(15일) 단위
        domain=True, domainColor=_GRID_C, ticks=True, tickColor=_GRID_C, labelAngle=0))
    y_enc = alt.Y("종가:Q", scale=alt.Scale(
        domain=[lo, hi], nice=False, zero=False, clamp=True),  # ← 최솟값~최댓값 꽉차게
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


# ── 칩 HTML ────────────────────────────────────────────────────
def _method_chip(m: str) -> str:
    cls = "tech" if "특례" in (m or "") else "normal"
    return f'<span class="chip {cls}">{html.escape(m or "일반상장")}</span>'


def _tile_summary(s: dict) -> str:
    pct = s.get("pct")
    pct_html = ""
    if isinstance(pct, (int, float)):
        cls = "up" if pct >= 0 else "down"
        pct_html = f'<div class="d {cls}">{"+" if pct >= 0 else ""}{pct:.1f}%</div>'
    nm = html.escape(s.get("name", ""))
    link = html.escape(naver_stock_url(s.get("name", "")))
    chips = _method_chip(s.get("method"))
    if s.get("lockup"):
        chips += f'<span class="chip lock">🔒 {html.escape(_short_lock(s["lockup"]))}</span>'
    if s.get("valuation"):
        chips += f'<span class="chip val">{html.escape(s["valuation"])}</span>'
    return (
        '<div class="ipo-tile"><div class="top">'
        f'<div><div class="nm"><a href="{link}" target="_blank" rel="noopener">{nm}</a></div>'
        f'<div class="ss">{html.escape(s.get("sector",""))} · 상장 {html.escape(s.get("listed",""))}</div></div>'
        f'<div class="cap">{html.escape(str(s.get("cap","-")))}{pct_html}</div>'
        f'</div><div class="chips">{chips}</div></div>'
    )


def _short_lock(lock: str) -> str:
    for tok in str(lock).replace(" ", "").split("·"):
        if "확약" in tok:
            return tok
    return (str(lock)[:14] + "…") if len(str(lock)) > 15 else str(lock)


# ── 메인 렌더 ─────────────────────────────────────────────────
def render_ipo_tab():
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown('<div class="ipo-bar"></div>', unsafe_allow_html=True)
    st.title("IPO")

    data = load_ipo()
    recent = data.get("recent") or []
    upcoming = data.get("upcoming") or []
    asof = data.get("asof", "")
    cap_txt = f"기준 {asof} · 최근 2년 내 상장(현재 시총 5,000억원 이상) · 최신순"
    if data.get("_sample"):
        cap_txt = "샘플 데이터 — 엔진(ipo_run) 첫 실행 후 실데이터로 대체돼요 · " + cap_txt
    st.caption(cap_txt)

    # ① 향후 IPO 일정
    st.markdown('<div class="ipo-sec">향후 IPO 일정</div>', unsafe_allow_html=True)
    if upcoming:
        cards = ""
        for u in upcoming:
            soon = " soon" if u.get("soon") else ""
            cards += (
                '<div class="ipo-up"><div class="nm">'
                f'{html.escape(u.get("name",""))}<span class="dday{soon}">{html.escape(u.get("dday",""))}</span></div>'
                f'<div class="sub">{html.escape(u.get("state",""))} · {html.escape(u.get("under",""))}<br>'
                f'{html.escape(u.get("method",""))}</div>'
                f'<div class="ds">{html.escape(u.get("intro",""))}</div></div>'
            )
        st.markdown(f'<div class="ipo-strip">{cards}</div>', unsafe_allow_html=True)
    else:
        st.caption("확정된 향후 일정이 없어요.")

    # ② 최근 상장 종목
    st.markdown('<div class="ipo-sec">최근 상장 종목 '
                '<span class="mut">· 타일 아래 ‘차트·상세 보기’를 누르면 차트가 펼쳐져요</span></div>',
                unsafe_allow_html=True)
    if not recent:
        st.markdown('<div class="ipo-cna">표시할 종목이 없어요.</div>', unsafe_allow_html=True)
        return

    period = st.radio("조회 기간", list(_PERIODS.keys()), index=2, horizontal=True,
                      key="ipo_period", label_visibility="collapsed")
    days = _PERIODS[period]

    cols = st.columns(2, gap="medium")
    for i, s in enumerate(recent):
        with cols[i % 2]:
            st.markdown(_tile_summary(s), unsafe_allow_html=True)
            with st.expander("차트·상세 보기"):
                _ipo_chart(s.get("name", ""), days)
                meta = (
                    '<div class="ipo-meta">'
                    f'<span class="k">상장일</span><span class="v">{html.escape(str(s.get("listed","-")))}</span>'
                    f'<span class="k">시가총액</span><span class="v">{html.escape(str(s.get("cap","-")))}</span>'
                    f'<span class="k">상장방식</span><span class="v">{html.escape(str(s.get("method","-")))}</span>'
                    f'<span class="k">밸류</span><span class="v">{html.escape(str(s.get("ipo_price","-")))} · {html.escape(str(s.get("valuation","-")))}</span>'
                    f'<span class="k">보호예수</span><span class="v">{html.escape(str(s.get("lockup","-")))}</span>'
                    '</div>'
                    f'<div class="ipo-intro">{html.escape(str(s.get("intro","")))}</div>'
                )
                st.markdown(meta, unsafe_allow_html=True)

    st.caption("차트: 면적+선 · 마우스 십자선 · 가로축 보름(15일) 눈금 · 세로축 최솟값~최댓값 꽉차게 · "
               "종목명 클릭=네이버 시세. 시세는 네이버 siseJson(일별) 기준 약 15분 지연.")
