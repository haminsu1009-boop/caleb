"""
ml/leverage_longonly.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MA 롱온리에 레버리지를 걸면 어떻게 되는가 + 약세장 매수신호 포착력

지금까지 레버리지 검증은 전부 롱숏 전략 대상이었다:
  · regime_switch.py  — 롱숏 전환, 2x부터 청산
  · cycle_timing.py   — 강세롱/약세숏, 2x부터 청산
방향을 계속 뒤집는 전략은 휩쏘 왕복손실이 레버리지로 증폭돼 무너진다.

MA 롱온리는 다르다. 신호가 꺼지면 반대로 뒤집는 게 아니라 현금으로
빠진다. 왕복 횟수가 적고 하락 구간에 노출이 없으므로 레버리지 반응이
다를 수 있다. 한 번도 측정한 적이 없어 여기서 확인한다.

측정 내용:
  1. 레버리지별 성과 — 청산을 실제로 반영한다.
     일일 손실이 증거금(1/레버리지)을 넘으면 그 시점에 전액 손실 처리.
  2. 약세장 매수신호 — 사이클 약세 구간에서 이 전략이 몇 %의 시간을
     시장에 있었고, 그 진입들의 성과가 어땠는지. "약세장에서도 매수
     신호를 잡는다"는 것이 실제로 성립하는지 확인.
  3. 종목 분산 효과 — N종에 나눠 담으면 개별 종목 MDD가 상쇄되는지.
     분산이 MDD를 낮추면 그만큼 레버리지 여력이 생긴다.

사용법:
    python ml/leverage_longonly.py
    python ml/leverage_longonly.py --interval 4h
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, glob, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ml.validate_extended import load_sym, load_funding, available_symbols, BASE6

FEE, SLIP = 0.0005, 0.0005
FAST_DAYS, SLOW_DAYS = 3, 33
BPD = {"1d": 1, "4h": 6, "1h": 24}

# 사이클 약세 구간 (BTC 기준 사후 확정)
BEAR = [("2017-12-17", "2018-12-15"), ("2021-11-10", "2022-11-21"),
        ("2025-10-06", "2026-12-31")]
BULL = [("2018-12-15", "2021-11-10"), ("2022-11-21", "2025-10-06")]


def ma_signal(df, interval):
    d = BPD[interval]
    f = max(2, FAST_DAYS*d); s = max(3, SLOW_DAYS*d)
    c = df["close"]
    fa = c.rolling(f).mean().shift(1); sl = c.rolling(s).mean().shift(1)
    p = np.where(fa > sl, 1.0, 0.0)
    p[np.isnan(fa.values) | np.isnan(sl.values)] = 0.0
    return p


def strat_returns(df, pos, lev, funding=None):
    c = df["close"].values
    r = np.zeros(len(c)); r[1:] = c[1:]/c[:-1] - 1.0
    held = np.roll(pos, 1); held[0] = 0.0
    turn = np.abs(np.diff(np.concatenate([[0.0], pos])))
    sr = held*r*lev - turn*(FEE+SLIP)*lev
    if funding is not None and len(funding):
        idx = pd.DatetimeIndex(df["datetime"])
        acc = np.zeros(len(df))
        loc = np.searchsorted(idx.values, funding.index.values, side="right") - 1
        ok = (loc >= 0) & (loc < len(df))
        np.add.at(acc, loc[ok], funding.values[ok])
        sr = sr - held*acc*lev
    return sr


def equity_with_liquidation(sr, lev):
    """일일 손실이 증거금(1/lev)을 넘으면 청산 → 이후 자본 0"""
    eq = np.ones(len(sr)); cap = 1.0; liq = 0
    for i, x in enumerate(sr):
        if cap > 0 and x <= -1.0/lev:
            cap = 0.0; liq += 1
        else:
            cap = max(cap*(1.0+x), 0.0)
        eq[i] = cap
    return eq, liq


def stats(eq):
    if eq[-1] <= 0:
        return -100.0, -100.0
    return (eq[-1]-1)*100, (eq/np.maximum.accumulate(eq)-1).min()*100


def mask_of(idx, segs):
    idx = pd.DatetimeIndex(idx)
    m = np.zeros(len(idx), dtype=bool)
    for lo, hi in segs:
        m |= np.asarray((idx >= lo) & (idx <= hi))
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1d")
    ap.add_argument("--max-symbols", type=int, default=40)
    a = ap.parse_args()
    iv = a.interval

    syms = available_symbols(iv)[:a.max_symbols]
    data, sig, fund = {}, {}, {}
    for s in syms:
        df = load_sym(s, iv)
        if len(df) < SLOW_DAYS*BPD[iv] + 120:
            continue
        data[s] = df; sig[s] = ma_signal(df, iv); fund[s] = load_funding(s)
    nf = sum(1 for v in fund.values() if v is not None and len(v))

    print("=" * 96)
    print(f"  MA롱온리({FAST_DAYS}d/{SLOW_DAYS}d) {iv} — 레버리지 검증  ({len(data)}종, 펀딩비 {nf}종)")
    print("=" * 96)

    # ── 1. 개별 종목 레버리지별 (청산 반영) ────────────────
    print("\n[1] 레버리지별 성과 — 종목 중앙값, 청산 반영")
    print(f"\n  {'레버':>6s}{'수익률 중앙값':>16s}{'MDD 중앙값':>14s}{'청산발생 종목':>15s}{'전멸(-100%)':>13s}")
    print("  " + "-" * 66)
    for lev in [1.0, 1.5, 2.0, 3.0, 5.0]:
        tot, mdd, nliq, dead = [], [], 0, 0
        for s in data:
            sr = strat_returns(data[s], sig[s], lev, fund.get(s))
            eq, liq = equity_with_liquidation(sr, lev)
            t, m = stats(eq)
            tot.append(t); mdd.append(m)
            if liq: nliq += 1
            if t <= -99.9: dead += 1
        print(f"  {lev:>5.1f}x{np.median(tot):>15,.0f}%{np.median(mdd):>13.1f}%"
              f"{nliq:>12d}/{len(data):<3d}{dead:>12d}")

    # ── 2. 분산 포트폴리오 레버리지 ────────────────────────
    print(f"\n[2] {len(data)}종 동일가중 분산 후 레버리지 — 분산이 MDD를 낮추면 여력이 생긴다")
    allidx = sorted(set().union(*[set(d["datetime"]) for d in data.values()]))
    allidx = pd.DatetimeIndex(allidx)
    R = pd.DataFrame(index=allidx)
    for s in data:
        sr = strat_returns(data[s], sig[s], 1.0, fund.get(s))
        R[s] = pd.Series(sr, index=pd.DatetimeIndex(data[s]["datetime"])).reindex(allidx)
    port1 = R.mean(axis=1, skipna=True).fillna(0.0).values

    B = pd.DataFrame(index=allidx)
    for s in data:
        c = data[s]["close"].values
        r = np.zeros(len(c)); r[1:] = c[1:]/c[:-1]-1
        B[s] = pd.Series(r, index=pd.DatetimeIndex(data[s]["datetime"])).reindex(allidx)
    bh = B.mean(axis=1, skipna=True).fillna(0.0).values
    bt, bm = stats(np.cumprod(1+bh))

    print(f"\n  기준: {len(data)}종 동일가중 존버   수익률 {bt:,.0f}%   MDD {bm:.1f}%")
    print(f"\n  {'레버':>6s}{'수익률':>15s}{'MDD':>10s}{'청산':>8s}{'존버대비':>14s}")
    print("  " + "-" * 56)
    for lev in [1.0, 1.5, 2.0, 3.0, 5.0]:
        eq, liq = equity_with_liquidation(port1*lev, lev)
        t, m = stats(eq)
        flag = "💀" if liq else ("✅" if t > bt else "  ")
        print(f"  {lev:>5.1f}x{t:>14,.0f}%{m:>9.1f}%{liq:>8d}{t-bt:>+13,.0f}%p {flag}")

    # ── 3. 약세장 매수신호 포착력 ──────────────────────────
    print(f"\n[3] 약세장에서도 매수신호를 잡는가")
    bear_m = mask_of(allidx, BEAR); bull_m = mask_of(allidx, BULL)
    expo = pd.DataFrame(index=allidx)
    for s in data:
        expo[s] = pd.Series(np.roll(sig[s], 1),
                            index=pd.DatetimeIndex(data[s]["datetime"])).reindex(allidx)
    ex = expo.mean(axis=1, skipna=True).fillna(0.0).values

    for lbl, m in [("강세 사이클", bull_m), ("약세 사이클", bear_m)]:
        if m.sum() == 0: continue
        eq, _ = equity_with_liquidation(port1[m], 1.0)
        t, mm = stats(eq)
        bt2, bm2 = stats(np.cumprod(1+bh[m]))
        print(f"\n  ── {lbl} ({m.sum():,}일) ──")
        print(f"     평균 노출도 {ex[m].mean()*100:.0f}%   (0%=전부 현금, 100%=전 종목 보유)")
        print(f"     전략 {t:+,.1f}%   존버 {bt2:+,.1f}%   차이 {t-bt2:+,.1f}%p")
        print(f"     전략 MDD {mm:.1f}%   존버 MDD {bm2:.1f}%")

    # 약세 구간별
    print(f"\n  약세 사이클 세부:")
    for lo, hi in BEAR:
        m = mask_of(allidx, [(lo, hi)])
        if m.sum() < 30: continue
        eq, _ = equity_with_liquidation(port1[m], 1.0)
        t, _ = stats(eq)
        bt2, _ = stats(np.cumprod(1+bh[m]))
        print(f"    {lo} ~ {hi[:10]}   노출 {ex[m].mean()*100:>3.0f}%   "
              f"전략 {t:>+8.1f}%   존버 {bt2:>+8.1f}%   차이 {t-bt2:>+8.1f}%p")


if __name__ == "__main__":
    main()
