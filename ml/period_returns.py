"""
ml/period_returns.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
월 수익·일 수익은 얼마인가, 해마다 얼마나 다른가

"연 46%"를 12로 나눠 "월 3.8%"라고 하면 안 된다. 이 규칙은
수익이 고르게 나지 않는다 — 거래가 아예 없는 날이 대부분이고,
신호가 몰리는 날에 한꺼번에 난다. 그래서 평균이 아니라 분포로
봐야 한다.

여기서는 일별 평가액(mark-to-market) 곡선을 직접 만들어
  · 하루 수익률 분포 (거래 없는 날이 몇 %인가)
  · 월 수익률 분포
  · 연도별 성적
을 낸다.

일별 평가액은 보유 포지션을 그날 가격으로 다시 매긴 값이다.
청산된 것만 세면 실제로 겪는 출렁임이 안 보인다.
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
from ml.backtest_current_bot import (build_all, Pos, pnl_pct,
                                     ROUND_TRIP, FUNDING_PER_8H, BAR_HOURS)

TE = pd.Timestamp("2024-01-01")


def equity_curve(trades, *, leverage=2.0, per_trade=0.05, max_gross=0.8,
                 cb=0.25, cool_days=30):
    """거래를 처리하면서 하루 한 번 평가액을 기록한다."""
    liq_line = -100.0 / leverage + 0.5
    cash = peak = 1.0
    positions: dict[str, Pos] = {}
    halted_until = None
    curve = {}                       # date -> equity
    t_all = [pd.Timestamp(t["dt"]) for t in trades]
    days = pd.date_range(t_all[0].normalize(), t_all[-1].normalize(), freq="D")
    di = 0

    def mark(upto):
        """upto 이전 날짜들의 평가액을 기록한다."""
        nonlocal di
        while di < len(days) and days[di] <= upto:
            d = days[di]
            eq = cash + sum(p.unreal(d.to_datetime64()) for p in positions.values())
            curve[d] = eq
            di += 1

    for t in trades:
        now = pd.Timestamp(t["dt"])
        mark(now)
        for s in [s for s, p in positions.items() if p.exit_dt <= t["dt"]]:
            cash += positions.pop(s).realized
        eq = cash + sum(p.unreal(t["dt"]) for p in positions.values())
        if eq <= 1e-9:
            break
        peak = max(peak, eq)
        if halted_until is not None and now < halted_until:
            continue
        halted_until = None
        if 1 - eq / peak >= cb:
            halted_until = now + pd.Timedelta(days=cool_days)
            peak = eq
            continue
        if t["sym"] in positions:
            continue
        margin = per_trade * eq
        notional = margin * leverage
        if sum(p.reserved for p in positions.values()) + notional > max_gross * leverage * eq:
            continue
        px_ret, was_liq = pnl_pct(t["entry_avg"], t["exit_px"], leverage,
                                  liq_line, t["mae"])
        held_h = (t["exit_bar"] - t["entry_bar"]) * BAR_HOURS
        fee = ROUND_TRIP + FUNDING_PER_8H * (held_h / 8.0)
        realized = max(margin * leverage * (px_ret - fee) / 100, -margin)
        positions[t["sym"]] = Pos(t, margin, leverage, liq_line, fee, realized)
    mark(days[-1])
    for p in positions.values():
        cash += p.realized
    s = pd.Series(curve).sort_index()
    return s[s > 0]


def main():
    argparse.ArgumentParser().parse_args()
    trades, have, _ = build_all()
    eq = equity_curve(trades)
    r = eq.pct_change().dropna()

    print("=" * 84)
    print("  일·월·연 수익 분포 — 배율 2배 · 거래당 5% · 총노출 80% · 복리")
    print(f"  {eq.index[0].date()} ~ {eq.index[-1].date()} ({len(eq):,}일)")
    print("=" * 84)

    print(f"\n  ── 하루 수익률")
    flat = (r.abs() < 0.0005)
    print(f"     아무 일도 없는 날 (±0.05% 이내)  {flat.mean()*100:.0f}%")
    print(f"     오른 날 {(r>0).mean()*100:.0f}%  ·  내린 날 {(r<0).mean()*100:.0f}%")
    print(f"\n     {'':>10s}{'수익률':>10s}")
    print("     " + "-" * 22)
    for lab, q in [("최악", 0.0), ("하위 1%", .01), ("하위 5%", .05),
                   ("중앙값", .5), ("상위 5%", .95), ("상위 1%", .99), ("최고", 1.0)]:
        print(f"     {lab:>10s}{r.quantile(q)*100:>9.2f}%")
    print(f"     평균 {r.mean()*100:+.3f}%  ·  표준편차 {r.std()*100:.2f}%")

    m = eq.resample("ME").last().pct_change().dropna()
    print(f"\n  ── 월 수익률  (총 {len(m)}개월)")
    print(f"     플러스인 달 {(m>0).mean()*100:.0f}%  ·  마이너스인 달 {(m<0).mean()*100:.0f}%")
    print(f"\n     {'':>10s}{'수익률':>10s}")
    print("     " + "-" * 22)
    for lab, q in [("최악", 0.0), ("하위 10%", .10), ("하위 25%", .25),
                   ("중앙값", .5), ("상위 25%", .75), ("상위 10%", .90), ("최고", 1.0)]:
        print(f"     {lab:>10s}{m.quantile(q)*100:>9.1f}%")
    print(f"     평균 {m.mean()*100:+.1f}%")
    print(f"\n     ※ 중앙값 {m.median()*100:.1f}%를 12번 곱하면 "
          f"{((1+m.median())**12-1)*100:.0f}%다. 평균으로 계산한 것과 다른 이유는")
    print(f"       수익이 큰 달 몇 개에 몰려 있기 때문이다.")
    worst = m.nsmallest(3)
    best = m.nlargest(3)
    print(f"\n     최악의 달  " + " · ".join(f"{i.strftime('%Y-%m')} {v*100:.0f}%"
                                          for i, v in worst.items()))
    print(f"     최고의 달  " + " · ".join(f"{i.strftime('%Y-%m')} {v*100:+.0f}%"
                                          for i, v in best.items()))

    y = eq.resample("YE").last()
    yr = y.pct_change()
    yr.iloc[0] = y.iloc[0] / eq.iloc[0] - 1
    print(f"\n  ── 연도별  (해마다 이렇게 다르다)")
    print(f"     {'연도':>6s}{'수익률':>10s}{'최대낙폭':>10s}{'거래':>7s}   구간")
    print("     " + "-" * 52)
    for dt, v in yr.items():
        seg = eq[eq.index.year == dt.year]
        dd = (1 - (seg / seg.cummax()).min()) * 100
        n = sum(1 for t in trades if pd.Timestamp(t["dt"]).year == dt.year)
        tag = "홀드아웃" if dt.year >= 2024 else "학습"
        print(f"     {dt.year:>6d}{v*100:>9.0f}%{dd:>9.0f}%{n:>7d}   {tag}")
    print(f"\n     플러스인 해 {(yr>0).sum()}/{len(yr)}  ·  "
          f"중앙값 {yr.median()*100:.0f}%  ·  최악 {yr.min()*100:.0f}%")


if __name__ == "__main__":
    main()
