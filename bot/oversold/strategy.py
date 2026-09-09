"""
bot/oversold/strategy.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
검증된 규칙 하나만 담는다 — 신호 판정 로직

    진입: 4시간봉 종가가 20기간 이동평균 대비 -12.26% 이하
          1차 30% 즉시 체결, 1차 진입가 대비 -5% 더 빠지면 2차 70% 추가
          (분할매수 — ml/scale_in.py, ml/scale_in_portfolio.py 검증)
    청산: 20봉(80시간) 경과   ← 목표가가 아니라 시간 청산이다 (10봉 → 20봉으로 상향)
    손절: -40%  (대참사 방지용. 좁은 손절은 이 규칙을 망친다 — 아래 참조)
    대상: 46종 (delisted 4종 제외 실거래 42종)

백테스트 이력 (2017~2026, 46종 풀링):
    v1 — 메이저 12종·일괄매수·10봉:
         홀드아웃 2024~26  120건  승률 80.0%  거래당 +4.76%  (무조건진입 44.4%)
    v2 — 46종·일괄매수·20봉 (이 파일 이전 버전):
         홀드아웃            n=467  승률 68.7%  거래당 +4.10%
    v3 — 46종·분할매수(30%+트리거시70%)·20봉 (현재):
         홀드아웃            승률 76.9% (하한 73.5%)  거래당 +6.51%  최악 -50.1%
         포트폴리오(1배, 20종동시): 8.8년 4.8배, 연복리 20%, 낙폭 31.5%(장중 53.1%)
         (트리거 -8%로 하면 4.5배·낙폭 29.7%/48.4%로 낙폭은 더 낮다 —
          -5%를 기본값으로 쓴 건 거래당 검증표와의 일관성 때문이다)
         → 일괄매수(2.4배, 낙폭 37.3%)보다 수익도 높고 낙폭도 낮다.
           2차 매수가 안 걸린 신호는 자본의 30%만 투입된 채 끝나므로
           분할이 자동 사이징 역할도 한다.

주의 — 이 파일은 순수 함수만 둔다. 주문·키·네트워크는 executor.py에 있다.
백테스트와 실거래가 같은 코드로 신호를 만들어야 둘이 갈라지지 않는다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Sequence

# 백테스트에 쓴 전체 46종 (2017~2026, 바이낸스 현물 상장 이력 기준).
# ml/path_to_100x.py의 all_symbols()와 동일해야 백테스트-실거래가
# 갈리지 않는다.
ALL_SYMBOLS = [
    "AAVEUSDT", "ADAUSDT", "ALGOUSDT", "APTUSDT", "ARBUSDT", "ATOMUSDT",
    "AVAXUSDT", "AXSUSDT", "BNBUSDT", "BTCUSDT", "CHZUSDT", "DOGEUSDT",
    "DOTUSDT", "EGLDUSDT", "EOSUSDT", "ETCUSDT", "ETHUSDT", "FILUSDT",
    "FLOWUSDT", "FTMUSDT", "GRTUSDT", "HBARUSDT", "ICPUSDT", "INJUSDT",
    "IOTAUSDT", "LINKUSDT", "LTCUSDT", "MANAUSDT", "MATICUSDT", "MKRUSDT",
    "NEARUSDT", "NEOUSDT", "OPUSDT", "QNTUSDT", "RUNEUSDT", "SANDUSDT",
    "SEIUSDT", "SOLUSDT", "SUIUSDT", "THETAUSDT", "TIAUSDT", "TRXUSDT",
    "UNIUSDT", "VETUSDT", "XLMUSDT", "XRPUSDT",
]

# 이 4종은 티커 자체가 사라졌다 — MATIC→POL, FTM→S 로 리브랜딩,
# EOS·MKR은 상장폐지/전환됐다. 옛 심볼로는 바이빗에서 거래가 안
# 되므로 실거래 목록에서는 뺀다. 백테스트 재현이 필요하면
# ALL_SYMBOLS를 쓴다(이 4종의 과거 데이터는 남아 있다 — 생존자
# 편향 위험이 있으니 결과 해석 시 감안할 것, 46종 중 4종뿐이라
# 영향은 제한적이다).
_DELISTED = {"MATICUSDT", "FTMUSDT", "EOSUSDT", "MKRUSDT"}
SYMBOLS = [s for s in ALL_SYMBOLS if s not in _DELISTED]

# 이전 버전과의 호환 별칭 — 다른 코드가 아직 MAJORS를 참조할 수 있다.
MAJORS = SYMBOLS

INTERVAL      = "240"       # 바이빗 표기: 4시간
MA_PERIOD     = 20
ENTRY_THRESH  = -12.26      # 20기간선 대비 % — 학습구간에서 정한 값
HOLD_BARS     = 20          # 80시간(3.3일). 10봉보다 이 값이 낫다(ml/btc_exit_search.py,
                             # ml/sim_correct.py) — 포지션 자리를 2배 오래 잡지만
                             # 거래당 수익 개선이 그보다 크다.

# ── 분할매수 ─────────────────────────────────────────────────────
# "더 빠졌을 때만 추가한다"가 핵심이다. 시간 기준 분할(예: 3봉 뒤
# 무조건 추가)은 평단을 오히려 올려서 전부 손해였다(ml/scale_in.py).
# 가격 기준 분할만 효과가 있었고, 그중 30%+(트리거시)70%가 최선이었다.
SCALE_IN_FIRST_FRAC  = 0.30   # 1차 매수 비율 (나머지는 트리거 도달 시 2차)
SCALE_IN_TRIGGER_PCT = -5.0   # 1차 진입가 대비 이만큼 더 빠지면 2차 매수

# 손절폭을 -8%로 잡으면 안 된다. 이 규칙은 "급락 직후" 진입이라 진입 후
# 변동성이 극단적이고, 보유 중 저가가 진입가 대비 얼마나 내려가는지
# (MAE) 중앙값이 -7.1%다. 즉 좁은 손절은 반등 전 흔들림에 먼저 걸린다.
#
#   손절   체결률   승률    거래당      (메이저12종·10봉 기준 참고값)
#    -8%   44.2%   50.8%   +0.46%     ← 전략이 죽는다
#   -15%   14.2%   76.7%   +3.48%
#   -25%    4.2%   79.2%   +4.09%
#   -40%    0.0%   80.0%   +4.96%
#   없음    0.0%   80.0%   +4.96%
#
# -40%는 실질적으로 아무 거래도 자르지 않으면서, 봇이 죽었을 때와
# COVID 폭락(2020-03-12 LINK 저가 -100%) 같은 사건만 막는 역할을 한다.
# 2배 격리마진의 거래소 청산선(-50%)보다 앞서 걸리므로 청산을 피한다.
STOP_PCT      = -40.0       # 진입가(분할 완료 후엔 평단) 대비 %
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


def scale_in_trigger_price(first_entry: float) -> float:
    """1차 체결가 기준 2차 매수가 발동되는 가격."""
    return first_entry * (1 + SCALE_IN_TRIGGER_PCT / 100)


def blended_entry(price1: float, qty1: float, price2: float, qty2: float) -> float:
    """두 번에 나눠 산 뒤의 수량가중 평균 단가."""
    total_qty = qty1 + qty2
    if total_qty <= 0:
        return price1
    return (price1 * qty1 + price2 * qty2) / total_qty


def stop_price(entry: float) -> float:
    return entry * (1 + STOP_PCT / 100)


def should_exit(bars_held: int) -> bool:
    return bars_held >= HOLD_BARS
