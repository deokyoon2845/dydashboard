"""부동산 오늘의 키워드 뷰 — 증시 키워드 탭과 동일 양식.

증시(modules/keywords_view.py)를 부동산 도메인으로 미러:
  - 카드 레이아웃·배지(카테고리/연속🔥/NEW)·중요도 막대·뉴스 링크는 동일.
  - '관련 종목 → 네이버 주가' 대신 '관련 지역(시군구·권역) → 네이버부동산'.
  - 카테고리: 정책 / 금리 / 공급 / 시황 / 지역.
  - 데이터: data/realestate_keywords_today.json (+ 날짜별 아카이브).
    엔진(engine/realestate_keywords.py)이 네이버 부동산 뉴스를 수집해 채운다.

다른 부동산 서브탭과 동일하게 accent-bar(전역 CSS) + st.title 로 연다.
부모 패널 첫 요소가 별도 CSS 블록이면 세로 간격이 벌어지므로,
CSS는 accent-bar와 한 블록으로 합쳐 주입한다(간격 일치).
"""

import html
import json
from datetime import date
from pathlib import Path
from urllib.parse import quote

import streamlit as st

RE_KW_PATH = Path("data/realestate_keywords_today.json")
RE_KW_ARCHIVE_DIR = Path("data/realestate_keywords_archive")

CAT_CLS = {"정책": "cat-policy", "금리": "cat-macro", "공급": "cat-sector",
           "시황": "cat-stock", "지역": "cat-region"}

_RE_KW_CSS = """
<style>
/* 2열 그리드 (데스크톱) → 좁아지면 1열 — 증시 키워드 탭과 동일 */
.rekw-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-top:6px;}
@media(max-width:680px){.rekw-grid{grid-template-columns:1fr;}}

.rekw-card{background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);border-radius:14px;
  padding:14px 15px;display:flex;flex-direction:column;gap:0;}
.rekw-head{display:flex;align-items:center;gap:8px;margin-bottom:7px;flex-wrap:wrap;}
.rekw-rank{font-family:'Fraunces','Noto Sans KR',Georgia,serif;font-size:18px;font-weight:600;
  color:var(--sage-deep,#7E9A83);min-width:20px;line-height:1;}
.rekw-kw{font-size:14.5px;font-weight:700;color:var(--ink,#34352f);flex:1;min-width:0;
  word-break:keep-all;line-height:1.35;}
.rekw-cat{font-size:10px;font-weight:700;padding:2px 7px;border-radius:5px;letter-spacing:.02em;flex:none;}
.cat-macro{background:#E6F0F6;color:#2C5F7C;}
.cat-sector{background:#EBF3EC;color:#4A6B4F;}
.cat-stock{background:#F3EEE6;color:#7C5F2C;}
.cat-policy{background:#F0E9F3;color:#6B4A7C;}
.cat-region{background:#EAF1EA;color:#3F6F49;}
.rekw-streak{font-size:9.5px;font-weight:700;color:#C2410C;background:#FDEEE3;padding:2px 6px;border-radius:5px;flex:none;}
.rekw-new{font-size:9.5px;font-weight:700;color:#0f6e56;background:#e1f5ee;padding:2px 6px;border-radius:5px;flex:none;}
.rekw-wbar{height:4px;border-radius:3px;background:var(--line,#ECEDE7);margin:0 0 9px;overflow:hidden;}
.rekw-wbar>span{display:block;height:100%;background:var(--sage,#A7BBA9);border-radius:3px;}
.rekw-tags{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:9px;}
.rekw-tag{font-size:11px;font-weight:600;text-decoration:none;background:var(--pill-bg,#F1F2EC);
  color:var(--pill-ink,#5d6258);border:1px solid var(--line,#ECEDE7);padding:2px 8px;border-radius:7px;}
.rekw-news{margin-top:auto;}
/* 뉴스 제목: 1줄 고정 + 말줄임 (카드 높이 균일) */
.rekw-news a{display:block;font-size:12px;line-height:1.5;color:var(--sage-deep,#7E9A83);
  text-decoration:none;margin-bottom:5px;padding-left:11px;position:relative;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.rekw-news a:before{content:"›";position:absolute;left:0;color:var(--muted,#9a9b92);}
.rekw-news a:hover{text-decoration:underline;}
.rekw-weak{font-size:10.5px;color:var(--muted,#9a9b92);margin-top:6px;}

/* ── 마이크로 인터랙션 (미니멀 미스트) ── */
@keyframes rekw-fade-up{from{opacity:0;transform:translateY(10px);}to{opacity:1;transform:translateY(0);}}
.rekw-card{animation:rekw-fade-up .5s cubic-bezier(.22,.61,.36,1) both;
  transition:transform .2s ease,box-shadow .2s ease,border-color .2s ease;}
.rekw-grid .rekw-card:nth-child(1){animation-delay:.02s;}
.rekw-grid .rekw-card:nth-child(2){animation-delay:.05s;}
.rekw-grid .rekw-card:nth-child(3){animation-delay:.08s;}
.rekw-grid .rekw-card:nth-child(4){animation-delay:.11s;}
.rekw-grid .rekw-card:nth-child(5){animation-delay:.14s;}
.rekw-grid .rekw-card:nth-child(6){animation-delay:.17s;}
.rekw-grid .rekw-card:nth-child(7){animation-delay:.20s;}
.rekw-grid .rekw-card:nth-child(8){animation-delay:.23s;}
.rekw-grid .rekw-card:nth-child(9){animation-delay:.26s;}
.rekw-grid .rekw-card:nth-child(10){animation-delay:.29s;}
.rekw-grid .rekw-card:nth-child(11){animation-delay:.32s;}
.rekw-grid .rekw-card:nth-child(12){animation-delay:.35s;}
.rekw-grid .rekw-card:nth-child(13){animation-delay:.38s;}
.rekw-grid .rekw-card:nth-child(14){animation-delay:.41s;}
.rekw-grid .rekw-card:nth-child(15){animation-delay:.44s;}
.rekw-card:hover{transform:translateY(-2px);box-shadow:0 6px 18px rgba(52,53,47,.08);
  border-color:var(--sage,#A7BBA9);}
@keyframes rekw-bar-grow{from{transform:scaleX(0);}to{transform:scaleX(1);}}
.rekw-wbar>span{transform-origin:left center;
  animation:rekw-bar-grow .8s cubic-bezier(.22,.61,.36,1) .25s both;}
.rekw-news a{transition:color .15s ease,padding-left .15s ease;}
.rekw-news a:hover{padding-left:14px;}
.rekw-tag{transition:transform .15s ease,box-shadow .15s ease,border-color .15s ease;}
.rekw-tag:hover{transform:translateY(-1px);box-shadow:0 2px 6px rgba(52,53,47,.08);
  border-color:var(--sage,#A7BBA9);}
@media(prefers-reduced-motion:reduce){
  .rekw-card,.rekw-wbar>span{animation:none !important;}
  .rekw-card,.rekw-news a,.rekw-tag{transition:none !important;}
}
</style>
"""


def _load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _archive_dates():
    if not RE_KW_ARCHIVE_DIR.exists():
        return []
    out = []
    for f in sorted(RE_KW_ARCHIVE_DIR.glob("*.json"), reverse=True):
        try:
            y, m, d = f.stem.split("-")
            out.append((date(int(y), int(m), int(d)), f))
        except ValueError:
            continue
    return out


def _naver_land_url(region: str) -> str:
    """지역명을 네이버부동산 검색으로 연결."""
    return "https://m.land.naver.com/search/result/" + quote(region)


def _region_html(regions):
    """관련 지역 pill — 이름 + 네이버부동산 링크."""
    parts = []
    for n in regions or []:
        n = (n or "").strip()
        if not n:
            continue
        parts.append(
            f'<a class="rekw-tag" href="{html.escape(_naver_land_url(n))}" '
            f'target="_blank" rel="noopener">{html.escape(n)}</a>'
        )
    return f'<div class="rekw-tags">{"".join(parts)}</div>' if parts else ""


def _render_items(items):
    cards = []
    for i, it in enumerate(items[:15], start=1):
        cat = it.get("category", "")
        kw = html.escape(it.get("keyword", ""))
        cat_html = (f'<span class="rekw-cat {CAT_CLS.get(cat, "cat-sector")}">{html.escape(cat)}</span>'
                    if cat else "")
        streak = it.get("streak", 1)
        streak_html = (f'<span class="rekw-streak">🔥 {streak}일째</span>'
                       if streak and streak >= 2 else "")
        new_html = '<span class="rekw-new">NEW</span>' if it.get("is_new") else ""

        weight = it.get("weight")
        wbar = ""
        if isinstance(weight, int):
            wbar = f'<div class="rekw-wbar"><span style="width:{weight*10}%"></span></div>'

        # 관련 지역(없으면 구버전 호환으로 stocks 키도 시도)
        regions = it.get("regions") or it.get("stocks") or []
        tags_html = _region_html(regions)

        news_list = it.get("news")
        if not news_list and it.get("news_url"):
            news_list = [{"title": it.get("news_title", ""), "url": it.get("news_url", "")}]
        news_html = ""
        n_news = len([n for n in (news_list or []) if n.get("url")])
        if news_list:
            links = "".join(
                f'<a href="{html.escape(n.get("url",""))}" target="_blank" rel="noopener">'
                f'{html.escape(n.get("title",""))} ↗</a>'
                for n in news_list[:2] if n.get("url"))
            news_html = f'<div class="rekw-news">{links}</div>'
        if n_news == 0:
            weak_html = ('<div class="rekw-weak">대표 기사 없음 — '
                         '상위 키워드와 겹치는 주제일 수 있어요</div>')
        elif n_news == 1:
            weak_html = '<div class="rekw-weak">근거 기사 1건 — 참고만 하세요</div>'
        else:
            weak_html = ""

        cards.append(
            f'<div class="rekw-card">'
            f'<div class="rekw-head">'
            f'<span class="rekw-rank">{i}</span>'
            f'<span class="rekw-kw">{kw}</span>'
            f'{cat_html}{new_html}{streak_html}</div>'
            f'{wbar}{tags_html}{news_html}{weak_html}</div>'
        )

    if not cards:
        st.caption("표시할 키워드가 없어요.")
        return
    st.markdown(f'<div class="rekw-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def render_realestate_keywords():
    # CSS는 accent-bar와 한 블록으로 합쳐 주입(별도 블록이 만드는 세로 간격 제거).
    st.markdown(_RE_KW_CSS + '<div class="accent-bar"></div>', unsafe_allow_html=True)
    st.title("부동산 키워드")

    if st.button("🔄 키워드 갱신", key="re_kw_refresh"):
        with st.spinner("네이버 부동산 뉴스 수집 → 키워드 추출 중..."):
            try:
                from engine.realestate_keywords import build_realestate_keywords
                res = build_realestate_keywords()
            except Exception as e:
                res = {"ok": False, "reason": str(e)}
        if res.get("ok"):
            st.success(f"키워드 {res.get('count', '')}개를 갱신했어요.")
            st.rerun()
        else:
            st.warning(f"갱신 실패 · {res.get('reason')}")

    # 아카이브 날짜 선택
    archive = _archive_dates()
    if archive:
        labels = {str(f): (f"{d:%Y-%m-%d}" + (" (오늘)" if d == date.today() else ""))
                  for d, f in archive}
        opts = [str(f) for _, f in archive]
        pick = st.selectbox("날짜 선택", options=opts,
                            format_func=lambda s: labels[s], key="re_kw_date")
        data = _load(Path(pick))
    else:
        data = _load(RE_KW_PATH)

    if not data or not data.get("items"):
        st.markdown(
            '<div class="empty"><div class="ico">🏠</div>'
            '<div class="msg">아직 부동산 키워드가 없어요</div>'
            '<div class="hint">"🔄 키워드 갱신"을 눌러 오늘의 부동산 키워드를 불러오세요</div></div>',
            unsafe_allow_html=True)
        return

    when = str(data.get("generated", ""))[:16].replace("T", " ")
    st.caption(f"기준: {when} · 네이버 부동산 뉴스 기반")

    _render_items(data["items"])
    st.caption("※ 키워드·지역·카테고리·중요도는 AI 추출, 링크는 네이버 뉴스 실제 기사. "
               "🔥 = 연속 등장 일수, NEW = 오늘 첫 등장, 막대 = 중요도, "
               "지역 클릭 시 네이버부동산. 뉴스는 카드당 2건 표시.")
