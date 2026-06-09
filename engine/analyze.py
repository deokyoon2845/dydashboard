"""[엔진] 텔레그램 메시지 → 구조화 JSON 시황 보고서.

반환: (report_dict, usage_dict)
  report_dict 스키마:
    headline, key_takeaway, sections[], themes[], keywords[], mood,
    source_channels[]
"""

import json
import os
import re

from anthropic import Anthropic

MODEL = os.environ.get("REPORT_MODEL", "claude-sonnet-4-6")


# ── JSON 파싱 헬퍼 ─────────────────────────────────────────────

def _fix_inner_quotes(text):
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if not in_str:
            out.append(c)
            if c == '"': in_str = True
            i += 1; continue
        if c == '\\' and i + 1 < n:
            out.append(c); out.append(text[i+1]); i += 2; continue
        if c == '"':
            j = i + 1
            while j < n and text[j] in " \t\r\n": j += 1
            nxt = text[j] if j < n else ""
            if nxt in (":", ",", "}", "]", ""):
                out.append(c); in_str = False; i += 1
            else:
                out.append('\\"'); i += 1
            continue
        out.append(c); i += 1
    return "".join(out)


def _safe_json_parse(raw):
    for fn in (lambda t: t, _fix_inner_quotes):
        t = fn(raw)
        try: return json.loads(t)
        except Exception: pass
        s, e = t.find("{"), t.rfind("}")
        chunk = t[s:e+1] if (s != -1 and e != -1 and e > s) else t
        try: return json.loads(chunk)
        except Exception: pass
        try:
            fixed = re.sub(r",\s*$", "", chunk)
            if fixed.count('"') % 2 == 1: fixed += '"'
            fixed += "]" * max(0, fixed.count("[") - fixed.count("]"))
            fixed += "}" * max(0, fixed.count("{") - fixed.count("}"))
            return json.loads(fixed)
        except Exception: pass
    return None


# ── 메인 분석 함수 ─────────────────────────────────────────────

def analyze_messages(messages, channel_name: str = ""):
    """messages: [{'date':..., 'text':..., 'channel':...}, ...]
    → (report_dict, usage_dict)"""

    lines = []
    for m in messages:
        ch = m.get("channel", channel_name)
        ds = str(m.get("date", ""))[:16]
        txt = (m.get("text") or "").strip()
        if txt:
            lines.append(f"[{ch}] ({ds}) {txt}")

    corpus = "\n".join(lines)
    if len(corpus) > 45000:
        corpus = corpus[:45000] + "\n…(이하 생략)"

    prompt = (
        "당신은 한국 주식시장을 깊이 이해하는 베테랑 애널리스트입니다. "
        f"아래는 텔레그램 시황 채널({channel_name})에 올라온 메시지 전체입니다.\n"
        "개인 투자자가 오늘 장 시작 전에 읽고 '오늘 시장이 어떨지, 무엇을 봐야 할지' "
        "통찰을 얻을 수 있도록, 깊이 있는 시황 보고서를 작성하세요.\n\n"
        f"=== 메시지 모음 ===\n{corpus}\n=== 끝 ===\n\n"
        "작성 철학:\n"
        "- 보고서 구조를 미리 정해두지 마세요. 오늘 메시지에서 가장 중요한 흐름이 무엇인지 "
        "먼저 판단하고, 그에 맞춰 섹션을 스스로 구성하세요.\n"
        "- 단순 사실 나열이 아니라 '왜 그런가, 그래서 무엇을 의미하는가'까지 해석하세요.\n"
        "- 과장 금지. 메시지에 없는 사실을 지어내지 마세요.\n"
        "- 투자 조언(매수/매도 단정)이 아니라 판단을 돕는 시장 이해의 관점으로 쓰세요.\n"
        "- ★JSON 안전: 문자열 값 안에 큰따옴표(\") 절대 금지. 강조는 작은따옴표(')나 「」 사용.\n\n"
        "다음 JSON만 반환 (다른 텍스트 없이):\n"
        '{"headline":"오늘 핵심 한 줄(35자 이내, 날짜 제외)",'
        '"key_takeaway":"오늘 투자자가 가장 주목해야 할 핵심 통찰·관전 포인트 2~3문장",'
        '"sections":['
        '{"title":"섹션 제목(오늘 내용에 맞게 직접 작명, 예: 미국 금리 재부각)","body":"본문 4~7문장"}'
        '],'
        '"themes":[{"name":"테마명","detail":"내용 2~3문장","tickers":"관련종목(쉼표구분)"}],'
        '"keywords":['
        '{"keyword":"핵심 키워드","desc":"왜 거론되는지 배경 한 줄(45자 이내)",'
        '"news_headline":"근본 원인 뉴스 헤드라인(주가 등락 표현 금지)","weight":10,"related":"관련종목"}'
        '],'
        '"mood":"positive 또는 neutral 또는 cautious"}\n\n'
        "sections 3~6개, keywords 정확히 10개(자주·중요 순), themes 3~6개."
    )

    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    msg = client.messages.create(
        model=MODEL, max_tokens=6000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.lstrip().startswith("json"):
            raw = raw.lstrip()[4:]
        raw = raw.strip()

    result = _safe_json_parse(raw)
    if result is None:
        raise ValueError(f"JSON 파싱 실패. 끝부분: …{raw[-120:]}")

    result.setdefault("headline", "시황 분석 보고서")
    result.setdefault("key_takeaway", "")
    result.setdefault("sections", [])
    result.setdefault("themes", [])
    result.setdefault("keywords", [])
    result.setdefault("mood", "neutral")

    usage = {
        "model": MODEL,
        "input_tokens": msg.usage.input_tokens,
        "output_tokens": msg.usage.output_tokens,
    }
    return result, usage
