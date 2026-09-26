"""
ml/candle_edge.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
캔들 기하학 · 지표 상태 · 차트 모양의 조건부 우위 탐색

지금까지의 실패 원인 진단:
    의사결정나무로 190개 피처를 5단계 깊이까지 조합했다. 조합 공간이
    사실상 무한해서 과거에 우연히 맞은 조합이 항상 발견됐고, 표본은
    심볼당 수십~수백 개뿐이라 그게 우연인지 구분할 수 없었다.

이 스크립트의 접근:
    1. 조합하지 않는다. 단일 조건(또는 2개 조합)만 본다. 자유도를 낮춘다.
    2. 46개 심볼을 전부 합쳐서 표본을 키운다.
       46종 × 3,000봉 ≈ 138,000 관측치. 10분위 구간당 약 13,800개.
       n=13,800이면 Wilson 신뢰구간이 ±0.8% 수준이라 1~2%의 미세한
       우위도 통계적으로 판별 가능하다.
    3. 시장 드리프트를 뺀다. 코인은 강세장에 뭘 사도 오르므로
       "구간 평균수익 − 같은 기간 전체 평균수익"을 우위(edge)로 본다.
    4. 학습(2017~2023) / 홀드아웃(2024~2026)에서 방향이 같아야만 채택.

측정 대상:
    [A] 캔들 기하학 — 몸통비율, 위/아래꼬리비율, 종가위치, ATR대비 크기, 갭
    [B] 지표 상태   — RSI, 볼린저 위치, 이평선 이격도, 거래량비
    [C] 차트 모양   — 직전 3봉 방향 패턴(8종), 연속 상승/하락 카운트,
                      고점/저점 구조(HH/HL/LH/LL)

사용법:
    python ml/candle_edge.py --interval 1d
    python ml/candle_edge.py --interval 4h --horizon 3
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, glob, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ROUND_TRIP = 0.002          # 왕복 수수료+슬리피지
TRAIN_END  = "2024-01-01"


# ══════════════════════════════════════════════════════════════
def load_all(interval: str) -> pd.DataFrame:
    """전 심볼을 하나의 긴 테이블로 합친다 (symbol 열로 구분)"""
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
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def add_features(d: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """심볼별로 피처 + 미래수익 계산 (미래참조 없음: 피처는 당봉까지만)"""
    out = []
    for sym, g in d.groupby("symbol", sort=False):
        g = g.sort_values("datetime").reset_index(drop=True)
        o, h, l, c, v = g["open"], g["high"], g["low"], g["close"], g["volume"]
        rng = (h - l).replace(0, np.nan)

        # ── [A] 캔들 기하학 ─────────────────────────────
        g["body_pct"]    = (c - o) / o * 100                       # 몸통 %
        g["range_pct"]   = (h - l) / o * 100                       # 전체 변동폭 %
        g["body_ratio"]  = (c - o).abs() / rng                     # 몸통/전체 (실체 비중)
        g["upper_wick"]  = (h - np.maximum(o, c)) / rng            # 위꼬리 비중
        g["lower_wick"]  = (np.minimum(o, c) - l) / rng            # 아래꼬리 비중
        g["close_pos"]   = (c - l) / rng                           # 종가가 범위 내 어디서 마감했나
        g["gap_pct"]     = (o - c.shift(1)) / c.shift(1) * 100     # 시가 갭 %
        g["cc_ret"]      = c.pct_change() * 100                    # 전일종가 대비 %

        # ATR 대비 캔들 크기
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        g["size_vs_atr"] = (h - l) / atr

        # ── [B] 지표 상태 ───────────────────────────────
        delta = c.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        g["rsi14"] = 100 - 100 / (1 + gain / (loss + 1e-12))

        ma20 = c.rolling(20).mean(); sd20 = c.rolling(20).std()
        g["bb_pos"]    = (c - (ma20 - 2*sd20)) / ((ma20 + 2*sd20) - (ma20 - 2*sd20) + 1e-12)
        g["vs_ma20"]   = (c / ma20 - 1) * 100
        g["vs_ma50"]   = (c / c.rolling(50).mean() - 1) * 100
        g["vol_ratio"] = v / v.rolling(20).mean()

        # ── [C] 차트 모양 ───────────────────────────────
        up = (c > o).astype(int)
        # 직전 3봉 방향 패턴 (당봉 포함 X — 당봉은 신호 발생 시점)
        g["pat3"] = (up.shift(2)*4 + up.shift(1)*2 + up).astype("Int64")
        # 연속 상승/하락 카운트
        streak = np.zeros(len(g)); s = 0
        uv = up.values
        for i in range(len(g)):
            if i == 0: s = 0
            elif uv[i] == uv[i-1]: s = s + 1 if uv[i] == 1 else s - 1
            else: s = 1 if uv[i] == 1 else -1
            streak[i] = s
        g["streak"] = streak
        # 고점/저점 구조
        hh = (h > h.rolling(10).max().shift(1)).astype(int)
        ll = (l < l.rolling(10).min().shift(1)).astype(int)
        g["structure"] = hh - ll        # +1 신고점, -1 신저점, 0 내부

        # ── 미래 수익 (종가 → N봉 후 종가) ──────────────
        g["fwd"] = (c.shift(-horizon) / c - 1) * 100

        out.append(g)
    return pd.concat(out, ignore_index=True)


def wilson(wins: int, n: int, z: float = 1.96) -> tuple:
    if n == 0: return 0.0, 0.0
    p = wins / n
    den = 1 + z*z/n
    ctr = p + z*z/(2*n)
    mar = z * np.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return (ctr - mar)/den*100, (ctr + mar)/den*100


# ══════════════════════════════════════════════════════════════
def analyze_bins(df: pd.DataFrame, col: str, n_bins: int = 10,
                 min_n: int = 500) -> pd.DataFrame:
    """한 피처를 분위로 나눠 학습/홀드아웃 각각의 우위를 측정"""
    d = df[[col, "fwd", "datetime"]].dropna()
    if len(d) < min_n * n_bins:
        return pd.DataFrame()

    # 학습구간 기준으로 구간 경계 확정 (홀드아웃 정보 사용 금지)
    tr = d[d["datetime"] < TRAIN_END]
    if len(tr) < min_n * n_bins:
        return pd.DataFrame()
    try:
        edges = np.unique(np.quantile(tr[col], np.linspace(0, 1, n_bins + 1)))
    except Exception:
        return pd.DataFrame()
    if len(edges) < 3:
        return pd.DataFrame()

    d = d.copy()
    d["bin"] = pd.cut(d[col], bins=edges, include_lowest=True, duplicates="drop")
    tr = d[d["datetime"] < TRAIN_END]
    ho = d[d["datetime"] >= TRAIN_END]
    if len(ho) < min_n:
        return pd.DataFrame()

    base_tr = tr["fwd"].mean()
    base_ho = ho["fwd"].mean()

    rows = []
    for b, g_tr in tr.groupby("bin", observed=True):
        g_ho = ho[ho["bin"] == b]
        if len(g_tr) < min_n or len(g_ho) < min_n // 3:
            continue
        w_tr = int((g_tr["fwd"] > 0).sum()); w_ho = int((g_ho["fwd"] > 0).sum())
        lo_ho, hi_ho = wilson(w_ho, len(g_ho))
        rows.append({
            "feature": col, "bin": str(b),
            "n_train": len(g_tr), "edge_train": g_tr["fwd"].mean() - base_tr,
            "n_hold": len(g_ho),  "edge_hold":  g_ho["fwd"].mean() - base_ho,
            "wr_hold": w_ho/len(g_ho)*100, "wr_lo": lo_ho, "wr_hi": hi_ho,
            "mean_hold": g_ho["fwd"].mean(),
        })
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1d")
    ap.add_argument("--horizon", type=int, default=3, help="미래 N봉 수익")
    ap.add_argument("--bins", type=int, default=10)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    print("=" * 100)
    print(f"  캔들·지표·모양 조건부 우위 탐색 — {a.interval}, {a.horizon}봉 후 수익")
    print("=" * 100)

    raw = load_all(a.interval)
    if raw.empty:
        print("  데이터 없음"); return
    print(f"\n  로드: {raw['symbol'].nunique()}종목 × 총 {len(raw):,}봉")

    df = add_features(raw, a.horizon)
    tr_n = (df["datetime"] < TRAIN_END).sum()
    ho_n = (df["datetime"] >= TRAIN_END).sum()
    print(f"  학습 {tr_n:,}봉 / 홀드아웃 {ho_n:,}봉")
    print(f"  전체 평균 {a.horizon}봉 수익: 학습 {df[df['datetime']<TRAIN_END]['fwd'].mean():+.3f}%"
          f"  홀드아웃 {df[df['datetime']>=TRAIN_END]['fwd'].mean():+.3f}%  ← 이게 기준선")

    FEATURES = {
        "[A]캔들": ["body_pct", "range_pct", "body_ratio", "upper_wick",
                    "lower_wick", "close_pos", "gap_pct", "cc_ret", "size_vs_atr"],
        "[B]지표": ["rsi14", "bb_pos", "vs_ma20", "vs_ma50", "vol_ratio"],
        "[C]모양": ["streak"],
    }

    all_res = []
    for group, cols in FEATURES.items():
        for col in cols:
            r = analyze_bins(df, col, a.bins)
            if not r.empty:
                r["group"] = group
                all_res.append(r)

    if not all_res:
        print("\n  분석 가능한 피처 없음"); return
    res = pd.concat(all_res, ignore_index=True)

    # 채택 조건: 학습·홀드아웃 방향 일치 + 홀드아웃 우위가 비용을 넘음
    res["same_sign"] = np.sign(res["edge_train"]) == np.sign(res["edge_hold"])
    res["abs_hold"] = res["edge_hold"].abs()
    survivors = res[res["same_sign"] & (res["abs_hold"] > ROUND_TRIP*100)]

    print(f"\n{'='*100}")
    print(f"  전체 {len(res)}개 구간 중 학습·홀드아웃 방향 일치 + 비용 초과: {len(survivors)}개")
    print("=" * 100)

    if len(survivors):
        top = survivors.reindex(survivors["abs_hold"].sort_values(ascending=False).index).head(20)
        print(f"\n  {'그룹':8s}{'피처':14s}{'구간':26s}{'학습우위':>9s}{'홀드우위':>9s}"
              f"{'홀드n':>8s}{'승률':>7s}{'95%CI':>14s}")
        print("  " + "-" * 96)
        for _, r in top.iterrows():
            ci = f"{r['wr_lo']:.1f}~{r['wr_hi']:.1f}"
            print(f"  {r['group']:8s}{r['feature']:14s}{r['bin'][:25]:26s}"
                  f"{r['edge_train']:>+8.3f}%{r['edge_hold']:>+8.3f}%"
                  f"{r['n_hold']:>8,}{r['wr_hold']:>6.1f}%{ci:>14s}")

    out = a.out or f"ml/saved_models/candle_edge_{a.interval}_h{a.horizon}.csv"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    res.to_csv(out, index=False)
    print(f"\n  전체 결과 저장: {out}")


if __name__ == "__main__":
    main()
