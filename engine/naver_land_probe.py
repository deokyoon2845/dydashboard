"""[엔진 프로브] 네이버부동산 '단지(complexNo)' API 사전 점검 — GitHub Actions(데이터센터 IP)에서 1회 실행.

complexNo 딥링크(new.land.naver.com/complexes/{no}) 리졸버 본체를 짜기 전에,
'클라우드에서 네이버부동산 내부 API가 살아있는지 + 어떻게 인증되는지'를 한 번만 확인한다.

배경(메모리 원칙): Naver는 Actions의 데이터센터 IP를 차단할 수 있고, new.land.naver.com/api/*
는 비공식 API라 최근 authorization: Bearer 토큰을 요구할 수 있다. 이 가정이 이 환경에서
실제로 어떤지 '그대로' 찍는다(침묵 실패 금지 — 왜 0건/차단인지 원인 문구를 남긴다).

점검 대상
  [0] 도달성            new.land.naver.com / m.land.naver.com 메인 (IP 차단 여부)
  [1] 지역 목록 API     api/regions/list?cortarNo=... (무인증 응답 여부 = 토큰 필요 판별)
  [2] 지역 드릴다운     서울 → 노원구 → 상계동 cortarNo 확인
  [3] 동별 단지 목록    api/regions/complexes?cortarNo={동} → complexNo+단지명 (핵심 경로)
  [4] 단지 개요         api/complexes/overview/{knownNo} (단지 상세 무인증 여부)
  [5] 검색 엔드포인트   api/search?keyword=... (있으면 1콜 리졸브 가능)

각 단계마다 HTTP status / 응답이 JSON인지(HTML이면 차단·리다이렉트 신호) / 핵심 키·샘플을 찍는다.
[3]에서는 실제 리졸브 흉내로 '주공5' → '상계주공5단지' → complexNo 매칭까지 시도한다.

사용: GitHub Actions → '네이버부동산 단지 API 프로브' → Run workflow → 로그의 [0]~[5] 확인.
키 불필요(내부 API는 헤더 기반). 토큰이 필요하면 [1]이 401/JSON error로 드러난다.
"""

import json
import re

import requests

try:
    requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]
except Exception:
    pass

_H = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Referer": "https://new.land.naver.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

# 리졸브 시나리오용 샘플(우리 데이터에서 나올 법한 약식명 포함)
_TARGETS = [
    ("서울", "1100000000", "노원구", "상계동", "주공5"),      # → 상계주공5단지
    ("서울", "1100000000", "강남구", "대치동", "은마"),        # → 은마
    ("서울", "1100000000", "송파구", "가락동", "헬리오시티"),  # → 송파헬리오시티
]
_KNOWN_COMPLEX_NO = "8928"   # LG개포자이 (개요 무인증 확인용)


def _bar():
    print("-" * 68)


def _norm(s):
    """비교용 정규화 — 공백·'단지/아파트' 제거."""
    return re.sub(r"\s+", "", (s or "")).replace("단지", "").replace("아파트", "")


def _get(url, params=None):
    """(status, is_json, payload_or_text_head, err)."""
    try:
        r = requests.get(url, params=params, headers=_H, timeout=20, verify=False)
    except Exception as e:
        return None, False, None, f"{type(e).__name__}: {e}"
    ct = r.headers.get("content-type", "")
    body = r.text or ""
    if "json" in ct or body[:1] in "{[":
        try:
            return r.status_code, True, r.json(), None
        except Exception as e:
            return r.status_code, False, body[:300], f"JSON 파싱 실패: {e}"
    return r.status_code, False, body[:300], "(HTML/텍스트 — 차단·리다이렉트·로그인벽 가능)"


# ── [0] 도달성 ──────────────────────────────────────────────────────
def probe_reach():
    print("[0] 도달성 — 메인 페이지 (Actions IP 차단 여부)")
    for u in ("https://new.land.naver.com/", "https://m.land.naver.com/"):
        try:
            r = requests.get(u, headers=_H, timeout=20, verify=False)
            print(f"    {u} → HTTP {r.status_code} · {len(r.text):,}B")
        except Exception as e:
            print(f"    {u} → ❌ {type(e).__name__}: {e}")
    _bar()


# ── [1] 지역 목록 API (무인증 응답 = 토큰 필요 판별) ────────────────
def probe_regions_root():
    print("[1] 지역 목록 API — api/regions/list?cortarNo=0000000000 (무인증 응답 여부)")
    st, isj, payload, err = _get(
        "https://new.land.naver.com/api/regions/list",
        {"cortarNo": "0000000000"})
    print(f"    HTTP {st} · JSON={isj}" + (f" · {err}" if err else ""))
    if isj and isinstance(payload, dict):
        rl = payload.get("regionList") or []
        print(f"    ✅ regionList {len(rl)}개 — 무인증 OK. 샘플: "
              + ", ".join(f'{x.get("cortarName")}({x.get("cortarNo")})' for x in rl[:4]))
        print("    → 토큰 불필요 신호. [2]~[3] 진행 가능.")
    else:
        print("    ⚠️ JSON 아님/에러 — authorization 토큰 요구 또는 IP 차단 가능.")
        print(f"    응답 머리: {payload}")
    _bar()
    return isj


# ── [2] 지역 드릴다운 (서울 → 구 → 동 cortarNo) ─────────────────────
def _find_child(cortarNo, name):
    st, isj, payload, err = _get(
        "https://new.land.naver.com/api/regions/list", {"cortarNo": cortarNo})
    if not (isj and isinstance(payload, dict)):
        return None, (st, err)
    for x in payload.get("regionList") or []:
        if x.get("cortarName") == name:
            return x.get("cortarNo"), None
    # 부분일치 폴백
    for x in payload.get("regionList") or []:
        if name in (x.get("cortarName") or ""):
            return x.get("cortarNo"), None
    return None, (st, "이름 미발견")


def probe_drill():
    print("[2] 지역 드릴다운 — 서울 → 구 → 동 cortarNo")
    results = {}
    for sido, sido_no, gu, dong, apt in _TARGETS:
        gu_no, e1 = _find_child(sido_no, gu)
        if not gu_no:
            print(f"    {gu} ❌ 구 코드 실패 {e1}")
            continue
        dong_no, e2 = _find_child(gu_no, dong)
        if not dong_no:
            print(f"    {gu} {dong} ❌ 동 코드 실패 {e2} (구={gu_no})")
            continue
        print(f"    {gu}({gu_no}) → {dong}({dong_no})  [찾을 단지: {apt}]")
        results[(gu, dong, apt)] = dong_no
    _bar()
    return results


# ── [3] 동별 단지 목록 → 리졸브 흉내(약식명 매칭) ───────────────────
def probe_complexes(drill):
    print("[3] 동별 단지 목록 — api/regions/complexes?cortarNo={동} → complexNo 매칭")
    if not drill:
        print("    (드릴 결과 없음 — [2] 실패로 스킵)")
        _bar()
        return
    for (gu, dong, apt), dong_no in drill.items():
        st, isj, payload, err = _get(
            "https://new.land.naver.com/api/regions/complexes",
            {"cortarNo": dong_no, "realEstateType": "APT", "order": ""})
        if not (isj and isinstance(payload, dict)):
            print(f"    {gu} {dong}: HTTP {st} · JSON={isj} · {err} · {payload}")
            continue
        cl = payload.get("complexList") or []
        want = _norm(apt)
        hit = [c for c in cl
               if want in _norm(c.get("complexName"))
               or _norm(c.get("complexName")) in want]
        print(f"    {gu} {dong}: 단지 {len(cl)}개 · '{apt}' 매칭 {len(hit)}건")
        for c in hit[:3]:
            print(f"        → complexNo={c.get('complexNo')} "
                  f"name={c.get('complexName')} "
                  f"세대={c.get('totalHouseholdCount') or c.get('totalHouseHoldCount')}")
        if not hit and cl:
            print("        (미매칭 — 목록 샘플: "
                  + ", ".join(f'{c.get("complexName")}/{c.get("complexNo")}'
                              for c in cl[:5]) + ")")
    _bar()


# ── [4] 단지 개요 (무인증 상세) ─────────────────────────────────────
def probe_overview():
    print(f"[4] 단지 개요 — api/complexes/overview/{_KNOWN_COMPLEX_NO} (무인증 상세 여부)")
    for path in (f"https://new.land.naver.com/api/complexes/overview/{_KNOWN_COMPLEX_NO}",
                 f"https://new.land.naver.com/api/complexes/{_KNOWN_COMPLEX_NO}"):
        st, isj, payload, err = _get(path)
        if isj and isinstance(payload, dict):
            nm = payload.get("complexName") or (payload.get("complexDetail") or {}).get("complexName")
            print(f"    {path.split('/api/')[1]} → HTTP {st} · complexName={nm}")
        else:
            print(f"    {path.split('/api/')[1]} → HTTP {st} · JSON={isj} · {err}")
    _bar()


# ── [5] 검색 엔드포인트(있으면 1콜 리졸브) ──────────────────────────
def probe_search():
    print("[5] 검색 엔드포인트 — api/search?keyword=... (있으면 1콜 리졸브)")
    for kw in ("상계주공5단지", "노원구 주공5", "은마"):
        st, isj, payload, err = _get(
            "https://new.land.naver.com/api/search", {"keyword": kw})
        head = None
        if isj and isinstance(payload, dict):
            head = list(payload.keys())
        print(f"    keyword='{kw}' → HTTP {st} · JSON={isj} · keys={head}"
              + (f" · {err}" if err else ""))
    _bar()


def main():
    print("=" * 68)
    print(" 네이버부동산 단지(complexNo) API 프로브 — Actions 데이터센터 IP")
    print("=" * 68)
    probe_reach()
    ok = probe_regions_root()
    drill = probe_drill() if ok else {}
    probe_complexes(drill)
    probe_overview()
    probe_search()
    print("요약: [1]이 JSON regionList면 무인증 드릴 경로 사용 가능 → 2단계 리졸버는")
    print("      서울/경기 구·동 드릴 + 동별 complexes 매칭 + Supabase 캐시로 구현.")
    print("      [1]이 HTML/401이면 토큰 필요 → 토큰 취득 or 통합검색 폴백로 방향 전환.")


if __name__ == "__main__":
    main()
