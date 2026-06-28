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
"""
import json
import os
import re
from datetime import datetime

from supabase import create_client, Client

TABLE = "reports"
WL_TABLE = "watchlist"
WL_ID = 1
RE_TABLE = "realestate_snapshots"
KW_TABLE = "keywords"
IPO_TABLE = "ipo_snapshots"
LEADERS_TABLE = "leaders"
SM_TABLE = "stock_master"
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
