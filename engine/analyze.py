"""[엔진] 텔레그램 메시지를 Claude API로 분석해 마크다운 보고서 본문을 생성."""

from anthropic import Anthropic

# 모델 선택 (한 줄만 바꾸면 됩니다):
#   claude-sonnet-4-6  : 품질/비용 균형 (기본 추천)
#   claude-haiku-4-5   : 더 빠르고 저렴 (가벼운 요약)
#   claude-opus-4-8    : 가장 깊은 분석 (비용 높음)
MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = (
    "당신은 신중한 한국 금융시장 애널리스트입니다. "
    "텔레그램 채널의 시황 메시지들을 받아 한국어로 간결한 시황 분석 보고서를 작성합니다. "
    "메시지에 실제로 담긴 내용에만 근거하고, 없는 사실을 지어내지 마세요. "
    "수치나 종목이 불확실하면 단정하지 말고 '언급됨' 수준으로 표현하세요. "
    "이 보고서는 정보 정리용이며 투자 권유가 아님을 마지막에 한 줄로 명시하세요."
)


def analyze_messages(messages, channel_name: str = "") -> str:
    """messages: [{'date':..., 'text':...}, ...] -> 마크다운 보고서 본문(str)."""
    joined = "\n\n".join(
        f"[{m['date']:%Y-%m-%d %H:%M}] {m['text']}" for m in messages
    )

    user_prompt = (
        f"다음은 '{channel_name}' 채널의 최근 메시지입니다. "
        "이를 바탕으로 아래 형식의 시황 분석 보고서를 마크다운으로 작성하세요.\n\n"
        "## 한 줄 요약\n"
        "## 주요 이슈\n(불릿으로 5~10개)\n"
        "## 언급된 종목·섹터\n"
        "## 시장 분위기\n(긍정 / 중립 / 부정 중 하나 + 근거)\n"
        "## 유의사항\n\n"
        "----- 메시지 시작 -----\n"
        f"{joined}\n"
        "----- 메시지 끝 -----"
    )

    client = Anthropic()  # ANTHROPIC_API_KEY 환경변수에서 자동으로 읽음
    resp = client.messages.create(
        model=MODEL,
        max_tokens=5000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = resp.content[0].text
    usage = {
        "model": MODEL,
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
    }
    return text, usage
