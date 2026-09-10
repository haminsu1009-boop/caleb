"""
vessel/formatter.py
조회 결과 → 사람이 읽는 한국어 답장 문장

세 채널(텔레그램/카카오/웹위젯)이 전부 이 함수를 공유해서, 문구를
한 곳에서만 고치면 세 군데 다 반영된다.
"""

from __future__ import annotations

from vessel.providers import VesselPosition

MAP_LINK_TMPL = "https://www.google.com/maps?q={lat},{lon}"


def format_position(name: str | None, voyage_no: str | None,
                     pos: VesselPosition) -> str:
    lines = [f"🚢 {pos.name or name or '선박'}" + (f" (IMO {pos.imo})" if pos.imo else "")]

    if voyage_no:
        lines.append(f"항차: {voyage_no}  ※AIS 데이터엔 항차번호가 없어 참고 표시용입니다")

    if pos.lat is not None and pos.lon is not None:
        lines.append(f"위치: {pos.lat:.4f}, {pos.lon:.4f}  ({MAP_LINK_TMPL.format(lat=pos.lat, lon=pos.lon)})")
    if pos.speed_kn is not None or pos.course_deg is not None:
        speed = f"{pos.speed_kn:.1f}kn" if pos.speed_kn is not None else "-"
        course = f"{pos.course_deg:.0f}°" if pos.course_deg is not None else "-"
        lines.append(f"속력: {speed}  침로: {course}")
    if pos.nav_status:
        lines.append(f"항행상태: {pos.nav_status}")
    if pos.destination:
        lines.append(f"목적지(AIS): {pos.destination}")
    if pos.eta_utc:
        lines.append(f"ETA(AIS): {pos.eta_utc}")
    if pos.last_report_utc:
        lines.append(f"최종 수신: {pos.last_report_utc}")

    source_label = {
        "vesselfinder": "VesselFinder (실시간 AIS)",
        "marinetraffic": "MarineTraffic (실시간 AIS)",
        "mock": "⚠️ 데모 데이터 — 실제 API 키 미등록 상태",
    }.get(pos.source, pos.source)
    lines.append(f"출처: {source_label}")

    if pos.imo and pos.source != "mock":
        lines.append(f"지도에서 보기: https://www.marinetraffic.com/en/ais/details/ships/imo:{pos.imo}")

    return "\n".join(lines)


def format_ambiguous(vessel_name: str, candidates: list[dict]) -> str:
    lines = [f"🔍 '{vessel_name}'와(과) 비슷한 선박이 여러 척 있어요. 어느 배인가요?"]
    for c in candidates[:5]:
        primary = c["names"][0]
        ident = f"IMO {c['imo']}" if c.get("imo") else f"MMSI {c.get('mmsi', '?')}"
        lines.append(f"  • {primary} ({ident})")
    lines.append("\n정확한 선명으로 다시 말씀해 주세요.")
    return "\n".join(lines)


def format_not_in_directory(vessel_name: str) -> str:
    return (
        f"🚢 '{vessel_name}'을(를) 선박 디렉터리에서 찾을 수 없어요.\n"
        "등록된 선박명이 아니거나 표기가 달라서 그럴 수 있어요.\n"
        "정확한 영문 선명으로 다시 시도하거나, 담당자에게 등록을 요청해 주세요."
    )


def format_no_position(vessel_name: str) -> str:
    return f"🚢 '{vessel_name}'의 IMO/MMSI는 확인했지만, 현재 AIS 위치 데이터를 가져오지 못했어요. 잠시 후 다시 시도해 주세요."


def format_need_input() -> str:
    return (
        "🚢 모선명과 항차번호를 알려주시면 바로 추적해드려요.\n"
        "예) HMM 코펜하겐, 0526E"
    )


def format_error(detail: str) -> str:
    return f"⚠️ 조회 중 오류가 발생했어요: {detail}\n잠시 후 다시 시도해 주세요."
