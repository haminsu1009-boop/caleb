"""
ml/crash_predict.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
폭락을 미리 맞힐 수 있는가 — 신호를 조합하면 달라지는가

ml/crash_short.py에서 단일 신호 14개를 시험했고 최고가 기준선의
1.19배였다(사실상 정보 없음). 하지만 단일 신호가 안 된다고 조합도
안 된다는 보장은 없다. 각각은 약해도 함께 보면 강해지는 경우가 있다.

그래서 여기서는
  ① 특징 10여 개를 한꺼번에 넣어 로지스틱 회귀를 학습시킨다
  ② 학습은 2017~2023에서만, 판정은 2024~ 홀드아웃에서만 한다
  ③ 맞힌 확률이 아니라 **기준선 대비 몇 배인가**로 판정한다
     (전체 봉의 22%가 폭락 직전이므로, 22%를 맞히는 건 정보가 아니다)
  ④ 모델이 가장 확신한 상위 N%만 봤을 때의 적중률도 같이 본다
     실전에서는 전체를 다 쓰는 게 아니라 확신할 때만 치면 되기 때문이다

정직하게 짚어둘 것
  · 폭락 라벨은 미래 30일을 보고 만든다. 특징은 전부 과거만 본다.
  · 표본이 겹친다. 4시간봉 하나하나를 독립 표본으로 세면 실제보다
    통계가 부풀려진다. 그래서 유의성 검정 대신 홀드아웃 성적만 본다.
  · 로지스틱 회귀는 표준화·L2 정규화를 넣어 직접 구현한다(sklearn 없음).
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, glob, argparse, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from bot.oversold import strategy as S
import ml.crash_short as CS
import ml.coin_indicator_backtest as ci
from ml.indicator_backtest import _z

TE = pd.Timestamp("2024-01-01")


def features(B, C):
    """전부 '그 시점에 이미 알 수 있던 것'만 쓴다."""
    market, _, _ = ci.build_coin_market()
    market = market.reindex(B.index, method="ffill")
    senti = ci.load_crypto_sentiment()
    if not senti.empty:
        senti = senti.reindex(B.index, method="ffill")

    fr = {}
    for f in sorted(glob.glob("data/funding/*_funding.csv.gz")):
        sym = os.path.basename(f).split("_")[0]
        if sym not in S.SYMBOLS:
            continue
        d = pd.read_csv(f, compression="gzip", parse_dates=["datetime"]).set_index("datetime")
        fr[sym] = d["funding_rate"] * 10000
    FR = pd.DataFrame(fr).sort_index().mean(axis=1).reindex(B.index, method="ffill")

    r = B.pct_change()
    bars30 = 180
    X = pd.DataFrame(index=B.index)
    X["ret_5d"] = (B / B.shift(30) - 1) * 100
    X["ret_20d"] = (B / B.shift(120) - 1) * 100
    X["ret_60d"] = (B / B.shift(360) - 1) * 100
    X["dd_30d"] = (B / B.rolling(bars30, min_periods=1).max() - 1) * 100
    X["vol"] = r.rolling(120).std() * np.sqrt(6 * 365) * 100
    X["vol_z"] = _z(X["vol"], 720)
    X["vol_chg"] = X["vol"] / X["vol"].rolling(120).mean() - 1
    X["breadth"] = market["breadth"]
    X["btc_ma50"] = market["btc_ma50"]
    X["btc_ma200"] = market["btc_ma200"]
    X["alt_btc"] = market["alt_minus_btc"]
    X["fr"] = FR
    X["fr_z"] = _z(FR, 810)
    if not senti.empty:
        X["fng"] = senti["fng"]
        X["fng_z"] = senti["fng_z"]
    return X


def fit_logit(X, y, l2=1.0, iters=400, lr=0.5):
    """표준화 + L2 로지스틱 회귀. 뉴턴 대신 안정적인 경사하강."""
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = (X - mu) / sd
    Z = np.c_[np.ones(len(Z)), Z]
    w = np.zeros(Z.shape[1])
    n = len(Z)
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(Z @ w, -30, 30)))
        g = Z.T @ (p - y) / n
        g[1:] += l2 * w[1:] / n
        w -= lr * g
    return w, mu, sd


def predict(w, mu, sd, X):
    Z = np.c_[np.ones(len(X)), (X - mu) / sd]
    return 1 / (1 + np.exp(-np.clip(Z @ w, -30, 30)))


def auc(y, p):
    o = np.argsort(p)
    yr = y[o]
    n1, n0 = yr.sum(), len(yr) - yr.sum()
    if n1 == 0 or n0 == 0:
        return np.nan
    ranks = np.arange(1, len(yr) + 1)
    return (ranks[yr == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--crash-pct", type=float, default=25.0)
    ap.add_argument("--crash-days", type=int, default=30)
    a = ap.parse_args()

    C, H, L, O = CS.panel()
    B = CS.basket(C)
    bars = int(a.crash_days * 6)
    fwd_min = B[::-1].rolling(bars, min_periods=1).min()[::-1]
    y_all = (((fwd_min / B - 1) * 100) <= -a.crash_pct).astype(int)

    X = features(B, C)
    ok = X.notna().all(axis=1) & B.notna()
    # 라벨이 미래 30일을 쓰므로 마지막 30일은 라벨이 불완전하다 — 버린다
    ok.iloc[-bars:] = False
    X, y = X[ok], y_all[ok]
    idx = X.index

    tr = idx < TE
    ho = ~tr
    Xtr, ytr = X[tr].values, y[tr].values
    Xho, yho = X[ho].values, y[ho].values
    base_tr, base_ho = ytr.mean() * 100, yho.mean() * 100

    print("=" * 92)
    print(f"  폭락 예측 — {a.crash_days}일 안에 바스켓 {a.crash_pct:.0f}% 하락")
    print("=" * 92)
    print(f"\n  특징 {X.shape[1]}개: {', '.join(X.columns)}")
    print(f"  학습 {tr.sum():,}봉 (폭락 직전 {base_tr:.1f}%) · "
          f"홀드아웃 {ho.sum():,}봉 (폭락 직전 {base_ho:.1f}%)")

    w, mu, sd = fit_logit(Xtr, ytr)
    ptr, pho = predict(w, mu, sd, Xtr), predict(w, mu, sd, Xho)
    print(f"\n  AUC   학습 {auc(ytr,ptr):.3f}   홀드아웃 {auc(yho,pho):.3f}")
    print(f"        0.50 = 동전던지기 · 0.70 이상이어야 실용적이라고 본다")

    print(f"\n  ── 모델이 확신한 상위 N%만 골랐을 때 (홀드아웃)")
    print(f"  {'상위':>7s}{'봉 수':>9s}{'적중률':>9s}{'기준선대비':>11s}{'포착률':>9s}")
    print("  " + "-" * 46)
    for q in [1, 5, 10, 20, 30, 50]:
        thr = np.percentile(pho, 100 - q)
        m = pho >= thr
        if m.sum() < 20:
            continue
        prec = yho[m].mean() * 100
        rec = yho[m].sum() / max(yho.sum(), 1) * 100
        print(f"  {q:>6d}%{int(m.sum()):>9,d}{prec:>8.1f}%"
              f"{prec/max(base_ho,1e-9):>10.2f}배{rec:>8.1f}%")

    print(f"\n  ── 참고: 학습 구간에서는 (과최적화 정도를 보려고)")
    print(f"  {'상위':>7s}{'봉 수':>9s}{'적중률':>9s}{'기준선대비':>11s}")
    print("  " + "-" * 38)
    for q in [1, 5, 10, 20]:
        thr = np.percentile(ptr, 100 - q)
        m = ptr >= thr
        prec = ytr[m].mean() * 100
        print(f"  {q:>6d}%{int(m.sum()):>9,d}{prec:>8.1f}%{prec/max(base_tr,1e-9):>10.2f}배")

    print(f"\n  ── 어떤 특징에 가중치가 실렸나 (표준화 계수)")
    order = np.argsort(-np.abs(w[1:]))
    for i in order:
        print(f"    {X.columns[i]:<12s}{w[1+i]:>+8.3f}")

    print(f"\n  ── 폭락 기준을 바꿔가며 (홀드아웃 AUC)")
    print(f"  {'기준':>14s}{'학습 AUC':>10s}{'홀드 AUC':>10s}{'상위5% 배수':>13s}")
    print("  " + "-" * 48)
    for pct, days in [(15, 14), (20, 30), (25, 30), (30, 60), (40, 60)]:
        bb = int(days * 6)
        fm = B[::-1].rolling(bb, min_periods=1).min()[::-1]
        yy = (((fm / B - 1) * 100) <= -pct).astype(int)
        m2 = ok.copy(); m2.iloc[-bb:] = False
        Xf, yf = X[m2.reindex(X.index).fillna(False)], yy[m2]
        yf = yf.reindex(Xf.index)
        t2 = Xf.index < TE
        if yf[t2].sum() < 50 or yf[~t2].sum() < 20:
            print(f"  {days}일 {pct}%".rjust(14) + "   표본 부족")
            continue
        w2, m_, s_ = fit_logit(Xf[t2].values, yf[t2].values)
        p2t = predict(w2, m_, s_, Xf[t2].values)
        p2h = predict(w2, m_, s_, Xf[~t2].values)
        bh = yf[~t2].mean() * 100
        thr = np.percentile(p2h, 95)
        sel = p2h >= thr
        prec = yf[~t2].values[sel].mean() * 100
        print(f"  {f'{days}일 {pct}%':>14s}{auc(yf[t2].values,p2t):>10.3f}"
              f"{auc(yf[~t2].values,p2h):>10.3f}{prec/max(bh,1e-9):>12.2f}배")


if __name__ == "__main__":
    main()
