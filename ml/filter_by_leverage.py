"""
ml/filter_by_leverage.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
지표 필터의 값어치는 배율에 따라 완전히 뒤집힌다

앞선 두 스크립트(indicator_backtest / coin_indicator_backtest)는
63개 필터를 전부 **배율 2배**에서 판정했고 통과 0개였다. 그 결론은
2배에서는 맞다. 하지만 일반화하면 틀린다.

이유가 명확하다.
  · 낮은 배율에서 이 규칙은 애초에 파산하지 않는다. 그러니 필터가
    하는 일은 "거래 수를 줄이는 것"뿐이고, 복리에서 거래 수는 자산이라
    무조건 손해다. (ml/filter_breakeven.py 참고)
  · 높은 배율에서는 생존이 구속조건이 된다. 8배 무필터는 189개 1년
    창에서 파산확률 33%, 전형적인 해가 0.83배(손실)다. 여기서 필터는
    거래를 줄이는 대가로 파산을 막는다. 그 교환이 성립한다.

그래서 같은 필터를 2배와 8배에서 나란히 돌린다. 같은 필터가 한쪽에서
손해, 다른 쪽에서 결정적으로 바뀌는 것을 보이기 위한 스크립트다.

부수적으로 확인되는 것: "나스닥 20일 상승"이 유일하게 살아남은
외부 지표였는데, BTC>MA200 단독이 그것보다 낫다. 거시 데이터는
필요 없다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from ml.backtest_current_bot import build_all, simulate
from ml.hunt_50x import window_stats
import ml.coin_indicator_backtest as ci
from ml.indicator_backtest import load_funding, load_metrics

TE = pd.Timestamp("2024-01-01")

TESTS = [
    ("필터 없음",            None,            lambda t: True),
    ("BTC > MA200",         "btc_ma200",     lambda t: t["btc_ma200"] > 0),
    ("BTC > MA50",          "btc_ma50",      lambda t: t["btc_ma50"] > 0),
    ("BTC>MA200 & >MA50",   "btc_ma50",      lambda t: t["btc_ma200"] > 0 and t["btc_ma50"] > 0),
    ("공포탐욕 > 50",         "fng",           lambda t: t["fng"] > 50),
    ("공포탐욕 < 20",         "fng",           lambda t: t["fng"] < 20),
    ("시장 폭 > 50%",        "breadth",       lambda t: t["breadth"] > 50),
    ("BTC 변동성 z>1",       "btc_vol_z",     lambda t: t["btc_vol_z"] > 1),
    ("동시신호 6종 이상",       "n_signal",      lambda t: t["n_signal"] >= 6),
    ("알트 > BTC",           "alt_minus_btc", lambda t: t["alt_minus_btc"] > 0),
    ("펀딩 > 0",             "fr_bps",        lambda t: t["fr_bps"] > 0),
]


def row(T, name, col, fn, lev, pt):
    have = [t for t in T if col is None or not pd.isna(t.get(col, np.nan))]
    sub = [t for t in have if fn(t)]
    if len(sub) < 60:
        return None
    d = window_stats(sub, lev, pt, 0.25, 30, compound=True)
    if d.empty:
        return None
    a = [t for t in sub if pd.Timestamp(t["dt"]) < TE]
    b = [t for t in sub if pd.Timestamp(t["dt"]) >= TE]
    ra = simulate(a, lev, pt, 1.0, 0.25, 30, 1e-6, compound=True)
    rb = simulate(b, lev, pt, 1.0, 0.25, 30, 1e-6, compound=True) if len(b) >= 20 else None
    return {"name": name, "n": len(sub), "max": d.mult.max(),
            "p50": (d.mult >= 50).mean() * 100, "median": d.mult.median(),
            "p_bust": (d.mult <= 0.01).mean() * 100, "mdd": d.mdd.median() * 100,
            "tr": ra["final"], "ho": rb["final"] if rb else np.nan}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--levs", nargs="*", type=float, default=[2.0, 3.0, 5.0, 8.0])
    ap.add_argument("--per-trade", type=float, default=None,
                    help="고정할 경우. 기본은 배율별 기본값")
    a = ap.parse_args()

    market, volz, symvol = ci.build_coin_market()
    senti = ci.load_crypto_sentiment()
    if not senti.empty:
        market = market.join(senti.reindex(market.index, method="ffill"))
    trades, have, _ = build_all()
    T = ci.attach(trades, market, {"f": load_funding(), "m": load_metrics()},
                  volz, symvol)

    print("=" * 96)
    print("  같은 필터를 배율별로 — 낮은 배율에선 손해, 높은 배율에선 생존장치")
    print("  전부 코인 지표만 (거시경제 제외) · 복리 · 청산 저가판정 · 189개 1년 창")
    print("=" * 96)

    for lev in a.levs:
        pt = a.per_trade if a.per_trade else (0.05 if lev <= 2 else 0.10)
        print(f"\n  ── 배율 {lev:.0f}배 / 동시{round(1/pt)}")
        print(f"  {'필터':<22s}{'거래':>6s}{'1년최대':>10s}{'50배확률':>9s}{'중앙':>8s}"
              f"{'파산':>6s}{'낙폭':>7s}{'학습':>10s}{'홀드':>10s}")
        print("  " + "-" * 84)
        rows = [r for r in (row(T, n, c, f, lev, pt) for n, c, f in TESTS) if r]
        ref = rows[0]
        for r in rows:
            better = (r["median"] > ref["median"] and r["p_bust"] <= ref["p_bust"])
            print(f"  {r['name']:<22s}{r['n']:>6d}{r['max']:>9.1f}배{r['p50']:>8.1f}%"
                  f"{r['median']:>7.2f}배{r['p_bust']:>5.0f}%{r['mdd']:>6.0f}%"
                  f"{r['tr']:>9.1f}배{r['ho']:>9.2f}배{'  ✅' if better else ''}")
        n_better = sum(1 for r in rows[1:]
                       if r["median"] > ref["median"] and r["p_bust"] <= ref["p_bust"])
        print(f"    → 필터 없음보다 '전형적인 해'가 낫고 파산도 낮은 것: "
              f"{n_better} / {len(rows)-1}")

    print(f"\n  ✅ = 중앙값이 필터 없음보다 높고 파산확률도 같거나 낮음")


if __name__ == "__main__":
    main()
