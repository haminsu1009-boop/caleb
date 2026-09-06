"""
ml/dca_1year.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
적립식 1년 — 100만원 시작 + 월 30만원

일시불과 적립식은 결과가 다르다. 적립식은 하락 구간에 넣은 돈이 더
싼 값에 들어가고, 고점에 넣은 돈은 그대로 물린다. 그래서 같은 전략,
같은 기간이라도 최종 금액이 달라진다.

또 하나 중요한 차이: 뒤에 넣은 돈은 굴릴 시간이 짧다. 12월에 넣은
30만원은 한 달만 일한다. 그래서 "총 납입액 대비 수익률"은 일시불의
수익률보다 구조적으로 낮게 나온다. 이것은 전략의 문제가 아니라
적립식의 성질이다.

비교 기준을 셋 둔다:
    그냥 저축      460만원 (원금 그대로)
    일시불 460만원  처음부터 전액을 넣었을 경우
    적립식         100만 + 월 30만

189개 시작 시점 전부에 대해 계산하고 분포로 보고한다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ml.sim_correct import Pos
from ml.full_optimizer import build, resolve, RT, F8
from ml.path_to_100x import all_symbols

START = 1_000_000
MONTHLY = 300_000


def sim_dca(trades, kind, prm, lev, per, mg, start_dt, monthly=MONTHLY,
            start_cap=START, cb=0.25, cool=30, stop=-40.0, bh=4.0):
    """월 적립을 반영한 1년 시뮬레이션. 금액 단위는 원."""
    liq = -100.0/lev + 0.5
    cash = float(start_cap)
    deposited = float(start_cap)
    next_dep = start_dt + pd.DateOffset(months=1)
    peak = cash; mdd = 0.0; peak_l = cash; mdd_l = 0.0
    openp = {}; taken = wins = liqs = halts = 0
    halted = None

    for t in sorted(trades, key=lambda x: x["dt"]):
        now = t["dt"]
        # 적립: 해당 시점이 지났으면 현금에 더한다
        while now >= next_dep and deposited < start_cap + monthly*12:
            cash += monthly; deposited += monthly
            next_dep = next_dep + pd.DateOffset(months=1)
        for s in [s for s, p in openp.items() if p.exit_dt <= now]:
            cash += openp.pop(s).realized
        eq   = cash + sum(p.unreal(now) for p in openp.values())
        eq_l = cash + sum(p.unreal(now, True) for p in openp.values())
        if eq <= 0:
            return {"final": 0.0, "dep": deposited, "mdd": 1.0, "mdd_low": 1.0,
                    "n": taken, "wr": 0.0, "bust": True, "halts": halts}
        if 1 - eq/peak > mdd: mdd = 1 - eq/peak
        peak = max(peak, eq)
        peak_l = max(peak_l, eq_l); mdd_l = max(mdd_l, 1 - eq_l/peak_l)
        if cb is not None:
            if halted is not None and now < halted: continue
            if 1 - eq/peak >= cb:
                halted = now + pd.Timedelta(days=cool); halts += 1; peak = eq; continue
        if t["sym"] in openp: continue
        gross = sum(p.notional for p in openp.values())
        margin = eq * per; notional = margin * lev
        if gross + notional > eq * mg * lev: continue
        r, k, was_liq = resolve(t, kind, prm, stop, liq)
        if was_liq: liqs += 1
        net = r - RT - F8*(k*bh/8.0)
        realized = max(margin*lev*net/100, -margin)
        taken += 1; wins += net > 0
        kk = min(k, len(t["dts"])-1)
        openp[t["sym"]] = Pos(t["sym"], t["e"], notional, t["dts"][kk],
                              t["dts"][:kk+1], t["o"][:kk+1], t["l"][:kk+1],
                              realized, max(stop, liq))
    # 미납입분이 남았으면 마저 더한다 (거래가 일찍 끝난 창)
    while deposited < start_cap + monthly*12:
        cash += monthly; deposited += monthly
    for s in list(openp): cash += openp.pop(s).realized
    return {"final": cash, "dep": deposited, "mdd": mdd, "mdd_low": mdd_l,
            "n": taken, "wr": wins/max(taken,1)*100, "bust": False, "halts": halts}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=int, default=15)
    a = ap.parse_args()
    T = build(symbols=all_symbols())
    t0, t1 = T[0]["dt"], T[-1]["dt"]
    starts = pd.date_range(t0, t1 - pd.Timedelta(days=365), freq=f"{a.step}D")
    TOTAL = START + MONTHLY*12

    CFG = [("fixed", 20, 0.05, 1.0, 1, "20봉·20종동시·1배"),
           ("fixed", 20, 0.05, 1.0, 2, "20봉·20종동시·2배"),
           ("atr",  2.0, 0.033, 1.0, 2, "ATR×2·30종동시·2배"),
           ("fixed", 20, 0.10, 1.0, 3, "20봉·10종동시·3배")]

    print("=" * 100)
    print(f"  적립식 1년 — 시작 {START:,}원 + 월 {MONTHLY:,}원")
    print(f"  총 납입 {TOTAL:,}원 · 46종 · 차단기 -25% · {len(starts)}개 시작 시점")
    print("=" * 100)
    print(f"\n  {'설정':22s}{'하위5%':>12s}{'하위25%':>12s}{'중앙':>12s}"
          f"{'상위25%':>12s}{'상위5%':>12s}")
    print("  " + "-" * 84)
    store = {}
    for kind, prm, per, mg, lev, lab in CFG:
        res = []
        for s in starts:
            win = [t for t in T if s <= t["dt"] < s + pd.Timedelta(days=365)]
            if len(win) < 25: continue
            r = sim_dca(win, kind, prm, lev, per, mg, s)
            res.append({"s": s, "f": r["final"], "mdd": r["mdd"],
                        "low": r["mdd_low"], "n": r["n"]})
        d = pd.DataFrame(res); store[lab] = d
        q = [d.f.quantile(x) for x in (.05,.25,.5,.75,.95)]
        print(f"  {lab:22s}" + "".join(f"{v:>11,.0f}" for v in q))

    print(f"\n  {'설정':22s}{'납입대비 중앙':>13s}{'원금손실':>9s}{'2배+':>7s}"
          f"{'최악':>12s}{'최고':>13s}{'연거래':>7s}")
    print("  " + "-" * 84)
    for lab, d in store.items():
        print(f"  {lab:22s}{(d.f.median()/TOTAL-1)*100:>+12.1f}%"
              f"{(d.f < TOTAL).mean()*100:>8.0f}%{(d.f >= TOTAL*2).mean()*100:>6.0f}%"
              f"{d.f.min():>12,.0f}{d.f.max():>13,.0f}{d.n.mean():>7.0f}")

    print(f"\n  {'설정':22s}{'평균 계좌낙폭':>14s}{'평균 장중낙폭':>14s}{'최악 장중':>11s}")
    print("  " + "-" * 64)
    for lab, d in store.items():
        print(f"  {lab:22s}{d.mdd.mean()*100:>13.0f}%{d.low.mean()*100:>13.0f}%"
              f"{d.low.max()*100:>10.0f}%")

    print(f"\n{'='*100}")
    print(f"  비교 — 아무것도 안 하면 {TOTAL:,}원")
    print("=" * 100)
    d = store["20봉·20종동시·2배"]
    print(f"  {'':22s}{'금액':>13s}{'납입 대비':>11s}")
    print(f"  {'그냥 저축':22s}{TOTAL:>13,}{0:>10.0f}%")
    for q, lab in ((.05,"하위 5%"),(.25,"하위 25%"),(.5,"중앙"),(.75,"상위 25%"),(.95,"상위 5%")):
        v = d.f.quantile(q)
        print(f"  {'2배 운용 · '+lab:22s}{v:>13,.0f}{(v/TOTAL-1)*100:>+10.1f}%")

    print(f"\n  시작 연도별 (2배) — 언제 시작하느냐")
    d2 = d.copy(); d2["y"] = pd.DatetimeIndex(d2.s).year
    print(f"  {'연도':8s}{'창':>4s}{'중앙':>13s}{'최악':>13s}{'최고':>14s}{'손실확률':>9s}")
    for y, g in d2.groupby("y"):
        print(f"  {y:<8d}{len(g):>4}{g.f.median():>13,.0f}{g.f.min():>13,.0f}"
              f"{g.f.max():>14,.0f}{(g.f < TOTAL).mean()*100:>8.0f}%")


if __name__ == "__main__":
    main()
