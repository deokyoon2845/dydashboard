"""[뷰어] 주도주 — 주식 탭의 '주도주' 하위탭.

레이아웃 = A안(계층형) + C안(매트릭스) 조합
  · 도움말(주도주 보는 법) expander
  · 상단 요약: 주도 매트릭스(산점도) + 통합 주도주 리더보드(B안: 미니차트 강조 + 전일등락)
  · 메인: 주도 섹터(업종) 랭킹 → 좌5·우5 2열, 각 섹터(expander) 펼치면 상위 10종목 카드

데이터는 Supabase(leaders 최신 스냅샷)만 읽는다(엔진이 채움). 외부 API 직접호출 없음.
payload 구조(engine.leaders_collect.collect): {asof, asof_date, params, sectors[], stocks[]}
  · stocks[] : {code,name,market,upjong,group,score,comp{...},mom_1d,mom_1w,mom_1m,mom_3m,
                rs_3m,mcap_eok,turnover_eok,high_ratio,aligned,streak,is_new,spark[]}
"""

import html

import altair as alt
import pandas as pd
import streamlit as st

from modules.stocks import naver_stock_url

SHOW_SECTORS = 10          # 화면에 펼칠 주도 섹터 수 (좌5·우5 2열)
CARDS_PER_SECTOR = 10      # 섹터당 표시 종목 수
MATRIX_LIMIT = 140         # 매트릭스에 찍을 상위 종목 수(가독성)
MATRIX_HEIGHT = 900        # 매트릭스 높이(px) — 모멘텀 축이 넓어 3배로 키움
LEADERBOARD_N = 15         # 통합 리더보드 종목 수

# 대표그룹 → 색 (engine COARSE_RULES의 그룹명과 일치 · 카테고리 구분용)
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
  padding:10px 14px;font-size:12.5px;color:var(--sage-deep);font-weight:600;margin:2px 0 14px;line-height:1.7;}
.ldr-strip b{color:var(--ink);font-weight:700;} .ldr-strip b.up{color:var(--up);} .ldr-strip b.down{color:var(--down);}
.ldr-h{font-size:12px;font-weight:700;letter-spacing:.05em;color:var(--muted);text-transform:uppercase;margin:18px 0 10px;}
.ldr-bar{height:7px;background:var(--summary-bg);border-radius:5px;overflow:hidden;}
.ldr-bar>i{display:block;height:100%;background:var(--sage-deep);border-radius:5px;}
.ldr-new{display:inline-block;background:#eef4ef;color:var(--sage-deep);font-size:9.5px;font-weight:700;
  padding:1px 5px;border-radius:5px;margin-left:5px;vertical-align:1px;}
.ldr-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:9px;margin:4px 0 4px;}
.ldr-card{border:1px solid var(--line);border-radius:11px;background:var(--card);padding:11px 13px;
  transition:border-color .15s,transform .15s;}
.ldr-card:hover{border-color:var(--sage-deep);transform:translateY(-1px);}
.ldr-card .top{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px;}
.ldr-card .nm{font-size:13px;font-weight:700;}
.ldr-card .nm a{color:var(--ink);text-decoration:none;} .ldr-card .nm a:hover{text-decoration:underline;}
.ldr-card .sc{font-size:11px;color:var(--muted);font-weight:600;}
.ldr-card .met{display:flex;gap:12px;margin-top:9px;font-size:11px;color:var(--muted);flex-wrap:wrap;}
.ldr-card .sub{display:flex;justify-content:space-between;margin-top:6px;font-size:10.5px;color:var(--muted);}
.ldr-up{color:var(--up);font-weight:700;} .ldr-down{color:var(--down);font-weight:700;}
.ldr-dot-hi{color:var(--up);} .ldr-dot-mid{color:var(--sage-deep);} .ldr-dot-lo{color:var(--muted);}
.ldr-pill{display:inline-block;font-size:10px;font-weight:700;padding:2px 7px;border-radius:6px;}
/* 통합 리더보드 — B안(미니차트 강조) */
.ldr-lb2{display:flex;align-items:center;gap:12px;padding:11px 2px;border-bottom:1px solid var(--line);}
.ldr-lb2 .rk{width:20px;text-align:center;font-size:12px;font-weight:700;flex:none;}
.ldr-lb2 .nmcol{width:120px;flex:none;}
.ldr-lb2 .nmcol .nm{font-size:13px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.ldr-lb2 .nmcol .nm a{color:var(--ink);text-decoration:none;} .ldr-lb2 .nmcol .nm a:hover{text-decoration:underline;}
.ldr-lb2 .nmcol .sub2{margin-top:4px;white-space:nowrap;}
.ldr-lb2 .nmcol .scp{font-size:10.5px;color:var(--muted);font-weight:600;margin-left:6px;}
.ldr-lb2 .spk{flex:1;position:relative;min-width:70px;}
.ldr-lb2 .spk .m3{position:absolute;left:2px;top:0;font-size:10px;font-weight:700;}
.ldr-lb2 .d1{width:72px;text-align:right;font-size:12px;flex:none;}
.ldr-lb2 .d1 .d1l{font-size:9.5px;color:var(--muted);margin-top:2px;}
.ldr-sec-head{display:flex;align-items:center;gap:11px;margin:2px 0 10px;}
.ldr-sec-head .gp{font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:6px;}
.ldr-sec-head .mt{font-size:11.5px;color:var(--muted);}
.ldr-help{font-size:13.5px;line-height:1.8;color:var(--ink);}
.ldr-help b{color:var(--sage-deep);}
</style>
"""

_HELP_MD = """
**추세 지속성** — 주가가 얼마나 *꾸준히* 우상향했는지를 0~100으로 본 값입니다.
20·60·120일 이동평균 정배열 여부, 최근 60일 중 주가가 20일선 위에 머문 비율,
연속 상승일을 합쳐 계산해요. 높을수록 "깔끔하게 오르는" 추세입니다. (매트릭스 가로축)

**모멘텀(3개월)** — 최근 3개월 수익률입니다. 하루 급등이 아니라 *일정 기간* 오른 정도를 봐요. (매트릭스 세로축)

**주도 점수(종목, 0~100)** — 5개 축의 가중합입니다.
- 모멘텀 35 · 상대강도 20 · 추세지속성 20 · 유동성 15 · 신고가근접 10
- **상대강도** = 코스피/코스닥 지수 대비 초과수익 (시장보다 세게 가는가)
- **유동성** = 평균 거래대금 (돈이 몰리는가)
- **신고가근접** = 52주 고가 대비 현재가

**주도주 선정 기준** — 시총 2,000억↑ · 평균 거래대금 30억↑ · 3개월 수익률 산출 가능 ·
**우선주·스팩·리츠·ETF 제외** (ETF는 개별 주도 종목이 아니라서 뺍니다). 그 안에서 점수순으로 줄세웁니다.

**주도 섹터(업종) 선정 기준** — 구성종목이 4개 이상인 업종만 집계합니다.
섹터 점수 = 상위 5종목 평균점수 × 0.5 + 폭(breadth) × 0.3 + 업종 모멘텀 × 0.2.
**폭** = 업종 안에서 (1개월 수익률 +이고 정배열인) 종목 비율 →
1~2 종목만 튄 '가짜 주도'와 섹터 전반이 오르는 '진짜 주도'를 구분합니다.

**NEW 뱃지** — 직전 갱신 대비 처음으로 주도 그룹(점수 60↑)에 진입한 종목입니다.

**매트릭스 읽는 법** — 가로=추세 지속성, 세로=3개월 모멘텀, 버블 크기=거래대금, 색=대표그룹.
오른쪽 위(꾸준 + 강함)가 주도 영역, 점선은 중앙값입니다.

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


def _spark_svg(vals, color, height=42):
    """종가 리스트 → 전폭 미니 라인차트(SVG). vals 없으면 빈 문자열."""
    vals = [v for v in (vals or []) if isinstance(v, (int, float))]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rg = (hi - lo) or 1
    n = len(vals)
    pts = " ".join(
        f"{i/(n-1)*100:.1f},{height-2-((v-lo)/rg)*(height-4):.1f}"
        for i, v in enumerate(vals)
    )
    return (
        f'<svg viewBox="0 0 100 {height}" preserveAspectRatio="none" '
        f'style="width:100%;height:{height}px;display:block">'
        f'<polygon points="{pts} 100,{height} 0,{height}" style="fill:{color};opacity:.10"/>'
        f'<polyline points="{pts}" style="fill:none;stroke:{color};stroke-width:1.6;opacity:.85"/></svg>'
    )


def _d1(v):
    """전일대비 등락률 배지."""
    if v is None:
        return '<span style="color:var(--muted)">–</span>'
    up = v >= 0
    c = "var(--up)" if up else "var(--down)"
    ar = "▲" if up else "▼"
    return f'<span style="color:{c};font-weight:700">{ar} {"+" if up else ""}{v:.1f}%</span>'


def _stock_card_html(s):
    nm = html.escape(s.get("name", ""))
    url = html.escape(naver_stock_url(s.get("name", "")))
    new = '<span class="ldr-new">NEW</span>' if s.get("is_new") else ""
    aligned = ' · <span style="color:var(--sage-deep)">정배열</span>' if s.get("aligned") else ""
    cap = s.get("mcap_eok")
    cap_txt = f"{cap/10000:.1f}조" if cap and cap >= 10000 else (f"{cap:,.0f}억" if cap else "–")
    turn = s.get("turnover_eok")
    turn_txt = f"{turn:,.0f}억" if turn else "–"
    return (
        '<div class="ldr-card">'
        f'<div class="top"><div class="nm"><a href="{url}" target="_blank" rel="noopener">{nm}</a>{new}</div>'
        f'<div class="sc">{s.get("score","")}점</div></div>'
        f'{_bar(s.get("score"))}'
        f'<div class="met"><span>1M {_pc(s.get("mom_1m"))}</span>'
        f'<span>3M {_pc(s.get("mom_3m"))}</span>'
        f'<span>RS {_pc(s.get("rs_3m"))}</span></div>'
        f'<div class="sub"><span>시총 {cap_txt} · 거래대금 {turn_txt}{aligned}</span>'
        f'<span>{_hi_dot(s.get("high_ratio"))}</span></div>'
        '</div>'
    )


def _leaderboard_html(stocks, n=LEADERBOARD_N):
    """B안 — 미니차트 강조 + 전일등락."""
    rows = ""
    for i, s in enumerate(stocks[:n]):
        col = _grp_color(s.get("group"))
        nm = html.escape(s.get("name", ""))
        url = html.escape(naver_stock_url(s.get("name", "")))
        new = '<span class="ldr-new">NEW</span>' if s.get("is_new") else ""
        rank_col = "var(--up)" if i < 3 else "var(--muted)"
        up3 = (s.get("mom_3m") or 0) >= 0
        spc = "var(--up)" if up3 else "var(--down)"
        spark = _spark_svg(s.get("spark"), spc, 42)
        upj = html.escape((s.get("upjong") or "")[:8])
        rows += (
            '<div class="ldr-lb2">'
            f'<div class="rk" style="color:{rank_col}">{i+1}</div>'
            '<div class="nmcol">'
            f'<div class="nm"><a href="{url}" target="_blank" rel="noopener">{nm}</a>{new}</div>'
            f'<div class="sub2"><span class="ldr-pill" style="background:{col}1f;color:{col}">{upj}</span>'
            f'<span class="scp">{s.get("score","")}점</span></div></div>'
            f'<div class="spk">{spark}<span class="m3" style="color:{spc}">3M {_pc(s.get("mom_3m"))}</span></div>'
            f'<div class="d1">{_d1(s.get("mom_1d"))}<div class="d1l">전일</div></div>'
            '</div>'
        )
    return rows


def _matrix_df(stocks, limit=MATRIX_LIMIT):
    rows = []
    for s in stocks[:limit]:
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


def _render_matrix(stocks):
    df = _matrix_df(stocks)
    if df.empty or len(df) < 3:
        st.caption("매트릭스를 그릴 데이터가 부족해요.")
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
        size=alt.Size("거래대금:Q", scale=alt.Scale(range=[40, 900]), legend=None),
        color=alt.Color("그룹:N", scale=scale,
                        legend=alt.Legend(title=None, orient="bottom", columns=5,
                                          labelFontSize=10, symbolSize=70)),
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
        align="right", dx=-2, dy=2, fontSize=12, fontWeight="bold",
        color="#7E9A83").encode(x="x:Q", y="y:Q", text="t:N")

    try:
        chart = (alt.layer(vrule, hrule, pts, lead)
                 .properties(height=MATRIX_HEIGHT, background="transparent")
                 .configure_view(strokeWidth=0))
    except Exception:
        chart = pts.properties(height=MATRIX_HEIGHT, background="transparent")
    st.altair_chart(chart, use_container_width=True)
    st.caption("오른쪽 위(추세 지속성↑·모멘텀↑)가 주도 영역 · 점선=중앙값 · "
               "버블 크기=거래대금 · 색=대표그룹 · 마우스를 올리면 종목·수치가 떠요. "
               f"상위 {min(len(df), MATRIX_LIMIT)}종목 표시.")


def _render_sector(rank, sec, by_upjong):
    upj = sec.get("upjong")
    members = sorted(by_upjong.get(upj, []), key=lambda x: x.get("score", 0), reverse=True)
    label = (f"{rank+1}.  {upj}   ·   주도 {sec.get('score','')}점   ·   "
             f"1M {sec.get('mom_1m','')}%   ·   폭 {sec.get('breadth','')}%   ·   "
             f"{sec.get('n','')}종목")
    with st.expander(label, expanded=(rank == 0)):
        col = _grp_color(sec.get("group"))
        head = (
            '<div class="ldr-sec-head">'
            f'<span class="gp" style="background:{col}1f;color:{col}">{html.escape(sec.get("group","") or "")}</span>'
            f'<div style="flex:1">{_bar(sec.get("score"))}</div>'
            f'<span class="mt">3M {_pc(sec.get("mom_3m"))} · 지속성 {sec.get("persist","")}</span>'
            '</div>'
        )
        cards = "".join(_stock_card_html(s) for s in members[:CARDS_PER_SECTOR])
        st.markdown(head + f'<div class="ldr-grid">{cards}</div>', unsafe_allow_html=True)


def render_leaders():
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown('<div class="accent-bar"></div>', unsafe_allow_html=True)
    st.title("주도주")

    with st.expander("ⓘ 주도주 보는 법", expanded=False):
        st.markdown(f'<div class="ldr-help">', unsafe_allow_html=True)
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

    n_new = sum(1 for s in stocks if s.get("is_new"))
    top_sec = sectors[0]["upjong"] if sectors else "–"
    if isinstance(params.get("universe_n"), int):
        strip = (f'기준 <b>{html.escape(str(asof))}</b> · '
                 f'유니버스 <b>{params.get("universe_n"):,}</b>종목 → 후보 <b>{len(stocks):,}</b> · '
                 f'주도 섹터 <b>{len(sectors)}</b> (선두 <b>{html.escape(str(top_sec))}</b>) · '
                 f'NEW <b>{n_new}</b>')
    else:
        strip = (f'기준 <b>{html.escape(str(asof))}</b> · 후보 <b>{len(stocks):,}</b>종목 · '
                 f'주도 섹터 <b>{len(sectors)}</b> · NEW <b>{n_new}</b>')
    st.markdown(f'<div class="ldr-strip">{strip}</div>', unsafe_allow_html=True)

    # ── 상단 요약(C안): 매트릭스 + 통합 리더보드 ──
    st.markdown('<div class="ldr-h">주도 매트릭스</div>', unsafe_allow_html=True)
    _render_matrix(stocks)

    st.markdown('<div class="ldr-h">통합 주도주 리더보드 · 점수순</div>', unsafe_allow_html=True)
    st.markdown(_leaderboard_html(stocks), unsafe_allow_html=True)

    # ── 메인(A안): 주도 섹터 → 주도주 (좌5·우5 2열) ──
    st.markdown('<div class="ldr-h">주도 섹터 · 펼치면 주도주</div>', unsafe_allow_html=True)

    by_upjong = {}
    for s in stocks:
        by_upjong.setdefault(s.get("upjong"), []).append(s)

    shown = sectors[:SHOW_SECTORS]
    cols = st.columns(2, gap="medium")
    for i, sec in enumerate(shown):
        with cols[0 if i < 5 else 1]:
            _render_sector(i, sec, by_upjong)

    w = params.get("weights") or {}
    st.caption(
        "주도 점수 = 모멘텀·상대강도·추세지속성·유동성·신고가근접 가중합"
        + (f" ({int(w.get('mom',0)*100)}/{int(w.get('rs',0)*100)}/{int(w.get('trend',0)*100)}/"
           f"{int(w.get('liq',0)*100)}/{int(w.get('high',0)*100)})" if w else "")
        + f" · 시총 {params.get('mcap_min_eok','–')}억↑ · 평균거래대금 {params.get('turnover_min_eok','–')}억↑ · "
        "우선주·스팩·리츠·ETF 제외 · 상대강도=코스피/코스닥 대비 초과수익 · "
        "데이터: Naver · 장마감 후 1일 1회 갱신 · 투자판단의 근거가 아니라 모니터링용 참고치예요."
    )
