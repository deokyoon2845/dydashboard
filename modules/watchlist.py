"""사용자 관심종목(워치리스트) — 저장은 Supabase DB 우선, 로컬은 JSON 폴백.

영속성: Streamlit Cloud 파일시스템은 휘발성이라 data/watchlist.json은 reboot 때 사라진다.
  그래서 Supabase가 설정돼 있으면 DB(watchlist 테이블)에 저장해 재시작에도 보존한다.
  Supabase 미설정(로컬 개발 등)에서는 기존처럼 data/watchlist.json을 쓴다.

load_watchlist()는 어떤 상황에서도 예외를 던지지 않는다(엔진·키워드뷰 등 여러 곳이 호출).
save_watchlist()는 Supabase 설정 시 DB에 저장하며, 실패하면 예외를 올려 UI가 표시하게 한다
  (조용히 휘발성 JSON에 저장해 '저장된 줄 알았는데 사라지는' 일을 막기 위함).
"""

import json
from pathlib import Path

WL_PATH = Path("data/watchlist.json")


def _db():
    """db 모듈 핸들 — supabase 미설치 등으로 import 실패하면 None."""
    try:
        from modules import db
        return db
    except Exception:
        return None


def _dedup(stocks: list) -> list:
    clean = []
    for s in stocks:
        s = str(s).strip()
        if s and s not in clean:
            clean.append(s)
    return clean[:20]


def load_watchlist() -> list:
    """관심종목 목록. DB 우선(설정 시) → 로컬 JSON 폴백 → 빈 리스트. 예외 없음."""
    db = _db()
    if db is not None:
        try:
            if db.supabase_configured():
                return db.load_watchlist_db()
        except Exception:
            pass
    # 로컬 JSON 폴백 (Supabase 미설정 환경)
    try:
        if WL_PATH.exists():
            data = json.loads(WL_PATH.read_text(encoding="utf-8"))
            return [str(s).strip() for s in data.get("stocks", []) if str(s).strip()]
    except Exception:
        pass
    return []


def save_watchlist(stocks: list) -> list:
    """관심종목 저장. Supabase 설정 시 DB에 저장(실패하면 예외).
    미설정 시 로컬 JSON에 저장. 정리된 목록 반환."""
    clean = _dedup(stocks)
    db = _db()
    if db is not None and db.supabase_configured():
        # DB 저장 — 실패 시 예외를 그대로 올려 호출부(UI)가 오류를 표시하게 한다.
        return db.save_watchlist_db(clean)
    # 로컬 JSON 폴백
    WL_PATH.parent.mkdir(exist_ok=True)
    WL_PATH.write_text(
        json.dumps({"stocks": clean}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return clean


def render_watchlist_editor():
    """리포트 탭에서 쓰는 간단 편집기 (기존 호환 유지)."""
    import streamlit as st
    with st.expander("⭐ 내 관심종목 (리포트에 '내 종목' 섹션 추가)"):
        current = load_watchlist()
        text = st.text_input(
            "관심 종목 (쉼표로 구분, 최대 20개)",
            value=", ".join(current),
            placeholder="예: 삼성전자, SK하이닉스, 현대차",
            key="wl_input")
        if st.button("저장", key="wl_save"):
            try:
                saved = save_watchlist(text.split(","))
                st.success(f"{len(saved)}개 종목 저장 완료. '관심 종목' 탭과 다음 리포트에 반영돼요.")
            except Exception as e:
                st.error(f"저장 실패: {e}")
