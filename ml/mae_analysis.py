"""
ml/mae_analysis.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
최대역행폭(MAE) — 손절이 실제로 어디서 걸리는지

portfolio_sim.py는 손절을 `max(수익률, -8%)`로 근사했다. 즉 **종가
기준 최종 수익률**이 -8%보다 나쁘면 -8%로 잘랐다. 이건 틀렸다.
실제 손절은 보유 중 **봉 안의 저가**가 손절선을 스치는 순간 체결된다.

재생 테스트에서 20건이 전부 손절됐다. 이 규칙은 "12% 급락 직후"에
진입하므로 진입 시점의 변동성이 극단적으로 높고, 40시간 안에 추가로
8% 더 빠지는 일이 흔하다. 종가로는 회복해도 저가는 이미 손절선을
지나간 뒤다.

이 스크립트는 각 거래의 진입가 대비 보유기간 중 최저가(MAE)를 재서
손절폭별로 몇 %가 잘려나가는지, 그리고 손절 후 실제 기대값이
얼마인지 계산한다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ml.edge_scan_all import load_all
from ml.majors_only import MAJORS

ROUND_TRIP = 0.002
FUNDING_PER_8H = 0.0001
TRAIN_END = "2024-01-01"


def build_trades(interval="4h", thr=-12.26, hold=10):
    raw = load_all(interval)
    raw = raw[raw["symbol"].isin(MAJORS)]
    rows = []
    for sym, g in raw.groupby("symbol", sort=False):
        g = g.sort_values("datetime").reset_index(drop=True)
        c = g["close"].astype(float)
        ma = c.rolling(20).mean()
        vs = (c / ma - 1) * 100
        o, h, l = g["open"].astype(float), g["high"].astype(float), g["low"].astype(float)
        idx = np.where(vs <= thr)[0]
        lock = -10**9
        for i in idx:                       # 보유 중 재진입 금지
            if i <= lock or i + 1 + hold >= len(g):
                continue
            lock = i + hold
            entry = o.iloc[i + 1]           # 다음 봉 시가 진입
            seg = slice(i + 1, i + 1 + hold)
            mae = (l.iloc[seg].min() / entry - 1) * 100     # 최대역행
            mfe = (h.iloc[seg].max() / entry - 1) * 100     # 최대순행
            exit_px = o.iloc[i + 1 + hold]
            rows.append({"symbol": sym, "datetime": g.loc[i, "datetime"],
                         "entry": entry, "mae": mae, "mfe": mfe,
                         "close_ret": (exit_px / entry - 1) * 100})
    return pd.DataFrame(rows)


def net(r, hold, side="LONG"):
    fee = FUNDING_PER_8H * (hold * 4 / 8.0) * 100
    return r - ROUND_TRIP * 100 - fee


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=int, default=10)
    a = ap.parse_args()
    t = build_trades(hold=a.hold)
    ho = t[t["datetime"] >= TRAIN_END]

    print("=" * 96)
    print(f"  최대역행폭 분석 — 메이저 12종, 4h, 이격 -12.26%, {a.hold}봉 보유")
    print(f"  거래 {len(t):,}건 (홀드아웃 {len(ho):,}건)")
    print("=" * 96)

    print(f"\n[1] 보유 중 최저가가 진입가 대비 얼마나 내려가는가 (MAE)")
    for label, d in (("전체", t), ("홀드아웃", ho)):
        q = d["mae"].quantile([.5, .25, .1, .05, .01])
        print(f"    {label:8s} 중앙값 {q[.5]:>6.1f}%   하위25% {q[.25]:>6.1f}%   "
              f"하위10% {q[.1]:>6.1f}%   최악 {d['mae'].min():>6.1f}%")

    print(f"\n[2] 손절폭별로 몇 %가 잘리는가 — 그리고 잘린 뒤 기대값")
    print(f"    {'손절':>7s}{'체결률':>9s}{'승률':>8s}{'거래당':>9s}{'최악':>9s}   비고")
    print("    " + "-" * 62)
    for stop in (-5, -8, -10, -12, -15, -20, -25, -30, None):
        for label, d in (("홀드아웃", ho),):
            if stop is None:
                pnl = net(d["close_ret"], a.hold)
                hit = 0.0
                tag = "손절 없음"
            else:
                hit_mask = d["mae"] <= stop
                pnl = np.where(hit_mask, stop, d["close_ret"])
                pnl = net(pd.Series(pnl), a.hold)
                hit = hit_mask.mean() * 100
                tag = "대부분 손절" if hit > 80 else ""
            w = (pnl > 0).mean() * 100
            st = "없음" if stop is None else f"{stop}%"
            print(f"    {st:>7s}{hit:>8.1f}%{w:>7.1f}%{pnl.mean():>+8.2f}%"
                  f"{pnl.min():>+8.1f}%   {tag}")

    print(f"\n[3] 왜 이런가 — 진입 시점의 변동성")
    print(f"    이 규칙은 20기간선 대비 -12% 급락 직후에 진입한다.")
    print(f"    최대순행(MFE) 중앙값 {ho['mfe'].median():+.1f}% / 최대역행 중앙값 {ho['mae'].median():+.1f}%")
    print(f"    즉 40시간 안에 위아래로 크게 흔들린다. 좁은 손절은 흔들림에 먼저 걸린다.")

    print(f"\n[4] 손절 없이 갈 때의 실제 위험")
    pnl = net(ho["close_ret"], a.hold)
    print(f"    승률 {(pnl>0).mean()*100:.1f}%   거래당 {pnl.mean():+.2f}%   "
          f"최악 1회 {pnl.min():+.1f}%   하위5% {pnl.quantile(.05):+.1f}%")
    print(f"    레버리지 L배에서 -{100/1:.0f}%/L 이동이면 청산이다:")
    for lev in (1, 2, 3, 5, 10):
        liq = -100 / lev
        n_liq = (ho["mae"] <= liq).sum()
        print(f"      {lev:>2}x → -{100/lev:.0f}% 이동 시 청산.  홀드아웃에서 "
              f"{n_liq}건 / {len(ho)}건 ({n_liq/len(ho)*100:.1f}%)이 이 선을 건드렸다")


if __name__ == "__main__":
    main()
