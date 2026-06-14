"""Supabase 보고서 저장소 — 엔진(GitHub Actions)·뷰어(Streamlit) 공용 얇은 계층.

- 뷰어에서는 Streamlit Secrets, 엔진에서는 환경변수로 키를 읽는다(둘 다 지원).
- 보고서는 reports 테이블에 (report_date, report_kind) 기준 upsert 된다.
"""
import os
import re
from datetime import datetime

from supabase import create_client, Client

TABLE = "reports"
_CLIENT: Client | None = None


def _cfg(key: str) -> str:
    """SUPABASE_URL / SUPABASE_KEY를 환경변수 우선, 없으면 Streamlit Secrets에서 읽는다."""
    val = os.environ.get(key)
    if val:
        return val
    try:
        import streamlit as st  # 뷰어(Streamlit)에서만 존재
        return st.secrets[key]
    except Exception as e:
        raise RuntimeError(f"{key}가 설정되지 않았어요 (Secrets 또는 환경변수 확인).") from e


def _client() -> Client:
    global _CLIENT
    if _CLIENT is None:
        url = _cfg("SUPABASE_URL").strip().rstrip("/")
        key = _cfg("SUPABASE_KEY").strip()
        _CLIENT = create_client(url, key)
    return _CLIENT


def _meta_from_data(data: dict):
    """보고서 dict에서 slug · 날짜 · 종류(pre/post)를 유도한다."""
    gen = str(data.get("generated_at", "")).strip()
    m = re.search(r"(\d{4}-\d{2}-\d{2})\D+(\d{2}):?(\d{2})", gen)
    if m:
        d, hhmm = m.group(1), m.group(2) + m.group(3)
    else:
        # generated_at이 비었으면 analysis_until → 그래도 없으면 현재 시각
        m2 = re.search(r"(\d{4}-\d{2}-\d{2})", str(data.get("analysis_until", "")) or gen)
        now = datetime.now()
        d = m2.group(1) if m2 else now.strftime("%Y-%m-%d")
        hhmm = now.strftime("%H%M")

    kind = data.get("report_kind")
    if kind not in ("pre", "post"):
        kind = "pre" if int(hhmm[:2]) < 12 else "post"
    return f"{d}_{hhmm}", d, kind


# ── 쓰기 ──────────────────────────────────────────────────────

def save_report(data: dict) -> str:
    """보고서 dict를 DB에 저장(upsert). 같은 날·같은 종류는 덮어쓴다. slug 반환."""
    slug, d, kind = _meta_from_data(data)
    row = {
        "slug": slug,
        "report_date": d,
        "report_kind": kind,
        "generated_at": str(data.get("generated_at", "")),
        "data": data,
    }
    _client().table(TABLE).upsert(row, on_conflict="report_date,report_kind").execute()
    return slug


# ── 읽기 ──────────────────────────────────────────────────────

def list_slugs() -> list[str]:
    """모든 보고서 slug를 최신 날짜순으로 반환."""
    res = (_client().table(TABLE)
           .select("slug,report_date")
           .order("report_date", desc=True)
           .execute())
    return [r["slug"] for r in (res.data or [])]


def load_by_slug(slug: str) -> dict | None:
    """slug(=파일명 stem)로 보고서 data(JSON) 단건 조회."""
    res = (_client().table(TABLE)
           .select("data")
           .eq("slug", slug)
           .limit(1)
           .execute())
    return res.data[0]["data"] if res.data else None


def delete_by_slug(slug: str) -> None:
    """slug로 보고서 삭제 (삭제 UI용)."""
    _client().table(TABLE).delete().eq("slug", slug).execute()
