"""채널 목록 관리.

우선순위:
  1. engine/channels.json  — GitHub에서 직접 편집 가능
  2. 환경변수 TELEGRAM_CHANNEL — JSON 없을 때 fallback
"""

import json
import os
from pathlib import Path

_JSON_PATH = Path(__file__).parent / "channels.json"


def load_channels() -> list:
    """활성(active=true) 채널 ID 목록 반환."""
    if _JSON_PATH.exists():
        try:
            data = json.loads(_JSON_PATH.read_text(encoding="utf-8"))
            return [
                ch["id"].strip()
                for ch in data.get("channels", [])
                if ch.get("active", True) and str(ch.get("id", "")).strip()
            ]
        except Exception:
            pass  # JSON 파싱 실패 시 환경변수로 fallback

    # fallback: 환경변수 (쉼표 구분)
    raw = os.environ.get("TELEGRAM_CHANNEL", "").strip()
    return [c.strip() for c in raw.split(",") if c.strip()]


def channel_label() -> str:
    """리포트 헤더·분석용 채널 표시 이름."""
    channels = load_channels()
    return " / ".join(channels) if channels else "(채널 없음)"
