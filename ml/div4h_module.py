"""
ml/div4h_module.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4시간봉 상승 다이버전스 모듈 — RESEARCH_AGENDA "수익률·거래 수 같이 늘리기" (2026-10-12)

지금 다이버(일봉, RSI차 8, 10일 보유, 40% 1배)는 1년에 몇 건뿐이다. 같은 신호를
4시간봉에서 찾으면 신호가 훨씬 많아서, 조용한 상승장(2023년 롱 68건)을 채울 수
있는지 본다. 새 kind "div4" 로 지금 봇(ml/crash_window.py 설정, 증거금 상한 95%)에
더해 ml/module_winrate.taken 으로 지갑 전체를 돌린다.

신호: ml/divergence_scoped.divergence (스윙 k=5, 우측 5봉이 지나 확정된 뒤에만) 를
4시간봉에 그대로 쓴다. 다음 봉 시가 진입, hold 봉 뒤 종가 청산, 1배.
같은 코인 보유 중 재진입 없음. 수수료 왕복 0.40%(1배라 펀딩은 net()이 안 뺀다 →
가격에서 0.01%/8h 를 직접 뺀다).

격자: RSI차 {5, 8, 12} × 보유 {30, 60}봉(5·10일) × 비중 {5, 10}% = 12개.
고르기는 ~2023 결과만, 2024~ 는 고른 뒤 한 번만. 이웃(±1칸) 모두 개선돼야 한다.

━━ 결과 (2026-10-12) — 기각 ━━
                        2017~  곡선낙폭  1년손실  2024~  거래/년   2023   2025
    지금 봇              36.2배  24.9%    2%      6.2배   188건   +15%  +165%
    RSI차12·60봉·5% (1등) 33.3배  25.3%    6%      5.0배   +31    +12   +119
    RSI차12·30봉·5%      34.6배  24.9%    2%      5.7배   +32    +22   +145
    RSI차8·30봉·10%      27.7배  30.3%    9%      5.4배   +62    +24    +94
    RSI차5·30봉·5%       27.1배  30.6%    9%      6.3배  +129    +25    +87
  12개 전부 2017~ 가 지금보다 낮다. 4시간봉 다이버 거래 자체가 승률 39~45%,
  거래당 -0.7~+0.4%(수수료·펀딩 뒤)로 기대값이 거의 0이다. 거래 수는 연 +27~+129건
  늘고 2023년도 일부 올라가지만(+15→+25%), 증거금을 잡아먹어 2025년 롱 수익이
  +165%→+11~145%로 깎인다. 일봉 다이버의 효과는 4시간봉으로 내려가면 사라진다.
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
import ml.divergence_scoped as DS
from ml.backtest_current_bot import load
from ml.per_coin_rules import sim
from ml.per_coin_walkforward import MENU
from ml.per_coin_portfolio import to_up
from ml.module_winrate import taken
from ml.bear_leverage import bear_series, is_on, T0, T19, TE
from ml.crash_window import crash_hits, in_window

GAPS = (5.0, 8.0, 12.0)
HOLDS = (30, 60)
SIZES = (0.05, 0.10)
FUND = 0.01


def make_div4(G, gap, hold):
    out = []
    for s, g in G.items():
        d = g.rename(columns={"datetime": "dt"})
        o, c, l = (d[k].astype(float).values for k in ("open", "close", "low"))
        dt = pd.to_datetime(d["dt"]).values
        n = len(c); lock = -10**9
        for i in DS.divergence(d, bullish=True, gap=gap):
            if i <= lock or i + 1 + hold >= n:
                continue
            e = o[i + 1]; x = c[i + hold] * (1 - FUND / 100 * hold * 4 / 8)
            out.append({"kind": "div4", "sym": s, "dt": pd.Timestamp(dt[i + 1]),
                        "exit": pd.Timestamp(dt[i + hold]), "entry": e, "exit_px": x,
                        "mae": (l[i + 1:i + hold + 1].min() / e - 1) * 100, "deployed": 1.0,
                        "bars_h": hold * 4, "long": True})
            lock = i + hold
    return out


def main():
    Dd = {s: SS.load_daily(s) for s in S.SYMBOLS}
    Dd = {k: v for k, v in Dd.items() if v is not None and len(v) >= 400}
    W = {s: SS.to_weekly(d) for s, d in Dd.items()}
    ma, th, hd, fr, ou, st = MENU["A 지금 봇"]
    L, G = [], {}
    for s in S.SYMBOLS:
        g = load(s)
        if g is None or len(g) < 400:
            continue
        G[s] = g
        o, h, l, c = (g[k].astype(float).values for k in ("open", "high", "low", "close"))
        L += [to_up(t) for t in sim(o, h, l, c, g["datetime"].values, ma, th, hd, fr, ou,
                                    S.STOP_PCT, sym=s, step=st)]
    cut = lambda X: [t for t in X if t["dt"] >= T0]
    L, Sh, Dv = cut(L), cut(UP.make_short(W)), cut(UP.make_div(Dd))
    btc = Dd["BTCUSDT"].set_index("dt")["close"]
    B = bear_series(btc, REG.AUTO_BEAR_ON, REG.AUTO_BEAR_OFF, REG.AUTO_BEAR_N)
    hits = crash_hits(load("BTCUSDT").set_index("datetime")["close"].astype(float))
    base_tr = [dict(t, kind="longb") if (is_on(B, t["dt"]) or in_window(hits, t["dt"])) else t
               for t in L] + Sh + Dv

    def run(extra, size=0.0):
        tr = base_tr + extra
        pt = {"long": .015, "longb": .015, "short": .40, "div": .40, "div4": size}
        lv = {"long": 4.0, "longb": 2.0, "short": 1.0, "div": 1.0, "div4": 1.0}
        f = lambda X: taken(X, pt, lv)
        fin, mdd, got, c = f(tr); w = UP.windows(c)
        f19, _, _, c19 = f([t for t in tr if t["dt"] >= T19]); w19 = UP.windows(c19)
        a = f([t for t in tr if t["dt"] < TE])[0]; h = f([t for t in tr if t["dt"] >= TE])[0]
        y = c.resample("YE").last(); yr = ((y / y.shift(1).fillna(1) - 1) * 100)
        yrs = (c.index[-1] - c.index[0]).days / 365
        g4 = [x for x in got if x[0] == "div4"]
        return dict(fin=fin, f19=f19, mdd=mdd * 100, cdd=float((1 - c / c.cummax()).max() * 100),
                    l1=(w < 1).mean() * 100, l19=(w19 < 1).mean() * 100, a=a, h=h,
                    yr={d.year: v for d, v in yr.items()}, n=len(got) / yrs, n4=len(g4) / yrs,
                    wr4=np.mean([x[1] > 0 for x in g4]) * 100 if g4 else np.nan,
                    av4=np.mean([x[1] for x in g4]) if g4 else np.nan)

    def show(lab, r):
        y = r["yr"]
        print(f"{lab:<22}{r['fin']:>6.1f}배{r['f19']:>6.1f}배{r['mdd']:>5.1f}%{r['cdd']:>6.1f}%"
              f"{r['l1']:>4.0f}/{r['l19']:.0f}%{r['a']:>6.1f}배{r['h']:>6.1f}배 "
              f"연{r['n']:>4.0f}건(+{r['n4']:.0f}) "
              + (f"승{r['wr4']:.0f}% {r['av4']:+.1f}% " if r['n4'] else "")
              + " ".join(f"{k%100}:{v:+.0f}" for k, v in y.items() if k >= 2018), flush=True)
        return r

    print(f"{'':<22}{'2017~':>7}{'2019~':>7}{'낙폭':>6}{'곡선':>7}{'1년손실':>8}{'~2023':>7}{'2024~':>7}  거래(연)  연도별%")
    base = show("지금 봇", run([]))
    R = {}
    for gap in GAPS:
        for hold in HOLDS:
            D4 = cut(make_div4(G, gap, hold))
            for size in SIZES:
                R[(gap, hold, size)] = show(f"RSI차{gap:g}·{hold}봉·{size*100:.0f}%", run(D4, size))

    best = max(R, key=lambda k: R[k]["a"])
    print(f"\n학습(~2023) 1등: {best}")
    gi, hi, si = GAPS.index(best[0]), HOLDS.index(best[1]), SIZES.index(best[2])
    nb = set()
    for dg, dh, ds in ((-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0), (0, 0, -1), (0, 0, 1)):
        a, b_, c_ = gi + dg, hi + dh, si + ds
        if 0 <= a < len(GAPS) and 0 <= b_ < len(HOLDS) and 0 <= c_ < len(SIZES):
            nb.add((GAPS[a], HOLDS[b_], SIZES[c_]))
    for k in [best] + sorted(nb):
        r = R[k]; bad = []
        for key, nm, sgn in (("fin", "2017~", 1), ("h", "2024~", 1), ("cdd", "곡선낙폭", -1), ("l1", "1년손실", -1)):
            if (r[key] - base[key]) * sgn < -1e-9:
                bad.append(f"{nm} {base[key]:.1f}→{r[key]:.1f}")
        cut_yr = [f"{yy}: {base['yr'][yy]:+.0f}→{r['yr'][yy]:+.0f}" for yy in base["yr"]
                  if yy in r["yr"] and r["yr"][yy] < base["yr"][yy] - 20]
        print(f"  {'1등' if k == best else '이웃'} {k}: {'통과' if not bad else '나빠짐 ' + ', '.join(bad)}"
              + (f" | 크게 깎인 해 {', '.join(cut_yr)}" if cut_yr else ""))


if __name__ == "__main__":
    main()
