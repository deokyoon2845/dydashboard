"""세대수 소스 프로브 v4 — REB 식별정보 odcloud(엔진 벌크 1순위 소스) 검증.

경위: 기본정보 API 전면 500(v2) → K-apt 벌크 XLSX는 데이터센터 IP 차단으로
커넥션 타임아웃(v3) → 공공데이터포털 원문파일(한국부동산원 '공동주택 단지
식별정보_기본정보', data.go.kr/15106861 · 전국 30만여 행)을 odcloud 자동변환
API로 조회하는 방식으로 전환. data.go.kr 인프라라 Actions에서 접근 가능하다.

  ★ 사전 1회: data.go.kr 로그인 → 15106861 파일데이터 페이지 → '오픈API' 탭
    → 활용신청(자동승인). 키는 기존 데이터포털 키 그대로.

  [1] odcloud 1페이지 표본 — 인증·스키마(컬럼명)·주소 형식 확인
  [2] 전 페이지 순회 — 수도권 파싱 건수·지역 수·대단지 표본(은마·파크리오·리센츠)
  [3] 기본정보 API 생존 재확인(1콜) — 살아나면 ②순위 폴백으로 자동 복귀

판독: [2]에서 '수도권 N천 단지'와 표본 세대수가 찍히면 성공 — 내일 크론부터
벌크 기반 재빌드. [1]이 401/403이면 활용신청 미완, 타임아웃이면 결과 공유.
실행: Actions → 'units 세대수 API 프로브 (수동)' → Run workflow.
"""

import os

import requests

_ODCLOUD = ("https://api.odcloud.kr/api/15106861/v1/"
            "uddi:46a20910-19aa-462e-ba09-e897b77d0e76")
_INFO = "apis.data.go.kr/1613000/AptBasisInfoServiceV3/getAphusBassInfoV3"


def _key():
    for k in ("MOLIT_API_KEY", "PUBLIC_DATA_API_KEY", "DATA_GO_KR_KEY"):
        v = os.environ.get(k)
        if v:
            return v.strip()
    return None


def main():
    key = _key()
    if not key:
        print("::error::데이터포털 키가 비어 있어요.")
        return
    uq = requests.utils.unquote(key)

    print("[1] odcloud 1페이지 표본(perPage=3)")
    try:
        r = requests.get(_ODCLOUD, params={"page": 1, "perPage": 3,
                                           "serviceKey": uq,
                                           "returnType": "JSON"}, timeout=60)
    except Exception as e:
        print(f"   → 요청 실패: {e}")
        return
    print(f"   → HTTP {r.status_code} · 본문 머리: "
          + (r.text or "")[:180].replace("\n", " "))
    if r.status_code in (401, 403):
        print("   ⛔ 인증 실패 — data.go.kr에서 15106861 파일데이터의 "
              "'오픈API' 활용신청(자동승인) 후 재실행하세요.")
        return
    if r.status_code != 200:
        print("   ⛔ 예상 밖 응답 — 결과를 공유해 주세요.")
        return
    data = r.json()
    rows = data.get("data") or []
    print(f"   → totalCount={data.get('totalCount')} · 표본 {len(rows)}행")
    if rows:
        print("   → 컬럼:", sorted(rows[0].keys()))
        print("   → 표본:", {k: rows[0].get(k) for k in
                             ("주소", "단지명_공시가격", "세대수") if k in rows[0]})

    print("\n[2] 전 페이지 순회 — 수도권 파싱")
    per, page, regions, samples = 5000, 0, {}, {}   # 307,407행 ≈ 62페이지
    targets = [("강남구", "은마"), ("송파구", "파크리오"), ("송파구", "리센츠")]
    while page < 70:
        page += 1
        rr = requests.get(_ODCLOUD, params={"page": page, "perPage": per,
                                            "serviceKey": uq,
                                            "returnType": "JSON"}, timeout=90)
        if rr.status_code != 200:
            print(f"   p{page} HTTP {rr.status_code} — 중단")
            break
        rows = (rr.json() or {}).get("data") or []
        for row in rows:
            addr = str(row.get("주소") or "")
            t = addr.split()
            if len(t) < 2 or t[0][:2] not in ("서울", "경기", "인천"):
                continue
            try:
                u = int(float(str(row.get("세대수") or 0)))
            except (ValueError, TypeError):
                continue
            if u < 100:
                continue
            regions[t[1]] = regions.get(t[1], 0) + 1
            names = " ".join(str(row.get(k) or "") for k in
                             ("단지명_공시가격", "단지명_건축물대장", "단지명_도로명주소"))
            for gu, nm in targets:
                if gu in addr and nm in names and (gu, nm) not in samples:
                    samples[(gu, nm)] = u
        if page % 10 == 0:
            print(f"   … p{page} 진행(누적 수도권 {sum(regions.values())}단지)")
        if len(rows) < per:
            break
    print(f"   → 수도권 {sum(regions.values())}단지(세대수 100+) · "
          f"{len(regions)}개 시군구 · {page}페이지")
    top = sorted(regions.items(), key=lambda x: -x[1])[:6]
    print("   → 상위 시군구:", ", ".join(f"{k} {v}" for k, v in top))
    for (gu, nm) in [t for t in targets]:
        print(f"   {gu} {nm} → 세대수 {samples.get((gu, nm), '미발견')}")

    print("\n[3] 기본정보 API 생존 재확인(1콜)")
    rr = requests.get(f"https://{_INFO}",
                      params={"serviceKey": uq, "kaptCode": "A13805002"}, timeout=15)
    print(f"   → HTTP {rr.status_code} · 본문: {(rr.text or '')[:120]}")
    print("\n프로브 끝 — [2] 정상이면 내일 크론에서 벌크 기반 유니버스 재빌드 완료.")


if __name__ == "__main__":
    main()
