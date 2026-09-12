"""
vessel/telegram_bot.py
텔레그램에서 "모선명, 항차번호"를 보내면 자동으로 추적해 답장하는 봇.
관리자는 /update 명령으로 터미널 정보(선석/ETA/ETB/ETD/상태)를 직접
입력해둘 수 있다 — 자동 터미널 API 연동 전까지 쓰는 임시 대체 수단.

설정:
  1. @BotFather → /newbot → 토큰 발급
  2. .env 에 TELEGRAM_TOKEN 입력
     (기존 coin/notifier.py 가 쓰는 TELEGRAM_TOKEN과 같은 변수지만,
      이 봇은 특정 chat_id로만 보내는 게 아니라 아무나 말을 걸면
      응답하는 구조라 TELEGRAM_CHAT_ID는 필요 없다)
  3. .env 에 TELEGRAM_ADMIN_IDS 입력 — /update, /delete 를 쓸 수 있는
     텔레그램 chat_id 목록(콤마구분). 비워두면 누구나 값을 바꿀 수 있으니
     운영 전에 꼭 설정할 것. 본인 chat_id는 @userinfobot 에게 물어보면 된다.
  4. python vessel/telegram_bot.py

사용법 (텔레그램 채팅창):
  HMM 코펜하겐, 0526E
  모선 EVER GIVEN 항차 45E

관리자 전용:
  /update EVER GIVEN, 0526E | 터미널=HJNC | 선석=1부두 | ETB=2026-09-15 08:00 | 상태=접안예정
  /delete EVER GIVEN, 0526E
  /list                (현재 저장된 수동입력 전체 확인)
"""

from __future__ import annotations

import os
import time

import requests
from dotenv import load_dotenv

from vessel import manual_store
from vessel.tracker import track_from_text

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN", "")
BASE = f"https://api.telegram.org/bot{TOKEN}"
ADMIN_IDS = {x.strip() for x in os.getenv("TELEGRAM_ADMIN_IDS", "").split(",") if x.strip()}

WELCOME = (
    "🚢 선박 추적 봇입니다.\n"
    "모선명과 항차번호를 보내주시면 실시간 위치를 알려드려요.\n\n"
    "예) HMM 코펜하겐, 0526E\n\n"
    "관리자는 /update 로 터미널 정보를 직접 입력할 수 있어요 — 자세히 보려면 /update 만 입력."
)

UPDATE_HELP = (
    "📝 터미널 정보 직접 입력 (관리자 전용)\n\n"
    "형식:\n"
    "/update 선명, 항차 | 터미널=HJNC | 선석=1부두 | ETB=2026-09-15 08:00 | 상태=접안예정\n\n"
    "키(필요한 것만 넣으면 됨):\n"
    "  터미널, 선석, ETA(입항예정), ETB(접안예정·제일 중요), ETD(출항예정), 상태\n\n"
    "예)\n"
    "/update EVER GIVEN, 0526E | ETB=2026-09-15 08:00 | 선석=1부두 | 터미널=HJNC\n\n"
    f"저장된 값은 {manual_store.TTL_HOURS:.0f}시간 지나면 자동으로 사라져요(오래된 정보 방지).\n"
    "삭제: /delete 선명, 항차\n"
    "전체 확인: /list"
)


def is_admin(chat_id) -> bool:
    # ADMIN_IDS를 안 정해두면 개발 편의상 전부 허용한다 — 운영 전엔 꼭 설정할 것.
    return not ADMIN_IDS or str(chat_id) in ADMIN_IDS


def send(chat_id, text: str) -> None:
    try:
        requests.post(f"{BASE}/sendMessage",
                       json={"chat_id": chat_id, "text": text[:4000]},
                       timeout=10)
    except requests.RequestException as e:
        print(f"[텔레그램 전송 오류] {e}")


def _command_args(text: str) -> str:
    parts = text.split(maxsplit=1)
    return parts[1] if len(parts) > 1 else ""


def handle_update(chat_id, text: str) -> None:
    if not is_admin(chat_id):
        send(chat_id, "⛔ 이 명령은 관리자만 쓸 수 있어요.")
        return
    args = _command_args(text)
    parsed = manual_store.parse_update_args(args)
    if parsed is None:
        send(chat_id, UPDATE_HELP)
        return
    vessel_name, voyage_no, fields = parsed
    manual_store.set_entry(vessel_name, voyage_no, fields, updated_by=str(chat_id))
    saved = "\n".join(f"  {k}={v}" for k, v in fields.items())
    send(chat_id, f"✅ 저장했어요: {vessel_name} / {voyage_no}\n{saved}")


def handle_delete(chat_id, text: str) -> None:
    if not is_admin(chat_id):
        send(chat_id, "⛔ 이 명령은 관리자만 쓸 수 있어요.")
        return
    args = _command_args(text)
    if "," not in args:
        send(chat_id, "형식: /delete 선명, 항차\n예) /delete EVER GIVEN, 0526E")
        return
    vessel_name, voyage_no = (x.strip() for x in args.split(",", 1))
    ok = manual_store.delete_entry(vessel_name, voyage_no)
    send(chat_id, "🗑️ 삭제했어요." if ok else "해당 항목을 찾지 못했어요.")


def handle_list(chat_id) -> None:
    if not is_admin(chat_id):
        send(chat_id, "⛔ 이 명령은 관리자만 쓸 수 있어요.")
        return
    entries = manual_store.list_entries()
    if not entries:
        send(chat_id, "저장된 수동입력이 없어요.")
        return
    lines = [f"📋 현재 수동입력 {len(entries)}건:"]
    for e in entries:
        age_min = round((time.time() - e["updated_at"]) / 60)
        age = f"{age_min}분 전" if age_min < 60 else f"{age_min // 60}시간 전"
        summary = ", ".join(f"{k}={v}" for k, v in e["fields"].items())
        lines.append(f"  • {e['vessel_name']} / {e['voyage_no']} — {summary} ({age})")
    send(chat_id, "\n".join(lines))


def run() -> None:
    if not TOKEN:
        print("⚠️ TELEGRAM_TOKEN 없음 — .env 설정 후 다시 실행하세요.")
        return
    if not ADMIN_IDS:
        print("⚠️ TELEGRAM_ADMIN_IDS 미설정 — 지금은 누구나 /update로 터미널 정보를 바꿀 수 있습니다.")

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
                elif text.startswith("/update"):
                    handle_update(chat_id, text)
                elif text.startswith("/delete"):
                    handle_delete(chat_id, text)
                elif text.startswith("/list"):
                    handle_list(chat_id)
                else:
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
