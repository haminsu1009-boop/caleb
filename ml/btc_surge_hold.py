"""
ml/btc_surge_hold.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
급등장(BTC 60일 수익률 ≥ +X%, 전날 종가)일 때 자본 일부로 BTC 1배 롱을 들면?

과매도 롱은 급락이 없는 급등장에 신호가 드물다. 그동안 비는 증거금 일부로
BTC를 1배로 든다. 지금 봇 설정 그대로(롱 4배, 60일 폭락장·24시간 급락 2배,
숏·다이버 1배 40%, 증거금 상한 95%, 차단기) ml/module_winrate.taken 으로
돌린다. 다음 날 시가에 사고, 조건이 꺼진 다음 날 시가에 판다(30일마다 끊어
다시 잡는다). 수수료 왕복 0.40% + 롱 펀딩 0.01%/8h(0.03%로도 확인).

━━ 결과 (2026-10-09) ━━  2017~ / 곡선낙폭 / 1년손실(17~/19~) / ~2023 / 2024~
  지금 전략              36.2배  25%   2%/0%   5.8배  6.2배
  +20% · BTC 20/30/40%   67~104배 28~33%  2~7%/0~2%  10.4~16.4배  6.3~6.5배
  +25% · BTC 20/30/40%   59~73배  25~26%  3~13%/0~7%  9.2~11.4배  6.2~6.4배
  +30% · BTC 20%         60.1배  25%   2%/0%   9.3배  6.5배
  +30% · BTC 30%         74.9배  25%   2%/0%  11.5배  6.5배   ← 4가지 조건 모두 통과
  +30% · BTC 40%         90.5배  25%   3%/0%  14.1배  6.5배
  +35% · BTC 20/30/40%   57~72배  25%   2~6%/0%  8.7~10.5배  6.5~6.8배
  +40% · BTC 20/30/40%   53~62배  25%   2~6%/0%  8.4~10.0배  6.3배
  +30% · 30% · 펀딩 0.03% 64.9배  25%   3%/0%  10.2배  6.4배
  15개 변형 모두 2017~ 와 2024~ 가 지금 이상. 이득 대부분은 2017·2020~21
  대상승장(~2023 5.8→11.5배)이고, 검증구간 2024~ 는 6.2→6.5배(+5%)로 작다.
  배율 (조건 +30%): 1배·30% 74.7배 25% 2% 6.5 · 2배·30% 105.9배 25% 11% 6.4 ·
    4배·30% 201.7배 39% 10% 5.4 · 2배·15%(같은 크기) 75.4배 25% 2% 6.5 ·
    4배·7.5% 72.0배 25% 3% 6.5 (구간 중 최대 역행 -26.8% > 4배 청산선).
  켜고 끄는 기준 분리(2배·15%): 30/30 75.4배 2% 6.5 · 30/25 73.0배 3% 6.4 ·
    30/20 64.8배 6% 6.4 · 30/15 73.7배 6% 6.7 · 25/15 70.5배 12% 7.2 ·
    35/20 81.9배 1% 6.5 — 어느 것도 30/30을 모든 조건에서 이기지 못한다.
  구간 승률(30/30) 38%·중앙 -1.2%·평균 +10.1% — 대상승장 몇 번이 전부다.
  실거래에 넣으려면 같은 BTCUSDT 과매도 롱과 단방향 포지션이 겹치지 않게
  처리해야 한다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import sys,os; ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,ROOT); os.chdir(ROOT)
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from bot.oversold import strategy as S, regime as REG
import ml.unified_pool as UP, ml.short_setups as SS
from ml.backtest_current_bot import load
from ml.per_coin_rules import sim
from ml.per_coin_walkforward import MENU
from ml.per_coin_portfolio import to_up
from ml.module_winrate import taken
from ml.bear_leverage import bear_series, is_on, T0
from ml.crash_window import crash_hits, in_window
Dd={s:SS.load_daily(s) for s in S.SYMBOLS}; Dd={k:v for k,v in Dd.items() if v is not None and len(v)>=400}
W={s:SS.to_weekly(d) for s,d in Dd.items()}
ma,th,hd,fr,ou,st=MENU["A 지금 봇"]; L=[]
for s in S.SYMBOLS:
    g=load(s); o,h,l,c=(g[k].astype(float).values for k in ("open","high","low","close"))
    L+=[to_up(t) for t in sim(o,h,l,c,g["datetime"].values,ma,th,hd,fr,ou,S.STOP_PCT,sym=s,step=st)]
cut=lambda X:[t for t in X if t["dt"]>=T0]; L,Sh,Dv=cut(L),cut(UP.make_short(W)),cut(UP.make_div(Dd))
btc=Dd["BTCUSDT"].set_index("dt")["close"]; B=bear_series(btc)
hits=crash_hits(load("BTCUSDT").set_index("datetime")["close"].astype(float))
tr=[dict(t,kind="longb") if (is_on(B,t["dt"]) or in_window(hits,t["dt"])) else t for t in L]+Sh+Dv

from ml.bear_leverage import T19, TE
bd=SS.load_daily("BTCUSDT").set_index("dt"); bc=bd["close"]; bo=bd["open"]; bl=bd["low"]
r60=(bc/bc.shift(60)-1)*100
def btc_trades(th, fund):
    on=(r60>=th).shift(1).fillna(False); on=on[on.index>=T0]
    out=[];st=None
    for d,v in on.items():
        if v and st is None: st=d
        if st is not None and ((not v) or (d-st).days>=30):
            days=(d-st).days
            ex=bo[d]*(1-fund/100*3*days)       # 롱 펀딩비(8시간마다)를 가격에서 뺀다
            out.append({"kind":"btc","sym":"BTCHOLD","dt":st,"exit":d,"entry":bo[st],"exit_px":ex,
                        "mae":(bl[st:d].min()/bo[st]-1)*100,"deployed":1.0,"bars_h":days*24,"long":True})
            st=d if v else None
    return out
def run(extra,pb,lab):
    pt={"long":.015,"longb":.015,"short":.4,"div":.4,"btc":max(pb,1e-9)}; lv={"long":4.0,"longb":2.0,"short":1.0,"div":1.0,"btc":1.0}
    X=tr+extra; f=lambda Y:taken(Y,pt,lv)
    fin,mdd,got,c=f(X); w=UP.windows(c); cm=float((1-c/c.cummax()).max())
    f19,_,_,c19=f([t for t in X if t["dt"]>=T19]); w19=UP.windows(c19)
    a=f([t for t in X if t["dt"]<TE])[0]; h,_,_,ch=f([t for t in X if t["dt"]>=TE]); chm=float((1-ch/ch.cummax()).max())
    nb=sum(1 for g in got if g[0]=="btc"); nl=sum(1 for g in got if g[0] in("long","longb"))
    print(f"{lab:<30}{fin:>6.1f}배 19~{f19:>5.1f}배 곡선낙폭 {cm*100:>3.0f}% 1년손실 {(w<1).mean()*100:>2.0f}%/{(w19<1).mean()*100:>2.0f}% ~2023 {a:>4.1f}배 2024~ {h:>4.1f}배(낙폭 {chm*100:.0f}%) BTC {nb} 롱 {nl}")
run([],0,"지금 전략")
for th in (20,25,30,35,40):
    for pb in (0.2,0.3,0.4):
        run(btc_trades(th,0.01),pb,f"+{th}% · BTC {int(pb*100)}%")
print("펀딩비 0.03%/8h")
for th in (30,):
    for pb in (0.3,):
        run(btc_trades(th,0.03),pb,f"+{th}% · BTC {int(pb*100)}% (펀딩 3배)")
