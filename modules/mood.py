"""감성(mood) 3색 통일 팔레트 — 배지·차트·게이지·교차검증에서 공통 사용.

긍정 positive / 중립 neutral / 주의 cautious
각 항목: 라이트(fg, bg) · 다크(fg, bg)
"""

MOOD_KO = {"positive": "긍정", "neutral": "중립", "cautious": "주의"}

# 메인 색(라이트 / 다크) — 그래프 선·게이지 등 채도 있는 용도
MOOD_MAIN = {
    "positive": ("#2E7D5B", "#7FD3B4"),
    "neutral":  ("#7E9A83", "#A8D8C0"),
    "cautious": ("#C2410C", "#F0A36B"),
}

# 배경 톤(라이트 / 다크) — 배지·박스 배경
MOOD_BG = {
    "positive": ("#E1F5EE", "#0C4435"),
    "neutral":  ("#EDF1EC", "#33403A"),
    "cautious": ("#FBEADF", "#4F2E18"),
}

# 배지 글자색(라이트 / 다크)
MOOD_FG = {
    "positive": ("#0F6E56", "#9FE1CB"),
    "neutral":  ("#5A6B5E", "#BFD6C5"),
    "cautious": ("#9C4318", "#F0B58C"),
}


def mood_main(mood: str, dark: bool = False) -> str:
    light, dk = MOOD_MAIN.get(mood, MOOD_MAIN["neutral"])
    return dk if dark else light


def mood_css(prefix: str = "mood") -> str:
    """배지용 CSS 규칙 문자열 생성 (.{prefix}-pos/-neu/-cau, 다크 포함)."""
    keys = {"positive": "pos", "neutral": "neu", "cautious": "cau"}
    out = []
    for m, sfx in keys.items():
        lb, db = MOOD_BG[m]
        lf, df = MOOD_FG[m]
        out.append(f".{prefix}-{sfx}{{background:{lb};color:{lf};}}")
        out.append(f".app.dark .{prefix}-{sfx}{{background:{db};color:{df};}}")
    return "\n".join(out)
