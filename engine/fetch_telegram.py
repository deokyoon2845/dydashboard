"""[엔진] 텔레그램 채널 메시지 수집.

- fetch_since(channel, since_dt) : 지정 시각 이후 모든 메시지 (앱 버튼이 사용)
- fetch_recent(channel, limit)   : 최근 N개 (간단 테스트용)

channel 인자는 단일 문자열(@ch) 또는 쉼표 구분 문자열(@ch1,@ch2)을 모두 지원합니다.
여러 채널일 때 단일 연결을 재사용하고, 수집 결과를 날짜순으로 합산 정렬합니다.
"""

import os
import asyncio

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

load_dotenv()


def _creds():
    return (
        int(os.environ["TELEGRAM_API_ID"]),
        os.environ["TELEGRAM_API_HASH"],
        os.environ["TELEGRAM_SESSION"],
    )


def _parse_channels(channel):
    """문자열('@ch1,@ch2') 또는 리스트를 채널 리스트로 정규화."""
    if isinstance(channel, list):
        return [str(c).strip() for c in channel if str(c).strip()]
    return [c.strip() for c in str(channel).split(",") if c.strip()]


async def _fetch_all(channels, since_dt=None, limit=None):
    """여러 채널 메시지 수집 — 단일 연결 재사용, 날짜순 합산 반환."""
    api_id, api_hash, session = _creds()
    client = TelegramClient(StringSession(session), api_id, api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError(
                "세션이 유효하지 않습니다. engine/telegram_login.py 를 다시 실행해 "
                "TELEGRAM_SESSION 을 갱신하세요."
            )
        results = []
        for channel in channels:
            async for msg in client.iter_messages(channel, limit=limit):
                # since_dt 보다 오래된 메시지를 만나면 이 채널 중단 (최신순 순회)
                if since_dt is not None and msg.date is not None and msg.date < since_dt:
                    break
                if msg.text:
                    results.append({
                        "date": msg.date,
                        "text": msg.text,
                        "channel": channel,
                    })
        # 여러 채널 메시지를 날짜 오름차순으로 합산 정렬
        results.sort(key=lambda m: m["date"])
        return results
    finally:
        await client.disconnect()


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def fetch_since(channel, since_dt):
    """since_dt(타임존 포함) 이후의 모든 텍스트 메시지를 시간순으로 반환.
    channel은 단일 '@ch' 또는 쉼표 구분 '@ch1,@ch2' 모두 지원."""
    return _run(_fetch_all(_parse_channels(channel), since_dt=since_dt))


def fetch_recent(channel, limit=20):
    """최근 limit개 텍스트 메시지를 시간순으로 반환.
    channel은 단일 '@ch' 또는 쉼표 구분 '@ch1,@ch2' 모두 지원."""
    return _run(_fetch_all(_parse_channels(channel), limit=limit))


if __name__ == "__main__":
    from engine.channels import load_channels
    channels = load_channels()
    if not channels:
        raise SystemExit("채널이 없습니다. engine/channels.json 또는 .env의 TELEGRAM_CHANNEL을 확인하세요.")
    print(f"수집 대상 채널: {channels}")
    msgs = fetch_recent(channels)
    print(f"\n가져온 메시지: {len(msgs)}개\n")
    for m in msgs:
        label = f"[{m.get('channel','')}]" if len(channels) > 1 else ""
        print(f"[{m['date']:%Y-%m-%d %H:%M}]{label} {m['text'][:120]}")
        print("-" * 50)
