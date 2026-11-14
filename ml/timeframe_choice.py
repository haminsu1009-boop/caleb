"""
ml/timeframe_choice.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
봉 길이를 바꾸면 — 4시간봉이 최적점인가

"하루 단위로 해보자"에서 나왔다. 이 세션의 결론이 "보유를 늘릴수록
좋아진다"였으므로 일봉은 자연스러운 다음 단계다.

임계값을 그대로 옮기면 안 된다. -12.26%는 4시간봉 20기간선(3.3일
평균)에 맞춰 찾은 값이다. 일봉 20기간선은 20일 평균이라 성격이
다르다. 학습구간에서 다시 찾는다.

펀딩비도 봉 길이에 맞춰야 한다. simulate()는 BAR_HOURS를 모듈
전역으로 쓰므로 일봉에서는 24로 바꿔 넣는다. 그대로 두면 일봉
10봉 보유(240시간)의 자금조달 비용을 40시간치로 계산해 6분의 1로
과소평가한다.

━━ 결과: 일봉이 진다 ━━

    봉    임계값    보유    체결    승률     최종   낙폭  청산    홀드   홀드승률
    4h  -12.26%  10일  1,663  83.0%  3.16배  36.2%  10  1.99배  88.5%
    1d  -12.26%  10일  2,142  62.2%  1.13배  44.0%  17  1.04배  60.6%
    1d  -18.00%  10일  1,203  68.1%  1.88배  34.5%  15  1.26배  70.4%
    1d  -22.00%  30일    667  71.1%  1.97배  32.1%   9  1.28배  74.7%
    1d  -26.00%  20일    436  71.3%  1.82배  27.5%   2  1.11배  70.4%

    일봉 학습 1위(-26%·20봉) → 홀드아웃 1.11배 (홀드아웃 실제 1위 1.31배)
    학습 ↔ 홀드아웃 상관 +0.745

일봉 최고가 홀드아웃 1.31배인데 4시간봉은 1.99배다. 승률도 78.2%
대 88.5%다.

이 세션에서 양쪽 방향을 다 쟀다.

    1분 < 5분 < 15분 < 1시간 < 4시간 > 일봉

봉을 늘리면 좋아지다가 4시간에서 꺾인다. 두 힘이 반대로 작용한다.
봉이 길수록 수수료 대비 먹을 수 있는 폭은 커지지만, 평균회귀
신호의 질은 나빠진다.

일봉 20기간선 대비 -12%는 20일짜리 하락 추세다. 되돌아오는 것이
아니라 내려가는 중인 것이다 — 실제로 청산이 10건에서 17건으로
늘고 낙폭이 36%에서 44%로 커진다. 4시간봉 20기간선 대비 -12%는
3일 평균에서 튄 것이라 되돌아올 확률이 높다.

임계값을 -26%까지 깊게 하면 일봉도 청산이 2건으로 줄고 낙폭이
27.5%로 안정된다. 그런데 거래가 444건뿐이라 복리가 붙지 않는다.

"떨어진 것을 산다"는 짧은 시간 안에서 튄 것이어야 작동한다.
일봉에서는 그것이 추세로 바뀐다.

사용법:
    python ml/timeframe_choice.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, warnings
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from bot.oversold import strategy as S
from ml.per_coin_rules import sim
import ml.backtest_current_bot as BC
TE=pd.Timestamp("2024-01-01")

def load_tf(sym, tf):
    f=f"data/{sym}_{tf}_all.csv.gz"
    if not os.path.exists(f): return None
    g=pd.read_csv(f)
    col="datetime" if "datetime" in g.columns else g.columns[0]
    g[col]=pd.to_datetime(g[col],format="mixed")
    return g.rename(columns={col:"dt"}).sort_values("dt").reset_index(drop=True)

DATA={}
for tf in ["4h","1d"]:
    for sym in S.SYMBOLS:
        g=load_tf(sym,tf)
        if g is None or len(g)<300: continue
        DATA[(tf,sym)]=tuple(g[k].astype(float).values for k in ("open","high","low","close"))+(g["dt"].values,)

def run(tf, thresh, hold, bb_k=S.BB_K, fracs=(0.30,0.70), pt=0.015, mg=0.6):
    """펀딩비가 봉 길이에 비례하므로 BAR_HOURS를 봉에 맞춘다."""
    bh = 4.0 if tf=="4h" else 24.0
    old=BC.BAR_HOURS; BC.BAR_HOURS=bh
    try:
        tr=[]
        for (t,sym),(o,h,l,c,dt) in DATA.items():
            if t!=tf: continue
            tr+=sim(o,h,l,c,dt,20,thresh,hold,list(fracs),[(1.0,bb_k)],S.STOP_PCT,sym=sym)
        if not tr: return None
        tr.sort(key=lambda x:x["dt"])
        kw=dict(leverage=2.0,per_trade=pt,max_gross=mg,cb=0.20,cool_days=30,
                min_equity=0.0,compound=True)
        f=BC.simulate(tr,**kw)
        a=BC.simulate([x for x in tr if x["dt"]< TE],**kw)
        b=BC.simulate([x for x in tr if x["dt"]>=TE],**kw)
    finally:
        BC.BAR_HOURS=old
    yrs=(tr[-1]["dt"]-tr[0]["dt"]).days/365.25
    return dict(n=len(tr), took=f["n"], wr=f["wr"], final=f["final"],
                cagr=(f["final"]**(1/yrs)-1)*100 if f["final"]>0 else -100,
                mdd=f["mdd_low"]*100, liq=f["liq"], tr=a["final"], ho=b["final"],
                ho_wr=b["wr"], days=hold*(bh/24))

print("="*112)
print("  4시간봉 vs 일봉 — 같은 규칙, 같은 배분(2배·1.5%·60%·차단기20%)")
print("  펀딩비는 봉 길이에 맞춰 계산 (일봉 10봉 = 240시간)")
print("="*112)
print(f"\n  {'봉':>4s}{'임계값':>8s}{'보유봉':>7s}{'보유일':>7s}{'신호':>8s}{'체결':>8s}"
      f"{'승률':>7s}{'최종':>9s}{'연복리':>7s}{'낙폭':>7s}{'청산':>5s}"
      f"{'학습':>8s}{'홀드':>8s}{'홀드승률':>9s}")
print("  "+"-"*110)
rows=[]
for tf, ths, holds in [("4h",[-12.26],[60]),
                       ("1d",[-12.26,-15,-18,-22,-26],[5,10,20,30])]:
    for th in ths:
        for hd in holds:
            r=run(tf,th,hd)
            if r is None or r["took"]<50: continue
            rows.append((tf,th,hd,r))
            mark="  ← 지금 봇" if tf=="4h" else ""
            print(f"  {tf:>4s}{th:>7.2f}%{hd:>7}{r['days']:>6.0f}일{r['n']:>8,}{r['took']:>8,}"
                  f"{r['wr']:>6.1f}%{r['final']:>8.2f}배{r['cagr']:>6.0f}%{r['mdd']:>6.1f}%"
                  f"{r['liq']:>5}{r['tr']:>7.2f}배{r['ho']:>7.2f}배{r['ho_wr']:>8.1f}%{mark}")
# 학습 1위 → 홀드아웃
d=[x for x in rows if x[0]=="1d"]
if d:
    best=max(d,key=lambda x:x[3]["tr"])
    xs=np.array([x[3]["tr"] for x in d]); ys=np.array([x[3]["ho"] for x in d])
    print(f"\n  일봉 후보 {len(d)}개 · 학습 1위: 임계값 {best[1]}% · {best[2]}봉"
          f" → 학습 {best[3]['tr']:.2f}배 · 홀드아웃 {best[3]['ho']:.2f}배")
    print(f"  (홀드아웃 실제 1위는 {max(ys):.2f}배)")
    if len(d)>3: print(f"  학습 ↔ 홀드아웃 상관 = {np.corrcoef(xs,ys)[0,1]:+.3f}")
print("="*112)
