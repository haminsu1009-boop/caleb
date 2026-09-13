"""
ml/btc_all_timeframes.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
비트코인 단일 종목 · 전 시간대 · 전 지표 전수 탐색

지금까지의 규칙은 46종을 풀링해서 찾았다. 표본을 키워야 1~2% 우위가
측정 가능하기 때문이다. BTC 하나만 보면 표본이 수십 분의 일로 줄고,
그만큼 우연히 좋아 보이는 조건이 나올 위험이 커진다. 그래서 보정을
훨씬 세게 건다.

대입하는 것:
    지표     RSI(7,14) · 볼린저(위치/폭) · 이격도(20/50/200) · MACD
             스토캐스틱 · ATR · ADX · CCI · Williams%R · MFI · OBV기울기
             거래량비율
    캔들 %   몸통% · 전체폭% · 몸통비율 · 윗꼬리 · 아랫꼬리 · 종가위치
             갭% · 전봉대비% · ATR대비 크기
    차트모양 연속 양/음봉 · 고점대비 낙폭 · 저점대비 상승 · 장악형
             망치형 · 도지 · 인사이드바 · 아웃사이드바 · 밴드 수축

거르는 방법 (세 겹):
    1. 임계값은 학습구간에서만 정한다
    2. 학습·홀드아웃 방향이 일치해야 한다
    3. 전체 검정 횟수에 Bonferroni 보정한 Wilson 하한이 기준선을 넘어야 한다

비용:
    바이빗 BTC 무기한 테이커 왕복 0.11% + 슬리피지 여유 = 0.12%.
    BTC는 가장 유동성이 깊어 이 가정이 현실적이다. 짧은 분봉일수록
    비용이 수익 대비 치명적이므로 이 값이 결과를 크게 좌우한다.

사용법:
    python ml/btc_all_timeframes.py
    python ml/btc_all_timeframes.py --tf 4h 1d
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings, gc
import numpy as np
import pandas as pd
from scipy.stats import norm

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ROUND_TRIP = 0.12          # %  왕복 (바이빗 테이커 0.055%×2 + 여유)
TRAIN_FRAC = 0.70          # 앞 70%로 임계값 결정, 뒤 30%는 확인용

TFS = ["5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"]
# 봉당 시간(시간 단위) — 펀딩·연환산 계산용
TF_HOURS = {"5m":1/12, "15m":.25, "30m":.5, "1h":1, "2h":2, "4h":4,
            "6h":6, "12h":12, "1d":24}
HORIZONS = [1, 3, 5, 10, 20]
PCTS = [1, 2, 5, 10, 20, 80, 90, 95, 98, 99]


def load(tf: str) -> pd.DataFrame:
    f = f"data/BTCUSDT_{tf}_all.csv.gz"
    if not os.path.exists(f):
        return pd.DataFrame()
    d = pd.read_csv(f, compression="gzip")
    tc = "timestamp" if "timestamp" in d.columns else "datetime"
    d[tc] = pd.to_datetime(d[tc], format="mixed", errors="coerce")
    d = d.dropna(subset=[tc])
    # 1w·3d 등에 남아 있는 타임스탬프 손상(연도 57962 같은 값)을 걸러낸다
    d = d[(d[tc] >= "2017-01-01") & (d[tc] <= "2027-01-01")]
    d = d.sort_values(tc).drop_duplicates(tc).reset_index(drop=True)
    return d.rename(columns={tc: "datetime"})


def features(g: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c, v = (g[x].astype("float64") for x in ("open","high","low","close","volume"))
    pc = c.shift(1)
    rng = (h - l).replace(0, np.nan)
    f = pd.DataFrame(index=g.index)

    # ── 캔들 퍼센티지
    f["body_pct"]    = (c - o) / o * 100
    f["range_pct"]   = (h - l) / o * 100
    f["body_ratio"]  = (c - o).abs() / rng
    f["upper_wick"]  = (h - np.maximum(o, c)) / rng
    f["lower_wick"]  = (np.minimum(o, c) - l) / rng
    f["close_pos"]   = (c - l) / rng
    f["gap_pct"]     = (o - pc) / pc * 100
    f["cc_ret"]      = c.pct_change() * 100

    # ── 변동성 / 추세 지표
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    f["size_vs_atr"] = (h - l) / atr
    f["atr_pct"]     = atr / c * 100

    for p in (7, 14):
        dl = c.diff()
        gn = dl.clip(lower=0).rolling(p).mean()
        ls = (-dl.clip(upper=0)).rolling(p).mean()
        f[f"rsi{p}"] = 100 - 100 / (1 + gn / (ls + 1e-12))

    ma20 = c.rolling(20).mean(); sd20 = c.rolling(20).std()
    f["bb_pos"]   = (c - (ma20 - 2*sd20)) / (4*sd20 + 1e-12)
    f["bb_width"] = (4*sd20) / (ma20 + 1e-12) * 100
    f["vs_ma20"]  = (c / ma20 - 1) * 100
    f["vs_ma50"]  = (c / c.rolling(50).mean() - 1) * 100
    f["vs_ma200"] = (c / c.rolling(200).mean() - 1) * 100

    e12 = c.ewm(span=12, adjust=False).mean(); e26 = c.ewm(span=26, adjust=False).mean()
    macd = e12 - e26
    f["macd_hist"] = (macd - macd.ewm(span=9, adjust=False).mean()) / c * 100

    ll = l.rolling(14).min(); hh = h.rolling(14).max()
    f["stoch_k"] = (c - ll) / (hh - ll + 1e-12) * 100
    f["willr"]   = (hh - c) / (hh - ll + 1e-12) * -100

    tp = (h + l + c) / 3
    f["cci"] = (tp - tp.rolling(20).mean()) / (0.015 * tp.rolling(20).std() + 1e-12)

    up = (h.diff()).clip(lower=0); dn = (-l.diff()).clip(lower=0)
    plus = 100 * (up.where(up > dn, 0).rolling(14).mean()) / (atr + 1e-12)
    minus = 100 * (dn.where(dn > up, 0).rolling(14).mean()) / (atr + 1e-12)
    f["adx"] = (100 * (plus - minus).abs() / (plus + minus + 1e-12)).rolling(14).mean()

    mf = tp * v
    pos = mf.where(c > pc, 0).rolling(14).sum()
    neg = mf.where(c < pc, 0).rolling(14).sum()
    f["mfi"] = 100 - 100 / (1 + pos / (neg + 1e-12))

    obv = (np.sign(c.diff()).fillna(0) * v).cumsum()
    f["obv_slope"] = (obv - obv.shift(20)) / (v.rolling(20).mean() * 20 + 1e-12)
    f["vol_ratio"] = v / v.rolling(20).mean()

    # ── 차트 모양
    upb = (c > o)
    st = np.zeros(len(g)); uv = upb.values; s = 0
    for i in range(len(g)):
        if i == 0: s = 0
        elif uv[i] == uv[i-1]: s = s + 1 if uv[i] else s - 1
        else: s = 1 if uv[i] else -1
        st[i] = s
    f["streak"] = st
    f["dd_from_high"] = (c / c.rolling(60).max() - 1) * 100
    f["up_from_low"]  = (c / c.rolling(60).min() - 1) * 100
    f["bb_squeeze"]   = f["bb_width"] / (f["bb_width"].rolling(100).mean() + 1e-12)

    po, pcl = o.shift(1), c.shift(1)
    f["engulf"]    = ((c > po) & (o < pcl) & upb).astype(float) \
                   - ((c < po) & (o > pcl) & ~upb).astype(float)
    f["hammer"]    = (f["lower_wick"] > 0.5).astype(float) - (f["upper_wick"] > 0.5).astype(float)
    f["doji"]      = (f["body_ratio"] < 0.1).astype(float)
    f["inside"]    = ((h < h.shift(1)) & (l > l.shift(1))).astype(float)
    f["outside"]   = ((h > h.shift(1)) & (l < l.shift(1))).astype(float)

    return f.astype("float32")


FEATURES = None   # features()가 만드는 전체 컬럼을 그대로 쓴다


def wilson_lo(w, n, z):
    if n == 0: return 0.0
    p = w / n; den = 1 + z*z/n; ctr = p + z*z/(2*n)
    mar = z * np.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return (ctr - mar) / den * 100


def scan_tf(tf, z, min_n):
    g = load(tf)
    if len(g) < 2000:
        return pd.DataFrame()
    f = features(g)
    o = g["open"].astype("float64")
    h = g["high"].astype("float64")
    l = g["low"].astype("float64")

    entry = o.shift(-1)
    res = {}
    for H in HORIZONS:
        ex = o.shift(-1 - H)
        # 가격 수익률만 담는다. 비용은 방향별로 각각 차감한다 —
        # 여기서 미리 빼면 숏에서 부호가 뒤집혀 비용이 이익으로 둔갑한다.
        res[f"px{H}"] = ((ex / entry - 1) * 100).astype("float32")
        # 보유 중 최대 순행/역행 — "몇 퍼센트까지 먹을 수 있었나"
        fwd_hi = h.shift(-1).rolling(H, min_periods=1).max().shift(-(H-1)) if H > 1 else h.shift(-1)
        fwd_lo = l.shift(-1).rolling(H, min_periods=1).min().shift(-(H-1)) if H > 1 else l.shift(-1)
        res[f"mfe{H}"] = ((fwd_hi / entry - 1) * 100).astype("float32")
        res[f"mae{H}"] = ((fwd_lo / entry - 1) * 100).astype("float32")
    r = pd.DataFrame(res, index=g.index)

    split = int(len(g) * TRAIN_FRAC)
    is_tr = np.zeros(len(g), dtype=bool); is_tr[:split] = True

    # 기준선(무조건 진입 승률)은 조건과 무관하므로 한 번만 구한다.
    # 루프 안에서 매번 계산하면 6,800번 전체 배열을 훑게 된다.
    # 롱/숏 손익을 따로 만든다. 둘 다 비용을 차감한다.
    for H in HORIZONS:
        px = r[f"px{H}"]
        r[f"L{H}"] = px - ROUND_TRIP
        r[f"S{H}"] = -px - ROUND_TRIP

    base = {}
    for H in HORIZONS:
        fin = np.isfinite(r[f"px{H}"].values)
        base[H] = {}
        for sd in ("L", "S"):
            v = r[f"{sd}{H}"].values
            base[H][sd] = ((v[is_tr & fin] > 0).mean() * 100,
                           (v[~is_tr & fin] > 0).mean() * 100)

    rows = []
    cols = [c for c in f.columns]
    for col in cols:
        s = f[col]
        str_ = s[is_tr].dropna()
        if len(str_) < min_n * 5 or str_.nunique() < 5:
            continue
        for p in PCTS:
            thr = np.percentile(str_, p)
            for op in ("<=", ">="):
                m = (s <= thr) if op == "<=" else (s >= thr)
                m = m.values
                for H in HORIZONS:
                    ok = m & np.isfinite(r[f"px{H}"].values)
                    a, b = ok & is_tr, ok & ~is_tr
                    n_tr, n_ho = a.sum(), b.sum()
                    if n_tr < min_n or n_ho < min_n:
                        continue
                    for side in ("LONG", "SHORT"):
                        sd = "L" if side == "LONG" else "S"
                        pnl = r[f"{sd}{H}"].values
                        rt, rh = pnl[a], pnl[b]
                        bt, bh = base[H][sd]
                        wt, wh = (rt > 0).sum(), (rh > 0).sum()
                        mu = rh.mean()
                        mfe = (r[f"mfe{H}"].values[b] if side == "LONG"
                               else -r[f"mae{H}"].values[b])
                        wr_t, wr_h = wt/n_tr*100, wh/n_ho*100
                        if wr_t <= bt or wr_h <= bh or mu <= 0:
                            continue
                        wl = wilson_lo(int(wh), int(n_ho), z)
                        if wl <= bh:
                            continue
                        mfe = mfe[np.isfinite(mfe)]
                        rows.append({
                            "tf": tf, "side": side, "H": H,
                            "cond": f"{col} {op} {thr:.4g}", "feat": col,
                            "n_tr": int(n_tr), "wr_tr": wr_t,
                            "n_ho": int(n_ho), "wr_ho": wr_h, "base_ho": bh,
                            "edge": wr_h - bh, "wl": wl, "mean": mu,
                            "mfe_med": float(np.median(mfe)) if len(mfe) else np.nan,
                            "mfe_p90": float(np.percentile(mfe, 90)) if len(mfe) else np.nan,
                        })
    del f, r, g; gc.collect()
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", nargs="*", default=TFS)
    ap.add_argument("--min-n", type=int, default=200)
    ap.add_argument("--top", type=int, default=30)
    a = ap.parse_args()

    probe = features(load(a.tf[0]).head(500))
    n_feat = probe.shape[1]
    n_tests = len(a.tf) * n_feat * len(PCTS) * 2 * 2 * len(HORIZONS)
    z = norm.ppf(1 - 0.05 / (2 * n_tests))

    print("=" * 104)
    print(f"  비트코인 전 시간대 전수 탐색 — 지표 {n_feat}종 × 임계 {len(PCTS)} × "
          f"연산 2 × 방향 2 × 보유 {len(HORIZONS)} × 시간대 {len(a.tf)}")
    print(f"  총 검정 {n_tests:,}회  →  Bonferroni z = {z:.3f} (미보정 1.96)")
    print(f"  비용 왕복 {ROUND_TRIP}% 차감 · 학습 앞 70% / 홀드아웃 뒤 30%")
    print("=" * 104)

    allr = []
    for tf in a.tf:
        r = scan_tf(tf, z, a.min_n)
        g = load(tf)
        print(f"  {tf:>4s}  {len(g):>9,}봉  →  통과 {len(r):>4}개")
        if not r.empty:
            allr.append(r)
    if not allr:
        print("\n  보정을 견디는 조건이 하나도 없음"); return
    res = pd.concat(allr, ignore_index=True).sort_values("wl", ascending=False)
    os.makedirs("ml/saved_models", exist_ok=True)
    res.to_csv("ml/saved_models/btc_all_tf.csv", index=False)

    print(f"\n{'='*104}\n  통과 {len(res)}개 · 보정 Wilson 하한 순 상위 {a.top}\n{'='*104}")
    print(f"  {'시간':5s}{'방향':6s}{'보유':5s}{'조건':30s}{'홀드n':>7s}{'승률':>7s}"
          f"{'하한':>7s}{'기준':>7s}{'초과':>7s}{'거래당':>8s}{'최대먹은%':>10s}")
    print("  " + "-" * 100)
    for _, x in res.head(a.top).iterrows():
        print(f"  {x['tf']:5s}{x['side']:6s}{x['H']:>3.0f}봉 {x['cond']:30s}{x['n_ho']:>7,}"
              f"{x['wr_ho']:>6.1f}%{x['wl']:>6.1f}%{x['base_ho']:>6.1f}%{x['edge']:>+6.1f}%"
              f"{x['mean']:>+7.2f}%{x['mfe_med']:>+9.2f}%")
    print(f"\n  저장: ml/saved_models/btc_all_tf.csv")
    print(f"\n  시간대별 통과 수:")
    for tf, n in res["tf"].value_counts().items():
        sub = res[res.tf == tf]
        print(f"    {tf:>4s} {n:>4}개   LONG {int((sub.side=='LONG').sum()):>3} / "
              f"SHORT {int((sub.side=='SHORT').sum()):>3}   최고하한 {sub.wl.max():.1f}%")


if __name__ == "__main__":
    main()
