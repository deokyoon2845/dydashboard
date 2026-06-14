# DY Monitoring — 전략·시황 대시보드

한국 주식시장을 위한 **개인 투자 리서치 자동화 대시보드**. 텔레그램 애널리스트 채널의 시장 시각을 수집·분석하고, 글로벌 지수·키워드·시황 보고서를 한곳에서 본다.

> **한 줄 요약**: 텔레그램 시장 시각 + 정량 데이터 → AI 분석 → 전략·시황 보고서. 엔진(생성)과 뷰어(표시)를 분리한 풀스택 Streamlit 앱.

라이브: `https://dymonitoring.streamlit.app`

---

## 무엇을 하는가

매일 장전·장마감 후 두 번, 수십 개 증권사·애널리스트 텔레그램 채널의 메시지를 수집해 AI가 주제별로 분석한 **전략·시황 보고서**를 생성한다. 여기에 글로벌 지수 현황, 오늘의 키워드, 시황 타임라인을 더해 시장을 입체적으로 조망한다.

핵심 차별점은 **"시장 시각(채널 의견) vs 실제 데이터(정량)"의 교차 검증**과, 주제별 **합의/이견 분리**다. 단순 요약이 아니라 "무엇이 합의되고 무엇이 갈리는가"를 보여준다.

---

## 4개 탭

| 탭 | 내용 |
|----|------|
| **지수 현황** | 한국·미국·환율·원자재·암호화폐 지수, 공포·탐욕 지수, VIX, RSI, 경제 일정 캘린더 |
| **시황 (전략·시황 보고서)** | AI 생성 장전·장마감 보고서 (주제 카드: 사실·합의/이견·정량·시사점), 워치리스트, PDF/JSON 내보내기 |
| **오늘의 키워드** | 네이버 뉴스 기반 키워드 15개 + 관계 그래프(공통 종목·공통어로 키워드 연결), 카테고리·중요도·연속배지 |
| **타임라인** | 최근 5거래일 보고서 흐름(지그재그 타임라인), 감성 추세 차트, 예측 적중률 채점, 주간 다이제스트 |

---

## 기술 스택

- **프론트엔드**: Streamlit, Altair, 순수 SVG/CSS (미니멀 미스트 디자인 시스템)
- **데이터**: yfinance(글로벌 지수), pykrx(한국 시장·수급), CNN Fear & Greed API, 네이버 뉴스 API, Telegram(Telethon)
- **AI**: Anthropic API — Claude Haiku(1차 클러스터링) + Opus(2차 심층 분석)
- **기타**: pandas, python-dotenv, requests, reportlab(PDF)
- **배포**: Streamlit Cloud + GitHub (소스 연동)

---

## 아키텍처 한눈에

```
┌─────────────────┐         ┌──────────────────┐
│   engine/       │  생성    │   reports/*.json │
│  (데이터 생성)   │ ──────> │   data/*.json    │
│  로컬/Actions    │         │   (산출물 저장)   │
└─────────────────┘         └────────┬─────────┘
                                     │ 읽기
                            ┌────────▼─────────┐
                            │   modules/ + app.py │
                            │   (뷰어 = 표시 전용) │
                            │   Streamlit Cloud   │
                            └─────────────────────┘
```

**엔진과 뷰어를 엄격히 분리**한다. 엔진(`engine/`)은 텔레그램·API를 호출해 보고서·키워드 JSON을 만들어 저장하고, 뷰어(`app.py` + `modules/`)는 그 JSON을 읽어 그리기만 한다. 이 분리 덕에 Streamlit Cloud엔 무거운 생성 로직이 안 올라가고, 보고서 생성은 로컬이나 GitHub Actions에서 돈다.

자세한 구조는 [`ARCHITECTURE.md`](./ARCHITECTURE.md), 진행 상황은 [`HANDOFF.md`](./HANDOFF.md) 참고.

---

## 설치 · 실행

### 1. 의존성

```bash
pip install -r requirements.txt
```

### 2. 환경 변수 (`.env`)

```
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
NAVER_CLIENT_ID=...
NAVER_CLIENT_SECRET=...
```

### 3. 텔레그램 세션 로그인 (최초 1회)

```bash
python engine/telegram_login.py
```

### 4. 뷰어 실행 (로컬)

```bash
streamlit run app.py
```

### 5. 보고서 생성 (수동)

```bash
python engine/generate.py pre    # 장전 보고서
python engine/generate.py post   # 장마감 후 보고서
python engine/run_all.py         # 전체 파이프라인
```

> **참고**: Streamlit Cloud의 뷰어에서도 비밀번호(`APP_PASSWORD`) 인증 후 보고서 생성 버튼을 쓸 수 있다. 다만 정석 운영은 GitHub Actions 스케줄(평일 KST 07:50)로 자동 생성하고, 산출 JSON을 `reports/`에 커밋하는 방식이다.

---

## 운영 흐름 (일일)

1. **평일 07:50 (KST)** — GitHub Actions가 장전 보고서 생성 → `reports/`에 커밋
2. 뷰어가 새 JSON을 읽어 자동 반영 (타임라인·추세에도 반영)
3. **장마감 후** — 장마감 보고서 생성, 동일 흐름
4. 텔레그램 봇으로 PDF 발송 (선택)

---

## 디자인 시스템 — "미니멀 미스트"

- 배경 `#FCFCFA` · 카드 `#ffffff` · 잉크 `#34352f`
- sage 액센트 `#A7BBA9` / `#7E9A83`
- 상승 = 한국식 빨강 `#B65F5A` · 하락 = 파랑 `#5A7CA0`
- 폰트: Fraunces(제목 세리프) + Hanken Grotesk + Noto Sans KR
- 전역 마이크로 인터랙션 (카드 페이드인·호버 리프트·게이지 채우기·카운트업)

---

## 라이선스 · 주의

개인 투자 리서치 도구. 제공되는 모든 분석은 **투자 권유가 아니며**, AI 생성 내용은 오류를 포함할 수 있다. 보고서마다 원본 텔레그램 메시지를 동봉해 직접 검증할 수 있게 했다.
