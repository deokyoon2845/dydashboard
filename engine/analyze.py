"""[엔진] 텔레그램 메시지 → 구조화 JSON 시황 보고서 (2단계 파이프라인, 장전/장후 양식 분리).

1차(Haiku): 메시지가 많으면 주제별 클러스터링·중복 제거 (저렴한 정제)
2차(Opus): 정제된 메시지 + 정량 데이터 + 뉴스 헤드라인 + 워치리스트로 심층 분석

양식 분리:
- 장전(pre):  전일 마감 이후~현재(특히 미국장) 정리 → 오늘 한국 장 예측
- 장후(post): 오늘 한국 장 결산 → 오늘 밤 미국장 / 다음 한국 장 전망

핵심 지시: 채널 '의견'과 실제 '데이터·사실'을 교차 검증하고 불일치를 짚는다.
누락 금지: 분량을 이유로 메시지 내용을 빼지 않는다(중복만 압축).
추가: 오늘의 시장 동력 매트릭스(단기/장기 × 상승/하락) — 프레임 고정, 내용은 보고서별 생성.
"""

import json
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from anthropic import Anthropic

MODEL = os.environ.get("REPORT_MODEL", "claude-opus-4-8")
HAIKU = "claude-haiku-4-5"
CLUSTER_THRESHOLD = int(os.environ.get("CLUSTER_THRESHOLD", "15"))  # 이 수↑면 1차 정제

_WD = "월화수목금토일"

# 장전/장후 양식 정의 — 프롬프트 톤·목표를 분기
_KIND_INFO = {
    "pre": {
        "ko": "장전(개장 전) 보고서",
        "window": "전일 장 마감(15:30) 이후부터 오늘 아침까지 — 특히 간밤 미국 증시 흐름",
        "goal": ("간밤 해외(특히 미국장) 흐름과 전일 마감 이후의 이슈를 정리하고, "
                 "오늘 한국 장(코스피·코스닥)이 어떻게 출발·전개될지 예상하는 것"),
        "reader": "개인 투자자가 장 시작 전에 읽고 '오늘 무엇을 봐야 할지' 통찰을 얻도록",
        "matrix_view": "오늘 한국 장에 대한 '예측' 관점 (개장 전이라 결과는 아직 없음)",
    },
    "post": {
        "ko": "장마감 후 보고서",
        "window": "오늘 아침(07:50)부터 한국 장 마감 이후까지 — 오늘 한국 장에서 일어난 일",
        "goal": ("오늘 한국 장에서 무슨 일이 있었는지 원인과 함께 결산하고, "
                 "오늘 밤 미국장과 다음 한국 장을 전망하는 것"),
        "reader": "개인 투자자가 장 마감 후 읽고 '오늘을 정리하고 다음 장을 어떻게 볼지' 잡도록",
        "matrix_view": "오늘 장 '결과'를 반영하고, 다음 장(미국장·익일 국장) 전망까지 담은 관점",
    },
}


def _today_kst_str() -> str:
    """'2026-06-12(금)' 형태의 오늘(KST) 날짜 문자열."""
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    return f"{now.strftime('%Y-%m-%d')}({_WD[now.weekday()]})"


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
    try:
        from engine.calendar_events import build_calendar_text
        text = build_calendar_text(days=14, include_earnings=True)
        if text:
            return f"\n\n=== 다가오는 주요 일정 (검증된 사실) ===\n{text}\n=== 끝 ==="
    except Exception:
        pass
    return ""


def _build_flow_block():
    try:
        from engine.timeline_context import build_recent_flow_text
        text = build_recent_flow_text(5)
        if text:
            return f"\n\n=== 최근 시황 흐름 (참고용 맥락) ===\n{text}\n=== 끝 ==="
    except Exception:
        pass
    return ""


# ── 1차: 메시지 정제 (Haiku) ───────────────────────────────────

def _stage1_digest(client, corpus, info):
    today = _today_kst_str()
    prompt = (
        f"다음은 텔레그램 시황 채널 메시지 원문입니다({info['ko']} 작성용). "
        "2차 심층 분석의 입력으로 쓸 수 있게 정제해주세요.\n\n"
        f"기준 정보: 오늘은 {today}입니다. 각 메시지 머리에 [채널] (작성시각)이 붙어 있으며, "
        f"메시지는 {info['window']} 동안 수집된 것입니다.\n\n"
        f"=== 원문 ===\n{corpus}\n=== 끝 ===\n\n"
        "정제 규칙:\n"
        "- ★누락 금지(최우선): 서로 다른 사실·이슈·종목·수치는 분량을 이유로 빼지 마세요. "
        "오직 '같은 내용의 중복'만 하나로 합치세요. 길어져도 됩니다.\n"
        "- 주제별로 묶어서 정리하세요 (주제 제목 + 핵심 내용).\n"
        "- 숫자·고유명사·팩트는 절대 빠뜨리지 말고 그대로 보존하세요.\n"
        "- ★날짜 명확화: 메시지 속 '오늘·어제·금일·전일' 같은 상대 표현은 그 메시지의 "
        "작성시각 기준이므로 그대로 옮기면 날짜가 뒤섞입니다. 작성시각을 보고 실제 날짜로 "
        "환산해 'MM/DD' 형태로 바꿔 쓰세요. 판단이 안 되면 작성시각을 그대로 병기하세요.\n"
        "- ★원인 보존(최우선): 가격·지수·섹터가 움직인 '이유'가 원문에 있으면 결과 수치와 "
        "반드시 한 묶음으로 보존하세요. '반도체 급등'처럼 결과만 남기지 말고 "
        "'○○ 실적 서프라이즈 → 반도체 급등'처럼 원인→결과로 쓰세요.\n"
        "- 각 항목 끝에 (사실) 또는 (의견)을 표기해 사실과 채널 의견을 구분하세요.\n"
        "- 광고·잡담·무의미한 메시지는 제외하세요.\n"
        "출력은 일반 텍스트로만."
    )
    resp = client.messages.create(
        model=HAIKU, max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    usage = {"model": HAIKU,
             "input_tokens": resp.usage.input_tokens,
             "output_tokens": resp.usage.output_tokens}
    return resp.content[0].text.strip(), usage


# ── 메인 분석 함수 ─────────────────────────────────────────────

def analyze_messages(messages, kind: str = "pre", channel_name: str = "",
                     snapshot_text: str = "", news_titles=None, watchlist=None):
    """→ (report_dict, usage_dict)
    kind: 'pre'(장전) 또는 'post'(장후) — 보고서 양식·매트릭스 관점을 분기.
    """
    info = _KIND_INFO.get(kind, _KIND_INFO["pre"])

    lines = []
    for m in messages:
        ch = m.get("channel", channel_name)
        ds = str(m.get("date", ""))[:16]
        txt = (m.get("text") or "").strip()
        if txt:
            lines.append(f"[{ch}] ({ds}) {txt}")

    corpus = "\n".join(lines)
    # 누락 방지를 위해 상한을 넉넉히 (Haiku가 뒤에서 중복 압축). 극단적으로 길 때만 자름.
    if len(corpus) > 100000:
        corpus = corpus[:100000] + "\n…(이하 생략)"

    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    calls = []

    # 1차 정제 (메시지가 많을 때만 — 비용 대비 효과)
    if len(lines) >= CLUSTER_THRESHOLD:
        digest, u1 = _stage1_digest(client, corpus, info)
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

    cal_block = _build_calendar_block()
    flow_block = _build_flow_block()

    # 워치리스트 블록 + 스키마 확장
    watch_block, watch_schema = "", ""
    if watchlist:
        wl = ", ".join(watchlist)
        watch_block = f"\n\n=== 사용자 워치리스트 종목 ===\n{wl}\n=== 끝 ==="
        watch_schema = (
            ',"watchlist_mentions":[{"stock":"워치리스트 종목명","summary":"이 종목 관련 '
            '언급·이슈 1-2문장. 언급이 전혀 없으면 이 종목은 배열에서 제외"}]'
        )

    today = _today_kst_str()
    prompt = (
        "당신은 한국 주식시장을 깊이 이해하는 베테랑 애널리스트입니다.\n"
        f"지금 작성하는 것은 ★{info['ko']}★ 입니다. 작성일(오늘)은 {today}이고, "
        "모든 '오늘·전일·간밤' 표현은 이 날짜 기준입니다.\n"
        f"이 보고서의 목표: {info['goal']}.\n"
        f"수집된 메시지 구간: {info['window']}.\n\n"
        f"아래는 텔레그램 시황 채널({channel_name})의 메시지"
        + (", 실제 시장 정량 데이터, 언론 뉴스 헤드라인" if (snapshot_text or news_titles) else "")
        + (", 다가오는 주요 일정" if cal_block else "")
        + (", 최근 시황 흐름" if flow_block else "")
        + "입니다.\n"
        f"{info['reader']} 깊이 있는 전략·시황 보고서를 작성하세요.\n\n"
        f"{msg_block}{quant_block}{news_block}{cal_block}{flow_block}{watch_block}\n\n"
        "작성 철학:\n"
        + ("- ★장전 관점: 결과를 단정하지 말고, 간밤 미국장·해외 흐름이 오늘 한국 장에 미칠 "
           "영향을 '예상' 중심으로 쓰세요. '오늘(개장 전) 무엇을 주목해야 하는가'가 핵심입니다.\n"
           if kind == "pre" else
           "- ★장후 관점: 오늘 한국 장에서 실제로 무슨 일이 있었는지(지수·수급·주도 섹터·원인) "
           "결산하고, 이어서 오늘 밤 미국장과 다음 한국 장(익일) 전망까지 한 호흡으로 쓰세요.\n")
        + "- ★누락 금지: 입력에 담긴 서로 다른 사실·이슈·종목은 분량을 이유로 빼지 마세요. "
        "중복만 합치고, 길어지더라도 중요한 내용은 모두 살리세요. 섹션 수는 내용에 맞춰 늘려도 됩니다.\n"
        "- ★날짜 구분: '오늘·전일(어제)·간밤'을 각각 처음 언급할 때 날짜를 병기하세요 "
        "(예: '간밤(06/11 미국장) 반도체 +7.9%', '오늘(06/12, 금)'). 이후 반복 시 생략 가능.\n"
        "- ★인과 사슬(가장 중요): 주요 변동을 언급할 때 반드시 '무엇이 촉발했는가(원인)'를 "
        "함께 쓰세요. '미국 증시가 상승했다' 식 표면 서술 금지. '원인 → 결과 → 국내 파급 경로' "
        "사슬로 한 단계 이상 파고드세요. 입력에 원인이 없으면 지어내지 말고 "
        "'촉발 요인은 입력 자료에서 확인되지 않음'이라고 명시하세요.\n"
        "- ★교차 검증: '시장 시각'(채널 판단)을 정량 데이터·뉴스라는 '사실'과 대조하세요. "
        "어긋나면 반드시 짚고, 일치하면 신뢰도가 높다고 평가하세요.\n"
        + ("- 임박한 이벤트(FOMC·금통위·CPI·실적 등)가 오늘 시장 심리에 미치는 영향을 반영하세요.\n"
           if cal_block else "")
        + ("- '최근 시황 흐름'은 직전 보고서들의 판단입니다. 연속성·변화를 짚되, 오늘 데이터가 "
           "다르면 다르다고 쓰세요.\n" if flow_block else "")
        + "- 단순 사실 나열이 아니라 '왜 그런가, 그래서 무엇을 의미하는가'까지 해석하세요.\n"
        "- 과장·창작 금지. 입력에 없는 사실을 지어내지 마세요. 투자 조언(매수/매도 단정)이 아니라 "
        "판단을 돕는 시장 이해의 관점으로 쓰세요.\n"
        "- ★JSON 안전: 문자열 값 안에 큰따옴표(\") 절대 금지. 강조는 작은따옴표(')나 「」 사용.\n\n"
        "─ 오늘의 시장 동력 매트릭스(market_drivers) 작성 규칙 ─\n"
        "프레임은 고정입니다: 시계열(short_term=단기: 수급·심리·노이즈 / long_term=장기: 거시·실적·정책) "
        "× 방향(up=상승·모멘텀 요인 / down=하락·리스크 요인). 이 4칸을 입력 자료 근거로 채우세요.\n"
        f"이 보고서의 매트릭스 관점: {info['matrix_view']}.\n"
        "각 칸은 0~3개 항목. 항목은 {{label, desc}} 형태로, label은 짧은 핵심어(대괄호 없이, "
        "예: 외국인 숏커버링), desc는 근거가 담긴 한 줄(수치·원인 포함). 근거가 없으면 빈 배열로 두세요.\n\n"
        "다음 JSON만 반환 (다른 텍스트 없이):\n"
        '{"headline":"핵심 한 줄(35자 이내, 날짜 제외)",'
        '"key_takeaway":"가장 주목해야 할 핵심 통찰 2~3문장",'
        '"cross_check":{'
        '"market_view":"시장 시각(채널 판단)을 1~2문장 요약",'
        '"data_fact":"실제 정량 데이터·뉴스가 말하는 사실을 1~2문장 요약",'
        '"verdict":"align 또는 diverge 또는 mixed",'
        '"insight":"둘을 대조한 결론·시사점 1~2문장"},'
        '"market_drivers":{'
        '"short_term":{"up":[{"label":"요인 핵심어","desc":"근거 한 줄"}],'
        '"down":[{"label":"요인 핵심어","desc":"근거 한 줄"}]},'
        '"long_term":{"up":[{"label":"요인 핵심어","desc":"근거 한 줄"}],'
        '"down":[{"label":"요인 핵심어","desc":"근거 한 줄"}]}},'
        '"sections":['
        '{"title":"섹션 제목(오늘 내용에 맞게 직접 작명)",'
        '"body":"본문 4~7문장. 주요 변동은 원인→결과→시사점의 인과 사슬로 서술"}'
        '],'
        '"themes":[{"name":"테마명",'
        '"detail":"내용 2~3문장. 이 테마가 왜 지금 부각되는지 촉발 요인을 첫 문장에 명시",'
        '"tickers":"관련종목(쉼표구분)"}],'
        '"keywords":['
        '{"keyword":"핵심 키워드","desc":"왜 거론되는지 배경 한 줄(45자 이내)",'
        '"news_headline":"근본 원인 뉴스 헤드라인(주가 등락 표현 금지)","weight":10,"related":"관련종목"}'
        ']'
        f'{watch_schema},'
        '"mood":"positive 또는 neutral 또는 cautious"}\n\n'
        "sections는 내용에 맞게 충분히(보통 4~8개), keywords 정확히 10개(자주·중요 순), "
        "themes 3~6개. cross_check 와 market_drivers 는 반드시 채우세요"
        + (" (정량 데이터·뉴스가 제공되었습니다)." if (snapshot_text or news_titles)
           else ". 단, 정량 데이터가 없으면 market_view 위주로 쓰고 data_fact 는 뉴스 기반으로 채우세요.")
    )

    resp = client.messages.create(
        model=MODEL, max_tokens=8000,
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
    result.setdefault("market_drivers",
                      {"short_term": {"up": [], "down": []},
                       "long_term": {"up": [], "down": []}})
    result.setdefault("sections", [])
    result.setdefault("themes", [])
    result.setdefault("keywords", [])
    result.setdefault("mood", "neutral")
    result.setdefault("report_kind", kind)

    usage = {
        "model": MODEL + (" + haiku 정제" if len(calls) > 1 else ""),
        "calls": calls,
        "input_tokens": sum(c["input_tokens"] for c in calls),
        "output_tokens": sum(c["output_tokens"] for c in calls),
    }
    return result, usage
