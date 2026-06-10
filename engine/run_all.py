"""[엔진] 일일 자동 실행 — 리포트 + 키워드를 한 번에 생성.

GitHub Actions가 호출합니다. 하나가 실패해도 다른 하나는 계속 진행합니다.
실행: python -m engine.run_all
"""

from engine.generate import generate_report
from engine.keywords import build_today_keywords


def main():
    print("== 전략/시황 보고서 생성 ==")
    try:
        r = generate_report(send_telegram=True)
        if r.get("ok"):
            print("리포트:", r.get("path"))
            tg = r.get("telegram")
            if tg:
                print("텔레그램 발송:", "성공" if tg.get("ok") else f"실패 ({tg.get('reason')})")
        else:
            print("리포트: 건너뜀 (", r.get("reason"), ")")
    except Exception as e:
        print("리포트 오류:", e)

    print("== 오늘의 키워드 갱신 ==")
    try:
        k = build_today_keywords()
        print("키워드:", f"{k.get('count')}개" if k.get("ok") else f"건너뜀 ({k.get('reason')})")
    except Exception as e:
        print("키워드 오류:", e)


    print("== 예측 채점 갱신 ==")
    try:
        from engine.predictions import update_scores
        r = update_scores()
        print("채점:", f"{r.get('total')}건 · 적중률 {r.get('accuracy')}%" if r.get("ok") else f"건너뜀 ({r.get('reason')})")
    except Exception as e:
        print("채점 오류:", e)


if __name__ == "__main__":
    main()
