"""
vessel/manual_store.py
자동 터미널 API 연동이 되기 전까지, 직원이 텔레그램으로 직접 입력한
터미널 정보(선석/ETA/ETB/ETD/상태)를 저장하는 임시 저장소.

`vessel/terminal_providers.py`의 자동 조회 프로바이더들은 아직 뼈대만
있어서(vessel/README.md 참고) 실제 값을 못 가져온다. 그 공백을 메우는
가장 빠른 방법은 "직원이 터미널 사이트를 직접 보고 텔레그램으로 값을
불러주면 봇이 저장해뒀다가, 이후 조회에 그대로 보여주는" 방식이다 —
API 연동이 늦어져도 오늘부터 바로 쓸 수 있다.

tracker.py는 자동 프로바이더보다 이 저장소를 먼저 확인한다 — 사람이
방금 확인해서 입력한 값이 가장 신선하기 때문이다. TTL(기본 72시간)이
지나면 자동으로 무시된다 — 갱신을 깜빡한 값을 최신인 것처럼 보여주지
않기 위해서다.

입력 형식 (텔레그램 /update 명령):
  /update 선명, 항차 | 터미널=HJNC | 선석=1부두 | ETB=2026-09-15 08:00 | 상태=접안예정
"""

from __future__ import annotations

import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE_PATH = os.path.join(ROOT, "data", "vessel_manual_terminal.json")
TTL_HOURS = float(os.getenv("MANUAL_TERMINAL_TTL_HOURS", "72"))

FIELD_ALIASES = {
    "터미널": "terminal_name", "terminal": "terminal_name",
    "선석": "berth", "berth": "berth",
    "eta": "eta", "입항": "eta",
    "etb": "etb", "접안": "etb",
    "etd": "etd", "출항": "etd",
    "상태": "status", "status": "status",
}


def _key(vessel_name: str, voyage_no: str | None) -> str:
    v = (vessel_name or "").strip().upper()
    n = (voyage_no or "").strip().upper()
    return f"{v}|{n}"


def _load() -> dict:
    if not os.path.exists(STORE_PATH):
        return {}
    try:
        with open(STORE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def set_entry(vessel_name: str, voyage_no: str, fields: dict, updated_by: str = "") -> None:
    data = _load()
    data[_key(vessel_name, voyage_no)] = {
        "vessel_name": vessel_name,
        "voyage_no": voyage_no,
        "fields": fields,
        "updated_at": time.time(),
        "updated_by": updated_by,
    }
    _save(data)


def delete_entry(vessel_name: str, voyage_no: str) -> bool:
    data = _load()
    key = _key(vessel_name, voyage_no)
    if key not in data:
        return False
    del data[key]
    _save(data)
    return True


def get_entry(vessel_name: str, voyage_no: str | None) -> dict | None:
    """(선명, 항차) 정확히 일치하는 최신 수동 입력을 돌려준다. TTL 초과면 None."""
    entry = _load().get(_key(vessel_name, voyage_no))
    if entry is None:
        return None
    age_hours = (time.time() - entry["updated_at"]) / 3600
    if age_hours > TTL_HOURS:
        return None
    return entry


def list_entries() -> list[dict]:
    """만료 안 된 수동 입력을 전부 돌려준다(운영 확인용, 텔레그램 /list가 씀).
    최근 입력 순으로 정렬."""
    now = time.time()
    entries = [e for e in _load().values() if (now - e["updated_at"]) / 3600 <= TTL_HOURS]
    return sorted(entries, key=lambda e: e["updated_at"], reverse=True)


def parse_update_args(args: str) -> tuple[str, str, dict] | None:
    """"/update" 뒤에 오는 문자열을 파싱한다.

    형식: "선명, 항차 | 키=값 | 키=값 ..."
    키: 터미널/terminal, 선석/berth, eta/입항, etb/접안, etd/출항, 상태/status
    형식이 안 맞으면 None을 돌려준다(부를 곳에서 사용법을 안내하면 됨).
    """
    parts = [p.strip() for p in args.split("|") if p.strip()]
    if not parts or "," not in parts[0]:
        return None

    vessel_name, voyage_no = (x.strip() for x in parts[0].split(",", 1))
    if not vessel_name or not voyage_no:
        return None

    fields = {}
    for p in parts[1:]:
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        canon = FIELD_ALIASES.get(k.strip().lower())
        if canon and v.strip():
            fields[canon] = v.strip()

    if not fields:
        return None
    return vessel_name, voyage_no, fields
