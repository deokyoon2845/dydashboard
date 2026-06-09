"""[엔진] 리포트 생성 통합 로직 (CLI와 앱 버튼이 함께 사용).

전일 00:00(KST) ~ 지금 구간의 모든 메시지를 분석합니다.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from engine.fetch_telegram import fetch_since
from engine.analyze import analyze_messages
from engine.channels import load_channels, channel_label
from modules.usage import estimate_cost_usd, append_usage

load_dotenv()

KST = ZoneInfo("Asia/Seoul")
REPORTS_DIR = Path("reports")


def yesterday_midnight(now: datetime = None) -> datetime:
    """전일 00:00(KST)."""
    now = now or datetime.now(KST)
    return (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def generate_report() -> dict:
    """리포트 1건 생성. 결과 dict 반환."""
    channels = load_channels()
    label = channel_label()
    if not channels:
        return {"ok": False, "reason": "채널이 설정되지 않았습니다. engine/channels.json 또는 TELEGRAM_CHANNEL 환경변수를 확인하세요."}
    since = yesterday_midnight()

    messages = fetch_since(channels, since)
    if not messages:
        return {"ok": False, "reason": "해당 기간에 메시지가 없습니다."}

    report_body, usage = analyze_messages(messages, channel_name=label)
    now = datetime.now(KST)
    cost_usd = estimate_cost_usd(usage["model"], usage["input_tokens"], usage["output_tokens"])

    REPORTS_DIR.mkdir(exist_ok=True)
    path = REPORTS_DIR / f"{now:%Y-%m-%d_%H%M}.md"
    header = (
        f"# 시황 분석 보고서\n\n"
        f"- **채널**: {label}\n"
        f"- **분석 기간**: {since:%Y-%m-%d %H:%M} ~ {now:%Y-%m-%d %H:%M} (KST)\n"
        f"- **분석 메시지 수**: {len(messages)}\n"
        f"- **생성 시각**: {now:%Y-%m-%d %H:%M} (KST)\n\n"
        f"---\n\n"
    )
    path.write_text(header + report_body, encoding="utf-8")

    append_usage({
        "time": now.isoformat(),
        "model": usage["model"],
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "cost_usd": cost_usd,
        "messages": len(messages),
        "report": path.name,
    })

    return {
        "ok": True,
        "path": str(path),
        "messages": len(messages),
        "since": since,
        "now": now,
        "usage": usage,
        "cost_usd": cost_usd,
    }


if __name__ == "__main__":
    res = generate_report()
    if res.get("ok"):
        print(f"완료: {res['path']} · {res['messages']}개 메시지 · 예상 ${res['cost_usd']:.4f}")
    else:
        print(f"실패: {res.get('reason')}")
