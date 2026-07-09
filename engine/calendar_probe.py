"""[프로브 v2] DART IR(기업설명회) 공시 분류 탐색 + 개최일시 파싱 검증.

v1 결과: 잠정실적은 공정공시(I002)에서 32건/45일 매칭 완료.
그러나 기업설명회(IR) 공시는 I002에서 0건 → 다른 분류에 있음. v2는 그 위치를 찾는다.

판독법:
[A] 분류별 스캔 — I001(수시)·I002(공정)·I003(시장조치 등)·거래소공시 전체(I)를 돌며
    report_nm에 '기업설명회'가 포함된 공시 건수를 분류별로 출력.
    · 어느 분류든 N건 잡히면 → 그 분류로 수집기 확정
    · 전 분류 0건이면 → 최근 14일에 IR 공시 자체가 없는 것(시즌 이슈) → 기간 늘려 재확인
[B] 개최일시 파싱 — [A]에서 찾은 IR 공시 최대 3건의 원문(document.xml)에서
    '일시' 라벨 주변 발췌 출력. 날짜 형태가 보이면 미래 IR 일정 달력 등재 가능 확정.

키: DART_API_KEY
실행: python -m engine.calendar_probe
"""

import io
import os
import re
import zipfile
from datetime import date, timedelta

import requests

_UA = {"User-Agent": "Mozilla/5.0 (compatible; DYMonitoring-CalProbe/2.0)"}
_DART = "https://opendart.fss.or.kr/api"
_DART_LIST = f"{_DART}/list.json"
_DART_DOC = f"{_DART}/document.xml"

_DAYS = 21                      # 탐색 기간(일)
_IR_PAT = re.compile(r"기업설명회|IR\s*개최")


def _log(msg):
    print(f"[cal_probe2] {msg}", flush=True)


def _dartk() -> str:
    return (os.environ.get("DART_API_KEY") or "").strip()


def _scan(key, bgn, end, detail=None, ty=None, max_pages=40):
    """list.json 페이지네이션 → (전체건수, IR매칭 리스트, 조기중단 여부)."""
    hits, total, page = [], 0, 1
    while page <= max_pages:
        params = {"crtfc_key": key, "bgn_de": bgn, "end_de": end,
                  "page_no": page, "page_count": 100}
        if detail:
            params["pblntf_detail_ty"] = detail
        elif ty:
            params["pblntf_ty"] = ty
        try:
            r = requests.get(_DART_LIST, params=params, headers=_UA, timeout=30)
            data = r.json() or {}
        except Exception as e:
            _log(f"    p{page} 실패: {str(e)[:80]}")
            break
        if str(data.get("status")) != "000":
            if page == 1:
                _log(f"    status={data.get('status')} msg={str(data.get('message'))[:70]}")
            break
        rows = data.get("list") or []
        total = int(data.get("total_count") or 0)
        for x in rows:
            if _IR_PAT.search(str(x.get("report_nm", ""))):
                hits.append(x)
        if page * 100 >= total or not rows:
            return total, hits, False
        page += 1
    return total, hits, page > max_pages    # True면 페이지 한도로 조기중단


def probe_ir_class():
    _log("=" * 60)
    _log(f"[A] DART IR 공시 분류 탐색 (최근 {_DAYS}일)")
    key = _dartk()
    if not key:
        _log("  DART_API_KEY 없음 → 중단")
        return []
    bgn = (date.today() - timedelta(days=_DAYS)).strftime("%Y%m%d")
    end = date.today().strftime("%Y%m%d")

    found = []
    for label, kw in (("I001 수시공시", {"detail": "I001"}),
                      ("I002 공정공시", {"detail": "I002"}),
                      ("I003 시장조치·안내", {"detail": "I003"}),
                      ("I 거래소공시 전체", {"ty": "I"})):
        total, hits, cut = _scan(key, bgn, end, **kw)
        cut_s = " (페이지 한도 도달·부분 스캔)" if cut else ""
        _log(f"  {label}: 총 {total}건 중 IR 매칭 {len(hits)}건{cut_s}")
        for x in hits[:4]:
            _log(f"    · {x.get('rcept_dt')} {x.get('corp_name')} "
                 f"({x.get('stock_code') or '-'}) — {x.get('report_nm')}")
        if hits and not found:
            found = hits
    if not found:
        _log("  → 전 분류 IR 0건: 기간 내 IR 공시 자체가 없거나 명칭 상이."
             " 결과 공유해주면 기간 확대판으로 재확인할게요.")
    return found


def probe_ir_doc(ir_rows):
    _log("=" * 60)
    _log("[B] IR 원문 개최일시 파싱 검증")
    key = _dartk()
    if not key or not ir_rows:
        _log("  대상 없음 → 생략")
        return
    for x in ir_rows[:3]:
        rcept = x.get("rcept_no", "")
        try:
            r = requests.get(_DART_DOC, params={"crtfc_key": key, "rcept_no": rcept},
                             headers=_UA, timeout=40)
            r.raise_for_status()
            if r.content[:2] != b"PK":
                _log(f"  {x.get('corp_name')}: zip 아님 — {r.text[:90]}")
                continue
            z = zipfile.ZipFile(io.BytesIO(r.content))
            body = ""
            for nm in z.namelist():
                raw = z.read(nm)
                for enc in ("utf-8", "cp949", "euc-kr"):
                    try:
                        body += raw.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue
                if len(body) > 300_000:
                    break
            flat = re.sub(r"\s+", "", re.sub(r"<[^>]+>", " ", body))
            hit = ""
            for lbl in ("개최일시", "일시", "개최일자", "일자"):
                p = flat.find(lbl)
                if p >= 0:
                    hit = f"{lbl}@{p}: {flat[p:p + 140]}"
                    break
            _log(f"  {x.get('corp_name')} — {x.get('report_nm')}")
            _log(f"    {hit or ('일시 라벨 없음 — 앞부분: ' + flat[:140])}")
        except Exception as e:
            _log(f"  {x.get('corp_name')}: 실패 — {str(e)[:90]}")


def main():
    ir = probe_ir_class()
    probe_ir_doc(ir)
    _log("=" * 60)
    _log("프로브 v2 완료 — [A][B] 결과를 공유해주세요.")


if __name__ == "__main__":
    main()
