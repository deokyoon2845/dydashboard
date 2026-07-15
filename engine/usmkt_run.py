# -*- coding: utf-8 -*-
"""[엔진] 미국 전일 시장 수집 → Supabase(usmkt_snapshots) 저장.

글로벌 탭 '미국 전일 시장' 섹션의 데이터 소스. 설계 근거: engine/usmkt_probe
(2026-07-15 실측 — ETF 11종 0.6초 · 120종 배치 5.4초 · fast_info 시총 50종 ≈9초 ·
 야후 .news / 네이버 뉴스 API 모두 Actions IP에서 정상).

수집 내용(payload):
  sectors  SPDR 섹터 ETF 11종 — 전일 등락률(+5일) · 폴백/참고용 유지
  groups   유니버스 120종 → 산업군 23그룹 재분류 — 동일가중 평균 등락(2026-07 · 메인 표시)
  top50    시총 상위 50 — fast_info 라이브 시총으로 매일 재랭킹(정적 순서 아님).
           시총은 달러(십억 $)와 원화(조원) 병기 — 원화는 당일 KRW=X 환율로 환산.
  movers   유니버스(120종) 내 상승/하락 Top5
  issues   |전일 등락| ≥ 4% 이슈 종목(최대 12) + 이슈 전 종목의 뉴스(네이버 한글 우선,
           제목에 종목명 포함 기사만 채택 · 부족하면 야후 영문 보충, 야후도 제목에
           티커가 있어야 채택 — 둘 다 무관 기사를 섞어 주기 때문)

데이터 품질 가드(probe에서 확인된 함정):
  · |등락| > 20%는 값을 보존한 채 suspect 표시만(실제 폭락을 지우지 않기 위해)
  · 상장폐지/티커 변경(예: FI 404)은 배치에서 자동 결측 → 조용히 스킵
  · 휴장일엔 직전 거래일 봉이 그대로 오므로 payload에 trade_date를 실어
    뷰어가 '기준일'을 표시(값 중복 저장은 무해 · asof_date는 KST 날짜)

멱등: collected_today('usmkt_snapshots') — 멀티슬롯 크론(07:20/08:20 KST)이
  두 번 돌아도 당일 1회만 수집. FORCE_COLLECT=1로 무시 가능.

필요 환경변수: SUPABASE_URL, SUPABASE_KEY
  (선택) NAVER_CLIENT_ID/NAVER_CLIENT_SECRET — 없으면 뉴스는 야후 영문만.
"""
import os
import re
import time
from datetime import datetime

import requests

try:
    from zoneinfo import ZoneInfo
    _KST = ZoneInfo("Asia/Seoul")
except Exception:
    _KST = None

# ── 업종: SPDR 섹터 ETF 11종(미국 업종 표준) ─────────────────────────────────
SECTOR_ETFS = [
    ("기술", "XLK"), ("금융", "XLF"), ("헬스케어", "XLV"), ("경기소비재", "XLY"),
    ("필수소비재", "XLP"), ("에너지", "XLE"), ("산업재", "XLI"), ("소재", "XLB"),
    ("리츠", "XLRE"), ("유틸리티", "XLU"), ("커뮤니케이션", "XLC"),
]

# ── 유니버스 120종 {티커: 한글명} — 뉴스 검색·표시 공용.
#    시총 순위는 매일 fast_info로 재랭킹하므로 여기 '순서'는 의미 없음.
#    티커 변경/상폐는 배치 결측으로 자동 스킵되니 연 1~2회만 손질하면 된다.
UNIVERSE = {
    # 메가캡(시총 랭킹 후보군 포함)
    "NVDA": "엔비디아", "MSFT": "마이크로소프트", "AAPL": "애플",
    "GOOGL": "알파벳", "AMZN": "아마존", "META": "메타", "AVGO": "브로드컴",
    "TSLA": "테슬라", "BRK-B": "버크셔해서웨이", "LLY": "일라이릴리",
    "WMT": "월마트", "JPM": "JP모건", "V": "비자", "ORCL": "오라클",
    "MA": "마스터카드", "XOM": "엑슨모빌", "COST": "코스트코",
    "NFLX": "넷플릭스", "PG": "P&G", "JNJ": "존슨앤드존슨", "HD": "홈디포",
    "ABBV": "애브비", "BAC": "뱅크오브아메리카", "KO": "코카콜라",
    "PLTR": "팔란티어", "CRM": "세일즈포스", "UNH": "유나이티드헬스",
    "CVX": "셰브런", "TMUS": "T모바일", "WFC": "웰스파고", "CSCO": "시스코",
    "PM": "필립모리스", "MS": "모건스탠리", "IBM": "IBM", "ABT": "애보트",
    "AMD": "AMD", "GE": "GE에어로스페이스", "LIN": "린데", "MCD": "맥도날드",
    "AXP": "아메리칸익스프레스", "DIS": "디즈니", "NOW": "서비스나우",
    "MRK": "머크", "GS": "골드만삭스", "ISRG": "인튜이티브서지컬",
    "T": "AT&T", "UBER": "우버", "INTU": "인튜이트", "PEP": "펩시코",
    "TXN": "텍사스인스트루먼트",
    # 대형(이슈 스캔 확장분)
    "QCOM": "퀄컴", "BKNG": "부킹홀딩스", "AMGN": "암젠", "CAT": "캐터필러",
    "ADBE": "어도비", "SPGI": "S&P글로벌", "BSX": "보스턴사이언티픽",
    "SYK": "스트라이커", "BLK": "블랙록", "NEE": "넥스트에라에너지",
    "DHR": "다나허", "HON": "허니웰", "TJX": "TJX", "PGR": "프로그레시브",
    "PFE": "화이자", "C": "씨티그룹", "UNP": "유니언퍼시픽",
    "GILD": "길리어드", "CMCSA": "컴캐스트", "LOW": "로우스",
    "SCHW": "찰스슈왑", "ADP": "ADP", "DE": "디어", "COP": "코노코필립스",
    "BMY": "브리스톨마이어스", "MU": "마이크론", "ANET": "아리스타네트웍스",
    "VRTX": "버텍스", "LMT": "록히드마틴", "SBUX": "스타벅스",
    "MDT": "메드트로닉", "BA": "보잉", "PANW": "팔로알토", "KKR": "KKR",
    "PLD": "프로로지스", "AMAT": "어플라이드머티어리얼즈", "SO": "서던컴퍼니",
    "NKE": "나이키", "ICE": "인터컨티넨털익스체인지", "ELV": "엘레번스헬스",
    "UPS": "UPS", "MO": "알트리아", "SHW": "셔윈윌리엄스", "APH": "암페놀",
    "CME": "CME그룹", "DUK": "듀크에너지", "AON": "에이온",
    "WM": "웨이스트매니지먼트", "MCO": "무디스", "CL": "콜게이트",
    "TT": "트레인테크놀로지스", "ABNB": "에어비앤비", "CTAS": "신타스",
    "MMM": "3M", "GD": "제너럴다이내믹스", "ITW": "일리노이툴웍스",
    "EQIX": "에퀴닉스", "CVS": "CVS헬스", "APD": "에어프로덕츠",
    "ORLY": "오라일리", "CRWD": "크라우드스트라이크", "MRVL": "마벨테크놀로지",
    "SNPS": "시놉시스", "CDNS": "케이던스", "FTNT": "포티넷",
    "MELI": "메르카도리브레", "PYPL": "페이팔", "ETN": "이튼",
    "PH": "파커하니핀", "INTC": "인텔", "MMC": "마시앤드맥레넌",
}

# 시총 랭킹 후보(fast_info 개별 콜 대상 — 60종 ≈ 11초). Top50이 이 안에서 나온다.
_MCAP_CANDIDATES = list(UNIVERSE)[:50] + [
    "QCOM", "BKNG", "AMGN", "CAT", "ADBE", "SPGI", "BLK", "NEE", "INTC", "MU",
]

# ── 산업군 재분류 (2026-07) — 유니버스 120종을 ~23개 산업군으로 정적 매핑.
#    업종 바 차트가 SPDR 11섹터 ETF 대신 이 재분류의 '동일가중 평균 등락'을 쓴다.
#    동일가중인 이유: 시총가중은 NVDA 하나가 반도체를 지배해 업종 정보가 죽는다.
#    티커 추가/삭제 시 UNIVERSE와 함께 여기도 갱신(누락은 ci 테스트가 잡는다).
INDUSTRY_GROUPS = {
    "반도체": ["NVDA", "AVGO", "AMD", "TXN", "QCOM", "MU", "INTC",
               "AMAT", "MRVL", "SNPS", "CDNS"],
    "소프트웨어": ["MSFT", "ORCL", "CRM", "NOW", "INTU", "ADBE", "PLTR"],
    "사이버보안": ["PANW", "CRWD", "FTNT"],
    "인터넷·플랫폼": ["GOOGL", "AMZN", "META", "NFLX", "UBER", "ABNB",
                      "BKNG", "MELI"],
    "IT하드웨어·네트워크": ["AAPL", "CSCO", "IBM", "ANET", "APH"],
    "은행": ["JPM", "BAC", "WFC", "C", "GS", "MS", "SCHW"],
    "결제·핀테크": ["V", "MA", "AXP", "PYPL"],
    "금융투자·거래소": ["BRK-B", "BLK", "KKR", "SPGI", "ICE", "CME", "MCO"],
    "보험": ["PGR", "MMC", "AON"],
    "제약·바이오": ["LLY", "JNJ", "ABBV", "MRK", "PFE", "BMY", "AMGN",
                    "GILD", "VRTX"],
    "의료기기·헬스서비스": ["ABT", "ISRG", "BSX", "SYK", "MDT", "DHR",
                            "UNH", "ELV", "CVS"],
    "필수소비재": ["PG", "KO", "PEP", "PM", "MO", "CL"],
    "소매·유통": ["WMT", "COST", "HD", "LOW", "TJX", "ORLY"],
    "외식·소비브랜드": ["MCD", "SBUX", "NKE"],
    "자동차": ["TSLA"],
    "미디어·통신": ["DIS", "CMCSA", "T", "TMUS"],
    "에너지": ["XOM", "CVX", "COP"],
    "항공우주·방산": ["GE", "BA", "LMT", "GD"],
    "기계·산업재": ["CAT", "DE", "HON", "ETN", "PH", "ITW", "MMM", "TT"],
    "산업서비스·운송": ["UNP", "UPS", "WM", "CTAS", "ADP"],
    "소재·화학": ["LIN", "SHW", "APD"],
    "유틸리티": ["NEE", "SO", "DUK"],
    "리츠": ["PLD", "EQIX"],
}

ISSUE_TH = 4.0      # |전일 등락%| ≥ 이 값 → 이슈 종목
ISSUE_MAX = 12      # 이슈 카드 최대 개수
GLITCH_TH = 20.0    # |등락| > 이 값 → 의심 표시(값은 보존 — 아래 _flag_glitch 참고)
# 뉴스는 이슈 전체에 대해 수집한다. 예전엔 8종만 받아서 9~12위 카드에 '관련 기사 없음'이
# 떴는데, 기사가 없는 게 아니라 안 받은 것이라 거짓 표기였다. 둘을 같은 수로 묶는다.
NEWS_MAX_STOCKS = ISSUE_MAX
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def _now_kst():
    return datetime.now(_KST) if _KST else datetime.now()


# ── 시세 수집 ─────────────────────────────────────────────────────────────────
def _batch(tickers):
    """yf.download 배치 → ({티커:{close,chg,chg5}}, trade_date). 결측 자동 스킵."""
    import yfinance as yf
    df = yf.download(tickers=" ".join(tickers), period="7d", interval="1d",
                     group_by="ticker", auto_adjust=True, progress=False,
                     threads=True)
    out, tdate = {}, None
    for t in tickers:
        try:
            s = df[t]["Close"].dropna() if len(tickers) > 1 else df["Close"].dropna()
            if len(s) < 2:
                continue
            c, p = float(s.iloc[-1]), float(s.iloc[-2])
            row = {"close": round(c, 2), "chg": round((c / p - 1) * 100, 2)}
            if len(s) >= 6:
                row["chg5"] = round((c / float(s.iloc[-6]) - 1) * 100, 2)
            out[t] = row
            d = s.index[-1]
            d = d.date().isoformat() if hasattr(d, "date") else str(d)[:10]
            tdate = max(tdate, d) if tdate else d
        except Exception:
            continue
    return out, tdate


def _spark_batch(tickers, points=30):
    """Top50용 3개월 종가 스파크 — 배치 1회(≈5초). {티커: [float×~30]}.
    ~63개 일봉을 균등 다운샘플(마지막 포함)해 payload를 가볍게 유지한다.
    실패 종목은 생략 — 뷰어가 스파크 없이 타일만 그린다(무회귀)."""
    import yfinance as yf
    out = {}
    try:
        df = yf.download(tickers=" ".join(tickers), period="3mo", interval="1d",
                         group_by="ticker", auto_adjust=True, progress=False,
                         threads=True)
    except Exception as e:
        print(f"[usmkt] 스파크 배치 실패: {e}")
        return out
    for t in tickers:
        try:
            s = df[t]["Close"].dropna() if len(tickers) > 1 else df["Close"].dropna()
            n = len(s)
            if n < 5:
                continue
            k = min(points, n)
            idx = [round(i * (n - 1) / (k - 1)) for i in range(k)]
            out[t] = [round(float(s.iloc[i]), 2) for i in idx]
        except Exception:
            continue
    return out


def _usdkrw():
    """원/달러 환율 — 시총 원화 병기용. 배치 시세와 같은 소스(yfinance)라 추가 의존 없음.
    실패 시 None → 뷰어가 달러만 표시(무회귀)."""
    try:
        import yfinance as yf
        s = yf.download(tickers="KRW=X", period="5d", interval="1d",
                        auto_adjust=True, progress=False)["Close"].dropna()
        if len(s):
            return round(float(s.iloc[-1]), 2)
    except Exception as e:
        print(f"[usmkt] 환율 조회 실패: {e}")
    return None


def _fast_info(t):
    """fast_info dict — 신/구 키 모두 대응. 실패 시 {}."""
    import yfinance as yf
    try:
        fi = yf.Ticker(t).fast_info
        return {"mcap": fi.get("marketCap") or fi.get("market_cap"),
                "last": fi.get("lastPrice") or fi.get("last_price"),
                "prev": fi.get("previousClose") or fi.get("previous_close")
                        or fi.get("regularMarketPreviousClose")}
    except Exception:
        return {}


def _flag_glitch(t, row):
    """|등락|>20%는 '의심' 표시만 하고 값은 절대 건드리지 않는다.

    이전 버전은 fast_info와 5%p 이상 어긋나면 자동 교정했는데, 이는 실제 폭락을
    조용히 지워버릴 수 있다(실측: IBM이 실적 프리어나운스로 하루 −25% 마감 —
    분할 글리치가 아니라 진짜였고, 그런 날이야말로 이슈 카드에 떠야 한다).
    판단은 사람이 하도록 원본 수치를 보존하고 뷰어에 '?' 배지만 띄운다.
    fast_info 대조는 로그로만 남겨 사후 확인을 돕는다.
    """
    if abs(row.get("chg") or 0) <= GLITCH_TH:
        return row
    row["suspect"] = True
    fi = _fast_info(t)
    try:
        rc = (float(fi["last"]) / float(fi["prev"]) - 1) * 100
        note = f"실시간 대조 {rc:+.1f}%" + (" (일치)" if abs(rc - row["chg"]) <= 5
                                        else " ⚠️ 불일치 — 분할/데이터오류 가능")
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        note = "실시간 대조 불가"
    print(f"[usmkt] {t} 등락 {row['chg']:+.1f}% — 의심 표시(값 보존) · {note}")
    return row


# ── 뉴스 ─────────────────────────────────────────────────────────────────────
def _clean(s):
    return re.sub(r"<[^>]+>", "", str(s or "")).replace("&quot;", '"').strip()


def _naver_news(kname, limit=3):
    """네이버 뉴스 검색 — 제목에 종목명이 실제 포함된 기사만(probe에서 시황기사
    혼입 확인 → 제목 필터 필수). 시크릿 없으면 []."""
    cid = os.environ.get("NAVER_CLIENT_ID", "").strip()
    sec = os.environ.get("NAVER_CLIENT_SECRET", "").strip()
    if not (cid and sec):
        return []
    try:
        r = requests.get("https://openapi.naver.com/v1/search/news.json",
                         params={"query": kname, "display": 10, "sort": "date"},
                         headers={"X-Naver-Client-Id": cid,
                                  "X-Naver-Client-Secret": sec}, timeout=10)
        items = r.json().get("items", []) if r.ok else []
    except Exception as e:
        print(f"[usmkt] 네이버 뉴스 '{kname}' 실패: {e}")
        return []
    out = []
    for it in items:
        title = _clean(it.get("title"))
        if kname not in title:
            continue
        out.append({"t": title[:90], "u": it.get("link") or it.get("originallink"),
                    "src": "네이버", "when": (it.get("pubDate") or "")[:16]})
        if len(out) >= limit:
            break
    return out


# 흔한 영단어와 철자가 겹치는 티커 — 제목에 그냥 등장했다고 종목 기사로 보면 안 된다.
# ("Buy This Stock NOW" ≠ 서비스나우) → 괄호·$·콤마 나열 등 '티커스러운' 문맥일 때만 인정.
_AMBIG_TK = {"V", "MA", "T", "C", "GE", "MU", "NOW", "SO", "DE", "CAT",
             "ICE", "PM", "MS", "ALL", "KEY", "ON", "IT"}


def _title_has_ticker(tk, title):
    """제목이 이 종목을 실제로 다루는가 — 티커 토큰이 있어야 인정(대소문자 구분).

    야후 .news는 종목 페이지의 '관련 기사'까지 섞어 준다(실측: 마벨 요청에 브로드컴
    기사, 오라클 요청에 IBM 기사). 네이버와 동일하게 제목 필터를 걸어 오배치를 막는다.
    영문 사명은 표기 흔들림이 커서(Alphabet/Google 등) 티커 토큰만 신뢰한다.
    """
    if not re.search(rf"(?<![A-Za-z0-9]){re.escape(tk)}(?![A-Za-z0-9])", title):
        return False
    if tk not in _AMBIG_TK:
        return True
    return bool(re.search(rf"[($]{re.escape(tk)}\)?|{re.escape(tk)}(?=\s*[,:])", title))


def _yahoo_news(ticker, limit=2):
    """야후 종목 뉴스(영문) — 네이버가 비었을 때 보충. 제목에 티커가 있는 기사만."""
    import yfinance as yf
    try:
        ns = yf.Ticker(ticker).news or []
    except Exception:
        return []
    out = []
    for n in ns:
        c = n.get("content") or n                  # 신/구 스키마
        title = _clean(c.get("title"))
        url = c.get("canonicalUrl")
        url = url.get("url") if isinstance(url, dict) else (url or c.get("link"))
        if not (title and url):
            continue
        if not _title_has_ticker(ticker, title):   # 무관 기사 배제
            continue
        prov = c.get("provider")
        prov = (prov.get("displayName") if isinstance(prov, dict) else prov) or "Yahoo"
        out.append({"t": title[:90], "u": url, "src": str(prov)[:20],
                    "when": _clean(c.get("pubDate"))[:10]})
        if len(out) >= limit:
            break
    return out


# ── 수집 본체 ─────────────────────────────────────────────────────────────────
def collect():
    t0 = time.time()
    # 1) 업종 ETF
    etf_px, tdate = _batch([tk for _, tk in SECTOR_ETFS])
    sectors = [{"nm": nm, "tk": tk, **etf_px[tk]}
               for nm, tk in SECTOR_ETFS if tk in etf_px]
    print(f"[usmkt] 업종 {len(sectors)}/11 · 기준일 {tdate}")

    # 2) 유니버스 배치 + 글리치 가드
    px, td2 = _batch(list(UNIVERSE))
    tdate = max(tdate or "", td2 or "") or None
    for t in list(px):
        px[t] = _flag_glitch(t, px[t])
    print(f"[usmkt] 유니버스 {len(px)}/{len(UNIVERSE)}종")

    # 2.5) 산업군 재분류(23그룹) — 유니버스 등락의 동일가중 평균(추가 API 0).
    #      시세 결측 종목은 그룹 평균에서 자동 제외 · 산출 종목 수(n)를 함께 저장.
    groups = []
    for gnm, tks in INDUSTRY_GROUPS.items():
        chgs = [px[t]["chg"] for t in tks if t in px]
        if not chgs:
            continue
        groups.append({"nm": gnm, "chg": round(sum(chgs) / len(chgs), 2),
                       "n": len(chgs)})
    groups.sort(key=lambda g: g["chg"], reverse=True)
    print(f"[usmkt] 산업군 {len(groups)}/{len(INDUSTRY_GROUPS)}그룹 (동일가중)")

    # 3) 시총 Top50 — fast_info 라이브 랭킹
    mcaps = {}
    for t in _MCAP_CANDIDATES:
        if t not in px:
            continue
        mc = _fast_info(t).get("mcap")
        if mc:
            mcaps[t] = float(mc)
    fx = _usdkrw()          # 원/달러 — 원화 시총 병기용(없으면 달러만)
    top50 = []
    for t in sorted(mcaps, key=mcaps.get, reverse=True)[:50]:
        row = {"tk": t, "nm": UNIVERSE[t],
               "mcap_b": round(mcaps[t] / 1e9),        # 십억 달러
               **px[t]}
        if fx:                                          # 조원 = 달러시총 × 환율 ÷ 1e12
            row["mcap_kj"] = round(mcaps[t] * fx / 1e12, 1)
        top50.append(row)
    print(f"[usmkt] 시총 랭킹 {len(mcaps)}종 조회 → Top{len(top50)} · "
          f"환율 {fx if fx else '실패(달러만)'}")

    # 3.5) Top50 3개월 스파크(타일 미니차트) — 배치 1회 · 실패 종목은 생략.
    sparks = _spark_batch([r["tk"] for r in top50])
    for r in top50:
        if r["tk"] in sparks:
            r["sp"] = sparks[r["tk"]]
    print(f"[usmkt] 스파크 {len(sparks)}/{len(top50)}종")

    # 4) 상승/하락 Top5 + 이슈
    ranked = sorted(px.items(), key=lambda kv: kv[1]["chg"])
    mk = lambda t, r: {"tk": t, "nm": UNIVERSE[t], **r}
    movers = {"up": [mk(t, r) for t, r in ranked[::-1][:5]],
              "dn": [mk(t, r) for t, r in ranked[:5]]}
    issues = [mk(t, r) for t, r in
              sorted(px.items(), key=lambda kv: -abs(kv[1]["chg"]))
              if abs(r["chg"]) >= ISSUE_TH][:ISSUE_MAX]

    # 5) 이슈 종목 뉴스(상위 8종) — 네이버 한글 우선, 부족하면 야후 보충
    for it in issues[:NEWS_MAX_STOCKS]:
        news = _naver_news(it["nm"])
        if len(news) < 2:
            news += _yahoo_news(it["tk"], limit=2 if not news else 1)
        it["news"] = news
        time.sleep(0.15)                           # 네이버 QPS 예의
    print(f"[usmkt] 이슈 {len(issues)}종 · 뉴스 수집 "
          f"{sum(1 for i in issues if i.get('news'))}종 · {time.time()-t0:.0f}초")

    now = _now_kst()
    return {"asof": now.strftime("%Y-%m-%d %H:%M"),
            "asof_date": now.date().isoformat(),
            "trade_date": tdate, "usdkrw": fx,
            "sectors": sectors, "groups": groups, "top50": top50,
            "movers": movers, "issues": issues}


def main():
    from modules.db import save_usmkt, collected_today
    force = os.environ.get("FORCE_COLLECT", "").strip() == "1"
    if not force and collected_today("usmkt_snapshots"):
        print("[usmkt] 오늘 이미 수집됨 — 건너뜀 (FORCE_COLLECT=1로 무시 가능)")
        return
    if force:
        print("[usmkt] FORCE_COLLECT — 멱등 가드 무시하고 당일 재수집.")
    payload = collect()
    if not payload.get("sectors") and not payload.get("top50"):
        raise RuntimeError("usmkt: 업종·Top50 모두 비어 있음 — 저장 중단(조용한 실패 방지)")
    save_usmkt(payload)
    print(f"[usmkt] Supabase 저장 완료: asof_date={payload['asof_date']} "
          f"(거래 기준일 {payload['trade_date']})")


if __name__ == "__main__":
    main()
