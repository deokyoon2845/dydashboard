"""분양 단지 수집 — 한국부동산원 청약홈 APT 분양정보(data.go.kr/15098547).

엔드포인트: api.odcloud.kr ApplyhomeInfoDetailSvc/getAPTLttotPblancDetail
  · 응답: {"data":[{...}], "totalCount":..., ...}, 날짜는 'YYYY-MM-DD'
  · 주요 필드: PBLANC_NO(공고번호), HOUSE_MANAGE_NO(주택관리번호), PBLANC_URL(청약홈 공고 URL),
    HOUSE_NM(주택명), SUBSCRPT_AREA_CODE_NM(공급지역=서울/경기/인천…),
    HSSPLY_ADRES(공급위치), HOUSE_DTL_SECD_NM/HOUSE_SECD_NM(유형), TOT_SUPLY_HSHLDCO(공급세대),
    RCEPT_BGNDE/RCEPT_ENDDE(청약접수 시작/종료), MVN_PREARNGE_YM(입주예정월)

뷰어(modules/realestate.py)의 fetch_subscriptions와 같은 10-튜플 형식으로 반환한다:
  (단지명, 시군구, 주소, 유형, 공급세대, 청약시작'MM.DD', 청약종료'MM.DD', 입주예정'YY.MM',
   seoul|gg, 청약홈공고URL)
  ※ 10번째 url은 카드 클릭 시 청약홈 해당 공고로 이동시키는 링크. PBLANC_URL(청약홈 주소)이
    있으면 그대로, 없으면 주택관리번호+공고번호로 상세뷰 URL을 합성. 둘 다 없으면 빈 문자열
    (뷰어가 청약홈 APT 분양정보 목록으로 폴백).
  [호환] 과거 9-튜플 스냅샷도 뷰어가 그대로 렌더한다(url 없음 → 목록 폴백).

키: 실거래와 동일한 공공데이터포털 키(MOLIT_API_KEY 등)를 그대로 쓴다
    (같은 계정으로 '청약홈 분양정보 조회 서비스' 활용신청만 되어 있으면 됨).

────────────────────────────────────────────────────────────────────────────
[2026-06 개편] 무음 실패 제거 — 실거래(_request)와 동일하게:
  · 키를 unquote 후 params로 넘긴다(Encoding 키 이중 인코딩 방지).
  · HTTP status·odcloud 에러봉투(code/msg)를 그대로 읽어 '진짜 원인'을 표면화.
    (예전엔 except: break 로 조용히 빈 리스트 → 샘플 폴백, 원인 불명)
  · 공급지역 매칭을 '서울'/'서울특별시', '경기'/'경기도' 접두 허용으로 완화.
  · diagnose_subscriptions(): 단 1콜로 키·등록·네트워크 상태만 점검.
"""

from datetime import date, datetime, timedelta

import requests

from engine.realestate_collect import _get_key

SUB_API = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/getAPTLttotPblancDetail"
SUB_REGION = {"서울": "seoul", "경기": "gg"}
_TIMEOUT = 15


# ── 키 정규화 (실거래와 동일 규칙) ──────────────────────────────
def _skey():
    """공공데이터포털 키 → Decoding 형태로 정규화. unquote 후 requests가 재인코딩하게 둔다
       (Encoding 키를 그대로 넘기면 %2B→%252B 이중 인코딩으로 인증 실패)."""
    key = _get_key()
    if not key:
        raise RuntimeError("공공데이터포털 서비스키가 없어요 (MOLIT_API_KEY 등).")
    return requests.utils.unquote(key)


def _g(rec, *keys):
    """레코드에서 후보 키들을 순서대로 시도해 첫 유효 문자열 반환."""
    for k in keys:
        v = rec.get(k)
        if v not in (None, "", " ", "-"):
            return str(v).strip()
    return ""


def _area_region(area):
    """공급지역명 → 'seoul'|'gg'|''. '서울'/'서울특별시', '경기'/'경기도' 모두 허용."""
    a = (area or "").strip()
    if a.startswith("서울"):
        return "seoul"
    if a.startswith("경기"):
        return "gg"
    return ""


def _sigungu(addr):
    """공급위치 주소 → 시군구 (예: '서울특별시 서초구 방배동' → '서초구',
       '경기도 성남시 분당구' → '성남시'). 시·도 레벨 토큰은 건너뛴다."""
    sido_suffix = ("특별시", "광역시", "특별자치시", "특별자치도", "도")
    for tok in addr.split():
        if tok.endswith(sido_suffix):      # 서울특별시/경기도/세종특별자치시 등
            continue
        if tok.endswith(("구", "시", "군")) and len(tok) >= 2:
            return tok
    return ""


def _mmdd(s):
    """'YYYY-MM-DD'(또는 'YYYY.MM.DD') → 'MM.DD'."""
    try:
        p = s.replace(".", "-").split("-")
        return f"{int(p[1]):02d}.{int(p[2]):02d}"
    except Exception:
        return ""


def _movein(s):
    """'YYYYMM' / 'YYYY-MM' / 'YYYY.MM' → 'YY.MM'."""
    d = "".join(ch for ch in str(s) if ch.isdigit())
    return f"{d[2:4]}.{d[4:6]}" if len(d) >= 6 else ""


# 청약홈 APT 분양공고 상세뷰. 주택관리번호+공고번호로 직접 이동한다.
APPLYHOME_DETAIL = ("https://www.applyhome.co.kr/ai/aia/"
                    "selectAPTLttotPblancDetailView.do")


def _sub_url(rec):
    """레코드 → 청약홈 해당 공고 URL.
       1) PBLANC_URL이 청약홈(applyhome) 주소면 그대로
       2) 주택관리번호(HOUSE_MANAGE_NO)+공고번호(PBLANC_NO)로 상세뷰 합성
       3) PBLANC_URL이 일반 http면 그대로(폴백)
       4) 없으면 '' (뷰어가 청약홈 목록으로 폴백)."""
    direct = _g(rec, "PBLANC_URL")
    if direct.startswith("http") and "applyhome" in direct:
        return direct
    hmn = _g(rec, "HOUSE_MANAGE_NO")
    pno = _g(rec, "PBLANC_NO")
    if hmn and pno:
        return f"{APPLYHOME_DETAIL}?houseManageNo={hmn}&pblancNo={pno}"
    if direct.startswith("http"):
        return direct
    return ""


def _parse_date(s):
    try:
        return datetime.strptime(s.replace(".", "-")[:10], "%Y-%m-%d").date()
    except Exception:
        return None


# ── 저수준 호출 + 에러 표면화 ───────────────────────────────────
def _fetch_page(skey, page, per_page=1000):
    """odcloud 1페이지 → (data_list, error_or_None). 에러는 사람이 읽을 문구."""
    try:
        r = requests.get(SUB_API, timeout=_TIMEOUT, params={
            "page": page, "perPage": per_page, "serviceKey": skey})
    except Exception as e:
        return [], f"네트워크 오류: {e}"
    if r.status_code != 200:
        snippet = r.text[:160].replace("\n", " ")
        return [], f"HTTP {r.status_code} · {snippet}"
    try:
        j = r.json()
    except Exception as e:
        return [], f"JSON 파싱 실패: {e} · 앞부분 {r.text[:120]!r}"
    if "data" not in j:
        # odcloud 에러봉투(code/msg) 가능성
        msg = j.get("msg") or j.get("message") or str(j)[:160]
        return [], f"응답에 data 없음 · {msg}"
    return (j.get("data") or []), None


def diagnose_subscriptions(asof=None):
    """청약홈 분양정보 1콜 점검 → (status, message).
       status ∈ {OK, OK_EMPTY, NO_KEY, KEY_INVALID, NETWORK, API_ERROR}.
       OK/OK_EMPTY 면 수집 진행 가능, 나머지는 치명."""
    try:
        skey = _skey()
    except RuntimeError as e:
        return ("NO_KEY", str(e))
    data, err = _fetch_page(skey, 1, per_page=10)
    if err:
        up = err.upper()
        if ("HTTP 401" in up or "HTTP 403" in up or "등록" in err or "인증" in err
                or "NOT_REGISTERED" in up or "SERVICE" in up):
            return ("KEY_INVALID",
                    "청약홈 분양정보 서비스에 키가 미승인/무효예요. data.go.kr에서 "
                    "'한국부동산원_청약홈 분양정보 조회 서비스(15098547)' 활용신청 "
                    f"승인 여부와 키를 확인하세요. 원문: {err}")
        if "네트워크" in err or "TIMEOUT" in up or "TIMED OUT" in up:
            return ("NETWORK", f"청약홈 연결 실패(네트워크/IP). 원문: {err}")
        return ("API_ERROR", f"청약홈 응답 오류. 원문: {err}")
    if not data:
        return ("OK_EMPTY", "호출은 정상인데 결과가 0건이에요(키·연결은 정상).")
    return ("OK", f"정상 — 분양정보 {len(data)}건 확인. 수집을 진행할 수 있어요.")


# ── 분양 수집 ───────────────────────────────────────────────────
def collect_subscriptions(asof=None, regions=("서울", "경기"), recent_days=30, limit=60):
    """청약홈 APT 분양정보 → 서울/경기 · 청약종료가 최근 recent_days 이내~미래인 건만.

    반환: 뷰어 9-튜플 리스트(임박·진행 먼저).
    인증/등록 실패 등 '받지 못함'은 RuntimeError(뷰어에서 샘플 폴백 + 원인 표시).
    데이터는 받았으나 해당 지역·기간 매물이 없으면 빈 리스트(정상).
    """
    skey = _skey()
    asof = asof or date.today()
    cutoff = asof - timedelta(days=recent_days)

    rows, last_err = [], None
    for page in range(1, 6):
        data, err = _fetch_page(skey, page)
        if err:
            last_err = err
            break
        if not data:
            break
        rows += data
        if len(data) < 1000:
            break

    # 한 건도 못 받았는데 에러가 있었으면 → 원인을 올려보낸다(샘플 폴백 + 표면화).
    if not rows and last_err:
        raise RuntimeError(f"청약홈 분양정보를 받지 못했어요 · {last_err}")

    out = []
    for rec in rows:
        sd = _area_region(_g(rec, "SUBSCRPT_AREA_CODE_NM"))
        if not sd:
            continue
        end_d = _parse_date(_g(rec, "RCEPT_ENDDE", "SUBSCRPT_RCEPT_ENDDE"))
        if end_d is None or end_d < cutoff:
            continue
        nm = _g(rec, "HOUSE_NM")
        if not nm:
            continue
        addr = _g(rec, "HSSPLY_ADRES")
        gu = _sigungu(addr)
        typ = _g(rec, "HOUSE_DTL_SECD_NM", "HOUSE_SECD_NM") or "민영"
        try:
            units = int(float(str(rec.get("TOT_SUPLY_HSHLDCO", 0)).replace(",", "")))
        except (ValueError, TypeError):
            units = 0
        start_s = _mmdd(_g(rec, "RCEPT_BGNDE", "SUBSCRPT_RCEPT_BGNDE", "RCRIT_PBLANC_DE"))
        end_s = _mmdd(_g(rec, "RCEPT_ENDDE", "SUBSCRPT_RCEPT_ENDDE"))
        mv = _movein(_g(rec, "MVN_PREARNGE_YM"))
        url = _sub_url(rec)
        out.append((nm, gu, addr, typ, units, start_s, end_s, mv, sd, url, end_d))

    out.sort(key=lambda x: x[-1])          # 청약종료 가까운 순
    return [t[:-1] for t in out[:limit]]   # end_d 제거 → 10-튜플(…, url)


if __name__ == "__main__":
    print(diagnose_subscriptions())
    subs = collect_subscriptions()
    print(f"분양 {len(subs)}건")
    for s in subs[:10]:
        print(" ", s)
