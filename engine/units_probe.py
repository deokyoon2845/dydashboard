"""세대수 소스 프로브 v3 — K-apt '벌크 XLSX' 경로 검증(엔진 세대수 1순위 소스 전환).

v2 결과(2026-07-07): 기본정보 API(getAphusBassInfoV3)가 파라미터·단지 무관 전면
HTTP 500 → 개별 조회를 포기하고 국토부 파일데이터(data.go.kr/15073271,
전국 18,000여 단지 · 주간 갱신 · 세대수+시공사)를 k-apt.go.kr에서 XLSX 1회
다운로드하는 방식으로 전환했다. 이 프로브는 그 경로가 GitHub Actions(데이터센터
IP)에서 실제로 동작하는지 확인한다 — 활용신청·API키 불필요.

  [1] XLSX 다운로드: HTTP 상태·크기·헤더 행 인식·수도권 파싱 건수
  [2] 대단지 표본 조회: 은마(강남구)·파크리오(송파구)·리센츠(송파구) 세대수
  [3] 기본정보 API 생존 재확인(1콜) — 살아나면 ②순위 폴백으로 자동 복귀

판독: [1]에서 '수도권 N단지'(N이 수천)와 [2] 세대수가 찍히면 성공 —
내일 크론부터 유니버스가 벌크 기반으로 정상 재빌드된다. [1]이 차단(403/타임아웃)
이면 k-apt도 데이터센터 IP 차단 목록에 추가된 것 → 결과 공유해 주면 다음 스텝.
실행: Actions → 'units 세대수 API 프로브 (수동)' → Run workflow.
"""

import io
import os

import requests

_XLSX = "https://www.k-apt.go.kr/web/board/goKaptBasicExcelDownload.do"
_INFO = "apis.data.go.kr/1613000/AptBasisInfoServiceV3/getAphusBassInfoV3"


def _key():
    for k in ("MOLIT_API_KEY", "PUBLIC_DATA_API_KEY", "DATA_GO_KR_KEY"):
        v = os.environ.get(k)
        if v:
            return v.strip()
    return None


def main():
    print("[1] K-apt 벌크 XLSX 다운로드")
    try:
        r = requests.get(_XLSX, timeout=300, verify=False,
                         headers={"User-Agent": "Mozilla/5.0"})
    except Exception as e:
        print(f"   → 요청 실패: {e}")
        return
    ctype = r.headers.get("Content-Type", "?")
    print(f"   → HTTP {r.status_code} · {len(r.content):,}B · Content-Type={ctype}")
    if r.status_code != 200 or len(r.content) < 10000:
        print("   본문 머리:", (r.text or "")[:200].replace("\n", " "))
        print("   ⛔ 다운로드 실패 — 차단/변경 여부 확인 필요")
        return

    import pandas as pd
    try:
        df = pd.read_excel(io.BytesIO(r.content), header=None, dtype=str)
    except Exception as e:
        print(f"   ⛔ XLSX 파싱 실패: {e}")
        return
    print(f"   → 파싱 OK: {len(df)}행 × {df.shape[1]}열")

    hdr_i = cols = None
    for i in range(min(8, len(df))):
        row = [str(v or "").strip() for v in df.iloc[i].tolist()]
        if any("단지명" in v for v in row) and any("세대수" in v for v in row):
            def _find(*keys):
                for j, v in enumerate(row):
                    if any(k == v or k in v for k in keys):
                        return j
                return None
            cols = {"sido": _find("시도"), "sgg": _find("시군구"),
                    "name": _find("단지명"), "units": _find("세대수"),
                    "builder": _find("시공사")}
            hdr_i = i
            print(f"   → 헤더 행 {i}: cols={cols}")
            print("   → 헤더 원문(앞 12열):", row[:12])
            break
    if hdr_i is None:
        print("   ⛔ 헤더 인식 실패 — 상위 3행:")
        for i in range(min(3, len(df))):
            print("     ", [str(v)[:14] for v in df.iloc[i].tolist()[:10]])
        return

    body = df.iloc[hdr_i + 1:]
    seoul = body[body.iloc[:, cols["sido"]].astype(str).str.startswith("서울", na=False)]
    gg = body[body.iloc[:, cols["sido"]].astype(str).str.startswith("경기", na=False)]
    ic = body[body.iloc[:, cols["sido"]].astype(str).str.startswith("인천", na=False)]
    print(f"   → 서울 {len(seoul)} · 경기 {len(gg)} · 인천 {len(ic)} / 전체 {len(body)}단지")

    print("\n[2] 대단지 표본 조회")
    for gu, name in [("강남구", "은마"), ("송파구", "파크리오"), ("송파구", "리센츠")]:
        sub = body[(body.iloc[:, cols["sgg"]].astype(str).str.contains(gu, na=False))
                   & (body.iloc[:, cols["name"]].astype(str).str.contains(name, na=False))]
        if len(sub):
            row = sub.iloc[0]
            b = row.iloc[cols["builder"]] if cols["builder"] is not None else "?"
            print(f"   {gu} {name} → 세대수 {row.iloc[cols['units']]} · 시공사 {b}")
        else:
            print(f"   {gu} {name} → 미발견(명칭 확인 필요)")

    print("\n[3] 기본정보 API 생존 재확인(1콜)")
    key = _key()
    if not key:
        print("   → 키 없음(생략)")
        return
    uq = requests.utils.unquote(key)
    rr = requests.get(f"https://{_INFO}",
                      params={"serviceKey": uq, "kaptCode": "A13805002"}, timeout=15)
    print(f"   → HTTP {rr.status_code} · 본문: {(rr.text or '')[:120]}")
    print("\n프로브 끝 — [1][2] 정상이면 내일 크론에서 벌크 기반 유니버스 재빌드 완료.")


if __name__ == "__main__":
    main()
