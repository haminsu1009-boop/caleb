"""
ml/martingale_grid.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
물타기 그리드 봇 — 승률 99.4%가 무엇을 뜻하는가

실제로 돌고 있는 봇 설정을 그대로 재현한다.

    레버리지 20x · ISOLATED · 50 분할 · 분할 간격 0.2%
    목표 수익 0.3% · 손절 -100%(= 손절 없음) · 분할당 0.001 BTC

화면에 찍힌 성적은 승률 99.4%(익절 534 / 종료 537), 실현 +$412.9다.
그 승률은 성능이 아니라 설계의 결과다. 0.3%를 먹고 나가는 것을
반복하고, 손절이 없으므로 지는 경우는 청산 한 번뿐이다. 이기는
횟수를 아무리 늘려도 한 번의 청산이 그 전부를 가져간다.

핵심은 청산까지의 거리다. 물을 타면 평단이 내려가지만 **가격보다
느리게** 내려간다 — 평단은 이미 산 비싼 값들의 평균이기 때문이다.
그래서 물을 탈수록 가격이 청산선에 가까워진다.

    n번째 분할까지 채웠을 때
        가격    = P0 × (1 - 0.002n)
        평단    ≈ P0 × (1 - 0.001(n-1))
        차이    ≈ 0.1% × n
    20배 격리 마진의 청산선은 평단 대비 약 -4.5%이므로
        0.1n = 4.5  →  n ≈ 45

즉 사다리 50칸을 다 쓰기 직전에 청산된다. BTC가 9~10% 빠지면 그
포지션은 전액 손실이다. 사다리가 딱 그만큼만 버티도록 짜여 있다.

이 파일은 그 가정을 검증하지 않고 **체결 단위로 그대로 돌린다.**
5분봉 94만 봉(2017~2026)에서 사이클이 몇 번 돌고, 청산이 몇 번
나고, 합산 손익이 얼마인지 센다.

사용법:
    python ml/martingale_grid.py
    python ml/martingale_grid.py --lev 10 --tranches 100 --gap 0.3
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
from ml.daytrade_scalein import load_tf

TAKER = 0.055          # 바이빗 테이커 편도 %. 물타기 봇은 시장가로 긁는다.
MAINT = 0.5            # 유지증거금 %. 격리 20배 청산선 ≈ 평단 -4.5%.


def run(h, l, c, dt, lev=20.0, n_max=50, gap=0.2, tp=0.3, qty=0.001,
        fee=TAKER):
    """체결 단위 시뮬레이션. 한 봉 안에서는 저가를 먼저 본다 —
    같은 봉에서 청산과 익절이 둘 다 가능하면 청산이 먼저다. 어느
    쪽이 먼저였는지 봉 데이터로는 알 수 없고, 유리한 쪽을 고르면
    그게 곧 룩어헤드다."""
    liq_frac = (100.0 / lev - MAINT) / 100.0     # 평단 대비 청산 하락폭
    px, n = [], 0
    first = None
    cycles, liqs = [], []
    peak_n = 0
    start_i = 0
    for i in range(len(c)):
        if n == 0:                                # 새 사이클 시작
            first = c[i]; px = [c[i]]; n = 1; start_i = i
            continue
        avg = float(np.mean(px))
        # ① 청산 — 저가 기준. 스치면 끝이다.
        if l[i] <= avg * (1 - liq_frac):
            notional = sum(px) * qty
            margin = notional / lev
            liqs.append(dict(dt=dt[i], n=n, loss=-margin,
                             drop=(c[i] / first - 1) * 100,
                             bars=i - start_i))
            peak_n = max(peak_n, n)
            n = 0; px = []
            continue
        # ② 익절 — 고가가 목표에 닿으면
        if h[i] >= avg * (1 + tp / 100):
            notional = sum(px) * qty
            gross = notional * tp / 100
            cost = notional * fee / 100 * 2       # 진입·청산 왕복
            cycles.append(dict(dt=dt[i], n=n, pnl=gross - cost,
                               bars=i - start_i))
            peak_n = max(peak_n, n)
            n = 0; px = []
            continue
        # ③ 물타기 — 마지막 매수가 대비 gap% 더 빠지면
        if n < n_max and l[i] <= px[-1] * (1 - gap / 100):
            px.append(px[-1] * (1 - gap / 100)); n += 1
    return cycles, liqs, peak_n


def report(sym, cycles, liqs, peak_n, lev, n_max, gap, tp, qty, years):
    win = len(cycles); lose = len(liqs)
    tot = win + lose
    gain = sum(x["pnl"] for x in cycles)
    loss = sum(x["loss"] for x in liqs)
    full_margin = qty * n_max * np.mean([1]) * 0 + 0   # 아래에서 실제값으로
    print(f"\n  {sym} · {lev:.0f}배 · {n_max}분할 · 간격 {gap}% · 목표 {tp}%")
    print("  " + "-" * 76)
    print(f"  사이클 {tot:,}회 — 익절 {win:,} · 청산 {lose:,}"
          f"  (승률 {win/max(tot,1)*100:.2f}%)")
    print(f"  익절 합계 {gain:>+12,.2f} $")
    print(f"  청산 합계 {loss:>+12,.2f} $")
    print(f"  합산      {gain+loss:>+12,.2f} $   ({years:.1f}년)")
    if cycles:
        print(f"  익절 1회 평균 {np.mean([x['pnl'] for x in cycles]):>+8.3f} $ · "
              f"평균 {np.mean([x['n'] for x in cycles]):.1f}분할 · "
              f"평균 {np.mean([x['bars'] for x in cycles])*5/60:.1f}시간")
    if liqs:
        L = [x["loss"] for x in liqs]
        print(f"  청산 1회 평균 {np.mean(L):>+8.2f} $ · 최대 {min(L):>+8.2f} $")
        print(f"  청산까지 걸린 하락폭 평균 {np.mean([x['drop'] for x in liqs]):.1f}%")
        print(f"  청산 주기 — 평균 {years*12/len(liqs):.1f}개월에 한 번")
        print(f"  익절 {win/max(lose,1):.0f}회당 청산 1회")
    print(f"  사다리 최대 사용 {peak_n}/{n_max}칸")
    return gain + loss, win, lose


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", default="BTCUSDT")
    ap.add_argument("--tf", default="5m")
    ap.add_argument("--lev", type=float, default=20.0)
    ap.add_argument("--tranches", type=int, default=50)
    ap.add_argument("--gap", type=float, default=0.2)
    ap.add_argument("--tp", type=float, default=0.3)
    ap.add_argument("--qty", type=float, default=0.001)
    ap.add_argument("--sweep", action="store_true", help="설정을 바꿔가며 비교")
    a = ap.parse_args()

    g = load_tf(a.sym, a.tf)
    if g is None:
        raise SystemExit(f"{a.sym} {a.tf} 데이터 없음")
    h = g["high"].astype(float).values
    l = g["low"].astype(float).values
    c = g["close"].astype(float).values
    dt = g["dt"].values
    years = (pd.Timestamp(dt[-1]) - pd.Timestamp(dt[0])).days / 365.25

    print("=" * 84)
    print(f"  물타기 그리드 — 체결 단위 재현 · {a.sym} {a.tf} {len(c):,}봉 · {years:.1f}년")
    print(f"  수수료 테이커 편도 {TAKER}% · 청산선 = 평단 대비 "
          f"-{(100/a.lev - MAINT):.2f}%")
    print("=" * 84)

    cyc, liq, pk = run(h, l, c, dt, a.lev, a.tranches, a.gap, a.tp, a.qty)
    report(a.sym, cyc, liq, pk, a.lev, a.tranches, a.gap, a.tp, a.qty, years)

    if not a.sweep:
        print("\n" + "=" * 84)
        return

    print("\n" + "=" * 84)
    print("  설정을 바꾸면 — 청산을 없앨 수 있는가")
    print("=" * 84)
    print(f"\n  {'배율':>5s}{'분할':>6s}{'간격':>7s}{'청산선':>8s}{'사다리커버':>11s}"
          f"{'익절':>9s}{'청산':>7s}{'합산($)':>12s}")
    print("  " + "-" * 68)
    for lev, nt, gp in [(20, 50, 0.2), (20, 100, 0.2), (20, 50, 0.1),
                        (10, 50, 0.2), (10, 100, 0.2), (5, 50, 0.4),
                        (5, 100, 0.4), (3, 100, 0.5), (2, 100, 0.5),
                        (1, 100, 0.5)]:
        cy, lq, _ = run(h, l, c, dt, lev, nt, gp, a.tp, a.qty)
        s = sum(x["pnl"] for x in cy) + sum(x["loss"] for x in lq)
        print(f"  {lev:>4.0f}배{nt:>6}{gp:>6.1f}%{100/lev-MAINT:>7.2f}%"
              f"{nt*gp:>10.1f}%{len(cy):>9,}{len(lq):>7,}{s:>+12,.0f}")
    print("=" * 84)


if __name__ == "__main__":
    main()
