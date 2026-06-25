"""[엔진 프로브] 주도주 데이터 소스 사전 점검 — GitHub Actions(데이터센터 IP)에서 1회 실행.

엔진 본체(전종목 스캔·점수화)를 짜기 전에, '클라우드에서 어떤 소스가 살아있는지'를
한 번만 확인한다. 메모리상 원칙: Naver·KRX는 Actions의 데이터센터 IP를 차단할 수 있고
(부동산 엔진에서 확인), data.go.kr/MOLIT/KOSIS/ECOS/KB 직접호출은 정상 동작한다.
→ 그 가정이 이 환경에서도 맞는지 실제로 검증한다.

점검 대상
  [1] data.go.kr 금융위 주식시세정보 getStockPriceInfo
        엔진 1순위 후보. 전종목 종가·등락률·시총·거래대금 + 종목별 일별 시계열을
        한 소스로 커버. 상대강도(시장수익률)는 유니버스 내부에서 계산하므로 지수 API 불필요.
  [2] Naver 시가총액 페이지 sise_market_sum   — Actions에서 살아있으면 대안 유니버스 소스
  [3] Naver siseJson 일별                      — Actions에서 살아있으면 대안 일봉 소스
  [4] Naver 업종분류 sise_group               — 섹터(업종) 라벨 소스(살아있는 쪽에서 사용)

각 소스에 대해 HTTP status / resultCode / totalCount / 샘플을 '그대로' 찍는다.
(침묵 실패 금지 — 0건이면 왜 0건인지 원인 문구를 남긴다.)

키: DATA_GO_KR_KEY → PUBLIC_DATA_API_KEY → MOLIT_API_KEY 순으로 찾는다.
    (Encoding/Decoding 키 무관 — unquote 후 requests가 재인코딩.)

사용: GitHub Actions → 'leaders 데이터 소스 프로브' → Run workflow → 로그 확인.
"""

import os
import re
from datetime import date, timedelta
from urllib.parse import unquote

import requests

try:
    requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]
except Exception:
    pass

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/124.0 Safari/537.36"}


def _bar():
    print("-" * 64)


def _key():
    """data.go.kr 서비스키 — (decoded_key, 출처이름) 또는 (None, None)."""
    for k in ("DATA_GO_KR_KEY", "PUBLIC_DATA_API_KEY", "MOLIT_API_KEY"):
        v = os.environ.get(k)
        if v and v.strip():
            return unquote(v.strip()), k
    return None, None


# ── [1] data.go.kr 금융위 주식시세정보 ──────────────────────────────

def probe_dataportal_price():
    print("[1] data.go.kr 금융위 주식시세정보 getStockPriceInfo (엔진 1순위 후보)")
    key, src = _key()
    if not key:
        print("  ✗ 키 없음 — DATA_GO_KR_KEY / PUBLIC_DATA_API_KEY / MOLIT_API_KEY 중 하나 필요")
        _bar()
        return
    print(f"  키 출처: {src}")
    url = ("https://apis.data.go.kr/1160100/service/"
           "GetStockSecuritiesInfoService/getStockPriceInfo")

    # (1-a) 종목 시계열 가능 여부: 삼성전자(005930) 최근 ~12일치 일별
    end = date.today()
    begin = end - timedelta(days=12)
    params = {
        "serviceKey": key, "resultType": "json",
        "numOfRows": "30", "pageNo": "1",
        "beginBasDt": begin.strftime("%Y%m%d"),
        "endBasDt": end.strftime("%Y%m%d"),
        "likeSrtnCd": "005930",
    }
    try:
        r = requests.get(url, params=params, timeout=20, headers=_UA, verify=False)
        print(f"  (1-a) 종목 일별 — HTTP {r.status_code}")
        _report_dataportal_body(r)
    except Exception as e:
        print(f"  (1-a) ✗ 요청 실패: {e}")

    # (1-b) 전종목 스냅샷 가능 여부: 최근 영업일을 찾아 basDt 단일일자 1페이지
    found = False
    for back in range(0, 8):
        d = (end - timedelta(days=back)).strftime("%Y%m%d")
        p2 = {"serviceKey": key, "resultType": "json",
              "numOfRows": "5", "pageNo": "1", "basDt": d}
        try:
            r2 = requests.get(url, params=p2, timeout=20, headers=_UA, verify=False)
            total = _total_count(r2)
            if total and total > 100:
                print(f"  (1-b) 전종목 스냅샷 — basDt={d} HTTP {r2.status_code} "
                      f"totalCount={total}")
                _report_dataportal_body(r2, sample_only=True)
                found = True
                break
        except Exception as e:
            print(f"  (1-b) basDt={d} ✗ {e}")
    if not found:
        print("  (1-b) ✗ 최근 8일 내 전종목 스냅샷을 못 받음 "
              "(서비스 미승인=resultCode 30 / 키오류 / 영업일 형식 확인)")
    _bar()


def _total_count(r):
    try:
        j = r.json()
        return int(j.get("response", {}).get("body", {}).get("totalCount") or 0)
    except Exception:
        m = re.search(r"<totalCount>(\d+)</totalCount>", r.text)
        return int(m.group(1)) if m else 0


def _report_dataportal_body(r, sample_only=False):
    txt = r.text
    try:
        j = r.json()
        header = j.get("response", {}).get("header", {})
        body = j.get("response", {}).get("body", {})
        rc, rmsg = header.get("resultCode"), header.get("resultMsg")
        total = body.get("totalCount")
        items = body.get("items", {}).get("item", [])
        if isinstance(items, dict):
            items = [items]
        if not sample_only:
            print(f"       resultCode={rc} ({rmsg}) totalCount={total} items={len(items)}")
        if items:
            it = items[0]
            print(f"       샘플: {it.get('basDt')} {it.get('itmsNm')} "
                  f"종가={it.get('clpr')} 등락률={it.get('fltRt')} "
                  f"시총={it.get('mrktTotAmt')} 거래대금={it.get('trPrc')} "
                  f"거래량={it.get('trqu')} 시장={it.get('mrktCtg')} "
                  f"코드={it.get('srtnCd')}")
            print("       ✓ 사용 가능")
        elif not sample_only:
            print("       ✗ items 비어있음 — resultCode/메시지로 원인 확인")
    except Exception:
        print("       JSON 파싱 실패 — 원문 일부:")
        print("       " + re.sub(r"\s+", " ", txt)[:280])


# ── [2] Naver 시가총액 페이지 ───────────────────────────────────────

def probe_naver_marketsum():
    print("[2] Naver 시가총액 sise_market_sum (Actions에서 살아있으면 대안)")
    url = "https://finance.naver.com/sise/sise_market_sum.naver?sosok=0&page=1"
    try:
        r = requests.get(url, timeout=12, headers=_UA)
        print(f"  HTTP {r.status_code} · 길이 {len(r.text)}")
        try:
            from lxml import html as lh
            doc = lh.fromstring(r.text)
            links = doc.xpath("//table[contains(@class,'type_2')]"
                              "//a[contains(@href,'/item/main')]")
            names = [a.text_content().strip() for a in links if a.text_content().strip()]
            print(f"  종목행 링크 {len(names)}개 · 샘플 {names[:5]}")
            print("  ✓ 사용 가능" if len(names) >= 10
                  else "  ✗ 행이 거의 없음 — 차단/리다이렉트 가능성")
        except Exception as e:
            print(f"  파싱 실패: {e} · 원문 일부: "
                  + re.sub(r'\s+', ' ', r.text)[:160])
    except Exception as e:
        print(f"  ✗ 요청 실패(차단 가능성): {e}")
    _bar()


# ── [3] Naver siseJson 일별 ─────────────────────────────────────────

def probe_naver_sisejson():
    print("[3] Naver siseJson 일별 (종목 일봉 · 005930)")
    end = date.today().strftime("%Y%m%d")
    start = (date.today() - timedelta(days=20)).strftime("%Y%m%d")
    url = ("https://api.finance.naver.com/siseJson.naver"
           f"?symbol=005930&requestType=1&startTime={start}"
           f"&endTime={end}&timeframe=day")
    try:
        r = requests.get(url, timeout=12, headers=_UA)
        print(f"  HTTP {r.status_code} · 길이 {len(r.text)}")
        import json as _json
        rows = _json.loads(r.text.strip().replace("'", '"'))
        body = [x for x in rows[1:] if x and len(x) >= 5]
        print(f"  일봉 {len(body)}개 · 마지막 {body[-1][:5] if body else '없음'}")
        print("  ✓ 사용 가능" if len(body) >= 5 else "  ✗ 데이터 없음 — 차단 가능성")
    except Exception as e:
        print(f"  ✗ 요청/파싱 실패(차단 가능성): {e}")
    _bar()


# ── [4] Naver 업종분류 ──────────────────────────────────────────────

def probe_naver_sector():
    print("[4] Naver 업종분류 sise_group (섹터 라벨 소스)")
    url = "https://finance.naver.com/sise/sise_group.naver?type=upjong"
    try:
        r = requests.get(url, timeout=12, headers=_UA)
        print(f"  HTTP {r.status_code} · 길이 {len(r.text)}")
        try:
            from lxml import html as lh
            doc = lh.fromstring(r.text)
            links = doc.xpath("//a[contains(@href,'sise_group_detail')]")
            names = [a.text_content().strip() for a in links if a.text_content().strip()]
            print(f"  업종 {len(names)}개 · 샘플 {names[:6]}")
            print("  ✓ 사용 가능" if len(names) >= 10 else "  ✗ 업종이 거의 없음")
        except Exception as e:
            print(f"  파싱 실패: {e}")
    except Exception as e:
        print(f"  ✗ 요청 실패(차단 가능성): {e}")
    _bar()


def main():
    print("=" * 64)
    print(" 주도주 데이터 소스 프로브 — 어느 소스가 Actions에서 살아있나")
    print("=" * 64)
    probe_dataportal_price()
    probe_naver_marketsum()
    probe_naver_sisejson()
    probe_naver_sector()
    print("판정 가이드:")
    print("  · [1]이 ✓ 면 → 엔진은 data.go.kr 단일 소스로 간다(권장).")
    print("  · [1]이 ✗ 인데 [2][3]이 ✓ 면 → 엔진을 Naver로 짠다.")
    print("  · [4]는 섹터 라벨용 — [1]로 가더라도 섹터는 ✓ 인 쪽에서 붙인다.")
    print("=" * 64)


if __name__ == "__main__":
    main()
