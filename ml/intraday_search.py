"""
ml/intraday_search.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4h / 1h 체계적 파라미터 탐색 + 워크포워드 검증

timeframe_rules.py에서 30분봉 이하는 왕복비용이 봉 변동폭에 근접·초과해
손익분기 승률이 비현실적이라는 것이 확인됐다. 그래서 탐색 대상은
4h와 1h로 한정한다.

탐색 방식:
    전략군 × 파라미터 격자를 6개 심볼 × 2개 타임프레임에 전부 돌린다.
    최고 성적 한 칸만 보고하면 그게 우연인지 알 수 없으므로,
    아래 세 가지를 함께 요구한다.

      1. 워크포워드  — 3개 구간(2018-2021 / 2021-2023 / 2023-2026)으로
                       나눠 각 구간에서 독립적으로 성과를 낸다.
      2. 구간 일관성 — 3구간 중 2구간 이상에서 양의 수익.
      3. 심볼 일관성 — 6심볼 중 4심볼 이상에서 양의 수익.

    이 셋을 모두 통과한 조합만 "생존"으로 본다. 한 심볼·한 구간에서만
    좋은 것은 과적합으로 간주해 버린다.

사용법:
    python ml/intraday_search.py
    python ml/intraday_search.py --interval 4h
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings, itertools
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ml.trend_backtest import load, FEE, SLIP

SYMS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]
BARS_PER_YEAR = {"4h": 365*6, "1h": 365*24}
BARS_PER_DAY  = {"4h": 6, "1h": 24}

SEGMENTS = [("2018-01-01", "2021-01-01"),
            ("2021-01-01", "2023-06-01"),
            ("2023-06-01", "2026-12-31")]


# ══════════════════════════════════════════════════════════════
# 전략군
# ══════════════════════════════════════════════════════════════

def p_donchian(df, n_e, n_x):
    h, l, c = df["high"], df["low"], df["close"]
    ue = h.rolling(n_e).max().shift(1).values
    de = l.rolling(n_e).min().shift(1).values
    ux = h.rolling(n_x).max().shift(1).values
    dx = l.rolling(n_x).min().shift(1).values
    cv = c.values
    p = np.zeros(len(df)); cur = 0
    for i in range(len(df)):
        if np.isnan(ue[i]) or np.isnan(de[i]) or np.isnan(ux[i]) or np.isnan(dx[i]):
            p[i] = 0; continue
        if cur == 0:
            if cv[i] > ue[i]: cur = 1
            elif cv[i] < de[i]: cur = -1
        elif cur == 1 and cv[i] < dx[i]: cur = -1 if cv[i] < de[i] else 0
        elif cur == -1 and cv[i] > ux[i]: cur = 1 if cv[i] > ue[i] else 0
        p[i] = cur
    return p


def p_ma(df, fast, slow):
    c = df["close"]
    f = c.rolling(fast).mean().shift(1); s = c.rolling(slow).mean().shift(1)
    p = np.where(f > s, 1.0, -1.0)
    p[np.isnan(f.values) | np.isnan(s.values)] = 0.0
    return p


def p_ma_long_only(df, fast, slow):
    return np.clip(p_ma(df, fast, slow), 0, 1)


def p_supertrend(df, period, mult):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h-l, np.maximum(np.abs(h-pc), np.abs(l-pc)))
    atr = pd.Series(tr).rolling(period).mean().shift(1).values
    hl2 = (h+l)/2.0
    p = np.zeros(len(df)); cur = 0; fu = fl = np.nan
    for i in range(len(df)):
        if np.isnan(atr[i]): p[i] = 0; continue
        u, d = hl2[i]+mult*atr[i], hl2[i]-mult*atr[i]
        fu = u if np.isnan(fu) else (min(u, fu) if c[i-1] <= fu else u)
        fl = d if np.isnan(fl) else (max(d, fl) if c[i-1] >= fl else d)
        if cur <= 0 and c[i] > fu: cur = 1
        elif cur >= 0 and c[i] < fl: cur = -1
        p[i] = cur
    return p


def p_breakout_atr(df, n, k):
    """N봉 고가 + k×ATR 돌파 = 롱, 반대 = 숏"""
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(n).mean().shift(1)
    hi = h.rolling(n).max().shift(1); lo = l.rolling(n).min().shift(1)
    up = (hi + k*atr).values; dn = (lo - k*atr).values
    cv = c.values
    p = np.zeros(len(df)); cur = 0
    for i in range(len(df)):
        if np.isnan(up[i]): p[i] = 0; continue
        if cv[i] > up[i]: cur = 1
        elif cv[i] < dn[i]: cur = -1
        p[i] = cur
    return p


def build_grid(interval: str):
    d = BARS_PER_DAY[interval]
    B = lambda days: max(2, int(round(days*d)))
    g = []
    for e, x in itertools.product([3, 5, 9, 15, 25], [1, 2, 3, 5]):
        if x < e:
            g.append((f"돌파({e}d/{x}d)", lambda df, a=B(e), b=B(x): p_donchian(df, a, b)))
    for f, s in itertools.product([1, 2, 3, 5, 8], [10, 20, 33, 50]):
        if f < s:
            g.append((f"MA({f}d/{s}d)", lambda df, a=B(f), b=B(s): p_ma(df, a, b)))
    for f, s in [(2, 20), (3, 33), (5, 50)]:
        g.append((f"MA롱온리({f}d/{s}d)", lambda df, a=B(f), b=B(s): p_ma_long_only(df, a, b)))
    for pr, m in itertools.product([2, 4, 7], [2.0, 3.0, 4.0]):
        g.append((f"Supertrend({pr}d,{m})", lambda df, a=B(pr), b=m: p_supertrend(df, a, b)))
    for n, k in itertools.product([3, 7, 14], [0.5, 1.0]):
        g.append((f"ATR돌파({n}d,{k})", lambda df, a=B(n), b=k: p_breakout_atr(df, a, b)))
    return g


# ══════════════════════════════════════════════════════════════
def perf(df, pos, interval, lo=None, hi=None):
    m = np.ones(len(df), dtype=bool)
    if lo is not None:
        m &= (df["datetime"] >= lo).values
    if hi is not None:
        m &= (df["datetime"] < hi).values
    if m.sum() < 200:
        return None
    c = df["close"].values[m]; p = pos[m]
    r = np.zeros(len(c)); r[1:] = c[1:]/c[:-1] - 1.0
    held = np.roll(p, 1); held[0] = 0.0
    turn = np.abs(np.diff(np.concatenate([[0.0], p])))
    sr = held*r - turn*(FEE+SLIP)
    eq = np.cumprod(1+sr)
    if eq[-1] <= 0:
        return {"total": -100.0, "sharpe": 0.0, "mdd": -100.0, "bh": (np.prod(1+r)-1)*100}
    sd = sr.std()
    return {"total": (eq[-1]-1)*100,
            "sharpe": sr.mean()/sd*np.sqrt(BARS_PER_YEAR[interval]) if sd > 0 else 0.0,
            "mdd": (eq/np.maximum.accumulate(eq)-1).min()*100,
            "bh": (np.prod(1+r)-1)*100}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intervals", nargs="*", default=["4h", "1h"])
    ap.add_argument("--out", default="ml/saved_models/intraday_search.csv")
    a = ap.parse_args()

    print("=" * 100)
    print("  4h / 1h 체계적 탐색 — 구간 2/3 + 심볼 4/6 이상 양수만 생존")
    print("=" * 100)

    rows = []
    for interval in a.intervals:
        grid = build_grid(interval)
        print(f"\n  {interval}: 전략 {len(grid)}개 × 심볼 {len(SYMS)}개 = {len(grid)*len(SYMS)}회 실행")
        data = {}
        for s in SYMS:
            try:
                data[s] = load(s, interval, 2017)
            except Exception:
                pass

        for name, fn in grid:
            per_sym, seg_pos, sym_pos = [], [0, 0, 0], 0
            for s, df in data.items():
                try:
                    pos = fn(df)
                except Exception:
                    continue
                full = perf(df, pos, interval)
                if full is None:
                    continue
                per_sym.append(full["total"])
                if full["total"] > 0:
                    sym_pos += 1
                for j, (lo, hi) in enumerate(SEGMENTS):
                    sg = perf(df, pos, interval, lo, hi)
                    if sg and sg["total"] > 0:
                        seg_pos[j] += 1
            if not per_sym:
                continue
            n_sym = len(per_sym)
            segs_ok = sum(1 for x in seg_pos if x > n_sym/2)
            rows.append({
                "interval": interval, "strategy": name,
                "평균수익%": float(np.mean(per_sym)),
                "중앙값%": float(np.median(per_sym)),
                "양수심볼": sym_pos, "총심볼": n_sym,
                "양수구간": segs_ok,
                "생존": (segs_ok >= 2 and sym_pos >= 4),
            })

    out = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    out.to_csv(a.out, index=False)

    for interval in a.intervals:
        sub = out[out.interval == interval].sort_values("중앙값%", ascending=False)
        alive = sub[sub["생존"]]
        print(f"\n{'='*100}")
        print(f"  {interval} 결과 — 전체 {len(sub)}개 중 생존 {len(alive)}개")
        print("=" * 100)
        print(f"  {'전략':22s}{'평균수익%':>12s}{'중앙값%':>11s}{'양수심볼':>10s}{'양수구간':>10s}{'생존':>7s}")
        print("  " + "-" * 74)
        for _, r in sub.head(12).iterrows():
            flag = "✅" if r["생존"] else "  "
            print(f"  {r['strategy']:22s}{r['평균수익%']:>11.1f}%{r['중앙값%']:>10.1f}%"
                  f"{r['양수심볼']:>7.0f}/{r['총심볼']:<3.0f}{r['양수구간']:>8.0f}/3{flag:>7s}")

    print(f"\n  저장: {a.out}")


if __name__ == "__main__":
    main()
