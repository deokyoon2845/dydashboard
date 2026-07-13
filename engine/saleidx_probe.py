"""KB 매매가격지수(서울) 장기 조회 프로브 — 백테스트 빨간선이 24.05부터만 그려지는 원인 규명.

배경: modules/realestate_cycle._render_macro_backtest 는 sale_m(월간 매매지수)이 24개 이상이면
그걸로 2020~ 궤적을 그리고, 부족하면 주간(sale) 폴백으로 내려간다. 화면상 빨간선이 딱
24.05(≈24개월)부터라, KB data-api priceIndex가 주간/월간 모두 '최근 ~2년'만 돌려주는 것으로
의심된다(sale_m이 ~24개월뿐 → 그 이전이 아예 없음).

이 프로브는 engine.realestate_collect 의 '실제 코드경로'(_kb_get/_kb_rows)로 KB priceIndex를
① 월간 파라미터 조합 ② 기간(period)·조회범위 파라미터 변형으로 호출해, 각 응답의
'유효 포인트 수 + 시작~끝 날짜'를 출력한다. → 2020.1까지 받는 조합을 찾으면 그 조합으로
collect_indicators()의 sale_m 호출만 교체하면 된다(다른 소스 불필요).

KB data-api는 인증키가 필요 없다. 저장/부수효과 없음 · 출력만.
GitHub Actions 수동 실행 전용(.github/workflows/saleidx_probe.yml → Run workflow).
"""

from engine.realestate_collect import _kb_get, _kb_rows, _KB_URL, _KB_SIDO


def _span(url_key, params):
    """KB 호출 → '서울행'의 유효값 개수 + 시작/끝 날짜 요약 문자열."""
    try:
        data = _kb_get(_KB_URL[url_key], {**params, "지역코드": _KB_SIDO["서울"]})
    except Exception as e:
        return f"ERR {type(e).__name__}: {str(e)[:90]}"
    rows = _kb_rows(data)
    if not rows:
        return "rows=0 (응답 없음 / resultCode≠11000 / 파라미터 거부)"
    pick = next((r for r in rows if r["name"] in ("서울", "서울특별시")), rows[0])
    dates = list(pick.get("dates", []))
    vals = [v for v in pick["vals"] if v is not None]
    d0 = dates[0] if dates else "?"
    dN = dates[-1] if dates else "?"
    return (f"서울행='{pick['name']}' · 유효값 {len(vals):>3}개 · "
            f"날짜 {len(dates):>3}개 · {d0} ~ {dN}")


def main():
    base = {"매물종별구분": "01", "매매전세코드": "01"}
    print("=" * 74)
    print("KB priceIndex 매매지수(서울) 장기조회 프로브")
    print("목표: 유효값이 ~72개(2020.1~) 나오는 '월간' 조합을 찾는다")
    print("=" * 74)

    print("\n[1] 월간(월간주간구분코드=01) · '기간' 파라미터 변형")
    for gigan in (None, "1", "2", "3", "5", "10", "20", "50", "100"):
        p = {**base, "월간주간구분코드": "01"}
        if gigan is not None:
            p["기간"] = gigan
        print(f"  기간={str(gigan):>5} → {_span('index', p)}")

    print("\n[2] 주간(월간주간구분코드=02) · '기간' 변형 (대조군 — 현재 sale 소스)")
    for gigan in (None, "1", "3", "10"):
        p = {**base, "월간주간구분코드": "02"}
        if gigan is not None:
            p["기간"] = gigan
        print(f"  기간={str(gigan):>5} → {_span('index', p)}")

    print("\n[3] 월간 · 조회범위로 쓰일 수 있는 기타 파라미터 후보")
    for extra in ({"조회구분": "2"}, {"기간구분": "3"}, {"시작년월": "202001"},
                  {"기준년월": "202001", "기간": "80"}, {"startYm": "202001"},
                  {"searchGbn": "2"}):
        p = {**base, "월간주간구분코드": "01", **extra}
        print(f"  {str(extra):<32} → {_span('index', p)}")

    print("\n[4] 참고: 월간중위가격(mdpsPrc)·평균가격(avgPrc)은 얼마나 길게 오나")
    for k in ("median", "avg"):
        try:
            data = _kb_get(_KB_URL[k], {**base})
            rows = _kb_rows(data)
        except Exception as e:
            print(f"  {k}: ERR {str(e)[:70]}")
            continue
        seoul = next((r for r in rows if "서울" in r.get("name", "")), None)
        if seoul:
            ds = list(seoul.get("dates", []))
            vs = [v for v in seoul["vals"] if v is not None]
            print(f"  {k}: 서울 유효값 {len(vs)}개 · "
                  f"{ds[0] if ds else '?'} ~ {ds[-1] if ds else '?'}")
        else:
            print(f"  {k}: 서울행 없음 (rows={len(rows)})")

    print("\n" + "=" * 74)
    print("판정: [1]에서 유효값이 ~60개 이상 나오는 '기간' 값을 찾으면 →")
    print("      collect_indicators()의 sale_m 호출에 그 '기간'만 추가하면 끝.")
    print("      전부 ~24개면 KB priceIndex는 2년벽 → KOSIS(부동산원) 장기시계열로")
    print("      전환하는 2차 probe가 필요(알려주면 그 방향으로 준비).")
    print("=" * 74)


if __name__ == "__main__":
    main()
