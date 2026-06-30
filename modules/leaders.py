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
import json
 
import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
 
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

# ── 시간 레이어(어제 대비) 튜너블 ──
HISTORY_DAYS = 4           # 과거 스냅샷 조회 일수(순위Δ·지속일·RRG 꼬리)
RRG_K = 6.0                # 섹터 상대강도 표준화 스케일(100 중심)
RRG_M = 1.8                # 섹터 모멘텀(상대강도 변화) 스케일
RRG_TAIL = 3               # RRG 꼬리 최대 세그먼트(=점 4개)
RRG_SECTORS = 12           # RRG에 찍을 상위 섹터 수
HIGH_BREAK = 99.5          # 신고가 '돌파/경신' 판정 임계(52주 고점 대비 %)
EVENT_EX = 3               # 이벤트 칩에 미리보기로 보여줄 종목 수
DETAIL_PICK_N = 30         # '종목 자세히' 드롭다운 후보 수(점수순 상위)
SECTOR_PICK_N = 15         # '섹터 자세히' 드롭다운 후보 수(점수순 상위)

# 국면 태그(종목이 추세상 어디쯤 와 있나) — 색·한줄 설명
PHASES = {
    "초입": {"c": "#7E9A83", "d": "막 진입 · 여력 있음"},
    "돌파": {"c": "#B65F5A", "d": "신고가 경신 중"},
    "연장": {"c": "#C08A6A", "d": "많이 감 · 과열 주의"},
    "눌림": {"c": "#5A7CA0", "d": "고점서 조정 · 추세 유지"},
}
 
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
.ldr-secbar .lab{width:140px;flex:none;font-size:11.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
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

/* ── 시간 레이어(어제 대비) ── */
.ldr-evgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin:2px 0 4px;}
.ldr-ev{border:1px solid var(--line);border-radius:12px;background:var(--card);padding:11px 14px;}
.ldr-ev .h{display:flex;align-items:center;gap:6px;font-size:11.5px;color:var(--muted);font-weight:600;margin-bottom:3px;}
.ldr-ev .h .ic{font-size:13px;line-height:1;}
.ldr-ev .n{font-size:23px;font-weight:800;line-height:1.15;}
.ldr-ev .ex{font-size:10.5px;color:var(--muted);margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.ev-in{color:var(--sage-deep);} .ev-out{color:var(--down);} .ev-hi{color:var(--up);}
.ldr-lb-row .dl{width:28px;flex:none;text-align:center;font-size:10.5px;font-weight:700;}
.ldr-lb-row .stk{width:36px;flex:none;text-align:center;}
.ldr-lb-row .stk span{font-size:9px;color:var(--muted);border:1px solid var(--line);border-radius:5px;padding:1px 4px;white-space:nowrap;}
.ldr-rk-up{color:var(--up);} .ldr-rk-dn{color:var(--down);} .ldr-rk-new{color:var(--sage-deep);font-weight:800;}
.ldr-lb-row.t .nm{flex:1 1 auto;width:auto;min-width:0;} .ldr-lb-row.t .m3{flex:0 0 auto;width:56px;}
.ldr-lb-row.t .spk{width:56px;} .ldr-lb-row.t .spk svg{width:56px !important;}
.ldr-lb-row.t .d1{width:48px;}
.ldr-rrgnote{font-size:11px;color:var(--muted);line-height:1.7;margin-top:2px;}
.ldr-secbar .dl{width:50px;flex:none;text-align:right;font-size:10.5px;font-weight:700;}
.ldr-secbar .dl .up{color:var(--up);} .ldr-secbar .dl .dn{color:var(--down);} .ldr-secbar .dl .fl{color:var(--muted);}
</style>
"""
 
_HELP_MD = """
**주도주 = 시장을 이끄는 종목.** 이 탭은 *분석 대상 전체*가 아니라, 아래 **주도 게이트**를
모두 통과한 종목만 보여줍니다(과밀 해소). 화면은 위에서 아래로
**① 오늘의 변화 → ② 한눈에 보기 → ③ 종목 자세히 → ④ 섹터 로테이션 → ⑤ 섹터 자세히**
순으로, 같은 데이터를 점점 깊게 파고듭니다.

**주도 게이트(통과 조건)**
- **상대강도 RS > 0** — 코스피/코스닥 대비 초과수익. *시장보다 세게 가는가*가 주도의 본질입니다.
- **3개월 수익률 > 0** — 하락장이라도 *실제로 오른* 종목만.
- **52주 고점 80%↑** — 고점 근처에 있는가(신고가 임박).
- **60일선 위** — 추세가 살아있는가.
- **평균 거래대금 50억↑** — 돈이 충분히 몰리는가.
강도는 약/중/강 3단계로 조절되며 기본은 **중**입니다. (폭주장 대비 표시 상한 160개)

**주도 점수(0~100)** — 게이트를 통과한 종목을 줄세우는 값. 5개 축의 가중합입니다.
모멘텀 35 · 상대강도 20 · 추세지속성 20 · 유동성 15 · 신고가근접 10.

---

**① 오늘의 변화 · 이벤트** — 어제 스냅샷과 비교해 *오늘 달라진 것*만 뽑습니다.
- **신규 주도 진입** — 어제는 게이트 밖이었다가 오늘 주도로 올라온 종목.
- **주도 이탈** — 어제 주도였다가 오늘 빠진 종목.
- **52주 신고가 경신** — 어제는 신고가권이 아니었는데 오늘 99.5%↑로 올라선 종목.

**② 한눈에 보기 — 매트릭스 + 리더보드**
- **매트릭스** : 가로=추세 지속성, 세로=3개월 모멘텀, 버블 크기=거래대금, 색=대표그룹.
오른쪽 위(꾸준 + 강함)가 주도 영역, 점선은 중앙값입니다.
- **리더보드** : 점수순 TOP 12. 종목명 왼쪽 **▲▼는 어제 대비 순위 변화**(NEW=신규 진입),
**D+n은 며칠째 연속 주도**인지(스냅샷이 쌓일수록 더 길게 표시됩니다).

**③ 종목 자세히 — 5축 프로파일 · 국면**
드롭다운으로 종목을 고르면 해부 패널이 열립니다.
- **5축 레이더** : 모멘텀·상대강도·추세·유동성·신고가를 0~100으로. *모양*만 봐도 어느 축이 약한지 보입니다.
- **국면 태그** — 추세상 *어디쯤 와 있나*. '이미 많이 간'과 '막 진입'을 가릅니다.
    - **돌파** : 52주 신고가(99.5%↑) 경신 중.
    - **연장** : 고점권(96%↑)인데 1개월 급등·연속상승 → 과열 주의.
    - **눌림** : 고점서 빠졌지만(88~96%) 정배열 유지 → 조정 중.
    - **초입** : 그 외, 여력 있는 진입권.
- 같은 섹터 동료도 각자 국면 태그와 함께 표시됩니다.

**④ 섹터 로테이션 — 돈이 어디로 흐르나** (막대+Δ)
- **막대** : 길이=주도 점수, 색=1개월 모멘텀. 섹터 강도를 한눈에 비교합니다.
- **Δ** : 어제 대비 점수 변화(▲늘면 자금 유입 · ▼줄면 이탈). 빠른 스캔용.

**⑤ 섹터 자세히 — 폭 · 자금 · 선두/후발**
드롭다운으로 섹터를 고르면 내부 구조가 열립니다.
- **폭(breadth)** : 섹터 안에서 (1개월 +이고 정배열인) 종목 비율. 1~2종목만 튄 '가짜 주도'와
섹터째 오르는 '진짜 주도'를 가릅니다. 폭이 늘면 확산, 줄면 소수 쏠림.
- **자금유입** : 섹터 구성종목의 거래대금 합과 그 추이.
- **선두 vs 후발** : 국면 기준으로 *이미 간 선두*(돌파·연장)와 *따라오는 후발*(초입·눌림)을 나눕니다.
선두가 두껍고 후발이 받쳐주면 건강한 주도 섹터입니다.

---

**주도 섹터(업종) 집계** — 구성종목 4개 이상 업종만 집계합니다. 섹터 점수 = 상위 5종목 평균 × 0.5 +
폭 × 0.3 + 업종 모멘텀 × 0.2. *(섹터 통계는 게이트와 무관하게 정밀스캔 전체로 계산됩니다.)*

데이터는 Naver 기준이며 장마감 후 1일 1회 갱신됩니다. 시간 비교(순위 변화·이벤트·로테이션 꼬리)는
과거 스냅샷이 쌓일수록 풍부해집니다. 투자판단의 근거가 아니라 모니터링용 참고치예요.
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
 
 
def _rank_badge(d):
    """순위 변화 배지. d = 어제순위 − 오늘순위(양수=상승). None=신규 진입."""
    if d is None:
        return '<span class="ldr-rk-new">NEW</span>'
    if d > 0:
        return f'<span class="ldr-rk-up">▲{d}</span>'
    if d < 0:
        return f'<span class="ldr-rk-dn">▼{-d}</span>'
    return '<span style="color:var(--muted)">–</span>'


def _streak_badge(days, capped):
    """주도 지속일 배지(오늘 포함 연속 주도 일수). 윈도우 한계면 '+' 표기."""
    if not days or days < 1:
        return ''
    return f'<span>D+{days}{"+" if capped else ""}</span>'


def _leaderboard_compact(leaders, tl=None, n=LEADERBOARD_N):
    rank_delta = (tl or {}).get("rank_delta") or {}
    streak = (tl or {}).get("streak_days") or {}
    capped = bool((tl or {}).get("streak_capped"))
    has_time = bool(tl and tl.get("multi"))
    rowcls = "ldr-lb-row t" if has_time else "ldr-lb-row"
    rows = ""
    for i, s in enumerate(leaders[:n]):
        code = s.get("code")
        nm = html.escape(s.get("name", ""))
        url = html.escape(naver_stock_page_url(name=s.get("name", ""), code=s.get("code", "")))
        new = '<span class="ldr-new">N</span>' if s.get("is_new") else ""
        rank_col = "top" if i < 3 else ""
        up3 = (s.get("mom_3m") or 0) >= 0
        spc = "var(--up)" if up3 else "var(--down)"
        spark = _spark_svg(s.get("spark"), spc)
        dl = f'<div class="dl">{_rank_badge(rank_delta.get(code))}</div>' if has_time else ""
        stk = f'<div class="stk">{_streak_badge(streak.get(code), capped)}</div>' if has_time else ""
        rows += (
            f'<div class="{rowcls}">'
            f'<div class="rk {rank_col}">{i+1}</div>'
            f'{dl}'
            f'<div class="nm"><a href="{url}" target="_blank" rel="noopener">{nm}</a>{_nv_icon(s)}{new}</div>'
            f'{stk}'
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
        lead_txt = f'<b>{nlead}</b>주도' if nlead else f'{s.get("n","")}종목'
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
 
 
# ── 시간 레이어(어제 대비): 순위 변화·주도 지속일·섹터 로테이션·이벤트 ──
# 엔진을 다시 돌리지 않고, 이미 누적된 과거 스냅샷(db.load_leaders_history)만 읽어
# Δ를 만든다. 추가 API·cron 0. 스냅샷이 1일뿐이면 비교정보는 비우고 graceful 폴백.

def _day_leaders_sorted(payload):
    ld = _leaders(payload.get("stocks") or [])
    return sorted(ld, key=lambda x: (x.get("score") or 0), reverse=True)


def _rs_map(payload):
    """그날 섹터 점수를 횡단면 표준화 → {upjong: 상대강도(100 중심)}."""
    secs = payload.get("sectors") or []
    scores = [s.get("score") for s in secs if isinstance(s.get("score"), (int, float))]
    if len(scores) < 2:
        return {}
    mean = sum(scores) / len(scores)
    var = sum((x - mean) ** 2 for x in scores) / len(scores)
    std = var ** 0.5 or 1.0
    out = {}
    for s in secs:
        sc = s.get("score")
        if isinstance(sc, (int, float)):
            out[s.get("upjong")] = 100.0 + (sc - mean) / std * RRG_K
    return out


def _sector_rrg(days):
    """days=[today, prev, ...] (최신순) → 섹터별 RRG 좌표·꼬리·Δ 리스트."""
    if not days:
        return []
    chron = list(reversed(days))                  # 오래된→오늘
    rs_series = [_rs_map(p) for p in chron]
    today = days[0]
    today_rs = rs_series[-1] if rs_series else {}
    prev_score = {}
    if len(days) > 1:
        for s in (days[1].get("sectors") or []):
            prev_score[s.get("upjong")] = s.get("score")
    out = []
    for s in (today.get("sectors") or [])[:RRG_SECTORS]:
        u = s.get("upjong")
        if u not in today_rs:
            continue
        series = [rmap.get(u) for rmap in rs_series]
        pts = []
        for i in range(len(series)):
            if series[i] is None:
                pts = []                          # 끊기면 현재까지 연속만 사용
                continue
            y = (100.0 + (series[i] - series[i - 1]) * RRG_M) \
                if (i > 0 and series[i - 1] is not None) else None
            pts.append((series[i], y))
        usable = [(x, y) for (x, y) in pts if y is not None]
        if not usable:                            # 점 하나(오늘)뿐이면 모멘텀 중립
            usable = [(today_rs[u], 100.0)]
        usable = usable[-(RRG_TAIL + 1):]
        cur_x, cur_y = usable[-1]
        dlt = None
        ps, cs = prev_score.get(u), s.get("score")
        if isinstance(ps, (int, float)) and isinstance(cs, (int, float)):
            dlt = round(cs - ps, 1)
        out.append({
            "upjong": u, "group": s.get("group") or "기타",
            "x": round(cur_x, 2), "y": round(cur_y, 2),
            "tail": [(round(a, 2), round(b, 2)) for (a, b) in usable],
            "score": cs, "dlt": dlt, "mom_1m": s.get("mom_1m"),
            "breadth": s.get("breadth"),
        })
    return out


def _time_layer(history):
    """과거 스냅샷 비교 결과. history=[today, prev, ...] (최신순).
       1일뿐이면 비교정보는 비고 streak=1로 채운다(graceful)."""
    if not history:
        return None
    days = history
    rank_by_day, set_by_day, smap_by_day = [], [], []
    for p in days:
        ld = _day_leaders_sorted(p)
        rk = {s.get("code"): i + 1 for i, s in enumerate(ld) if s.get("code")}
        rank_by_day.append(rk)
        set_by_day.append(set(rk.keys()))
        smap_by_day.append({s.get("code"): s for s in (p.get("stocks") or []) if s.get("code")})

    today_rank = rank_by_day[0]
    prev_rank = rank_by_day[1] if len(rank_by_day) > 1 else {}
    rank_delta = {}
    for code, r in today_rank.items():
        pr = prev_rank.get(code)
        rank_delta[code] = (pr - r) if pr is not None else None

    streak_days = {}
    for code in today_rank:
        c = 0
        for ds in set_by_day:
            if code in ds:
                c += 1
            else:
                break
        streak_days[code] = c
    streak_capped = len(days) >= 2 and any(v >= len(days) for v in streak_days.values())

    today_set = set_by_day[0]
    prev_set = set_by_day[1] if len(set_by_day) > 1 else set()
    today_smap = smap_by_day[0]
    prev_smap = smap_by_day[1] if len(smap_by_day) > 1 else {}
    multi = len(days) > 1

    entered = [today_smap[c] for c in (today_set - prev_set) if c in today_smap] if multi else []
    exited = [prev_smap[c] for c in (prev_set - today_set) if c in prev_smap] if multi else []
    broke = []
    if multi:
        for c in today_set:
            s = today_smap.get(c)
            if not s:
                continue
            hr = s.get("high_ratio")
            if hr is None or hr < HIGH_BREAK:
                continue
            ps = prev_smap.get(c)
            phr = ps.get("high_ratio") if ps else None
            if phr is None or phr < HIGH_BREAK:
                broke.append(s)

    def _k(x):
        return x.get("score") or 0
    entered.sort(key=_k, reverse=True)
    exited.sort(key=_k, reverse=True)
    broke.sort(key=_k, reverse=True)

    return {
        "n_days": len(days), "multi": multi,
        "rank_delta": rank_delta, "streak_days": streak_days, "streak_capped": streak_capped,
        "entered": entered, "exited": exited, "broke_high": broke,
        "sector_rrg": _sector_rrg(days),
    }


def _events_html(tl):
    """오늘의 변화 칩(신규 주도 진입·이탈·52주 신고가 경신)."""
    if not tl or not tl.get("multi"):
        return None
    ent, ext, brk = tl.get("entered") or [], tl.get("exited") or [], tl.get("broke_high") or []

    def ex_names(lst):
        names = [html.escape(x.get("name", "")) for x in lst[:EVENT_EX] if x.get("name")]
        if not names:
            return "—"
        extra = len(lst) - len(names)
        return " · ".join(names) + (f" 외 {extra}" if extra > 0 else "")

    cells = [
        ("신규 주도 진입", "ev-in", "▲", len(ent), ex_names(ent)),
        ("주도 이탈", "ev-out", "▼", len(ext), ex_names(ext)),
        ("52주 신고가 경신", "ev-hi", "●", len(brk), ex_names(brk)),
    ]
    chips = ""
    for title, cls, ic, num, ex in cells:
        chips += (
            '<div class="ldr-ev">'
            f'<div class="h"><span class="ic {cls}">{ic}</span>{title}</div>'
            f'<div class="n {cls}">{num}</div>'
            f'<div class="ex">{ex}</div>'
            '</div>'
        )
    return f'<div class="ldr-evgrid">{chips}</div>'


def _sector_bars_delta_html(sectors, leaders, tl):
    """막대 + Δ: 기존 섹터 강도 막대 우측에 어제 대비 점수 Δ를 덧붙인다."""
    if not sectors:
        return '<div class="ldr-secwrap"><span class="ldr-sub">주도 섹터를 집계할 데이터가 부족해요.</span></div>'
    dlt_by = {}
    for r in ((tl or {}).get("sector_rrg") or []):
        dlt_by[r.get("upjong")] = r.get("dlt")
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
        lead_txt = f'<b>{nlead}</b>주도' if nlead else f'{s.get("n","")}종목'
        d = dlt_by.get(upj)
        if d is None:
            dl = '<div class="dl"><span class="fl">–</span></div>'
        elif d > 0:
            dl = f'<div class="dl"><span class="up">▲{d:g}</span></div>'
        elif d < 0:
            dl = f'<div class="dl"><span class="dn">▼{abs(d):g}</span></div>'
        else:
            dl = '<div class="dl"><span class="fl">0</span></div>'
        bars += (
            '<div class="ldr-secbar">'
            f'<div class="lab" title="{html.escape(upj)}">{html.escape(upj)}</div>'
            f'<div class="track"><i style="width:{sc/maxsc*100:.0f}%;background:{col}"></i></div>'
            f'<div class="val"><b>{sc}</b> · 1M {_pc(s.get("mom_1m"))} · {lead_txt}</div>'
            f'{dl}'
            '</div>'
        )
    return f'<div class="ldr-secwrap"><div class="ldr-secgrid">{bars}</div></div>'


def _rrg_components(rrg, n_days):
    """섹터 로테이션 사분면(RRG)을 iframe SVG로 렌더(미니멀 미스트)."""
    if not rrg:
        st.caption("로테이션을 그릴 섹터 데이터가 부족해요.")
        return
    xs = [p["x"] for p in rrg] + [t[0] for p in rrg for t in p["tail"]]
    ys = [p["y"] for p in rrg] + [t[1] for p in rrg for t in p["tail"]]
    xmin, xmax = min(xs + [97.0]), max(xs + [103.0])
    ymin, ymax = min(ys + [96.0]), max(ys + [104.0])
    xpad = (xmax - xmin) * 0.14 + 0.5
    ypad = (ymax - ymin) * 0.14 + 0.5
    xmin -= xpad; xmax += xpad; ymin -= ypad; ymax += ypad
    if (ymax - ymin) < 14:                 # 모멘텀 변화가 작으면 최소 표시폭 보장(점 몰림 완화)
        ymid = (ymax + ymin) / 2
        ymin, ymax = ymid - 7, ymid + 7
    W, H, L, R, T, B = 720, 384, 60, 624, 26, 326

    def px(x):
        return L + (x - xmin) / (xmax - xmin) * (R - L)

    def py(y):
        return B - (y - ymin) / (ymax - ymin) * (B - T)

    cx, cy = px(100.0), py(100.0)
    s = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg">']
    s.append(f'<rect x="{cx:.0f}" y="{T}" width="{R-cx:.0f}" height="{cy-T:.0f}" fill="#B65F5A" opacity="0.05"/>')
    s.append(f'<rect x="{cx:.0f}" y="{cy:.0f}" width="{R-cx:.0f}" height="{B-cy:.0f}" fill="#C08A6A" opacity="0.05"/>')
    s.append(f'<rect x="{L}" y="{cy:.0f}" width="{cx-L:.0f}" height="{B-cy:.0f}" fill="#5A7CA0" opacity="0.05"/>')
    s.append(f'<rect x="{L}" y="{T}" width="{cx-L:.0f}" height="{cy-T:.0f}" fill="#7E9A83" opacity="0.06"/>')
    s.append(f'<line x1="{cx:.0f}" y1="{T}" x2="{cx:.0f}" y2="{B}" stroke="#9a9b92" stroke-dasharray="4 4" opacity="0.55"/>')
    s.append(f'<line x1="{L}" y1="{cy:.0f}" x2="{R}" y2="{cy:.0f}" stroke="#9a9b92" stroke-dasharray="4 4" opacity="0.55"/>')
    s.append(f'<text x="{R-6}" y="{T+14}" text-anchor="end" font-size="11" fill="#B65F5A">선도</text>')
    s.append(f'<text x="{R-6}" y="{B-7}" text-anchor="end" font-size="11" fill="#9A6E3A" opacity="0.85">약화</text>')
    s.append(f'<text x="{L+6}" y="{B-7}" font-size="11" fill="#5A7CA0">후퇴</text>')
    s.append(f'<text x="{L+6}" y="{T+14}" font-size="11" fill="#5E7A63">개선</text>')
    s.append(f'<text x="{cx:.0f}" y="{B+17}" text-anchor="middle" font-size="10.5" fill="#9a9b92">상대강도 →</text>')
    mid = (T + B) / 2
    s.append(f'<text x="15" y="{mid:.0f}" font-size="10.5" fill="#9a9b92" transform="rotate(-90 15 {mid:.0f})">모멘텀 →</text>')
    for d in rrg:
        col = GROUP_COLORS.get(d["group"], GROUP_COLORS["기타"])
        tail = d["tail"]
        if len(tail) >= 2:
            path = "M " + " L ".join(f"{px(a):.1f} {py(b):.1f}" for a, b in tail)
            s.append(f'<path d="{path}" fill="none" stroke="{col}" stroke-width="1.6" opacity="0.45"/>')
            for a, b in tail[:-1]:
                s.append(f'<circle cx="{px(a):.1f}" cy="{py(b):.1f}" r="2" fill="{col}" opacity="0.32"/>')
        x2, y2 = px(d["x"]), py(d["y"])
        s.append(f'<circle cx="{x2:.1f}" cy="{y2:.1f}" r="6.5" fill="{col}" opacity="0.9"/>')
        nm = html.escape(d["upjong"])
        if x2 > cx:        # 오른쪽 점 → 라벨을 점 왼쪽에(viewBox 밖 잘림 방지)
            s.append(f'<text x="{x2-9:.1f}" y="{y2+4:.1f}" text-anchor="end" font-size="11" fill="#34352f">{nm}</text>')
        else:
            s.append(f'<text x="{x2+9:.1f}" y="{y2+4:.1f}" font-size="11" fill="#34352f">{nm}</text>')
    s.append('</svg>')
    doc = ('<div style="font-family:Pretendard,-apple-system,BlinkMacSystemFont,sans-serif;'
           'background:transparent;margin:0;">' + "".join(s) + '</div>')
    components.html(doc, height=H + 8, scrolling=False)


def _phase(s):
    """종목 국면 태그 판정 → (라벨, 색). 저장된 high_ratio·mom_*·streak·aligned로 산출.
       위에서부터 먼저 걸리는 것: 돌파 > 연장 > 눌림 > 초입(기본)."""
    hr = s.get("high_ratio")
    m1 = s.get("mom_1m") or 0
    m1w = s.get("mom_1w")
    stk = s.get("streak") or 0
    aligned = bool(s.get("aligned"))
    if hr is not None:
        if hr >= 99.5:
            lab = "돌파"
        elif hr >= 96 and (m1 >= 25 or stk >= 5):
            lab = "연장"
        elif 88 <= hr < 96 and aligned and (m1w is not None and m1w <= 0):
            lab = "눌림"
        else:
            lab = "초입"
    else:
        lab = "초입"
    return lab, PHASES[lab]["c"]


def _radar_svg(comp):
    """5축 점수 프로파일(모멘텀·상대강도·추세·유동성·신고가) → 레이더 SVG."""
    import math
    order = ["mom", "rs", "trend", "liq", "high"]
    axlab = ["모멘텀", "상대강도", "추세", "유동성", "신고가"]
    vals = [max(0.0, min(100.0, (comp or {}).get(k) or 0)) for k in order]
    W = Hh = 260
    cx, cy, Rm, n = 130, 132, 92, 5

    def pt(i, r):
        a = -math.pi / 2 + i * 2 * math.pi / n
        return cx + math.cos(a) * r, cy + math.sin(a) * r

    s = [f'<svg viewBox="0 0 {W} {Hh}" width="100%" xmlns="http://www.w3.org/2000/svg" '
         'style="max-width:280px;display:block;margin:0 auto;">']
    for g in (20, 40, 60, 80, 100):
        p = " ".join(f"{pt(i, Rm*g/100)[0]:.1f},{pt(i, Rm*g/100)[1]:.1f}" for i in range(n))
        s.append(f'<polygon points="{p}" fill="none" stroke="#E4E2DB" stroke-width="1"/>')
    for i in range(n):
        x, y = pt(i, Rm)
        s.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="#E4E2DB" stroke-width="1"/>')
    dp = " ".join(f"{pt(i, Rm*vals[i]/100)[0]:.1f},{pt(i, Rm*vals[i]/100)[1]:.1f}" for i in range(n))
    s.append(f'<polygon points="{dp}" fill="#7E9A83" fill-opacity="0.18" stroke="#7E9A83" stroke-width="1.8"/>')
    for i in range(n):
        x, y = pt(i, Rm * vals[i] / 100)
        s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="#7E9A83"/>')
    for i in range(n):
        x, y = pt(i, Rm + 15)
        s.append(f'<text x="{x:.1f}" y="{y+3:.1f}" text-anchor="middle" font-size="10.5" fill="#9a9b92">{axlab[i]}</text>')
    s.append('</svg>')
    return "".join(s)


def _detail_metrics_html(s):
    def mv(label, val, move=False, pct=False):
        if val is None:
            v = '<span style="color:#b6b4ab">–</span>'
        elif move:
            c = "#B65F5A" if val >= 0 else "#5A7CA0"
            v = f'<span style="color:{c}">{"+" if val >= 0 else ""}{val:g}%</span>'
        elif pct:
            v = f'{val:g}%'
        else:
            v = f'{val}'
        return ('<div style="display:flex;justify-content:space-between;padding:6.5px 0;'
                'border-bottom:1px solid #ECEDE7;">'
                f'<span style="font-size:11.5px;color:#9a9b92;">{label}</span>'
                f'<span style="font-size:12.5px;font-weight:700;">{v}</span></div>')
    cap = s.get("mcap_eok")
    cap_txt = f"{cap/10000:.1f}조" if cap and cap >= 10000 else (f"{cap:,.0f}억" if cap else "–")
    turn = s.get("turnover_eok")
    turn_txt = f"{turn/10000:.2f}조" if turn and turn >= 10000 else (f"{turn:,.0f}억" if turn else "–")
    return (
        '<div>'
        + mv("3개월", s.get("mom_3m"), move=True)
        + mv("1개월", s.get("mom_1m"), move=True)
        + mv("1주", s.get("mom_1w"), move=True)
        + mv("전일", s.get("mom_1d"), move=True)
        + mv("상대강도 RS", s.get("rs_3m"), move=True)
        + mv("52주 고점 대비", s.get("high_ratio"), pct=True)
        + ('<div style="display:flex;justify-content:space-between;padding:6.5px 0;border-bottom:1px solid #ECEDE7;">'
           f'<span style="font-size:11.5px;color:#9a9b92;">거래대금</span>'
           f'<span style="font-size:12.5px;font-weight:700;">{turn_txt}</span></div>')
        + ('<div style="display:flex;justify-content:space-between;padding:6.5px 0;">'
           f'<span style="font-size:11.5px;color:#9a9b92;">시가총액</span>'
           f'<span style="font-size:12.5px;font-weight:700;">{cap_txt}</span></div>')
        + '</div>'
    )


def _detail_price_chart_html(labels, ys, line_color, height=210):
    """종목 디테일용 가격 차트 — 지수 탭(코스피/코스닥)과 동일 양식.
       면적 그라데이션 + Y축 그리드/라벨 + crosshair hover + 좌→우 등장 애니메이션."""
    hx = line_color.lstrip("#")
    r, g, b = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
    tpl = r'''<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css">
<style>
html,body{margin:0;background:transparent;}
#host{width:100%;height:__H__px;}
svg{display:block;width:100%;height:__H__px;overflow:visible;}
text{font-family:Pretendard,'Noto Sans KR',sans-serif;}
.ic-line{fill:none;stroke:__COLOR__;stroke-width:2;stroke-linejoin:round;stroke-linecap:round;}
</style></head><body><div id="host"></div>
<script>
var YS=__YS__, LB=__LB__, PREV=__PREV__, H=__H__, COLOR="__COLOR__", RGB="__RGB__", first=true;
var REDUCE = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
function draw(){
  var host=document.getElementById('host');
  var W=Math.max(280, host.clientWidth||700);
  var ml=50,mr=14,mt=12,mb=24, pw=W-ml-mr, ph=H-mt-mb;
  var lo=Math.min.apply(null,YS), hi=Math.max.apply(null,YS);
  if(PREV!=null){lo=Math.min(lo,PREV);hi=Math.max(hi,PREV);}
  var pad=(hi-lo)*0.10||hi*0.005||1; lo-=pad; hi+=pad; var sp=(hi-lo)||1, n=YS.length;
  function X(i){return ml+(n>1?i/(n-1):0)*pw;}
  function Y(v){return mt+(1-(v-lo)/sp)*ph;}
  var line='M'+YS.map(function(v,i){return X(i).toFixed(1)+','+Y(v).toFixed(1);}).join(' L');
  var area=line+' L'+X(n-1).toFixed(1)+','+(mt+ph).toFixed(1)+' L'+X(0).toFixed(1)+','+(mt+ph).toFixed(1)+' Z';
  var yg='';
  for(var k=0;k<5;k++){var v=lo+sp*k/4, y=Y(v).toFixed(1);
    yg+='<line x1='+ml+' y1='+y+' x2='+(ml+pw)+' y2='+y+' stroke="#ECEDE7"/>';
    yg+='<text x='+(ml-8)+' y='+(parseFloat(y)+3.5).toFixed(1)+' text-anchor="end" font-size="11" fill="#9a9b92">'+Math.round(v).toLocaleString()+'</text>';}
  var xg='', step=Math.max(1,Math.floor(n/6));
  for(var i=0;i<n;i+=step){if(LB[i])xg+='<text x='+X(i).toFixed(1)+' y='+(H-7)+' text-anchor="middle" font-size="11" fill="#9a9b92">'+LB[i]+'</text>';}
  var pv='';
  if(PREV!=null){var py=Y(PREV).toFixed(1);
    pv='<line x1='+ml+' y1='+py+' x2='+(ml+pw)+' y2='+py+' stroke="#9a9b92" stroke-dasharray="4 4" opacity="0.6"/>';}
  var doAnim = first && !REDUCE;
  var aw = doAnim ? '<animate attributeName="width" from="0" to="'+pw+'" dur="0.85s" calcMode="spline" keyTimes="0;1" keySplines="0.22 0.61 0.36 1" fill="freeze"/>' : '';
  var rw = doAnim ? 0 : pw;
  var svg='<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">'
    +'<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="rgba('+RGB+',0.20)"/><stop offset="1" stop-color="rgba('+RGB+',0)"/></linearGradient>'
    +'<clipPath id="rv"><rect x="'+ml+'" y="0" width="'+rw+'" height="'+H+'">'+aw+'</rect></clipPath></defs>'
    +yg+pv
    +'<g clip-path="url(#rv)"><path d="'+area+'" fill="url(#g)"/><path d="'+line+'" class="ic-line"/></g>'
    +xg
    +'<g id="cr" style="display:none"><line id="vl" y1="'+mt+'" y2="'+(mt+ph)+'" stroke="#9a9b92" stroke-dasharray="3 3"/><circle id="dt" r="4" fill="'+COLOR+'"/><g id="tp"><rect id="tb" rx="4" height="18" fill="#34352f"/><text id="tt" font-size="11" font-weight="700" fill="#fff" text-anchor="middle"></text></g></g>'
    +'<rect id="ht" x="'+ml+'" y="'+mt+'" width="'+pw+'" height="'+ph+'" fill="transparent" style="cursor:crosshair"/>'
    +'</svg>';
  host.innerHTML=svg; first=false;
  var root=host.querySelector('svg'),cr=root.querySelector('#cr'),vl=root.querySelector('#vl'),dt=root.querySelector('#dt'),tb=root.querySelector('#tb'),tt=root.querySelector('#tt'),ht=root.querySelector('#ht');
  var P=YS.map(function(v,i){return [X(i),Y(v),v,LB[i]];});
  ht.addEventListener('mousemove',function(e){
    var r=root.getBoundingClientRect(), mx=(e.clientX-r.left)/r.width*W, bi=0, bd=1e9;
    for(var i=0;i<P.length;i++){var dd=Math.abs(P[i][0]-mx);if(dd<bd){bd=dd;bi=i;}}
    var p=P[bi]; cr.style.display='';
    vl.setAttribute('x1',p[0]);vl.setAttribute('x2',p[0]);dt.setAttribute('cx',p[0]);dt.setAttribute('cy',p[1]);
    var txt=(p[3]?p[3]+'  ':'')+p[2].toLocaleString('en-US',{minimumFractionDigits:0,maximumFractionDigits:0});
    tt.textContent=txt; var tw=txt.length*6.7+14, tx=Math.max(ml+tw/2,Math.min(ml+pw-tw/2,p[0])), ty=Math.max(mt+13,p[1]-12);
    tb.setAttribute('width',tw);tb.setAttribute('x',tx-tw/2);tb.setAttribute('y',ty-13);tt.setAttribute('x',tx);tt.setAttribute('y',ty);
  });
  ht.addEventListener('mouseleave',function(){cr.style.display='none';});
}
draw(); var rt; window.addEventListener('resize',function(){clearTimeout(rt);rt=setTimeout(draw,150);});
</script></body></html>'''
    return (tpl
            .replace("__YS__", json.dumps([round(float(v), 2) for v in ys]))
            .replace("__LB__", json.dumps(list(labels), ensure_ascii=False))
            .replace("__PREV__", "null")
            .replace("__H__", str(int(height)))
            .replace("__COLOR__", line_color)
            .replace("__RGB__", "%d,%d,%d" % (r, g, b)))


def _detail_peers_html(sel, leaders):
    upj = sel.get("upjong")
    peers = [s for s in leaders
             if s.get("upjong") == upj and s.get("code") != sel.get("code")]
    peers = sorted(peers, key=lambda x: (x.get("score") or 0), reverse=True)[:4]
    if not peers:
        return '<div style="font-size:11px;color:#9a9b92;">같은 섹터에 다른 주도주가 없어요.</div>'
    rows = ""
    for p in peers:
        lab, col = _phase(p)
        url = html.escape(naver_stock_page_url(name=p.get("name", ""), code=p.get("code", "")))
        rows += ('<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid #ECEDE7;">'
                 f'<a href="{url}" target="_blank" rel="noopener" '
                 f'style="flex:1;font-size:12.5px;color:#34352f;text-decoration:none;">{html.escape(p.get("name",""))}</a>'
                 f'<span style="font-size:11px;color:#9a9b92;">{p.get("score","")}점</span>'
                 f'<span style="font-size:10px;font-weight:700;color:{col};background:{col}1f;'
                 f'border-radius:5px;padding:1px 7px;">{lab}</span></div>')
    return rows


def _spark_labels(dates, n):
    """spark_dates('YYYYMMDD' 문자열) → 차트 X축 'MM/DD' 라벨.
       날짜가 없거나(과거 스냅샷) 길이가 안 맞으면 빈 라벨(축 생략)."""
    dates = dates or []
    if len(dates) != n:
        return [""] * n
    out = []
    for d in dates:
        digits = "".join(ch for ch in str(d) if ch.isdigit())
        out.append(f"{digits[4:6]}/{digits[6:8]}" if len(digits) >= 8 else "")
    return out


def _render_detail(s, leaders):
    """선택 종목 디테일 — 레이더·국면·지표·동료는 iframe 카드, 가격 차트는 지수 양식으로."""
    lab, col = _phase(s)
    desc = PHASES[lab]["d"]
    url = html.escape(naver_stock_page_url(name=s.get("name", ""), code=s.get("code", "")))
    nm = html.escape(s.get("name", ""))
    radar = _radar_svg(s.get("comp") or {})
    mets = _detail_metrics_html(s)
    peers = _detail_peers_html(s, leaders)
    doc = (
        '<div style="font-family:Pretendard,-apple-system,BlinkMacSystemFont,sans-serif;'
        'color:#34352f;background:transparent;margin:0;">'
        '<div style="border:1px solid #ECEDE7;border-radius:13px;background:#FFFFFF;padding:15px 18px;">'
        '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:3px;">'
        f'<a href="{url}" target="_blank" rel="noopener" '
        f'style="font-size:17px;font-weight:700;color:#34352f;text-decoration:none;">{nm}</a>'
        f'<span style="font-size:11px;font-weight:700;color:{col};background:{col}22;'
        f'border-radius:6px;padding:2px 9px;">{lab}</span>'
        f'<span style="font-size:11.5px;color:#9a9b92;">{html.escape(s.get("upjong","") or "")} · 주도 {s.get("score","")}점</span>'
        '</div>'
        f'<div style="font-size:11.5px;color:{col};margin-bottom:12px;">{desc}</div>'
        '<div style="display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.1fr);gap:18px;align-items:center;">'
        f'<div>{radar}<div style="font-size:10px;color:#9a9b92;text-align:center;margin-top:2px;">'
        '5축 점수 프로파일 · 0~100</div></div>'
        f'<div>{mets}</div>'
        '</div>'
        '<div style="margin-top:14px;"><div style="font-size:11px;color:#9a9b92;margin-bottom:4px;">'
        f'같은 섹터 동료</div>{peers}</div>'
        '</div></div>'
    )
    components.html(doc, height=500, scrolling=False)

    # ── 최근 3개월 추이 (지수 탭과 동일 양식) ──
    spk = [v for v in (s.get("spark") or []) if isinstance(v, (int, float))]
    st.markdown('<div class="ldr-sub" style="margin:10px 0 2px">최근 3개월 추이</div>',
                unsafe_allow_html=True)
    if len(spk) >= 2:
        period_up = spk[-1] >= spk[0]
        line_c = "#B65F5A" if period_up else "#5A7CA0"
        labels = _spark_labels(s.get("spark_dates"), len(spk))
        components.html(_detail_price_chart_html(labels, spk, line_c, height=210),
                        height=222, scrolling=False)
    else:
        st.caption("시계열 데이터가 부족해요.")


# ── 섹터 해부: 폭(breadth)·자금유입·선두/후발 ────────────────────────

def _split_lead_follow(members):
    """국면 기반 분류 — 돌파·연장=이미 간 선두 / 초입·눌림=따라오는 후발."""
    lead, follow = [], []
    for s in members:
        ph, _ = _phase(s)
        (lead if ph in ("돌파", "연장") else follow).append(s)
    return lead, follow


def _sector_flow_eok(payload, upj):
    """그날 그 업종 종목들의 거래대금(억) 합 = 자금유입 프록시."""
    tot = 0.0
    for s in (payload.get("stocks") or []):
        if s.get("upjong") == upj:
            t = s.get("turnover_eok")
            if isinstance(t, (int, float)):
                tot += t
    return tot


def _sector_series(history, upj):
    """history(최신순) → 그 업종의 (breadth, flow, score) 시계열을 오래된→오늘 순으로."""
    chron = list(reversed(history or []))
    b, f, sc = [], [], []
    for p in chron:
        sec = next((x for x in (p.get("sectors") or []) if x.get("upjong") == upj), None)
        b.append(sec.get("breadth") if sec else None)
        sc.append(sec.get("score") if sec else None)
        f.append(_sector_flow_eok(p, upj))
    return {"breadth": b, "flow": f, "score": sc}


def _mini_line_svg(vals, up, w=120, h=30):
    vals = [v for v in vals if isinstance(v, (int, float))]
    if len(vals) < 2:
        return '<span style="font-size:10.5px;color:#9a9b92;">추이 부족</span>'
    lo, hi = min(vals), max(vals)
    rg = (hi - lo) or 1
    n = len(vals)
    pts = " ".join(f"{i/(n-1)*w:.1f},{h-3-((v-lo)/rg)*(h-6):.1f}" for i, v in enumerate(vals))
    c = "#B65F5A" if up else "#5A7CA0"
    return (f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" style="width:{w}px;height:{h}px;display:block;">'
            f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="1.8" opacity="0.85"/></svg>')


def _sec_member_html(s):
    ph, c = _phase(s)
    url = html.escape(naver_stock_page_url(name=s.get("name", ""), code=s.get("code", "")))
    m1 = s.get("mom_1m")
    m1txt = (f'{"+" if (m1 or 0) >= 0 else ""}{m1:g}%') if m1 is not None else "–"
    m1col = "#B65F5A" if (m1 or 0) >= 0 else "#5A7CA0"
    return ('<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid #ECEDE7;">'
            f'<a href="{url}" target="_blank" rel="noopener" '
            f'style="flex:1;font-size:12.5px;color:#34352f;text-decoration:none;">{html.escape(s.get("name",""))}</a>'
            f'<span style="font-size:10.5px;color:{m1col};">{m1txt}</span>'
            f'<span style="font-size:11px;color:#9a9b92;">{s.get("score","")}</span>'
            f'<span style="font-size:10px;font-weight:700;color:{c};background:{c}1f;'
            f'border-radius:5px;padding:1px 7px;">{ph}</span></div>')


def _dlt_span(v, suf=""):
    if v is None:
        return ""
    c = "#B65F5A" if v >= 0 else "#5A7CA0"
    a = "▲" if v >= 0 else "▼"
    return f' <span style="color:{c};font-weight:700;">{a}{abs(v):g}{suf}</span>'


def _fmt_eok(v):
    if v is None:
        return "–"
    return f"{v/10000:.1f}조" if v >= 10000 else f"{v:,.0f}억"


def _render_sector_panel(sec, leaders, history):
    """선택 섹터 디테일 — 폭·자금유입·추이·선두/후발을 iframe 한 장으로."""
    upj = sec.get("upjong")
    grp = sec.get("group") or "기타"
    gcol = GROUP_COLORS.get(grp, GROUP_COLORS["기타"])
    members = sorted([s for s in leaders if s.get("upjong") == upj],
                     key=lambda x: (x.get("score") or 0), reverse=True)
    lead, follow = _split_lead_follow(members)

    ser = _sector_series(history, upj) if history else {"breadth": [], "flow": [], "score": []}
    bser = [x for x in ser["breadth"] if isinstance(x, (int, float))]
    fser = [x for x in ser["flow"] if isinstance(x, (int, float))]
    sser = [x for x in ser["score"] if isinstance(x, (int, float))]
    b_dlt = round(bser[-1] - bser[-2]) if len(bser) >= 2 else None
    f_dlt = round((fser[-1] - fser[-2]) / fser[-2] * 100) if len(fser) >= 2 and fser[-2] else None
    s_dlt = round(sser[-1] - sser[-2], 1) if len(sser) >= 2 else None
    flow_today = fser[-1] if fser else (_sector_flow_eok(history[0], upj) if history else None)
    breadth = sec.get("breadth")

    def stat(label, val, sub):
        sub_html = f'<div style="font-size:10.5px;margin-top:1px;">{sub}</div>' if sub else ''
        return ('<div style="background:#FCFCFA;border-radius:8px;padding:9px 11px;">'
                f'<div style="font-size:10.5px;color:#9a9b92;margin-bottom:2px;">{label}</div>'
                f'<div style="font-size:17px;font-weight:700;color:#34352f;line-height:1.2;">{val}</div>'
                f'{sub_html}</div>')

    head = (
        '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px;">'
        f'<span style="width:10px;height:10px;border-radius:3px;background:{gcol};"></span>'
        f'<span style="font-size:17px;font-weight:700;color:#34352f;">{html.escape(upj or "")}</span>'
        f'<span style="font-size:12px;color:#9a9b92;">주도 {sec.get("score","")}점{_dlt_span(s_dlt)} · '
        f'3M {("+" if (sec.get("mom_3m") or 0) >= 0 else "")}{sec.get("mom_3m","")}%</span>'
        '</div>'
    )
    stats = (
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin-bottom:14px;">'
        + stat("폭 (breadth)", f"{breadth}%" if breadth is not None else "–",
               (f"어제 대비{_dlt_span(b_dlt, '%p')}") if b_dlt is not None else "")
        + stat("자금유입", _fmt_eok(flow_today),
               (f"거래대금{_dlt_span(f_dlt, '%')}") if f_dlt is not None else "")
        + stat("주도주", f"{len(members)}개", f"선두 {len(lead)} · 후발 {len(follow)}")
        + '</div>'
    )
    b_up = (bser[-1] >= bser[0]) if len(bser) >= 2 else True
    f_up = (f_dlt or 0) >= 0
    trends = (
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:16px;">'
        f'<div><div style="font-size:10.5px;color:#9a9b92;margin-bottom:3px;">폭 추이</div>'
        f'{_mini_line_svg(bser, b_up)}</div>'
        f'<div><div style="font-size:10.5px;color:#9a9b92;margin-bottom:3px;">자금 추이</div>'
        f'{_mini_line_svg(fser, f_up)}</div>'
        '</div>'
    )

    def col(title, arr, empty):
        rows = "".join(_sec_member_html(s) for s in arr[:6]) if arr \
            else f'<div style="font-size:11px;color:#9a9b92;padding:8px 0;">{empty}</div>'
        return ('<div><div style="font-size:11px;font-weight:700;color:#5f5e5a;margin-bottom:4px;">'
                f'{title}</div>{rows}</div>')

    cols = (
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;">'
        + col("선두 · 이미 간 (돌파·연장)", lead, "아직 선두 종목이 없어요(섹터 초기)")
        + col("후발 · 따라오는 (초입·눌림)", follow, "후발 주도주 없음")
        + '</div>'
    )
    doc = (
        '<div style="font-family:Pretendard,-apple-system,BlinkMacSystemFont,sans-serif;'
        'color:#34352f;background:transparent;margin:0;">'
        '<div style="border:1px solid #ECEDE7;border-radius:13px;background:#FFFFFF;padding:15px 18px;">'
        + head + stats + trends + cols +
        '</div></div>'
    )
    # iframe 높이를 실제 내용(선두/후발 행 수)에 맞춰 동적 계산 → 하단 빈 공간 제거
    n_rows = max(min(len(lead), 6), min(len(follow), 6), 1)
    panel_h = 256 + n_rows * 28
    components.html(doc, height=panel_h, scrolling=False)


# ── 메인 ─────────────────────────────────────────────────────────────
 
def render_leaders():
    tab_header("주도주", css=_CSS)
 
    with st.expander("ⓘ 주도주 보는 법", expanded=False):
        st.markdown('<div class="ldr-help">', unsafe_allow_html=True)
        st.markdown(_HELP_MD)
        st.markdown('</div>', unsafe_allow_html=True)
 
    history = []
    payload = None
    try:
        from modules import db
        if db.supabase_configured():
            if hasattr(db, "load_leaders_history"):
                history = db.load_leaders_history(HISTORY_DAYS) or []
            payload = history[0] if history else db.load_leaders()
    except Exception:
        history, payload = [], None
 
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
 
    tl = _time_layer(history) if history else None

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

    # ── 오늘의 변화: 이벤트 피드(시간 레이어) ──
    ev_html = _events_html(tl)
    if ev_html:
        st.markdown('<div class="ldr-h">오늘의 변화 · 이벤트</div>', unsafe_allow_html=True)
        st.markdown(ev_html, unsafe_allow_html=True)
 
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
        st.markdown(_leaderboard_compact(leaders, tl), unsafe_allow_html=True)
 
    # ── 종목 해부: 5축 프로파일·국면(드롭다운 선택) ──
    pick_pool = leaders[:DETAIL_PICK_N]
    if pick_pool:
        st.markdown('<div class="ldr-h">종목 자세히 · 5축 프로파일 · 국면</div>',
                    unsafe_allow_html=True)

        def _detail_label(i):
            d = pick_pool[i]
            lab, _ = _phase(d)
            return f'{i+1}. {d.get("name","")} · {d.get("score","")}점 · {lab}'

        idx = st.selectbox("종목 선택", range(len(pick_pool)),
                           format_func=_detail_label,
                           label_visibility="collapsed", key="ldr_detail_pick")
        _render_detail(pick_pool[idx], leaders)

    # ── 주도 섹터 로테이션(시간 레이어) — 막대(+Δ)만, 사분면(RRG) 제거 ──
    rrg = (tl or {}).get("sector_rrg") or []
    if rrg and (tl or {}).get("multi"):
        st.markdown('<div class="ldr-h">주도 섹터 로테이션 · 돈이 어디로 흐르나</div>',
                    unsafe_allow_html=True)
        st.markdown('<div class="ldr-sub" style="margin-bottom:6px">색=1개월 모멘텀 · '
                    '길이=주도 점수 · 우측 Δ=어제 대비 점수 변화</div>', unsafe_allow_html=True)
        st.markdown(_sector_bars_delta_html(sectors, leaders, tl), unsafe_allow_html=True)
    else:
        # 시간 레이어 없음(스냅샷 1일뿐/구버전 db) → 기존 섹터 강도 막대
        st.markdown('<div class="ldr-h">주도 섹터 강도 · 색=1개월 모멘텀 · 길이=주도 점수</div>',
                    unsafe_allow_html=True)
        st.markdown(_sector_bars_html(sectors, leaders), unsafe_allow_html=True)
 
    # ── 섹터 해부: 폭·자금·선두/후발(드롭다운 선택) ──
    if sectors:
        st.markdown('<div class="ldr-h">섹터 자세히 · 폭 · 자금 · 선두/후발</div>',
                    unsafe_allow_html=True)
        sec_pool = sectors[:SECTOR_PICK_N]

        def _sec_label(i):
            x = sec_pool[i]
            return f'{i+1}. {x.get("upjong","")} · {x.get("score","")}점'

        sidx = st.selectbox("섹터 선택", range(len(sec_pool)),
                            format_func=_sec_label,
                            label_visibility="collapsed", key="ldr_sector_pick")
        _render_sector_panel(sec_pool[sidx], leaders, history)

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
        + " · 국면: 돌파(52주 신고가 99.5%↑)·연장(고점권+과열)·눌림(고점서 조정·정배열)·초입(여력)"
        + " · 우선주·스팩·리츠·ETF 제외 · 상대강도=코스피/코스닥 대비 초과수익 · "
        "데이터: Naver · 장마감 후 1일 1회 갱신 · 투자판단의 근거가 아니라 모니터링용 참고치예요."
    )
