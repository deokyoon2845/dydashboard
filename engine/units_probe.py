"""세대수(공동주택) API 프로브 — GitHub Actions에서 수동 1회 실행용.

유니버스가 _KNOWN_UNITS 폴백만으로 지어지는 사고(2026-07)의 원인 판별:
  [1] 단지 목록(getSigunguAptList3) — unquote 키 (엔진과 동일 방식)
  [2] 단지 목록 — raw 키 (기존 버그 재현: Encoding형 키면 이중 인코딩으로 실패)
  [3] 기본정보(getAphusBassInfoV3) — [1]에서 얻은 kaptCode로 세대수 확인

판독법:
  · [1] OK + [2] AUTH  → 원인은 '키 이중 인코딩'(이번 엔진 수정으로 해결 완료)
  · [1] AUTH(returnAuthMsg에 NOT_REGISTERED/DENIED 류) → 두 서비스 활용신청 미승인
        → data.go.kr 마이페이지에서 'AptListService3'·'AptBasisInfoServiceV3' 신청
  · [1] AUTH(LIMITED_NUMBER... ) → 일일 쿼터 초과 → 내일 재시도 또는 운영계정 전환
실행: Actions → 'units 세대수 API 프로브 (수동)' → Run workflow → 로그 확인.
"""

import json
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
    """Response → 사람이 읽을 한 줄 판정 + 본문 머리 300자."""
    head = (r.text or "")[:300].replace("\n", " ")
    verdict = f"HTTP {r.status_code}"
    body = None
    try:
        data = r.json()
        hdr = ((data or {}).get("response") or {}).get("header") or {}
        rc = str(hdr.get("resultCode") or "")
        verdict += f" · JSON · resultCode={rc or '?'} ({hdr.get('resultMsg')})"
        body = ((data or {}).get("response") or {}).get("body") or {}
        verdict += f" · totalCount={body.get('totalCount')}"
    except ValueError:
        try:
            import xmltodict
            x = xmltodict.parse(r.text)
            if "OpenAPI_ServiceResponse" in x:
                h = (x["OpenAPI_ServiceResponse"] or {}).get("cmmMsgHeader") or {}
                verdict += (f" · XML 게이트웨이 오류 · AUTH "
                            f"{h.get('returnReasonCode')}: {h.get('returnAuthMsg')}")
            else:
                hdr = ((x.get("response") or {}).get("header") or {})
                verdict += (f" · XML · resultCode={hdr.get('resultCode')} "
                            f"({hdr.get('resultMsg')})")
                body = (x.get("response") or {}).get("body") or {}
        except Exception as e:
            verdict += f" · 파싱 불가({e})"
    return verdict, head, body


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
        print("::error::MOLIT_API_KEY/PUBLIC_DATA_API_KEY/DATA_GO_KR_KEY 가 비어 있어요.")
        return
    enc_hint = "포함" if "%" in key else "없음"
    print(f"키 길이 {len(key)} · '%' 문자 {enc_hint} "
          f"(포함이면 Encoding형 — unquote 필요 케이스)")

    uq = requests.utils.unquote(key)
    base = {"type": "json", "numOfRows": 30, "pageNo": 1, "sigunguCode": "11680"}

    print("\n[1] 단지 목록 · unquote 키(엔진 수정판과 동일)")
    r1 = requests.get(f"https://{_LIST}", params={"serviceKey": uq, **base}, timeout=15)
    v, head, body1 = _describe(r1)
    print("   →", v)
    print("   본문:", head)

    print("\n[2] 단지 목록 · raw 키(기존 버그 재현)")
    r2 = requests.get(f"https://{_LIST}", params={"serviceKey": key, **base}, timeout=15)
    v, head, _ = _describe(r2)
    print("   →", v)
    print("   본문:", head)

    its = _items(body1)
    if its:
        smp = its[0]
        kc = str(smp.get("kaptCode") or "").strip()
        print(f"\n[3] 기본정보 · kaptCode={kc} ({smp.get('kaptName')})")
        r3 = requests.get(f"https://{_INFO}",
                          params={"serviceKey": uq, "type": "json", "kaptCode": kc},
                          timeout=15)
        v, head, body3 = _describe(r3)
        print("   →", v)
        item = (body3 or {}).get("item") or {}
        if isinstance(item, list):
            item = item[0] if item else {}
        print(f"   세대수(kaptdaCnt)={item.get('kaptdaCnt')} · "
              f"시공사={item.get('kaptBcompany')}")
        print("   본문:", head)
    else:
        print("\n[3] 생략 — [1]에서 단지 목록을 못 받아 kaptCode가 없어요.")

    print("\n프로브 끝 — 위 판독법(모듈 독스트링) 기준으로 [1]/[2] 결과를 비교하세요.")


if __name__ == "__main__":
    main()
