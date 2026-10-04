"""
ml/mtm_drawdown.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
평가손익까지 포함한 진짜 낙폭

지금까지 보고한 낙폭은 **청산된 거래만**으로 그린 자본 곡선에서 쟀다.
거래가 끝나야 자본이 갱신되므로, 포지션을 들고 있는 동안의 평가손실이
빠져 있다. 10종목을 동시에 들고 전부 -20%면 계좌 잔고는 이미 줄어
있는데 그 곡선에는 나타나지 않는다.

실제 계좌에서 보이는 숫자는 평가손익을 포함한 값이고, 강제청산도
평가손익 기준으로 일어난다. 그래서 이쪽이 진짜다.

여기서 계산하는 것:
    실현 낙폭      청산된 거래만 (기존 방식)
    평가 낙폭(종가) 매 봉 종가로 미결제 포지션을 평가
    평가 낙폭(저가) 매 봉 저가로 평가 — 장중에 실제로 본 최악

세 번째가 가장 보수적이고, 사람이 화면에서 실제로 보는 숫자에 가깝다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ml.full_optimizer import build, resolve, RT, F8
from ml.path_to_100x import all_symbols
from ml.majors_only import MAJORS


def simulate_mtm(trades, kind, prm, lev, per_trade, max_gross,
                 cb=None, cool_days=30, stop=-40.0, bar_h=4.0):
    """봉 단위로 평가손익까지 포함해 자본 곡선을 만든다."""
    liq = -100.0/lev + 0.5
    cash = 1.0                       # 실현 자본
    peak_r = peak_c = peak_l = 1.0
    mdd_r = mdd_c = mdd_l = 0.0
    mdd_l_at = None
    halted_until = None; halts = 0
    taken = liqs = wins = 0
    hit100 = None

    # 미결제: dict[sym] = {"exit_dt","qty_notional","entry","closes","lows","dts","idx"}
    openp = {}
    # 시간축: 모든 진입/청산 시점을 훑되, 평가는 각 포지션의 봉을 따라간다
    events = []                      # (시각, 종류, 데이터)
    for t in trades:
        events.append((t["dt"], "signal", t))
    events.sort(key=lambda x: x[0])

    def mtm(now, use_low):
        """현재 미결제 포지션의 평가손익 합"""
        tot = 0.0
        for sym, p in openp.items():
            k = np.searchsorted(p["dts"], np.datetime64(now), side="right") - 1
            if k < 0: continue
            k = min(k, len(p["px_c"]) - 1)
            px = p["px_l"][k] if use_low else p["px_c"][k]
            r = (px / p["entry"] - 1) * 100
            r = max(r, max(stop, liq))          # 손절/청산선 아래로는 안 간다
            tot += p["notional"] * r / 100
        return tot

    for now, _, t in events:
        # 만기 도래 청산
        for sym in list(openp):
            if openp[sym]["exit_dt"] <= now:
                p = openp.pop(sym)
                cash += p["realized"]
        if cb is not None:
            if halted_until is not None and now < halted_until:
                pass
            else:
                cur = cash + mtm(now, False)
                if peak_c > 0 and 1 - cur/peak_c >= cb:
                    halted_until = now + pd.Timedelta(days=cool_days)
                    halts += 1; peak_c = cur; peak_r = cash
                    continue
        if halted_until is not None and now < halted_until:
            continue
        if t["sym"] in openp:
            continue
        gross = sum(p["notional"] for p in openp.values())
        eq_now = cash + mtm(now, False)
        margin = eq_now * per_trade; notional = margin * lev
        if gross + notional > eq_now * max_gross * lev:
            continue
        r, k, was_liq = resolve(t, kind, prm, stop, liq)
        if was_liq: liqs += 1
        net = r - RT - F8*(k*bar_h/8.0)
        realized = max(margin*lev*net/100, -margin)
        taken += 1; wins += net > 0
        kk = min(k, len(t["dts"]) - 1)
        openp[t["sym"]] = {
            "exit_dt": t["dts"][kk], "notional": notional, "entry": t["e"],
            "realized": realized, "dts": t["dts"][:kk+1],
            "px_c": t["o"][:kk+1], "px_l": t["l"][:kk+1],
        }
        # 세 가지 낙폭 갱신
        e_r = cash
        e_c = cash + mtm(now, False)
        e_l = cash + mtm(now, True)
        if e_c <= 0 or e_l <= 0:
            return {"bust": True, "mdd_r": 1, "mdd_c": 1, "mdd_l": 1,
                    "final": 0, "n": taken, "liq": liqs, "halts": halts,
                    "hit100": None, "wr": 0, "mdd_l_at": mdd_l_at}
        for e, pk, nm in ((e_r,"r",None),(e_c,"c",None),(e_l,"l",None)):
            pass
        peak_r = max(peak_r, e_r); mdd_r = max(mdd_r, 1 - e_r/peak_r)
        peak_c = max(peak_c, e_c); mdd_c = max(mdd_c, 1 - e_c/peak_c)
        if peak_l > 0 and 1 - e_l/peak_l > mdd_l:
            mdd_l = 1 - e_l/peak_l; mdd_l_at = now
        peak_l = max(peak_l, e_l)
        if hit100 is None and cash >= 100: hit100 = now
    for sym in list(openp):
        cash += openp.pop(sym)["realized"]
    return {"bust": False, "final": cash, "mdd_r": mdd_r, "mdd_c": mdd_c,
            "mdd_l": mdd_l, "n": taken, "liq": liqs, "halts": halts,
            "hit100": hit100, "wr": wins/max(taken,1)*100, "mdd_l_at": mdd_l_at}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default="all")
    a = ap.parse_args()
    syms = all_symbols() if a.universe == "all" else MAJORS
    T = build(symbols=syms)
    t0 = T[0]["dt"]

    print("=" * 100)
    print(f"  평가손익 포함 낙폭 — {'전체 46종' if a.universe=='all' else '메이저 12종'}, "
          f"고정20봉, 2배")
    print("  실현 = 청산된 거래만 · 평가(종가) = 미결제 포함 · 평가(저가) = 장중 최악")
    print("=" * 100)
    print(f"  {'차단기':12s}{'동시':6s}{'거래':>7s}{'최종':>9s}"
          f"{'실현낙폭':>9s}{'평가낙폭':>9s}{'장중최악':>9s}{'100배':>8s}{'발동':>5s}")
    print("  " + "-" * 84)
    for pt, mg, sl in ((0.10, 1.0, "10종"), (0.05, 1.0, "20종")):
        for cb, lab in ((None, "없음"), (0.25, "고점-25%")):
            r = simulate_mtm(T, "fixed", 20, 2, pt, mg, cb=cb)
            if r["bust"]:
                print(f"  {lab:12s}{sl:6s}  파산"); continue
            hit = f"{(r['hit100']-t0).days/365.25:.1f}년" if r["hit100"] else "미도달"
            print(f"  {lab:12s}{sl:6s}{r['n']:>7,}{r['final']:>8,.0f}배"
                  f"{r['mdd_r']*100:>8.1f}%{r['mdd_c']*100:>8.1f}%{r['mdd_l']*100:>8.1f}%"
                  f"{hit:>8s}{r['halts']:>5}")
            if r["mdd_l_at"] is not None:
                print(f"  {'':18s}장중 최악 시점: {str(r['mdd_l_at'])[:10]}")
        print()


if __name__ == "__main__":
    main()
