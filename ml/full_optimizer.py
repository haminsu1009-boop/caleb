"""
ml/full_optimizer.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
전체 최적화 — 승률·수익·안정성을 한 화면에서 비교한다

세 목표는 같은 방향이 아니다. 이 저장소에서 이미 나온 사례:
    +5% 익절은 승률 80.4%로 1등이지만 총수익은 10봉 보유의 2/3다.
    3배는 수익이 최고지만 낙폭 76%로 실제로는 못 버틴다.
그래서 하나를 고르는 게 아니라 셋을 나란히 놓고 고르게 한다.

여기서 새로 반영하는 것:
    ATR 배수 목표 청산 (btc_exit_search.py에서 7개 시간대 28/35로 검증)
    이 청산은 평균 43봉을 보유한다. 고정 10봉의 4배다. 포지션 자리를
    4배 오래 차지하므로 동시보유 한도에 걸려 거래 수가 줄어든다.
    거래당 수익이 70% 늘어도 거래 수가 1/4이 되면 손해다.
    포트폴리오로 굴려봐야 알 수 있다.

시뮬레이션 규칙:
    · 시간순 진행, 신호가 나면 자리가 있을 때만 진입
    · 종목당 1포지션, 총노출 상한 준수
    · 격리마진 — 청산되면 그 포지션 증거금만 잃는다
    · 청산/손절은 봉 안 고가·저가로 판정
    · 비용 왕복 0.2% + 펀딩 0.01%/8h
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ml.edge_scan_all import load_all
from ml.majors_only import MAJORS

RT = 0.2            # % 왕복
F8 = 0.01           # % per 8h
MAXB = 90           # 청산 규칙이 안 걸리면 강제 종료
TRAIN_END = pd.Timestamp("2024-01-01")


def build(thr=-12.26, symbols=None, interval="4h"):
    raw = load_all(interval)
    raw = raw[raw["symbol"].isin(symbols or MAJORS)]
    out = []
    for sym, g in raw.groupby("symbol", sort=False):
        g = g.sort_values("datetime").reset_index(drop=True)
        o = g["open"].astype(float).values; h = g["high"].astype(float).values
        l = g["low"].astype(float).values;  c = g["close"].astype(float).values
        vs = (c / pd.Series(c).rolling(20).mean().values - 1) * 100
        pc = np.roll(c, 1)
        trg = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
        atr = pd.Series(trg).rolling(14).mean().values
        for i in np.where(vs <= thr)[0]:
            if i + 1 + MAXB >= len(g) or not np.isfinite(atr[i]) or atr[i] <= 0:
                continue
            out.append({"sym": sym, "i": i, "dt": g["datetime"].iloc[i],
                        "e": o[i+1], "atr": atr[i], "vs": vs[i],
                        "dts": g["datetime"].values[i+1:i+1+MAXB],
                        "o": o[i+1:i+1+MAXB], "h": h[i+1:i+1+MAXB],
                        "l": l[i+1:i+1+MAXB]})
    return sorted(out, key=lambda t: t["dt"])


def resolve(t, exit_kind, param, stop_pct, liq_pct=None):
    """청산가·보유봉수·강제청산여부.

    강제청산은 반드시 **봉 안 저가**로 판정해야 한다. 최종 수익률로만
    보면, 저가가 청산선을 뚫었다가 되돌아온 거래를 이익으로 세게 되고
    고배율일수록 그 착시가 커진다(30배에서 10^46배가 나온 원인).
    손절선과 청산선 중 더 가까운 쪽이 먼저 걸린다.
    """
    e = t["e"]
    lines = [x for x in (stop_pct, liq_pct) if x is not None]
    hard = max(lines) if lines else None          # 덜 깊은 쪽이 먼저 닿는다
    stop = e * (1 + hard/100) if hard is not None else None
    stop_pct = hard
    if exit_kind == "fixed":
        N = min(int(param), len(t["o"]) - 1)
        for k in range(N):
            if stop is not None and t["l"][k] <= stop:
                return stop_pct, k+1, (liq_pct is not None and stop_pct == liq_pct)
        return (t["o"][N]/e - 1)*100, N, False
    tgt = e + param * t["atr"]
    for k in range(len(t["h"])):
        if stop is not None and t["l"][k] <= stop:
            return stop_pct, k+1, (liq_pct is not None and stop_pct == liq_pct)
        if t["h"][k] >= tgt:
            return (tgt/e - 1)*100, k+1, False
    N = len(t["o"]) - 1
    return (t["o"][N]/e - 1)*100, N, False


def simulate(trades, exit_kind, param, lev, per_trade, max_gross,
             stop_pct=-40.0, bar_h=4.0):
    eq, peak, mdd = 1.0, 1.0, 0.0
    liq_line = -100.0/lev + 0.5
    open_pos = []          # (청산시각, 명목, 심볼)
    taken = skipped = liqs = 0
    wins = 0
    rets = []
    for t in trades:
        now = t["dt"]
        open_pos = [p for p in open_pos if p[0] > now]
        if any(p[2] == t["sym"] for p in open_pos):
            continue                       # 종목당 1포지션
        gross = sum(p[1] for p in open_pos)
        margin = eq * per_trade
        notional = margin * lev
        if gross + notional > eq * max_gross * lev:
            skipped += 1; continue
        r, k, was_liq = resolve(t, exit_kind, param, stop_pct, liq_line)
        if was_liq:
            liqs += 1
        net = r - RT - F8 * (k * bar_h / 8.0)
        pl = max(margin * lev * net / 100, -margin)
        eq += pl
        if eq <= 0:
            return {"final": 0.0, "mdd": 1.0, "n": taken, "skip": skipped, "wr": 0.0,
                    "liq": liqs, "cagr": -100.0, "yrs": 0.0, "mean": 0.0}
        peak = max(peak, eq); mdd = max(mdd, 1 - eq/peak)
        taken += 1; wins += net > 0; rets.append(net)
        exit_dt = t["dts"][min(k, len(t["dts"])-1)]
        open_pos.append((exit_dt, notional, t["sym"]))
    yrs = (trades[-1]["dt"] - trades[0]["dt"]).days / 365.25
    return {"final": eq, "mdd": mdd, "n": taken, "skip": skipped,
            "wr": wins/max(taken,1)*100, "liq": liqs,
            "cagr": (eq**(1/yrs)-1)*100 if eq > 0 and yrs > 0 else -100,
            "yrs": yrs, "mean": float(np.mean(rets)) if rets else 0.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout-only", action="store_true")
    a = ap.parse_args()

    T = build()
    if a.holdout_only:
        T = [t for t in T if t["dt"] >= TRAIN_END]
    print("=" * 104)
    print(f"  전체 최적화 — 메이저 12종 · 4h · 20MA대비 -12.26% · 신호 {len(T)}건")
    print(f"  구간 {str(T[0]['dt'])[:10]} ~ {str(T[-1]['dt'])[:10]}")
    print(f"  비용 왕복 {RT}% + 펀딩 {F8}%/8h · 격리마진 · 손절 -40%")
    print("=" * 104)

    EXITS = [("fixed", 10, "고정 10봉 (현재)"), ("fixed", 20, "고정 20봉"),
             ("atr", 2.0, "목표 ATR×2"), ("atr", 3.0, "목표 ATR×3"),
             ("atr", 4.0, "목표 ATR×4")]
    SIZES = [(0.15, 1.0, "6종목"), (0.25, 0.5, "2종목"), (0.125, 1.0, "8종목")]

    print(f"\n  {'청산':16s}{'동시':7s}{'배율':5s}{'거래':>6s}{'승률':>7s}"
          f"{'거래당':>8s}{'최종':>10s}{'연복리':>8s}{'낙폭':>8s}{'청산':>5s}")
    print("  " + "-" * 96)
    rows = []
    for kind, prm, elab in EXITS:
        for pt, mg, slab in SIZES:
            for lev in (1, 2, 3):
                r = simulate(T, kind, prm, lev, pt, mg)
                rows.append({"exit": elab, "size": slab, "lev": lev, **r})
                print(f"  {elab:16s}{slab:7s}{lev:>4.0f}x{r['n']:>6,}{r['wr']:>6.1f}%"
                      f"{r['mean']:>+7.2f}%{r['final']:>9,.1f}배{r['cagr']:>7.0f}%"
                      f"{r['mdd']*100:>7.1f}%{r['liq']:>5}")
        print()
    d = pd.DataFrame(rows)
    d.to_csv("ml/saved_models/full_opt.csv", index=False)

    print("=" * 104)
    print("  목표별 최선 — 세 목표는 서로 다른 답을 가리킨다")
    print("=" * 104)
    for goal, key, cond in (("최고 승률 (원금 보전 중)", "wr", d["final"] > 1),
                            ("최고 수익", "final", d["final"] > 0),
                            ("최고 안정성 (낙폭 30% 이내 중 최고수익)", "final", d["mdd"] <= 0.30),
                            ("낙폭 45% 이내 중 최고수익", "final", d["mdd"] <= 0.45)):
        s = d[cond]
        if s.empty: print(f"  {goal:36s} 해당 없음"); continue
        x = s.loc[s[key].idxmax()]
        print(f"  {goal:36s} {x['exit']} · {x['size']} · {x.lev:.0f}배  →  "
              f"승률 {x.wr:.1f}% · {x['final']:,.1f}배 · 연복리 {x.cagr:.0f}% · 낙폭 {x.mdd*100:.1f}%")


if __name__ == "__main__":
    main()
