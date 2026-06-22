"""부동산 실거래 일일 수집 → Supabase 저장.

GitHub Actions(.github/workflows/realestate.yml)의 일일 스케줄, 또는 수동 실행으로 돈다.
국토부 실거래를 수집해 realestate_snapshots 테이블에 그날치(asof_date) 한 행으로 upsert 한다.
뷰어(modules/realestate.py)는 이 최신 행을 읽어 '항상 실데이터'를 보여준다.

필요 환경변수: SUPABASE_URL, SUPABASE_KEY, MOLIT_API_KEY(또는 PUBLIC_DATA_API_KEY/DATA_GO_KR_KEY)
"""

from engine.realestate_collect import (collect_region_metrics, collect_anomalies,
                                        collect_indicators)
from modules.db import save_realestate


def main():
    metrics = None
    anomalies = None
    indicators = None
    subscriptions = None

    try:
        metrics = collect_region_metrics()
        print(f"[realestate] 지역 지표 {len(metrics)}개 수집")
    except Exception as e:
        print(f"[realestate] 지역 지표 수집 실패: {e}")

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

    if not metrics and not anomalies and not subscriptions and not indicators:
        raise SystemExit("[realestate] 수집 결과가 비어 저장하지 않습니다 (키/네트워크 확인).")

    asof_date = save_realestate(metrics=metrics, anomalies=anomalies,
                                indicators=indicators, subscriptions=subscriptions)
    print(f"[realestate] Supabase 저장 완료: asof_date={asof_date}")


if __name__ == "__main__":
    main()
