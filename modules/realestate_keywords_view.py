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
/* ── 데스크톱 2열 고정높이 카드, 모바일 1열 — 증시 키워드 탭과 동일 양식 ── */
.rekw-list{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:8px;}
@media(max-width:760px){.rekw-list{grid-template-columns:1fr;}}
.rekw-row{display:grid;grid-template-columns:44px 1fr;gap:13px;
  height:160px;overflow:hidden;
  background:#fff;border:.5px solid var(--line,#ECEDE7);border-radius:12px;
  padding:14px 16px;transition:border-color .18s ease,box-shadow .18s ease;}
@media(max-width:760px){.rekw-row{height:auto;min-height:120px;}}
.rekw-row:hover{border-color:var(--sage,#A7BBA9);box-shadow:0 2px 8px rgba(52,53,47,.06);}

.rekw-rank{display:flex;flex-direction:column;align-items:flex-end;min-width:0;padding-top:1px;}
.rekw-num{font-family:'Fraunces','Noto Sans KR',Georgia,serif;font-size:26px;font-weight:500;
  line-height:1;color:var(--sage-deep,#7E9A83);white-space:nowrap;
  font-variant-numeric:tabular-nums;}
.rekw-impbar{display:flex;gap:2px;justify-content:flex-end;margin-top:8px;}
.rekw-impbar i{width:5px;height:5px;border-radius:50%;background:var(--line,#ECEDE7);}
.rekw-impbar i.f{background:var(--sage,#A7BBA9);}

.rekw-main{min-width:0;}
.rekw-head{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap;margin-bottom:7px;}
.rekw-kw{font-size:18px;font-weight:700;color:var(--ink,#34352f);letter-spacing:-.01em;
  line-height:1.3;word-break:keep-all;}
.rekw-tagrow{display:inline-flex;gap:6px;align-items:center;flex-wrap:wrap;}
.rekw-cat{font-size:10px;font-weight:700;padding:2px 7px;border-radius:5px;letter-spacing:.02em;white-space:nowrap;}
.cat-macro{background:#E6F0F6;color:#2C5F7C;}
.cat-sector{background:#EBF3EC;color:#4A6B4F;}
.cat-stock{background:#F3EEE6;color:#7C5F2C;}
.cat-policy{background:#F0E9F3;color:#6B4A7C;}
.cat-region{background:#EAF1EA;color:#3F6F49;}
.rekw-streak{font-size:9.5px;font-weight:700;color:#C2410C;background:#FDEEE3;padding:2px 6px;border-radius:5px;white-space:nowrap;}
.rekw-new{font-size:9.5px;font-weight:800;color:#fff;background:var(--sage-deep,#7E9A83);
  padding:2px 7px;border-radius:5px;letter-spacing:.04em;white-space:nowrap;}

.rekw-tags{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 9px;}
.rekw-tag{font-size:11px;font-weight:600;text-decoration:none;background:var(--pill-bg,#F1F2EC);
  color:var(--pill-ink,#5d6258);border:1px solid var(--line,#ECEDE7);padding:2px 8px;border-radius:7px;}

.rekw-news a{display:block;font-size:12.5px;line-height:1.6;color:var(--sage-deep,#7E9A83);
  text-decoration:none;padding-left:13px;position:relative;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;}
.rekw-news a:before{content:"›";position:absolute;left:0;color:var(--muted,#9a9b92);}
.rekw-news a:hover{text-decoration:underline;}
.rekw-weak{font-size:10.5px;color:var(--muted,#9a9b92);margin-top:5px;}

@media(max-width:560px){
  .rekw-row{grid-template-columns:40px 1fr;gap:11px;}
  .rekw-num{font-size:23px;}
  .rekw-kw{font-size:16px;}
}

/* ── 마이크로 인터랙션 (미니멀 미스트) ── */
@keyframes rekw-fade-up{from{opacity:0;transform:translateY(8px);}to{opacity:1;transform:translateY(0);}}
.rekw-row{animation:rekw-fade-up .45s cubic-bezier(.22,.61,.36,1) both;}
.rekw-list .rekw-row:nth-child(1){animation-delay:.02s;}
.rekw-list .rekw-row:nth-child(2){animation-delay:.04s;}
.rekw-list .rekw-row:nth-child(3){animation-delay:.06s;}
.rekw-list .rekw-row:nth-child(4){animation-delay:.08s;}
.rekw-list .rekw-row:nth-child(5){animation-delay:.10s;}
.rekw-list .rekw-row:nth-child(6){animation-delay:.12s;}
.rekw-list .rekw-row:nth-child(7){animation-delay:.14s;}
.rekw-list .rekw-row:nth-child(8){animation-delay:.16s;}
.rekw-list .rekw-row:nth-child(9){animation-delay:.18s;}
.rekw-list .rekw-row:nth-child(10){animation-delay:.20s;}
.rekw-list .rekw-row:nth-child(11){animation-delay:.22s;}
.rekw-list .rekw-row:nth-child(12){animation-delay:.24s;}
.rekw-list .rekw-row:nth-child(13){animation-delay:.26s;}
.rekw-list .rekw-row:nth-child(14){animation-delay:.28s;}
.rekw-list .rekw-row:nth-child(15){animation-delay:.30s;}
.rekw-impbar i.f{animation:rekw-dot-in .5s ease both .25s;}
@keyframes rekw-dot-in{from{transform:scale(.4);opacity:.3;}to{transform:scale(1);opacity:1;}}
.rekw-news a{transition:color .15s ease,padding-left .15s ease;}
.rekw-news a:hover{padding-left:16px;}
.rekw-tag{transition:transform .15s ease,box-shadow .15s ease,border-color .15s ease;}
.rekw-tag:hover{transform:translateY(-1px);box-shadow:0 2px 6px rgba(52,53,47,.08);
  border-color:var(--sage,#A7BBA9);}
@media(prefers-reduced-motion:reduce){
  .rekw-row,.rekw-impbar i.f{animation:none !important;}
  .rekw-row,.rekw-news a,.rekw-tag{transition:none !important;}
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


# ── 키워드 소스: Supabase(누적) 우선, 미구성 시 파일 폴백 (증시 키워드와 동일 패턴) ──

def _kw_source() -> str:
    """'db' 또는 'file'. Supabase가 구성돼 있으면 누적 DB를 우선 사용."""
    try:
        from modules import db
        if db.supabase_configured():
            return "db"
    except Exception:
        pass
    return "file"


def _kw_dates():
    """[(날짜문자열, picker값)] 최신순. picker값은 DB면 'YYYY-MM-DD', 파일이면 경로문자열."""
    if _kw_source() == "db":
        try:
            from modules import db
            return [(d, d) for d in db.list_realestate_keyword_dates()]
        except Exception:
            pass
    return [(f"{d:%Y-%m-%d}", str(f)) for d, f in _archive_dates()]


def _kw_load(picker_value):
    """picker값(날짜문자열 또는 파일경로)으로 키워드 dict({generated, items, ...}) 로드."""
    if _kw_source() == "db":
        try:
            from modules import db
            return (db.load_realestate_keywords_by_date(picker_value) if picker_value
                    else db.load_realestate_keywords_latest())
        except Exception:
            pass
    if picker_value and Path(picker_value).exists():
        return _load(Path(picker_value))
    return _load(RE_KW_PATH)


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
    rows = []
    for i, it in enumerate(items[:15], start=1):
        cat = it.get("category", "")
        kw = html.escape(it.get("keyword", ""))
        cat_html = (f'<span class="rekw-cat {CAT_CLS.get(cat, "cat-sector")}">{html.escape(cat)}</span>'
                    if cat else "")

        # NEW(오늘 처음) 우선, 아니면 연속 등장(streak)
        is_new = bool(it.get("is_new"))
        streak = it.get("streak", 1)
        if is_new:
            badge_html = '<span class="rekw-new">NEW</span>'
        elif streak and streak >= 2:
            badge_html = f'<span class="rekw-streak">🔥 {streak}일째</span>'
        else:
            badge_html = ""

        # 중요도(weight 1~10) → 5칸 도트
        weight = it.get("weight")
        if isinstance(weight, int):
            filled = max(0, min(5, round(weight / 2)))
            dots = "".join(f'<i class="{"f" if k < filled else ""}"></i>' for k in range(5))
            impbar = f'<div class="rekw-impbar">{dots}</div>'
        else:
            impbar = ""

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

        rows.append(
            f'<div class="rekw-row">'
            f'<div class="rekw-rank"><span class="rekw-num">{i}</span>{impbar}</div>'
            f'<div class="rekw-main">'
            f'<div class="rekw-head"><span class="rekw-kw">{kw}</span>'
            f'<span class="rekw-tagrow">{cat_html}{badge_html}</span></div>'
            f'{tags_html}{news_html}{weak_html}'
            f'</div></div>'
        )

    if not rows:
        st.caption("표시할 키워드가 없어요.")
        return
    st.markdown(f'<div class="rekw-list">{"".join(rows)}</div>', unsafe_allow_html=True)


def render_realestate_keywords():
    # 표준 크롬(tab_header) — 탭 CSS를 액센트 바와 한 블록으로 합쳐 주입(간격 일치).
    from modules.ui import tab_header
    tab_header("부동산 키워드", css=_RE_KW_CSS)

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

    # 날짜 선택 — Supabase 누적 데이터 우선(없으면 파일 아카이브)
    dates = _kw_dates()
    data = None
    if dates:
        today_s = date.today().strftime("%Y-%m-%d")
        labels = {pv: (ds + (" (오늘)" if ds == today_s else "")) for ds, pv in dates}
        opts = [pv for _, pv in dates]
        pick = st.selectbox("날짜 선택", options=opts,
                            format_func=lambda s: labels.get(s, s), key="re_kw_date")
        data = _kw_load(pick)
    else:
        data = _kw_load(None)

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
               "🔥 = 연속 등장 일수, NEW = 오늘 첫 등장, 점 = 중요도, "
               "지역 클릭 시 네이버부동산. 뉴스는 키워드당 2건 표시.")
