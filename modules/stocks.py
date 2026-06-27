"""종목 클릭 → 네이버 시세 검색 링크 (공용)."""

import html
from urllib.parse import quote


def naver_stock_url(name: str) -> str:
    """종목명을 네이버 '○○ 주가' 검색으로 연결 (시세 카드가 바로 뜸)."""
    return "https://search.naver.com/search.naver?query=" + quote(f"{name} 주가")


def _digits6(v) -> str:
    """문자열에서 숫자만 추려 앞 6자리. (코드 정규화)"""
    return "".join(ch for ch in str(v or "") if ch.isdigit())[:6]


def naver_stock_page_url(name: str = "", code: str = "") -> str:
    """네이버페이 증권 종목페이지 URL.

    1) code(6자리)가 있으면 바로 사용
    2) 없으면 name을 캐시된 KRX 사전으로 코드 변환
    3) 그래도 없으면 기존 '○○ 주가' 검색으로 폴백
    """
    c = _digits6(code)
    if len(c) != 6 and name:
        try:
            from modules.stock_quote import code_for_name
            c = _digits6(code_for_name(name))
        except Exception:
            c = ""
    if len(c) == 6:
        return f"https://stock.naver.com/domestic/stock/{c}/price"
    return naver_stock_url(name)


def naver_n_icon(name: str = "", code: str = "", cls: str = "nv") -> str:
    """종목 옆 네이버 'N' 아이콘 HTML. 종목페이지로 연결(코드 없으면 검색 폴백)."""
    url = naver_stock_page_url(name=name, code=code)
    return (f'<a class="{cls}" href="{html.escape(url)}" target="_blank" '
            f'rel="noopener" title="네이버페이 증권에서 보기">N</a>')


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
