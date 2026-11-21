"""
ml/sim_correct.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
올바른 포트폴리오 시뮬레이터 — 앞선 두 구현이 모두 틀렸다

버그 1 (full_optimizer.simulate):
    진입 시점에 손익을 자본에 즉시 더했다. 20봉 뒤에 실현될 이익을
    진입 순간부터 복리로 굴린 셈이다. 46종 2배에서 317배를 만들었다.

버그 2 (손익을 청산 시점에 반영하되 크기는 실현자본 기준):
    미실현 손실이 반영 안 된 자본으로 포지션 크기를 정한다. 하락장에
    10종목이 전부 물려 있는데도 부풀려진 자본의 10%씩 계속 넣는다.
    이번엔 반대로 손실을 키운다.

올바른 방식 (거래소와 같게):
    자본 = 현금 + 미결제 포지션의 평가손익
    새 포지션 크기는 그 자본을 기준으로 정한다
    청산되면 실현 손익이 현금으로 넘어온다
    낙폭도 이 자본으로 잰다 — 계좌 화면에 뜨는 숫자가 이것이다

평가는 봉 시가 기준으로 한다. 장중 저가 기준은 더 보수적이라 따로 낸다.
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


class Pos:
    __slots__ = ("sym","entry","notional","exit_dt","dts","px","lows","realized","liq_line")
    def __init__(self, sym, entry, notional, exit_dt, dts, px, lows, realized, liq_line):
        self.sym=sym; self.entry=entry; self.notional=notional
        self.exit_dt=exit_dt; self.dts=dts; self.px=px; self.lows=lows
        self.realized=realized; self.liq_line=liq_line

    def unreal(self, now, use_low=False):
        k = np.searchsorted(self.dts, np.datetime64(now), side="right") - 1
        if k < 0: return 0.0
        k = min(k, len(self.px)-1)
        p = self.lows[k] if use_low else self.px[k]
        r = (p/self.entry - 1)*100
        r = max(r, self.liq_line)              # 청산선 아래로는 못 간다
        return self.notional * r / 100


def simulate(trades, kind, prm, lev, per, mg, cb=None, cool_days=30,
             stop=-40.0, bh=4.0):
    liq = -100.0/lev + 0.5
    hard = max(stop, liq)
    cash = 1.0
    peak = 1.0; mdd = 0.0; mdd_at = None
    mdd_low = 0.0; peak_low = 1.0
    openp = {}
    taken = liqs = wins = 0
    hit100 = None; halts = 0; halted_until = None
    under = 0

    ev = sorted(trades, key=lambda t: t["dt"])
    for t in ev:
        now = t["dt"]
        for s in [s for s,p in openp.items() if p.exit_dt <= now]:
            cash += openp.pop(s).realized
        eq = cash + sum(p.unreal(now) for p in openp.values())
        eq_low = cash + sum(p.unreal(now, True) for p in openp.values())
        if eq <= 0:
            return {"bust": True, "final": 0.0, "mdd": 1.0, "mdd_low": 1.0,
                    "n": taken, "liq": liqs, "wr": 0.0, "hit100": None,
                    "halts": halts, "under": under, "mdd_at": mdd_at}
        if eq > peak: peak = eq
        else: mdd = max(mdd, 1 - eq/peak) if 1-eq/peak <= mdd else mdd
        if 1 - eq/peak > mdd: mdd = 1 - eq/peak; mdd_at = now
        peak_low = max(peak_low, eq_low); mdd_low = max(mdd_low, 1 - eq_low/peak_low)
        if eq < 1.0: under += 1
        if hit100 is None and eq >= 100: hit100 = now

        if cb is not None:
            if halted_until is not None and now < halted_until:
                continue
            if 1 - eq/peak >= cb:
                halted_until = now + pd.Timedelta(days=cool_days)
                halts += 1; peak = eq
                continue
        if t["sym"] in openp: continue
        gross = sum(p.notional for p in openp.values())
        margin = eq * per; notional = margin * lev
        if gross + notional > eq * mg * lev: continue

        r, k, was_liq = resolve(t, kind, prm, stop, liq)
        if was_liq: liqs += 1
        net = r - RT - F8*(k*bh/8.0)
        realized = max(margin*lev*net/100, -margin)
        taken += 1; wins += net > 0
        kk = min(k, len(t["dts"])-1)
        openp[t["sym"]] = Pos(t["sym"], t["e"], notional, t["dts"][kk],
                              t["dts"][:kk+1], t["o"][:kk+1], t["l"][:kk+1],
                              realized, hard)
    for s in list(openp): cash += openp.pop(s).realized
    return {"bust": False, "final": cash, "mdd": mdd, "mdd_low": mdd_low,
            "n": taken, "liq": liqs, "wr": wins/max(taken,1)*100,
            "hit100": hit100, "halts": halts, "under": under, "mdd_at": mdd_at}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=14)
    a = ap.parse_args()
    print("=" * 104)
    print("  올바른 시뮬레이션 — 자본 = 현금 + 평가손익, 크기도 낙폭도 이 자본 기준")
    print(f"  비용 왕복 {RT}% + 펀딩 {F8}%/8h · 격리마진 · 손절 -40% · 강제청산 봉 안 저가")
    print("=" * 104)
    for uname, syms in (("메이저 12종", MAJORS), ("전체 46종", all_symbols())):
        T = build(symbols=syms); t0 = T[0]["dt"]
        yrs = (T[-1]["dt"] - t0).days/365.25
        print(f"\n  [{uname}]  신호 {len(T):,}건 · {yrs:.1f}년")
        print(f"  {'청산':10s}{'동시':6s}{'배율':>5s}{'차단기':>9s}{'거래':>7s}{'승률':>7s}"
              f"{'최종':>10s}{'연복리':>8s}{'낙폭':>7s}{'장중':>7s}{'청산':>5s}")
        print("  " + "-" * 96)
        for kind, prm, el in (("fixed",20,"고정20봉"), ("atr",2.0,"ATR×2")):
            for per, mg, sl in ((0.10,1.0,"10종"), (0.05,1.0,"20종")):
                for lev in (1,2,3):
                    for cb, cl in ((None,"없음"), (0.25,"-25%")):
                        r = simulate(T, kind, prm, lev, per, mg, cb=cb)
                        if r["bust"]:
                            print(f"  {el:10s}{sl:6s}{lev:>4}x{cl:>9s}  파산"); continue
                        cagr = (r["final"]**(1/yrs)-1)*100 if r["final"]>0 else -100
                        print(f"  {el:10s}{sl:6s}{lev:>4}x{cl:>9s}{r['n']:>7,}{r['wr']:>6.1f}%"
                              f"{r['final']:>9,.1f}배{cagr:>7.0f}%{r['mdd']*100:>6.1f}%"
                              f"{r['mdd_low']*100:>6.1f}%{r['liq']:>5}")
                print()


if __name__ == "__main__":
    main()
