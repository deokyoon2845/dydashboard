"""[엔진] 예측 트래킹 — 리포트의 mood가 다음 거래일 코스피 방향과 맞았는지 자동 채점.

positive → 다음 거래일 상승 예측 / cautious → 하락 예측 / neutral → 채점 제외.
결과는 data/predictions.json 에 누적, 적중률을 대시보드에 공개.
"""

import json
from datetime import date
from pathlib import Path

REPORTS_DIR = Path("reports")
PRED_PATH = Path("data/predictions.json")

_DIR = {"positive": 1, "cautious": -1}


def _report_meta():
    """리포트 파일들에서 (날짜, mood, 파일명) 수집."""
    out = []
    if not REPORTS_DIR.exists():
        return out
    for f in sorted(REPORTS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            y, m, d = f.stem.split("_")[0].split("-")
            out.append({"date": date(int(y), int(m), int(d)),
                        "mood": data.get("mood", "neutral"),
                        "report": f.name})
        except Exception:
            continue
    return out


def score_against(close, metas):
    """순수 채점 로직 (테스트 가능).
    close: 날짜 인덱스의 종가 Series / metas: _report_meta() 결과"""
    rets = close.pct_change() * 100
    records = []
    for meta in metas:
        direction = _DIR.get(meta["mood"], 0)
        if direction == 0:
            continue
        # 리포트 날짜 '이후' 첫 거래일의 수익률
        after = [d for d in rets.index if d.date() > meta["date"]]
        if not after:
            continue                      # 아직 다음 거래일이 오지 않음
        nxt = after[0]
        ret = rets.loc[nxt]
        if ret != ret:                    # NaN
            continue
        hit = (direction > 0 and ret > 0) or (direction < 0 and ret < 0)
        records.append({
            "report": meta["report"],
            "date": str(meta["date"]),
            "mood": meta["mood"],
            "next_day": str(nxt.date()),
            "next_ret": round(float(ret), 2),
            "hit": bool(hit),
        })
    return records


def update_scores():
    """yfinance 코스피 데이터로 전체 리포트 채점 → data/predictions.json 갱신."""
    metas = _report_meta()
    if not metas:
        return {"ok": False, "reason": "리포트 없음"}
    try:
        import yfinance as yf
        df = yf.Ticker("^KS11").history(period="6mo", interval="1d")
        close = df["Close"].dropna()
        idx = close.index
        if getattr(idx, "tz", None) is not None:
            close.index = idx.tz_localize(None)
    except Exception as e:
        return {"ok": False, "reason": f"지수 조회 실패: {e}"}

    records = score_against(close, metas)
    n = len(records)
    hits = sum(1 for r in records if r["hit"])
    payload = {
        "updated": str(date.today()),
        "total": n,
        "hits": hits,
        "accuracy": round(hits / n * 100, 1) if n else None,
        "records": records[-100:],
    }
    PRED_PATH.parent.mkdir(exist_ok=True)
    PRED_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, **{k: payload[k] for k in ("total", "hits", "accuracy")}}


def load_scores():
    try:
        if PRED_PATH.exists():
            return json.loads(PRED_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None
