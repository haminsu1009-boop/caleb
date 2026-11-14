"""
ml/exit_rules.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
조기 청산이 도움이 되는가 — 음봉에서 나가야 하나 버텨야 하나

현재 규칙은 무조건 10봉 보유다. 가격이 뭘 하든 안 본다.
직관적으로는 "음봉 나오면 손절하고 나가는 게 안전"할 것 같지만,
이 규칙의 통계는 정반대를 가리킨다.

    보유 10봉 중 음봉 개수 중앙값 5개 — 절반은 음봉이다
    진입 직후 첫 봉이 음봉인 경우 41%
    보유 중 한 번이라도 마이너스였던 거래 73%
      └ 그중 53%(홀드아웃 70%)가 결국 수익으로 끝난다

즉 이 전략의 수익은 "흔들리는 걸 견디는 대가"로 나온다. 급락 직후
반등을 먹는 규칙이라 반등 전에 한 번 더 흔드는 것이 정상 경로다.

여기서는 여러 조기청산 규칙을 같은 거래 집합에 적용해 비교한다.
모두 미래를 안 쓰고 봉 순서대로만 판단한다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ml.edge_scan_all import load_all, wilson_lo
from ml.majors_only import MAJORS

HOLD, THR = 10, -12.26
COST = 0.2 + 0.05          # 왕복 수수료 + 펀딩
TRAIN_END = "2024-01-01"


def collect():
    """거래별로 보유 구간의 봉 경로를 통째로 보관한다"""
    raw = load_all("4h"); raw = raw[raw["symbol"].isin(MAJORS)]
    out = []
    for sym, g in raw.groupby("symbol", sort=False):
        g = g.sort_values("datetime").reset_index(drop=True)
        c = g["close"].astype(float); o = g["open"].astype(float)
        h = g["high"].astype(float); l = g["low"].astype(float)
        vs = (c / c.rolling(20).mean() - 1) * 100
        lock = -10**9
        for i in np.where(vs <= THR)[0]:
            if i <= lock or i + 1 + HOLD >= len(g):
                continue
            lock = i + HOLD
            e = o.iloc[i + 1]
            sl = slice(i + 1, i + 1 + HOLD)
            out.append({
                "symbol": sym, "dt": g.loc[i, "datetime"], "entry": e,
                "o": o.iloc[sl].values, "h": h.iloc[sl].values,
                "l": l.iloc[sl].values, "c": c.iloc[sl].values,
                "exit_open": o.iloc[i + 1 + HOLD],
            })
    return out


# ── 청산 규칙들. 각각 (청산가, 몇 봉째) 를 돌려준다 ──────────────────
def rule_hold(t):
    return t["exit_open"], HOLD

def rule_first_red(t):
    for k in range(HOLD):
        if t["c"][k] < t["o"][k]:
            return t["c"][k], k + 1
    return t["exit_open"], HOLD

def rule_two_red(t):
    run = 0
    for k in range(HOLD):
        run = run + 1 if t["c"][k] < t["o"][k] else 0
        if run >= 2:
            return t["c"][k], k + 1
    return t["exit_open"], HOLD

def rule_neg_after(n):
    def f(t):
        for k in range(n - 1, HOLD):
            if t["c"][k] < t["entry"]:
                return t["c"][k], k + 1
        return t["exit_open"], HOLD
    return f

def rule_trailing(pct):
    def f(t):
        peak = t["entry"]
        for k in range(HOLD):
            peak = max(peak, t["h"][k])
            if t["l"][k] <= peak * (1 - pct / 100):
                return peak * (1 - pct / 100), k + 1
        return t["exit_open"], HOLD
    return f

def rule_take_profit(pct):
    def f(t):
        tgt = t["entry"] * (1 + pct / 100)
        for k in range(HOLD):
            if t["h"][k] >= tgt:
                return tgt, k + 1
        return t["exit_open"], HOLD
    return f

def rule_stop(pct):
    def f(t):
        s = t["entry"] * (1 + pct / 100)
        for k in range(HOLD):
            if t["l"][k] <= s:
                return s, k + 1
        return t["exit_open"], HOLD
    return f


RULES = [
    ("10봉 보유 (현재 규칙)",     rule_hold),
    ("첫 음봉에서 청산",          rule_first_red),
    ("음봉 2연속이면 청산",       rule_two_red),
    ("3봉째 마이너스면 청산",     rule_neg_after(3)),
    ("5봉째 마이너스면 청산",     rule_neg_after(5)),
    ("고점대비 -5% 추격손절",     rule_trailing(5)),
    ("고점대비 -10% 추격손절",    rule_trailing(10)),
    ("+5% 목표 도달 시 익절",     rule_take_profit(5)),
    ("+10% 목표 도달 시 익절",    rule_take_profit(10)),
    ("-8% 손절",                 rule_stop(-8)),
    ("-15% 손절",                rule_stop(-15)),
]


def main():
    ts = collect()
    ho = [t for t in ts if t["dt"] >= pd.Timestamp(TRAIN_END)]
    print("=" * 96)
    print(f"  청산 규칙 비교 — 메이저 12종, 4h, 진입조건 동일 ({len(ts)}거래)")
    print(f"  비용 {COST}% 차감 · 보유기간이 짧아지면 펀딩도 줄지만 보수적으로 동일 적용")
    print("=" * 96)
    for label, data in (("전체 2017~2026", ts), ("홀드아웃 2024~2026", ho)):
        print(f"\n  [{label}]  {len(data)}거래")
        print(f"    {'청산 규칙':26s}{'승률':>8s}{'거래당':>9s}{'총수익':>10s}"
              f"{'평균보유':>9s}{'최악':>8s}")
        print("    " + "-" * 72)
        base = None
        for name, fn in RULES:
            rets, bars = [], []
            for t in data:
                px, k = fn(t)
                rets.append((px / t["entry"] - 1) * 100 - COST)
                bars.append(k)
            r = np.array(rets)
            if base is None:
                base = r.sum()
            mark = "  ← 기준" if name.startswith("10봉") else (
                   "  ✅" if r.sum() > base else "")
            print(f"    {name:26s}{(r>0).mean()*100:>7.1f}%{r.mean():>+8.2f}%"
                  f"{r.sum():>+9.0f}%{np.mean(bars):>8.1f}봉{r.min():>+7.1f}%{mark}")


if __name__ == "__main__":
    main()
