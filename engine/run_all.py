"""[엔진] 일일 자동 실행 — 작업을 골라 실행(report / keywords / scores / all).

GitHub Actions가 호출합니다. 하나가 실패해도 다른 하나는 계속 진행합니다.
실행:
    python -m engine.run_all            # 전체(보고서+키워드+채점+국고채) — 수동 실행 기본값
    python -m engine.run_all report     # 보고서만(장전/장후 시각 자동판별, 채점 포함)
    python -m engine.run_all keywords   # 오늘의 키워드만
    python -m engine.run_all scores     # 예측 채점만
    python -m engine.run_all rates      # 한국 국고채 수집만(ECOS → engine_cache)

장전/장후는 generate_report()가 생성 '시각'으로 자동 판별한다(오전=장전, 오후=장후).
따라서 07:50 KST cron → 장전, 17:00 KST cron → 장마감 후로 자동으로 갈린다.
"""

import sys

from engine.generate import generate_report
from engine.keywords import build_today_keywords


def _run_report():
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


def _run_keywords():
    print("== 오늘의 키워드 갱신 ==")
    try:
        k = build_today_keywords()
        print("키워드:", f"{k.get('count')}개" if k.get("ok") else f"건너뜀 ({k.get('reason')})")
    except Exception as e:
        print("키워드 오류:", e)


def _run_scores():
    print("== 예측 채점 갱신 ==")
    try:
        from engine.predictions import update_scores
        r = update_scores()
        print("채점:", f"{r.get('total')}건 · 적중률 {r.get('accuracy')}%"
              if r.get("ok") else f"건너뜀 ({r.get('reason')})")
    except Exception as e:
        print("채점 오류:", e)


def _run_kr_rates():
    print("== 한국 국고채 수집(ECOS → engine_cache) ==")
    try:
        from engine.kr_rates_collect import collect_kr_rates
        r = collect_kr_rates()
        print("국고채:", r.get("counts") if r.get("ok") else f"건너뜀 ({r.get('reason')})")
    except Exception as e:
        print("국고채 오류:", e)


def main(task="all"):
    task = (task or "all").strip().lower()
    if task not in ("all", "report", "keywords", "scores", "rates"):
        print(f"알 수 없는 작업 '{task}' → 전체(all)로 실행")
        task = "all"
    print(f"== run_all: 작업='{task}' ==")
    if task in ("all", "report"):
        _run_report()          # generate_report 내부에서 예측 채점도 함께 갱신됨
    if task in ("all", "keywords"):
        _run_keywords()
    if task in ("all", "scores"):
        _run_scores()
    if task in ("all", "rates"):
        _run_kr_rates()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "all")
