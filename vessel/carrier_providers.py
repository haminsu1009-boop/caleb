"""
vessel/carrier_providers.py
선사(운항사) 사이트 스케줄 조회 — HMM/ONE/SM상선/장금상선(Sinokor)/
고려해운(KMTC)/Maersk 등

터미널 접안예정(ETB)이 제일 정확하지만, 우리 터미널(부산신항 등)을
안 쓰는 선박이거나 터미널 쪽 자동조회가 아직 안 됐을 때는 선사가
공지하는 스케줄이 차선책이 된다. 다만 이건 "계획"이라 실제 지연이
늦게 반영되는 경우가 많아 터미널보다는 부정확할 수 있다 —
formatter.py가 그 우선순위를 답장에 그대로 표시한다
(수동입력 ≥ 터미널 > 선사 > AIS).

⚠️ 지금은 왜 "뼈대"만 있나 — terminal_providers.py와 같은 이유.
이 세션에서 아래 선사 도메인에 직접 접속이 막혀 있어서 실제 조회
요청 형식(파라미터명, GET/POST, 세션 필요 여부)을 확인 못 했다.
완성하는 법도 동일: query_url을 열어 검색 → 개발자도구 Network 탭
→ 요청 캡처 → Claude에게 전달.

대부분은 회원가입이나 API 키 없이 홈페이지에서 바로 조회 가능한
공개 페이지로 보인다(선사가 화주 편의를 위해 열어둔 서비스) — 다만
실제로 로그인 없이 되는지는 각 사이트를 열어봐야 확실하다.

.env 설정:
  VESSEL_CARRIERS=hmm,one    # 콤마구분 코드. 비우면 아래 전부 시도.
"""

from __future__ import annotations

import os

from vessel.terminal_providers import NotConfiguredError, TerminalCall


class CarrierProvider:
    code = "base"
    name = "base"
    query_url = ""

    def lookup(self, vessel_name: str, voyage_no: str | None) -> TerminalCall | None:
        raise NotConfiguredError(
            f"{self.name} 조회는 아직 실제 요청 형식이 확인되지 않았습니다. "
            f"{self.query_url} 를 열어 검색해보고, 그 요청(Network 탭)을 캡처해서 "
            f"알려주시면 연동을 완성할 수 있어요."
        )


class HMMProvider(CarrierProvider):
    code, name = "hmm", "HMM"
    query_url = "https://www.hmm21.com/e-service/general/schedule/ScheduleMain/byVesselName.do"


class ONEProvider(CarrierProvider):
    code, name = "one", "ONE(Ocean Network Express)"
    query_url = "https://ecomm.one-line.com/ecom/CUP_HOM_3005.do?sessLocale=ko"


class SMLineProvider(CarrierProvider):
    code, name = "sm", "SM상선(SM Line)"
    query_url = "https://esvc.smlines.com/smline/CUP_HOM_3005.do?sessLocale=ko"


class SinokorProvider(CarrierProvider):
    code, name = "sinokor", "장금상선(Sinokor)"
    query_url = "https://ebiz.sinokor.co.kr/Schedule"


class KMTCProvider(CarrierProvider):
    code, name = "kmtc", "고려해운(KMTC)"
    query_url = "https://www.kmtc.co.kr/index.jsp"


class MaerskProvider(CarrierProvider):
    code, name = "maersk", "Maersk"
    query_url = "https://www.maersk.com/schedules/vesselSchedules"


ALL_CARRIERS: list[CarrierProvider] = [
    HMMProvider(), ONEProvider(), SMLineProvider(), SinokorProvider(),
    KMTCProvider(), MaerskProvider(),
]


def get_active_carriers() -> list[CarrierProvider]:
    """.env의 VESSEL_CARRIERS(콤마구분 코드)로 조회 대상을 좁힌다. 비어 있으면 전부 시도."""
    codes = os.getenv("VESSEL_CARRIERS", "").strip()
    if not codes:
        return ALL_CARRIERS
    wanted = {c.strip().lower() for c in codes.split(",") if c.strip()}
    return [c for c in ALL_CARRIERS if c.code in wanted]


def lookup_carriers(vessel_name: str, voyage_no: str | None
                     ) -> tuple[TerminalCall | None, list[CarrierProvider]]:
    """설정된 선사를 순서대로 조회 시도. 반환 형태는 terminal_providers.lookup_terminals와 동일."""
    tried = []
    for provider in get_active_carriers():
        tried.append(provider)
        try:
            call = provider.lookup(vessel_name, voyage_no)
        except NotConfiguredError:
            continue
        except Exception as e:  # 선사 사이트 오류로 전체 조회가 죽으면 안 됨
            print(f"[vessel] {provider.name} 조회 오류: {e}")
            continue
        if call is not None:
            call.kind = "carrier"
            return call, tried
    return None, tried
