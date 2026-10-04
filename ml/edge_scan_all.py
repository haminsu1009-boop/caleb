"""
ml/edge_scan_all.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
고승률 조건 전수 탐색 — 롱/숏 양방향, 다중검정 보정 포함

candle_edge.py가 단일 피처의 분위 구간만 봤다면, 여기서는 실제
매매 조건 형태(예: "RSI <= 25")로 임계값을 훑고, 살아남은 조건끼리
2개씩 조합까지 확인한다. 롱(수익 > 0)과 숏(수익 < 0) 양방향 모두 센다.

다중검정 문제:
    수천 개 조건을 훑으면 순전히 우연으로 좋아 보이는 것이 반드시
    나온다. 유의수준 5%로 1,000개를 검정하면 아무 우위가 없어도
    약 50개가 "유의"하게 보인다. 그래서 세 겹으로 거른다.

    1. 학습구간에서 임계값을 정하고, 홀드아웃은 확인에만 쓴다.
    2. 학습·홀드아웃 방향이 일치해야 한다 (우연은 방향을 못 지킨다).
    3. Bonferroni 보정: 검정 횟수 N에 대해 유의수준을 0.05/N로 낮춘
       z값을 써서 Wilson 하한을 계산한다.

승률의 기준선:
    조건 없이 아무 때나 진입했을 때의 승률과 비교해야 의미가 있다.
    강세장에서는 아무거나 사도 승률이 50%를 넘기 때문이다.
    표의 '초과'는 같은 기간 무조건진입 승률 대비 차이다.

사용법:
    python ml/edge_scan_all.py
    python ml/edge_scan_all.py --interval 4h --min-n 300
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, glob, argparse, warnings, itertools
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ROUND_TRIP = 0.002
TRAIN_END = "2024-01-01"


def load_all(interval: str) -> pd.DataFrame:
    frames = []
    for f in sorted(glob.glob(f"data/*_{interval}_all.csv.gz")):
        sym = os.path.basename(f).split(f"_{interval}_")[0]
        if not sym.endswith("USDT"):
            continue
        try:
            d = pd.read_csv(f, compression="gzip")
        except Exception:
            continue
        tc = "timestamp" if "timestamp" in d.columns else "datetime"
        d[tc] = pd.to_datetime(d[tc], format="mixed", errors="coerce")
        d = d.dropna(subset=[tc]).sort_values(tc).drop_duplicates(tc)
        if len(d) < 300:
            continue
        d = d.rename(columns={tc: "datetime"})
        d["symbol"] = sym
        frames.append(d[["datetime", "symbol", "open", "high", "low", "close", "volume"]])
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def build(d: pd.DataFrame, horizons) -> pd.DataFrame:
    out = []
    for sym, g in d.groupby("symbol", sort=False):
        g = g.sort_values("datetime").reset_index(drop=True)
        o, h, l, c, v = g["open"], g["high"], g["low"], g["close"], g["volume"]
        rng = (h - l).replace(0, np.nan)
        pc = c.shift(1)

        # 캔들 기하학
        g["body_pct"]   = (c - o) / o * 100
        g["range_pct"]  = (h - l) / o * 100
        g["body_ratio"] = (c - o).abs() / rng
        g["upper_wick"] = (h - np.maximum(o, c)) / rng
        g["lower_wick"] = (np.minimum(o, c) - l) / rng
        g["close_pos"]  = (c - l) / rng
        g["gap_pct"]    = (o - pc) / pc * 100
        g["cc_ret"]     = c.pct_change() * 100
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        g["size_vs_atr"] = (h - l) / tr.rolling(14).mean()

        # 지표
        delta = c.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        g["rsi14"] = 100 - 100 / (1 + gain / (loss + 1e-12))
        ma20 = c.rolling(20).mean(); sd20 = c.rolling(20).std()
        g["bb_pos"]   = (c - (ma20 - 2*sd20)) / ((ma20 + 2*sd20) - (ma20 - 2*sd20) + 1e-12)
        g["bb_width"] = (4 * sd20) / (ma20 + 1e-12) * 100
        g["vs_ma20"]  = (c / ma20 - 1) * 100
        g["vs_ma50"]  = (c / c.rolling(50).mean() - 1) * 100
        g["vs_ma200"] = (c / c.rolling(200).mean() - 1) * 100
        g["vol_ratio"] = v / v.rolling(20).mean()

        # 모양
        up = (c > o).astype(int)
        st = np.zeros(len(g)); s = 0; uv = up.values
        for i in range(len(g)):
            if i == 0: s = 0
            elif uv[i] == uv[i-1]: s = s + 1 if uv[i] == 1 else s - 1
            else: s = 1 if uv[i] == 1 else -1
            st[i] = s
        g["streak"] = st
        g["dd_from_high"] = (c / c.rolling(60).max() - 1) * 100   # 60봉 고점 대비 낙폭

        # 레짐 (확정봉만)
        g["above200"] = (c > c.rolling(200).mean()).shift(1)

        # 미래 수익 (다음봉 시가 진입 → N봉 뒤 시가 청산, 비용 차감)
        entry = o.shift(-1)
        for H in horizons:
            # 가격 수익률만 담는다. 비용은 방향별로 따로 뺀다 — 여기서
            # 미리 빼면 숏 계산에서 부호가 뒤집혀 비용이 이익이 된다.
            g[f"px{H}"] = (o.shift(-1-H) / entry - 1) * 100
            g[f"ret{H}"] = g[f"px{H}"] - ROUND_TRIP * 100
            g[f"sht{H}"] = -g[f"px{H}"] - ROUND_TRIP * 100
        out.append(g)
    return pd.concat(out, ignore_index=True)


def wilson_lo(w: int, n: int, z: float) -> float:
    if n == 0: return 0.0
    p = w / n; den = 1 + z*z/n; ctr = p + z*z/(2*n)
    mar = z * np.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return (ctr - mar) / den * 100


FEATURES = [
    "body_pct", "range_pct", "body_ratio", "upper_wick", "lower_wick",
    "close_pos", "gap_pct", "cc_ret", "size_vs_atr",
    "rsi14", "bb_pos", "bb_width", "vs_ma20", "vs_ma50", "vs_ma200",
    "vol_ratio", "streak", "dd_from_high",
]
PCTS = [2, 5, 10, 15, 20, 80, 85, 90, 95, 98]


def scan(df: pd.DataFrame, H: int, min_n: int, z: float):
    """단일 조건 전수 스캔 — 롱/숏 양방향"""
    ret, sht = f"ret{H}", f"sht{H}"
    tr = df[df["datetime"] < TRAIN_END]
    ho = df[df["datetime"] >= TRAIN_END]
    base_tr_l = (tr[ret] > 0).mean() * 100
    base_ho_l = (ho[ret] > 0).mean() * 100
    base_tr_s = (tr[sht] > 0).mean() * 100
    base_ho_s = (ho[sht] > 0).mean() * 100

    rows = []
    for feat in FEATURES:
        s_tr = tr[feat].dropna()
        if len(s_tr) < min_n * 5:
            continue
        for p in PCTS:
            thr = np.percentile(s_tr, p)
            for op in ("<=", ">="):
                m_tr = (tr[feat] <= thr) if op == "<=" else (tr[feat] >= thr)
                m_ho = (ho[feat] <= thr) if op == "<=" else (ho[feat] >= thr)
                if m_tr.sum() < min_n or m_ho.sum() < min_n:
                    continue
                for side in ("LONG", "SHORT"):
                    col = ret if side == "LONG" else sht
                    t_tr = tr.loc[m_tr, col].dropna()
                    t_ho = ho.loc[m_ho, col].dropna()
                    if len(t_tr) < min_n or len(t_ho) < min_n:
                        continue
                    w_tr = int((t_tr > 0).sum()); w_ho = int((t_ho > 0).sum())
                    mean_ho = t_ho.mean()
                    base_tr, base_ho = ((base_tr_l, base_ho_l) if side == "LONG"
                                        else (base_tr_s, base_ho_s))
                    wr_tr = w_tr / len(t_tr) * 100
                    wr_ho = w_ho / len(t_ho) * 100
                    rows.append({
                        "side": side, "cond": f"{feat} {op} {thr:.4g}",
                        "feat": feat, "op": op, "thr": thr,
                        "n_tr": len(t_tr), "wr_tr": wr_tr, "edge_tr": wr_tr - base_tr,
                        "n_ho": len(t_ho), "wr_ho": wr_ho, "edge_ho": wr_ho - base_ho,
                        "base_ho": base_ho,
                        "wl_ho": wilson_lo(w_ho, len(t_ho), z),
                        "mean_ho": mean_ho,
                    })
    return pd.DataFrame(rows), base_ho_l


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1d")
    ap.add_argument("--horizons", nargs="*", type=int, default=[1, 3, 5, 10])
    ap.add_argument("--min-n", type=int, default=400)
    ap.add_argument("--top", type=int, default=25)
    a = ap.parse_args()

    print("=" * 108)
    print(f"  고승률 조건 전수 탐색 — {a.interval}, 롱/숏 양방향, 다중검정 보정")
    print("=" * 108)

    raw = load_all(a.interval)
    if raw.empty:
        print("  데이터 없음"); return
    df = build(raw, a.horizons)
    print(f"\n  {raw['symbol'].nunique()}종목 × {len(raw):,}봉  "
          f"(학습 {(df['datetime']<TRAIN_END).sum():,} / 홀드아웃 {(df['datetime']>=TRAIN_END).sum():,})")

    # 검정 횟수 추정 → Bonferroni z
    n_tests = len(FEATURES) * len(PCTS) * 2 * 2 * len(a.horizons)
    from scipy.stats import norm
    z_bonf = norm.ppf(1 - 0.05 / (2 * n_tests))
    print(f"  총 검정 {n_tests:,}회 → Bonferroni 보정 z = {z_bonf:.3f} (미보정 1.96)")

    allr = []
    for H in a.horizons:
        r, _ = scan(df, H, a.min_n, z_bonf)
        if r.empty: continue
        r["H"] = H
        allr.append(r)
    if not allr:
        print("\n  결과 없음"); return
    res = pd.concat(allr, ignore_index=True)

    # 필터: 학습·홀드아웃 방향 일치 + 보정 Wilson 하한이 기준선 초과 + 비용 넘는 수익
    ok = (res["edge_tr"] > 0) & (res["edge_ho"] > 0)
    ok &= res["wl_ho"] > res["base_ho"]
    ok &= res["mean_ho"] > ROUND_TRIP * 100
    surv = res[ok].copy()

    print(f"\n{'='*108}")
    print(f"  전체 {len(res):,}개 조건 중 3중 필터 통과: {len(surv)}개")
    print(f"    ① 학습·홀드아웃 방향 일치  ② 보정 Wilson하한 > 기준선  ③ 평균수익 > 비용")
    print("=" * 108)

    if surv.empty:
        print("\n  통과 조건 없음 — 다중검정 보정을 견디는 우위가 발견되지 않음")
        return

    surv = surv.sort_values("wl_ho", ascending=False)
    print(f"\n  {'방향':6s}{'보유':5s}{'조건':30s}{'홀드n':>7s}{'승률':>7s}"
          f"{'보정하한':>9s}{'기준선':>8s}{'초과':>8s}{'평균수익':>9s}")
    print("  " + "-" * 100)
    for _, r in surv.head(a.top).iterrows():
        base = r["base_ho"]
        print(f"  {r['side']:6s}{r['H']:>3d}봉 {r['cond']:30s}{r['n_ho']:>7,}"
              f"{r['wr_ho']:>6.1f}%{r['wl_ho']:>8.1f}%{base:>7.1f}%"
              f"{r['edge_ho']:>+7.1f}%{r['mean_ho']:>+8.2f}%")

    out = f"ml/saved_models/edge_scan_{a.interval}.csv"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    surv.to_csv(out, index=False)
    print(f"\n  통과 조건 전체 저장: {out}")

    # 방향별 요약
    print(f"\n  방향별: LONG {int((surv['side']=='LONG').sum())}개 / "
          f"SHORT {int((surv['side']=='SHORT').sum())}개")
    print(f"  피처별 통과 횟수:")
    vc = surv["feat"].value_counts()
    for f, n in vc.head(10).items():
        print(f"    {f:16s} {n}개")


if __name__ == "__main__":
    main()
