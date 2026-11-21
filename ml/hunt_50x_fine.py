"""
ml/hunt_50x_fine.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
50배 문턱 주변 정밀 격자 — 실제 봇 규칙, 복리

ml/hunt_50x.py의 넓은 격자(배율 3~20x)는 8배 이상에서 파산확률이
40~90%로 치솟아 쓸 데가 없다는 것만 알려줬다. 실제로 쓸 수 있는
구간은 2~5배이고, 거기서 1년 50배가 닿는지를 촘촘히 본다.

동시보유(=1/진입당비율)가 배율만큼이나 중요한 손잡이인데 넓은
격자에서는 5개 값밖에 안 봤다. 여기서는 6개 × 배율 5개를 돈다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import os,sys,warnings
warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import numpy as np, pandas as pd
from ml.backtest_current_bot import build_all
from ml.hunt_50x import window_stats

t,_,_ = build_all()
print("="*100)
print("  1년 50배 정밀 격자 — 실제 봇 규칙 · 복리 · 청산 저가판정")
print("="*100)
print(f"\n  {'배율':>6s}{'진입당':>8s}{'동시':>5s}{'1년최대':>10s}{'50배확률':>9s}"
      f"{'중앙':>8s}{'손실확률':>9s}{'파산확률':>9s}{'중앙낙폭':>9s}  최고시작")
print("  "+"-"*88)
rows=[]
for lev in [2.0,2.5,3.0,4.0,5.0]:
    for pt in [0.05,0.075,0.10,0.15,0.20,0.33]:
        d = window_stats(t, lev, pt, 0.25, 30, compound=True)
        if d.empty: continue
        r = {"lev":lev,"pt":pt,"conc":round(1/pt),"max":d.mult.max(),
             "p50":(d.mult>=50).mean()*100,"median":d.mult.median(),
             "p_loss":(d.mult<1).mean()*100,"p_bust":(d.mult<=0.01).mean()*100,
             "mdd":d.mdd.median()*100,
             "best":str(d.loc[d.mult.idxmax(),"start"])[:7]}
        rows.append(r)
        print(f"  {lev:>5.1f}x{pt*100:>7.1f}%{r['conc']:>5d}{r['max']:>9.1f}배"
              f"{r['p50']:>8.1f}%{r['median']:>7.2f}배{r['p_loss']:>8.0f}%"
              f"{r['p_bust']:>8.0f}%{r['mdd']:>8.0f}%  {r['best']}")
df=pd.DataFrame(rows)
df.to_csv("ml/saved_models/hunt_50x_fine.csv",index=False)
print(f"\n  50배를 찍은 설정: {(df['p50']>0).sum()}개 / {len(df)}개")
best = df[df.p_bust<=5].sort_values("max",ascending=False)
print(f"  파산확률 5% 이하 중 최대치 1위: 배율 {best.iloc[0].lev}x 동시 {best.iloc[0].conc:.0f} "
      f"→ 1년최대 {best.iloc[0]['max']:.1f}배 (중앙 {best.iloc[0]['median']:.2f}배)")
