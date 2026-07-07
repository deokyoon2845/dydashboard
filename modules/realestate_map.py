"""부동산 '지도' 탭 — 수도권 choropleth + 워치리스트 밴드 + 상승 스트릭.

지도 경계는 realestate_geo의 _GEO/_LOCAL_GEO를 쓰고, 호버 인터랙션(JS) 때문에
components.html(iframe)로 렌더한다. iframe은 부모 CSS 변수를 못 읽으므로 색은
hex 인라인, Pretendard 웹폰트는 iframe 안에 직접 임베드(실패 시 시스템 폰트 폴백).
"""

import copy
import streamlit as st
import streamlit.components.v1 as components

from modules.realestate_geo import _GEO, _LOCAL_GEO, _LOCAL_SAMPLE
from modules.realestate_common import _resolved_metrics, fetch_region_metrics


def _merged_regions():
    metrics = None
    try:
        metrics = fetch_region_metrics()
    except Exception:
        metrics = None
    if not metrics:
        return _GEO
    out = []
    for d in _GEO:
        m = metrics.get(d["n"]) or {}
        out.append({**d, **{k: m[k] for k in ("mm", "js", "v", "vc", "jr", "vavg") if k in m}})
    return out


# ── 권역 레벨(강남3구·서울·경기·수도권) — 지수 레벨 + 주간Δ + 추이 ──────────
#   엔진(collect_region_metrics)이 metrics 페이로드에 '_groups'/'_trend'로 실어 보낸다.
#   DB/세션에 없으면 아래 샘플로 폴백(화면이 비지 않게). 샘플은 상승장 가정.
def _sample_ramp(start, end, n=156):
    import math
    return [round(start + (end - start) * (i / (n - 1)) + 0.12 * math.sin(i / 6.0), 2)
            for i in range(n)]


_TREND_SAMPLE = {
    "gn3":   {"sale": _sample_ramp(101.0, 105.8), "jeonse": _sample_ramp(98.6, 101.2)},
    "seoul": {"sale": _sample_ramp(95.0, 98.2),   "jeonse": _sample_ramp(95.1, 97.4)},
    "gg":    {"sale": _sample_ramp(93.2, 94.6),   "jeonse": _sample_ramp(94.2, 95.8)},
    "all":   {"sale": _sample_ramp(93.9, 96.1),   "jeonse": _sample_ramp(94.4, 96.5)},
}


_GROUP_SAMPLE = {
    "gn3":   {"name": "강남3구", "sale": 105.8, "sale_wk": 0.24, "jeonse": 101.2,
              "jeonse_wk": 0.15, "jr": 51.3, "v": 412, "vc": 18},
    "seoul": {"name": "서울", "sale": 98.2, "sale_wk": 0.18, "jeonse": 97.4,
              "jeonse_wk": 0.09, "jr": 53.9, "v": 1840, "vc": 12},
    "gg":    {"name": "경기", "sale": 94.6, "sale_wk": 0.08, "jeonse": 95.8,
              "jeonse_wk": 0.11, "jr": 61.2, "v": 3210, "vc": 6},
    "all":   {"name": "수도권", "sale": 96.1, "sale_wk": 0.12, "jeonse": 96.5,
              "jeonse_wk": 0.10, "jr": 57.4, "v": 5050, "vc": 9},
}


def fetch_region_levels():
    """권역+시군구 레벨·추이 (groups, trend) 튜플.
    세션/DB metrics의 '_groups'/'_trend'(엔진 실데이터) → 샘플 폴백.
    엔진이 시군구(children)를 안 실어 보낸 경우 지도 샘플에서 시군구를 합성해 채운다."""
    m = _resolved_metrics()
    if isinstance(m, dict):
        g, t = m.get("_groups"), m.get("_trend")
        if g and t:
            return _augment_sigungu(g, t)
    return _augment_sigungu(_GROUP_SAMPLE, _TREND_SAMPLE)


_GU3 = ["강남구", "서초구", "송파구"]


def _augment_sigungu(groups, trend):
    """권역 groups/trend에 시군구(서울 구·경기 시) 레벨·추이를 보강.
    엔진이 이미 children을 실었으면(실데이터) 그대로 반환. 아니면 지도 샘플(_merged_regions의
    주간Δ·거래·전세가율)에서 결정적으로 합성해 아코디언이 폴백 상태에서도 동작하게 한다.
    레벨은 권역 샘플 대비 결정적 오프셋(지역 간 비교용 아님 — 데모/폴백 가독성용)."""
    if any("children" in (groups.get(k) or {}) for k in ("seoul", "gg")):
        return groups, trend
    g = copy.deepcopy(dict(groups))
    t = copy.deepcopy(dict(trend))
    try:
        regions = _merged_regions()
    except Exception:
        regions = []
    seoul_ch, gg_ch = [], []
    for d in regions:
        name, sd = d.get("n"), d.get("sd")
        if not name or sd not in ("seoul", "gg") or name in g:
            continue
        parent = "seoul" if sd == "seoul" else "gg"
        base = (g.get(parent) or {}).get("sale") or 100.0
        jbase = (g.get(parent) or {}).get("jeonse") or 96.0
        off = ((sum(ord(c) for c in name) % 21) - 10) * 0.45
        sale = round(base + off, 2)
        jeon = round(jbase + off * 0.7, 2)
        g[name] = {"name": name, "sale": sale, "sale_wk": d.get("mm", 0.0),
                   "jeonse": jeon, "jeonse_wk": d.get("js", 0.0),
                   "jr": d.get("jr"), "v": d.get("v", 0), "vc": d.get("vc", 0),
                   "leaf": True}
        t[name] = {"sale": _sample_ramp(sale - 3.0, sale),
                   "jeonse": _sample_ramp(jeon - 2.2, jeon)}
        (seoul_ch if parent == "seoul" else gg_ch).append(name)

    def _by_sale(n):
        s = g.get(n, {}).get("sale")
        return s if s is not None else -1.0
    seoul_ch.sort(key=_by_sale, reverse=True)
    gg_ch.sort(key=_by_sale, reverse=True)
    gn3_ch = sorted([n for n in _GU3 if n in g], key=_by_sale, reverse=True)
    if "gn3" in g:
        g["gn3"]["children"] = gn3_ch
    if "seoul" in g:
        g["seoul"]["children"] = seoul_ch
    if "gg" in g:
        g["gg"]["children"] = gg_ch
    if "all" in g:
        g["all"]["children"] = []
    return g, t


_MAPC_HTML = r'''<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
:root{--bg:#FCFCFA;--card:#fff;--ink:#34352f;--muted:#9a9b92;--line:#ECEDE7;--line2:#DEDED7;
 --sage:#A7BBA9;--sage2:#7E9A83;--up:#B65F5A;--dn:#5A7CA0;--jr:#6E8FA8;
 --kfont:'Pretendard',-apple-system,BlinkMacSystemFont,sans-serif;}
*{box-sizing:border-box}
body{margin:0;background:transparent;color:var(--ink);font-family:var(--kfont);font-size:14px;-webkit-font-smoothing:antialiased;}
.up{color:var(--up)}.dn{color:var(--dn)}
.hd{display:flex;justify-content:space-between;align-items:flex-end;gap:10px;margin:0 0 10px;flex-wrap:wrap}
.h1{font-size:18px;font-weight:800;letter-spacing:-.02em}
.crumb{font-size:11.5px;color:var(--muted);margin-top:3px;display:flex;align-items:center;gap:6px}
.crumb b{color:var(--ink)} .crumb .back{cursor:pointer;border:1px solid var(--line2);border-radius:7px;padding:1px 8px;color:var(--ink);background:var(--card);font-size:11px}
.live{display:inline-flex;align-items:center;gap:5px;font-size:11px;color:var(--sage2);font-weight:700;margin-left:6px}
.live i{width:7px;height:7px;border-radius:50%;background:var(--sage2);animation:bl 1.6s ease-in-out infinite}
@keyframes bl{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.35;transform:scale(.7)}}
.seg{display:inline-flex;border:1px solid var(--line2);border-radius:8px;overflow:hidden;background:var(--card)}
.seg button{border:none;background:none;padding:5px 12px;font-size:11.5px;color:var(--muted);cursor:pointer;border-right:1px solid var(--line);font-family:var(--kfont)}
.seg button:last-child{border-right:none}.seg button.on{background:#EEF1EC;color:var(--ink);font-weight:700}
.chips{display:flex;flex-wrap:wrap;gap:7px;margin:0 0 12px}
.chip{font-size:12.5px;color:var(--ink);background:var(--card);border:1px solid var(--line2);border-radius:999px;padding:6px 15px;cursor:pointer;transition:all .15s ease}
.chip:hover{border-color:var(--sage)} .chip.on{background:var(--sage2);color:#fff;border-color:var(--sage2);box-shadow:0 3px 10px rgba(126,154,131,.3)}
.maparea{position:relative;width:100%;height:500px;border:1px solid var(--line);border-radius:16px;background:var(--bg);overflow:hidden;margin-bottom:13px}
#big{display:block;width:100%;height:100%;cursor:crosshair}
.dist{stroke:#fff;stroke-width:.7;transition:fill .4s ease,opacity .3s}
.dlabel{pointer-events:none;fill:#2f302a;font-family:var(--kfont);font-weight:600}
#hoverLabel{pointer-events:none;font-family:var(--kfont);font-weight:800;fill:#23241d;opacity:0;transition:opacity .1s}
.nav{position:absolute;top:11px;right:11px;width:140px;background:rgba(252,252,250,.92);border:1px solid var(--line2);border-radius:12px;padding:8px 8px 6px;backdrop-filter:blur(5px);box-shadow:0 6px 20px rgba(52,53,47,.10)}
.nav .nt{font-size:9.5px;font-weight:800;color:var(--muted);letter-spacing:.04em;margin:0 2px 3px;display:flex;justify-content:space-between}
.nav svg{display:block;width:100%;height:auto}
#kland{fill:#EDEFE9;stroke:#D7DBD0;stroke-width:1.2}
.kdot{cursor:pointer}.kdot circle{transition:r .15s ease,fill .2s ease}
.kdot text{font-size:7.2px;font-weight:800;fill:#5d6258;font-family:var(--kfont);pointer-events:none}
.kdot.on .pulse{animation:pl 1.7s ease-out infinite}
@keyframes pl{0%{r:4;opacity:.5}100%{r:13;opacity:0}}
.legend{position:absolute;left:13px;top:11px;display:flex;flex-direction:column;align-items:flex-start;gap:2px;width:190px;font-size:10px;color:var(--muted);background:rgba(252,252,250,.94);border:1px solid var(--line2);border-radius:9px;padding:6px 9px 5px;backdrop-filter:blur(4px)}
.legend .lgcap{font-size:9.5px;font-weight:700;color:#5d6258}
.legend .lgrow{display:flex;width:100%}
.legend .lgsw{flex:1;height:11px}
.legend .lgsw.neu{outline:1.4px solid #C9CABF;outline-offset:-1.4px}
.legend .lgticks{position:relative;width:100%;height:11px;margin-top:1px}
.legend .lgticks span{position:absolute;font-size:8.5px;font-weight:700;color:#6f7066;white-space:nowrap}
.pills{position:absolute;right:11px;bottom:12px;display:inline-flex;gap:4px;background:rgba(252,252,250,.92);border:1px solid var(--line2);border-radius:9px;padding:3px;backdrop-filter:blur(4px)}
.pills button{border:none;border-radius:7px;padding:4px 10px;font-size:10.5px;color:var(--muted);cursor:pointer;background:transparent;font-family:var(--kfont)}
.pills button.on{background:#EEF1EC;color:var(--ink);font-weight:700}
.tip{position:absolute;pointer-events:none;background:var(--card);border:1px solid var(--line2);border-radius:9px;padding:8px 11px;font-size:12px;min-width:148px;box-shadow:0 6px 22px rgba(52,53,47,.14);opacity:0;transform:translateY(4px);transition:opacity .14s,transform .14s;z-index:7}
.tip .up{color:var(--up)}.tip .dn{color:var(--dn)}
.phbadge{position:absolute;left:50%;top:11px;transform:translateX(-50%);font-size:10px;font-weight:700;color:#9A7B43;background:rgba(255,250,238,.94);border:1px solid #E6D9B8;border-radius:999px;padding:3px 11px;backdrop-filter:blur(4px);box-shadow:0 2px 8px rgba(52,53,47,.08);z-index:6}
.vctx{font-weight:700}.vctx.hi{color:#7E9A83}.vctx.lo{color:#5A7CA0}.vctx.nm{color:#9a9b92}
.cnt{color:#5b5c54}
.mrow{display:flex;gap:14px;align-items:flex-start;margin-bottom:6px}
.mleft{flex:2;min-width:0} .mright{flex:3;min-width:0}
table.mx{width:100%;border-collapse:collapse;table-layout:fixed}
.mxwrap{border:1px solid var(--line);border-radius:12px;overflow-y:auto;max-height:440px;}
.mxwrap::-webkit-scrollbar{width:8px}.mxwrap::-webkit-scrollbar-thumb{background:#E2E3DC;border-radius:6px}
table.mx thead th{position:sticky;top:0;z-index:2}
table.mx th{font-size:10.5px;color:var(--muted);font-weight:600;text-align:right;padding:7px 8px;background:var(--card)}
table.mx th i{font-style:normal;font-weight:600;font-size:8.5px;color:#B5B7AD;margin-left:2px;vertical-align:1px}
table.mx th:first-child{text-align:left}
table.mx td{padding:7px 8px;border-top:1px solid var(--line);text-align:right;vertical-align:middle;font-size:11.5px}
table.mx td:first-child{text-align:left;font-weight:700;font-size:12px}
table.mx tr:hover{background:#FAFAF6}
.dl{font-weight:800}.muted{color:var(--muted)}
.panel{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:12px 14px;}
.p-h{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px}
.p-t{font-size:12.5px;font-weight:800}
.p-lg{font-size:10.5px;color:var(--muted);display:flex;gap:12px}.p-lg i{font-style:normal}
.p-r{display:flex;align-items:center;gap:9px}
.cmptog,.cmpmet{display:flex;flex:none}
.cmptog button,.cmpmet button{border:1px solid var(--line2);background:var(--card);color:var(--muted);font-family:var(--kfont);cursor:pointer}
.cmptog button{font-size:9.5px;padding:2px 7px}.cmpmet button{font-size:10px;padding:2px 9px}
.cmptog button:first-child,.cmpmet button:first-child{border-radius:6px 0 0 6px}
.cmptog button:last-child,.cmpmet button:last-child{border-radius:0 6px 6px 0;border-left:none}
.cmptog button.on,.cmpmet button.on{background:#EEF1EC;color:var(--ink);font-weight:700}
.cmpctl{display:flex;flex-wrap:wrap;align-items:center;gap:7px;margin:0 0 7px}
.cmpchips{display:flex;flex-wrap:wrap;gap:5px}
.cmpchip{display:inline-flex;align-items:center;gap:4px;font-size:11px;color:#5b5c54;background:var(--card);border:1px solid var(--line2);border-radius:999px;padding:3px 9px;cursor:pointer;transition:all .12s}
.cmpchip .cd{width:8px;height:8px;border-radius:50%;background:#C4C6BD}
.cmpchip.on{color:var(--ink);font-weight:700}
.dot{display:inline-block;width:9px;height:9px;border-radius:2px;vertical-align:-1px;margin-right:3px}
#trChart{display:block;width:100%;height:auto}
.axt{fill:var(--muted);font-size:10px;font-family:var(--kfont)}
.axtitle{fill:#8b8c84;font-size:8px;font-family:var(--kfont)}
.vtip{position:absolute;pointer-events:none;background:var(--card);border:1px solid var(--line2);border-radius:7px;padding:6px 9px;font-size:11px;opacity:0;transition:opacity .12s;white-space:nowrap;box-shadow:0 4px 14px rgba(52,53,47,.12);z-index:6}
.note{color:var(--muted);font-size:10.8px;margin-top:9px;line-height:1.6}
.draw{stroke-dasharray:var(--L);stroke-dashoffset:var(--L);}
.drawn{stroke-dashoffset:0;transition:stroke-dashoffset .85s ease}
@media(max-width:760px){.maparea{height:400px}.nav{display:none}.mrow{flex-direction:column}.mleft,.mright{width:100%;flex:none}.mxwrap{max-height:280px}}
</style></head><body>
<div class="hd">
  <div><div class="crumb"><span class="back" id="back">‹ 전국</span> <span>전국</span> › <b id="crName">서울</b>
      <span class="live"><i></i> 방금 갱신</span></div></div>
  <div class="seg" id="periodSeg"><button data-p="1y">1년</button><button data-p="3y">3년</button><button data-p="all" class="on">전체</button></div>
</div>
<div class="chips" id="chips"></div>
<div class="maparea" id="maparea">
  <div class="legend" id="legend"></div>
  <svg id="big" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet" role="img" aria-label="상세 지도"></svg>
  <div class="pills" id="metricPills"><button data-m="mm" class="on">매매</button><button data-m="js">전세</button><button data-m="v">거래</button><button data-m="jr">전세가율</button></div>
  <div class="nav"><div class="nt"><span>전국</span><span style="color:#C4C6BD">탭하여 이동</span></div>
    <svg viewBox="0 0 120 150" role="img" aria-label="한반도 내비게이터">
      <path id="kland" d="M44 14 C58 8 74 12 80 24 C86 34 82 44 88 52 C95 61 96 72 90 80 C97 86 100 96 95 106 C101 112 100 124 92 130 C86 134 80 128 76 120 C70 126 62 122 60 114 C52 118 44 114 42 106 C33 108 24 102 24 92 C16 90 12 80 18 72 C12 64 14 52 24 48 C22 38 28 26 38 22 C39 18 41 15 44 14 Z"></path>
      <g id="kdots"></g></svg></div>
  <div class="tip" id="tip"></div>
  <div class="phbadge" id="phbadge" hidden>예시 배치 · 실제 구 경계 아님</div>
</div>
<div class="mrow">
  <div class="mleft"><div class="mxwrap"><table class="mx"><thead><tr><th style="width:34%">지역</th><th>매매Δ<i>월</i></th><th>전세Δ<i>월</i></th><th>거래<i>주</i></th><th>전세가율<i>월</i></th></tr></thead><tbody id="mxBody"></tbody></table></div></div>
  <div class="mright"><div class="panel"><div class="p-h"><span class="p-t" id="trTitle"></span>
    <span class="p-r"><span class="p-lg" id="trLeg"><i><span class="dot" style="background:#B65F5A"></span>매매</i><i><span class="dot" style="background:#5A7CA0"></span>전세</i></span>
      <span class="cmptog" id="cmpTog"><button data-cm="single" class="on">단일</button><button data-cm="cmp">비교</button></span></span></div>
    <div class="cmpctl" id="cmpCtl" hidden><span class="cmpmet" id="cmpMet"><button data-m="mm" class="on">매매</button><button data-m="js">전세</button></span><span class="cmpchips" id="cmpChips"></span></div>
    <div style="position:relative"><svg id="trChart" viewBox="0 0 620 230" role="img" aria-label="가격지수 추이"></svg><div class="vtip" id="vtip"></div></div></div></div>
</div>
<div class="note" id="note"></div>
<script>
const D=__D__,LGEO=__LGEO__,LOCAL=__LOCAL__,TREND=__TREND__,GN3=__GN3__,ASOF=__ASOF__;
const ORDER=["gn3","seoul","gg","incheon","daegu","busan"];
const RNAME={gn3:"강남3구",seoul:"서울",gg:"경기",incheon:"인천",daegu:"대구",busan:"부산"};
const SUDO=new Set(["gn3","seoul","gg"]);
const NAVPOS={incheon:[34,54],seoul:[50,47],gn3:[54,55,1],gg:[64,45],daegu:[82,96],busan:[95,118]};
let region="seoul",metric="mm",period="all",busy=false;
const fmtP=v=>(v>0?"+":"")+(+v||0).toFixed(2)+"%";
const cls=v=>v>0.005?"up":(v<-0.005?"dn":"");
function colMM(v){if(v>=.30)return"#C16C64";if(v>=.15)return"#D89089";if(v>=.05)return"#E9BDB8";if(v>-.02)return"#EFEEE9";if(v>-.10)return"#C9D6E5";return"#A9C0DA";}
function colJR(v){if(v>=68)return"#6E8FA8";if(v>=63)return"#92ABC1";if(v>=58)return"#B4C7D8";if(v>=53)return"#D2DEE9";return"#EBF0F5";}
function vrat(d){return (d.vavg!=null&&d.vavg>0&&d.v!=null)?(d.v/d.vavg-1)*100:null;}
function colVR(p){if(p>=100)return"#5E8770";if(p>=50)return"#8FB39B";if(p>=15)return"#BBD2C0";if(p>-15)return"#EFEEE9";if(p>-40)return"#DDE4D8";return"#C9D2C4";}
function volCtx(d){const p=vrat(d);if(p==null)return null;const m=d.v/d.vavg;
  if(Math.abs(p)<15)return{full:"평소 수준",bare:"평소",cls:"nm"};
  if(m>=2)return{full:"평소 "+m.toFixed(1)+"×",bare:m.toFixed(1)+"×",cls:"hi"};
  if(p>0)return{full:"평소 +"+Math.round(p)+"%",bare:"+"+Math.round(p)+"%",cls:"hi"};
  return{full:"평소 "+Math.round(p)+"%",bare:Math.round(p)+"%",cls:"lo"};}
function fillOf(d){if(metric==="v"){const p=vrat(d);return p==null?"#F1F2EC":colVR(p);}if(metric==="jr")return colJR(d.jr==null?0:d.jr);return colMM(metric==="js"?d.js:d.mm);}
function pathsOf(r){
  if(SUDO.has(r)){
    let f=r==="gn3"?D.filter(d=>GN3.includes(d.n)):r==="seoul"?D.filter(d=>d.sd==="seoul"):D.filter(d=>d.sd==="gg");
    return f.map(d=>({n:d.n,sl:d.sl,d:d.d,cx:d.cx,cy:d.cy,mm:d.mm,js:d.js,v:d.v,vc:d.vc,vavg:d.vavg,jr:d.jr}));}
  const geo=LGEO[r]||[],lc=(LOCAL[r]||{}).gu||{};
  return geo.map(t=>{const m=lc[t.n]||{};
    return {n:t.n,sl:t.sl,d:t.d,cx:t.cx,cy:t.cy,mm:m.mm||0,js:m.js||0,v:null,jr:(m.jr==null?null:m.jr)};});
}
function pathNums(d){return (d.match(/-?\d+\.?\d*/g)||[]).map(Number);}
function vbOf(paths){let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;
  paths.forEach(d=>{const n=pathNums(d.d);for(let i=0;i+1<n.length;i+=2){const x=n[i],y=n[i+1];if(x<x0)x0=x;if(x>x1)x1=x;if(y<y0)y0=y;if(y>y1)y1=y;}});
  if(x1<x0)return[0,0,1100,1087];const px=(x1-x0)*0.07,py=(y1-y0)*0.15;
  return[x0-px,y0-py,(x1-x0)+2*px,(y1-y0)+2*py];}

function drawChips(){document.getElementById("chips").innerHTML=ORDER.map(r=>
  `<div class="chip ${r===region?"on":""}" data-r="${r}">${RNAME[r]}</div>`).join("");
  document.querySelectorAll(".chip").forEach(c=>c.onclick=()=>setRegion(c.dataset.r));}
function drawNav(){document.getElementById("kdots").innerHTML=ORDER.map(r=>{const p=NAVPOS[r];const on=r===region;const rad=p[2]?2.6:3.6;
  return `<g class="kdot ${on?"on":""}" data-r="${r}">${on?`<circle class="pulse" cx="${p[0]}" cy="${p[1]}" r="4" fill="#B65F5A"/>`:""}<circle class="main" cx="${p[0]}" cy="${p[1]}" r="${rad}" fill="${on?"#B65F5A":"#9aa39b"}"/><text x="${p[0]}" y="${p[1]-6}" text-anchor="middle">${p[2]?"강남3":RNAME[r]}</text></g>`;}).join("");
  document.querySelectorAll("#kdots .kdot").forEach(el=>el.onclick=()=>setRegion(el.dataset.r));}
function lgStepped(cells,ticks,cap){
  const sw=cells.map((c,i)=>{let r="";if(i===0)r=";border-radius:3px 0 0 3px";if(i===cells.length-1)r=";border-radius:0 3px 3px 0";
    return `<div class="lgsw${c.neu?" neu":""}" style="background:${c.c}${r}"></div>`;}).join("");
  const tk=ticks.map(t=>`<span style="${t.pos}">${t.t}</span>`).join("");
  return `<div class="lgcap">${cap}</div><div class="lgrow">${sw}</div><div class="lgticks">${tk}</div>`;}
function drawLegend(){let h="";
  if(metric==="v")h=lgStepped(
    [{c:"#C9D2C4"},{c:"#DDE4D8"},{c:"#EFEEE9",neu:true},{c:"#BBD2C0"},{c:"#8FB39B"},{c:"#5E8770"}],
    [{t:"한산",pos:"left:0"},{t:"평소",pos:"left:41.7%;transform:translateX(-50%);color:#34352f"},{t:"활발",pos:"right:0"}],
    "거래 평소 대비 · 주간");
  else if(metric==="jr")h=lgStepped(
    [{c:"#EBF0F5"},{c:"#D2DEE9"},{c:"#B4C7D8"},{c:"#92ABC1"},{c:"#6E8FA8"}],
    [{t:"53",pos:"left:20%;transform:translateX(-50%)"},{t:"58",pos:"left:40%;transform:translateX(-50%)"},{t:"63",pos:"left:60%;transform:translateX(-50%)"},{t:"68%",pos:"left:80%;transform:translateX(-50%)"}],
    "전세가율 % · 월간");
  else h=lgStepped(
    [{c:"#A9C0DA"},{c:"#C9D6E5"},{c:"#EFEEE9",neu:true},{c:"#E9BDB8"},{c:"#D89089"},{c:"#C16C64"}],
    [{t:"≤−.10",pos:"left:0"},{t:"0%",pos:"left:41.7%;transform:translateX(-50%);color:#34352f"},{t:"≥+.30",pos:"right:0"}],
    (metric==="mm"?"매매":"전세")+" 등락 % · 월간");
  document.getElementById("legend").innerHTML=h;}

let _paths=[],_vb=[0,0,100,100];
function pathsHTML(big){const ps=_paths.map((d,i)=>`<path class="dist" data-i="${i}" d="${d.d}" fill="${fillOf(d)}"></path>`).join("");
  const ref=Math.sqrt(_vb[2]*_vb[3]/Math.max(1,_paths.length));   // 평균 구역 한 변(viewBox 단위)
  const labs=_paths.map(d=>{const fs=ref*(d.sl.length>3?0.135:0.165);   // 화면 픽셀 균일 + 밀도(N) 보정
    return `<text class="dlabel" x="${d.cx}" y="${d.cy}" text-anchor="middle" dominant-baseline="middle" font-size="${fs.toFixed(1)}" paint-order="stroke" stroke="#FCFCFA" stroke-width="${(fs*0.22).toFixed(1)}" stroke-linejoin="round">${d.sl}</text>`;}).join("");
  return `<g id="paths">${ps}</g><g>${labs}</g>`;}
function drawMap(){_paths=pathsOf(region);_vb=vbOf(_paths);const svg=document.getElementById("big");
  svg.setAttribute("viewBox",_vb.join(" "));const big=_paths.length<=8;
  svg.innerHTML=pathsHTML(big)+`<text id="hoverLabel" text-anchor="middle" dominant-baseline="middle" paint-order="stroke" stroke="#FCFCFA" stroke-width="2.6" stroke-linejoin="round"></text>`;
  const tip=document.getElementById("tip"),area=document.getElementById("maparea"),pg=svg.querySelector("#paths"),hl=svg.querySelector("#hoverLabel");
  svg.querySelectorAll("path.dist").forEach(p=>{const d=_paths[+p.dataset.i];
    p.onmouseenter=()=>{p.style.stroke="#7E9A83";p.style.strokeWidth="1.6";pg.appendChild(p);
      const _vx=volCtx(d);const vline=d.v==null?'<div class="muted">거래 — 미수집(지방)</div>'
        :`<div class="muted">거래 ${d.v}건${_vx?` · <span class="vctx ${_vx.cls}">${_vx.full}</span>`:""}</div>`;
      tip.innerHTML=`<div style="font-weight:800;margin-bottom:4px">${d.n}</div><div class="muted">매매 <span class="${cls(d.mm)}">${fmtP(d.mm)}</span> · 전세 <span class="${cls(d.js)}">${fmtP(d.js)}</span></div>${vline}<div class="muted">전세가율 ${d.jr==null?"-":d.jr+"%"}</div><div class="muted" style="font-size:10px;margin-top:3px;color:#A9AB9F">매매·전세·전세가율 월간(전월대비) · 거래 주간</div>`;
      tip.style.opacity="1";tip.style.transform="translateY(0)";
      const _hf=Math.sqrt(_vb[2]*_vb[3]/Math.max(1,_paths.length))*0.20;
      hl.setAttribute("x",d.cx);hl.setAttribute("y",d.cy);hl.setAttribute("font-size",_hf.toFixed(1));hl.setAttribute("stroke-width",(_hf*0.22).toFixed(1));hl.textContent=d.sl;hl.style.opacity="1";};
    p.onmouseleave=()=>{p.style.stroke="#fff";p.style.strokeWidth=".7";tip.style.opacity="0";hl.style.opacity="0";};});
  area.onmousemove=e=>{const b=area.getBoundingClientRect();let x=e.clientX-b.left,y=e.clientY-b.top;
    let tx=x+14,ty=y+14;if(tx>b.width-176)tx-=190;if(ty>b.height-96)ty-=104;tip.style.left=tx+"px";tip.style.top=ty+"px";};
  area.onmouseleave=()=>{tip.style.opacity="0";hl.style.opacity="0";};}

function drawTable(){const rows=_paths.length?_paths:pathsOf(region);
  const sorted=[...rows].sort((a,b)=>(b.mm||-9)-(a.mm||-9));
  document.getElementById("mxBody").innerHTML=sorted.map(d=>{
    const _vx=volCtx(d);
    const vcell=d.v==null?'<span class="muted">–</span>'
      :`<span class="cnt">${d.v.toLocaleString()}</span>${_vx?` <span class="vctx ${_vx.cls}" style="font-size:10px">${_vx.bare}</span>`:""}`;
    return `<tr><td>${d.n}</td><td><span class="dl ${cls(d.mm)}">${fmtP(d.mm)}</span></td>`
      +`<td><span class="dl ${cls(d.js)}">${fmtP(d.js)}</span></td><td>${vcell}</td>`
      +`<td>${d.jr==null?"-":d.jr+"%"}</td></tr>`;}).join("");}

function trendOf(r){if(SUDO.has(r))return TREND[r]||{};const o=(LOCAL[r]||{}).others||{};return{sale:o.sale,jeonse:o.jeonse};}
function sliceP(a){const wk=SUDO.has(region);const n=period==="1y"?(wk?52:12):period==="3y"?(wk?156:36):1e9;return (a||[]).slice(-n);}
let _trH=230,_trB=188;   // 추이 차트 viewBox 높이(좌측 표 높이에 맞춰 동적 산정)
function fitTrendHeight(){
  try{
    const svg=document.getElementById("trChart");if(!svg){drawTrend();return;}
    const svgC=svg.parentElement;                 // position:relative 컨테이너
    const panel=svgC.closest(".panel");
    const left=document.querySelector(".mleft");
    const W=svgC.clientWidth||svg.clientWidth||500;
    if(left&&panel&&W>1){
      const headH=svgC.getBoundingClientRect().top-panel.getBoundingClientRect().top; // 패널 헤더+컨트롤 높이
      const targetH=Math.max(230,left.offsetHeight-headH-12);   // 좌측 표 높이 − 헤더 − 패딩
      _trH=Math.round(620*targetH/W);             // 렌더 높이 ≈ targetH 되도록 viewBox 높이 환산
    }else _trH=230;
    _trB=_trH-42;                                 // 플롯 바닥(축 라벨 42 확보)
    svg.setAttribute("viewBox","0 0 620 "+_trH);
  }catch(e){_trH=230;_trB=188;}
  drawTrend();
}
function drawChart(){const tk=trendOf(region);const sale=sliceP(tk.sale),jeon=sliceP(tk.jeonse);
  document.getElementById("trTitle").textContent=RNAME[region]+" 가격지수 추이";
  const svg=document.getElementById("trChart");const all=(sale||[]).concat(jeon||[]).filter(v=>v!=null);
  if(all.length<2){svg.innerHTML='<text class="axt" x="310" y="'+(_trH/2).toFixed(0)+'" text-anchor="middle">추이 데이터가 아직 없어요</text>';return;}
  const L=52,Rr=606,T0=14,B=_trB,W=Rr-L,Hh=B-T0,n=sale.length,wk=SUDO.has(region);
  let dmn=Math.min(...all),dmx=Math.max(...all);const pad=(dmx-dmn)*0.14||1,lo=dmn-pad,hi=dmx+pad,rr=(hi-lo)||1;
  const X=i=>L+(n<=1?0:i/(n-1)*W),Y=v=>B-(v-lo)/rr*Hh;
  const line=s=>s.map((v,i)=>v==null?"":`${(i&&s[i-1]!=null)?"L":"M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
  const area=`M${X(0).toFixed(1)},${B} `+sale.map((v,i)=>`L${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ")+` L${X(n-1).toFixed(1)},${B} Z`;
  let grid="";const step=(hi-lo)/3;for(let g=0;g<=3;g++){const tv=lo+step*g,y=Y(tv).toFixed(1);
    grid+=`<line x1="${L}" y1="${y}" x2="${Rr}" y2="${y}" stroke="#F1F2EC"/><text class="axt" x="${L-7}" y="${(+y+3).toFixed(1)}" text-anchor="end">${tv.toFixed(0)}</text>`;}
  let xt="";const asof=new Date(ASOF+"T00:00:00");
  for(let j=0;j<4;j++){const i=Math.round(j/3*(n-1));const d=new Date(asof);
    if(wk)d.setDate(d.getDate()-7*(n-1-i));else d.setMonth(d.getMonth()-(n-1-i));
    xt+=`<text class="axt" x="${X(i).toFixed(1)}" y="${B+15}" text-anchor="middle">'${String(d.getFullYear()).slice(2)}.${d.getMonth()+1}</text>`;}
  const ycy=((T0+B)/2).toFixed(0);
  svg.innerHTML=`<defs><linearGradient id="gA" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#B65F5A" stop-opacity=".24"/><stop offset="1" stop-color="#B65F5A" stop-opacity="0"/></linearGradient></defs>`
    +grid+`<line x1="${L}" y1="${B}" x2="${Rr}" y2="${B}" stroke="#D7D8D0"/>`
    +`<path id="trArea" d="${area}" fill="url(#gA)" opacity="0" style="transition:opacity .6s ease .15s"/>`
    +`<path id="trJeon" class="draw" d="${line(jeon)}" fill="none" stroke="#5A7CA0" stroke-width="1.7" stroke-dasharray="4 3"/>`
    +`<path id="trSale" class="draw" d="${line(sale)}" fill="none" stroke="#B65F5A" stroke-width="2.2"/>`
    +`<circle id="trDotS" cx="${X(n-1)}" cy="${Y(sale[n-1])}" r="4" fill="#B65F5A" stroke="#fff" stroke-width="1.4" opacity="0" style="transition:opacity .3s ease .7s"/>`
    +`<circle id="trDotJ" cx="${X(n-1)}" cy="${Y(jeon[n-1])}" r="3.2" fill="#5A7CA0" stroke="#fff" stroke-width="1.2" opacity="0" style="transition:opacity .3s ease .7s"/>`
    +xt+`<text class="axtitle" x="${((L+Rr)/2).toFixed(0)}" y="${_trH-6}" text-anchor="middle">시점(${wk?"주간 지수":"월간 지수"})</text>`
    +`<text class="axtitle" x="14" y="${ycy}" text-anchor="middle" transform="rotate(-90 14 ${ycy})">가격지수 (2022.1.10=100)</text>`
    +`<line class="vx" x1="${L}" x2="${L}" y1="${T0}" y2="${B}" stroke="#B9BBB0" stroke-dasharray="3 3" opacity="0"/>`
    +`<circle class="vd1" r="3" fill="#B65F5A" opacity="0"/><circle class="vd2" r="2.6" fill="#5A7CA0" opacity="0"/>`;
  // ── 그려지는 애니메이션 (stroke-dashoffset) ──
  ["trSale","trJeon"].forEach(id=>{const p=svg.querySelector("#"+id);const Ln=p.getTotalLength();
    p.style.setProperty("--L",Ln);p.style.strokeDasharray=Ln;p.style.strokeDashoffset=Ln;p.getBoundingClientRect();
    p.style.transition="stroke-dashoffset .85s ease";p.style.strokeDashoffset="0";});
  requestAnimationFrame(()=>{svg.querySelector("#trArea").style.opacity="1";svg.querySelector("#trDotS").style.opacity="1";svg.querySelector("#trDotJ").style.opacity="1";});
  // 호버 크로스헤어
  const vtip=document.getElementById("vtip"),vx=svg.querySelector(".vx"),vd1=svg.querySelector(".vd1"),vd2=svg.querySelector(".vd2");
  svg.onmousemove=e=>{const b=svg.getBoundingClientRect();const ux=(e.clientX-b.left)/b.width*620;let i=Math.round((ux-L)/W*(n-1));i=Math.max(0,Math.min(n-1,i));
    const x=X(i);vx.setAttribute("x1",x);vx.setAttribute("x2",x);vx.style.opacity="1";
    if(sale[i]!=null){vd1.setAttribute("cx",x);vd1.setAttribute("cy",Y(sale[i]));vd1.style.opacity="1";}else vd1.style.opacity="0";
    if(jeon[i]!=null){vd2.setAttribute("cx",x);vd2.setAttribute("cy",Y(jeon[i]));vd2.style.opacity="1";}else vd2.style.opacity="0";
    vtip.innerHTML=`매매 <b>${sale[i]==null?"-":sale[i]}</b> · 전세 <b style="color:#5A7CA0">${jeon[i]==null?"-":jeon[i]}</b>`;
    let lx=e.clientX-b.left+12;if(lx>b.width-150)lx-=160;vtip.style.left=lx+"px";vtip.style.top="2px";vtip.style.opacity="1";};
  svg.onmouseleave=()=>{vx.style.opacity="0";vd1.style.opacity="0";vd2.style.opacity="0";vtip.style.opacity="0";};}

// ── 지역 비교 모드 (여러 지역 가격지수 오버레이 · 월간 통일) ──
const CMPC={gn3:"#B65F5A",seoul:"#C28A4E",gg:"#5A7CA0",incheon:"#7E9A83",daegu:"#9A7AA8",busan:"#C2A24E"};
let cmpMode=false,cmpSel=["gn3","gg","busan"],cmpMet="mm";
function toMonthly(series,weekly){const s=(series||[]).filter(v=>v!=null);
  if(!weekly)return s.slice();
  const n=s.length,asof=new Date(ASOF+"T00:00:00"),bk={},od=[];
  for(let i=0;i<n;i++){const d=new Date(asof);d.setDate(d.getDate()-7*(n-1-i));const k=d.getFullYear()+"-"+d.getMonth();if(!(k in bk))od.push(k);bk[k]=s[i];}
  return od.map(k=>bk[k]);}
function cmpSeries(rk,met){let raw;
  if(SUDO.has(rk)){const tk=TREND[rk]||{};raw=met==="js"?tk.jeonse:tk.sale;return toMonthly(raw,true);}
  const o=(LOCAL[rk]||{}).others||{};raw=met==="js"?o.jeonse:o.sale;return toMonthly(raw,false);}
function drawCompare(){
  document.getElementById("trTitle").textContent="지역 비교 · "+(cmpMet==="js"?"전세":"매매")+" 지수";
  const svg=document.getElementById("trChart");svg.onmousemove=null;svg.onmouseleave=null;
  document.getElementById("vtip").style.opacity="0";
  const pm=period==="1y"?12:period==="3y"?36:1e9;
  let series=cmpSel.map(k=>({k,c:CMPC[k],nm:RNAME[k],s:cmpSeries(k,cmpMet)})).filter(o=>o.s&&o.s.length>=2);
  if(!series.length){svg.innerHTML='<text class="axt" x="310" y="'+(_trH/2).toFixed(0)+'" text-anchor="middle">비교할 지역을 선택하세요</text>';return;}
  let K=Math.min(...series.map(o=>o.s.length));K=Math.min(K,pm);
  series=series.map(o=>({k:o.k,c:o.c,nm:o.nm,s:o.s.slice(-K)}));
  const L=52,Rr=606,T0=14,B=_trB,W=Rr-L,Hh=B-T0,n=K;
  let all=[];series.forEach(o=>all=all.concat(o.s));
  let dmn=Math.min(...all),dmx=Math.max(...all);const pad=(dmx-dmn)*0.14||1,lo=dmn-pad,hi=dmx+pad,rr=(hi-lo)||1;
  const X=i=>L+(n<=1?0:i/(n-1)*W),Y=v=>B-(v-lo)/rr*Hh;
  let grid="";const step=(hi-lo)/3;for(let g=0;g<=3;g++){const tv=lo+step*g,y=Y(tv).toFixed(1);
    grid+=`<line x1="${L}" y1="${y}" x2="${Rr}" y2="${y}" stroke="#F1F2EC"/><text class="axt" x="${L-7}" y="${(+y+3).toFixed(1)}" text-anchor="end">${tv.toFixed(0)}</text>`;}
  let xt="";const asof=new Date(ASOF+"T00:00:00");
  for(let j=0;j<4;j++){const i=Math.round(j/3*(n-1));const d=new Date(asof);d.setMonth(d.getMonth()-(n-1-i));
    xt+=`<text class="axt" x="${X(i).toFixed(1)}" y="${B+15}" text-anchor="middle">'${String(d.getFullYear()).slice(2)}.${d.getMonth()+1}</text>`;}
  let lines="";series.forEach(o=>{const d=o.s.map((v,i)=>`${i?"L":"M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
    lines+=`<path d="${d}" fill="none" stroke="${o.c}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
    const lx=X(n-1),ly=Y(o.s[n-1]);
    lines+=`<circle cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="3.4" fill="${o.c}" stroke="#fff" stroke-width="1.3"/><text class="axt" x="${(lx+6).toFixed(1)}" y="${(ly+3).toFixed(1)}" fill="${o.c}" font-weight="700">${o.s[n-1].toFixed(0)}</text>`;});
  const ycy=((T0+B)/2).toFixed(0);
  svg.innerHTML=grid+`<line x1="${L}" y1="${B}" x2="${Rr}" y2="${B}" stroke="#D7D8D0"/>`+xt
    +`<text class="axtitle" x="${((L+Rr)/2).toFixed(0)}" y="${_trH-6}" text-anchor="middle">시점(월간)</text>`
    +`<text class="axtitle" x="14" y="${ycy}" text-anchor="middle" transform="rotate(-90 14 ${ycy})">가격지수 (2022.1.10=100)</text>`+lines;}
function drawTrend(){if(cmpMode)drawCompare();else drawChart();}
function drawCmpChips(){document.getElementById("cmpChips").innerHTML=ORDER.map(k=>{const on=cmpSel.includes(k),c=CMPC[k];
  return `<span class="cmpchip ${on?"on":""}" data-k="${k}" style="${on?`border-color:${c};background:${c}14`:""}"><span class="cd" style="${on?`background:${c}`:""}"></span>${RNAME[k]}</span>`;}).join("");
  document.querySelectorAll("#cmpChips .cmpchip").forEach(c=>c.onclick=()=>cmpToggle(c.dataset.k));}
function cmpToggle(k){const i=cmpSel.indexOf(k);
  if(i>=0){if(cmpSel.length<=1)return;cmpSel.splice(i,1);}
  else{if(cmpSel.length>=3)return;cmpSel.push(k);}
  drawCmpChips();drawCompare();}

function updateNote(){const ph=!SUDO.has(region);
  document.getElementById("note").innerHTML=(ph
    ?"인천·부산·대구는 구별 KB 월간 가격지수 · 지도 형태는 예시 배치(실제 구 경계 아님) · 거래(실거래)는 지방 미수집(–) · 군·섬 지역 제외"
    :"우상단 미니 한반도/칩으로 지역 이동 · 시군구는 표본 작아 주간 거래 변동 큼")
    +" · 매매·전세Δ=KB 월간 가격지수 전월대비, 전세가율=KB 월간, 거래=주간 실거래(평소比=현재주 vs 최근2개월 주당 평균·현재주 제외, 신고지연으로 참고용) · 추이=KB 지수("
    +(ph?"월간":"수도권 주간·지방 월간")+", 2022.1.10=100)";}

function refresh(){drawChips();drawNav();drawLegend();drawMap();drawTable();fitTrendHeight();updateNote();document.getElementById("crName").textContent=RNAME[region];
  document.getElementById("phbadge").hidden=SUDO.has(region);}
function setRegion(k){if(!RNAME[k]||busy)return;busy=true;region=k;
  drawChips();drawNav();document.getElementById("crName").textContent=RNAME[k];
  const svg=document.getElementById("big");svg.style.transformOrigin="50% 46%";svg.style.transition="transform .16s ease, opacity .16s ease";
  svg.style.opacity="0";svg.style.transform="scale(1.12)";
  setTimeout(()=>{drawLegend();drawMap();drawTable();fitTrendHeight();updateNote();
    svg.style.transition="none";svg.style.opacity="0";svg.style.transform="scale(.9)";svg.getBoundingClientRect();
    requestAnimationFrame(()=>requestAnimationFrame(()=>{svg.style.transition="transform .44s cubic-bezier(.18,.7,.3,1), opacity .3s ease";svg.style.opacity="1";svg.style.transform="scale(1)";}));
    setTimeout(()=>{busy=false;},480);},190);}
document.querySelectorAll("#periodSeg button").forEach(b=>b.onclick=()=>{document.querySelectorAll("#periodSeg button").forEach(x=>x.classList.remove("on"));b.classList.add("on");period=b.dataset.p;drawTrend();});
document.querySelectorAll("#cmpTog button").forEach(b=>b.onclick=()=>{document.querySelectorAll("#cmpTog button").forEach(x=>x.classList.remove("on"));b.classList.add("on");
  cmpMode=(b.dataset.cm==="cmp");document.getElementById("cmpCtl").hidden=!cmpMode;document.getElementById("trLeg").style.display=cmpMode?"none":"";
  if(cmpMode)drawCmpChips();drawTrend();});
document.querySelectorAll("#cmpMet button").forEach(b=>b.onclick=()=>{document.querySelectorAll("#cmpMet button").forEach(x=>x.classList.remove("on"));b.classList.add("on");cmpMet=b.dataset.m;drawCompare();});
document.querySelectorAll("#metricPills button").forEach(b=>b.onclick=()=>{document.querySelectorAll("#metricPills button").forEach(x=>x.classList.remove("on"));b.classList.add("on");metric=b.dataset.m;drawLegend();drawMap();drawTable();});
document.getElementById("back").onclick=()=>setRegion("seoul");
refresh();
setTimeout(fitTrendHeight,220);setTimeout(fitTrendHeight,750);   // 폰트·레이아웃 안정 후 재맞춤
(function(){let _rt;window.addEventListener("resize",function(){clearTimeout(_rt);_rt=setTimeout(fitTrendHeight,180);});})();
(function(){function _fit(){try{var h=Math.ceil(document.body.getBoundingClientRect().height)+2;if(window.frameElement){window.frameElement.style.height=h+"px";window.frameElement.setAttribute("height",h);}}catch(e){}}window.addEventListener("load",_fit);setTimeout(_fit,150);setTimeout(_fit,600);setTimeout(_fit,1500);window.addEventListener("resize",_fit);try{new ResizeObserver(_fit).observe(document.body);}catch(e){}})();
</script></body></html>
'''


def _add_months(d, k):
    m = d.month - 1 + k
    y = d.year + m // 12
    return type(d)(y, m % 12 + 1, 1)


def _monthly_series(series, weekly, asof):
    """시계열을 월말값으로 리샘플 → [((y,m), value)...]. weekly면 7일, 아니면 1개월씩 역산."""
    from datetime import timedelta, date as _date
    s = [float(v) for v in (series or []) if v is not None]
    if not s:
        return []
    base = _date(asof.year, asof.month, 1)
    bucket = {}
    n = len(s)
    for i, v in enumerate(s):
        back = n - 1 - i
        if weekly:
            d = asof - timedelta(days=7 * back)
        else:
            d = _add_months(base, -back)
        bucket[(d.year, d.month)] = v
    return [(ym, bucket[ym]) for ym in sorted(bucket)]


def _streak_ytd(monthly):
    """(방향 up:bool|None, 연속개월:int, 26년초대비 %:float|None)."""
    vals = [v for _, v in monthly]
    if len(vals) < 2:
        return (None, 0, None)
    up = vals[-1] >= vals[-2]
    cnt = 1
    for i in range(len(vals) - 2, 0, -1):
        if (vals[i] >= vals[i - 1]) == up:
            cnt += 1
        else:
            break
    base = next((v for (ym, v) in monthly if ym == (2026, 1)), None)
    ytd = (vals[-1] / base - 1) * 100 if base else None
    return (up, cnt, ytd)


def _streak_card(name, su, sc, sy, ju, jc, jy):
    def badge(u, c):
        if u is None or c == 0:
            return '<span class="re-strk-bdg fl">— 자료</span>'
        cls = "up" if u else "dn"
        return f'<span class="re-strk-bdg {cls}">{"▲" if u else "▼"} {c}개월</span>'
    def yt(y):
        if y is None:
            return '<span class="re-strk-ytd fl">—</span>'
        cls = "up" if y >= 0 else "dn"
        return f'<span class="re-strk-ytd {cls}">{"+" if y >= 0 else ""}{y:.1f}%</span>'
    return (f'<div class="re-strk-c"><div class="re-strk-rg">{name}</div>'
            f'<div class="re-strk-row"><span class="t">매매</span>{badge(su, sc)}{yt(sy)}</div>'
            f'<div class="re-strk-row"><span class="t">전세</span>{badge(ju, jc)}{yt(jy)}</div></div>')


def _wb_pct(v, dec=2):
    """전월대비 % 포맷. None이면 '—'. 음수는 유니코드 마이너스(−)."""
    if not isinstance(v, (int, float)):
        return "—"
    sign = "+" if v >= 0 else "−"
    return f"{sign}{abs(v):.{dec}f}%"


def _watchlist_signals():
    """지도 위 '주목 지역' 밴드용 신호 4종. 서울·경기·인천·대구·부산 구를 한 풀로 모아
    급등/약세/거래급증/괴리를 계산한다.
      · mm/js = KB 월간 가격지수 전월대비%(수도권·지방 동일 기준) → 통합 랭킹 안전.
      · vc(거래 전주비%) = 수도권 실거래만 존재 → 거래급증은 수도권 한정.
    각 구는 {'reg'(권역),'nm'(구명),'mm','js','vc'}. 같은 구명(중구 등) 충돌은 reg로 구분."""
    pool = []
    try:
        regions = _merged_regions()
    except Exception:
        regions = _GEO
    for d in (regions or []):
        sd = d.get("sd")
        reg = "서울" if sd == "seoul" else ("경기" if sd == "gg" else None)
        if reg is None:
            continue
        pool.append({"reg": reg, "nm": d.get("n") or d.get("sl") or "",
                     "mm": d.get("mm"), "js": d.get("js"),
                     "v": d.get("v"), "vavg": d.get("vavg")})
    _NM = {"incheon": "인천", "busan": "부산", "daegu": "대구"}
    local = _fetch_local() or {}
    for rk, rv in local.items():
        reg = (rv or {}).get("name") or _NM.get(rk, rk)
        for gname, gv in ((rv or {}).get("gu") or {}).items():
            if not isinstance(gv, dict):
                continue
            pool.append({"reg": reg, "nm": gname,
                         "mm": gv.get("mm"), "js": gv.get("js"),
                         "v": None, "vavg": None})

    def _num(x, k):
        return isinstance(x.get(k), (int, float))

    # 거래 활발도 = 평소比 = (현재주 거래수 v / 평소 주당평균 vavg − 1)×100.
    # 지도 구별 테이블과 동일 지표. 전주比(vc)는 신고지연으로 최신주 표본이 늘
    # 결손 → 대부분 ≤0이라 '급증'이 안 잡히던 문제를 평소比로 통일해 해소.
    V_FLOOR = 2   # 단일 거래로 배수가 튀는 초박형 시군구 제외(노이즈 컷)
    for x in pool:
        v, va = x.get("v"), x.get("vavg")
        x["vr"] = ((v / va - 1) * 100
                   if isinstance(v, (int, float)) and isinstance(va, (int, float))
                   and va > 0 and v >= V_FLOOR else None)

    mm = [x for x in pool if _num(x, "mm")]
    vv = [x for x in pool if _num(x, "vr")]
    gp = [x for x in pool if _num(x, "mm") and _num(x, "js")]
    return {
        "surge": sorted(mm, key=lambda x: x["mm"], reverse=True)[:3],
        "weak": sorted(mm, key=lambda x: x["mm"])[:3],
        "vsurge": sorted(vv, key=lambda x: x["vr"], reverse=True)[:3],
        "gap": sorted(gp, key=lambda x: abs(x["mm"] - x["js"]), reverse=True)[:3],
    }


def _wb_head(title, dot, sub=""):
    s = f'<span class="sub">{sub}</span>' if sub else ""
    return (f'<div class="re-wb-h"><span class="dot" style="background:{dot}"></span>'
            f'{title}{s}</div>')


def _wb_rg(x):
    return f'<span class="rg"><em>{x["reg"]}</em>{x["nm"]}</span>'


def _wb_mover_card(title, dot, items):
    """매매 급등/약세 카드 — 값 부호로 색을 정해 정직하게 표시(상승=red·하락=blue)."""
    if not items:
        return (f'<div class="re-wb-c">{_wb_head(title, dot)}'
                f'<div class="re-wb-r lead"><span class="rg">자료 없음</span></div></div>')
    rows = ""
    for i, x in enumerate(items):
        cls = "lead" if i == 0 else "sub2"
        vc = "up" if x["mm"] >= 0 else "dn"
        rows += (f'<div class="re-wb-r {cls}">{_wb_rg(x)}'
                 f'<span class="v {vc}">{_wb_pct(x["mm"])}</span></div>')
    return f'<div class="re-wb-c">{_wb_head(title, dot)}{rows}</div>'


def _wb_vol_label(x):
    """평소比(vr) → '평소 2.3×' / '평소 +40%' / '평소 수준' / '평소 −41%' (지도 volCtx와 동일)."""
    p = x.get("vr")
    if p is None:
        return "평소 —"
    va = x.get("vavg") or 0
    m = (x.get("v") / va) if va else None
    if abs(p) < 15:
        return "평소 수준"
    if m is not None and m >= 2:
        return f"평소 {m:.1f}×"
    if p > 0:
        return f"평소 +{round(p)}%"
    return f"평소 {round(p)}%"


def _wb_vol_card(title, dot, items):
    """거래 활발도 카드 — 수도권 실거래 평소比(현재주 vs 최근2개월 주당평균)."""
    sub = "수도권 · 평소比"
    if not items:
        return (f'<div class="re-wb-c">{_wb_head(title, dot, sub)}'
                f'<div class="re-wb-r lead"><span class="rg">자료 없음</span></div></div>')
    rows = ""
    for i, x in enumerate(items):
        cls = "lead" if i == 0 else "sub2"
        rows += (f'<div class="re-wb-r {cls}">{_wb_rg(x)}'
                 f'<span class="v sg">{_wb_vol_label(x)}</span></div>')
    return f'<div class="re-wb-c">{_wb_head(title, dot, sub)}{rows}</div>'


def _wb_gap_card(title, dot, items):
    """매매·전세 괴리 카드 — |매매Δ−전세Δ| 큰 순. 매매>전세=매매주도, 반대=전세주도.
    선두만 매·전 상세를 보이고 2·3위는 칩만(카드 높이 균형)."""
    if not items:
        return (f'<div class="re-wb-c">{_wb_head(title, dot)}'
                f'<div class="re-wb-r lead"><span class="rg">자료 없음</span></div></div>')
    rows = ""
    for i, x in enumerate(items):
        lead = (x["mm"] >= x["js"])
        pill = ('<span class="re-wb-pill up">매매주도</span>' if lead
                else '<span class="re-wb-pill dn">전세주도</span>')
        cls = "lead" if i == 0 else "sub2"
        rows += f'<div class="re-wb-r {cls}">{_wb_rg(x)}{pill}</div>'
        if i == 0:
            rows += (f'<div class="re-wb-gap">매 {_wb_pct(x["mm"])} · '
                     f'전 {_wb_pct(x["js"])}</div>')
    return f'<div class="re-wb-c">{_wb_head(title, dot)}{rows}</div>'


def _render_watchlist_band():
    """지도 위 '주목 지역' 밴드 — 5개 권역 구를 한눈에 스캔(급등/약세/거래급증/괴리).
    iframe 바깥 부모 문서에 그려 _RE_CSS 전역 변수를 그대로 쓴다(표시 전용 v1)."""
    sig = _watchlist_signals()
    cards = (_wb_mover_card("매매 급등", "#B65F5A", sig["surge"])
             + _wb_mover_card("매매 약세", "#5A7CA0", sig["weak"])
             + _wb_vol_card("거래 활발도", "#7E9A83", sig["vsurge"])
             + _wb_gap_card("매매·전세 괴리", "#C2A86A", sig["gap"]))
    st.markdown('<div class="re-wb-sec">주목 지역'
                '<span>이번 달 · 전월대비 · 서울·경기·인천·대구·부산 구 단위</span></div>',
                unsafe_allow_html=True)
    st.markdown(f'<div class="re-wb">{cards}</div>', unsafe_allow_html=True)
    st.markdown('<div class="re-wb-foot">매매·전세 = KB 월간 가격지수 전월대비 · '
                '거래 활발도 = 수도권 실거래 평소比(현재주 vs 최근2개월 주당 평균 · '
                '지도 테이블과 동일 지표 · 신고지연으로 참고용 · 지방 미수집) · '
                '같은 구명은 앞의 권역으로 구분</div>', unsafe_allow_html=True)


def _render_streak_section():
    """지도 위 고정 섹션 — 6개 지역 × 매매·전세: 월간 연속 상승/하락 + 26년초 대비 %.
    수도권 추이는 KB 주간 → 월말값 리샘플, 지방은 KB 월간 그대로(월 단위 통일)."""
    from datetime import date as _date
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime as _dt
        asof = _dt.now(ZoneInfo("Asia/Seoul")).date()
    except Exception:
        asof = _date.today()
    _g, t = fetch_region_levels()
    local = _fetch_local()
    REG = [("gn3", "강남3구", True), ("seoul", "서울", True), ("gg", "경기", True),
           ("incheon", "인천", False), ("daegu", "대구", False), ("busan", "부산", False)]
    cards = ""
    for key, name, weekly in REG:
        if weekly:
            tr = (t or {}).get(key, {})
            sale, jeon = tr.get("sale"), tr.get("jeonse")
        else:
            o = ((local or {}).get(key) or {}).get("others", {})
            sale, jeon = o.get("sale"), o.get("jeonse")
        su, sc, sy = _streak_ytd(_monthly_series(sale, weekly, asof))
        ju, jc, jy = _streak_ytd(_monthly_series(jeon, weekly, asof))
        cards += _streak_card(name, su, sc, sy, ju, jc, jy)
    st.markdown('<div class="re-strk-sec">가격지수 동향'
                '<span>월간 · 연속 상승/하락 · \u201926년초 대비</span></div>',
                unsafe_allow_html=True)
    st.markdown(f'<div class="re-strk">{cards}</div>', unsafe_allow_html=True)


def _map_component(regions, groups, trend, local):
    """지도 탭 C안 컴포넌트(iframe) — 미니 한반도 내비(상시) + 줌 전환 + 6지역 + 구별표 + 추이."""
    import json as _json
    from datetime import date as _date
    D = _json.dumps(regions, ensure_ascii=False, separators=(",", ":"))
    LG = _json.dumps(_LOCAL_GEO, ensure_ascii=False, separators=(",", ":"))
    LC = _json.dumps(local or {}, ensure_ascii=False, separators=(",", ":"))
    TR = _json.dumps({k: (trend or {}).get(k, {}) for k in ("gn3", "seoul", "gg")},
                     ensure_ascii=False, separators=(",", ":"))
    GN3 = _json.dumps(["강남구", "서초구", "송파구"], ensure_ascii=False)
    AS = _json.dumps(_date.today().isoformat())
    return (_MAPC_HTML.replace("__D__", D).replace("__LGEO__", LG)
            .replace("__LOCAL__", LC).replace("__TREND__", TR)
            .replace("__GN3__", GN3).replace("__ASOF__", AS))


def _fetch_local():
    """지방 광역시(인천·부산·대구) 지도 데이터. 세션/DB metrics의 '_local' → 샘플 폴백."""
    m = _resolved_metrics()
    if isinstance(m, dict) and isinstance(m.get("_local"), dict) and m["_local"]:
        return m["_local"]
    return _LOCAL_SAMPLE


def _render_map():
    g, t = fetch_region_levels()
    components.html(_map_component(_merged_regions(), g, t, _fetch_local()),
                    height=1240, scrolling=False)
