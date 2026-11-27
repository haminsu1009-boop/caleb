"""
ml/backtest_scenarios.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
현재 코드 기준 시나리오 백테스트 — 1년 후 얼마?·월적립하면?·100배까지?

ml/backtest_current_bot.py가 "지금 코드가 전체 기간에 뭘 했는가"를
답했다. 여기서는 같은 신호·같은 실행 로직을 그대로 재사용하면서
"시작 시점이 언제냐에 따라 결과가 얼마나 갈리는가"를 묻는다 — 이
질문들은 이 세션 초반에도 나왔지만, 그때는 분할매수도 없었고 예약
노출 버그도 있었고 차단기가 영구정지였다. 지금 코드로 다시 낸다.

reserved 노출·재개 차단기·mtm 평가는 backtest_current_bot.py의
simulate()/Pos를 그대로 가져다 쓴다 — 여기서 새로 구현하면 두 파일이
갈라질 위험이 있다. DCA(월 적립)만 이 파일에서 새로 얹는다.

사용법:
    python ml/backtest_scenarios.py                # 전부
    python ml/backtest_scenarios.py --only rolling  # 1년 창만
    python ml/backtest_scenarios.py --only dca       # 월적립만
    python ml/backtest_scenarios.py --only 100x      # 100배 도달만
    python ml/backtest_scenarios.py --only stress    # 비용 스트레스만
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import argparse
import os
import sys
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from ml.backtest_current_bot import build_all, simulate, Pos, pnl_pct
from ml.backtest_current_bot import ROUND_TRIP, FUNDING_PER_8H, BAR_HOURS
from bot.oversold import strategy as S

START = 1_000_000          # 100만원
MONTHLY = 300_000          # 월 30만원
LEV = 2.0
PER_TRADE = 0.05
MAX_GROSS = 1.0
CB = 0.25
COOL_DAYS = 30


# ── DCA(월 적립) — simulate()를 확장해 매달 현금을 주입한다 ─────────────
def simulate_dca(trades, leverage, per_trade, max_gross, cb, cool_days,
                 start_cap=1.0, monthly=0.0, months=12):
    liq_line = -100.0 / leverage + 0.5
    cash = start_cap
    deposited = start_cap
    peak = cash
    mdd = 0.0
    peak_low = cash
    mdd_low = 0.0
    positions: dict[str, Pos] = {}
    halted_until = None
    halts = 0
    n_trades = wins = liqs = 0
    next_dep = None
    total_planned = start_cap + monthly * months

    for t in trades:
        now = t["dt"]
        if next_dep is None:
            next_dep = pd.Timestamp(now) + pd.DateOffset(months=1)
        while monthly > 0 and deposited < total_planned - 1e-9 and pd.Timestamp(now) >= next_dep:
            cash += monthly
            deposited += monthly
            next_dep += pd.DateOffset(months=1)

        for s in [s for s, p in positions.items() if p.exit_dt <= now]:
            cash += positions.pop(s).realized

        eq_mtm = cash + sum(p.unreal(now) for p in positions.values())
        eq_low = cash + sum(p.unreal(now, True) for p in positions.values())
        if eq_mtm <= 0:
            return {"final": 0.0, "dep": deposited, "mdd": 1.0, "mdd_low": 1.0,
                    "n": n_trades, "wr": 0.0, "liq": liqs, "halts": halts, "bust": True}
        peak = max(peak, eq_mtm)
        if 1 - eq_mtm / peak > mdd:
            mdd = 1 - eq_mtm / peak
        peak_low = max(peak_low, eq_low)
        if 1 - eq_low / peak_low > mdd_low:
            mdd_low = 1 - eq_low / peak_low

        if halted_until is not None and now < halted_until:
            can_enter = False
        else:
            halted_until = None
            can_enter = True
        if can_enter and peak > 0 and 1 - eq_mtm / peak >= cb:
            halted_until = pd.Timestamp(now) + pd.Timedelta(days=cool_days)
            halts += 1
            peak = eq_mtm
            can_enter = False

        if t["sym"] in positions or not can_enter:
            continue
        # 진입당 비율은 "현재 자본"이 아니라 "이번까지 납입된 원금" 기준으로
        # 잡는다 — 아직 안 넣은 미래 적립분을 미리 베팅하면 안 된다.
        full_notional = per_trade * leverage * deposited
        gross = sum(p.reserved for p in positions.values())
        if gross + full_notional > max_gross * leverage * deposited:
            continue

        px_ret, was_liq = pnl_pct(t["entry_avg"], t["exit_px"], leverage, liq_line)
        held_h = (t["exit_bar"] - t["entry_bar"]) * BAR_HOURS
        fee = ROUND_TRIP + FUNDING_PER_8H * (held_h / 8.0)
        net = px_ret - fee
        margin = per_trade * deposited
        realized = max(margin * leverage * net / 100, -margin)
        n_trades += 1
        wins += net > 0
        liqs += was_liq
        positions[t["sym"]] = Pos(t, margin, leverage, liq_line, fee, realized)

    while monthly > 0 and deposited < total_planned - 1e-9:
        cash += monthly
        deposited += monthly

    for p in positions.values():
        cash += p.realized
    return {"final": cash, "dep": deposited, "mdd": mdd, "mdd_low": mdd_low,
            "n": n_trades, "wr": wins / max(n_trades, 1) * 100, "liq": liqs,
            "halts": halts, "bust": False}


def rolling_windows(trades, days=365, step_days=15):
    t0, t1 = trades[0]["dt"], trades[-1]["dt"]
    starts = pd.date_range(pd.Timestamp(t0), pd.Timestamp(t1) - pd.Timedelta(days=days), freq=f"{step_days}D")
    return [pd.Timestamp(s) for s in starts]


def section_rolling(trades):
    print("=" * 100)
    print("  [1] 1년 창 — 지금 시작하면 1년 뒤 얼마인가 (모든 시작 시점 굴려봄)")
    print("=" * 100)
    starts = rolling_windows(trades)
    res = []
    for s in starts:
        win = [t for t in trades if s <= t["dt"] < s + pd.Timedelta(days=365)]
        if len(win) < 15:
            continue
        r = simulate(win, LEV, PER_TRADE, MAX_GROSS, CB, COOL_DAYS, 1e-6)
        res.append({"s": s, "m": 0.0 if r["bust"] else r["final"], "mdd": r["mdd_low"], "n": r["n"]})
    d = pd.DataFrame(res)
    print(f"\n  창 {len(d)}개 · 배율 {LEV}x · 진입당 {PER_TRADE*100:.0f}% · 차단기 -{CB*100:.0f}%/{COOL_DAYS:.0f}일재개")
    print(f"\n  {'분위':10s}{'배수':>10s}{'100만원 기준':>14s}")
    for q, lab in ((.05, "하위5%"), (.25, "하위25%"), (.5, "중앙"), (.75, "상위25%"), (.95, "상위5%")):
        v = d.m.quantile(q)
        print(f"  {lab:10s}{v:>9.2f}배{v*START:>13,.0f}원")
    print(f"\n  1년 뒤 원금 손실 확률   {(d.m<1).mean()*100:>5.1f}%")
    print(f"  1년 뒤 반토막 확률      {(d.m<0.5).mean()*100:>5.1f}%")
    print(f"  1년에 2배 이상 확률     {(d.m>=2).mean()*100:>5.1f}%")
    print(f"  1년에 10배 이상 확률    {(d.m>=10).mean()*100:>5.1f}%")
    print(f"  최악 / 최고             {d.m.min():.2f}배 / {d.m.max():.2f}배")
    print(f"  평균 장중 낙폭(저가기준) {d.mdd.mean()*100:.1f}%   최악 {d.mdd.max()*100:.1f}%")

    d2 = d.copy(); d2["y"] = pd.DatetimeIndex(d2.s).year
    print(f"\n  시작연도별")
    print(f"  {'연도':8s}{'창':>4s}{'중앙':>9s}{'최악':>9s}{'최고':>10s}{'손실확률':>9s}")
    for y, g in d2.groupby("y"):
        print(f"  {y:<8d}{len(g):>4}{g.m.median():>8.2f}배{g.m.min():>8.2f}배"
              f"{g.m.max():>9.2f}배{(g.m<1).mean()*100:>8.0f}%")
    return d


def section_dca(trades):
    print(f"\n{'='*100}")
    print(f"  [2] 월 적립 — 100만원 시작 + 월 30만원, 1년 후")
    print("=" * 100)
    starts = rolling_windows(trades)
    res = []
    for s in starts:
        win = [t for t in trades if s <= t["dt"] < s + pd.Timedelta(days=365)]
        if len(win) < 15:
            continue
        r = simulate_dca(win, LEV, PER_TRADE, MAX_GROSS, CB, COOL_DAYS,
                         start_cap=START, monthly=MONTHLY, months=12)
        res.append({"s": s, "final": 0.0 if r["bust"] else r["final"], "dep": r["dep"]})
    d = pd.DataFrame(res)
    total = START + MONTHLY * 12
    print(f"\n  창 {len(d)}개 · 총 납입 {total:,.0f}원 (그냥 저축하면 이 금액)")
    print(f"\n  {'분위':10s}{'금액':>13s}{'납입대비':>10s}")
    for q, lab in ((.05, "하위5%"), (.25, "하위25%"), (.5, "중앙"), (.75, "상위25%"), (.95, "상위5%")):
        v = d.final.quantile(q)
        print(f"  {lab:10s}{v:>12,.0f}원{(v/total-1)*100:>+9.1f}%")
    print(f"\n  원금(납입액) 손실 확률  {(d.final<total).mean()*100:>5.1f}%")
    print(f"  최악 / 최고             {d.final.min():>10,.0f}원 / {d.final.max():>10,.0f}원")
    d2 = d.copy(); d2["y"] = pd.DatetimeIndex(d2.s).year
    print(f"\n  시작연도별")
    print(f"  {'연도':8s}{'창':>4s}{'중앙':>13s}{'손실확률':>9s}")
    for y, g in d2.groupby("y"):
        print(f"  {y:<8d}{len(g):>4}{g.final.median():>12,.0f}원{(g.final<total).mean()*100:>8.0f}%")


def section_100x(trades):
    print(f"\n{'='*100}")
    print("  [3] 100배까지 — 전체구간·홀드아웃 각각의 연복리로 역산")
    print("=" * 100)
    ho = [t for t in trades if t["dt"] >= pd.Timestamp("2024-01-01")]
    for label, T in (("전체 2017~2026 (28% 연복리)", trades), ("홀드아웃 2024~2026 (71% 연복리)", ho)):
        r = simulate(T, LEV, PER_TRADE, MAX_GROSS, CB, COOL_DAYS, 1e-6)
        yrs = (T[-1]["dt"] - T[0]["dt"]) / np.timedelta64(1, "D") / 365.25
        if r["bust"] or r["final"] <= 1:
            print(f"  {label}: 원금 손실 — 도달 불가"); continue
        cagr = r["final"] ** (1/yrs) - 1
        t100 = np.log(100) / np.log(1 + cagr)
        print(f"  {label}: 실제 연복리 {cagr*100:.0f}%  →  100배까지 {t100:.1f}년")
    print(f"\n  홀드아웃 연복리(71%)가 유지된다는 가정은 낙관적이다 — 2년치 표본이고")
    print(f"  마침 강세장이었다. 전체구간(28%) 쪽이 더 현실적인 기준값이다.")


def section_stress(trades):
    print(f"\n{'='*100}")
    print("  [4] 비용 스트레스 — 슬리피지가 가정보다 나쁘면?")
    print("=" * 100)
    import ml.backtest_current_bot as B
    orig_rt, orig_fund = B.ROUND_TRIP, B.FUNDING_PER_8H
    ho = [t for t in trades if t["dt"] >= pd.Timestamp("2024-01-01")]
    print(f"\n  {'왕복비용':10s}{'전체 최종':>11s}{'전체승률':>9s}{'홀드 최종':>11s}{'홀드승률':>9s}")
    for rt in (0.20, 0.30, 0.40, 0.60, 0.80, 1.00):
        B.ROUND_TRIP = rt
        r_full = simulate(trades, LEV, PER_TRADE, MAX_GROSS, CB, COOL_DAYS, 1e-6)
        r_ho = simulate(ho, LEV, PER_TRADE, MAX_GROSS, CB, COOL_DAYS, 1e-6)
        f1 = "파산" if r_full["bust"] else f"{r_full['final']:.2f}배"
        f2 = "파산" if r_ho["bust"] else f"{r_ho['final']:.2f}배"
        mark = "  ← 기본가정" if abs(rt - orig_rt) < 1e-9 else ""
        print(f"  {rt:>8.2f}%{f1:>11s}{r_full['wr']:>8.1f}%{f2:>11s}{r_ho['wr']:>8.1f}%{mark}")
    B.ROUND_TRIP = orig_rt
    print(f"\n  '판단은 종가, 체결은 다음봉 시가' 가정이 실제(같은 봉 종가 체결)와")
    print(f"  얼마나 다른지는 아직 모른다 — 이 표는 그 불확실성을 비용으로")
    print(f"  환산해서 어디까지 견디는지 보는 것이다. 0.6% 왕복까지도 전체구간은")
    print(f"  살아남는지 확인해라.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["rolling", "dca", "100x", "stress"], default=None)
    a = ap.parse_args()

    print("=" * 100)
    print(f"  시나리오 백테스트 — bot/oversold/ 현재 설정 (42종·20봉·분할매수·"
          f"{LEV}x·차단-{CB*100:.0f}%/{COOL_DAYS:.0f}일)")
    print("=" * 100)
    trades, have, missing = build_all()
    print(f"  종목 {len(have)}개 · 신호 {len(trades):,}건 · "
          f"{str(trades[0]['dt'])[:10]} ~ {str(trades[-1]['dt'])[:10]}")

    if a.only in (None, "rolling"):
        section_rolling(trades)
    if a.only in (None, "dca"):
        section_dca(trades)
    if a.only in (None, "100x"):
        section_100x(trades)
    if a.only in (None, "stress"):
        section_stress(trades)


if __name__ == "__main__":
    main()
