"""
ml/btc_combos.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
지표 2개 조합 전수 탐색 — 마지막 미탐색 영역

단일 조건은 다 훑었다. 남은 것은 조합이다. 세션 초반에 조합 탐색을
피했던 이유가 있다: 조건을 겹칠수록 표본이 줄고, 경우의 수는 제곱으로
늘어 과최적화가 거의 확실해진다. 그래서 이번엔 방어를 세 겹으로 건다.

    1. 각 단일 조건은 학습구간에서 정한 분위 임계값만 쓴다
    2. 조합의 표본이 최소 개수 미만이면 버린다
    3. Bonferroni 보정을 조합 개수 전체에 건다
    4. 추가로 **조합이 단일 조건보다 나아야 한다** — 두 조건 각각의
       성적보다 조합이 나은 경우만 남긴다. 이게 없으면 그냥 더 강한
       한 조건을 두 번 쓴 것과 구분되지 않는다.

4번이 핵심이다. "A와 B를 모두 만족" 조건은 A 하나보다 표본이 적고
승률이 높아 보이기 쉬운데, 그것이 B의 기여인지 단순히 더 극단적인
A인지 구분해야 한다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings, itertools
import numpy as np
import pandas as pd
from scipy.stats import norm

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ml.btc_all_timeframes import load, features, ROUND_TRIP, TRAIN_FRAC

# 단일 스캔에서 실제로 살아남은 지표군만 쓴다. 전부 넣으면 조합 수가
# 폭발하고 보정이 감당 못 한다.
CORE = ["dd_from_high", "vs_ma200", "vs_ma50", "vs_ma20", "atr_pct",
        "rsi14", "bb_pos", "adx", "macd_hist", "vol_ratio", "streak",
        "up_from_low", "bb_squeeze", "stoch_k", "cci", "mfi"]
PCTS = [5, 10, 20, 80, 90, 95]


def wilson_lo(w, n, z):
    if n == 0: return 0.0
    p = w/n; den = 1+z*z/n; ctr = p+z*z/(2*n)
    return (ctr - z*np.sqrt(p*(1-p)/n + z*z/(4*n*n)))/den*100


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--H", type=int, default=20)
    ap.add_argument("--min-n", type=int, default=120)
    ap.add_argument("--top", type=int, default=20)
    a = ap.parse_args()

    g = load(a.tf); f = features(g)
    o = g["open"].astype(float)
    entry = o.shift(-1)
    px = ((o.shift(-1-a.H)/entry - 1) * 100).values
    L = px - ROUND_TRIP
    S = -px - ROUND_TRIP
    fin = np.isfinite(px)
    n = len(g); split = int(n*TRAIN_FRAC)
    tr = np.zeros(n, bool); tr[:split] = True

    cols = [c for c in CORE if c in f.columns]
    # 단일 마스크 사전 생성
    masks = {}
    for c in cols:
        s = f[c].values
        base = s[tr & np.isfinite(s)]
        if len(base) < 500: continue
        for p in PCTS:
            thr = np.percentile(base, p)
            op = "<=" if p < 50 else ">="
            masks[f"{c} {op} {thr:.4g}"] = (s <= thr) if op == "<=" else (s >= thr)

    keys = list(masks)
    n_tests = len(keys)*(len(keys)-1)//2 * 2
    z = norm.ppf(1 - 0.05/(2*n_tests))
    base_ho = {"L": (L[~tr & fin] > 0).mean()*100, "S": (S[~tr & fin] > 0).mean()*100}

    print("=" * 100)
    print(f"  BTC 지표 2개 조합 — {a.tf}, {a.H}봉 보유")
    print(f"  단일 조건 {len(keys)}개 → 조합 {len(keys)*(len(keys)-1)//2:,}개 × 방향 2 = {n_tests:,} 검정")
    print(f"  Bonferroni z = {z:.3f}  ·  기준선 롱 {base_ho['L']:.1f}% / 숏 {base_ho['S']:.1f}%")
    print("=" * 100)

    # 단일 조건 성적을 먼저 구해둔다 (조합이 이것을 이겨야 한다)
    single = {}
    for k, m in masks.items():
        for sd, pnl in (("L", L), ("S", S)):
            ok = m & fin & ~tr
            if ok.sum() < a.min_n: continue
            single[(k, sd)] = (pnl[ok] > 0).mean()*100

    rows = []
    for k1, k2 in itertools.combinations(keys, 2):
        if k1.split()[0] == k2.split()[0]:      # 같은 지표끼리는 무의미
            continue
        m = masks[k1] & masks[k2]
        for sd, pnl in (("L", L), ("S", S)):
            a_tr = m & fin & tr; a_ho = m & fin & ~tr
            if a_tr.sum() < a.min_n or a_ho.sum() < a.min_n:
                continue
            pt, ph = pnl[a_tr], pnl[a_ho]
            if pt.mean() <= 0 or ph.mean() <= 0:
                continue
            w = int((ph > 0).sum()); wr = w/len(ph)*100
            if wr <= base_ho[sd]:
                continue
            lo = wilson_lo(w, len(ph), z)
            if lo <= base_ho[sd]:
                continue
            # 조합이 두 단일 조건 각각보다 나아야 한다
            s1 = single.get((k1, sd), -1); s2 = single.get((k2, sd), -1)
            if wr <= max(s1, s2):
                continue
            rows.append({"cond": f"{k1}  AND  {k2}", "side": "롱" if sd=="L" else "숏",
                         "n_tr": int(a_tr.sum()), "wr_tr": (pt>0).mean()*100,
                         "n_ho": len(ph), "wr_ho": wr, "lo": lo,
                         "mean": ph.mean(), "best_single": max(s1, s2)})

    if not rows:
        print("\n  통과 조합 없음 — 단일 조건을 뛰어넘는 2개 조합이 보정을 견디지 못했다")
        return
    d = pd.DataFrame(rows).sort_values("lo", ascending=False)
    print(f"\n  통과 {len(d)}개\n")
    print(f"  {'방향':5s}{'조건':56s}{'홀드n':>7s}{'승률':>7s}{'하한':>7s}{'단일최고':>9s}{'거래당':>8s}")
    print("  " + "-" * 98)
    for _, x in d.head(a.top).iterrows():
        print(f"  {x['side']:5s}{x['cond']:56s}{x.n_ho:>7,}{x.wr_ho:>6.1f}%"
              f"{x.lo:>6.1f}%{x.best_single:>8.1f}%{x['mean']:>+7.2f}%")
    os.makedirs("ml/saved_models", exist_ok=True)
    d.to_csv(f"ml/saved_models/btc_combos_{a.tf}.csv", index=False)
    print(f"\n  저장: ml/saved_models/btc_combos_{a.tf}.csv")


if __name__ == "__main__":
    main()
