"""
ml/btc_exit_search.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
청산 방법 전수 탐색 — 고정 봉수가 남기고 나오는 것을 회수한다

btc_all_timeframes.py가 남긴 단서: 4시간봉 규칙은 거래당 +0.66%를
버는데 보유 중 최고점 중앙값은 +3.56%였다. 잡은 움직임의 1/5만 먹고
나온다는 뜻이다. 진입은 그대로 두고 청산만 바꿔서 그 차이를 얼마나
회수할 수 있는지 본다.

시험하는 청산 (모두 봉 순서대로만 판단, 미래참조 없음):
    고정        N봉 뒤 시가
    목표        +X% 도달 시 (고가 기준)
    ATR 목표    진입 시 ATR의 k배 도달 시
    추격손절    고점 대비 X% 하락 시
    ATR 추격    고점 대비 ATR의 k배 하락 시
    지표 청산   RSI/이격도가 특정선 회복 시
    복합        목표 + 손절 동시, 먼저 닿는 쪽

앞의 exit_rules.py와 다른 점:
    그쪽은 46종 4시간봉 한 규칙만 봤다. 여기서는 BTC의 각 시간대별
    최고 규칙에 대해 각각 최적 청산을 찾고, 학습구간에서 고른 뒤
    홀드아웃으로 확인한다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ml.btc_all_timeframes import load, features, ROUND_TRIP, TRAIN_FRAC

# 시간대별 최고 진입 규칙 (btc_all_timeframes.py 결과)
ENTRIES = [
    ("5m",  "dd_from_high", "<=", -4.867, 20),
    ("15m", "dd_from_high", "<=", -5.661, 20),
    ("30m", "vs_ma200",     "<=", -7.102, 20),
    ("1h",  "vs_ma50",      "<=", -4.873, 10),
    ("2h",  "atr_pct",      ">=",  2.013, 20),
    ("4h",  "vs_ma200",     "<=", -8.08,  20),
    ("6h",  "adx",          "<=", 18.52,  20),
]
MAXBARS = 60          # 어떤 청산이든 이 봉수를 넘기면 강제 종료


def build(tf, feat, op, thr, hold):
    """진입 시점과 이후 경로를 통째로 뽑는다"""
    g = load(tf); f = features(g)
    o = g["open"].astype(float).values
    h = g["high"].astype(float).values
    l = g["low"].astype(float).values
    c = g["close"].astype(float).values
    atr = (f["atr_pct"].values / 100.0) * c            # ATR 절대값
    rsi = f["rsi14"].values
    vm20 = f["vs_ma20"].values
    s = f[feat].values
    m = (s <= thr) if op == "<=" else (s >= thr)

    trades, lock = [], -10**9
    n = len(g)
    for i in np.where(m)[0]:
        if i <= lock or i + 1 + MAXBARS >= n:
            continue
        lock = i + hold
        e = o[i+1]
        sl = slice(i+1, i+1+MAXBARS)
        trades.append({
            "i": i, "dt": g["datetime"].iloc[i], "entry": e,
            "atr": atr[i] if np.isfinite(atr[i]) else np.nan,
            "o": o[sl], "h": h[sl], "l": l[sl], "c": c[sl],
            "rsi": rsi[i+1:i+1+MAXBARS], "vm20": vm20[i+1:i+1+MAXBARS],
        })
    return trades


# ── 청산 규칙들: (수익률%, 보유봉수) 반환 ───────────────────────
def ex_fixed(t, N):
    N = min(N, len(t["o"])-1)
    return (t["o"][N]/t["entry"]-1)*100, N

def ex_target(t, pct, cap):
    tgt = t["entry"]*(1+pct/100)
    for k in range(min(cap, len(t["h"]))):
        if t["h"][k] >= tgt:
            return pct, k+1
    return ex_fixed(t, cap)

def ex_atr_target(t, k_atr, cap):
    if not np.isfinite(t["atr"]) or t["atr"] <= 0:
        return ex_fixed(t, cap)
    tgt = t["entry"] + k_atr*t["atr"]
    for k in range(min(cap, len(t["h"]))):
        if t["h"][k] >= tgt:
            return (tgt/t["entry"]-1)*100, k+1
    return ex_fixed(t, cap)

def ex_trail(t, pct, cap):
    peak = t["entry"]
    for k in range(min(cap, len(t["h"]))):
        peak = max(peak, t["h"][k])
        stop = peak*(1-pct/100)
        if t["l"][k] <= stop:
            return (stop/t["entry"]-1)*100, k+1
    return ex_fixed(t, cap)

def ex_atr_trail(t, k_atr, cap):
    if not np.isfinite(t["atr"]) or t["atr"] <= 0:
        return ex_fixed(t, cap)
    peak = t["entry"]
    for k in range(min(cap, len(t["h"]))):
        peak = max(peak, t["h"][k])
        stop = peak - k_atr*t["atr"]
        if t["l"][k] <= stop:
            return (stop/t["entry"]-1)*100, k+1
    return ex_fixed(t, cap)

def ex_rsi(t, lvl, cap):
    for k in range(min(cap, len(t["rsi"]))):
        if np.isfinite(t["rsi"][k]) and t["rsi"][k] >= lvl:
            return (t["c"][k]/t["entry"]-1)*100, k+1
    return ex_fixed(t, cap)

def ex_ma(t, lvl, cap):
    for k in range(min(cap, len(t["vm20"]))):
        if np.isfinite(t["vm20"][k]) and t["vm20"][k] >= lvl:
            return (t["c"][k]/t["entry"]-1)*100, k+1
    return ex_fixed(t, cap)

def ex_combo(t, tgt_pct, stop_pct, cap):
    tgt = t["entry"]*(1+tgt_pct/100); stp = t["entry"]*(1+stop_pct/100)
    for k in range(min(cap, len(t["h"]))):
        hit_s = t["l"][k] <= stp
        hit_t = t["h"][k] >= tgt
        if hit_s:                       # 같은 봉이면 손절 우선(보수적)
            return stop_pct, k+1
        if hit_t:
            return tgt_pct, k+1
    return ex_fixed(t, cap)


def rules_for(hold):
    R = [(f"고정 {hold}봉 (현재)", lambda t: ex_fixed(t, hold))]
    for N in (hold//2, hold*2, hold*3):
        if N >= 1 and N != hold and N <= MAXBARS:
            R.append((f"고정 {N}봉", (lambda N: lambda t: ex_fixed(t, N))(N)))
    for p in (0.5, 1, 2, 3, 5, 8):
        R.append((f"목표 +{p}%", (lambda p: lambda t: ex_target(t, p, MAXBARS))(p)))
    for k in (1, 1.5, 2, 3, 4):
        R.append((f"목표 ATR×{k}", (lambda k: lambda t: ex_atr_target(t, k, MAXBARS))(k)))
    for p in (1, 2, 3, 5, 8):
        R.append((f"추격손절 -{p}%", (lambda p: lambda t: ex_trail(t, p, MAXBARS))(p)))
    for k in (1, 1.5, 2, 3):
        R.append((f"추격 ATR×{k}", (lambda k: lambda t: ex_atr_trail(t, k, MAXBARS))(k)))
    for lv in (50, 60, 70):
        R.append((f"RSI {lv} 회복", (lambda lv: lambda t: ex_rsi(t, lv, MAXBARS))(lv)))
    for lv in (0, 2, 5):
        R.append((f"20선 +{lv}% 회복", (lambda lv: lambda t: ex_ma(t, lv, MAXBARS))(lv)))
    for tg, st in ((3,-2),(5,-3),(5,-5),(8,-4),(10,-5),(2,-1)):
        R.append((f"목표+{tg}%/손절{st}%",
                  (lambda tg,st: lambda t: ex_combo(t, tg, st, MAXBARS))(tg,st)))
    return R


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", nargs="*", default=[e[0] for e in ENTRIES])
    ap.add_argument("--top", type=int, default=8)
    a = ap.parse_args()

    print("=" * 100)
    print(f"  비트코인 청산 방법 전수 탐색 — 진입은 고정, 청산만 교체")
    print(f"  비용 왕복 {ROUND_TRIP}% · 최대 보유 {MAXBARS}봉 · 학습 앞 70%에서 고르고 홀드아웃 확인")
    print("=" * 100)

    for tf, feat, op, thr, hold in ENTRIES:
        if tf not in a.tf:
            continue
        T = build(tf, feat, op, thr, hold)
        if len(T) < 80:
            print(f"\n  [{tf}] 거래 부족 ({len(T)})"); continue
        split = int(len(T) * TRAIN_FRAC)
        print(f"\n{'─'*100}")
        print(f"  [{tf}]  {feat} {op} {thr}  ·  거래 {len(T)}건 (학습 {split} / 홀드아웃 {len(T)-split})")
        print(f"{'─'*100}")
        rows = []
        for name, fn in rules_for(hold):
            rets, bars = [], []
            for t in T:
                r, k = fn(t)
                rets.append(r - ROUND_TRIP); bars.append(k)
            r = np.array(rets); b = np.array(bars)
            tr, ho = r[:split], r[split:]
            rows.append({"name": name, "tr_mean": tr.mean(), "tr_sum": tr.sum(),
                         "ho_n": len(ho), "ho_wr": (ho>0).mean()*100,
                         "ho_mean": ho.mean(), "ho_sum": ho.sum(),
                         "bars": b.mean()})
        df = pd.DataFrame(rows)
        base = df[df.name.str.contains("현재")].iloc[0]
        # 학습구간 총수익 순으로 고르고, 홀드아웃은 확인만
        df = df.sort_values("tr_sum", ascending=False)
        print(f"    {'청산 방법':22s}{'학습 거래당':>12s}{'홀드 승률':>10s}"
              f"{'홀드 거래당':>12s}{'홀드 누적':>11s}{'평균보유':>9s}")
        print("    " + "-" * 78)
        for _, x in df.head(a.top).iterrows():
            mark = " ← 현재" if "현재" in x["name"] else (
                   "  ✅" if x.ho_sum > base.ho_sum else "")
            print(f"    {x['name']:22s}{x.tr_mean:>+11.3f}%{x.ho_wr:>9.1f}%"
                  f"{x.ho_mean:>+11.3f}%{x.ho_sum:>+10.1f}%{x.bars:>8.1f}봉{mark}")
        print(f"    {'─'*78}")
        print(f"    {base['name']:22s}{base.tr_mean:>+11.3f}%{base.ho_wr:>9.1f}%"
              f"{base.ho_mean:>+11.3f}%{base.ho_sum:>+10.1f}%{base.bars:>8.1f}봉  ← 기준")


if __name__ == "__main__":
    main()
