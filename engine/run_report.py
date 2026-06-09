"""[엔진] CLI에서 리포트 1건 생성.

프로젝트 루트에서 실행:
    python -m engine.run_report
"""

from engine.generate import generate_report


def main():
    print("리포트 생성 중... (전일 00:00 ~ 지금)")
    res = generate_report()
    if res.get("ok"):
        print(f"완료: {res['path']}")
        print(f"  메시지 {res['messages']}개 · 예상 비용 ${res['cost_usd']:.4f}")
    else:
        print(f"실패: {res.get('reason')}")


if __name__ == "__main__":
    main()
