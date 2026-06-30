# DY Monitoring — 주식·부동산 시장 모니터링 대시보드

한국 **주식시장과 부동산시장**을 한 화면에서 모니터링하는 개인 투자 리서치 자동화 대시보드. 증권사·애널리스트 텔레그램 채널의 시장 시각, 글로벌 지수·키워드·주도주·IPO, 그리고 전국 아파트 실거래·분양·지표를 한곳에 모았다.

> **한 줄 요약**: 시장 시각(텔레그램·뉴스) + 정량 데이터(지수·실거래·지표) → AI 분석 → 보고서·대시보드. 데이터를 만드는 **엔진**과 보여주는 **뷰어**를 분리한 풀스택 Streamlit 앱.

라이브: `https://dymonitoring.streamlit.app`

---

## 무엇을 하는가

매일 정해진 시각에 GitHub Actions가 각종 데이터(텔레그램 메시지, 증시 지수, 국토부 실거래, KB 가격지수, 청약홈 분양정보 등)를 수집하고, AI(Claude)가 시장 시각을 주제별로 분석한 **전략·시황 보고서**를 만든다. 수집·분석 결과는 모두 Supabase DB에 저장되고, Streamlit 뷰어가 그 DB를 읽어 **주식**과 **부동산** 두 개의 큰 탭으로 보여준다.

핵심 차별점은 두 가지다.

- **"시장 시각(채널 의견) vs 실제 데이터(정량)"의 교차 검증** — 단순 요약이 아니라, 무엇이 합의되고 무엇이 갈리는지(합의/이견)를 분리해 보여준다.
- **하나의 도구 안에서 주식과 부동산을 함께** — 같은 디자인 언어, 같은 데이터 파이프라인 위에서 두 시장을 나란히 본다.

> 제공되는 모든 분석은 **투자 권유가 아니다.** AI 생성 내용은 오류를 포함할 수 있으며, 보고서마다 원본 메시지를 동봉해 직접 검증할 수 있게 했다.

---

## 아키텍처 한눈에

```mermaid
flowchart LR
    subgraph SRC[데이터 소스]
        TG[텔레그램 채널]
        MKT[지수·수급·뉴스]
        RE[국토부·KB·청약홈·ECOS]
        IPOD[금융위·DART]
    end

    subgraph ENG["엔진 (GitHub Actions / 로컬)"]
        COL[수집] --> AI[Claude 분석<br/>Haiku 군집 → Opus 보고서]
    end

    subgraph DB[(Supabase)]
        T1[reports]
        T2[keywords]
        T3[leaders]
        T4[ipo_snapshots]
        T5[realestate_snapshots]
    end

    subgraph VIEW["뷰어 (Streamlit)"]
        S[주식 탭]
        R[부동산 탭]
    end

    SRC --> ENG --> DB --> VIEW
```

**엔진(생성)과 뷰어(표시)를 엄격히 분리**한다. 엔진은 각종 API·텔레그램을 호출해 데이터를 만들어 Supabase DB에 저장하고, 뷰어(Streamlit 앱)는 그 DB를 **읽어서 그리기만** 한다. 이 분리 덕분에 무거운 수집·분석 로직이 Streamlit Cloud에 올라가지 않고, 생성은 GitHub Actions 스케줄이나 로컬에서 돈다.

데이터 종류별로 Supabase 테이블이 나뉘어 있어 잡(job)끼리 충돌하지 않는다 — `reports`(보고서), `keywords`(키워드), `leaders`(주도주), `ipo_snapshots`(IPO), `realestate_snapshots`(부동산) 등.

> **왜 수집을 엔진에만 두는가**: Streamlit Cloud의 공인 IP에서는 KRX/pykrx·KB·네이버 일부 엔드포인트가 차단된다. 그래서 무거운 수집은 GitHub Actions(또는 로컬)에서만 돌리고, 뷰어는 Supabase만 읽는다. 클라우드에서 비교적 안정적으로 닿는 건 data.go.kr·MOLIT·KOSIS·ECOS·DART 직접 엔드포인트 정도다.

---

## 화면 구성

대시보드는 최상위에 **주식 / 부동산** 두 탭을 두고, 각 탭 안에 다시 서브탭을 둔다.

### 주식 (5개 서브탭)

| 서브탭 | 내용 | 주요 데이터 |
|--------|------|-------------|
| **지수** | 코스피·코스닥 현황, 수급 추세, 외국인·기관 순매수 상위 종목, 시장 폭(상승/하락 종목 비율), 섹터 등락, 공포·탐욕 지수·VIX·RSI, 미국·원자재·암호화폐 히트맵, 환율·금리·금리차, 경제 일정 캘린더 | yfinance, pykrx(엔진), CNN Fear&Greed |
| **시황** | AI가 생성한 장전·장마감 **전략·시황 보고서**(주제 카드: 사실·합의/이견·정량·시사점), 최근 5거래일 보고서 타임라인, 감성 추세, 예측 적중률 채점, PDF/JSON 내보내기 | 텔레그램 채널 + Claude |
| **주도주** | 전종목을 스캔해 주도 섹터·주도주를 점수화. 주도 점수 = 모멘텀·상대강도·추세지속성·유동성·신고가근접 가중합. 우선주·스팩·리츠·ETF 제외 | 네이버(종가) |
| **IPO** | 최근 2년 신규상장(시총 기준 컷)·향후 IPO 일정. 종목별 PER·PBR·PSR과 매출·영업이익·당기순이익(DART 최근 연간) | 금융위(data.go.kr), DART |
| **키워드** | 네이버 뉴스 기반 오늘의 키워드 + 관계 그래프(공통 종목·공통어로 키워드 연결), 카테고리·중요도·연속 배지, 관심 종목(워치리스트) 시세 | 네이버 뉴스 API |

### 부동산 (5개 서브탭)

| 서브탭 | 내용 | 주요 데이터 |
|--------|------|-------------|
| **지도** | 전국 아파트 가격지도 — 지역별 가격·변동을 지도 위에 표시, 주목 지역 워치리스트 밴드(매매급등·매매약세·거래급증·매매전세괴리) | KB 가격지수, 국토부 실거래 |
| **지표** | 부동산 사이클 위치, 선행/동행/수급·심리/펀더멘털 그룹별 지표, 카드별 신호·해석 | ECOS(한국은행), KB 등 |
| **주목단지** | 최근 거래가 몰린 상승 단지(세대수·시공사·소재지·실거래가) + 특이거래(신고가·신저가·급등락·거래량 급증). 국토부 실거래 기준, 직거래 기본 제외 | 국토부 실거래 |
| **분양** | 한국부동산원 청약홈 분양정보 — 청약 임박·진행 단지 우선 | 청약홈 |
| **키워드** | 부동산 뉴스 기반 키워드 분석(지역 화이트리스트·행정단위 정규화) | 네이버 뉴스 API |

---

## 데이터 소스 한눈에

| 분류 | 소스 | 쓰임 |
|------|------|------|
| 시장 시각 | 텔레그램(Telethon) | 증권사·애널리스트 채널 메시지 → 보고서 |
| 글로벌 지수 | yfinance | 미국·환율·원자재·암호화폐 |
| 국내 증시·수급 | pykrx (엔진 전용) | 코스피·코스닥·외국인/기관 수급 |
| 심리 지표 | CNN Fear & Greed | 공포·탐욕 지수 |
| 뉴스·키워드 | 네이버 뉴스 API | 오늘의 키워드, 관계 그래프 |
| 주도주 | 네이버 금융 | 전종목 종가 스캔 |
| IPO | 금융위 주식시세정보(data.go.kr), DART | 신규상장·재무·향후 일정 |
| 부동산 실거래 | 국토부(PublicDataReader / data.go.kr) | 실거래가·주목단지 |
| 부동산 가격지수 | KB 가격지수 | 가격지도·지표 |
| 부동산 분양 | 청약홈 | 분양정보 |
| 경제 통계 | ECOS(한국은행) | 부동산 선행/펀더멘털 지표 |
| AI 분석 | Anthropic Claude | 보고서·키워드 추출 |
| 저장소 | Supabase | 모든 산출물 DB 저장 |

---

## 자동화 스케줄 (GitHub Actions)

| 워크플로 | 실행 시각(KST) | 하는 일 |
|----------|---------------|---------|
| 부동산 실거래 수집 (`realestate.yml`) | 매일 07:07 | KB 가격지수·국토부 실거래·청약홈 분양 수집 → DB |
| 증시 IPO 수집 (`ipo.yml`) | 매일 06:07 | 최근 2년 상장·향후 IPO 수집 → DB |
| 종목 마스터 (`stock_master.yml`) | 매일 06:20 | KRX 종목 마스터 갱신 (T+1) |
| 주도주 수집 (`leaders.yml`) | 평일 17:30 | 전종목 스캔·주도주 점수화 → DB (장마감 후) |
| keepalive (`keepalive.yml`) | 매주 월 12:17 | 60일 무커밋 시 예약 워크플로 자동 비활성화 방지 |
| 전략·시황 보고서 (`daily.yml`) | **수동 전용** | 보고서·키워드 생성 + 예측 채점 + 텔레그램 발송 |

> 보고서는 자동 예약을 제거하고 **원할 때만** 만들도록 했다. 두 가지 수동 방법이 있다.
> 1. GitHub → Actions → 해당 워크플로 → **Run workflow** (전체 파이프라인 + 텔레그램 발송)
> 2. Streamlit 앱 → **시황** 탭 맨 아래 '🌅 장전 / 🌆 장마감 후 보고서 생성' 버튼 (DB 저장, 텔레그램 발송은 안 함)

---

## AI 파이프라인 & 비용

시황 보고서는 **2단계 파이프라인**으로 만든다.

1. **군집화 (Haiku)** — 텔레그램 원문 메시지를 주제별로 묶는다. (`CLUSTER_MAX_TOKENS` 기본 10,000)
2. **보고서 생성 (Opus)** — 묶인 주제를 받아 사실/합의·이견/정량/시사점 구조의 보고서를 쓴다. 출력이 길어 잘리면 이어받기(continuation)로 완성한다. (`REPORT_MAX_TOKENS` 기본 24,000)

키워드 탭(증시·부동산)은 **Haiku 단독**으로 추출한다(출력 한도 3,500).

비용이 드는 건 **Anthropic API 호출이 있는 탭뿐**이다. 인프라(Streamlit Cloud·Supabase·GitHub Actions)는 모두 무료 티어로 돌릴 수 있게 설계했다. 모델 단가와 호출별 예상 비용은 아래 「운영 비용」 절 참고.

| 환경변수 | 의미 | 기본값 |
|----------|------|--------|
| `REPORT_MODEL` | 보고서 생성 모델 | `claude-opus-4-8` |
| `CLUSTER_MAX_TOKENS` | Haiku 군집 출력 한도 | 10,000 |
| `REPORT_MAX_TOKENS` | Opus 보고서 출력 한도 | 24,000 |

---

## 기술 스택

- **프론트엔드**: Streamlit, Altair, 순수 SVG/CSS (미니멀 미스트 디자인 시스템)
- **데이터 수집**: yfinance, pykrx, PublicDataReader, requests, lxml, Telethon
- **AI**: Anthropic Claude (보고서·키워드 분석)
- **저장소**: Supabase
- **문서/기타**: pandas, reportlab(PDF), python-dotenv
- **배포·자동화**: Streamlit Cloud(뷰어) + GitHub Actions(엔진 스케줄)

---

## 설치 · 실행

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### 2. 환경 변수 (`.env` 또는 GitHub Secrets)

| 변수 | 용도 | 필수 |
|------|------|------|
| `ANTHROPIC_API_KEY` | Claude 분석 | ✅ |
| `SUPABASE_URL` / `SUPABASE_KEY` | DB 저장·조회 | ✅ |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` / `TELEGRAM_SESSION` | 채널 메시지 수집 | ✅(시황) |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` / `TELEGRAM_CHANNEL` | 보고서 텔레그램 발송 | 선택 |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | 뉴스·키워드 | ✅(키워드) |
| `ECOS_API_KEY` | 한국은행 경제통계(부동산 지표) | 선택 |
| `DATA_GO_KR_KEY` (또는 `MOLIT_API_KEY`) | 국토부·금융위 공공데이터 | ✅(부동산·IPO) |
| `DART_API_KEY` | IPO 재무·향후 일정 | 선택 |
| `REPORT_MODEL` | 보고서 모델 지정(기본값 있음) | 선택 |
| `APP_PASSWORD` | 뷰어에서 보고서 생성 잠금(소유자 전용) | 선택 |

### 3. 텔레그램 세션 로그인 (최초 1회)

```bash
python -m engine.telegram_login
```

### 4. 뷰어 실행 (로컬)

```bash
streamlit run app.py
```

### 5. 엔진 수동 실행

```bash
python -m engine.run_all          # 보고서 + 키워드 + 예측 채점 (+텔레그램)
python -m engine.realestate_run   # 부동산 실거래·분양 수집
python -m engine.ipo_run          # IPO 수집
python -m engine.leaders_run      # 주도주 수집
```

> Supabase는 최초 1회 테이블 생성이 필요하다(`modules/db.py` 상단의 SQL 참고).

---

## 운영 비용

| 항목 | 현재(Streamlit Cloud) | 비고 |
|------|----------------------|------|
| 뷰어 호스팅 | **₩0** | Streamlit Community Cloud 무료 |
| DB | **₩0** | Supabase 무료 티어 (일일 수집이 프로젝트를 깨워둠) |
| 스케줄러 | **₩0** | GitHub Actions 무료(퍼블릭/사적 사용 한도 내) |
| AI 분석 | **변동** | 보고서·키워드 생성 시에만 과금 |

AI 비용은 **보고서를 얼마나 자주 만드느냐**에 거의 전적으로 달려 있다. 키워드 탭은 Haiku라 호출당 몇 센트 수준으로 사실상 무시할 만하다. 자세한 호스팅 이전 비용 비교는 별도 메모 참고.

---

## 디자인 시스템 — "미니멀 미스트"

- 배경 `#FCFCFA` · 카드 `#ffffff` · 잉크 `#34352f`
- sage 액센트 `#A7BBA9` / `#7E9A83`
- 상승 = 한국식 빨강 `#B65F5A` · 하락 = 파랑 `#5A7CA0`
- 폰트: Fraunces(제목 세리프) + Hanken Grotesk + Noto Sans KR
- 주식·부동산 탭이 같은 액센트 바·제목·카드 스타일을 공유해 픽셀 단위로 통일

---

## 라이선스 · 주의

개인 투자 리서치 도구입니다. 제공되는 모든 분석은 **투자 권유가 아니며**, AI 생성 내용과 자동 수집 데이터는 오류·지연을 포함할 수 있습니다. 실제 투자 판단과 데이터 검증은 이용자 본인의 책임입니다.
