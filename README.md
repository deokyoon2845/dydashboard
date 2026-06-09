# 📊 시장 현황 대시보드

국내·해외 주요 지수, 텔레그램 채널 기반 AI 시황 분석 리포트, 오늘의 증시 키워드를
한 곳에서 보는 개인용 Streamlit 대시보드입니다.

## 주요 기능

- **📈 지수 현황** — 코스피·코스닥·S&P500·나스닥·다우·원/달러·VIX·금·WTI를 카드로 표시 (Yahoo Finance, 약 15분 지연)
- **📰 시황 리포트** — 텔레그램 채널의 *전일 00:00 ~ 지금* 메시지를 Claude로 분석해 보고서 생성. 키워드·기간으로 검색되는 아카이브, 토큰 사용량·예상 비용·잔액(추정) 포함
- **🔑 오늘의 키워드 Top10** — 네이버 뉴스 기반 오늘의 증시 키워드 + 관련 종목 + 실제 기사 링크

디자인: 미니멀 미스트(파스텔) · 등락색 한국식(상승 빨강 / 하락 파랑)

## 폴더 구조

```
my-market-dashboard/
├── app.py                  # 메인 앱 (탭 3개)
├── requirements.txt        # 필요한 라이브러리
├── .gitignore              # 깃 제외 목록 (.env 등)
├── .env.example            # 환경변수 템플릿 (이걸 복사해 .env 생성)
├── .streamlit/
│   └── config.toml         # 테마(색·폰트) 설정
├── modules/                # 화면(뷰어)
│   ├── __init__.py
│   ├── indices.py          # 지수 데이터
│   ├── reports.py          # 리포트 뷰 + 아카이브 검색
│   ├── keywords_view.py    # 오늘의 키워드 뷰
│   └── usage.py            # 비용 계산 + 사용량 로그
├── engine/                 # 데이터 생성(엔진) — 로컬에서 실행
│   ├── __init__.py
│   ├── telegram_login.py   # 최초 1회 텔레그램 로그인
│   ├── fetch_telegram.py   # 채널 메시지 수집
│   ├── analyze.py          # Claude 시황 분석
│   ├── generate.py         # 리포트 생성 통합 로직
│   ├── news.py             # 네이버 뉴스 수집
│   ├── keywords.py         # 오늘의 키워드 추출
│   └── run_report.py       # CLI로 리포트 생성
├── reports/                # 생성된 리포트(.md)가 쌓이는 곳 (= 아카이브)
└── data/                   # 사용량 로그·키워드 캐시
```

> design_concepts.html / report_layouts.html / keyword_layouts.html 은 디자인 고를 때 쓴
> 미리보기 파일이라 앱 동작과 무관합니다. 지워도 됩니다.

## 시작하기

### 1. 라이브러리 설치

```bash
pip install -r requirements.txt
```

가상환경은 필수가 아닙니다(써도 좋음).

### 2. 환경변수 설정

`.env.example` 을 복사해 같은 폴더에 **`.env`** 로 저장하고 값을 채웁니다.

| 변수 | 설명 | 발급처 |
|------|------|--------|
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | 텔레그램 API 키 | my.telegram.org |
| `TELEGRAM_SESSION` | 로그인 세션 문자열 | `telegram_login.py` 실행 결과 |
| `TELEGRAM_CHANNEL` | 분석할 채널 (`@아이디`) | — |
| `ANTHROPIC_API_KEY` | Claude API 키 | console.anthropic.com |
| `ANTHROPIC_BUDGET_KRW` | 총 예산(원), 잔액 표시용 (선택) | — |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | 네이버 뉴스 검색 API | developers.naver.com |

### 3. 텔레그램 최초 로그인 (1회만)

```bash
python engine/telegram_login.py
```

전화번호(+82…) → 인증코드 입력 → 출력된 세션 문자열을 `.env` 의 `TELEGRAM_SESSION` 에 붙여넣기.

### 4. 실행

```bash
streamlit run app.py
```

브라우저에서 `localhost:8501` 이 열립니다.

## 사용법

- **지수 현황**: 자동 표시. "새로고침"으로 최신화
- **시황 리포트**: "📝 리포트 생성" → 전일 00:00~지금 메시지 분석·저장. 검색창·기간으로 과거 리포트 찾기. 하단에 토큰·비용·잔액
- **오늘의 키워드**: "🔄 키워드 갱신" → 뉴스 기반 Top10. 기사 제목(↗) 클릭 시 실제 기사로 이동

## 인터넷에 올리기 (배포)

1. GitHub Desktop 등으로 코드를 GitHub 저장소에 올림
2. share.streamlit.io 에서 그 저장소를 연결해 배포
3. 작동 방식
   - **로컬(내 컴퓨터)**: 생성 버튼 포함 모든 기능 사용 → 여기서 리포트·키워드를 만듦
   - **클라우드(배포 링크)**: 보기·공유 전용. 생성 버튼은 키가 없어 동작하지 않음(정상)
   - 새로 만든 결과를 클라우드에도 보이게 하려면: **로컬 생성 → GitHub에 Push → 클라우드 자동 반영**

## ⚠️ 보안 · 주의

- **`.env` 는 절대 GitHub에 올리지 마세요.** `.gitignore` 가 자동으로 막아둠
- 텔레그램 세션 문자열·API 키는 비밀번호급. 공유 금지
- 비용·잔액은 **토큰 단가 기반 추정치**입니다. 실제 청구는 Anthropic 콘솔(Billing)에서 확인
- Yahoo Finance 데이터는 지연되며, 클라우드 환경에서 일시 차단될 수 있음
- 본 도구는 **정보 정리용이며 투자 권유가 아닙니다**

## 🛠 기술 스택

Streamlit · yfinance · Telethon · Claude API(Anthropic) · 네이버 뉴스 검색 API

## 💡 앞으로 개선하면 좋은 것 (선택)

- `requirements.txt` 라이브러리 버전 고정 → 배포 안정성↑
- 클라우드에 비밀키(Secrets) 설정 → 클라우드에서도 '키워드 갱신' 가능
- `data/usage_log.json` 을 깃에 커밋 → 기기 간 잔액 공유
- 텔레그램 메시지 기반 키워드도 함께 반영
