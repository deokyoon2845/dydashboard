# 📈 DY Monitoring — 전략·시황 대시보드

한국·글로벌 증시를 한눈에 보는 개인용 시장 인텔리전스 대시보드.  
텔레그램 시장 시각 채널 + 정량 데이터 + 뉴스를 AI(Claude)로 교차 분석해  
매일 아침 장 시작 전 읽는 전략·시황 보고서를 자동 생성하고,  
지수·키워드·일정·추세를 함께 모아 시장을 빠르게 파악합니다.

---

## 한눈에 보기

- **4개 탭**: 지수 현황 · 전략·시황 · 오늘의 키워드 · 추세
- **상단 전광판**: 코스피·코스닥·환율·미국 지수 + 워치리스트 종목이 흐르는 티커 테이프 (모든 탭 공통)
- **2단계 AI 파이프라인**: Haiku 정제 → Opus 심층 분석 (비용 절감 + 통찰 품질 유지)
- **디자인 시스템 "미니멀 미스트"**: 라이트 단일 테마, 한국식 등락 색 (상승 적 · 하락 청)

---

## 아키텍처: 엔진 ↔ 뷰어 분리

```
┌─────────────────────┐   reports/*.json   ┌──────────────────────┐
│      engine/        │ ─── data/*.json ──▶ │      modules/        │
│   (데이터 생성)      │   digests/*.md      │   (Streamlit 뷰어)   │
│                     │                     │                      │
│  로컬 / GH Actions  │                     │   Streamlit Cloud    │
└─────────────────────┘                     └──────────────────────┘
```

- **engine/** — 텔레그램 수집 → AI 분석 → JSON 리포트·키워드 생성. Streamlit 의존성 없음 → GitHub Actions에서도 동작.
- **modules/** — 생성된 JSON·MD를 읽어 화면 표시. 데이터를 직접 만들지 않음.
- 이 분리로 배포가 단순하고, 무거운 생성 작업과 가벼운 조회가 섞이지 않습니다.

---

## 폴더 트리

```
dy-monitoring/
│
├── app.py                        # Streamlit 메인 앱 (4탭 라우팅, 전역 CSS)
│
├── engine/                       # 데이터 생성 (로컬 / GitHub Actions)
│   ├── generate.py               # 보고서 생성 오케스트레이터 (장전·장후)
│   ├── analyze.py                # Claude Haiku→Opus 2단계 분석
│   ├── telegram.py               # Telethon 수집 (channels.json 참조)
│   ├── channels.json             # 수집 채널 목록 (시장 시각 소스)
│   ├── news.py                   # 네이버 뉴스 API 수집
│   ├── keywords.py               # 오늘의 키워드 추출 (Haiku, 사건 단위 중복 제거)
│   ├── market_snapshot.py        # 정량 스냅샷 (지수·환율·수급·RSI)
│   └── digest.py                 # 주간 다이제스트 생성
│
├── modules/                      # Streamlit 뷰어 (화면 표시 전용)
│   ├── reports.py                # 전략·시황 탭 렌더러
│   │                             #   ⓪ TL;DR (mood 흐름 + 헤드라인)
│   │                             #   ① 시장 동력 매트릭스 (단기/장기 × 상승/하락)
│   │                             #   ② 장전·장후 카드 (교차검증 포함)
│   │                             #   ③ 주목 테마 (3열)
│   ├── keywords_view.py          # 오늘의 키워드 탭 (2열 그리드, 뉴스 1줄)
│   ├── timeline_view.py          # 추세 탭 타임라인
│   ├── trends.py                 # 추세 탭 감성 차트·다이제스트
│   ├── indices.py                # 지수 데이터 fetch (yfinance·pykrx)
│   ├── indicators.py             # 시장 체온계 (CNN F&G, RSI)
│   ├── calendar_view.py          # 경제 일정 캘린더
│   ├── ticker_tape.py            # 상단 전광판 티커
│   ├── watchlist.py              # 워치리스트 편집·로드
│   ├── stocks.py                 # 종목 네이버 URL 헬퍼
│   ├── stock_quote.py            # 당일 등락률 조회
│   ├── report_pdf.py             # PDF 생성 (NanumGothic)
│   ├── mood.py                   # mood 색·레이블 통합 팔레트
│   ├── usage.py                  # 토큰·비용 추적
│   └── verify.py                 # 예측 검증 UI
│
├── reports/                      # 생성된 보고서 JSON (날짜_HHMM.json)
│   └── YYYY-MM-DD_HHMM.json
│
├── data/                         # 생성된 데이터 JSON
│   ├── keywords_today.json       # 오늘의 키워드
│   ├── keywords_archive/         # 날짜별 키워드 아카이브
│   │   └── YYYY-MM-DD.json
│   ├── market_snapshot.json      # 최신 정량 스냅샷
│   ├── calendar.json             # 경제 일정
│   └── watchlist.json            # 워치리스트
│
├── digests/                      # 주간 다이제스트 MD
│   └── YYYY-WNN.md
│
├── .env                          # 로컬 환경 변수 (gitignore)
├── requirements.txt
└── README.md
```

---

## 탭별 기능

### 1. 지수 현황
- 지수 카드: 국내·미국·환율·변동성/원자재·암호화폐 그룹 (등락률 + 스파크라인), 그룹 간 구분선
- 코스피·코스닥 대형 차트: 기간 선택 (1·3·6개월 / 1년), 좌우 반반 전체 폭, 툴팁
- 시장 지표 (체온계): CNN 공포·탐욕 지수, RSI 4종
- 월간 캘린더: FOMC·CPI·실적 일정을 달력 그리드에 표시 + 직접 일정 추가
- 수급 상위 종목: 외국인·기관 순매수 Top5 (pykrx)

### 2. 전략·시황
- **⓪ 오늘의 한 줄 TL;DR**: 장전→장후 mood 흐름 + 최신 헤드라인 (날짜 제목 바로 아래)
- **① 시장 동력 매트릭스**: 단기/장기 × 상승/하락 4분면 (market_drivers 기반)
- **② 장전·장후 카드**: 헤드라인 · 오늘의 관전(결산) · 본문 섹션 · **교차 검증** (시장 시각 vs 실제 데이터 → 판정) · 출처 칩
- **③ 주목 테마**: 전체 폭 3열 그리드
- PDF 다운로드 (NanumGothic), JSON 저장 (깃허브 영구 보존용), 지난 리포트 조회, 워치리스트 편집, 리포트 삭제

### 3. 오늘의 키워드
- 최대 15개 키워드 (중요도 순), 2열 그리드, 뉴스 1줄 고정 (높이 균일)
- 사건 단위 중복 제거: 기사군이 겹치는 키워드 자동 병합 (코드 레벨)
- 카테고리 라벨 (거시·섹터·종목·정책), 🔥 연속 등장, NEW, ⭐ 워치리스트 배지
- 날짜별 아카이브

### 4. 추세
- 시장 분위기(mood) 추세 차트 (긍정 +1 / 중립 0 / 부정 −1)
- 주간 다이제스트 생성·표시

---

## 보고서 JSON 스키마

```jsonc
{
  "report_kind": "pre",           // "pre"(장전) | "post"(장후)
  "headline": "...",              // 한 줄 헤드라인
  "key_takeaway": "...",          // 오늘의 관전 / 결산
  "mood": "positive",            // "positive" | "neutral" | "cautious"
  "market_drivers": {             // 시장 동력 매트릭스
    "short_term": {
      "up":   [{"label": "...", "desc": "..."}],
      "down": [{"label": "...", "desc": "..."}]
    },
    "long_term": {
      "up":   [{"label": "...", "desc": "..."}],
      "down": [{"label": "...", "desc": "..."}]
    }
  },
  "cross_check": {                // 교차 검증
    "market_view": "...",         // 텔레그램 시장 시각
    "data_fact":   "...",         // 실제 정량 데이터
    "verdict":     "mixed",       // 판정 한 단어
    "insight":     "..."          // 종합 통찰
  },
  "sections": [                   // 본문 섹션 (제목 + 본문)
    {"title": "...", "body": "..."}
  ],
  "themes": [                     // 주목 테마
    {"name": "...", "detail": "...", "tickers": "종목A,종목B"}
  ],
  "keywords": [...],
  "generated_at": "2026-06-13T08:50:00+09:00",
  "messages_count": 52,
  "data_enriched": true,          // 정량 스냅샷 주입 여부
  "source_channels": ["채널명"],
  "analysis_since": "2026-06-12 15:30",
  "analysis_until": "2026-06-13 08:50"
}
```

---

## 설치 및 실행

```bash
pip install -r requirements.txt
streamlit run app.py
```

### 환경 변수 / Secrets

`.env` (로컬) 또는 Streamlit Secrets:

```env
ANTHROPIC_API_KEY=...        # AI 분석 (필수)
TELEGRAM_API_ID=...          # 텔레그램 수집 (필수)
TELEGRAM_API_HASH=...
NAVER_CLIENT_ID=...          # 뉴스 키워드 (필수)
NAVER_CLIENT_SECRET=...
APP_PASSWORD=...             # 리포트 생성 잠금 (선택)
REPORT_MODEL=claude-opus-4-8 # 분석 모델 (선택, 기본 Opus)
```

---

## 알려진 제약

| 항목 | 내용 |
|------|------|
| Streamlit Cloud 디스크 | 휘발성. 앱에서 생성한 JSON은 Reboot·재배포 시 초기화. 영구 보관은 GitHub Actions에서 생성 후 저장소에 커밋하거나 `data/` · `reports/`를 저장소에 직접 추가. |
| 시세 지연 | yfinance 약 15분 지연, 새로고침 시 갱신. 실시간 아님. |
| 캘린더 실적일 | yfinance 추정이라 부정확할 수 있음 (특히 한국 종목). |
| AI 호출 자동화 | Claude.ai 구독으로 자동화 불가 (ToS 위반). 비용 절감은 Haiku→Opus 2단계 파이프라인으로 해결. |
| 키워드 중복 | 기사군이 겹치는 경우 코드 레벨에서 병합. 기사가 다르면서 의미만 같은 경우는 프롬프트 강화로 최소화하나 완전 제거 불가. |
