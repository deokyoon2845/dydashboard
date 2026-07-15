# -*- coding: utf-8 -*-
"""usmkt_probe — 글로벌 탭 '미국 전일 시장' 수집 설계 실측 (GitHub Actions IP).

검증 항목
  [1] SPDR 섹터 ETF 11종 배치(yf.download) → 전일 등락률 산출 가능?
  [2] 시총 Top50 배치 다운로드 → 소요시간·결측 티커
  [3] fast_info 시총 — 개별 콜 속도(라이브 시총 랭킹 가능성 판단)
  [4] yfinance .news — Actions IP에서 뉴스 응답 구조·건수
  [5] 네이버 뉴스 검색 API — 한글 종목명 검색 품질(시크릿 필요)
  [6] 120종 배치 타이밍 — S&P500 전체 스캔(500종) 소요 외삽

판정 가이드는 맨 아래 출력. 이 결과로 본구현(usmkt_collect)의
유니버스 크기·뉴스 소스·시총 랭킹 방식을 확정한다.
"""
import os
import time

import requests
import yfinance as yf

# ── 유니버스 ────────────────────────────────────────────────────────────────
SECTOR_ETFS = {  # SPDR 섹터 11종 — 미국 업종 표준
    "기술": "XLK", "금융": "XLF", "헬스케어": "XLV", "경기소비재": "XLY",
    "필수소비재": "XLP", "에너지": "XLE", "산업재": "XLI", "소재": "XLB",
    "리츠": "XLRE", "유틸리티": "XLU", "커뮤니케이션": "XLC",
}
TOP50 = [  # 시총 상위권(2026 중반 근사 · 본구현에서 확정)
    "NVDA", "MSFT", "AAPL", "GOOGL", "AMZN", "META", "AVGO", "TSLA",
    "BRK-B", "LLY", "WMT", "JPM", "V", "ORCL", "MA", "XOM", "COST",
    "NFLX", "PG", "JNJ", "HD", "ABBV", "BAC", "KO", "PLTR", "CRM",
    "UNH", "CVX", "TMUS", "WFC", "CSCO", "PM", "MS", "IBM", "ABT",
    "AMD", "GE", "LIN", "MCD", "AXP", "DIS", "NOW", "MRK", "GS",
    "ISRG", "T", "UBER", "INTU", "PEP", "TXN",
]
EXTRA70 = [  # [6] 타이밍 외삽용 추가분(중대형 유동주)
    "QCOM", "BKNG", "AMGN", "CAT", "ADBE", "SPGI", "BSX", "SYK", "BLK",
    "NEE", "DHR", "HON", "TJX", "PGR", "PFE", "C", "UNP", "GILD", "CMCSA",
    "LOW", "SCHW", "FI", "ADP", "DE", "COP", "BMY", "MU", "ANET", "VRTX",
    "LMT", "SBUX", "MDT", "BA", "PANW", "KKR", "PLD", "AMAT", "SO", "MMC",
    "NKE", "ICE", "ELV", "UPS", "MO", "SHW", "APH", "CME", "DUK", "AON",
    "WM", "MCO", "CL", "TT", "ABNB", "CTAS", "MMM", "GD", "ITW", "EQIX",
    "CVS", "APD", "ORLY", "CRWD", "MRVL", "SNPS", "CDNS", "FTNT", "MELI",
    "PYPL",
]


def _dl(tickers, label):
    """yf.download 배치 → (DataFrame, 소요초). 실패 시 (None, 초)."""
    t0 = time.time()
    try:
        df = yf.download(tickers=" ".join(tickers), period="5d",
                         interval="1d", group_by="ticker",
                         auto_adjust=True, progress=False, threads=True)
        return df, time.time() - t0
    except Exception as e:
        print(f"    ✗ {label} 배치 실패: {e}")
        return None, time.time() - t0


def _chg_map(df, tickers):
    """배치 결과 → {티커: (종가, 전일대비%)}. 2봉 미만 티커는 제외."""
    out = {}
    for t in tickers:
        try:
            sub = df[t]["Close"].dropna() if len(tickers) > 1 else df["Close"].dropna()
            if len(sub) >= 2:
                c, p = float(sub.iloc[-1]), float(sub.iloc[-2])
                out[t] = (round(c, 2), round((c / p - 1) * 100, 2))
        except Exception:
            continue
    return out


print("=" * 76)
print("usmkt_probe — 미국 전일 시장(업종 ETF·시총 Top50·이슈 종목 뉴스) 실측")
print("=" * 76)

# [1] 섹터 ETF ---------------------------------------------------------------
print("\n[1] SPDR 섹터 ETF 11종 배치")
df, sec = _dl(list(SECTOR_ETFS.values()), "ETF")
if df is not None:
    m = _chg_map(df, list(SECTOR_ETFS.values()))
    print(f"    OK {len(m)}/11종 · {sec:.1f}초")
    for nm, tk in list(SECTOR_ETFS.items())[:4]:
        if tk in m:
            print(f"      {nm}({tk}): {m[tk][0]} ({m[tk][1]:+.2f}%)")

# [2] Top50 ------------------------------------------------------------------
print("\n[2] 시총 Top50 배치")
df50, sec = _dl(TOP50, "Top50")
m50 = {}
if df50 is not None:
    m50 = _chg_map(df50, TOP50)
    miss = [t for t in TOP50 if t not in m50]
    print(f"    OK {len(m50)}/50종 · {sec:.1f}초 · 결측={miss or '없음'}")
    mv = sorted(m50.items(), key=lambda kv: kv[1][1])
    print(f"      하락1={mv[0][0]} {mv[0][1][1]:+.2f}% · 상승1={mv[-1][0]} {mv[-1][1][1]:+.2f}%")

# [3] fast_info 시총 ----------------------------------------------------------
print("\n[3] fast_info 시총 — 개별 콜 5종 속도")
t0 = time.time()
ok = 0
for t in TOP50[:5]:
    try:
        mc = yf.Ticker(t).fast_info.get("marketCap")
        if mc:
            ok += 1
            print(f"      {t}: {mc / 1e12:.2f}조$")
    except Exception as e:
        print(f"      {t}: 실패 {e}")
el = time.time() - t0
print(f"    {ok}/5 OK · {el:.1f}초 (50종 외삽 ≈ {el * 10:.0f}초)")

# [4] yfinance 뉴스 -----------------------------------------------------------
print("\n[4] yfinance .news — NVDA·TSLA")
for t in ("NVDA", "TSLA"):
    try:
        ns = yf.Ticker(t).news or []
        print(f"    {t}: {len(ns)}건")
        if ns:
            n0 = ns[0]
            c = n0.get("content") or n0          # 신/구 스키마 모두 대응
            title = c.get("title")
            url = ((c.get("canonicalUrl") or {}).get("url")
                   if isinstance(c.get("canonicalUrl"), dict) else c.get("link"))
            print(f"      keys={sorted(n0.keys())[:6]}")
            print(f"      1건: {str(title)[:60]} · {str(url)[:50]}")
    except Exception as e:
        print(f"    {t}: 실패 {e}")

# [5] 네이버 뉴스 검색 API ------------------------------------------------------
print("\n[5] 네이버 뉴스 검색 API — 한글 종목명")
cid = os.environ.get("NAVER_CLIENT_ID", "").strip()
csec = os.environ.get("NAVER_CLIENT_SECRET", "").strip()
if not (cid and csec):
    print("    시크릿 없음 — 건너뜀 (yml에 NAVER_CLIENT_ID/SECRET 추가 필요)")
else:
    for q in ("엔비디아", "브로드컴", "일라이릴리"):
        try:
            r = requests.get(
                "https://openapi.naver.com/v1/search/news.json",
                params={"query": q, "display": 3, "sort": "date"},
                headers={"X-Naver-Client-Id": cid,
                         "X-Naver-Client-Secret": csec},
                timeout=10)
            items = r.json().get("items", []) if r.ok else []
            print(f"    '{q}': HTTP {r.status_code} · {len(items)}건")
            if items:
                import re as _re
                t1 = _re.sub(r"<[^>]+>", "", items[0].get("title", ""))
                print(f"      1건: {t1[:60]} · {items[0].get('pubDate', '')[:22]}")
        except Exception as e:
            print(f"    '{q}': 실패 {e}")

# [6] 120종 타이밍 — S&P500 외삽 -----------------------------------------------
print("\n[6] 120종 배치 타이밍(S&P500 스캔 외삽)")
df120, sec = _dl(TOP50 + EXTRA70, "120종")
if df120 is not None:
    m = _chg_map(df120, TOP50 + EXTRA70)
    print(f"    OK {len(m)}/120종 · {sec:.1f}초 → 500종 외삽 ≈ {sec / 120 * 500:.0f}초")

print("\n" + "-" * 76)
print("판정 가이드: ① [1][2]가 OK면 업종+Top50은 배치 1콜로 확정.")
print("② 시총 랭킹 — [3]이 느리면(>60초/50종) 정적 순서 유지, 빠르면 주 1회 라이브.")
print("③ 뉴스 소스 — [4]와 [5]의 응답 품질 비교로 한글(네이버)/영문(야후) 확정.")
print("④ 이슈 스캔 범위 — [6] 외삽이 3분 이내면 S&P500 전체 스캔도 엔진에서 가능.")
print("=" * 76)
