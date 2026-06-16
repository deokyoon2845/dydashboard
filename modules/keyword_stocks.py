"""오늘의 키워드 TOP15 → 종목 언급 랭킹 (키워드 네트워크 그래프 대체).

점수 = Σ (그 종목을 태그한 키워드의 중요도 weight) × (1 + 연속일 가산)
  · keywords_today.json 스키마(keyword / category / weight / streak / stocks) 그대로 사용
  · 별도 데이터 생성 없음 — TOP15에 이미 붙은 stocks 태그만 재집계
  · 종목명은 네이버 시세로 링크, 워치리스트 종목은 ⭐ + 진한 세이지로 강조
  · 각 종목 아래 칩 = 그 종목을 지목한 키워드(#순위) → TOP15와의 연관성 표시

외부 패키지 없음. keywords_view.render_keywords() 안에서 호출.
"""

import html

import streamlit as st

from modules.stocks import naver_stock_url

# 카테고리 색 (keyword_graph / keywords_view 와 동일 톤)
_CAT_COLOR = {
    "거시": "#2C5F7C", "섹터": "#4A6B4F", "종목": "#7C5F2C", "정책": "#6B4A7C",
}
_CAT_DEFAULT = "#7E9A83"

STREAK_BONUS = 0.05   # 연속 등장(🔥) 하루당 +5%. 0으로 두면 순수 중요도(weight) 가중.


def _norm(s: str) -> str:
    return "".join(str(s).split()).casefold()


def _watch_set() -> set:
    try:
        from modules.watchlist import load_watchlist
        return {_norm(s) for s in load_watchlist()}
    except Exception:
        return set()


def aggregate_stocks(items, watch_set=None):
    """TOP15 키워드(items) → 점수순으로 정렬된 종목 dict 리스트."""
    watch_set = watch_set or set()
    agg = {}  # stock -> {score, count, sources}

    for idx, it in enumerate(items, start=1):
        title  = (it.get("keyword") or "").strip()
        weight = it.get("weight")
        weight = weight if isinstance(weight, (int, float)) and weight > 0 else 5
        cat    = (it.get("category") or "").strip()
        try:
            streak = int(it.get("streak") or 1)
        except (TypeError, ValueError):
            streak = 1

        w = weight * (1 + STREAK_BONUS * max(streak - 1, 0))

        for raw in (it.get("stocks") or []):
            name = str(raw).replace("⭐", "").strip()
            if not name:
                continue
            r = agg.setdefault(name, {"score": 0.0, "count": 0, "sources": []})
            r["score"] += w
            r["count"] += 1
            r["sources"].append({"rank": idx, "title": title, "cat": cat, "weight": weight})

    rows = []
    for name, r in agg.items():
        rows.append({
            "stock":    name,
            "score":    round(r["score"], 1),
            "count":    r["count"],
            "is_watch": _norm(name) in watch_set,
            "sources":  sorted(r["sources"], key=lambda s: -s["weight"]),
        })
    rows.sort(key=lambda x: (-x["score"], -x["count"], not x["is_watch"]))
    return rows


_CSS = """
<style>
.ks-wrap{margin:4px 0 2px;}
.ks-summary{font-size:12px;color:var(--muted,#9a9b92);margin:0 0 12px;}
.ks-summary b{color:var(--ink,#34352f);}
.ks-row{padding:11px 2px;border-bottom:1px solid var(--line,#ECEDE7);
  animation:ks-fade .5s cubic-bezier(.22,.61,.36,1) both;}
.ks-row:last-child{border-bottom:none;}
@keyframes ks-fade{from{opacity:0;transform:translateY(8px);}to{opacity:1;transform:translateY(0);}}
.ks-head{display:flex;align-items:baseline;gap:8px;}
.ks-rank{font-family:'Fraunces','Noto Sans KR',serif;font-size:18px;font-weight:600;
  color:var(--sage-deep,#7E9A83);min-width:22px;text-align:center;flex:none;line-height:1;}
.ks-name{font-size:15px;font-weight:700;text-decoration:none;color:var(--ink,#34352f);}
.ks-name:hover{text-decoration:underline;}
.ks-star{color:#D9A93C;}
.ks-meta{margin-left:auto;font-size:11.5px;color:var(--muted,#9a9b92);
  white-space:nowrap;flex:none;}
.ks-bar{height:6px;border-radius:4px;background:var(--line,#ECEDE7);
  margin:7px 0 7px 30px;overflow:hidden;}
.ks-bar>span{display:block;height:100%;border-radius:4px;transform-origin:left center;
  animation:ks-grow .8s cubic-bezier(.22,.61,.36,1) .2s both;}
@keyframes ks-grow{from{transform:scaleX(0);}to{transform:scaleX(1);}}
.ks-src{margin-left:30px;display:flex;flex-wrap:wrap;gap:5px;align-items:center;}
.ks-chip{font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:6px;
  color:#fff;opacity:.92;}
.ks-more{font-size:10.5px;color:var(--muted,#9a9b92);}
@media(prefers-reduced-motion:reduce){.ks-row,.ks-bar>span{animation:none !important;}}
</style>
"""


def render_stock_ranking(items, watch_set=None, top_n=12):
    """TOP15 키워드 → 종목 무게중심 랭킹을 그린다."""
    if watch_set is None:
        watch_set = _watch_set()
    rows = aggregate_stocks(items, watch_set)

    st.markdown(
        '<div class="mkt-group">🎯 오늘의 종목 무게중심 — 키워드가 가장 많이 지목한 종목</div>',
        unsafe_allow_html=True)

    if not rows:
        st.caption("오늘 키워드에 태그된 종목이 없어요. "
                   "키워드 생성 시 종목을 함께 뽑으면 이 랭킹이 채워집니다.")
        return

    st.markdown(_CSS, unsafe_allow_html=True)

    # 요약 한 줄 (그래프의 '오늘의 허브'를 대체하는 즉답형 인사이트)
    n_kw_with_stock = sum(1 for it in items if (it.get("stocks") or []))
    top = rows[0]
    st.markdown(
        f'<div class="ks-summary">키워드 {len(items)}개 중 {n_kw_with_stock}개가 '
        f'{len(rows)}개 종목을 지목 · 최다 가중 <b>{html.escape(top["stock"])}</b> '
        f'(점수 {top["score"]})</div>', unsafe_allow_html=True)

    rows = rows[:top_n]
    max_score = max(r["score"] for r in rows) or 1

    blocks = []
    for i, r in enumerate(rows, 1):
        star  = '<span class="ks-star">⭐</span> ' if r["is_watch"] else ""
        url   = html.escape(naver_stock_url(r["stock"]))
        bar_w = max(4, int(r["score"] / max_score * 100))
        bar_c = "var(--sage-deep,#7E9A83)" if r["is_watch"] else "var(--sage,#A7BBA9)"

        chips = ""
        for s in r["sources"][:4]:
            c = _CAT_COLOR.get(s["cat"], _CAT_DEFAULT)
            t = s["title"]
            short = t if len(t) <= 13 else t[:12] + "…"
            chips += (f'<span class="ks-chip" style="background:{c}">'
                      f'#{s["rank"]} {html.escape(short)}</span>')
        more = (f'<span class="ks-more">+{len(r["sources"]) - 4}</span>'
                if len(r["sources"]) > 4 else "")

        blocks.append(
            f'<div class="ks-row">'
            f'<div class="ks-head">'
            f'<span class="ks-rank">{i}</span>'
            f'<a class="ks-name" href="{url}" target="_blank" rel="noopener">'
            f'{star}{html.escape(r["stock"])}</a>'
            f'<span class="ks-meta">점수 {r["score"]} · 언급 {r["count"]}회</span>'
            f'</div>'
            f'<div class="ks-bar"><span style="width:{bar_w}%;background:{bar_c}"></span></div>'
            f'<div class="ks-src">{chips}{more}</div>'
            f'</div>'
        )
    st.markdown(f'<div class="ks-wrap">{"".join(blocks)}</div>', unsafe_allow_html=True)

    if len(rows) < 3:
        st.caption("ⓘ 태그된 종목이 적어요. 키워드 생성 프롬프트에서 키워드마다 "
                   "관련 종목을 1~3개 뽑게 하면 랭킹이 풍부해집니다.")
