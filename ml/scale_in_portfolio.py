"""
ml/scale_in_portfolio.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
분할매수를 포트폴리오에서 검증 — 거래당 개선이 살아남는가

거래 하나만 보면 분할매수는 명확히 낫다(홀드아웃 +4.10% → +6.51%).
하지만 이 세션에서 거래당 개선이 포트폴리오에서 뒤집힌 사례가 여럿
있었다. ATR 청산은 거래당 수익을 70% 올렸지만 포지션 자리를 4배
오래 잡아 진입 횟수를 줄였다.

분할매수의 위험은 방향이 다르다. 2차 매수는 **가격이 더 빠졌을 때**
나간다. 코인은 상관 0.575라 급락하면 여러 종목이 동시에 2차 매수
조건을 만족한다. 즉 가장 위험한 순간에 노출이 한꺼번에 커진다.
거래당 평단은 좋아져도 계좌 낙폭은 나빠질 수 있다.

여기서는 sim_correct와 같은 방식으로(자본 = 현금 + 평가손익) 굴리되,
포지션이 두 번에 나눠 들어가는 것을 반영한다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, glob, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ml.edge_scan_all import load_all
from ml.majors_only import MAJORS

RT_ONE = 0.1; FUND8 = 0.01; HOLD = 20; MAXB = 60


def build(symbols=None):
    raw = load_all("4h")
    raw = raw[raw["symbol"].isin(symbols or MAJORS)]
    out = []
    for sym, g in raw.groupby("symbol", sort=False):
        g = g.sort_values("datetime").reset_index(drop=True)
        o = g["open"].astype(float).values; h = g["high"].astype(float).values
        l = g["low"].astype(float).values
        c = g["close"].astype(float).values
        vs = (c / pd.Series(c).rolling(20).mean().values - 1) * 100
        lock = -10**9
        for i in np.where(vs <= -12.26)[0]:
            if i <= lock or i + 1 + MAXB >= len(g): continue
            lock = i + HOLD
            out.append({"sym": sym, "dt": g["datetime"].iloc[i],
                        "dts": g["datetime"].values[i+1:i+1+MAXB],
                        "o": o[i+1:i+1+MAXB], "h": h[i+1:i+1+MAXB],
                        "l": l[i+1:i+1+MAXB]})
    return sorted(out, key=lambda t: t["dt"])


class P:
    __slots__ = ("sym","avg","notional","exit_dt","dts","px","lows","realized","liq","peak_not")
    def __init__(s, sym, avg, notional, exit_dt, dts, px, lows, realized, liq):
        s.sym=sym; s.avg=avg; s.notional=notional; s.exit_dt=exit_dt
        s.dts=dts; s.px=px; s.lows=lows; s.realized=realized; s.liq=liq
    def unreal(s, now, low=False):
        k = np.searchsorted(s.dts, np.datetime64(now), side="right") - 1
        if k < 0: return 0.0
        k = min(k, len(s.px)-1)
        p = s.lows[k] if low else s.px[k]
        return s.notional * max((p/s.avg - 1)*100, s.liq) / 100


def resolve_scaled(t, w1, drop, lev, stop=-40.0):
    """분할 진입 후 HOLD봉 뒤 청산. 평단·명목·매수횟수·강제청산 여부."""
    e0 = t["o"][0]
    liq_line = -100.0/lev + 0.5
    hard = max(stop, liq_line)
    trig = e0 * (1 + drop/100)
    hit = np.where(t["l"][:HOLD] <= trig)[0]
    if len(hit):
        avg = e0*w1 + trig*(1-w1); nfill = 2; scale = 1.0
    else:
        avg = e0; nfill = 1; scale = w1        # 2차 미체결 → 그만큼만 투입
    # 청산/손절: 평단 기준 저가
    mae = (t["l"][:HOLD].min()/avg - 1)*100
    was_liq = mae <= hard and hard == liq_line
    if mae <= hard:
        gross = hard
    else:
        gross = (t["o"][min(HOLD, len(t["o"])-1)]/avg - 1)*100
    cost = RT_ONE*(nfill+1) + FUND8*(HOLD*4/8)
    return avg, gross - cost, scale, nfill, was_liq


def simulate(trades, w1, drop, lev, per, mg, cb=0.25, cool=30):
    """w1=1.0 이면 일괄매수(현재 규칙)"""
    liq = -100.0/lev + 0.5
    cash = 1.0; peak = 1.0; mdd = 0.0; peak_l = 1.0; mdd_l = 0.0
    openp = {}; taken = wins = liqs = halts = 0; halted = None
    for t in trades:
        now = t["dt"]
        for s in [s for s,p in openp.items() if p.exit_dt <= now]:
            cash += openp.pop(s).realized
        eq   = cash + sum(p.unreal(now) for p in openp.values())
        eq_l = cash + sum(p.unreal(now, True) for p in openp.values())
        if eq <= 0:
            return {"bust": True, "final": 0.0, "mdd": 1.0, "mdd_low": 1.0,
                    "n": taken, "wr": 0.0, "liq": liqs, "halts": halts}
        if 1 - eq/peak > mdd: mdd = 1 - eq/peak
        peak = max(peak, eq)
        peak_l = max(peak_l, eq_l); mdd_l = max(mdd_l, 1 - eq_l/peak_l)
        if cb is not None:
            if halted is not None and now < halted: continue
            if 1 - eq/peak >= cb:
                halted = now + pd.Timedelta(days=cool); halts += 1; peak = eq; continue
        if t["sym"] in openp: continue
        gross_exp = sum(p.notional for p in openp.values())
        margin_full = eq * per
        # 2차까지 갈 수 있으므로 전액 기준으로 자리를 잡아둔다
        if gross_exp + margin_full*lev > eq * mg * lev: continue
        avg, net, scale, nfill, wl = resolve_scaled(t, w1, drop, lev)
        if wl: liqs += 1
        margin = margin_full * scale
        realized = max(margin*lev*net/100, -margin)
        cash_delta = realized
        taken += 1; wins += net > 0
        kk = min(HOLD, len(t["dts"])-1)
        openp[t["sym"]] = P(t["sym"], avg, margin*lev, t["dts"][kk],
                            t["dts"][:kk+1], t["o"][:kk+1], t["l"][:kk+1],
                            cash_delta, max(-40.0, liq))
    for s in list(openp): cash += openp.pop(s).realized
    return {"bust": False, "final": cash, "mdd": mdd, "mdd_low": mdd_l,
            "n": taken, "wr": wins/max(taken,1)*100, "liq": liqs, "halts": halts}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all46", action="store_true")
    a = ap.parse_args()
    syms = None
    if a.all46:
        syms = [os.path.basename(f).split("_4h_")[0]
                for f in sorted(glob.glob("data/*_4h_all.csv.gz"))]
        syms = [s for s in syms if s.endswith("USDT")]
    T = build(syms)
    yrs = (T[-1]["dt"] - T[0]["dt"]).days/365.25
    print("=" * 96)
    print(f"  분할매수 포트폴리오 검증 — {'46종' if a.all46 else '메이저 12종'} · "
          f"신호 {len(T):,}건 · {yrs:.1f}년")
    print(f"  자본 = 현금 + 평가손익 · 차단기 -25% · 편도 비용 {RT_ONE}%")
    print("=" * 96)
    print(f"\n  {'진입 방식':24s}{'배율':>5s}{'거래':>6s}{'승률':>7s}{'최종':>9s}"
          f"{'연복리':>8s}{'낙폭':>7s}{'장중':>7s}{'청산':>5s}")
    print("  " + "-" * 84)
    for lev in (1, 2):
        base = None
        for w1, drop, lab in ((1.0, -5.0, "일괄 (현재 규칙)"),
                              (0.5, -5.0, "분할 50% + -5%에 50%"),
                              (0.3, -5.0, "분할 30% + -5%에 70%"),
                              (0.5, -8.0, "분할 50% + -8%에 50%"),
                              (0.3, -8.0, "분할 30% + -8%에 70%")):
            r = simulate(T, w1, drop, lev, 0.05, 1.0)
            if r["bust"]:
                print(f"  {lab:24s}{lev:>4}x  파산"); continue
            cagr = (r["final"]**(1/yrs)-1)*100
            if base is None: base = r["final"]
            mark = "  ← 기준" if w1 == 1.0 else ("  ✅" if r["final"] > base else "")
            print(f"  {lab:24s}{lev:>4}x{r['n']:>6,}{r['wr']:>6.1f}%"
                  f"{r['final']:>8.1f}배{cagr:>7.0f}%{r['mdd']*100:>6.1f}%"
                  f"{r['mdd_low']*100:>6.1f}%{r['liq']:>5}{mark}")
        print()


if __name__ == "__main__":
    main()
