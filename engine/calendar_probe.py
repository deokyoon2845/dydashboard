"""[프로브] 실적·IR 캘린더 소스 비교 — FnGuide 접근성 vs DART 공시 API.

GitHub Actions(데이터센터 IP)에서 아래 3가지를 검증한다. 판독법:

[1] FnGuide 접근성
    · HTTP 200 + '잠정실적' 키워드 + 데이터 행(<tr) 다수 → 서버렌더 파싱 가능
      (단, FnGuide 약관상 무단 DB화 금지 리스크는 별개로 남음)
    · 403/타임아웃/키워드 없음 → 차단 또는 XHR 렌더 → FnGuide 탈락 유력
    · 'XHR 후보' 로그에 api 경로가 찍히면 그 엔드포인트 추가 프로브 여지 있음

[2] DART 공정공시 검색 (list.json, pblntf_detail_ty=I002)
    · 최근 45일 '영업(잠정)실적' N건 / '기업설명회(IR)' M건이 잡히면 소스로 충분
    · status!=000 이면 키/파라미터 문제 → 로그의 message 확인

[3] DART IR 문서 개최일시 파싱 가능성 (document.xml)
    · 기업설명회 공시 원문에서 '일시' 주변 발췌가 날짜 형태로 찍히면
      미래 IR 일정을 달력에 올릴 수 있음 → DART 단독으로 3개 카테고리 커버 확정

키: DART_API_KEY (FnGuide 프로브는 키 불필요)
실행: python -m engine.calendar_probe
"""

import io
import os
import re
import zipfile
from datetime import date, timedelta

import requests

_UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/126.0.0.0 Safari/537.36")}

_FNG_URLS = [
    ("comp(구버전 ASP)", "https://comp.fnguide.com/SVO2/ASP/SVD_comp_calendar.asp"
     "?pGB=1&gicode=A005930&MenuYn=Y&NewMenuID=701&stkGb=701"),
    ("wcomp(신버전)", "https://wcomp.fnguide.com/Calendar/CompCalendar"
     "?c_id=AA&menu_type=01&cmp_cd=005930"),
]

_DART = "https://opendart.fss.or.kr/api"
_DART_LIST = f"{_DART}/list.json"
_DART_DOC = f"{_DART}/document.xml"

_EARN_PAT = re.compile(r"잠정실적|영업\s*\(잠정\)\s*실적|영업실적.*잠정")
_IR_PAT = re.compile(r"기업설명회|IR개최")


def _log(msg):
    print(f"[cal_probe] {msg}", flush=True)


def _dartk() -> str:
    return (os.environ.get("DART_API_KEY") or "").strip()


# ── [1] FnGuide 접근성 ─────────────────────────────────────────

def probe_fnguide():
    _log("=" * 60)
    _log("[1] FnGuide 접근성 프로브")
    for label, url in _FNG_URLS:
        try:
            r = requests.get(url, headers=_UA, timeout=20)
            html = r.text or ""
            n_tr = len(re.findall(r"<tr", html, re.I))
            has_earn = "잠정실적" in html
            has_ir = ("기업설명회" in html) or ("IR" in html)
            _log(f"  {label}: HTTP {r.status_code} · {len(html):,}자 · "
                 f"<tr {n_tr}개 · 잠정실적={'O' if has_earn else 'X'} · "
                 f"IR={'O' if has_ir else 'X'}")
            # 잠정실적 주변 발췌 (서버렌더 여부 판단용)
            if has_earn:
                flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "|", html))
                p = flat.find("잠정실적")
                _log(f"    발췌: …{flat[max(0, p - 30):p + 220]}…")
            # XHR/api 경로 후보 (데이터가 스크립트 로드형인 경우 대비)
            cands = sorted(set(re.findall(
                r"""["'](/[A-Za-z0-9_/\.]*(?:Calendar|calendar|Ajax|ajax|api)"""
                r"""[A-Za-z0-9_/\.\?=&%-]*)["']""", html)))[:8]
            if cands:
                _log(f"    XHR 후보: {cands}")
        except Exception as e:
            _log(f"  {label}: 실패 — {type(e).__name__}: {str(e)[:120]}")


# ── [2] DART 공정공시 검색 ─────────────────────────────────────

def probe_dart_list():
    _log("=" * 60)
    _log("[2] DART 공정공시(list.json) 프로브")
    key = _dartk()
    if not key:
        _log("  DART_API_KEY 없음 → 생략")
        return []
    bgn = (date.today() - timedelta(days=45)).strftime("%Y%m%d")
    end = date.today().strftime("%Y%m%d")
    earn, ir = [], []
    for cls in ("Y", "K"):              # 유가 / 코스닥
        page = 1
        while page <= 10:
            try:
                r = requests.get(_DART_LIST, params={
                    "crtfc_key": key, "bgn_de": bgn, "end_de": end,
                    "pblntf_detail_ty": "I002",      # 공정공시
                    "corp_cls": cls, "page_no": page, "page_count": 100,
                }, headers=_UA, timeout=30)
                data = r.json() or {}
            except Exception as e:
                _log(f"  {cls} p{page} 실패: {str(e)[:100]}")
                break
            if str(data.get("status")) != "000":
                _log(f"  {cls} p{page}: status={data.get('status')} "
                     f"msg={str(data.get('message'))[:80]}")
                break
            rows = data.get("list") or []
            for x in rows:
                rn = str(x.get("report_nm", ""))
                if _EARN_PAT.search(rn):
                    earn.append(x)
                elif _IR_PAT.search(rn):
                    ir.append(x)
            total = int(data.get("total_count") or 0)
            if page == 1:
                _log(f"  corp_cls={cls}: 공정공시 총 {total}건 (45일)")
            if page * 100 >= total or not rows:
                break
            page += 1
    _log(f"  → 잠정실적 매칭 {len(earn)}건 · 기업설명회(IR) 매칭 {len(ir)}건")
    for tag, lst in (("잠정실적", earn), ("IR", ir)):
        for x in lst[:5]:
            _log(f"    [{tag}] {x.get('rcept_dt')} {x.get('corp_name')} "
                 f"({x.get('stock_code') or '-'}) — {x.get('report_nm')}")
    return ir


# ── [3] DART IR 문서 개최일시 파싱 가능성 ─────────────────────

def probe_ir_doc(ir_rows):
    _log("=" * 60)
    _log("[3] DART IR 원문 개최일시 프로브")
    key = _dartk()
    if not key or not ir_rows:
        _log("  대상 없음 → 생략")
        return
    for x in ir_rows[:2]:
        rcept = x.get("rcept_no", "")
        try:
            r = requests.get(_DART_DOC, params={"crtfc_key": key, "rcept_no": rcept},
                             headers=_UA, timeout=40)
            r.raise_for_status()
            if r.content[:2] != b"PK":
                _log(f"  {x.get('corp_name')}: zip 아님(오류응답) — {r.text[:100]}")
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
            hits = []
            for lbl in ("개최일시", "일시", "개최일자", "일자"):
                p = flat.find(lbl)
                if p >= 0:
                    hits.append(f"{lbl}@{p}: {flat[p:p + 120]}")
                    break
            _log(f"  {x.get('corp_name')} ({x.get('report_nm')}):")
            _log(f"    {hits[0] if hits else '일시 라벨 못 찾음 — 앞부분: ' + flat[:120]}")
        except Exception as e:
            _log(f"  {x.get('corp_name')}: 실패 — {str(e)[:100]}")


def main():
    probe_fnguide()
    ir_rows = probe_dart_list()
    probe_ir_doc(ir_rows)
    _log("=" * 60)
    _log("프로브 완료 — 위 [1][2][3] 결과를 공유해주세요.")


if __name__ == "__main__":
    main()
