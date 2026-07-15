"""시장 지표(체온계): 공포·탐욕 지수 + VIX 차트 · RSI.

2026-06 추가:
- 지표 설명 팝오버(st.popover): 공포·탐욕 / VIX / RSI 해석 가이드. 구버전이면 캡션 폴백.
- VIX 차트 인터랙티브: hover 크로스헤어 + 가로 스크롤·드래그 x줌 (실패 시 정적 폴백).
"""

import altair as alt
import pandas as pd
import streamlit as st

from modules.indices import fetch_history, fetch_index

_RSI_TARGETS = {"코스피": "^KS11", "코스닥": "^KQ11", "S&P500": "^GSPC", "나스닥": "^IXIC"}

_RATING_KO = {
    "extreme fear": "극단적 공포", "fear": "공포", "neutral": "중립",
    "greed": "탐욕", "extreme greed": "극단적 탐욕",
}


def compute_rsi(ticker, period=14):
    """지수 종가로 RSI(기본 14). 실패 시 None."""
    close = fetch_history(ticker)
    if close is None or len(close) < period + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    g, l = avg_gain.iloc[-1], avg_loss.iloc[-1]
    if l == 0:
        return 100.0
    return float(100 - 100 / (1 + g / l))


# ── 시장 국면 판정(체온계 종합) — 부동산 사이클과 대칭인 '위험선호' 모델 ──
# 공포·탐욕 / VIX / RSI 평균 / 수급(코스피 5거래일)을 각각 -1(위험회피)~+1(위험선호)
# 점수로 정규화한 뒤, 가용 지표의 단순 평균 = 종합 강도 s 로 국면을 판정한다.
# 매매 신호가 아니라 '시장이 위험을 얼마나 감수하려 하나'를 읽는 온도계.
# ★임계값은 전부 아래 상수 — 체감과 다르면 여기만 조정하면 된다.
_PHASES = ["위험회피", "경계", "중립", "위험선호"]
_PHASE_BANDS = (-0.40, -0.10, 0.30)   # s<-0.40 회피 · <-0.10 경계 · <+0.30 중립 · 이상 선호


def _score_fng(score):
    """공포·탐욕 0~100 → CNN 5구간 그대로 -1~+1."""
    if score is None:
        return None
    if score < 25:
        return -1.0
    if score < 45:
        return -0.5
    if score <= 55:
        return 0.0
    if score <= 75:
        return 0.5
    return 1.0


def _score_vix(v):
    """VIX 레벨 점수. 저변동성은 우호적이나 그 자체가 안일함(과열) 신호일 수 있어 +0.5 캡."""
    if v is None:
        return None
    if v < 17:
        return 0.5
    if v < 25:
        return 0.0
    if v < 30:
        return -0.5
    return -1.0


def _score_rsi(avg):
    """RSI 평균 → 점수. 국면 측정이므로 고RSI=위험선호(+), 저RSI=위험회피(−)."""
    if avg is None:
        return None
    if avg >= 65:
        return 1.0
    if avg >= 55:
        return 0.5
    if avg > 45:
        return 0.0
    if avg > 35:
        return -0.5
    return -1.0


def _score_flow(f_sum, i_sum):
    """코스피 최근 5거래일 외국인·기관 순매수 '방향' 합 → (sign+sign)/2 = ±1·±0.5·0."""
    def _sgn(x):
        return 1 if x > 0 else (-1 if x < 0 else 0)
    return (_sgn(f_sum) + _sgn(i_sum)) / 2.0


_FLOW_WORD = {1.0: "동반 매수", 0.5: "매수 우위", 0.0: "혼조",
              -0.5: "매도 우위", -1.0: "동반 매도"}


def _phase_payload(fng, rsi_vals):
    """국면 위젯 데이터 — parts=[{name,val,s}] · 가용 지표 평균 s → phase 인덱스.
    가용 지표 0개면 None(위젯 조용히 생략). 일부 실패는 나머지로 판정하고 개수 표기."""
    parts = []
    if fng and fng.get("score") is not None:
        rating = _RATING_KO.get(str(fng.get("rating", "")).lower(), "")
        val = f'{fng["score"]}' + (f" · {rating}" if rating else "")
        parts.append({"name": "공포·탐욕", "val": val, "s": _score_fng(fng["score"])})
    try:
        d = fetch_index("^VIX")
        vix = float(d["current"]) if d else None
    except Exception:
        vix = None
    if vix is not None:
        parts.append({"name": "VIX", "val": f"{vix:.1f}", "s": _score_vix(vix)})
    rs = [v for v in (rsi_vals or {}).values() if v is not None]
    if rs:
        avg = sum(rs) / len(rs)
        parts.append({"name": "RSI 평균", "val": f"{avg:.0f}", "s": _score_rsi(avg)})
    try:
        from modules.supply_trend import _fetch_investor
        df = _fetch_investor("01")
    except Exception:
        df = None
    if df is not None and not df.empty:
        t = df.tail(5)
        s = _score_flow(float(t["외국인"].sum()), float(t["기관"].sum()))
        parts.append({"name": "수급 5일", "val": _FLOW_WORD.get(s, "혼조"), "s": s})

    parts = [p for p in parts if p["s"] is not None]
    if not parts:
        return None
    score = sum(p["s"] for p in parts) / len(parts)
    if score < _PHASE_BANDS[0]:
        ph = 0
    elif score < _PHASE_BANDS[1]:
        ph = 1
    elif score < _PHASE_BANDS[2]:
        ph = 2
    else:
        ph = 3
    return {"score": score, "phase": ph, "parts": parts}


_PHASE_CSS = """
<style>
.tmo{background:#fff;border:1px solid var(--line,#ECEDE7);border-radius:16px;padding:13px 16px;margin:0 0 14px;}
.tmo-top{display:flex;justify-content:space-between;align-items:baseline;gap:10px;flex-wrap:wrap;}
.tmo-top .t{font-size:12px;font-weight:700;color:var(--ink,#34352f);}
.tmo-top .r{font-size:11.5px;color:var(--muted,#9a9b92);font-weight:600;}
.tmo-top .r b{color:var(--sage-deep,#7E9A83);}
.tmo-ph{display:flex;gap:6px;margin:10px 0 11px;}
.tmo-ph .p{flex:1;text-align:center;padding:8px 4px;border-radius:10px;border:1px solid var(--line,#ECEDE7);
  background:#fff;font-size:12.5px;font-weight:700;color:var(--muted,#9a9b92);}
.tmo-ph .p.on{border-color:var(--sage-deep,#7E9A83);background:#F1F5F0;color:var(--sage-deep,#7E9A83);}
.tmo-parts{display:flex;gap:7px;flex-wrap:wrap;}
.tmo-chip{display:inline-flex;align-items:baseline;gap:5px;background:var(--summary-bg,#F6F7F2);
  border:1px solid var(--line,#ECEDE7);border-radius:9px;padding:5px 10px;font-size:11.5px;
  font-weight:600;color:var(--pill-ink,#5d6258);white-space:nowrap;}
.tmo-chip b{font-size:12px;font-weight:700;}
.tmo-chip b.u{color:var(--up,#B65F5A);}
.tmo-chip b.d{color:var(--down,#5A7CA0);}
.tmo-chip b.n{color:var(--ink,#34352f);}
.tmo-foot{font-size:11px;color:var(--muted,#9a9b92);margin-top:9px;line-height:1.55;}
</style>"""


def _phase_html(pp):
    """국면 위젯 HTML — 4국면 필 + 판정 근거 칩 + 종합 강도 푸터."""
    pills = "".join(
        f'<div class="p{" on" if i == pp["phase"] else ""}">{name}</div>'
        for i, name in enumerate(_PHASES))
    chips = ""
    for p in pp["parts"]:
        cls = "u" if p["s"] > 0 else ("d" if p["s"] < 0 else "n")
        chips += (f'<span class="tmo-chip">{p["name"]} '
                  f'<b class="{cls}">{p["val"]}</b></span>')
    pos = sum(1 for p in pp["parts"] if p["s"] > 0)
    neg = sum(1 for p in pp["parts"] if p["s"] < 0)
    neu = len(pp["parts"]) - pos - neg
    return (f'<div class="tmo">'
            f'<div class="tmo-top"><span class="t">시장 국면 판정</span>'
            f'<span class="r">{len(pp["parts"])}지표 종합 → 현재 '
            f'<b>{_PHASES[pp["phase"]]}</b></span></div>'
            f'<div class="tmo-ph">{pills}</div>'
            f'<div class="tmo-parts">{chips}</div>'
            f'<div class="tmo-foot">판정 근거 — 위험선호 {pos} · 중립 {neu} · '
            f'위험회피 {neg} → 종합 강도 {pp["score"]:+.2f} '
            f'(밴드 {_PHASE_BANDS[0]:+.2f} / {_PHASE_BANDS[1]:+.2f} / '
            f'{_PHASE_BANDS[2]:+.2f})</div>'
            f'</div>')


@st.cache_data(ttl=1800)
def fetch_cnn_fng():
    """CNN 공포·탐욕 지수(미국). 비공식 API."""
    try:
        import requests
        r = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                     "Accept": "application/json"},
            timeout=10,
        )
        r.raise_for_status()
        fg = r.json().get("fear_and_greed", {})
        if fg.get("score") is None:
            return None
        return {"score": round(float(fg["score"])), "rating": fg.get("rating", ""),
                "asof": _fng_asof(fg.get("timestamp"))}
    except Exception:
        return None


def _fng_asof(ts):
    """CNN timestamp(ISO 또는 ms)를 KST 'YYYY-MM-DD HH:MM'로."""
    if ts is None:
        return None
    try:
        from datetime import datetime, timezone, timedelta
        kst = timezone(timedelta(hours=9))
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt.astimezone(kst).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)[:16]


def _rsi_state(v):
    if v >= 70:
        return "과매수", "up"
    if v <= 30:
        return "과매도", "down"
    return "중립", ""


def _rsi_asof():
    """RSI 대상 지수들의 가장 최근 종가일 (YYYY-MM-DD)."""
    dates = []
    for tk in _RSI_TARGETS.values():
        c = fetch_history(tk)
        if c is not None and len(c):
            try:
                dates.append(c.index[-1].strftime("%Y-%m-%d"))
            except Exception:
                pass
    return max(dates) if dates else "—"


def _metric_help():
    """체온계 지표 해석 팝오버. st.popover 미지원(구버전)이면 조용히 생략."""
    if not hasattr(st, "popover"):
        return
    with st.popover("ⓘ 지표 보는 법"):
        st.markdown(
            "**시장 국면 판정 (종합)**  \n"
            "공포·탐욕 / VIX / RSI 평균 / 수급(코스피 5거래일)을 각각 -1(위험회피)~"
            "+1(위험선호)로 점수화해 평균낸 종합 강도로 국면을 판정해요. "
            "-0.40 미만 위험회피 · -0.10 미만 경계 · +0.30 미만 중립 · 이상 위험선호. "
            "매매 신호가 아니라 '시장이 위험을 얼마나 감수하려 하나'를 읽는 온도계이며, "
            "일부 지표가 실패하면 가용 지표만으로 판정하고 개수를 표기해요.\n\n"
            "**공포·탐욕 지수 (CNN · 0~100)**  \n"
            "낮을수록 공포(투자자 위축), 높을수록 탐욕(과열). "
            "0~24 극단적 공포 · 25~44 공포 · 45~55 중립 · 56~75 탐욕 · 76~100 극단적 탐욕. "
            "지나친 공포는 저점, 지나친 탐욕은 고점 신호로 보는 역발상 지표로도 쓰여요.\n\n"
            "**VIX · 변동성 지수**  \n"
            "S&P500 옵션이 가리키는 향후 30일 기대 변동성. "
            "대략 20 이하면 안정, 30 이상이면 불안 구간. VIX↑=공포 확대 / VIX↓=시장 안정.\n\n"
            "**RSI(14)**  \n"
            "최근 14일 상승·하락 강도로 만든 0~100 모멘텀 지표. "
            "70 이상 과매수(단기 과열), 30 이하 과매도(단기 침체). "
            "강한 추세장에선 한쪽에 오래 머물 수 있어 단독보다 보조지표로 보세요."
        )


# ── VIX 6개월 차트 (우측) ────────────────────────────────────

_VIX_CSS = """
<style>
/* 공포탐욕 게이지 인디케이터: 막대 → 동그라미 */
.gauge{position:relative;height:8px;border-radius:5px;
  background:linear-gradient(90deg,#5A7CA0 0%,#A7BBA9 50%,#B65F5A 100%);margin:14px 0 7px;}
.gauge .dot{position:absolute;top:50%;width:16px;height:16px;border-radius:50%;
  background:#fff;border:3px solid var(--ink,#34352f);
  transform:translate(-50%,-50%);box-shadow:0 1px 3px rgba(0,0,0,.25);}
/* 지표 2단(공포탐욕 | VIX 차트) */
.tmpr-2col{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:10px;align-items:stretch;}
@media(max-width:760px){.tmpr-2col{grid-template-columns:1fr;}}
.tmpr-card{background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);border-radius:16px;
  padding:14px 16px 12px;}
.vix-head{display:flex;align-items:baseline;gap:8px;margin-bottom:2px;}
.vix-val{font-size:21px;font-weight:700;color:var(--ink,#34352f);letter-spacing:-.02em;}
.vix-chg{font-size:12.5px;font-weight:700;}
.vix-chg.up{color:var(--up,#B65F5A);} .vix-chg.down{color:var(--down,#5A7CA0);}
.vix-note{font-size:10.5px;color:var(--muted,#9a9b92);margin-top:6px;}

/* ── 마이크로 인터랙션 (미니멀 미스트) ── */
/* 지표 카드 등장 + 호버 */
@keyframes ind-fade-up{from{opacity:0;transform:translateY(8px);}to{opacity:1;transform:translateY(0);}}
.tmpr-card{animation:ind-fade-up .5s cubic-bezier(.22,.61,.36,1) both;
  transition:transform .2s ease,box-shadow .2s ease,border-color .2s ease;}
.tmpr-card:hover{transform:translateY(-2px);box-shadow:0 6px 18px rgba(52,53,47,.08);
  border-color:var(--sage,#A7BBA9);}
/* 공포·탐욕 게이지: 막대가 좌→우로 채워지고, 동그라미가 톡 등장 */
@keyframes ind-bar-grow{from{transform:scaleX(0);}to{transform:scaleX(1);}}
@keyframes ind-dot-pop{
  0%{opacity:0;transform:translate(-50%,-50%) scale(.2);}
  70%{opacity:1;transform:translate(-50%,-50%) scale(1.15);}
  100%{opacity:1;transform:translate(-50%,-50%) scale(1);}}
.gauge{transform-origin:left center;
  animation:ind-bar-grow .7s cubic-bezier(.22,.61,.36,1) both;}
.gauge .dot{animation:ind-dot-pop .5s cubic-bezier(.34,1.56,.64,1) .55s both;}
@media(prefers-reduced-motion:reduce){
  .tmpr-card,.gauge,.gauge .dot{animation:none !important;}
  .tmpr-card{transition:none !important;}
}
</style>
"""

# RSI 게이지 마커 등장 애니메이션 (app.py의 .rsi-gauge i를 보완)
_RSI_CSS = """
<style>
@keyframes rsi-marker-in{from{opacity:0;transform:translateX(-50%) scaleY(.3);}
  to{opacity:1;transform:translateX(-50%) scaleY(1);}}
.rsi-gauge i{animation:rsi-marker-in .5s ease .5s both;}
@media(prefers-reduced-motion:reduce){.rsi-gauge i{animation:none !important;}}
</style>
"""


def _vix_chart(df, line_c, y_dom):
    """VIX 라인(영역) 차트. 인터랙티브(hover 크로스헤어·x줌), 실패 시 정적 폴백."""
    x_enc = alt.X("날짜:T", axis=alt.Axis(title=None, format="%m/%d",
                                          labelColor="#9a9b92", grid=False))
    y_enc = alt.Y("VIX:Q", scale=alt.Scale(domain=y_dom, nice=False, clamp=True),
                  axis=alt.Axis(title=None, labelColor="#9a9b92", gridColor="#ECEDE7",
                                format=",.0f"))
    tip = [alt.Tooltip("날짜:T", format="%Y-%m-%d"), alt.Tooltip("VIX:Q", format=",.2f")]
    area = alt.Chart(df).mark_area(
        color=line_c, opacity=0.13,
        line={"color": line_c, "strokeWidth": 2},
    ).encode(x=x_enc, y=y_enc, tooltip=tip)
    try:
        hover = alt.selection_point(fields=["날짜"], nearest=True,
                                    on="mouseover", empty=False)
        zoom = alt.selection_interval(bind="scales", encodings=["x"])
        selectors = alt.Chart(df).mark_point().encode(
            x=x_enc, opacity=alt.value(0)).add_params(hover)
        rule = alt.Chart(df).mark_rule(color="#9a9b92", strokeDash=[3, 3]).encode(
            x=x_enc).transform_filter(hover)
        hpoints = alt.Chart(df).mark_point(size=55, color=line_c, filled=True).encode(
            x=x_enc, y=y_enc,
            opacity=alt.condition(hover, alt.value(1), alt.value(0)))
        return (alt.layer(area, selectors, rule, hpoints)
                .add_params(zoom)
                .properties(height=150, background="transparent")
                .configure_view(strokeWidth=0))
    except Exception:
        return (area.properties(height=150, background="transparent")
                .configure_view(strokeWidth=0))


def _vix_chart_card():
    """우측: VIX 6개월 라인 차트 (코스피 대형 차트와 동일한 룩, y축 min~max)."""
    close = fetch_history("^VIX", "6mo")
    if close is None or len(close) < 2:
        st.markdown(
            '<div class="tmpr-card"><div class="mkt-name">VIX · 변동성 지수 (6개월)</div>'
            '<div class="mkt-na">데이터 없음</div></div>', unsafe_allow_html=True)
        return

    df = pd.DataFrame({"날짜": pd.to_datetime(close.index),
                       "VIX": pd.to_numeric(close.values, errors="coerce")}).dropna()
    if len(df) < 2:
        st.markdown('<div class="tmpr-card"><div class="mkt-name">VIX (6개월)</div>'
                    '<div class="mkt-na">데이터 부족</div></div>', unsafe_allow_html=True)
        return

    cur = float(df["VIX"].iloc[-1])
    prev = float(df["VIX"].iloc[-2])
    change = cur - prev
    pct = (change / prev) * 100 if prev else 0.0
    # VIX는 하락이 시장에 우호적 → 색 반전(하락=파랑/안정, 상승=빨강/경계)
    up = change >= 0
    chg_cls = "up" if up else "down"
    arrow = "▲" if change > 0 else ("▼" if change < 0 else "▬")
    line_c = "#B65F5A" if up else "#5A7CA0"

    # y축: 0부터가 아니라 표시 구간의 최솟값~최댓값 (약간의 패딩)
    lo, hi = float(df["VIX"].min()), float(df["VIX"].max())
    pad = (hi - lo) * 0.08 or 1.0
    y_dom = [lo - pad, hi + pad]

    st.markdown(
        f'<div class="tmpr-card" style="padding-bottom:6px;">'
        f'<div class="mkt-name">VIX · 변동성 지수 (6개월)</div>'
        f'<div class="vix-head"><span class="vix-val">{cur:,.2f}</span>'
        f'<span class="vix-chg {chg_cls}">{arrow} {change:+,.2f} ({pct:+.2f}%)</span></div>',
        unsafe_allow_html=True)

    st.altair_chart(_vix_chart(df, line_c, y_dom), use_container_width=True)
    st.markdown('<div class="vix-note">VIX↑ = 변동성·공포 확대 · VIX↓ = 시장 안정 · '
                'y축은 표시 구간 최소~최대 · 차트 위 hover/스크롤로 값·확대</div></div>',
                unsafe_allow_html=True)


def _fng_card(fng):
    """좌측: 공포·탐욕 지수 카드 (게이지 인디케이터 = 동그라미)."""
    if not fng:
        st.markdown(
            '<div class="tmpr-card"><div class="mkt-name">공포·탐욕 지수 · CNN (미국 기준)</div>'
            '<div class="mkt-na">불러오지 못했어요 (CNN 비공식 API)</div></div>',
            unsafe_allow_html=True)
        return
    ko = _RATING_KO.get((fng["rating"] or "").lower(), fng["rating"])
    asof = f' · 기준 {fng["asof"]} KST' if fng.get("asof") else ""
    score = max(0, min(100, fng["score"]))
    st.markdown(
        f'<div class="tmpr-card">'
        f'<div class="mkt-name">공포·탐욕 지수 · CNN (미국 기준)</div>'
        f'<div style="display:flex;align-items:baseline;gap:8px;margin-top:2px;">'
        f'<span class="mkt-val">{fng["score"]}</span>'
        f'<span style="font-weight:700;color:var(--muted);">/ 100 · {ko}</span></div>'
        f'<div class="gauge"><span class="dot" style="left:{score}%"></span></div>'
        f'<div style="font-size:10.5px;color:var(--muted);">공포(파랑) ↔ 탐욕(빨강) · '
        f'비공식 API{asof}</div>'
        f'</div>', unsafe_allow_html=True)


@st.cache_data(ttl=600, show_spinner=False)
def phase_brief():
    """시장 국면 한 줄 요약 — '오늘의 한 장' 결론 스트립용(app.py).

    render_indicators와 같은 재료(공포·탐욕/VIX/RSI/수급)로 판정하되 위젯 없이
    {'phase': '중립', 'score': +0.25}만 돌려준다. 내부 페처가 전부 캐시라
    시장 탭 아래쪽 지표 섹션과 중복 호출 비용은 사실상 0. 판정 불가 시 None."""
    try:
        fng = fetch_cnn_fng()
        rsi_vals = {name: compute_rsi(tk) for name, tk in _RSI_TARGETS.items()}
        pp = _phase_payload(fng, rsi_vals)
        if not pp:
            return None
        return {"phase": _PHASES[pp["phase"]], "score": pp["score"]}
    except Exception:
        return None


def render_indicators():
    st.markdown(_VIX_CSS, unsafe_allow_html=True)
    st.markdown(_RSI_CSS, unsafe_allow_html=True)
    st.markdown(_PHASE_CSS, unsafe_allow_html=True)

    # 헤더 + 지표 설명 팝오버 (오른쪽 작은 버튼)
    hc1, hc2 = st.columns([4, 1])
    with hc1:
        st.markdown('<div class="mkt-group">시장 지표 (체온계)</div>', unsafe_allow_html=True)
    with hc2:
        _metric_help()

    fng = fetch_cnn_fng()
    rsi_vals = {name: compute_rsi(tk) for name, tk in _RSI_TARGETS.items()}

    # 국면 판정 위젯 — 부동산 사이클과 대칭(A안 승격). 가용 지표 0개면 조용히 생략.
    pp = _phase_payload(fng, rsi_vals)
    if pp:
        st.markdown(_phase_html(pp), unsafe_allow_html=True)

    # 공포·탐욕(좌) + VIX 6개월 차트(우) — 2단
    left, right = st.columns(2, gap="medium")
    with left:
        _fng_card(fng)
    with right:
        _vix_chart_card()

    # RSI — 위에서 계산한 rsi_vals 재사용(중복 계산 제거)
    rcards = []
    for name, tk in _RSI_TARGETS.items():
        v = rsi_vals[name]
        if v is None:
            rcards.append(f'<div class="mkt-card"><div class="mkt-name">{name} RSI</div>'
                          f'<div class="mkt-na">데이터 없음</div></div>')
            continue
        state, tone = _rsi_state(v)
        tint = {"up": "mkt-up", "down": "mkt-down", "": ""}[tone]
        pos = max(0, min(100, v))
        rcards.append(
            f'<div class="mkt-card {tint}"><div class="mkt-name">{name} RSI(14)</div>'
            f'<div style="display:flex;align-items:baseline;gap:6px;">'
            f'<span class="mkt-val">{v:.0f}</span>'
            f'<span class="mkt-chg {tone}" style="margin:0;">{state}</span></div>'
            f'<div class="rsi-gauge"><span class="t30"></span><span class="t70"></span>'
            f'<i class="{tone}" style="left:{pos}%"></i></div></div>')
    st.markdown(f'<div class="mkt-grid">{"".join(rcards)}</div>', unsafe_allow_html=True)
    # 헤더 우측엔 이미 '지표 보는 법' 팝오버가 있어 배지 중복을 피해 카드 아래 단독 행으로.
    from modules.ui import foot_row
    st.markdown(foot_row(
        "yfinance · CNN",
        f"RSI ≥70 과매수 · ≤30 과매도 (종가 14일 · 기준 {_rsi_asof()})"),
        unsafe_allow_html=True)
