"""
ml/xs_momentum_module.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
주간 횡단면 모멘텀 롱 모듈 (2026-11-08, 사용자 요청 "다른 전략 서칭해서 연구")

근거: 학술 연구(Fieberg·Liedtke·Metko·Zaremba 2023, Quantitative Finance —
코인 3,900종 34개 이상현상 재현)에서 "과거 승자가 패자를 이긴다(모멘텀)"가
가장 꾸준했다. 다만 큰 코인에서는 거래비용이 크고 알파가 주로 숏 쪽에서 나온다는
반론도 있다(Fieberg·Liedtke·Zaremba 2024). ml/market_neutral.py 는 4시간봉
상위N 롱숏을 따로 봤고, 지금 지갑에 붙여 본 적은 없다.
지금 봇은 상승장에 거래가 적다(과매도가 드묾). 모멘텀은 상승장에 신호가
몰리므로 빈칸을 채울 수 있는지 본다.

규칙: 매주 월요일 주봉 종가(W-MON)로 42종의 L주 수익률을 줄 세워 상위 K개 중
수익률 > 0 인 것만 다음날(화) 시가에 1배 롱, 1주 보유 뒤 다음 주 첫 시가 근처
(그 주 종가)에서 청산. 수수료 왕복 0.40%(net()), 펀딩 0.01%/8h 를 가격에서 뺀다.
같은 코인을 과매도 롱이 들고 있으면 taken() 이 건너뛴다.
격자: L {2,4,8}주 × K {3,5} × 비중 {5,10}% = 12개. 고르기는 ~2023 결과만.

━━ 결과 ━━
기각 (2026-11-08)
                          2017~  곡선낙폭  1년손실  ~2023  2024~  모멘텀 승률·거래당   2022   2025
    지금 봇                36.6배  24.9%    2%     5.8배  6.3배         –            +21%  +165%
    2주·상위3·10% (학습1등) 158.6배 39.4%   18%    33.7배 4.7배     46% · +2.7%      −29%   +75%
    2주·상위3·5%           41.4배  37.0%   25%     7.1배  5.8배     45% · +2.2%      −31%   +95%
    4주·상위3·5%           39.5배  31.7%   15%     9.1배  4.4배     46% · +2.0%      −17%   +56%
    8주·상위5·10%          77.1배  49.2%   27%    12.8배  6.0배     47% · +1.6%      −38%   +77%
  12개 전부 곡선낙폭(31~54%)과 1년손실(15~29%)이 크게 나빠지고, 2024~ 는 하나도
  지금(6.3배)을 넘지 못한다. 모멘텀 거래 자체는 승률 45~47%·거래당 +1.4~2.7%로
  양수지만 수익이 2021 같은 대상승장(+150~880%)에 몰리고, 2022 하락장에서 −6~−43%로
  크게 잃는다. 연 120~185건이 증거금을 잡아 2025 과매도 롱 수익도 깎는다.
  상승장에서만 켜는 변형은 '상승장 돌파 모듈'(2026-10 기각)과 같은 성격이라 하지 않았다.
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

GAPS = (2, 4, 8)        # 룩백 주
HOLDS = (3, 5)          # 상위 K
SIZES = (0.05, 0.10)
FUND = 0.01


def make_div4(W, look, k):
    """W: {sym: 주봉}. 이름은 div4h_module 틀을 재사용해서 그대로 둔다(kind='div4')."""
    C = pd.DataFrame({s: w.set_index("dt")["close"] for s, w in W.items()})
    O = pd.DataFrame({s: w.set_index("dt")["open"] for s, w in W.items()})
    L_ = pd.DataFrame({s: w.set_index("dt")["low"] for s, w in W.items()})
    idx = C.index; out = []
    R = C / C.shift(look) - 1
    for i in range(look, len(idx) - 2):
        r = R.iloc[i].dropna()
        r = r[r > 0].nlargest(k)
        for s in r.index:
            e = O[s].iloc[i + 1]; x = C[s].iloc[i + 1]
            if not (np.isfinite(e) and np.isfinite(x)) or e <= 0:
                continue
            x *= (1 - FUND / 100 * 21)
            out.append({"kind": "div4", "sym": s, "dt": idx[i] + pd.Timedelta(days=1),
                        "exit": idx[i + 1] + pd.Timedelta(days=1), "entry": e, "exit_px": x,
                        "mae": (L_[s].iloc[i + 1] / e - 1) * 100, "deployed": 1.0,
                        "bars_h": 7 * 24, "long": True})
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
            D4 = cut(make_div4(W, gap, hold))
            for size in SIZES:
                R[(gap, hold, size)] = show(f"{gap}주·상위{hold}·{size*100:.0f}%", run(D4, size))

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
