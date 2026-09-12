"""
vessel/test_vessel.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
선박 추적 파이프라인 회귀 테스트 (파서 → 디렉터리 → 프로바이더 → 트래커)

외부 API 키 없이 MockProvider로 전부 돈다. 손으로 매번 확인하던
시나리오(EVER GIVEN 조회, 없는 배, 모호한 이름, 수동입력 우선순위,
TTL 만료 등)를 재현 가능하게 고정해둔 것 — 코드를 고칠 때마다
이 파일 하나만 돌려보면 파이프라인이 안 깨졌는지 바로 안다.

    python vessel/test_vessel.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

FAILED = 0


def check(name: str, ok: bool, detail: str = ""):
    global FAILED
    print(f"  {'✅' if ok else '❌'} {name}" + (f"  — {detail}" if detail else ""))
    if not ok:
        FAILED += 1


def _clean_state():
    for f in ("data/vessel_cache.json", "data/vessel_manual_terminal.json"):
        path = os.path.join(ROOT, f)
        if os.path.exists(path):
            os.remove(path)


def test_parser():
    from vessel.parser import parse

    q = parse("EVER GIVEN, 0526E")
    check("구분자(,) 파싱 — 선명", q.vessel_name == "EVER GIVEN", q.vessel_name)
    check("구분자(,) 파싱 — 항차", q.voyage_no == "0526E", q.voyage_no)

    q = parse("모선명: HMM 코펜하겐, 항차번호: 45N")
    check("키워드 파싱 — 선명", q.vessel_name == "HMM 코펜하겐", q.vessel_name)
    check("키워드 파싱 — 항차", q.voyage_no == "45N", q.voyage_no)

    q = parse("에버기븐호 45E 지금 어디쯤이야?")
    check("자유문장 파싱 — 항차는 정확히 뽑힘", q.voyage_no == "45E", q.voyage_no)

    q = parse("")
    check("빈 입력 — 선명 없음", q.vessel_name is None)
    check("빈 입력 — 항차 없음", q.voyage_no is None)


def test_directory():
    from vessel import directory

    entries = [
        {"names": ["HMM COPENHAGEN", "현대코펜하겐"], "imo": "1111111", "mmsi": None},
        {"names": ["HMM COPACABANA"], "imo": "2222222", "mmsi": None},
    ]

    entry, cands = directory.resolve("현대코펜하겐", entries)
    check("정확 일치(별칭)", entry is not None and entry["imo"] == "1111111")

    entry, cands = directory.resolve("코펜하겐", entries)
    check("부분 포함 매칭", entry is not None and entry["imo"] == "1111111")

    entry, cands = directory.resolve("HMM COP", entries)
    check("모호한 이름 → 후보 2개 반환", entry is None and len(cands) == 2, len(cands))

    entry, cands = directory.resolve("존재안함선박", entries)
    check("등록 안 된 이름 → None + 후보 없음", entry is None and not cands)


def test_manual_store():
    from vessel import manual_store

    manual_store.delete_entry("TESTSHIP", "1A")
    parsed = manual_store.parse_update_args(
        "TESTSHIP, 1A | 터미널=HJNC | 선석=1부두 | ETB=2026-09-15 08:00 | 상태=접안예정"
    )
    check("update 명령 파싱 성공", parsed is not None)
    vessel_name, voyage_no, fields = parsed
    check("update 파싱 — 선명/항차", (vessel_name, voyage_no) == ("TESTSHIP", "1A"))
    check("update 파싱 — 필드", fields.get("etb") == "2026-09-15 08:00", fields)

    manual_store.set_entry(vessel_name, voyage_no, fields, updated_by="test")
    got = manual_store.get_entry("TESTSHIP", "1A")
    check("저장 직후 조회됨", got is not None and got["fields"]["berth"] == "1부두")

    # TTL 만료 시뮬레이션 — updated_at을 과거로 돌려놓고 다시 읽으면 None
    data = manual_store._load()
    data[manual_store._key("TESTSHIP", "1A")]["updated_at"] = time.time() - 999999
    manual_store._save(data)
    check("TTL 지난 값은 조회 안 됨", manual_store.get_entry("TESTSHIP", "1A") is None)

    check("삭제 성공", manual_store.delete_entry("TESTSHIP", "1A") is True)
    check("이미 지운 건 삭제 실패", manual_store.delete_entry("TESTSHIP", "1A") is False)

    check("형식 틀린 update는 None", manual_store.parse_update_args("이상한입력") is None)


def test_terminal_and_carrier_stubs():
    from vessel.terminal_providers import lookup_terminals
    from vessel.carrier_providers import lookup_carriers

    call, tried = lookup_terminals("존재안함선박×", "0000X")
    check("터미널 자동조회 미연동 → None + 시도목록 반환", call is None and len(tried) == 5, len(tried))

    call, tried = lookup_carriers("존재안함선박×", "0000X")
    check("선사 자동조회 미연동 → None + 시도목록 반환", call is None and len(tried) == 6, len(tried))


def test_tracker_end_to_end():
    from vessel.tracker import track_from_text

    r = track_from_text("EVER GIVEN, 0526E")
    check("EVER GIVEN 조회 성공(Mock)", r.ok and r.kind == "position", r.kind)
    check("응답에 IMO 포함", "9811000" in r.message)
    check("응답에 터미널·선사 링크 폴백 포함", "터미널·선사 직접 확인" in r.message)

    r = track_from_text("없는배 123A")
    check("등록 안 된 선박 → not_found", r.kind == "not_found" and not r.ok, r.kind)

    r = track_from_text("")
    check("빈 입력 → no_input", r.kind == "no_input" and not r.ok, r.kind)


def test_manual_override_priority():
    from vessel import manual_store
    from vessel.tracker import track_from_text

    manual_store.set_entry("EVER GIVEN", "0526E",
                            {"terminal_name": "HJNC", "etb": "2026-09-15 08:00"},
                            updated_by="test")
    r = track_from_text("EVER GIVEN, 0526E")
    check("수동입력이 있으면 최우선으로 노출", r.message.startswith("🧑‍💼"), r.message[:30])
    check("수동입력엔 자동조회 링크가 안 붙음(이미 찾았으므로)",
          "터미널·선사 직접 확인" not in r.message)
    manual_store.delete_entry("EVER GIVEN", "0526E")

    r = track_from_text("EVER GIVEN, 0526E")
    check("수동입력 삭제 후엔 다시 링크 폴백으로 돌아감", r.message.startswith("📋"), r.message[:30])


def main():
    print("=" * 84)
    print("  선박 추적 봇 — 파이프라인 회귀 테스트")
    print("=" * 84)

    _clean_state()
    try:
        test_parser()
        test_directory()
        test_manual_store()
        test_terminal_and_carrier_stubs()
        test_tracker_end_to_end()
        test_manual_override_priority()
    finally:
        _clean_state()

    print("=" * 84)
    print(f"  {'✅ 전부 통과' if FAILED == 0 else f'❌ {FAILED}건 실패'}")
    print("=" * 84)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
