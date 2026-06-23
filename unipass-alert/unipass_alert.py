"""
유니패스(관세청 Open API) 화물진행정보를 주기적으로 조회해서
새로운 진행 내역을 텔레그램으로 알려주는 스크립트.

설정: config.json (config.example.json 참고)
상태 저장: state.json (이미 알린 항목을 기억해서 중복 알림 방지)
"""
import json
import os
import sys
import time
import xml.etree.ElementTree as ET

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
STATE_PATH = os.path.join(BASE_DIR, "state.json")

UNIPASS_URL = "https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo"


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def send_telegram(bot_token, chat_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    resp = requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=10)
    resp.raise_for_status()
    return resp.json()


def fetch_cargo_progress(api_key, mbl_no, hbl_no, bl_yy):
    params = {
        "crkyCn": api_key,
        "mblNo": mbl_no,
        "hblNo": hbl_no,
        "blYy": bl_yy,
    }
    resp = requests.get(UNIPASS_URL, params=params, timeout=15)
    resp.raise_for_status()
    root = ET.fromstring(resp.text)

    entries = []
    for node in root.iter():
        # 응답의 각 진행 내역 항목을 일반화해서 텍스트 필드들을 수집
        if node.tag.lower().endswith("cargcsclprgsinfoqryvo"):
            fields = {child.tag: (child.text or "").strip() for child in node}
            if fields:
                entries.append(fields)
    return entries


def entry_key(entry):
    return json.dumps(entry, sort_keys=True, ensure_ascii=False)


def format_entry(label, entry):
    lines = [f"[{label}] 화물 진행정보 업데이트"]
    for k, v in entry.items():
        if v:
            lines.append(f"- {k}: {v}")
    return "\n".join(lines)


def matches_keywords(entry, keywords):
    if not keywords:
        return False
    blob = " ".join(entry.values())
    return any(kw in blob for kw in keywords)


def run_once(config, state):
    bot_token = config["telegram_bot_token"]
    chat_id = config["telegram_chat_id"]

    for watch in config.get("watch_list", []):
        label = watch.get("label", "화물")
        try:
            entries = fetch_cargo_progress(
                config["unipass_api_key"],
                watch.get("mbl_no", ""),
                watch.get("hbl_no", ""),
                watch.get("bl_yy", ""),
            )
        except Exception as e:
            print(f"[{label}] 조회 실패: {e}", file=sys.stderr)
            continue

        seen = set(state.get(label, []))
        new_seen = list(seen)

        for entry in entries:
            key = entry_key(entry)
            if key in seen:
                continue
            new_seen.append(key)

            text = format_entry(label, entry)
            if matches_keywords(entry, watch.get("alert_keywords", [])):
                text = "🔔 [관심 키워드 매칭]\n" + text

            send_telegram(bot_token, chat_id, text)

        state[label] = new_seen

    save_json(STATE_PATH, state)


def main():
    if not os.path.exists(CONFIG_PATH):
        print(
            f"config.json이 없습니다. config.example.json을 복사해서 "
            f"{CONFIG_PATH} 를 만들어주세요.",
            file=sys.stderr,
        )
        sys.exit(1)

    config = load_json(CONFIG_PATH, {})
    state = load_json(STATE_PATH, {})

    if "--once" in sys.argv:
        run_once(config, state)
        return

    interval = config.get("poll_interval_seconds", 600)
    while True:
        run_once(config, state)
        time.sleep(interval)


if __name__ == "__main__":
    main()
