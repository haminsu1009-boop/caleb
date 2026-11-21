"""
bot/oversold/regime.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사람이 거는 국면 스위치

자동 판정(시장 200일선)도 있지만, 그건 꺾인 걸 늦게 안다.
사람이 직접 "지금 상승장이다"라고 말해주면 그 말을 따른다.
봇을 멈추지 않고 파일 하나만 바꾸면 다음 틱부터 반영된다.

모드는 셋이다.
  normal  기본. 롱·숏·다이버전스가 각자 규칙대로 판단한다.
  bull    상승장. 숏 계열을 끈다.
  bear    폭락장. 과매도 롱만 끈다. 주봉 숏·상승 다이버전스는 그대로 둔다.

bear를 둔 이유 (ml/leverage_filters.py 뒤 실측):
  롱의 청산은 여러 코인이 한날한시에 무너지는 폭락장에 몰린다. 그 구간에
  롱을 끄면 배율을 3배로 올려도 장중 낙폭이 지금(2배·안 끔) 수준에 머문다.
  폭락장 판정 기준을 네 가지로 흔들어도 같은 방향이었다.

    구성               배율   최종    연복리  장중낙폭  청산   2024~
    안 끔               2배  3.16배   14%   36.2%   10  1.99배
    안 끔               3배  4.13배   18%   51.3%   96  2.57배
    폭락장에 끔(4기준)    3배  5.05~7.48배  20~26%  34.2%  33~63  1.99~2.63배
    폭락장에 끔          5배  4.25~6.28배  18~23%  54.3%  ~150

  5배는 끄더라도 낙폭 54%에 수익이 3배보다 늘지 않는다. 3배가 상한이다.
  **3배는 bear를 제때 켠다는 전제다.** 놓치면 "안 끔·3배" 줄이 된다.

  폭락장에 새 숏 규칙을 넣지 않은 이유: "20기간선 대비 +N% 이상이면 숏"
  (과매도의 거울상)은 15가지 조건 전부 손실이었고 최악 역행 -708%였다.
  주봉 숏은 원래 하락장에서만 신호가 뜨고 이미 검증돼 있다.

  다이버전스를 켜두는 이유 (ml/per_coin_portfolio.py 앞 실측, 롱+숏+다이버
  한 지갑): 폭락장에 롱만 끈 쪽이 롱·다이버를 같이 끈 쪽보다 대부분 나았다.
  4배에서 46~63배 대 20~58배, 결과 범위도 더 좁았다. 다이버전스는 1배라
  폭락장에서도 청산 위험이 작고 반등을 잘 잡는다.

  bear는 **새 진입만** 막는다. 이미 들고 있는 롱은 손절·목표·시간청산
  규칙대로 정리된다. 당장 닫고 싶으면 --close-all.

숏은 원래도 상승장에 안 켜진다 — 23건 전부 직전 60일 시장이 −5%
아래일 때만 나갔고 상승·급등 국면 신호는 0건이다. 이 스위치는
그 구조적 보호에 사람의 판단을 한 겹 더 얹는 것이다.

돌파(신고가) 계열은 운용에서 뺐다. 승률 56%로 넷 중 꼴찌였고
최악 −99.9%였다. 자본 보존을 앞에 두면 빠지는 게 맞다.
연구 기록은 ml/bull_breakout.py 에 남아 있다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import json
import os
import time

MODES = ("normal", "bull", "bear")

# 모드별로 어떤 계열을 켜고 끄는지. 모듈이 늘면 여기만 고친다.
# 급락반등(crash)은 **꺼져 있다.** 그 모듈의 엣지가 전부 미래참조였다 —
# ml/wonyotti_patterns.py 의 추세 필터가 신호봉이 아니라 체결봉의 종가를
# 보고 있었다. 진입은 그 봉의 시가에 하므로 모를 값이다. 고치니
# 거래당 +0.623% → -0.018%, 포트폴리오 51.43배 → 18.83배로 3종(21.52배)
# 보다 나빠졌다. 코드는 남겨두되 켜지지 않게 한다.
_ENABLED = {
    "normal": {"long": True, "short": True,  "div": True, "crash": False},
    "bull":   {"long": True, "short": False, "div": True, "crash": False},
    "bear":   {"long": False, "short": True, "div": True, "crash": False},
}

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PATH = os.path.join(ROOT, "state", "regime.json")

# ── 자동 폭락장 (ml/bear_leverage.py) ─────────────────────────────────
# 사람이 켜는 bear(롱 끔)와 별개로, 봇이 매일 BTC를 보고 판단한다.
# BTC 60일 수익률이 -15% 이하면 켜고, -10%를 넘으면 끈다(경계선에서
# 하루마다 켜졌다 꺼지는 것을 막는다). 전날까지 확정된 일봉 종가만 쓴다.
# 켜지면 롱을 끄지 않고 **배율만 2배로** 낮춘다 — 폭락장에서도 과매도
# 롱은 평균 플러스이고, 문제는 4배 청산(-24.5%)이었다. 2배면 -49.5%.
#   (2017~, 증거금 제약 포함)  끔 21배·1년손실 24% → 2배 36배·9%, 낙폭 21% 같음
AUTO_BEAR_N, AUTO_BEAR_ON, AUTO_BEAR_OFF = 60, -15.0, -10.0


# ── 급락 감지 (ml/crash_window.py) ────────────────────────────────────
# BTC 4시간봉 확정 종가가 직전 24시간(6봉) 최고 종가보다 10% 이상 낮으면,
# 그 봉 시작 시각부터 3일 동안 새 롱을 2배(증거금 비중은 같음)로 산다.
# 하루짜리 폭락(2020-03-12, 2022-11-08)은 60일 기준이 늦게 켜져 4배로
# 들어갔다. (2017~, 증거금 제약) 1년 손실확률 9% → 2%, 수익·낙폭 같음.
CRASH_BARS, CRASH_DROP, CRASH_DAYS = 6, -10.0, 3


def crash_drop(closes) -> float | None:
    """확정 4시간봉 종가들로 직전 24시간 최고 대비 마지막 종가의 낙폭(%)."""
    w = list(closes)[-CRASH_BARS:]
    if len(w) < CRASH_BARS:
        return None
    return (w[-1] / max(w) - 1) * 100


def auto_bear_update(prev_on: bool, r60: float) -> bool:
    """BTC 60일 수익률(%)로 자동 폭락장 상태를 갱신한다."""
    if r60 != r60:          # NaN
        return prev_on
    if not prev_on and r60 <= AUTO_BEAR_ON:
        return True
    if prev_on and r60 > AUTO_BEAR_OFF:
        return False
    return prev_on


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
