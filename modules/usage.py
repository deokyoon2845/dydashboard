"""토큰 비용 계산 + 사용량 로그 (잔액 추정의 토대)."""

import json
from pathlib import Path

# USD per 1,000,000 tokens (입력, 출력) — 2026년 단가
PRICES_USD_PER_MTOK = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-opus-4-8": (5.0, 25.0),
}

DATA_DIR = Path("data")
LOG_PATH = DATA_DIR / "usage_log.json"


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = PRICES_USD_PER_MTOK.get(model, (3.0, 15.0))
    return input_tokens / 1_000_000 * pin + output_tokens / 1_000_000 * pout


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
