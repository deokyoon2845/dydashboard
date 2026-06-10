"""[엔진] 네이버 뉴스 검색 API로 오늘의 증시 뉴스를 수집."""

import os
import re
import html

import requests
from dotenv import load_dotenv

load_dotenv()

NAVER_URL = "https://openapi.naver.com/v1/search/news.json"
DEFAULT_QUERIES = [
    "증시 시황", "코스피", "코스닥", "외국인 순매수",
    "반도체 실적", "2차전지", "AI 반도체", "기준금리",
    "환율", "실적 발표", "정부 정책 증시",
]


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)   # <b> 등 태그 제거
    return html.unescape(text).strip()    # &quot; 등 엔티티 복원


def _headers():
    return {
        "X-Naver-Client-Id": os.environ["NAVER_CLIENT_ID"],
        "X-Naver-Client-Secret": os.environ["NAVER_CLIENT_SECRET"],
    }


def fetch_market_news(queries=None, per_query: int = 25, cap: int = 120):
    """시황 관련 뉴스를 [{title, url, pubDate}, ...]로 반환 (중복 제거)."""
    queries = queries or DEFAULT_QUERIES
    headers = _headers()
    seen, seen_title, out = set(), set(), []

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
            title = _clean(it.get("title", ""))
            tkey = re.sub(r"\s+", "", title)[:40]      # 제목 기반 중복도 제거
            if not url or url in seen or tkey in seen_title:
                continue
            seen.add(url)
            seen_title.add(tkey)
            out.append({"title": title, "url": url, "pubDate": it.get("pubDate", "")})
        if len(out) >= cap:
            break

    return out[:cap]
