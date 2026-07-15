"""[엔진 진입점] 한국 국고채 수익률 수집 — ECOS → Supabase(engine_cache) 저장.

배경: 뷰어(rates.py·rate_gap.py)가 ECOS를 직접 호출하던 구조는 Streamlit Cloud
(해외 데이터센터 IP)에서 ECOS가 응답하지 않아 '데이터 없음'으로 떨어졌다.
엔진-퍼스트 원칙에 맞게 GitHub Actions(ECOS 접근 확인됨)에서 수집해 engine_cache에
저장하고, 뷰어는 캐시를 읽는다(로컬 실행 시 직접 호출 폴백은 뷰어 쪽에 유지).

수집: ECOS 817Y002 '시장금리(일별)' — 국고채 2년·3년·10년, 최근 ~100일.
저장: engine_cache(cache_key='kr_rates')
      payload = {"tenors": {"2y": [["YYYYMMDD", 값], ...], "3y": [...], "10y": [...]},
                 "items": {"2y": "항목이름", ...}, "asof": "YYYY-MM-DD HH:MM"}
실행:
    python -m engine.kr_rates_collect            # 수집 + 저장
run_all('all' 또는 'rates')에서도 호출된다. AI 비용 없음 · HTTP 4회라
멀티 슬롯 크론이 겹쳐 여러 번 돌아도 부담 없다(항상 최신으로 upsert).
"""

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

ECOS_TABLE = "817Y002"   # 시장금리(일별)
CACHE_KEY = "kr_rates"

# 저장 키 ↔ ECOS 항목 이름 키워드 (뷰어 rates.py의 _KR_TENORS와 짝을 이룬다)
TENORS = [
    ("2y", ("국고채", "2년")),
    ("3y", ("국고채", "3년")),
    ("10y", ("국고채", "10년")),
]

_TIMEOUT = 15


def _key() -> str:
    return (os.environ.get("ECOS_API_KEY") or "").strip()


def _ecos_items(key: str) -> dict:
    """817Y002의 {항목이름: 항목코드}. 실패 시 빈 dict."""
    url = f"https://ecos.bok.or.kr/api/StatisticItemList/{key}/json/kr/1/300/{ECOS_TABLE}"
    try:
        r = requests.get(url, timeout=_TIMEOUT)
        rows = r.json().get("StatisticItemList", {}).get("row", [])
        return {row.get("ITEM_NAME", ""): row.get("ITEM_CODE", "") for row in rows}
    except Exception as e:
        print(f"  [items] 조회 실패: {e}")
        return {}


def _find(items: dict, keywords) -> tuple[str | None, str | None]:
    """항목 이름에 keywords가 모두 들어간 첫 (코드, 이름)."""
    for name, code in items.items():
        if name and all(k in name for k in keywords):
            return code, name
    return None, None


def _ecos_series(key: str, item_code: str) -> list:
    """항목의 [(YYYYMMDD, float)] (최근 ~100일, 오름차순). 실패 시 []."""
    if not item_code:
        return []
    end = datetime.now(ZoneInfo("Asia/Seoul"))
    start = end - timedelta(days=100)
    url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/300/"
           f"{ECOS_TABLE}/D/{start:%Y%m%d}/{end:%Y%m%d}/{item_code}")
    try:
        r = requests.get(url, timeout=_TIMEOUT)
        rows = r.json().get("StatisticSearch", {}).get("row", [])
    except Exception as e:
        print(f"  [series {item_code}] 조회 실패: {e}")
        return []
    out = []
    for row in rows:
        v, t = row.get("DATA_VALUE"), row.get("TIME")
        if v in (None, "", ".") or not t:
            continue
        try:
            out.append([str(t), float(v)])
        except Exception:
            continue
    out.sort(key=lambda x: x[0])
    return out


def collect_kr_rates() -> dict:
    """수집 → engine_cache 저장. {'ok': bool, 'reason'/'counts': ...} 반환."""
    key = _key()
    if not key:
        return {"ok": False, "reason": "ECOS_API_KEY 미설정"}

    items = _ecos_items(key)
    if not items:
        return {"ok": False, "reason": "ECOS 항목 목록 조회 실패"}

    tenors, names, counts = {}, {}, {}
    for tkey, kw in TENORS:
        code, name = _find(items, kw)
        vals = _ecos_series(key, code) if code else []
        # 새니티 가드: 값이 있고 상식 범위(0~20%)여야 저장 — 파싱 오염 방지
        vals = [x for x in vals if 0.0 < x[1] < 20.0]
        if vals:
            tenors[tkey] = vals
            names[tkey] = name or ""
        counts[tkey] = len(vals)
        print(f"  {tkey}: {len(vals)}건" + (f" ({name})" if name else " — 항목 못 찾음"))

    if not tenors:
        return {"ok": False, "reason": "국고채 시계열 없음 (ECOS 응답 비어있음)"}

    from modules import db
    payload = {
        "tenors": tenors,
        "items": names,
        "asof": datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M"),
    }
    if not db.cache_set(CACHE_KEY, payload):
        return {"ok": False, "reason": "engine_cache 저장 실패"}
    return {"ok": True, "counts": counts}


if __name__ == "__main__":
    print("== 한국 국고채 수집(ECOS → engine_cache) ==")
    r = collect_kr_rates()
    if r.get("ok"):
        print("완료:", r.get("counts"))
    else:
        # 새니티 원칙: 조용히 성공한 척하지 않고 명시적으로 실패를 남긴다
        raise SystemExit(f"실패: {r.get('reason')}")
