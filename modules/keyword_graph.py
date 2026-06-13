"""오늘의 키워드 관계 그래프 — 공통 종목·같은 카테고리로 키워드를 잇는 SVG 네트워크.

연결 규칙:
  · 공통 종목 ≥ 1  → 진한 sage 실선 (겹치는 종목 수에 비례해 굵게)
  · 종목은 안 겹치나 같은 카테고리 → 아주 흐린 점선 (느슨한 맥락)

노드:
  · 크기 = weight(중요도, 1~10). 없으면 기본값
  · 색   = 카테고리(거시/섹터/종목/정책)
  · 금색 링 = 워치리스트 종목이 엮인 키워드

인터랙션(순수 CSS+약간의 JS):
  · 노드 hover → 연결된 노드·선만 강조, 나머지는 흐려짐
  · 노드 순차 등장 (미니멀 미스트 마이크로 인터랙션과 동일 톤)

외부 패키지 없음. st.markdown(SVG) 한 번으로 렌더.
"""

import html
import math

import streamlit as st

# 카테고리별 노드 색 (키워드 카드 cat 색과 같은 계열)
_CAT_COLOR = {
    "거시": "#2C5F7C",   # 파랑
    "섹터": "#4A6B4F",   # 초록(sage 계열)
    "종목": "#7C5F2C",   # 갈색/금
    "정책": "#6B4A7C",   # 보라
}
_CAT_DEFAULT = "#7E9A83"

_EDGE_STOCK = "#7E9A83"    # 공통 종목 선 (진한 sage)
_EDGE_CAT = "#C7CFC2"      # 같은 카테고리 선 (흐림)


def _norm(s: str) -> str:
    return "".join(str(s).split()).casefold()


def _watch_set() -> set:
    try:
        from modules.watchlist import load_watchlist
        return {_norm(s) for s in load_watchlist()}
    except Exception:
        return set()


def _build_graph(items, watch_set):
    """items → (nodes, edges).

    nodes: [{id,label,cat,color,weight,r,watch}]
    edges: [{a,b,kind,shared,width}]  kind: 'stock' | 'cat'
    """
    nodes = []
    for i, it in enumerate(items):
        kw = (it.get("keyword") or "").strip()
        if not kw:
            continue
        cat = (it.get("category") or "").strip()
        stocks = {_norm(s) for s in (it.get("stocks") or []) if s}
        w = it.get("weight")
        w = w if isinstance(w, int) and w > 0 else 5
        has_watch = bool(stocks & watch_set)
        nodes.append({
            "id": len(nodes),
            "label": kw,
            "cat": cat,
            "color": _CAT_COLOR.get(cat, _CAT_DEFAULT),
            "weight": w,
            "stocks": stocks,
            "watch": has_watch,
        })

    edges = []
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            a, b = nodes[i], nodes[j]
            shared = a["stocks"] & b["stocks"]
            if shared:
                edges.append({"a": i, "b": j, "kind": "stock",
                              "shared": len(shared),
                              "shared_names": sorted(shared)})
            elif a["cat"] and a["cat"] == b["cat"]:
                edges.append({"a": i, "b": j, "kind": "cat", "shared": 0})
    return nodes, edges


def _layout_circle(n, cx, cy, radius):
    """n개 노드를 원형으로 균등 배치. 12시 방향부터 시계방향."""
    pts = []
    for i in range(n):
        ang = -math.pi / 2 + (2 * math.pi * i / n)
        pts.append((cx + radius * math.cos(ang), cy + radius * math.sin(ang)))
    return pts


def _graph_css() -> str:
    return """
<style>
.kg-wrap{background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);
  border-radius:14px;padding:10px 8px 4px;margin:6px 0 4px;}
.kg-svg{width:100%;height:auto;display:block;}
.kg-edge{transition:opacity .18s ease,stroke-width .18s ease;}
.kg-node-g{cursor:default;}
.kg-node{transition:opacity .18s ease;
  transform-box:fill-box;transform-origin:center;
  animation:kg-pop .42s cubic-bezier(.34,1.56,.64,1) both;}
.kg-node-ring{transition:opacity .18s ease;}
.kg-label{font-family:'Hanken Grotesk','Noto Sans KR',sans-serif;
  font-weight:700;fill:var(--ink,#34352f);
  transition:opacity .18s ease;pointer-events:none;}
@keyframes kg-pop{from{opacity:0;transform:scale(.3);}to{opacity:1;transform:scale(1);}}

/* hover 강조: 흐려질 대상에 .kg-dim, 강조 대상에 .kg-hot 클래스를 JS가 토글 */
.kg-dim{opacity:.12 !important;}
.kg-edge.kg-hot{opacity:1 !important;}

/* 범례 */
.kg-legend{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;
  padding:8px 10px 6px;font-size:11px;color:var(--muted,#9a9b92);}
.kg-leg-item{display:inline-flex;align-items:center;gap:5px;}
.kg-dot{width:10px;height:10px;border-radius:50%;display:inline-block;}
.kg-line{width:18px;height:0;display:inline-block;border-top-width:2px;border-top-style:solid;}
.kg-line.cat{border-top-style:dashed;border-top-color:#C7CFC2;}
.kg-line.stk{border-top-color:#7E9A83;}
.kg-hint{font-size:10.5px;color:var(--muted,#9a9b92);padding:0 10px 8px;}

@media(prefers-reduced-motion:reduce){.kg-node{animation:none !important;}}
</style>
"""


def _graph_js() -> str:
    """노드 hover 시 연결된 것만 강조. 부모 문서에 위임 이벤트 1개만 건다."""
    return """
<script>
(function(){
  const doc = window.parent && window.parent.document ? window.parent.document : document;
  function setup(svg){
    if (svg.dataset.kgReady === '1') return;
    svg.dataset.kgReady = '1';
    const nodes = svg.querySelectorAll('.kg-node-g');
    const edges = svg.querySelectorAll('.kg-edge');
    const labels = svg.querySelectorAll('.kg-label');
    function clear(){
      svg.querySelectorAll('.kg-dim,.kg-hot').forEach(function(el){
        el.classList.remove('kg-dim','kg-hot');});
    }
    nodes.forEach(function(g){
      const id = g.getAttribute('data-id');
      g.addEventListener('mouseenter', function(){
        const linked = new Set([id]);
        edges.forEach(function(e){
          const a = e.getAttribute('data-a'), b = e.getAttribute('data-b');
          if (a===id || b===id){ e.classList.add('kg-hot');
            linked.add(a); linked.add(b); }
          else { e.classList.add('kg-dim'); }
        });
        nodes.forEach(function(nn){
          if (!linked.has(nn.getAttribute('data-id'))) nn.classList.add('kg-dim');
        });
        labels.forEach(function(lb){
          if (!linked.has(lb.getAttribute('data-id'))) lb.classList.add('kg-dim');
        });
      });
      g.addEventListener('mouseleave', clear);
    });
  }
  function scan(){ doc.querySelectorAll('svg.kg-svg').forEach(setup); }
  scan();
  const mo = new MutationObserver(scan);
  mo.observe(doc.body, {childList:true, subtree:true});
  setTimeout(function(){ mo.disconnect(); }, 4000);
})();
</script>
"""


def _svg(nodes, edges) -> str:
    W, H = 720, 460
    cx, cy = W / 2, H / 2 - 6
    n = len(nodes)
    radius = min(W, H) * 0.36
    pts = _layout_circle(n, cx, cy, radius)

    # 노드 반지름: weight 1~10 → 13~26px
    def node_r(w):
        return 13 + (max(1, min(10, w)) - 1) / 9 * 13

    parts = [f'<svg class="kg-svg" viewBox="0 0 {W} {H}" '
             f'xmlns="http://www.w3.org/2000/svg">']

    # 1) 엣지 먼저 (노드 뒤에 깔리도록)
    for e in edges:
        ax, ay = pts[e["a"]]
        bx, by = pts[e["b"]]
        if e["kind"] == "stock":
            width = 1.4 + min(e["shared"], 4) * 0.9   # 겹치는 종목 수에 비례
            dash = ""
            color = _EDGE_STOCK
            op = 0.55
            title = "공통 종목: " + ", ".join(e.get("shared_names", []))
        else:
            width = 1.0
            dash = ' stroke-dasharray="3 4"'
            color = _EDGE_CAT
            op = 0.6
            title = "같은 카테고리"
        parts.append(
            f'<line class="kg-edge" data-a="{e["a"]}" data-b="{e["b"]}" '
            f'x1="{ax:.1f}" y1="{ay:.1f}" x2="{bx:.1f}" y2="{by:.1f}" '
            f'stroke="{color}" stroke-width="{width:.1f}" stroke-opacity="{op}"'
            f'{dash}><title>{html.escape(title)}</title></line>'
        )

    # 2) 노드 + 라벨
    for nd, (x, y) in zip(nodes, pts):
        r = node_r(nd["weight"])
        delay = nd["id"] * 0.05
        ring = ""
        if nd["watch"]:
            ring = (f'<circle class="kg-node-ring" cx="{x:.1f}" cy="{y:.1f}" '
                    f'r="{r+3.5:.1f}" fill="none" stroke="#D9A93C" stroke-width="2"/>')
        # 라벨 위치: 노드가 위쪽 절반이면 위로, 아래면 아래로
        label_dy = -(r + 7) if y < cy else (r + 14)
        # 라벨이 너무 길면 줄임
        label = nd["label"]
        if len(label) > 11:
            label = label[:11] + "…"
        parts.append(
            f'<g class="kg-node-g" data-id="{nd["id"]}">'
            f'{ring}'
            f'<circle class="kg-node" cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" '
            f'fill="{nd["color"]}" fill-opacity="0.88" '
            f'stroke="var(--bg,#FCFCFA)" stroke-width="2.5" '
            f'style="animation-delay:{delay:.2f}s">'
            f'<title>{html.escape(nd["label"])} · {html.escape(nd["cat"])}</title>'
            f'</circle>'
            f'<text class="kg-label" data-id="{nd["id"]}" x="{x:.1f}" '
            f'y="{y + label_dy:.1f}" text-anchor="middle" font-size="11.5">'
            f'{html.escape(label)}</text>'
            f'</g>'
        )

    parts.append("</svg>")
    return "".join(parts)


def _legend_html(nodes, edges) -> str:
    # 실제 등장한 카테고리만 범례에 표시
    cats_present = []
    for c in ("거시", "섹터", "종목", "정책"):
        if any(nd["cat"] == c for nd in nodes):
            cats_present.append(c)
    cat_items = "".join(
        f'<span class="kg-leg-item"><span class="kg-dot" '
        f'style="background:{_CAT_COLOR.get(c, _CAT_DEFAULT)}"></span>{c}</span>'
        for c in cats_present)
    n_stock = sum(1 for e in edges if e["kind"] == "stock")
    n_cat = sum(1 for e in edges if e["kind"] == "cat")
    return (
        f'<div class="kg-legend">{cat_items}'
        f'<span class="kg-leg-item"><span class="kg-line stk"></span>공통 종목 ({n_stock})</span>'
        f'<span class="kg-leg-item"><span class="kg-line cat"></span>같은 카테고리 ({n_cat})</span>'
        f'<span class="kg-leg-item">⭐ 워치리스트 종목 포함</span>'
        f'<span class="kg-leg-item">노드 크기 = 중요도</span>'
        f'</div>'
    )


def render_keyword_graph(items, max_nodes=14):
    """키워드 관계 그래프를 그린다. items: keywords_today.json의 items 리스트."""
    items = [it for it in (items or []) if (it.get("keyword") or "").strip()][:max_nodes]
    if len(items) < 2:
        st.caption("관계 그래프는 키워드가 2개 이상일 때 표시돼요.")
        return

    watch_set = _watch_set()
    nodes, edges = _build_graph(items, watch_set)
    if len(nodes) < 2:
        st.caption("관계 그래프를 그릴 키워드가 부족해요.")
        return

    st.markdown(_graph_css(), unsafe_allow_html=True)
    svg = _svg(nodes, edges)
    legend = _legend_html(nodes, edges)
    n_stock = sum(1 for e in edges if e["kind"] == "stock")

    st.markdown(
        f'<div class="kg-wrap">{svg}{legend}'
        f'<div class="kg-hint">노드에 마우스를 올리면 연결된 키워드만 밝아져요. '
        f'진한 선 = 같은 종목을 공유(테마 클러스터), 흐린 점선 = 같은 카테고리.</div>'
        f'</div>',
        unsafe_allow_html=True)
    # hover 강조 스크립트 (1px, 부모 문서에 이벤트 위임)
    import streamlit.components.v1 as components
    components.html(_graph_js(), height=0)

    if n_stock == 0:
        st.caption("오늘은 종목을 공유하는 키워드가 없어요. 점선(같은 카테고리)만 표시됩니다.")
