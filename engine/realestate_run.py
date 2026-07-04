"""부동산 실거래 일일 수집 → Supabase 저장.

GitHub Actions(.github/workflows/realestate.yml)의 일일 스케줄, 또는 수동 실행으로 돈다.
국토부 실거래를 수집해 realestate_snapshots 테이블에 그날치(asof_date) 한 행으로 upsert 한다.
뷰어(modules/realestate.py)는 이 최신 행을 읽어 '항상 실데이터'를 보여준다.

필요 환경변수: SUPABASE_URL, SUPABASE_KEY, MOLIT_API_KEY(또는 PUBLIC_DATA_API_KEY/DATA_GO_KR_KEY)
"""

from engine.realestate_collect import (collect_region_metrics, collect_anomalies,
                                        collect_indicators)
from modules.db import save_realestate, collected_today, purge_old_data


def main():
    # ── 보존 정책: 오래된 시계열 정리(용량 관리) ──
    #   부동산 크론은 매일(주말 포함) 도는 유일한 일일 잡이라, 전역 데이터 정리를 여기에
    #   얹는다. reports·keywords·leaders·ipo 등 다른 테이블도 db.RETENTION에 따라 함께
    #   정리한다. 멱등이라 3슬롯 중복 실행돼도 두 번째부턴 0건이라 안전하다.
    #   실패해도 격리되어 실거래 수집엔 영향 없다.
    try:
        purged = purge_old_data()
        hit = ", ".join(f"{k} {v}건" for k, v in purged.items() if v)
        print(f"[retention] 오래된 행 정리: {hit or '삭제 대상 없음'}", flush=True)
    except Exception as e:
        print(f"[retention] 정리 실패(무시): {e}", flush=True)

    # ── 멱등 가드: 오늘(KST) 이미 수집을 마쳤으면 다음 슬롯은 즉시 스킵 ──
    #   realestate.yml은 06:07·07:07·08:07 KST 세 슬롯. 첫 성공이 잡으면 여기서
    #   빠져 중복 수집·중복 부동산 키워드(Anthropic) 과금을 막는다.
    if collected_today("realestate_snapshots"):
        print("[realestate] 오늘 이미 수집 완료 — 스킵(멱등 가드).", flush=True)
        return

    metrics = None
    anomalies = None
    indicators = None
    subscriptions = None

    try:
        metrics = collect_region_metrics()
        print(f"[realestate] 지역 지표 {len(metrics)}개 수집")
    except Exception as e:
        print(f"[realestate] 지역 지표 수집 실패: {e}")

    # 주목 단지(거래 활발·상승 + 검색관심도) — metrics 페이로드에 '_hot'으로 실어 보냄(스키마 무변경)
    if isinstance(metrics, dict):
        try:
            from engine.realestate_collect import collect_hot_complexes
            hot, cap, gain = collect_hot_complexes(with_cap=True, with_gain=True)
            metrics["_hot"] = hot
            metrics["_caplead"] = cap          # 구별 시가총액 상위 단지(같은 스윕 공유)
            metrics["_capgain"] = gain         # 작년말 대비 시총 상승률 상위(전년 12월 추가 스윕)
            print(f"[realestate] 주목 단지 {len(hot)}개 · 시총리더 {len(cap)}개 · 상승률리더 {len(gain)}개 수집")
        except Exception as e:
            print(f"[realestate] 주목 단지 수집 실패(생략): {e}")

    # 주요 단지 유니버스(지역별 세대수 TOP-N) — engine_cache(re_universe) 30일 TTL, 월1회 실질 재빌드.
    #   시총·주목단지·특이거래가 이 위에서 계산되도록 먼저 '확보·적재'한다(현재 단계: 확보만,
    #   기존 탭 계산은 무변경). metrics 페이로드에 _universe로 실어 뷰어가 같은 스냅샷에서 읽게 함.
    try:
        from engine.realestate_collect import collect_universe
        uni = collect_universe()
        if isinstance(metrics, dict) and isinstance(uni, dict):
            metrics["_universe"] = uni
        print(f"[realestate] 유니버스 {len(uni.get('flat', []))}단지 확보")
    except Exception as e:
        print(f"[realestate] 유니버스 확보 실패(생략): {e}")

    try:
        indicators = collect_indicators()
        print(f"[realestate] 지표 시계열 {len(indicators)}종 수집")
    except Exception as e:
        print(f"[realestate] 지표 시계열 수집 실패: {e}")

    try:
        anomalies = collect_anomalies()
        print(f"[realestate] 특이거래 {len(anomalies)}건 수집")
    except Exception as e:
        print(f"[realestate] 특이거래 수집 실패: {e}")

    try:
        from engine.realestate_subscriptions import collect_subscriptions
        subscriptions = collect_subscriptions()
        print(f"[realestate] 분양 {len(subscriptions)}건 수집")
    except Exception as e:
        print(f"[realestate] 분양 수집 실패: {e}")

    # ── 부동산 키워드 (네이버 뉴스 + Haiku) — 실거래와 독립. 실패해도 격리되어
    #    실거래 저장에 영향 없음. DB(realestate_keywords)에 날짜별 누적 → streak/NEW 영속. ──
    try:
        from engine.realestate_keywords import build_realestate_keywords
        kw = build_realestate_keywords()
        if kw.get("ok"):
            print(f"[realestate] 키워드 {kw.get('count')}개 생성·저장")
        else:
            print(f"[realestate] 키워드 생성 건너뜀: {kw.get('reason')}")
    except Exception as e:
        print(f"[realestate] 키워드 빌드 실패(생략): {e}")

    if not metrics and not anomalies and not subscriptions and not indicators:
        raise SystemExit("[realestate] 수집 결과가 비어 저장하지 않습니다 (키/네트워크 확인).")

    asof_date = save_realestate(metrics=metrics, anomalies=anomalies,
                                indicators=indicators, subscriptions=subscriptions)
    print(f"[realestate] Supabase 저장 완료: asof_date={asof_date}")


if __name__ == "__main__":
    main()
