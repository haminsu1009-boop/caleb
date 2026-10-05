"""
ml/sideways_long.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
횡보장에서 롱이 본전인 문제 — 남겨둔 후보 (2026-10-06)

횡보장 = BTC 60일 수익률 -5% ~ +5% (전날 일봉 기준). 폭락장·급락 창이 아닐 때.
먼저 국면별(BTC 60일 수익률 구간) 롱 거래당 수익을 새 기준 지갑에서 실제로
체결된 거래로 나눠 보고, 횡보장에서만 롱을
  · 끈다 (증거금을 숏·다이버·다른 장 롱에 비워 둔다)
  · 비중을 줄인다 (1.5% → 0.75%)
  · 진입선을 깊게 한다 (-12.26% → -15 / -18%)
로 바꿔 본다. 나머지는 ml/crash_window.py 봇 설정 그대로(증거금 상한 95%).

판정: 학습(~2023) 1등이 2017~·2019~·낙폭(공식·곡선)·1년손실·2024~ 를
하나도 나쁘게 하지 않을 때만 후보.

━━ 결과 (2026-10-06) — 기각 ━━
  국면별 4배 롱 (거래당, 배율 전, 수수료·펀딩 뺌)
    BTC 60일 -15~-5%   167건  88%  +3.72%   (2024~ +5.49%)
             -5~+5%    243건  77%  -0.31%   (2024~ +2.86%)  ← 횡보장
             +5~+20%   123건  69%  -2.18%   (2024~ +2.07%)
             +20%~     395건  88%  +7.76%   (2024~ +7.87%)
                        2017~  2019~  낙폭   곡선낙폭  1년손실  ~2023  2024~
    지금 봇              36.2배  32.9배  20.5%  24.9%    2/0%    5.8배  6.2배
    횡보장 롱 끔         29.8배  25.5배  32.5%  32.5%    4/2%    5.4배  5.5배
    횡보장 비중 0.75%    28.7배  25.3배  37.9%  37.9%    7/6%    4.8배  5.9배
    횡보장 진입 -15%     31.5배  27.4배  38.0%  38.0%    7/6%    4.9배  6.5배
    횡보장 진입 -18%     33.5배  28.7배  34.6%  34.6%    4/2%    5.2배  6.5배
  넷 다 전부 나빠진다. 횡보장 롱이 본전인 건 2023년 이전 얘기이고 2024~ 는 +2.86%.
  거래당 수익이 0 근처여도 그 거래를 빼면 지갑의 경로(차단기가 걸리는 때,
  증거금이 비는 때)가 바뀌어 낙폭이 오히려 커진다. 횡보장 후보는 닫는다.
  (참고: 가장 약한 구간은 횡보가 아니라 BTC 60일 +5~+20% 다. 이건 결과를 보고
   찾은 것이라 바로 고치지 않는다.)
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

THS = (-12.26, -15.0, -18.0)


def main():
    Dd = {s: SS.load_daily(s) for s in S.SYMBOLS}
    Dd = {k: v for k, v in Dd.items() if v is not None and len(v) >= 400}
    W = {s: SS.to_weekly(d) for s, d in Dd.items()}
    ma, _, hd, fr, ou, st = MENU["A 지금 봇"]
    cut = lambda X: [t for t in X if t["dt"] >= T0]
    LV = {th: [] for th in THS}
    for s in S.SYMBOLS:
        g = load(s)
        o, h, l, c = (g[k].astype(float).values for k in ("open", "high", "low", "close"))
        for th in THS:
            LV[th] += [to_up(t) for t in sim(o, h, l, c, g["datetime"].values, ma, th, hd, fr, ou,
                                             S.STOP_PCT, sym=s, step=st)]
    LV = {k: cut(v) for k, v in LV.items()}
    Sh, Dv = cut(UP.make_short(W)), cut(UP.make_div(Dd))
    btc = Dd["BTCUSDT"].set_index("dt")["close"]
    B = bear_series(btc, REG.AUTO_BEAR_ON, REG.AUTO_BEAR_OFF, REG.AUTO_BEAR_N)
    hits = crash_hits(load("BTCUSDT").set_index("datetime")["close"].astype(float))
    R60 = (btc / btc.shift(60) - 1) * 100
    hot = lambda ts: is_on(B, ts) or in_window(hits, ts)

    def r60(ts):
        i = R60.index.searchsorted(pd.Timestamp(ts), side="right") - 2   # 전날 일봉
        return R60.iloc[i] if i >= 0 else np.nan
    side = lambda ts: (not hot(ts)) and -5 <= r60(ts) <= 5

    def longs(mode="base", th=-12.26):
        out = []
        for t in LV[-12.26]:
            if hot(t["dt"]):
                out.append(dict(t, kind="longb"))
            elif not side(t["dt"]):
                out.append(t)
            elif mode == "base":
                out.append(t)
            elif mode == "small":
                out.append(dict(t, kind="longs"))
        if mode == "deep":
            out += [t for t in LV[th] if side(t["dt"])]
        return out

    def run(tr):
        pt = {"long": .015, "longb": .015, "longs": .0075, "short": .40, "div": .40}
        lv = {"long": 4.0, "longb": 2.0, "longs": 4.0, "short": 1.0, "div": 1.0}
        f = lambda X: taken(X, pt, lv)
        fin, mdd, got, c = f(tr); w = UP.windows(c)
        f19, _, _, c19 = f([t for t in tr if t["dt"] >= T19]); w19 = UP.windows(c19)
        a = f([t for t in tr if t["dt"] < TE])[0]; h = f([t for t in tr if t["dt"] >= TE])[0]
        return dict(fin=fin, f19=f19, mdd=mdd * 100, cdd=float((1 - c / c.cummax()).max() * 100),
                    l1=(w < 1).mean() * 100, l19=(w19 < 1).mean() * 100, a=a, h=h, got=got)

    base = run(longs() + Sh + Dv)

    # 1) 진단: 실제 체결된 롱(4배)의 국면별 거래당 — 진입 순서대로 BTC 60일 구간에 붙인다
    lt = sorted([t for t in longs() if t["kind"] == "long"], key=lambda t: t["dt"])
    print("국면별 롱 (4배 롱 신호 전체, 수수료·펀딩 뺀 배율 전 거래당, 투입금 가중)")
    from ml.module_winrate import net
    bins = [(-99, -15), (-15, -5), (-5, 5), (5, 20), (20, 999)]
    for lo, hi in bins:
        g = [t for t in lt if lo <= r60(t["dt"]) < hi]
        if not g:
            continue
        r = np.array([net(t, 4.0) for t in g]); d = np.array([t["deployed"] for t in g])
        g2 = [t for t in g if t["dt"] >= TE]
        r2 = np.array([net(t, 4.0) for t in g2]) if g2 else np.array([np.nan])
        d2 = np.array([t["deployed"] for t in g2]) if g2 else np.array([1.0])
        print(f"  BTC 60일 {lo:>4}~{hi:<4}%  {len(g):>5}건  승률 {np.mean(r > 0)*100:>3.0f}%  "
              f"거래당 {np.average(r, weights=d):+6.2f}%   (2024~ {len(g2)}건 {np.average(r2, weights=d2):+6.2f}%)")

    print(f"\n{'':<24}{'2017~':>7}{'2019~':>7}{'낙폭':>6}{'곡선낙폭':>8}{'1년손실':>8}{'~2023':>7}{'2024~':>7}")
    def show(lab, r):
        print(f"{lab:<24}{r['fin']:>6.1f}배{r['f19']:>6.1f}배{r['mdd']:>5.1f}%{r['cdd']:>7.1f}%"
              f"{r['l1']:>4.0f}/{r['l19']:.0f}%{r['a']:>6.1f}배{r['h']:>6.1f}배", flush=True)
        return r
    show("지금 봇", base)
    V = {"횡보장 롱 끔": run(longs("off") + Sh + Dv),
         "횡보장 비중 0.75%": run(longs("small") + Sh + Dv),
         "횡보장 진입 -15%": run(longs("deep", -15.0) + Sh + Dv),
         "횡보장 진입 -18%": run(longs("deep", -18.0) + Sh + Dv)}
    for k, r in V.items():
        show(k, r)

    best = max(V, key=lambda k: V[k]["a"])
    bad = []
    for k, nm, sgn in (("fin", "2017~", 1), ("f19", "2019~", 1), ("mdd", "낙폭", -1), ("cdd", "곡선낙폭", -1),
                       ("l1", "1년손실", -1), ("l19", "1년손실19~", -1), ("h", "2024~", 1)):
        if (V[best][k] - base[k]) * sgn < -1e-9:
            bad.append(f"{nm} {base[k]:.1f}→{V[best][k]:.1f}")
    print(f"\n학습(~2023) 1등: {best} → {'통과' if not bad else '나빠짐: ' + ', '.join(bad)}")


if __name__ == "__main__":
    main()
