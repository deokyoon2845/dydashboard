"""[엔진] 리포트 생성 통합 로직 — JSON 형식으로 저장."""

import json
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


def yesterday_midnight(now=None):
    now = now or datetime.now(KST)
    return (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def generate_report() -> dict:
    channels = load_channels()
    label = channel_label()
    if not channels:
        return {"ok": False, "reason": "채널이 설정되지 않았습니다."}

    since = yesterday_midnight()
    messages = fetch_since(channels, since)
    if not messages:
        return {"ok": False, "reason": "해당 기간에 메시지가 없습니다."}

    report_data, usage = analyze_messages(messages, channel_name=label)
    now = datetime.now(KST)
    cost_usd = estimate_cost_usd(usage["model"], usage["input_tokens"], usage["output_tokens"])

    # 메타데이터 추가
    report_data["generated_at"] = now.strftime("%Y-%m-%d %H:%M")
    report_data["channel"] = label
    report_data["analysis_since"] = since.strftime("%Y-%m-%d %H:%M")
    report_data["analysis_until"] = now.strftime("%Y-%m-%d %H:%M")
    report_data["messages_count"] = len(messages)
    report_data["source_channels"] = list({m.get("channel", label) for m in messages if m.get("channel")})

    REPORTS_DIR.mkdir(exist_ok=True)
    path = REPORTS_DIR / f"{now:%Y-%m-%d_%H%M}.json"
    path.write_text(json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8")

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
        print(f"완료: {res['path']} · {res['messages']}개 · 예상 ${res['cost_usd']:.4f}")
    else:
        print(f"실패: {res.get('reason')}")
