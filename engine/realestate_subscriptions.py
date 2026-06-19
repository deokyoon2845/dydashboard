"""분양 단지 수집 — 한국부동산원 청약홈 APT 분양정보(data.go.kr/15098547).

엔드포인트: api.odcloud.kr ApplyhomeInfoDetailSvc/getAPTLttotPblancDetail
  · 응답: {"data":[{...}], "totalCount":..., ...}, 날짜는 'YYYY-MM-DD'
  · 주요 필드: PBLANC_NO(공고), HOUSE_NM(주택명), SUBSCRPT_AREA_CODE_NM(공급지역=서울/경기/인천…),
    HSSPLY_ADRES(공급위치), HOUSE_DTL_SECD_NM/HOUSE_SECD_NM(유형), TOT_SUPLY_HSHLDCO(공급세대),
    RCEPT_BGNDE/RCEPT_ENDDE(청약접수 시작/종료), MVN_PREARNGE_YM(입주예정월)

뷰어(modules/realestate.py)의 fetch_subscriptions와 같은 9-튜플 형식으로 반환한다:
  (단지명, 시군구, 주소, 유형, 공급세대, 청약시작'MM.DD', 청약종료'MM.DD', 입주예정'YY.MM', seoul|gg)

키: 실거래와 동일한 공공데이터포털 Decoding 키(MOLIT_API_KEY 등)를 그대로 쓴다
    (같은 계정으로 '청약홈 분양정보 조회 서비스' 활용신청만 되어 있으면 됨).
"""

from datetime import date, datetime, timedelta

from engine.realestate_collect import _get_key

SUB_API = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/getAPTLttotPblancDetail"
SUB_REGION = {"서울": "seoul", "경기": "gg"}


def _g(rec, *keys):
    """레코드에서 후보 키들을 순서대로 시도해 첫 유효 문자열 반환."""
    for k in keys:
        v = rec.get(k)
        if v not in (None, "", " ", "-"):
            return str(v).strip()
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


def _parse_date(s):
    try:
        return datetime.strptime(s.replace(".", "-")[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def collect_subscriptions(asof=None, regions=("서울", "경기"), recent_days=30, limit=60):
    """청약홈 APT 분양정보 → 서울/경기 · 청약종료가 최근 recent_days 이내~미래인 건만.

    반환: 뷰어 9-튜플 리스트(임박·진행 먼저). 실패 시 예외(뷰어에서 샘플 폴백).
    """
    import requests

    key = _get_key()
    if not key:
        raise RuntimeError("공공데이터포털 서비스키가 없어요 (MOLIT_API_KEY).")
    asof = asof or date.today()
    cutoff = asof - timedelta(days=recent_days)

    rows = []
    for page in range(1, 6):
        try:
            r = requests.get(SUB_API, timeout=15, params={
                "page": page, "perPage": 1000, "serviceKey": key})
            data = r.json().get("data", []) or []
        except Exception:
            break
        if not data:
            break
        rows += data
        if len(data) < 1000:
            break

    out = []
    for rec in rows:
        area = _g(rec, "SUBSCRPT_AREA_CODE_NM")
        if area not in regions:
            continue
        end_d = _parse_date(_g(rec, "RCEPT_ENDDE", "SUBSCRPT_RCEPT_ENDDE"))
        if end_d is None or end_d < cutoff:
            continue
        nm = _g(rec, "HOUSE_NM")
        sd = SUB_REGION.get(area, "")
        if not (nm and sd):
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
        out.append((nm, gu, addr, typ, units, start_s, end_s, mv, sd, end_d))

    out.sort(key=lambda x: x[-1])          # 청약종료 가까운 순
    return [t[:-1] for t in out[:limit]]   # end_d 제거 → 9-튜플


if __name__ == "__main__":
    subs = collect_subscriptions()
    print(f"분양 {len(subs)}건")
    for s in subs[:10]:
        print(" ", s)
