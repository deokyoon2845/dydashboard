"""[엔진] 주도주 수집·점수화 — 전종목 스캔 → Supabase 저장용 페이로드 생성.

GitHub Actions(.github/workflows/leaders.yml)의 일일 스케줄 또는 수동 실행으로 돈다.
프로브(engine.leaders_probe) 결과 Naver가 Actions에서 정상 동작함을 확인 → 전 과정 Naver 사용.

데이터 경로 (모두 Naver · Actions에서 동작 확인됨)
  · 유니버스/시총/거래량/현재가 : finance.naver.com/sise/sise_market_sum (코스피=0·코스닥=1 페이징)
  · 업종(세분) + 구성종목        : finance.naver.com/sise/sise_group(_detail) type=upjong (79개)
  · 종목 일별 시계열             : api.finance.naver.com/siseJson (≈250영업일)
  · 시장수익률(상대강도)         : siseJson symbol=KOSPI/KOSDAQ

"주도" 점수 (종목, 0~100) = 가중합
  모멘텀 0.35 · 상대강도 0.20 · 추세지속성 0.20 · 유동성 0.15 · 신고가근접 0.10
하드 필터(=정밀스캔 대상): 시총 ≥ MCAP_MIN_EOK · 평균거래대금 ≥ TURNOVER_MIN_EOK ·
           우선주/스팩/리츠/ETF 제외 · 3개월 수익률 산출 가능한 시계열 길이.

★ 주도 게이트(is_leader) — '분석 대상'과 '주도주'를 구분하는 추가 관문.
  하드 필터만으론 횡보·하락 종목까지 모두 '후보'로 남아 매트릭스가 과밀해진다.
  주도주의 본질(시장보다 강하게·신고가 근처에서·추세를 타고·거래를 동반해 오름)을
  통과 조건으로 건다. GATE_PRESET('약'/'중'/'강')으로 강도 조절(기본 '중').
    · 약 : RS_3m>0 and mom_3m>0
    · 중 : 약 + high_ratio≥80 and above_ma60 and turnover≥50  (권장)
    · 강 : 중 + aligned(정배열) and high_ratio≥90 and turnover≥80
  폭주장 대비 상한 LEADER_CAP(점수순)으로 표시 개수 천장을 둔다.
  ※ 섹터 점수·폭(breadth)은 게이트와 무관하게 정밀스캔 전체로 계산(섹터 통계 보존).
     게이트는 stocks[].is_leader 플래그로만 표시되고, 뷰어가 이 플래그로 추려 보여준다.

주도 섹터(=업종) 점수 = 0.5·상위5종목 평균점수 + 0.3·breadth + 0.2·업종모멘텀순위
  breadth = 업종 내 (1개월 수익률>0 & 종가>20일선) 종목 비율. 구성종목 SECTOR_MIN_N개 미만 업종은
  '주도 섹터'로 집계하지 않되(노이즈), 소속 종목은 통합 리스트엔 그대로 남는다.

침묵 실패 금지: 단계별 수집 건수·실패율을 print 하고, 본체가 사실상 비면 저장하지 않는다(run에서 판정).
폴백: 만약 Naver가 대량 루프에서 차단되기 시작하면 실패율로 드러난다 → 그때 data.go.kr 금융위
       '주식시세정보' 활용신청 후 그 소스로 전환(현재는 403=미승인).
"""

import os
import re
import time
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

try:
    requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]
except Exception:
    pass

_KST = ZoneInfo("Asia/Seoul")
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/124.0 Safari/537.36"}

# ── 튜너블 ──────────────────────────────────────────────────────────
MCAP_MIN_EOK = 2000        # 시총 하한(억)
TURNOVER_MIN_EOK = 30      # 20일 평균 거래대금 하한(억)
SECTOR_MIN_N = 4           # '주도 섹터' 집계 최소 구성종목 수
HIST_CAL_DAYS = 380        # siseJson 요청 달력일(≈250영업일 → 52주 신고가 계산)
DEEP_SCAN_MAX = int(os.environ.get("LEADERS_MAX", "800"))   # 일별 시세 받을 최대 종목 수
SLEEP = float(os.environ.get("LEADERS_SLEEP", "0.06"))      # 호출 간 예의 슬립(초)
SECTOR_TOPK = 5            # 섹터 점수 = 상위 K 종목 평균
TOP_STOCKS_PER_SECTOR = 6  # 섹터에 묶어 저장할 종목 수(뷰어 표시용 상한)

WEIGHTS = {"mom": 0.35, "rs": 0.20, "trend": 0.20, "liq": 0.15, "high": 0.10}

# ── 주도 게이트(is_leader 판정) ──────────────────────────────────────
# '분석 대상(후보)'과 '실제 주도주'를 가르는 추가 관문. GATE_PRESET로 강도 조절.
#   약 : 시장 대비 강세 + 절대 상승만        (느슨 · 통과 多)
#   중 : 약 + 고점권 + 추세생존 + 유동성 상향 (권장)
#   강 : 중 + 정배열 + 신고가 임박 + 유동성↑↑ (엄격 · 통과 少)
# 환경변수 LEADERS_GATE 로도 덮어쓸 수 있다(예: LEADERS_GATE=강).
GATE_PRESET = os.environ.get("LEADERS_GATE", "중").strip()
_GATE_TABLE = {
    "약": {"rs_min": 0.0, "mom3_min": 0.0, "high_min": 0.0,
           "above_ma60": False, "aligned": False, "turnover_min": TURNOVER_MIN_EOK},
    "중": {"rs_min": 0.0, "mom3_min": 0.0, "high_min": 80.0,
           "above_ma60": True, "aligned": False, "turnover_min": 50.0},
    "강": {"rs_min": 0.0, "mom3_min": 0.0, "high_min": 90.0,
           "above_ma60": True, "aligned": True, "turnover_min": 80.0},
}
GATE = _GATE_TABLE.get(GATE_PRESET, _GATE_TABLE["중"])
LEADER_CAP = int(os.environ.get("LEADERS_CAP", "160"))  # 주도주 표시 상한(점수순) — 폭주장 안전장치


def _passes_gate(m, rs_3m):
    """주도 게이트 통과 여부. m=metrics(_metrics 결과), rs_3m=시장대비 3개월 초과수익."""
    if (rs_3m or 0) <= GATE["rs_min"]:
        return False
    if (m.get("ret_3m") or 0) <= GATE["mom3_min"]:
        return False
    if (m.get("high_ratio") or 0) < GATE["high_min"]:
        return False
    if GATE["above_ma60"] and not m.get("above_ma60"):
        return False
    if GATE["aligned"] and not m.get("aligned"):
        return False
    if (m.get("turnover_eok") or 0) < GATE["turnover_min"]:
        return False
    return True

# 세분 업종(79) → 색·그룹용 대표 카테고리 (substring 규칙 · 못 맞추면 '기타')
COARSE_RULES = [
    ("반도체", ["반도체"]),
    ("2차전지", ["전지", "배터리"]),
    ("자동차", ["자동차", "타이어", "부품"]),
    ("금융", ["은행", "증권", "보험", "금융", "지주", "신용"]),
    ("조선", ["조선"]),
    ("방산·항공", ["방위", "항공", "우주", "국방"]),
    ("기계·장비", ["기계", "장비", "전기장비", "전기제품"]),
    ("건설", ["건설", "건축", "토목"]),
    ("철강·소재", ["철강", "금속", "비철"]),
    ("화학·에너지", ["화학", "정유", "에너지", "가스", "석유"]),
    ("바이오·제약", ["제약", "바이오", "생명", "건강관리", "의료"]),
    ("IT·SW", ["소프트웨어", "인터넷", "it", "디스플레이", "전자장비", "통신장비", "하드웨어"]),
    ("게임·미디어", ["게임", "미디어", "엔터", "방송", "출판", "레저", "호텔"]),
    ("운송", ["운송", "항만", "물류", "해운", "택배"]),
    ("소비재·유통", ["식품", "음료", "유통", "화장품", "의류", "섬유", "가정", "백화점", "소매"]),
]


def _coarse(upjong: str) -> str:
    u = (upjong or "").lower()
    for grp, keys in COARSE_RULES:
        for k in keys:
            if k.lower() in u:
                return grp
    return "기타"


def _session():
    s = requests.Session()
    s.headers.update(_UA)
    return s


def _num(txt):
    """문자열에서 숫자만 추출(콤마·기호 제거). 실패 시 None."""
    if txt is None:
        return None
    m = re.search(r"-?\d[\d,]*\.?\d*", str(txt))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


# 제외 패턴: 우선주(…우/우B) · 스팩 · 리츠 · ETF/ETN 브랜드
_EXCL_NAME = re.compile(r"(우$|우B$|[0-9]우$|스팩|리츠|리얼티)")
_EXCL_ETF = re.compile(
    r"(KODEX|TIGER|PLUS|ARIRANG|KBSTAR|ACE|SOL|RISE|HANARO|KOSEF|TIMEFOLIO|ETN|"
    r"WON|UNICORN|KIWOOM|TIME|KoAct|1Q|BNK|마이다스|히어로즈|마이티|FOCUS|마이다스|"
    r"파워|에셋플러스|VITA|히어로|액티브|밸류업액티브)",
    re.IGNORECASE)


def _is_excluded(name: str, code: str) -> bool:
    if not name:
        return True
    if _EXCL_NAME.search(name) or _EXCL_ETF.search(name):
        return True
    # 보통주는 코드 끝이 0. 끝이 0이 아니면 우선주·신주인수권 등일 확률↑
    if code and not code.endswith("0"):
        return True
    return False


# ── 1) 유니버스 ─────────────────────────────────────────────────────

def fetch_universe(sess=None):
    """코스피+코스닥 전종목 기본정보. 반환: [{code,name,market,price,mcap_eok,volume}]."""
    from lxml import html as lh
    sess = sess or _session()
    out = {}
    for sosok, market in ((0, "KS"), (1, "KQ")):
        page, empty_streak = 1, 0
        while page <= 50:
            url = ("https://finance.naver.com/sise/sise_market_sum.naver"
                   f"?sosok={sosok}&page={page}")
            try:
                r = sess.get(url, timeout=12)
                doc = lh.fromstring(r.text)
            except Exception as e:
                print(f"[universe] sosok={sosok} page={page} 실패: {e}")
                break
            rows = doc.xpath("//table[contains(@class,'type_2')]/tbody/tr") \
                or doc.xpath("//table[contains(@class,'type_2')]//tr")
            added = 0
            for row in rows:
                a = row.xpath(".//a[contains(@href,'code=')]")
                if not a:
                    continue
                href = a[0].get("href") or ""
                m = re.search(r"code=(\d{6})", href)
                if not m:
                    continue
                code = m.group(1)
                name = a[0].text_content().strip()
                tds = row.xpath("./td")
                if len(tds) < 10:
                    continue
                price = _num(tds[2].text_content())
                mcap = _num(tds[6].text_content())       # 시가총액(억원)
                vol = _num(tds[9].text_content())        # 거래량(주)
                if not (code and name and price and mcap):
                    continue
                if _is_excluded(name, code):
                    continue
                out[code] = {"code": code, "name": name, "market": market,
                             "price": price, "mcap_eok": mcap, "volume": vol or 0}
                added += 1
            if added == 0:
                empty_streak += 1
                if empty_streak >= 2:
                    break
            else:
                empty_streak = 0
            page += 1
            time.sleep(SLEEP)
        print(f"[universe] {market} 누적 {len(out)}종목 (마지막 page={page})")
    return list(out.values())


# ── 2) 업종(세분) + 구성종목 ────────────────────────────────────────

def fetch_sector_map(sess=None):
    """종목코드 → 세분 업종명. 반환: {code: 업종명}. (Naver 업종분류 79개 크롤)"""
    from lxml import html as lh
    sess = sess or _session()
    code_to_upjong = {}
    try:
        r = sess.get("https://finance.naver.com/sise/sise_group.naver?type=upjong",
                     timeout=12)
        doc = lh.fromstring(r.text)
        links = doc.xpath("//a[contains(@href,'sise_group_detail')]")
    except Exception as e:
        print(f"[sector] 업종목록 실패: {e}")
        return code_to_upjong

    seen = []
    for a in links:
        href = a.get("href") or ""
        no = re.search(r"no=(\d+)", href)
        nm = a.text_content().strip()
        if not no or not nm:
            continue
        seen.append((no.group(1), nm))

    for no, upjong in seen:
        url = ("https://finance.naver.com/sise/sise_group_detail.naver"
               f"?type=upjong&no={no}")
        try:
            r = sess.get(url, timeout=12)
            doc = lh.fromstring(r.text)
            for a in doc.xpath("//a[contains(@href,'code=')]"):
                m = re.search(r"code=(\d{6})", a.get("href") or "")
                if m:
                    code_to_upjong.setdefault(m.group(1), upjong)
        except Exception as e:
            print(f"[sector] {upjong} 상세 실패: {e}")
        time.sleep(SLEEP)
    print(f"[sector] 업종 {len(seen)}개 · 매핑된 종목 {len(code_to_upjong)}개")
    return code_to_upjong


# ── 3) 일별 시세 (siseJson) ─────────────────────────────────────────

def _fetch_daily(code: str, sess=None, days: int = HIST_CAL_DAYS, retries: int = 2):
    """종목 일별 (날짜, 종가, 거래량). 반환: (closes[list], vols[list]) 또는 (None,None)."""
    sess = sess or _session()
    end = date.today().strftime("%Y%m%d")
    start = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
    url = ("https://api.finance.naver.com/siseJson.naver"
           f"?symbol={code}&requestType=1&startTime={start}&endTime={end}&timeframe=day")
    for attempt in range(retries + 1):
        try:
            r = sess.get(url, timeout=10)
            rows = json.loads(r.text.strip().replace("'", '"'))
            closes, vols = [], []
            for x in rows[1:]:
                if not x or len(x) < 6:
                    continue
                c = _num(x[4])
                v = _num(x[5])
                if c is not None:
                    closes.append(c)
                    vols.append(v or 0.0)
            if len(closes) >= 2:
                return closes, vols
            return None, None
        except Exception:
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
            else:
                return None, None
    return None, None


def _ma(vals, n):
    if len(vals) < n:
        return None
    return sum(vals[-n:]) / n


def _downsample(vals, n=30):
    """리스트를 n개로 균등 다운샘플 + 반올림(정수). 스파크라인 저장용."""
    if not vals:
        return []
    if len(vals) <= n:
        return [round(v) for v in vals]
    step = len(vals) / n
    return [round(vals[int(i * step)]) for i in range(n)]


def _ret(closes, offset):
    if len(closes) <= offset:
        return None
    base = closes[-1 - offset]
    if not base:
        return None
    return (closes[-1] / base - 1) * 100


def _metrics(closes, vols):
    """일별 종가/거래량 → 점수 산출용 지표 dict. 데이터 부족 시 None."""
    if not closes or len(closes) < 30:
        return None
    last = closes[-1]
    ret_1d = _ret(closes, 1)
    ret_1w, ret_1m, ret_3m = _ret(closes, 5), _ret(closes, 21), _ret(closes, 63)
    if ret_3m is None:           # 3개월 수익률을 못 내면 주도주 후보에서 제외
        return None
    ma20, ma60, ma120 = _ma(closes, 20), _ma(closes, 60), _ma(closes, 120)
    aligned = bool(ma20 and ma60 and ma120 and last > ma20 > ma60 > ma120)
    # 최근 60일 종가가 그 시점 20일선 위였던 비율
    above = 0
    cnt = 0
    for i in range(max(20, len(closes) - 60), len(closes)):
        m = sum(closes[i - 19:i + 1]) / 20
        cnt += 1
        if closes[i] >= m:
            above += 1
    above_ratio = (above / cnt) if cnt else 0.0
    hi = max(closes[-250:]) if len(closes) >= 2 else last
    high_ratio = (last / hi * 100) if hi else 0.0
    # 연속 상승일
    streak = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] > closes[i - 1]:
            streak += 1
        else:
            break
    # 20일 평균 거래대금(억) = mean(종가×거래량)/1e8
    turn = 0.0
    if vols:
        pairs = list(zip(closes[-20:], vols[-20:]))
        if pairs:
            turn = sum(c * v for c, v in pairs) / len(pairs) / 1e8
    return {
        "ret_1d": ret_1d, "ret_1w": ret_1w, "ret_1m": ret_1m, "ret_3m": ret_3m,
        "aligned": aligned, "above_ratio": above_ratio,
        "above_ma60": bool(ma60 and last > ma60),
        "high_ratio": round(high_ratio, 1), "streak": streak,
        "turnover_eok": round(turn, 1),
        "spark": _downsample(closes[-63:], 30),   # 3개월(≈63영업일) 미니차트용
    }


def _market_returns(sess=None):
    """코스피·코스닥 1·3개월 수익률(%) → {'KS':{'1m','3m'},'KQ':{...}}."""
    out = {}
    for mk, sym in (("KS", "KOSPI"), ("KQ", "KOSDAQ")):
        closes, _ = _fetch_daily(sym, sess=sess)
        if closes:
            out[mk] = {"1m": _ret(closes, 21) or 0.0, "3m": _ret(closes, 63) or 0.0}
        else:
            out[mk] = {"1m": 0.0, "3m": 0.0}
    return out


# ── 4) 점수화 ───────────────────────────────────────────────────────

def _pct_rank(values):
    """값 리스트 → 백분위(0~100, 큰 값일수록 높음)."""
    n = len(values)
    if n <= 1:
        return [50.0] * n
    order = sorted(range(n), key=lambda i: values[i])
    out = [0.0] * n
    for pos, i in enumerate(order):
        out[i] = pos / (n - 1) * 100
    return out


def _trend_score(m):
    s = (0.45 * (1.0 if m["aligned"] else 0.0)
         + 0.30 * m["above_ratio"]
         + 0.15 * (1.0 if m["above_ma60"] else 0.0)
         + 0.10 * min(1.0, m["streak"] / 3.0))
    return round(s * 100, 1)


def score(cands, mkt_ret):
    """필터 통과 후보(메트릭 포함)에 점수 부여. cands: [{...,'m':metrics}]. 정렬된 리스트 반환."""
    if not cands:
        return []
    mom_raw = [0.4 * (c["m"]["ret_1m"] or 0) + 0.6 * c["m"]["ret_3m"] for c in cands]
    rs_raw = []
    for c in cands:
        mr = mkt_ret.get(c["market"], {"1m": 0, "3m": 0})
        rs = 0.4 * ((c["m"]["ret_1m"] or 0) - mr["1m"]) + 0.6 * (c["m"]["ret_3m"] - mr["3m"])
        rs_raw.append(rs)
    liq_raw = [c["m"]["turnover_eok"] for c in cands]

    mom_s = _pct_rank(mom_raw)
    rs_s = _pct_rank(rs_raw)
    liq_s = _pct_rank(liq_raw)

    out = []
    for i, c in enumerate(cands):
        m = c["m"]
        trend_s = _trend_score(m)
        high_s = max(0.0, min(100.0, m["high_ratio"]))
        total = (WEIGHTS["mom"] * mom_s[i] + WEIGHTS["rs"] * rs_s[i]
                 + WEIGHTS["trend"] * trend_s + WEIGHTS["liq"] * liq_s[i]
                 + WEIGHTS["high"] * high_s)
        out.append({
            "code": c["code"], "name": c["name"], "market": c["market"],
            "upjong": c.get("upjong") or "기타", "group": _coarse(c.get("upjong")),
            "score": round(total, 1),
            "mom_1d": round(m["ret_1d"], 2) if m.get("ret_1d") is not None else None,
            "mom_1w": round(m["ret_1w"], 1) if m["ret_1w"] is not None else None,
            "mom_1m": round(m["ret_1m"], 1) if m["ret_1m"] is not None else None,
            "mom_3m": round(m["ret_3m"], 1),
            "rs_3m": round(rs_raw[i], 1),
            "mcap_eok": round(c["mcap_eok"]),
            "turnover_eok": m["turnover_eok"],
            "high_ratio": m["high_ratio"], "aligned": m["aligned"],
            "above_ma60": bool(m.get("above_ma60")),
            "streak": m["streak"], "spark": m.get("spark") or [],
            "is_leader": _passes_gate(m, rs_raw[i]),
            "comp": {"mom": round(mom_s[i], 1), "rs": round(rs_s[i], 1),
                     "trend": trend_s, "liq": round(liq_s[i], 1),
                     "high": round(high_s, 1)},
        })
    out.sort(key=lambda x: x["score"], reverse=True)

    # 폭주장 안전장치: 게이트 통과분이 LEADER_CAP을 넘으면 점수 하위부터 주도 해제
    seen = 0
    for s in out:
        if s["is_leader"]:
            seen += 1
            if seen > LEADER_CAP:
                s["is_leader"] = False
    return out


# ── 5) 섹터(업종) 집계 ──────────────────────────────────────────────

def build_sectors(stocks):
    by = {}
    for s in stocks:
        by.setdefault(s["upjong"], []).append(s)
    # 업종 모멘텀(평균 3개월) 순위용
    upj = [u for u, lst in by.items() if len(lst) >= SECTOR_MIN_N]
    mom_by = {u: (sum(x["mom_3m"] for x in by[u]) / len(by[u])) for u in upj}
    order = sorted(upj, key=lambda u: mom_by[u])
    mom_rank = {u: (order.index(u) / (len(upj) - 1) * 100 if len(upj) > 1 else 50.0)
                for u in upj}

    sectors = []
    for u in upj:
        lst = sorted(by[u], key=lambda x: x["score"], reverse=True)
        topk = lst[:SECTOR_TOPK]
        mean_top = sum(x["score"] for x in topk) / len(topk)
        breadth = 100.0 * sum(1 for x in lst
                              if (x["mom_1m"] or 0) > 0 and x["aligned"]) / len(lst)
        sec_score = 0.5 * mean_top + 0.3 * breadth + 0.2 * mom_rank[u]
        sectors.append({
            "upjong": u, "group": _coarse(u),
            "score": round(sec_score, 1),
            "mom_1m": round(sum(x["mom_1m"] or 0 for x in lst) / len(lst), 1),
            "mom_3m": round(mom_by[u], 1),
            "breadth": round(breadth),
            "persist": round(sum(x["comp"]["trend"] for x in lst) / len(lst)),
            "n": len(lst),
            "member_codes": [x["code"] for x in lst[:TOP_STOCKS_PER_SECTOR]],
        })
    sectors.sort(key=lambda x: x["score"], reverse=True)
    return sectors


# ── 6) 오케스트레이션 ───────────────────────────────────────────────

def collect():
    sess = _session()
    t0 = time.time()
    uni = fetch_universe(sess)
    print(f"[collect] 유니버스 {len(uni)}종목")
    sect = fetch_sector_map(sess)

    # 시총 하한 + '진짜 종목'만(네이버 업종에 매핑된 코드 = ETF/ETN 제외) + 시총 내림차순 상한
    n_pre = sum(1 for u in uni if u["mcap_eok"] >= MCAP_MIN_EOK)
    cand = [u for u in uni if u["mcap_eok"] >= MCAP_MIN_EOK and u["code"] in sect]
    n_etf = n_pre - len(cand)
    cand.sort(key=lambda x: x["mcap_eok"], reverse=True)
    cand = cand[:DEEP_SCAN_MAX]
    print(f"[collect] 시총 {MCAP_MIN_EOK}억↑ {n_pre}종목 · 업종 미매핑(ETF 등) {n_etf}종목 제외 · "
          f"상위 {DEEP_SCAN_MAX} → 정밀스캔 {len(cand)}종목")

    mkt_ret = _market_returns(sess)
    print(f"[collect] 시장수익률 {mkt_ret}")

    scored_cands, ok, fail = [], 0, 0
    for i, u in enumerate(cand):
        closes, vols = _fetch_daily(u["code"], sess=sess)
        if closes is None:
            fail += 1
            time.sleep(SLEEP)
            continue
        m = _metrics(closes, vols)
        if m is None or m["turnover_eok"] < TURNOVER_MIN_EOK:
            time.sleep(SLEEP)
            continue
        u2 = dict(u)
        u2["upjong"] = sect.get(u["code"])
        u2["m"] = m
        scored_cands.append(u2)
        ok += 1
        time.sleep(SLEEP)
        if (i + 1) % 100 == 0:
            print(f"[collect] 진행 {i+1}/{len(cand)} · 통과 {ok} · 실패 {fail}")

    print(f"[collect] 정밀스캔 완료 · 후보 {len(scored_cands)} · 시세실패 {fail}")
    stocks = score(scored_cands, mkt_ret)
    sectors = build_sectors(stocks)

    now = datetime.now(_KST)
    n_leaders = sum(1 for s in stocks if s.get("is_leader"))
    payload = {
        "asof": now.strftime("%Y-%m-%d %H:%M"),
        "asof_date": now.strftime("%Y-%m-%d"),
        "params": {
            "weights": WEIGHTS, "mcap_min_eok": MCAP_MIN_EOK,
            "turnover_min_eok": TURNOVER_MIN_EOK, "sector_min_n": SECTOR_MIN_N,
            "universe_n": len(uni), "scanned_n": len(cand),
            "qualified_n": len(stocks), "leaders_n": n_leaders,
            "gate_preset": GATE_PRESET, "gate": GATE, "leader_cap": LEADER_CAP,
            "fetch_fail": fail,
        },
        "sectors": sectors,
        "stocks": stocks,
    }
    print(f"[collect] 완료 · 섹터 {len(sectors)} · 종목 {len(stocks)} · "
          f"주도 {n_leaders}(게이트 '{GATE_PRESET}') · {time.time()-t0:.0f}s")
    return payload


def diagnose():
    """1콜씩 던져 각 소스 상태를 한 줄로. (활용 전 빠른 점검용)"""
    sess = _session()
    uni = fetch_universe(sess)
    print(f"diagnose · universe={len(uni)}")
    if uni:
        c = uni[0]["code"]
        closes, vols = _fetch_daily(c, sess=sess)
        print(f"diagnose · daily({c})={'OK' if closes else 'FAIL'} "
              f"len={len(closes) if closes else 0}")
    sect = fetch_sector_map(sess)
    print(f"diagnose · sector_map={len(sect)}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "diagnose":
        diagnose()
    else:
        p = collect()
        print(json.dumps(p["params"], ensure_ascii=False))
