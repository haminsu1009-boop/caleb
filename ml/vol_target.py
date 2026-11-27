"""
ml/vol_target.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
변동성 타겟팅 — Sharpe를 올려 레버리지 여력을 만든다

leverage_limit.py 결과: 켈리 f* = mu/sigma^2 이고 현재 롱온리는
Sharpe 1.32, f* 2.66x. 10x를 쓰려면 Sharpe 4.95가 필요하다.
분자(수익)를 4배 만드는 것보다 분모(변동성)를 줄이는 쪽이 현실적이다.

세 단계를 각각 켜고 끄며 기여도를 분리 측정한다.

  1. 동일가중 (기준)
     지금까지 쓴 방식. 변동성이 제각각인 종목을 같은 금액씩 담으므로
     변동성 큰 종목이 포트폴리오 위험을 지배한다.

  2. 역변동성 가중 (리스크 패리티)
     종목별 비중을 1/최근변동성에 비례시킨다. 각 종목이 위험을
     비슷하게 기여하도록 만든다. 종목 간 불균형을 제거한다.

  3. 포트폴리오 변동성 타겟팅
     포트폴리오 전체 변동성이 목표치(예: 연 20%)가 되도록 총 노출을
     매일 조절한다. 변동성이 낮은 국면엔 노출을 키우고 높은 국면엔
     줄인다. 시간에 따른 불균형을 제거한다.

모든 변동성 추정은 shift(1)로 과거만 사용한다 — 미래참조 없음.

사용법:
    python ml/vol_target.py --interval 4h
    python ml/vol_target.py --interval 4h --target-vol 0.20
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

VOL_LOOKBACK_DAYS = 20      # 변동성 추정 기간
MAX_WEIGHT_MULT   = 3.0     # 개별 종목 비중 상한 (동일가중 대비 배수)
MAX_GROSS         = 1.0     # 총 노출 상한 (1.0 = 자본 100%, 레버리지는 별도)


def ma_signal(df, interval):
    d = BPD[interval]
    f = max(2, FAST_DAYS*d); s = max(3, SLOW_DAYS*d)
    c = df["close"]
    fa = c.rolling(f).mean().shift(1); sl = c.rolling(s).mean().shift(1)
    p = np.where(fa > sl, 1.0, 0.0)
    p[np.isnan(fa.values) | np.isnan(sl.values)] = 0.0
    return p


def build_panel(interval: str):
    """심볼별 신호·수익률·변동성을 공통 인덱스로 정렬"""
    syms = available_symbols(interval)
    need = SLOW_DAYS*BPD[interval] + 120
    data, fund = {}, {}
    for s in syms:
        df = load_sym(s, interval)
        if len(df) >= need:
            data[s] = df; fund[s] = load_funding(s)

    idx = pd.DatetimeIndex(sorted(set().union(*[set(d["datetime"]) for d in data.values()])))
    SIG = pd.DataFrame(index=idx); RET = pd.DataFrame(index=idx)
    VOL = pd.DataFrame(index=idx); FUND = pd.DataFrame(index=idx)

    vb = VOL_LOOKBACK_DAYS * BPD[interval]
    for s, df in data.items():
        di = pd.DatetimeIndex(df["datetime"])
        c = df["close"].values
        r = np.zeros(len(c)); r[1:] = c[1:]/c[:-1] - 1.0
        pos = ma_signal(df, interval)

        RET[s] = pd.Series(r, index=di).reindex(idx)
        SIG[s] = pd.Series(np.roll(pos, 1), index=di).reindex(idx)   # 체결 지연
        VOL[s] = pd.Series(pd.Series(r, index=di).rolling(vb).std().shift(1).values,
                           index=di).reindex(idx)

        f = fund.get(s)
        acc = np.zeros(len(df))
        if f is not None and len(f):
            loc = np.searchsorted(di.values, f.index.values, side="right") - 1
            ok = (loc >= 0) & (loc < len(df))
            np.add.at(acc, loc[ok], f.values[ok])
        FUND[s] = pd.Series(acc, index=di).reindex(idx)

    return SIG.fillna(0.0), RET.fillna(0.0), VOL, FUND.fillna(0.0), idx


def portfolio(SIG, RET, VOL, FUND, mode: str, interval: str,
              target_vol: float = 0.20) -> np.ndarray:
    """mode: equal | invvol | invvol_target"""
    by = BARS_YEAR[interval]

    if mode == "equal":
        raw = SIG.copy()
    else:
        inv = 1.0 / VOL.replace(0, np.nan)
        raw = SIG * inv

    tot = raw.sum(axis=1).replace(0, np.nan)
    w = raw.div(tot, axis=0).fillna(0.0)

    # 개별 종목 비중 상한 — 한 종목이 포트폴리오를 지배하지 않도록
    n_on = SIG.sum(axis=1).replace(0, np.nan)
    cap = (MAX_WEIGHT_MULT / n_on).fillna(0.0)
    w = w.clip(upper=cap, axis=0)

    # 신호 개수만큼만 노출 (전 종목 현금이면 0)
    gross = (SIG.sum(axis=1) / SIG.shape[1]).clip(upper=MAX_GROSS)
    w = w.div(w.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    w = w.mul(gross, axis=0)

    if mode == "invvol_target":
        # 포트폴리오 실현변동성을 목표치에 맞추도록 총 노출 스케일
        base = (w * RET).sum(axis=1)
        vb = VOL_LOOKBACK_DAYS * BPD[interval]
        pv = base.rolling(vb).std().shift(1) * np.sqrt(by)
        scale = (target_vol / pv).replace([np.inf, -np.inf], np.nan)
        scale = scale.clip(upper=3.0).fillna(1.0)     # 스케일 상한 3배
        w = w.mul(scale, axis=0)

    turn = w.diff().abs().sum(axis=1).fillna(0.0)
    ret = (w * RET).sum(axis=1) - turn * (FEE + SLIP) - (w * FUND).sum(axis=1)
    return ret.values, w


def sim(r1x, lev):
    cap = 1.0; curve = np.empty(len(r1x)); liq = 0
    thr = -1.0/lev
    for i, x in enumerate(r1x):
        if cap > 0 and x <= thr:
            cap = 0.0; liq += 1
        else:
            cap = max(cap*(1.0 + x*lev), 0.0)
        curve[i] = cap
    if cap <= 0:
        return -100.0, -100.0, liq
    peak = np.maximum.accumulate(curve)
    return (cap-1)*100, (curve/peak-1).min()*100, liq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="4h")
    ap.add_argument("--target-vol", type=float, default=0.20)
    a = ap.parse_args()
    iv = a.interval; by = BARS_YEAR[iv]

    SIG, RET, VOL, FUND, idx = build_panel(iv)
    print("=" * 96)
    print(f"  변동성 타겟팅 — {iv}, {SIG.shape[1]}종, {idx[0].date()} ~ {idx[-1].date()}")
    print(f"  목표 변동성 연 {a.target_vol*100:.0f}%   변동성 추정 {VOL_LOOKBACK_DAYS}일")
    print("=" * 96)

    modes = [("equal", "① 동일가중 (기존)"),
             ("invvol", "② 역변동성 가중"),
             ("invvol_target", "③ 역변동성 + 변동성타겟")]

    results = {}
    print(f"\n  {'구성':24s}{'연수익':>10s}{'연변동성':>11s}{'Sharpe':>9s}{'켈리 f*':>10s}{'1x수익률':>14s}{'MDD':>9s}")
    print("  " + "-" * 88)
    for mode, label in modes:
        r, w = portfolio(SIG, RET, VOL, FUND, mode, iv, a.target_vol)
        mu = r.mean()*by; sd = r.std()*np.sqrt(by)
        sh = mu/sd if sd > 0 else 0.0
        f = mu/(sd**2) if sd > 0 else 0.0
        t, m, _ = sim(r, 1.0)
        results[label] = (r, mu, sd, sh, f)
        print(f"  {label:24s}{mu*100:>9.1f}%{sd*100:>10.1f}%{sh:>9.2f}{f:>9.2f}x{t:>13,.0f}%{m:>8.1f}%")

    # 레버리지 스윕
    print(f"\n  레버리지별 성과 (청산 반영)")
    print(f"\n  {'구성':24s}", end="")
    for lev in [1, 2, 3, 5, 10]: print(f"{str(lev)+'x':>13s}", end="")
    print()
    print("  " + "-" * 89)
    for label, (r, *_ ) in results.items():
        line = f"  {label:24s}"
        for lev in [1, 2, 3, 5, 10]:
            t, m, liq = sim(r, lev)
            line += f"{'청산💀':>13s}" if liq else f"{t:>12,.0f}%"
        print(line)

    print(f"\n  최대 낙폭")
    print(f"\n  {'구성':24s}", end="")
    for lev in [1, 2, 3, 5]: print(f"{str(lev)+'x':>11s}", end="")
    print()
    print("  " + "-" * 70)
    for label, (r, *_ ) in results.items():
        line = f"  {label:24s}"
        for lev in [1, 2, 3, 5]:
            t, m, liq = sim(r, lev)
            line += f"{m:>10.1f}%"
        print(line)

    # 개선 요약
    base_sh = results[modes[0][1]][3]
    best_lbl = max(results, key=lambda k: results[k][3])
    best_sh, best_f = results[best_lbl][3], results[best_lbl][4]
    print(f"\n{'='*96}")
    print(f"  Sharpe {base_sh:.2f} → {best_sh:.2f}  ({(best_sh/base_sh-1)*100:+.0f}%)"
          f"   켈리 f* {results[modes[0][1]][4]:.2f}x → {best_f:.2f}x")
    need = 10*(results[best_lbl][2]**2)
    print(f"  10x를 쓰려면 여전히 연수익 {need*100:.0f}% 또는 Sharpe {10*results[best_lbl][2]:.2f} 필요")
    print("=" * 96)


if __name__ == "__main__":
    main()
