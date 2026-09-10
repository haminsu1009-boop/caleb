"""
vessel/telegram_bot.py
텔레그램에서 "모선명, 항차번호"를 보내면 자동으로 추적해 답장하는 봇.

설정:
  1. @BotFather → /newbot → 토큰 발급
  2. .env 에 TELEGRAM_TOKEN 입력
     (기존 coin/notifier.py 가 쓰는 TELEGRAM_TOKEN과 같은 변수지만,
      이 봇은 특정 chat_id로만 보내는 게 아니라 아무나 말을 걸면
      응답하는 구조라 TELEGRAM_CHAT_ID는 필요 없다)
  3. python vessel/telegram_bot.py

사용법 (텔레그램 채팅창):
  HMM 코펜하겐, 0526E
  모선 EVER GIVEN 항차 45E
"""

from __future__ import annotations

import os
import time

import requests
from dotenv import load_dotenv

from vessel.tracker import track_from_text

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN", "")
BASE = f"https://api.telegram.org/bot{TOKEN}"

WELCOME = (
    "🚢 선박 추적 봇입니다.\n"
    "모선명과 항차번호를 보내주시면 실시간 위치를 알려드려요.\n\n"
    "예) HMM 코펜하겐, 0526E"
)


def send(chat_id, text: str) -> None:
    try:
        requests.post(f"{BASE}/sendMessage",
                       json={"chat_id": chat_id, "text": text[:4000]},
                       timeout=10)
    except requests.RequestException as e:
        print(f"[텔레그램 전송 오류] {e}")


def run() -> None:
    if not TOKEN:
        print("⚠️ TELEGRAM_TOKEN 없음 — .env 설정 후 다시 실행하세요.")
        return

    print("🚢 선박 추적 텔레그램 봇 시작 (Ctrl+C로 종료)")
    offset = None
    while True:
        try:
            r = requests.get(f"{BASE}/getUpdates",
                              params={"timeout": 30, "offset": offset}, timeout=35)
            r.raise_for_status()
            for upd in r.json().get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or {}
                text = (msg.get("text") or "").strip()
                chat_id = msg.get("chat", {}).get("id")
                if chat_id is None or not text:
                    continue
                if text in ("/start", "/help"):
                    send(chat_id, WELCOME)
                    continue
                result = track_from_text(text)
                send(chat_id, result.message)
        except requests.RequestException as e:
            print(f"[폴링 오류] {e}")
            time.sleep(3)
        except KeyboardInterrupt:
            print("종료합니다.")
            break


if __name__ == "__main__":
    run()
