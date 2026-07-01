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

    # ── 멱등 가드: 오늘(KST) 이미 수집을 마쳤으면 다음 슬롯은 즉시 스킵 ──
    #   ipo.yml은 14:00·15:00 KST 두 슬롯. 첫 성공이 잡으면 여기서 빠져
    #   중복 수집·중복 회사소개(Anthropic) 과금을 막는다.
    if db.collected_today("ipo_snapshots"):
        print("[ipo_run] 오늘 이미 수집 완료 — 스킵(멱등 가드).", flush=True)
        return 0

    try:
        data = collect()
    except Exception:
        print("[ipo_run] 수집 실패:", flush=True)
        traceback.print_exc()
        return 1

    # 회사소개(intro) 보강 — DART 사업보고서 → Haiku 요약(캐시 우선).
    # 키(DART_API_KEY·ANTHROPIC_API_KEY)가 없으면 캐시만 사용하고 신규 생성은 건너뛴다.
    # 실거래 수집과 독립이라 실패해도 스냅샷 저장에는 영향 없다.
    try:
        from engine.ipo_about import enrich
        enrich(data.get("recent") or [])
    except Exception as e:
        print(f"[ipo_run] 회사소개 보강 건너뜀: {e}", flush=True)

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
