"""
ml/crash_clustering.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사다리가 막는 폭락과 못 막는 폭락

ml/deep_ladder.py에서 깊은 분할매수가 청산률을 절반으로 줄이는 것을
봤다(3배에서 7.3% → 4.4%). 평단이 내려가면 청산선까지 거리가 멀어
지니 당연하다. 그 숫자만 보면 "사다리를 깔면 3배를 쓸 수 있다"는
결론이 나온다.

폭락 구간을 떼어놓고 보면 그 결론이 성립하지 않는다.

    구간             2단 청산률   20단 청산률
    2022-05 루나        26%         7%     ← 사다리가 크게 막는다
    2022-11 FTX          5%         2%     ← 막는다
    2021-05 조정        31%        24%     ← 별로
    2020-03 코로나      33%        28%     ← 거의 못 막는다

두 종류가 있다.

  · **한 코인이 며칠에 걸쳐 무너지는 폭락**(루나·FTX). 다른 코인은
    버티고 있으므로 사다리가 평단을 낮출 시간이 있다. 효과가 크다.
  · **전 종목이 하루에 무너지는 폭락**(코로나·2021-05). 사다리 2단을
    채우기도 전에 청산선을 지나간다. 효과가 거의 없다.

계좌를 죽이는 것은 두 번째다. 2021-05-19 하루에 25~34종목이 동시에
청산된다. 암호화폐 42종은 폭락장에서 사실상 1종목이고, 분산이 되지
않는다.

그리고 홀드아웃(2024~2026)은 3배를 검증해주지 못한다. 청산 79건 중
78건이 학습구간(2018·2020·2021·2022)에 있다. 그 2년 반에 코로나급
폭락이 없었을 뿐이다. "홀드아웃 청산 1건"은 안전의 증거가 아니라
시험이 없었다는 증거다.

최종 수치 (투입 자본을 맞추고 배율만 올린 것):

    설정              최종   연복리  장중낙폭  청산    홀드  1년손실  최악1년   파산
    2단·2배(지금)    2.42배   11%   34.6%    10  1.64배   38%  0.83배    0%
    2단·3배          2.82배   13%   47.5%    94  1.95배   42%  0.64배    0%
    20단·2배         2.91배   13%   54.9%     9  1.64배   28%  0.63배    0%
    20단·3배         6.35배   24%   76.4%    37  2.13배   28%  0.45배    6%

20단·3배는 수익을 2.6배로 늘리지만 장중 낙폭이 76.4%이고, 1년 구간
16개 중 1개에서 자본이 절반 이하가 된다. 76% 낙폭을 실제로 견디는
사람은 드물다 — 바닥에서 끄면 6.35배는 애초에 받을 수 없는 숫자다.

사용법:
    python ml/crash_clustering.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
warnings.filterwarnings("ignore")
from collections import Counter
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from bot.oversold import strategy as S
from ml.backtest_current_bot import load, simulate
from ml.per_coin_rules import sim
from ml.deep_ladder import fracs_for

TE = pd.Timestamp("2024-01-01")
CFGS = [("2단 (지금 봇)", 2, 5.0), ("20단 · 폭20%", 20, 20.0)]
EPISODES = [("2020-03 코로나", "2020-02-15", "2020-04-15"),
            ("2021-05 조정",   "2021-05-01", "2021-07-01"),
            ("2022-05 루나",   "2022-05-01", "2022-06-15"),
            ("2022-11 FTX",    "2022-11-01", "2022-12-15")]
LIQ3X = -100.0 / 3.0 + 0.5      # 3배 강제청산선 = -32.8%


def load_all():
    d = {}
    for sym in S.SYMBOLS:
        g = load(sym)
        if g is None or len(g) < 400:
            continue
        d[sym] = tuple(g[k].astype(float).values
                       for k in ("open", "high", "low", "close")) + (g["datetime"].values,)
    return d


def build(data, n, span):
    step = span / max(n - 1, 1)
    fr = fracs_for(n)
    tr = []
    for sym, (o, h, l, c, dt) in data.items():
        tr += sim(o, h, l, c, dt, S.MA_PERIOD, S.ENTRY_THRESH, S.HOLD_BARS,
                  fr, [(1.0, S.BB_K)], S.STOP_PCT, sym=sym, step=step)
    return sorted(tr, key=lambda t: t["dt"])


def roll1y(tr, **kw):
    t0, t1 = tr[0]["dt"], tr[-1]["dt"]
    out = []
    for s in pd.date_range(t0, t1 - pd.Timedelta(days=365), freq="30D"):
        w = [t for t in tr if s <= t["dt"] < s + pd.Timedelta(days=365)]
        if len(w) < 5:
            continue
        r = simulate(w, **kw)
        out.append(0.0 if r["bust"] else r["final"])
    return np.array(out)


def main():
    argparse.ArgumentParser().parse_args()
    data = load_all()
    built = {lab: build(data, n, span) for lab, n, span in CFGS}

    print("=" * 96)
    print(f"  청산은 언제 터지나 — 3배 청산선 {LIQ3X:.1f}%를 뚫은 거래의 연도별 분포")
    print("=" * 96)
    liqs = {lab: [t for t in tr if t["mae"] <= LIQ3X] for lab, tr in built.items()}
    cnts = {lab: Counter(pd.Timestamp(t["dt"]).year for t in v) for lab, v in liqs.items()}
    years = sorted({y for c in cnts.values() for y in c})
    print(f"\n  {'연도':>6s}" + "".join(f"{lab:>18s}" for lab, _, _ in CFGS))
    print("  " + "-" * 44)
    for y in years:
        row = "".join(f"{cnts[lab].get(y, 0):>14}건" for lab, _, _ in CFGS)
        tag = ("  ← 코로나" if y == 2020 else
               "  ← 루나·FTX" if y == 2022 else
               "  ← 홀드아웃" if y >= 2024 else "")
        print(f"  {y:>6}{row}{tag}")
    print("  " + "-" * 44)
    for lab, _, _ in CFGS:
        n_all, n_liq = len(built[lab]), sum(cnts[lab].values())
        ho = sum(v for y, v in cnts[lab].items() if y >= 2024)
        print(f"  {lab}: {n_all:,}건 중 청산 {n_liq}건 ({n_liq/n_all*100:.1f}%) "
              f"· 그중 홀드아웃 {ho}건")

    print("\n  최악의 하루 — 하루에 몇 건이 동시에 청산되나")
    for lab, _, _ in CFGS:
        d = Counter(pd.Timestamp(t["dt"]).date() for t in liqs[lab])
        print(f"  {lab}: " + " · ".join(f"{k} {v}건" for k, v in d.most_common(3)))
    print("  42종은 폭락장에서 사실상 1종목이다. 사다리는 이 꼬리를 못 줄인다.")

    print("\n" + "=" * 96)
    print("  폭락 구간별 — 사다리가 막는 종류와 못 막는 종류")
    print("=" * 96)
    print(f"\n  {'구간':>16s}" + "".join(f"{lab:>26s}" for lab, _, _ in CFGS))
    print("  " + "-" * 70)
    for elab, s0, s1 in EPISODES:
        cells = []
        for lab, _, _ in CFGS:
            w = [t for t in built[lab]
                 if pd.Timestamp(s0) <= pd.Timestamp(t["dt"]) <= pd.Timestamp(s1)]
            if not w:
                cells.append(f"{'—':>26s}")
                continue
            mae = np.array([t["mae"] for t in w])
            cells.append(f"{len(w):>8}건 청산{(mae <= LIQ3X).mean()*100:>5.0f}%"
                         f" 최악{mae.min():>6.0f}%")
        print(f"  {elab:>16s}" + "".join(cells))

    print("\n" + "=" * 96)
    print("  같은 투입 자본에서 배율만 올렸을 때 실제로 감수하는 것")
    print("=" * 96)
    print(f"\n  {'설정':<20s}{'최종':>9s}{'연복리':>7s}{'장중낙폭':>9s}{'청산':>6s}"
          f"{'홀드':>8s}{'1년손실':>8s}{'최악1년':>8s}{'파산':>6s}")
    print("  " + "-" * 82)
    dep0 = None
    for lab, n, span, lev in [("지금 봇 2단·2배", 2, 5.0, 2.0), ("2단·3배", 2, 5.0, 3.0),
                              ("20단·2배", 20, 20.0, 2.0), ("20단·3배", 20, 20.0, 3.0)]:
        tr = build(data, n, span)
        dep = np.array([t["deployed"] for t in tr])
        if dep0 is None:
            dep0 = dep.mean()
        pt = 0.015 * (dep0 / dep.mean())
        kw = dict(leverage=lev, per_trade=pt, max_gross=0.4 * (pt / 0.015),
                  cb=0.20, cool_days=30, min_equity=0.0, compound=True)
        f = simulate(tr, **kw)
        b = simulate([t for t in tr if t["dt"] >= TE], **kw)
        y = roll1y(tr, **kw)
        yrs = (tr[-1]["dt"] - tr[0]["dt"]).days / 365.25
        cagr = (f["final"] ** (1 / yrs) - 1) * 100 if f["final"] > 0 else -100
        print(f"  {lab:<20s}{f['final']:>8.2f}배{cagr:>6.0f}%{f['mdd_low']*100:>8.1f}%"
              f"{f['liq']:>6}{b['final']:>7.2f}배{(y<1).mean()*100:>7.0f}%"
              f"{y.min():>7.2f}배{(y<=0.5).mean()*100:>5.0f}%")
    print("\n  파산 = 1년 구간 중 자본이 절반 이하로 줄어든 비율")
    print("=" * 96)


if __name__ == "__main__":
    main()
