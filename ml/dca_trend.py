"""
ml/dca_trend.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
추세추종 전략 적립식(DCA) 시뮬레이션
초기 100만원 + 매월 30만원, 2017년 ~ 현재

dca_backtest.py(ML 신호용)와 달리 여기서는 trend_backtest.py의
추세추종 전략을 그대로 쓴다. 즉 고정 익절 없이 추세가 꺾일 때까지
들고 가고, 자본 전액을 굴리며, 롱·숏 양방향으로 돈다.

자본 회계:
    매월 초 적립금을 넣고, 그 자본 전체가 그날의 전략 수익률로 복리된다.
        C_t+1 = (C_t + 적립금_t) × (1 + 전략수익률_t)
    Buy&Hold는 같은 적립금으로 그날 종가에 현물을 사서 계속 보유한다.

⚠️ 해석 주의
    전체 기간(2017~2026) 숫자는 2017~2021 대상승장이 지배한다.
    또 전략 파라미터를 고른 구간이 이 안에 포함돼 있어 낙관 편향이 있다.
    그래서 구간별(강세장/약세장/사이클고점 이후) 결과를 함께 출력한다.

사용법:
    python ml/dca_trend.py
    python ml/dca_trend.py --leverage 1.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ml.trend_backtest import (
    load, sig_donchian, sig_ma_cross, sig_supertrend, FEE, SLIP,
)

INITIAL = 1_000_000
MONTHLY =   300_000
SYMS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]

STRATS = {
    "MA교차(20,100)":    lambda d: sig_ma_cross(d, 20, 100),
    "MA교차(10,50)":     lambda d: sig_ma_cross(d, 10, 50),
    "MA교차(50,200)":    lambda d: sig_ma_cross(d, 50, 200),
    "Donchian(55,20)":  lambda d: sig_donchian(d, 55, 20),
    "Donchian(100,25)": lambda d: sig_donchian(d, 100, 25),
    "Supertrend(10,3)": lambda d: sig_supertrend(d, 10, 3.0),
}

PERIODS = [
    ("전체 (2017~현재)",        "2017-01-01", "2026-12-31"),
    ("강세장 (2020~2021)",      "2020-01-01", "2021-12-31"),
    ("약세장 (2022)",           "2022-01-01", "2022-12-31"),
    ("회복장 (2023~2025.09)",   "2023-01-01", "2025-10-05"),
    ("고점이후 (2025.10~현재)", "2025-10-06", "2026-12-31"),
]


# ══════════════════════════════════════════════════════════════
# 심볼별 일간 수익률 (전략 / Buy&Hold)
# ══════════════════════════════════════════════════════════════

def daily_returns(sym: str, sigfn, leverage: float = 1.0) -> pd.DataFrame:
    df = load(sym, "1d")[["datetime", "open", "high", "low", "close"]].copy()
    pos = sigfn(df)
    c = df["close"].values

    ret = np.zeros(len(c))
    ret[1:] = c[1:] / c[:-1] - 1.0

    held = np.roll(pos, 1); held[0] = 0.0
    turn = np.abs(np.diff(np.concatenate([[0.0], pos])))
    s = held * ret * leverage - turn * (FEE + SLIP) * leverage

    return pd.DataFrame({"datetime": df["datetime"], "s": s, "b": ret}).set_index("datetime")


def portfolio_returns(sigfn, leverage: float = 1.0) -> pd.DataFrame:
    """6종 동일가중 — 상장 전 심볼은 자동 제외(평균에서 NaN 무시)"""
    frames = [daily_returns(s, sigfn, leverage) for s in SYMS]
    S = pd.concat([f["s"].rename(s) for f, s in zip(frames, SYMS)], axis=1)
    B = pd.concat([f["b"].rename(s) for f, s in zip(frames, SYMS)], axis=1)
    return pd.DataFrame({"s": S.mean(axis=1, skipna=True),
                         "b": B.mean(axis=1, skipna=True)}).fillna(0.0)


# ══════════════════════════════════════════════════════════════
# 적립식 자본 시뮬레이션
# ══════════════════════════════════════════════════════════════

def dca(returns: pd.Series) -> dict:
    """매월 초 적립 후 그날 수익률로 복리"""
    idx = returns.index
    months = pd.DatetimeIndex(idx).to_period("M")

    capital = 0.0
    contributed = 0.0
    last_month = None
    curve = []

    for i, r in enumerate(returns.values):
        m = months[i]
        if last_month is None:
            capital += INITIAL; contributed += INITIAL; last_month = m
        elif m != last_month:
            capital += MONTHLY; contributed += MONTHLY; last_month = m

        capital *= (1.0 + r)
        capital = max(capital, 0.0)          # 청산 하한
        curve.append(capital)

    curve = np.array(curve)
    peak = np.maximum.accumulate(np.maximum(curve, 1e-9))
    mdd = (curve / peak - 1).min() * 100

    return {"final": capital, "contributed": contributed,
            "mdd": mdd, "curve": curve,
            "profit": capital - contributed,
            "ret_pct": (capital / contributed - 1) * 100 if contributed else 0.0}


def slice_period(df: pd.DataFrame, lo: str, hi: str) -> pd.DataFrame:
    return df[(df.index >= lo) & (df.index <= hi)]


# ══════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--leverage", type=float, default=1.0)
    a = ap.parse_args()

    print("=" * 104)
    print(f"  추세추종 적립식 시뮬레이션 — 초기 {INITIAL:,}원 + 매월 {MONTHLY:,}원  (레버리지 {a.leverage:.0f}x)")
    print("=" * 104)

    cache = {name: portfolio_returns(fn, a.leverage) for name, fn in STRATS.items()}
    bh_series = list(cache.values())[0]["b"]

    for plabel, lo, hi in PERIODS:
        bh_r = slice_period(bh_series.to_frame("b"), lo, hi)["b"]
        if len(bh_r) < 30:
            continue
        bh = dca(bh_r)

        print(f"\n{'='*104}")
        print(f"  {plabel}   ({bh_r.index[0].date()} ~ {bh_r.index[-1].date()}, {len(bh_r)}일)")
        print(f"{'='*104}")
        print(f"  {'전략':20s}{'투입원금':>14s}{'최종자산':>16s}{'손익':>16s}{'수익률':>10s}{'MDD':>9s}{'BH대비':>12s}")
        print("  " + "-" * 98)
        print(f"  {'[기준] 6종 존버':20s}{bh['contributed']:>13,.0f}원{bh['final']:>15,.0f}원"
              f"{bh['profit']:>15,.0f}원{bh['ret_pct']:>9.1f}%{bh['mdd']:>8.1f}%{'—':>12s}")

        rows = []
        for name, pr in cache.items():
            r = slice_period(pr, lo, hi)["s"]
            if len(r) < 30:
                continue
            d = dca(r)
            rows.append((name, d))
        rows.sort(key=lambda x: -x[1]["final"])

        for name, d in rows:
            diff = d["final"] - bh["final"]
            flag = "✅" if diff > 0 else "  "
            print(f"  {name:20s}{d['contributed']:>13,.0f}원{d['final']:>15,.0f}원"
                  f"{d['profit']:>15,.0f}원{d['ret_pct']:>9.1f}%{d['mdd']:>8.1f}%"
                  f"{diff:>+11,.0f}원 {flag}")

    print(f"\n{'='*104}")
    print("  ⚠️ 전체 기간 수치는 2017~2021 대상승장이 지배하며, 전략 파라미터를")
    print("     고른 구간이 포함돼 낙관 편향이 있다. 구간별 결과를 함께 볼 것.")
    print("=" * 104)


if __name__ == "__main__":
    main()
