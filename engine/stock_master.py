"""[엔진 진입점] 종목 마스터(종목명 ↔ 종목코드) 수집 → Supabase(stock_master) 저장.

data.go.kr 「KRX상장종목정보」(승인됨)에서 전 종목의 종목명·단축코드·시장·ISIN을
받아 Supabase `stock_master` 테이블에 적재한다. 뷰어(modules/stock_quote.py)는
이 테이블을 읽어 '종목명 → 코드'를 해석한다(클라우드에서 pykrx 대신).

GitHub Actions(stock_master.yml)에서 `python -m engine.stock_master` 로 실행.
키: DATA_GO_KR_KEY(없으면 MOLIT_API_KEY).
※ 최초 1회 Supabase에 stock_master 테이블 생성 필요(modules/db.py 상단 SQL).
"""

import os
import re
import sys
import time
import traceback
from datetime import datetime, timedelta

import requests

_DATAGO = "https://apis.data.go.kr/1160100/service"
_KRX = f"{_DATAGO}/GetKrxListedInfoService/getItemInfo"   # KRX상장종목정보(승인)
_UA = {"User-Agent": "Mozilla/5.0 (compatible; stock-master/1.0)"}


def _dk() -> str:
    return (os.environ.get("DATA_GO_KR_KEY") or os.environ.get("MOLIT_API_KEY") or "").strip()


def _log(msg):
    print(f"[stock_master] {msg}", flush=True)


def _digits(x, n=None):
    s = re.sub(r"[^0-9]", "", str(x or ""))
    return s[:n] if n else s


def _get(url, params, timeout=30, retries=3):
    """GET → JSON. 타임아웃·연결오류만 재시도(HTTP 4xx/비-JSON은 즉시 전파)."""
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, headers=_UA, timeout=timeout)
            r.raise_for_status()
            txt = r.text.strip()
            if txt.startswith("<"):
                raise RuntimeError(f"비-JSON 응답(인증/권한/파라미터): {txt[:160]}")
            return r.json()
        except (requests.Timeout, requests.ConnectionError) as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def _items(data):
    body = (data.get("response") or {}).get("body") or {}
    it = ((body.get("items") or {}).get("item")) or []
    if isinstance(it, dict):
        it = [it]
    return it, body


def _fetch_day(key, basdt):
    """기준일(basdt, YYYYMMDD)의 전 종목 마스터를 페이지 순회로 모은다. code 기준 중복 제거."""
    out = {}
    page = 1
    while page <= 12:
        it, body = _items(_get(_KRX, {
            "serviceKey": key, "resultType": "json",
            "numOfRows": 5000, "pageNo": page, "basDt": basdt,
        }))
        for x in it:
            code = _digits(x.get("srtnCd"), 6)
            name = str(x.get("itmsNm") or "").strip()
            if not code or not name or code in out:
                continue
            out[code] = {
                "code": code,
                "name": name,
                "corp_name": str(x.get("corpNm") or "").strip(),
                "market": str(x.get("mrktCtg") or "").strip(),
                "isin": str(x.get("isinCd") or "").strip(),
            }
        total = int(body.get("totalCount") or 0)
        if not it or page * 5000 >= total:
            break
        page += 1
    return list(out.values())


def collect():
    """종목 마스터 행 목록과 기준일을 반환. (KRX 데이터는 T+1이라 빈 날은 며칠 앞으로 탐색)"""
    key = _dk()
    if not key:
        raise RuntimeError("DATA_GO_KR_KEY(또는 MOLIT_API_KEY)가 없어요.")
    today = datetime.now().date()
    for probe in range(0, 9):
        d = (today - timedelta(days=probe)).strftime("%Y%m%d")
        try:
            rows = _fetch_day(key, d)
        except Exception as e:
            _log(f"basDt={d} 조회 오류: {str(e)[:90]}")
            continue
        if rows:
            _log(f"종목 마스터 basDt={d} · {len(rows)}종목")
            return rows, d
    _log("종목 마스터 조회 실패(빈 응답).")
    return [], ""


def main():
    try:
        from modules import db
    except Exception as e:
        print(f"[stock_master] db 모듈 로드 실패: {e}", flush=True)
        return 1

    if not db.supabase_configured():
        print("[stock_master] SUPABASE 미설정 — 저장 건너뜀(키 확인).", flush=True)
        return 1

    # ── 멱등 가드: 오늘(KST) 이미 수집을 마쳤으면 다음 슬롯은 즉시 스킵 ──
    #   stock_master.yml은 06:20·07:20 KST 두 슬롯. 첫 성공이 잡으면 여기서 빠진다.
    if db.collected_today("stock_master"):
        print("[stock_master] 오늘 이미 수집 완료 — 스킵(멱등 가드).", flush=True)
        return 0

    try:
        rows, basdt = collect()
    except Exception:
        print("[stock_master] 수집 실패:", flush=True)
        traceback.print_exc()
        return 1

    if not rows:
        print("[stock_master] 수집 결과가 비어 있음 — 기존 마스터 보존 위해 저장 건너뜀.", flush=True)
        return 1

    try:
        n = db.save_stock_master(rows, basdt=basdt)
        print(f"[stock_master] 저장 완료 basDt={basdt} · {n}종목", flush=True)
        return 0
    except Exception:
        print("[stock_master] 저장 실패:", flush=True)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
