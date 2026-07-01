"""[엔진] 주도주 일일 수집 → Supabase(leaders) 저장.

GitHub Actions(.github/workflows/leaders.yml) 일일 스케줄 또는 수동 실행으로 돈다.
engine.leaders_collect.collect() 결과(섹터·종목 점수)를 leaders 테이블에 그날치(asof_date)로 upsert.
뷰어(modules/leaders.py)는 이 최신 행만 읽는다.

NEW 뱃지: 직전 스냅샷(load_leaders) 대비 '이번에 처음 주도 그룹(score≥NEW_TH)에 진입'한 종목을 표시.

필요 환경변수: SUPABASE_URL, SUPABASE_KEY  (Naver는 키 불필요)
"""

from engine.leaders_collect import collect
from modules.db import save_leaders, load_leaders, collected_today

NEW_TH = 60.0   # 이 점수 이상을 '주도 그룹'으로 보고 신규 진입(NEW) 판정


def _prev_leader_codes():
    """직전 스냅샷에서 score≥NEW_TH 였던 종목코드 집합. 없으면 None(=NEW 판정 보류)."""
    try:
        prev = load_leaders()
    except Exception as e:
        print(f"[leaders] 직전 스냅샷 로드 실패(생략): {e}")
        return None
    if not prev:
        return None
    codes = set()
    for s in (prev.get("stocks") or []):
        try:
            if float(s.get("score", 0)) >= NEW_TH:
                codes.add(s.get("code"))
        except (TypeError, ValueError):
            continue
    return codes


def main():
    # ── 멱등 가드: 오늘(KST) 이미 수집을 마쳤으면 다음 슬롯은 즉시 스킵 ──
    #   leaders.yml은 16:40·17:40·18:40 KST 세 슬롯으로 도는데, 첫 성공이 잡으면
    #   나머지는 여기서 빠져 중복 수집·중복 키워드 API 과금을 막는다.
    if collected_today("leaders"):
        print("[leaders] 오늘 이미 수집 완료 — 스킵(멱등 가드).", flush=True)
        return

    prev_codes = _prev_leader_codes()

    payload = collect()
    stocks = payload.get("stocks") or []
    if not stocks:
        raise SystemExit("[leaders] 수집 결과가 비어 저장하지 않습니다 (Naver 차단/네트워크 확인).")

    # NEW 뱃지 부여 (직전 스냅샷이 있을 때만; 첫 실행은 모두 NEW 아님)
    n_new = 0
    for s in stocks:
        is_new = False
        if prev_codes is not None and s["score"] >= NEW_TH and s["code"] not in prev_codes:
            is_new = True
            n_new += 1
        s["is_new"] = is_new

    asof_date = save_leaders(payload, asof=payload["asof"],
                             asof_date=payload["asof_date"])
    print(f"[leaders] Supabase 저장 완료: asof_date={asof_date} · "
          f"섹터 {len(payload.get('sectors') or [])} · 종목 {len(stocks)} · NEW {n_new}")

    # ── 증시 키워드(테마 탭) — 장마감 후 매일 여기서 함께 생성. 주도주와 독립이라
    #    실패해도 격리되어 주도주 저장에는 영향 없다. 네이버 뉴스 + Haiku 사용
    #    (ANTHROPIC_API_KEY·NAVER_CLIENT_ID/SECRET 없으면 조용히 건너뜀). ──
    try:
        from engine.keywords import build_today_keywords
        k = build_today_keywords()
        if k.get("ok"):
            print(f"[leaders] 증시 키워드 {k.get('count')}개 생성·저장", flush=True)
        else:
            print(f"[leaders] 증시 키워드 건너뜀: {k.get('reason')}", flush=True)
    except Exception as e:
        print(f"[leaders] 증시 키워드 빌드 실패(생략): {e}", flush=True)


if __name__ == "__main__":
    main()
