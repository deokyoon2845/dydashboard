"""[엔진] 텔레그램 메시지 → 구조화 JSON 시황 보고서 (2단계 파이프라인).

1차(Haiku): 메시지가 많으면 주제별 클러스터링·중복 제거 (저렴한 정제)
2차(Sonnet): 정제된 메시지 + 정량 데이터 + 뉴스 헤드라인 + 워치리스트로 심층 분석

핵심 지시: 채널 '의견'과 실제 '데이터·사실'을 교차 검증하고 불일치를 짚는다.
추가 컨텍스트: 다가오는 주요 일정(캘린더) + 최근 시황 흐름(직전 보고서) 주입.
"""

import json
import os
import re

from anthropic import Anthropic

MODEL = os.environ.get("REPORT_MODEL", "claude-opus-4-8")
HAIKU = "claude-haiku-4-5"
CLUSTER_THRESHOLD = int(os.environ.get("CLUSTER_THRESHOLD", "15"))  # 이 수↑면 1차 정제(Opus 입력비 절감)


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


def _strip_fence(raw):
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.lstrip().startswith("json"):
            raw = raw.lstrip()[4:]
        raw = raw.strip()
    return raw


# ── 추가 컨텍스트 빌더 (실패해도 보고서 생성에 영향 없음) ──────

def _build_calendar_block():
    """다가오는 주요 일정 (FOMC·금통위·CPI·실적) 블록. 실패/빈 일정 시 ''."""
    try:
        from engine.calendar_events import build_calendar_text
        text = build_calendar_text(days=14, include_earnings=True)
        if text:
            return f"\n\n=== 다가오는 주요 일정 (검증된 사실) ===\n{text}\n=== 끝 ==="
    except Exception:
        pass
    return ""


def _build_flow_block():
    """최근 시황 흐름 (직전 보고서들의 판단) 블록. 실패/보고서 없음 시 ''."""
    try:
        from engine.timeline_context import build_recent_flow_text
        text = build_recent_flow_text(5)
        if text:
            return f"\n\n=== 최근 시황 흐름 (참고용 맥락) ===\n{text}\n=== 끝 ==="
    except Exception:
        pass
    return ""


# ── 1차: 메시지 정제 (Haiku) ───────────────────────────────────

def _stage1_digest(client, corpus):
    prompt = (
        "다음은 텔레그램 시황 채널 메시지 원문입니다. 2차 심층 분석의 입력으로 쓸 수 있게 "
        "정제해주세요.\n\n"
        f"=== 원문 ===\n{corpus}\n=== 끝 ===\n\n"
        "정제 규칙:\n"
        "- 같은 내용의 중복 메시지는 하나로 합치세요.\n"
        "- 주제별로 묶어서 정리하세요 (주제 제목 + 핵심 내용).\n"
        "- 숫자·고유명사·팩트는 절대 빠뜨리지 말고 그대로 보존하세요.\n"
        "- 각 항목 끝에 (사실) 또는 (의견)을 표기해 사실과 채널의 의견을 구분하세요.\n"
        "- 광고·잡담·무의미한 메시지는 제외하세요.\n"
        "출력은 일반 텍스트로만."
    )
    resp = client.messages.create(
        model=HAIKU, max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    usage = {"model": HAIKU,
             "input_tokens": resp.usage.input_tokens,
             "output_tokens": resp.usage.output_tokens}
    return resp.content[0].text.strip(), usage


# ── 메인 분석 함수 ─────────────────────────────────────────────

def analyze_messages(messages, channel_name: str = "",
                     snapshot_text: str = "", news_titles=None, watchlist=None):
    """→ (report_dict, usage_dict)
    usage_dict: {"model": 표기용, "calls":[콜별 사용량], "input_tokens": 합, "output_tokens": 합}
    """
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

    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    calls = []

    # 1차 정제 (메시지가 많을 때만 — 비용 대비 효과)
    if len(lines) >= CLUSTER_THRESHOLD:
        digest, u1 = _stage1_digest(client, corpus)
        calls.append(u1)
        msg_block = f"=== 채널 메시지 (1차 정제·주제별 정리, 사실/의견 구분) ===\n{digest}\n=== 끝 ==="
    else:
        msg_block = f"=== 채널 메시지 원문 ===\n{corpus}\n=== 끝 ==="

    # 정량 데이터 블록
    quant_block = ""
    if snapshot_text:
        quant_block = f"\n\n=== 실제 시장 정량 데이터 (검증된 사실) ===\n{snapshot_text}\n=== 끝 ==="

    # 뉴스 헤드라인 블록 (멀티소스)
    news_block = ""
    if news_titles:
        nl = "\n".join(f"- {t}" for t in news_titles[:25])
        news_block = f"\n\n=== 오늘의 뉴스 헤드라인 (언론 보도) ===\n{nl}\n=== 끝 ==="

    # 다가오는 일정 + 최근 시황 흐름 블록
    cal_block = _build_calendar_block()
    flow_block = _build_flow_block()

    # 워치리스트 블록 + 스키마 확장
    watch_block, watch_schema = "", ""
    if watchlist:
        wl = ", ".join(watchlist)
        watch_block = f"\n\n=== 사용자 워치리스트 종목 ===\n{wl}\n=== 끝 ==="
        watch_schema = (
            ',"watchlist_mentions":[{"stock":"워치리스트 종목명","summary":"이 종목 관련 '
            '오늘의 언급·이슈 1-2문장. 언급이 전혀 없으면 이 종목은 배열에서 제외"}]'
        )

    prompt = (
        "당신은 한국 주식시장을 깊이 이해하는 베테랑 애널리스트입니다.\n"
        f"아래는 텔레그램 시황 채널({channel_name})의 메시지"
        + (", 실제 시장 정량 데이터, 언론 뉴스 헤드라인" if (snapshot_text or news_titles) else "")
        + (", 다가오는 주요 일정" if cal_block else "")
        + (", 최근 시황 흐름" if flow_block else "")
        + "입니다.\n"
        "개인 투자자가 장 시작 전에 읽고 '오늘 시장이 어떨지, 무엇을 봐야 할지' "
        "통찰을 얻을 수 있도록 깊이 있는 전략·시황 보고서를 작성하세요.\n\n"
        f"{msg_block}{quant_block}{news_block}{cal_block}{flow_block}{watch_block}\n\n"
        "작성 철학:\n"
        "- ★교차 검증: '시장 시각'(애널리스트·전문투자자 채널의 판단)을 정량 데이터·뉴스라는 "
        "'사실'과 대조하세요. 둘이 어긋나면 반드시 짚으세요 (예: '시장 시각은 반도체 낙관론이 "
        "우세하지만 실제 외국인은 순매도 지속'). 일치하면 그 시각의 신뢰도가 높다고 평가하세요.\n"
        + ("- 다가오는 일정이 제공되었습니다. 임박한 이벤트(FOMC·금통위·CPI·실적 등)가 "
           "오늘 시장 심리에 미치는 영향을 관전 포인트에 반영하세요 (예: 'D-2 FOMC를 앞둔 관망세').\n"
           if cal_block else "")
        + ("- '최근 시황 흐름'은 직전 보고서들의 판단입니다. 흐름과의 연속성·변화를 짚으세요 "
           "(예: '어제 주의로 본 레버리지 수급이 오늘 일부 해소'). 단, 과거 판단을 무비판적으로 "
           "답습하지 말고 오늘 데이터가 다르면 다르다고 쓰세요.\n"
           if flow_block else "")
        + "- 보고서 구조를 미리 정해두지 말고, 오늘 가장 중요한 흐름에 맞춰 섹션을 직접 구성하세요.\n"
        "- 단순 사실 나열이 아니라 '왜 그런가, 그래서 무엇을 의미하는가'까지 해석하세요.\n"
        "- 과장 금지. 입력에 없는 사실을 지어내지 마세요.\n"
        "- 투자 조언(매수/매도 단정)이 아니라 판단을 돕는 시장 이해의 관점으로 쓰세요.\n"
        "- ★JSON 안전: 문자열 값 안에 큰따옴표(\") 절대 금지. 강조는 작은따옴표(')나 「」 사용.\n\n"
        "다음 JSON만 반환 (다른 텍스트 없이):\n"
        '{"headline":"오늘 핵심 한 줄(35자 이내, 날짜 제외)",'
        '"key_takeaway":"오늘 투자자가 가장 주목해야 할 핵심 통찰·관전 포인트 2~3문장",'
        '"cross_check":{'
        '"market_view":"시장 시각(채널들의 판단·전망)을 1~2문장으로 요약",'
        '"data_fact":"실제 정량 데이터·뉴스가 말하는 사실을 1~2문장으로 요약",'
        '"verdict":"align 또는 diverge 또는 mixed",'
        '"insight":"둘을 대조한 결론·시사점 1~2문장"},'
        '"sections":['
        '{"title":"섹션 제목(오늘 내용에 맞게 직접 작명)","body":"본문 4~7문장"}'
        '],'
        '"themes":[{"name":"테마명","detail":"내용 2~3문장","tickers":"관련종목(쉼표구분)"}],'
        '"keywords":['
        '{"keyword":"핵심 키워드","desc":"왜 거론되는지 배경 한 줄(45자 이내)",'
        '"news_headline":"근본 원인 뉴스 헤드라인(주가 등락 표현 금지)","weight":10,"related":"관련종목"}'
        ']'
        f'{watch_schema},'
        '"mood":"positive 또는 neutral 또는 cautious"}\n\n'
        "sections 3~6개, keywords 정확히 10개(자주·중요 순), themes 3~6개. "
        "cross_check 는 '시장 시각 vs 실제 데이터'의 핵심 대조이며 반드시 채우세요"
        + (" (정량 데이터·뉴스가 제공되었습니다)." if (snapshot_text or news_titles)
           else ". 단, 정량 데이터가 없으면 market_view 위주로 쓰고 data_fact 는 뉴스 기반으로 채우세요.")
    )

    resp = client.messages.create(
        model=MODEL, max_tokens=6000,
        messages=[{"role": "user", "content": prompt}],
    )
    calls.append({"model": MODEL,
                  "input_tokens": resp.usage.input_tokens,
                  "output_tokens": resp.usage.output_tokens})

    result = _safe_json_parse(_strip_fence(resp.content[0].text))
    if result is None:
        raise ValueError("JSON 파싱 실패. 다시 시도해주세요.")

    result.setdefault("headline", "전략·시황 보고서")
    result.setdefault("key_takeaway", "")
    result.setdefault("cross_check", None)
    result.setdefault("sections", [])
    result.setdefault("themes", [])
    result.setdefault("keywords", [])
    result.setdefault("mood", "neutral")

    usage = {
        "model": MODEL + (" + haiku 정제" if len(calls) > 1 else ""),
        "calls": calls,
        "input_tokens": sum(c["input_tokens"] for c in calls),
        "output_tokens": sum(c["output_tokens"] for c in calls),
    }
    return result, usage
