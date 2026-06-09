"""오늘의 키워드 Top10 뷰 (랭킹 리스트 양식)."""

import html
import json
from pathlib import Path

import streamlit as st

from modules.stocks import stock_pills_html

KW_PATH = Path("data/keywords_today.json")


def _load():
    if not KW_PATH.exists():
        return None
    try:
        return json.loads(KW_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def render_keywords():
    st.markdown('<div class="rpt-bar"></div>', unsafe_allow_html=True)
    st.title("오늘의 키워드 Top 10")

    if st.button("🔄 키워드 갱신"):
        with st.spinner("네이버 뉴스 수집 → 키워드 추출 중..."):
            try:
                from engine.keywords import build_today_keywords
                res = build_today_keywords()
            except Exception as e:
                res = {"ok": False, "reason": str(e)}
        if res.get("ok"):
            st.success("키워드를 갱신했어요.")
            st.rerun()
        else:
            st.warning(f"갱신 실패 · {res.get('reason')}")

    data = _load()
    if not data or not data.get("items"):
        st.markdown(
            '<div class="empty"><div class="ico">🔑</div>'
            '<div class="msg">아직 키워드가 없어요</div>'
            '<div class="hint">"🔄 키워드 갱신"을 눌러 오늘의 키워드를 불러오세요</div></div>',
            unsafe_allow_html=True,
        )
        return

    when = str(data.get("generated", ""))[:16].replace("T", " ")
    st.caption(f"기준: {when} · 네이버 뉴스 기반")

    rows = []
    for i, it in enumerate(data["items"][:10], start=1):
        kw = html.escape(it.get("keyword", ""))
        pills = stock_pills_html(it.get("stocks") or [])
        url = it.get("news_url", "")
        title = html.escape(it.get("news_title", ""))
        news = (
            f'<div class="kw-news"><a href="{html.escape(url)}" target="_blank" '
            f'rel="noopener">{title} ↗</a></div>'
            if url else ""
        )
        rows.append(
            f'<div class="kw-row"><div class="kw-rank">{i}</div>'
            f'<div class="kw-mid"><div class="kw-kw">{kw}</div>'
            f'<div>{pills}</div>{news}</div></div>'
        )

    st.markdown("".join(rows), unsafe_allow_html=True)
    st.caption("※ 키워드·종목은 AI 추출, 링크는 네이버 뉴스의 실제 기사입니다.")
