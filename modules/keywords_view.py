"""오늘의 키워드 뷰 — 카테고리·중요도·연속배지·인라인시세·아카이브.

데스크톱: 3열 그리드 카드 (TOP15 → 3×5) / 모바일: 1열로 자동 전환.
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
/* 3열 그리드 (데스크톱) → 좁아지면 2열 → 1열 */
.kw-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:6px;}
@media(max-width:900px){.kw-grid{grid-template-columns:repeat(2,1fr);}}
@media(max-width:600px){.kw-grid{grid-template-columns:1fr;}}

.kw-card{background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);border-radius:14px;
  padding:14px 15px;display:flex;flex-direction:column;gap:0;}
.kw-card-head{display:flex;align-items:center;gap:8px;margin-bottom:7px;}
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
.kw-wbar{height:4px;border-radius:3px;background:var(--line,#ECEDE7);margin:0 0 9px;overflow:hidden;}
.kw-wbar>span{display:block;height:100%;background:var(--sage,#A7BBA9);border-radius:3px;}
.kw-stocks{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:9px;}
.kw-stk{font-size:11px;font-weight:600;text-decoration:none;background:var(--pill-bg,#F1F2EC);
  color:var(--pill-ink,#5d6258);border:1px solid var(--line,#ECEDE7);padding:2px 8px;border-radius:7px;}
.kw-stk .up{color:#B65F5A;} .kw-stk .down{color:#5A7CA0;} .kw-stk .flat{color:#9a9b92;}
.kw-news{margin-top:auto;}
.kw-news a{display:block;font-size:12px;line-height:1.45;color:var(--sage-deep,#7E9A83);
  text-decoration:none;margin-bottom:4px;padding-left:11px;position:relative;
  overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;}
.kw-news a:before{content:"›";position:absolute;left:0;color:var(--muted,#9a9b92);}
.kw-news a:hover{text-decoration:underline;}
.app.dark .cat-macro{background:#21303B;color:#9CC4DC;}
.app.dark .cat-sector{background:#243025;color:#A9C9AE;}
.app.dark .cat-stock{background:#332B1E;color:#D9BC8C;}
.app.dark .cat-policy{background:#2E2436;color:#C9A9D9;}
.app.dark .kw-streak{background:#3D2412;color:#F0A36B;}
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


def _stock_html(names, show_quote):
    """종목 pill — show_quote면 당일 등락률 인라인 표시."""
    parts = []
    fetch = None
    if show_quote:
        try:
            from modules.stock_quote import fetch_stock_change
            fetch = fetch_stock_change
        except Exception:
            fetch = None

    for n in names or []:
        n = (n or "").strip()
        if not n:
            continue
        label = html.escape(n)
        if fetch:
            q = fetch(n)
            if q and q.get("pct") is not None:
                pct = q["pct"]
                cls = "up" if pct > 0 else ("down" if pct < 0 else "flat")
                arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "·")
                label += f' <span class="{cls}">{arrow}{abs(pct):.1f}%</span>'
        parts.append(
            f'<a class="kw-stk" href="{html.escape(naver_stock_url(n))}" '
            f'target="_blank" rel="noopener">{label}</a>'
        )
    return f'<div class="kw-stocks">{"".join(parts)}</div>' if parts else ""


def _render_items(items, show_quote):
    cards = []
    for i, it in enumerate(items[:15], start=1):
        kw = html.escape(it.get("keyword", ""))
        cat = it.get("category", "")
        cat_html = (f'<span class="kw-cat {CAT_CLS.get(cat, "cat-sector")}">{html.escape(cat)}</span>'
                    if cat else "")
        streak = it.get("streak", 1)
        streak_html = f'<span class="kw-streak">🔥 {streak}일째</span>' if streak and streak >= 2 else ""

        weight = it.get("weight")
        wbar = ""
        if isinstance(weight, int):
            wbar = f'<div class="kw-wbar"><span style="width:{weight*10}%"></span></div>'

        stocks_html = _stock_html(it.get("stocks") or [], show_quote)

        news_list = it.get("news")
        if not news_list and it.get("news_url"):
            news_list = [{"title": it.get("news_title", ""), "url": it.get("news_url", "")}]
        news_html = ""
        if news_list:
            # 그리드 카드 높이 균일화를 위해 뉴스는 카드당 최대 2개
            links = "".join(
                f'<a href="{html.escape(n.get("url",""))}" target="_blank" rel="noopener">'
                f'{html.escape(n.get("title",""))} ↗</a>'
                for n in news_list[:2] if n.get("url"))
            news_html = f'<div class="kw-news">{links}</div>'

        cards.append(
            f'<div class="kw-card">'
            f'<div class="kw-card-head">'
            f'<span class="kw-rank">{i}</span>'
            f'<span class="kw-kw">{kw}</span>'
            f'{cat_html}{streak_html}</div>'
            f'{wbar}{stocks_html}{news_html}</div>'
        )
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
    show_quote = st.toggle("종목 당일 등락률 표시", value=False, key="kw_quote",
                           help="국내 종목의 당일 등락률을 인라인으로 보여줘요 (KRX 조회, 첫 로딩 느릴 수 있음)")
    st.caption(f"기준: {when} · 네이버 뉴스 기반")

    _render_items(data["items"], show_quote)
    st.caption("※ 키워드·종목·카테고리·중요도는 AI 추출, 링크는 네이버 뉴스 실제 기사. "
               "🔥 배지는 연속 등장 일수, 막대는 중요도. 뉴스는 카드당 2건 표시.")
