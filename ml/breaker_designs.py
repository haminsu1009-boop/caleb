"""
ml/breaker_designs.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
차단기 설계를 바꿔서 낙폭을 실제로 묶을 수 있는가

지금 차단기는 -25%에서 신규 진입을 멈추고 30일 뒤 재개한다.
그런데 1년 창 189개에서 장중 낙폭이 -90%를 넘는 경우가 13%다
(배율 2배 기준). -25%로 묶는다고 했는데 -90%가 나오는 이유:

  1. 발동할 때 고점을 현재 자본으로 리셋한다(peak = eq_mtm).
     그래서 -25%가 여섯 번 겹치면 0.75^6 ≈ -82%가 된다.
     각 구간은 -25%지만 누적은 안 묶인다.
  2. 종가로만 판정한다. 저가로 -40%를 찍고 되돌아온 봉은
     차단기가 보지 못한다. 거래소 청산은 저가에서 집행된다.
  3. 신규 진입만 멈춘다. 이미 열린 포지션은 그대로 간다.
     동시 20종이 열려 있으면 멈춰도 노출은 그대로다.

여기서 여러 설계를 실제로 붙여 비교한다. 판정 기준은 수익이
아니라 **낙폭 분포**다 — 얼마나 자주 -70%, -90%를 겪는가.

수익을 얼마나 포기하고 낙폭을 얼마나 사는지, 그 교환비를 본다.
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

TRAIN_END = pd.Timestamp("2024-01-01")
WIN, STEP = 365, 15


def run(trades, *, leverage=2.0, per_trade=0.05, max_gross=1.0,
        cb=0.25, cool_days=30, min_equity=1e-6,
        reset_peak=True,        # 발동 시 고점을 현재 자본으로 리셋하는가
        basis="close",          # 차단기 판정 기준: close | low
        soft_cb=None,           # 이 낙폭부터 베팅을 줄인다 (2단계)
        soft_frac=0.5,          # 줄이는 비율
        taper=False,            # 낙폭에 비례해 연속적으로 줄인다
        ):
    """차단기 설계를 바꿔가며 돌릴 수 있는 시뮬레이터.

    기본 인자는 현재 봇과 동일하다(reset_peak=True, basis="close").
    """
    liq_line = -100.0 / leverage + 0.5
    cash = peak = peak_low = 1.0
    mdd = mdd_low = 0.0
    positions: dict[str, Pos] = {}
    halted_until = None
    halts = n_trades = wins = liqs = 0
    bust = False

    for t in trades:
        now = t["dt"]
        for s in [s for s, p in positions.items() if p.exit_dt <= now]:
            cash += positions.pop(s).realized

        eq_mtm = cash + sum(p.unreal(now) for p in positions.values())
        eq_low = cash + sum(p.unreal(now, True) for p in positions.values())
        if eq_mtm <= 0 or eq_mtm < min_equity:
            bust = True
            break
        if eq_mtm > peak:
            peak = eq_mtm
        else:
            mdd = max(mdd, 1 - eq_mtm / peak)
        if eq_low > peak_low:
            peak_low = eq_low
        else:
            mdd_low = max(mdd_low, 1 - eq_low / peak_low)

        # ── 차단기 판정
        # basis="low"면 저가 기준 자본으로 판정한다. 거래소 청산이
        # 저가에서 집행되므로 그쪽이 실제 위험에 가깝다.
        eq_judge = eq_low if basis == "low" else eq_mtm
        peak_judge = peak_low if basis == "low" else peak
        dd = 1 - eq_judge / peak_judge if peak_judge > 0 else 0.0

        if halted_until is not None and now < halted_until:
            can_enter = False
        else:
            halted_until = None
            can_enter = True

        if can_enter and dd >= cb:
            halted_until = now + pd.Timedelta(days=cool_days)
            halts += 1
            # reset_peak=False면 고점을 그대로 둔다. 그러면 재개 후에도
            # 여전히 -25% 아래라 바로 다시 걸린다 — 즉 회복할 때까지
            # 사실상 계속 멈춰 있다. 이게 누적 낙폭을 묶는 핵심이다.
            if reset_peak:
                peak = eq_mtm
                peak_low = eq_low
            can_enter = False

        if t["sym"] in positions or not can_enter:
            continue

        # ── 베팅 크기 축소 (2단계 / 연속)
        scale = 1.0
        if taper and dd > 0:
            scale = max(0.0, 1 - dd / cb)          # 낙폭이 cb에 가까울수록 0으로
        elif soft_cb is not None and dd >= soft_cb:
            scale = soft_frac
        if scale <= 0.01:
            continue

        base = eq_mtm
        margin = per_trade * base * scale
        full_notional = margin * leverage
        gross = sum(p.reserved for p in positions.values())
        if gross + full_notional > max_gross * leverage * base:
            continue

        px_ret, was_liq = pnl_pct(t["entry_avg"], t["exit_px"], leverage,
                                  liq_line, t["mae"])
        held_h = (t["exit_bar"] - t["entry_bar"]) * BAR_HOURS
        fee = ROUND_TRIP + FUNDING_PER_8H * (held_h / 8.0)
        net = px_ret - fee
        realized = max(margin * leverage * net / 100, -margin)
        n_trades += 1
        wins += net > 0
        liqs += was_liq
        positions[t["sym"]] = Pos(t, margin, leverage, liq_line, fee, realized)

    for p in positions.values():
        cash += p.realized
    return {"final": cash, "mdd": mdd, "mdd_low": mdd_low, "n": n_trades,
            "wr": wins / max(n_trades, 1) * 100, "liq": liqs,
            "halts": halts, "bust": bust}


def windows(trades, **kw):
    t0, t1 = trades[0]["dt"], trades[-1]["dt"]
    starts = pd.date_range(pd.Timestamp(t0),
                           pd.Timestamp(t1) - pd.Timedelta(days=WIN), freq=f"{STEP}D")
    rows = []
    for s in starts:
        w = [t for t in trades if s <= t["dt"] < s + pd.Timedelta(days=WIN)]
        if len(w) < 10:
            continue
        r = run(w, **kw)
        rows.append({"mult": 0.0 if r["bust"] else r["final"],
                     "close": r["mdd"], "low": r["mdd_low"], "halts": r["halts"]})
    return pd.DataFrame(rows)


DESIGNS = [
    ("① 현재 (-25%, 고점리셋, 종가)",   dict()),
    ("② 고점 유지 (회복까지 정지)",      dict(reset_peak=False)),
    ("③ 장중(저가) 기준 판정",          dict(basis="low")),
    ("④ ②+③ 둘 다",                  dict(reset_peak=False, basis="low")),
    ("⑤ 2단계 -15%부터 절반",          dict(soft_cb=0.15)),
    ("⑥ 낙폭비례 축소 (연속)",          dict(taper=True)),
    ("⑦ ④+⑥ 전부",                   dict(reset_peak=False, basis="low", taper=True)),
    ("⑧ 차단기 -15%로 강화",           dict(cb=0.15)),
    ("⑨ -15% + 고점유지 + 장중",        dict(cb=0.15, reset_peak=False, basis="low")),
    ("⑩ 총노출 50%로 축소",            dict(max_gross=0.5)),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--leverage", type=float, default=2.0)
    ap.add_argument("--per-trade", type=float, default=0.05)
    a = ap.parse_args()

    trades, have, _ = build_all()
    tr = [t for t in trades if pd.Timestamp(t["dt"]) < TRAIN_END]
    ho = [t for t in trades if pd.Timestamp(t["dt"]) >= TRAIN_END]

    print("=" * 100)
    print(f"  차단기 설계 비교 — 배율 {a.leverage:g}배 · 진입당 {a.per_trade*100:g}% · 복리")
    print(f"  판정 기준은 수익이 아니라 낙폭 분포다 (1년 창 189개)")
    print("=" * 100)
    print(f"\n  {'설계':<26s}{'전체':>9s}{'홀드':>9s}{'중앙낙폭':>9s}"
          f"{'-50%':>6s}{'-70%':>6s}{'-90%':>6s}{'거래':>7s}{'차단':>6s}")
    print("  " + "-" * 90)
    rows = []
    for name, kw in DESIGNS:
        kw = dict(leverage=a.leverage, per_trade=a.per_trade, **kw)
        d = windows(trades, **kw)
        rf = run(trades, **kw)
        rh = run(ho, **kw)
        rec = {"name": name, "full": rf["final"], "ho": rh["final"],
               "mdd_med": d["low"].median() * 100,
               "p50": (d["low"] >= .5).mean() * 100,
               "p70": (d["low"] >= .7).mean() * 100,
               "p90": (d["low"] >= .9).mean() * 100,
               "n": rf["n"], "halts": rf["halts"]}
        rows.append(rec)
        print(f"  {name:<26s}{rec['full']:>8.1f}배{rec['ho']:>8.2f}배"
              f"{rec['mdd_med']:>8.0f}%{rec['p50']:>5.0f}%{rec['p70']:>5.0f}%"
              f"{rec['p90']:>5.0f}%{rec['n']:>7d}{rec['halts']:>6d}")

    r = pd.DataFrame(rows)
    base = r.iloc[0]
    print(f"\n  ── 현재 설계 대비 (수익을 얼마 포기하고 낙폭을 얼마 샀나)")
    print(f"  {'설계':<26s}{'수익 비율':>10s}{'-90% 감소':>11s}{'-70% 감소':>11s}{'교환비':>9s}")
    print("  " + "-" * 68)
    for _, x in r.iloc[1:].iterrows():
        keep = x.full / base.full if base.full > 0 else np.nan
        d90 = base.p90 - x.p90
        d70 = base.p70 - x.p70
        # 교환비: 낙폭 위험을 1%p 줄이는 데 수익의 몇 %를 냈나
        cost = (1 - keep) * 100
        ratio = cost / d90 if d90 > 0 else np.nan
        print(f"  {x['name']:<26s}{keep:>9.2f}배{d90:>10.0f}%p{d70:>10.0f}%p"
              f"{(f'{ratio:.1f}' if ratio == ratio else '  —'):>9s}")
    print(f"\n  교환비 = 장중 -90% 확률을 1%p 낮추는 데 포기한 수익(%). 낮을수록 좋다.")


if __name__ == "__main__":
    main()
