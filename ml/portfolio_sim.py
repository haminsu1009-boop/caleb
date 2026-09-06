"""
ml/portfolio_sim.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
포트폴리오 시뮬레이션 — 동시 진입을 제대로 다룬다

leverage_sim.py의 결함:
    거래를 하나씩 순차로 굴렸다. 그래서 639거래 × 3배에서 700만 배라는
    말도 안 되는 수가 나왔다. 실제로는 시장이 급락하면 메이저 12종의
    신호가 같은 날 동시에 뜬다. 순차 복리는 이 동시성을 무시하고,
    자본을 12번 재사용한 것처럼 계산한다.

    더 중요한 것은 위험 쪽이다. 동시에 12개를 들고 있으면 그 12개는
    독립이 아니다. 급락장에서 알트는 같이 움직인다. 한 번의 추가 급락에
    12개가 동시에 손실을 낸다.

이 시뮬레이션:
    - 시간순으로 진행하며 신호가 뜨면 진입, hold봉 뒤 청산
    - 총 노출 상한을 두고 초과분은 진입 포기 (실제 계좌와 같음)
    - 자본 대비 비율로 사이징하므로 복리는 자연스럽게 반영
    - 손절은 봉 종가 기준 근사 (실제 체결은 더 나쁠 수 있음)
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

TRAIN_END = "2024-01-01"


def run(sig: pd.DataFrame, lev: float, stop: float, per_trade: float,
        max_gross: float, start: float = 1.0):
    """sig: [datetime, symbol, pnl] — 시간순. per_trade/max_gross는 자본 대비 배수."""
    eq, peak, mdd = start, start, 0.0
    open_pos = []          # (청산시각, 명목, 수익률%)
    equity_curve = []
    events = sorted(set(sig["datetime"]))
    by_dt = {d: g for d, g in sig.groupby("datetime")}
    skipped = taken = 0

    for now in events:
        # 만기 도래분 청산
        still = []
        for exit_dt, notional, r in open_pos:
            if exit_dt <= now:
                eq += notional * max(r, stop) / 100
            else:
                still.append((exit_dt, notional, r))
        open_pos = still
        if eq <= 0:
            return 0.0, 1.0, taken, skipped, []

        gross = sum(n for _, n, _ in open_pos)
        for _, row in by_dt[now].iterrows():
            want = eq * per_trade * lev
            if gross + want > eq * max_gross * lev:
                skipped += 1
                continue
            open_pos.append((row["exit_dt"], want, row["pnl"]))
            gross += want
            taken += 1

        # 미실현 포함 자산 근사 (보유 중 평가손익은 최종 수익률로 선형 근사)
        peak = max(peak, eq)
        mdd = max(mdd, 1 - eq / peak)
        equity_curve.append((now, eq))

    for exit_dt, notional, r in open_pos:
        eq += notional * max(r, stop) / 100
    peak = max(peak, eq); mdd = max(mdd, 1 - eq / peak)
    return max(eq, 0.0), mdd, taken, skipped, equity_curve


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="4h")
    ap.add_argument("--threshold", type=float, default=-12.26)
    ap.add_argument("--hold", type=int, default=10)
    ap.add_argument("--per-trade", type=float, default=0.15)
    ap.add_argument("--max-gross", type=float, default=1.0)
    a = ap.parse_args()
    iv, thr, hold = a.interval, a.threshold, a.hold

    raw = load_all(iv); raw = raw[raw["symbol"].isin(MAJORS)]
    df = build(raw, [hold]).sort_values(["symbol", "datetime"]).reset_index(drop=True)
    df["pnl"] = net(df[f"ret{hold}"], hold, iv, "LONG")
    # 포지션 보유 중 같은 종목 재진입 금지
    keep = []
    for sym, g in df.groupby("symbol", sort=False):
        g = g.reset_index(drop=True)
        idx = np.where(g["vs_ma20"] <= thr)[0]
        lock = -10**9
        for i in idx:
            if i <= lock: continue
            if i + hold < len(g):
                keep.append({"datetime": g.loc[i, "datetime"], "symbol": sym,
                             "pnl": g.loc[i, "pnl"],
                             "exit_dt": g.loc[i + hold, "datetime"]})
            lock = i + hold
    sig = pd.DataFrame(keep).dropna(subset=["pnl"]).sort_values("datetime")

    print("=" * 98)
    print(f"  포트폴리오 시뮬레이션 — 메이저 12종, {iv}, 이격 {thr}%, {hold}봉 보유")
    print(f"  1거래 = 자본의 {a.per_trade*100:.0f}% × 배율   ·   총노출 상한 = 자본의 {a.max_gross*100:.0f}% × 배율")
    print("=" * 98)

    # 동시 보유 분포
    conc = []
    for _, r in sig.iterrows():
        conc.append(((sig["datetime"] <= r["datetime"]) & (sig["exit_dt"] > r["datetime"])).sum())
    print(f"\n  동시 보유 종목수:  중앙값 {int(np.median(conc))}   90%분위 {int(np.percentile(conc,90))}   최대 {max(conc)}")
    print(f"  → 급락 시 {max(conc)}종목이 한꺼번에 물린다. 이게 진짜 위험이다.")

    for label, data in (("전체 2017~2026", sig),
                        ("홀드아웃 2024~2026", sig[sig["datetime"] >= TRAIN_END])):
        yrs = (data["datetime"].max() - data["datetime"].min()).days / 365.25
        print(f"\n  [{label}]  신호 {len(data)}회 / {yrs:.1f}년 (연 {len(data)/yrs:.0f}회)")
        print(f"    {'손절':>6s}{'배율':>6s}{'최종':>10s}{'연복리':>9s}{'최대낙폭':>10s}{'체결':>7s}{'포기':>6s}   판정")
        print("    " + "-" * 70)
        for stop in (-8.0, -100.0):
            for lev in (1, 2, 3, 5):
                eq, mdd, tk, sk, _ = run(data, lev, stop, a.per_trade, a.max_gross)
                cagr = (eq ** (1/yrs) - 1) * 100 if eq > 0 else -100
                v = ("파산" if eq <= 0 else "안전" if mdd < .25 else
                     "감내 가능" if mdd < .5 else "위험" if mdd < .75 else "사실상 불가")
                st = "없음" if stop <= -99 else f"{stop:.0f}%"
                print(f"    {st:>6s}{lev:>5.0f}x{eq:>9,.1f}배{cagr:>8.0f}%{mdd*100:>9.1f}%"
                      f"{tk:>7,}{sk:>6,}   {v}")
            print()


if __name__ == "__main__":
    main()
