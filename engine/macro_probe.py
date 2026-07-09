"""[엔진·1회성 probe · 2차] 거시지표 잔여 코드 확정 — M2 신지표 · 착공.

1차 probe에서 확정: 주담대 121Y006/M/BECBLA0302 · GDP 200Y102/Q/10111 ·
기준금리 722Y001/M/0101000. 잔여 미확정 2개만 검증한다.

  [A] M2 신지표: 161Y005(평잔·계절조정)/161Y006(평잔·원계열) 항목코드 조회
      → 'M2' 합계 항목으로 실데이터 샘플 fetch (2020년 커버 여부 포함)
  [B] 착공:
      B-1) ECOS 901Y103 건축착공현황 항목코드 조회 → 주거용 항목 실데이터
      B-2) KOSIS 착공 후보를 objL 단계 확장으로 재시도(1차의 err20 해소)
      ※ 값이 연간 누계(YTD)인지 월별인지 판별 위해 연속 6개월 출력

실행: macro_probe.yml (workflow_dispatch) — 로그 전체를 복사해 검토.
환경변수: ECOS_API_KEY(필수) · KOSIS_API_KEY(선택)
"""

import json
import os
import sys
import time

import requests

ECOS_KEY = os.environ.get("ECOS_API_KEY", "").strip()
KOSIS_KEY = os.environ.get("KOSIS_API_KEY", "").strip()
_TIMEOUT = 30
_UA = {"User-Agent": "Mozilla/5.0 (compatible; dy-monitoring-probe/2.0)"}


def _sec(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def _get_json(url):
    try:
        r = requests.get(url, headers=_UA, timeout=_TIMEOUT)
        try:
            return r.json(), None
        except Exception:
            return None, f"HTTP {r.status_code} · JSON 아님 · 앞 300자: {r.text[:300]!r}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def ecos_item_list(stat):
    url = (f"https://ecos.bok.or.kr/api/StatisticItemList/{ECOS_KEY}"
           f"/json/kr/1/1000/{stat}")
    j, err = _get_json(url)
    if err:
        return None, err
    rows = ((j or {}).get("StatisticItemList") or {}).get("row")
    if rows is None:
        return None, json.dumps((j or {}).get("RESULT", j), ensure_ascii=False)[:200]
    return rows, None


def ecos_search(stat, cycle, item, start, end):
    url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{ECOS_KEY}"
           f"/json/kr/1/300/{stat}/{cycle}/{start}/{end}/{item}")
    j, err = _get_json(url)
    if err:
        return None, err, url
    rows = ((j or {}).get("StatisticSearch") or {}).get("row")
    if not rows:
        return None, json.dumps((j or {}).get("RESULT", j), ensure_ascii=False)[:200], url
    return rows, None, url


def _dump_rows(rows, head=3, tail=6):
    for r in rows[:head]:
        print(f"     {r.get('TIME')} = {r.get('DATA_VALUE')}  "
              f"({r.get('ITEM_NAME1')}) 단위:{r.get('UNIT_NAME')}")
    if len(rows) > head + tail:
        print(f"     … 중략({len(rows)}행) …")
    for r in rows[-tail:]:
        print(f"     {r.get('TIME')} = {r.get('DATA_VALUE')}  "
              f"({r.get('ITEM_NAME1')}) 단위:{r.get('UNIT_NAME')}")


# ── [A] M2 신지표 ────────────────────────────────────────────────────────
def probe_m2():
    _sec("[A] M2 신지표(161Y005 계절조정 / 161Y006 원계열) — 항목코드 + 샘플")
    if not ECOS_KEY:
        print("  ! ECOS_API_KEY 미설정 — 생략")
        return
    for stat, label in (("161Y005", "M2 상품별(평잔, 계절조정)"),
                        ("161Y006", "M2 상품별(평잔, 원계열)")):
        print(f"\n  ── {stat} · {label} · 항목 목록(상위 20)")
        rows, err = ecos_item_list(stat)
        if err:
            print(f"     ! 실패: {err}")
            continue
        m2_items = []
        for r in rows[:20]:
            nm = r.get("ITEM_NAME") or ""
            print(f"     item={r.get('ITEM_CODE'):>12s} · cycle={r.get('CYCLE') or '-':>2s}"
                  f" · {nm} · {r.get('START_TIME')}~{r.get('END_TIME')}")
        for r in rows:
            nm = (r.get("ITEM_NAME") or "").replace(" ", "")
            if nm.startswith("M2") and (r.get("CYCLE") == "M"):
                m2_items.append((r.get("ITEM_CODE"), r.get("ITEM_NAME")))
        # 합계로 보이는 항목(이름이 'M2'로 시작하는 최상위) 우선 샘플
        for code, nm in m2_items[:2]:
            print(f"\n     ▶ 샘플 fetch {stat}/M/{code} · {nm} (2020.1~ 커버 확인)")
            data, err, url = ecos_search(stat, "M", code, "202001", "202607")
            print(f"       {url}")
            if err:
                print(f"       ! 실패: {err}")
            else:
                _dump_rows(data)
        time.sleep(0.3)


# ── [B-1] ECOS 착공(901Y103 건축착공현황) ────────────────────────────────
def probe_ecos_start():
    _sec("[B-1] ECOS 901Y103 건축착공현황 — 항목코드 + 주거용 샘플")
    if not ECOS_KEY:
        return
    rows, err = ecos_item_list("901Y103")
    if err:
        print(f"  ! 실패: {err}")
        return
    print(f"  항목 {len(rows)}개 — 전체 출력:")
    res_items = []
    for r in rows:
        nm = r.get("ITEM_NAME") or ""
        print(f"  item={r.get('ITEM_CODE'):>12s} · cycle={r.get('CYCLE') or '-':>2s}"
              f" · {nm} · {r.get('START_TIME')}~{r.get('END_TIME')} · 단위:{r.get('UNIT_NAME')}")
        if any(k in nm for k in ("주거", "주택", "전체", "계", "전국")):
            res_items.append((r.get("ITEM_CODE"), nm))
    for code, nm in res_items[:3]:
        print(f"\n  ▶ 샘플 fetch 901Y103/M/{code} · {nm} · 연속 6개월(누계 여부 판별)")
        data, err, url = ecos_search("901Y103", "M", code, "202512", "202606")
        print(f"    {url}")
        if err:
            print(f"    ! 실패: {err}")
        else:
            _dump_rows(data, head=6, tail=1)
        time.sleep(0.3)
    # 2020 커버 확인(첫 항목)
    if res_items:
        code, nm = res_items[0]
        data, err, url = ecos_search("901Y103", "M", code, "202001", "202006")
        print(f"\n  ▶ 2020년 커버 확인 {code} · {nm}")
        if err:
            print(f"    ! 실패: {err}")
        else:
            _dump_rows(data, head=6, tail=1)


# ── [B-2] KOSIS 착공 — objL 단계 확장 재시도 ────────────────────────────
_KOSIS_CANDIDATES = [
    ("116", "DT_MLTM_5405", "주택건설 착공실적(후보1)"),
    ("116", "DT_MLTM_5386", "주택건설 착공실적(후보2)"),
    ("116", "DT_MLTM_1244", "주택건설실적통계(후보)"),
    ("116", "DT_MLTM_2080", "미분양주택현황(참고)"),
]


def probe_kosis_start():
    _sec("[B-2] KOSIS 착공 후보 — objL 단계 확장(err20 해소 시도)")
    if not KOSIS_KEY:
        print("  ! KOSIS_API_KEY 미설정 — 생략")
        return
    base = ("https://kosis.kr/openapi/Param/statisticsParameterData.do"
            "?method=getList&apiKey={key}&orgId={org}&tblId={tbl}"
            "&itmId=ALL&prdSe=M&newEstPrdCnt=6&format=json&jsonVD=Y")
    ladders = [
        "&objL1=ALL",
        "&objL1=ALL&objL2=ALL",
        "&objL1=ALL&objL2=ALL&objL3=ALL",
        "&objL1=ALL&objL2=ALL&objL3=ALL&objL4=ALL",
    ]
    for org, tbl, label in _KOSIS_CANDIDATES:
        print(f"\n  ── {org}/{tbl} · {label}")
        ok = False
        for lad in ladders:
            url = base.format(key=KOSIS_KEY, org=org, tbl=tbl) + lad
            j, err = _get_json(url)
            if err:
                print(f"     [{lad}] 요청 실패: {err}")
                continue
            if isinstance(j, list) and j:
                print(f"     OK [{lad}] · {len(j)}행 · 샘플 5행(누계 여부 판별용 연속월):")
                for r in j[:5]:
                    print(f"       {r.get('PRD_DE')} · {r.get('C1_NM')} · {r.get('C2_NM') or ''}"
                          f" · {r.get('ITM_NM')} = {r.get('DT')} {r.get('UNIT_NM')}")
                ok = True
                break
            print(f"     [{lad}] 오류: {json.dumps(j, ensure_ascii=False)[:160]}")
            time.sleep(0.2)
        if not ok:
            print("     → 전 단계 실패 · kosis.kr에서 표 열어 tblId/objL 구조 확인 필요")
        time.sleep(0.3)


def main():
    print("macro_probe(2차) — M2 신지표 · 착공 코드 확정")
    print(f"ECOS_API_KEY: {'설정됨' if ECOS_KEY else '없음'} · "
          f"KOSIS_API_KEY: {'설정됨' if KOSIS_KEY else '없음'}")
    probe_m2()
    probe_ecos_start()
    probe_kosis_start()
    print("\n[완료] 로그 전체를 복사해 검토하면 M2·착공 코드를 확정할 수 있어요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
