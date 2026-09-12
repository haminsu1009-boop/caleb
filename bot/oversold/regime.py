"""
bot/oversold/regime.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사람이 거는 국면 스위치

자동 판정(시장 200일선)도 있지만, 그건 꺾인 걸 늦게 안다.
사람이 직접 "지금 상승장이다"라고 말해주면 그 말을 따른다.
봇을 멈추지 않고 파일 하나만 바꾸면 다음 틱부터 반영된다.

모드는 셋이다.
  normal  기본. 모든 모듈이 각자 규칙대로 판단한다.
  bull    상승장. 숏 계열을 끄고, 돌파 계열을 켠다.
  bear    하락장. 돌파 계열을 끈다. 숏·과매도 롱은 그대로.

백테스트가 말하는 것 (돌파 모듈 기준, 진입당 5%):
  · 돌파 끔          23.11배 · 낙폭 28.7% · 1년 손실확률 10% · 샤프 1.24
  · 항상 켬(자동)    530.77배 · 낙폭 31.9% · 손실확률 12% · 샤프 1.81
  · 사람이 켬(60일)  163.84배 · 낙폭 28.7% · 손실확률  7% · 샤프 1.68

수동 스위치의 값은 수익률이 아니라 낙폭이다. 자동으로 켜면 낙폭이
늘지만, 사람이 확인하고 켜면 낙폭이 돌파 없는 것과 똑같은 28.7%로
유지된다. 손실확률은 오히려 셋 중 가장 낮다.

다만 홀드아웃(2024년 이후)만 보면 돌파 모듈은 보탬이 없었다
(끔 7.52배 / 사람이 켬 7.21배, 낙폭은 9.3%→16.7%로 악화).
163배의 대부분은 2021년 한 해에서 나온 숫자다. 켤 때 그걸 알고 켜라.

주의: 지금 실거래 봇에는 과매도 롱 모듈 하나뿐이다. 숏·다이버전스·
돌파는 아직 백테스트에만 있다. 그때까지 이 스위치는 로그만 남긴다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import json
import os
import time

MODES = ("normal", "bull", "bear")

# 모드별로 어떤 계열을 켜고 끄는지. 모듈이 늘면 여기만 고친다.
_ENABLED = {
    "normal": {"long": True, "short": True,  "div": True, "break": False},
    "bull":   {"long": True, "short": False, "div": True, "break": True},
    "bear":   {"long": True, "short": True,  "div": True, "break": False},
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
