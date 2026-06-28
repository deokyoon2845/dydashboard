"""[엔진 진입점] 수급 상위 종목(외국인·기관 순매수) 수집 → Supabase(market_flow) 저장.

KRX/pykrx가 로그인 요구·차단으로 막혀, 네이버 금융 '외국인·기관 순매매 거래 상위'를
스크래핑한다(supply_trend.py와 동일한 euc-kr + pandas.read_html 방식).
뷰어(modules/indices.py)는 Supabase의 최신 payload를 읽어 '수급 상위 종목'을 표시한다.

GitHub Actions(market_flow.yml)에서 `python -m engine.market_flow` 로 실행.
키 불필요(SUPABASE만). ※ 최초 1회 Supabase에 market_flow 테이블 생성 필요.

비공식 스크래핑이라 네이버가 레이아웃을 바꾸면 깨질 수 있다. 그 경우 빈 값으로
안전하게 떨어지고, 진단 로그(표 개수·컬럼·샘플)를 남겨 파서를 바로 고칠 수 있게 한다.
값 단위: 네이버 순매매대금은 '백만원' 표기 → 억원으로 환산(÷100).
"""

import re
import sys
import traceback
from datetime import datetime
from io import StringIO
from zoneinfo import ZoneInfo

import pandas as pd
import requests

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
# 네이버 '외국인·기관 순매매 거래상위' (sosok: 01=코스피, 02=코스닥)
_URL = "https://finance.naver.com/sise/sise_deal_rank.naver?sosok={sosok}"
_MARKETS = (("01", "코스피"), ("02", "코스닥"))


def _log(msg):
    print(f"[market_flow] {msg}", flush=True)


def _to_eok(x):
    """네이버 표기(백만원 등) → 억원 정수. 부호 유지. 실패 시 None."""
    try:
        s = str(x).replace(",", "").replace("+", "").strip()
        if s in ("", "-", "nan", "None"):
            return None
        v = float(s)
        return int(round(v / 100.0))   # 백만원 → 억원
    except Exception:
        return None


def _name_cell(x):
    """종목명 셀 정리(공백/숫자만 제거). 종목명 같지 않으면 ''."""
    s = re.sub(r"\s+", " ", str(x or "")).strip()
    if not s or s in ("종목명", "nan", "None") or s.replace(".", "").isdigit():
        return ""
    return s


def _scrape_market(sosok, label):
    """한 시장의 외국인·기관 순매수 상위 5종목을 파싱.
       반환: {'date':..., '외국인':[(name,억)..], '기관':[..]} 또는 None."""
    url = _URL.format(sosok=sosok)
    try:
        r = requests.get(url, headers=_HEADERS, timeout=12)
        r.encoding = "euc-kr"
        tables = pd.read_html(StringIO(r.text))
    except Exception as e:
        _log(f"{label} 요청/파싱 실패: {str(e)[:90]}")
        return None

    # 진단: 표 개수·각 표의 shape + 실제 행 내용(첫 실행 확인용)
    _log(f"{label} 표 {len(tables)}개")
    for i, tb in enumerate(tables):
        _log(f"  표[{i}] shape={tb.shape}")
        for j, (_, row) in enumerate(tb.iterrows()):
            if j >= 8:
                break
            cells = " ¦ ".join(str(v) for v in list(row.values)[:6])
            _log(f"    [{i}.{j}] {cells[:200]}")

    out = {"date": datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d')}
    # 휴리스틱: '외국인'/'기관'이 컬럼명에 있고 종목명 컬럼이 있는 표에서 상위 5
    for col_key in ("외국인", "기관"):
        picked = []
        for tb in tables:
            cols = [str(c) for c in tb.columns]
            name_col = next((c for c in tb.columns
                             if "종목" in str(c) or "종목명" in str(c)), None)
            val_col = next((c for c in tb.columns if col_key in str(c)
                            and ("순매수" in str(c) or "순매매" in str(c) or "금액" in str(c) or "대금" in str(c))), None)
            if name_col is None or val_col is None:
                continue
            for _, row in tb.iterrows():
                nm = _name_cell(row.get(name_col))
                val = _to_eok(row.get(val_col))
                if nm and val is not None:
                    picked.append((nm, val))
            if picked:
                break
        if picked:
            picked.sort(key=lambda t: t[1], reverse=True)
            out[col_key] = [[n, v] for n, v in picked[:5]]
            sample = picked[0]
            _log(f"{label} {col_key} {len(out[col_key])}종목 (예: {sample[0]} {sample[1]}억)")
    if out.get("외국인") or out.get("기관"):
        return out
    _log(f"{label}: 외국인/기관 컬럼을 가진 표를 못 찾음 — 위 진단 로그로 파서 보정 필요")
    return None


def collect():
    result = {}
    for sosok, label in _MARKETS:
        data = _scrape_market(sosok, label)
        if data:
            result[label] = data
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
        print("[market_flow] 수집 실패:", flush=True)
        traceback.print_exc()
        return 1
    if not payload:
        print("[market_flow] 수집 결과가 비어 있음 — 저장 건너뜀(기존 데이터 보존).", flush=True)
        return 1
    try:
        asof = datetime.now(ZoneInfo('Asia/Seoul')).strftime("%Y-%m-%d")
        db.save_market_flow(payload, asof_date=asof)
        print(f"[market_flow] 저장 완료 asof={asof} · 시장 {len(payload)}", flush=True)
        return 0
    except Exception:
        print("[market_flow] 저장 실패:", flush=True)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
