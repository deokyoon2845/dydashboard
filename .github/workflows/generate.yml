name: 전략시황 보고서 자동 생성

on:
  schedule:
    # 평일(KST) 장전 07:50  = UTC 전일 22:50 (UTC 일~목 → KST 월~금 아침)
    - cron: "50 22 * * 0-4"
    # 평일(KST) 장마감 후 17:00 = UTC 당일 08:00 (UTC 월~금 → KST 월~금 저녁)
    - cron: "0 8 * * 1-5"
    # ※ 두 cron 모두 요일 지정으로 토·일(KST)에는 실행되지 않음.
    #   장전/장후 구분은 generate.py가 생성 시각(KST)으로 자동 판별(오전=장전, 오후=장후).
  workflow_dispatch:        # GitHub에서 수동 실행 버튼도 제공

permissions:
  contents: write

jobs:
  generate:
    runs-on: ubuntu-latest
    steps:
      - name: 저장소 체크아웃
        uses: actions/checkout@v4

      - name: 파이썬 설정
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: 라이브러리 설치
        run: pip install -r requirements.txt

      - name: 보고서·키워드 생성 + 텔레그램 발송
        env:
          TELEGRAM_API_ID: ${{ secrets.TELEGRAM_API_ID }}
          TELEGRAM_API_HASH: ${{ secrets.TELEGRAM_API_HASH }}
          TELEGRAM_SESSION: ${{ secrets.TELEGRAM_SESSION }}
          TELEGRAM_CHANNEL: ${{ secrets.TELEGRAM_CHANNEL }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          REPORT_MODEL: ${{ secrets.REPORT_MODEL }}
          NAVER_CLIENT_ID: ${{ secrets.NAVER_CLIENT_ID }}
          NAVER_CLIENT_SECRET: ${{ secrets.NAVER_CLIENT_SECRET }}
        run: python -m engine.run_all

      - name: 결과 커밋 & 푸시
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add reports/ data/
          git diff --staged --quiet || git commit -m "자동 생성: $(date -u +%Y-%m-%d) ($(date -u +%H:%MUTC))"
          git push
