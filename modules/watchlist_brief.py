"""[뷰어] 관심 종목 브리핑 + 관심종목 관리 (키워드 탭 하단에 표시).

브리핑: 워치리스트 종목별로
  · 오늘 등락(현재가·등락률) + 오늘자 미니차트
  · '왜 움직였나' (오늘 리포트 토픽 / 키워드에서 이 종목을 짚은 항목)
  · 리포트·키워드 근거(한 줄에 하나씩, 말줄임 없음)
관리: 같은 섹션 하단에서 관심종목 추가·삭제(쉼표 구분). 저장은 Supabase DB(영속).

시세·차트 데이터 경로 (★pykrx 제거 — KRX가 클라우드 IP를 영구 차단하기 때문):
  · 종목명 → 종목코드(+시장)   : 네이버 자동완성 API (ac.stock.naver.com)
  · 가격/등락/미니차트         : yfinance(fetch_intraday→오늘, fetch_history→일별)
                                  실패 시 네이버 siseJson(일별)로 폴백
  · 리포트 토픽 = Supabase DB의 최신 보고서 topics[].stocks
  · 키워드 = data/keywords_today.json items[].stocks
"""

import html
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

from modules.stocks import naver_stock_url
from modules.watchlist import load_watchlist, save_watchlist
from modules.indices import fetch_intraday, fetch_history, sparkline_points

_KW_PATH = Path("data/keywords_today.json")
_KST = ZoneInfo("Asia/Seoul")
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/124.0 Safari/537.36"}

_WB_CSS = """
<style>
.wb-bar{height:3px;width:30px;background:var(--sage,#A7BBA9);border-radius:3px;margin:0 0 12px;}
.wb-strip{background:var(--summary-bg,#F6F7F2);border:1px solid var(--line,#ECEDE7);border-radius:10px;
  padding:9px 13px;font-size:12.5px;color:var(--sage-deep,#7E9A83);font-weight:600;margin:2px 0 14px;line-height:1.65;}
.wb-strip b{color:var(--ink,#34352f);font-weight:700;}
.wb-strip b.up{color:var(--up,#B65F5A);} .wb-strip b.down{color:var(--down,#5A7CA0);}
.wb-list{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;}
@media(max-width:680px){.wb-list{grid-template-columns:1fr;}}
.wb-card{background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);border-left:3px solid var(--sage,#A7BBA9);
  border-radius:0 14px 14px 0;padding:13px 15px;transition:transform .2s ease,box-shadow .2s ease,border-color .2s ease;}
.wb-card:hover{transform:translateY(-2px);box-shadow:0 6px 18px rgba(52,53,47,.08);border-color:var(--sage-deep,#7E9A83);}
.wb-top{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;}
.wb-name{font-size:15px;font-weight:700;color:var(--ink,#34352f);}
.wb-name a{color:var(--ink,#34352f);text-decoration:none;}
.wb-name a:hover{text-decoration:underline;}
.wb-right{text-align:right;flex:none;}
.wb-val{font-size:16px;font-weight:700;color:var(--ink,#34352f);letter-spacing:-.02em;}
.wb-chg{font-size:12.5px;font-weight:700;margin-top:2px;}
.wb-chg.up{color:var(--up,#B65F5A);} .wb-chg.down{color:var(--down,#5A7CA0);}
.wb-na{font-size:11.5px;color:var(--muted,#9a9b92);margin-top:3px;}
/* 오늘자 미니차트 */
.wb-spark{width:100%;height:30px;display:block;margin:9px 0 2px;}
.wb-why{font-size:12px;color:var(--muted,#9a9b92);margin-top:8px;line-height:1.55;word-break:keep-all;}
/* 근거: 한 줄에 하나씩, 말줄임 없이 전체 표시 */
.wb-refs{display:flex;flex-direction:column;gap:6px;margin-top:11px;}
.wb-ref{font-size:11.5px;font-weight:600;padding:6px 10px;border-radius:8px;border:1px solid var(--line,#ECEDE7);
  background:var(--pill-bg,#F1F2EC);color:var(--pill-ink,#5d6258);line-height:1.55;
  word-break:keep-all;white-space:normal;}
.wb-ref.rpt{background:#eef4ef;color:var(--sage-deep,#7E9A83);border-color:#dfe9e0;}
.wb-ref b{font-weight:700;}
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
    """네이버 siseJson 일별 종가. 반환 dict 또는 None."""
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


# ── 종목 시세 + 오늘자 미니차트 조회 ──

@st.cache_data(ttl=600)
def _quote(name: str):
    """종목명 → 시세/차트. 반환:
      {'code', 'close', 'pct', 'series', 'asof', 'intraday'} (코드 없으면 code=None).
    경로: 코드해석(네이버) → yfinance 분봉(오늘) → yfinance 일별 → 네이버 siseJson 일별.
    """
    code, suffix = _resolve_code(name)
    base = {"code": code, "close": None, "pct": None,
            "series": None, "asof": "", "intraday": False}
    if not code:
        return base

    cands = _suffix_candidates(code, suffix)

    # 1) yfinance 분봉(오늘) — '오늘자 미니차트'에 가장 적합
    for tk in cands:
        try:
            d = fetch_intraday(tk, "5m")
        except Exception:
            d = None
        if d and d.get("series") is not None and len(d["series"]) >= 2:
            base.update({"close": d.get("current"), "pct": d.get("pct"),
                         "series": d["series"],
                         "asof": datetime.now(_KST).strftime("%Y%m%d"),
                         "intraday": True})
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
            base.update({"close": cur, "pct": pct, "series": close,
                         "asof": asof, "intraday": False})
            return base

    # 3) 네이버 siseJson 일별 폴백
    nv = _naver_daily(code)
    if nv:
        base.update(nv)
    return base


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


# ── 행(카드) 데이터 빌드 ──

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
            "series": q.get("series"), "intraday": q.get("intraday"),
            "why": why, "rpt": rpt[:2], "kw": kw[:2],
        })
    asof = max(asofs) if asofs else ""
    return rows, asof


def _spark_svg(series, up: bool) -> str:
    """오늘자/최근 미니차트 SVG (지수 카드 sparkline과 동일 규격: 100x28)."""
    if series is None or len(series) < 2:
        return ""
    try:
        pts = sparkline_points(series, n=min(60, len(series)))
    except Exception:
        pts = ""
    if not pts:
        return ""
    v = "--up" if up else "--down"
    return (f'<svg class="wb-spark" viewBox="0 0 100 28" preserveAspectRatio="none">'
            f'<polygon points="{pts} 100,28 0,28" style="fill:var({v},#B65F5A);opacity:.10"/>'
            f'<polyline points="{pts}" style="fill:none;stroke:var({v},#B65F5A);stroke-width:1.6"/>'
            f'</svg>')


def _card_html(r) -> str:
    nm = html.escape(r["name"])
    if r["code"]:
        name_inner = (f'<a href="{html.escape(naver_stock_url(r["name"]))}" '
                      f'target="_blank" rel="noopener">⭐ {nm}</a>')
    else:
        name_inner = f'⭐ {nm}'

    has_price = r["close"] is not None and r["pct"] is not None
    if has_price:
        up = r["pct"] >= 0
        cls = "up" if up else "down"
        arrow = "▲" if r["pct"] > 0 else ("▼" if r["pct"] < 0 else "▬")
        price_html = (f'<div class="wb-val">{r["close"]:,.0f}</div>'
                      f'<div class="wb-chg {cls}">{arrow} {r["pct"]:+.2f}%</div>')
    elif r["code"]:
        up = True
        price_html = '<div class="wb-na">시세 조회 실패</div>'
    else:
        up = True
        price_html = '<div class="wb-na">코드 미확인</div>'

    spark_html = _spark_svg(r.get("series"), up) if has_price else ""

    # 근거: 한 줄에 하나씩, 말줄임 없이 전체 표시
    refs = ""
    for i, t in r["rpt"]:
        refs += f'<div class="wb-ref rpt"><b>리포트 {i}</b> · {html.escape(t)}</div>'
    for i, k in r["kw"]:
        refs += f'<div class="wb-ref"><b>키워드 {i}</b> · {html.escape(k)}</div>'
    refs_html = f'<div class="wb-refs">{refs}</div>' if refs else ""

    return (f'<div class="wb-card">'
            f'<div class="wb-top">'
            f'<div class="wb-name">{name_inner}</div>'
            f'<div class="wb-right">{price_html}</div>'
            f'</div>'
            f'{spark_html}'
            f'<div class="wb-why">{html.escape(r["why"])}</div>'
            f'{refs_html}</div>')


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
            '<div class="hint">아래에서 종목을 추가하면 오늘 등락·미니차트와 그 이유가 카드로 떠요</div></div>',
            unsafe_allow_html=True)
        st.divider()
        _render_manage(wl)
        return

    rows, asof = _build_rows(wl)

    # 요약 띠
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

    cards = "".join(_card_html(r) for r in rows)
    st.markdown(f'<div class="wb-list">{cards}</div>', unsafe_allow_html=True)

    asof_txt = f" · 시세 기준 {_fmt_asof(asof)}" if asof else ""
    st.caption("종목명 클릭=네이버 시세 · ⭐=관심종목 · 근거=오늘 리포트 토픽/키워드에서 이 종목을 짚은 항목 · "
               "미니차트=오늘(휴장 시 직전 거래일) 흐름" + asof_txt
               + " · 시세는 yfinance·네이버 기준 약 15분 지연.")

    st.divider()
    _render_manage(wl)
