"""
ml/filter_breakeven.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
왜 어떤 지표 필터도 이 규칙을 개선하지 못하는가

거시경제 포함 32개, 코인 지표만 31개를 돌렸는데 통과가 0개였다.
"지표가 다 쓸모없다"로 끝내면 이유를 모른 채 남는다. 이 스크립트는
그 이유를 수치로 낸다.

복리에서는 거래 수 자체가 자산이다. (1+r)을 n번 곱하는 것이라
n이 줄면 r이 그만큼 커져야 본전이다. 필터는 언제나 n을 줄인다.
그래서 필터는 "조금 더 나은 거래를 고른다"로는 부족하고
"줄어든 곱셈 횟수를 메울 만큼" 나아야 한다.

두 가지를 같이 본다
  1. 거래를 f 비율만 남길 때 필요한 거래당 수익률 (손익분기)
  2. 각 지표가 실제로 승자와 패자를 가르는 폭

둘을 비교하면 왜 전부 미달인지 바로 보인다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import os,sys,warnings
warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import numpy as np, pandas as pd
from ml.backtest_current_bot import build_all, simulate, ROUND_TRIP

t,_,_ = build_all()
px = np.array([(x["exit_px"]/x["entry_avg"]-1)*100 - ROUND_TRIP for x in t])
print("="*84)
print("  왜 어떤 필터도 못 이기나 — 필터의 손익분기")
print("="*84)
print(f"\n  전체 거래 {len(t):,}건 · 거래당 평균 {px.mean():+.2f}% · 승률 {(px>0).mean()*100:.1f}%")

print(f"\n  ── 거래를 몇 % 남기면, 거래당 평균이 얼마여야 본전인가")
print(f"  (복리라 거래 수가 줄면 그만큼 곱셈 횟수가 준다)")
print(f"\n  {'남기는 비율':>12s}{'거래 수':>9s}{'필요 거래당':>12s}{'현재 대비':>11s}")
print("  "+"-"*46)
base_n=len(px); mu=px.mean()
# 근사: (1+r)^n 이 같아지려면 n*log(1+r) 보존
import math
for f in [0.97,0.90,0.75,0.50,0.30,0.16,0.05]:
    n=int(base_n*f)
    need=(math.exp(base_n*math.log(1+mu/100)/n)-1)*100
    print(f"  {f*100:>11.0f}%{n:>9d}{need:>11.2f}%{need/mu:>10.2f}배")

print(f"\n  ── 그런데 지표들이 실제로 승자와 패자를 가르는가")
print(f"     (필터를 통과한 거래 vs 걸러진 거래의 거래당 평균 차이)")
import importlib
ci = importlib.import_module("ml.coin_indicator_backtest")
market, volz, symvol = ci.build_coin_market()
senti = ci.load_crypto_sentiment()
if not senti.empty:
    market = market.join(senti.reindex(market.index, method="ffill"))
from ml.indicator_backtest import load_funding, load_metrics
tt = ci.attach(t, market, {"f":load_funding(),"m":load_metrics()}, volz, symvol)
ret = {id(x):(x["exit_px"]/x["entry_avg"]-1)*100-ROUND_TRIP for x in tt}

CH=[("시장 폭 < 30%","breadth",lambda x:x["breadth"]<30),
    ("동시신호 6종 이상","n_signal",lambda x:x["n_signal"]>=6),
    ("동시신호 1~2종","n_signal",lambda x:x["n_signal"]<=2),
    ("BTC > MA200","btc_ma200",lambda x:x["btc_ma200"]>0),
    ("BTC 변동성 z>1","btc_vol_z",lambda x:x["btc_vol_z"]>1),
    ("공포탐욕 < 20","fng",lambda x:x["fng"]<20),
    ("펀딩 > 0","fr_bps",lambda x:x["fr_bps"]>0),
    ("고래 숏 쏠림","whale_z",lambda x:x["whale_z"]<-0.5),
    ("거래량 2배 이상","vol_ratio",lambda x:x["vol_ratio"]>2)]
print(f"\n  {'필터':<20s}{'통과 거래당':>12s}{'걸러진 거래당':>14s}{'차이':>9s}{'통과율':>9s}")
print("  "+"-"*66)
for name,col,fn in CH:
    have=[x for x in tt if not pd.isna(x.get(col,np.nan))]
    if len(have)<50: continue
    a=np.array([ret[id(x)] for x in have if fn(x)])
    b=np.array([ret[id(x)] for x in have if not fn(x)])
    if len(a)<20 or len(b)<20: continue
    print(f"  {name:<20s}{a.mean():>11.2f}%{b.mean():>13.2f}%"
          f"{a.mean()-b.mean():>8.2f}%{len(a)/len(have)*100:>8.0f}%")
