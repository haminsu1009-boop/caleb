"""
vessel/parser.py
자유 텍스트에서 모선명 / 항차번호를 뽑아낸다.

지원하는 입력 형태 (아래로 갈수록 관대하게 해석):
  1. "HMM 코펜하겐 / 0526E"          — 구분자(/, -, ,)로 명확히 분리
  2. "모선 HMM 코펜하겐 항차 0526E"   — 키워드로 명시
  3. "HMM 코펜하겐호 0526E 언제 부산 와요?"
                                     — 마지막에 나오는 항차번호 패턴 토큰을
                                       항차번호로, 그 앞부분을 모선명으로 간주

항차번호는 보통 숫자 2~4자리 + 방향 접미 알파벳 0~2글자로 표기한다
(예: 0526E, 123N, 45W). 이 패턴에 맞는 "마지막 토큰"을 항차번호 후보로
본다 — 모선명 안에 이런 토큰이 없다는 보장은 없으므로 100% 정확하진
않다. 확실하게 하려면 구분자(1번 방식)를 쓰는 게 가장 안전하다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

VOYAGE_RE = re.compile(r"^\d{2,5}[A-Za-z]{0,2}$")
KEYWORDS = ["모선명", "모선", "선명", "선박명", "항차번호", "항차", "voyage", "vessel"]
TRAILING_PARTICLES = re.compile(r"(호|은|는|이|가|을|를)$")


@dataclass
class ParsedQuery:
    vessel_name: str | None
    voyage_no: str | None
    raw: str


def _strip_keywords(text: str) -> str:
    out = text
    for kw in KEYWORDS:
        out = re.sub(rf"{re.escape(kw)}\s*[:：]?\s*", " ", out, flags=re.IGNORECASE)
    return out


def parse(text: str) -> ParsedQuery:
    raw = text.strip()
    if not raw:
        return ParsedQuery(None, None, raw)

    # 1) 구분자로 명확히 나뉘는 경우
    for sep in ("/", ",", "，", "-", "|"):
        if sep in raw:
            left, right = raw.split(sep, 1)
            left, right = _strip_keywords(left).strip(), _strip_keywords(right).strip()
            # 오른쪽이 항차번호 패턴이면 그대로 확정
            right_first_tok = right.split()[0] if right.split() else ""
            if VOYAGE_RE.match(right_first_tok.upper()):
                return ParsedQuery(_clean_name(left), right_first_tok.upper(), raw)

    # 2) 키워드 제거 후 토큰 분석 — 항차번호 패턴에 맞는 토큰을 찾는다
    cleaned = _strip_keywords(raw)
    tokens = cleaned.split()
    voyage_no, voyage_idx = None, None
    for i, tok in enumerate(tokens):
        t = tok.strip("?!.,()[]")
        if VOYAGE_RE.match(t.upper()) and not t.isalpha():
            voyage_no, voyage_idx = t.upper(), i
            # 뒤쪽에 나온 토큰을 우선한다(보통 "선명 다음에 항차"가 자연스러움)

    if voyage_idx is not None:
        name_tokens = tokens[:voyage_idx] + tokens[voyage_idx + 1:]
        # 흔한 질문 어미 제거
        name_tokens = [t for t in name_tokens
                       if t not in ("어디", "어디쯤", "언제", "지금", "위치", "조회", "알려줘", "와요", "오나요", "도착")]
        vessel_name = _clean_name(" ".join(name_tokens))
        return ParsedQuery(vessel_name or None, voyage_no, raw)

    # 3) 항차번호를 못 찾음 — 전체를 모선명 후보로
    return ParsedQuery(_clean_name(cleaned) or None, None, raw)


def _clean_name(name: str) -> str:
    name = name.strip()
    name = TRAILING_PARTICLES.sub("", name)
    return name.strip()
