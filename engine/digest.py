"""[엔진] 주간 다이제스트: 최근 N일 리포트를 Claude로 한 장 요약."""

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from anthropic import Anthropic

from modules.reports import list_reports, _report_date, _parse
from modules.usage import estimate_cost_usd, append_usage

KST = ZoneInfo("Asia/Seoul")
DIGEST_DIR = Path("digests")
MODEL = "claude-sonnet-4-6"

SYSTEM = "당신은 한국 증시의 주간 흐름을 정리하는 애널리스트입니다."


def build_weekly_digest(days: int = 7) -> dict:
    today = datetime.now(KST).date()
    start = today - timedelta(days=days - 1)

    files = [f for f in list_reports() if start <= _report_date(f) <= today]
    if not files:
        return {"ok": False, "reason": f"최근 {days}일 내 리포트가 없습니다."}

    chunks = []
    for f in sorted(files):
        _, summary, body = _parse(f.read_text(encoding="utf-8"))
        chunks.append(f"[{_report_date(f)}] 요약: {summary}\n{body[:800]}")
    joined = "\n\n----\n\n".join(chunks)

    prompt = (
        "다음은 최근 며칠간의 일일 시황 리포트들입니다. 이를 종합해 한 주(기간) 시황을 "
        "정리한 '주간 다이제스트'를 마크다운으로 작성하세요.\n\n"
        "## 이번 주 한눈에\n## 핵심 흐름\n(불릿 3~6개)\n## 주목할 종목·섹터\n"
        "## 분위기 변화\n## 다음 주 관전 포인트\n\n"
        f"{joined}\n\n"
        "※ 정보 정리용이며 투자 권유가 아님을 마지막에 명시하세요."
    )

    client = Anthropic()
    resp = client.messages.create(
        model=MODEL, max_tokens=2500, system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    body = resp.content[0].text

    now = datetime.now(KST)
    DIGEST_DIR.mkdir(exist_ok=True)
    path = DIGEST_DIR / f"{now:%Y-%m-%d}_weekly.md"
    header = (
        f"# 주간 다이제스트\n\n"
        f"- **기간**: {start} ~ {today}\n"
        f"- **종합 리포트 수**: {len(files)}건\n"
        f"- **생성 시각**: {now:%Y-%m-%d %H:%M} (KST)\n\n---\n\n"
    )
    path.write_text(header + body, encoding="utf-8")

    cost = estimate_cost_usd(MODEL, resp.usage.input_tokens, resp.usage.output_tokens)
    append_usage({
        "time": now.isoformat(), "model": MODEL,
        "input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens,
        "cost_usd": cost, "kind": "digest", "reports": len(files),
    })
    return {"ok": True, "path": str(path), "reports": len(files), "cost_usd": cost}
