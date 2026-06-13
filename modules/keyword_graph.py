"""오늘의 키워드 관계 그래프 — 공통 종목·공통 키워드로 키워드를 잇는 SVG 네트워크.

연결 규칙 (B: 텍스트 공통어 기반):
  · 공통 종목 ≥ 1            → 진한 sage 실선 (가장 강한 연결)
  · 키워드+뉴스 제목의 공통 토큰 → 중간 톤 실선 (공유 토큰 수에 비례)

솎아내기:
  · 공통 종목 연결은 항상 표시 / 토큰 연결은 점수 상위 max_edges개만

배치 (force-directed, 파이썬에서 정적 계산):
  · 반발력(겹침 방지) + 인력(연결된 것끼리 뭉침) + 중심력(중앙 수렴)
  · 연결 많은 노드가 자연히 중앙으로 → "오늘의 허브" 가시화
  · seed 고정으로 새로고침해도 같은 배치 (결정적)

라벨 (A):
  · 핵심 명사구까지만(괄호·수식어 제거), 작은 폰트 + 두 줄, 풀 제목은 호버 툴팁

노드: 크기=중요도, 색=카테고리, 금색 링=워치리스트 종목 포함
외부 패키지 없음.
"""

import html
import math
import random
import re

import streamlit as st

_CAT_COLOR = {
    "거시": "#2C5F7C", "섹터": "#4A6B4F", "종목": "#7C5F2C", "정책": "#6B4A7C",
}
_CAT_DEFAULT = "#7E9A83"
_EDGE_STOCK = "#5E7E64"
_EDGE_TOKEN = "#A7BBA9"

_STOP = {
    "강세", "약세", "급등", "급락", "상승", "하락", "조정", "회복", "돌파", "전망",
    "기대", "확대", "축소", "증가", "감소", "우려", "리스크", "이슈", "관련", "전후",
    "당일", "오늘", "이번", "지난", "최근", "대비", "복귀", "시도", "성공", "수혜",
    "결과", "장세", "수급", "경쟁", "완화", "긴축", "발표", "예정", "가능", "지속",
    "주가", "종목", "전망치", "분석", "마감",
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
    text = re.sub(r"[^가-힣A-Za-z0-9 ]", " ", str(text))
    out = set()
    for w in text.split():
        w = w.strip()
        if not w:
            continue
        if re.fullmatch(r"[A-Za-z0-9]+", w):
            if len(w) >= 2:
                out.add(w.upper())
            continue
        if w in _STOP:
            continue
        if len(w) >= 2:
            out.add(w)
        for suf in ("주", "株", "기업", "산업", "시장", "지수", "정책"):
            if w.endswith(suf) and len(w) > len(suf) + 1:
                stem = w[:-len(suf)]
                if len(stem) >= 2 and stem not in _STOP:
                    out.add(stem)
    return out


def _item_tokens(it: dict) -> set:
    parts = [it.get("keyword", "")]
    for n in (it.get("news") or []):
        if n.get("title"):
            parts.append(n["title"])
    if it.get("news_title"):
        parts.append(it["news_title"])
    toks = set()
    for p in parts:
        toks |= _tokens(p)
    return toks


def _short_label(label: str) -> str:
    """그래프용 짧은 라벨: 괄호 앞 + 구분자(및/·/,) 앞부분만 취해 핵심만 남김.

    접미사 목록에 의존하지 않고, 어떤 제목이든 핵심 명사구로 줄인다.
    예) '파운드리 및 전력반도체 성장전망' → '파운드리'
        '삼성전기 및 광통신·부품소재 강세'   → '삼성전기'
        '비트코인 변동성 및 암호화폐 약세'   → '비트코인 변동성'
    """
    label = label.strip()
    # 1) 괄호 앞에서 끊기
    m = re.match(r"^(.*?)\s*[\(（]", label)
    if m and len(m.group(1).strip()) >= 2:
        label = m.group(1).strip()
    # 2) 구분자 앞부분만 (너무 짧아지면 원본 유지)
    for sep in (" 및 ", "·", ",", "/"):
        if sep in label:
            head = label.split(sep)[0].strip()
            if len(head) >= 2:
                label = head
                break
    return label


def _build_graph(items, watch_set, max_edges=14):
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
            "id": len(nodes), "label": kw, "short": _short_label(kw),
            "cat": cat, "color": _CAT_COLOR.get(cat, _CAT_DEFAULT),
            "weight": w, "stocks": stocks, "tokens": _item_tokens(it),
            "watch": bool(stocks & watch_set), "deg": 0,
        })

    stock_edges, token_edges = [], []
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            a, b = nodes[i], nodes[j]
            shared_stock = a["stocks"] & b["stocks"]
            if shared_stock:
                stock_edges.append({"a": i, "b": j, "kind": "stock",
                                    "shared": len(shared_stock),
                                    "shared_names": sorted(shared_stock),
                                    "score": 100 + len(shared_stock) * 10})
                continue
            shared_tok = a["tokens"] & b["tokens"]
            if shared_tok:
                token_edges.append({"a": i, "b": j, "kind": "token",
                                    "shared": len(shared_tok),
                                    "shared_names": sorted(shared_tok),
                                    "score": len(shared_tok) * 10})

    token_edges.sort(key=lambda e: e["score"], reverse=True)
    room = max(0, max_edges - len(stock_edges))
    edges = stock_edges + token_edges[:room]

    # 연결 차수(degree) 계산 → 허브 식별
    for e in edges:
        nodes[e["a"]]["deg"] += 1
        nodes[e["b"]]["deg"] += 1
    return nodes, edges


def _force_layout(n, edges, W, H, iters=320, seed=42):
    """파이썬 정적 force-directed 레이아웃. 같은 입력엔 같은 출력(seed 고정)."""
    rnd = random.Random(seed)
    cx, cy = W / 2, H / 2
    pos = []
    for i in range(n):
        ang = -math.pi / 2 + 2 * math.pi * i / n
        r = min(W, H) * 0.32
        pos.append([cx + r * math.cos(ang) + rnd.uniform(-8, 8),
                    cy + r * math.sin(ang) + rnd.uniform(-8, 8)])
    adj = {}
    for e in edges:
        s = 1 + (e["shared"] if e["kind"] == "stock" else 0)
        adj[(e["a"], e["b"])] = s
        adj[(e["b"], e["a"])] = s

    k_rep, k_att, k_ctr = 9000.0, 0.006, 0.01
    for it in range(iters):
        cool = 1.0 - it / iters
        disp = [[0.0, 0.0] for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                dx = pos[i][0] - pos[j][0]
                dy = pos[i][1] - pos[j][1]
                d2 = dx * dx + dy * dy + 0.01
                d = math.sqrt(d2)
                f = k_rep / d2
                ux, uy = dx / d, dy / d
                disp[i][0] += ux * f; disp[i][1] += uy * f
                disp[j][0] -= ux * f; disp[j][1] -= uy * f
        for (a, b), s in adj.items():
            if a < b:
                dx = pos[a][0] - pos[b][0]
                dy = pos[a][1] - pos[b][1]
                d = math.sqrt(dx * dx + dy * dy) + 0.01
                f = k_att * d * (1 + s)
                ux, uy = dx / d, dy / d
                disp[a][0] -= ux * f; disp[a][1] -= uy * f
                disp[b][0] += ux * f; disp[b][1] += uy * f
        for i in range(n):
            disp[i][0] += (cx - pos[i][0]) * k_ctr
            disp[i][1] += (cy - pos[i][1]) * k_ctr
            mag = math.sqrt(disp[i][0] ** 2 + disp[i][1] ** 2) + 1e-9
            step = min(mag, 18 * cool)
            pos[i][0] += disp[i][0] / mag * step
            pos[i][1] += disp[i][1] / mag * step
            pos[i][0] = max(95, min(W - 95, pos[i][0]))
            pos[i][1] = max(88, min(H - 88, pos[i][1]))
    return [(p[0], p[1]) for p in pos]


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
.kg-node-ring,.kg-hub-halo{transition:opacity .18s ease;}
.kg-label{font-family:'Hanken Grotesk','Noto Sans KR',sans-serif;font-weight:700;
  fill:var(--ink,#34352f);transition:opacity .18s ease;pointer-events:none;
  paint-order:stroke;stroke:var(--bg,#FCFCFA);stroke-width:3px;stroke-linejoin:round;}
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
          const a=e.getAttribute('data-a'), b=e.getAttribute('data-b');
          if (a===id||b===id){ e.classList.add('kg-hot'); linked.add(a); linked.add(b); }
          else { e.classList.add('kg-dim'); }
        });
        nodes.forEach(function(nn){
          if(!linked.has(nn.getAttribute('data-id'))) nn.classList.add('kg-dim');});
        labels.forEach(function(lb){
          if(!linked.has(lb.getAttribute('data-id'))) lb.classList.add('kg-dim');});
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


def _wrap_short(label, max_per_line=7, max_lines=2):
    """글자수 상한을 강제하는 줄바꿈. 최대 max_per_line*max_lines자.

    어떤 긴 라벨이 와도 상한을 넘으면 …로 잘라 화면 밖으로 안 나간다(잘림 원천봉쇄).
    단어 경계를 우선하되, 한 단어가 줄 폭을 넘으면 글자 단위로 분할.
    """
    label = label.strip()
    if not label:
        return [""]
    words = label.split()
    lines, cur = [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if len(cand) <= max_per_line or not cur:
            if len(cand) > max_per_line and not cur:
                # 한 단어가 줄 폭 초과 → 글자 단위로 강제 분할
                lines.append(cand[:max_per_line])
                rest = cand[max_per_line:]
                while rest and len(lines) < max_lines:
                    lines.append(rest[:max_per_line])
                    rest = rest[max_per_line:]
                cur = ""
                if len(lines) >= max_lines:
                    break
            else:
                cur = cand
        else:
            lines.append(cur)
            cur = w
            if len(lines) >= max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    lines = lines[:max_lines]
    # 원본이 더 길어서 잘렸으면 마지막 줄 끝에 …
    plain = label.replace(" ", "")
    shown = "".join(lines).replace(" ", "").replace("…", "")
    if len(shown) < len(plain) and lines:
        if not lines[-1].endswith("…"):
            if len(lines[-1]) >= max_per_line:
                lines[-1] = lines[-1][:max_per_line - 1] + "…"
            else:
                lines[-1] += "…"
    return lines[:max_lines]


def _svg(nodes, edges) -> str:
    W, H = 760, 620
    n = len(nodes)
    pos = _force_layout(n, edges, W, H)
    cy = H / 2

    max_deg = max((nd["deg"] for nd in nodes), default=0)

    def node_r(w):
        return 12 + (max(1, min(10, w)) - 1) / 9 * 11

    parts = [f'<svg class="kg-svg" viewBox="0 0 {W} {H}" '
             f'xmlns="http://www.w3.org/2000/svg">']

    # 엣지
    for e in edges:
        ax, ay = pos[e["a"]]
        bx, by = pos[e["b"]]
        if e["kind"] == "stock":
            width = 2.0 + min(e["shared"], 4) * 1.0
            color, op = _EDGE_STOCK, 0.7
            title = "공통 종목: " + ", ".join(e.get("shared_names", []))
        else:
            width = 1.2 + min(e["shared"], 3) * 0.7
            color, op = _EDGE_TOKEN, 0.5
            title = "공통어: " + ", ".join(e.get("shared_names", []))
        parts.append(
            f'<line class="kg-edge" data-a="{e["a"]}" data-b="{e["b"]}" '
            f'x1="{ax:.1f}" y1="{ay:.1f}" x2="{bx:.1f}" y2="{by:.1f}" '
            f'stroke="{color}" stroke-width="{width:.1f}" stroke-opacity="{op}">'
            f'<title>{html.escape(title)}</title></line>'
        )

    # 노드 + 라벨
    for nd, (x, y) in zip(nodes, pos):
        r = node_r(nd["weight"])
        delay = nd["id"] * 0.05
        # 허브 후광: 연결이 가장 많은 노드(들)에 옅은 sage 후광
        halo = ""
        if max_deg >= 2 and nd["deg"] == max_deg:
            halo = (f'<circle class="kg-hub-halo" cx="{x:.1f}" cy="{y:.1f}" '
                    f'r="{r+9:.1f}" fill="#A7BBA9" fill-opacity="0.16"/>')
        ring = ""
        if nd["watch"]:
            ring = (f'<circle class="kg-node-ring" cx="{x:.1f}" cy="{y:.1f}" '
                    f'r="{r+3.5:.1f}" fill="none" stroke="#D9A93C" stroke-width="2"/>')
        above = y < cy
        line_h = 13
        label_lines = _wrap_short(nd["short"])
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
            f'{halo}{ring}'
            f'<circle class="kg-node" cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" '
            f'fill="{nd["color"]}" fill-opacity="0.88" '
            f'stroke="var(--bg,#FCFCFA)" stroke-width="2.5" '
            f'style="animation-delay:{delay:.2f}s">'
            f'<title>{html.escape(nd["label"])} · {html.escape(nd["cat"])}'
            f' · 연결 {nd["deg"]}개</title></circle>'
            f'<text class="kg-label" data-id="{nd["id"]}" x="{x:.1f}" y="{base_y:.1f}" '
            f'text-anchor="middle" font-size="10">{tspans}</text>'
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
    # 허브 키워드(연결 최다) 안내
    max_deg = max((nd["deg"] for nd in nodes), default=0)
    hub = ""
    if max_deg >= 2:
        hubs = [nd["short"] for nd in nodes if nd["deg"] == max_deg]
        hub = (f'<span class="kg-leg-item">🌐 오늘의 허브: '
               f'<b style="color:var(--ink,#34352f)">{html.escape(", ".join(hubs[:2]))}</b> '
               f'(연결 {max_deg}개)</span>')
    return (
        f'<div class="kg-legend">{cat_items}'
        f'<span class="kg-leg-item"><span class="kg-line stk"></span>공통 종목 ({n_stock})</span>'
        f'<span class="kg-leg-item"><span class="kg-line tok"></span>공통 키워드 ({n_tok})</span>'
        f'<span class="kg-leg-item">⭐ 워치리스트 포함</span>'
        f'<span class="kg-leg-item">노드 크기 = 중요도</span>'
        f'{hub}</div>'
    )


def render_keyword_graph(items, max_nodes=14, max_edges=14):
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
        f'<div class="kg-hint">연결이 많은 키워드일수록 가운데로 모여요(=오늘의 중심). '
        f'노드에 마우스를 올리면 연결된 키워드만 밝아지고, 선에 올리면 무엇을 공유하는지 보여요. '
        f'진한 선 = 같은 종목, 연한 선 = 제목·뉴스의 공통 키워드.</div>'
        f'</div>',
        unsafe_allow_html=True)

    import streamlit.components.v1 as components
    components.html(_graph_js(), height=0)

    if n_stock == 0 and n_tok == 0:
        st.caption("오늘은 키워드 사이에 뚜렷한 공통점이 없어요. 각 주제가 독립적으로 부각된 날입니다.")
