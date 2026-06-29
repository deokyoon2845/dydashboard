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


# ── 연속 등장 / NEW 배지 (의미 유사도 + DB 영속) ─────────────
def _norm_kw(k) -> str:
    return str(k).lower().replace(" ", "")


# 부동산 키워드 토큰화용 불용어 — 매일 흔들리는 수식어를 제거해 핵심만 남긴다.
# (예: '강남 재건축 규제 완화' → {강남, 재건축, 규제},  '강남 재건축 활성화' → {강남, 재건축})
_KW_STOP = {
    # 공통 시세·방향 수식어
    "강세", "약세", "급등", "급락", "상승", "하락", "조정", "회복", "돌파", "전망",
    "기대", "기대감", "확대", "축소", "증가", "감소", "우려", "리스크", "이슈", "관련",
    "기록", "경신", "지속", "둔화", "개선", "부각", "주목", "전환", "고조", "재개",
    "최고", "최대", "최저", "사상", "역대", "당일", "오늘", "이번", "지난", "최근",
    # 부동산 특화 수식어
    "완화", "강화", "규제완화", "활성화", "위축", "냉각", "과열", "안정", "급증", "급감",
    "신고가", "신저가", "반등", "반락", "관망", "매수세", "매도세", "거래절벽", "들썩",
    "대책", "방안", "추진", "검토", "발표", "예정", "전망치", "심리", "수급",
    # 조사·단위
    "및", "등", "와", "과", "의", "를", "을", "은", "는", "이", "가", "에", "로", "으로",
    "만에", "만", "억", "조", "선", "개", "년", "월", "일", "원", "퍼센트",
}


def _kw_tokens(text: str) -> set:
    """키워드를 핵심 토큰 집합으로. 수식어·조사·숫자토큰 제거, 접미사 어간 추출.

    streak/NEW를 표현 흔들림에 강하게 만들기 위한 의미 매칭의 기본 단위.
    """
    text = re.sub(r"[^가-힣A-Za-z0-9 ]", " ", str(text))
    out = set()
    for w in text.split():
        w = w.strip()
        if not w:
            continue
        if re.fullmatch(r"[A-Za-z0-9]+", w):
            if len(w) >= 2:
                out.add(w.upper())
            continue
        if w in _KW_STOP:
            continue
        if re.search(r"\d", w):           # '15억'·'9억'·'3억' 등 숫자 섞인 토큰은 노이즈
            continue
        if len(w) >= 2:
            out.add(w)
        # 접미사를 떼어 어간도 함께 등록 ('재건축지구'→'재건축', '분양가상한제'는 그대로)
        for suf in ("지구", "지역", "단지", "시장", "정책", "대출", "제도"):
            if w.endswith(suf) and len(w) > len(suf) + 1:
                stem = w[:-len(suf)]
                if len(stem) >= 2 and stem not in _KW_STOP:
                    out.add(stem)
    return out


def _kw_record(it: dict) -> dict:
    """키워드 dict → 유사도 비교용 레코드 {keyword, norm, tokens, regions}."""
    kw = str(it.get("keyword", "")).strip()
    regions = it.get("regions") or it.get("stocks") or []     # 구버전 stocks 폴백
    return {
        "keyword": kw,
        "norm": _norm_kw(kw),
        "tokens": _kw_tokens(kw),
        "regions": {str(r).strip() for r in regions if str(r).strip()},
    }


def _similar(a: dict, b: dict) -> bool:
    """두 키워드 레코드가 '같은 주제'인지 — 표현이 흔들려도 잡아낸다.

    하나라도 충족하면 같은 주제:
      1) 정규화 완전 일치 (기존 동작 보존)
      2) 핵심 토큰 자카드 유사도 ≥ 0.5
      3) 한쪽 토큰이 다른 쪽에 80% 이상 포함 (짧은 키워드 ⊂ 긴 키워드)
      4) 연결 지역 집합이 (비어있지 않게) 같고 토큰도 1개 이상 겹침
    """
    if a["norm"] and a["norm"] == b["norm"]:
        return True
    ta, tb = a["tokens"], b["tokens"]
    if ta and tb:
        inter = len(ta & tb)
        if inter:
            if inter / len(ta | tb) >= 0.5:
                return True
            if inter / min(len(ta), len(tb)) >= 0.8:
                return True
    ra, rb = a["regions"], b["regions"]
    if ra and ra == rb and (ta & tb):
        return True
    return False


def _past_keyword_sets(now, back_days: int = 35) -> dict:
    """{date객체: [레코드, ...]} — 오늘 이전 날짜들의 키워드 레코드 목록.

    ★우선 Supabase(realestate_keywords 테이블)에서 읽는다(영속·누적). DB가 비었거나
    실패하면 파일 아카이브로 폴백. 휘발성 디스크 탓에 끊기던 streak/NEW를 복구.
    """
    from datetime import date as _date
    out = {}

    def _records(items):
        recs = []
        for it in (items or []):
            if str(it.get("keyword", "")).strip():
                recs.append(_kw_record(it))
        return recs

    # 1) DB 우선
    try:
        from modules import db
        for row in db.load_recent_realestate_keywords(limit=back_days + 5):
            ds = str(row.get("kw_date", ""))
            try:
                y, m, d = ds.split("-")
                dt = _date(int(y), int(m), int(d))
            except ValueError:
                continue
            out[dt] = _records(row.get("items"))
    except Exception:
        out = {}

    # 2) 파일 폴백 (DB가 아무 것도 못 줄 때만)
    if not out and RE_KW_ARCHIVE_DIR.exists():
        for f in RE_KW_ARCHIVE_DIR.glob("*.json"):
            try:
                y, m, d = f.stem.split("-")
                dt = _date(int(y), int(m), int(d))
                past = json.loads(f.read_text(encoding="utf-8"))
                out[dt] = _records(past.get("items"))
            except Exception:
                continue
    return out


def _compute_streaks(today_records, now, past_sets: dict):
    """오늘 키워드별 '연속 등장 일수' 계산 (의미 유사도 기반).
    직전 날짜부터 거슬러 올라가며, 과거 그 날의 키워드 중 하나라도 '같은 주제'면 연속 +1.
    해당 날짜 데이터가 없으면(주말 등) 연속을 끊지 않고 건너뜀.

    today_records: [{keyword, norm, tokens, regions}, ...]
    past_sets: {date: [과거 레코드, ...]}
    """
    from datetime import timedelta

    consecutive_days = {r["keyword"]: 1 for r in today_records}
    if not past_sets:
        return consecutive_days

    still_alive = {r["keyword"]: r for r in today_records}
    cur = now.date()
    for back in range(1, 31):
        if not still_alive:
            break
        d = cur - timedelta(days=back)
        past_list = past_sets.get(d)
        if past_list is None:          # 그 날 데이터 없음 → 건너뜀 (연속 유지)
            continue
        ended = []
        for kw, rec in still_alive.items():
            if any(_similar(rec, pj) for pj in past_list):
                consecutive_days[kw] += 1
            else:
                ended.append(kw)
        for kw in ended:
            still_alive.pop(kw, None)

    return consecutive_days


def _has_prev_keywords(now, past_sets: dict) -> bool:
    """오늘 이전 날짜의 키워드 기록이 하나라도 있는지(NEW 오발동 방지)."""
    today = now.date()
    return any(d < today for d in past_sets)


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

    # 연속 등장(streak) 계산 — DB의 과거 키워드(없으면 파일)와 의미 유사도로 비교
    today_records = [_kw_record(it) for it in items]
    past_sets = _past_keyword_sets(now)
    streaks = _compute_streaks(today_records, now, past_sets)
    prev_exists = _has_prev_keywords(now, past_sets)
    for it in items:
        it["streak"] = streaks.get(it["keyword"], 1)
        it["is_new"] = bool(prev_exists and it["streak"] <= 1)

    payload = {"generated": now.isoformat(), "items": items}

    # 파일 저장 (로컬 디버깅·하위호환). Streamlit Cloud에선 휘발성이라 영속성은 DB가 담당.
    try:
        RE_KW_PATH.parent.mkdir(exist_ok=True)
        RE_KW_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        RE_KW_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        (RE_KW_ARCHIVE_DIR / f"{now:%Y-%m-%d}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[realestate_keywords] 파일 저장 건너뜀: {e}")

    # ★DB 저장 (영속·누적) — 증시 키워드처럼 날짜별로 쌓인다. 뷰어는 여기서 읽는다.
    try:
        from modules import db
        db.save_realestate_keywords(items, generated=payload["generated"], kw_date=f"{now:%Y-%m-%d}")
    except Exception as e:
        print(f"[realestate_keywords] DB 저장 실패(파일은 저장됨): {e}")

    cost = estimate_cost_usd(MODEL, resp.usage.input_tokens, resp.usage.output_tokens)
    append_usage({
        "time": now.isoformat(), "model": MODEL,
        "input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens,
        "cost_usd": cost, "kind": "realestate_keywords", "count": len(items),
    })
    return {"ok": True, "count": len(items), "cost_usd": cost}
