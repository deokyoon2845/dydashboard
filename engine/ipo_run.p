"""[엔진 진입점] IPO 데이터 수집 → Supabase(ipo_snapshots) 저장.

GitHub Actions(ipo.yml)에서 `python -m engine.ipo_run` 으로 실행.
뷰어(modules/ipo.py)는 이 테이블의 최신 1행만 읽는다.
※ 최초 1회 Supabase에 ipo_snapshots 테이블 생성 필요(modules/db.py 상단 SQL).
"""

import sys
import traceback

from engine.ipo_collect import collect


def main():
    try:
        from modules import db
    except Exception as e:
        print(f"[ipo_run] db 모듈 로드 실패: {e}", flush=True)
        return 1

    if not db.supabase_configured():
        print("[ipo_run] SUPABASE 미설정 — 저장 건너뜀(키 확인).", flush=True)
        return 1

    try:
        data = collect()
    except Exception:
        print("[ipo_run] 수집 실패:", flush=True)
        traceback.print_exc()
        return 1

    n_recent = len(data.get("recent") or [])
    n_up = len(data.get("upcoming") or [])
    if n_recent == 0 and n_up == 0:
        print("[ipo_run] 수집 결과가 비어 있음 — 기존 스냅샷 보존 위해 저장 건너뜀.", flush=True)
        return 1

    try:
        asof_date = db.save_ipo(
            recent=data["recent"], upcoming=data["upcoming"],
            asof=data.get("asof"), asof_date=data.get("asof_date"))
        print(f"[ipo_run] 저장 완료 asof_date={asof_date} · 최근 {n_recent} · 향후 {n_up}", flush=True)
        return 0
    except Exception:
        print("[ipo_run] 저장 실패:", flush=True)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
