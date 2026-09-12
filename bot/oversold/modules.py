"""
bot/oversold/modules.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
봇이 굴리는 세 전략 — 서로 다른 시간봉, 하나의 자본

  과매도 롱    4시간봉  20기간선 −12.26% 이하 → 분할진입 → 볼린저 상단/20봉
  주봉 숏      주봉     MA60주 이탈 + 4연속 음봉 → 4주 보유
  상승 다이버   일봉     저점↓ RSI↑ 격차 ≥8p → 10일 보유

롱은 strategy.py에 그대로 두고, 여기에는 숏과 다이버전스를 담는다.
셋은 일간 수익 상관이 0.003 / −0.001 / −0.001로 사실상 무상관이고,
그래서 셋을 합쳐도 낙폭이 21.6%로 같은데 수익만 3.14배 → 21.52배가
된다(ml/unified_pool.py).

주봉은 거래소의 주봉 캔들을 쓰지 않고 **일봉을 받아서 직접 주봉으로
묶는다.** 거래소마다 주의 시작 요일이 다를 수 있고, 그러면 봇이
백테스트와 다른 봉을 보게 된다. 같은 일봉에서 같은 규칙으로 묶으면
어긋날 자리가 없다. 다이버전스도 일봉을 쓰므로 심볼당 일봉 한 번
조회로 둘 다 판정한다.

손절은 파국 대비용으로만 건다. 검증 결과 숏에 손절을 걸면 모든
수준에서 성적이 나빠졌다(−30%에서도 거래당 12.02% → 10.49%).
숏은 먼저 역행했다가 돌아오는 패턴이라 손절이 그 흔들림에 먼저
걸린다. 그래서 −50%에 건다 — 8.9년 최악 거래가 −45.6%였으므로
과거 어떤 거래도 자르지 않는다. 무기한 숏의 무한 손실만 막는
보험이다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Sequence
import numpy as np
import pandas as pd

# ── 주봉 숏 ──────────────────────────────────────────────────────
SHORT_MA_WEEKS = 60       # 주봉 이동평균 기간
SHORT_STREAK = 4          # 이탈 후 연속 음봉 개수
SHORT_HOLD_WEEKS = 4      # 보유 주
SHORT_MAX_CONCURRENT = 1  # 같은 주에 동시 진입 상한
# 동시 2건이 터진 2020-03-23(TRX −31.1% · IOTA −45.6%)에서 그 주가
# −76.7%p였다. 주당 1건으로 묶으면 −31.1%p가 되고, 거래당 비용은
# 12.02% → 11.45%로 0.57%p뿐이다.

# ── 상승 다이버전스 ───────────────────────────────────────────────
DIV_RSI_PERIOD = 14
DIV_PIVOT_K = 5           # 스윙 확정에 필요한 좌우 봉수
DIV_GAP = 8.0             # RSI 격차 최소 요구치(포인트)
DIV_MAX_GAP = 120         # 두 스윙 사이 최대 봉수
DIV_HOLD_DAYS = 10
DIV_CONFIRM_WINDOW = 5    # 스윙 확정 후 양봉을 기다리는 봉수

CATASTROPHE_STOP = 50.0   # 진입가 대비 % (양수). 파국 대비용.


@dataclass(frozen=True)
class Signal:
    symbol: str
    kind: str          # "short" | "div"
    side: str          # "Sell" | "Buy"
    price: float       # 신호가 확정된 봉의 종가
    bar_time: int      # 그 봉의 시작 시각 (ms)
    hold_bars: int     # 이 모듈 시간봉 기준 보유 봉수


def rsi(c: Sequence[float], n: int = DIV_RSI_PERIOD) -> np.ndarray:
    """ml/short_setups.rsi 와 같은 계산(EWM, adjust=False)."""
    c = np.asarray(c, dtype=float)
    d = np.diff(c, prepend=c[0])
    au = pd.Series(np.where(d > 0, d, 0.0)).ewm(alpha=1/n, adjust=False).mean().values
    ad = pd.Series(np.where(d < 0, -d, 0.0)).ewm(alpha=1/n, adjust=False).mean().values
    rs = np.divide(au, ad, out=np.full_like(au, np.inf), where=ad > 0)
    out = 100 - 100 / (1 + rs)
    out[:n] = np.nan
    return out


def to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """일봉 → 주봉. ml/short_setups.to_weekly 와 같은 규칙(W-MON)."""
    x = daily.set_index("dt")
    return pd.DataFrame({
        "open": x["open"].resample("W-MON").first(),
        "high": x["high"].resample("W-MON").max(),
        "low": x["low"].resample("W-MON").min(),
        "close": x["close"].resample("W-MON").last(),
    }).dropna().reset_index()


def short_signals(w: pd.DataFrame, ma=SHORT_MA_WEEKS,
                  streak=SHORT_STREAK) -> np.ndarray:
    """MA 이탈 마감 후 streak개 연속 음봉. 판정은 종가, 체결은 다음 봉 시가.

    '이탈 마감'은 그 봉에서 **처음** 아래로 내려간 것이다. 이미 한참
    아래에 있는 상태는 이탈이 아니다.
    """
    c, o = w["close"].values, w["open"].values
    m = pd.Series(c).rolling(ma).mean().values
    below = c < m
    broke = below & ~np.r_[False, below[:-1]]
    bear = c < o
    n = len(c)
    sig = []
    for i in np.where(broke)[0]:
        k, j = 0, i + 1
        while j < n and bear[j] and below[j]:
            k += 1
            if k == streak:
                sig.append(j)
                break
            j += 1
    return np.array(sig, dtype=int)


def div_signals(d: pd.DataFrame, *, period=DIV_RSI_PERIOD, k=DIV_PIVOT_K,
                gap=DIV_GAP, max_gap=DIV_MAX_GAP) -> np.ndarray:
    """상승 다이버전스 — 저점은 낮아지는데 RSI는 높아진다.

    스윙 저점은 우측 k봉이 지나야 확정되므로 진입 판정을 b+k로
    미룬다(미래참조 방지). 거기서부터 최대 5봉 안에 양봉이 마감하면
    그 봉을 신호로 삼는다.
    """
    c, o, l = d["close"].values, d["open"].values, d["low"].values
    r = rsi(c, period)
    n = len(c)
    piv = []
    for i in range(k, n - k):
        w = l[i - k:i + k + 1]
        if l[i] == w.min() and (w == l[i]).sum() == 1:
            piv.append(i)
    bull_bar = c > o
    out = []
    for a, b in zip(piv[:-1], piv[1:]):
        if b - a > max_gap or np.isnan(r[a]) or np.isnan(r[b]):
            continue
        if not (l[b] < l[a] and (r[b] - r[a]) >= gap):
            continue
        j, end = b + k, min(b + k + DIV_CONFIRM_WINDOW, n)
        while j < end and not bull_bar[j]:
            j += 1
        if j < end and bull_bar[j]:
            out.append(j)
    return np.array(sorted(set(out)), dtype=int)


def stop_price(entry: float, side: str, pct: float = CATASTROPHE_STOP) -> float:
    """파국 대비 손절. 숏은 위, 롱은 아래."""
    return entry * (1 + pct / 100) if side == "Sell" else entry * (1 - pct / 100)


def evaluate_short(symbol: str, daily: pd.DataFrame) -> Optional[Signal]:
    """가장 최근 확정 주봉이 숏 신호인가."""
    w = to_weekly(daily)
    if len(w) < SHORT_MA_WEEKS + SHORT_STREAK + 2:
        return None
    sig = short_signals(w)
    last = len(w) - 1
    if len(sig) == 0 or sig[-1] != last:
        return None
    return Signal(symbol=symbol, kind="short", side="Sell",
                  price=float(w["close"].iloc[last]),
                  bar_time=int(pd.Timestamp(w["dt"].iloc[last]).value // 10**6),
                  hold_bars=SHORT_HOLD_WEEKS)


def evaluate_div(symbol: str, daily: pd.DataFrame) -> Optional[Signal]:
    """가장 최근 확정 일봉이 상승 다이버전스 신호인가."""
    if len(daily) < DIV_MAX_GAP + DIV_PIVOT_K + 2:
        return None
    sig = div_signals(daily)
    last = len(daily) - 1
    if len(sig) == 0 or sig[-1] != last:
        return None
    return Signal(symbol=symbol, kind="div", side="Buy",
                  price=float(daily["close"].iloc[last]),
                  bar_time=int(pd.Timestamp(daily["dt"].iloc[last]).value // 10**6),
                  hold_bars=DIV_HOLD_DAYS)
