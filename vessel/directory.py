"""
vessel/directory.py
모선명 → IMO/MMSI 로컬 디렉터리

⚠️ 중요한 설계 이유: VesselFinder·MarineTraffic 등 AIS API는 선박명
자유검색을 지원하지 않는다 — IMO 또는 MMSI 번호로만 위치를 조회할 수
있다. 그래서 "모선명만 말하면 자동 추적"이 되려면, 사람이 말하는
이름(오탈자·별칭 포함)을 IMO/MMSI로 바꿔주는 매핑표가 먼저 있어야
한다. 이 파일이 그 역할이다.

data/vessel_directory.json 형식:
[
  {"names": ["HMM COPENHAGEN", "현대코펜하겐"], "imo": "9863297", "mmsi": "440183000"}
]

실무에서 쓰려면: 거래하는 선사가 운항하는 선박을 이 파일에 계속
추가하면 된다. IMO 번호는 선사 스케줄표, 또는 무료 조회 사이트인
equasis.org(프랑스 해양청 운영, 회원가입만 하면 무료) 등에서 확인할
수 있다.
"""

from __future__ import annotations

import difflib
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIRECTORY_PATH = os.path.join(ROOT, "data", "vessel_directory.json")


def _normalize(s: str) -> str:
    s = s.upper().strip()
    s = re.sub(r"[^A-Z0-9가-힣 ]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def load_directory(path: str = DIRECTORY_PATH) -> list[dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def resolve(vessel_name: str, entries: list[dict] | None = None,
            cutoff: float = 0.72) -> tuple[dict | None, list[dict]]:
    """모선명을 디렉터리에서 찾는다.

    반환: (확정된 엔트리 또는 None, 후보 목록)
      - 정확히(정규화 기준) 일치하는 이름이 있으면 바로 확정.
      - 없으면 difflib로 유사도 매칭 — 1건만 애매하지 않게 위면 확정,
        여러 건이면 후보로 돌려줘서 사용자에게 되물을 수 있게 한다.
    """
    entries = entries if entries is not None else load_directory()
    if not vessel_name or not entries:
        return None, []

    target = _normalize(vessel_name)

    # 이름 → 엔트리 인덱스 (정확 일치용)
    exact_index: dict[str, dict] = {}
    all_alias = []
    for e in entries:
        for alias in e.get("names", []):
            norm = _normalize(alias)
            exact_index[norm] = e
            all_alias.append(norm)

    if target in exact_index:
        return exact_index[target], []

    # 부분 문자열 포함 매칭 (예: "코펜하겐" → "HMM COPENHAGEN" 별칭 "현대코펜하겐")
    substr_hits = [exact_index[a] for a in all_alias if target and (target in a or a in target)]
    substr_hits = _dedup(substr_hits)
    if len(substr_hits) == 1:
        return substr_hits[0], []

    # 유사도 매칭 (오탈자 대응)
    close = difflib.get_close_matches(target, all_alias, n=5, cutoff=cutoff)
    fuzzy_hits = _dedup([exact_index[a] for a in close])

    candidates = _dedup(substr_hits + fuzzy_hits)
    if len(candidates) == 1:
        return candidates[0], []
    return None, candidates


def _dedup(entries: list[dict]) -> list[dict]:
    seen, out = set(), []
    for e in entries:
        key = e.get("imo") or e.get("mmsi") or e["names"][0]
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out
