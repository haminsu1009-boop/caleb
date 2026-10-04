"""
ml/bear_leverage.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
폭락장에 롱을 "끄는" 대신 "배율만 낮추면" 어떤가

폭락장 판단은 전날 일봉 종가만 쓴다(미래 참조 없음). 시뮬레이터는
ml/module_winrate.taken — 증거금 합이 자본의 95%를 넘는 진입은 건너뛴다.
롱 1.5%(증거금)·숏·다이버 각 40%·1배·총노출 0.6×4·차단기 20%/30일.
2017-01부터. 학습 ~2023 / 검증 2024~.

━━ 결과 ━━ (폭락장 = BTC 60일 -15%에서 켜고 -10% 넘으면 끔)

    폭락장에 롱을    2017~  2019~  낙폭  1년손실(17~/19~)  ~2023  2024~
    끔 (지금 계획)   21배   24배   21%     24% / 12%       3.9배  5.3배
    2배로 낮춤      36배   34배   21%      9% /  2%       5.7배  6.3배
    1배로 낮춤      37배   35배   21%     11% /  2%       6.2배  5.9배
    3배로 낮춤      25배   23배   32%     12% / 13%       3.7배  6.9배
    판단 없음(4배)   22배   20배   28%     17% / 13%       2.9배  7.5배

  폭락장 기준을 바꿔도 "2배로 낮춤"이 "끔"보다 낫다 (5개 중 4개):
    30일 -15%   끔 33배·낙폭 38%·1년손실 20%  → 2배 46배·22%·5%
    60일 -15%   끔 20배·21%·26%              → 2배 36배·21%·9%
    90일 -20%   끔 37배·22%·9%               → 2배 41배·22%·4%
    120일 -25%  끔 30배·22%·18%              → 2배 19배·32%·24%   (여기만 나빠짐)

  왜: 폭락장에서도 과매도 롱은 거래당 평균이 플러스다(+13%, 승률 73%).
  끄면 그 수익을 버린다. 문제는 4배의 청산(평단 -24.5%)이었는데 2배면
  청산선이 -49.5%라 대부분 버틴다. 버는 건 남기고 청산만 줄인다.

  숏·다이버 비중 30% / 50%는 40%보다 나빴다 — 지금 값 유지.
  같은 명목에 배율만 낮추는 것(3배·2%, 2배·3%)은 증거금을 더 묶어
  다른 진입이 막히므로 이득이 사라진다.

  ⚠️ 증거금 제약을 넣으면 기준값 자체가 낮아진다. 이전에 적은 숫자들
  (24~48배 등)은 증거금이 자본의 120%를 넘는 상태를 허용한 결과다.

사용법:
    python ml/bear_leverage.py
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
import ml.unified_pool as UP
import ml.short_setups as SS
from ml.backtest_current_bot import load
from ml.per_coin_rules import sim
from ml.per_coin_walkforward import MENU
from ml.per_coin_portfolio import to_up
from ml.module_winrate import taken

T0, T19, TE = pd.Timestamp("2017-01-01"), pd.Timestamp("2019-01-01"), pd.Timestamp("2024-01-01")


def bear_series(btc: pd.Series, on=-15.0, off=-10.0, n=60) -> pd.Series:
    """BTC n일 수익률이 on 이하면 켜고, off를 넘으면 끈다 (일봉 종가 기준)."""
    r = (btc / btc.shift(n) - 1) * 100
    st, s = [], False
    for v in r.values:
        if not np.isnan(v):
            if not s and v <= on:
                s = True
            elif s and v > off:
                s = False
        st.append(s)
    return pd.Series(st, index=btc.index)


def is_on(series: pd.Series, ts) -> bool:
    """ts 시점에 알 수 있는 값 = 전날 일봉까지."""
    i = series.index.searchsorted(pd.Timestamp(ts), side="right") - 2
    return i >= 0 and bool(series.iloc[i])


def main():
    Dd = {s: SS.load_daily(s) for s in S.SYMBOLS}
    Dd = {k: v for k, v in Dd.items() if v is not None and len(v) >= 400}
    W = {s: SS.to_weekly(d) for s, d in Dd.items()}
    ma, th, hd, fr, ou, st = MENU["A 지금 봇"]
    L = []
    for s in S.SYMBOLS:
        g = load(s)
        if g is None or len(g) < 400:
            continue
        o, h, l, c = (g[k].astype(float).values for k in ("open", "high", "low", "close"))
        L += [to_up(t) for t in sim(o, h, l, c, g["datetime"].values, ma, th, hd, fr, ou,
                                    S.STOP_PCT, sym=s, step=st)]
    cut = lambda X: [t for t in X if t["dt"] >= T0]
    L, Sh, Dv = cut(L), cut(UP.make_short(W)), cut(UP.make_div(Dd))
    btc = Dd["BTCUSDT"].set_index("dt")["close"]
    B = bear_series(btc)

    def run(mode, blev):
        tr = []
        for t in L:
            if is_on(B, t["dt"]):
                if mode == "off":
                    continue
                if mode == "lev":
                    t = dict(t); t["kind"] = "longb"
            tr.append(t)
        tr += Sh + Dv
        pt = {"long": .015, "longb": .015, "short": .40, "div": .40}
        lv = {"long": 4.0, "longb": blev, "short": 1.0, "div": 1.0}
        f = lambda X: taken(X, pt, lv)
        fin, mdd, _, c = f(tr); w = UP.windows(c)
        f19, _, _, c19 = f([t for t in tr if t["dt"] >= T19]); w19 = UP.windows(c19)
        a = f([t for t in tr if t["dt"] < TE])[0]; h = f([t for t in tr if t["dt"] >= TE])[0]
        return fin, f19, mdd * 100, (w < 1).mean() * 100, (w19 < 1).mean() * 100, a, h

    print(f"{'폭락장에 롱을':<14}{'2017~':>8}{'2019~':>8}{'낙폭':>7}{'1년손실17~':>11}{'19~':>6}{'~2023':>8}{'2024~':>8}")
    for lab, mode, blev in (("끔", "off", 4.0), ("2배로", "lev", 2.0), ("1배로", "lev", 1.0),
                            ("3배로", "lev", 3.0), ("판단 없음", "none", 4.0)):
        r = run(mode, blev)
        print(f"{lab:<14}{r[0]:>7.1f}배{r[1]:>7.1f}배{r[2]:>6.0f}%{r[3]:>10.0f}%{r[4]:>5.0f}%{r[5]:>7.1f}배{r[6]:>7.1f}배")


if __name__ == "__main__":
    main()
