# -*- coding: utf-8 -*-
"""[엔진] daily_rollup — 10일 purge 전에 '핵심 집계값'만 영구 테이블에 보존.

배경: 대부분의 시계열 테이블(leaders·realestate_snapshots 등)은 10일 후
  삭제(modules.db.RETENTION)되어 장기 추세·백테스트·적중률 누적이 불가능했다.
  이 모듈은 매 수집 잡의 마지막 단계에서 그날의 핵심값만 daily_rollup
  테이블(하루·섹션당 1행, purge 제외)에 upsert해 장기 자산을 쌓는다.

사용(워크플로에서):
    python -m engine.rollup stock        # 주식 마감 후(leaders.yml 끝)
    python -m engine.rollup realestate   # 부동산 수집 후(realestate.yml 끝)

섹션·내용:
  stock_market     코스피·코스닥 종가/등락률 + breadth(상승·보합·하락, 거래대금 억)
                   — 네이버 integration/polling(뷰어 market_breadth와 동일 소스)
  stock_leaders    주도주 Top10(code·name·market·score) — leaders 최신 행에서
  global           S&P500·나스닥·SOX·원달러 종가/등락률 — yfinance 배치
  realestate_cycle v5 산식 원료의 최신값(매수우위·주담대·착공YoY·전세YoY·매매지수·전세가율)
                   — realestate_snapshots.indicators에서. 합성 점수는 저장하지 않는다:
                   원료를 보존하면 v5든 이후 산식이든 언제든 소급 재계산 가능(산식 개정에 안전).

설계 원칙:
  · 기존 수집기는 수정하지 않는다 — 저장이 끝난 스냅샷을 '읽어서' 요약(결합도 0).
  · upsert(d, section) 멱등 — 멀티슬롯 크론이 여러 번 돌아도 그날 행 1개.
  · 섹션 하나가 실패해도 나머지는 저장(부분 성공). 전부 실패 시에만 exit 1
    → 워크플로 실패 알림(텔레그램)으로 이어져 조용한 실패를 차단.

테이블(최초 1회 SQL — 2026-07-15 실행 완료):
    create table if not exists daily_rollup (
      d date not null, section text not null,
      metrics jsonb not null default '{}'::jsonb,
      created_at timestamptz not null default now(),
      primary key (d, section));
"""
import sys
from datetime import datetime

import requests

try:
    from zoneinfo import ZoneInfo
    _KST = ZoneInfo("Asia/Seoul")
except Exception:
    _KST = None

ROLLUP_TABLE = "daily_rollup"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
_NAVER_CODE = {"kospi": "KOSPI", "kosdaq": "KOSDAQ"}


def _today() -> str:
    now = datetime.now(_KST) if _KST else datetime.now()
    return now.date().isoformat()


def save_rollup(section: str, metrics: dict) -> bool:
    """daily_rollup에 (오늘, 섹션) upsert. 성공 True."""
    if not metrics:
        print(f"[rollup] {section}: 빈 metrics — 저장 생략")
        return False
    from modules.db import _client
    row = {"d": _today(), "section": section, "metrics": metrics}
    _client().table(ROLLUP_TABLE).upsert(row, on_conflict="d,section").execute()
    print(f"[rollup] {section}: 저장 OK ({_today()}) · keys={sorted(metrics)[:8]}")
    return True


# ── 유틸 ──────────────────────────────────────────────────────────────────────
def _digits(x):
    try:
        return int("".join(ch for ch in str(x) if ch.isdigit()))
    except ValueError:
        return None


def _last(series):
    """시계열 배열의 마지막 유효값(float). 없으면 None."""
    for v in reversed(series or []):
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


# ── 소스: 네이버 지수·breadth (뷰어 market_breadth와 동일 엔드포인트) ─────────
def _naver_market(key: str):
    """{close, chg_pct, adv, flat, dec, value_eok} — 부분 실패 시 가능한 값만."""
    code = _NAVER_CODE.get(key)
    out = {}
    try:  # polling — 종가·등락률
        r = requests.get(
            f"https://polling.finance.naver.com/api/realtime/domestic/index/{code}",
            headers=_HEADERS, timeout=12)
        d0 = ((r.json() or {}).get("datas") or [{}])[0]
        cv = d0.get("closePrice") or d0.get("nv")
        if cv is not None:
            out["close"] = round(float(str(cv).replace(",", "")), 2)
        fr = d0.get("fluctuationsRatio")
        if fr is not None:
            out["chg_pct"] = round(float(fr), 2)
    except Exception as e:
        print(f"[rollup] {key} polling 실패: {e}")
    try:  # integration — breadth·거래대금
        r = requests.get(
            f"https://m.stock.naver.com/api/index/{code}/integration",
            headers=_HEADERS, timeout=12)
        data = r.json() or {}
        ud = data.get("upDownStockInfo") or {}
        adv = (_digits(ud.get("riseCount")) or 0) + (_digits(ud.get("upperCount")) or 0)
        dec = (_digits(ud.get("fallCount")) or 0) + (_digits(ud.get("lowerCount")) or 0)
        flat = _digits(ud.get("steadyCount")) or 0
        if adv + dec >= 100:            # 오파싱 가드(뷰어와 동일 기준)
            out.update({"adv": adv, "flat": flat, "dec": dec})
        for it in (data.get("totalInfos") or []):
            if it.get("code") == "accumulatedTradingValue":
                mn = _digits(it.get("value"))
                if mn:
                    out["value_eok"] = round(mn / 100)   # 백만 → 억
                break
    except Exception as e:
        print(f"[rollup] {key} integration 실패: {e}")
    return out


# ── 섹션 빌더 ─────────────────────────────────────────────────────────────────
def _build_stock_market():
    m = {}
    for key in ("kospi", "kosdaq"):
        v = _naver_market(key)
        if v:
            m[key] = v
    return m


def _build_stock_leaders():
    from modules.db import load_leaders
    ld = load_leaders() or {}
    stocks = sorted(ld.get("stocks") or [], key=lambda x: x.get("score") or 0,
                    reverse=True)[:10]
    if not stocks:
        return {}
    top = [{"code": s.get("code"), "name": s.get("name"),
            "market": s.get("market"), "score": s.get("score")} for s in stocks]
    return {"top": top, "asof": ld.get("asof")}


def _build_global():
    import yfinance as yf
    tick = {"^GSPC": "sp500", "^IXIC": "nasdaq", "^SOX": "sox", "KRW=X": "usdkrw"}
    m = {}
    try:
        df = yf.download(tickers=" ".join(tick), period="5d", interval="1d",
                         auto_adjust=True, group_by="ticker", progress=False)
        for t, key in tick.items():
            try:
                s = df[t]["Close"].dropna()
                if len(s) >= 2:
                    c, p = float(s.iloc[-1]), float(s.iloc[-2])
                    m[key] = {"close": round(c, 2),
                              "chg_pct": round((c / p - 1) * 100, 2)}
            except Exception:
                continue
    except Exception as e:
        print(f"[rollup] global yfinance 실패: {e}")
    return m


def _build_realestate_cycle():
    from modules.db import _client
    res = (_client().table("realestate_snapshots")
           .select("asof_date,indicators")
           .order("asof_date", desc=True).limit(1).execute())
    if not res.data:
        return {}
    row = res.data[0]
    by = {it.get("key"): it for it in (row.get("indicators") or [])}

    def last_of(*keys):
        for k in keys:
            v = _last((by.get(k) or {}).get("series"))
            if v is not None:
                return v
        return None

    m = {"asof": row.get("asof_date"),
         "buy": last_of("buy_l", "buy"),          # 매수우위(주간 최신)
         "mortgage": last_of("mortgage"),          # 주담대 금리(%)
         "starts_yoy": last_of("starts"),          # 착공 YoY 3M평균(%)
         "sale_m": last_of("sale_m"),              # 서울 매매지수(월간)
         "jr": last_of("jr")}                      # 전세가율(%)
    jm = [v for v in ((by.get("jeonse_m") or {}).get("series") or [])
          if v is not None]
    if len(jm) >= 13 and jm[-13]:                  # 전세지수 YoY(%)
        m["jeonse_yoy"] = round((jm[-1] / jm[-13] - 1) * 100, 2)
    return {k: v for k, v in m.items() if v is not None}


def _build_us_market():
    """usmkt_snapshots 최신 행 → 업종 등락·상하위·이슈 티커 요약(장기 자산)."""
    from modules.db import load_usmkt
    d = load_usmkt() or {}
    p = d.get("payload") or {}
    if not p.get("sectors"):
        return {}
    return {"trade_date": p.get("trade_date"),
            "sectors": {s["nm"]: s.get("chg") for s in p["sectors"]},
            "up": [{"tk": x["tk"], "chg": x.get("chg")}
                   for x in (p.get("movers") or {}).get("up") or []],
            "dn": [{"tk": x["tk"], "chg": x.get("chg")}
                   for x in (p.get("movers") or {}).get("dn") or []],
            "issues": [x["tk"] for x in p.get("issues") or []]}


# ── 진입점 ────────────────────────────────────────────────────────────────────
def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    if mode == "stock":
        jobs = [("stock_market", _build_stock_market),
                ("stock_leaders", _build_stock_leaders),
                ("global", _build_global)]
    elif mode == "realestate":
        jobs = [("realestate_cycle", _build_realestate_cycle)]
    elif mode == "us":
        jobs = [("us_market", _build_us_market)]
    else:
        print("usage: python -m engine.rollup [stock|realestate|us]")
        sys.exit(2)
    ok = 0
    for section, fn in jobs:
        try:
            if save_rollup(section, fn()):
                ok += 1
        except Exception as e:
            print(f"[rollup] {section} 실패: {e}")
    print(f"[rollup] {mode}: {ok}/{len(jobs)} 섹션 저장")
    if ok == 0:                    # 전멸 시에만 잡 실패 → 텔레그램 실패 알림
        sys.exit(1)


if __name__ == "__main__":
    main()
