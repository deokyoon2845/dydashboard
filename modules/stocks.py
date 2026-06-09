"""종목 클릭 → 네이버 시세 검색 링크 (공용)."""

import html
from urllib.parse import quote


def naver_stock_url(name: str) -> str:
    """종목명을 네이버 '○○ 주가' 검색으로 연결 (시세 카드가 바로 뜸)."""
    return "https://search.naver.com/search.naver?query=" + quote(f"{name} 주가")


def stock_pills_html(names) -> str:
    """종목 이름 목록을 클릭 가능한 pill HTML로."""
    out = []
    for n in names or []:
        n = (n or "").strip()
        if not n:
            continue
        out.append(
            f'<a class="pill pill-link" href="{html.escape(naver_stock_url(n))}" '
            f'target="_blank" rel="noopener">{html.escape(n)}</a>'
        )
    return "".join(out)
