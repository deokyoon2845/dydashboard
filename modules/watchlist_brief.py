"""[뷰어] 관심 종목 브리핑 (키워드 탭 하단에 표시).

레이아웃(A안): 종목마다 한 행을 차지하며
  · 왼쪽  : '지수 탭과 동일한 양식'의 큰 인터랙티브 차트
            (면적+선 · 마우스 십자선 · 가로 줌 · 기간 1일/1개월/3개월/6개월/1년)
  · 오른쪽: 그 종목의 근거 패널
            ('왜 움직였나' + 오늘 리포트 토픽 / 키워드에서 이 종목을 짚은 항목)
기간 선택은 맨 위 공용 라디오 1개(지수 탭과 동일)로, 모든 종목 차트에 함께 적용.
관리(추가·삭제, 쉼표 구분)는 같은 섹션 하단. 저장은 Supabase DB(영속).

시세·차트 데이터 경로 (★pykrx 제거 — KRX가 클라우드 IP를 영구 차단하기 때문):
  · 종목명 → 종목코드(+시장)   : 네이버 자동완성 API (ac.stock.naver.com)
  · 큰 차트(일별)             : yfinance fetch_history(1y)  · 실패 시 네이버 siseJson(일별)
  · 큰 차트(1일·5분봉)        : yfinance fetch_intraday(5m)
  · 요약 띠 시세              : fetch_intraday→오늘 / fetch_history→일별 / 네이버 siseJson
  · 리포트 토픽 = Supabase DB의 최신 보고서 topics[].stocks
  · 키워드 = data/keywords_today.json items[].stocks

차트 함수(_big_stock_chart / _big_stock_chart_intraday)는 app.py의
_big_index_chart / _big_index_chart_intraday 와 의도적으로 동일한 구조다.
지수=지수값(소수 2자리), 종목=원 단위(정수)라 표시 포맷만 ',.0f'로 맞췄다.
"""

import html
import json
import re
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import requests
import streamlit as st
from lxml import html as lxml_html

from modules.stocks import naver_stock_url
from modules.watchlist import load_watchlist, save_watchlist
from modules.indices import fetch_intraday, fetch_history

_KW_PATH = Path("data/keywords_today.json")
_KST = ZoneInfo("Asia/Seoul")
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/124.0 Safari/537.36"}

# 지수 탭과 동일한 기간 → 일수 매핑
_PERIODS = {"1일": 1, "1개월": 31, "3개월": 92, "6개월": 183, "1년": 366}

# 지수 탭과 동일한 색 (미니멀 미스트)
_UP_C, _DOWN_C = "#B65F5A", "#5A7CA0"
_AXIS_C, _GRID_C = "#9a9b92", "#ECEDE7"

_WB_CSS = """
<style>
.wb-bar{height:3px;width:30px;background:var(--sage,#A7BBA9);border-radius:3px;margin:0 0 12px;}
.wb-strip{background:var(--summary-bg,#F6F7F2);border:1px solid var(--line,#ECEDE7);border-radius:10px;
  padding:9px 13px;font-size:12.5px;color:var(--sage-deep,#7E9A83);font-weight:600;margin:2px 0 8px;line-height:1.65;}
.wb-strip b{color:var(--ink,#34352f);font-weight:700;}
.wb-strip b.up{color:var(--up,#B65F5A);} .wb-strip b.down{color:var(--down,#5A7CA0);}
/* 차트 헤더 (지수 탭 헤더와 동일 톤) */
.wb-chead{margin-bottom:2px;}
.wb-chead .nm{font-size:12px;color:var(--muted,#9a9b92);font-weight:600;}
.wb-chead .nm a{color:var(--ink,#34352f);text-decoration:none;}
.wb-chead .nm a:hover{text-decoration:underline;}
.wb-chead .val{font-size:24px;font-weight:700;color:var(--ink,#34352f);letter-spacing:-.02em;}
.wb-chead .chg{font-size:13px;font-weight:700;margin-left:2px;}
.wb-chead .chg.up{color:var(--up,#B65F5A);} .wb-chead .chg.down{color:var(--down,#5A7CA0);}
.wb-cna{font-size:12px;color:var(--muted,#9a9b92);padding:18px 2px;}
/* 오른쪽 근거 패널 */
.wb-refpanel{padding-top:4px;}
.wb-why-h{font-size:11px;font-weight:700;letter-spacing:.05em;color:var(--muted,#9a9b92);
  text-transform:uppercase;margin:0 0 6px;}
.wb-why{font-size:12.5px;color:var(--pill-ink,#5d6258);line-height:1.55;margin-bottom:11px;word-break:keep-all;}
.wb-refs{display:flex;flex-direction:column;gap:6px;}
.wb-ref{font-size:11.5px;font-weight:600;padding:7px 10px;border-radius:8px;border:1px solid var(--line,#ECEDE7);
  background:var(--pill-bg,#F1F2EC);color:var(--pill-ink,#5d6258);line-height:1.5;
  word-break:keep-all;white-space:normal;}
.wb-ref.rpt{background:#eef4ef;color:var(--sage-deep,#7E9A83);border-color:#dfe9e0;}
.wb-ref b{font-weight:700;}
.wb-na{font-size:11.5px;color:var(--muted,#9a9b92);}
/* 최근 뉴스 */
.wb-news-h{font-size:11px;font-weight:700;letter-spacing:.05em;color:var(--muted,#9a9b92);
  text-transform:uppercase;margin:13px 0 6px;}
.wb-news{display:flex;flex-direction:column;gap:6px;}
.wb-news-item{display:block;text-decoration:none;padding:7px 10px;border-radius:8px;
  border:1px solid var(--line,#ECEDE7);background:var(--card,#fff);transition:border-color .15s ease,background .15s ease;}
.wb-news-item:hover{border-color:var(--sage-deep,#7E9A83);background:#fbfcfa;}
.wb-news-t{display:block;font-size:12px;font-weight:600;color:var(--ink,#34352f);line-height:1.45;word-break:keep-all;}
.wb-news-m{display:block;font-size:10.5px;color:var(--muted,#9a9b92);margin-top:3px;}
.wb-news-na{font-size:11.5px;color:var(--muted,#9a9b92);}
.wb-div{height:1px;background:var(--line,#ECEDE7);margin:16px 0 18px;}
.wb-mng-h{font-size:12px;font-weight:700;letter-spacing:.05em;color:var(--muted,#9a9b92);margin:6px 0 8px;text-transform:uppercase;}
</style>
"""


def _norm(s: str) -> str:
    return "".join(str(s).split()).casefold()


# ── 종목명 → (종목코드, yfinance 접미사) : 네이버 자동완성 (pykrx 미사용) ──

@st.cache_data(ttl=86400)
def _resolve_code(name: str):
    """종목명 → (6자리 코드, '.KS'/'.KQ'). 네이버 자동완성 기반. 실패 시 (None, None).

    응답 형식이 버전에 따라 dict 리스트 또는 중첩 배열일 수 있어 둘 다 방어적으로 처리.
    """
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

    nq = _norm(q)
    best = None       # 정확히 이름이 일치하는 후보 (우선)
    first = None      # 첫 유효 후보 (폴백)
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
        if first is None:
            first = cand
        if nm and _norm(nm) == nq:
            best = cand
            break
    return best or first or (None, None)


def _suffix_candidates(code, suffix):
    """우선 접미사 + 반대 접미사 순서로 yfinance 티커 후보 목록."""
    other = ".KQ" if suffix == ".KS" else ".KS"
    return [f"{code}{suffix}", f"{code}{other}"]


# ── 네이버 siseJson 일별 폴백 (yfinance 실패 시) ──

def _naver_daily(code: str):
    """네이버 siseJson 일별 종가. 반환 dict 또는 None.

    반환: {'close', 'pct', 'series'(DatetimeIndex), 'asof'} · 약 70일치.
    """
    try:
        end = date.today().strftime("%Y%m%d")
        start = (date.today() - timedelta(days=70)).strftime("%Y%m%d")
        url = ("https://api.finance.naver.com/siseJson.naver"
               f"?symbol={code}&requestType=1"
               f"&startTime={start}&endTime={end}&timeframe=day")
        r = requests.get(url, headers=_UA, timeout=5)
        r.raise_for_status()
        rows = json.loads(r.text.strip().replace("'", '"'))
        body = [x for x in rows[1:] if x and len(x) >= 5]
        closes, dates = [], []
        for x in body:
            try:
                closes.append(float(x[4]))
                dates.append(str(x[0]))
            except (ValueError, TypeError):
                continue
        if len(closes) < 2:
            return None
        s = pd.Series(closes, index=pd.to_datetime(dates, errors="coerce")).dropna()
        cur, prev = closes[-1], closes[-2]
        pct = (cur - prev) / prev * 100 if prev else 0.0
        asof = dates[-1][:8] if dates else ""
        return {"close": cur, "pct": pct, "series": s, "asof": asof}
    except Exception:
        return None


# ── 종목 뉴스: 전영업일 장마감(15:30)~현재 윈도우, 네이버 종목 뉴스 3개 ──

def _prev_session_close(now: datetime) -> datetime:
    """직전 영업일 15:30 KST(전영업일 장마감) 시각. 주말은 건너뜀.
    (공휴일은 거르지 않음 — 약간의 오차는 허용, 무회귀 우선.)"""
    prev = now.date() - timedelta(days=1)
    while prev.weekday() >= 5:  # 5=토, 6=일
        prev -= timedelta(days=1)
    return datetime.combine(prev, dtime(15, 30), tzinfo=_KST)


def _parse_kdate(s: str):
    """'2026.06.22 14:30' 또는 '2026.06.22' → KST datetime. 실패 시 None."""
    s = (s or "").strip()
    for fmt in ("%Y.%m.%d %H:%M", "%Y.%m.%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=_KST)
        except ValueError:
            continue
    return None


def _news_rows_from_doc(doc):
    """finance.naver.com 종목뉴스 페이지(table.type5)에서 (제목·링크·출처·시각) 추출.
    본문에 손대지 않고 헤드라인/출처/시각/링크만 가져온다(저작권 안전).
    반환: [{'title','url','source','dt'(KST)}] · 페이지 등장 순서."""
    out = []
    for tr in doc.xpath('//tr[td[contains(@class,"title")]]'):
        a = tr.xpath('.//td[contains(@class,"title")]//a')
        dcell = tr.xpath('.//td[contains(@class,"date")]')
        if not a or not dcell:
            continue
        title = " ".join("".join(a[0].itertext()).split())
        href = (a[0].get("href") or "").strip()
        dt = _parse_kdate(" ".join("".join(dcell[0].itertext()).split()))
        if not title or not href or dt is None:
            continue
        icell = tr.xpath('.//td[contains(@class,"info")]')
        source = " ".join("".join(icell[0].itertext()).split()) if icell else ""
        url = href if href.startswith("http") else "https://finance.naver.com" + href
        out.append({"title": title, "url": url, "source": source, "dt": dt})
    return out


@st.cache_data(ttl=900)
def _stock_news(code: str, name: str):
    """전영업일 장마감(15:30)~현재 사이 네이버 '종목 뉴스' 중
       제목에 종목명을 담은(관련도) → 최신순 상위 3개.
    반환: [{'title','url','source','dt'}] · 최대 3 · 실패/없음 시 [].
    경로: finance.naver.com/item/news_news.naver 스크래핑(키 불필요)."""
    if not code:
        return []
    now = datetime.now(_KST)
    start = _prev_session_close(now)
    end = now + timedelta(minutes=5)

    collected, seen = [], set()
    for page in (1, 2):
        try:
            r = requests.get(
                "https://finance.naver.com/item/news_news.naver",
                params={"code": str(code).zfill(6), "page": page,
                        "sm": "title_entity_id.basic", "clusterId": ""},
                headers=_UA, timeout=6)
            r.raise_for_status()
            doc = lxml_html.fromstring(r.content)  # 페이지 meta(euc-kr) 자동 인식
        except Exception:
            break
        rows = _news_rows_from_doc(doc)
        if not rows:
            break
        page_min = None
        for row in rows:
            tkey = re.sub(r"\s+", "", row["title"])[:40]
            if tkey in seen:
                continue
            seen.add(tkey)
            collected.append(row)
            page_min = row["dt"] if page_min is None else min(page_min, row["dt"])
        # 이 페이지가 이미 윈도우 시작 이전까지 내려갔으면 다음 페이지 불필요
        if page_min is not None and page_min < start:
            break

    in_win = [c for c in collected if start <= c["dt"] <= end]
    nrm = _norm(name)
    in_win.sort(key=lambda c: (nrm in _norm(c["title"]), c["dt"]), reverse=True)
    return in_win[:3]


# ── 요약 띠용: 종목 오늘 시세 (현재가·등락) ──

@st.cache_data(ttl=600)
def _quote(name: str):
    """종목명 → 오늘 시세. 반환:
      {'code', 'close', 'pct', 'asof'} (코드 없으면 code=None).
    경로: 코드해석(네이버) → yfinance 분봉(오늘) → yfinance 일별 → 네이버 siseJson 일별.
    """
    code, suffix = _resolve_code(name)
    base = {"code": code, "close": None, "pct": None, "asof": ""}
    if not code:
        return base

    cands = _suffix_candidates(code, suffix)

    # 1) yfinance 분봉(오늘)
    for tk in cands:
        try:
            d = fetch_intraday(tk, "5m")
        except Exception:
            d = None
        if d and d.get("series") is not None and len(d["series"]) >= 2:
            base.update({"close": d.get("current"), "pct": d.get("pct"),
                         "asof": datetime.now(_KST).strftime("%Y%m%d")})
            return base

    # 2) yfinance 일별
    for tk in cands:
        try:
            close = fetch_history(tk, "1mo")
        except Exception:
            close = None
        if close is not None and len(close) >= 2:
            cur, prev = float(close.iloc[-1]), float(close.iloc[-2])
            pct = (cur - prev) / prev * 100 if prev else 0.0
            try:
                asof = pd.to_datetime(close.index[-1]).strftime("%Y%m%d")
            except Exception:
                asof = ""
            base.update({"close": cur, "pct": pct, "asof": asof})
            return base

    # 3) 네이버 siseJson 일별 폴백
    nv = _naver_daily(code)
    if nv:
        base.update({"close": nv["close"], "pct": nv["pct"], "asof": nv["asof"]})
    return base


# ── 큰 차트용 시계열 ──

@st.cache_data(ttl=1800)
def _history_1y(name: str):
    """큰 차트(일별)용 1년 종가 Series. yfinance 우선, 실패 시 네이버(~70일) 폴백.
    반환: pd.Series(DatetimeIndex→종가) 또는 None."""
    code, suffix = _resolve_code(name)
    if not code:
        return None
    for tk in _suffix_candidates(code, suffix):
        try:
            close = fetch_history(tk, "1y")
        except Exception:
            close = None
        if close is not None and len(close) >= 2:
            return close
    nv = _naver_daily(code)
    if nv and nv.get("series") is not None and len(nv["series"]) >= 2:
        return nv["series"]
    return None


def _intraday(name: str):
    """큰 차트(1일·5분봉)용. fetch_intraday 후보 중 첫 성공분. 실패 시 None."""
    code, suffix = _resolve_code(name)
    if not code:
        return None
    for tk in _suffix_candidates(code, suffix):
        try:
            d = fetch_intraday(tk, "5m")
        except Exception:
            d = None
        if d and d.get("series") is not None and len(d["series"]) >= 2:
            return d
    return None


# ── 링크 소스: 최신 리포트 토픽 / 오늘의 키워드 ──

def _latest_report() -> dict:
    try:
        from modules import db
        slugs = db.list_slugs()
        return db.load_by_slug(slugs[0]) if slugs else None
    except Exception:
        return None


def _today_keywords() -> list:
    try:
        data = json.loads(_KW_PATH.read_text(encoding="utf-8"))
        return data.get("items", []) or []
    except Exception:
        return []


def _fmt_asof(d: str) -> str:
    if d and len(d) == 8:
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return d


# ── 행 데이터 빌드 (요약 띠 + 근거) ──

def _build_rows(watchlist):
    report = _latest_report()
    topics = (report.get("topics") if report else None) or []
    keywords = _today_keywords()

    rows, asofs = [], []
    for name in watchlist:
        nn = _norm(name)
        q = _quote(name)
        if q.get("asof"):
            asofs.append(q["asof"])

        rpt = []
        for i, tp in enumerate(topics, start=1):
            if nn in {_norm(s) for s in (tp.get("stocks") or [])}:
                rpt.append((i, str(tp.get("title", "")).strip()))
        kw = []
        for i, it in enumerate(keywords[:15], start=1):
            if nn in {_norm(s) for s in (it.get("stocks") or [])}:
                kw.append((i, str(it.get("keyword", "")).strip()))

        if rpt:
            why = rpt[0][1]
        elif kw:
            why = kw[0][1]
        else:
            why = "오늘 리포트·키워드에서 직접 언급 없음"

        rows.append({
            "name": name, "code": q.get("code"),
            "close": q.get("close"), "pct": q.get("pct"),
            "why": why, "rpt": rpt[:2], "kw": kw[:2],
            "news": _stock_news(q.get("code"), name),
        })
    asof = max(asofs) if asofs else ""
    return rows, asof


# ── 차트 헤더 HTML (지수 탭 헤더와 동일 톤 · 종목명은 네이버 링크) ──

def _chart_head(name, code, cur, change, pct, sub=""):
    up = change >= 0
    color = _UP_C if up else _DOWN_C
    cls = "up" if up else "down"
    arrow = "▲" if change > 0 else ("▼" if change < 0 else "▬")
    nm = html.escape(name)
    if code:
        nm_inner = (f'<a href="{html.escape(naver_stock_url(name))}" '
                    f'target="_blank" rel="noopener">⭐ {nm}</a>')
    else:
        nm_inner = f'⭐ {nm}'
    sub_html = f' · {html.escape(sub)}' if sub else ''
    return (f'<div class="wb-chead">'
            f'<span class="nm">{nm_inner}{sub_html}</span><br>'
            f'<span class="val">{cur:,.0f}</span> '
            f'<span class="chg {cls}">{arrow} {change:+,.0f} ({pct:+.2f}%)</span>'
            f'</div>')


# ── 큰 차트: 일별(1개월/3개월/6개월/1년) — app._big_index_chart 동일 구조 ──

def _big_stock_chart(r, days: int):
    name, code = r["name"], r.get("code")
    if not code:
        st.markdown(_chart_head(name, None, 0, 0, 0), unsafe_allow_html=True)
        st.markdown('<div class="wb-cna">종목 코드를 확인하지 못했어요. '
                    '(KRX 상장명과 정확히 일치해야 시세가 떠요)</div>',
                    unsafe_allow_html=True)
        return

    close = _history_1y(name)
    if close is None or len(close) < 2:
        st.markdown(_chart_head(name, code, 0, 0, 0), unsafe_allow_html=True)
        st.markdown(f'<div class="wb-cna">{html.escape(name)} 데이터를 불러오지 못했어요. '
                    f'(잠시 후 새로고침)</div>', unsafe_allow_html=True)
        return

    df = pd.DataFrame({"날짜": pd.to_datetime(close.index),
                       "종가": pd.to_numeric(close.values, errors="coerce")}).dropna()
    if len(df) < 2:
        st.markdown(_chart_head(name, code, 0, 0, 0), unsafe_allow_html=True)
        st.markdown(f'<div class="wb-cna">{html.escape(name)} 데이터가 부족해요.</div>',
                    unsafe_allow_html=True)
        return

    cutoff = df["날짜"].max() - pd.Timedelta(days=days)
    seg = df[df["날짜"] >= cutoff]
    if len(seg) < 2:
        seg = df

    cur, prev = float(seg["종가"].iloc[-1]), float(seg["종가"].iloc[-2])
    change = cur - prev
    pct = (change / prev) * 100 if prev else 0.0
    period_up = cur >= float(seg["종가"].iloc[0])
    line_c = _UP_C if period_up else _DOWN_C

    st.markdown(_chart_head(name, code, cur, change, pct), unsafe_allow_html=True)

    lo_v, hi_v = float(seg["종가"].min()), float(seg["종가"].max())
    pad_v = (hi_v - lo_v) * 0.08 or 1.0
    y_dom = [lo_v - pad_v, hi_v + pad_v]

    x_enc = alt.X("날짜:T", axis=alt.Axis(title=None, format="%m/%d",
                                          labelColor=_AXIS_C, grid=False))
    y_enc = alt.Y("종가:Q", scale=alt.Scale(domain=y_dom, nice=False, clamp=True, zero=False),
                  axis=alt.Axis(title=None, labelColor=_AXIS_C, gridColor=_GRID_C,
                                format=",.0f"))
    tip = [alt.Tooltip("날짜:T", format="%Y-%m-%d"),
           alt.Tooltip("종가:Q", format=",.0f")]

    seg_a = seg.copy()
    seg_a["바닥"] = y_dom[0]
    area = alt.Chart(seg_a).mark_area(color=line_c, opacity=0.13).encode(
        x=x_enc, y=y_enc, y2=alt.Y2("바닥:Q"), tooltip=tip)
    line_main = alt.Chart(seg).mark_line(color=line_c, strokeWidth=2).encode(
        x=x_enc, y=y_enc, tooltip=tip)

    try:
        hover = alt.selection_point(fields=["날짜"], nearest=True,
                                    on="mouseover", empty=False)
        zoom = alt.selection_interval(bind="scales", encodings=["x"])
        selectors = alt.Chart(seg).mark_point().encode(
            x=x_enc, opacity=alt.value(0)).add_params(hover)
        vrule = alt.Chart(seg).mark_rule(color=_AXIS_C, strokeDash=[3, 3]).encode(
            x=x_enc).transform_filter(hover)
        hrule = alt.Chart(seg).mark_rule(color=_AXIS_C, strokeDash=[3, 3]).encode(
            y=y_enc).transform_filter(hover)
        hpoints = alt.Chart(seg).mark_point(size=60, color=line_c, filled=True).encode(
            x=x_enc, y=y_enc,
            opacity=alt.condition(hover, alt.value(1), alt.value(0)))
        htext = alt.Chart(seg).mark_text(
            align="left", dx=8, dy=-10, fontSize=12, fontWeight="bold",
            color=line_c).encode(
            x=x_enc, y=y_enc,
            text=alt.condition(hover, alt.Text("종가:Q", format=",.0f"),
                               alt.value("")))
        chart = (alt.layer(area, line_main, selectors, vrule, hrule, hpoints, htext)
                 .add_params(zoom)
                 .properties(height=260, background="transparent")
                 .configure_view(strokeWidth=0))
    except Exception:
        chart = (alt.layer(area, line_main)
                 .properties(height=260, background="transparent")
                 .configure_view(strokeWidth=0))

    st.altair_chart(chart, use_container_width=True)


# ── 큰 차트: 1일(5분봉) — app._big_index_chart_intraday 동일 구조 ──

def _big_stock_chart_intraday(r):
    name, code = r["name"], r.get("code")
    if not code:
        st.markdown(_chart_head(name, None, 0, 0, 0), unsafe_allow_html=True)
        st.markdown('<div class="wb-cna">종목 코드를 확인하지 못했어요.</div>',
                    unsafe_allow_html=True)
        return

    d = _intraday(name)
    if not d or d.get("series") is None or len(d["series"]) < 2:
        st.markdown(_chart_head(name, code, 0, 0, 0), unsafe_allow_html=True)
        st.markdown(f'<div class="wb-cna">{html.escape(name)} 분봉 데이터를 불러오지 못했어요. '
                    f'(분봉은 지연·누락될 수 있어요. 다른 기간을 선택해 보세요.)</div>',
                    unsafe_allow_html=True)
        return

    s = d["series"]
    df = pd.DataFrame({"시각": pd.to_datetime(s.index),
                       "종가": pd.to_numeric(s.values, errors="coerce")}).dropna()
    if len(df) < 2:
        st.markdown(_chart_head(name, code, 0, 0, 0), unsafe_allow_html=True)
        st.markdown(f'<div class="wb-cna">{html.escape(name)} 분봉 데이터가 부족해요.</div>',
                    unsafe_allow_html=True)
        return

    cur = d["current"]
    change = d["change"]
    pct = d["pct"]
    day_up = change >= 0
    prev_close = d.get("prev_close")
    base_is_prev = d.get("base_is_prev", False)
    line_c = _UP_C if day_up else _DOWN_C

    base_label = "전일 종가 대비" if base_is_prev else "시가 대비"
    sub = f'{d.get("asof", "")} ({base_label})'
    st.markdown(_chart_head(name, code, cur, change, pct, sub=sub),
                unsafe_allow_html=True)

    lo_v, hi_v = float(df["종가"].min()), float(df["종가"].max())
    span = (hi_v - lo_v) or (hi_v * 0.01) or 1.0

    show_baseline = False
    if base_is_prev and prev_close is not None and prev_close > 0:
        if (lo_v - 1.5 * span) <= prev_close <= (hi_v + 1.5 * span):
            lo_v = min(lo_v, prev_close)
            hi_v = max(hi_v, prev_close)
            show_baseline = True

    pad_v = (hi_v - lo_v) * 0.10 or (hi_v * 0.01) or 1.0
    y_dom = [lo_v - pad_v, hi_v + pad_v]

    x_enc = alt.X("시각:T", axis=alt.Axis(title=None, format="%H:%M",
                                          labelColor=_AXIS_C, grid=False))
    y_enc = alt.Y("종가:Q", scale=alt.Scale(domain=y_dom, nice=False, clamp=True, zero=False),
                  axis=alt.Axis(title=None, labelColor=_AXIS_C, gridColor=_GRID_C,
                                format=",.0f"))
    tip = [alt.Tooltip("시각:T", format="%H:%M"),
           alt.Tooltip("종가:Q", format=",.0f")]

    df_a = df.copy()
    df_a["바닥"] = y_dom[0]
    area = alt.Chart(df_a).mark_area(color=line_c, opacity=0.10).encode(
        x=x_enc, y=y_enc, y2=alt.Y2("바닥:Q"), tooltip=tip)

    layers = [area]
    line_layer = alt.Chart(df).mark_line(color=line_c, strokeWidth=2).encode(
        x=x_enc, y=y_enc, tooltip=tip)
    layers.append(line_layer)
    if show_baseline:
        baseline = alt.Chart(pd.DataFrame({"y": [prev_close]})).mark_rule(
            color=_AXIS_C, strokeDash=[4, 4], opacity=0.7).encode(y="y:Q")
        layers.insert(0, baseline)

    try:
        hover = alt.selection_point(fields=["시각"], nearest=True,
                                    on="mouseover", empty=False)
        selectors = alt.Chart(df).mark_point().encode(
            x=x_enc, opacity=alt.value(0)).add_params(hover)
        vrule = alt.Chart(df).mark_rule(color=_AXIS_C, strokeDash=[3, 3]).encode(
            x=x_enc).transform_filter(hover)
        hrule = alt.Chart(df).mark_rule(color=_AXIS_C, strokeDash=[3, 3]).encode(
            y=y_enc).transform_filter(hover)
        hpoints = alt.Chart(df).mark_point(size=60, color=line_c, filled=True).encode(
            x=x_enc, y=y_enc,
            opacity=alt.condition(hover, alt.value(1), alt.value(0)))
        htext = alt.Chart(df).mark_text(
            align="left", dx=8, dy=-10, fontSize=12, fontWeight="bold",
            color=line_c).encode(
            x=x_enc, y=y_enc,
            text=alt.condition(hover, alt.Text("종가:Q", format=",.0f"),
                               alt.value("")))
        chart = (alt.layer(*layers, selectors, vrule, hrule, hpoints, htext)
                 .properties(height=260, background="transparent")
                 .configure_view(strokeWidth=0))
    except Exception:
        chart = (alt.layer(*layers)
                 .properties(height=260, background="transparent")
                 .configure_view(strokeWidth=0))

    st.altair_chart(chart, use_container_width=True)


# ── 오른쪽 근거 패널 HTML ──

def _refs_html(r) -> str:
    parts = ('<div class="wb-why-h">왜 움직였나</div>'
             f'<div class="wb-why">{html.escape(r["why"])}</div>')
    refs = ""
    for i, t in r["rpt"]:
        refs += f'<div class="wb-ref rpt"><b>리포트 {i}</b> · {html.escape(t)}</div>'
    for i, k in r["kw"]:
        refs += f'<div class="wb-ref"><b>키워드 {i}</b> · {html.escape(k)}</div>'
    if refs:
        parts += f'<div class="wb-refs">{refs}</div>'
    else:
        parts += '<div class="wb-na">오늘 리포트·키워드에서 직접 언급 없음</div>'

    # 최근 뉴스 (전영업일 장마감~현재 · 제목/출처/시각/링크만)
    if r.get("code"):
        news = r.get("news") or []
        if news:
            items = ""
            for nw in news:
                t = html.escape(nw["title"])
                u = html.escape(nw["url"])
                src = html.escape(nw.get("source") or "")
                tm = nw["dt"].strftime("%m/%d %H:%M")
                meta = " · ".join(x for x in (src, tm) if x)
                items += (f'<a class="wb-news-item" href="{u}" '
                          f'target="_blank" rel="noopener">'
                          f'<span class="wb-news-t">{t}</span>'
                          f'<span class="wb-news-m">{meta}</span></a>')
            parts += (f'<div class="wb-news-h">최근 뉴스</div>'
                      f'<div class="wb-news">{items}</div>')
        else:
            parts += ('<div class="wb-news-h">최근 뉴스</div>'
                      '<div class="wb-news-na">전영업일 장마감 이후 종목 뉴스가 없어요.</div>')
    return f'<div class="wb-refpanel">{parts}</div>'


def _render_manage(current):
    st.markdown('<div class="wb-mng-h">관심종목 관리</div>', unsafe_allow_html=True)
    st.caption("쉼표로 구분 · 최대 20개 · KRX 상장명과 정확히 일치해야 시세가 떠요 "
               "(예: 삼성전자, SK하이닉스, 현대차). 저장하면 Supabase DB에 보관돼 재시작에도 사라지지 않아요.")
    text = st.text_input(
        "관심 종목", value=", ".join(current),
        placeholder="예: 삼성전자, SK하이닉스, 현대차",
        key="wb_input", label_visibility="collapsed")
    if st.button("저장", key="wb_save"):
        try:
            saved = save_watchlist(text.split(","))
            st.success(f"{len(saved)}개 종목 저장 완료 — 브리핑·키워드·다음 리포트에 바로 반영돼요.")
            st.rerun()
        except Exception as e:
            st.error(f"저장 실패: {e} · SUPABASE 설정과 watchlist 테이블을 확인하세요.")


def render_watchlist_tab():
    st.markdown(_WB_CSS, unsafe_allow_html=True)
    st.markdown('<div class="wb-bar"></div>', unsafe_allow_html=True)
    st.title("관심 종목")

    wl = load_watchlist()

    if not wl:
        st.markdown(
            '<div class="empty"><div class="ico">⭐</div>'
            '<div class="msg">아직 관심종목이 없어요</div>'
            '<div class="hint">아래에서 종목을 추가하면 지수 탭과 같은 양식의 차트와 그 이유가 떠요</div></div>',
            unsafe_allow_html=True)
        st.divider()
        _render_manage(wl)
        return

    rows, asof = _build_rows(wl)

    # 요약 띠 (오늘 기준 — 기간 선택과 무관)
    prices = [r["pct"] for r in rows if r["pct"] is not None]
    n_rpt = sum(len(r["rpt"]) for r in rows)
    n_kw = sum(len(r["kw"]) for r in rows)
    if prices:
        avg = sum(prices) / len(prices)
        n_up = sum(1 for p in prices if p > 0)
        n_dn = sum(1 for p in prices if p < 0)
        avg_cls = "up" if avg >= 0 else "down"
        avg_txt = f'<b class="{avg_cls}">{avg:+.2f}%</b>'
        strip = (f'오늘 평균 {avg_txt} · {n_up} 상승 {n_dn} 하락 · '
                 f'리포트 언급 <b>{n_rpt}건</b> · 키워드 언급 <b>{n_kw}건</b>')
    else:
        strip = (f'시세를 불러오지 못했어요(장외·휴장·일시 오류일 수 있어요). · '
                 f'리포트 언급 <b>{n_rpt}건</b> · 키워드 언급 <b>{n_kw}건</b>')
    st.markdown(f'<div class="wb-strip">{strip}</div>', unsafe_allow_html=True)

    # 공용 기간 선택 (지수 탭과 동일)
    period_label = st.radio(
        "조회 기간", list(_PERIODS.keys()), index=3, horizontal=True,
        key="wb_chart_period", label_visibility="collapsed")
    is_intraday = (period_label == "1일")
    days = _PERIODS[period_label]

    # 종목별: [큰 차트 | 근거 패널]
    for i, r in enumerate(rows):
        c1, c2 = st.columns([1.7, 1], gap="medium")
        with c1:
            if is_intraday:
                _big_stock_chart_intraday(r)
            else:
                _big_stock_chart(r, days)
        with c2:
            st.markdown(_refs_html(r), unsafe_allow_html=True)
        if i < len(rows) - 1:
            st.markdown('<div class="wb-div"></div>', unsafe_allow_html=True)

    asof_txt = f" · 시세 기준 {_fmt_asof(asof)}" if asof else ""
    news_note = ("최근 뉴스=전영업일 장마감(15:30)~현재 네이버 종목 뉴스 중 관련도·최신순 3개 · ")
    if is_intraday:
        st.caption("당일(휴장 시 직전 거래일) 5분봉 · 전일 종가 대비 등락(회색 점선=전일 종가) · "
                   "종목명 클릭=네이버 시세 · ⭐=관심종목 · 근거=오늘 리포트/키워드에서 이 종목을 짚은 항목 · "
                   + news_note +
                   "yfinance 기준 약 15분 지연이며 일부 누락될 수 있어요." + asof_txt)
    else:
        st.caption("차트 위에 마우스를 올리면 해당 시점·값이 십자선으로 표시되고, 가로 드래그로 기간을 확대할 수 있어요 "
                   "(지수 탭과 동일). · 종목명 클릭=네이버 시세 · ⭐=관심종목 · "
                   "근거=오늘 리포트/키워드에서 이 종목을 짚은 항목 · "
                   + news_note +
                   "일부 종목은 네이버 폴백 시 약 3개월까지만 표시될 수 있어요." + asof_txt)

    st.divider()
    _render_manage(wl)
