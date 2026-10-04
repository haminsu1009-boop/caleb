"""최종 후보 검증 — 연도별 안정성 + 레짐 필터 + 종목 분산"""
import sys, os
sys.path.insert(0,"/home/user/caleb"); os.chdir("/home/user/caleb")
import numpy as np, pandas as pd, warnings
warnings.filterwarnings("ignore")
from ml.edge_scan_all import load_all, build, wilson_lo

IV = sys.argv[1] if len(sys.argv)>1 else "4h"
raw = load_all(IV)
df = build(raw, [1,3,5,10])
df = df.sort_values(["symbol","datetime"]).reset_index(drop=True)
g = df.groupby("symbol")["close"]
df["ma50"] = g.transform(lambda s: s.rolling(50).mean())
df["ma200"] = g.transform(lambda s: s.rolling(200).mean())
df["above200"] = (df["close"] > df["ma200"]).shift(1)
df["ma50_up"] = (df["ma50"] > df.groupby("symbol")["ma50"].shift(5)).shift(1)
df["year"] = pd.DatetimeIndex(df["datetime"]).year
HO = df["datetime"] >= "2024-01-01"

CANDS = eval(sys.argv[2]) if len(sys.argv)>2 else []

def stat(p):
    w = int((p>0).sum()); n=len(p)
    return n, w/n*100 if n else 0, wilson_lo(w,n,1.96), p.mean()

for side, feat, op, thr, H, desc, filt in CANDS:
    m = (df[feat] <= thr) if op=="<=" else (df[feat] >= thr)
    if filt == "bull":   m &= (df.above200==True) & (df.ma50_up==True)
    elif filt == "bear": m &= (df.above200==False) & (df.ma50_up==False)
    sub = df[m].dropna(subset=[f"ret{H}"]).copy()
    sub["pnl"] = sub[f"ret{H}"] if side=="LONG" else -sub[f"ret{H}"]
    n,wr,lo,mu = stat(sub.loc[HO[sub.index],"pnl"])
    print("="*96)
    print(f"  [{side}] {desc}  ({IV}, {H}봉 보유, 필터={filt or '없음'})")
    print(f"  홀드아웃 n={n:,}  승률 {wr:.1f}% (하한 {lo:.1f}%)  거래당평균 {mu:+.2f}%")
    print("-"*96)
    print(f"  {'연도':6s}{'발동':>7s}{'승률':>8s}{'평균':>9s}{'종목':>6s}")
    for y, gg in sub.groupby("year"):
        if len(gg)<10: continue
        n2,wr2,_,mu2 = stat(gg["pnl"])
        print(f"  {y:<6d}{n2:>7,}{wr2:>7.1f}%{mu2:>+8.2f}%{gg['symbol'].nunique():>6d}"
              f"{'  ←홀드아웃' if y>=2024 else ''}")
    # 종목 분산
    rows=[]
    for s,gg in sub[HO[sub.index]].groupby("symbol"):
        if len(gg)<20: continue
        n2,wr2,_,mu2 = stat(gg["pnl"]); rows.append(mu2)
    if rows:
        print(f"  종목별: {sum(1 for x in rows if x>0)}/{len(rows)}종목 평균 플러스")
    print()
