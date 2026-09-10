"""
vessel/terminal_providers.py
항만 터미널(부두 운영사) 스케줄 조회 — 부산신항/북항 주요 터미널

사용자 말대로, 선사가 주는 스케줄보다 **터미널이 발표하는 접안예정(ETB)
시간이 실제 도착시간에 훨씬 가깝다** — 터미널은 실제 선석 배정을 관리하는
쪽이라 지연/앞당김이 바로 반영되기 때문이다. 그래서 AIS 위치추적과는
별도로, 터미널 사이트에서 "선명+항차"로 조회하는 경로를 추가한다.

⚠️ 지금은 왜 "뼈대"만 있나
이 세션의 네트워크 정책상 아래 터미널 도메인에 직접 접속이 막혀 있어서
(조직 egress 정책 차단 — 우회 시도 대상이 아님), 각 사이트의 실제 조회
요청 형식(파라미터명, GET/POST, 로그인·세션 필요 여부)을 확인하지 못한
채로는 "그럴듯해 보이지만 실제로는 안 되는" 스크래퍼가 된다. 그래서
연동부는 NotConfiguredError를 던지는 자리로 남겨뒀고, 대신 사용자에게
해당 터미널 조회 페이지 링크를 바로 보여주는 폴백을 tracker.py에 뒀다.

완성하는 법 (오래 안 걸림):
  1. 아래 query_url을 브라우저로 열어서 실제 선박 하나를 검색해본다.
  2. 개발자도구 Network 탭에서 그 검색 요청(URL + 파라미터, 또는 POST
     본문)을 "Copy as cURL"로 복사한다.
  3. 그 내용을 Claude에게 붙여주면 해당 lookup()을 완성할 수 있다.
     (PNIT와 HPNT는 URL 패턴이 완전히 같아서, 하나만 확인해도 둘 다
     같은 방식으로 풀릴 가능성이 높다 — 같은 터미널 운영 솔루션 계열로 보임)

.env 설정:
  VESSEL_TERMINALS=hjnc,pnit    # 콤마구분 코드. 비우면 아래 전부 시도.
"""

from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass

from vessel import manual_store


class NotConfiguredError(Exception):
    """이 터미널의 실제 조회 요청 형식이 아직 확인되지 않았을 때."""


@dataclass
class TerminalCall:
    """터미널/선사/직원수동입력 — 셋 다 "선명+항차로 찾은 스케줄 정보"라는
    같은 모양이라 하나의 타입으로 통일했다. kind로 출처를 구분한다."""
    terminal: str                    # 코드 (예: "hjnc", "hmm", 수동입력은 "manual")
    terminal_name: str                # 사람이 읽는 이름
    vessel_name: str
    voyage_no: str | None
    kind: str = "terminal"             # "terminal" | "carrier" | "manual"
    berth: str | None = None          # 선석 (터미널 전용, 선사엔 보통 없음)
    eta: str | None = None            # 입항 예정
    etb: str | None = None            # 접안 예정 — 터미널 기준일 때 제일 정확
    etd: str | None = None            # 출항 예정
    status: str | None = None
    source_url: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class TerminalProvider:
    code = "base"
    name = "base"
    query_url = ""

    def lookup(self, vessel_name: str, voyage_no: str | None) -> TerminalCall | None:
        raise NotConfiguredError(
            f"{self.name} 조회는 아직 실제 요청 형식이 확인되지 않았습니다. "
            f"{self.query_url} 를 열어 검색해보고, 그 요청(Network 탭)을 캡처해서 "
            f"알려주시면 연동을 완성할 수 있어요."
        )


class BPTProvider(TerminalProvider):
    code, name = "bpt", "신선대부두(BPT · CJ KBCT 운영)"
    query_url = ("https://info.bptc.co.kr/content/cg/frame/"
                 "ship_no_frame_cg_kr.jsp?p_id=SHNO_CN_KR&snb_num=1&snb_div=service")


class HJNCProvider(TerminalProvider):
    code, name = "hjnc", "한진신항만(HJNC)"
    query_url = "https://www.hjnc.co.kr/esvc/vessel/voyageList"


class PNITProvider(TerminalProvider):
    code, name = "pnit", "부산신항국제터미널(PNIT · PSA)"
    query_url = "https://www.pnitl.com/infoservice/vessel/vslScheduleList.jsp"


class HPNTProvider(TerminalProvider):
    code, name = "hpnt", "현대부산신항만(HPNT)"
    query_url = "https://www.hpnt.co.kr/infoservice/vessel/vslScheduleList.jsp"


class PNCProvider(TerminalProvider):
    code, name = "pnc", "부산신항만(PNC)"
    query_url = "https://svc.pncport.com/"


ALL_TERMINALS: list[TerminalProvider] = [
    BPTProvider(), HJNCProvider(), PNITProvider(), HPNTProvider(), PNCProvider(),
]


def get_active_terminals() -> list[TerminalProvider]:
    """.env의 VESSEL_TERMINALS(콤마구분 코드, 예: hjnc,pnit)로 조회 대상을 좁힌다.
    비어 있으면 전부 시도한다."""
    codes = os.getenv("VESSEL_TERMINALS", "").strip()
    if not codes:
        return ALL_TERMINALS
    wanted = {c.strip().lower() for c in codes.split(",") if c.strip()}
    return [t for t in ALL_TERMINALS if t.code in wanted]


def _manual_to_call(vessel_name: str, voyage_no: str | None, entry: dict) -> TerminalCall:
    f = entry["fields"]
    age_min = round((time.time() - entry["updated_at"]) / 60)
    age_label = f"{age_min}분 전" if age_min < 60 else f"{age_min // 60}시간 전"
    return TerminalCall(
        terminal="manual",
        terminal_name=f.get("terminal_name") or "직원 확인",
        vessel_name=entry.get("vessel_name") or vessel_name,
        voyage_no=entry.get("voyage_no") or voyage_no,
        berth=f.get("berth"),
        eta=f.get("eta"),
        etb=f.get("etb"),
        etd=f.get("etd"),
        status=f.get("status"),
        source_url=f"직원 입력 · {age_label}",
        kind="manual",
    )


def lookup_terminals(vessel_name: str, voyage_no: str | None
                      ) -> tuple[TerminalCall | None, list[TerminalProvider]]:
    """터미널 정보를 찾는다 — 순서: 직원 수동 입력(가장 신선) → 자동 프로바이더들.

    반환: (결과 또는 None, 자동 프로바이더 중 실제로 시도한 목록)
    두 번째 값은 전부 실패/미연동일 때 포맷터가 "직접 확인" 링크를
    보여주는 데 쓴다(수동 입력값을 이미 찾았으면 시도하지 않으므로 빈 리스트).
    """
    manual_entry = manual_store.get_entry(vessel_name, voyage_no)
    if manual_entry is not None:
        return _manual_to_call(vessel_name, voyage_no, manual_entry), []

    tried = []
    for provider in get_active_terminals():
        tried.append(provider)
        try:
            call = provider.lookup(vessel_name, voyage_no)
        except NotConfiguredError:
            continue
        except Exception as e:  # 터미널 사이트 오류로 전체 조회가 죽으면 안 됨
            print(f"[vessel] {provider.name} 조회 오류: {e}")
            continue
        if call is not None:
            return call, tried
    return None, tried
