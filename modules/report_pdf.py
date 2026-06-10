"""리포트 → PDF 변환 (reportlab). 한글 폰트 자동 등록."""

import io
import os
import urllib.request
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                Table, TableStyle)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

_FONT_DIR = Path("data/fonts")
_FONT_PATH = _FONT_DIR / "NanumGothic.ttf"
_FONT_BOLD_PATH = _FONT_DIR / "NanumGothicBold.ttf"
_FONT_URLS = [
    "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf",
    "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/nanumgothic/NanumGothic-Regular.ttf",
]
_FONT_BOLD_URLS = [
    "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Bold.ttf",
    "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/nanumgothic/NanumGothic-Bold.ttf",
]

_FONT_NAME = "KFont"
_FONT_BOLD = "KFontBold"
_registered = False

SAGE = HexColor("#7E9A83")
INK = HexColor("#34352f")
MUTED = HexColor("#9a9b92")
BG = HexColor("#F6F7F2")


def _download_first(urls, dest):
    for url in urls:
        try:
            urllib.request.urlretrieve(url, dest)
            if dest.exists() and dest.stat().st_size > 10000:
                return True
        except Exception:
            continue
    return False


def _ensure_fonts():
    """나눔고딕 폰트 확보 (여러 소스 시도). 실패 시 기본 폰트로 폴백."""
    global _registered
    if _registered:
        return True
    try:
        _FONT_DIR.mkdir(parents=True, exist_ok=True)
        if not _FONT_PATH.exists() and not _download_first(_FONT_URLS, _FONT_PATH):
            return False
        if not _FONT_BOLD_PATH.exists() and not _download_first(_FONT_BOLD_URLS, _FONT_BOLD_PATH):
            return False
        pdfmetrics.registerFont(TTFont(_FONT_NAME, str(_FONT_PATH)))
        pdfmetrics.registerFont(TTFont(_FONT_BOLD, str(_FONT_BOLD_PATH)))
        _registered = True
        return True
    except Exception:
        return False


def _esc(text):
    if not isinstance(text, str):
        text = str(text)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_pdf(data: dict) -> bytes:
    """리포트 dict → PDF 바이트."""
    ok = _ensure_fonts()
    base = _FONT_NAME if ok else "Helvetica"
    bold = _FONT_BOLD if ok else "Helvetica-Bold"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
    )

    s_head = ParagraphStyle("head", fontName=bold, fontSize=18, textColor=INK,
                            leading=24, spaceAfter=4)
    s_meta = ParagraphStyle("meta", fontName=base, fontSize=9, textColor=MUTED,
                            leading=13, spaceAfter=10)
    s_kt_label = ParagraphStyle("ktl", fontName=bold, fontSize=9, textColor=SAGE,
                                leading=13, spaceAfter=3)
    s_kt = ParagraphStyle("kt", fontName=base, fontSize=10.5, textColor=INK,
                          leading=17, spaceAfter=4)
    s_sec_title = ParagraphStyle("st", fontName=bold, fontSize=12, textColor=INK,
                                 leading=16, spaceBefore=12, spaceAfter=5)
    s_body = ParagraphStyle("body", fontName=base, fontSize=10, textColor=INK,
                            leading=16, spaceAfter=4)
    s_group = ParagraphStyle("grp", fontName=bold, fontSize=10, textColor=MUTED,
                             leading=14, spaceBefore=14, spaceAfter=6)
    s_theme_name = ParagraphStyle("tn", fontName=bold, fontSize=10.5, textColor=INK,
                                  leading=15, spaceAfter=2)
    s_theme_detail = ParagraphStyle("td", fontName=base, fontSize=9.5, textColor=INK,
                                    leading=14, spaceAfter=2)
    s_theme_tk = ParagraphStyle("ttk", fontName=base, fontSize=8.5, textColor=MUTED,
                                leading=12)
    s_src = ParagraphStyle("src", fontName=base, fontSize=8.5, textColor=MUTED,
                           leading=13, spaceBefore=12)

    elems = []
    mood_ko = {"positive": "긍정", "neutral": "중립", "cautious": "주의"}.get(
        data.get("mood", "neutral"), "중립")
    gen_at = data.get("generated_at", "")
    n_msg = data.get("messages_count", 0)

    elems.append(Paragraph(f"[{mood_ko}] " + _esc(data.get("headline", "전략·시황 보고서")), s_head))
    meta = gen_at + (f" · {n_msg}개 메시지" if n_msg else "")
    elems.append(Paragraph(_esc(meta), s_meta))

    kt = data.get("key_takeaway", "")
    if kt:
        elems.append(Paragraph("오늘의 관전", s_kt_label))
        box = Table([[Paragraph(_esc(kt), s_kt)]], colWidths=[doc.width])
        box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BG),
            ("LINEBEFORE", (0, 0), (0, -1), 2, SAGE),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        elems.append(box)
        elems.append(Spacer(1, 12))

    # 시장 시각 vs 실제 데이터
    xc = data.get("cross_check")
    if isinstance(xc, dict) and (xc.get("market_view") or xc.get("data_fact")):
        vmap = {"align": "일치", "diverge": "괴리", "mixed": "혼재"}
        vko = vmap.get((xc.get("verdict") or "mixed").lower(), "혼재")
        elems.append(Paragraph(f"⚖ 시장 시각 vs 실제 데이터 [{vko}]", s_sec_title))
        row = Table(
            [[Paragraph("<b>시장 시각</b><br/>" + _esc(xc.get("market_view", "")), s_body),
              Paragraph("<b>실제 데이터</b><br/>" + _esc(xc.get("data_fact", "")), s_body)]],
            colWidths=[doc.width / 2, doc.width / 2])
        row.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BG),
            ("LINEAFTER", (0, 0), (0, -1), 0.5, HexColor("#D8DAD2")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        elems.append(row)
        if xc.get("insight"):
            elems.append(Spacer(1, 3))
            elems.append(Paragraph("해석 · " + _esc(xc["insight"]), s_theme_detail))
        elems.append(Spacer(1, 10))

    for sec in data.get("sections", []):
        if sec.get("title"):
            elems.append(Paragraph(_esc(sec["title"]), s_sec_title))
        if sec.get("body"):
            elems.append(Paragraph(_esc(sec["body"]), s_body))

    themes = data.get("themes", [])
    if themes:
        elems.append(Paragraph("주목 테마", s_group))
        for th in themes:
            elems.append(Paragraph(_esc(th.get("name", "")), s_theme_name))
            if th.get("detail"):
                elems.append(Paragraph(_esc(th["detail"]), s_theme_detail))
            if th.get("tickers"):
                elems.append(Paragraph("관련: " + _esc(th["tickers"]), s_theme_tk))
            elems.append(Spacer(1, 6))

    sources = data.get("source_channels", [])
    if sources:
        elems.append(Paragraph("출처: " + _esc(", ".join(sources)), s_src))

    doc.build(elems)
    return buf.getvalue()
