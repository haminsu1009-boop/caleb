"""
ml/vol_scaled_entry.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
덜 흔들리는 코인은 덜 빠져도 산다 — 변동성에 맞춘 진입 기준

"신호가 잘 안 오는 코인은 전략을 바꿔야 하지 않나"에서 나왔다.
지금 규칙은 42종 전부 "20기간선 대비 -12.26%"다. BTC는 그만큼 빠지는
일이 드물어 1년에 3번 뜨고, 변동성 큰 알트는 7~8번 뜬다.

코인마다 기준을 따로 고르는 것은 이미 세 번 졌다(ml/per_coin_rules.py
등). 코인당 학습 거래 25건에 후보 1,080개면 운을 외운다. 여기서는
다르게 한다 — 기준을 **각 코인의 평소 흔들림에 비례**시키고, 비례
상수 z 하나만 전 종목 공통으로 정한다.

    평소 흔들림 σ = 그 코인의 "20기간선 대비 괴리"의 표준편차
                   (직전 500봉, 과거만 본다)
    진입 기준     = -z × σ

z는 학습구간(~2023)에서 고르고 홀드아웃(2024~)으로 채점한다. 두 변형을
같이 본다.

    완전 비례    모든 코인이 -zσ
    완화만      -max(zσ, ?)가 아니라 min(12.26, zσ) — 덜 흔들리는 코인만
                기준을 얕게, 많이 흔들리는 코인은 지금 그대로

━━ 결과: 지금 규칙이 이긴다 ━━

    진입 기준            신호   BTC  승률   2배 8년  낙폭   학습    2024~
    지금(-12.26% 고정)  1,815   24  83.0%  3.16배  36%  1.59배  1.99배
    완전 비례 z=2.25    2,024   66  78.4%  1.56배  40%  0.77배  2.01배
    완화만   z=2.25    2,499   71  79.4%  2.37배  39%  1.15배  2.06배
    (z를 더 낮추면 신호는 4,800건까지 늘고 8년 결과는 1배 아래로 떨어진다)

신호는 늘어난다(BTC 24건 → 66~143건). 그런데 승률이 83%에서 75~79%로
떨어지고 낙폭은 커진다. 학습구간에서 어떤 z도 지금 규칙을 못 이기고,
2024~는 비슷하다(2.06 대 1.99, 4배로는 3.07 대 3.12).

-12%라는 "절대적인 깊이"가 엣지의 원천으로 보인다. 그만큼 빠지면
코인 종류와 상관없이 강제청산 연쇄·투매가 나온 뒤다. BTC가 평소
흔들림의 두 배인 -6%쯤 빠지는 건 그냥 흔한 조정이고 반등을 보장하지
않는다. 신호가 드문 코인은 드문 게 맞다.

사용법:
    python ml/vol_scaled_entry.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations
import os, sys, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from bot.oversold import strategy as S
from ml.backtest_current_bot import load, simulate
from ml.per_coin_rules import sim, GLOBAL

TE = pd.Timestamp("2024-01-01")


def main():
    data = {}
    for sym in S.SYMBOLS:
        g = load(sym)
        if g is None or len(g) < 800:
            continue
        o, h, l, c = (g[k].astype(float).values for k in ("open", "high", "low", "close"))
        vs = (c / pd.Series(c).rolling(20).mean().values - 1) * 100
        sd = pd.Series(vs).rolling(500, min_periods=200).std().shift(1).values
        data[sym] = (o, h, l, c, g["datetime"].values, vs, sd)

    sig_lvl = {s: np.nanmedian(d[6]) for s, d in data.items()}
    med = np.nanmedian(list(sig_lvl.values()))

    def build(mode, z):
        T = []
        for sym, (o, h, l, c, dt, vs, sd) in data.items():
            if mode == "fixed":
                thr = np.full(len(c), S.ENTRY_THRESH)
            elif mode == "full":
                thr = -z * sd
            else:  # 완화만
                thr = np.maximum(-z * sd, S.ENTRY_THRESH)
            ok = ~np.isnan(thr)
            idx = np.where(ok & (vs <= thr))[0]
            T += sim(o, h, l, c, dt, *GLOBAL, S.STOP_PCT, sym=sym, entries=idx)
        T.sort(key=lambda t: t["dt"])
        return T

    def port(T, lev):
        kw = dict(leverage=lev, per_trade=0.015, max_gross=0.6, cb=0.20,
                  cool_days=30, min_equity=0.0, compound=True)
        a = simulate([t for t in T if t["dt"] < TE], **kw)
        b = simulate([t for t in T if t["dt"] >= TE], **kw)
        f = simulate(T, **kw)
        return f, a, b

    print("=" * 108)
    print("  변동성에 맞춘 진입 기준 · 롱 모듈 · 42종 4시간봉")
    print(f"  평소 흔들림(σ) 중앙값: 전체 {med:.1f}% · 가장 작은 BTC {sig_lvl.get('BTCUSDT', np.nan):.1f}%"
          f" · 가장 큰 {max(sig_lvl, key=sig_lvl.get)} {max(sig_lvl.values()):.1f}%")
    print("=" * 108)
    print(f"\n  {'진입 기준':<22s}{'신호':>7s}{'BTC':>5s}{'ETH':>5s}{'승률':>7s}"
          f"{'2배 8년':>9s}{'낙폭':>6s}{'2배 학습':>9s}{'2배 2024~':>10s}{'4배 2024~':>10s}")
    print("  " + "-" * 102)
    rows = []
    cases = [("fixed", 0, "지금 (-12.26% 고정)")]
    cases += [("full", z, f"완전 비례 z={z}") for z in [1.5, 1.75, 2.0, 2.25, 2.5]]
    cases += [("loose", z, f"완화만 z={z}") for z in [1.5, 1.75, 2.0, 2.25]]
    for mode, z, lab in cases:
        T = build(mode, z)
        f, a, b = port(T, 2.0)
        _, _, b4 = port(T, 4.0)
        nb = sum(1 for t in T if t["sym"] == "BTCUSDT")
        ne = sum(1 for t in T if t["sym"] == "ETHUSDT")
        rows.append((lab, a["final"], b["final"]))
        print(f"  {lab:<22s}{len(T):>7,}{nb:>5}{ne:>5}{f['wr']:>6.1f}%{f['final']:>8.2f}배"
              f"{f['mdd_low']*100:>5.0f}%{a['final']:>8.2f}배{b['final']:>9.2f}배{b4['final']:>9.2f}배")
    best = max(rows[1:], key=lambda r: r[1])
    print(f"\n  학습구간 1위: {best[0]} → 학습 {best[1]:.2f}배 · 2024~ {best[2]:.2f}배"
          f"  (지금 규칙: 학습 {rows[0][1]:.2f}배 · 2024~ {rows[0][2]:.2f}배)")
    print("=" * 108)


if __name__ == "__main__":
    main()
