"""
ml/coin_swap.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
약한 42종 코인을 빼거나 후보 중 좋은 코인으로 바꾸면? (지금 봇 규칙: 평소 4배,
60일 폭락장·24시간 급락 3일 2배 · 증거금 상한 95%)

━━ 결과 (2026-10-05) — 전부 지금보다 나쁘다 ━━
  결과를 보고 고름(부풀려짐):
    지금 42종                    36.2배 곡선낙폭 25% 1년손실  2% · 2024~ 6.2배
    42종 − 약한 12              7.8배        39%         30%        5.0배
    약한 12 ↔ 좋은 후보 12      11.6배       40%         24%        6.0배
    42종 + 좋은 후보 12         35.6배       27%         11%        6.2배
  공정(2023년까지 성적으로만 고르고 2024~ 로 채점):
    42종 − 약한 12             11.9배       24%         14%        5.5배
    약한 12 ↔ 좋은 후보 12      6.4배        36%         29%        4.6배
  2023년까지 "약했던" 코인이 2024~ 에는 잘했다(GRT 승률 94%, NEO 평균 +58%,
  LTC 100%). 코인별 성적은 이어지지 않는다. 빼면 신호가 줄어 지갑이 숏·다이버
  (각 40%)에 더 기대게 되고, 결과가 크게 흔들린다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import sys,os; ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,ROOT); sys.path.insert(0,os.path.join(ROOT,"bybit")); os.chdir(ROOT)
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from bot.oversold import strategy as S, regime as REG
import ml.unified_pool as UP, ml.short_setups as SS
from ml.backtest_current_bot import load
from ml.per_coin_rules import sim
from ml.per_coin_walkforward import MENU
from ml.per_coin_portfolio import to_up
from ml.module_winrate import taken, net
from ml.bear_leverage import bear_series, is_on, T0, T19, TE
from ml.crash_window import crash_hits, in_window
from collect_history import CANDIDATE_SYMBOLS as CAND
ma,th,hd,fr,ou,st=MENU["A 지금 봇"]
btc=SS.load_daily("BTCUSDT").set_index("dt")["close"]; B=bear_series(btc)
hits=crash_hits(load("BTCUSDT").set_index("datetime")["close"].astype(float))
ALL=list(S.SYMBOLS)+list(CAND)
LT={}; DD={}
for s in ALL:
    g=load(s); o,h,l,c=(g[k].astype(float).values for k in ("open","high","low","close"))
    X=[to_up(t) for t in sim(o,h,l,c,g["datetime"].values,ma,th,hd,fr,ou,S.STOP_PCT,sym=s,step=st)]
    LT[s]=[dict(t,kind="longb") if (is_on(B,t["dt"]) or in_window(hits,t["dt"])) else t for t in X if t["dt"]>=T0]
    d=SS.load_daily(s)
    if d is not None and len(d)>=400: DD[s]=d
def stats(ts):
    if not ts: return 0,np.nan,np.nan,0
    lev=lambda t:2.0 if t["kind"]=="longb" else 4.0
    r=np.array([net(t,lev(t))*lev(t) for t in ts])
    liq=sum(t["mae"]<=-(100/lev(t)-0.5) for t in ts)
    return len(ts),(r>0).mean()*100,r.mean(),liq
WEAK=["RUNEUSDT","FLOWUSDT","APTUSDT","ICPUSDT","CHZUSDT","GRTUSDT","FILUSDT","NEOUSDT","ETCUSDT","ETHUSDT","LTCUSDT","SANDUSDT"]
GOOD=["ZECUSDT","COMPUSDT","KSMUSDT","1INCHUSDT","DYDXUSDT","GALAUSDT","IMXUSDT","APEUSDT","LDOUSDT","WLDUSDT","ORDIUSDT","JTOUSDT"]
print("== 지금 봇 규칙(평소 4배·폭락장/급락 2배)으로 코인별 롱")
for lab,grp in (("약한 42종 12개",WEAK),("후보 중 좋은 12개",GOOD)):
    print(f"[{lab}]")
    for s in grp:
        n,w,m,lq=stats(LT[s]); n1,w1,m1,_=stats([t for t in LT[s] if t["dt"]>=TE])
        print(f"  {s[:-4]:<6} {n:>3}건 승률 {w:>3.0f}% 평균 {m:+5.0f}% 청산 {lq:>2} | 2024~ {n1:>2}건 {w1:>3.0f}% {m1:+4.0f}%")
    tot=[t for s in grp for t in LT[s]]; n,w,m,lq=stats(tot); n1,w1,m1,_=stats([t for t in tot if t["dt"]>=TE])
    print(f"  합계 {n}건 승률 {w:.0f}% 평균 {m:+.0f}% 청산 {lq} | 2024~ {n1}건 {w1:.0f}% {m1:+.0f}%")
pt={"long":.015,"longb":.015,"short":.40,"div":.40}; lv={"long":4.0,"longb":2.0,"short":1.0,"div":1.0}
def port(syms,lab):
    L=[t for s in syms for t in LT[s]]; D={s:DD[s] for s in syms if s in DD}; W={s:SS.to_weekly(d) for s,d in D.items()}
    Sh=[t for t in UP.make_short(W) if t["dt"]>=T0]; Dv=[t for t in UP.make_div(D) if t["dt"]>=T0]
    tr=L+Sh+Dv; f=lambda X:taken(X,pt,lv)
    fin,mdd,_,c=f(tr); w=UP.windows(c); cm=float((1-c/c.cummax()).max())
    a=f([t for t in tr if t["dt"]<TE])[0]; h=f([t for t in tr if t["dt"]>=TE])[0]
    print(f"{lab:<36}{fin:>6.1f}배 곡선낙폭 {cm*100:>3.0f}% 1년손실 {(w<1).mean()*100:>3.0f}% ~2023 {a:>5.1f}배 2024~ {h:>5.1f}배")
base=list(S.SYMBOLS)
print("\n== 지갑 전체 (결과를 보고 고름 — 부풀려짐)")
port(base,"지금 42종")
port([s for s in base if s not in WEAK],"42종 − 약한 12 (30종)")
port([s for s in base if s not in WEAK]+GOOD,"약한 12 ↔ 좋은 12 교체 (42종)")
port(base+GOOD,"42종 + 좋은 12 (54종)")
# 공정: 2023년까지 성적으로만 고르고 2024~ 로 채점
def score(s):
    ts=[t for t in LT[s] if t["dt"]<TE]
    if len(ts)<10: return None
    return stats(ts)[2]
sc42={s:score(s) for s in base}; scc={s:score(s) for s in CAND}
w12=sorted([s for s in base if sc42[s] is not None],key=lambda s:sc42[s])[:12]
g12=sorted([s for s in CAND if scc[s] is not None],key=lambda s:-scc[s])[:12]
print("\n== 공정: 2023년까지 성적으로만 고름 → 2024~ 로 확인")
print("  2023까지 기준 약한 12:",",".join(s[:-4] for s in w12))
print("  2023까지 기준 좋은 후보:",",".join(s[:-4] for s in g12), f"({len(g12)}종, 거래 10건 미만 후보 제외)")
port([s for s in base if s not in w12],"42종 − 약한 12")
port([s for s in base if s not in w12]+g12,"약한 12 ↔ 좋은 후보 교체")
