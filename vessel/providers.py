"""
vessel/providers.py
AIS(선박자동식별장치) 실시간 위치 조회 — 프로바이더 3종

  VesselFinderProvider  : https://api.vesselfinder.com/vessels (유료, userkey 발급 필요)
                           공식 문서: https://api.vesselfinder.com/docs/vessels.html
                           파라미터/응답 필드는 위 문서 기준으로 구현했다.
  MarineTrafficProvider : services.marinetraffic.com 의 exportvessel 계열 엔드포인트 (유료)
                           ⚠️ MarineTraffic은 서비스(PS01/PS07 등)마다 별도 계약·키가
                              필요하고 정확한 파라미터가 구독 플랜에 따라 달라진다.
                              아래 구현은 공개된 레거시 패턴 기준 best-effort이니,
                              키를 발급받으면 대시보드의 실제 엔드포인트로 URL을
                              맞춰써야 한다 (get_position 안의 TODO 참고).
  MockProvider          : 키가 없을 때 자동 사용되는 데모용 가짜 데이터.
                           나머지 파이프라인(파서/디렉터리/포맷터/3채널 봇)을
                           실제 API 없이 끝까지 테스트할 수 있게 해준다.

.env 설정:
  AIS_PROVIDER=vesselfinder|marinetraffic|mock   (비우면 키가 있는 쪽을 자동 선택)
  VESSELFINDER_API_KEY=
  MARINETRAFFIC_API_KEY=
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone

import requests

# AIS 표준 항행상태 코드 (ITU-R M.1371)
NAVSTAT = {
    0: "항해중(기관사용)", 1: "정박중", 2: "조종불능", 3: "조종제한",
    4: "흘수제약", 5: "계류중", 6: "좌초", 7: "어로중", 8: "범주항해중",
    9: "위험물 운송중(예비)", 10: "예비", 11: "예비", 12: "예비",
    13: "예비", 14: "AIS-SART(조난)", 15: "미정의",
}


@dataclass
class VesselPosition:
    name: str | None
    imo: str | None
    mmsi: str | None
    lat: float | None
    lon: float | None
    speed_kn: float | None
    course_deg: float | None
    nav_status: str | None
    destination: str | None
    eta_utc: str | None
    last_report_utc: str | None
    source: str                          # "vesselfinder" | "marinetraffic" | "mock"
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class AISProvider:
    name = "base"

    def position(self, imo: str | None = None, mmsi: str | None = None,
                 name: str | None = None) -> VesselPosition | None:
        raise NotImplementedError


class VesselFinderProvider(AISProvider):
    name = "vesselfinder"
    BASE = "https://api.vesselfinder.com/vessels"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def position(self, imo: str | None = None, mmsi: str | None = None,
                 name: str | None = None) -> VesselPosition | None:
        if not imo and not mmsi:
            return None
        params = {"userkey": self.api_key, "extradata": "voyage,master"}
        if imo:
            params["imo"] = imo
        if mmsi:
            params["mmsi"] = mmsi

        r = requests.get(self.BASE, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        if not data:
            return None

        item = data[0]
        ais = item.get("AIS", {}) or {}
        voyage = item.get("VOYAGE", {}) or {}  # extradata=voyage 요청 시 포함

        navstat = ais.get("NAVSTAT")
        return VesselPosition(
            name=ais.get("NAME"),
            imo=str(ais.get("IMO") or imo or "") or None,
            mmsi=str(ais.get("MMSI") or mmsi or "") or None,
            lat=ais.get("LATITUDE"),
            lon=ais.get("LONGITUDE"),
            speed_kn=ais.get("SPEED"),
            course_deg=ais.get("COURSE"),
            nav_status=NAVSTAT.get(navstat, str(navstat) if navstat is not None else None),
            destination=ais.get("DESTINATION") or voyage.get("DESTINATION"),
            eta_utc=ais.get("ETA") or voyage.get("ETA") or ais.get("ETA_AIS"),
            last_report_utc=ais.get("TIMESTAMP"),
            source=self.name,
            raw=item,
        )


class MarineTrafficProvider(AISProvider):
    name = "marinetraffic"
    # TODO: 실제 키 발급 후 MarineTraffic 대시보드의 서비스별(PS01/PS07 등)
    #       엔드포인트로 교체할 것. 아래는 공개된 레거시 exportvessel 패턴이다.
    URL_TMPL = "https://services.marinetraffic.com/api/exportvessel/{key}/v:8/imo:{imo}/protocol:jsono"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def position(self, imo: str | None = None, mmsi: str | None = None,
                 name: str | None = None) -> VesselPosition | None:
        if not imo:
            return None  # 이 엔드포인트는 IMO 기준 조회만 지원
        url = self.URL_TMPL.format(key=self.api_key, imo=imo)
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        rows = data if isinstance(data, list) else data.get("data", [])
        if not rows:
            return None
        row = rows[0]
        return VesselPosition(
            name=row.get("SHIPNAME"),
            imo=str(row.get("IMO") or imo),
            mmsi=str(row.get("MMSI") or "") or None,
            lat=_to_float(row.get("LAT")),
            lon=_to_float(row.get("LON")),
            speed_kn=_to_float(row.get("SPEED")),
            course_deg=_to_float(row.get("COURSE")),
            nav_status=row.get("STATUS_NAME") or str(row.get("STATUS", "")),
            destination=row.get("DESTINATION"),
            eta_utc=row.get("ETA"),
            last_report_utc=row.get("TIMESTAMP"),
            source=self.name,
            raw=row,
        )


class MockProvider(AISProvider):
    """API 키 없이 파이프라인을 끝까지 테스트하기 위한 데모용 프로바이더.

    같은 IMO/MMSI/이름을 넣으면 항상 같은(고정 시드) 값이 나오되,
    시간이 지날수록 항로를 따라 조금씩 이동한 것처럼 보이게 한다.
    """
    name = "mock"

    # 부산 → 롱비치 항로 위의 waypoint 몇 개 (데모용, 대권항로 근사)
    ROUTE = [
        (35.10, 129.04, "BUSAN"),
        (33.6, 140.0, ""),
        (40.0, 175.0, ""),
        (45.0, -170.0, ""),
        (40.0, -140.0, ""),
        (33.75, -118.19, "LONG BEACH"),
    ]

    def position(self, imo: str | None = None, mmsi: str | None = None,
                 name: str | None = None) -> VesselPosition | None:
        seed_key = imo or mmsi or name or "UNKNOWN"
        rnd = random.Random(seed_key)

        progress = rnd.random()  # 0=출항, 1=도착 (고정 시드라 항상 동일)
        idx_f = progress * (len(self.ROUTE) - 1)
        i = min(int(idx_f), len(self.ROUTE) - 2)
        frac = idx_f - i
        lat = self.ROUTE[i][0] + (self.ROUTE[i + 1][0] - self.ROUTE[i][0]) * frac
        lon = self.ROUTE[i][1] + (self.ROUTE[i + 1][1] - self.ROUTE[i][1]) * frac

        eta = datetime.now(timezone.utc) + timedelta(days=round((1 - progress) * 14, 1))
        last_report = datetime.now(timezone.utc) - timedelta(minutes=rnd.randint(2, 45))

        return VesselPosition(
            name=name or f"MOCK VESSEL {seed_key}",
            imo=imo or f"MOCK-{abs(hash(seed_key)) % 10_000_000:07d}",
            mmsi=mmsi,
            lat=round(lat, 4),
            lon=round(((lon + 180) % 360) - 180, 4),
            speed_kn=round(rnd.uniform(11, 19), 1),
            course_deg=round(rnd.uniform(0, 359), 0),
            nav_status=NAVSTAT[0],
            destination="LONG BEACH, US",
            eta_utc=eta.strftime("%Y-%m-%d %H:%M UTC"),
            last_report_utc=last_report.strftime("%Y-%m-%d %H:%M UTC"),
            source=self.name,
            raw={"note": "⚠️ 데모용 가짜 데이터 — 실제 AIS 키를 .env에 등록하면 실데이터로 전환됩니다."},
        )


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def get_provider() -> AISProvider:
    """.env 설정에 따라 프로바이더를 고른다.

    AIS_PROVIDER를 명시하면 그대로 쓰고, 비어 있으면 키가 등록된
    프로바이더를 자동으로 고르며, 아무 키도 없으면 MockProvider로
    폴백한다(데모/개발 모드).
    """
    choice = os.getenv("AIS_PROVIDER", "").strip().lower()
    vf_key = os.getenv("VESSELFINDER_API_KEY", "").strip()
    mt_key = os.getenv("MARINETRAFFIC_API_KEY", "").strip()

    if choice == "vesselfinder" and vf_key:
        return VesselFinderProvider(vf_key)
    if choice == "marinetraffic" and mt_key:
        return MarineTrafficProvider(mt_key)
    if choice == "mock":
        return MockProvider()

    if vf_key:
        return VesselFinderProvider(vf_key)
    if mt_key:
        return MarineTrafficProvider(mt_key)

    print("[vessel] ⚠️ AIS API 키 없음 — MockProvider(데모 데이터)로 동작합니다. "
          ".env에 VESSELFINDER_API_KEY 또는 MARINETRAFFIC_API_KEY를 넣으면 실데이터로 전환됩니다.")
    return MockProvider()
