"""
ml/combined_portfolio.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
코인 + 미국주식 결합 — 100배를 막는 병목을 푸는 유일한 길

지금까지 확인된 병목:
    코인끼리 상관 0.575 → 12종을 담아도 실효 독립은 1.6종이다.
    급락일에는 상관이 더 오른다. 분산이 가장 필요한 순간에 사라진다.
    그래서 레버리지를 2배 넘게 못 올리고, 연복리가 36%에서 막힌다.

측정된 탈출구:
    코인 ↔ 미국주식 상관 +0.149.
    코인 폭락 하위 5% 날에도 +0.135로 유지된다 — 같이 안 무너진다.

같은 규칙(20MA 대비 과매도 반등)이 두 시장에 다 존재한다는 것은
이미 확인했다. 주식 쪽은 우위가 작지만(기준선 대비 +4~6%p) 코인과
독립적이라, 포트폴리오 수준에서는 낙폭을 낮춰 레버리지 여력을 만든다.

시험하는 것:
    코인만 / 주식만 / 둘을 섞었을 때
    같은 낙폭 예산에서 연복리가 올라가는가
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, glob, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ml.sim_correct import simulate, Pos
from ml.full_optimizer import build, resolve, RT, F8
from ml.path_to_100x import all_symbols

STOCK_RT = 0.05        # 주식 왕복 수수료+슬리피지 (코인보다 싸다)
# 주식을 1배 넘게 쓰면 증권사 신용이자가 붙는다. 국내 해외주식 신용은
# 연 6~9% 수준이므로 8%로 잡고 보유일수만큼 차감한다. 코인 펀딩과
# 달리 배율에 비례해 빌린 금액에만 붙으므로 (lev-1) 배로 계산한다.
STOCK_MARGIN_APR = 8.0   # %/년
MAXB = 90


def stock_trades(thr=-8.0, hold=10, min_rows=1000):
    """미국주식: 20일선 대비 thr% 이하 → 다음날 시가 진입 → hold일 뒤 청산"""
    out = []
    for f in sorted(glob.glob("data/stocks/*_1d.csv.gz")):
        sym = os.path.basename(f).split("_")[0]
        d = pd.read_csv(f, compression="gzip")
        d["datetime"] = pd.to_datetime(d["datetime"], format="mixed", errors="coerce")
        d = d.dropna(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)
        if len(d) < min_rows:
            continue
        o = d["open"].astype(float).values; h = d["high"].astype(float).values
        l = d["low"].astype(float).values;  c = d["close"].astype(float).values
        vs = (c / pd.Series(c).rolling(20).mean().values - 1) * 100
        pc = np.roll(c, 1)
        trg = np.maximum(h-l, np.maximum(abs(h-pc), abs(l-pc)))
        atr = pd.Series(trg).rolling(14).mean().values
        for i in np.where(vs <= thr)[0]:
            if i + 1 + MAXB >= len(d) or not np.isfinite(atr[i]) or atr[i] <= 0:
                continue
            out.append({"sym": "S_"+sym, "dt": d["datetime"].iloc[i], "e": o[i+1],
                        "atr": atr[i], "kind": "stock",
                        "dts": d["datetime"].values[i+1:i+1+MAXB],
                        "o": o[i+1:i+1+MAXB], "h": h[i+1:i+1+MAXB],
                        "l": l[i+1:i+1+MAXB]})
    return out


def sim_mixed(trades, prm, lev_c, lev_s, per, mg, cb=0.25, cool=30, stop=-40.0):
    """자산군별로 배율과 비용을 다르게 적용. 나머지는 sim_correct와 동일."""
    cash = 1.0; peak = 1.0; mdd = 0.0; peak_l = 1.0; mdd_l = 0.0
    openp = {}; taken = liqs = wins = 0; halts = 0; halted = None
    for t in sorted(trades, key=lambda x: x["dt"]):
        now = t["dt"]
        for s in [s for s, p in openp.items() if p.exit_dt <= now]:
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
        gross = sum(p.notional for p in openp.values())
        is_stock = t.get("kind") == "stock"
        lev = lev_s if is_stock else lev_c
        cost_rt = STOCK_RT if is_stock else RT
        bar_h = 24.0 if is_stock else 4.0
        margin = eq * per; notional = margin * lev
        if gross + notional > eq * mg * max(lev_c, lev_s): continue
        liq = -100.0/lev + 0.5
        r, k, was_liq = resolve(t, "atr", prm, stop, liq)
        if was_liq: liqs += 1
        if is_stock:
            fund = STOCK_MARGIN_APR * (lev-1)/max(lev,1) * (k/252.0) * 100/100
        else:
            fund = F8*(k*bar_h/8.0)
        net = r - cost_rt - fund
        realized = max(margin*lev*net/100, -margin)
        taken += 1; wins += net > 0
        kk = min(k, len(t["dts"])-1)
        openp[t["sym"]] = Pos(t["sym"], t["e"], notional, t["dts"][kk],
                              t["dts"][:kk+1], t["o"][:kk+1], t["l"][:kk+1],
                              realized, max(stop, liq))
    for s in list(openp): cash += openp.pop(s).realized
    return {"bust": False, "final": cash, "mdd": mdd, "mdd_low": mdd_l,
            "n": taken, "wr": wins/max(taken,1)*100, "liq": liqs, "halts": halts}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2018-01-01")
    a = ap.parse_args()

    C = [t for t in build(symbols=all_symbols()) if t["dt"] >= pd.Timestamp(a.start)]
    for t in C: t["kind"] = "coin"
    S = [t for t in stock_trades() if t["dt"] >= pd.Timestamp(a.start)]
    both = C + S
    t0 = min(t["dt"] for t in both); t1 = max(t["dt"] for t in both)
    yrs = (t1 - t0).days / 365.25

    print("=" * 100)
    print(f"  코인 + 미국주식 결합 — {a.start} 이후 {yrs:.1f}년")
    print(f"  코인 신호 {len(C):,}건 · 주식 신호 {len(S):,}건")
    print(f"  코인 비용 왕복 {RT}%+펀딩 · 주식 왕복 {STOCK_RT}% · 청산 ATR×2 · 차단기 -25%")
    print("=" * 100)
    print(f"  {'구성':24s}{'배율(코인/주식)':>16s}{'거래':>7s}{'승률':>7s}"
          f"{'최종':>9s}{'연복리':>8s}{'낙폭':>7s}{'장중':>7s}")
    print("  " + "-" * 88)
    rows = []
    for name, T, lc, ls in (("코인만",       C,    1, 0), ("코인만",       C,    2, 0),
                            ("코인만",       C,    3, 0),
                            ("주식만",       S,    0, 1), ("주식만",       S,    0, 2),
                            ("코인+주식",    both, 1, 1), ("코인+주식",    both, 2, 1),
                            ("코인+주식",    both, 2, 2), ("코인+주식",    both, 3, 2),
                            ("코인+주식",    both, 3, 3)):
        if not T: continue
        r = sim_mixed(T, 2.0, max(lc,1), max(ls,1), 0.033, 1.0)
        if r["bust"]:
            print(f"  {name:24s}{f'{lc}/{ls}':>16s}  파산"); continue
        cagr = (r["final"]**(1/yrs)-1)*100
        rows.append({"name": name, "lc": lc, "ls": ls, "final": r["final"],
                     "cagr": cagr, "mdd": r["mdd"], "low": r["mdd_low"]})
        print(f"  {name:24s}{f'{lc}배/{ls}배':>16s}{r['n']:>7,}{r['wr']:>6.1f}%"
              f"{r['final']:>8.1f}배{cagr:>7.0f}%{r['mdd']*100:>6.1f}%{r['mdd_low']*100:>6.1f}%")

    d = pd.DataFrame(rows)
    print(f"\n{'='*100}")
    print("  같은 낙폭 예산에서 누가 더 버는가 — 이게 분산의 가치다")
    print("=" * 100)
    for cap in (0.35, 0.50, 0.65):
        s = d[d.mdd <= cap]
        if s.empty: continue
        x = s.loc[s.cagr.idxmax()]
        t100 = np.log(100)/np.log(1+x.cagr/100) if x.cagr > 0 else 999
        print(f"  낙폭 {cap*100:.0f}% 이내 최고: {x['name']} ({x.lc}배/{x.ls}배)  "
              f"연복리 {x.cagr:.0f}%  →  100배까지 {t100:.1f}년")


if __name__ == "__main__":
    main()
