#!/usr/bin/env python3
"""
유니패스(UNI-PASS) 화물통관 진행정보를 조회하고,
이전 조회 결과와 비교해 상태가 바뀐 경우에만 텔레그램으로 알려준다.

사용법:
    python unipass_notify.py --bl <BL번호> [--year <BL년도>]
    python unipass_notify.py --cargo <화물관리번호>

필요한 환경변수 (.env 또는 export):
    UNIPASS_API_KEY      유니패스 OpenAPI 인증키 (crkyCn)
    TELEGRAM_BOT_TOKEN   텔레그램 봇 토큰
    TELEGRAM_CHAT_ID     알림을 받을 chat id
"""
import argparse
import hashlib
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

UNIPASS_URL = "https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo"

STATE_DIR = Path(os.environ.get("UNIPASS_STATE_DIR", Path.home() / ".unipass_notifier"))
STATE_FILE = STATE_DIR / "state.json"


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_progress(api_key: str, *, cargo_no: str | None, bl_no: str | None, bl_year: str | None) -> list[dict]:
    params = {"crkyCn": api_key}
    if cargo_no:
        params["cargMtNo"] = cargo_no
    else:
        params["mblNo"] = bl_no
        if bl_year:
            params["blYy"] = bl_year

    resp = requests.get(UNIPASS_URL, params=params, timeout=15)
    resp.raise_for_status()

    root = ET.fromstring(resp.content)

    error_msg = root.findtext(".//tCnt") if root.find(".//tCnt") is not None else None
    records = []
    for el in root.iter():
        if "cargCsclPrgsInfo" in el.tag and len(list(el)) > 0:
            records.append({child.tag: (child.text or "").strip() for child in el})

    if not records:
        raise RuntimeError(
            f"조회 결과가 없습니다. 화물관리번호/BL번호를 확인하세요. (응답 일부: {resp.text[:300]})"
        )
    return records


def summarize(records: list[dict]) -> str:
    latest = records[-1]
    # 필드명은 API 응답에 따라 다를 수 있어 흔한 키를 우선 찾고, 없으면 전체를 보여준다.
    status = latest.get("csclPrgsStts") or latest.get("prgsStts") or latest.get("cargTrcnRsltNm")
    date = latest.get("prcsDttm") or latest.get("cargTrcnPrcsDttm") or latest.get("prcsDt")
    if status:
        line = status
        if date:
            line += f" ({date})"
        return line
    return ", ".join(f"{k}={v}" for k, v in latest.items() if v)


def state_hash(records: list[dict]) -> str:
    return hashlib.sha256(json.dumps(records, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> None:
    resp = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data={"chat_id": chat_id, "text": text},
        timeout=10,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"텔레그램 알림 전송 실패 ({resp.status_code}): {resp.text}")


def main() -> None:
    parser = argparse.ArgumentParser(description="유니패스 통관상태 변경 감지 및 카카오톡 알림")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--bl", help="BL(House/Master) 번호")
    group.add_argument("--cargo", help="화물관리번호")
    parser.add_argument("--year", help="BL 년도 (--bl 사용 시, 예: 2026)")
    parser.add_argument("--force-notify", action="store_true", help="변경이 없어도 현재 상태를 알려준다")
    args = parser.parse_args()

    api_key = os.environ.get("UNIPASS_API_KEY")
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not api_key:
        sys.exit("환경변수 UNIPASS_API_KEY 가 설정되어 있지 않습니다.")
    if not bot_token or not chat_id:
        sys.exit("환경변수 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 가 설정되어 있지 않습니다.")

    key = args.cargo or f"BL:{args.bl}:{args.year or ''}"

    try:
        records = fetch_progress(api_key, cargo_no=args.cargo, bl_no=args.bl, bl_year=args.year)
    except Exception as e:
        sys.exit(f"조회 실패: {e}")

    new_hash = state_hash(records)
    state = load_state()
    prev = state.get(key)

    summary = summarize(records)
    target_label = args.cargo or args.bl

    if prev is None:
        send_telegram_message(bot_token, chat_id, f"[유니패스] {target_label} 조회 시작\n현재 상태: {summary}")
        print(f"최초 조회: {summary}")
    elif prev["hash"] != new_hash:
        send_telegram_message(
            bot_token,
            chat_id,
            f"[유니패스] {target_label} 상태 변경!\n이전: {prev['summary']}\n현재: {summary}",
        )
        print(f"상태 변경 감지 및 알림 전송: {prev['summary']} -> {summary}")
    elif args.force_notify:
        send_telegram_message(bot_token, chat_id, f"[유니패스] {target_label} 현재 상태\n{summary}")
        print(f"변경 없음 (강제 알림 전송): {summary}")
    else:
        print(f"변경 없음: {summary}")

    state[key] = {"hash": new_hash, "summary": summary}
    save_state(state)


if __name__ == "__main__":
    main()
