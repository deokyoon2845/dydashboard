"""[뷰어] 주도주 — 주식 탭의 '주도주' 하위탭. (레이아웃 A안: 한 화면 대시보드)
 
구성
  · 도움말(주도주 보는 법) expander
  · 상단 스트립: 유니버스 → 정밀스캔 → 주도 N (정직한 깔때기)
  · 한눈에 보기: [좌] 컴팩트 주도 매트릭스(높이 축소) · [우] 통합 리더보드 TOP N(짧은 스파크라인)
  · 주도 섹터 강도: 가로 막대 2열(색=1개월 모멘텀, 길이=주도 점수, 우측에 주도 종목 수)
  · (보조·접힘) 섹터별 주도주 자세히: 섹터 expander → 주도주 카드
 
데이터는 Supabase(leaders 최신 스냅샷)만 읽는다(엔진이 채움). 외부 API 직접호출 없음.
매트릭스·리더보드·섹터카드는 '주도 게이트' 통과분(is_leader)만 표시한다.
섹터 점수·폭(breadth)은 엔진이 정밀스캔 전체로 계산하므로 게이트와 무관하게 유지된다.
 
payload 구조(engine.leaders_collect.collect): {asof, asof_date, params, sectors[], stocks[]}
  · stocks[] : {code,name,market,upjong,group,score,comp{...},mom_1d,mom_1w,mom_1m,mom_3m,
                rs_3m,mcap_eok,turnover_eok,high_ratio,aligned,above_ma60,streak,is_leader,is_new,spark[]}
  · params  : {..., leaders_n, gate_preset, gate{...}, leader_cap}
"""
 
import html
 
import altair as alt
import pandas as pd
import streamlit as st
 
from modules.stocks import naver_stock_url, naver_stock_page_url, naver_n_icon
from modules.ui import tab_header
 
 
def _nv_icon(s) -> str:
    """종목별 네이버 N 아이콘(네이버페이 증권 종목페이지, 코드 없으면 검색)."""
    return naver_n_icon(name=s.get("name", ""), code=s.get("code", ""))
 
LEADERBOARD_N = 12         # 통합 리더보드 종목 수
MATRIX_LIMIT = 160         # 매트릭스에 찍을 상위 주도주 수(=게이트 cap과 동률)
MATRIX_HEIGHT = 600        # 매트릭스 높이(px) — 우측 리더보드 12행과 높이 맞춤
SECTOR_BARS = 10           # 섹터 강도 막대 개수
CARDS_PER_SECTOR = 8       # 섹터 expander당 주도주 카드 수
DETAIL_SECTORS = 6         # 보조(접힘) 섹터 상세 개수
 
# 게이트 폴백(구버전 payload에 is_leader가 없을 때 뷰어가 근사 판정) — '중'에 준함
_FB_HIGH_MIN = 80.0
 
# 대표그룹 → 색
GROUP_COLORS = {
    "반도체": "#5A7CA0", "2차전지": "#7E9A83", "자동차": "#B6885A",
    "금융": "#6E7E9A", "조선": "#4FA0A0", "방산·항공": "#B65F5A",
    "기계·장비": "#8A7CA0", "건설": "#A0925A", "철강·소재": "#888780",
    "화학·에너지": "#9A6E7E", "바이오·제약": "#6FA07E", "IT·SW": "#5A8CB0",
    "게임·미디어": "#C08A6A", "운송": "#7A93A8", "소비재·유통": "#B07A93",
    "기타": "#B4B2A9",
}
 
_CSS = """
<style>
.ldr-strip{background:var(--summary-bg);border:1px solid var(--line);border-radius:10px;
  padding:10px 14px;font-size:12.5px;color:var(--sage-deep);font-weight:600;margin:2px 0 6px;line-height:1.7;}
.ldr-strip b{color:var(--ink);font-weight:700;} .ldr-strip b.up{color:var(--up);} .ldr-strip b.down{color:var(--down);}
.ldr-strip .arw{color:var(--muted);margin:0 4px;}
.ldr-h{font-size:12px;font-weight:700;letter-spacing:.05em;color:var(--muted);text-transform:uppercase;margin:20px 0 10px;}
.ldr-sub{font-size:10.5px;color:var(--muted);font-weight:600;}
.ldr-new{display:inline-block;background:#eef4ef;color:var(--sage-deep);font-size:9.5px;font-weight:700;
  padding:1px 5px;border-radius:5px;margin-left:5px;vertical-align:1px;}
.nv{display:inline-flex;align-items:center;justify-content:center;width:15px;height:15px;flex:none;
  border-radius:4px;background:#03C75A;color:#fff;font-size:10px;font-weight:900;
  text-decoration:none;margin-left:5px;vertical-align:1px;line-height:1;}
.nv:hover{filter:brightness(.92);}
.ldr-pill{display:inline-block;font-size:10px;font-weight:700;padding:2px 7px;border-radius:6px;}
.ldr-up{color:var(--up);font-weight:700;} .ldr-down{color:var(--down);font-weight:700;}
 
/* 컴팩트 리더보드 (짧은 스파크라인) */
.ldr-lb{border:1px solid var(--line);border-radius:13px;background:var(--card);padding:6px 14px 8px;}
.ldr-lb-row{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--line);}
.ldr-lb-row:last-child{border-bottom:none;}
.ldr-lb-row .rk{width:16px;text-align:center;font-size:12px;font-weight:800;color:var(--muted);flex:none;}
.ldr-lb-row .rk.top{color:var(--up);}
.ldr-lb-row .nm{width:96px;flex:none;display:flex;align-items:center;font-size:13px;font-weight:700;}
.ldr-lb-row .nm a{color:var(--ink);text-decoration:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;} .ldr-lb-row .nm a:hover{text-decoration:underline;}
.ldr-lb-row .spk{width:118px;flex:none;height:24px;}
.ldr-lb-row .spk svg{width:118px;height:24px;display:block;}
.ldr-lb-row .m3{flex:1;text-align:right;font-size:11.5px;font-weight:700;min-width:54px;}
.ldr-lb-row .d1{width:62px;flex:none;text-align:right;font-size:11.5px;}
.ldr-lb-row .d1 .d1l{font-size:9px;color:var(--muted);}
 
/* 섹터 강도 막대 */
.ldr-secwrap{border:1px solid var(--line);border-radius:13px;background:var(--card);padding:14px 16px;}
.ldr-secgrid{display:grid;grid-template-columns:1fr 1fr;gap:10px 26px;}
.ldr-secbar{display:flex;align-items:center;gap:10px;}
.ldr-secbar .lab{width:104px;flex:none;font-size:11.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.ldr-secbar .track{flex:1;height:9px;background:var(--summary-bg);border-radius:5px;overflow:hidden;min-width:40px;}
.ldr-secbar .track>i{display:block;height:100%;border-radius:5px;}
.ldr-secbar .val{width:88px;flex:none;text-align:right;font-size:10.5px;color:var(--muted);}
.ldr-secbar .val b{color:var(--ink);font-weight:700;}
 
/* 섹터 상세(보조) 카드 */
.ldr-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:9px;margin:4px 0;}
.ldr-card{border:1px solid var(--line);border-radius:11px;background:var(--card);padding:11px 13px;
  transition:border-color .15s,transform .15s;}
.ldr-card:hover{border-color:var(--sage-deep);transform:translateY(-1px);}
.ldr-card .top{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px;}
.ldr-card .nm{font-size:13px;font-weight:700;}
.ldr-card .nm a{color:var(--ink);text-decoration:none;} .ldr-card .nm a:hover{text-decoration:underline;}
.ldr-card .sc{font-size:11px;color:var(--muted);font-weight:600;}
.ldr-card .met{display:flex;gap:12px;margin-top:9px;font-size:11px;color:var(--muted);flex-wrap:wrap;}
.ldr-card .sub{display:flex;justify-content:space-between;margin-top:6px;font-size:10.5px;color:var(--muted);}
.ldr-dot-hi{color:var(--up);} .ldr-dot-mid{color:var(--sage-deep);} .ldr-dot-lo{color:var(--muted);}
.ldr-bar{height:6px;background:var(--summary-bg);border-radius:5px;overflow:hidden;}
.ldr-bar>i{display:block;height:100%;background:var(--sage-deep);border-radius:5px;}
.ldr-sec-head{display:flex;align-items:center;gap:11px;margin:2px 0 10px;}
.ldr-sec-head .gp{font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:6px;}
.ldr-sec-head .mt{font-size:11.5px;color:var(--muted);}
.ldr-help{font-size:13.5px;line-height:1.8;color:var(--ink);}
.ldr-help b{color:var(--sage-deep);}
.ldr-matnote{font-size:11px;color:var(--muted);line-height:1.7;margin-top:6px;}

/* ── 등장 애니메이션 (A안: 랭크 빌드업) ──
   리더보드는 순위대로 차오르고, 스파크라인은 좌→우로 그려지고,
   섹터 막대는 채워지고, 매트릭스(Altair)는 컨테이너째 부드럽게 팝업된다. */
@keyframes ldr-rise{from{opacity:0;transform:translateY(12px);}to{opacity:1;transform:none;}}
@keyframes ldr-draw{from{stroke-dashoffset:100;}to{stroke-dashoffset:0;}}
@keyframes ldr-grow{from{transform:scaleX(0);}to{transform:scaleX(1);}}
@keyframes ldr-mx-in{from{opacity:0;transform:scale(.985);}to{opacity:1;transform:none;}}

/* 리더보드 행: 순위대로 아래에서 위로 */
.ldr-lb-row{animation:ldr-rise .5s cubic-bezier(.22,.61,.36,1) both;}
.ldr-lb .ldr-lb-row:nth-child(1){animation-delay:.03s;}
.ldr-lb .ldr-lb-row:nth-child(2){animation-delay:.07s;}
.ldr-lb .ldr-lb-row:nth-child(3){animation-delay:.11s;}
.ldr-lb .ldr-lb-row:nth-child(4){animation-delay:.15s;}
.ldr-lb .ldr-lb-row:nth-child(5){animation-delay:.19s;}
.ldr-lb .ldr-lb-row:nth-child(6){animation-delay:.23s;}
.ldr-lb .ldr-lb-row:nth-child(7){animation-delay:.27s;}
.ldr-lb .ldr-lb-row:nth-child(8){animation-delay:.31s;}
.ldr-lb .ldr-lb-row:nth-child(9){animation-delay:.35s;}
.ldr-lb .ldr-lb-row:nth-child(10){animation-delay:.39s;}
.ldr-lb .ldr-lb-row:nth-child(11){animation-delay:.43s;}
.ldr-lb .ldr-lb-row:nth-child(12){animation-delay:.47s;}

/* 스파크라인: 좌→우 그리기 (리더보드 안에서만) */
.ldr-lb-row .spk .ldr-spk-line{stroke-dasharray:100;stroke-dashoffset:100;
  animation:ldr-draw .7s ease .2s both;}

/* 섹터 막대: 좌→우 채움 */
.ldr-secbar .track>i{transform-origin:left center;
  animation:ldr-grow .7s cubic-bezier(.22,.61,.36,1) .2s both;}

/* 매트릭스(Altair 산점도): 컨테이너 스코프로 부드럽게 팝업 */
.st-key-ldr_matrix [data-testid="stVegaLiteChart"],
.st-key-ldr_matrix [data-testid="stArrowVegaLiteChart"],
.st-key-ldr_matrix .stVegaLiteChart{
  animation:ldr-mx-in .5s cubic-bezier(.22,.61,.36,1) both;}

@media(prefers-reduced-motion:reduce){
  .ldr-lb-row,.ldr-secbar .track>i,
  .st-key-ldr_matrix [data-testid="stVegaLiteChart"],
  .st-key-ldr_matrix [data-testid="stArrowVegaLiteChart"],
  .st-key-ldr_matrix .stVegaLiteChart{animation:none !important;}
  .ldr-lb-row .spk .ldr-spk-line{animation:none !important;stroke-dashoffset:0 !important;}
  .ldr-secbar .track>i{transform:none !important;}
}
</style>
"""
 
_HELP_MD = """
**주도주 = 시장을 이끄는 종목.** 이 탭은 *분석 대상 전체*가 아니라, 아래 **주도 게이트**를
모두 통과한 종목만 보여줍니다(과밀 해소).
 
**주도 게이트(통과 조건)**
- **상대강도 RS > 0** — 코스피/코스닥 대비 초과수익. *시장보다 세게 가는가*가 주도의 본질입니다.
- **3개월 수익률 > 0** — 하락장이라도 *실제로 오른* 종목만.
- **52주 고점 80%↑** — 고점 근처에 있는가(신고가 임박).
- **60일선 위** — 추세가 살아있는가.
- **평균 거래대금 50억↑** — 돈이 충분히 몰리는가.
강도는 약/중/강 3단계로 조절되며 기본은 **중**입니다. (폭주장 대비 표시 상한 160개)
 
**주도 점수(0~100)** — 게이트를 통과한 종목을 줄세우는 값. 5개 축의 가중합입니다.
- 모멘텀 35 · 상대강도 20 · 추세지속성 20 · 유동성 15 · 신고가근접 10
 
**매트릭스 읽는 법** — 가로=추세 지속성, 세로=3개월 모멘텀, 버블 크기=거래대금, 색=대표그룹.
오른쪽 위(꾸준 + 강함)가 주도 영역, 점선은 중앙값입니다.
 
**주도 섹터(업종)** — 구성종목 4개 이상 업종만 집계. 섹터 점수 = 상위 5종목 평균 × 0.5 +
폭(breadth) × 0.3 + 업종 모멘텀 × 0.2. **폭** = 업종 안에서 (1개월 +이고 정배열인) 종목 비율 →
1~2 종목만 튄 '가짜 주도'와 섹터 전반이 오르는 '진짜 주도'를 구분합니다.
*(섹터 통계는 게이트와 무관하게 정밀스캔 전체로 계산됩니다.)*
 
데이터는 Naver 기준이며 장마감 후 1일 1회 갱신됩니다. 투자판단의 근거가 아니라 모니터링용 참고치예요.
"""
 
 
def _pc(v, plus=True):
    if v is None:
        return '<span style="color:var(--muted)">–</span>'
    cls = "ldr-up" if v >= 0 else "ldr-down"
    sign = "+" if (plus and v >= 0) else ""
    return f'<span class="{cls}">{sign}{v:g}%</span>'
 
 
def _bar(score, w="100%"):
    s = max(0, min(100, score or 0))
    return f'<div class="ldr-bar" style="width:{w}"><i style="width:{s:.0f}%"></i></div>'
 
 
def _hi_dot(hr):
    if hr is None:
        return ""
    if hr >= 97:
        return '<span class="ldr-dot-hi">신고가 ●</span>'
    if hr >= 90:
        return '<span class="ldr-dot-mid">고가권 ●</span>'
    return '<span class="ldr-dot-lo">조정 ○</span>'
 
 
def _grp_color(group):
    return GROUP_COLORS.get(group, GROUP_COLORS["기타"])
 
 
def _heat_color(m1):
    """1개월 모멘텀 → 섹터 막대 색(붉을수록 강세·푸를수록 약세)."""
    if m1 is None:
        return "#D9D2CC"
    if m1 >= 8:
        return "#D98A85"
    if m1 >= -5:
        return "#E3B5A8"
    if m1 >= -15:
        return "#D9D2CC"
    if m1 >= -25:
        return "#AEC0CF"
    return "#8FAAC2"
 
 
def _spark_svg(vals, color, width=118, height=24):
    """종가 리스트 → 고정폭 미니 라인차트(SVG)."""
    vals = [v for v in (vals or []) if isinstance(v, (int, float))]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rg = (hi - lo) or 1
    n = len(vals)
    pts = " ".join(
        f"{i/(n-1)*width:.1f},{height-2-((v-lo)/rg)*(height-4):.1f}"
        for i, v in enumerate(vals)
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
        f'style="width:{width}px;height:{height}px;display:block">'
        f'<polygon points="{pts} {width},{height} 0,{height}" style="fill:{color};opacity:.10"/>'
        f'<polyline class="ldr-spk-line" pathLength="100" points="{pts}" style="fill:none;stroke:{color};stroke-width:1.6;opacity:.85"/></svg>'
    )
 
 
def _d1(v):
    """전일대비 등락률 배지."""
    if v is None:
        return '<span style="color:var(--muted)">–</span>'
    up = v >= 0
    c = "var(--up)" if up else "var(--down)"
    ar = "▲" if up else "▼"
    return f'<span style="color:{c};font-weight:700">{ar} {"+" if up else ""}{v:.1f}%</span>'
 
 
# ── 주도 게이트 추출 (엔진 플래그 우선, 없으면 뷰어 근사) ──────────────
 
def _leaders(stocks):
    """is_leader 플래그가 있으면 그걸로, 없으면(구버전) 근사 게이트로 주도주 추출."""
    flagged = [s for s in stocks if s.get("is_leader")]
    if any("is_leader" in s for s in stocks):
        return flagged
    # 폴백: above_ma60는 구버전에 없을 수 있어 RS·3M·고점만으로 근사
    out = []
    for s in stocks:
        if ((s.get("rs_3m") or 0) > 0 and (s.get("mom_3m") or 0) > 0
                and (s.get("high_ratio") or 0) >= _FB_HIGH_MIN):
            out.append(s)
    return out
 
 
# ── 컴팩트 리더보드 ──────────────────────────────────────────────────
 
def _stock_card_html(s):
    nm = html.escape(s.get("name", ""))
    url = html.escape(naver_stock_page_url(name=s.get("name", ""), code=s.get("code", "")))
    new = '<span class="ldr-new">NEW</span>' if s.get("is_new") else ""
    aligned = ' · <span style="color:var(--sage-deep)">정배열</span>' if s.get("aligned") else ""
    cap = s.get("mcap_eok")
    cap_txt = f"{cap/10000:.1f}조" if cap and cap >= 10000 else (f"{cap:,.0f}억" if cap else "–")
    turn = s.get("turnover_eok")
    turn_txt = f"{turn:,.0f}억" if turn else "–"
    return (
        '<div class="ldr-card">'
        f'<div class="top"><div class="nm"><a href="{url}" target="_blank" rel="noopener">{nm}</a>{_nv_icon(s)}{new}</div>'
        f'<div class="sc">{s.get("score","")}점</div></div>'
        f'{_bar(s.get("score"))}'
        f'<div class="met"><span>3M {_pc(s.get("mom_3m"))}</span>'
        f'<span>RS {_pc(s.get("rs_3m"), plus=True)}</span>'
        f'<span>전일 {_d1(s.get("mom_1d"))}</span></div>'
        f'<div class="sub"><span>{cap_txt} · {turn_txt}{aligned}</span>'
        f'<span>{_hi_dot(s.get("high_ratio"))}</span></div>'
        '</div>'
    )
 
 
def _leaderboard_compact(leaders, n=LEADERBOARD_N):
    rows = ""
    for i, s in enumerate(leaders[:n]):
        nm = html.escape(s.get("name", ""))
        url = html.escape(naver_stock_page_url(name=s.get("name", ""), code=s.get("code", "")))
        new = '<span class="ldr-new">N</span>' if s.get("is_new") else ""
        rank_col = "top" if i < 3 else ""
        up3 = (s.get("mom_3m") or 0) >= 0
        spc = "var(--up)" if up3 else "var(--down)"
        spark = _spark_svg(s.get("spark"), spc)
        rows += (
            '<div class="ldr-lb-row">'
            f'<div class="rk {rank_col}">{i+1}</div>'
            f'<div class="nm"><a href="{url}" target="_blank" rel="noopener">{nm}</a>{_nv_icon(s)}{new}</div>'
            f'<div class="spk">{spark}</div>'
            f'<div class="m3">{_pc(s.get("mom_3m"))}</div>'
            f'<div class="d1">{_d1(s.get("mom_1d"))}<div class="d1l">전일</div></div>'
            '</div>'
        )
    return f'<div class="ldr-lb">{rows}</div>'
 
 
# ── 섹터 강도 막대 ───────────────────────────────────────────────────
 
def _sector_bars_html(sectors, leaders):
    if not sectors:
        return '<div class="ldr-secwrap"><span class="ldr-sub">주도 섹터를 집계할 데이터가 부족해요.</span></div>'
    lead_by_upj = {}
    for s in leaders:
        lead_by_upj[s.get("upjong")] = lead_by_upj.get(s.get("upjong"), 0) + 1
    shown = sectors[:SECTOR_BARS]
    maxsc = max((s.get("score") or 0) for s in shown) or 1
    bars = ""
    for s in shown:
        upj = s.get("upjong", "")
        sc = s.get("score") or 0
        col = _heat_color(s.get("mom_1m"))
        nlead = lead_by_upj.get(upj, 0)
        lead_txt = f'<b>{nlead}</b>주도' if nlead else f'{s.get("n","")}종'
        bars += (
            '<div class="ldr-secbar">'
            f'<div class="lab" title="{html.escape(upj)}">{html.escape(upj)}</div>'
            f'<div class="track"><i style="width:{sc/maxsc*100:.0f}%;background:{col}"></i></div>'
            f'<div class="val"><b>{sc}</b> · 1M {_pc(s.get("mom_1m"))} · {lead_txt}</div>'
            '</div>'
        )
    return f'<div class="ldr-secwrap"><div class="ldr-secgrid">{bars}</div></div>'
 
 
# ── 컴팩트 매트릭스 ──────────────────────────────────────────────────
 
def _matrix_df(leaders, limit=MATRIX_LIMIT):
    rows = []
    for s in leaders[:limit]:
        comp = s.get("comp") or {}
        rows.append({
            "종목": s.get("name"), "업종": s.get("upjong") or "기타",
            "그룹": s.get("group") or "기타",
            "지속성": comp.get("trend"), "모멘텀": s.get("mom_3m"),
            "거래대금": s.get("turnover_eok") or 0, "점수": s.get("score"),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.dropna(subset=["지속성", "모멘텀"])
    return df
 
 
def _render_matrix(leaders):
    df = _matrix_df(leaders)
    if df.empty or len(df) < 3:
        st.caption("매트릭스를 그릴 주도주가 부족해요. (게이트가 너무 강하면 약/중으로 낮춰보세요)")
        return
    groups = [g for g in GROUP_COLORS if g in set(df["그룹"])]
    scale = alt.Scale(domain=groups, range=[GROUP_COLORS[g] for g in groups])
 
    px = float(df["지속성"].median())
    py = float(df["모멘텀"].median())
 
    base = alt.Chart(df)
    pts = base.mark_circle(opacity=0.62).encode(
        x=alt.X("지속성:Q", scale=alt.Scale(zero=False),
                axis=alt.Axis(title="추세 지속성 →", labelColor="#9a9b92", gridColor="#ECEDE7")),
        y=alt.Y("모멘텀:Q", scale=alt.Scale(zero=False),
                axis=alt.Axis(title="3개월 모멘텀(%) →", labelColor="#9a9b92", gridColor="#ECEDE7")),
        size=alt.Size("거래대금:Q", scale=alt.Scale(range=[30, 520]), legend=None),
        color=alt.Color("그룹:N", scale=scale,
                        legend=alt.Legend(title=None, orient="bottom", columns=4,
                                          labelFontSize=9, symbolSize=55)),
        tooltip=[alt.Tooltip("종목:N"), alt.Tooltip("업종:N"),
                 alt.Tooltip("점수:Q"), alt.Tooltip("모멘텀:Q", title="3M%", format=".1f"),
                 alt.Tooltip("지속성:Q", format=".0f"),
                 alt.Tooltip("거래대금:Q", title="거래대금(억)", format=",.0f")],
    )
    vrule = alt.Chart(pd.DataFrame({"x": [px]})).mark_rule(
        color="#9a9b92", strokeDash=[4, 4], opacity=0.6).encode(x="x:Q")
    hrule = alt.Chart(pd.DataFrame({"y": [py]})).mark_rule(
        color="#9a9b92", strokeDash=[4, 4], opacity=0.6).encode(y="y:Q")
    lead = alt.Chart(pd.DataFrame({
        "x": [float(df["지속성"].max())], "y": [float(df["모멘텀"].max())],
        "t": ["주도 영역"]})).mark_text(
        align="right", dx=-2, dy=2, fontSize=11, fontWeight="bold",
        color="#7E9A83").encode(x="x:Q", y="y:Q", text="t:N")
 
    try:
        chart = (alt.layer(vrule, hrule, pts, lead)
                 .properties(height=MATRIX_HEIGHT, background="transparent")
                 .configure_view(strokeWidth=0))
    except Exception:
        chart = pts.properties(height=MATRIX_HEIGHT, background="transparent")
    try:
        mx_box = st.container(key="ldr_matrix")
    except TypeError:                 # 구버전 Streamlit 폴백(스코프만 생략, 동작은 정상)
        mx_box = st.container()
    with mx_box:
        st.altair_chart(chart, use_container_width=True)
 
 
def _render_sector_detail(rank, sec, leaders_by_upj):
    upj = sec.get("upjong")
    members = sorted(leaders_by_upj.get(upj, []), key=lambda x: x.get("score", 0), reverse=True)
    if not members:
        return
    label = (f"{rank+1}.  {upj}   ·   주도 {sec.get('score','')}점   ·   "
             f"1M {sec.get('mom_1m','')}%   ·   주도주 {len(members)}")
    with st.expander(label, expanded=False):
        col = _grp_color(sec.get("group"))
        head = (
            '<div class="ldr-sec-head">'
            f'<span class="gp" style="background:{col}1f;color:{col}">{html.escape(sec.get("group","") or "")}</span>'
            f'<div style="flex:1">{_bar(sec.get("score"))}</div>'
            f'<span class="mt">3M {_pc(sec.get("mom_3m"))} · 폭 {sec.get("breadth","")}%</span>'
            '</div>'
        )
        cards = "".join(_stock_card_html(s) for s in members[:CARDS_PER_SECTOR])
        st.markdown(head + f'<div class="ldr-grid">{cards}</div>', unsafe_allow_html=True)
 
 
# ── 메인 ─────────────────────────────────────────────────────────────
 
def render_leaders():
    tab_header("주도주", css=_CSS)
 
    with st.expander("ⓘ 주도주 보는 법", expanded=False):
        st.markdown('<div class="ldr-help">', unsafe_allow_html=True)
        st.markdown(_HELP_MD)
        st.markdown('</div>', unsafe_allow_html=True)
 
    try:
        from modules import db
        payload = db.load_leaders() if db.supabase_configured() else None
    except Exception:
        payload = None
 
    if not payload or not payload.get("stocks"):
        st.markdown(
            '<div class="empty"><div class="ico">🏇</div>'
            '<div class="msg">아직 주도주 스냅샷이 없어요</div>'
            '<div class="hint">엔진(Actions → \'주도주 수집\')을 한 번 실행하면 '
            '주도 섹터·주도주가 여기에 떠요</div></div>',
            unsafe_allow_html=True)
        return
 
    stocks = payload.get("stocks") or []
    sectors = payload.get("sectors") or []
    params = payload.get("params") or {}
    asof = payload.get("asof", "")
 
    leaders = _leaders(stocks)
    if not leaders:
        # 게이트가 너무 강해 0개면 점수 상위로 폴백 표시(빈 화면 방지)
        leaders = stocks[:MATRIX_LIMIT]
 
    n_new = sum(1 for s in leaders if s.get("is_new"))
    top_sec = sectors[0]["upjong"] if sectors else "–"
    gate = params.get("gate_preset", "")
    uni_n = params.get("universe_n")
    scan_n = params.get("scanned_n") or len(stocks)
    lead_n = params.get("leaders_n", len(leaders))
 
    if isinstance(uni_n, int):
        strip = (f'기준 <b>{html.escape(str(asof))}</b>'
                 f'<span class="arw">·</span>유니버스 <b>{uni_n:,}</b>'
                 f'<span class="arw">→</span>정밀스캔 <b>{scan_n:,}</b>'
                 f'<span class="arw">→</span>주도 <b>{lead_n:,}</b>'
                 + (f' <span class="ldr-sub">(게이트 {html.escape(str(gate))})</span>' if gate else "")
                 + f'<span class="arw">·</span>선두 <b>{html.escape(str(top_sec))}</b>'
                 + (f'<span class="arw">·</span>NEW <b>{n_new}</b>' if n_new else ""))
    else:
        strip = (f'기준 <b>{html.escape(str(asof))}</b><span class="arw">·</span>'
                 f'주도 <b>{lead_n:,}</b>종목<span class="arw">·</span>'
                 f'주도 섹터 <b>{len(sectors)}</b>')
    st.markdown(f'<div class="ldr-strip">{strip}</div>', unsafe_allow_html=True)
 
    # ── 한눈에 보기: 매트릭스(좌) + 리더보드(우) ──
    st.markdown('<div class="ldr-h">한눈에 보기</div>', unsafe_allow_html=True)
    c_left, c_right = st.columns([1.05, 1], gap="large")
    with c_left:
        st.markdown('<div class="ldr-sub" style="margin-bottom:6px">주도 매트릭스 · '
                    '가로 추세지속성 · 세로 3M모멘텀 · 크기 거래대금</div>', unsafe_allow_html=True)
        _render_matrix(leaders)
        st.markdown('<div class="ldr-matnote">오른쪽 위가 주도 영역 · 점선=중앙값 · 색=대표그룹 · '
                    f'마우스를 올리면 종목·수치가 떠요. 주도주 {min(len(leaders), MATRIX_LIMIT)}종목 표시.</div>',
                    unsafe_allow_html=True)
    with c_right:
        st.markdown('<div class="ldr-sub" style="margin-bottom:6px">통합 리더보드 · 점수순 '
                    f'TOP {LEADERBOARD_N}</div>', unsafe_allow_html=True)
        st.markdown(_leaderboard_compact(leaders), unsafe_allow_html=True)
 
    # ── 주도 섹터 강도 ──
    st.markdown('<div class="ldr-h">주도 섹터 강도 · 색=1개월 모멘텀 · 길이=주도 점수</div>',
                unsafe_allow_html=True)
    st.markdown(_sector_bars_html(sectors, leaders), unsafe_allow_html=True)
 
    # ── (보조·접힘) 섹터별 주도주 자세히 ──
    leaders_by_upj = {}
    for s in leaders:
        leaders_by_upj.setdefault(s.get("upjong"), []).append(s)
    detail_secs = [s for s in sectors if leaders_by_upj.get(s.get("upjong"))][:DETAIL_SECTORS]
    if detail_secs:
        st.markdown('<div class="ldr-h">섹터별 주도주 자세히 · 펼쳐 보기</div>', unsafe_allow_html=True)
        for i, sec in enumerate(detail_secs):
            _render_sector_detail(i, sec, leaders_by_upj)
 
    w = params.get("weights") or {}
    g = params.get("gate") or {}
    gate_txt = ""
    if g:
        gate_txt = (f" · 게이트('{gate}'): RS>0 · 3M>0"
                    + (f" · 고점 {g.get('high_min',0):.0f}%↑" if g.get("high_min") else "")
                    + (" · 60일선↑" if g.get("above_ma60") else "")
                    + (" · 정배열" if g.get("aligned") else "")
                    + (f" · 거래대금 {g.get('turnover_min',0):.0f}억↑" if g.get("turnover_min") else ""))
    st.caption(
        "주도 점수 = 모멘텀·상대강도·추세지속성·유동성·신고가근접 가중합"
        + (f" ({int(w.get('mom',0)*100)}/{int(w.get('rs',0)*100)}/{int(w.get('trend',0)*100)}/"
           f"{int(w.get('liq',0)*100)}/{int(w.get('high',0)*100)})" if w else "")
        + gate_txt
        + " · 우선주·스팩·리츠·ETF 제외 · 상대강도=코스피/코스닥 대비 초과수익 · "
        "데이터: Naver · 장마감 후 1일 1회 갱신 · 투자판단의 근거가 아니라 모니터링용 참고치예요."
    )
