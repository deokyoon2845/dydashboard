# DY Monitoring

개인용 한국 증시 모니터링 대시보드. 텔레그램 시황 채널 + 네이버 뉴스 + 실시간 시장 데이터를 묶어 **"전략·시황 보고서"**를 자동 생성하고, 지수·키워드·추세를 한 화면에서 본다.

> **아키텍처 한 줄 요약**: `엔진(engine/) — 데이터 생성·자동화` + `뷰어(modules/ + app.py) — 표시` 분리

---

## 1. 빠른 시작

### 로컬 실행
```bash
pip install -r requirements.txt
streamlit run app.py
```

### 비밀키 설정 (`.streamlit/secrets.toml` 또는 Streamlit Cloud Secrets)
```toml
ANTHROPIC_API_KEY = "sk-..."
TELEGRAM_API_ID = "..."
TELEGRAM_API_HASH = "..."
TELEGRAM_SESSION = "..."
APP_PASSWORD = "리포트_생성_잠금_비밀번호"   # ← 토큰 보호용 (미설정 시 잠금 없음)
```

> ⚠️ `APP_PASSWORD`를 설정하지 않으면 누구나 리포트를 생성할 수 있어 API 토큰이 소비된다. 외부 공유 시 반드시 설정할 것.

---

## 2. 4개 탭 구성

| 탭 | 내용 |
|---|---|
| **지수 현황** | 시장 지표(체온계: 공포·탐욕·ADR·RSI) + 주요 지수 4열 그리드 + 다가오는 일정 + 수급 상위 종목 |
| **전략·시황** | AI 보고서(헤드라인·관전·섹션·테마·내 종목) + 워치리스트 + PDF + 삭제 |
| **오늘의 키워드** | TOP15 키워드 3×5 그리드(카테고리·중요도·🔥연속·인라인시세·뉴스) + 날짜 아카이브 |
| **추세** | 시황 타임라인 + 시장 분위기 추세 + 주간 다이제스트 + 감성vs지수 검증 |

---

## 3. 핵심 데이터 흐름

```
[수집] 텔레그램(전일 15:40~) + 네이버 뉴스 + yfinance/pykrx
   │
[분석] engine/analyze.py — 2단계 파이프라인
   │     1차 Haiku: 메시지 클러스터링·중복제거 (15건↑일 때만)
   │     2차 Opus:  심층 분석 + JSON 구조화
   │     ↳ 주입: 정량 스냅샷 + 뉴스 + 캘린더 일정 + 최근 시황 흐름 + 워치리스트
   │
[저장] reports/YYYY-MM-DD_HHMM.json
   │
[표시] app.py + modules/ (Streamlit Cloud)
```

자동화: `.github/workflows/daily.yml` — 평일 KST 07:50 (cron `50 22 * * 0-4`) → 보고서·키워드·예측채점 생성 후 텔레그램 발송.

---

## 4. 디자인 시스템 "미니멀 미스트"

- 배경 `#FCFCFA` · 세이지 액센트 `#A7BBA9` · 상승=적 `#B65F5A` / 하락=청 `#5A7CA0`
- 폰트: Fraunces(세리프 제목) + Hanken Grotesk + Noto Sans KR
- 다크모드 지원 (`.app.dark` 변수 오버라이드)
- mood 3색은 `modules/mood.py` 단일 팔레트로 통일 (긍정 `#2E7D5B` / 중립 세이지 / 주의 `#C2410C`)
- 레이아웃: 컨테이너 최대폭 1280px, 카드 그리드 4열(981px+) → 3열 → 2열 반응형

---

## 5. 외부 의존성

| 소스 | 용도 | 안정성 |
|---|---|---|
| yfinance | 지수·환율·RSI·종목 히스토리 | 높음 |
| pykrx | ADR·수급·종목명 | ⚠️ 해외 IP 차단 가능 (폴백 있음) |
| KRX data API | ADR 2차 폴백 | ⚠️ 동일 |
| 네이버 금융/뉴스 | ADR 3차 폴백·키워드·종목링크 | 높음 |
| CNN F&G (비공식) | 공포·탐욕 지수 | 중간 |
| Anthropic API | 보고서·키워드 분석 | 높음 |

자세한 파일별 역할·작업 규칙·로드맵은 `Handoff.md` 참고.
