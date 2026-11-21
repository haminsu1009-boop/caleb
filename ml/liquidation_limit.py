"""
ml/liquidation_limit.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"청산 안 당하면서 수익률 최대" — 그 경계가 어디인가

목표를 승률이 아니라 **청산 회피 + 수익 최대**로 잡으면 계산이
달라진다. 승률 제약이 빠지므로 승률 40%짜리 급락반등 모듈
(ml/wonyotti_patterns.py)이 후보로 올라오고, 배율을 어디까지
올릴 수 있는지가 핵심 질문이 된다.

━━━ 배율별 강제청산 (보유 중 최저가 기준. 스치기만 해도 청산된다) ━━━

    배율   청산선    과매도 롱          주봉 숏        상승 다이버
    1배   −99.5%   1/1821 (0.1%)    0/23        0/66
    2배   −49.5%  11/1821 (0.6%)    1/23 (4.3%) 0/66
    3배   −32.8% 130/1821 (7.1%)    3/23 (13%)  2/66 (3.0%)
    5배   −19.5% 323/1821 (17.7%)   6/23 (26%)  7/66 (10.6%)
   10배    −9.5% 681/1821 (37.4%)  13/23 (57%) 20/66 (30.3%)
   20배    −4.5%1279/1821 (70.2%)  17/23 (74%) 38/66 (57.6%)

각 모듈의 최악 역행:
    과매도 롱  −100.0%  (2020-03 COVID, 보유 중 코인이 0이 됨)
    주봉 숏     −60.7%
    상승 다이버  −46.4%

**청산 0건은 불가능하다.** 과매도 롱의 최악이 −100%라 1배에서도
1건이 난다. 현실적 목표는 0건이 아니라 '드물게'다.

2배에서 2.5배로 올리면 청산이 11건 → 79건(0.6% → 4.3%)으로 7배가
되는데 수익은 95.0배 → 112.3배(+18%)뿐이다. **2배가 명확한 경계다.**

━━━ 2배 안에서 수익률 최대 ━━━

    구성                      전체    연복리   낙폭   샤프  1년손실 최악1년 홀드아웃
    현재 3종 (기준)          21.5배   41%  21.6%  1.38   1%   1.04   4.9배
    +급락반등 5%·노출60%      51.4배   55%  22.3%  1.68   1%   1.09   5.7배
    롱2%·급락8%·노출60%      62.0배   58%  29.6%  1.58   5%   1.02   6.0배
    롱2%·급락8%·노출100%     95.0배   66%  29.6%  1.56  11%   0.80  10.2배
    ── 2.5배부터는 청산이 79건으로 뛴다 ──
    롱1.5%·2.5배·급락8%     108.6배   69%  26.9%  1.63   9%   0.86   9.8배
    롱2%·2.5배·급락8%       112.3배   69%  34.6%  1.54  21%   0.76  12.8배

수익만 보면 95.0배(2배·노출100%)가 최대다. 대신 1년 손실확률이
1% → 11%로 오르고 최악의 1년이 +4% → −20%가 된다. 낙폭도 22.3% →
29.6%다. 청산이 늘어서가 아니라 **한 번에 크게 싣기 때문**이다.

51.4배 지점은 낙폭과 1년손실확률이 현재와 거의 같으면서 수익만
2.4배가 된다. 그 위로는 위험을 사서 수익을 얻는 구간이다.

주의: 급락반등 모듈은 승률 40%라 전체 승률이 81% → 56%가 되고,
매년 5연패, 3년에 한 번 8연패를 겪는다(계좌 낙폭은 거의 안 변한다).
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

실행: python ml/liquidation_limit.py
"""

from __future__ import annotations
import os, sys, argparse, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from bot.oversold import strategy as S
from ml.backtest_current_bot import ROUND_TRIP
import ml.short_setups as SS
import ml.unified_pool as UP
import ml.wonyotti_patterns as WP

TE = pd.Timestamp("2024-01-01")


def build():
    Dd = {}
    for s in S.SYMBOLS:
        d = SS.load_daily(s)
        if d is None or len(d) < 400:
            continue
        d["dt"] = pd.to_datetime(d["dt"])
        Dd[s] = d
    Wk = {s: SS.to_weekly(d) for s, d in Dd.items()}
    D4 = {s: WP.load(s, "4h") for s in S.SYMBOLS}
    D4 = {k: v for k, v in D4.items() if v is not None and len(v) > 500}
    L = UP.make_long(fracs=[.30, .70], hold=S.HOLD_BARS, bb=True,
                     bb_k=S.BB_K, symbols=list(Dd))
    CR = []
    for s, d in D4.items():
        f = WP.features(d)
        dts = d["dt"].values
        for x in WP.run_bracket(f, np.where(f["ret"] <= -5.)[0], 10., 5., 48,
                                True, f["trend"]):
            e = x["i"]; j = min(e + x["bars"], len(dts) - 1)
            CR.append({"kind": "crash", "sym": s, "dt": pd.Timestamp(dts[e]),
                       "exit": pd.Timestamp(dts[j]), "entry": 100.,
                       "exit_px": 100. * (1 + (x["ret"] + ROUND_TRIP) / 100),
                       "mae": -5., "deployed": 1., "bars_h": x["bars"] * 4,
                       "long": True})
    return L, UP.make_short(Wk), UP.make_div(Dd), CR


def main():
    argparse.ArgumentParser().parse_args()
    L, Sh, Dv, CR = build()

    print("=" * 92)
    print("  배율별 강제청산 — 보유 중 최저가(MAE) 기준")
    print("=" * 92)
    print(f"  {'배율':<8s}{'청산선':>9s}{'과매도 롱':>16s}{'주봉 숏':>14s}{'상승 다이버':>15s}")
    print("  " + "-" * 62)
    for lev in [1, 2, 2.5, 3, 5, 10, 20]:
        liq = 100.0 / lev - 0.5
        row = ""
        for ts in (L, Sh, Dv):
            mae = np.array([t["mae"] for t in ts])
            n = int((mae <= -liq).sum())
            row += f"{f'{n}/{len(ts)} ({n/len(ts)*100:.1f}%)':>16s}"
        print(f"  {f'{lev:g}배':<8s}{f'-{liq:.1f}%':>9s}{row}")
    print("\n  청산 0건은 불가능하다 — 과매도 롱 최악 MAE가 -100.0%다"
          " (2020-03, 보유 중 코인이 0이 됨).")

    def sim(pt, llev, mg, use_cr, seg="all"):
        tr = (L + Sh + Dv + CR) if use_cr else (L + Sh + Dv)
        tr = [t for t in tr if seg == "all" or t["dt"] >= TE]
        r = UP.simulate(tr, per_trade=pt,
                        leverage={"long": llev, "short": 1., "div": 1., "crash": 1.},
                        max_gross=mg, cb=.20)
        c = r["curve"]
        yrs = (c.index[-1] - c.index[0]).days / 365.25
        ret = c.pct_change().fillna(0)
        w = UP.windows(c)
        return (r["final"], r["final"] ** (1/yrs) - 1, r["mdd"],
                ret.mean()/ret.std()*np.sqrt(365),
                (w < 1).mean() if len(w) else np.nan,
                np.percentile(w, 5) if len(w) else np.nan)

    B = {"long": .015, "short": .40, "div": .40}
    CAND = [("현재 3종 (기준)",         dict(B),                       2., .6, False),
            ("+급락반등 5%·노출60%",     dict(B, crash=.05),            2., .6, True),
            ("롱2%·급락8%·노출60%",     dict(B, long=.02, crash=.08),  2., .6, True),
            ("롱2%·급락8%·노출100%",    dict(B, long=.02, crash=.08),  2., 1., True),
            ("롱1.5%·2.5배·급락8%",     dict(B, crash=.08),            2.5, 1., True),
            ("롱2%·2.5배·급락8%",       dict(B, long=.02, crash=.08),  2.5, 1., True)]

    print("\n" + "=" * 100)
    print("  청산을 드물게 유지하면서 수익률 최대")
    print("=" * 100)
    print(f"  {'구성':<24s}{'전체':>9s}{'연복리':>8s}{'낙폭':>8s}{'샤프':>7s}"
          f"{'1년손실':>8s}{'최악1년':>9s}{'롱 청산':>9s}{'홀드아웃':>10s}")
    print("  " + "-" * 94)
    for nm, pt, llev, mg, uc in CAND:
        x, c, m, sh, l, p5 = sim(pt, llev, mg, uc)
        hx = sim(pt, llev, mg, uc, "ho")[0]
        nl = sum(1 for t in L if t["mae"] <= -(100./llev - 0.5))
        print(f"  {nm:<24s}{x:>8.1f}배{c*100:>8.0f}%{m*100:>8.1f}%{sh:>7.2f}"
              f"{l*100:>7.0f}%{p5:>9.2f}{f'{nl}건':>9s}{hx:>9.1f}배")
    print("\n  2배 → 2.5배는 청산이 11건 → 79건인데 수익은 +18%뿐이다. 2배가 경계다.")


if __name__ == "__main__":
    main()
