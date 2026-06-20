"""[엔진] 오늘의 부동산 키워드 추출 (최대 15개, 키워드당 뉴스 3개).

증시 키워드(engine/keywords.py)의 부동산 버전.
  - 네이버 부동산 뉴스(engine.news.fetch_market_news에 부동산 쿼리) → Haiku → 키워드 추출.
  - 키워드당 '관련 지역'은 서울 자치구·경기 시·군만(코드 화이트리스트로 강제).
    AI가 부산·세종 등 서울·경기 밖을 뱉어도 걸러지고, 동·신도시명은 상위 시·구로 매핑.
  - 카테고리: 정책 / 금리 / 공급 / 시황 / 지역.
  - data/realestate_keywords_today.json (+ 날짜별 아카이브) 저장.

안전장치(증시와 동일): AI는 우리가 건넨 '실제 기사 목록'에서 번호만 고른다(가짜 링크 방지).
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
RE_KW_PATH = Path("data/realestate_keywords_today.json")
RE_KW_ARCHIVE_DIR = Path("data/realestate_keywords_archive")
MODEL = "claude-haiku-4-5"

CATEGORIES = ["정책", "금리", "공급", "시황", "지역"]
MAX_KEYWORDS = 15

SYSTEM = ("당신은 한국 수도권(서울·경기) 부동산 시장 애널리스트입니다. "
          "오늘 뉴스 헤드라인에서 핵심 키워드를 추출합니다.")

# 부동산 뉴스 검색 쿼리(서울·경기 중심)
RE_QUERIES = [
    "부동산 시장", "아파트 매매", "서울 아파트", "경기 부동산", "수도권 집값",
    "전세 시장", "전세사기", "분양 청약", "재건축 재개발", "부동산 정책",
    "주택담보대출 금리", "미분양", "갭투자", "부동산 세금", "입주물량",
]

# ── 서울/경기 지역 화이트리스트 ─────────────────────────────────
_SEOUL_GU = [
    "종로구", "중구", "용산구", "성동구", "광진구", "동대문구", "중랑구", "성북구",
    "강북구", "도봉구", "노원구", "은평구", "서대문구", "마포구", "양천구", "강서구",
    "구로구", "금천구", "영등포구", "동작구", "관악구", "서초구", "강남구", "송파구", "강동구",
]
_GG_SI = [
    "수원시", "성남시", "의정부시", "안양시", "부천시", "광명시", "평택시", "동두천시",
    "안산시", "고양시", "과천시", "구리시", "남양주시", "오산시", "시흥시", "군포시",
    "의왕시", "하남시", "용인시", "파주시", "이천시", "안성시", "김포시", "화성시",
    "광주시", "양주시", "포천시", "여주시", "연천군", "가평군", "양평군",
]
_UMBRELLA = ["서울", "경기", "수도권", "강남3구"]
# 동·신도시·권역명 → 상위 시·구
_SUBMARKET = {
    "분당": "성남시", "판교": "성남시", "동탄": "화성시", "일산": "고양시",
    "광교": "수원시", "평촌": "안양시", "영통": "수원시", "위례": "송파구",
    "반포": "서초구", "압구정": "강남구", "대치": "강남구", "잠실": "송파구",
    "목동": "양천구", "여의도": "영등포구", "마곡": "강서구", "상계": "노원구",
    "둔촌": "강동구", "과천": "과천시",
}

_CANON = set(_SEOUL_GU) | set(_GG_SI) | set(_UMBRELLA)
_ALIAS = {}
for _r in _CANON:
    _ALIAS[_r] = _r
    if len(_r) >= 3 and _r.endswith(("구", "시", "군")):   # 강남구→강남, 수원시→수원
        _ALIAS.setdefault(_r[:-1], _r)
for _k, _v in _SUBMARKET.items():
    _ALIAS.setdefault(_k, _v)

# 분양 광고·단순 단신 류 노이즈(제목 핵심이 이거면 제외)
_NOISE = re.compile(r"(모델하우스\s*오픈|분양\s*광고|선착순\s*분양|특별\s*분양\s*안내)")


def _is_noise(title: str) -> bool:
    return bool(_NOISE.search(title.strip()))


def _canon_region(name):
    """입력 지역명을 서울 자치구·경기 시군 정식명으로 정규화. 밖이면 None."""
    n = str(name).replace("⭐", "").strip()
    if not n:
        return None
    if n in _ALIAS:
        return _ALIAS[n]
    for suf in ("구", "시", "군"):       # '강남' → '강남구'
        if (n + suf) in _CANON:
            return n + suf
    return None


def _clean_regions(raw) -> list:
    """regions 정리 — 서울/경기만 통과, 정식명으로 정규화, 중복 제거, 최대 3개."""
    out, seen = [], set()
    for s in (raw or []):
        c = _canon_region(s)
        if not c or c in seen:
            continue
        seen.add(c)
        out.append(c)
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
    idxs = obj.get("article_indices") or obj.get("article_index")
    if isinstance(idxs, int):
        idxs = [idxs]
    return {i for i in (idxs or []) if isinstance(i, int) and 0 <= i < n_articles}


def _region_set(obj) -> set:
    return {c for c in (_canon_region(s) for s in (obj.get("regions") or [])) if c}


def _dedupe_events(parsed, n_articles, limit=MAX_KEYWORDS):
    """근거 기사군이 겹치는 키워드는 같은 사건으로 보고 weight 높은 쪽만 남김."""
    if not isinstance(parsed, list):
        return []
    order = sorted(range(len(parsed)), key=lambda i: (-_weight_of(parsed[i]), i))

    accepted = []
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
        regions = _region_set(obj)

        is_dup = False
        for a_idx, a_reg in accepted:
            shared = idxs & a_idx
            if len(shared) >= 2:
                is_dup = True
                break
            denom = min(len(idxs), len(a_idx))
            if shared and denom and len(shared) / denom >= 0.5:
                is_dup = True
                break
            if regions and regions == a_reg and shared:
                is_dup = True
                break
        if is_dup:
            continue

        seen_kw.add(norm)
        accepted.append((idxs, regions))
        result.append(obj)
        if len(result) >= limit:
            break
    return result


# ── 연속 등장 / NEW 배지 ─────────────────────────────────────
def _compute_streaks(today_keywords, now):
    """오늘 키워드별 '연속 등장 일수' 계산(아카이브 직전 날짜들과 비교)."""
    from datetime import timedelta

    def _norm(k):
        return k.lower().replace(" ", "")

    if not RE_KW_ARCHIVE_DIR.exists():
        return {k: 1 for k in today_keywords}

    consecutive_days = {k: 1 for k in today_keywords}
    still_alive = set(today_keywords)
    cur = now.date()
    for back in range(1, 31):
        if not still_alive:
            break
        d = cur - timedelta(days=back)
        f = RE_KW_ARCHIVE_DIR / f"{d:%Y-%m-%d}.json"
        if not f.exists():
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
    """오늘 이전 날짜의 키워드 아카이브가 하나라도 있는지(NEW 오발동 방지)."""
    if not RE_KW_ARCHIVE_DIR.exists():
        return False
    today = now.date()
    for f in RE_KW_ARCHIVE_DIR.glob("*.json"):
        try:
            y, m, d = f.stem.split("-")
            from datetime import date as _date
            if _date(int(y), int(m), int(d)) < today:
                return True
        except ValueError:
            continue
    return False


def build_realestate_keywords() -> dict:
    raw_articles = fetch_market_news(queries=RE_QUERIES)
    if not raw_articles:
        return {"ok": False, "reason": "부동산 뉴스를 가져오지 못했습니다. (네이버 키/쿼터 확인)"}

    articles = [a for a in raw_articles if not _is_noise(a["title"])]
    if len(articles) < 10:                       # 너무 적으면 원본 유지
        articles = raw_articles

    listing = "\n".join(f"{i}: {a['title']}" for i, a in enumerate(articles))
    prompt = (
        "다음은 오늘의 부동산 관련 뉴스 헤드라인 목록입니다 (번호: 제목).\n\n"
        f"{listing}\n\n"
        "이 중에서 오늘 수도권(서울·경기) 부동산에서 가장 중요한 키워드 16개를 중요도 순으로 "
        "뽑아주세요 (서로 확실히 다른 사건·주제여야 합니다).\n"
        "각 키워드마다 (1) 관련 지역(서울 자치구 또는 경기 시·군) 1~3개, (2) 그 키워드를 대표하는 "
        "헤드라인 번호를 중요도 순으로 최대 3개, (3) 카테고리, (4) 중요도 점수를 매기세요.\n\n"
        "규칙:\n"
        "- 의미가 겹치는 키워드는 하나의 대표어로 통합하세요. 절대 비슷한 키워드를 중복 생성하지 마세요.\n"
        "- ★사건 단위 통합(가장 중요): 같은 '사건'의 원인과 결과를 별개 키워드로 쪼개지 마세요. "
        "'원인이 되는 사건' 하나만 만들고, 그로 인한 가격 변동·거래량 변화·매수심리 변화 같은 "
        "'결과 현상'은 그 키워드에 흡수시키세요.\n"
        "  합칠 게 있으면 차라리 16개를 못 채우고 개수가 줄어도 좋습니다. 중복보다 적은 게 낫습니다.\n"
        "- ★지역 태깅(중요): regions 에는 '서울특별시 자치구' 또는 '경기도 시·군'의 정식 행정구역명만 "
        "넣으세요 (예: 강남구, 송파구, 마포구, 성남시, 수원시, 고양시, 용인시). "
        "동·신도시·권역명은 상위 시·구로 올리세요(예: 판교→성남시, 동탄→화성시, 일산→고양시, "
        "반포→서초구, 잠실→송파구). 광역 전체면 '서울' 또는 '경기'를 쓰세요. "
        "부산·대구·세종 등 서울·경기 밖 지역이나 전국 단위 일반 이슈는 regions 를 빈 배열로 두세요.\n"
        "- ★카테고리: 다음 중 하나. 정책(규제·세제·법·대책), 금리(대출·금리·자금조달), "
        "공급(분양·청약·입주·미분양·공급대책), 시황(가격·거래량·전세·매수심리), "
        "지역(특정 권역 집중 이슈).\n"
        "- weight 는 1~10 정수 (오늘 시장 영향력).\n"
        "- 하나의 기사 번호는 가능한 한 키워드에만 배정하세요. 두 키워드가 같은 기사를 "
        "공유해야 한다면 그 둘은 사실 같은 키워드라는 신호이니 통합을 먼저 검토하세요.\n"
        "- '○○아파트 ○억 신고가' 같은 개별 단지 단신은 키워드가 아닙니다. "
        "정책·금리·공급·시황 등 '사건/원인'이 되는 키워드를 뽑으세요.\n"
        "- '아파트', '부동산', '집값' 같은 일반어 단독은 키워드로 쓰지 마세요.\n"
        "- article_indices 의 번호는 위 목록에 실제 있는 번호여야 합니다. 지어내지 마세요.\n\n"
        "아래 JSON 배열로만 응답하세요(설명·코드블록 없이):\n"
        '[{"keyword":"...","category":"정책","weight":8,'
        '"regions":["강남구","송파구"],"article_indices":[정수,정수,정수]}, ...]'
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

    parsed = _dedupe_events(parsed, len(articles), limit=MAX_KEYWORDS)

    items, seen_kw = [], set()
    used_urls = set()
    for obj in parsed:
        kw = str(obj.get("keyword", "")).strip()
        if not kw:
            continue
        norm = kw.lower().replace(" ", "")
        if norm in seen_kw:
            continue
        seen_kw.add(norm)

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
                    shared_pool.append(art)
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
            cat = "시황"
        weight = _weight_of(obj)

        items.append({
            "keyword": kw,
            "category": cat,
            "weight": weight,
            "regions": _clean_regions(obj.get("regions")),
            "news": news,
        })
        if len(items) >= MAX_KEYWORDS:
            break

    now = datetime.now(KST)

    streaks = _compute_streaks([it["keyword"] for it in items], now)
    prev_exists = _has_prev_archive(now)
    for it in items:
        it["streak"] = streaks.get(it["keyword"], 1)
        it["is_new"] = bool(prev_exists and it["streak"] <= 1)

    payload = {"generated": now.isoformat(), "items": items}
    RE_KW_PATH.parent.mkdir(exist_ok=True)
    RE_KW_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    RE_KW_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    (RE_KW_ARCHIVE_DIR / f"{now:%Y-%m-%d}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    cost = estimate_cost_usd(MODEL, resp.usage.input_tokens, resp.usage.output_tokens)
    append_usage({
        "time": now.isoformat(), "model": MODEL,
        "input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens,
        "cost_usd": cost, "kind": "realestate_keywords", "count": len(items),
    })
    return {"ok": True, "count": len(items), "cost_usd": cost}
