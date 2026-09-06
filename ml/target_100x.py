"""
ml/target_100x.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
100만원 → 1억 (100배) 이 실제로 어떤 확률인가

연복리만 보면 착시가 생긴다. "연복리 132%"는 8.8년 평균이고, 그 안에는
자본이 2/3 날아간 구간이 들어 있다. 1년만 굴린다면 어느 1년이냐에 따라
결과가 완전히 다르다.

그래서 백테스트 전 구간에 **1년짜리 창을 겹쳐가며 굴린다**. 2017년
9월 시작, 2017년 10월 시작, ... 이렇게 모든 시작 시점에 대해 1년 뒤
결과를 낸다. 그 분포가 "1년 굴리면 무슨 일이 생기는가"의 답이다.

같이 보는 것:
    · 1년 창의 수익 분포 (중앙값·최악·최고)
    · 원금 절반 이하로 떨어진 창의 비율
    · 100배까지 걸리는 기간
    · 목표를 100배로 잡았을 때 필요한 배율과 그때의 파산 확률
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ml.full_optimizer import build, simulate, TRAIN_END

CONFIGS = [
    ("고정 20봉 · 6종목 · 3배", "fixed", 20, 3, 0.15, 1.0),
    ("ATR×2 · 8종목 · 3배",     "atr",  2.0, 3, 0.125, 1.0),
    ("고정 20봉 · 2종목 · 2배", "fixed", 20, 2, 0.25, 0.5),
    ("고정 20봉 · 2종목 · 1배", "fixed", 20, 1, 0.25, 0.5),
    ("고정 10봉 · 6종목 · 2배", "fixed", 10, 2, 0.15, 1.0),
]


def rolling_years(T, kind, prm, lev, pt, mg, step_days=30):
    """모든 시작 시점에 대해 1년 뒤 배수를 낸다"""
    dts = pd.DatetimeIndex([t["dt"] for t in T])
    start, end = dts[0], dts[-1] - pd.Timedelta(days=365)
    res = []
    cur = start
    while cur <= end:
        win = [t for t in T if cur <= t["dt"] < cur + pd.Timedelta(days=365)]
        if len(win) >= 15:
            r = simulate(win, kind, prm, lev, pt, mg)
            res.append({"start": cur, "mult": r["final"], "mdd": r["mdd"],
                        "n": r["n"], "wr": r["wr"]})
        cur += pd.Timedelta(days=step_days)
    return pd.DataFrame(res)


def main():
    T = build()
    print("=" * 100)
    print("  100만원 → 1억 (100배) 검증 — 1년짜리 창을 모든 시작 시점에 굴린다")
    print(f"  신호 {len(T)}건 · {str(T[0]['dt'])[:10]} ~ {str(T[-1]['dt'])[:10]}")
    print("=" * 100)

    print(f"\n  {'설정':26s}{'창수':>5s}{'중앙':>8s}{'최악':>8s}{'최고':>9s}"
          f"{'반토막':>8s}{'2배+':>7s}{'10배+':>7s}{'평균낙폭':>9s}")
    print("  " + "-" * 88)
    store = {}
    for lab, kind, prm, lev, pt, mg in CONFIGS:
        d = rolling_years(T, kind, prm, lev, pt, mg)
        store[lab] = d
        print(f"  {lab:26s}{len(d):>5}{d['mult'].median():>7.2f}배{d['mult'].min():>7.2f}배"
              f"{d['mult'].max():>8.1f}배{(d['mult']<0.5).mean()*100:>7.0f}%"
              f"{(d['mult']>=2).mean()*100:>6.0f}%{(d['mult']>=10).mean()*100:>6.0f}%"
              f"{d['mdd'].mean()*100:>8.1f}%")

    print(f"\n  '반토막' = 1년 뒤 원금 절반 이하로 끝난 창의 비율")
    print(f"  '10배+'  = 1년 만에 10배 이상 낸 창의 비율")

    print(f"\n{'='*100}")
    print("  100배까지 걸리는 기간 (전 구간 연복리 기준)")
    print("=" * 100)
    full = {}
    for lab, kind, prm, lev, pt, mg in CONFIGS:
        r = simulate(T, kind, prm, lev, pt, mg)
        full[lab] = r
        if r["final"] <= 1:
            print(f"  {lab:26s} 원금 손실 — 도달 불가"); continue
        g = r["final"] ** (1/r["yrs"])
        yrs = np.log(100) / np.log(g)
        print(f"  {lab:26s} 연복리 {r['cagr']:>4.0f}%  →  100배까지 "
              f"{yrs:>5.1f}년   (전구간 최대낙폭 {r['mdd']*100:.0f}%)")

    print(f"\n{'='*100}")
    print("  1년 안에 100배를 내려면")
    print("=" * 100)
    best = max(full.items(), key=lambda kv: kv[1]["cagr"])
    print(f"  최고 설정의 연복리는 {best[1]['cagr']:.0f}% ({best[0]}).")
    print(f"  100배 = 연복리 9,900%. 필요한 배율을 역산하면:")
    lab, kind, prm, lev, pt, mg = CONFIGS[0]
    for L in (3, 5, 8, 10, 15, 20, 30):
        r = simulate(T, kind, prm, L, pt, mg)
        st = "💀 파산" if r["final"] <= 0 else f"{r['final']:,.0f}배"
        print(f"    {L:>2}배 → 전구간 {st:>12s}  낙폭 {r['mdd']*100:>5.1f}%  강제청산 {r['liq']:>3}회")

    print(f"\n{'='*100}")
    print("  1년 창 분포 상세 — 가장 공격적인 설정")
    print("=" * 100)
    d = store["고정 20봉 · 6종목 · 3배"]
    for q, lab in ((0.05,"하위 5%"),(0.25,"하위 25%"),(0.5,"중앙"),
                   (0.75,"상위 25%"),(0.95,"상위 5%")):
        print(f"    {lab:10s} {d['mult'].quantile(q):>7.2f}배")
    d2 = d.copy(); d2["y"] = pd.DatetimeIndex(d2["start"]).year
    print(f"\n    {'시작연도':10s}{'창수':>5s}{'중앙 배수':>11s}{'최악':>9s}")
    for y, g in d2.groupby("y"):
        print(f"    {y:<10d}{len(g):>5}{g['mult'].median():>10.2f}배{g['mult'].min():>8.2f}배")


if __name__ == "__main__":
    main()
