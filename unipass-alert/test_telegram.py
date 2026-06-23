"""유니패스 API 키 없이도 텔레그램 알림 연결만 빠르게 테스트하는 스크립트."""
import json
import os
import sys

from unipass_alert import send_telegram, CONFIG_PATH, load_json

if __name__ == "__main__":
    config = load_json(CONFIG_PATH, {})
    if not config:
        print(f"{CONFIG_PATH} 가 없습니다. config.example.json을 복사해 만들어주세요.")
        sys.exit(1)

    result = send_telegram(
        config["telegram_bot_token"],
        config["telegram_chat_id"],
        "유니패스 알림 자동화 - 텔레그램 연결 테스트 ✅\n실제 API 키 연동 전 사전 점검입니다.",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
