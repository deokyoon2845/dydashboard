"""[엔진] 리포트 생성 통합 — 정량 스냅샷 + 뉴스 + 워치리스트 결합, 예측 채점 갱신."""

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
from modules.watchlist import load_watchlist

load_dotenv()

KST = ZoneInfo("Asia/Seoul")
REPORTS_DIR = Path("reports")


def collection_start(now=None):
    """수집 시작 시점: 전일 15:40 (KST)."""
    now = now or datetime.now(KST)
    return (now - timedelta(days=1)).replace(hour=15, minute=40, second=0, microsecond=0)


def generate_report(send_telegram: bool = False) -> dict:
    channels = load_channels()
    label = channel_label()
    if not channels:
        return {"ok": False, "reason": "채널이 설정되지 않았습니다."}

    since = collection_start()
    messages = fetch_since(channels, since)
    if not messages:
        return {"ok": False, "reason": "해당 기간에 메시지가 없습니다."}

    # 정량 스냅샷 (실패해도 리포트는 계속)
    snapshot_text = ""
    try:
        from engine.market_snapshot import build_snapshot_text
        snapshot_text = build_snapshot_text()
    except Exception:
        pass

    # 뉴스 헤드라인 (멀티소스 교차)
    news_titles = []
    try:
        from engine.news import fetch_market_news
        news_titles = [a["title"] for a in fetch_market_news()[:25]]
    except Exception:
        pass

    watchlist = load_watchlist()

    report_data, usage = analyze_messages(
        messages, channel_name=label,
        snapshot_text=snapshot_text, news_titles=news_titles, watchlist=watchlist)

    now = datetime.now(KST)
    cost_usd = sum(
        estimate_cost_usd(c["model"], c["input_tokens"], c["output_tokens"])
        for c in usage.get("calls", []))

    report_data["generated_at"] = now.strftime("%Y-%m-%d %H:%M")
    report_data["channel"] = label
    report_data["analysis_since"] = since.strftime("%Y-%m-%d %H:%M")
    report_data["analysis_until"] = now.strftime("%Y-%m-%d %H:%M")
    report_data["messages_count"] = len(messages)
    report_data["source_channels"] = list(
        {m.get("channel", label) for m in messages if m.get("channel")})
    report_data["data_enriched"] = bool(snapshot_text)

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

    # 예측 채점 갱신 (실패 무시)
    try:
        from engine.predictions import update_scores
        update_scores()
    except Exception:
        pass

    # 텔레그램 발송 (자동화에서만)
    telegram_result = None
    if send_telegram:
        try:
            from modules.report_pdf import build_pdf
            from engine.telegram_send import send_report
            pdf_bytes = build_pdf(report_data)
            mood_ko = {"positive": "긍정", "neutral": "중립", "cautious": "주의"}.get(
                report_data.get("mood", "neutral"), "중립")
            caption = (
                f"📊 <b>전략/시황 보고서</b> ({mood_ko})\n"
                f"{report_data.get('headline', '')}\n\n"
                f"{report_data.get('key_takeaway', '')[:500]}\n\n"
                f"🕒 {now:%Y-%m-%d %H:%M} KST · {len(messages)}개 메시지 분석"
            )
            telegram_result = send_report(
                pdf_bytes, caption, filename=f"전략시황보고서_{now:%Y%m%d}.pdf")
        except Exception as e:
            telegram_result = {"ok": False, "reason": str(e)}

    return {
        "ok": True, "path": str(path), "messages": len(messages),
        "since": since, "now": now, "usage": usage, "cost_usd": cost_usd,
        "telegram": telegram_result,
    }


if __name__ == "__main__":
    res = generate_report()
    if res.get("ok"):
        print(f"완료: {res['path']} · {res['messages']}개 · 예상 ${res['cost_usd']:.4f}")
    else:
        print(f"실패: {res.get('reason')}")
