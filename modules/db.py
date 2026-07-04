"""Supabase 보고서·관심종목·부동산·IPO 저장소 — 엔진(GitHub Actions)·뷰어(Streamlit) 공용 얇은 계층.

- 뷰어에서는 Streamlit Secrets, 엔진에서는 환경변수로 키를 읽는다(둘 다 지원).
- 보고서는 reports 테이블에 (report_date, report_kind) 기준 upsert 된다.
- 관심종목(워치리스트)은 watchlist 테이블의 단일 행(id=1)에 jsonb 배열로 저장한다.
  → Streamlit Cloud 파일시스템이 휘발성이라, 앱에서 바꾼 관심종목이 reboot에도 보존되게 한다.
  (※ 최초 1회 아래 SQL로 테이블을 만들어야 함)

    create table if not exists watchlist (
      id int primary key,
      stocks jsonb not null default '[]'::jsonb,
      updated_at timestamptz default now()
    );
    insert into watchlist (id, stocks) values (1, '[]'::jsonb)
      on conflict (id) do nothing;

- 부동산 실거래 스냅샷은 realestate_snapshots 테이블에 날짜(asof_date)별 upsert 된다.
  뷰어는 가장 최신 1행만 읽는다(과거 행은 향후 추세/이력용으로 누적). 갱신은 운영자 버튼
  또는 일일 GitHub Actions(engine.realestate_run)가 수행한다.
  (※ 최초 1회 아래 SQL로 테이블을 만들어야 함)

    create table if not exists realestate_snapshots (
      asof_date     date primary key,
      asof          text,
      metrics       jsonb,
      anomalies     jsonb,
      indicators    jsonb,
      subscriptions jsonb,
      updated_at    timestamptz default now()
    );

  (※ 이미 테이블이 있으면 분양용 컬럼만 한 번 추가)
    alter table realestate_snapshots add column if not exists subscriptions jsonb;

- 오늘의 키워드는 keywords 테이블에 날짜(kw_date)별로 upsert 되어 '시황 보고서처럼' 누적된다.
  (기존엔 data/keywords_archive/*.json 파일에 저장 → Streamlit Cloud 휘발성 디스크라
   reboot 때 사라져 누적이 끊겼다. 영속 저장소인 DB로 이전해 항상 보존된다.)
  뷰어는 날짜별로 골라 읽고, 엔진은 streak(연속 등장) 계산에 최근 행들을 읽는다.
  (※ 최초 1회 아래 SQL로 테이블을 만들어야 함)

    create table if not exists keywords (
      kw_date    date primary key,
      generated  text,
      items      jsonb not null default '[]'::jsonb,
      updated_at timestamptz default now()
    );

- 증시 IPO 스냅샷은 ipo_snapshots 테이블에 날짜(asof_date)별로 upsert 된다.
  엔진(engine.ipo_run)이 최근 2년 신규상장(시총 2,000억↑)·향후 IPO를 적재하고,
  뷰어(modules/ipo.py)는 최신 1행만 읽는다(없으면 샘플 폴백).
  (※ 최초 1회 아래 SQL로 테이블을 만들어야 함)

    create table if not exists ipo_snapshots (
      asof_date  date primary key,
      asof       text,
      recent     jsonb not null default '[]'::jsonb,
      upcoming   jsonb not null default '[]'::jsonb,
      updated_at timestamptz default now()
    );

- 엔진 공용 캐시는 engine_cache 테이블에 cache_key별 jsonb로 저장된다(비용·런타임 절감용).
  · 세대수 맵(apt_info): kaptCode→세대수/시공사. 거의 안 변해 7일 TTL로 미스만 재조회.
  · 작년말 baseline(rtms_dec_YYYYMM): 전년 12월 실거래 평단가. 신고지연이 끝나면 고정 →
    주 1회만 재스윕하고 평소엔 캐시 재사용(매일 49구 1개월 스윕 제거).
  (※ 최초 1회 아래 SQL로 테이블을 만들어야 함)

    create table if not exists engine_cache (
      cache_key  text primary key,
      payload    jsonb not null default '{}'::jsonb,
      updated    text,
      updated_at timestamptz default now()
    );
"""
import json
import os
import re
from datetime import datetime, timezone, timedelta

from supabase import create_client, Client

TABLE = "reports"
WL_TABLE = "watchlist"
WL_ID = 1
RE_TABLE = "realestate_snapshots"
KW_TABLE = "keywords"
RE_KW_TABLE = "realestate_keywords"
IPO_TABLE = "ipo_snapshots"
LEADERS_TABLE = "leaders"
SM_TABLE = "stock_master"
IPO_ABOUT_TABLE = "ipo_about"
MFLOW_TABLE = "market_flow"
CACHE_TABLE = "engine_cache"
_CLIENT: Client | None = None


def _cfg(key: str) -> str:
    """SUPABASE_URL / SUPABASE_KEY를 환경변수 우선, 없으면 Streamlit Secrets에서 읽는다."""
    val = os.environ.get(key)
    if val:
        return val
    try:
        import streamlit as st  # 뷰어(Streamlit)에서만 존재
        return st.secrets[key]
    except Exception as e:
        raise RuntimeError(f"{key}가 설정되지 않았어요 (Secrets 또는 환경변수 확인).") from e


def supabase_configured() -> bool:
    """SUPABASE_URL·SUPABASE_KEY가 (환경변수 또는 Secrets에) 모두 있으면 True. 예외 없이 판별."""
    for key in ("SUPABASE_URL", "SUPABASE_KEY"):
        val = os.environ.get(key)
        if not val:
            try:
                import streamlit as st
                val = st.secrets.get(key)
            except Exception:
                val = None
        if not val:
            return False
    return True


def _client() -> Client:
    global _CLIENT
    if _CLIENT is None:
        url = _cfg("SUPABASE_URL").strip().rstrip("/")
        key = _cfg("SUPABASE_KEY").strip()
        _CLIENT = create_client(url, key)
    return _CLIENT


# ── 멱등 가드(다중 cron 슬롯 중복 방지) ──────────────────────────────
_KST = timezone(timedelta(hours=9))


def last_updated_kst(table: str, ts_col: str = "updated_at"):
    """지정 테이블의 최신 updated_at을 KST aware datetime으로 반환. 없으면 None.

    - GitHub 러너는 UTC라 updated_at은 대개 tz 없는 UTC 값 → UTC로 간주해 KST 변환.
    - 미설정·행없음·파싱실패는 모두 None으로 안전 폴백한다.
    화면의 '자동 갱신 현황'(최근 갱신 시각)과 엔진 멱등 가드가 공유하는 단일 소스.
    """
    if not supabase_configured():
        return None
    try:
        res = (_client().table(table)
               .select(ts_col)
               .order(ts_col, desc=True)
               .limit(1).execute())
        rows = res.data or []
        if not rows:
            return None
        raw = rows[0].get(ts_col)
        if not raw:
            return None
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_KST)
    except Exception as e:
        print(f"[db.last_updated_kst] 실패({table}): {e}", flush=True)
        return None


def collected_today(table: str, ts_col: str = "updated_at") -> bool:
    """지정 테이블의 최신 updated_at(KST 기준)이 '오늘'이면 True.

    다중 cron 슬롯(예: 06:07·07:07·08:07 KST)에서 '이미 오늘 수집을 마쳤는지'
    판정해, 뒤 슬롯이 중복 수집·중복 API 과금(특히 Anthropic)을 하지 않게 막는다.
    미설정·행없음·파싱실패는 False(=수집 진행)로 안전 폴백한다.
    """
    dt = last_updated_kst(table, ts_col)
    if dt is None:
        return False
    return dt.date() == datetime.now(_KST).date()


# ── 엔진 공용 캐시(engine_cache) — 세대수 맵·작년말 baseline 등 ──────
def cache_get(key: str) -> dict | None:
    """engine_cache에서 cache_key의 payload(dict) 반환. 없음/실패/미설정 시 None.
    payload에 '_updated'(마지막 갱신 문자열)를 끼워 넣어 호출부 TTL 판정에 쓰게 한다."""
    if not supabase_configured():
        return None
    try:
        res = (_client().table(CACHE_TABLE)
               .select("payload,updated")
               .eq("cache_key", key)
               .limit(1).execute())
    except Exception:
        return None
    if not res.data:
        return None
    row = res.data[0]
    payload = row.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = None
    if isinstance(payload, dict):
        payload.setdefault("_updated", row.get("updated"))
        return payload
    return None


def cache_set(key: str, payload: dict) -> bool:
    """engine_cache에 cache_key=payload upsert. 성공 True, 실패/미설정 False."""
    if not supabase_configured():
        return False
    try:
        clean = {k: v for k, v in payload.items() if k != "_updated"}
        row = {"cache_key": key, "payload": clean,
               "updated": datetime.now().strftime("%Y-%m-%d %H:%M")}
        _client().table(CACHE_TABLE).upsert(row, on_conflict="cache_key").execute()
        return True
    except Exception:
        return False


# ── 보존 정책(오래된 시계열 정리) — 용량 관리 ────────────────────
# 날짜 컬럼 기준 보존 기간이 지난 행을 삭제한다. 엔진(GitHub Actions)이 하루 1회
# 호출한다(engine.realestate_run — 매일 도는 유일한 일일 잡). 뷰어(Streamlit)에서는
# 절대 호출하지 않는다.
#
# · 날짜 컬럼은 모두 'YYYY-MM-DD'(date 또는 text)라 ISO 사전식=시간순 → 문자열
#   커트오프로 .lt() 비교하면 date/text 어느 쪽이든 안전하게 동작한다.
# · keywords·realestate_keywords는 streak(연속 등장) 계산이 최근 35일을 읽으므로
#   40일 보존한다. 그 외 시계열은 뷰어가 최근 며칠만 읽어 10일로 충분하다.
# · engine_cache·watchlist·stock_master·ipo_about은 시계열이 아니라 제외한다.
RETENTION: dict[str, tuple[str, int]] = {
    "reports":              ("report_date", 10),
    "realestate_snapshots": ("asof_date",   10),
    "ipo_snapshots":        ("asof_date",   10),
    "market_flow":          ("asof_date",   10),
    "leaders":              ("asof_date",   10),
    "keywords":             ("kw_date",     40),
    "realestate_keywords":  ("kw_date",     40),
}


def _retention_cutoff(keep_days: int) -> str:
    """오늘(KST)로부터 keep_days일 이전 날짜를 'YYYY-MM-DD'로 반환.
    이 값보다 '작은'(=오래된) 행이 삭제 대상이다."""
    return (datetime.now(_KST).date() - timedelta(days=int(keep_days))).isoformat()


def purge_table(table: str, date_col: str, keep_days: int) -> int:
    """date_col < (오늘-keep_days)인 행을 삭제하고 삭제 행 수를 반환.
    미설정·실패는 0으로 안전 폴백해 수집 파이프라인을 막지 않는다.
    반드시 .lt(date_col, cutoff) 필터가 걸리므로 전체 삭제 위험은 없다."""
    if not supabase_configured():
        return 0
    cutoff = _retention_cutoff(keep_days)
    try:
        res = (_client().table(table)
               .delete()
               .lt(date_col, cutoff)
               .execute())
        return len(res.data or [])
    except Exception as e:
        print(f"[db.purge_table] 실패({table}): {e}", flush=True)
        return 0


def purge_old_data(policy: dict | None = None) -> dict:
    """RETENTION 정책대로 각 테이블의 오래된 행을 삭제. {table: 삭제행수} 반환.
    엔진 일일 실행에서 1회 호출한다(중복 호출도 멱등 — 두 번째부턴 0건 삭제)."""
    policy = policy or RETENTION
    out: dict[str, int] = {}
    for table, (col, days) in policy.items():
        out[table] = purge_table(table, col, days)
    return out


def _meta_from_data(data: dict):
    """보고서 dict에서 slug · 날짜 · 종류(pre/post)를 유도한다."""
    gen = str(data.get("generated_at", "")).strip()
    m = re.search(r"(\d{4}-\d{2}-\d{2})\D+(\d{2}):?(\d{2})", gen)
    if m:
        d, hhmm = m.group(1), m.group(2) + m.group(3)
    else:
        # generated_at이 비었으면 analysis_until → 그래도 없으면 현재 시각
        m2 = re.search(r"(\d{4}-\d{2}-\d{2})", str(data.get("analysis_until", "")) or gen)
        now = datetime.now()
        d = m2.group(1) if m2 else now.strftime("%Y-%m-%d")
        hhmm = now.strftime("%H%M")

    kind = data.get("report_kind")
    if kind not in ("pre", "post"):
        kind = "pre" if int(hhmm[:2]) < 12 else "post"
    return f"{d}_{hhmm}", d, kind


# ── 보고서: 쓰기 ──────────────────────────────────────────────

def save_report(data: dict) -> str:
    """보고서 dict를 DB에 저장(upsert). 같은 날·같은 종류는 덮어쓴다. slug 반환."""
    slug, d, kind = _meta_from_data(data)
    row = {
        "slug": slug,
        "report_date": d,
        "report_kind": kind,
        "generated_at": str(data.get("generated_at", "")),
        "data": data,
    }
    _client().table(TABLE).upsert(row, on_conflict="report_date,report_kind").execute()
    return slug


# ── 보고서: 읽기 ──────────────────────────────────────────────

def list_slugs() -> list[str]:
    """모든 보고서 slug를 최신 날짜순으로 반환."""
    res = (_client().table(TABLE)
           .select("slug,report_date")
           .order("report_date", desc=True)
           .execute())
    return [r["slug"] for r in (res.data or [])]


def list_recent(limit: int = 12) -> list[dict]:
    """최근 보고서들을 최신순으로 (slug, report_date, report_kind, data)까지 묶어 반환.
    타임라인 등 '최근 며칠치 본문'이 한 번에 필요한 뷰어용. limit는 행 수(날짜 수 아님).

    정렬: report_date desc → slug desc. slug='YYYY-MM-DD_HHMM'이라, 같은 날짜에서는
    HHMM이 늦은(=장마감 후) 행이 먼저 온다 → 호출 측에서 날짜별 '처음 행'만 취하면
    자동으로 장마감 후 우선이 된다."""
    res = (_client().table(TABLE)
           .select("slug,report_date,report_kind,data")
           .order("report_date", desc=True)
           .order("slug", desc=True)
           .limit(limit)
           .execute())
    return res.data or []


def load_by_slug(slug: str) -> dict | None:
    """slug(=파일명 stem)로 보고서 data(JSON) 단건 조회."""
    res = (_client().table(TABLE)
           .select("data")
           .eq("slug", slug)
           .limit(1)
           .execute())
    return res.data[0]["data"] if res.data else None


def delete_by_slug(slug: str) -> None:
    """slug로 보고서 삭제 (삭제 UI용)."""
    _client().table(TABLE).delete().eq("slug", slug).execute()


# ── 관심종목(워치리스트): 읽기·쓰기 ───────────────────────────
# watchlist 테이블의 단일 행(id=1)에 종목명 배열을 jsonb로 보관.
# Streamlit Cloud 재시작에도 보존되는 영속 저장소.

def load_watchlist_db() -> list[str]:
    """관심종목 목록을 DB에서 읽어 반환. 행이 없으면 빈 리스트."""
    res = (_client().table(WL_TABLE)
           .select("stocks")
           .eq("id", WL_ID)
           .limit(1)
           .execute())
    if res.data:
        stocks = res.data[0].get("stocks") or []
        return [str(s).strip() for s in stocks if str(s).strip()]
    return []


def save_watchlist_db(stocks: list) -> list[str]:
    """관심종목 목록을 DB에 저장(upsert, id=1 단일 행). 정리된 목록 반환."""
    clean = []
    for s in stocks:
        s = str(s).strip()
        if s and s not in clean:
            clean.append(s)
    clean = clean[:20]
    _client().table(WL_TABLE).upsert(
        {"id": WL_ID, "stocks": clean, "updated_at": datetime.now().isoformat()},
        on_conflict="id").execute()
    return clean


# ── 부동산 스냅샷: 읽기·쓰기 ──────────────────────────────────
# realestate_snapshots 테이블에 날짜(asof_date)별로 최신 수집 결과를 upsert.
# 뷰어는 최신 1행만 읽어 '항상 실데이터'를 보장(샘플 폴백은 행이 없을 때만).
# metrics/anomalies/indicators는 뷰어가 그대로 그릴 수 있는 형식(dict/list)으로 저장.

def save_realestate(metrics=None, anomalies=None, indicators=None,
                    subscriptions=None,
                    asof: str | None = None, asof_date: str | None = None) -> str:
    """부동산 스냅샷 저장(upsert, asof_date 단일행). asof는 'YYYY-MM-DD HH:MM' 문자열."""
    now = datetime.now()
    asof = asof or now.strftime("%Y-%m-%d %H:%M")
    asof_date = asof_date or asof[:10]
    row = {
        "asof_date": asof_date,
        "asof": asof,
        "metrics": metrics,
        "anomalies": anomalies,
        "indicators": indicators,
        "subscriptions": subscriptions,
        "updated_at": now.isoformat(),
    }
    _client().table(RE_TABLE).upsert(row, on_conflict="asof_date").execute()
    return asof_date


def load_realestate() -> dict | None:
    """가장 최신 부동산 스냅샷 1행을 반환. 행이 없으면 None.
       반환 dict: {'asof','metrics','anomalies','indicators','subscriptions'}."""
    res = (_client().table(RE_TABLE)
           .select("asof,metrics,anomalies,indicators,subscriptions")
           .order("asof_date", desc=True)
           .limit(1)
           .execute())
    return res.data[0] if res.data else None


def load_recent_realestate(days: int = 7) -> list[dict]:
    """최근 N일 부동산 스냅샷 행들(최신순). 주간 뷰가 날짜별 지표를 재집계할 때 사용.
       각 행: {'asof_date','asof','metrics','anomalies'}."""
    res = (_client().table(RE_TABLE)
           .select("asof_date,asof,metrics,anomalies")
           .order("asof_date", desc=True)
           .limit(max(1, int(days)))
           .execute())
    return res.data or []


# ── 오늘의 키워드: 읽기·쓰기 ──────────────────────────────────
# keywords 테이블에 날짜(kw_date)별로 키워드 묶음을 upsert. 시황 보고서처럼 매일 누적.
# items 는 뷰어가 그대로 그리는 형식의 dict 배열
#   [{keyword, category, weight, stocks[], news[], streak, is_new}, ...]

def save_keywords(items: list, generated: str | None = None,
                  kw_date: str | None = None) -> str:
    """오늘의 키워드를 DB에 저장(upsert, kw_date 단일행). kw_date 미지정 시 generated에서 유도."""
    now = datetime.now()
    generated = generated or now.isoformat()
    if not kw_date:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", str(generated))
        kw_date = m.group(1) if m else now.strftime("%Y-%m-%d")
    row = {
        "kw_date": kw_date,
        "generated": str(generated),
        "items": items or [],
        "updated_at": now.isoformat(),
    }
    _client().table(KW_TABLE).upsert(row, on_conflict="kw_date").execute()
    return kw_date


def load_keywords_latest() -> dict | None:
    """가장 최신 키워드 1행을 반환. 행이 없으면 None.
       반환 dict: {'kw_date','generated','items'}."""
    res = (_client().table(KW_TABLE)
           .select("kw_date,generated,items")
           .order("kw_date", desc=True)
           .limit(1)
           .execute())
    return res.data[0] if res.data else None


def load_keywords_by_date(kw_date: str) -> dict | None:
    """특정 날짜(YYYY-MM-DD)의 키워드 1행을 반환. 없으면 None."""
    res = (_client().table(KW_TABLE)
           .select("kw_date,generated,items")
           .eq("kw_date", kw_date)
           .limit(1)
           .execute())
    return res.data[0] if res.data else None


def list_keyword_dates(limit: int = 90) -> list[str]:
    """키워드가 저장된 날짜 목록을 최신순으로 반환(YYYY-MM-DD)."""
    res = (_client().table(KW_TABLE)
           .select("kw_date")
           .order("kw_date", desc=True)
           .limit(limit)
           .execute())
    return [r["kw_date"] for r in (res.data or [])]


def load_recent_keywords(limit: int = 40) -> list[dict]:
    """최근 키워드 행들을 최신순으로 반환(streak·NEW 계산용).
       각 행: {'kw_date','generated','items'}."""
    res = (_client().table(KW_TABLE)
           .select("kw_date,generated,items")
           .order("kw_date", desc=True)
           .limit(limit)
           .execute())
    return res.data or []


# ── 부동산 키워드: 읽기·쓰기 (증시 keywords 미러, realestate_keywords 테이블) ──
# 증시(keywords)와 동일 스키마: kw_date(PK)·generated·items(JSONB)·updated_at.
# 영속·누적 저장으로 streak/NEW가 끊기지 않게 한다(파일 아카이브는 휘발성).

def save_realestate_keywords(items: list, generated: str | None = None,
                             kw_date: str | None = None) -> str:
    """오늘의 부동산 키워드를 DB에 저장(upsert, kw_date 단일행)."""
    now = datetime.now()
    generated = generated or now.isoformat()
    if not kw_date:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", str(generated))
        kw_date = m.group(1) if m else now.strftime("%Y-%m-%d")
    row = {
        "kw_date": kw_date,
        "generated": str(generated),
        "items": items or [],
        "updated_at": now.isoformat(),
    }
    _client().table(RE_KW_TABLE).upsert(row, on_conflict="kw_date").execute()
    return kw_date


def load_realestate_keywords_latest() -> dict | None:
    """가장 최신 부동산 키워드 1행. 없으면 None. 반환: {'kw_date','generated','items'}."""
    res = (_client().table(RE_KW_TABLE)
           .select("kw_date,generated,items")
           .order("kw_date", desc=True)
           .limit(1)
           .execute())
    return res.data[0] if res.data else None


def load_realestate_keywords_by_date(kw_date: str) -> dict | None:
    """특정 날짜(YYYY-MM-DD)의 부동산 키워드 1행. 없으면 None."""
    res = (_client().table(RE_KW_TABLE)
           .select("kw_date,generated,items")
           .eq("kw_date", kw_date)
           .limit(1)
           .execute())
    return res.data[0] if res.data else None


def list_realestate_keyword_dates(limit: int = 90) -> list[str]:
    """부동산 키워드가 저장된 날짜 목록을 최신순으로 반환(YYYY-MM-DD)."""
    res = (_client().table(RE_KW_TABLE)
           .select("kw_date")
           .order("kw_date", desc=True)
           .limit(limit)
           .execute())
    return [r["kw_date"] for r in (res.data or [])]


def load_recent_realestate_keywords(limit: int = 40) -> list[dict]:
    """최근 부동산 키워드 행들을 최신순으로 반환(streak·NEW 계산용)."""
    res = (_client().table(RE_KW_TABLE)
           .select("kw_date,generated,items")
           .order("kw_date", desc=True)
           .limit(limit)
           .execute())
    return res.data or []


# ── 증시 IPO 스냅샷: 읽기·쓰기 ────────────────────────────────
# ipo_snapshots 테이블에 날짜(asof_date)별로 최신 수집 결과를 upsert.
# 뷰어(modules/ipo.py)는 최신 1행만 읽어 '항상 실데이터'를 보장(샘플 폴백은 행이 없을 때만).
# recent/upcoming 은 뷰어가 그대로 그릴 수 있는 dict 배열.

def save_ipo(recent=None, upcoming=None,
             asof: str | None = None, asof_date: str | None = None) -> str:
    """IPO 스냅샷 저장(upsert, asof_date 단일행)."""
    now = datetime.now()
    asof = asof or now.strftime("%Y-%m-%d %H:%M")
    asof_date = asof_date or asof[:10]
    row = {
        "asof_date": asof_date,
        "asof": asof,
        "recent": recent or [],
        "upcoming": upcoming or [],
        "updated_at": now.isoformat(),
    }
    _client().table(IPO_TABLE).upsert(row, on_conflict="asof_date").execute()
    return asof_date


def load_ipo() -> dict | None:
    """가장 최신 IPO 스냅샷 1행을 반환. 행이 없으면 None.
       반환 dict: {'asof','recent','upcoming'}."""
    res = (_client().table(IPO_TABLE)
           .select("asof,recent,upcoming")
           .order("asof_date", desc=True)
           .limit(1)
           .execute())
    return res.data[0] if res.data else None


# ── 주도주 스냅샷: 읽기·쓰기 ──────────────────────────────────
# leaders 테이블에 날짜(asof_date)별로 전종목 스캔·점수화 결과를 payload(jsonb)로 upsert.
# 뷰어(modules/leaders.py)는 최신 1행만 읽어 '항상 실데이터'를 보장.
# payload 구조: {asof, asof_date, params, sectors[], stocks[]}
 
def save_leaders(payload: dict, asof: str | None = None,
                 asof_date: str | None = None) -> str:
    """주도주 스냅샷 저장(upsert, asof_date 단일행). payload는 collect() 결과 dict."""
    now = datetime.now()
    asof = asof or (payload or {}).get("asof") or now.strftime("%Y-%m-%d %H:%M")
    asof_date = asof_date or (payload or {}).get("asof_date") or asof[:10]
    row = {
        "asof_date": asof_date,
        "asof": asof,
        "payload": payload,
        "updated_at": now.isoformat(),
    }
    _client().table(LEADERS_TABLE).upsert(row, on_conflict="asof_date").execute()
    return asof_date
 
 
def load_leaders() -> dict | None:
    """가장 최신 주도주 스냅샷 payload를 반환. 행이 없으면 None.
       반환 dict: {asof, asof_date, params, sectors[], stocks[]}."""
    res = (_client().table(LEADERS_TABLE)
           .select("asof,payload")
           .order("asof_date", desc=True)
           .limit(1)
           .execute())
    if not res.data:
        return None
    row = res.data[0]
    payload = row.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}
    payload.setdefault("asof", row.get("asof"))
    return payload


def load_leaders_history(n: int = 4) -> list[dict]:
    """최근 N일 주도주 스냅샷 payload를 최신순(오늘=[0])으로 반환. 행이 없으면 빈 리스트.

    주도주 '시간 레이어'(순위 변화·주도 지속일·섹터 로테이션·이벤트) 계산용.
    엔진을 다시 돌리지 않고 이미 누적된 과거 스냅샷만 읽어 Δ를 만든다(추가 수집비용 0).
    각 dict: {asof, asof_date, params, sectors[], stocks[]}."""
    try:
        res = (_client().table(LEADERS_TABLE)
               .select("asof,asof_date,payload")
               .order("asof_date", desc=True)
               .limit(max(1, int(n)))
               .execute())
    except Exception:
        return []
    out = []
    for row in (res.data or []):
        payload = row.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        if not isinstance(payload, dict):
            continue
        payload.setdefault("asof", row.get("asof"))
        payload.setdefault("asof_date", row.get("asof_date"))
        out.append(payload)
    return out


# ── 종목 마스터(종목명 ↔ 종목코드): 읽기·쓰기 ────────────────
# stock_master 테이블에 전 종목을 code(단축코드) 기준으로 upsert.
# 엔진(engine/stock_master.py)이 data.go.kr KRX상장종목정보로 채우고,
# 뷰어(modules/stock_quote.py)가 읽어 '종목명 → 코드'를 해석한다(pykrx 대체).
#
# 최초 1회 아래 SQL로 테이블 생성:
#   create table if not exists stock_master (
#     code       text primary key,
#     name       text not null,
#     corp_name  text,
#     market     text,
#     isin       text,
#     bas_dt     text,
#     updated_at timestamptz default now()
#   );
#   create index if not exists stock_master_name_idx on stock_master (name);

def save_stock_master(rows: list, basdt: str | None = None) -> int:
    """종목 마스터 행 목록을 code 기준 upsert. 저장한 행 수 반환.
       rows 각 항목: {code, name, corp_name, market, isin}."""
    now = datetime.now().isoformat()
    payload = []
    for r in rows or []:
        code = str(r.get("code") or "").strip()
        name = str(r.get("name") or "").strip()
        if not code or not name:
            continue
        payload.append({
            "code": code,
            "name": name,
            "corp_name": str(r.get("corp_name") or "").strip(),
            "market": str(r.get("market") or "").strip(),
            "isin": str(r.get("isin") or "").strip(),
            "bas_dt": str(basdt or "").strip(),
            "updated_at": now,
        })
    if not payload:
        return 0
    # Supabase 요청 크기 제한을 피하려 청크 단위 upsert
    tbl = _client().table(SM_TABLE)
    for i in range(0, len(payload), 500):
        tbl.upsert(payload[i:i + 500], on_conflict="code").execute()
    return len(payload)


def load_stock_master() -> list[dict]:
    """종목 마스터 전체 행을 반환(없으면 빈 리스트). 각 행: {code,name,corp_name,market}.
       Supabase 기본 응답 한도를 고려해 페이지 단위로 모두 읽는다."""
    out: list[dict] = []
    step = 1000
    start = 0
    while True:
        res = (_client().table(SM_TABLE)
               .select("code,name,corp_name,market")
               .range(start, start + step - 1)
               .execute())
        batch = res.data or []
        out.extend(batch)
        if len(batch) < step:
            break
        start += step
    return out


# ── IPO 회사소개(about) 캐시: 읽기·쓰기 ───────────────────────
# ipo_about 테이블에 종목코드별로 Haiku 요약 회사소개를 1회 저장(영구 캐시).
# 엔진(engine/ipo_about.py)이 DART 문서 → Haiku 요약 → 여기에 저장하고,
# 같은 종목은 재호출하지 않는다(신규 IPO만 생성).
#
# 최초 1회 아래 SQL로 테이블 생성:
#   create table if not exists ipo_about (
#     code       text primary key,
#     name       text,
#     about      text,
#     source     text,
#     updated_at timestamptz default now()
#   );

def save_ipo_about(code: str, name: str = "", about: str = "", source: str = "") -> None:
    """종목코드별 회사소개를 upsert(빈 about도 저장 → 반복 생성 비용 방지)."""
    code = str(code or "").strip()
    if not code:
        return
    _client().table(IPO_ABOUT_TABLE).upsert({
        "code": code,
        "name": str(name or "").strip(),
        "about": str(about or "").strip(),
        "source": str(source or "").strip(),
        "updated_at": datetime.now().isoformat(),
    }, on_conflict="code").execute()


def load_ipo_about_map() -> dict:
    """{종목코드: 회사소개} 전체를 반환(없으면 빈 dict). 빈 about도 키로 포함."""
    out: dict = {}
    step = 1000
    start = 0
    while True:
        res = (_client().table(IPO_ABOUT_TABLE)
               .select("code,about")
               .range(start, start + step - 1)
               .execute())
        batch = res.data or []
        for row in batch:
            c = str(row.get("code") or "").strip()
            if c:
                out[c] = str(row.get("about") or "").strip()
        if len(batch) < step:
            break
        start += step
    return out


# ── 수급 상위 종목(market_flow): 읽기·쓰기 ────────────────────
# market_flow 테이블에 날짜별로 외국인·기관 거래대금 상위 종목 payload(jsonb)를 저장.
# 엔진(engine/market_flow.py)이 pykrx로 채우고, 뷰어(modules/indices.py)가 최신 1행을 읽는다.
#
# 최초 1회 아래 SQL로 테이블 생성:
#   create table if not exists market_flow (
#     asof_date  text primary key,
#     payload    jsonb,
#     updated_at timestamptz default now()
#   );

def save_market_flow(payload: dict, asof_date: str | None = None) -> str:
    """수급 상위 payload를 날짜 기준 upsert."""
    asof_date = asof_date or datetime.now().strftime("%Y-%m-%d")
    _client().table(MFLOW_TABLE).upsert({
        "asof_date": asof_date,
        "payload": payload,
        "updated_at": datetime.now().isoformat(),
    }, on_conflict="asof_date").execute()
    return asof_date


def load_market_flow() -> dict | None:
    """가장 최신 수급 상위 payload(dict)를 반환. 없으면 None."""
    res = (_client().table(MFLOW_TABLE)
           .select("payload")
           .order("asof_date", desc=True)
           .limit(1)
           .execute())
    if res.data and res.data[0].get("payload"):
        return res.data[0]["payload"]
    return None
