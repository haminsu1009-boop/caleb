"""
ml/coin_selection.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
42종이 꼭 필요한가 — 좋은 코인만 골라내면 더 나은가

"성적 좋은 코인만 골라 쓰자"는 백테스트에서 언제나 옳아 보인다.
과거 성적으로 고르면 과거 성적이 좋아지는 건 동어반복이기 때문이다.
질문은 하나다: **학습구간 성적으로 고른 코인이 홀드아웃에서도
좋은가.** 코인의 '성격'이 실재한다면 그래야 하고, 성적 차이가
운이었다면 그러지 않는다.

같이 재는 것 — 종목을 줄이면 신호도 줄어든다. 자본이 한정된 계좌
에서는 그게 오히려 이득일 수 있다(좋은 자리에 더 크게 싣는다).
그래서 '거래당 수익'뿐 아니라 '분산 감소'도 같이 본다.

사용법:
    python ml/coin_selection.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
warnings.filterwarnings("ignore")
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from bot.oversold import strategy as S
from ml.backtest_current_bot import load
from ml.per_coin_rules import sim, score, split, GLOBAL


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-train", type=int, default=8)
    a = ap.parse_args()

    print("=" * 96)
    print("  종목 선별 — 학습구간 성적으로 고르고 홀드아웃으로 채점 (규칙은 전역 고정)")
    print("=" * 96)

    per = {}
    for sym in S.SYMBOLS:
        g = load(sym)
        if g is None or len(g) < 400:
            continue
        o, h, l, c = (g[k].astype(float).values for k in ("open", "high", "low", "close"))
        t = sim(o, h, l, c, g["datetime"].values, *GLOBAL, S.STOP_PCT)
        tr, ho = split(t)
        if len(tr) < a.min_train:
            continue
        per[sym] = (score(tr), score(ho))

    syms = sorted(per, key=lambda s: -per[s][0]["mu"])
    print(f"\n  대상 {len(syms)}종 (학습 {a.min_train}건 이상)")

    # 학습 순위 ↔ 홀드아웃 순위
    x = np.array([per[s][0]["mu"] for s in syms])
    y = np.array([per[s][1]["mu"] for s in syms])
    from scipy.stats import spearmanr
    rho, p = spearmanr(x, y)
    print(f"  학습 거래당 ↔ 홀드아웃 거래당  피어슨 {np.corrcoef(x, y)[0,1]:+.3f} · "
          f"스피어만 {rho:+.3f} (p={p:.3f})")
    print("  → 0 근처면 '좋은 코인'은 학습구간의 운이었다는 뜻이다.")

    print(f"\n  {'상위 N종':>9s}{'홀드아웃 거래':>14s}{'승률':>8s}{'거래당':>10s}"
          f"{'전체(42종)대비':>15s}")
    print("  " + "-" * 60)
    all_ho = [t for s in syms for t in [per[s][1]]]
    n_all = sum(v["n"] for v in all_ho)
    mu_all = sum(v["mu"] * v["n"] for v in all_ho) / n_all
    wr_all = sum(v["wr"] * v["n"] for v in all_ho) / n_all
    for N in [5, 8, 10, 15, 20, 25, 30, len(syms)]:
        if N > len(syms):
            continue
        sel = syms[:N]
        n = sum(per[s][1]["n"] for s in sel)
        if n == 0:
            continue
        mu = sum(per[s][1]["mu"] * per[s][1]["n"] for s in sel) / n
        wr = sum(per[s][1]["wr"] * per[s][1]["n"] for s in sel) / n
        tag = "  ← 전체" if N == len(syms) else ""
        print(f"  {N:>9}{n:>14,}{wr:>7.1f}%{mu:>+9.2f}%{mu - mu_all:>+14.2f}%p{tag}")

    print(f"\n  무작위 N종과 비교 (학습 성적 무시, 1000회 평균)")
    rng = np.random.default_rng(0)
    print(f"  {'N':>9s}{'선별':>10s}{'무작위 평균':>13s}{'무작위 상위5%':>14s}{'판정':>10s}")
    print("  " + "-" * 60)
    for N in [5, 10, 15, 20, 30]:
        if N > len(syms):
            continue
        sel = syms[:N]
        n = sum(per[s][1]["n"] for s in sel)
        mu = sum(per[s][1]["mu"] * per[s][1]["n"] for s in sel) / max(n, 1)
        sims = []
        for _ in range(1000):
            pick = rng.choice(syms, N, replace=False)
            nn = sum(per[s][1]["n"] for s in pick)
            if nn == 0:
                continue
            sims.append(sum(per[s][1]["mu"] * per[s][1]["n"] for s in pick) / nn)
        sims = np.array(sims)
        # pct = 무작위 추출 중 선별보다 나쁜 비율. 95 이상이어야
        # "고른 보람이 있다"가 된다.
        pct = (sims < mu).mean() * 100
        verdict = "의미있음" if pct >= 95 else ("애매" if pct >= 80 else "무의미")
        print(f"  {N:>9}{mu:>+9.2f}%{sims.mean():>+12.2f}%"
              f"{np.percentile(sims, 95):>+13.2f}%{verdict:>10s}"
              f"  (무작위 {len(sims)}회 중 {pct:.0f}%만 이 선별보다 나쁨)")

    print(f"\n  종목별 (학습 거래당 순)")
    print(f"  {'심볼':12s}{'학습n':>6s}{'학습승률':>9s}{'학습거래당':>11s}"
          f"{'홀드n':>6s}{'홀드승률':>9s}{'홀드거래당':>11s}")
    for s in syms:
        tr, ho = per[s]
        print(f"  {s:12s}{tr['n']:>6}{tr['wr']:>8.1f}%{tr['mu']:>+10.2f}%"
              f"{ho['n']:>6}{ho['wr']:>8.1f}%{ho['mu']:>+10.2f}%")
    print("=" * 96)


if __name__ == "__main__":
    main()
