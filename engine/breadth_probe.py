"""breadth_probe.py — 등락 종목 수(상승/보합/하락) JSON 소스 탐색 probe.

시장 폭 탭에서 등락 종목 수가 안 잡히는 문제(네이버·다음 등락 페이지가 JS
렌더링 SPA로 바뀌어 정적 HTML 파싱 불가)를 해결하기 위한 1회성 진단 스크립트.

네이버/다음의 비공식 JSON API 여러 후보를 순서대로 때려보고, 응답 JSON을
재귀 탐색해서 "등락 종목 수처럼 보이는" 필드(키/경로/값)를 자동으로 뽑아준다.
이 로그를 검토해 정확한 엔드포인트 + 필드명을 확정한 뒤 market_breadth.py에 반영.

실행: GitHub → Actions → breadth probe → Run workflow → 로그 전체 복사.
(수집·저장 없음. 순수 진단용. 어떤 파일도 쓰지 않는다.)
"""

import json
import re
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

H_NAVER = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://m.stock.naver.com/",
}
H_DAUM = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://finance.daum.net/domestic",
}

# (라벨, URL, 헤더) — 등락 종목 수(상승/보합/하락)가 들어있을 만한 후보들.
# 코스피 위주로 구조를 찾고, 유력 엔드포인트만 코스닥도 확인한다.
CANDIDATES = [
    ("naver polling realtime index KOSPI",
     "https://polling.finance.naver.com/api/realtime/domestic/index/KOSPI", H_NAVER),
    ("naver m.stock index KOSPI basic",
     "https://m.stock.naver.com/api/index/KOSPI/basic", H_NAVER),
    ("naver m.stock index KOSPI integration",
     "https://m.stock.naver.com/api/index/KOSPI/integration", H_NAVER),
    ("naver m.stock index KOSPI marketValue",
     "https://m.stock.naver.com/api/index/KOSPI/marketValue", H_NAVER),
    ("naver m.stock index KOSPI upDown",
     "https://m.stock.naver.com/api/index/KOSPI/upDown", H_NAVER),
    ("naver m.stock domestic index KOSPI (page)",
     "https://m.stock.naver.com/api/index/KOSPI", H_NAVER),
    ("naver m.stock market-index domestic",
     "https://m.stock.naver.com/api/home/marketIndex/domesticIndexList", H_NAVER),
    # 다음 후보 (Referer 필요)
    ("daum market_index days KOSPI",
     "https://finance.daum.net/api/market_index/days?symbolCode=KOSPI&page=1&perPage=1&pagination=true",
     H_DAUM),
    ("daum quotes index domestic",
     "https://finance.daum.net/api/quote/index/domestic", H_DAUM),
    ("daum domestic sectors (rise/fall hint)",
     "https://finance.daum.net/api/domestic/sectors", H_DAUM),
    # 참고: 데스크톱 HTML — 지금도 등락 종목 수가 정적으로 있는지 최종 확인
    ("naver desktop sise_index KOSPI (HTML check)",
     "https://finance.naver.com/sise/sise_index.naver?code=KOSPI", H_NAVER),
]

# 코스닥도 확인할 유력 후보(라벨에 'integration'/'polling'/'basic' 포함 시)
KOSDAQ_ALSO = [
    ("naver polling realtime index KOSDAQ",
     "https://polling.finance.naver.com/api/realtime/domestic/index/KOSDAQ", H_NAVER),
    ("naver m.stock index KOSDAQ integration",
     "https://m.stock.naver.com/api/index/KOSDAQ/integration", H_NAVER),
]

# 등락 종목 수 후보로 의심할 키 이름(부분일치, 대소문자 무시)
KEY_HINTS = re.compile(
    r"(up|down|rise|fall|same|steady|hold|advance|decline|"
    r"increase|decrease|unchanged|상승|하락|보합|증가|감소|"
    r"count|cnt|number|num)",
    re.IGNORECASE,
)
# 오탐 줄이기: 값이 정수(문자열 포함)이고 0~5000 범위일 때만 후보로 본다.
_INT_RE = re.compile(r"^-?[\d,]+$")


def _is_countish(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return 0 <= v <= 5000
    if isinstance(v, str) and _INT_RE.match(v.strip()):
        try:
            return 0 <= int(v.replace(",", "")) <= 5000
        except Exception:
            return False
    return False


def _walk(obj, path=""):
    """(경로, 키, 값) 튜플을 재귀로 수집."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else str(k)
            if isinstance(v, (dict, list)):
                out.extend(_walk(v, p))
            else:
                out.append((p, str(k), v))
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:5]):  # 리스트는 앞 5개만
            p = f"{path}[{i}]"
            if isinstance(v, (dict, list)):
                out.extend(_walk(v, p))
            else:
                out.append((p, "", v))
    return out


def _scan_json(data):
    pairs = _walk(data)
    hits = [(p, k, v) for (p, k, v) in pairs
            if KEY_HINTS.search(p) and _is_countish(v)]
    return pairs, hits


def _dump(label, url, headers):
    print("\n" + "=" * 78)
    print(f"[{label}]\n{url}")
    try:
        r = requests.get(url, headers=headers, timeout=15)
    except Exception as e:
        print(f"  요청 실패: {e!r}")
        return
    ctype = r.headers.get("Content-Type", "")
    print(f"  status={r.status_code}  content-type={ctype}  len={len(r.text)}")
    body = r.text

    # JSON 시도
    parsed = None
    try:
        parsed = r.json()
    except Exception:
        # 앞뒤 콜백 래핑(jsonp) 제거 후 재시도
        m = re.search(r"\{.*\}|\[.*\]", body, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except Exception:
                parsed = None

    if parsed is not None:
        top = (list(parsed.keys())[:20] if isinstance(parsed, dict)
               else f"list(len={len(parsed)})")
        print(f"  JSON OK · top-level keys: {top}")
        pairs, hits = _scan_json(parsed)
        if hits:
            print(f"  ▼ 등락 종목 수 후보 필드 {len(hits)}개:")
            for p, k, v in hits[:40]:
                print(f"      {p} = {v!r}")
        else:
            print("  (등락 종목 수처럼 보이는 필드 못 찾음)")
        # 원문도 일부 남긴다(수동 확인용)
        raw = json.dumps(parsed, ensure_ascii=False)
        print(f"  raw(≤1400): {raw[:1400]}")
    else:
        # HTML/텍스트: 상승/보합/하락 주변 숫자 확인
        txt = re.sub(r"<[^>]+>", " ", body)
        txt = re.sub(r"\s+", " ", txt)
        print("  (JSON 아님 · HTML/텍스트) 상승/보합/하락 주변:")
        for lab in ("상승", "보합", "하락"):
            for m in list(re.finditer(lab, txt))[:3]:
                i = m.start()
                seg = txt[i:i + 40]
                print(f"      …{seg}…")
        print(f"  raw(≤600): {body[:600]!r}")


def main():
    print("### 등락 종목 수 JSON 소스 탐색 probe (breadth_probe) ###")
    for label, url, headers in CANDIDATES:
        _dump(label, url, headers)
    print("\n\n########## 코스닥 유력 후보 교차 확인 ##########")
    for label, url, headers in KOSDAQ_ALSO:
        _dump(label, url, headers)
    print("\n### probe 완료 — 위에서 status=200 + '후보 필드'가 뜬 엔드포인트를 확정 ###")


if __name__ == "__main__":
    main()
