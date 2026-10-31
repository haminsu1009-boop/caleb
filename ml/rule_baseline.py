"""
ml/rule_baseline.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
재튜닝 규칙의 엣지가 국면 이상의 것인가

ml/global_retune.py가 고른 규칙은 홀드아웃 승률 96.7%(n=91)를 냈다.
그 숫자 자체가 경보다. 2024~2025는 대체로 상승장이었고, 상승장에
진입하면 무엇을 사도 이긴다. 거래 수가 91건뿐이라 더 그렇다.

이 세션에서 신고가 돌파·ROC 모멘텀·급락반등 세 전략이 전부
"나이브 검정 통과 → 국면 기준선에 패배"로 탈락했다. 같은 검정을
여기에도 건다.

기준선: **같은 코인, 같은 시기(±30일), 같은 청산 규칙, 진입 시점만
무작위.** 전역 평균과 비교하면 "폭락 뒤에 산다"는 사실만으로
이기는데, 그건 규칙의 공이 아니다.

규칙이 기준선을 못 이기면, 그 규칙이 보는 것은 국면뿐이다.

사용법:
    python ml/rule_baseline.py
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
from bot.oversold import strategy as S
from ml.backtest_current_bot import load, ROUND_TRIP, FUNDING_PER_8H
from ml.per_coin_rules import sim, score, split, GLOBAL
from ml.rule_shootout import CANDIDATES, load_all

BARS_PER_DAY = 6          # 4시간봉
WINDOW_DAYS = 30


def net(trades):
    return np.array([(t["exit_px"] / t["entry"] - 1) * 100 - ROUND_TRIP
                     - FUNDING_PER_8H * (t["bars_h"] / 8.0) for t in trades])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=200,
                    help="기준선 반복 횟수 (많을수록 p값이 안정된다)")
    a = ap.parse_args()
    rng = np.random.default_rng(0)
    W = WINDOW_DAYS * BARS_PER_DAY

    data = load_all()
    print("=" * 100)
    print("  국면 통제 기준선 — 같은 코인 · 같은 시기(±30일) · 같은 청산 · 진입만 무작위")
    print(f"  반복 {a.reps}회 · 종목 {len(data)}종")
    print("=" * 100)
    print(f"\n  {'규칙':<18s}{'구간':>8s}{'n':>6s}{'실제승률':>9s}{'기준승률':>9s}"
          f"{'실제거래당':>11s}{'기준거래당':>11s}{'초과':>8s}{'p':>7s}{'판정':>10s}")
    print("  " + "-" * 98)

    for lab, cfg in CANDIDATES:
        ma_p, thresh, hold, fracs, outs = cfg
        real_all, sig_map = [], {}
        for sym, (o, h, l, c, dt) in data.items():
            t = sim(o, h, l, c, dt, *cfg, S.STOP_PCT, sym=sym)
            real_all += t
            ma = pd.Series(c).rolling(ma_p).mean().values
            vs = (c / ma - 1) * 100
            sig_map[sym] = np.where(vs <= thresh)[0]

        for seg_lab, keep in [("전체", None), ("홀드아웃", True)]:
            real = (real_all if keep is None
                    else [t for t in real_all if t["dt"] >= pd.Timestamp("2024-01-01")])
            if len(real) < 20:
                continue
            r = net(real)
            # 기준선 — 실제 신호 시점 ±30일 안에서 진입 봉만 흔든다
            b_mu, b_wr = [], []
            for _ in range(a.reps):
                bt = []
                for sym, (o, h, l, c, dt) in data.items():
                    sg = sig_map[sym]
                    if len(sg) == 0:
                        continue
                    n = len(c)
                    jit = sg + rng.integers(-W, W + 1, size=len(sg))
                    jit = np.unique(np.clip(jit, max(ma_p, 20) + 1, n - hold - 3))
                    bt += sim(o, h, l, c, dt, ma_p, thresh, hold, fracs, outs,
                              S.STOP_PCT, sym=sym, entries=jit)
                if keep is not None:
                    bt = [t for t in bt if t["dt"] >= pd.Timestamp("2024-01-01")]
                if not bt:
                    continue
                bn = net(bt)
                b_mu.append(bn.mean()); b_wr.append((bn > 0).mean() * 100)
            if not b_mu:
                continue
            b_mu = np.array(b_mu); b_wr = np.array(b_wr)
            p = float((b_mu >= r.mean()).mean())
            verdict = "통과" if p < 0.05 else ("애매" if p < 0.15 else "탈락")
            print(f"  {lab:<18s}{seg_lab:>8s}{len(r):>6,}{(r>0).mean()*100:>8.1f}%"
                  f"{b_wr.mean():>8.1f}%{r.mean():>+10.2f}%{b_mu.mean():>+10.2f}%"
                  f"{r.mean()-b_mu.mean():>+7.2f}%{p:>7.3f}{verdict:>10s}")
    print("=" * 100)
    print("  p = 무작위 진입이 실제 규칙만큼 좋았던 비율. 0.05 미만이어야 엣지다.")


if __name__ == "__main__":
    main()
