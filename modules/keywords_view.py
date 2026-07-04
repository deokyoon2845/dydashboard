"""오늘의 키워드 뷰 — 카테고리·중요도·연속배지·워치리스트★·인라인종목·아카이브.

데스크톱: 2열 고정높이 카드 (TOP15) / 모바일: 1열로 자동 전환.
카드 높이를 160px로 고정해 정렬을 맞추고, 넘치는 내용은 숨김(overflow) 처리.
넘버링 숫자는 .kw-num span(nowrap)으로 분리해 두 자리(10~15)도 줄바꿈되지 않음.
"""

import html
import json
from datetime import date
from pathlib import Path

import streamlit as st

from modules.stocks import naver_stock_search_url

KW_PATH = Path("data/keywords_today.json")
KW_ARCHIVE_DIR = Path("data/keywords_archive")

CAT_CLS = {"거시": "cat-macro", "섹터": "cat-sector", "종목": "cat-stock", "정책": "cat-policy"}

_KW_CSS = """
<style>
/* ── A안: 에디토리얼 인덱스 — 데스크톱 2열 고정높이 카드, 모바일 1열 ── */
.kw-list{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:8px;}
@media(max-width:760px){.kw-list{grid-template-columns:1fr;}}
.kw-row{display:grid;grid-template-columns:44px 1fr;gap:13px;
  height:168px;overflow:hidden;
  background:#fff;border:1px solid var(--line,#ECEDE7);border-radius:12px;
  padding:14px 16px;transition:border-color .18s ease,box-shadow .18s ease;}
@media(max-width:760px){.kw-row{height:auto;min-height:120px;}}
.kw-row:hover{border-color:var(--sage,#A7BBA9);box-shadow:0 2px 8px rgba(52,53,47,.06);}
.kw-row.kw-rowwatch{border-color:#D9A93C;
  background:linear-gradient(180deg,rgba(217,169,60,.05),transparent 60%);}
.kw-row.kw-rowwatch:hover{box-shadow:0 2px 8px rgba(217,169,60,.14);}

.kw-rank{display:flex;flex-direction:column;align-items:flex-end;min-width:0;padding-top:1px;}
.kw-num{font-family:'Fraunces','Noto Sans KR',Georgia,serif;font-size:26px;font-weight:500;
  line-height:1;color:var(--sage-deep,#7E9A83);white-space:nowrap;
  font-variant-numeric:tabular-nums;}
.kw-impbar{display:flex;gap:2px;justify-content:flex-end;margin-top:8px;}
.kw-impbar i{width:5px;height:5px;border-radius:50%;background:var(--line,#ECEDE7);}
.kw-impbar i.f{background:var(--sage,#A7BBA9);}

.kw-main{min-width:0;}
.kw-head{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;margin-bottom:7px;}
.kw-kw{font-size:17px;font-weight:700;color:var(--ink,#34352f);letter-spacing:-.01em;
  line-height:1.3;word-break:keep-all;}
.kw-tags{display:inline-flex;gap:6px;align-items:center;flex-wrap:wrap;}
.kw-cat{font-size:10px;font-weight:700;padding:2px 7px;border-radius:5px;letter-spacing:.02em;white-space:nowrap;}
.cat-macro{background:#E6F0F6;color:#2C5F7C;}
.cat-sector{background:#EBF3EC;color:#4A6B4F;}
.cat-stock{background:#F3EEE6;color:#7C5F2C;}
.cat-policy{background:#F0E9F3;color:#6B4A7C;}
.kw-streak{font-size:9.5px;font-weight:700;color:#C2410C;background:#FDEEE3;padding:2px 6px;border-radius:5px;white-space:nowrap;}
.kw-new{font-size:9.5px;font-weight:800;color:#fff;background:var(--sage-deep,#7E9A83);
  padding:2px 7px;border-radius:5px;letter-spacing:.04em;white-space:nowrap;}
.kw-watch{font-size:12px;}

.kw-stocks{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 9px;}
.kw-stkwrap{display:inline-flex;align-items:center;}
.nv{display:inline-flex;align-items:center;justify-content:center;width:15px;height:15px;flex:none;
  border-radius:4px;background:#03C75A;color:#fff;font-size:10px;font-weight:900;
  text-decoration:none;margin-left:5px;vertical-align:1px;line-height:1;}
.nv:hover{filter:brightness(.92);}
.kw-stk{font-size:11px;font-weight:600;text-decoration:none;background:var(--pill-bg,#F1F2EC);
  color:var(--pill-ink,#5d6258);border:1px solid var(--line,#ECEDE7);padding:2px 8px;border-radius:7px;}
.kw-stk.kw-stk-watch{background:#FBF6EA;color:#7C5F2C;border-color:#D9A93C;}

.kw-news a{display:block;font-size:12.5px;line-height:1.65;color:var(--sage-deep,#7E9A83);
  text-decoration:none;padding-left:13px;position:relative;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;}
.kw-news a:before{content:"›";position:absolute;left:0;color:var(--muted,#9a9b92);}
.kw-news a:hover{text-decoration:underline;}
.kw-weak{font-size:10.5px;color:var(--muted,#9a9b92);margin-top:5px;}

@media(max-width:560px){
  .kw-row{grid-template-columns:40px 1fr;gap:11px;}
  .kw-num{font-size:23px;}
  .kw-kw{font-size:16px;}
}

/* ── 마이크로 인터랙션 (미니멀 미스트) ── */
@keyframes kw-fade-up{from{opacity:0;transform:translateY(8px);}to{opacity:1;transform:translateY(0);}}
.kw-row{animation:kw-fade-up .45s cubic-bezier(.22,.61,.36,1) both;}
.kw-list .kw-row:nth-child(1){animation-delay:.02s;}
.kw-list .kw-row:nth-child(2){animation-delay:.04s;}
.kw-list .kw-row:nth-child(3){animation-delay:.06s;}
.kw-list .kw-row:nth-child(4){animation-delay:.08s;}
.kw-list .kw-row:nth-child(5){animation-delay:.10s;}
.kw-list .kw-row:nth-child(6){animation-delay:.12s;}
.kw-list .kw-row:nth-child(7){animation-delay:.14s;}
.kw-list .kw-row:nth-child(8){animation-delay:.16s;}
.kw-list .kw-row:nth-child(9){animation-delay:.18s;}
.kw-list .kw-row:nth-child(10){animation-delay:.20s;}
.kw-list .kw-row:nth-child(11){animation-delay:.22s;}
.kw-list .kw-row:nth-child(12){animation-delay:.24s;}
.kw-list .kw-row:nth-child(13){animation-delay:.26s;}
.kw-list .kw-row:nth-child(14){animation-delay:.28s;}
.kw-list .kw-row:nth-child(15){animation-delay:.30s;}
/* 중요도 도트: 등장 시 살짝 채워지는 느낌 */
.kw-impbar i.f{animation:kw-dot-in .5s ease both .25s;}
@keyframes kw-dot-in{from{transform:scale(.4);opacity:.3;}to{transform:scale(1);opacity:1;}}
.kw-news a{transition:color .15s ease,padding-left .15s ease;}
.kw-news a:hover{padding-left:16px;}
.kw-stk{transition:transform .15s ease,box-shadow .15s ease,border-color .15s ease;}
.kw-stk:hover{transform:translateY(-1px);box-shadow:0 2px 6px rgba(52,53,47,.08);
  border-color:var(--sage,#A7BBA9);}
@media(prefers-reduced-motion:reduce){
  .kw-row,.kw-impbar i.f{animation:none !important;}
  .kw-row,.kw-news a,.kw-stk{transition:none !important;}
}
</style>
"""


def _load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _archive_dates():
    if not KW_ARCHIVE_DIR.exists():
        return []
    out = []
    for f in sorted(KW_ARCHIVE_DIR.glob("*.json"), reverse=True):
        try:
            y, m, d = f.stem.split("-")
            out.append((date(int(y), int(m), int(d)), f))
        except ValueError:
            continue
    return out


# ── 키워드 소스: Supabase(누적) 우선, 미구성 시 파일 폴백 ──────

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
            return [(d, d) for d in db.list_keyword_dates()]
        except Exception:
            pass
    return [(f"{d:%Y-%m-%d}", str(f)) for d, f in _archive_dates()]


def _kw_load(picker_value):
    """picker값(날짜문자열 또는 파일경로)으로 키워드 dict({generated, items, ...}) 로드."""
    if _kw_source() == "db":
        try:
            from modules import db
            return (db.load_keywords_by_date(picker_value) if picker_value
                    else db.load_keywords_latest())
        except Exception:
            pass
    if picker_value and Path(picker_value).exists():
        return _load(Path(picker_value))
    return _load(KW_PATH)


def _norm_name(s: str) -> str:
    return "".join(str(s).split()).casefold()


def _watch_set() -> set:
    """워치리스트 종목명 (정규화). 실패 시 빈 set."""
    try:
        from modules.watchlist import load_watchlist
        return {_norm_name(s) for s in load_watchlist()}
    except Exception:
        return set()


def _stock_html(names, watch_set):
    """종목 pill — 이름 + 네이버 시세 링크. 워치리스트 종목은 ★ 테두리."""
    parts = []
    for n in names or []:
        n = (n or "").strip()
        if not n:
            continue
        is_watch = _norm_name(n) in watch_set
        label = ("⭐ " if is_watch else "") + html.escape(n)
        watch_cls = " kw-stk-watch" if is_watch else ""
        parts.append(
            f'<span class="kw-stkwrap">'
            f'<a class="kw-stk{watch_cls}" href="{html.escape(naver_stock_search_url(n))}" '
            f'target="_blank" rel="noopener">{label}</a>'
            f'</span>'
        )
    return f'<div class="kw-stocks">{"".join(parts)}</div>' if parts else ""


def _render_items(items, watch_set):
    rows = []
    for i, it in enumerate(items[:15], start=1):
        cat = it.get("category", "")
        kw = html.escape(it.get("keyword", ""))
        cat_html = (f'<span class="kw-cat {CAT_CLS.get(cat, "cat-sector")}">{html.escape(cat)}</span>'
                    if cat else "")

        # NEW(오늘 처음) 우선, 아니면 연속 등장(streak)
        is_new = bool(it.get("is_new"))
        streak = it.get("streak", 1)
        if is_new:
            badge_html = '<span class="kw-new">NEW</span>'
        elif streak and streak >= 2:
            badge_html = f'<span class="kw-streak">🔥 {streak}일째</span>'
        else:
            badge_html = ""

        # 워치리스트 종목이 엮인 키워드는 행 강조
        stocks = it.get("stocks") or []
        has_watch = any(_norm_name(s) in watch_set for s in stocks)
        watch_html = '<span class="kw-watch">⭐</span>' if has_watch else ""
        row_cls = "kw-row kw-rowwatch" if has_watch else "kw-row"

        # 중요도(weight 1~10) → 5칸 도트
        weight = it.get("weight")
        if isinstance(weight, int):
            filled = max(0, min(5, round(weight / 2)))
            dots = "".join(f'<i class="{"f" if k < filled else ""}"></i>' for k in range(5))
            impbar = f'<div class="kw-impbar">{dots}</div>'
        else:
            impbar = ""

        stocks_html = _stock_html(stocks, watch_set)

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
            news_html = f'<div class="kw-news">{links}</div>'
        if n_news == 0:
            weak_html = '<div class="kw-weak">대표 기사 없음 — 상위 키워드와 겹치는 주제일 수 있어요</div>'
        elif n_news == 1:
            weak_html = '<div class="kw-weak">근거 기사 1건 — 참고만 하세요</div>'
        else:
            weak_html = ""

        rows.append(
            f'<div class="{row_cls}">'
            f'<div class="kw-rank"><span class="kw-num">{i}</span>{impbar}</div>'
            f'<div class="kw-main">'
            f'<div class="kw-head"><span class="kw-kw">{kw}</span>'
            f'<span class="kw-tags">{watch_html}{cat_html}{badge_html}</span></div>'
            f'{stocks_html}{news_html}{weak_html}'
            f'</div></div>'
        )

    if not rows:
        st.caption("표시할 키워드가 없어요.")
        return
    st.markdown(f'<div class="kw-list">{"".join(rows)}</div>', unsafe_allow_html=True)


def render_keywords():
    # 전체 크롬: 영문 대제목과 탭 CSS는 app.py가 [영문 대제목 | 하위 pill] 행에서 함께 주입한다.
    if st.button("🔄 키워드 갱신"):
        with st.spinner("네이버 뉴스 수집 → 키워드 추출 중..."):
            try:
                from engine.keywords import build_today_keywords
                res = build_today_keywords()
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
                            format_func=lambda s: labels.get(s, s), key="kw_date")
        data = _kw_load(pick)
    else:
        data = _kw_load(None)

    if not data or not data.get("items"):
        st.markdown(
            '<div class="empty"><div class="ico">🔑</div>'
            '<div class="msg">아직 키워드가 없어요</div>'
            '<div class="hint">"🔄 키워드 갱신"을 눌러 오늘의 키워드를 불러오세요</div></div>',
            unsafe_allow_html=True)
        return

    when = str(data.get("generated", ""))[:16].replace("T", " ")
    st.caption(f"기준: {when} · 네이버 뉴스 기반")

    watch_set = _watch_set()

    # 키워드 카드 (TOP15)
    _render_items(data["items"], watch_set)
    st.caption("※ 키워드·종목·카테고리·중요도는 AI 추출, 링크는 네이버 뉴스 실제 기사. "
               "🔥 = 연속 등장 일수, NEW = 오늘 처음 등장, ⭐ = 내 워치리스트 종목 포함, "
               "점 = 중요도. 뉴스는 키워드당 2건 표시.")
