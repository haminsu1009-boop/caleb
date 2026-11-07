"""
ml/global_retune.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
코인별 맞춤의 대조군 — 전 코인 공통 규칙 하나만 다시 고른다

ml/per_coin_rules.py는 코인마다 다른 규칙을 뽑는다. 그게 지금 봇보다
좋아 보여도, 좋아진 이유가 "코인마다 달라서"인지 "지금 임계값이
그냥 덜 좋아서"인지는 그것만으로 구별되지 않는다.

그래서 같은 후보 집합에서 **전 종목 공통** 규칙 하나를 학습구간
기준으로 고르고, 같은 홀드아웃으로 채점한다. 셋을 나란히 둔다.

    지금 봇 (전역, 손으로 정한 값)
    전역 재튜닝 (전역, 학습구간에서 고름)   ← 이 파일
    코인별 맞춤 (코인마다 다름)             ← per_coin_rules.py

코인별이 전역 재튜닝을 못 이기면, 코인별로 나눌 이유가 없다.
자유도만 늘리고 얻는 게 없다는 뜻이다.

사용법:
    python ml/global_retune.py
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
from ml.per_coin_rules import sim, score, split, grid, GLOBAL


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args()

    G = grid(a.quick)
    print("=" * 104)
    print("  전역 재튜닝 — 전 종목 공통 규칙 하나를 학습구간에서 고른다")
    print(f"  후보 {len(G)}개 · 종목 {len(S.SYMBOLS)}종 · 학습 ~2023 · 홀드아웃 2024~")
    print("=" * 104)

    data = {}
    for sym in S.SYMBOLS:
        g = load(sym)
        if g is None or len(g) < 400:
            continue
        data[sym] = tuple(g[k].astype(float).values
                          for k in ("open", "high", "low", "close")) + \
                    (g["datetime"].values,)

    res = []
    for cfg in G:
        tr_all, ho_all = [], []
        for sym, (o, h, l, c, dt) in data.items():
            t = sim(o, h, l, c, dt, *cfg, S.STOP_PCT)
            tr, ho = split(t)
            tr_all += tr; ho_all += ho
        res.append((cfg, score(tr_all), score(ho_all)))

    # 지금 봇
    gtr, gho = [], []
    for sym, (o, h, l, c, dt) in data.items():
        t = sim(o, h, l, c, dt, *GLOBAL, S.STOP_PCT)
        x, y = split(t); gtr += x; gho += y
    g_tr, g_ho = score(gtr), score(gho)

    # 학습구간 거래당 순수익으로 고른다
    res.sort(key=lambda r: -r[1]["mu"])
    pick = res[0]

    def line(lab, cfg, tr, ho):
        ma_p, th, hold, fr, ou = cfg
        fs = "+".join(f"{x*100:.0f}" for x in fr)
        os_ = " ".join(f"{f*100:.0f}%@{k}σ" for f, k in ou)
        print(f"  {lab:<16s}{ma_p:>4}{th:>8.2f}%{hold:>5}{fs:>9s}{os_:>22s}"
              f"{tr['n']:>7,}{tr['wr']:>6.1f}%{tr['mu']:>+8.2f}%"
              f"{ho['n']:>7,}{ho['wr']:>6.1f}%{ho['mu']:>+8.2f}%")

    print(f"\n  {'':16s}{'MA':>4s}{'진입':>9s}{'보유':>5s}{'분할매수':>9s}{'분할매도':>22s}"
          f"{'학습n':>7s}{'승률':>6s}{'거래당':>8s}{'홀드n':>7s}{'승률':>6s}{'거래당':>8s}")
    print("  " + "-" * 102)
    line("지금 봇", GLOBAL, g_tr, g_ho)
    line("전역 재튜닝", pick[0], pick[1], pick[2])
    print(f"\n  홀드아웃 차이: 거래당 {pick[2]['mu'] - g_ho['mu']:+.2f}%p · "
          f"승률 {pick[2]['wr'] - g_ho['wr']:+.1f}%p")
    d_tr = pick[1]["mu"] - g_tr["mu"]
    d_ho = pick[2]["mu"] - g_ho["mu"]
    if abs(d_tr) > 1e-9:
        print(f"  학습 앞선 폭 {d_tr:+.2f}%p → 홀드아웃 {d_ho:+.2f}%p (유지율 {d_ho/d_tr*100:.0f}%)")

    print(f"\n  학습구간 상위 {a.top}개 — 홀드아웃이 따라오는지 본다")
    print(f"  {'#':>3s}{'MA':>4s}{'진입':>9s}{'보유':>5s}{'분할매수':>9s}{'분할매도':>22s}"
          f"{'학습거래당':>10s}{'홀드거래당':>10s}{'홀드승률':>9s}")
    for i, (cfg, tr, ho) in enumerate(res[:a.top], 1):
        ma_p, th, hold, fr, ou = cfg
        fs = "+".join(f"{x*100:.0f}" for x in fr)
        os_ = " ".join(f"{f*100:.0f}%@{k}σ" for f, k in ou)
        print(f"  {i:>3}{ma_p:>4}{th:>8.2f}%{hold:>5}{fs:>9s}{os_:>22s}"
              f"{tr['mu']:>+9.2f}%{ho['mu']:>+9.2f}%{ho['wr']:>8.1f}%")

    # 상관: 학습 점수가 홀드아웃 점수를 예측하는가
    x = np.array([r[1]["mu"] for r in res])
    y = np.array([r[2]["mu"] for r in res])
    print(f"\n  후보 {len(res)}개 전체에서 학습 점수 ↔ 홀드아웃 점수 상관 = {np.corrcoef(x, y)[0,1]:+.3f}")
    print("  (0에 가까우면 학습 점수로 고르는 행위 자체가 의미 없다는 뜻이다)")
    print("=" * 104)


if __name__ == "__main__":
    main()
