"""[엔진] 일일 자동 실행 — 리포트 + 키워드를 한 번에 생성.

GitHub Actions가 호출합니다. 하나가 실패해도 다른 하나는 계속 진행합니다.
실행: python -m engine.run_all
"""

from engine.generate import generate_report
from engine.keywords import build_today_keywords


def main():
    print("== 시황 리포트 생성 ==")
    try:
        r = generate_report()
        print("리포트:", r.get("path") if r.get("ok") else f"건너뜀 ({r.get('reason')})")
    except Exception as e:
        print("리포트 오류:", e)

    print("== 오늘의 키워드 갱신 ==")
    try:
        k = build_today_keywords()
        print("키워드:", f"{k.get('count')}개" if k.get("ok") else f"건너뜀 ({k.get('reason')})")
    except Exception as e:
        print("키워드 오류:", e)


if __name__ == "__main__":
    main()
