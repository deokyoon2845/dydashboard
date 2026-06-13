"""[엔진] 주요 경제 일정 — 캘린더 데이터 로드 + 실적일 자동 수집 + 프롬프트 주입 텍스트.

- 고정 일정(FOMC·금통위·CPI·고용·PPI·PCE·GDP·소매판매): data/calendar.json 수동 관리 (연 1회 갱신)
- 실적 발표일: yfinance로 자동 수집 (미국 종목은 비교적 정확, 한국 종목은 부정확할 수 있음)
- 스트림릿 의존 없음 (GitHub Actions에서도 동작)

표시 정책:
- 달력 그리드에는 지난 일정도 함께 표시(지나도 사라지지 않게) → upcoming_events(past_days=...)
- AI 프롬프트 주입(build_calendar_text)은 '다가오는' 일정만 (과거는 굳이 주입 안 함)
"""

import json
import os
from datetime import datetime, date
from zoneinfo import ZoneInfo

_CAL_PATH = os.path.join("data", "calendar.json")
_KST = ZoneInfo("Asia/Seoul")


def _today_kst() -> date:
    return datetime.now(_KST).date()


def load_calendar() -> dict:
    """calendar.json 로드. 실패 시 빈 구조 반환."""
    try:
        with open(_CAL_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"events": [], "earnings_tickers": {}}


def upcoming_events(days: int = 30, past_days: int = 0) -> list:
    """일정을 D-day와 함께 날짜순 반환.

    - days: 오늘부터 며칠 뒤까지 포함 (미래 범위)
    - past_days: 오늘로부터 며칠 전까지 포함 (과거 범위, 0이면 과거 제외)
      → 달력 그리드에서 지난 일정도 보이게 하려면 past_days를 넉넉히 준다.

    반환 항목: {date, name, category, note, dday}
      dday는 음수면 지난 일정(D+N으로 표시), 0이면 오늘, 양수면 다가오는 일정.
    """
    today = _today_kst()
    out = []
    for ev in load_calendar().get("events", []):
        if str(ev.get("date", "")).startswith("_"):
            continue
        try:
            d = datetime.strptime(ev["date"], "%Y-%m-%d").date()
        except Exception:
            continue
        dday = (d - today).days
        if -past_days <= dday <= days:
            out.append({**ev, "dday": dday})
    out.sort(key=lambda e: e["dday"])
    return out


def fetch_next_earnings() -> list:
    """earnings_tickers의 다음 실적 발표일을 yfinance로 수집.

    ⚠️ 한계: 미국 종목은 비교적 정확하지만, 한국 종목은 yfinance에
    실적일 데이터가 없거나 부정확한 경우가 많습니다. 실패 항목은 생략됩니다.

    반환 항목: {date, name, category, note, dday}
    """
    out = []
    tickers = load_calendar().get("earnings_tickers", {})
    if not tickers:
        return out
    try:
        import yfinance as yf
    except Exception:
        return out

    today = _today_kst()
    for name, tk in tickers.items():
        try:
            edf = yf.Ticker(tk).get_earnings_dates(limit=8)
            if edf is None or edf.empty:
                continue
            future = None
            for idx in edf.index:
                try:
                    d = idx.date() if hasattr(idx, "date") else None
                except Exception:
                    continue
                if d and d >= today:
                    future = d if (future is None or d < future) else future
            if future is None:
                continue
            dday = (future - today).days
            if dday <= 45:  # 너무 먼 일정은 노이즈
                out.append({
                    "date": future.strftime("%Y-%m-%d"),
                    "name": f"{name} 실적 발표",
                    "category": "실적",
                    "note": "yfinance 추정 · 변동 가능",
                    "dday": dday,
                })
        except Exception:
            continue
    out.sort(key=lambda e: e["dday"])
    return out


def build_calendar_text(days: int = 14, include_earnings: bool = True) -> str:
    """AI 보고서 프롬프트 주입용 일정 텍스트. (다가오는 일정만 — 과거 제외)

    예) [다가오는 주요 일정 (2주 이내)]
        - D-6 (06-17, 수) FOMC 금리 결정 — SEP·점도표 발표
    빈 일정이면 빈 문자열 반환 → 주입 생략 가능.
    """
    events = upcoming_events(days)  # past_days=0 → 과거 제외
    if include_earnings:
        try:
            events += [e for e in fetch_next_earnings() if e["dday"] <= days]
        except Exception:
            pass
    if not events:
        return ""
    events.sort(key=lambda e: e["dday"])

    weekdays = "월화수목금토일"
    lines = []
    for ev in events:
        try:
            d = datetime.strptime(ev["date"], "%Y-%m-%d").date()
            wd = weekdays[d.weekday()]
            ds = d.strftime("%m-%d")
        except Exception:
            wd, ds = "", ev.get("date", "")
        dday_str = "오늘" if ev["dday"] == 0 else f"D-{ev['dday']}"
        note = f" — {ev['note']}" if ev.get("note") else ""
        lines.append(f"- {dday_str} ({ds}, {wd}) {ev['name']}{note}")
    return f"[다가오는 주요 일정 ({days}일 이내)]\n" + "\n".join(lines)
