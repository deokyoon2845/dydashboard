"""[엔진] 오늘의 증시 Top10 키워드 추출.

안전장치: AI는 우리가 건넨 '실제 기사 목록'에서 번호만 고릅니다.
URL을 새로 만들지 않으므로 가짜 링크가 생기지 않습니다.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from anthropic import Anthropic

from engine.news import fetch_market_news
from modules.usage import estimate_cost_usd, append_usage

KST = ZoneInfo("Asia/Seoul")
KW_PATH = Path("data/keywords_today.json")
MODEL = "claude-haiku-4-5"  # 헤드라인 추출 → 저렴·빠른 모델

SYSTEM = "당신은 한국 증시 애널리스트입니다. 오늘 뉴스 헤드라인에서 핵심 키워드를 추출합니다."


def _parse_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        text = m.group(0)
    return json.loads(text)


def build_today_keywords() -> dict:
    articles = fetch_market_news()
    if not articles:
        return {"ok": False, "reason": "뉴스를 가져오지 못했습니다. (네이버 키/쿼터 확인)"}

    listing = "\n".join(f"{i}: {a['title']}" for i, a in enumerate(articles))
    prompt = (
        "다음은 오늘의 증시 관련 뉴스 헤드라인 목록입니다 (번호: 제목).\n\n"
        f"{listing}\n\n"
        "이 중에서 오늘 증시에서 가장 중요한 키워드 10개를 중요도 순으로 뽑아주세요. "
        "각 키워드마다 (1) 관련 한국 종목명 0~3개, (2) 그 키워드를 가장 잘 대표하는 "
        "헤드라인의 번호 하나를 고르세요.\n"
        "반드시 아래 JSON 배열 형식으로만 응답하세요(설명·코드블록 없이 JSON만):\n"
        '[{"keyword":"...","stocks":["...","..."],"article_index": 정수}, ...]\n'
        "- article_index 는 위 목록에 실제 있는 번호여야 합니다. 번호나 URL을 지어내지 마세요.\n"
        "- 종목이 분명하지 않으면 stocks 는 빈 배열로 두세요."
    )

    client = Anthropic()
    resp = client.messages.create(
        model=MODEL, max_tokens=1200, system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        parsed = _parse_json(resp.content[0].text)
    except Exception:
        return {"ok": False, "reason": "AI 응답을 해석하지 못했습니다. 다시 시도해주세요."}

    items = []
    for obj in parsed[:10]:
        idx = obj.get("article_index")
        art = articles[idx] if isinstance(idx, int) and 0 <= idx < len(articles) else None
        items.append({
            "keyword": str(obj.get("keyword", "")).strip(),
            "stocks": [str(s).strip() for s in (obj.get("stocks") or [])][:3],
            "news_title": art["title"] if art else "",
            "news_url": art["url"] if art else "",
        })

    now = datetime.now(KST)
    KW_PATH.parent.mkdir(exist_ok=True)
    KW_PATH.write_text(
        json.dumps({"generated": now.isoformat(), "items": items}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    cost = estimate_cost_usd(MODEL, resp.usage.input_tokens, resp.usage.output_tokens)
    append_usage({
        "time": now.isoformat(), "model": MODEL,
        "input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens,
        "cost_usd": cost, "kind": "keywords", "count": len(items),
    })
    return {"ok": True, "count": len(items), "cost_usd": cost}
