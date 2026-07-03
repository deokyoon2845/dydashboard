"""[엔진 프로브 v2] 네이버부동산 '단지(complexNo)' API 확정 진단 — GitHub Actions에서 1회 실행.

v1 결과: new.land 메인은 200, 그러나 /api/* 는 전부 429(에러 봉투). 첫 호출부터 429라
'요청 과다'가 아니라 인증(Bearer 토큰)·세션쿠키 요구 또는 데이터센터 IP 프리블록으로 추정.

v2는 그걸 '확정'한다:
  (A) requests.Session 으로 메인페이지를 먼저 열어 쿠키 확보 → 그 세션으로 API 호출
  (B) 429면 실제 message/code 를 '그대로' 출력 (인증인지 레이트인지 판별)
  (C) 메인페이지 HTML/JS에서 Bearer 토큰(JWT) 추출 시도 → 있으면 authorization 헤더로 재시도
  (D) 호출 간 지연 + 429 백오프 재시도 (일시적 레이트 vs 하드블록 구분)

판정
  · 세션/토큰으로 200+regionList 나오면 → 리졸버 구현 가능(세션 or 토큰 방식)
  · 지연·세션·토큰 다 429면 → 내부 API는 Actions에서 불가 → 통합검색 폴백을 최종안으로 확정

사용: Actions → '네이버부동산 단지 API 프로브' → Run workflow → 로그의 (A)~(D) 확인. 키 불필요.
"""

import re
import time

import requests

try:
    requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]
except Exception:
    pass

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_BASE = "https://new.land.naver.com"
_TARGETS = [("서울", "1100000000", "노원구", "상계동", "주공5"),
            ("서울", "1100000000", "강남구", "대치동", "은마")]
_KNOWN_NO = "8928"


def _bar():
    print("-" * 68)


def _norm(s):
    return re.sub(r"\s+", "", (s or "")).replace("단지", "").replace("아파트", "")


def _session():
    """메인페이지를 먼저 열어 쿠키(NNB 등)를 확보한 세션."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": _UA,
        "Referer": _BASE + "/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
    })
    try:
        r = s.get(_BASE + "/", timeout=20, verify=False)
        print(f"    메인페이지 GET -> HTTP {r.status_code} · {len(r.text):,}B · "
              f"쿠키 {len(s.cookies)}개: {list(s.cookies.keys())}")
        return s, r.text
    except Exception as e:
        print(f"    메인페이지 GET ❌ {type(e).__name__}: {e}")
        return s, ""


def _extract_token(html):
    """메인페이지 HTML/JS에서 Bearer JWT 후보 추출(있으면)."""
    if not html:
        return None
    for pat in (r'[Aa]uthorization"\s*:\s*"Bearer\s+([A-Za-z0-9._\-]+)',
                r'"Bearer\s+([A-Za-z0-9._\-]{20,})"',
                r'\b(eyJ[A-Za-z0-9._\-]{30,})'):
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None


def _call(s, path, params=None, tag="", retry_429=True):
    """세션 호출 — status/JSON/메시지를 그대로 출력. 429면 3초 후 1회 백오프."""
    payload = None
    for attempt in (1, 2):
        try:
            r = s.get(_BASE + path, params=params, timeout=20, verify=False)
        except Exception as e:
            print(f"    {tag} ❌ {type(e).__name__}: {e}")
            return None, None
        ct = r.headers.get("content-type", "")
        body = r.text or ""
        payload = None
        if "json" in ct or body[:1] in "{[":
            try:
                payload = r.json()
            except Exception:
                payload = None
        msg = ""
        if isinstance(payload, dict):
            msg = f" · code={payload.get('code')} msg={payload.get('message')}"
        print(f"    {tag} -> HTTP {r.status_code}{msg}"
              + ("" if payload is not None else f" · (비JSON: {body[:120]})"))
        if r.status_code == 429 and retry_429 and attempt == 1:
            print("       └ 429 -> 3초 후 백오프 재시도")
            time.sleep(3.0)
            continue
        return r.status_code, payload
    return 429, payload


def main():
    print("=" * 68)
    print(" 네이버부동산 단지 API 프로브 v2 — 세션·토큰·429메시지 확정 진단")
    print("=" * 68)

    print("(A) 세션 쿠키 확보")
    s, html = _session()
    _bar()

    print("(B) 세션 쿠키로 지역목록 API 재시도 (429 메시지 확인)")
    st, payload = _call(s, "/api/regions/list", {"cortarNo": "0000000000"},
                        tag="regions/list(root)")
    ok_session = (st == 200 and isinstance(payload, dict)
                  and payload.get("regionList"))
    if ok_session:
        rl = payload["regionList"]
        print("    ✅ 200 + regionList "
              + ", ".join(f'{x.get("cortarName")}({x.get("cortarNo")})' for x in rl[:4]))
    _bar()

    print("(C) 메인페이지에서 Bearer 토큰 추출 -> authorization 헤더로 재시도")
    tok = _extract_token(html)
    ok_token = False
    if tok:
        print(f"    토큰 후보 발견(len={len(tok)}): {tok[:24]}…")
        s.headers["authorization"] = "Bearer " + tok
        time.sleep(1.0)
        st2, pl2 = _call(s, "/api/regions/list", {"cortarNo": "0000000000"},
                         tag="regions/list(+token)")
        ok_token = (st2 == 200 and isinstance(pl2, dict) and pl2.get("regionList"))
    else:
        print("    토큰 후보 없음 — 초기 HTML에 미포함(클라이언트 JS 동적 생성 가능성).")
    _bar()

    print("(D) 실제 리졸브 경로 시도 (되는 경우만 의미) — 드릴 + 동별 단지")
    if ok_session or ok_token:
        for sido, sido_no, gu, dong, apt in _TARGETS:
            time.sleep(1.0)
            _, pl = _call(s, "/api/regions/list", {"cortarNo": sido_no}, tag=f"{gu} 구목록")
            gu_no = None
            if isinstance(pl, dict):
                for x in pl.get("regionList") or []:
                    if x.get("cortarName") == gu:
                        gu_no = x.get("cortarNo")
            if not gu_no:
                print(f"       {gu} 코드 실패"); continue
            time.sleep(1.0)
            _, pd = _call(s, "/api/regions/list", {"cortarNo": gu_no}, tag=f"{dong} 동목록")
            dong_no = None
            if isinstance(pd, dict):
                for x in pd.get("regionList") or []:
                    if x.get("cortarName") == dong:
                        dong_no = x.get("cortarNo")
            if not dong_no:
                print(f"       {dong} 코드 실패"); continue
            time.sleep(1.0)
            _, pc = _call(s, "/api/regions/complexes",
                          {"cortarNo": dong_no, "realEstateType": "APT", "order": ""},
                          tag=f"{dong} 단지목록")
            if isinstance(pc, dict):
                cl = pc.get("complexList") or []
                want = _norm(apt)
                hit = [c for c in cl if want in _norm(c.get("complexName"))]
                for c in hit[:2]:
                    print(f"       ✅ '{apt}' -> complexNo={c.get('complexNo')} "
                          f"{c.get('complexName')}")
                if not hit:
                    print(f"       '{apt}' 미매칭 (목록 {len(cl)}개)")
    else:
        print("    (B)·(C) 모두 실패 -> 드릴 스킵. 내부 API 접근 불가 상태.")
        print("    참고: /api/search 검색 엔드포인트도 429였음(v1) — 동일 인증장벽.")
    _bar()

    print("판정:")
    if ok_session or ok_token:
        how = "세션쿠키" if ok_session else "토큰추출"
        print(f"    ✅ {how} 방식으로 200 응답 -> complexNo 리졸버 구현 가능.")
        print("       2단계: 이 방식 + 서울/경기 구·동 드릴 + Supabase engine_cache.")
    else:
        print("    ❌ 세션·토큰·백오프 모두 429 -> 내부 API는 Actions에서 사실상 불가.")
        print("       -> complexNo 딥링크 포기, 통합검색 폴백을 최종안으로 확정 권장.")


if __name__ == "__main__":
    main()
