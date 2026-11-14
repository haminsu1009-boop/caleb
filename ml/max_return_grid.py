"""
ml/max_return_grid.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"백테스트 수익을 최대로 하려면" 에 대한 정직한 답

노브 8개(롱·돌파·숏·다이버 비중, 롱·돌파 배율, 총노출, 차단기)를
3,888가지로 조합해 전부 돌렸다. 결과:

  · 1,542개(40%)는 계좌가 0이 됐다
  · 최대 수익 설정은 9,725배 (연복리 179%)
      롱 4%·2배 / 돌파 5%·3배 / 숏 50% / 다이버 30% / 총노출 200% / 차단기 60%
  · 같은 설정의 낙폭 62.9%, 1년 손실확률 31%

문제는 안정성이다. 이 설정에서 노브를 한 칸씩만 움직이면:

    차단기 60%→25%      9,725배 → 413배   (−96%)
    돌파 배율 3→2        9,725배 → 619배   (−94%)
    돌파 비중 5%→6%      9,725배 → 1,042배 (−89%)
    롱 비중 4%→2%        9,725배 → 1,106배 (−89%)
    돌파 배율 3→5        9,725배 → 22,447배 (+131%)

한 칸에 90%씩 흔들린다는 건 9,725라는 숫자가 규칙이 아니라 노브
위치를 설명한다는 뜻이다. 특히 차단기 60%는 "−60%까지 안 멈춘다"는
뜻인데, 그게 이 설정 수익의 대부분을 만든다.

그렇다고 전부 허구는 아니다. 이 설정은 홀드아웃(2024~)에서도
23.04배를 냈다. 신호 자체는 살아 있다. 위험이 클 뿐이다.

비교 (전체 8.9년 / 홀드아웃 2024~):

  설정             전체        낙폭    샤프   1년손실  | 홀드아웃  낙폭   샤프
  수익 1등      9,724.88배   62.9%   1.57    31%   |  23.04배  32.8%  1.74
  샤프 1등        247.41배   28.7%   1.87    12%   |   7.26배  14.4%  2.11
  돌파 없는 3종      23.11배   28.7%   1.24    10%   |   7.52배   9.3%  1.94
  지금 실거래 봇       3.83배   57.2%   0.65    33%   |   3.03배   9.7%  1.87

샤프 1등은 수익 1등의 1/39이지만 낙폭이 절반이고 홀드아웃 1년
손실확률이 0%다. 노브를 흔들어도 잘 안 무너진다.

수익 1등을 고를 이유는 하나뿐이다 — 낙폭 63%를 실제로 견딜 수
있고, 그게 2021년 한 번 더 오는 데 거는 베팅임을 알 때.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

실행: python ml/max_return_grid.py
"""

from __future__ import annotations
import os, sys, warnings, argparse
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from bot.oversold import strategy as S
import ml.short_setups as SS
import ml.unified_pool as UP

TE = pd.Timestamp("2024-01-01")

# 그리드에서 나온 두 극단과, 비교용 두 개.
CONFIGS = {
    "수익 1등": dict(kinds=4, pt={"long": .04, "short": .50, "div": .30, "break": .05},
                  lev={"long": 2., "short": 1., "div": 1., "break": 3.},
                  mg=2.0, cb=.60),
    "샤프 1등": dict(kinds=4, pt={"long": .02, "short": .30, "div": .30, "break": .04},
                  lev={"long": 2., "short": 1., "div": 1., "break": 1.},
                  mg=1.0, cb=.25),
    "돌파 없는 3종": dict(kinds=3, pt={"long": .02, "short": .50, "div": .30},
                     lev={"long": 2., "short": 1., "div": 1.}, mg=1.0, cb=.25),
    "지금 실거래 봇": dict(kinds=1, pt={"long": .05}, lev={"long": 2.}, mg=0.8, cb=.25),
}


def load():
    syms = [s for s in S.SYMBOLS if os.path.exists(f"data/{s}_1d_all.csv.gz")]
    D = {s: SS.load_daily(s) for s in syms}
    D = {k: v for k, v in D.items() if v is not None and len(v) >= 400}
    W = {s: SS.to_weekly(d) for s, d in D.items()}
    L = UP.make_long(fracs=[.30, .70], hold=60, bb=True, bb_k=1.5)
    return {1: L, 3: L + UP.make_short(W) + UP.make_div(D),
            4: L + UP.make_short(W) + UP.make_div(D) + UP.make_break(D)}


def stats(trades, pt, lev, mg, cb):
    r = UP.simulate(trades, per_trade=pt, leverage=lev, max_gross=mg, cb=cb)
    c = r["curve"]
    yrs = (c.index[-1] - c.index[0]).days / 365.25
    ret = c.pct_change().fillna(0)
    w = UP.windows(c)
    return (r["final"], r["final"] ** (1 / yrs) - 1, r["mdd"],
            ret.mean() / ret.std() * np.sqrt(365) if ret.std() > 0 else 0.0,
            (w < 1).mean() if len(w) else np.nan)


def main():
    argparse.ArgumentParser().parse_args()
    POOL = load()
    print("=" * 84)
    print("  백테스트 수익 최대화 — 그 숫자가 무엇을 대가로 하는지")
    print("=" * 84)
    for seg, lab in [("all", "전체 8.9년"), ("tr", "학습 ~2023"), ("ho", "홀드아웃 2024~")]:
        print(f"\n  ── {lab}")
        print(f"  {'설정':<20s}{'전체':>11s}{'연복리':>8s}{'낙폭':>8s}{'샤프':>7s}{'1년손실':>8s}")
        print("  " + "-" * 62)
        for name, c in CONFIGS.items():
            tr = POOL[c["kinds"]]
            if seg == "tr":
                tr = [t for t in tr if t["dt"] < TE]
            elif seg == "ho":
                tr = [t for t in tr if t["dt"] >= TE]
            x, g, m, s, l = stats(tr, c["pt"], c["lev"], c["mg"], c["cb"])
            print(f"  {name:<20s}{x:>10.2f}배{g*100:>8.0f}%{m*100:>8.1f}%{s:>7.2f}{l*100:>8.0f}%")

    print("\n" + "=" * 84)
    print("  수익 1등 설정에서 노브를 한 칸씩만 (전체 기간)")
    print("=" * 84)
    c = CONFIGS["수익 1등"]; tr = POOL[4]
    base = stats(tr, c["pt"], c["lev"], c["mg"], c["cb"])[0]
    print(f"  {'변경':<24s}{'전체':>11s}{'낙폭':>8s}{'샤프':>7s}{'1등 대비':>10s}")
    print("  " + "-" * 62)
    print(f"  {'(기준)':<24s}{base:>10.0f}배{'':>8s}{'':>7s}{'—':>10s}")
    tweaks = [("차단기 25%", dict(cb=.25)), ("차단기 40%", dict(cb=.40)),
              ("총노출 100%", dict(mg=1.0)), ("총노출 150%", dict(mg=1.5)),
              ("돌파 배율 2배", dict(lev={**c["lev"], "break": 2.})),
              ("돌파 배율 5배", dict(lev={**c["lev"], "break": 5.})),
              ("돌파 비중 4%", dict(pt={**c["pt"], "break": .04})),
              ("돌파 비중 6%", dict(pt={**c["pt"], "break": .06})),
              ("롱 비중 2%", dict(pt={**c["pt"], "long": .02})),
              ("롱 비중 6%", dict(pt={**c["pt"], "long": .06}))]
    for lab, over in tweaks:
        a = {**{k: c[k] for k in ("pt", "lev", "mg", "cb")}, **over}
        x, _, m, s, _ = stats(tr, a["pt"], a["lev"], a["mg"], a["cb"])
        print(f"  {lab:<24s}{x:>10.0f}배{m*100:>7.1f}%{s:>7.2f}{x/base-1:>9.0%}")


if __name__ == "__main__":
    main()
