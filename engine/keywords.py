"""[엔진] 오늘의 증시 키워드 추출 (최대 15개, 키워드당 뉴스 3개).

안전장치: AI는 우리가 건넨 '실제 기사 목록'에서 번호만 고릅니다.
URL을 새로 만들지 않으므로 가짜 링크가 생기지 않습니다.

개선:
- 키워드 최대 15개(16개 받아 중복 제거 후 상위 15), 키워드당 대표 기사 최대 3개
- '코스피 1.2% 상승' 같은 단순 시세/등락 뉴스는 사전 필터로 제외
- 의미가 겹치는 키워드는 대표어로 통합하도록 지시
- 같은 '사건'에서 파생된 키워드(원인↔결과)도 하나로 통합
- ★코드 레벨 사건 중복 제거: 근거 기사군이 겹치는 키워드는 같은 사건으로 보고 병합
- 카테고리 균형 (거시 편중 방지, 거시 최대 5개)
- 같은 기사가 여러 키워드에 중복 배정되지 않도록 코드 레벨 차단
- 오늘 처음 등장한 키워드에 is_new 플래그 (뷰어의 NEW 배지용)
- ★종목 태깅 강화: 거시·정책 키워드도 수혜/피해주로 연결해 종목 랭킹(modules.keyword_stocks)을 채움
"""

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from anthropic import Anthropic

from engine.news import fetch_market_news
from modules.usage import estimate_cost_usd, append_usage

KST = ZoneInfo("Asia/Seoul")
KW_PATH = Path("data/keywords_today.json")
KW_ARCHIVE_DIR = Path("data/keywords_archive")
MODEL = "claude-haiku-4-5"

CATEGORIES = ["거시", "섹터", "종목", "정책"]
MAX_KEYWORDS = 15

SYSTEM = "당신은 한국 증시 애널리스트입니다. 오늘 뉴스 헤드라인에서 핵심 키워드를 추출합니다."

# 단순 시세·등락 뉴스로 간주할 패턴 (제목에 이게 핵심이면 제외)
_PRICE_NOISE = re.compile(
    r"(코스피|코스닥|증시|지수|다우|나스닥|S&P|환율|원\s*달러)\s*[\d.,]*\s*"
    r"(%|％|포인트|p|pt|원)?\s*"
    r"(상승|하락|급등|급락|강세|약세|마감|출발|개장|혼조|보합|반등|하락세|상승세|↑|↓)"
)
_PRICE_NOISE2 = re.compile(r"(장\s*마감|개장|시황|마감\s*시황|오전\s*시황|오후\s*시황)\s*$")

# stocks 에 섞여 들어오면 안 되는 비종목 토큰 (지수·ETF·일반어) — 정규화 비교
_NON_STOCK = {
    "코스피", "코스닥", "kospi", "kosdaq", "나스닥", "다우", "s&p500", "sp500",
    "etf", "지수", "관련주", "수혜주", "테마주", "반도체주", "건설주", "방산주",
}


def _is_price_noise(title: str) -> bool:
    """'코스피 1.2% 상승' 류 단순 시세 헤드라인이면 True."""
    t = title.strip()
    if _PRICE_NOISE.search(t):
        return True
    if _PRICE_NOISE2.search(t):
        return True
    return False


def _clean_stocks(raw) -> list:
    """stocks 정리 — ⭐·공백 제거, 중복 제거(순서 보존), 비종목 토큰 제외, 최대 3개."""
    out, seen = [], set()
    for s in (raw or []):
        name = str(s).replace("⭐", "").strip()
        if not name:
            continue
        key = name.lower().replace(" ", "")
        if key in seen or key in _NON_STOCK:
            continue
        seen.add(key)
        out.append(name)
        if len(out) >= 3:
            break
    return out


def _parse_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        text = m.group(0)
    return json.loads(text)


# ── 사건 중복 제거 (기사군 겹침 기반) ─────────────────────────

def _weight_of(obj) -> int:
    try:
        return max(1, min(10, int(obj.get("weight", 5))))
    except (ValueError, TypeError):
        return 5


def _idx_set(obj, n_articles) -> set:
    """obj가 가리키는 유효 기사 인덱스 집합."""
    idxs = obj.get("article_indices") or obj.get("article_index")
    if isinstance(idxs, int):
        idxs = [idxs]
    return {i for i in (idxs or []) if isinstance(i, int) and 0 <= i < n_articles}


def _stock_set(obj) -> set:
    return {str(s).strip().lower().replace(" ", "")
            for s in (obj.get("stocks") or []) if str(s).strip()}


def _dedupe_events(parsed, n_articles, limit=MAX_KEYWORDS):
    """근거 기사군이 겹치는 키워드는 같은 사건으로 보고 weight 높은 쪽만 남김.

    같은 사건 판정 기준 (하나라도 충족):
      - 두 키워드가 근거 기사를 2건 이상 공유
      - 기사를 1건 이상 공유하고, 적은 쪽 기사 수의 절반 이상이 겹침
      - 종목 집합이 (비어있지 않게) 완전히 같고 기사도 1건 이상 겹침
    """
    if not isinstance(parsed, list):
        return []
    # weight 내림차순 (동률은 원래 순서 보존)
    order = sorted(range(len(parsed)), key=lambda i: (-_weight_of(parsed[i]), i))

    accepted = []          # [(idx_set, stock_set), ...]
    result, seen_kw = [], set()
    for i in order:
        obj = parsed[i]
        if not isinstance(obj, dict):
            continue
        kw = str(obj.get("keyword", "")).strip()
        if not kw:
            continue
        norm = kw.lower().replace(" ", "")
        if norm in seen_kw:
            continue

        idxs = _idx_set(obj, n_articles)
        stocks = _stock_set(obj)

        is_dup = False
        for a_idx, a_stk in accepted:
            shared = idxs & a_idx
            if len(shared) >= 2:
                is_dup = True
                break
            denom = min(len(idxs), len(a_idx))
            if shared and denom and len(shared) / denom >= 0.5:
                is_dup = True
                break
            if stocks and stocks == a_stk and shared:
                is_dup = True
                break
        if is_dup:
            continue

        seen_kw.add(norm)
        accepted.append((idxs, stocks))
        result.append(obj)
        if len(result) >= limit:
            break
    return result


# ── 연속 등장 / NEW 배지 ─────────────────────────────────────

def _compute_streaks(today_keywords, now):
    """오늘 키워드별 '연속 등장 일수' 계산.
    아카이브의 직전 날짜들을 거슬러 올라가며, 키워드가 연속으로 나타난 날 수를 셈."""
    from datetime import timedelta

    def _norm(k):
        return k.lower().replace(" ", "")

    streaks = {k: 1 for k in today_keywords}        # 오늘 포함 최소 1

    if not KW_ARCHIVE_DIR.exists():
        return streaks

    # 직전 날짜부터 최대 30일 거슬러 올라감
    consecutive_days = {k: 1 for k in today_keywords}
    still_alive = set(today_keywords)
    cur = now.date()
    for back in range(1, 31):
        if not still_alive:
            break
        d = cur - timedelta(days=back)
        f = KW_ARCHIVE_DIR / f"{d:%Y-%m-%d}.json"
        if not f.exists():
            # 해당 날짜 데이터가 없으면 연속 끊김으로 보지 않고 건너뜀(주말·휴장 고려)
            continue
        try:
            past = json.loads(f.read_text(encoding="utf-8"))
            past_set = {_norm(it.get("keyword", "")) for it in past.get("items", [])}
        except Exception:
            continue
        ended = set()
        for k in still_alive:
            if _norm(k) in past_set:
                consecutive_days[k] += 1
            else:
                ended.add(k)
        still_alive -= ended

    return consecutive_days


def _has_prev_archive(now) -> bool:
    """오늘 이전 날짜의 키워드 아카이브가 하나라도 있는지 (NEW 배지 오발동 방지)."""
    if not KW_ARCHIVE_DIR.exists():
        return False
    today = now.date()
    for f in KW_ARCHIVE_DIR.glob("*.json"):
        try:
            y, m, d = f.stem.split("-")
            from datetime import date as _date
            if _date(int(y), int(m), int(d)) < today:
                return True
        except ValueError:
            continue
    return False


def build_today_keywords() -> dict:
    raw_articles = fetch_market_news()
    if not raw_articles:
        return {"ok": False, "reason": "뉴스를 가져오지 못했습니다. (네이버 키/쿼터 확인)"}

    # 단순 시세·등락 뉴스 제외
    articles = [a for a in raw_articles if not _is_price_noise(a["title"])]
    if len(articles) < 10:                       # 너무 적으면 원본 유지
        articles = raw_articles

    listing = "\n".join(f"{i}: {a['title']}" for i, a in enumerate(articles))
    prompt = (
        "다음은 오늘의 증시 관련 뉴스 헤드라인 목록입니다 (번호: 제목).\n\n"
        f"{listing}\n\n"
        "이 중에서 오늘 증시에서 가장 중요한 키워드 16개를 중요도 순으로 뽑아주세요 "
        "(서로 확실히 다른 사건·주제여야 합니다).\n"
        "각 키워드마다 (1) 관련 한국 상장 종목명 1~3개(가능하면 반드시 채움), (2) 그 키워드를 대표하는 "
        "헤드라인 번호를 중요도 순으로 최대 3개, (3) 카테고리, (4) 중요도 점수를 매기세요.\n\n"
        "규칙:\n"
        "- 의미가 겹치는 키워드는 하나의 대표어로 통합하세요 "
        "(예: AI/인공지능/챗GPT → 'AI', 반도체/메모리/HBM → 적절한 대표어). "
        "절대 비슷한 키워드를 중복해서 만들지 마세요.\n"
        "- ★사건 단위 통합(가장 중요): 같은 '사건'에서 파생된 원인과 결과를 별개 키워드로 쪼개지 마세요. "
        "키워드는 '원인이 되는 사건' 하나만 만들고, 그로 인한 지수 급등락·지수 레벨 돌파(예: 8000선 회복)·"
        "사이드카 발동·수급 주체 변화(외국인/개인 순매수)·투자심리 회복 같은 '결과 현상'은 "
        "그 키워드에 흡수시키세요.\n"
        "  나쁜 예) '외국인 순매수 전환' + '코스피 8000선 회복' + '개인투자자 순매수' 를 각각 생성 "
        "→ 셋 다 '외국인 복귀로 코스피 8천선 회복'이라는 한 사건입니다. 하나로 합치세요.\n"
        "  나쁜 예) 종목이 같고 근거 기사가 겹치는 두 키워드(예: 같은 반도체 기사를 공유) "
        "→ 같은 키워드일 가능성이 큽니다. 통합을 먼저 검토하세요.\n"
        "  합칠 게 있으면 차라리 16개를 못 채우고 개수가 줄어도 좋습니다. 중복보다 적은 게 낫습니다.\n"
        "- ★종목 태깅(중요): 각 키워드에 직접 관련된 한국 상장 종목을 1~3개 stocks 에 넣으세요. "
        "거시·정책 키워드도 반드시 그 사건의 수혜·피해 종목으로 연결하세요.\n"
        "  예) 미·이란 종전 → 삼성E&A·에스오일·한화에어로스페이스, "
        "원유 가격 급락 → 에스오일·대한항공, 엔저 고착화 → 현대차·기아, "
        "AI 반도체 수요 → 삼성전자·SK하이닉스, 스페이스X 상장 → 한화에어로스페이스·한국항공우주, "
        "초과세수 정책 → 한국전력·현대건설.\n"
        "  실제 한국 상장사의 정확한 종목명만 쓰세요(지수·ETF·해외 종목·'반도체주' 같은 일반 업종명 금지). "
        "한국 종목과 연결점이 전혀 없을 때만 빈 배열로 두세요.\n"
        "- ★카테고리 균형: 거시 키워드는 최대 5개까지만. 섹터와 종목 카테고리를 합쳐 "
        "7개 이상 포함되도록, 덜 중요한 거시 이슈 대신 구체적인 섹터·개별 기업 이슈를 발굴하세요.\n"
        "- 하나의 기사 번호는 가능한 한 키워드에만 배정하세요. 두 키워드가 같은 기사를 "
        "공유해야 한다면 그 둘은 사실 같은 키워드라는 신호이니 통합을 먼저 검토하세요.\n"
        "- '코스피 1% 상승' 같은 단순 지수 등락은 키워드가 아닙니다. "
        "실적·정책·계약·기술·수급 등 '사건/원인'이 되는 키워드를 뽑으세요.\n"
        "- '관련주', '수혜주', '테마주' 같은 일반어는 키워드로 쓰지 마세요.\n"
        "- category 는 다음 중 하나: 거시(금리·환율·물가 등 매크로), 섹터(산업·테마), "
        "종목(개별 기업 이슈), 정책(정부·규제·제도).\n"
        "- weight 는 1~10 정수 (오늘 시장 영향력).\n"
        "- article_indices 의 번호는 위 목록에 실제 있는 번호여야 합니다. 지어내지 마세요.\n\n"
        "아래 JSON 배열로만 응답하세요(설명·코드블록 없이):\n"
        '[{"keyword":"...","category":"거시","weight":8,'
        '"stocks":["...","..."],"article_indices":[정수,정수,정수]}, ...]'
    )

    client = Anthropic()
    resp = client.messages.create(
        model=MODEL, max_tokens=3500, system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        parsed = _parse_json(resp.content[0].text)
    except Exception:
        return {"ok": False, "reason": "AI 응답을 해석하지 못했습니다. 다시 시도해주세요."}

    # ★ 사건 중복 제거: 근거 기사군이 겹치는 키워드 병합 후 상위 15개
    parsed = _dedupe_events(parsed, len(articles), limit=MAX_KEYWORDS)

    items, seen_kw = [], set()
    used_urls = set()                             # 키워드 간 기사 중복 배정 차단
    for obj in parsed:
        kw = str(obj.get("keyword", "")).strip()
        if not kw:
            continue
        norm = kw.lower().replace(" ", "")
        if norm in seen_kw:                       # 안전망: 중복 키워드 제거
            continue
        seen_kw.add(norm)

        # 기사 번호 → 실제 기사 (카드 내 + 카드 간 중복 url 제거, 최대 3개)
        # 단, 전부 상위 키워드와 겹쳐도 카드당 최소 1건은 보장 (공유 허용)
        idxs = obj.get("article_indices") or obj.get("article_index")
        if isinstance(idxs, int):
            idxs = [idxs]
        news, news_seen, shared_pool = [], set(), []
        for idx in (idxs or []):
            if isinstance(idx, int) and 0 <= idx < len(articles):
                art = articles[idx]
                if art["url"] in news_seen:
                    continue
                if art["url"] in used_urls:
                    shared_pool.append(art)       # 이미 다른 카드에 배정된 기사
                    continue
                news_seen.add(art["url"])
                news.append({"title": art["title"], "url": art["url"]})
            if len(news) >= 3:
                break
        if not news and shared_pool:              # 최소 1건 보장
            art = shared_pool[0]
            news.append({"title": art["title"], "url": art["url"]})
        used_urls.update(n["url"] for n in news)

        cat = str(obj.get("category", "")).strip()
        if cat not in CATEGORIES:
            cat = "섹터"
        weight = _weight_of(obj)

        items.append({
            "keyword": kw,
            "category": cat,
            "weight": weight,
            "stocks": _clean_stocks(obj.get("stocks")),
            "news": news,
        })
        if len(items) >= MAX_KEYWORDS:
            break

    now = datetime.now(KST)

    # 연속 등장(streak) 계산 — 아카이브의 직전 날짜들과 비교
    streaks = _compute_streaks([it["keyword"] for it in items], now)
    prev_exists = _has_prev_archive(now)
    for it in items:
        it["streak"] = streaks.get(it["keyword"], 1)
        # NEW: 과거 아카이브가 존재하는데 오늘 처음(연속 1일) 등장한 키워드
        it["is_new"] = bool(prev_exists and it["streak"] <= 1)

    payload = {"generated": now.isoformat(), "items": items}
    KW_PATH.parent.mkdir(exist_ok=True)
    KW_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # 날짜별 아카이브 저장
    KW_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    (KW_ARCHIVE_DIR / f"{now:%Y-%m-%d}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    cost = estimate_cost_usd(MODEL, resp.usage.input_tokens, resp.usage.output_tokens)
    append_usage({
        "time": now.isoformat(), "model": MODEL,
        "input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens,
        "cost_usd": cost, "kind": "keywords", "count": len(items),
    })
    return {"ok": True, "count": len(items), "cost_usd": cost}
