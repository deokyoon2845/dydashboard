"""[엔진] 증시 IPO 탭 데이터 수집 — 1차: 프로브(probe) 모드.

목적
  data.go.kr(금융위)·DART의 실제 응답 필드명을 확정하기 위한 진단 스크립트.
  아직 Supabase에 쓰지 않는다. 각 엔드포인트를 1회씩 호출해
  · 첫 아이템의 키 목록(field names)
  · 시가총액 상위 샘플 몇 건
  을 표준출력(Actions 로그)에 찍는다.
  이 출력으로 정확한 필드명을 확인한 뒤, 같은 파일에 collect()를 채워
  본 엔진으로 승격한다.

호출 방식
  GitHub Actions(workflow_dispatch)에서 `python -m engine.ipo_collect` 로 실행.
  키는 환경변수에서 읽는다(엔진 규칙):
    DATA_GO_KR_KEY  : data.go.kr 일반 인증키(Decoding). 없으면 MOLIT_API_KEY로 폴백.
    DART_API_KEY    : opendart 인증키.

설계 원칙(★silent-fail 방지)
  · 각 소스를 독립적으로 호출하고, 실패는 카테고리별로 분명히 출력한다.
  · 예외를 삼켜 빈 성공으로 위장하지 않는다(_section이 단계별로 OK/FAIL을 찍음).
"""

import json
import os
import sys
import traceback
from urllib.parse import urlencode

import requests

_UA = {"User-Agent": "Mozilla/5.0 (compatible; DYMonitoring-IPO/0.1)"}

# data.go.kr 금융위 서비스 베이스
_DATAGO = "https://apis.data.go.kr/1160100/service"
_SVC_PRICE = f"{_DATAGO}/GetStockSecuritiesInfoService/getStockPriceInfo"     # 주식시세정보
_SVC_KRXLIST = f"{_DATAGO}/GetKrxListedInfoService/getItemInfo"               # KRX상장종목정보
# 주식발행정보(_V2) — 오퍼레이션명은 프로브로 확인 후 확정. 우선 후보를 시도한다.
_SVC_ISSU_BASE = f"{_DATAGO}/GetStocIssuInfoService_V2"
_ISSU_ITEM_CANDS = ["getItemBasiInfo", "getItemBasicInfo"]                    # 종목기본정보(상장일)
_ISSU_LOCK_CANDS = ["getMandatoryDpsRtrInfo", "getMnatryH/oldDpsRtrInfo",
                    "getMandatoryDepositReturnInfo"]                         # 의무보호예수반환정보

# DART
_DART = "https://opendart.fss.or.kr/api"
_DART_LIST = f"{_DART}/list.json"
_DART_COMPANY = f"{_DART}/company.json"


def _datago_key() -> str:
    key = os.environ.get("DATA_GO_KR_KEY") or os.environ.get("MOLIT_API_KEY") or ""
    return key.strip()


def _dart_key() -> str:
    return (os.environ.get("DART_API_KEY") or "").strip()


def _section(title: str):
    print("\n" + "=" * 64)
    print(f"■ {title}")
    print("=" * 64)


def _get_json(url: str, params: dict, timeout: int = 12):
    """GET → JSON. serviceKey는 이미 디코딩 키이므로 requests가 인코딩하도록 그대로 전달."""
    r = requests.get(url, params=params, headers=_UA, timeout=timeout)
    r.raise_for_status()
    # data.go.kr은 에러 시 XML(혹은 평문)로 응답하기도 한다 → 먼저 텍스트로 확인.
    txt = r.text.strip()
    if txt.startswith("<"):
        raise RuntimeError(f"비-JSON 응답(아마 인증/파라미터 오류): {txt[:300]}")
    return r.json()


def _print_first_item_keys(label: str, items: list, n_sample: int = 5):
    if not items:
        print(f"  [{label}] items 비어 있음 (조건/날짜 확인 필요)")
        return
    print(f"  [{label}] 건수={len(items)}")
    print(f"  [{label}] 필드명: {sorted(items[0].keys())}")
    for it in items[:n_sample]:
        print("   ·", json.dumps(it, ensure_ascii=False)[:240])


# ── 1) 주식시세정보 : 시총·현재가·등락·상장주식수 ────────────────
def probe_price(key: str):
    _section("금융위 주식시세정보 (시총/현재가/등락/상장주식수)")
    # 최신 영업일은 모르니 basDt 미지정 + 최신순 가정. 시총 큰 종목부터 보려고 numOfRows만.
    params = {
        "serviceKey": key, "resultType": "json",
        "numOfRows": 10, "pageNo": 1,
    }
    print("  요청:", _SVC_PRICE, "?", urlencode({k: v for k, v in params.items() if k != "serviceKey"}))
    try:
        data = _get_json(_SVC_PRICE, params)
        body = (data.get("response") or {}).get("body") or {}
        items = ((body.get("items") or {}).get("item")) or []
        if isinstance(items, dict):
            items = [items]
        print("  totalCount =", body.get("totalCount"))
        _print_first_item_keys("price", items)
        print("  ※ 확인 포인트: 시가총액(mrktTotAmt?)·상장주식수(lstgStCnt?)·등락률(fltRt?)·"
              "종목명(itmsNm?)·단축코드(srtnCd?)·시장(mrktCtg?)·기준일(basDt?) 필드명")
    except Exception as e:
        print("  FAIL:", e)


# ── 2) KRX상장종목정보 : 법인등록번호(crno) 조인 ─────────────────
def probe_krxlist(key: str):
    _section("금융위 KRX상장종목정보 (법인등록번호 조인용)")
    params = {"serviceKey": key, "resultType": "json", "numOfRows": 5, "pageNo": 1}
    print("  요청:", _SVC_KRXLIST)
    try:
        data = _get_json(_SVC_KRXLIST, params)
        body = (data.get("response") or {}).get("body") or {}
        items = ((body.get("items") or {}).get("item")) or []
        if isinstance(items, dict):
            items = [items]
        _print_first_item_keys("krxlist", items)
        print("  ※ 확인 포인트: 법인등록번호(crno?)·단축코드(srtnCd?)·ISIN(isinCd?)·법인명(corpNm?)")
    except Exception as e:
        print("  FAIL:", e)


# ── 3) 주식발행정보 : 상장일 + 의무보호예수 ──────────────────────
def probe_issu(key: str):
    _section("금융위 주식발행정보 (상장일 + 의무보호예수)")
    # 종목기본정보(상장일) 오퍼레이션 후보를 순서대로 시도
    for op in _ISSU_ITEM_CANDS:
        url = f"{_SVC_ISSU_BASE}/{op}"
        params = {"serviceKey": key, "resultType": "json", "numOfRows": 3, "pageNo": 1}
        print(f"  [종목기본정보] 시도: {op}")
        try:
            data = _get_json(url, params)
            body = (data.get("response") or {}).get("body") or {}
            items = ((body.get("items") or {}).get("item")) or []
            if isinstance(items, dict):
                items = [items]
            _print_first_item_keys(f"issu/{op}", items)
            print("  ※ 확인 포인트: 상장일자(lstgDt? listDt?)·발행주식수·액면가·법인등록번호(crno?)")
            break
        except Exception as e:
            print(f"    {op} FAIL:", e)

    for op in _ISSU_LOCK_CANDS:
        url = f"{_SVC_ISSU_BASE}/{op}"
        params = {"serviceKey": key, "resultType": "json", "numOfRows": 3, "pageNo": 1}
        print(f"  [의무보호예수] 시도: {op}")
        try:
            data = _get_json(url, params)
            body = (data.get("response") or {}).get("body") or {}
            items = ((body.get("items") or {}).get("item")) or []
            if isinstance(items, dict):
                items = [items]
            _print_first_item_keys(f"lock/{op}", items)
            print("  ※ 확인 포인트: 반환일자(보호예수 해제일)·반환주식수·등록사유·법인등록번호")
            break
        except Exception as e:
            print(f"    {op} FAIL:", e)


# ── 4) DART : 향후 증권신고서(지분증권) + 기업개황 ───────────────
def probe_dart(key: str):
    _section("DART 공시검색 (증권신고서 지분증권 C001) + 기업개황")
    if not key:
        print("  SKIP: DART_API_KEY 없음")
        return
    # 최근 90일 증권신고서(지분증권) — 향후/최근 IPO 후보
    from datetime import date, timedelta
    end = date.today().strftime("%Y%m%d")
    bgn = (date.today() - timedelta(days=90)).strftime("%Y%m%d")
    params = {"crtfc_key": key, "bgn_de": bgn, "end_de": end,
              "pblntf_detail_ty": "C001", "page_no": 1, "page_count": 10}
    print("  요청:", _DART_LIST, f"(C001, {bgn}~{end})")
    sample_corp = None
    try:
        data = _get_json(_DART_LIST, params)
        print("  status =", data.get("status"), "/ message =", data.get("message"))
        items = data.get("list") or []
        _print_first_item_keys("dart/list", items)
        print("  ※ 확인 포인트: corp_code·corp_name·report_nm·rcept_dt·flr_nm(제출인=주관사 단서)")
        if items:
            sample_corp = items[0].get("corp_code")
    except Exception as e:
        print("  FAIL(list):", e)

    # 기업개황 — 회사소개용
    if sample_corp:
        params = {"crtfc_key": key, "corp_code": sample_corp}
        print("  요청:", _DART_COMPANY, f"(corp_code={sample_corp})")
        try:
            data = _get_json(_DART_COMPANY, params)
            print("  status =", data.get("status"))
            keys = sorted([k for k in data.keys() if k not in ("status", "message")])
            print("  [company] 필드명:", keys)
            print("   ·", json.dumps({k: data.get(k) for k in keys[:12]}, ensure_ascii=False)[:300])
            print("  ※ 확인 포인트: induty_code/업종·est_dt(설립일)·ceo_nm·stock_code·corp_name")
        except Exception as e:
            print("  FAIL(company):", e)


def probe():
    dk = _datago_key()
    print("DATA_GO_KR 키 길이:", len(dk), "(0이면 미설정)")
    print("DART 키 길이:", len(_dart_key()))
    if not dk:
        print("\n[중단] data.go.kr 키가 없어요. DATA_GO_KR_KEY 또는 MOLIT_API_KEY secret 확인.")
    else:
        probe_price(dk)
        probe_krxlist(dk)
        probe_issu(dk)
    probe_dart(_dart_key())
    print("\n" + "=" * 64)
    print("프로브 종료 — 위 '필드명' 줄들을 그대로 복사해서 덕윤이 붙여주면 본 엔진을 확정할게.")
    print("=" * 64)


def collect():
    """본 수집 — 프로브로 필드명 확정 후 채운다(현재는 미구현)."""
    raise NotImplementedError("프로브 출력 확인 후 구현 예정")


if __name__ == "__main__":
    mode = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("IPO_MODE", "probe")).lower()
    try:
        if mode == "probe":
            probe()
        else:
            collect()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
