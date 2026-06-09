"""[1회 실행용] 텔레그램에 로그인해서 '재사용 가능한 세션 문자열'을 발급합니다.

처음 한 번만 실행하면 됩니다. 전화번호 -> 인증코드(-> 2단계 비밀번호) 순으로 물어봐요.
끝나면 긴 문자열이 출력되는데, 그걸 .env 의 TELEGRAM_SESSION 에 붙여넣으세요.

⚠️ 이 세션 문자열은 '내 텔레그램 계정 비밀번호'와 같습니다. 절대 깃허브에 올리거나 공유하지 마세요.

실행: python engine/telegram_login.py
"""

import os

from dotenv import load_dotenv
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

load_dotenv()

api_id = int(os.environ["TELEGRAM_API_ID"])
api_hash = os.environ["TELEGRAM_API_HASH"]

with TelegramClient(StringSession(), api_id, api_hash) as client:
    session_str = client.session.save()
    me = client.get_me()
    print("\n" + "=" * 60)
    print(f"로그인 성공! ({me.first_name})")
    print("아래 한 줄을 .env 의 TELEGRAM_SESSION= 뒤에 붙여넣으세요:")
    print("=" * 60 + "\n")
    print(session_str)
    print("\n(이 문자열은 비밀번호와 같습니다. 절대 공개 금지)\n")
