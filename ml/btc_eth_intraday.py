"""
ml/btc_eth_intraday.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BTC·ETH만, 짧은 봉에서, 코인마다 다른 전략

요청받은 대로 두 가지를 바꾼다.
  · 전 종목 공통 규칙이 아니라 **코인마다 따로** 고른다.
  · 대상은 BTC·ETH 둘뿐, 봉은 5분·10분·30분·1시간.

1분봉은 받을 수 없다. data.binance.vision이 이 환경의 프록시에서
정책상 403으로 막혀 있다(.github/workflows/collect_binance_metrics.yml
주석에 같은 내용이 있다). GitHub Actions 러너에서는 받을 수 있으므로
필요하면 그 경로로 수집할 수 있다. 여기서는 5분봉이 가장 잘고,
10분·30분은 5분봉에서 합성한다.

━━━ 먼저 천장을 잰다 ━━━

전략을 고르기 전에 알아야 할 것이 있다. 봉이 짧을수록 그 안에서
가격이 덜 움직인다. 왕복 수수료 0.11%보다 덜 움직이는 봉에서는
어떤 전략을 써도 이길 수 없다 — 맞히는 문제가 아니라 산수 문제다.

그래서 봉 길이별로 "보유 구간 동안 가격이 평균 얼마나 움직이는가"를
먼저 재고 수수료와 비교한다. 그 비율이 전략의 상한이다. 실제
전략은 그 움직임의 일부만 가져가므로 상한보다 한참 낮게 나온다.

━━━ 코인마다 다른 전략 ━━━

이 저장소는 이미 코인별 맞춤을 한 번 쟀고 졌다(ml/per_coin_rules.py,
42종·4시간봉·후보 1,080개). 학습에서 거래당 +12.34%로 전역(+5.55%)을
크게 앞섰는데 홀드아웃에서는 +6.90% 대 +8.59%로 뒤집혔다. 유지율이
-25%였다.

여기서는 조건이 다르다. 코인이 2개뿐이라 하나당 후보가 적고, 짧은
봉이라 거래 수가 훨씬 많다(5분봉 94만 봉). 표본이 크면 맞춤이
살아날 수도 있다. 같은 방식으로 판정한다 — **학습구간에서만 고르고
홀드아웃으로 채점**한다.

손익은 반드시 투입 자본으로 가중한다. 분할매수 사다리는 가격이
내려갈 때만 조각을 채우므로 지는 거래에 돈이 더 실린다(실측 2.03배).
한 건씩 똑같이 세면 진 전략이 이긴 것처럼 보인다.

사용법:
    python ml/btc_eth_intraday.py --ceiling      # 봉 길이별 천장만
    python ml/btc_eth_intraday.py                # 전체
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from ml.daytrade_scalein import (STRATS, run_bracket, run_ladder, stat, FEE, load_tf)

COINS = ["BTCUSDT", "ETHUSDT"]
TFS = ["5m", "10m", "30m", "1h"]
BASE = {"5m": None, "10m": ("5m", 2), "30m": ("5m", 6), "1h": None}
TE = pd.Timestamp("2024-01-01")
RNG = np.random.default_rng(0)


def get(sym, tf):
    """없는 봉은 5분봉에서 합성한다. 시가=첫 시가, 고가=최고, 저가=최저,
    종가=마지막 종가, 거래량=합. 마지막 미완성 묶음은 버린다."""
    g = load_tf(sym, tf)
    if g is not None:
        return g
    if BASE.get(tf) is None:
        return None
    src, k = BASE[tf]
    b = load_tf(sym, src)
    if b is None:
        return None
    n = len(b) // k * k
    b = b.iloc[:n]
    idx = np.arange(n) // k
    out = pd.DataFrame({
        "dt": b["dt"].values[::k],
        "open": b["open"].values[::k],
        "high": pd.Series(b["high"].values).groupby(idx).max().values,
        "low": pd.Series(b["low"].values).groupby(idx).min().values,
        "close": b["close"].values[k - 1::k],
        "volume": pd.Series(b["volume"].values).groupby(idx).sum().values,
    })
    return out


def pack(sym, g):
    return dict(sym=sym, dt=g["dt"].values,
                o=g["open"].astype(float).values,
                h=g["high"].astype(float).values,
                l=g["low"].astype(float).values,
                c=g["close"].astype(float).values,
                v=g["volume"].astype(float).values)


def ceiling(D):
    """봉 길이별 천장 — 보유 구간 동안 가격이 평균 얼마나 움직이나."""
    print("=" * 96)
    print("  천장 — 수수료보다 덜 움직이는 봉에서는 어떤 전략도 못 이긴다")
    print(f"  왕복 수수료 {FEE}% (바이빗 테이커. 체결지연 포함하면 0.40%)")
    print("=" * 96)
    print(f"\n  {'코인':10s}{'봉':>5s}{'봉수':>11s}{'봉당움직임':>11s}"
          f"{'12봉 폭':>10s}{'12봉 폭/수수료':>15s}{'0.40% 대비':>12s}")
    print("  " + "-" * 76)
    for (sym, tf), d in D.items():
        c, h, l = d["c"], d["h"], d["l"]
        per_bar = np.abs(np.diff(c) / c[:-1]).mean() * 100
        hi = pd.Series(h).rolling(12).max().values
        lo = pd.Series(l).rolling(12).min().values
        span = np.nanmean((hi - lo) / c * 100)
        print(f"  {sym:10s}{tf:>5s}{len(c):>11,}{per_bar:>10.3f}%{span:>9.2f}%"
              f"{span/FEE:>14.1f}배{span/0.40:>11.1f}배")
    # 1분봉 외삽 — 가격 변동폭은 시간의 제곱근에 비례한다. 5분봉
    # 실측에서 √5로 나누면 1분봉 값이 나온다. 데이터를 못 받아도
    # 천장은 이렇게 알 수 있다.
    print(f"\n  {'(1분봉 외삽)':10s}{'1m':>5s}{'~4,700,000':>11s}", end="")
    b5 = [d for (s_, t_), d in D.items() if t_ == "5m" and s_ == "BTCUSDT"]
    if b5:
        c, h, l = b5[0]["c"], b5[0]["h"], b5[0]["l"]
        pb = np.abs(np.diff(c) / c[:-1]).mean() * 100 / np.sqrt(5)
        hi = pd.Series(h).rolling(12).max().values
        lo = pd.Series(l).rolling(12).min().values
        sp = np.nanmean((hi - lo) / c * 100) / np.sqrt(5)
        print(f"{pb:>10.3f}%{sp:>9.2f}%{sp/FEE:>14.1f}배{sp/0.40:>11.1f}배")
        print(f"  → 1분봉은 12봉을 완벽하게 다 먹어도 실수수료 0.40% 대비 "
              f"{sp/0.40:.1f}배뿐이다.")
        print(f"     전략이 폭의 20%를 가져간다고 보면 {sp*0.2/0.40:.2f}배 — 1배 미만,")
        print(f"     즉 이길 수 없다. 데이터를 받아올 필요가 없는 이유다.")

    print("\n  12봉 폭 = 12봉 동안의 고가-저가 폭. 전략이 가져갈 수 있는 최대치다.")
    print("  실제 전략은 그 일부만 가져가므로 이 비율보다 한참 낮게 나온다.")
    print("  참고: 과매도 롱(4시간봉·60봉 보유)은 실제 엣지/수수료가 16배다.")
    print("=" * 96)


def per_coin(D, reps=20, min_train=100):
    """코인×봉마다 14종 중 최고를 **학습구간에서만** 고르고 홀드아웃으로 채점.

    같이 재는 것
      · 전역 최고 — 두 코인·모든 봉에 같은 전략 하나를 쓸 때
      · 무작위 진입 — 전략 없이 같은 청산만 썼을 때
    맞춤이 이 둘을 홀드아웃에서 이겨야 의미가 있다.
    """
    print("\n" + "=" * 112)
    print("  코인×봉마다 따로 고른다 — 학습(~2023)에서 고르고 홀드아웃(2024~)으로 채점")
    print("  손익은 투입 자본 가중. 사다리는 지는 거래에 돈을 더 싣는다(2.03배).")
    print("=" * 112)

    # 전략별 성적을 코인×봉마다 전부 구해둔다
    grid = {}
    for (sym, tf), d in D.items():
        for name, fn in STRATS:
            try:
                idx = fn(d)
            except Exception:
                continue
            if len(idx) < 30:
                continue
            T = run_ladder(d, idx)
            tr = [t for t in T if pd.Timestamp(t["dt"]) < TE]
            ho = [t for t in T if pd.Timestamp(t["dt"]) >= TE]
            if len(tr) < min_train:
                continue
            grid[(sym, tf, name)] = (stat(tr, fee=0.40), stat(ho, fee=0.40))
        # 무작위 대조군. 5분봉은 94만 봉이라 전수로 돌리면 너무 느리다 —
        # 균등 간격으로 솎아도 추정값은 같다.
        allb = np.arange(25, len(d["c"]) - 30)
        if len(allb) > 120_000:
            allb = allb[:: len(allb) // 120_000 + 1]
        base = run_ladder(d, allb)
        grid[(sym, tf, "무작위(대조군)")] = (
            stat([t for t in base if pd.Timestamp(t["dt"]) < TE], fee=0.40),
            stat([t for t in base if pd.Timestamp(t["dt"]) >= TE], fee=0.40))

    print(f"\n  {'코인':9s}{'봉':>5s}{'학습 1위 전략':>18s}{'학습거래당':>11s}"
          f"{'홀드거래당':>11s}{'홀드n':>9s}{'무작위 홀드':>12s}{'초과':>9s}{'판정':>7s}")
    print("  " + "-" * 92)
    rows = []
    for (sym, tf) in D:
        cands = [(k[2], v) for k, v in grid.items()
                 if k[0] == sym and k[1] == tf and k[2] != "무작위(대조군)"]
        if not cands:
            continue
        name, (tr, ho) = max(cands, key=lambda x: x[1][0]["mu"])
        btr, bho = grid[(sym, tf, "무작위(대조군)")]
        exc = ho["mu"] - bho["mu"]
        ok = ho["mu"] > 0 and exc > 0
        rows.append((sym, tf, name, tr, ho, bho, exc, ok))
        print(f"  {sym:9s}{tf:>5s}{name:>18s}{tr['mu']:>+10.3f}%{ho['mu']:>+10.3f}%"
              f"{ho['n']:>9,}{bho['mu']:>+11.3f}%{exc:>+8.3f}%"
              f"{'통과' if ok else '탈락':>7s}")

    # 학습 점수가 홀드아웃을 예측하는가
    xs = [v[0]["mu"] for k, v in grid.items() if k[2] != "무작위(대조군)"]
    ys = [v[1]["mu"] for k, v in grid.items() if k[2] != "무작위(대조군)"]
    if len(xs) > 3:
        print(f"\n  후보 {len(xs)}개 전체에서 학습 거래당 ↔ 홀드아웃 거래당 상관 = "
              f"{np.corrcoef(xs, ys)[0,1]:+.3f}")
        print("  0 근처이거나 음수면 학습 성적으로 고르는 행위 자체가 무의미하다.")

    # 전역 하나만 썼다면
    print(f"\n  전역(코인·봉 무관하게 같은 전략 하나)로 골랐다면")
    agg = {}
    for (sym, tf, name), (tr, ho) in grid.items():
        if name == "무작위(대조군)":
            continue
        a = agg.setdefault(name, [0.0, 0, 0.0, 0])
        a[0] += tr["mu"] * tr["n"]; a[1] += tr["n"]
        a[2] += ho["mu"] * ho["n"]; a[3] += ho["n"]
    best = max(agg.items(), key=lambda kv: kv[1][0] / max(kv[1][1], 1))
    n, v = best
    print(f"    학습 1위 {n} → 학습 {v[0]/max(v[1],1):+.3f}% · "
          f"홀드아웃 {v[2]/max(v[3],1):+.3f}%")
    ho_best = max(agg.items(), key=lambda kv: kv[1][2] / max(kv[1][3], 1))
    print(f"    (홀드아웃 실제 1위는 {ho_best[0]} "
          f"{ho_best[1][2]/max(ho_best[1][3],1):+.3f}%)")

    n_ok = sum(1 for r in rows if r[7])
    print(f"\n  코인×봉 {len(rows)}칸 중 통과 {n_ok}칸 "
          f"(홀드아웃 플러스 + 무작위 초과)")
    print("=" * 112)
    return grid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ceiling", action="store_true", help="천장 계산만")
    ap.add_argument("--tfs", default=",".join(TFS))
    a = ap.parse_args()

    tfs = [x.strip() for x in a.tfs.split(",") if x.strip()]
    D = {}
    for sym in COINS:
        for tf in tfs:
            g = get(sym, tf)
            if g is None or len(g) < 5000:
                print(f"  ⚠️  {sym} {tf} 데이터 없음 — 건너뜀")
                continue
            D[(sym, tf)] = pack(sym, g)

    ceiling(D)
    if not a.ceiling:
        per_coin(D)


if __name__ == "__main__":
    main()
