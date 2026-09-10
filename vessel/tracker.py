"""
vessel/tracker.py
파서 → 디렉터리 → AIS 프로바이더 → 캐시 → 포맷터 를 이어붙이는 오케스트레이션.

세 채널(텔레그램/카카오/웹위젯) 봇은 전부 이 파일의 track()과
track_from_text() 두 함수만 부르면 된다.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

from dotenv import load_dotenv

from vessel import directory, parser
from vessel.formatter import (
    format_ambiguous, format_error, format_need_input,
    format_no_position, format_not_in_directory, format_position,
)
from vessel.providers import VesselPosition, get_provider
from vessel.terminal_providers import TerminalCall, lookup_terminals

load_dotenv()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_PATH = os.path.join(ROOT, "data", "vessel_cache.json")
CACHE_TTL_SEC = int(os.getenv("AIS_CACHE_TTL_SEC", "300"))  # 유료 API 호출 절약용

_provider = None  # lazy init — .env가 로드된 뒤 처음 조회할 때 생성


def _get_provider():
    global _provider
    if _provider is None:
        _provider = get_provider()
    return _provider


@dataclass
class TrackResult:
    ok: bool
    kind: str  # "position" | "ambiguous" | "not_found" | "no_position" | "no_input" | "error"
    message: str
    position: VesselPosition | None = None
    terminal_call: TerminalCall | None = None
    vessel_name: str | None = None
    voyage_no: str | None = None


def _load_cache() -> dict:
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _cached_position(key: str) -> VesselPosition | None:
    cache = _load_cache()
    entry = cache.get(key)
    if not entry or time.time() - entry["ts"] > CACHE_TTL_SEC:
        return None
    return VesselPosition(**entry["position"])


def _store_position(key: str, pos: VesselPosition) -> None:
    cache = _load_cache()
    cache[key] = {"ts": time.time(), "position": pos.to_dict()}
    _save_cache(cache)


def track(vessel_name: str | None, voyage_no: str | None) -> TrackResult:
    if not vessel_name:
        return TrackResult(False, "no_input", format_need_input())

    # 터미널 조회는 우리 로컬 디렉터리(IMO/MMSI)와 무관하게 선명+항차만
    # 있으면 시도할 수 있다 — AIS보다 먼저, 독립적으로 돌린다.
    terminal_call, tried_terminals = lookup_terminals(vessel_name, voyage_no)

    entry, candidates = directory.resolve(vessel_name)
    if entry is None:
        if candidates:
            return TrackResult(False, "ambiguous", format_ambiguous(vessel_name, candidates),
                                terminal_call=terminal_call,
                                vessel_name=vessel_name, voyage_no=voyage_no)
        return TrackResult(False, "not_found",
                            format_not_in_directory(vessel_name, terminal_call, tried_terminals),
                            terminal_call=terminal_call,
                            vessel_name=vessel_name, voyage_no=voyage_no)

    imo, mmsi = entry.get("imo"), entry.get("mmsi")
    cache_key = imo or mmsi or vessel_name

    pos = _cached_position(cache_key)
    if pos is None:
        try:
            pos = _get_provider().position(imo=imo, mmsi=mmsi, name=entry["names"][0])
        except Exception as e:  # AIS API 네트워크/응답 오류 — 사용자에겐 조용히 재시도 유도
            return TrackResult(False, "error", format_error(str(e)),
                                terminal_call=terminal_call,
                                vessel_name=vessel_name, voyage_no=voyage_no)
        if pos is not None:
            _store_position(cache_key, pos)

    if pos is None:
        return TrackResult(False, "no_position",
                            format_no_position(vessel_name, terminal_call, tried_terminals),
                            terminal_call=terminal_call,
                            vessel_name=vessel_name, voyage_no=voyage_no)

    msg = format_position(entry["names"][0], voyage_no, pos, terminal_call, tried_terminals)
    return TrackResult(True, "position", msg, position=pos, terminal_call=terminal_call,
                        vessel_name=vessel_name, voyage_no=voyage_no)


def track_from_text(text: str) -> TrackResult:
    q = parser.parse(text)
    return track(q.vessel_name, q.voyage_no)
