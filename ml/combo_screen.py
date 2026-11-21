"""
ml/combo_screen.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
유튜브 단타 공략을 조합으로 전수 탐색한다

이 저장소는 단타 전략을 이미 49종 돌렸고 전부 떨어졌다. 그런데
그 49종은 전부 **조건 하나짜리**였다. 유튜브 공략은 거의 전부
조합이다 — "RSI 30 **그리고** 볼린저 하단 **그리고** 거래량 2배",
"엔벨로프 돌파 **그리고** 볼린저 확장 **그리고** RSI", "RSI+MFI+거래량
15분봉" 같은 식이다. 조합은 한 번도 안 봤다.

영상을 하나씩 쫓아다니는 대신 조건 원자를 모아 **2개·3개 조합을
전수로** 돌린다. 그러면 특정 영상이 아니라 그 공략 공간 전체를
덮는다. 어떤 유튜버가 무엇을 조합했든 이 안에 들어온다.

━━ 2단계로 거른다 ━━

1차는 벡터 연산으로 빠르게 훑는다. 조건이 맞은 봉에서 H봉 뒤까지의
수익률 평균을, **아무 조건 없이 잡은 전체 평균**과 비교한다. 이
차이가 조건이 실제로 보태는 값이다. 전체 평균과 비교하는 이유는
암호화폐가 이 기간에 크게 올라서 "아무 때나 사도 오르는" 몫을
빼야 하기 때문이다.

2차는 살아남은 것만 체결 단위로 다시 돌린다.

━━ 판정 ━━

초과수익이 왕복 수수료보다 커야 한다. 수수료는 바이빗 테이커 왕복
0.11%를 쓴다(실제는 체결지연 포함 0.40%). 봉이 짧을수록 그 안에서
움직이는 폭이 작으므로 짧은 봉일수록 불리하다 — 1분봉은 12봉을
완벽하게 다 먹어도 실수수료 대비 1.1배뿐이다(ml/btc_eth_intraday.py).

사용법:
    python ml/combo_screen.py --tf 5m
    python ml/combo_screen.py --tf 1m --hold 30
    python ml/combo_screen.py --tf 15m --triples
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, glob, argparse, itertools, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

FEE = 0.11
TE = pd.Timestamp("2024-01-01")


def load_any(sym, tf):
    """_all 파일이 없으면 연도별 파일을 이어붙인다. 1분·3분봉이 그렇다."""
    f = f"data/{sym}_{tf}_all.csv.gz"
    if os.path.exists(f):
        g = pd.read_csv(f)
    else:
        fs = sorted(glob.glob(f"data/{sym}_{tf}_*.csv.gz"))
        if not fs:
            return None
        g = pd.concat([pd.read_csv(x) for x in fs], ignore_index=True)
    col = "datetime" if "datetime" in g.columns else g.columns[0]
    g[col] = pd.to_datetime(g[col], format="mixed", errors="coerce")
    g = g.rename(columns={col: "dt"}).dropna(subset=["dt"])
    return g.sort_values("dt").drop_duplicates("dt").reset_index(drop=True)


# ── 조건 원자 ────────────────────────────────────────────────────────
def atoms(o, h, l, c, v):
    """전부 그 봉의 **종가 시점에 알 수 있는** 값만 쓴다.
    다음 봉 시가에 체결하므로 이 봉의 정보까지는 합법이다."""
    s = pd.Series(c)
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    m20, sd20 = s.rolling(20).mean(), s.rolling(20).std()
    bw = (sd20 * 4 / m20)
    tp = (h + l + c) / 3
    mf = pd.Series(tp * v)
    pos = mf.where(pd.Series(tp).diff() > 0, 0).rolling(14).sum()
    neg = mf.where(pd.Series(tp).diff() < 0, 0).rolling(14).sum()
    mfi = 100 - 100 / (1 + pos / neg.replace(0, np.nan))
    rmin = rsi.rolling(14).min(); rmax = rsi.rolling(14).max()
    stoch = (rsi - rmin) / (rmax - rmin).replace(0, np.nan) * 100
    vma = pd.Series(v).rolling(20).mean()
    ema50 = s.ewm(span=50, adjust=False).mean()
    ma200 = s.rolling(200).mean()
    body = np.abs(c - o)
    lw = np.minimum(o, c) - l
    red = (c < o)
    A = {
        "RSI<30":        (rsi < 30).values,
        "RSI<20":        (rsi < 20).values,
        "볼린저하단":      (s <= m20 - 2 * sd20).values,
        "볼린저3σ하단":    (s <= m20 - 3 * sd20).values,
        "거래량2배":       (pd.Series(v) >= 2 * vma).values,
        "거래량3배":       (pd.Series(v) >= 3 * vma).values,
        "MFI<20":        (mfi < 20).values,
        "스토캐스틱<20":   (stoch < 20).values,
        "엔벨로프-2%":     (s <= ema50 * 0.98).values,
        "200선위":        (s > ma200).values,
        "200선아래":       (s < ma200).values,
        "밴드수축":        (bw <= bw.rolling(200).quantile(0.2)).values,
        "밴드확장":        (bw >= bw.rolling(200).quantile(0.8)).values,
        "3연속음봉":       red.rolling(3).sum().eq(3).values if hasattr(red, "rolling")
                          else pd.Series(red).rolling(3).sum().eq(3).values,
        "긴아랫꼬리":      (lw > 2 * np.maximum(body, 1e-12)),
    }
    return {k: np.nan_to_num(np.asarray(x, dtype=bool)) for k, x in A.items()}


def screen(sym, tf, hold, triples=False, min_n=200, top=20):
    g = load_any(sym, tf)
    if g is None or len(g) < 5000:
        print(f"  ⚠️  {sym} {tf} 데이터 없음")
        return None
    o, h, l, c, v = (g[k].astype(float).values
                     for k in ("open", "high", "low", "close", "volume"))
    dt = g["dt"].values
    A = atoms(o, h, l, c, v)
    n = len(c)

    # 판단은 봉 i 종가, 체결은 i+1 시가, 청산은 i+hold 종가.
    fwd = np.full(n, np.nan)
    e = o[1:n - hold + 1]
    x = c[hold:n]
    fwd[:len(e)] = (x / e - 1) * 100
    ok = ~np.isnan(fwd)
    base = np.nanmean(fwd)
    is_tr = pd.DatetimeIndex(dt) < TE

    keys = list(A)
    combos = [(k,) for k in keys]
    combos += list(itertools.combinations(keys, 2))
    if triples:
        combos += list(itertools.combinations(keys, 3))

    rows = []
    for cb in combos:
        m = ok.copy()
        for k in cb:
            m &= A[k]
        if m.sum() < min_n:
            continue
        r = fwd[m]
        tr = fwd[m & is_tr]; ho = fwd[m & ~is_tr]
        if len(tr) < min_n // 2 or len(ho) < 30:
            continue
        rows.append(dict(cb=" + ".join(cb), n=int(m.sum()),
                         mu=float(r.mean()), exc=float(r.mean() - base),
                         wr=float((r > 0).mean() * 100),
                         tr=float(tr.mean() - base), ho=float(ho.mean() - base),
                         nho=int(len(ho))))
    if not rows:
        print(f"  ⚠️  {sym} {tf} 조건을 만족하는 조합 없음")
        return None
    df = pd.DataFrame(rows).sort_values("tr", ascending=False)

    print(f"\n  {sym} {tf} · {n:,}봉 · {hold}봉 보유 · 조합 {len(combos):,}개 중 "
          f"표본 {min_n}건 이상 {len(df):,}개")
    print(f"  아무 때나 샀을 때 {hold}봉 수익 평균 = {base:+.4f}%  "
          f"(이게 기준선이다)")
    print(f"\n  {'조합':<42s}{'n':>8s}{'승률':>7s}{'초과':>9s}"
          f"{'학습초과':>10s}{'홀드초과':>10s}{'홀드n':>8s}")
    print("  " + "-" * 96)
    for _, r in df.head(top).iterrows():
        print(f"  {r['cb']:<42s}{r['n']:>8,}{r['wr']:>6.1f}%{r['exc']:>+8.3f}%"
              f"{r['tr']:>+9.3f}%{r['ho']:>+9.3f}%{r['nho']:>8,}")
    pos = df[(df.tr > FEE) & (df.ho > FEE)]
    print(f"\n  학습·홀드아웃 둘 다 초과 > 수수료({FEE}%): {len(pos)}개 / {len(df):,}개")
    if len(df) > 3:
        print(f"  학습초과 ↔ 홀드아웃초과 상관 = {df.tr.corr(df.ho):+.3f}"
              "   (0 근처면 학습으로 고르는 행위가 무의미하다)")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", default="BTCUSDT")
    ap.add_argument("--tf", default="5m")
    ap.add_argument("--hold", type=int, default=12)
    ap.add_argument("--triples", action="store_true", help="3개 조합까지")
    ap.add_argument("--top", type=int, default=20)
    a = ap.parse_args()
    print("=" * 104)
    print("  유튜브 단타 공략 — 조건 조합 전수 탐색")
    print(f"  판단 봉 종가 · 체결 다음 봉 시가 · {a.hold}봉 뒤 청산 · "
          f"왕복 수수료 {FEE}%")
    print("=" * 104)
    screen(a.sym, a.tf, a.hold, a.triples, top=a.top)
    print("=" * 104)


if __name__ == "__main__":
    main()
