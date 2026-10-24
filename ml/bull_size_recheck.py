"""
ml/bull_size_recheck.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"상승장에서만 롱 비중 키우기"를 새 기준(2026-10-04)으로 다시 잰다 (2026-10-05)

ml/bull_long_tweak.py(10-04)는 옛 기준으로 계산했다 — 증거금 상한 없음,
폭락장이면 롱 끔. 새 기준은 ml/crash_window.py 의 봇 설정 그대로다:
  롱 4배 1.5%, 60일 폭락장(-15% 켬/-10% 끔) 또는 급락 3일 창이면 롱 2배,
  숏·다이버 각 40% 1배, 총노출 0.6, 차단기 20%/30일, 증거금 상한 95%.
  판단은 진입 시각에 이미 닫힌 봉만(전날 일봉 / 앞선 4시간봉).

변형: 상승장(BTC N일 수익률 ≥ X%, 전날 일봉 기준)이고 폭락장·급락 창이
아닐 때 새 롱 증거금을 1.5% → 2.5 / 3.5%. 10-04 가설은 "60일 +20% · 3.5%".
견고성: 상승장 기준 60일 +15/+20/+25/+30%, 90일 +30%.
같이: 10-03 "다이버 2배" 를 증거금 상한 아래에서 한 번 더(손절 없음/-16%).

━━ 결과 (2026-10-05) ━━
                         2017~  2019~  낙폭*  곡선낙폭  1년손실  ~2023  2024~
    지금 봇 (새 기준)     36.2배  32.9배  20.5%   24.9%    2%/0%   5.8배  6.2배
    60일+20% · 2.5%      51.9배  48.2배  20.5%     -      2%/0%   8.4배  6.2배
    60일+20% · 3.5%      66.8배  61.7배  20.5%   25.9%    2%/0%  10.4배  6.4배
    60일+15/25/30%·3.5%  60~71배                          2%/0%   9.7~10.8배 6.2~6.6배
  * 낙폭 = taken 의 mdd. 차단기가 걸리면 고점을 그때 잔고로 다시 잡기 때문에
    실제 잔고 곡선의 최대낙폭(곡선낙폭, 고점 리셋 없음)보다 작게 나온다.
    곡선낙폭은 비중 1.5→3.5→4.5→5.5→7% 에 24.9→25.9→27.9→29.8→33.5% 로 커진다.
  연도별로 보면 늘어난 수익은 거의 2021년(+136%→+238%)과 2020년에서 나온다.
  2024~(검증 구간)은 6.2→6.4배로 거의 같고, 2025년은 오히려 165%→156%
  (증거금 상한 95% 안에서 상승장 롱이 자리를 차지해 다른 거래가 밀린다).
  → 보류. 공식 지표는 하나도 안 나빠지지만, 실제 곡선낙폭이 1%p 늘고
    검증 구간 이득이 작다. 이득이 한 해(2021)에 몰려 있다.
  다이버 2배(10-03 재확인): 손절없음 34.4배·낙폭 23.9%·1년손실 10%,
    손절-16% 29.9배·25.4%·15% → 둘 다 지금보다 나쁨, 기각 유지.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations
import os, sys, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from bot.oversold import strategy as S
from bot.oversold import regime as REG
import ml.unified_pool as UP
import ml.short_setups as SS
from ml.backtest_current_bot import load
from ml.per_coin_rules import sim
from ml.per_coin_walkforward import MENU
from ml.per_coin_portfolio import to_up
from ml.module_winrate import taken
from ml.bear_leverage import bear_series, is_on, T0, T19, TE
from ml.crash_window import crash_hits, in_window
from ml.div_leverage_stop import make_div_stop


def main():
    Dd = {s: SS.load_daily(s) for s in S.SYMBOLS}
    Dd = {k: v for k, v in Dd.items() if v is not None and len(v) >= 400}
    W = {s: SS.to_weekly(d) for s, d in Dd.items()}
    ma, th, hd, fr, ou, st = MENU["A 지금 봇"]
    L = []
    for s in S.SYMBOLS:
        g = load(s)
        o, h, l, c = (g[k].astype(float).values for k in ("open", "high", "low", "close"))
        L += [to_up(t) for t in sim(o, h, l, c, g["datetime"].values, ma, th, hd, fr, ou,
                                    S.STOP_PCT, sym=s, step=st)]
    cut = lambda X: [t for t in X if t["dt"] >= T0]
    L, Sh, Dv = cut(L), cut(UP.make_short(W)), cut(UP.make_div(Dd))
    Dv16 = cut(make_div_stop(Dd, 16))
    btc = Dd["BTCUSDT"].set_index("dt")["close"]
    B = bear_series(btc, REG.AUTO_BEAR_ON, REG.AUTO_BEAR_OFF, REG.AUTO_BEAR_N)
    hits = crash_hits(load("BTCUSDT").set_index("datetime")["close"].astype(float))

    def bull(n, x):
        return (btc / btc.shift(n) - 1) * 100 >= x       # is_on 으로 읽으면 전날 일봉까지

    def build(bs=None, dv=None):
        out = []
        for t in L:
            if is_on(B, t["dt"]) or in_window(hits, t["dt"]):
                out.append(dict(t, kind="longb"))
            elif bs is not None and is_on(bs, t["dt"]):
                out.append(dict(t, kind="longu"))
            else:
                out.append(t)
        return out + Sh + (Dv if dv is None else dv)

    def run(tr, size=.015, dlev=1.0):
        pt = {"long": .015, "longb": .015, "longu": size, "short": .40, "div": .40}
        lv = {"long": 4.0, "longb": 2.0, "longu": 4.0, "short": 1.0, "div": dlev}
        f = lambda X: taken(X, pt, lv)
        fin, mdd, got, c = f(tr); w = UP.windows(c)
        f19, _, _, c19 = f([t for t in tr if t["dt"] >= T19]); w19 = UP.windows(c19)
        a = f([t for t in tr if t["dt"] < TE])[0]; h = f([t for t in tr if t["dt"] >= TE])[0]
        nu = [x for x in got if x[0] == "longu"]
        return dict(fin=fin, f19=f19, mdd=mdd * 100, l1=(w < 1).mean() * 100,
                    l19=(w19 < 1).mean() * 100, a=a, h=h, nu=len(nu),
                    avu=np.mean([x[1] for x in nu]) if nu else np.nan)

    hdr = (f"{'':<34}{'2017~':>7}{'2019~':>7}{'낙폭':>6}{'1년손실':>7}{'19~':>5}"
           f"{'~2023':>7}{'2024~':>7}{'상승장롱':>8}{'거래당':>8}")
    def show(lab, r):
        print(f"{lab:<34}{r['fin']:>6.1f}배{r['f19']:>6.1f}배{r['mdd']:>5.1f}%{r['l1']:>7.0f}%"
              f"{r['l19']:>5.0f}%{r['a']:>6.1f}배{r['h']:>6.1f}배{r['nu']:>8d}"
              f"{r['avu']:>+7.1f}%" if r['nu'] else
              f"{lab:<34}{r['fin']:>6.1f}배{r['f19']:>6.1f}배{r['mdd']:>5.1f}%{r['l1']:>7.0f}%"
              f"{r['l19']:>5.0f}%{r['a']:>6.1f}배{r['h']:>6.1f}배", flush=True)
        return r

    print(hdr)
    base = show("지금 봇 (새 기준)", run(build()))
    print("\n[10-04 가설] 상승장(60일 +20%)일 때만 롱 증거금 키우기")
    R = {}
    for size in (.025, .035):
        R[size] = show(f"  60일+20% · {size*100:.1f}%", run(build(bull(60, 20)), size))
    print("\n[견고성] 3.5% 고정, 상승장 기준만 바꿈")
    for n, x in ((60, 15), (60, 25), (60, 30), (90, 30)):
        show(f"  {n}일+{x}% · 3.5%", run(build(bull(n, x)), .035))
    print("\n[10-03 재확인] 다이버 2배 (증거금 40% 그대로)")
    show("  다이버 2배 손절없음", run(build(), dlev=2.0))
    show("  다이버 2배 손절-16%", run(build(dv=Dv16), dlev=2.0))

    c = R[.035]
    print("\n판정 (60일+20% · 3.5% vs 지금):")
    for k, lab, better in (("fin", "2017~", 1), ("f19", "2019~", 1), ("mdd", "최대낙폭", -1),
                           ("l1", "1년손실", -1), ("h", "2024~", 1)):
        d = (c[k] - base[k]) * better
        print(f"  {lab}: {base[k]:.1f} → {c[k]:.1f}  {'나음' if d > 1e-9 else ('같음' if abs(d) <= 1e-9 else '나빠짐')}")


if __name__ == "__main__":
    main()
