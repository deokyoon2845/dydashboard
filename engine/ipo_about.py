"""IPO 종목 회사소개(about) 생성 — DART 공시문서 → Haiku 요약 → Supabase 캐시.

종목코드별로 '최초 1회만' DART 정기보고서(없으면 증권신고서)의 '사업의 내용'을
Haiku로 1~2문장 요약해 ipo_about 테이블에 저장한다. 이후엔 캐시를 읽어
재호출하지 않는다(신규 IPO만 새로 생성).

- enrich(recent): 최근상장 리스트의 각 항목에 about를 채운다(캐시 우선, 없으면 생성).
  ipo_collect.collect()가 호출하므로 IPO 수집 시 자동 보강된다.
- python -m engine.ipo_about : 최신 IPO 스냅샷을 읽어 about만 보강·저장(백필용).

키: DART_API_KEY · ANTHROPIC_API_KEY. 둘 중 하나라도 없으면 생성은 건너뛴다(캐시는 사용).
모델: claude-haiku-4-5.
※ 최초 1회 Supabase에 ipo_about 테이블 생성 필요(modules/db.py 상단 SQL).
"""

import io
import os
import re
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import requests

_DART = "https://opendart.fss.or.kr/api"
_LIST = f"{_DART}/list.json"
_CORPCODE = f"{_DART}/corpCode.xml"
_DOC = f"{_DART}/document.xml"
_UA = {"User-Agent": "Mozilla/5.0 (compatible; ipo-about/1.0)"}

HAIKU = "claude-haiku-4-5"
_MAX_DOC = 4000          # Haiku에 넣을 문서 발췌 길이
_MIN_DOC = 200           # 이보다 짧으면 요약 생략


def _dartk() -> str:
    return (os.environ.get("DART_API_KEY") or "").strip()


def _ak() -> str:
    return (os.environ.get("ANTHROPIC_API_KEY") or "").strip()


def _log(msg):
    print(f"[ipo_about] {msg}", flush=True)


def _digits6(x) -> str:
    return re.sub(r"[^0-9]", "", str(x or ""))[:6]


# ── DART corpCode.xml: 단축코드(6) → corp_code(8) ──
_cc_map = None


def _corpcode_map(key):
    global _cc_map
    if _cc_map is not None:
        return _cc_map
    _cc_map = {}
    if not key:
        return _cc_map
    try:
        r = requests.get(_CORPCODE, params={"crtfc_key": key}, headers=_UA, timeout=60)
        r.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(r.content))
        root = ET.fromstring(z.read(z.namelist()[0]))
        for c in root.iter("list"):
            sc = (c.findtext("stock_code") or "").strip()
            cc = (c.findtext("corp_code") or "").strip()
            if sc and len(sc) == 6 and cc:
                _cc_map[sc] = cc
        _log(f"DART corpCode 매핑 {len(_cc_map)}종목")
    except Exception as e:
        _log(f"corpCode 매핑 실패: {str(e)[:90]}")
    return _cc_map


def _latest_rcept(key, corp_code):
    """최근 2년 정기보고서(A) 우선, 없으면 증권신고서(C)의 최신 접수번호. 없으면 ''."""
    bgn = (date.today() - timedelta(days=730)).strftime("%Y%m%d")
    end = date.today().strftime("%Y%m%d")
    for ty in ("A", "C"):   # A=정기공시(사업·반기·분기) / C=발행공시(증권신고서)
        try:
            r = requests.get(_LIST, params={
                "crtfc_key": key, "corp_code": corp_code,
                "bgn_de": bgn, "end_de": end,
                "pblntf_ty": ty, "page_no": 1, "page_count": 100,
            }, headers=_UA, timeout=30)
            items = (r.json() or {}).get("list") or []
            if items:
                items.sort(key=lambda x: str(x.get("rcept_dt", "")), reverse=True)
                return items[0].get("rcept_no", "")
        except Exception:
            continue
    return ""


def _doc_text(key, rcept_no):
    """document.xml(zip) → 본문 평문 발췌('사업의 내용'/'회사의 개요' 우선). 실패 시 ''."""
    try:
        r = requests.get(_DOC, params={"crtfc_key": key, "rcept_no": rcept_no},
                         headers=_UA, timeout=60)
        r.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(r.content))
        names = [n for n in z.namelist() if n.lower().endswith(".xml")] or z.namelist()
        chunks = []
        for n in names:
            raw = z.read(n)
            txt = None
            for enc in ("utf-8", "cp949", "euc-kr"):
                try:
                    txt = raw.decode(enc)
                    break
                except Exception:
                    continue
            if txt is None:
                txt = raw.decode("utf-8", "ignore")
            chunks.append(txt)
        body = " ".join(chunks)
        body = re.sub(r"<[^>]+>", " ", body)
        body = re.sub(r"&[a-zA-Z#0-9]+;", " ", body)
        body = re.sub(r"\s+", " ", body).strip()
        body = body[:200000]
        for kw in ("사업의 내용", "사업의내용", "회사의 개요", "회사의개요", "회사의 개황", "회사개요"):
            i = body.find(kw)
            if i >= 0:
                return body[i:i + _MAX_DOC]
        return body[:_MAX_DOC]
    except Exception as e:
        _log(f"문서 조회 실패 rcept={rcept_no}: {str(e)[:80]}")
        return ""


def _summarize(text, name, ak):
    """공시 문서 발췌 → Haiku로 1~2문장 회사소개. 불충분하면 ''."""
    from anthropic import Anthropic
    client = Anthropic(api_key=ak)
    prompt = (
        f"다음은 '{name}'의 금융감독원 공시 문서 일부야.\n"
        "이 회사가 무슨 사업을 하는 회사인지 한국어 1~2문장(최대 90자)으로 간결히 요약해줘.\n"
        "- 제공된 내용에만 근거할 것(추측·과장 금지)\n"
        "- 회사명으로 문장을 시작하지 말고 사업 내용 위주로\n"
        "- 내용이 불충분하거나 사업 파악이 어려우면 빈 문자열만 출력\n"
        "- 따옴표·머리말·설명 없이 요약문만 출력\n\n"
        f"문서:\n{text}"
    )
    resp = client.messages.create(
        model=HAIKU, max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    out = (resp.content[0].text or "").strip().strip('"').strip()
    return out if 4 <= len(out) <= 200 else ""


def enrich(recent, dart_key=None, anthropic_key=None):
    """recent 각 항목의 about를 채운다. 캐시 우선, 없으면 DART+Haiku 생성 후 캐시."""
    if not recent:
        return recent
    dart_key = dart_key or _dartk()
    anthropic_key = anthropic_key or _ak()

    cache = {}
    db = None
    try:
        from modules import db as _db
        db = _db
        cache = db.load_ipo_about_map()
    except Exception as e:
        _log(f"about 캐시 로드 실패: {str(e)[:80]}")

    have_keys = bool(dart_key and anthropic_key)
    ccmap = _corpcode_map(dart_key) if have_keys else {}
    n_new = n_hit = 0

    for r in recent:
        code = _digits6(r.get("code"))
        if not code:
            continue
        if code in cache:
            if cache[code]:
                r["intro"] = r["about"] = cache[code]   # 뷰어는 intro를 읽는다
                n_hit += 1
            continue
        if not have_keys:
            continue
        cc = ccmap.get(code)
        if not cc:
            continue
        try:
            rcept = _latest_rcept(dart_key, cc)
            text = _doc_text(dart_key, rcept) if rcept else ""
            about = _summarize(text, r.get("name", ""), anthropic_key) if len(text) >= _MIN_DOC else ""
        except Exception as e:
            _log(f"{code} about 생성 실패(다음 실행 재시도): {str(e)[:80]}")
            continue   # 전송/네트워크 실패는 캐시하지 않음
        if db is not None:
            try:
                db.save_ipo_about(code, r.get("name", ""), about, source=rcept)
            except Exception:
                pass
        if about:
            r["intro"] = r["about"] = about         # 뷰어는 intro를 읽는다
            n_new += 1
        time.sleep(0.2)

    _log(f"회사소개 about: 캐시적중 {n_hit} · 신규생성 {n_new}")
    return recent


def main():
    try:
        from modules import db
    except Exception as e:
        print(f"[ipo_about] db 로드 실패: {e}", flush=True)
        return 1
    if not db.supabase_configured():
        print("[ipo_about] SUPABASE 미설정 — 건너뜀.", flush=True)
        return 1
    snap = db.load_ipo() or {}
    recent = snap.get("recent") or []
    if not recent:
        print("[ipo_about] 최근 IPO 스냅샷이 없음.", flush=True)
        return 1
    enrich(recent)
    try:
        db.save_ipo(recent=recent, upcoming=snap.get("upcoming") or [], asof=snap.get("asof"))
        print(f"[ipo_about] about 보강 저장 완료 · 최근 {len(recent)}종목", flush=True)
        return 0
    except Exception as e:
        print(f"[ipo_about] 저장 실패: {e}", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
