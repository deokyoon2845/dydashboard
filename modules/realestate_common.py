"""부동산 공용 계층 — 스냅샷 로더 · 공통 스타일 · 네이버 링크 · 인증/수집 컨트롤.

부동산 탭 모듈들(realestate_cycle/map/deals/subs)이 공유하는 최소 집합만 둔다.
이 모듈은 다른 부동산 탭 모듈을 import하지 않는다(순환 참조 방지 — 의존 방향은
항상 탭 모듈 → common/geo 단방향).
"""

import streamlit as st


# ── 데이터 훅 (세션 → Supabase 스냅샷 → 내장 샘플 폴백) ──────────
@st.cache_data(ttl=1800, show_spinner=False)
def _load_re_snapshot():
    """Supabase에 저장된 최신 부동산 스냅샷. 미설정/실패/테이블없음이면 None. (30분 캐시)"""
    try:
        from modules.db import supabase_configured, load_realestate
        if not supabase_configured():
            return None
        return load_realestate()
    except Exception:
        return None


@st.cache_data(ttl=1800, show_spinner=False)
def _load_recent_re_snapshots(days: int = 7):
    """최근 N일 부동산 스냅샷 행들(최신순). 주간 뷰용. 실패/미설정 → None. (30분 캐시)"""
    try:
        from modules.db import supabase_configured, load_recent_realestate
        if not supabase_configured():
            return None
        return load_recent_realestate(days)
    except Exception:
        return None


def _resolved_metrics():
    """지역 지표: 세션(직전 갱신) → DB 스냅샷 → None(샘플)."""
    m = st.session_state.get("re_metrics")
    if m:
        return m
    snap = _load_re_snapshot()
    return (snap or {}).get("metrics") if snap else None


def fetch_region_metrics():
    """지역명 -> {'mm','js','v','vc','jr'}. 세션→DB 스냅샷, 둘 다 없으면 None(샘플)."""
    return _resolved_metrics()


# ── 지표·거래 카드 CSS (부모 문서 · 전역 변수 사용) ──────────────
_RE_CSS = """
<style>
.re-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:12px;margin-top:6px;}
.re-card{background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);border-radius:14px;padding:13px 15px;
  transition:transform .2s ease,box-shadow .2s ease,border-color .2s ease;}
.re-card:hover{transform:translateY(-2px);box-shadow:0 6px 18px rgba(52,53,47,.08);border-color:var(--sage,#A7BBA9);}
.re-lab{font-size:12px;font-weight:600;color:var(--muted,#9a9b92);}
.re-val{font-size:22px;font-weight:700;color:var(--ink,#34352f);margin:2px 0 6px;letter-spacing:-.02em;}
.re-spark{width:100%;height:46px;display:block;}
.re-note{font-size:11px;color:var(--muted,#9a9b92);margin-top:6px;}
.re-anom{display:flex;align-items:center;gap:12px;background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);
  border-radius:12px;padding:10px 13px;margin-bottom:8px;
  transition:transform .15s ease,box-shadow .15s ease,border-color .15s ease;}
.re-anom:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(52,53,47,.07);border-color:var(--sage,#A7BBA9);}
.re-anom.excl{opacity:.5;}
.re-apt{font-weight:700;color:var(--ink,#34352f);}
.re-sub{font-size:12px;color:var(--muted,#9a9b92);}
.re-price{font-weight:700;color:var(--ink,#34352f);text-align:right;}
.re-chg{font-size:12px;font-weight:700;text-align:right;}
.re-chg.up{color:var(--up,#B65F5A);} .re-chg.dn{color:var(--down,#5A7CA0);}
.re-chg.lv1{font-size:13px;}
.re-chg.lv2{font-size:15px;letter-spacing:-.01em;}
.re-apt a{color:inherit;text-decoration:none;border-bottom:1px dashed #D6D8CF;}
.re-apt a:hover{border-bottom-color:var(--sage,#A7BBA9);}
.re-statband{display:flex;flex-wrap:wrap;gap:8px;margin:2px 0 12px;}
.re-stat{background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);border-radius:10px;
  padding:7px 12px;font-size:12.5px;color:var(--ink,#34352f);}
.re-stat b{font-size:16px;font-weight:800;margin-right:4px;letter-spacing:-.02em;}
/* 상승압력 게이지 */
.re-press{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 12px;font-size:11.5px;color:var(--muted,#9a9b92);}
.re-press .lab b{color:var(--ink,#34352f);font-weight:800;}
.re-press .bar{flex:1;min-width:120px;height:9px;border-radius:5px;overflow:hidden;
  background:linear-gradient(90deg,#E6F1FB,#EFEEE9 50%,#FCEBEB);position:relative;}
.re-press .bar i{display:block;height:100%;background:#B65F5A;opacity:.55;}
.re-press .nums b{font-weight:800;}
/* 주목 단지 보드 */
.re-hotwrap{display:flex;flex-direction:column;gap:7px;margin-bottom:6px;}
.re-hot{display:flex;align-items:center;gap:11px;background:var(--card,#fff);
  border:1px solid var(--line,#ECEDE7);border-radius:12px;padding:10px 13px;}
.re-hot-rk{flex:none;width:22px;height:22px;border-radius:7px;background:#F2F5F0;color:#5d6258;
  font-size:12px;font-weight:800;display:flex;align-items:center;justify-content:center;}
.re-hot-r{text-align:right;min-width:70px;}
.re-hot-si{flex:none;width:78px;display:flex;align-items:center;gap:6px;}
.re-hot-si .bar{flex:1;height:8px;border-radius:4px;background:#EEF1EC;overflow:hidden;}
.re-hot-si .bar i{display:block;height:100%;background:var(--sage-deep,#7E9A83);}
.re-hot-si .v{font-size:11px;font-weight:800;color:#5d6258;width:22px;text-align:right;}
.re-hot-si.dim{color:#C4C6BD;font-size:12px;justify-content:center;}
/* 주목 단지 카드 (59/84·세대수·시공사·소재지·지도) */
.re-hcwrap{display:flex;flex-direction:column;gap:8px;margin-bottom:6px;}
.re-hc{display:flex;align-items:stretch;gap:11px;background:var(--card,#fff);
  border:1px solid var(--line,#ECEDE7);border-radius:14px;padding:12px 14px;}
.re-hc-rk{flex:none;width:23px;height:23px;border-radius:7px;background:#F2F5F0;color:#5d6258;
  font-size:12px;font-weight:800;display:flex;align-items:center;justify-content:center;margin-top:1px;}
.re-hc-main{flex:1;min-width:0;}
.re-hc.has-chart .re-hc-main{flex:0 1 274px;}
/* 대형 실거래 차트(우측) — 점 1개=실거래 1건 · 평형별 색·연결선 */
.re-hc-chart{flex:1;min-width:250px;display:flex;flex-direction:column;justify-content:center;}
.re-hc-chart svg{width:100%;height:auto;display:block;}
.re-hc-leg{display:flex;gap:12px;justify-content:flex-end;font-size:10px;font-weight:700;
  color:var(--muted,#9a9b92);margin-bottom:1px;}
.re-hc-leg i{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:4px;}
.re-hc-note{font-size:9.5px;color:#b6b7ae;text-align:right;margin-top:2px;}
.re-hc-top{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;}
.re-hc-nm{font-size:14px;font-weight:800;color:var(--ink,#34352f);}
.re-hc-chg{font-size:12px;font-weight:800;}
.re-hc-chg.up{color:var(--up,#B65F5A);} .re-hc-chg.dn{color:var(--down,#5A7CA0);}
.re-hc-meta{font-size:11.5px;color:var(--muted,#9a9b92);margin-top:2px;}
.re-hc-stat{font-size:11.5px;color:var(--muted,#9a9b92);margin-top:3px;}
.re-hc-stat .up{color:var(--up,#B65F5A);} .re-hc-stat .dn{color:var(--down,#5A7CA0);}
.re-hc-stat .mut{color:#6f7068;} .re-hc-stat b{font-weight:800;}
.re-hc-prices{display:flex;align-items:center;gap:7px;margin-top:8px;flex-wrap:wrap;}
.re-hc-spk{display:inline-flex;align-items:center;gap:6px;margin-left:2px;}
.re-hc-spk .lab{font-size:9.5px;font-weight:700;color:#b3b4ab;}
.re-hc-pp{font-size:12.5px;font-weight:800;color:var(--ink,#34352f);background:#F7F8F4;
  border:1px solid var(--line,#ECEDE7);border-radius:8px;padding:4px 10px;}
.re-hc-pp i{font-style:normal;font-weight:700;color:var(--muted,#9a9b92);font-size:11px;margin-right:5px;}
.re-hc-pp.dim{color:#C4C6BD;background:#FAFAF7;} .re-hc-pp.dim i{color:#C4C6BD;}
.re-hc-jbox{display:flex;align-items:center;gap:11px;margin-top:9px;}
.re-hc-jg{flex:1;min-width:0;max-width:210px;}
.re-hc-jlab{display:flex;justify-content:space-between;font-size:10.5px;font-weight:700;
  color:var(--muted,#9a9b92);margin-bottom:4px;}
.re-hc-jlab b{color:var(--sage-deep,#7E9A83);font-weight:800;}
.re-hc-jbar{height:7px;border-radius:4px;background:#EBECE6;overflow:hidden;}
.re-hc-jbar i{display:block;height:100%;background:var(--sage,#A7BBA9);}
.re-hc-gap{font-size:12px;font-weight:600;color:#6f7068;white-space:nowrap;}
.re-hc-gap b{font-weight:800;color:var(--ink,#34352f);font-size:13px;}
.re-hc-map{flex:none;align-self:center;font-size:11.5px;font-weight:700;color:var(--sage-deep,#7E9A83);
  border:1px solid var(--line2,#DEDED7);border-radius:9px;padding:7px 11px;text-decoration:none;
  white-space:nowrap;transition:background .15s ease,border-color .15s ease;}
.re-hc-map:hover{background:#EEF1EC;border-color:var(--sage,#A7BBA9);}
@media(max-width:680px){.re-hc{flex-wrap:wrap;} .re-hc-map{margin-left:34px;margin-top:2px;}
  .re-hc.has-chart .re-hc-main{flex:1 1 calc(100% - 80px);}
  .re-hc-chart{flex:1 1 100%;order:5;margin-top:4px;}}
/* 가격지수 동향(연속/26년초대비) 섹션 */
.re-strk-sec{font-size:12px;font-weight:700;color:var(--ink,#34352f);margin:2px 2px 9px;letter-spacing:.02em;}
.re-strk-sec span{font-weight:500;color:var(--muted,#9a9b92);margin-left:6px;font-size:11px;}
.re-strk{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin:2px 0 16px;}
.re-strk-c{background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);border-radius:12px;padding:10px 12px;}
.re-strk-rg{font-size:13px;font-weight:800;color:var(--ink,#34352f);margin-bottom:5px;}
.re-strk-row{display:flex;align-items:center;gap:7px;font-size:11.5px;margin-top:4px;}
.re-strk-row .t{color:var(--muted,#9a9b92);width:26px;font-weight:600;}
.re-strk-bdg{font-weight:800;font-size:11px;border-radius:6px;padding:1px 7px;}
.re-strk-bdg.up{background:#FBEDEC;color:var(--up,#B65F5A);} .re-strk-bdg.dn{background:#EAF0F5;color:var(--down,#5A7CA0);} .re-strk-bdg.fl{background:#F0F1EC;color:var(--muted,#9a9b92);}
.re-strk-ytd{font-weight:800;margin-left:auto;} .re-strk-ytd.up{color:var(--up,#B65F5A);} .re-strk-ytd.dn{color:var(--down,#5A7CA0);} .re-strk-ytd.fl{color:var(--muted,#9a9b92);}
@media(max-width:680px){.re-strk{grid-template-columns:repeat(2,1fr);}}
.re-chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px;}
.re-chip{font-size:12px;color:var(--pill-ink,#5d6258);background:var(--pill-bg,#F1F2EC);
  border:1px solid var(--line,#ECEDE7);border-radius:999px;padding:4px 12px;}
.re-chip.on{background:var(--sage-deep,#7E9A83);color:#fff;border-color:var(--sage-deep,#7E9A83);}
.re-phase{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;background:var(--card,#fff);
  border:1px solid var(--line,#ECEDE7);border-radius:12px;padding:11px 15px;margin:2px 0 14px;}
.re-phase b{font-size:12px;color:var(--muted,#9a9b92);font-weight:600;margin-right:2px;}
.re-phase .seg{font-size:13px;font-weight:700;color:var(--ink,#34352f);}
.re-grp{font-size:12px;font-weight:700;color:var(--ink,#34352f);margin:16px 0 8px;letter-spacing:.02em;
  border-left:3px solid #B08268;padding-left:9px;}  /* 섹션 액센트(클레이) — A안 목업 '카드 악센트가 섹션색을 따라감' */
.re-grp .sub{font-weight:500;color:var(--muted,#9a9b92);font-size:11px;margin-left:6px;}
.re-delta{font-size:11px;font-weight:700;margin-left:7px;}
.re-delta.up{color:var(--up,#B65F5A);} .re-delta.dn{color:var(--down,#5A7CA0);} .re-delta.fl{color:var(--muted,#9a9b92);}
.re-base{font-size:10.5px;font-weight:500;color:var(--muted,#9a9b92);margin-left:6px;}
.re-sub-card{display:flex;align-items:flex-start;gap:11px;background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);
  border-radius:12px;padding:11px 14px;margin-bottom:8px;text-decoration:none;color:inherit;cursor:pointer;
  transition:transform .15s ease,box-shadow .15s ease,border-color .15s ease;}
.re-sub-card:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(52,53,47,.07);border-color:var(--sage,#A7BBA9);}
.re-sub-go{align-self:center;margin-left:8px;color:#CFD1C8;font-size:13px;font-weight:800;flex:none;
  transition:color .15s ease,transform .15s ease;}
.re-sub-card:hover .re-sub-go{color:var(--sage-deep,#7E9A83);transform:translateX(2px);}
.re-sub-bdg{font-size:10.5px;font-weight:700;padding:2px 9px;border-radius:6px;flex:none;margin-top:1px;}
.re-sub-nm{font-weight:700;color:var(--ink,#34352f);}
.re-sub-meta{font-size:12px;color:var(--muted,#9a9b92);margin-top:2px;}
.re-sub-r{margin-left:auto;text-align:right;font-size:11.5px;color:var(--muted,#9a9b92);white-space:nowrap;padding-left:10px;}
.re-sub-r b{display:block;color:var(--ink,#34352f);font-size:12.5px;margin-bottom:1px;}
.re-hl-sec{font-size:12px;font-weight:700;color:var(--ink,#34352f);margin:6px 2px 8px;letter-spacing:.02em;}
.re-hl-sec span{font-weight:500;color:var(--muted,#9a9b92);margin-left:6px;}
.re-hl{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:2px 0 14px;}
.re-hl-card{position:relative;background:linear-gradient(180deg,#FBF6EE,#fff);border:1px solid #EBE2D2;
  border-radius:14px;padding:12px 14px;display:block;text-decoration:none;color:inherit;cursor:pointer;
  transition:transform .15s ease,box-shadow .15s ease,border-color .15s ease;}
.re-hl-card:hover{transform:translateY(-2px);box-shadow:0 6px 18px rgba(138,109,59,.13);border-color:#D8C49A;}
.re-sub-card,.re-sub-card:link,.re-sub-card:visited,.re-hl-card,.re-hl-card:link,.re-hl-card:visited{color:var(--ink,#34352f) !important;text-decoration:none !important;}
.re-sub-card *,.re-hl-card *{text-decoration:none !important;}
.re-hl-go{position:absolute;right:12px;bottom:11px;color:#C9B78F;font-size:13px;font-weight:800;
  transition:color .15s ease,transform .15s ease;}
.re-hl-card:hover .re-hl-go{color:#8A6D3B;transform:translateX(2px);}
.re-hl-dday{position:absolute;top:11px;right:12px;background:var(--up,#B65F5A);color:#fff;
  font-size:11px;font-weight:800;border-radius:7px;padding:2px 8px;}
.re-hl-nm{font-size:14px;font-weight:800;color:var(--ink,#34352f);margin-bottom:2px;padding-right:62px;}
.re-hl-meta{font-size:11.5px;color:var(--muted,#9a9b92);line-height:1.5;}
.re-hl-when{font-size:12px;font-weight:700;color:#8A6D3B;margin-top:7px;}
.re-tl{display:flex;overflow-x:auto;background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);
  border-radius:14px;padding:4px 2px;margin:2px 0 14px;}
.re-tl-col{flex:1;min-width:80px;text-align:center;padding:9px 6px;border-right:1px dashed var(--line,#ECEDE7);}
.re-tl-col:last-child{border-right:none;}
.re-tl-d{font-size:11px;color:var(--muted,#9a9b92);font-weight:700;}
.re-tl-dot{margin:7px auto 5px;width:8px;height:8px;border-radius:50%;background:var(--line2,#DEDED7);}
.re-tl-dot.s{background:var(--sage-deep,#7E9A83);} .re-tl-dot.e{background:var(--up,#B65F5A);}
.re-tl-c{font-size:10.5px;color:var(--ink,#34352f);line-height:1.3;}
.re-sub-when{font-size:11.5px;color:var(--muted,#9a9b92);margin-top:3px;}
.re-sub-acts{display:flex;flex-direction:column;gap:5px;flex:none;align-self:center;padding-left:8px;}
.re-hl-acts{display:flex;gap:6px;margin-top:9px;}
.re-go-btn{font-size:11px;font-weight:700;color:var(--sage-deep,#7E9A83);border:1px solid var(--line2,#DEDED7);
  border-radius:8px;padding:5px 10px;text-decoration:none !important;white-space:nowrap;background:var(--card,#fff);
  transition:background .15s ease,border-color .15s ease;display:inline-block;text-align:center;}
.re-go-btn:hover{background:#EEF1EC;border-color:var(--sage,#A7BBA9);}
.re-go-btn.map{color:#5d6258;}
.re-go-btn.gold{border-color:#E2D3B0;color:#8A6D3B;background:rgba(255,255,255,.65);}
.re-go-btn.gold:hover{background:#fff;border-color:#D8C49A;}
.nv{display:inline-flex;align-items:center;justify-content:center;width:15px;height:15px;flex:none;
  border-radius:4px;background:#03C75A;color:#fff;font-size:10px;font-weight:900;
  text-decoration:none;margin-left:5px;vertical-align:1px;line-height:1;}
.nv:hover{filter:brightness(.92);}
@media(max-width:680px){.re-hl{grid-template-columns:1fr;}}
/* 주목 지역 밴드 (지도 위 · 5개 권역 구 통합 · 월간 전월대비) */
.re-wb-sec{font-size:12px;font-weight:700;color:var(--ink,#34352f);margin:2px 2px 9px;letter-spacing:.02em;}
.re-wb-sec span{font-weight:500;color:var(--muted,#9a9b92);margin-left:6px;font-size:11px;}
.re-wb{display:grid;grid-template-columns:repeat(auto-fit,minmax(205px,1fr));gap:9px;margin:2px 0 6px;}
.re-wb-c{background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);border-radius:12px;padding:10px 12px;}
.re-wb-h{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--muted,#9a9b92);font-weight:600;margin-bottom:7px;}
.re-wb-h .dot{width:8px;height:8px;border-radius:2px;flex:none;}
.re-wb-h .sub{font-weight:500;font-size:9.5px;}
.re-wb-r{display:flex;align-items:baseline;justify-content:space-between;gap:8px;margin-top:4px;}
.re-wb-r.lead{margin-top:0;}
.re-wb-r .rg{color:var(--ink,#34352f);font-size:12px;font-weight:700;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.re-wb-r .rg em{font-style:normal;font-weight:500;color:var(--muted,#9a9b92);margin-right:3px;}
.re-wb-r.sub2 .rg{font-size:11.5px;font-weight:500;color:#5b5c54;}
.re-wb-r .v{font-weight:800;font-size:14px;letter-spacing:-.01em;flex:none;}
.re-wb-r.sub2 .v{font-size:11.5px;font-weight:700;}
.re-wb-r .v.up{color:var(--up,#B65F5A);} .re-wb-r .v.dn{color:var(--down,#5A7CA0);} .re-wb-r .v.sg{color:var(--sage-deep,#7E9A83);}
.re-wb-pill{font-size:10px;font-weight:800;padding:1px 7px;border-radius:999px;flex:none;}
.re-wb-pill.up{background:#FBEDEC;color:var(--up,#B65F5A);} .re-wb-pill.dn{background:#EAF0F5;color:var(--down,#5A7CA0);}
.re-wb-gap{font-size:9.5px;color:var(--muted,#9a9b92);margin:1px 0 3px;}
.re-wb-foot{font-size:10px;color:var(--muted,#9a9b92);margin:0 2px 16px;line-height:1.5;}
@media(max-width:680px){.re-wb{grid-template-columns:repeat(2,1fr);}}
</style>
"""


def _naver_land_url(query):
    """단지명(+동/구) → 네이버 통합검색(부동산 시세 카드 상단 노출). 퍼지라 약식명도 도달.
       (complexNo 딥링크 리졸브 전/실패 시의 폴백 · 키 불필요.)"""
    from urllib.parse import quote
    return "https://search.naver.com/search.naver?query=" + quote((query or "").strip())


def _naver_n(query):
    """단지명(+동/구) 옆 네이버 'N' 아이콘 링크 — 주도주 탭과 동일 스타일(.nv) · 통합검색."""
    import html as _html
    return (f'<a class="nv" href="{_html.escape(_naver_land_url(query))}" target="_blank" '
            f'rel="noopener" title="네이버 검색에서 보기">N</a>')


def _run_collection():
    """뷰어 '최신 데이터 불러오기' — 라이브 API를 호출하지 않고 DB 스냅샷만 다시 읽는다.

    KB(data-api.kbland.kr)는 Streamlit Cloud IP에서 차단/타임아웃되고, 국토부 대량 호출도
    뷰어에서는 불안정하다(엔진-우선 원칙). 그래서 실제 수집은 매일 아침 GitHub Actions가
    수행해 Supabase(realestate_snapshots)에 채우고, 뷰어는 그 최신 행을 읽기만 한다.
    이 함수는 스냅샷 캐시를 비워 '방금 아침/수동 워크플로가 쓴 최신본'을 즉시 반영한다.
    (예외를 던지지 않는다 — 에러 배너 대신 항상 DB/샘플을 보여준다.)"""
    try:
        _load_re_snapshot.clear()      # 스냅샷 캐시 무효화 → 다음 읽기에서 DB 최신본 로드
    except Exception:
        pass
    # 직전 세션에 남아 있던 라이브 갱신값을 지워 DB 스냅샷이 그대로 보이게 한다.
    for k in ("re_metrics", "re_anoms", "re_subs", "re_indseries", "re_asof"):
        st.session_state.pop(k, None)


def _re_authed():
    """소유자 인증 여부만 판단 — 위젯을 그리지 않는다(여러 탭에서 안전하게 호출).
       APP_PASSWORD 미설정이면 누구나 가능. 리포트 잠금(gen_authed)을 공유한다."""
    try:
        pw = st.secrets.get("APP_PASSWORD", "")
    except Exception:
        pw = ""
    return (not pw) or bool(st.session_state.get("gen_authed"))


def _re_render_lock_gate():
    """비밀번호 잠금 UI를 '한 번만' 렌더(지도 탭 전용). 이미 인증됐으면 아무것도 안 그린다.
       위젯(key=re_pw/re_unlock)이 여러 탭에서 중복 생성되던 DuplicateElementKey를 방지."""
    if _re_authed():
        return
    try:
        pw = st.secrets.get("APP_PASSWORD", "")
    except Exception:
        pw = ""
    with st.expander("🔒 실거래 갱신은 소유자 전용이에요", expanded=False):
        st.caption("둘러보기는 자유롭고, 갱신(공공API 대량 호출)만 소유자 비밀번호가 필요해요.")
        p = st.text_input("비밀번호", type="password", key="re_pw")
        if st.button("잠금 해제", key="re_unlock"):
            if p == pw:
                st.session_state["gen_authed"] = True
                st.success("잠금 해제됐어요.")
                st.rerun()
            else:
                st.error("비밀번호가 일치하지 않아요.")


def _re_collect_asof():
    """부동산 스냅샷 수집 기준시각(asof · KST 문자열). 세션 → 스냅샷. 없으면 None."""
    a = st.session_state.get("re_asof")
    if not a:
        snap = _load_re_snapshot()
        a = (snap or {}).get("asof") if snap else None
    return a


def _render_collect_controls():
    """지도 탭 상단 — 데이터 기준시각 캡션만 렌더.
       (예전엔 갱신/진단 버튼도 있었으나 엔진-우선 원칙에 따라 제거 → 아래 참고.)"""
    asof = _re_collect_asof()
    if asof:
        st.caption(f"수도권·광역시 아파트 · 매매·전세=KB 월간 가격지수, 거래=주간 실거래 · 기준 {asof} KST · 매일 아침 자동 갱신 · 최근·다음 시각은 하단 🕐 자동 갱신 현황")
    else:
        st.caption("수도권 아파트 · 현재 샘플 — 매일 아침 자동 수집(KB 가격지수·실거래) 후 "
                   "실데이터로 채워집니다.")

    # 갱신은 매일 아침 GitHub Actions가 전담(엔진-우선)하므로, 뷰어에서 수동으로
    # 부를 이유가 사라졌다 → '최신 데이터 불러오기'(스냅샷 캐시만 비우던 버튼)와
    # '연결 진단'(뷰어에서 data.go.kr 라이브 콜 1회 · 엔진-우선 위반)을 제거했다.
    # 기준시각 캡션은 유용하므로 위에 그대로 남긴다. 잠금 게이트도 갱신 버튼이
    # 사라져 불필요 → 상단이 깔끔해진다.
    #   · _run_collection() / _re_render_lock_gate() / diagnose() 는 재사용 여지가
    #     있어 정의는 보존(호출부만 제거).
    return
