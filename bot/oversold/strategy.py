"""
bot/oversold/strategy.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
검증된 규칙 하나만 담는다 — 신호 판정 로직

    진입: 4시간봉 종가가 20기간 이동평균 대비 -12.26% 이하
    청산: 10봉(40시간) 경과   ← 목표가가 아니라 시간 청산이다
    손절: -40%  (대참사 방지용. 좁은 손절은 이 규칙을 망친다 — 아래 참조)
    대상: 메이저 12종

백테스트(2017~2026, 46종 풀링 후 메이저 한정 재검증):
    학습 2017~2023   519건  승률 61.7%  거래당 +2.32%
    홀드아웃 2024~26 120건  승률 80.0%  거래당 +4.76%   (무조건진입 44.4%)
    12/12 종목 개별 플러스 · 2022년은 손실년(40.4%, -1.57%)

주의 — 이 파일은 순수 함수만 둔다. 주문·키·네트워크는 executor.py에 있다.
백테스트와 실거래가 같은 코드로 신호를 만들어야 둘이 갈라지지 않는다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Sequence

MAJORS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "ADAUSDT", "DOTUSDT", "SOLUSDT",
          "BNBUSDT", "DOGEUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT", "TRXUSDT"]

INTERVAL      = "240"       # 바이빗 표기: 4시간
MA_PERIOD     = 20
ENTRY_THRESH  = -12.26      # 20기간선 대비 % — 학습구간에서 정한 값
HOLD_BARS     = 10          # 40시간
# 손절폭을 -8%로 잡으면 안 된다. 이 규칙은 "급락 직후" 진입이라 진입 후
# 변동성이 극단적이고, 보유 40시간 중 저가가 진입가 대비 얼마나 내려가는지
# (MAE) 중앙값이 -7.1%다. 즉 좁은 손절은 반등 전 흔들림에 먼저 걸린다.
#
#   손절   체결률   승률    거래당      (홀드아웃 120건)
#    -8%   44.2%   50.8%   +0.46%     ← 전략이 죽는다
#   -15%   14.2%   76.7%   +3.48%
#   -25%    4.2%   79.2%   +4.09%
#   -40%    0.0%   80.0%   +4.96%
#   없음    0.0%   80.0%   +4.96%
#
# -40%는 실질적으로 아무 거래도 자르지 않으면서, 봇이 죽었을 때와
# COVID 폭락(2020-03-12 LINK 저가 -100%) 같은 사건만 막는 역할을 한다.
# 2배 격리마진의 거래소 청산선(-50%)보다 앞서 걸리므로 청산을 피한다.
STOP_PCT      = -40.0       # 진입가 대비 %
SIDE          = "Buy"       # 롱 전용. 숏 규칙은 검증 통과 못 했다.


@dataclass(frozen=True)
class Signal:
    symbol: str
    ma20: float
    close: float
    vs_ma20: float
    bar_time: int           # 신호가 확정된 봉의 open time (ms)


def sma(values: Sequence[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def evaluate(symbol: str, closes: Sequence[float], bar_time: int) -> Optional[Signal]:
    """closes는 **확정된** 봉의 종가만. 진행 중인 봉을 넣으면 미래참조가 된다."""
    ma = sma(closes, MA_PERIOD)
    if ma is None or ma <= 0:
        return None
    close = closes[-1]
    vs = (close / ma - 1) * 100
    if vs > ENTRY_THRESH:
        return None
    return Signal(symbol=symbol, ma20=ma, close=close, vs_ma20=vs, bar_time=bar_time)


def stop_price(entry: float) -> float:
    return entry * (1 + STOP_PCT / 100)


def should_exit(bars_held: int) -> bool:
    return bars_held >= HOLD_BARS
