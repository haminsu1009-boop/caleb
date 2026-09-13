"""
bot/oversold/regime.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사람이 거는 국면 스위치

자동 판정(시장 200일선)도 있지만, 그건 꺾인 걸 늦게 안다.
사람이 직접 "지금 상승장이다"라고 말해주면 그 말을 따른다.
봇을 멈추지 않고 파일 하나만 바꾸면 다음 틱부터 반영된다.

모드는 둘이다.
  normal  기본. 롱·숏·다이버전스가 각자 규칙대로 판단한다.
  bull    상승장. 숏 계열을 끈다.

숏은 원래도 상승장에 안 켜진다 — 23건 전부 직전 60일 시장이 −5%
아래일 때만 나갔고 상승·급등 국면 신호는 0건이다. 이 스위치는
그 구조적 보호에 사람의 판단을 한 겹 더 얹는 것이다.

돌파(신고가) 계열은 운용에서 뺐다. 승률 56%로 넷 중 꼴찌였고
최악 −99.9%였다. 자본 보존을 앞에 두면 빠지는 게 맞다.
연구 기록은 ml/bull_breakout.py 에 남아 있다.

주의: 지금 실거래 봇에는 과매도 롱 모듈 하나뿐이다. 숏·다이버전스는
아직 백테스트에만 있다. 그때까지 이 스위치는 로그만 남긴다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import json
import os
import time

MODES = ("normal", "bull")

# 모드별로 어떤 계열을 켜고 끄는지. 모듈이 늘면 여기만 고친다.
_ENABLED = {
    "normal": {"long": True, "short": True,  "div": True},
    "bull":   {"long": True, "short": False, "div": True},
}

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PATH = os.path.join(ROOT, "state", "regime.json")


def read() -> dict:
    """매 틱 새로 읽는다. 봇을 멈추지 않고 바꿀 수 있도록."""
    try:
        d = json.load(open(PATH, encoding="utf-8"))
        if d.get("mode") in MODES:
            return d
    except Exception:
        pass
    return {"mode": "normal", "set_at": None, "note": ""}


def write(mode: str, note: str = "") -> dict:
    if mode not in MODES:
        raise ValueError(f"모드는 {MODES} 중 하나여야 한다 — 받은 값: {mode!r}")
    d = {"mode": mode, "set_at": time.strftime("%Y-%m-%d %H:%M:%S"), "note": note}
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    os.replace(tmp, PATH)
    return d


def enabled(kind: str, mode: str | None = None) -> bool:
    """이 국면에서 해당 계열을 켜도 되나."""
    if mode is None:
        mode = read()["mode"]
    return _ENABLED.get(mode, _ENABLED["normal"]).get(kind, False)


def describe(d: dict | None = None) -> str:
    d = d or read()
    on = [k for k, v in _ENABLED[d["mode"]].items() if v]
    s = f"국면 {d['mode']} — 켜진 계열: {', '.join(on)}"
    if d.get("set_at"):
        s += f" (설정 {d['set_at']}"
        s += f" · {d['note']})" if d.get("note") else ")"
    return s
