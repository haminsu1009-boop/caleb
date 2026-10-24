"""
ml/drawdown_fix.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
낙폭 47%를 줄이는 방법 — 숏 말고 무엇이 되는가

롱/숏 결합은 실패했다(ml/long_short.py). 거울상 숏 규칙은 모든
임계값에서 손실이고, 롱이 진 2022년에도 +0.14%로 아무것도 보전하지
못했다. 월별 상관 -0.18은 분산 효과라 부르기에도 약하다.

그래서 방향을 바꾼다. 낙폭이 언제 생겼는지 먼저 찾고, 그 구간을
'거래하지 않는' 방법을 찾는다. 지는 구간을 피하는 것이 지는 구간에
반대로 베팅하는 것보다 대개 쉽다.

시험하는 것:
    1. 낙폭이 실제로 발생한 시점과 원인
    2. 200기간선 아래에서는 진입 금지 (추세 필터)
    3. 배율을 낮추는 것과 필터를 거는 것 중 무엇이 효율적인가
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ml.edge_scan_all import load_all
from ml.majors_only import MAJORS

ROUND_TRIP, FUNDING_PER_8H, TRAIN_END, HOLD = 0.002, 0.0001, "2024-01-01", 10


def trades(thr=-12.26, hold=HOLD):
    raw = load_all("4h"); raw = raw[raw["symbol"].isin(MAJORS)]
    rows = []
    for sym, g in raw.groupby("symbol", sort=False):
        g = g.sort_values("datetime").reset_index(drop=True)
        c = g["close"].astype(float); o = g["open"].astype(float); l = g["low"].astype(float)
        vs = (c / c.rolling(20).mean() - 1) * 100
        ma200 = c.rolling(200).mean()
        above = (c > ma200).shift(1)                  # 확정봉 기준
        lock = -10**9
        for i in np.where(vs <= thr)[0]:
            if i <= lock or i + 1 + hold >= len(g):
                continue
            lock = i + hold
            e = o.iloc[i+1]
            rows.append({"symbol": sym, "datetime": g.loc[i, "datetime"],
                         "mae": (l.iloc[i+1:i+1+hold].min()/e - 1)*100,
                         "ret": (o.iloc[i+1+hold]/e - 1)*100,
                         "above200": bool(above.iloc[i]) if pd.notna(above.iloc[i]) else False,
                         "exit_dt": g.loc[i+1+hold, "datetime"]})
    d = pd.DataFrame(rows).sort_values("datetime").reset_index(drop=True)
    d["pnl"] = d["ret"] - ROUND_TRIP*100 - FUNDING_PER_8H*(hold*4/8)*100
    return d


def sim(d, lev, stop=-40.0, per_trade=0.15, max_gross=1.0):
    liq = -100.0/lev + 0.5
    eff = max(stop, liq)
    eq, peak, mdd, curve = 1.0, 1.0, 0.0, []
    openp = []
    for _, r in d.iterrows():
        openp = [p for p in openp if p[0] > r["datetime"]]
        gross = sum(p[1] for p in openp)
        margin = eq*per_trade; notional = margin*lev
        if gross + notional > eq*max_gross*lev:
            continue
        ret = eff if r["mae"] <= eff else r["pnl"]
        eq += max(margin*lev*ret/100, -margin)
        if eq <= 0: return 0.0, 1.0, curve
        peak = max(peak, eq); mdd = max(mdd, 1-eq/peak)
        curve.append((r["datetime"], eq, 1-eq/peak))
        openp.append((r["exit_dt"], notional))
    return eq, mdd, curve


def main():
    d = trades()
    print("=" * 92)
    print("  낙폭 원인 추적과 대안 — 메이저 12종, 4h, 진입당 15%, 손절 -40%")
    print("=" * 92)

    print("\n[1] 2배에서 최대낙폭이 언제 생겼는가")
    eq, mdd, curve = sim(d, 2)
    cv = pd.DataFrame(curve, columns=["dt", "eq", "dd"])
    worst = cv.loc[cv["dd"].idxmax()]
    print(f"    최종 {eq:,.1f}배 · 최대낙폭 {mdd*100:.1f}%  →  바닥 시점 {str(worst['dt'])[:10]}")
    cv["y"] = pd.DatetimeIndex(cv["dt"]).year
    print(f"\n    {'연도':6s}{'거래':>6s}{'연말자본':>11s}{'그해최대낙폭':>13s}")
    for y, g in cv.groupby("y"):
        print(f"    {y:<6d}{len(g):>6,}{g['eq'].iloc[-1]:>10,.2f}배{g['dd'].max()*100:>12.1f}%")

    print("\n[2] 200기간선 필터 — 하락추세에선 진입하지 않는다")
    filt = d[d["above200"]]
    print(f"    전체 {len(d)}거래 중 200선 위 진입만 남기면 {len(filt)}거래 "
          f"({len(filt)/len(d)*100:.0f}%)")
    print(f"\n    {'설정':22s}{'거래':>6s}{'승률':>8s}{'최종':>10s}{'최대낙폭':>10s}")
    print("    " + "-" * 56)
    for label, data in (("필터 없음", d), ("200선 위에서만", filt)):
        for lev in (1, 2, 3):
            e, m, _ = sim(data, lev)
            w = (data["pnl"] > 0).mean()*100
            print(f"    {label + f' {lev}배':22s}{len(data):>6,}{w:>7.1f}%{e:>9,.1f}배{m*100:>9.1f}%")
        print()

    print("[3] 필터 vs 배율 낮추기 — 같은 낙폭이면 어느 쪽이 더 버는가")
    opts = []
    for label, data in (("필터없음", d), ("200선필터", filt)):
        for lev in (1, 1.5, 2, 2.5, 3):
            e, m, _ = sim(data, lev)
            opts.append((label, lev, e, m))
    print(f"    {'설정':14s}{'배율':>6s}{'최종':>10s}{'최대낙폭':>10s}")
    for label, lev, e, m in sorted(opts, key=lambda x: x[3]):
        print(f"    {label:14s}{lev:>5.1f}x{e:>9,.1f}배{m*100:>9.1f}%")


if __name__ == "__main__":
    main()
