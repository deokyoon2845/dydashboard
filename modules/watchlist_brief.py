"""[뷰어] 관심 종목 탭 — 내 종목 브리핑 + 관심종목 관리.

브리핑: 워치리스트 종목별로
  · 오늘 등락(pykrx 종가·등락률)
  · '왜 움직였나' (오늘 리포트 토픽 / 키워드에서 이 종목을 짚은 항목)
  · 리포트·키워드 칩
관리: 같은 탭 하단에서 관심종목 추가·삭제(쉼표 구분). 저장은 Supabase DB(영속).

데이터는 전부 앱에 이미 있는 소스만 사용한다(새 스크래핑 없음):
  · 가격/등락 = pykrx (종목명→코드 매핑도 pykrx로 구성, 일 단위 캐시)
  · 리포트 토픽 = Supabase DB의 최신 보고서 topics[].stocks
  · 키워드 = data/keywords_today.json items[].stocks (GitHub Actions가 커밋 → 영속)

수급 칩은 앱의 수급 데이터가 '시장 전체 상위 종목'만이라 일반 관심종목엔 안 붙인다.
"""

import html
import json
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

from modules.stocks import naver_stock_url
from modules.watchlist import load_watchlist, save_watchlist

_KW_PATH = Path("data/keywords_today.json")

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
.wb-why{font-size:12px;color:var(--muted,#9a9b92);margin-top:4px;line-height:1.5;word-break:keep-all;}
.wb-right{text-align:right;flex:none;}
.wb-val{font-size:16px;font-weight:700;color:var(--ink,#34352f);letter-spacing:-.02em;}
.wb-chg{font-size:12.5px;font-weight:700;margin-top:2px;}
.wb-chg.up{color:var(--up,#B65F5A);} .wb-chg.down{color:var(--down,#5A7CA0);}
.wb-na{font-size:11.5px;color:var(--muted,#9a9b92);margin-top:3px;}
.wb-chips{display:flex;flex-wrap:wrap;gap:5px;margin-top:10px;}
.wb-chip{font-size:10.5px;font-weight:600;padding:3px 8px;border-radius:7px;border:1px solid var(--line,#ECEDE7);
  background:var(--pill-bg,#F1F2EC);color:var(--pill-ink,#5d6258);word-break:keep-all;}
.wb-chip.rpt{background:#eef4ef;color:var(--sage-deep,#7E9A83);border-color:#dfe9e0;}
.wb-mng-h{font-size:12px;font-weight:700;letter-spacing:.05em;color:var(--muted,#9a9b92);margin:6px 0 8px;text-transform:uppercase;}
</style>
"""


def _norm(s: str) -> str:
    return "".join(str(s).split()).casefold()


# ── 가격: pykrx 종목명→코드 맵(일 단위) + 종가·등락률 스냅샷(10분) ──

@st.cache_data(ttl=86400)
def _name_code_map() -> dict:
    """정규화 종목명 → 종목코드. pykrx 기준. 최근 거래일을 찾아 구성."""
    from pykrx import stock
    today = date.today()
    for back in range(0, 8):
        d = (today - timedelta(days=back)).strftime("%Y%m%d")
        m, ok = {}, False
        for mkt in ("KOSPI", "KOSDAQ"):
            try:
                codes = stock.get_market_ticker_list(d, market=mkt)
            except Exception:
                codes = []
            if codes:
                ok = True
            for code in codes:
                try:
                    m[_norm(stock.get_market_ticker_name(code))] = str(code)
                except Exception:
                    continue
        if ok and m:
            return m
    return {}


@st.cache_data(ttl=600)
def _price_snapshot():
    """종목코드 → (종가, 등락률%). 최근 거래일 1일치 전 종목 스냅샷. 반환 (dict, 'YYYYMMDD')."""
    from pykrx import stock
    import pandas as pd
    today = date.today()
    for back in range(0, 8):
        d = (today - timedelta(days=back)).strftime("%Y%m%d")
        try:
            frames = []
            for mkt in ("KOSPI", "KOSDAQ"):
                df = stock.get_market_ohlcv(d, market=mkt)
                if df is not None and not df.empty:
                    frames.append(df)
            if not frames:
                continue
            allc = pd.concat(frames)
            price = {}
            for code, row in allc.iterrows():
                try:
                    price[str(code)] = (float(row["종가"]), float(row["등락률"]))
                except Exception:
                    continue
            if price:
                return price, d
        except Exception:
            continue
    return {}, ""


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
    try:
        name_code = _name_code_map()
    except Exception:
        name_code = {}
    try:
        price, asof = _price_snapshot()
    except Exception:
        price, asof = {}, ""

    report = _latest_report()
    topics = (report.get("topics") if report else None) or []
    keywords = _today_keywords()

    rows = []
    for name in watchlist:
        nn = _norm(name)
        code = name_code.get(nn)
        close, pct = (None, None)
        if code and code in price:
            close, pct = price[code]

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

        rows.append({"name": name, "code": code, "close": close, "pct": pct,
                     "why": why, "rpt": rpt[:2], "kw": kw[:2]})
    return rows, asof


def _trunc(s, n=16):
    s = str(s)
    return s if len(s) <= n else s[:n] + "…"


def _card_html(r) -> str:
    nm = html.escape(r["name"])
    if r["code"]:
        name_inner = (f'<a href="{html.escape(naver_stock_url(r["name"]))}" '
                      f'target="_blank" rel="noopener">⭐ {nm}</a>')
    else:
        name_inner = f'⭐ {nm}'

    if r["close"] is not None and r["pct"] is not None:
        up = r["pct"] >= 0
        cls = "up" if up else "down"
        arrow = "▲" if r["pct"] > 0 else ("▼" if r["pct"] < 0 else "▬")
        price_html = (f'<div class="wb-val">{r["close"]:,.0f}</div>'
                      f'<div class="wb-chg {cls}">{arrow} {r["pct"]:+.2f}%</div>')
    elif r["code"]:
        price_html = '<div class="wb-na">시세 조회 실패</div>'
    else:
        price_html = '<div class="wb-na">코드 미확인</div>'

    chips = ""
    for i, t in r["rpt"]:
        chips += f'<span class="wb-chip rpt">리포트 {i} · {html.escape(_trunc(t))}</span>'
    for i, k in r["kw"]:
        chips += f'<span class="wb-chip">키워드 {i} · {html.escape(_trunc(k))}</span>'
    chips_html = f'<div class="wb-chips">{chips}</div>' if chips else ""

    return (f'<div class="wb-card"><div class="wb-top">'
            f'<div><div class="wb-name">{name_inner}</div>'
            f'<div class="wb-why">{html.escape(r["why"])}</div></div>'
            f'<div class="wb-right">{price_html}</div></div>'
            f'{chips_html}</div>')


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
            '<div class="hint">아래에서 종목을 추가하면 오늘 등락과 그 이유가 카드로 떠요</div></div>',
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
    st.caption("종목명 클릭=네이버 시세 · ⭐=관심종목 · 칩=오늘 리포트 토픽/키워드에서 이 종목을 짚은 항목"
               + asof_txt + " · 일별 종가 기준(pykrx).")

    st.divider()
    _render_manage(wl)
