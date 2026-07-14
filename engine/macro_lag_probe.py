"""macro_lag_probe — 종합 강도 v4 설계용 lag·가중치 실측 프로브 (1회성 진단).

목적: 사이클 탭 '종합 강도'가 서울 매매지수와 유의미하게 동행하도록,
  ① 타깃을 매매지수 '레벨'이 아닌 '3개월 변화율'로 재정의하고
  ② 6개 입력지표(매수우위·주담대·M2·착공·전세가율·GDP)를 3M 평활+z-score 후
     lag 0~36개월을 스캔해 타깃과의 상관이 최대인 lag·부호를 실측하고
  ③ 착공 대안 산식(12개월 누적 착공의 장기평균 대비 갭 — 기저효과 없는 레벨형)을
     기존 YoY·3M평균과 비교하고 (가설: lag 24~36개월 · 음(-)의 상관 = 공급 압력)
  ④ |상관| 비례 가중으로 v4 후보 합성 → 상관·방향 적중률을 리포트한다.

실행: GitHub Actions에서 `python -m engine.macro_lag_probe` (ECOS_API_KEY 필요).
결과는 stdout — 로그를 보고 v4 산식(가중치·lag·부호)을 확정한 뒤 본 구현에 반영.
KB는 키 불필요. Supabase 불필요(읽기·쓰기 없음).
"""

import math
import os
import time
from datetime import date

# 엔진의 검증된 저수준 fetcher 재사용(KB 호출·ECOS 호출 규약 동일 보장)
from engine.realestate_collect import (_KB_URL, _KB_SIDO, _kb_get, _kb_rows,
                                       _ecos_series, _env_key)

START_TARGET = "202001"   # 타깃(매매지수 변화율) 평가 시작
MAX_LAG = 36              # 지표 lag 스캔 상한(개월)
SMOOTH_K = 3              # 지표 3개월 이동평균
MIN_OVERLAP = 24          # 상관 계산 최소 표본(개월)

# ECOS는 GitHub Actions 러너 지역에 따라 간헐 타임아웃(2026-07-13 1차 실행에서
# northcentralus 전멸 확인 — 매일 새벽 수집은 정상이므로 해외 IP 간헐 차단 추정).
# → 빈 응답이면 대기 후 재시도. 그래도 실패면 해당 지표만 생략(로그에 남음).
ECOS_TRIES = 3
ECOS_WAIT = 12            # 재시도 간 대기(초)


def _retry_ecos(fn, *args, label="", **kw):
    """fn(*args) 결과가 '비어있으면' ECOS_TRIES회까지 재시도. 실패 시 마지막 결과."""
    out = None
    for i in range(ECOS_TRIES):
        out = fn(*args, **kw)
        got = out[0] if isinstance(out, tuple) else out
        if got:
            return out
        if i < ECOS_TRIES - 1:
            print(f"    [ECOS 재시도 {i + 1}/{ECOS_TRIES - 1}] {label} — {ECOS_WAIT}s 대기")
            time.sleep(ECOS_WAIT)
    return out


# ── 월 산술·시계열 유틸 ─────────────────────────────────────────
def ym_add(ym, k):
    y, m = int(ym[:4]), int(ym[4:6])
    t = y * 12 + (m - 1) + k
    return f"{t // 12}{t % 12 + 1:02d}"


def ym_range(a, b):
    out, cur = [], a
    while cur <= b:
        out.append(cur)
        cur = ym_add(cur, 1)
    return out


def ma(series, k=SMOOTH_K):
    """{ym:v} → k개월 이동평균(가용분). 연속성 가정 없이 ym-k+1..ym 존재분 평균."""
    out = {}
    for ym in series:
        w = [series[ym_add(ym, -i)] for i in range(k) if ym_add(ym, -i) in series]
        if w:
            out[ym] = sum(w) / len(w)
    return out


def zscore(series):
    vals = list(series.values())
    if len(vals) < 8:
        return {}
    mu = sum(vals) / len(vals)
    sd = math.sqrt(sum((v - mu) ** 2 for v in vals) / len(vals)) or 1e-9
    return {k: (v - mu) / sd for k, v in series.items()}


def pearson(a, b):
    """두 {ym:v}의 공통 월 상관계수. 표본 부족 시 (None, n)."""
    keys = sorted(set(a) & set(b))
    n = len(keys)
    if n < MIN_OVERLAP:
        return None, n
    xa = [a[k] for k in keys]
    xb = [b[k] for k in keys]
    mx, my = sum(xa) / n, sum(xb) / n
    sx = math.sqrt(sum((v - mx) ** 2 for v in xa))
    sy = math.sqrt(sum((v - my) ** 2 for v in xb))
    if not sx or not sy:
        return None, n
    cov = sum((p - mx) * (q - my) for p, q in zip(xa, xb))
    return cov / (sx * sy), n


def lag_shift(series, lag):
    """지표를 lag개월 뒤로 민다: t 시점 값 = 원계열 t-lag 값."""
    return {ym_add(k, lag): v for k, v in series.items()}


def lag_scan(ind, target, max_lag=MAX_LAG):
    """lag 0..max_lag 스캔 → (best_lag, best_corr, 전체 [(lag,corr,n)])."""
    rows = []
    for L in range(max_lag + 1):
        c, n = pearson(lag_shift(ind, L), target)
        if c is not None:
            rows.append((L, c, n))
    if not rows:
        return None, None, []
    best = max(rows, key=lambda t: abs(t[1]))
    return best[0], best[1], rows


def fmt_scan(rows, top=5):
    top_rows = sorted(rows, key=lambda t: abs(t[1]), reverse=True)[:top]
    return " · ".join(f"lag{L:>2}:{c:+.2f}(n{n})" for L, c, n in top_rows)


# ── 데이터 수집(전부 날짜 포함) ─────────────────────────────────
def kb_series_with_dates(url_key, params, pick_names=("서울", "서울특별시")):
    """KB → {날짜str: float} (서울 시도행). 날짜는 월간 YYYYMM / 주간 YYYYMMDD."""
    data = _kb_get(_KB_URL[url_key], {**params, "지역코드": _KB_SIDO["서울"]})
    rows = _kb_rows(data)
    if not rows:
        return {}
    pick = next((r for r in rows if r["name"] in pick_names), rows[0])
    out = {}
    for d, v in zip(pick["dates"], pick["vals"]):
        if v is not None:
            out[str(d)] = float(v)
    return out


def kb_maktrnd_with_dates(menu, 월간주간, params=None):
    """maktTrnd(dict형 dataList) → {날짜: 지수}."""
    from engine.realestate_collect import _KB_MAKT_COL
    p = {"메뉴코드": menu, "월간주간구분코드": 월간주간, "지역코드": _KB_SIDO["서울"]}
    if params:
        p.update(params)
    data = _kb_get(_KB_URL["trend"], p)
    if not data:
        return {}
    dates = [str(d) for d in (data.get("날짜리스트") or [])]
    rows = data.get("데이터리스트") or []
    if not rows:
        return {}
    col = _KB_MAKT_COL.get(menu)
    pick = next((r for r in rows
                 if str(r.get("지역명", "")) in ("서울", "서울특별시")), rows[0])
    out = {}
    for d, v in zip(dates, pick.get("dataList") or []):
        if isinstance(v, dict):
            v = v.get(col)
        try:
            out[d] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def weekly_to_monthly(series):
    """{YYYYMMDD: v} → {YYYYMM: 월평균}."""
    buckets = {}
    for d, v in series.items():
        buckets.setdefault(d[:6], []).append(v)
    return {ym: sum(vs) / len(vs) for ym, vs in buckets.items()}


def quarterly_to_monthly(dates, vals):
    """('2024Q1', v) → 분기 3개월에 동일값 전개."""
    out = {}
    for t, v in zip(dates, vals):
        t = str(t).upper().replace(" ", "")
        if "Q" not in t:
            continue
        y, q = t.split("Q")
        m0 = (int(q) - 1) * 3 + 1
        for m in range(m0, m0 + 3):
            out[f"{y}{m:02d}"] = v
    return out


def ecos_monthly(stat, item, start="201501"):
    end = date.today().strftime("%Y%m")
    d, v = _retry_ecos(_ecos_series, stat, "M", item, start, end, n=900,
                       label=f"{stat}/{item}")
    return dict(zip(d, v))


def yoy(series):
    out = {}
    for ym, v in series.items():
        p = series.get(ym_add(ym, -12))
        if p:
            out[ym] = (v / p - 1) * 100
    return out


def roll_sum(series, k=12):
    out = {}
    for ym in series:
        w = [series[ym_add(ym, -i)] for i in range(k) if ym_add(ym, -i) in series]
        if len(w) == k:
            out[ym] = sum(w)
    return out


def gap_vs_trailing_mean(series, k=60):
    """t값의 (직전 k개월 평균 대비 갭%). 공급 '레벨'형 지표 — 기저효과 없음."""
    out = {}
    for ym in series:
        w = [series[ym_add(ym, -i)] for i in range(1, k + 1)
             if ym_add(ym, -i) in series]
        if len(w) >= k // 2:
            base = sum(w) / len(w)
            if base:
                out[ym] = (series[ym] / base - 1) * 100
    return out


def resolve_starts_levels():
    """ECOS 901Y103 주거용 착공 — 서울+경기 합산 레벨(실패 시 전국 폴백).
    엔진 _collect_macro_indicators와 동일한 해석 전략(ItemList → 콤보 시도)."""
    import requests
    key = _env_key("ECOS_API_KEY")
    end = date.today().strftime("%Y%m")

    def item_rows(stat):
        def _once():
            url = (f"https://ecos.bok.or.kr/api/StatisticItemList/{key}"
                   f"/json/kr/1/500/{stat}")
            try:
                r = requests.get(url, timeout=25)
                return (r.json().get("StatisticItemList") or {}).get("row") or []
            except Exception as e:
                print(f"  [starts] ItemList 실패: {e}")
                return []
        return _retry_ecos(_once, label=f"ItemList {stat}")

    rows = item_rows("901Y103")
    seoul = next((r.get("ITEM_CODE") for r in rows
                  if "서울" in (r.get("ITEM_NAME") or "")), None)
    gg = next((r.get("ITEM_CODE") for r in rows
               if "경기" in (r.get("ITEM_NAME") or "")), None)
    if seoul and gg:
        regs = {}
        for reg in (seoul, gg):
            for combo in (f"{reg}/I47ABA", f"I47ABA/{reg}", reg):
                d, v = _retry_ecos(_ecos_series, "901Y103", "M", combo,
                                   "201001", end, n=900, label=f"착공 {combo}")
                if len(v) >= 24:
                    regs[reg] = dict(zip(d, v))
                    break
        if len(regs) == 2:
            common = sorted(set.intersection(*[set(m) for m in regs.values()]))
            if len(common) >= 24:
                print(f"  [starts] 서울({seoul})+경기({gg}) 합산 n={len(common)}")
                return {t: sum(m[t] for m in regs.values()) for t in common}, "서울+경기"
    for combo in ("1/I47ABA", "2/I47ABA", "I47ABA"):
        d, v = _retry_ecos(_ecos_series, "901Y103", "M", combo,
                           "201001", end, n=900, label=f"착공 {combo}")
        if len(v) >= 24:
            print(f"  [starts] 전국 폴백 item={combo} n={len(v)}")
            return dict(zip(d, v)), "전국"
    return {}, None


# ── 메인 ────────────────────────────────────────────────────────
def main():
    today_ym = date.today().strftime("%Y%m")
    print("=" * 76)
    print("macro_lag_probe — 종합 강도 v4: lag·가중치 실측")
    print(f"타깃 = 서울 매매지수(월간) 3개월 변화율 · 평가 {START_TARGET}~{today_ym}")
    print(f"지표 처리 = {SMOOTH_K}M 이동평균 → z-score → lag 0~{MAX_LAG} 스캔")
    print("=" * 76)

    # ── 타깃: 서울 매매지수 월간(기간=12 장기) → 3M 변화율 ──
    idx = kb_series_with_dates("index", {"월간주간구분코드": "01", "매물종별구분": "01",
                                         "매매전세코드": "01", "기간": "12"})
    print(f"\n[타깃] 매매지수 월간 n={len(idx)} "
          f"({min(idx) if idx else '-'}~{max(idx) if idx else '-'})")
    chg3 = {}
    for ym, v in idx.items():
        p = idx.get(ym_add(ym, -3))
        if p:
            chg3[ym] = (v / p - 1) * 100
    target = {k: v for k, v in chg3.items() if k >= START_TARGET}
    print(f"[타깃] 3M 변화율 n={len(target)}")
    if len(target) < MIN_OVERLAP:
        print("!! 타깃 표본 부족 — 기간 파라미터/응답 확인 필요. 중단.")
        return

    end = date.today().strftime("%Y%m")
    inds = {}   # name → {'raw': {ym:v}, 'note': str}

    # ── 지표 수집(전부 장기·월간으로 정렬) ──
    # 1) 매수우위 — 주간(기간=10, 501주) → 월평균. 레벨-100 편차로 사용.
    buy_w = kb_maktrnd_with_dates("01", "02", {"기간": "10"})
    buy_m = weekly_to_monthly(buy_w)
    if len(buy_m) < 36:                      # 주간 장기 미지원 시 월간 직접
        buy_m = kb_maktrnd_with_dates("01", "01", {"기간": "10"})
    inds["매수우위(레벨-100)"] = {"raw": {k: v - 100 for k, v in buy_m.items()},
                               "note": f"n={len(buy_m)}"}

    # 2) 주담대 금리 — 레벨(%) 그대로(높을수록 부담 → 음의 상관 기대)
    mort = ecos_monthly("121Y006", "BECBLA0302")
    inds["주담대(레벨)"] = {"raw": mort, "note": f"n={len(mort)}"}
    # 2b) 주담대 6M 변화(pp) — 방향형 대안
    mchg = {}
    for ym, v in mort.items():
        p = mort.get(ym_add(ym, -6))
        if p is not None:
            mchg[ym] = v - p
    inds["주담대(6M변화)"] = {"raw": mchg, "note": f"n={len(mchg)}"}

    # 3) M2 YoY
    m2 = ecos_monthly("161Y006", "BBHA00")
    inds["M2(YoY)"] = {"raw": yoy(m2), "note": f"n={len(m2)}"}

    # 4) GDP 전기비(분기→월 전개)
    endQ = f"{date.today().year}Q{(date.today().month - 1) // 3 + 1}"
    dq, vq = _retry_ecos(_ecos_series, "200Y102", "Q", "10111", "2015Q1", endQ,
                         n=200, label="GDP 200Y102")
    gdp = quarterly_to_monthly(dq, vq)
    inds["GDP(전기비)"] = {"raw": gdp, "note": f"n={len(gdp)}"}

    # 5) 전세가율(월간, 기간=12) — 레벨
    jr = kb_series_with_dates("jratio", {"월간주간구분코드": "01",
                                         "매물종별구분": "01", "기간": "12"})
    inds["전세가율(레벨)"] = {"raw": jr, "note": f"n={len(jr)}"}
    # 5b) 전세지수 YoY — 대안(매매 선행 가설)
    jidx = kb_series_with_dates("index", {"월간주간구분코드": "01", "매물종별구분": "01",
                                          "매매전세코드": "02", "기간": "12"})
    inds["전세지수(YoY)"] = {"raw": yoy(jidx), "note": f"n={len(jidx)}"}

    # 6) 착공 — 현행(YoY 3M평균) vs 대안(12M누적의 60M평균 대비 갭)
    print("\n[수집] 착공 레벨 해석 중…")
    starts, scope = resolve_starts_levels()
    if starts:
        sy = ma(yoy(starts), 3)
        inds[f"착공 YoY·3M평균({scope})"] = {"raw": sy, "note": f"n={len(sy)}"}
        gap = gap_vs_trailing_mean(roll_sum(starts, 12), 60)
        inds[f"착공 12M누적 갭({scope})"] = {"raw": gap, "note": f"n={len(gap)}"}

    # ── lag 스캔 ──
    print("\n" + "-" * 76)
    print("[lag 스캔] 지표별 최적 lag·상관 (|corr| 상위 5개 lag 표시)")
    print("-" * 76)
    results = {}
    for name, d in inds.items():
        proc = zscore(ma(d["raw"]))
        if not proc:
            print(f"  {name:<24} 표본 부족({d['note']}) — 생략")
            continue
        bl, bc, rows = lag_scan(proc, target)
        if bl is None:
            print(f"  {name:<24} 공통 표본 부족 — 생략")
            continue
        results[name] = {"lag": bl, "corr": bc, "z": proc}
        print(f"  {name:<24} {d['note']:<8} best lag={bl:>2} corr={bc:+.3f}")
        print(f"      상위: {fmt_scan(rows)}")

    if not results:
        print("!! 스캔 결과 없음 — 수집 로그 확인.")
        return

    # ── v4 후보 합성: |corr| 비례 가중 · corr 부호 반영 · 최적 lag 적용 ──
    #   (착공은 두 산식 중 |corr| 큰 쪽 하나만 채택 — 중복 방지. 전세도 동일.)
    def pick_one(prefix):
        cands = {k: v for k, v in results.items() if k.startswith(prefix)}
        if not cands:
            return None
        return max(cands.items(), key=lambda kv: abs(kv[1]["corr"]))

    chosen = {}
    for k, v in results.items():
        if k.startswith(("착공", "전세", "주담대")):
            continue
        chosen[k] = v
    for prefix in ("착공", "전세", "주담대"):
        p = pick_one(prefix)
        if p:
            chosen[p[0]] = p[1]

    tot = sum(abs(v["corr"]) for v in chosen.values()) or 1e-9
    print("\n" + "-" * 76)
    print("[v4 후보] 채택 지표·가중치(|corr| 비례)·부호·lag")
    print("-" * 76)
    comp = {}
    for name, v in chosen.items():
        w = abs(v["corr"]) / tot
        sign = 1 if v["corr"] >= 0 else -1
        print(f"  {name:<24} lag={v['lag']:>2} corr={v['corr']:+.3f} "
              f"→ weight={w*100:4.1f}% sign={'+' if sign > 0 else '−'}")
        shifted = lag_shift(v["z"], v["lag"])
        for ym, val in shifted.items():
            comp.setdefault(ym, 0.0)
            comp[ym] += sign * w * val
    comp = {k: v for k, v in comp.items() if k >= START_TARGET}

    c, n = pearson(comp, target)
    hits = 0
    keys = sorted(set(comp) & set(target))
    for k in keys:
        if comp[k] * target[k] > 0:
            hits += 1
    print("\n" + "=" * 76)
    print(f"[평가] v4 후보 vs 타깃(3M 변화율) — corr={c:+.3f} (n={n}) · "
          f"방향 적중률={hits}/{len(keys)} = {hits/len(keys)*100:.0f}%"
          if c is not None else "[평가] 공통 표본 부족")
    print("판정 가이드: corr ≥ +0.5 & 적중률 ≥ 65% → v4 채택. 미달 시 지표 조합 재검토.")
    print("=" * 76)

    # ── 고정 스펙 조합 A/B/C 평가 (2차 실행 확정용 · 2026-07-14 추가) ─────
    #   자동선택의 경계 인공물(주담대 레벨 lag36 · 스캔 상한)과 단일 사이클
    #   과적합 의심(M2 lag26)을 사람이 고른 스펙으로 나란히 비교한다.
    #   가중치는 '해당 lag에서 실측된 |corr|' 비례 · 부호는 스펙에 고정.
    def _find(prefix):
        return next(((k, v) for k, v in results.items()
                     if k.startswith(prefix)), (None, None))

    def eval_combo(title, spec):
        """spec = [(지표 prefix, lag, sign)] → 합성 corr·적중률 출력."""
        members = []
        for prefix, lag, sign in spec:
            name, v = _find(prefix)
            if not name:
                print(f"  {title}: '{prefix}' 미확보 — 조합 평가 생략")
                return
            cc, nn = pearson(lag_shift(v["z"], lag), target)
            if cc is None:
                print(f"  {title}: '{name}' lag={lag} 표본 부족 — 조합 평가 생략")
                return
            members.append((name, lag, sign, cc, v["z"]))
        tot2 = sum(abs(m[3]) for m in members) or 1e-9
        cmp2 = {}
        for name, lag, sign, cc, z in members:
            w = abs(cc) / tot2
            for ym, val in lag_shift(z, lag).items():
                cmp2[ym] = cmp2.get(ym, 0.0) + sign * w * val
        cmp2 = {k: v for k, v in cmp2.items() if k >= START_TARGET}
        c2, n2 = pearson(cmp2, target)
        ks = sorted(set(cmp2) & set(target))
        h2 = sum(1 for k in ks if cmp2[k] * target[k] > 0)
        wtxt = " · ".join(f"{m[0]}(lag{m[1]},{'+' if m[2] > 0 else '−'},"
                          f"w{abs(m[3])/tot2*100:.0f}%)" for m in members)
        print(f"  {title:<14} corr={c2:+.3f} (n={n2}) · 적중률 {h2}/{len(ks)}"
              f" = {h2/len(ks)*100:.0f}%")
        print(f"      구성: {wtxt}")

    print("\n" + "-" * 76)
    print("[고정 스펙 비교] A 경제해석형(4) / B A+M2(5) / C 동행형 KB(2)")
    print("-" * 76)
    _A = [("매수우위", 0, +1), ("전세지수", 0, +1),
          ("착공 YoY", 29, -1), ("주담대(6M변화)", 15, -1)]
    eval_combo("A 경제해석형(4)", _A)
    eval_combo("B A+M2(5)", _A + [("M2", 26, -1)])
    eval_combo("C 동행형KB(2)", [("매수우위", 0, +1), ("전세지수", 0, +1)])
    print("=" * 76)


if __name__ == "__main__":
    main()
