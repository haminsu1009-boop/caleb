"""
ml/short_stress_filter.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
주봉 숏 스트레스 테스트 + 급락 직후 숏 건너뛰기 필터 (2026-11-04, 사용자 대화)

배경: 주봉 숏 신호 23건 중 최악 2건(2020-03-23 IOTA −50%(+50% 파국 손절),
TRX −31%)은 백테스트 지갑에서 차단기 타이밍 덕에 우연히 잡히지 않았다.
실거래 봇은 주당 숏 1건(SHORT_MAX_CONCURRENT)이라 현실적 최악 = IOTA 1건.
taken() 을 복사해 force=True 거래는 차단기·보유·상한을 무시하고 잡게 했다.
숏 신호 전부에 +50% 파국 손절(봇의 CATASTROPHE_STOP)을 반영했다.

━━ 결과 ━━
  숏 비중   경우                2017~  곡선낙폭  1년손실  2024~   2020년
   40%     백테스트 그대로      36.6배   25%      2%     6.29배   +24%
   40%     IOTA 강제(현실 최악) 29.5배   38%      7%     6.29배    0%
   40%     둘 다(봇에선 불가)   25.0배   47%     12%     6.29배   −16%
   30%     IOTA 강제            27.0배   34%      4%     6.04배    +5%
   20%     IOTA 강제            23.8배   31%      3%     5.45배   +11%
    0%     숏 끔                17.1배   25%     10%     4.64배   +24%
  → 최악 1건을 넣어도 숏 40%가 숏 끔보다 낫다. 대가는 곡선낙폭 25→38%.

  필터: 직전 주봉이 X% 이하로 빠졌으면 숏 신호 건너뜀 (40%, IOTA 강제 가정)
    없음 29.5배·38%·7%·6.29 / −20% 33.4·25·2·5.89(CHZ 2606 +24% 잃음)
    −25~−35% 35.7배·25%·2%·6.29 (NEAR 2206 +8% 하나만 빠짐) / −40% 36.6(IOTA만 빠짐)
  파국 손절 폭: +50% 29.5·38% / +40% 30.7·35% / +35% 31.4·34% /
    +30% 26.5·32%·2024~ 5.18 (OP 2407 같은 역행 후 이익 숏을 자름) → 효과 작음.

판단: −30% 필터는 논리(투매 주 직후 = 과매도 롱이 사는 자리)·이웃 안정(−25~−35% 같음)·
작은 비용(+8% 1건)을 갖췄다. 하지만 근거 사건이 2020-03 하루뿐이고 2024~ 에는 해당
거래가 없어 검증 구간 확인이 불가능하다. 사용자 확인 필요(bot/ 변경).
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import sys,os,warnings;warnings.filterwarnings("ignore")
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)));sys.path.insert(0,ROOT);os.chdir(ROOT)
import numpy as np,pandas as pd
from bot.oversold import strategy as S
from bot.oversold import regime as REG
import ml.unified_pool as UP, ml.short_setups as SS
import ml.module_winrate as MW
from ml.backtest_current_bot import load
from ml.per_coin_rules import sim
from ml.per_coin_walkforward import MENU
from ml.per_coin_portfolio import to_up
from ml.bear_leverage import bear_series, is_on, T0
from ml.crash_window import crash_hits, in_window
Dd={s:SS.load_daily(s) for s in S.SYMBOLS};Dd={k:v for k,v in Dd.items() if v is not None and len(v)>=400}
W={s:SS.to_weekly(d) for s,d in Dd.items()}
ma,th,hd,fr,ou,st=MENU["A 지금 봇"];L=[]
for s in S.SYMBOLS:
    g=load(s)
    if g is None or len(g)<400: continue
    o,h,l,c=(g[k].astype(float).values for k in ("open","high","low","close"))
    L+=[to_up(t) for t in sim(o,h,l,c,g["datetime"].values,ma,th,hd,fr,ou,S.STOP_PCT,sym=s,step=st)]
cut=lambda X:[t for t in X if t["dt"]>=T0]
L,Sh,Dv=cut(L),cut(UP.make_short(W)),cut(UP.make_div(Dd))
btc=Dd["BTCUSDT"].set_index("dt")["close"]
B=bear_series(btc,REG.AUTO_BEAR_ON,REG.AUTO_BEAR_OFF,REG.AUTO_BEAR_N)
hits=crash_hits(load("BTCUSDT").set_index("datetime")["close"].astype(float))
tr=[dict(t,kind="longb") if (is_on(B,t["dt"]) or in_window(hits,t["dt"])) else t for t in L]+Sh+Dv
import inspect, ml.module_winrate as MW
from ml.bear_leverage import TE
lv={"long":4.0,"longb":2.0,"short":1.0,"div":1.0}
src=inspect.getsource(MW.taken).replace("def taken(","def taken_f(")
src=src.replace("        if halted is not None and now < halted:\n            continue",
 "        F=t.get('force',False)\n        if halted is not None and now < halted and not F:\n            continue")
src=src.replace("        if 1 - cash / peak >= cb:","        if 1 - cash / peak >= cb and not F:")
src=src.replace("        if t[\"sym\"] in held:\n            continue","        if t[\"sym\"] in held and not F:\n            continue")
src=src.replace("> max_gross * cash * max(leverage.values()):\n            continue",">max_gross*cash*max(leverage.values()) and not F:\n            continue")
src=src.replace("> mcap * cash:\n            continue","> mcap * cash and not F:\n            continue")
assert src.count("not F")==5, src.count("not F")
ns=dict(MW.__dict__); exec(src,ns); taken_f=ns["taken_f"]
def stop50(t):  # 숏 +50% 파국 손절 반영
    if t["kind"]=="short":
        d=Dd[t["sym"]].set_index("dt"); seg=d[(d.index>=t["dt"])&(d.index<=t["exit"])]
        if seg["high"].max()>=t["entry"]*1.5: t=dict(t,exit_px=t["entry"]*1.5,mae=0)
    return t
def win(c):
    v=c.values; return np.array([v[i+365]/v[i] for i in range(0,len(c)-365,15)])
base=[stop50(t) for t in tr]
sh=[t for t in base if t["kind"]=="short"]
sk=[t for t in sh if t["dt"].year==2020 and t["dt"].month==3]
for t in sk: print("2020-03 숏:",t["sym"],t["dt"].date(),f"{(1-t['exit_px']/t['entry'])*100:+.1f}%")
iota=[t for t in sk if t["sym"]=="IOTAUSDT"][0]; trx=[t for t in sk if t["sym"]=="TRXUSDT"][0]
def run(X,ps):
    pt={"long":.015,"longb":.015,"short":ps,"div":.40}
    fin,mdd,got,c=taken_f(X,pt,lv)
    h=taken_f([t for t in X if t["dt"]>=TE],pt,lv)[0]
    y=c.resample("YE").last(); yr=(y/y.shift(1).fillna(1)-1)*100
    return f"{fin:6.1f}배 곡선{(1-c/c.cummax()).max()*100:4.0f}% 1년손실{(win(c)<1).mean()*100:3.0f}% 2024~{h:5.2f}배 2020년{yr[pd.Timestamp('2020-12-31')]:+5.0f}%"
others=[t for t in base if t not in (iota,trx)]
for ps in (0.2,0.3,0.4):
    print(f"--- 숏 {ps*100:.0f}%")
    print(" 백테스트 그대로   ", run(base,ps))
    print(" TRX 강제 진입     ", run(others+[dict(trx,force=True)],ps))
    print(" IOTA 강제 진입    ", run(others+[dict(iota,force=True)],ps))
    print(" 둘 다(최악)       ", run(others+[dict(trx,force=True),dict(iota,force=True)],ps))
print("--- 숏 0%:", run([t for t in base if t["kind"]!="short"],0))
print("=== 마지막 주 급락 필터 (숏 40%, 2020-03은 IOTA 강제 진입 가정)")
def lastwk(t):
    w=W[t["sym"]]; w=w.set_index("dt") if "dt" in w else w
    p=w[w.index<t["dt"]]; return (p["close"].values[-1]/p["open"].values[-1]-1)*100
for X in (None,-20,-25,-30,-35,-40):
    keep=[t for t in others if not (t["kind"]=="short" and X is not None and lastwk(t)<=X)]
    extra=[] if (X is not None and lastwk(iota)<=X) else [dict(iota,force=True)]
    gone=[f"{t['sym'][:-4]}{t['dt'].strftime('%y%m')}" for t in others if t["kind"]=="short" and X is not None and lastwk(t)<=X]
    print(f" 필터 {X}: ", run(keep+extra,0.4), " 빠진 숏:", ",".join(gone))
print("=== 파국 손절 폭 (숏 40%, IOTA 강제)")
def stopk(t,k):
    if t["kind"]!="short": return t
    d=Dd[t["sym"]].set_index("dt"); seg=d[(d.index>=t["dt"])&(d.index<=t["exit"])]
    if seg["high"].max()>=t["entry"]*(1+k/100): return dict(t,exit_px=t["entry"]*(1+k/100))
    return t
for k in (50,40,35,30,25):
    X=[stopk(t,k) for t in others]+[dict(stopk(iota,k),force=True)]
    print(f" 손절 +{k}%: ", run(X,0.4))
