"""
ml/deep_ladder.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
분할을 20~30단으로 깊게 깔면 배율을 올릴 수 있나

직관은 이렇다. 분할을 깊게 깔면 물릴수록 평단이 내려간다. 평단이
내려가면 **평단 대비** 최대역행(MAE)이 작아지고, 강제청산선까지의
거리가 멀어진다. 그러면 배율을 올릴 여유가 생긴다.

이 직관은 맞다. 문제는 대가다.

    · 20단이면 신호 한 번에 자본의 1/20만 나간다. 끝까지 물리는
      일은 드물기 때문에 **대부분의 거래가 소액으로 끝난다**.
      승률은 오르지만 이길 때 버는 돈이 작아진다.
    · 사다리를 다 채우려면 가격이 그만큼 내려와야 한다. 간격을
      5%로 두면 20단은 -95%다 — 영원히 안 채워진다. 간격을 좁히면
      (2%) 사다리 전체가 -38%에 몰려 평단이 별로 안 내려간다.

그래서 "평단이 얼마나 내려가나"와 "돈이 얼마나 나가나"를 같이
재야 한다. 배율 여유는 공짜가 아니다.

여기서 재는 것
    1. 단수별 MAE 분포 → 청산 0건을 만족하는 최대 배율
    2. 그 배율에서의 최종 배수 · 승률 · 낙폭
    3. 실제 투입 비율(deployed) — 사다리가 얼마나 채워지는가

사용법:
    python ml/deep_ladder.py
    python ml/deep_ladder.py --symbols BTCUSDT      # 특정 종목만
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
from ml.backtest_current_bot import load, simulate
from ml.per_coin_rules import sim

TE = pd.Timestamp("2024-01-01")

# (단수, 사다리 전체가 걸치는 폭 %)
LADDERS = [
    (2,  5.0),    # 지금 봇 — 1차 30%, -5%에서 2차 70%
    (3,  20.0),
    (5,  20.0),
    (5,  40.0),
    (10, 20.0),
    (10, 40.0),
    (20, 20.0),
    (20, 40.0),
    (30, 30.0),
    (30, 45.0),
]
LEVS = [2.0, 3.0, 5.0, 10.0, 20.0]


def fracs_for(n):
    """지금 봇은 30/70이다 — 뒤로 갈수록 크게 싣는다. 그 성격을 지킨다.
    가중치를 1,2,3,...,n 으로 주고 합이 1이 되게 정규화한다."""
    if n == 2:
        return [S.SCALE_IN_FIRST_FRAC, 1 - S.SCALE_IN_FIRST_FRAC]
    w = np.arange(1, n + 1, dtype=float)
    return list(w / w.sum())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="", help="쉼표 구분. 비우면 42종 전부")
    ap.add_argument("--per-trade", type=float, default=0.015)
    ap.add_argument("--max-gross", type=float, default=0.4)
    a = ap.parse_args()

    syms = ([x.strip().upper() for x in a.symbols.split(",") if x.strip()]
            or list(S.SYMBOLS))
    data = {}
    for sym in syms:
        g = load(sym)
        if g is None or len(g) < 400:
            continue
        data[sym] = tuple(g[k].astype(float).values
                          for k in ("open", "high", "low", "close")) + (g["datetime"].values,)

    print("=" * 108)
    print("  깊은 분할매수 — 평단을 낮춰 배율 여유를 만들 수 있나")
    print(f"  종목 {len(data)}종 · 진입 {S.ENTRY_THRESH}% · {S.HOLD_BARS}봉 · "
          f"볼린저 {S.BB_K}σ · 진입당 {a.per_trade*100:.1f}% · 총노출 {a.max_gross*100:.0f}%")
    print("=" * 108)
    hdr = "".join(f"{str(int(v))+'배':>15s}" for v in LEVS)
    print(f"\n  {'단수':>4s}{'간격':>7s}{'폭':>7s}{'평균투입':>9s}{'맞춘진입':>8s}"
          f"{'MAE중앙':>9s}{'MAE하위5%':>9s}{hdr}")
    print("  " + "-" * (44 + 15 * len(LEVS)))

    dep0 = None
    for n, span in LADDERS:
        step = span / max(n - 1, 1)
        fr = fracs_for(n)
        tr = []
        for sym, (o, h, l, c, dt) in data.items():
            tr += sim(o, h, l, c, dt, S.MA_PERIOD, S.ENTRY_THRESH, S.HOLD_BARS,
                      fr, [(1.0, S.BB_K)], S.STOP_PCT, sym=sym, step=step)
        if not tr:
            continue
        tr.sort(key=lambda t: t["dt"])
        dep = np.array([t["deployed"] for t in tr])
        mae = np.array([t["mae"] for t in tr])
        if dep0 is None:
            dep0 = dep.mean()      # 기준은 지금 봇(2단)의 평균 투입

        # 배율별 청산률. "청산 0건"은 어떤 사다리로도 불가능하다 —
        # MAE 최악이 -100%인 거래가 있기 때문이다(2020-03 COVID,
        # 보유 중 코인이 0이 됐다). 청산은 중앙값이 아니라 최악값이
        # 결정하므로 사다리로는 그 꼬리를 없앨 수 없다.
        #
        # 투입 자본을 맞춘다. 20단이면 평균 투입이 0.11이라 같은
        # per_trade로 비교하면 "돈을 덜 걸어서 안전한 것"을 "사다리
        # 덕에 안전한 것"으로 착각하게 된다.
        pt = a.per_trade * (dep0 / dep.mean())
        cells = []
        for lev in LEVS:
            r = simulate(tr, leverage=lev, per_trade=pt,
                         max_gross=a.max_gross * (pt / a.per_trade),
                         cb=0.20, cool_days=30, min_equity=0.0, compound=True)
            liq_line = -100.0 / lev + 0.5
            cells.append((lev, (mae <= liq_line).mean() * 100, r))
        row = "".join(f"{c[1]:>6.1f}%{c[2]['final']:>8.2f}배" for c in cells)
        print(f"  {n:>4}{step:>6.1f}%{span:>6.0f}%{dep.mean():>8.2f}{pt*100:>7.1f}%"
              f"{np.median(mae):>8.1f}%{np.percentile(mae, 5):>8.1f}%{row}")

    print("\n  평균투입 = 신호 한 번에 실제로 나간 자본 비율 (1.00이면 계획한 전액)")
    print("  맞춘진입 = 평균투입이 같아지도록 키운 진입 비율 (총노출도 같은 배로 키움)")
    print("  MAE하위5% = 나쁜 쪽 5% 지점. 청산선(2배 -49.5% · 3배 -32.8% ·")
    print("              5배 -19.5% · 10배 -9.5% · 20배 -4.5%)과 비교한다.")
    print("  각 배율 칸 = 청산당한 거래 비율 / 그 배율에서의 최종 배수")
    print("=" * 108)


if __name__ == "__main__":
    main()
