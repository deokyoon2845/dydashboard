"""[엔진] 네이버 뉴스 검색 API로 오늘의 증시 뉴스를 수집."""

import os
import re
import html

import requests
from dotenv import load_dotenv

load_dotenv()

NAVER_URL = "https://openapi.naver.com/v1/search/news.json"
DEFAULT_QUERIES = ["증시 시황", "코스피", "코스닥", "주식 외국인"]


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)   # <b> 등 태그 제거
    return html.unescape(text).strip()    # &quot; 등 엔티티 복원


def _headers():
    return {
        "X-Naver-Client-Id": os.environ["NAVER_CLIENT_ID"],
        "X-Naver-Client-Secret": os.environ["NAVER_CLIENT_SECRET"],
    }


def fetch_market_news(queries=None, per_query: int = 30, cap: int = 70):
    """시황 관련 뉴스를 [{title, url, pubDate}, ...]로 반환 (중복 제거)."""
    queries = queries or DEFAULT_QUERIES
    headers = _headers()
    seen, out = set(), []

    for q in queries:
        try:
            r = requests.get(
                NAVER_URL, headers=headers,
                params={"query": q, "display": per_query, "sort": "date"},
                timeout=10,
            )
            r.raise_for_status()
            items = r.json().get("items", [])
        except Exception:
            continue

        for it in items:
            url = (it.get("originallink") or it.get("link") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            out.append({
                "title": _clean(it.get("title", "")),
                "url": url,
                "pubDate": it.get("pubDate", ""),
            })
        if len(out) >= cap:
            break

    return out[:cap]
