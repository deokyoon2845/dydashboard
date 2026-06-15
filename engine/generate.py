"""[엔진] 리포트 생성 통합 — 장전/장후 구분, 정량 스냅샷 + 뉴스 + 워치리스트 결합, 예측 채점 갱신.

- kind="pre"  (장전): 직전 거래일 마감(15:30) ~ 지금. 월요일이면 금요일 15:30까지 소급.
- kind="post" (장후): 당일 07:50 ~ 지금.
- kind 미지정 시 생성 시각으로 자동 판별(오전=장전, 오후=장후).

2026-06 재설계: 직전 보고서를 읽어 analyze에 넘김(변화 추적). 새 topics 스키마 대응.
2026-06 안정화: DB 저장이 'SUPABASE 설정돼 있는데도' 실패하면 예외를 터뜨린다
  → 자동화(Actions)에서 '초록 성공인데 뷰어 빈 화면'(조용한 실패)을 빨간 X로 노출.
"""

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

_KIND_KO = {"pre": "장전", "post": "장마감 후"}


def detect_kind(now=None) -> str:
    """생성 시각으로 장전/장후 자동 판별 (오전=장전, 오후=장후)."""
    now = now or datetime.now(KST)
    return "pre" if now.hour < 12 else "post"


def collection_window(kind: str, now=None) -> datetime:
    """분석 구간 시작 시각(KST)."""
    now = now or datetime.now(KST)
    if kind == "pre":
        days_back = 3 if now.weekday() == 0 else 1  # 0=월요일 → 금요일까지
        return (now - timedelta(days=days_back)).replace(
            hour=15, minute=30, second=0, microsecond=0)
    return now.replace(hour=7, minute=50, second=0, microsecond=0)


def _load_prev_report():
    """직전(가장 최근) 보고서를 DB에서 읽어 반환. 변화 추적용. 없으면 None."""
    try:
        from modules import db
        slugs = db.list_slugs()
        return db.load_by_slug(slugs[0]) if slugs else None
    except Exception:
        return None


def generate_report(kind: str = None, send_telegram: bool = False) -> dict:
    now = datetime.now(KST)
    if kind not in ("pre", "post"):
        kind = detect_kind(now)

    channels = load_channels()
    label = channel_label()
    if not channels:
        return {"ok": False, "reason": "채널이 설정되지 않았습니다."}

    since = collection_window(kind, now)
    messages = fetch_since(channels, since)
    if not messages:
        return {"ok": False, "reason": "해당 기간에 메시지가 없습니다.", "kind": kind}

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
    prev_report = _load_prev_report()   # 변화 추적용 직전 보고서

    report_data, usage = analyze_messages(
        messages, kind=kind, channel_name=label,
        snapshot_text=snapshot_text, news_titles=news_titles, watchlist=watchlist,
        prev_report=prev_report)

    cost_usd = sum(
        estimate_cost_usd(c["model"], c["input_tokens"], c["output_tokens"])
        for c in usage.get("calls", []))

    report_data["report_kind"] = kind
    report_data["generated_at"] = now.strftime("%Y-%m-%d %H:%M")
    report_data["channel"] = label
    report_data["analysis_since"] = since.strftime("%Y-%m-%d %H:%M")
    report_data["analysis_until"] = now.strftime("%Y-%m-%d %H:%M")
    report_data["messages_count"] = len(messages)
    report_data["source_channels"] = list(
        {m.get("channel", label) for m in messages if m.get("channel")})
    report_data["data_enriched"] = bool(snapshot_text)

    # 검증용: 분석에 들어간 텔레그램 원문 전체를 보고서에 동봉.
    def _msg_sort_key(m):
        return str(m.get("date", ""))

    report_data["source_messages"] = [
        {
            "channel": m.get("channel", label),
            "date": str(m.get("date", "")),
            "text": (m.get("text") or "").strip(),
        }
        for m in sorted(messages, key=_msg_sort_key)
        if (m.get("text") or "").strip()
    ]

    REPORTS_DIR.mkdir(exist_ok=True)
    path = REPORTS_DIR / f"{now:%Y-%m-%d_%H%M}.json"
    path.write_text(json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8")
    # ★ DB에도 저장 — 재시작에도 사라지지 않는 핵심 한 줄
    try:
        from modules import db
        db.save_report(report_data)
    except Exception as e:
        # SUPABASE가 설정돼 있는데 저장 실패 = '조용한 실패'(초록 성공인데 뷰어 빈 화면)의 주범.
        # 자동화에서는 일부러 예외를 터뜨려 Actions가 '빨간 X'로 알려주게 한다.
        if os.environ.get("SUPABASE_URL"):
            raise RuntimeError(
                "DB 저장 실패 — 보고서는 생성됐지만 Supabase에 안 들어갔습니다. "
                "SUPABASE_URL/SUPABASE_KEY 값과 키 권한(service_role)을 확인하세요. "
                f"(원인: {e})"
            )
        # 로컬 등 SUPABASE 미설정 환경에서는 기존처럼 무시(경고만).
        print(f"⚠️ DB 저장 건너뜀(SUPABASE 미설정): {e}")

    append_usage({
        "time": now.isoformat(),
        "model": usage["model"],
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "cost_usd": cost_usd,
        "messages": len(messages),
        "report": path.name,
        "kind": kind,
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
            kind_ko = _KIND_KO.get(kind, "")
            # 새 스키마: key_takeaway 대신 첫 주제 요약 사용 (없으면 headline)
            topics = report_data.get("topics") or []
            lead = ""
            if topics:
                lead = str(topics[0].get("fact", "")).strip()
            caption = (
                f"📊 <b>전략/시황 보고서 · {kind_ko}</b> ({mood_ko})\n"
                f"{report_data.get('headline', '')}\n\n"
                f"{lead[:500]}\n\n"
                f"🕒 {now:%Y-%m-%d %H:%M} KST · {len(messages)}개 메시지 분석"
            )
            telegram_result = send_report(
                pdf_bytes, caption,
                filename=f"전략시황보고서_{kind_ko}_{now:%Y%m%d}.pdf")
        except Exception as e:
            telegram_result = {"ok": False, "reason": str(e)}

    return {
        "ok": True, "path": str(path), "kind": kind, "messages": len(messages),
        "since": since, "now": now, "usage": usage, "cost_usd": cost_usd,
        "telegram": telegram_result,
    }


if __name__ == "__main__":
    import sys
    arg_kind = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ("pre", "post") else None
    res = generate_report(kind=arg_kind)
    if res.get("ok"):
        print(f"완료({res['kind']}): {res['path']} · {res['messages']}개 · "
              f"예상 ${res['cost_usd']:.4f}")
    else:
        print(f"실패: {res.get('reason')}")
