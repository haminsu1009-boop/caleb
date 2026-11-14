"""
ml/leverage_limit.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
레버리지 상한은 무엇이 결정하는가 — 롱온리 vs 롱숏, 1x ~ 30x

"규칙이 충분히 좋으면 10배도 30배도 된다"가 성립하는지 확인한다.
결론을 미리 정하지 않고, 세 가지를 각각 계산해 근거를 남긴다.

  1. 청산 물리학
     레버리지 L에서 증거금은 자본의 1/L이다. 즉 한 봉에서 -1/L 만큼
     역행하면 청산이다. 30x면 -3.33%, 10x면 -10%.
     전략 수익률 시계열에서 그런 봉이 실제로 몇 번 있었는지 센다.
     이건 승률이나 기대값과 무관한 순수 사건 빈도다.

  2. 켈리 최적 레버리지
     연속 시간 켈리: f* = mu / sigma^2  (mu, sigma는 무레버리지 수익률)
     이론상 최적점이며, f*를 넘으면 기대 로그성장률이 오히려 감소한다.
     2*f* 를 넘으면 기대 성장률이 음수가 된다. 이게 "얼마나 좋은
     규칙이면 몇 배가 정당한가"에 대한 정량적 답이다.

  3. 실제 시뮬레이션
     1x부터 30x까지 청산을 반영해 돌린다.

롱온리와 롱숏을 나란히 계산한다. 롱숏은 하락장에서도 포지션을 잡으므로
노출이 높고, 그만큼 청산 확률도 달라진다.

사용법:
    python ml/leverage_limit.py --interval 4h
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ml.validate_extended import load_sym, load_funding, available_symbols

FEE, SLIP = 0.0005, 0.0005
FAST_DAYS, SLOW_DAYS = 3, 33
BPD = {"1d": 1, "4h": 6, "1h": 24}
BARS_YEAR = {"1d": 365, "4h": 365*6, "1h": 365*24}


def signals(df, interval, mode):
    d = BPD[interval]
    f = max(2, FAST_DAYS*d); s = max(3, SLOW_DAYS*d)
    c = df["close"]
    fa = c.rolling(f).mean().shift(1); sl = c.rolling(s).mean().shift(1)
    if mode == "long":
        p = np.where(fa > sl, 1.0, 0.0)
    else:                                    # long/short
        p = np.where(fa > sl, 1.0, -1.0)
    p[np.isnan(fa.values) | np.isnan(sl.values)] = 0.0
    return p


def sym_returns(df, pos, funding=None):
    c = df["close"].values
    r = np.zeros(len(c)); r[1:] = c[1:]/c[:-1] - 1.0
    held = np.roll(pos, 1); held[0] = 0.0
    turn = np.abs(np.diff(np.concatenate([[0.0], pos])))
    sr = held*r - turn*(FEE+SLIP)
    if funding is not None and len(funding):
        idx = pd.DatetimeIndex(df["datetime"])
        acc = np.zeros(len(df))
        loc = np.searchsorted(idx.values, funding.index.values, side="right") - 1
        ok = (loc >= 0) & (loc < len(df))
        np.add.at(acc, loc[ok], funding.values[ok])
        sr = sr - held*acc          # 롱이면 지불, 숏이면 수취
    return sr


def sim(r1x, lev):
    """청산 반영 — 한 봉 손실이 증거금(1/lev)을 넘으면 전액 손실"""
    cap = 1.0; curve = np.empty(len(r1x)); liq = 0
    thr = -1.0/lev
    for i, x in enumerate(r1x):
        xl = x*lev
        if cap > 0 and x <= thr:
            cap = 0.0; liq += 1
        else:
            cap = max(cap*(1.0+xl), 0.0)
        curve[i] = cap
    if cap <= 0:
        return -100.0, -100.0, liq
    peak = np.maximum.accumulate(curve)
    return (cap-1)*100, (curve/peak - 1).min()*100, liq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="4h")
    a = ap.parse_args()
    iv = a.interval
    by = BARS_YEAR[iv]

    syms = available_symbols(iv)
    data, fund = {}, {}
    need = SLOW_DAYS*BPD[iv] + 120
    for s in syms:
        df = load_sym(s, iv)
        if len(df) >= need:
            data[s] = df; fund[s] = load_funding(s)

    idx = pd.DatetimeIndex(sorted(set().union(*[set(d["datetime"]) for d in data.values()])))

    print("=" * 92)
    print(f"  레버리지 상한 분석 — {iv}, {len(data)}종 동일가중 분산, 펀딩비 반영")
    print("=" * 92)

    ports = {}
    for mode, label in [("long", "롱온리"), ("longshort", "롱숏")]:
        R = pd.DataFrame(index=idx)
        for s in data:
            sr = sym_returns(data[s], signals(data[s], iv, mode), fund.get(s))
            R[s] = pd.Series(sr, index=pd.DatetimeIndex(data[s]["datetime"])).reindex(idx)
        ports[label] = R.mean(axis=1, skipna=True).fillna(0.0).values

    # ── 1. 청산 물리학 ──────────────────────────────────
    print("\n[1] 청산 물리학 — 레버리지 L은 한 봉 -1/L 역행에서 청산된다")
    print(f"    (분산 포트폴리오 기준, 전체 {len(idx):,}봉)")
    print(f"\n  {'레버':>6s}{'청산 임계':>11s}", end="")
    for label in ports: print(f"{label+' 발생':>16s}", end="")
    print()
    print("  " + "-" * 52)
    for lev in [2, 3, 5, 10, 20, 30]:
        thr = -1.0/lev
        line = f"  {lev:>5d}x{thr*100:>10.2f}%"
        for label, p in ports.items():
            n = int((p <= thr).sum())
            line += f"{n:>10d}회 {'💀' if n else '  '}"
        print(line)

    # ── 2. 켈리 최적 레버리지 ───────────────────────────
    print("\n[2] 켈리 최적 레버리지 — f* = mu / sigma^2 (무레버리지 수익률 기준)")
    print("    f*를 넘으면 기대 성장률이 감소하고, 2*f*를 넘으면 음수가 된다")
    print(f"\n  {'전략':>10s}{'연수익률':>11s}{'연변동성':>11s}{'Sharpe':>9s}"
          f"{'켈리 f*':>10s}{'2f*(성장0)':>12s}")
    print("  " + "-" * 64)
    kelly = {}
    for label, p in ports.items():
        mu = p.mean()*by
        sd = p.std()*np.sqrt(by)
        f = mu/(sd**2) if sd > 0 else 0.0
        kelly[label] = f
        print(f"  {label:>10s}{mu*100:>10.1f}%{sd*100:>10.1f}%{mu/sd if sd>0 else 0:>9.2f}"
              f"{f:>9.2f}x{2*f:>11.2f}x")

    # ── 3. 실제 시뮬레이션 ──────────────────────────────
    print("\n[3] 실제 시뮬레이션 — 청산 반영")
    print(f"\n  {'레버':>6s}", end="")
    for label in ports: print(f"{label+' 수익률':>18s}{'MDD':>9s}", end="")
    print()
    print("  " + "-" * 60)
    for lev in [1, 2, 3, 5, 10, 20, 30]:
        line = f"  {lev:>5d}x"
        for label, p in ports.items():
            t, m, liq = sim(p, lev)
            cell = "청산💀" if liq else f"{t:>15,.0f}%"
            line += f"{cell:>18s}{m:>8.1f}%"
        print(line)

    print(f"\n{'='*92}")
    print("  해석")
    print("=" * 92)
    for label in ports:
        f = kelly[label]
        print(f"    {label}: 켈리 최적 {f:.1f}x — 이 이상은 기대 성장률이 떨어지고, "
              f"{2*f:.1f}x 이상은 마이너스")
    print("    10x/30x가 되려면 켈리 f*가 그만큼 커야 하고, f* = mu/sigma^2 이므로")
    print("    변동성이 지금보다 훨씬 낮거나 수익률이 훨씬 높은 규칙이 필요하다.")


if __name__ == "__main__":
    main()
