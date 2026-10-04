"""연도별 발동 횟수 + 승률 — 상위 후보의 시간 안정성 검사"""
import sys, os
sys.path.insert(0, "/home/user/caleb")
os.chdir("/home/user/caleb")
import numpy as np, pandas as pd, warnings
warnings.filterwarnings("ignore")
from ml.edge_scan_all import load_all, build, wilson_lo

raw = load_all("1d")
df = build(raw, [3, 5, 10])
df["year"] = pd.DatetimeIndex(df["datetime"]).year

CANDS = [
    ("LONG", "vs_ma50", "<=", -32.96, 5, "20일선 아님·50일선 대비 -33% 이하"),
    ("LONG", "vs_ma20", "<=", -20.32, 5, "20일선 대비 -20% 이하"),
    ("LONG", "vs_ma20", "<=", -14.92, 5, "20일선 대비 -15% 이하"),
    ("LONG", "rsi14",   "<=", 22.69,  5, "RSI14 <= 22.7"),
    ("LONG", "bb_pos",  "<=", -0.0899, 10, "볼린저 하단 이탈 (bb_pos<0)"),
    ("LONG", "cc_ret",  "<=", -12.02,  3, "일봉 -12% 이상 급락"),
    ("SHORT","vol_ratio","<=", 0.3881, 10, "거래량 20일평균의 39% 이하"),
    ("LONG", "vol_ratio",">=", 2.228,  10, "거래량 20일평균의 2.2배 이상"),
]

for side, feat, op, thr, H, desc in CANDS:
    m = (df[feat] <= thr) if op == "<=" else (df[feat] >= thr)
    sub = df[m].dropna(subset=[f"ret{H}"]).copy()
    sub["pnl"] = sub[f"ret{H}"] if side == "LONG" else -sub[f"ret{H}"]
    print("=" * 92)
    print(f"  [{side}] {desc}   →  {H}봉 보유")
    print(f"  조건식: {feat} {op} {thr:.4g}    전체 발동 {len(sub):,}회 / {sub['symbol'].nunique()}종목")
    print("=" * 92)
    print(f"  {'연도':6s}{'발동':>7s}{'승률':>8s}{'평균':>9s}{'누적':>10s}   {'종목수':>6s}")
    print("  " + "-" * 60)
    for y, g in sub.groupby("year"):
        if len(g) < 5: continue
        w = int((g["pnl"] > 0).sum())
        tag = " ←홀드아웃" if y >= 2024 else ""
        print(f"  {y:<6d}{len(g):>7,}{w/len(g)*100:>7.1f}%{g['pnl'].mean():>+8.2f}%"
              f"{g['pnl'].sum():>+9.0f}%   {g['symbol'].nunique():>6d}{tag}")
    print()
