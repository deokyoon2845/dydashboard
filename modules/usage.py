"""토큰 비용 계산 + 사용량 로그 (잔액 추정의 토대)."""

import json
from pathlib import Path

# USD per 1,000,000 tokens (입력, 출력) — 2026년 단가
PRICES_USD_PER_MTOK = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-opus-4-8": (5.0, 25.0),
}

# 계열 기본 단가 (버전/날짜 접미사가 달라도 비용을 맞추기 위한 폴백)
_FAMILY_PRICES = {
    "opus": (5.0, 25.0),
    "sonnet": (3.0, 15.0),
    "haiku": (1.0, 5.0),
}

# 알 수 없는 모델일 때 마지막 폴백 (가장 보편적인 Sonnet 단가)
_DEFAULT_PRICE = (3.0, 15.0)

DATA_DIR = Path("data")
LOG_PATH = DATA_DIR / "usage_log.json"


def price_for(model: str):
    """모델 문자열 → (입력, 출력) 단가. 견고 매칭.

    실제 API 모델 문자열은 날짜 접미사가 붙을 수 있어(예: 'claude-haiku-4-5-20251001',
    'claude-opus-4-8-20260528') 정확 일치만으로는 단가 조회가 빗나가 잘못된 기본값으로
    폴백되는 문제가 있다. 정확 → 접두 → 계열(opus/sonnet/haiku) 순으로 매칭한다.
    """
    if not model:
        return _DEFAULT_PRICE
    m = str(model).strip()

    # 1) 정확 일치
    if m in PRICES_USD_PER_MTOK:
        return PRICES_USD_PER_MTOK[m]

    # 2) 접두 일치 (날짜/버전 접미사 흡수: 'claude-opus-4-8-2026...' → 'claude-opus-4-8')
    for key, price in PRICES_USD_PER_MTOK.items():
        if m.startswith(key):
            return price

    # 3) 계열 매칭 (모델 세대가 바뀌어도 비용 추정이 깨지지 않게)
    low = m.lower()
    for fam, price in _FAMILY_PRICES.items():
        if fam in low:
            return price

    # 4) 최종 폴백
    return _DEFAULT_PRICE


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = price_for(model)
    return (input_tokens or 0) / 1_000_000 * pin + (output_tokens or 0) / 1_000_000 * pout


def load_usage() -> list:
    if not LOG_PATH.exists():
        return []
    try:
        return json.loads(LOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def append_usage(record: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    log = load_usage()
    log.append(record)
    LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def total_cost_usd() -> float:
    return sum(r.get("cost_usd", 0.0) for r in load_usage())
