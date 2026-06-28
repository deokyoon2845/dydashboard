"""[엔진 진입점] 수급 상위 종목(외국인·기관) 수집 → Supabase(market_flow) 저장.

뷰어(Streamlit Cloud)에서는 pykrx가 해외 IP 차단으로 막히므로, 엔진(GitHub Actions)에서
pykrx로 코스피·코스닥의 외국인·기관 거래대금 상위 종목을 모아 Supabase에 저장한다.
뷰어(modules/indices.py)는 이 테이블을 읽어 '수급 상위 종목'을 표시한다.

GitHub Actions(market_flow.yml)에서 `python -m engine.market_flow` 로 실행.
※ 최초 1회 Supabase에 market_flow 테이블 생성 필요(modules/db.py 상단 SQL).

※ 이 잡은 'pykrx가 Actions에서 동작하는지'의 시험도 겸한다. 로그에
   '코스피 외국인 5 · 기관 5' 처럼 건수가 찍히면 정상, 0이면 pykrx가 Actions에서도
   막히는 것이므로 다른 소스(예: 한국투자증권 Open API)로 전환해야 한다.
"""

import sys
import traceback
from datetime import datetime, timedelta


def _log(msg):
    print(f"[market_flow] {msg}", flush=True)


def collect():
    """{'코스피': {'date','외국인':[(name,억원)...],'기관':[...]}, '코스닥': {...}} 반환.
       (뷰어의 기존 fetch_supply_demand_summary 로직과 동일 — pykrx 거래대금 상위)."""
    result = {}
    from pykrx import stock
    end = datetime.now()
    start = end - timedelta(days=10)
    start_str = start.strftime("%Y%m%d")
    end_str = end.strftime("%Y%m%d")

    for mkt, label in (("KOSPI", "코스피"), ("KOSDAQ", "코스닥")):
        try:
            df = stock.get_market_trading_value_by_ticker(start_str, end_str, mkt)
            if df is None or df.empty:
                _log(f"{label}: 빈 응답")
                continue
            frg_col = next((c for c in df.columns if "외국인" in c), None)
            ins_col = next((c for c in df.columns if "기관" in c), None)
            mkt_result = {"date": f"{end_str[:4]}-{end_str[4:6]}-{end_str[6:]}"}
            counts = []
            for col_key, col in (("외국인", frg_col), ("기관", ins_col)):
                if col is None:
                    continue
                items = []
                for ticker, row in df.nlargest(5, col).iterrows():
                    try:
                        name = stock.get_market_ticker_name(ticker)
                    except Exception:
                        name = ticker
                    items.append([name, int(row[col] / 1e8)])   # 억원
                mkt_result[col_key] = items
                counts.append(f"{col_key} {len(items)}")
            result[label] = mkt_result
            _log(f"{label} " + " · ".join(counts) if counts else f"{label}: 컬럼 없음")
        except Exception as e:
            _log(f"{label} 수집 오류: {str(e)[:100]}")
            continue
    return result


def main():
    try:
        from modules import db
    except Exception as e:
        print(f"[market_flow] db 로드 실패: {e}", flush=True)
        return 1
    if not db.supabase_configured():
        print("[market_flow] SUPABASE 미설정 — 건너뜀.", flush=True)
        return 1

    try:
        payload = collect()
    except Exception:
        print("[market_flow] 수집 실패(pykrx가 Actions에서 막혔을 수 있음):", flush=True)
        traceback.print_exc()
        return 1

    if not payload:
        print("[market_flow] 수집 결과가 비어 있음 — 저장 건너뜀(기존 데이터 보존).", flush=True)
        return 1

    try:
        asof = datetime.now().strftime("%Y-%m-%d")
        db.save_market_flow(payload, asof_date=asof)
        print(f"[market_flow] 저장 완료 asof={asof} · 시장 {len(payload)}", flush=True)
        return 0
    except Exception:
        print("[market_flow] 저장 실패:", flush=True)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
