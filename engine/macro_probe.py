"""[엔진·1회성 probe] 거시지표 API 검증 — ECOS(한국은행) + KOSIS(국토부 주택공급).

목적: 사이클 탭 '거시 환경' 지표(기준금리·주담대금리·M2·GDP성장률·주택공급)를
      실제 데이터센터 IP(GitHub Actions)에서 끌어올 수 있는지, 정확한 통계코드·
      항목코드가 무엇인지 빌드 전에 확정한다(probe before building).

실행: GitHub Actions macro_probe.yml (workflow_dispatch 수동 실행)
      → 로그 전체를 복사해 검토하면 코드 확정 가능.

검증 순서
  [1] ECOS StatisticTableList 전체(페이지네이션) → 키워드 매칭 통계표 출력
  [2] 후보 통계표별 StatisticItemList → 관련 항목코드 출력
  [3] 확정 가능 조합으로 StatisticSearch 실데이터 6건 샘플 fetch
  [4] KOSIS 후보 tblId 직접 조회(미분양·인허가 등) — 성공/실패 원문 출력

환경변수: ECOS_API_KEY(필수) · KOSIS_API_KEY(선택) · EXTRA_KOSIS_TBL(선택,
          "orgId:tblId,orgId:tblId" 형식으로 후보 추가)
"""

import json
import os
import sys
import time

import requests

ECOS_KEY = os.environ.get("ECOS_API_KEY", "").strip()
KOSIS_KEY = os.environ.get("KOSIS_API_KEY", "").strip()
_TIMEOUT = 30
_UA = {"User-Agent": "Mozilla/5.0 (compatible; dy-monitoring-probe/1.0)"}


def _sec(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def _get_json(url):
    """GET → json. 실패 시 (None, 에러문자열)."""
    try:
        r = requests.get(url, headers=_UA, timeout=_TIMEOUT)
        try:
            return r.json(), None
        except Exception:
            return None, f"HTTP {r.status_code} · JSON 아님 · 본문 앞 300자: {r.text[:300]!r}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# ── [1] ECOS 통계표 전체 목록 → 키워드 매칭 ─────────────────────────────
_ECOS_TBL_KEYWORDS = [
    "기준금리", "가중평균", "M2", "통화", "국내총생산", "경제성장",
    "주택", "인허가", "착공", "미분양", "건설",
]


def ecos_table_list():
    """StatisticTableList 페이지네이션 수집. 반환 [ {STAT_CODE, STAT_NAME, CYCLE, SRCH_YN}... ]"""
    out, page, per = [], 1, 1000
    while page <= 10:  # 안전 상한(전체 ~수천 건)
        s, e = (page - 1) * per + 1, page * per
        url = (f"https://ecos.bok.or.kr/api/StatisticTableList/{ECOS_KEY}"
               f"/json/kr/{s}/{e}/")
        j, err = _get_json(url)
        if err:
            print(f"  ! TableList p{page} 실패: {err}")
            break
        rows = ((j or {}).get("StatisticTableList") or {}).get("row") or []
        if not rows:
            # ECOS 오류 포맷 {"RESULT":{"CODE":..,"MESSAGE":..}}
            res = (j or {}).get("RESULT")
            if res:
                print(f"  ! ECOS 응답: {res}")
            break
        out.extend(rows)
        if len(rows) < per:
            break
        page += 1
        time.sleep(0.3)
    return out


def probe_ecos_tables():
    _sec("[1] ECOS 통계표 목록 — 키워드 매칭")
    if not ECOS_KEY:
        print("  ! ECOS_API_KEY 미설정 — ECOS 단계 전체 생략")
        return []
    tables = ecos_table_list()
    print(f"  통계표 총 {len(tables)}건 수신")
    hits = []
    for t in tables:
        name = t.get("STAT_NAME") or ""
        if any(k in name for k in _ECOS_TBL_KEYWORDS):
            hits.append(t)
    # 검색 가능(SRCH_YN=Y) 우선 출력
    for t in sorted(hits, key=lambda x: (x.get("SRCH_YN") != "Y", x.get("STAT_CODE", ""))):
        print(f"  {t.get('STAT_CODE'):>10s} · {t.get('CYCLE') or '-':>2s} · "
              f"srch={t.get('SRCH_YN')} · {t.get('STAT_NAME')}")
    return hits


# ── [2] 후보 통계표 항목코드 조회 ────────────────────────────────────────
#   (통계코드, 라벨, 항목 키워드 필터) — 필터 None이면 전체 출력(상위 40개)
_ECOS_ITEM_TARGETS = [
    ("722Y001", "한국은행 기준금리", None),
    ("121Y006", "예금은행 가중평균금리(신규취급액)", ["주택"]),
    ("101Y004", "M2 상품별(평잔)", ["M2"]),
    ("101Y003", "M2 상품별(말잔)", ["M2"]),
    ("200Y102", "국민소득(성장률 후보1)", ["국내총생산", "경제성장"]),
    ("200Y101", "국민소득(성장률 후보2)", ["국내총생산", "경제성장"]),
]


def ecos_item_list(stat):
    url = (f"https://ecos.bok.or.kr/api/StatisticItemList/{ECOS_KEY}"
           f"/json/kr/1/1000/{stat}")
    j, err = _get_json(url)
    if err:
        return None, err
    rows = ((j or {}).get("StatisticItemList") or {}).get("row")
    if rows is None:
        return None, f"항목 없음/오류: {json.dumps((j or {}).get('RESULT', j), ensure_ascii=False)[:200]}"
    return rows, None


def probe_ecos_items(extra_stats=()):
    _sec("[2] ECOS 항목코드 조회")
    if not ECOS_KEY:
        return {}
    found = {}
    targets = list(_ECOS_ITEM_TARGETS) + [(s, "(키워드 발견 통계표)", None)
                                          for s in extra_stats]
    for stat, label, kw in targets:
        print(f"\n  ── {stat} · {label}")
        rows, err = ecos_item_list(stat)
        if err:
            print(f"     ! 실패: {err}")
            continue
        shown = 0
        for r in rows:
            nm = r.get("ITEM_NAME") or ""
            if kw and not any(k in nm for k in kw):
                continue
            print(f"     item={r.get('ITEM_CODE'):>12s} · cycle={r.get('CYCLE') or '-':>2s}"
                  f" · {nm} · 기간 {r.get('START_TIME')}~{r.get('END_TIME')}")
            found.setdefault(stat, []).append(
                (r.get("ITEM_CODE"), r.get("CYCLE"), nm,
                 r.get("START_TIME"), r.get("END_TIME")))
            shown += 1
            if shown >= 40:
                print("     … (40개 초과 생략)")
                break
        if shown == 0:
            print("     (키워드 매칭 항목 없음 — 필터 없이 상위 10개)")
            for r in rows[:10]:
                print(f"     item={r.get('ITEM_CODE'):>12s} · cycle={r.get('CYCLE') or '-':>2s}"
                      f" · {r.get('ITEM_NAME')}")
        time.sleep(0.3)
    return found


# ── [3] 실데이터 샘플 fetch ──────────────────────────────────────────────
def _ecos_period(cycle, n=6):
    """주기별 최근 n개 기간 문자열(시작, 끝). ECOS 포맷: A=YYYY Q=YYYYQn M=YYYYMM D=YYYYMMDD"""
    from datetime import date
    t = date.today()
    if cycle == "D":
        return (t.replace(day=1).strftime("%Y%m01"), t.strftime("%Y%m%d"))
    if cycle == "M":
        y, m = t.year, t.month - (n - 1)
        while m <= 0:
            y, m = y - 1, m + 12
        return (f"{y}{m:02d}", f"{t.year}{t.month:02d}")
    if cycle == "Q":
        qi = (t.year * 4 + (t.month - 1) // 3) - (n - 1)
        return (f"{qi // 4}Q{qi % 4 + 1}", f"{t.year}Q{(t.month - 1) // 3 + 1}")
    return (str(t.year - n + 1), str(t.year))


def ecos_search(stat, cycle, item, n=6):
    s, e = _ecos_period(cycle, n)
    item_part = f"/{item}" if item else ""
    url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{ECOS_KEY}"
           f"/json/kr/1/100/{stat}/{cycle}/{s}/{e}{item_part}")
    j, err = _get_json(url)
    if err:
        return None, err, url
    rows = ((j or {}).get("StatisticSearch") or {}).get("row")
    if not rows:
        return None, json.dumps((j or {}).get("RESULT", j), ensure_ascii=False)[:200], url
    return rows, None, url


def probe_ecos_data(found):
    _sec("[3] ECOS 실데이터 샘플 (최근 관측치)")
    if not ECOS_KEY:
        return
    # 고정 후보 + [2]에서 발견된 항목 조합
    # ※ 722Y001/BECABA03은 realestate_cycle.py에 현재 박혀 있는 '주담대' 조합 —
    #   722Y001은 기준금리 통계표라 의심됨. 실제 뭘 반환하는지 여기서 직접 확인한다.
    combos = [("722Y001", "D", "0101000", "기준금리(일)"),
              ("722Y001", "M", "0101000", "기준금리(월)"),
              ("722Y001", "M", "BECABA03", "★기존 코드 검증: 722Y001+BECABA03(현행 주담대?)"),
              ("121Y006", "M", "BECBLA03", "★후보 검증: 121Y006+BECBLA03(주담대 신규취급)")]
    for stat, items in (found or {}).items():
        for code, cyc, nm, _s, _e in items[:3]:  # 통계표당 상위 3항목만 샘플
            combos.append((stat, cyc or "M", code, nm))
    seen = set()
    for stat, cyc, item, label in combos:
        key = (stat, cyc, item)
        if key in seen:
            continue
        seen.add(key)
        rows, err, url = ecos_search(stat, cyc, item)
        print(f"\n  ── {stat}/{cyc}/{item} · {label}")
        print(f"     {url}")
        if err:
            print(f"     ! 실패: {err}")
            continue
        for r in rows[-6:]:
            print(f"     {r.get('TIME')} = {r.get('DATA_VALUE')}"
                  f"  ({r.get('ITEM_NAME1')}) 단위:{r.get('UNIT_NAME')}")
        time.sleep(0.3)


# ── [4] KOSIS 주택공급 후보 직접 조회 ────────────────────────────────────
#   (orgId, tblId, 라벨) — 실패해도 원문 출력해 원인 판별(코드오류/IP차단/키오류)
#   ★공급 지표는 '착공' 확정 — 착공 후보를 우선 검증하고 인허가·미분양은 참고로 유지.
#   후보 tblId가 전부 실패하면: kosis.kr에서 '주택건설실적통계(착공)' 표를 열어
#   URL의 tblId= 값을 확인 → workflow 실행 시 extra_kosis_tbl 입력으로 재검증.
_KOSIS_CANDIDATES = [
    ("116", "DT_MLTM_5405", "주택건설 착공실적(후보1)"),
    ("116", "DT_MLTM_5386", "주택건설 착공실적(후보2)"),
    ("116", "DT_MLTM_1244", "주택건설실적통계(후보)"),
    ("116", "DT_MLTM_2080", "미분양주택현황(참고)"),
    ("116", "DT_MLTM_5403", "주택건설 인허가실적(참고)"),
]


def probe_kosis():
    _sec("[4] KOSIS 주택공급 후보 조회")
    if not KOSIS_KEY:
        print("  ! KOSIS_API_KEY 미설정 — 생략")
        return
    cands = list(_KOSIS_CANDIDATES)
    extra = os.environ.get("EXTRA_KOSIS_TBL", "").strip()
    if extra:
        for tok in extra.split(","):
            if ":" in tok:
                o, t = tok.split(":", 1)
                cands.append((o.strip(), t.strip(), "(수동 추가)"))
    for org, tbl, label in cands:
        url = ("https://kosis.kr/openapi/Param/statisticsParameterData.do"
               f"?method=getList&apiKey={KOSIS_KEY}&orgId={org}&tblId={tbl}"
               "&itmId=ALL&objL1=ALL&objL2=&objL3=&objL4=&objL5=&objL6=&objL7=&objL8="
               "&prdSe=M&newEstPrdCnt=2&format=json&jsonVD=Y")
        j, err = _get_json(url)
        print(f"\n  ── {org}/{tbl} · {label}")
        if err:
            print(f"     ! 요청 실패: {err}")
            continue
        if isinstance(j, list) and j:
            print(f"     OK · {len(j)}행 수신 · 샘플 3행:")
            for r in j[:3]:
                print(f"       {r.get('PRD_DE')} · {r.get('C1_NM')} · "
                      f"{r.get('ITM_NM')} = {r.get('DT')} {r.get('UNIT_NM')}")
        else:
            print(f"     ! 오류 응답: {json.dumps(j, ensure_ascii=False)[:300]}")
        time.sleep(0.3)


def main():
    print("macro_probe — ECOS/KOSIS 거시지표 접근성·코드 검증")
    print(f"ECOS_API_KEY: {'설정됨' if ECOS_KEY else '없음'} · "
          f"KOSIS_API_KEY: {'설정됨' if KOSIS_KEY else '없음'}")
    hits = probe_ecos_tables()
    # 주택/인허가/미분양 키워드로 발견된 통계표는 항목 조회 대상에 추가
    extra = [t.get("STAT_CODE") for t in hits
             if any(k in (t.get("STAT_NAME") or "")
                    for k in ("인허가", "미분양", "주택건설"))][:5]
    found = probe_ecos_items(extra_stats=extra)
    probe_ecos_data(found)
    probe_kosis()
    print("\n[완료] 위 로그 전체를 복사해 검토하면 통계코드·항목코드를 확정할 수 있어요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
