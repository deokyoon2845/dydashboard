"""[엔진] 텔레그램 메시지 → 구조화 JSON 시황 보고서 (2단계 파이프라인, 장전/장후 양식 분리).

재설계(2026-06): 목적 분리 + 주제 클러스터링 기반 새 양식.

1차(Haiku): 메시지를 '주제 클러스터'로 구조화 — 주제별 핵심·언급량·합의/이견·사실/의견 구분
2차(Opus): 클러스터 + 정량 데이터 + 뉴스 + 어제 보고서 + 워치리스트로 최종 보고서 생성

새 스키마(topics 중심):
- headline / mood / snapshot_line
- topics[]: {title, importance, fact, market_view{consensus,dissent}, metrics, implication, stocks[]}
  · 상위 5~6개만, 각 필드 문장 수 제한 → 길이 자동 통제
  · 기존 market_drivers(매트릭스)·cross_check(교차검증)를 topics로 흡수 (중복 제거)
- outlook: 장전=오늘 볼 것 / 장마감=장전 점검+내일 가설  (목적별 분기 = 중복 방지)
- change_tracking: 어제 대비 새 주제 / 지속 주제  (매일 반복 방지)

과거 호환: 뷰어는 topics가 있으면 새 카드, 없으면 기존 sections로 폴백.
잘림 방지: Opus 출력이 max_tokens로 끊기면 이어받아(continuation) 완성.
"""

import json
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from anthropic import Anthropic

MODEL = os.environ.get("REPORT_MODEL", "claude-opus-4-8")
HAIKU = "claude-haiku-4-5"
CLUSTER_THRESHOLD = int(os.environ.get("CLUSTER_THRESHOLD", "12"))  # 이 수↑면 1차 클러스터링
MAX_TOKENS = int(os.environ.get("REPORT_MAX_TOKENS", "16000"))
MAX_CONTINUE = 2

MAX_TOPICS = int(os.environ.get("REPORT_MAX_TOPICS", "6"))  # 주제 카드 상한

_WD = "월화수목금토일"

_KIND_INFO = {
    "pre": {
        "ko": "장전(개장 전) 보고서",
        "window": "전일 장 마감(15:30) 이후부터 오늘 아침까지 — 특히 간밤 미국 증시 흐름",
        "goal": ("간밤 해외(특히 미국장) 흐름과 전일 마감 이후 이슈를 정리해, "
                 "오늘 한국 장에서 '무엇을 보고 어떻게 대응할지'를 제시하는 것 (앞을 보는 문서)"),
        "reader": "개인 투자자가 장 시작 전에 읽고 '오늘 무엇을 주목할지' 행동 지침을 얻도록",
    },
    "post": {
        "ko": "장마감 후 보고서",
        "window": "오늘 아침(07:50)부터 한국 장 마감 이후까지 — 오늘 한국 장에서 일어난 일",
        "goal": ("오늘 한국 장에서 무슨 일이 왜 일어났는지 데이터로 결산하고, "
                 "시장 시각의 합의/이견을 정리하는 것 (뒤를 정리하는 문서)"),
        "reader": "개인 투자자가 장 마감 후 읽고 '오늘을 이해하고 내일 가설을 세울' 재료를 얻도록",
    },
}


def _today_kst_str() -> str:
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    return f"{now.strftime('%Y-%m-%d')}({_WD[now.weekday()]})"


# ── JSON 파싱 헬퍼 ─────────────────────────────────────────────

def _fix_inner_quotes(text):
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if not in_str:
            out.append(c)
            if c == '"':
                in_str = True
            i += 1
            continue
        if c == '\\' and i + 1 < n:
            out.append(c); out.append(text[i + 1]); i += 2; continue
        if c == '"':
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
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
        try:
            return json.loads(t)
        except Exception:
            pass
        s, e = t.find("{"), t.rfind("}")
        chunk = t[s:e + 1] if (s != -1 and e != -1 and e > s) else t
        try:
            return json.loads(chunk)
        except Exception:
            pass
        try:
            fixed = re.sub(r",\s*$", "", chunk)
            if fixed.count('"') % 2 == 1:
                fixed += '"'
            fixed += "]" * max(0, fixed.count("[") - fixed.count("]"))
            fixed += "}" * max(0, fixed.count("{") - fixed.count("}"))
            return json.loads(fixed)
        except Exception:
            pass
    return None


def _strip_fence(raw):
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.lstrip().startswith("json"):
            raw = raw.lstrip()[4:]
        raw = raw.strip()
    return raw


# ── Opus 호출 + 잘림 이어받기 ──────────────────────────────────

def _create_with_continuation(client, model, prompt, max_tokens):
    msgs = [{"role": "user", "content": prompt}]
    full, calls, truncated = "", [], False
    for _ in range(MAX_CONTINUE + 1):
        resp = client.messages.create(model=model, max_tokens=max_tokens, messages=msgs)
        calls.append({"model": model,
                      "input_tokens": resp.usage.input_tokens,
                      "output_tokens": resp.usage.output_tokens})
        piece = resp.content[0].text if resp.content else ""
        full += piece
        if resp.stop_reason != "max_tokens":
            truncated = False
            break
        truncated = True
        msgs = [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": full},
            {"role": "user", "content":
                "위 JSON이 중간에 끊겼습니다. 끊긴 바로 다음 글자부터 이어서 출력하세요. "
                "이미 출력한 부분을 반복하지 말고, 설명·코드펜스 없이 JSON 나머지만 "
                "이어 붙여 닫는 중괄호까지 완성하세요."},
        ]
    return full, calls, truncated


# ── 추가 컨텍스트 빌더 ─────────────────────────────────────────

def _build_calendar_block():
    try:
        from engine.calendar_events import build_calendar_text
        text = build_calendar_text(days=14, include_earnings=True)
        if text:
            return f"\n\n=== 다가오는 주요 일정 (검증된 사실) ===\n{text}\n=== 끝 ==="
    except Exception:
        pass
    return ""


# ── 1차: 메시지 클러스터링 (Haiku, 구조화 JSON) ────────────────

def _stage1_cluster(client, corpus, info):
    """메시지를 주제 클러스터로 구조화. 텍스트가 아니라 JSON으로 반환.

    각 클러스터: {topic, mention_count, facts[], consensus, dissent, stocks[]}
    - mention_count: 이 주제를 다룬 메시지 수 (= 시장의 관심도 신호)
    - facts: 사실 위주 핵심 (수치·원인 보존)
    - consensus: 채널 다수가 동의하는 시각 / dissent: 갈리는 시각(없으면 빈 문자열)
    """
    today = _today_kst_str()
    prompt = (
        f"다음은 텔레그램 시황 채널 메시지 원문입니다({info['ko']} 작성용). "
        "이를 '주제 클러스터'로 구조화하세요. 100여 개 메시지라도 실제 화제는 10개 안팎입니다.\n\n"
        f"기준: 오늘은 {today}. 각 메시지 머리에 [채널] (작성시각)이 붙어 있고, "
        f"{info['window']} 동안 수집됐습니다.\n\n"
        f"=== 원문 ===\n{corpus}\n=== 끝 ===\n\n"
        "규칙:\n"
        "- 비슷한 주제의 메시지를 하나의 클러스터로 묶으세요. 같은 화제면 채널이 달라도 한 묶음.\n"
        "- ★언급량(mention_count): 그 주제를 다룬 메시지 수를 세세요. 시장 관심도 신호입니다.\n"
        "- ★합의/이견: 같은 주제 안에서 채널 다수가 동의하는 시각은 consensus에, "
        "소수·반대 시각이 있으면 dissent에 적으세요. 이견이 없으면 dissent는 빈 문자열.\n"
        "- ★사실 보존: facts에는 수치·고유명사·원인을 그대로. '반도체 급등'이 아니라 "
        "'○○ 실적 서프라이즈 → 반도체 +7%'처럼 원인→결과로.\n"
        "- ★날짜 환산: 메시지 속 '오늘·어제·간밤'은 작성시각 기준이므로 실제 'MM/DD'로 환산.\n"
        "- 광고·잡담·인사·단순 링크는 제외.\n"
        "- 언급량이 많은 주제부터 정렬.\n\n"
        "다음 JSON만 반환 (설명·코드펜스 없이):\n"
        '{"clusters":[{'
        '"topic":"주제명(짧게)",'
        '"mention_count":정수,'
        '"facts":["사실 핵심 1(수치·원인 포함)","사실 핵심 2"],'
        '"consensus":"채널 다수 시각 1문장(없으면 빈 문자열)",'
        '"dissent":"갈리는 시각 1문장(없으면 빈 문자열)",'
        '"stocks":["관련 종목명"]}'
        ']}'
    )
    resp = client.messages.create(
        model=HAIKU, max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    usage = {"model": HAIKU,
             "input_tokens": resp.usage.input_tokens,
             "output_tokens": resp.usage.output_tokens}
    parsed = _safe_json_parse(_strip_fence(resp.content[0].text))
    clusters = (parsed or {}).get("clusters", []) if isinstance(parsed, dict) else []
    return clusters, resp.content[0].text.strip(), usage


def _clusters_to_block(clusters):
    """클러스터 JSON을 Opus 입력용 읽기 좋은 텍스트로."""
    if not clusters:
        return ""
    parts = []
    for c in clusters:
        if not isinstance(c, dict):
            continue
        topic = str(c.get("topic", "")).strip()
        mc = c.get("mention_count", "")
        facts = c.get("facts", []) or []
        cons = str(c.get("consensus", "")).strip()
        diss = str(c.get("dissent", "")).strip()
        stocks = c.get("stocks", []) or []
        block = [f"● 주제: {topic} (언급 {mc}건)"]
        for f in facts:
            block.append(f"   - 사실: {f}")
        if cons:
            block.append(f"   - 합의 시각: {cons}")
        if diss:
            block.append(f"   - 이견: {diss}")
        if stocks:
            block.append(f"   - 관련 종목: {', '.join(str(s) for s in stocks)}")
        parts.append("\n".join(block))
    return "\n\n".join(parts)


# ── 어제 보고서 비교 (변화 추적) ───────────────────────────────

def _prev_topics_block(prev_report):
    """어제(직전) 보고서의 주제 제목 목록을 텍스트로. 변화 추적용."""
    if not prev_report:
        return "", []
    titles = []
    for t in (prev_report.get("topics") or []):
        if isinstance(t, dict) and t.get("title"):
            titles.append(str(t["title"]).strip())
    # 구형 보고서 폴백: sections 제목
    if not titles:
        for s in (prev_report.get("sections") or []):
            if isinstance(s, dict) and s.get("title"):
                titles.append(str(s["title"]).strip())
    if not titles:
        return "", []
    block = ("\n\n=== 직전 보고서의 주제 (변화 추적용) ===\n"
             + "\n".join(f"- {t}" for t in titles) + "\n=== 끝 ===")
    return block, titles


# ── 길이·형식 통제 ─────────────────────────────────────────────

def _cap_topics(topics, max_n=MAX_TOPICS):
    """주제 카드를 importance 내림차순 상위 max_n개로 제한, 형식 정규화."""
    if not isinstance(topics, list):
        return []
    clean = []
    for t in topics:
        if not isinstance(t, dict):
            continue
        title = str(t.get("title", "")).strip()
        if not title:
            continue
        mv = t.get("market_view") or {}
        if not isinstance(mv, dict):
            mv = {}
        clean.append({
            "title": title,
            "importance": int(t["importance"]) if str(t.get("importance", "")).isdigit() else 5,
            "fact": str(t.get("fact", "")).strip(),
            "market_view": {
                "consensus": str(mv.get("consensus", "")).strip(),
                "dissent": str(mv.get("dissent", "")).strip(),
            },
            "metrics": str(t.get("metrics", "")).strip(),
            "implication": str(t.get("implication", "")).strip(),
            "stocks": [str(s).strip() for s in (t.get("stocks") or []) if str(s).strip()],
        })
    clean.sort(key=lambda x: x["importance"], reverse=True)
    return clean[:max_n]


# ── 메인 분석 함수 ─────────────────────────────────────────────

def analyze_messages(messages, kind: str = "pre", channel_name: str = "",
                     snapshot_text: str = "", news_titles=None, watchlist=None,
                     prev_report=None):
    """→ (report_dict, usage_dict)

    prev_report: 직전 보고서 dict (변화 추적용, 없으면 None)
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
    if len(corpus) > 100000:
        corpus = corpus[:100000] + "\n…(이하 생략)"

    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    calls = []

    # 1차: 클러스터링 (메시지 많을 때만)
    clusters = []
    if len(lines) >= CLUSTER_THRESHOLD:
        clusters, _raw, u1 = _stage1_cluster(client, corpus, info)
        calls.append(u1)
        cl_block = _clusters_to_block(clusters)
        if cl_block:
            msg_block = ("=== 주제 클러스터 (1차 구조화: 언급량·합의·이견·사실) ===\n"
                         + cl_block + "\n=== 끝 ===")
        else:
            # 클러스터링 실패 시 원문으로 폴백
            msg_block = f"=== 채널 메시지 원문 ===\n{corpus}\n=== 끝 ==="
    else:
        msg_block = f"=== 채널 메시지 원문 ===\n{corpus}\n=== 끝 ==="

    # 정량·뉴스·일정·어제비교 블록
    quant_block = (f"\n\n=== 실제 시장 정량 데이터 (검증된 사실) ===\n{snapshot_text}\n=== 끝 ==="
                   if snapshot_text else "")
    news_block = ""
    if news_titles:
        nl = "\n".join(f"- {t}" for t in news_titles[:25])
        news_block = f"\n\n=== 오늘의 뉴스 헤드라인 (언론 보도) ===\n{nl}\n=== 끝 ==="
    cal_block = _build_calendar_block()
    prev_block, _prev_titles = _prev_topics_block(prev_report)

    # 워치리스트
    watch_block, watch_schema = "", ""
    if watchlist:
        wl = ", ".join(watchlist)
        watch_block = f"\n\n=== 사용자 워치리스트 종목 ===\n{wl}\n=== 끝 ==="
        watch_schema = (
            ',"watchlist_mentions":[{"stock":"워치리스트 종목명","summary":"관련 언급·이슈 '
            '1문장. 언급 없으면 배열에서 제외"}]'
        )

    # 목적별 꼬리 스키마
    if kind == "pre":
        outlook_schema = ('"outlook":{"pre":["오늘 장에서 주목할 것 1(이벤트·체크포인트)",'
                          '"주목할 것 2","주목할 것 3"]}')
        outlook_rule = ("- outlook.pre: 오늘 한국 장에서 주목할 이벤트·종목·시나리오를 "
                        "3~4개 행동 지침으로. '오늘 무엇을 볼까'에 답하세요.")
    else:
        outlook_schema = ('"outlook":{"post":{"review":"오늘 아침 장전에 예상한 시나리오가 '
                          '맞았는지 점검 1~2문장","tomorrow":"오늘 밤 미국장·내일 한국 장에서 '
                          '주목할 가설 1~2문장"}}')
        outlook_rule = ("- outlook.post: review에 '장전 예상 대비 실제' 점검을, "
                        "tomorrow에 내일 가설을 쓰세요. '오늘을 정리하고 내일 가설'에 답하세요.")

    today = _today_kst_str()
    prompt = (
        "당신은 한국 주식시장을 깊이 이해하는 베테랑 애널리스트입니다.\n"
        f"지금 작성하는 것은 ★{info['ko']}★ 입니다. 작성일(오늘)은 {today}이고, "
        "모든 '오늘·전일·간밤' 표현은 이 날짜 기준입니다.\n"
        f"이 보고서의 목표: {info['goal']}.\n"
        f"수집 구간: {info['window']}.\n"
        f"독자: {info['reader']}.\n\n"
        f"{msg_block}{quant_block}{news_block}{cal_block}{prev_block}{watch_block}\n\n"
        "작성 철학:\n"
        "- ★주제 중심: 보고서 본문은 '주제 카드(topics)' 묶음입니다. 입력 클러스터를 바탕으로 "
        f"가장 중요한 주제 {MAX_TOPICS}개 이내를 골라, 각 주제를 사실→시장시각→정량→시사점 "
        "순으로 구성하세요. 언급량이 많고 시장 영향이 큰 주제를 importance 높게.\n"
        "- ★합의/이견 분리(핵심): 각 주제의 market_view에 채널 다수의 consensus와 갈리는 "
        "dissent를 나눠 쓰세요. 이게 단순 요약을 넘는 분석의 핵심입니다. 이견이 없으면 dissent는 빈 문자열.\n"
        "- ★정량 결합: 각 주제의 metrics에 그 주제와 직접 관련된 수치를 정량 데이터에서 찾아 넣으세요 "
        "(예: 반도체 주제 → '삼성전자 +X%, 외국인 순매수 Y억'). 관련 수치 없으면 빈 문자열.\n"
        "- ★인과 사슬: fact는 '원인 → 결과 → 국내 파급'으로. 표면 서술 금지. "
        "입력에 원인이 없으면 지어내지 말고 그 사실만 쓰세요.\n"
        "- ★날짜 구분: '오늘·전일·간밤'을 처음 언급할 때 날짜 병기(예: 간밤(06/11 미국장)).\n"
        + (outlook_rule + "\n")
        + "- ★변화 추적: 직전 보고서 주제와 비교해, change_tracking.new(오늘 새로 등장)와 "
        "continuing(어제에 이어 지속)을 채우세요. 매일 같은 말 반복을 피하는 장치입니다. "
        "직전 보고서가 없으면 new에 오늘 주제들을 넣고 continuing은 빈 배열.\n"
        "- ★길이 통제: 각 필드는 지정 문장 수를 넘기지 마세요. 주제는 최대 "
        f"{MAX_TOPICS}개. 화제가 적은 날은 3~4개여도 됩니다(억지로 늘리지 말 것).\n"
        "- 과장·창작 금지. 투자 조언(매수/매도 단정) 아니라 판단을 돕는 시장 이해의 관점으로.\n"
        "- ★JSON 안전: 문자열 값 안에 큰따옴표(\") 금지. 강조는 작은따옴표(')나 「」.\n\n"
        "다음 JSON만 반환 (다른 텍스트 없이):\n"
        '{"headline":"오늘의 핵심 한 줄(35자 이내, 날짜 제외)",'
        '"mood":"positive 또는 neutral 또는 cautious",'
        '"snapshot_line":"정량 데이터에서 뽑은 핵심 수치 한 줄'
        '(예: 코스피 8,123(+4.6%) · 원/달러 1,517(-0.5%) · VIX 17.7). 데이터 없으면 빈 문자열",'
        '"topics":[{'
        '"title":"주제명(짧고 구체적으로)",'
        '"importance":1~10 정수(중요도),'
        '"fact":"무슨 일이 있었나. 원인→결과→파급. 2~3문장",'
        '"market_view":{"consensus":"채널 다수 시각 1문장",'
        '"dissent":"갈리는 시각 1문장(없으면 빈 문자열)"},'
        '"metrics":"이 주제 관련 실제 수치(없으면 빈 문자열)",'
        '"implication":"그래서 무엇을 의미하나. 1~2문장",'
        '"stocks":["관련 종목명"]}'
        '],'
        f'{outlook_schema},'
        '"change_tracking":{"new":["오늘 새로 등장한 주제"],'
        '"continuing":["어제에 이어 지속되는 주제"]},'
        '"themes":[{"name":"테마명","detail":"이 테마가 왜 지금 부각되는지 2문장",'
        '"tickers":"관련종목(쉼표구분)"}],'
        '"keywords":[{"keyword":"핵심 키워드","desc":"배경 한 줄(45자 이내)",'
        '"news_headline":"근본 원인 뉴스 헤드라인(주가 등락 표현 금지)","weight":10,'
        '"related":"관련종목"}]'
        f'{watch_schema}}}\n\n'
        f"topics는 ★최대 {MAX_TOPICS}개★ (중요도 순). keywords 정확히 10개(중요 순). "
        "themes 3~6개. "
        + ("정량 데이터·뉴스가 제공되었으니 metrics·snapshot_line을 적극 채우세요."
           if (snapshot_text or news_titles)
           else "정량 데이터가 없으면 metrics·snapshot_line은 빈 문자열로 두고 시장 시각 위주로 쓰세요.")
    )

    text, opus_calls, truncated = _create_with_continuation(
        client, MODEL, prompt, MAX_TOKENS)
    calls.extend(opus_calls)

    result = _safe_json_parse(_strip_fence(text))
    if result is None:
        raise ValueError(
            "JSON 파싱 실패. 응답이 잘렸을 수 있어요. 다시 시도하거나 "
            "REPORT_MAX_TOKENS 를 더 늘려보세요."
            if truncated else "JSON 파싱 실패. 다시 시도해주세요.")

    if not result.get("topics"):
        raise ValueError(
            "보고서 본문(topics)이 비어 있습니다. 응답이 출력 한도에서 잘린 것으로 보여요. "
            "다시 생성하거나 REPORT_MAX_TOKENS 를 늘려주세요."
            if truncated else
            "보고서 본문(topics)이 비어 있습니다. 다시 생성해주세요.")

    # 기본값·정규화
    result.setdefault("headline", "전략·시황 보고서")
    result.setdefault("mood", "neutral")
    result.setdefault("snapshot_line", "")
    result.setdefault("outlook", {})
    result.setdefault("change_tracking", {"new": [], "continuing": []})
    result.setdefault("themes", [])
    result.setdefault("keywords", [])
    result.setdefault("report_kind", kind)
    result["topics"] = _cap_topics(result.get("topics"))

    # 클러스터 메타(언급량 등)를 보고서에 동봉 — 검증·디버깅용
    if clusters:
        result["_clusters_meta"] = [
            {"topic": c.get("topic", ""), "mention_count": c.get("mention_count", 0)}
            for c in clusters if isinstance(c, dict)
        ]

    usage = {
        "model": MODEL + (" + haiku 클러스터링" if clusters else "")
                 + (" + 이어받기" if len(opus_calls) > 1 else ""),
        "calls": calls,
        "input_tokens": sum(c["input_tokens"] for c in calls),
        "output_tokens": sum(c["output_tokens"] for c in calls),
    }
    return result, usage
