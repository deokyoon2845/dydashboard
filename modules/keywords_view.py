"""오늘의 키워드 뷰 — 카테고리·중요도·연속배지·NEW배지·워치리스트★·인라인종목·아카이브.

데스크톱: 2열 그리드 카드 (TOP15) / 모바일: 1열로 자동 전환.
뉴스 제목은 카드 높이 균일화를 위해 1줄로 표시(말줄임).
"""

import html
import json
from datetime import date
from pathlib import Path

import streamlit as st

from modules.stocks import naver_stock_url

KW_PATH = Path("data/keywords_today.json")
KW_ARCHIVE_DIR = Path("data/keywords_archive")

CAT_CLS = {"거시": "cat-macro", "섹터": "cat-sector", "종목": "cat-stock", "정책": "cat-policy"}

_KW_CSS = """
<style>
/* 2열 그리드 (데스크톱) → 좁아지면 1열 */
.kw-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-top:6px;}
@media(max-width:680px){.kw-grid{grid-template-columns:1fr;}}

.kw-card{background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);border-radius:14px;
  padding:14px 15px;display:flex;flex-direction:column;gap:0;}
.kw-card.kw-watchcard{border-left:3px solid #D9A93C;}
.kw-card-head{display:flex;align-items:center;gap:8px;margin-bottom:7px;flex-wrap:wrap;}
.kw-rank{font-family:'Fraunces','Noto Sans KR',Georgia,serif;font-size:18px;font-weight:600;
  color:var(--sage-deep,#7E9A83);min-width:20px;line-height:1;}
.kw-kw{font-size:14.5px;font-weight:700;color:var(--ink,#34352f);flex:1;min-width:0;
  word-break:keep-all;line-height:1.35;}
.kw-cat{font-size:10px;font-weight:700;padding:2px 7px;border-radius:5px;letter-spacing:.02em;flex:none;}
.cat-macro{background:#E6F0F6;color:#2C5F7C;}
.cat-sector{background:#EBF3EC;color:#4A6B4F;}
.cat-stock{background:#F3EEE6;color:#7C5F2C;}
.cat-policy{background:#F0E9F3;color:#6B4A7C;}
.kw-streak{font-size:9.5px;font-weight:700;color:#C2410C;background:#FDEEE3;padding:2px 6px;border-radius:5px;flex:none;}
.kw-new{font-size:9.5px;font-weight:700;color:#0f6e56;background:#e1f5ee;padding:2px 6px;border-radius:5px;flex:none;}
.kw-watch{font-size:11px;flex:none;}
.kw-wbar{height:4px;border-radius:3px;background:var(--line,#ECEDE7);margin:0 0 9px;overflow:hidden;}
.kw-wbar>span{display:block;height:100%;background:var(--sage,#A7BBA9);border-radius:3px;}
.kw-stocks{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:9px;}
.kw-stk{font-size:11px;font-weight:600;text-decoration:none;background:var(--pill-bg,#F1F2EC);
  color:var(--pill-ink,#5d6258);border:1px solid var(--line,#ECEDE7);padding:2px 8px;border-radius:7px;}
.kw-stk.kw-stk-watch{border-color:#D9A93C;}
.kw-news{margin-top:auto;}
/* 뉴스 제목: 1줄 고정 + 말줄임 (카드 높이 균일) */
.kw-news a{display:block;font-size:12px;line-height:1.5;color:var(--sage-deep,#7E9A83);
  text-decoration:none;margin-bottom:5px;padding-left:11px;position:relative;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.kw-news a:before{content:"›";position:absolute;left:0;color:var(--muted,#9a9b92);}
.kw-news a:hover{text-decoration:underline;}
.kw-weak{font-size:10.5px;color:var(--muted,#9a9b92);margin-top:6px;}

/* ── 마이크로 인터랙션 (미니멀 미스트) ── */
/* 카드 등장: 페이드+슬라이드업, 그리드 순서대로 시차 */
@keyframes kw-fade-up{from{opacity:0;transform:translateY(10px);}to{opacity:1;transform:translateY(0);}}
.kw-card{animation:kw-fade-up .5s cubic-bezier(.22,.61,.36,1) both;
  transition:transform .2s ease,box-shadow .2s ease,border-color .2s ease;}
.kw-grid .kw-card:nth-child(1){animation-delay:.02s;}
.kw-grid .kw-card:nth-child(2){animation-delay:.05s;}
.kw-grid .kw-card:nth-child(3){animation-delay:.08s;}
.kw-grid .kw-card:nth-child(4){animation-delay:.11s;}
.kw-grid .kw-card:nth-child(5){animation-delay:.14s;}
.kw-grid .kw-card:nth-child(6){animation-delay:.17s;}
.kw-grid .kw-card:nth-child(7){animation-delay:.20s;}
.kw-grid .kw-card:nth-child(8){animation-delay:.23s;}
.kw-grid .kw-card:nth-child(9){animation-delay:.26s;}
.kw-grid .kw-card:nth-child(10){animation-delay:.29s;}
.kw-grid .kw-card:nth-child(11){animation-delay:.32s;}
.kw-grid .kw-card:nth-child(12){animation-delay:.35s;}
.kw-grid .kw-card:nth-child(13){animation-delay:.38s;}
.kw-grid .kw-card:nth-child(14){animation-delay:.41s;}
.kw-grid .kw-card:nth-child(15){animation-delay:.44s;}
/* 호버: 살짝 떠오름 + sage 테두리 */
.kw-card:hover{transform:translateY(-2px);box-shadow:0 6px 18px rgba(52,53,47,.08);
  border-color:var(--sage,#A7BBA9);}
.kw-card.kw-watchcard:hover{border-color:#D9A93C;}
/* 중요도 바: 0→목표폭 채우기 */
@keyframes kw-bar-grow{from{transform:scaleX(0);}to{transform:scaleX(1);}}
.kw-wbar>span{transform-origin:left center;
  animation:kw-bar-grow .8s cubic-bezier(.22,.61,.36,1) .25s both;}
/* 뉴스 링크 호버: 화살표 살짝 밀림 */
.kw-news a{transition:color .15s ease,padding-left .15s ease;}
.kw-news a:hover{padding-left:14px;}
/* 종목 pill 호버 */
.kw-stk{transition:transform .15s ease,box-shadow .15s ease,border-color .15s ease;}
.kw-stk:hover{transform:translateY(-1px);box-shadow:0 2px 6px rgba(52,53,47,.08);
  border-color:var(--sage,#A7BBA9);}
@media(prefers-reduced-motion:reduce){
  .kw-card,.kw-wbar>span{animation:none !important;}
  .kw-card,.kw-news a,.kw-stk{transition:none !important;}
}
</style>
"""


def _load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _archive_dates():
    if not KW_ARCHIVE_DIR.exists():
        return []
    out = []
    for f in sorted(KW_ARCHIVE_DIR.glob("*.json"), reverse=True):
        try:
            y, m, d = f.stem.split("-")
            out.append((date(int(y), int(m), int(d)), f))
        except ValueError:
            continue
    return out


def _norm_name(s: str) -> str:
    return "".join(str(s).split()).casefold()


def _watch_set() -> set:
    """워치리스트 종목명 (정규화). 실패 시 빈 set."""
    try:
        from modules.watchlist import load_watchlist
        return {_norm_name(s) for s in load_watchlist()}
    except Exception:
        return set()


def _stock_html(names, watch_set):
    """종목 pill — 이름 + 네이버 시세 링크. 워치리스트 종목은 ★ 테두리."""
    parts = []
    for n in names or []:
        n = (n or "").strip()
        if not n:
            continue
        is_watch = _norm_name(n) in watch_set
        label = ("⭐ " if is_watch else "") + html.escape(n)
        watch_cls = " kw-stk-watch" if is_watch else ""
        parts.append(
            f'<a class="kw-stk{watch_cls}" href="{html.escape(naver_stock_url(n))}" '
            f'target="_blank" rel="noopener">{label}</a>'
        )
    return f'<div class="kw-stocks">{"".join(parts)}</div>' if parts else ""


def _render_items(items, watch_set):
    cards = []
    for i, it in enumerate(items[:15], start=1):
        cat = it.get("category", "")
        kw = html.escape(it.get("keyword", ""))
        cat_html = (f'<span class="kw-cat {CAT_CLS.get(cat, "cat-sector")}">{html.escape(cat)}</span>'
                    if cat else "")
        streak = it.get("streak", 1)
        streak_html = f'<span class="kw-streak">🔥 {streak}일째</span>' if streak and streak >= 2 else ""
        new_html = '<span class="kw-new">NEW</span>' if it.get("is_new") else ""

        # 워치리스트 종목이 엮인 키워드는 카드 강조
        stocks = it.get("stocks") or []
        has_watch = any(_norm_name(s) in watch_set for s in stocks)
        watch_html = '<span class="kw-watch">⭐</span>' if has_watch else ""
        card_cls = "kw-card kw-watchcard" if has_watch else "kw-card"

        weight = it.get("weight")
        wbar = ""
        if isinstance(weight, int):
            wbar = f'<div class="kw-wbar"><span style="width:{weight*10}%"></span></div>'

        stocks_html = _stock_html(stocks, watch_set)

        news_list = it.get("news")
        if not news_list and it.get("news_url"):
            news_list = [{"title": it.get("news_title", ""), "url": it.get("news_url", "")}]
        news_html = ""
        n_news = len([n for n in (news_list or []) if n.get("url")])
        if news_list:
            # 그리드 카드 높이 균일화를 위해 뉴스는 카드당 최대 2개
            links = "".join(
                f'<a href="{html.escape(n.get("url",""))}" target="_blank" rel="noopener">'
                f'{html.escape(n.get("title",""))} ↗</a>'
                for n in news_list[:2] if n.get("url"))
            news_html = f'<div class="kw-news">{links}</div>'
        if n_news == 0:
            weak_html = '<div class="kw-weak">대표 기사 없음 — 상위 키워드와 겹치는 주제일 수 있어요</div>'
        elif n_news == 1:
            weak_html = '<div class="kw-weak">근거 기사 1건 — 참고만 하세요</div>'
        else:
            weak_html = ""

        cards.append(
            f'<div class="{card_cls}">'
            f'<div class="kw-card-head">'
            f'<span class="kw-rank">{i}</span>'
            f'<span class="kw-kw">{kw}</span>'
            f'{watch_html}{cat_html}{new_html}{streak_html}</div>'
            f'{wbar}{stocks_html}{news_html}{weak_html}</div>'
        )

    if not cards:
        st.caption("표시할 키워드가 없어요.")
        return
    st.markdown(f'<div class="kw-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def render_keywords():
    st.markdown(_KW_CSS, unsafe_allow_html=True)
    st.markdown('<div class="rpt-bar"></div>', unsafe_allow_html=True)
    st.title("오늘의 키워드")

    if st.button("🔄 키워드 갱신"):
        with st.spinner("네이버 뉴스 수집 → 키워드 추출 중..."):
            try:
                from engine.keywords import build_today_keywords
                res = build_today_keywords()
            except Exception as e:
                res = {"ok": False, "reason": str(e)}
        if res.get("ok"):
            st.success(f"키워드 {res.get('count', '')}개를 갱신했어요.")
            st.rerun()
        else:
            st.warning(f"갱신 실패 · {res.get('reason')}")

    # 아카이브 날짜 선택
    archive = _archive_dates()
    data, when = None, ""
    if archive:
        labels = {str(f): (f"{d:%Y-%m-%d}" + (" (오늘)" if d == date.today() else ""))
                  for d, f in archive}
        opts = [str(f) for _, f in archive]
        pick = st.selectbox("날짜 선택", options=opts,
                            format_func=lambda s: labels[s], key="kw_date")
        data = _load(Path(pick))
    else:
        data = _load(KW_PATH)

    if not data or not data.get("items"):
        st.markdown(
            '<div class="empty"><div class="ico">🔑</div>'
            '<div class="msg">아직 키워드가 없어요</div>'
            '<div class="hint">"🔄 키워드 갱신"을 눌러 오늘의 키워드를 불러오세요</div></div>',
            unsafe_allow_html=True)
        return

    when = str(data.get("generated", ""))[:16].replace("T", " ")
    st.caption(f"기준: {when} · 네이버 뉴스 기반")

    # 관계 그래프 (공통 종목·공통 키워드로 연결) — 항상 표시
    st.markdown('<div class="mkt-group">🕸️ 키워드 관계 — 오늘 시장이 무엇을 중심으로 도는가</div>',
                unsafe_allow_html=True)
    try:
        from modules.keyword_graph import render_keyword_graph
        render_keyword_graph(data["items"])
    except Exception as e:
        st.caption(f"관계 그래프를 그릴 수 없어요 · {e}")

    watch_set = _watch_set()
    _render_items(data["items"], watch_set)
    st.caption("※ 키워드·종목·카테고리·중요도는 AI 추출, 링크는 네이버 뉴스 실제 기사. "
               "🔥 = 연속 등장 일수, NEW = 오늘 첫 등장, ⭐ = 내 워치리스트 종목 포함, "
               "막대 = 중요도. 뉴스는 카드당 2건 표시.")
