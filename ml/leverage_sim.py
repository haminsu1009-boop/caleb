"""
ml/leverage_sim.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
레버리지 상한 — 승률이 아니라 파산 확률로 정한다

승률 80%는 배율을 정해주지 않는다. 정하는 것은 두 가지다.
    1. 최악의 한 방 — 레버리지 L에서 -1/L 이동이면 청산이다.
       손절을 걸면 상한이 손절폭으로 바뀐다.
    2. 연속 손실 — 실제 데이터에서 13회 연속 손실이 있었다.
       한 번 질 때 자본의 x%를 잃는다면 13회 뒤 남는 것은 (1-x)^13이다.

여기서는 실제 거래 순서 그대로 복리로 굴려 배율별 최종 자본과
최대낙폭을 낸다. 동시에 여러 종목 신호가 뜨는 날이 있으므로
종목당 배분 비율도 같이 본다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ml.edge_scan_all import load_all, build
from ml.majors_only import MAJORS, net
from ml.episode_check import episodes

TRAIN_END = "2024-01-01"


def simulate(trades: pd.DataFrame, lev: float, stop: float, risk_frac: float):
    """trades: datetime 정렬된 pnl(%) 시리즈. stop은 음수(%) 손절폭."""
    eq, peak, mdd, liq = 1.0, 1.0, 0.0, 0
    for r in trades["pnl"].values:
        r_eff = max(r, stop)                 # 손절이 먼저 걸린다
        pl = r_eff / 100 * lev * risk_frac
        if pl <= -1.0:                        # 자본 전액 소진
            liq += 1
            return 0.0, 1.0, liq
        eq *= (1 + pl)
        peak = max(peak, eq)
        mdd = max(mdd, 1 - eq / peak)
    return eq, mdd, liq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="4h")
    ap.add_argument("--threshold", type=float, default=-12.26)
    ap.add_argument("--hold", type=int, default=10)
    ap.add_argument("--risk", type=float, default=0.25,
                    help="한 거래에 투입하는 자본 비율 (동시 신호 대비 분산)")
    a = ap.parse_args()
    iv, thr, hold = a.interval, a.threshold, a.hold

    raw = load_all(iv); raw = raw[raw["symbol"].isin(MAJORS)]
    df = build(raw, [hold]).sort_values(["symbol", "datetime"]).reset_index(drop=True)
    df["pnl"] = net(df[f"ret{hold}"], hold, iv, "LONG")
    ep = episodes(df, "vs_ma20", thr, hold)
    df["is_ep"] = [(s, d) in ep for s, d in zip(df["symbol"], df["datetime"])]
    tr = df[(df["vs_ma20"] <= thr) & df["is_ep"]].dropna(subset=["pnl"]).sort_values("datetime")

    full = tr
    ho = tr[tr["datetime"] >= TRAIN_END]

    print("=" * 98)
    print(f"  레버리지 시뮬레이션 — 메이저 12종, {iv}, 이격 {thr}%, {hold}봉 보유")
    print(f"  한 거래당 자본의 {a.risk*100:.0f}% 투입 (동시 신호 분산 가정)")
    print("=" * 98)

    for label, data in (("전체 2017~2026", full), ("홀드아웃 2024~2026", ho)):
        print(f"\n  [{label}]  거래 {len(data)}회  최악 1회 {data['pnl'].min():+.1f}%")
        print(f"    {'손절':>7s}{'배율':>6s}{'최종자본':>11s}{'최대낙폭':>10s}   판정")
        print("    " + "-" * 58)
        for stop in (-8.0, -12.0, -100.0):
            for lev in (1, 2, 3, 5, 10):
                eq, mdd, liq = simulate(data, lev, stop, a.risk)
                if liq:
                    verdict = "💀 파산"
                    eqs = "0"
                else:
                    eqs = f"{eq:,.1f}배"
                    verdict = ("안전" if mdd < 0.25 else
                               "감내 가능" if mdd < 0.5 else
                               "위험" if mdd < 0.75 else "사실상 불가")
                st = "없음" if stop <= -99 else f"{stop:.0f}%"
                print(f"    {st:>7s}{lev:>5.0f}x{eqs:>11s}{mdd*100:>9.1f}%   {verdict}")
            print()


if __name__ == "__main__":
    main()
