"""사용자 워치리스트 — 저장은 data/watchlist.json, UI는 리포트 탭."""

import json
from pathlib import Path

WL_PATH = Path("data/watchlist.json")


def load_watchlist() -> list:
    try:
        if WL_PATH.exists():
            data = json.loads(WL_PATH.read_text(encoding="utf-8"))
            return [str(s).strip() for s in data.get("stocks", []) if str(s).strip()]
    except Exception:
        pass
    return []


def save_watchlist(stocks: list):
    WL_PATH.parent.mkdir(exist_ok=True)
    clean = []
    for s in stocks:
        s = str(s).strip()
        if s and s not in clean:
            clean.append(s)
    WL_PATH.write_text(
        json.dumps({"stocks": clean[:20]}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return clean[:20]


def render_watchlist_editor():
    import streamlit as st
    with st.expander("⭐ 내 워치리스트 (리포트에 '내 종목' 섹션 추가)"):
        current = load_watchlist()
        text = st.text_input(
            "관심 종목 (쉼표로 구분, 최대 20개)",
            value=", ".join(current),
            placeholder="예: 삼성전자, SK하이닉스, 두산에너빌리티",
            key="wl_input")
        if st.button("저장", key="wl_save"):
            saved = save_watchlist(text.split(","))
            st.success(f"{len(saved)}개 종목 저장 완료. 다음 리포트 생성부터 반영돼요.")
