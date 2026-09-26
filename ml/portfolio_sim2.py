"""
ml/portfolio_sim2.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
최종 시뮬레이션 — 봉 안 저가로 손절·청산을 판정한다

portfolio_sim.py의 결함:
    손절을 `max(종가수익률, -8%)`로 근사했다. 실제 손절은 보유 중
    저가가 손절선을 스치는 순간 체결된다. 재생 테스트에서 20건 전부
    손절된 것을 보고 발견했다.

    이 차이는 사소하지 않다. -8% 손절은 종가 기준으로는 거의 안 걸리지만
    저가 기준으로는 44%가 걸리고, 승률이 80% → 51%로 무너진다.
    이 규칙은 "급락 직후" 진입이라 진입 후 변동성이 극단적으로 높다.
    좁은 손절은 반등 전의 흔들림에 먼저 걸린다.

여기서 반영한 것:
    · MAE(보유 중 최저가)로 손절 체결 판정
    · 격리마진 가정 — 청산되면 그 포지션 증거금만 잃는다 (전액 아님)
    · 레버리지 L에서 -100/L% 이동이면 청산
    · 동시 진입·총노출 상한·복리
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ml.mae_analysis import build_trades

ROUND_TRIP = 0.002
FUNDING_PER_8H = 0.0001
TRAIN_END = "2024-01-01"


def trade_return(row, lev, stop):
    """레버리지 반영 전 가격 수익률(%)을 낸다. 손절·청산은 저가로 판정."""
    liq = -100.0 / lev + 0.5          # 유지증거금 감안해 약간 앞당김
    eff_stop = max(stop, liq) if stop is not None else liq
    if row["mae"] <= eff_stop:
        return eff_stop, (eff_stop <= liq)
    return row["close_ret"], False


def simulate(tr, lev, stop, per_trade, max_gross, hold=10):
    fee = ROUND_TRIP * 100 + FUNDING_PER_8H * (hold * 4 / 8.0) * 100
    eq, peak, mdd, liqs = 1.0, 1.0, 0.0, 0
    open_pos = []
    for _, row in tr.iterrows():
        now = row["datetime"]
        open_pos = [p for p in open_pos if p[0] > now] if open_pos else []
        gross = sum(p[1] for p in open_pos)
        margin = eq * per_trade
        notional = margin * lev
        if gross + notional > eq * max_gross * lev:
            continue
        r, was_liq = trade_return(row, lev, stop)
        pl = margin * lev * (r - fee) / 100
        pl = max(pl, -margin)                     # 격리마진: 증거금까지만 잃는다
        if was_liq:
            liqs += 1
        eq += pl
        if eq <= 0:
            return 0.0, 1.0, liqs
        peak = max(peak, eq); mdd = max(mdd, 1 - eq / peak)
        open_pos.append((row["exit_dt"], notional))
    return eq, mdd, liqs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=int, default=10)
    ap.add_argument("--per-trade", type=float, default=0.15)
    ap.add_argument("--max-gross", type=float, default=1.0)
    a = ap.parse_args()

    t = build_trades(hold=a.hold).sort_values("datetime").reset_index(drop=True)
    t["exit_dt"] = t["datetime"] + pd.Timedelta(hours=4 * a.hold)

    print("=" * 96)
    print(f"  최종 시뮬레이션 — 손절/청산을 봉 안 저가로 판정")
    print(f"  메이저 12종 · 4h · 이격 -12.26% · {a.hold}봉 보유 · "
          f"진입당 {a.per_trade*100:.0f}% · 격리마진")
    print("=" * 96)

    for label, d in (("전체 2017~2026", t),
                     ("홀드아웃 2024~2026", t[t["datetime"] >= TRAIN_END])):
        yrs = (d["datetime"].max() - d["datetime"].min()).days / 365.25
        print(f"\n  [{label}]  {len(d)}거래 / {yrs:.1f}년")
        print(f"    {'손절':>7s}{'배율':>6s}{'최종':>11s}{'연복리':>9s}{'최대낙폭':>10s}{'청산':>6s}   판정")
        print("    " + "-" * 66)
        best = None
        for stop in (-8.0, -15.0, -25.0, None):
            for lev in (1, 2, 3, 5):
                eq, mdd, lq = simulate(d, lev, stop, a.per_trade, a.max_gross, a.hold)
                cagr = (eq ** (1 / yrs) - 1) * 100 if eq > 0 else -100
                v = ("파산" if eq <= 0 else "안전" if mdd < .25 else
                     "감내 가능" if mdd < .5 else "위험" if mdd < .75 else "사실상 불가")
                st = "없음" if stop is None else f"{stop:.0f}%"
                print(f"    {st:>7s}{lev:>5.0f}x{eq:>10,.1f}배{cagr:>8.0f}%"
                      f"{mdd*100:>9.1f}%{lq:>6}   {v}")
                if label.startswith("전체") and mdd < 0.5 and (best is None or cagr > best[0]):
                    best = (cagr, stop, lev, mdd, eq)
            print()
        if best:
            cagr, stop, lev, mdd, eq = best
            st = "없음" if stop is None else f"{stop:.0f}%"
            print(f"    → 낙폭 50% 이내에서 최고 수익: 손절 {st} · {lev}배 "
                  f"({eq:,.1f}배, 연복리 {cagr:.0f}%, 낙폭 {mdd*100:.1f}%)")


if __name__ == "__main__":
    main()
