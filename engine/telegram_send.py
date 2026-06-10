"""[엔진] 생성된 리포트를 텔레그램 봇으로 발송 (PDF 첨부).

필요 환경변수:
  TELEGRAM_BOT_TOKEN  — @BotFather 에서 발급한 봇 토큰
  TELEGRAM_CHAT_ID    — 받을 대상 chat_id (개인이면 본인 user id)

봇 토큰·chat_id 얻는 법은 README 참고. 둘 중 하나라도 없으면 발송을 건너뜁니다.
"""

import os

import requests

API_BASE = "https://api.telegram.org/bot{token}/{method}"


def _creds():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    return token, chat_id


def send_report(pdf_bytes: bytes, caption: str, filename: str = "report.pdf") -> dict:
    """PDF를 텔레그램으로 발송. 결과 dict 반환."""
    token, chat_id = _creds()
    if not token or not chat_id:
        return {"ok": False, "reason": "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 미설정"}

    try:
        # 캡션은 1024자 제한 → 잘라서 보냄
        cap = caption[:1000]
        r = requests.post(
            API_BASE.format(token=token, method="sendDocument"),
            data={"chat_id": chat_id, "caption": cap, "parse_mode": "HTML"},
            files={"document": (filename, pdf_bytes, "application/pdf")},
            timeout=30,
        )
        r.raise_for_status()
        body = r.json()
        if not body.get("ok"):
            return {"ok": False, "reason": f"텔레그램 API 오류: {body}"}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def send_text(text: str) -> dict:
    """간단 텍스트 메시지 발송 (실패 알림용)."""
    token, chat_id = _creds()
    if not token or not chat_id:
        return {"ok": False, "reason": "미설정"}
    try:
        r = requests.post(
            API_BASE.format(token=token, method="sendMessage"),
            data={"chat_id": chat_id, "text": text[:4000], "parse_mode": "HTML"},
            timeout=20,
        )
        r.raise_for_status()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "reason": str(e)}
