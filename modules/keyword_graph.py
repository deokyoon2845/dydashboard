"""오늘의 키워드 관계 그래프 — 공통 종목·공통 키워드로 키워드를 잇는 SVG 네트워크.

연결 규칙 (B: 텍스트 공통어 기반):
  · 공통 종목 ≥ 1            → 진한 sage 실선 (가장 강한 연결, 종목 수에 비례해 굵게)
  · 키워드+뉴스 제목의 공통 토큰 → 중간 톤 실선 (공유 토큰 수에 비례)
  · (카테고리 단독 연결은 제거 — 점선 거미줄의 주범이었음)

솎아내기 (D):
  · 공통 종목 연결은 항상 표시
  · 토큰 연결은 점수 상위 max_edges개만 (약한 연결이 화면을 덮지 않게)

노드:
  · 크기 = weight(중요도, 1~10)
  · 색   = 카테고리(거시/섹터/종목/정책)
  · 금색 링 = 워치리스트 종목이 엮인 키워드

레이아웃:
  · 항상 펼쳐서 표시(expander 제거)
  · 라벨은 작은 폰트 + 두 줄 허용 + 노드 간격 확대로 잘림 방지

외부 패키지 없음. st.markdown(SVG) 한 번으로 렌더.
"""

import html
import math
import re

import streamlit as st

# 카테고리별 노드 색
_CAT_COLOR = {
    "거시": "#2C5F7C", "섹터": "#4A6B4F", "종목": "#7C5F2C", "정책": "#6B4A7C",
}
_CAT_DEFAULT = "#7E9A83"

_EDGE_STOCK = "#5E7E64"    # 공통 종목 선 (진한 sage)
_EDGE_TOKEN = "#A7BBA9"    # 공통 토큰 선 (중간 sage)

# 토큰화에서 거를 불용어 (흔한 시황 표현·조사·단위)
_STOP = {
    "강세", "약세", "급등", "급락", "상승", "하락", "조정", "회복", "돌파", "전망",
    "기대", "확대", "축소", "증가", "감소", "우려", "리스크", "이슈", "관련", "전후",
    "당일", "오늘", "이번", "지난", "최근", "대비", "복귀", "시도", "성공", "수혜",
    "결과", "장세", "수급", "경쟁", "완화", "긴축", "발표", "예정", "가능", "지속",
    "및", "등", "과", "와", "의", "를", "을", "은", "는", "이", "가", "에", "로",
    "으로", "만에", "만", "달러", "억", "조", "선", "개", "년", "월", "일",
    "지정학적", "기업", "금융", "순자산", "한달여", "한달",
}


def _norm(s: str) -> str:
    return "".join(str(s).split()).casefold()


def _watch_set() -> set:
    try:
        from modules.watchlist import load_watchlist
        return {_norm(s) for s in load_watchlist()}
    except Exception:
        return set()


def _tokens(text: str) -> set:
    """제목에서 의미 있는 토큰(2글자 이상 명사류) 추출. 형태소 분석기 없이 휴리스틱."""
    text = re.sub(r"[^가-힣A-Za-z0-9 ]", " ", str(text))
    out = set()
    for w in text.split():
        w = w.strip()
        if not w:
            continue
        # 영문/숫자 토큰: 2글자 이상 그대로(대문자 정규화)
        if re.fullmatch(r"[A-Za-z0-9]+", w):
            if len(w) >= 2:
                out.add(w.upper())
            continue
        if w in _STOP:
            continue
        if len(w) >= 2:
            out.add(w)
        # 복합어 접미 제거로 핵심 명사 분리 (광통신주→광통신 등)
        for suf in ("주", "株", "기업", "산업", "시장", "지수", "정책"):
            if w.endswith(suf) and len(w) > len(suf) + 1:
                stem = w[:-len(suf)]
                if len(stem) >= 2 and stem not in _STOP:
                    out.add(stem)
    return out


def _item_tokens(it: dict) -> set:
    """키워드 + 뉴스 제목들을 합쳐 토큰 추출. 종목명은 별도 처리하므로 제외하지 않음."""
    parts = [it.get("keyword", "")]
    for n in (it.get("news") or []):
        t = n.get("title")
        if t:
            parts.append(t)
    if it.get("news_title"):
        parts.append(it["news_title"])
    toks = set()
    for p in parts:
        toks |= _tokens(p)
    return toks


def _build_graph(items, watch_set, max_edges=14):
    """items → (nodes, edges). B+D 적용."""
    nodes = []
    for it in items:
        kw = (it.get("keyword") or "").strip()
        if not kw:
            continue
        cat = (it.get("category") or "").strip()
        stocks = {_norm(s) for s in (it.get("stocks") or []) if s}
        w = it.get("weight")
        w = w if isinstance(w, int) and w > 0 else 5
        nodes.append({
            "id": len(nodes),
            "label": kw,
            "cat": cat,
            "color": _CAT_COLOR.get(cat, _CAT_DEFAULT),
            "weight": w,
            "stocks": stocks,
            "tokens": _item_tokens(it),
            "watch": bool(stocks & watch_set),
        })

    stock_edges, token_edges = [], []
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            a, b = nodes[i], nodes[j]
            shared_stock = a["stocks"] & b["stocks"]
            if shared_stock:
                stock_edges.append({
                    "a": i, "b": j, "kind": "stock",
                    "shared": len(shared_stock),
                    "shared_names": sorted(shared_stock),
                    "score": 100 + len(shared_stock) * 10,
                })
                continue  # 종목으로 이미 연결되면 토큰 중복 연결 안 함
            shared_tok = a["tokens"] & b["tokens"]
            if shared_tok:
                token_edges.append({
                    "a": i, "b": j, "kind": "token",
                    "shared": len(shared_tok),
                    "shared_names": sorted(shared_tok),
                    "score": len(shared_tok) * 10,
                })

    # D: 종목 연결은 모두, 토큰 연결은 점수 상위 (max_edges - 종목수)개만
    token_edges.sort(key=lambda e: e["score"], reverse=True)
    room = max(0, max_edges - len(stock_edges))
    edges = stock_edges + token_edges[:room]
    return nodes, edges


def _layout_circle(n, cx, cy, radius):
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
.kg-node{transition:opacity .18s ease;transform-box:fill-box;transform-origin:center;
  animation:kg-pop .42s cubic-bezier(.34,1.56,.64,1) both;}
.kg-node-ring{transition:opacity .18s ease;}
.kg-label{font-family:'Hanken Grotesk','Noto Sans KR',sans-serif;font-weight:700;
  fill:var(--ink,#34352f);transition:opacity .18s ease;pointer-events:none;}
@keyframes kg-pop{from{opacity:0;transform:scale(.3);}to{opacity:1;transform:scale(1);}}
.kg-dim{opacity:.12 !important;}
.kg-edge.kg-hot{opacity:1 !important;}
.kg-legend{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;
  padding:8px 10px 6px;font-size:11px;color:var(--muted,#9a9b92);}
.kg-leg-item{display:inline-flex;align-items:center;gap:5px;}
.kg-dot{width:10px;height:10px;border-radius:50%;display:inline-block;}
.kg-line{width:18px;height:0;display:inline-block;border-top-width:2px;border-top-style:solid;}
.kg-line.tok{border-top-color:#A7BBA9;}
.kg-line.stk{border-top-color:#5E7E64;border-top-width:3px;}
.kg-hint{font-size:10.5px;color:var(--muted,#9a9b92);padding:0 10px 8px;}
@media(prefers-reduced-motion:reduce){.kg-node{animation:none !important;}}
</style>
"""


def _graph_js() -> str:
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
          if (a===id || b===id){ e.classList.add('kg-hot'); linked.add(a); linked.add(b); }
          else { e.classList.add('kg-dim'); }
        });
        nodes.forEach(function(nn){
          if (!linked.has(nn.getAttribute('data-id'))) nn.classList.add('kg-dim');});
        labels.forEach(function(lb){
          if (!linked.has(lb.getAttribute('data-id'))) lb.classList.add('kg-dim');});
      });
      g.addEventListener('mouseleave', clear);
    });
  }
  function scan(){ doc.querySelectorAll('svg.kg-svg').forEach(setup); }
  scan();
  const mo = new MutationObserver(scan);
  mo.observe(doc.body, {childList:true, subtree:true});
  setTimeout(function(){ mo.disconnect(); }, 6000);
})();
</script>
"""


def _wrap_label(label, max_per_line=8, max_lines=2):
    """라벨을 글자수 기준으로 줄바꿈. 넘치면 …로 자름. (줄 리스트 반환)"""
    label = label.strip()
    # 괄호 앞에서 우선 끊기 (예: '반도체 강세 (삼성전자…)' → '반도체 강세')
    m = re.match(r"^(.*?)\s*[\(（]", label)
    head = m.group(1).strip() if m and len(m.group(1).strip()) >= 2 else label
    lines, cur = [], ""
    for ch in head:
        if len(cur) >= max_per_line:
            lines.append(cur)
            cur = ""
            if len(lines) >= max_lines:
                break
        cur += ch
    if cur and len(lines) < max_lines:
        lines.append(cur)
    # 원본이 더 길어서 잘렸으면 마지막 줄에 … 부착
    consumed = sum(len(x) for x in lines)
    if consumed < len(head):
        if lines:
            lines[-1] = lines[-1].rstrip() + "…"
    return lines[:max_lines]


def _svg(nodes, edges) -> str:
    W, H = 760, 600          # 세로를 늘려 라벨 두 줄 공간 확보
    cx, cy = W / 2, H / 2
    n = len(nodes)
    radius = min(W, H) * 0.34
    pts = _layout_circle(n, cx, cy, radius)

    def node_r(w):
        return 12 + (max(1, min(10, w)) - 1) / 9 * 11   # 12~23px (살짝 줄임)

    parts = [f'<svg class="kg-svg" viewBox="0 0 {W} {H}" '
             f'xmlns="http://www.w3.org/2000/svg">']

    # 엣지
    for e in edges:
        ax, ay = pts[e["a"]]
        bx, by = pts[e["b"]]
        if e["kind"] == "stock":
            width = 2.0 + min(e["shared"], 4) * 1.0
            color = _EDGE_STOCK
            op = 0.7
            title = "공통 종목: " + ", ".join(e.get("shared_names", []))
        else:
            width = 1.2 + min(e["shared"], 3) * 0.7
            color = _EDGE_TOKEN
            op = 0.5
            title = "공통어: " + ", ".join(e.get("shared_names", []))
        parts.append(
            f'<line class="kg-edge" data-a="{e["a"]}" data-b="{e["b"]}" '
            f'x1="{ax:.1f}" y1="{ay:.1f}" x2="{bx:.1f}" y2="{by:.1f}" '
            f'stroke="{color}" stroke-width="{width:.1f}" stroke-opacity="{op}">'
            f'<title>{html.escape(title)}</title></line>'
        )

    # 노드 + 라벨
    for nd, (x, y) in zip(nodes, pts):
        r = node_r(nd["weight"])
        delay = nd["id"] * 0.05
        ring = ""
        if nd["watch"]:
            ring = (f'<circle class="kg-node-ring" cx="{x:.1f}" cy="{y:.1f}" '
                    f'r="{r+3.5:.1f}" fill="none" stroke="#D9A93C" stroke-width="2"/>')
        # 라벨 위/아래 배치
        above = y < cy
        line_h = 13
        label_lines = _wrap_label(nd["label"])
        n_lines = len(label_lines)
        if above:
            base_y = y - r - 8 - (n_lines - 1) * line_h
        else:
            base_y = y + r + 16
        tspans = "".join(
            f'<tspan x="{x:.1f}" dy="{0 if k == 0 else line_h}">{html.escape(ln)}</tspan>'
            for k, ln in enumerate(label_lines))
        parts.append(
            f'<g class="kg-node-g" data-id="{nd["id"]}">'
            f'{ring}'
            f'<circle class="kg-node" cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" '
            f'fill="{nd["color"]}" fill-opacity="0.88" '
            f'stroke="var(--bg,#FCFCFA)" stroke-width="2.5" '
            f'style="animation-delay:{delay:.2f}s">'
            f'<title>{html.escape(nd["label"])} · {html.escape(nd["cat"])}</title></circle>'
            f'<text class="kg-label" data-id="{nd["id"]}" x="{x:.1f}" y="{base_y:.1f}" '
            f'text-anchor="middle" font-size="10.5">{tspans}</text>'
            f'</g>'
        )

    parts.append("</svg>")
    return "".join(parts)


def _legend_html(nodes, edges) -> str:
    cats_present = [c for c in ("거시", "섹터", "종목", "정책")
                    if any(nd["cat"] == c for nd in nodes)]
    cat_items = "".join(
        f'<span class="kg-leg-item"><span class="kg-dot" '
        f'style="background:{_CAT_COLOR.get(c, _CAT_DEFAULT)}"></span>{c}</span>'
        for c in cats_present)
    n_stock = sum(1 for e in edges if e["kind"] == "stock")
    n_tok = sum(1 for e in edges if e["kind"] == "token")
    return (
        f'<div class="kg-legend">{cat_items}'
        f'<span class="kg-leg-item"><span class="kg-line stk"></span>공통 종목 ({n_stock})</span>'
        f'<span class="kg-leg-item"><span class="kg-line tok"></span>공통 키워드 ({n_tok})</span>'
        f'<span class="kg-leg-item">⭐ 워치리스트 종목 포함</span>'
        f'<span class="kg-leg-item">노드 크기 = 중요도</span>'
        f'</div>'
    )


def render_keyword_graph(items, max_nodes=14, max_edges=14):
    """키워드 관계 그래프(항상 펼침). items: keywords_today.json의 items 리스트."""
    items = [it for it in (items or []) if (it.get("keyword") or "").strip()][:max_nodes]
    if len(items) < 2:
        st.caption("관계 그래프는 키워드가 2개 이상일 때 표시돼요.")
        return

    watch_set = _watch_set()
    nodes, edges = _build_graph(items, watch_set, max_edges=max_edges)
    if len(nodes) < 2:
        st.caption("관계 그래프를 그릴 키워드가 부족해요.")
        return

    st.markdown(_graph_css(), unsafe_allow_html=True)
    svg = _svg(nodes, edges)
    legend = _legend_html(nodes, edges)
    n_stock = sum(1 for e in edges if e["kind"] == "stock")
    n_tok = sum(1 for e in edges if e["kind"] == "token")

    st.markdown(
        f'<div class="kg-wrap">{svg}{legend}'
        f'<div class="kg-hint">노드에 마우스를 올리면 연결된 키워드만 밝아져요. '
        f'진한 선 = 같은 종목 공유(테마 클러스터), 연한 선 = 제목·뉴스의 공통 키워드.</div>'
        f'</div>',
        unsafe_allow_html=True)

    import streamlit.components.v1 as components
    components.html(_graph_js(), height=0)

    if n_stock == 0 and n_tok == 0:
        st.caption("오늘은 키워드 사이에 뚜렷한 공통점이 없어요. 각 주제가 독립적으로 부각된 날입니다.")
