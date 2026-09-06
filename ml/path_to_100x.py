"""
ml/path_to_100x.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
100배에 실제로 도달하는 설정을 전부 찾고, 그 대가를 같이 적는다

"100배가 되느냐"만 물으면 답은 쉽다. 배율을 올리면 백테스트 숫자는
커진다. 진짜 질문은 **그 경로를 사람이 통과할 수 있느냐**다.

그래서 도달 여부만이 아니라 다음을 같이 낸다:
    · 100배를 처음 찍은 날짜와 그때까지 걸린 기간
    · 그 경로에서 겪는 최대 낙폭과 그 시점
    · 원금 아래로 내려가 있던 기간 (수중 기간)
    · 강제청산 횟수

종목 수도 같이 비교한다. BTC 단독 9년 5.5배, 메이저 12종 58.5배로
이미 10배 차이가 났다. 46종으로 늘리면 신호가 더 늘어 자본 회전이
빨라지는지, 아니면 종목이 나빠져 상쇄되는지는 돌려봐야 안다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, glob, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ml.full_optimizer import build, resolve, RT, F8
from ml.majors_only import MAJORS


def all_symbols(interval="4h"):
    out = []
    for f in sorted(glob.glob(f"data/*_{interval}_all.csv.gz")):
        s = os.path.basename(f).split(f"_{interval}_")[0]
        if s.endswith("USDT"):
            out.append(s)
    return out


def run(trades, kind, prm, lev, per_trade, max_gross, stop=-40.0, bar_h=4.0):
    """자본 곡선을 통째로 돌려준다 — 도달 시점과 수중 기간을 재려면 경로가 필요하다"""
    liq = -100.0/lev + 0.5
    eq, peak, mdd = 1.0, 1.0, 0.0
    mdd_at = None
    open_pos, curve = [], []
    taken = liqs = wins = 0
    hit100 = None
    under = 0            # 원금 아래에 있던 거래 수
    for t in trades:
        now = t["dt"]
        open_pos = [p for p in open_pos if p[0] > now]
        if any(p[2] == t["sym"] for p in open_pos):
            continue
        gross = sum(p[1] for p in open_pos)
        margin = eq * per_trade; notional = margin * lev
        if gross + notional > eq * max_gross * lev:
            continue
        r, k, was_liq = resolve(t, kind, prm, stop, liq)
        if was_liq: liqs += 1
        net = r - RT - F8*(k*bar_h/8.0)
        eq += max(margin*lev*net/100, -margin)
        if eq <= 0:
            return {"final": 0.0, "mdd": 1.0, "hit100": None, "n": taken,
                    "liq": liqs, "wr": 0.0, "under": under, "curve": curve,
                    "mdd_at": mdd_at, "bust": True}
        taken += 1; wins += net > 0
        if eq < 1.0: under += 1
        if peak > 0 and 1 - eq/peak > mdd:
            mdd = 1 - eq/peak; mdd_at = now
        peak = max(peak, eq)
        if hit100 is None and eq >= 100:
            hit100 = now
        curve.append((now, eq))
        open_pos.append((t["dts"][min(k, len(t["dts"])-1)], notional, t["sym"]))
    return {"final": eq, "mdd": mdd, "hit100": hit100, "n": taken, "liq": liqs,
            "wr": wins/max(taken,1)*100, "under": under, "curve": curve,
            "mdd_at": mdd_at, "bust": False}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default="both", choices=["majors","all","both"])
    a = ap.parse_args()

    unis = []
    if a.universe in ("majors","both"): unis.append(("메이저 12종", MAJORS))
    if a.universe in ("all","both"):    unis.append(("전체 46종", all_symbols()))

    print("=" * 108)
    print("  100배 도달 경로 — 도달 여부와 그 대가를 같이 본다")
    print(f"  비용 왕복 {RT}% + 펀딩 {F8}%/8h · 격리마진 · 손절 -40% · 강제청산은 봉 안 저가 판정")
    print("=" * 108)

    EXITS = [("fixed", 20, "고정20봉"), ("atr", 2.0, "ATR×2")]
    SIZES = [(0.15, 1.0, "6종"), (0.125, 1.0, "8종"), (0.10, 1.0, "10종")]

    for uname, syms in unis:
        T = build(symbols=syms)
        t0, t1 = T[0]["dt"], T[-1]["dt"]
        yrs = (t1 - t0).days / 365.25
        print(f"\n{'─'*108}")
        print(f"  [{uname}]  종목 {len(set(t['sym'] for t in T))}개 · 신호 {len(T):,}건 · {yrs:.1f}년")
        print(f"{'─'*108}")
        print(f"  {'설정':22s}{'배율':>5s}{'거래':>6s}{'승률':>7s}{'최종':>11s}"
              f"{'낙폭':>7s}{'100배 도달':>13s}{'소요':>7s}{'청산':>5s}")
        print("  " + "-" * 104)
        best = []
        for kind, prm, elab in EXITS:
            for pt, mg, slab in SIZES:
                for lev in (2, 3, 4):
                    r = run(T, kind, prm, lev, pt, mg)
                    if r["bust"]:
                        hit = "파산"; took = "—"
                    elif r["hit100"]:
                        hit = str(r["hit100"])[:10]
                        took = f"{(r['hit100']-t0).days/365.25:.1f}년"
                    else:
                        hit = "미도달"; took = "—"
                    fin = "0" if r["bust"] else f"{r['final']:,.0f}배"
                    print(f"  {elab+' · '+slab:22s}{lev:>4}x{r['n']:>6,}{r['wr']:>6.1f}%"
                          f"{fin:>11s}{r['mdd']*100:>6.1f}%{hit:>13s}{took:>7s}{r['liq']:>5}")
                    if r["hit100"]:
                        best.append((elab, slab, lev, r))
            print()

        if best:
            print(f"  ── 100배 도달 설정 중 낙폭이 가장 작은 것 ──")
            e, s, lv, r = min(best, key=lambda x: x[3]["mdd"])
            print(f"    {e} · {s} · {lv}배")
            print(f"    최종 {r['final']:,.0f}배 · 승률 {r['wr']:.1f}% · 거래 {r['n']:,}건")
            print(f"    100배 도달 {str(r['hit100'])[:10]} ({(r['hit100']-t0).days/365.25:.1f}년)")
            print(f"    최대낙폭 {r['mdd']*100:.1f}% (바닥 {str(r['mdd_at'])[:10]})")
            print(f"    원금 아래에 있던 거래 {r['under']:,}건 / {r['n']:,}건 "
                  f"({r['under']/r['n']*100:.0f}%)")
            print(f"    강제청산 {r['liq']}회")


if __name__ == "__main__":
    main()
