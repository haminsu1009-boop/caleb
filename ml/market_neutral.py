"""
ml/market_neutral.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
시장중립 롱숏 — 공통 요인(BTC)을 상쇄해 변동성을 낮춘다

vol_target.py에서 변동성 타겟팅은 실패했다. MA 롱온리가 이미 하락
구간에 현금으로 빠지므로, 같은 구간을 한 번 더 줄이면 수익만 깎였다.

시장중립은 다른 축을 건드린다. 코인은 대부분 BTC와 함께 움직이므로
수익률의 상당 부분이 하나의 공통 요인에서 온다. 상위 종목을 롱하고
하위 종목을 같은 금액만큼 숏하면 그 공통 요인이 상쇄되고, 남는 것은
종목 간 상대 성과뿐이다. 변동성이 줄면 켈리 f* = mu/sigma^2 가 커져
레버리지 여력이 생긴다.

구성:
  1. 롱온리 상위N        — 기준 (기존 횡단면 전략)
  2. 달러중립 롱숏       — 상위N 롱 + 하위N 숏, 같은 금액
  3. 베타중립 롱숏       — 달러중립 + BTC로 잔여 베타 헤지

숏 펀딩비는 부호를 뒤집어 반영한다. 펀딩비가 양수일 때 숏은 받는
쪽이므로, 코인 시장에서 숏은 펀딩이 비용이 아니라 수입인 경우가 많다.

측정: 연수익 / 연변동성 / Sharpe / BTC 베타 / 켈리 f* / 레버리지별 성과

사용법:
    python ml/market_neutral.py --interval 4h
    python ml/market_neutral.py --interval 4h --top-n 8
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
BPD = {"1d": 1, "4h": 6, "1h": 24}
BARS_YEAR = {"1d": 365, "4h": 365*6, "1h": 365*24}


def build(interval: str, min_bars: int = 400):
    syms = available_symbols(interval)
    RET, FUND, PX = {}, {}, {}
    for s in syms:
        df = load_sym(s, interval)
        if len(df) < min_bars:
            continue
        di = pd.DatetimeIndex(df["datetime"])
        c = df["close"].values
        r = np.zeros(len(c)); r[1:] = c[1:]/c[:-1] - 1.0
        RET[s] = pd.Series(r, index=di)
        PX[s]  = pd.Series(c, index=di)

        f = load_funding(s)
        acc = np.zeros(len(df))
        if f is not None and len(f):
            loc = np.searchsorted(di.values, f.index.values, side="right") - 1
            ok = (loc >= 0) & (loc < len(df))
            np.add.at(acc, loc[ok], f.values[ok])
        FUND[s] = pd.Series(acc, index=di)

    RET = pd.DataFrame(RET).sort_index()
    PX  = pd.DataFrame(PX).sort_index()
    FUND = pd.DataFrame(FUND).reindex(RET.index).fillna(0.0)
    return RET.fillna(0.0), PX, FUND


def weights(PX, mode: str, top_n: int, rebal: int, lookback: int):
    """mode: long | neutral"""
    mom = PX.pct_change(lookback)
    W = pd.DataFrame(0.0, index=PX.index, columns=PX.columns)
    for i in range(lookback, len(PX), rebal):
        row = mom.iloc[i].dropna()
        if len(row) < top_n*2 + 2:
            continue
        top = row.nlargest(top_n).index
        if mode == "long":
            top = [t for t in top if row[t] > 0]      # 하락 종목 제외
            if not top:
                continue
            W.iloc[i:i+rebal, W.columns.get_indexer(top)] = 1.0/len(top)
        else:
            bot = row.nsmallest(top_n).index
            W.iloc[i:i+rebal, W.columns.get_indexer(top)] =  0.5/top_n
            W.iloc[i:i+rebal, W.columns.get_indexer(bot)] = -0.5/top_n
    return W


def evaluate(W, RET, FUND, interval, btc_ret=None, beta_hedge=False):
    Ws = W.shift(1).fillna(0.0)
    turn = Ws.diff().abs().sum(axis=1).fillna(0.0)

    # 펀딩: 롱은 지불(-), 숏은 수취(+) → 가중치 부호가 그대로 처리
    fund_pnl = (Ws * FUND).sum(axis=1)
    r = (Ws * RET).sum(axis=1) - turn*(FEE+SLIP) - fund_pnl

    if beta_hedge and btc_ret is not None:
        # 롤링 베타를 BTC로 헤지 (과거 60봉, shift로 미래참조 방지)
        win = 60
        cov = r.rolling(win).cov(btc_ret).shift(1)
        var = btc_ret.rolling(win).var().shift(1)
        beta = (cov/var).replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(-2, 2)
        r = r - beta*btc_ret
    return r


def stats(r, interval, btc_ret=None):
    by = BARS_YEAR[interval]
    mu, sd = r.mean()*by, r.std()*np.sqrt(by)
    sh = mu/sd if sd > 0 else 0.0
    f  = mu/(sd**2) if sd > 0 else 0.0
    beta = np.nan
    if btc_ret is not None and btc_ret.var() > 0:
        beta = r.cov(btc_ret)/btc_ret.var()
    eq = np.cumprod(1+r.values)
    mdd = (eq/np.maximum.accumulate(eq)-1).min()*100 if eq[-1] > 0 else -100.0
    tot = (eq[-1]-1)*100 if eq[-1] > 0 else -100.0
    return dict(mu=mu*100, sd=sd*100, sharpe=sh, kelly=f, beta=beta, tot=tot, mdd=mdd)


def sim(r, lev):
    cap = 1.0; curve = np.empty(len(r)); liq = 0; thr = -1.0/lev
    for i, x in enumerate(r):
        if cap > 0 and x <= thr:
            cap = 0.0; liq += 1
        else:
            cap = max(cap*(1+x*lev), 0.0)
        curve[i] = cap
    if cap <= 0:
        return -100.0, -100.0, liq
    peak = np.maximum.accumulate(curve)
    return (cap-1)*100, (curve/peak-1).min()*100, liq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="4h")
    ap.add_argument("--top-n", type=int, default=5)
    ap.add_argument("--rebal-days", type=int, default=7)
    ap.add_argument("--lookback-days", type=int, default=30)
    a = ap.parse_args()
    iv = a.interval; d = BPD[iv]
    rebal = a.rebal_days*d; lookback = a.lookback_days*d

    RET, PX, FUND = build(iv)
    btc = RET["BTCUSDT"] if "BTCUSDT" in RET.columns else None

    print("=" * 98)
    print(f"  시장중립 검증 — {iv}, {RET.shape[1]}종, 상위/하위 {a.top_n}종, "
          f"{a.rebal_days}일 리밸런싱, 모멘텀 {a.lookback_days}일")
    print(f"  {RET.index[0].date()} ~ {RET.index[-1].date()}   펀딩비 반영 (숏은 수취)")
    print("=" * 98)

    configs = [
        ("① 롱온리 상위N (기준)", "long",    False),
        ("② 달러중립 롱숏",       "neutral", False),
        ("③ 베타중립 롱숏",       "neutral", True),
    ]

    out = {}
    print(f"\n  {'구성':22s}{'연수익':>10s}{'연변동성':>11s}{'Sharpe':>9s}"
          f"{'BTC베타':>10s}{'켈리 f*':>10s}{'1x수익':>13s}{'MDD':>9s}")
    print("  " + "-" * 94)
    for label, mode, hedge in configs:
        W = weights(PX, mode, a.top_n, rebal, lookback)
        r = evaluate(W, RET, FUND, iv, btc, hedge)
        st = stats(r, iv, btc)
        out[label] = (r, st)
        print(f"  {label:22s}{st['mu']:>9.1f}%{st['sd']:>10.1f}%{st['sharpe']:>9.2f}"
              f"{st['beta']:>10.2f}{st['kelly']:>9.2f}x{st['tot']:>12,.0f}%{st['mdd']:>8.1f}%")

    print(f"\n  레버리지별 성과 (청산 반영)")
    print(f"\n  {'구성':22s}", end="")
    for lev in [1, 2, 3, 5, 10]: print(f"{str(lev)+'x':>14s}", end="")
    print()
    print("  " + "-" * 92)
    for label, (r, st) in out.items():
        line = f"  {label:22s}"
        for lev in [1, 2, 3, 5, 10]:
            t, m, liq = sim(r.values, lev)
            line += f"{'청산💀':>14s}" if liq else f"{t:>13,.0f}%"
        print(line)

    base = out[configs[0][0]][1]
    best = max(out, key=lambda k: out[k][1]["sharpe"])
    bs = out[best][1]
    print(f"\n{'='*98}")
    print(f"  Sharpe {base['sharpe']:.2f} → {bs['sharpe']:.2f} ({best})")
    print(f"  변동성 {base['sd']:.1f}% → {bs['sd']:.1f}%   "
          f"BTC베타 {base['beta']:.2f} → {bs['beta']:.2f}   "
          f"켈리 f* {base['kelly']:.2f}x → {bs['kelly']:.2f}x")
    need_sharpe = 10*(bs['sd']/100)
    print(f"  10x를 쓰려면 Sharpe {need_sharpe:.2f} 필요 (현재 {bs['sharpe']:.2f})")
    print("=" * 98)


if __name__ == "__main__":
    main()
