"""
ml/bull_ideas.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
상승장 아이디어 두 개 — 새 기준(2026-10-04)으로 (2026-10-05)

상승장 = BTC 60일 수익률 ≥ +20% (전날 일봉 기준, is_on). 폭락장·급락 창이 아닐 때만.
기준은 ml/crash_window.py 봇 설정 그대로(증거금 상한 95%, 폭락장·급락 롱 2배).

 ② 상승장일 때만 익절을 늦춘다
    상승장에서 들어간 롱만 볼린저 익절 k (1.5 → 2.0/2.5/3.0σ) 와
    시간청산(60 → 120/180봉)을 바꾼다. 다른 장의 롱은 그대로.
    (전체 기간에 대해 바꾸는 건 이미 실패 — 이건 상승장에만 적용.)
 ③ 상승장일 때 BTC 1배를 들고 있는다
    상승장이 켜져 있는 동안 BTCUSDT 롱 1배, 증거금 10/20/30%.
    30일 단위로 끊어 잡는다(자리가 없어 못 들어가면 다음 30일에 다시 시도).
    상승장이 꺼지면 다음날 시가에 판다. 1배라도 무기한 선물이라 펀딩을 낸다:
    8시간당 0.01%(평상시)와 0.03%(과열기) 두 가지로 잰다.

판정: 학습(~2023)에서 1등을 고르고, 2017~·2019~·낙폭(공식·곡선)·1년손실·
2024~ 가 하나도 나빠지지 않을 때만 후보. 곡선낙폭 = 고점 리셋 없는 잔고 곡선 낙폭.

━━ 결과 (2026-10-05) ━━
                         2017~  2019~  낙폭   곡선낙폭  1년손실  ~2023  2024~  2025년
    지금 봇               36.2배  32.9배  20.5%  24.9%    2/0%    5.8배  6.2배  +165%
  ② 익절 늦추기 (11개)    18~36배                                  3.0~5.9배
     k2.0·60봉            35.8배  32.5배  20.5%  24.9%    2/0%    6.0배  5.9배  +171%
     k2.0·180봉(학습1등)  32.5배  29.7배  20.4%  24.8%    2/0%    6.1배  5.3배  +116%
  ③ BTC 1배 보유
     10%·펀딩0.01         44.5배  38.8배  20.7%  25.6%    2/0%    7.1배  6.3배  +160%
     20%·펀딩0.03         49.3배  40.8배  20.8%  29.7%    3/1%    7.9배  6.2배  +156%
     30%·펀딩0.01         57.1배  52.6배  21.0%  32.3%    8/2%    8.9배  6.4배  +154%
  ② 기각: 11개 전부 2024~ 가 지금보다 낮다. 늦게 팔면 상승장 반등의 꼭대기를
     지나쳐 되밀린다. 2025년이 특히 나쁘다(165% → 35~171%).
  ③ 기각: 2017~ 는 늘지만 곡선낙폭이 25.6~33%로 커지고, 2024~ 는 6.2~6.4배로
     거의 같다. 이득은 2017~2021 대상승장에서만 나온다.
  10-05 비중 확대와 같은 모양이다 — "상승장에 더 싣기"는 2021년 같은 장에서만
  벌고 2024~ 에는 이득이 없다.
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

KS = (1.5, 2.0, 2.5, 3.0)
HOLDS = (60, 120, 180)
SLEEVE = (0.10, 0.20, 0.30)
FUNDS = (0.01, 0.03)          # %/8h


def main():
    Dd = {s: SS.load_daily(s) for s in S.SYMBOLS}
    Dd = {k: v for k, v in Dd.items() if v is not None and len(v) >= 400}
    W = {s: SS.to_weekly(d) for s, d in Dd.items()}
    ma, th, hd0, fr, ou0, st = MENU["A 지금 봇"]
    cut = lambda X: [t for t in X if t["dt"] >= T0]
    LV = {}
    for s in S.SYMBOLS:
        g = load(s)
        o, h, l, c = (g[k].astype(float).values for k in ("open", "high", "low", "close"))
        for k in KS:
            for hd in HOLDS:
                LV.setdefault((k, hd), []).extend(
                    to_up(t) for t in sim(o, h, l, c, g["datetime"].values, ma, th, hd, fr,
                                          [(1.0, k)], S.STOP_PCT, sym=s, step=st))
    LV = {key: cut(v) for key, v in LV.items()}
    Sh, Dv = cut(UP.make_short(W)), cut(UP.make_div(Dd))
    bd = Dd["BTCUSDT"]
    btc = bd.set_index("dt")["close"]
    B = bear_series(btc, REG.AUTO_BEAR_ON, REG.AUTO_BEAR_OFF, REG.AUTO_BEAR_N)
    hits = crash_hits(load("BTCUSDT").set_index("datetime")["close"].astype(float))
    BULL = (btc / btc.shift(60) - 1) * 100 >= 20
    hot = lambda ts: is_on(B, ts) or in_window(hits, ts)
    bull = lambda ts: is_on(BULL, ts) and not hot(ts)

    def longs(key_bull=(1.5, 60)):
        out = []
        for t in LV[(1.5, 60)]:
            if hot(t["dt"]):
                out.append(dict(t, kind="longb"))
            elif not bull(t["dt"]):
                out.append(t)
        out += [t for t in LV[key_bull] if bull(t["dt"])]
        return out

    # ③ BTC 1배 보유: 상승장 날들을 30일 조각으로
    bo, bc, bl, bdt = (bd[k].values for k in ("open", "close", "low", "dt"))
    bdt = pd.to_datetime(bdt)

    def sleeve(fund):
        out = []; i = 1; n = len(bdt)
        while i < n - 1:
            if bdt[i] < T0 or not bull(bdt[i]):
                i += 1; continue
            j = i
            while j + 1 < n and bull(bdt[j + 1]) and (bdt[j + 1] - bdt[i]).days < 30:
                j += 1
            ex = min(j + 1, n - 1)                       # 꺼진 다음날(또는 30일 끝) 시가에 판다
            hrs = (bdt[ex] - bdt[i]).total_seconds() / 3600
            e, x = bo[i], bo[ex]
            x_net = x * (1 - fund / 100 * hrs / 8)       # 1배라 net()이 펀딩을 안 빼므로 여기서 뺀다
            out.append({"kind": "btc", "sym": "BTCUSDT", "dt": pd.Timestamp(bdt[i]),
                        "exit": pd.Timestamp(bdt[ex]), "entry": e, "exit_px": x_net,
                        "mae": (bl[i:ex + 1].min() / e - 1) * 100, "deployed": 1.0,
                        "bars_h": hrs, "long": True})
            i = ex
        return out

    def run(tr, sl=0.0):
        pt = {"long": .015, "longb": .015, "short": .40, "div": .40, "btc": sl}
        lv = {"long": 4.0, "longb": 2.0, "short": 1.0, "div": 1.0, "btc": 1.0}
        tr = sorted(tr, key=lambda t: t["dt"])
        f = lambda X: taken(X, pt, lv)
        fin, mdd, got, c = f(tr); w = UP.windows(c)
        f19, _, _, c19 = f([t for t in tr if t["dt"] >= T19]); w19 = UP.windows(c19)
        a = f([t for t in tr if t["dt"] < TE])[0]; h = f([t for t in tr if t["dt"] >= TE])[0]
        cdd = float((1 - c / c.cummax()).max() * 100)
        y = c.resample("YE").last(); yr = (y / y.shift(1).fillna(1) - 1) * 100
        return dict(fin=fin, f19=f19, mdd=mdd * 100, cdd=cdd, l1=(w < 1).mean() * 100,
                    l19=(w19 < 1).mean() * 100, a=a, h=h,
                    y21=yr.get(pd.Timestamp("2021-12-31"), np.nan),
                    y25=yr.get(pd.Timestamp("2025-12-31"), np.nan),
                    nb=sum(1 for x in got if x[0] == "btc"))

    print(f"{'':<26}{'2017~':>7}{'2019~':>7}{'낙폭':>6}{'곡선낙폭':>8}{'1년손실':>8}"
          f"{'~2023':>7}{'2024~':>7}{'2021년':>8}{'2025년':>8}")

    def show(lab, r):
        print(f"{lab:<26}{r['fin']:>6.1f}배{r['f19']:>6.1f}배{r['mdd']:>5.1f}%{r['cdd']:>7.1f}%"
              f"{r['l1']:>4.0f}/{r['l19']:.0f}%{r['a']:>6.1f}배{r['h']:>6.1f}배"
              f"{r['y21']:>+7.0f}%{r['y25']:>+7.0f}%" + (f"  BTC조각 {r['nb']}" if r['nb'] else ""),
              flush=True)
        return r

    base = show("지금 봇", run(longs() + Sh + Dv))
    print("\n② 상승장 롱만 익절 늦추기 (볼린저 k · 시간청산 봉)")
    R2 = {}
    for k in KS:
        for hd in HOLDS:
            if (k, hd) == (1.5, 60):
                continue
            R2[(k, hd)] = show(f"  k {k} · {hd}봉", run(longs((k, hd)) + Sh + Dv))
    print("\n③ 상승장일 때 BTC 1배 보유 (증거금 · 펀딩 %/8h)")
    R3 = {}
    for fund in FUNDS:
        SL = sleeve(fund)
        for sl in SLEEVE:
            R3[(sl, fund)] = show(f"  {sl*100:.0f}% · 펀딩 {fund}", run(longs() + Sh + Dv + SL, sl))

    def judge(lab, c):
        bad = []
        for k, nm, sgn in (("fin", "2017~", 1), ("f19", "2019~", 1), ("mdd", "낙폭", -1),
                           ("cdd", "곡선낙폭", -1), ("l1", "1년손실", -1), ("l19", "1년손실19~", -1),
                           ("h", "2024~", 1)):
            if (c[k] - base[k]) * sgn < -1e-9:
                bad.append(f"{nm} {base[k]:.1f}→{c[k]:.1f}")
        print(f"  {lab}: {'통과' if not bad else '나빠짐: ' + ', '.join(bad)}")

    print("\n판정 (학습 ~2023 1등)")
    b2 = max(R2, key=lambda k: R2[k]["a"]); judge(f"② k {b2[0]} · {b2[1]}봉", R2[b2])
    b3 = max([k for k in R3 if k[1] == 0.03], key=lambda k: R3[k]["a"])
    judge(f"③ {b3[0]*100:.0f}% · 펀딩 0.03", R3[b3])
    b3l = max([k for k in R3 if k[1] == 0.01], key=lambda k: R3[k]["a"])
    judge(f"③ {b3l[0]*100:.0f}% · 펀딩 0.01", R3[b3l])


if __name__ == "__main__":
    main()
