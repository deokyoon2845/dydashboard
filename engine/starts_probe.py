"""starts_probe — 종합 강도 v4 '착공' 성분 재설계 실측 프로브 (1회성 진단).

문제의식(2026-07-14 · v4 첫 실화면에서 확인):
  현행 착공 성분 = ECOS 901Y103 주거용 착공 YoY·3M평균(전국) · lag29 · corr −0.80.
  ① YoY 기저효과 — 2023년 착공 붕괴 대비 2024년 +60~70%는 레벨이 여전히 낮아도
     커 보인다(현재 기여 −1.59가 공급 압력을 과장할 수 있음)
  ② 전국 폴백 — 타깃이 서울 매매지수인데 지방 착공까지 섞임
  ③ 임대 포함 — 분양시장 공급 신호로는 임대 제외가 순수
  ④ ECOS 착공 레벨이 2019.4~뿐 → 레벨형 산식(12M누적 갭)의 백테스트 표본 부족(n=24)

대안 소스: KOSIS 주택건설실적통계(국토부 승인통계) — 장기(2011~)·시도별·
  (표에 따라) 유형 구분까지. KOSIS는 Actions IP에서 검증된 통로(미분양 수집 가동 중).

프로브 절차(1회 실행에 전부 · 쓰기 없음):
  0) KOSIS 통합검색으로 '착공' 통계표 후보 자동 발견(orgId/tblId)
  1) 후보 표 구조 덤프 — 컬럼·분류값(서울/경기? 임대/분양?)·시점 범위
  2) 서울+경기 착공 시계열 구축 → 산식 후보 lag 스캔(타깃=서울 매매지수 3M 변화율):
       S1  12M누적의 60M평균 대비 갭  (레벨형 · 기저효과 없음)
       S2  YoY·3M평균                (현행 산식의 서울+경기 한정판)
       S3  임대 제외판 S1/S2          (유형 분류가 존재할 때만)
     기준선: 현행 ECOS 전국 YoY(2차 probe 실측 corr −0.803 · lag29)
  3) 승자 착공으로 조합 A 재평가(가중 재산정) → 현행 A(corr +0.869 · 85%)와 비교
  ★ 평가창 = 2016.1~ (EVAL_START) — 표시·백테스트를 2016년으로 넓히는 v5 확장의
    사전 실측을 겸함. 정권 전환 3회(박근혜→문재인→윤석열→이재명) 포함.
    단, S1 레벨형(12M누적+60M평균)은 KOSIS 2011~ 기준으로도 2019~부터만 산출
    가능해 2016~18 구간은 lag_scan의 n이 작게 나옴(정상 · 로그로 확인).
  4) [정책 레짐 · 2026-07-14 추가] 정권 더미(민주=+1.0 / 보수=−0.3 · REGIMES 상수)
     lag 스캔 + 조합 비교: A+P(40% 고정 · 사용자 편집 스펙) vs A+P(실측 가중) vs A.
     주의 — 창 안 정권 전환 2회뿐 · 2022~23 하락은 금리 쇼크와 중첩(교란) →
     corr이 높아도 '가설과 모순되지 않음' 수준의 증거. 가중 40%는 편집적 선택.

  5) [2026-07-14 2차] KOSIS 접근을 직접 REST(15초 타임아웃·재시도 3회)로 교체 —
     1차 실행에서 westus 러너의 kosis.kr connect timeout 실측(미분양 수집은 되던
     통로라 러너 지역별 간헐 이슈 추정). 검색 실패 시 국토부 후보 표 폴백(응답
     TBL_NM에 '착공' 검증 후 채택). 정책 고정가중 40% 단일점 → 10~40% 스윕 확장.
     1차 실측: P 단독 +0.609(lag0) · A 무정책 +0.823/80% ·
     A+P 실측가중(18%) +0.846/79% · A+P 40% 고정 +0.817/70%(적중률 -10pp).

실행: GitHub Actions에서 `python -m engine.starts_probe`
  (KOSIS_API_KEY · ECOS_API_KEY 필요 · KB는 키 불필요 · Supabase 불필요)
※ engine/macro_lag_probe.py 의 유틸을 import 하므로 그 파일은 이 작업이 끝날 때까지
  삭제하지 말 것(둘은 착공 확정 후 같이 삭제).
"""

from datetime import date

from engine.macro_lag_probe import (ym_add, ma, zscore, pearson, lag_shift,
                                    lag_scan, fmt_scan, roll_sum,
                                    gap_vs_trailing_mean, yoy,
                                    kb_series_with_dates, kb_maktrnd_with_dates,
                                    weekly_to_monthly, ecos_monthly,
                                    resolve_starts_levels, MIN_OVERLAP)

EVAL_START = "201601"  # 평가창 시작 — 2016~(정권 전환 3회 포함 · v5 확장 후보 창).
#                        macro_lag_probe의 202001 창 결과와 숫자가 달라지는 게 정상.
from engine.realestate_collect import _env_key

MAX_LAG = 40          # 착공은 2~3년 시차 가설 — 스캔 상한을 40으로 확장
KOSIS_MONTHS = 186    # 2011년~ 확보(12M누적+60M평균+lag29+z창이 2020.1 타깃을 커버)
REGIONS = ("서울", "경기")
TOTAL_LABELS = ("계", "합계", "소계", "전체", "총계")
RENT_HINTS = ("임대",)          # 유형 분류에서 '임대' 포함 라벨 제외용

# ── 정권 레짐 캘린더 — (시작YYYYMM, 끝YYYYMM|None=현재, 값) ─────
#   가설(사용자): 민주당 정권 = 규제·공급억제 기조로 강도 상승 압력(+1.0),
#   보수 정권 = 약보합(−0.3). 값·경계는 여기만 수정하면 됨.
REGIMES = [
    ("201302", "201704", -0.3),   # 박근혜~권한대행(보수) — 2016~ 평가창 커버용
    ("201705", "202204", +1.0),   # 문재인(민주)
    ("202205", "202505", -0.3),   # 윤석열~권한대행(보수)
    ("202506", None,     +1.0),   # 이재명(민주)
]
POLICY_W = 0.40                   # 사용자 편집 스펙 — 고정 가중 40%


def policy_series(start="201501"):
    """정권 더미 {YYYYMM: 값}. REGIMES 밖(2017.5 이전)은 직전/기본 0."""
    cur = date.today().strftime("%Y%m")
    out, ym = {}, start
    while ym <= cur:
        v = 0.0
        for a, b, val in REGIMES:
            if ym >= a and (b is None or ym <= b):
                v = val
        out[ym] = v
        ym = ym_add(ym, 1)
    return out


# ── 0) KOSIS 접근 — 직접 REST(타임아웃·재시도) ─────────────────
#   PublicDataReader는 타임아웃 제어가 없어 kosis.kr 간헐 차단(러너 지역별 ·
#   2026-07-14 westus에서 connect timeout 실측) 시 분당 단위로 매달린다.
#   ECOS와 같은 패턴: 15초 타임아웃 · 3회 재시도 · 실패 시 다음 단계로.
KOSIS_SEARCH_URL = "https://kosis.kr/openapi/statisticsSearch.do"
KOSIS_DATA_URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"

# 검색까지 막혔을 때 시도할 국토부(116) 주택건설실적 후보 표 — 이름을 모르는
# 추측 ID이므로, 응답의 TBL_NM에 '착공'이 있을 때만 채택(오표 채택 방지).
FALLBACK_TBLS = [("116", t) for t in
                 ("DT_MLTM_2080", "DT_MLTM_2078", "DT_MLTM_2079",
                  "DT_MLTM_2081", "DT_MLTM_2074", "DT_MLTM_2075",
                  "DT_MLTM_2076", "DT_MLTM_2077", "DT_MLTM_2083",
                  "DT_MLTM_2084", "DT_MLTM_2085", "DT_MLTM_5386")]


def _kosis_get(url, params, tries=3, wait=8):
    import time
    import requests
    key = _env_key("KOSIS_API_KEY")
    if not key:
        raise RuntimeError("KOSIS_API_KEY 없음")
    q = {"method": "getList", "apiKey": key, "format": "json", "jsonVD": "Y"}
    q.update(params)
    last = ""
    for i in range(tries):
        try:
            r = requests.get(url, params=q, timeout=15)
            j = r.json()
            if isinstance(j, list) and j:
                return j
            last = str(j)[:120]           # {"err":..} 형태 — 재시도 무의미
            break
        except Exception as e:
            last = str(e)[:120]
            if i < tries - 1:
                time.sleep(wait)
    print(f"    KOSIS 응답 없음({last})")
    return None


def search_tables(keyword):
    """KOSIS 통합검색 → [(org, tbl, name)] (착공 포함 표만)."""
    rows = _kosis_get(KOSIS_SEARCH_URL, {"searchNm": keyword})
    if not rows:
        print(f"  [검색] '{keyword}' 실패/0건")
        return []
    out = []
    for r in rows:
        nm = str(r.get("TBL_NM", ""))
        org, tbl = str(r.get("ORG_ID", "")), str(r.get("TBL_ID", ""))
        if "착공" in nm and org and tbl:
            out.append((org, tbl, nm))
    return out


def fetch_table(org, tbl, months=KOSIS_MONTHS):
    """통계자료 직접 조회 — 분류 차원 수를 몰라도 되도록 objL을 단계 확장."""
    import pandas as pd
    base = {"orgId": org, "tblId": tbl, "itmId": "ALL",
            "prdSe": "M", "newEstPrdCnt": str(months)}
    obj = {}
    for lv in ("objL1", "objL2", "objL3", "objL4"):
        obj[lv] = "ALL"
        rows = _kosis_get(KOSIS_DATA_URL, {**base, **obj}, tries=2, wait=6)
        if rows:
            return pd.DataFrame(rows)
    return None


def dump_structure(df, max_vals=14):
    """구조 덤프 — nm컬럼별 고유값·시점 범위. (지역컬럼, 시점컬럼, 값컬럼, nm컬럼들) 반환."""
    import pandas as pd
    cols = list(df.columns)
    pcol = next((c for c in cols if "시점" in c or c.upper() == "PRD_DE"), None)
    vcol = next((c for c in cols if c in ("수치", "DT") or c.upper() == "DT"), None)
    if vcol is None:
        for c in reversed(cols):
            if pd.to_numeric(df[c], errors="coerce").notna().sum() >= 2:
                vcol = c
                break
    import re as _re
    tblnm = str(df["TBL_NM"].iloc[0]) if "TBL_NM" in cols else ""
    if tblnm:
        print(f"    표명: {tblnm}")
    # 분류 컬럼만(C1_NM 등·ITM_NM·한글 '…명'). TBL_NM/UNIT_NM/C1_OBJ_NM 등
    # 메타 컬럼이 섞이면 '계' 필터가 전 행을 지워버리므로 제외.
    nmcols = [c for c in cols
              if _re.fullmatch(r"C\d_NM", c) or c == "ITM_NM"
              or (c.endswith("명") and c not in ("단위명",))]
    print(f"    행={len(df)} · 컬럼={cols}")
    if pcol is not None:
        print(f"    시점: {df[pcol].min()} ~ {df[pcol].max()}")
    regcol = None
    for c in nmcols:
        vals = [str(v) for v in df[c].dropna().unique()]
        mark = ""
        if any("서울" in v for v in vals):
            regcol = c
            mark = "  ← 지역컬럼"
        print(f"    {c} ({len(vals)}종): {vals[:max_vals]}{'…' if len(vals) > max_vals else ''}{mark}")
    return regcol, pcol, vcol, nmcols, tblnm


def build_series(df, regcol, pcol, vcol, nmcols, exclude_rent=False):
    """서울+경기 월별 합 {YYYYMM: value}. 지역 외 분류는 '계'만(중복합산 방지).
    exclude_rent=True면, '임대' 라벨이 존재하는 분류컬럼에서 임대 제외 합산으로 대체."""
    import pandas as pd
    d = df.copy()
    d["_v"] = pd.to_numeric(d[vcol].astype(str).str.replace(",", ""),
                            errors="coerce")
    d = d.dropna(subset=["_v"])
    d = d[d[regcol].astype(str).str.contains("|".join(REGIONS))]
    rent_col = None
    for c in [x for x in nmcols if x != regcol]:
        labels = d[c].astype(str)
        if exclude_rent and rent_col is None and labels.str.contains("|".join(RENT_HINTS)).any():
            rent_col = c              # 임대 라벨이 있는 분류 → 임대 제외·나머지 합산
            keep = ~labels.str.contains("|".join(RENT_HINTS))
            # '계'류 라벨은 임대를 포함하므로 함께 제외(이중합산·임대혼입 방지)
            keep &= ~labels.str.contains("|".join(TOTAL_LABELS))
            d = d[keep]
            continue
        m = labels.str.contains("|".join(TOTAL_LABELS))
        if m.any():
            d = d[m]
    if exclude_rent and rent_col is None:
        return {}, None               # 임대 분류 자체가 없음 → S3 불가
    g = d.groupby(pcol)["_v"].sum().sort_index()
    cur = date.today().strftime("%Y%m")
    out = {str(k): float(v) for k, v in g.items()
           if len(str(k)) == 6 and str(k) < cur and v == v}
    return out, rent_col


# ── 산식 후보 → lag 스캔 ────────────────────────────────────────
def scan(name, raw, target):
    proc = zscore(ma(raw))
    if not proc:
        print(f"  {name:<30} 표본 부족(n={len(raw)}) — 생략")
        return None
    bl, bc, rows = lag_scan(proc, target, max_lag=MAX_LAG)
    if bl is None:
        print(f"  {name:<30} 공통 표본 부족 — 생략")
        return None
    print(f"  {name:<30} n={len(raw):<4} best lag={bl:>2} corr={bc:+.3f}")
    print(f"      상위: {fmt_scan(rows)}")
    return {"lag": bl, "corr": bc, "z": proc, "rows": rows}


def eval_combo(title, members, target):
    """members=[(이름, zdict, lag, sign)] → |corr@lag| 비례 가중 합성 corr·적중률."""
    ms = []
    for nm, z, lag, sign in members:
        c, n = pearson(lag_shift(z, lag), target)
        if c is None:
            print(f"  {title}: '{nm}' lag={lag} 표본 부족 — 생략")
            return
        ms.append((nm, z, lag, sign, c))
    tot = sum(abs(m[4]) for m in ms) or 1e-9
    comp = {}
    for nm, z, lag, sign, c in ms:
        w = abs(c) / tot
        for ym, v in lag_shift(z, lag).items():
            comp[ym] = comp.get(ym, 0.0) + sign * w * v
    comp = {k: v for k, v in comp.items() if k >= EVAL_START}
    cc, n = pearson(comp, target)
    ks = sorted(set(comp) & set(target))
    hit = sum(1 for k in ks if comp[k] * target[k] > 0)
    wtxt = " · ".join(f"{m[0]}(lag{m[2]},{'+' if m[3] > 0 else '−'},"
                      f"w{abs(m[4])/tot*100:.0f}%)" for m in ms)
    print(f"  {title:<22} corr={cc:+.3f} (n={n}) · 적중률 {hit}/{len(ks)}"
          f" = {hit/len(ks)*100:.0f}%")
    print(f"      구성: {wtxt}")


def eval_combo_fixed(title, members, target, fixed_name, fixed_w=POLICY_W):
    """fixed_name 성분은 가중 고정(fixed_w), 나머지가 (1−fixed_w)를 |corr| 비례 분배."""
    ms = []
    for nm, z, lag, sign in members:
        c, n = pearson(lag_shift(z, lag), target)
        if c is None:
            print(f"  {title}: '{nm}' lag={lag} 표본 부족 — 생략")
            return
        ms.append((nm, z, lag, sign, c))
    rest = [m for m in ms if m[0] != fixed_name]
    tot = sum(abs(m[4]) for m in rest) or 1e-9
    comp = {}
    for nm, z, lag, sign, c in ms:
        w = fixed_w if nm == fixed_name else (1 - fixed_w) * abs(c) / tot
        for ym, v in lag_shift(z, lag).items():
            comp[ym] = comp.get(ym, 0.0) + sign * w * v
    comp = {k: v for k, v in comp.items() if k >= EVAL_START}
    cc, n = pearson(comp, target)
    ks = sorted(set(comp) & set(target))
    hit = sum(1 for k in ks if comp[k] * target[k] > 0)
    def _w(m):
        return fixed_w if m[0] == fixed_name else (1 - fixed_w) * abs(m[4]) / tot
    wtxt = " · ".join(f"{m[0]}(lag{m[2]},{'+' if m[3] > 0 else '−'},"
                      f"w{_w(m)*100:.0f}%)" for m in ms)
    print(f"  {title:<22} corr={cc:+.3f} (n={n}) · 적중률 {hit}/{len(ks)}"
          f" = {hit/len(ks)*100:.0f}%")
    print(f"      구성: {wtxt}")


def main():
    print("=" * 76)
    print("starts_probe — v4 착공 성분 재설계: KOSIS 서울+경기·레벨형·임대제외 실측")
    print(f"타깃 = 서울 매매지수(월간) 3개월 변화율 · 평가 {EVAL_START}~(v5 확장 창) · lag 0~{MAX_LAG}")
    print("=" * 76)

    # 타깃
    idx = kb_series_with_dates("index", {"월간주간구분코드": "01", "매물종별구분": "01",
                                         "매매전세코드": "01", "기간": "12"})
    chg3 = {}
    for ym, v in idx.items():
        p = idx.get(ym_add(ym, -3))
        if p:
            chg3[ym] = (v / p - 1) * 100
    target = {k: v for k, v in chg3.items() if k >= EVAL_START}
    print(f"\n[타깃] 매매지수 n={len(idx)} → 3M 변화율 n={len(target)}")
    if len(target) < MIN_OVERLAP:
        print("!! 타깃 부족 — 중단")
        return

    # 0) KOSIS 착공 표 탐색 — 검색 실패 시 국토부 후보 표 폴백(표명 검증 후 채택)
    print("\n[0] KOSIS 통합검색 (직접 REST · 15초 타임아웃 · 재시도)")
    cands, seen = [], set()
    for kw in ("주택 착공실적", "착공실적"):
        for org, tbl, nm in search_tables(kw):
            if (org, tbl) not in seen:
                seen.add((org, tbl))
                cands.append((org, tbl, nm))
        if cands:
            break                          # 첫 성공 검색어로 충분
    for org, tbl, nm in cands[:12]:
        print(f"  org={org} tbl={tbl} — {nm}")
    if not cands:
        print("  검색 불가 → 국토부 후보 표 폴백(표명에 착공 있을 때만 채택)")
        cands = [(o, t, "") for o, t in FALLBACK_TBLS]

    # 1) 구조 덤프 + 서울+경기 시계열 구축(첫 성공 표 채택)
    print("\n[1] 후보 표 구조 → 서울+경기 월별 착공 시계열")
    s_all = s_norent = None
    used_tbl = rent_col = None
    for org, tbl, nm in cands[:12]:
        tag = (' — ' + nm) if nm else ' (폴백 후보)'
        print(f"\n  ▶ org={org} tbl={tbl}{tag}")
        df = fetch_table(org, tbl)
        if df is None:
            continue
        regcol, pcol, vcol, nmcols, tblnm = dump_structure(df)
        if not nm and '착공' not in tblnm:
            print('    폴백 표명에 착공 없음 — 오표 채택 방지, 다음 후보')
            continue
        if not (regcol and pcol and vcol):
            print('    지역/시점/값 컬럼 인식 실패 — 다음 후보')
            continue
        s_all, _ = build_series(df, regcol, pcol, vcol, nmcols, exclude_rent=False)
        if len(s_all) < 100:
            print(f"    시계열 부족(n={len(s_all)}) — 다음 후보")
            s_all = None
            continue
        s_norent, rent_col = build_series(df, regcol, pcol, vcol, nmcols,
                                          exclude_rent=True)
        used_tbl = f"{org}/{tbl}"
        ks = sorted(s_all)
        print(f"    ✓ 채택 — 전체 n={len(s_all)} ({ks[0]}~{ks[-1]}) · "
              f"임대제외 {'n=' + str(len(s_norent)) + f' (분류={rent_col})' if s_norent else '불가(임대 분류 없음)'}")
        print(f"    표본: 최근 6개월 {[round(s_all[k]) for k in ks[-6:]]}")
        break
    if not s_all:
        print("!! 서울+경기 착공 구축 실패 — 구조 덤프로 표/분류 재지정 필요"
              " (S0·정책 섹션은 진행)")

    # 2) 산식 후보 lag 스캔
    print("\n" + "-" * 76)
    print("[2] 착공 산식 후보 lag 스캔 (3M 평활 → z → lag)")
    print("-" * 76)
    res = {}
    if s_all:
        res["S1 12M누적갭(서울+경기)"] = scan("S1 12M누적갭(서울+경기)",
                                         gap_vs_trailing_mean(roll_sum(s_all, 12), 60),
                                         target)
        res["S2 YoY(서울+경기)"] = scan("S2 YoY(서울+경기)", ma(yoy(s_all), 3), target)
    if s_all and s_norent:
        res["S3 12M누적갭(임대제외)"] = scan("S3 12M누적갭(임대제외)",
                                        gap_vs_trailing_mean(roll_sum(s_norent, 12), 60),
                                        target)
        res["S4 YoY(임대제외)"] = scan("S4 YoY(임대제외)", ma(yoy(s_norent), 3), target)
    # 기준선: 현행 ECOS 전국 YoY
    starts_ecos, scope = resolve_starts_levels()
    if starts_ecos:
        res[f"S0 현행 ECOS YoY({scope})"] = scan(f"S0 현행 ECOS YoY({scope})",
                                              ma(yoy(starts_ecos), 3), target)

    # 3) 조합 A 재평가 — 착공만 교체
    print("\n" + "-" * 76)
    print("[3] 조합 A 재평가 — 착공 성분 교체 비교(나머지 3지표 고정)")
    print("-" * 76)
    buy_m = weekly_to_monthly(kb_maktrnd_with_dates("01", "02", {"기간": "12"}))
    z_buy = zscore(ma({k: v - 100 for k, v in buy_m.items()}))
    jidx = kb_series_with_dates("index", {"월간주간구분코드": "01", "매물종별구분": "01",
                                          "매매전세코드": "02", "기간": "12"})
    z_jeon = zscore(ma(yoy(jidx)))
    mort = ecos_monthly("121Y006", "BECBLA0302")
    md6 = {}
    for ym, v in mort.items():
        p = mort.get(ym_add(ym, -6))
        if p is not None:
            md6[ym] = v - p
    z_mort = zscore(ma(md6))
    if not (z_buy and z_jeon and z_mort):
        print(f"!! 공통 3지표 확보 실패(buy={len(z_buy)} jeonse={len(z_jeon)} "
              f"mort={len(z_mort)}) — 조합 비교 생략")
        return
    base = [("매수우위", z_buy, 0, +1), ("전세지수YoY", z_jeon, 0, +1),
            ("주담대Δ6M", z_mort, 15, -1)]
    for name, r in res.items():
        if not r:
            continue
        sign = 1 if r["corr"] >= 0 else -1
        eval_combo(f"A + {name}", base + [(name, r["z"], r["lag"], sign)], target)
    # 4) 정책 레짐 더미 — KOSIS와 무관하게 항상 실행
    print("\n" + "-" * 76)
    print(f"[4] 정책 레짐 더미 — 민주=+1.0/보수=−0.3 · 고정가중 {POLICY_W:.0%}(사용자 스펙)")
    for a, b, v in REGIMES:
        print(f"      {a}~{b or '현재'} : {v:+.1f}")
    print("-" * 76)
    pol = scan("P 정권더미", policy_series(), target)
    if pol:
        psign = 1 if pol["corr"] >= 0 else -1
        # 짝지을 착공: |corr| 최고 후보(= v5 착공 스펙 후보와 동일 조건으로 비교)
        avail = [(k, v) for k, v in res.items() if v]
        s0nm = max(avail, key=lambda kv: abs(kv[1]["corr"]))[0] if avail else None
        if s0nm:
            r0 = res[s0nm]
            base4 = base + [(s0nm, r0["z"], r0["lag"],
                             1 if r0["corr"] >= 0 else -1)]
            eval_combo("A 기준(무정책)", base4, target)
            eval_combo("A+P 실측가중",
                       base4 + [("P정책", pol["z"], pol["lag"], psign)], target)
            for w in (0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50):
                eval_combo_fixed(f"A+P {w:.0%} 고정",
                                 base4 + [("P정책", pol["z"], pol["lag"], psign)],
                                 target, "P정책", fixed_w=w)
        else:
            eval_combo("3지표(착공無)", base, target)
            eval_combo("3지표+P 실측",
                       base + [("P정책", pol["z"], pol["lag"], psign)], target)
            for w in (0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50):
                eval_combo_fixed(f"3지표+P {w:.0%} 고정",
                                 base + [("P정책", pol["z"], pol["lag"], psign)],
                                 target, "P정책", fixed_w=w)

    print("\n판정 가이드: ① 착공 — 현행(S0) 대비 corr·적중률이 같거나 좋으면서 기저효과")
    print("없는 S1/S3(레벨형)이 있으면 채택(lag 24~36·부호 − 확인). ② 정책 — P 단독")
    print("corr과 'A+P 40%고정 vs 실측가중 vs 무정책' 3줄 비교로 40% 고정 여부 확정.")
    print("주의: 창 안 정권 전환 2회뿐 + 22~23 금리쇼크 중첩 → corr은 참고 증거.")
    print("=" * 76)


if __name__ == "__main__":
    main()
