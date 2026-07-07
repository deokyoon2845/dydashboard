"""세대수(공동주택) API 프로브 v2 — 기본정보(getAphusBassInfoV3) HTTP 500 판별 매트릭스.

v1 결과(2026-07-07): 키 평문·목록(getSigunguAptList3) 정상(233단지) —
기본정보만 HTTP 500 'Unexpected errors'. 남은 용의자를 이 매트릭스로 가른다:
  [A] kaptCode만(여분 파라미터 0 — V1 예제 방식) : 성공하면 'type=json 등 여분
      파라미터가 500 유발' 확정 → 엔진 minimal=True 패치로 해결 완료
  [B] kaptCode + type=json (v1 프로브와 동일 — 재현 확인)
  [C] kaptCode + type=xml
  [D] 다른 kaptCode 3종(대단지 포함) × [A] 방식 : 전부 500이면 엔드포인트 장애,
      일부만 500이면 코드별 데이터 결함(_KNOWN_UNITS 폴백이 그 몫을 메움)
판독: [A] OK → 조치 불필요(엔진 패치로 끝). 전부 500 → K-apt 백엔드 장애(재시도)
      또는 상세 스펙 변경(결과 공유해 주면 다음 스텝 진행).
실행: Actions → 'units 세대수 API 프로브 (수동)' → Run workflow.
"""

import os

import requests

_LIST = "apis.data.go.kr/1613000/AptListService3/getSigunguAptList3"
_INFO = "apis.data.go.kr/1613000/AptBasisInfoServiceV3/getAphusBassInfoV3"


def _key():
    for k in ("MOLIT_API_KEY", "PUBLIC_DATA_API_KEY", "DATA_GO_KR_KEY"):
        v = os.environ.get(k)
        if v:
            return v.strip()
    return None


def _describe(r):
    """Response → 한 줄 판정(+ kaptdaCnt 추출 시도)."""
    head = (r.text or "")[:200].replace("\n", " ")
    cnt = None
    verdict = f"HTTP {r.status_code}"
    body = None
    try:
        data = r.json()
        hdr = ((data or {}).get("response") or {}).get("header") or {}
        verdict += f" · JSON · resultCode={hdr.get('resultCode')}"
        body = ((data or {}).get("response") or {}).get("body") or {}
    except ValueError:
        try:
            import xmltodict
            x = xmltodict.parse(r.text)
            if "OpenAPI_ServiceResponse" in x:
                h = (x["OpenAPI_ServiceResponse"] or {}).get("cmmMsgHeader") or {}
                verdict += (f" · XML AUTH {h.get('returnReasonCode')}: "
                            f"{h.get('returnAuthMsg')}")
            else:
                resp = x.get("response") or {}
                hdr = resp.get("header") or {}
                verdict += f" · XML · resultCode={hdr.get('resultCode')}"
                body = resp.get("body") or {}
        except Exception:
            verdict += " · 파싱 불가"
    if body:
        item = body.get("item") or {}
        if isinstance(item, list):
            item = item[0] if item else {}
        cnt = item.get("kaptdaCnt")
        if cnt is not None:
            verdict += f" · kaptdaCnt={cnt}"
    return verdict, head


def _items(body):
    it = ((body or {}).get("items") or {})
    if isinstance(it, dict):
        it = it.get("item", [])
    if isinstance(it, dict):
        it = [it]
    return it or []


def main():
    key = _key()
    if not key:
        print("::error::데이터포털 키가 비어 있어요.")
        return
    uq = requests.utils.unquote(key)

    # 목록에서 kaptCode 확보(강남구 233단지 — v1에서 정상 확인됨)
    r = requests.get(f"https://{_LIST}",
                     params={"serviceKey": uq, "type": "json",
                             "numOfRows": 300, "pageNo": 1, "sigunguCode": "11680"},
                     timeout=15)
    its = []
    try:
        its = _items(((r.json() or {}).get("response") or {}).get("body") or {})
    except Exception:
        pass
    if not its:
        print("::error::목록 조회 실패 — v1과 상황이 달라졌어요. 본문:",
              (r.text or "")[:200])
        return
    print(f"목록 OK — 강남구 {len(its)}단지 확보")

    first = its[0]
    # 대단지 우선 표본: 은마·개포 등 유명 단지가 있으면 포함
    famous = [it for it in its
              if any(k in str(it.get("kaptName") or "") for k in ("은마", "래미안", "자이"))]
    samples = ([first] + famous[:2] + its[10:12])[:5]

    kc0 = str(first.get("kaptCode") or "").strip()
    matrix = [
        ("A", "kaptCode만(여분 파라미터 0)", {"kaptCode": kc0}),
        ("B", "kaptCode + type=json(v1 재현)", {"kaptCode": kc0, "type": "json"}),
        ("C", "kaptCode + type=xml", {"kaptCode": kc0, "type": "xml"}),
    ]
    for tag, label, extra in matrix:
        rr = requests.get(f"https://{_INFO}",
                          params={"serviceKey": uq, **extra}, timeout=15)
        v, head = _describe(rr)
        print(f"\n[{tag}] {label} · {first.get('kaptName')}")
        print("   →", v)
        print("   본문:", head)

    print("\n[D] 다른 kaptCode × A방식(kaptCode만)")
    for it in samples[1:]:
        kc = str(it.get("kaptCode") or "").strip()
        rr = requests.get(f"https://{_INFO}",
                          params={"serviceKey": uq, "kaptCode": kc}, timeout=15)
        v, _ = _describe(rr)
        print(f"   {it.get('kaptName')}({kc}) → {v}")

    print("\n프로브 끝 — [A]가 OK(kaptdaCnt 표시)면 엔진 minimal 패치로 해결 완료, "
          "추가 조치 불필요.")


if __name__ == "__main__":
    main()
