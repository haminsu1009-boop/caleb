"""
ml/backtest.py
저장된 DirectionalEnsemble 모델로 아웃오브샘플 백테스트

사용법:
    python ml/backtest.py                                    # BTC 1h (2024~)
    python ml/backtest.py --symbol BTCUSDT --interval 4h
    python ml/backtest.py --symbol all --interval all        # 전체 모델
    python ml/backtest.py --from_year 2023                  # 2023년부터
"""

import os, sys, glob, argparse, warnings, pickle
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ml.models import DirectionalEnsemble

# ── 경로 ──────────────────────────────────────────────
DATA_DIR  = os.path.join(ROOT, "data")
IND_DIR   = os.path.join(DATA_DIR, "indicators")
MODEL_DIR = os.path.join(ROOT, "ml", "saved_models")
CHART_DIR = os.path.join(ROOT, "charts")
os.makedirs(CHART_DIR, exist_ok=True)

# ── 백테스트 파라미터 ──────────────────────────────────
FEE_RATE = 0.0005   # 편도 수수료 0.05%
SLIPPAGE = 0.0005   # 슬리피지
TP_PCT   = 0.005    # Take-Profit 0.5%
SL_PCT   = 0.003    # Stop-Loss  0.3%
HORIZON  = 12       # 타겟 계산 봉 수
SIGNAL_THR = 0.58   # 신호 임계값 (모델 저장 threshold 없을 경우 기본값)

# 심볼×봉단위 목록
ALL_SYMBOLS   = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "SOLUSDT", "XRPUSDT"]
ALL_INTERVALS = ["5m", "1h", "4h", "1d"]


# ══════════════════════════════════════════════════════
# 유틸
# ══════════════════════════════════════════════════════

def load_ohlcv(symbol: str, interval: str, from_year: int = 2024) -> pd.DataFrame:
    pattern = os.path.join(DATA_DIR, f"{symbol}_{interval}_*.csv.gz")
    files = sorted(f for f in glob.glob(pattern)
                   if "_all" not in f
                   and int(os.path.basename(f).split("_")[-1].replace(".csv.gz", "")) >= from_year)
    if not files:
        raise FileNotFoundError(f"파일 없음: {symbol} {interval} (from {from_year})")

    dfs = []
    for f in files:
        df = pd.read_csv(f, compression="gzip")
        ts_raw = df["timestamp"].astype(str).iloc[0]
        try:
            ts_test = pd.to_datetime(ts_raw)
            if ts_test.year > 2100 or ts_test.year < 2010:
                raise ValueError
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        except Exception:
            try:
                df["timestamp"] = pd.to_datetime(
                    df["timestamp"].astype(float).astype("int64"), unit="ms", errors="coerce")
            except Exception:
                df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df[df["timestamp"].dt.year.between(2010, 2030)]
        if df.empty:
            continue
        dfs.append(df)

    df = (pd.concat(dfs)
            .drop_duplicates("timestamp")
            .sort_values("timestamp")
            .reset_index(drop=True))
    df = df.rename(columns={"timestamp": "datetime"})
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)
    return df


def load_model(symbol: str, interval: str):
    """모델 + feature_cols 로드"""
    model_path = os.path.join(MODEL_DIR, f"directional_{symbol}_{interval}.pkl")
    fcol_path  = os.path.join(MODEL_DIR, f"feature_cols_{symbol}_{interval}.pkl")
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"모델 없음: {model_path}")
    if not os.path.exists(fcol_path):
        raise FileNotFoundError(f"feature_cols 없음: {fcol_path}")
    with open(model_path, "rb") as f:
        model = pickle.load(f)
    with open(fcol_path, "rb") as f:
        feature_cols = pickle.load(f)
    return model, feature_cols


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """train_directional.py와 동일한 피처 계산"""
    df = df.copy()
    c = df["close"]; h = df["high"]; l = df["low"]
    v = df["volume"]; o = df["open"]

    for n in [1, 3, 6, 12, 24, 48, 96, 288]:
        df[f"ret_{n}"] = c.pct_change(n)
    for w in [12, 24, 48, 96, 288]:
        df[f"vol_{w}"] = c.pct_change().rolling(w).std()

    for p in [6, 14, 24]:
        delta = c.diff()
        g  = delta.clip(lower=0).ewm(span=p, adjust=False).mean()
        ls = (-delta.clip(upper=0)).ewm(span=p, adjust=False).mean()
        rsi = 100 - 100 / (1 + g / (ls + 1e-9))
        df[f"rsi_{p}"]       = rsi / 100
        df[f"rsi_{p}_slope"] = rsi.diff(3)

    e12 = c.ewm(span=12, adjust=False).mean()
    e26 = c.ewm(span=26, adjust=False).mean()
    macd = e12 - e26; sig = macd.ewm(span=9, adjust=False).mean()
    df["macd"]           = macd / c
    df["macd_sig"]       = sig  / c
    df["macd_hist"]      = (macd - sig) / c
    df["macd_cross_up"]  = ((macd > sig) & (macd.shift(1) <= sig.shift(1))).astype(int)
    df["macd_cross_down"]= ((macd < sig) & (macd.shift(1) >= sig.shift(1))).astype(int)

    for w in [20, 48]:
        mid = c.rolling(w).mean(); std = c.rolling(w).std()
        df[f"bb_pos_{w}"]    = (c - mid) / (2 * std + 1e-9)
        df[f"bb_width_{w}"]  = (4 * std) / (mid + 1e-9)
        df[f"bb_squeeze_{w}"]= (std < std.rolling(w * 2).mean() * 0.75).astype(int)

    for p in [14, 24]:
        lo = l.rolling(p).min(); hi = h.rolling(p).max()
        k  = (c - lo) / (hi - lo + 1e-9); d = k.rolling(3).mean()
        df[f"stoch_k_{p}"] = k; df[f"stoch_d_{p}"] = d
        df[f"stoch_os_{p}"]= (k < 0.2).astype(int)
        df[f"stoch_ob_{p}"]= (k > 0.8).astype(int)

    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr14 = tr.ewm(span=14, adjust=False).mean()
    df["atr_norm"] = atr14 / c
    for p in [14, 28]:
        dm_pos = (h.diff()).clip(lower=0)
        dm_neg = (-l.diff()).clip(lower=0)
        di_pos = dm_pos.ewm(span=p, adjust=False).mean()
        di_neg = dm_neg.ewm(span=p, adjust=False).mean()
        dx = (di_pos - di_neg).abs() / (di_pos + di_neg + 1e-9)
        df[f"adx_{p}"]    = dx.ewm(span=p, adjust=False).mean()
        df[f"di_pos_{p}"] = di_pos / (atr14 + 1e-9)
        df[f"di_neg_{p}"] = di_neg / (atr14 + 1e-9)

    for w in [5, 10, 20, 50, 100, 200]:
        ma = c.rolling(w).mean()
        df[f"ma_ratio_{w}"] = c / (ma + 1e-9) - 1
        df[f"ma_slope_{w}"] = ma.pct_change(3)

    df["vol_ratio"]   = v / (v.rolling(20).mean() + 1e-9)
    df["vol_slope"]   = v.pct_change(5)
    df["vol_burst"]   = (df["vol_ratio"] > 2.0).astype(int)
    df["obv"]         = (np.sign(c.diff()) * v).cumsum()
    df["obv_norm"]    = df["obv"] / (df["obv"].rolling(50).std() + 1e-9)
    df["body"]        = (c - o).abs() / (h - l + 1e-9)
    df["upper_wick"]  = (h - c.clip(lower=o)) / (h - l + 1e-9)
    df["lower_wick"]  = (c.clip(upper=o) - l) / (h - l + 1e-9)
    df["doji"]        = (df["body"] < 0.1).astype(int)
    df["hour_sin"]    = np.sin(2 * np.pi * df["datetime"].dt.hour / 24)
    df["hour_cos"]    = np.cos(2 * np.pi * df["datetime"].dt.hour / 24)
    df["dow_sin"]     = np.sin(2 * np.pi * df["datetime"].dt.dayofweek / 7)
    df["dow_cos"]     = np.cos(2 * np.pi * df["datetime"].dt.dayofweek / 7)
    df["month_sin"]   = np.sin(2 * np.pi * df["datetime"].dt.month / 12)
    df["month_cos"]   = np.cos(2 * np.pi * df["datetime"].dt.month / 12)

    return df


def simulate_trades(df: pd.DataFrame, model, feature_cols: list,
                    threshold: float = SIGNAL_THR) -> pd.DataFrame:
    """모델 신호로 TP/SL 시뮬레이션"""
    X = df[feature_cols].fillna(0)
    lp = model.predict_proba_long(X)
    sp = model.predict_proba_short(X)

    thr = min(threshold, 0.65)
    long_sig  = lp >= thr
    short_sig = sp >= thr

    closes = df["close"].values
    highs  = df["high"].values
    lows   = df["low"].values
    times  = df["datetime"].values
    n      = len(df)

    trades = []
    fee = FEE_RATE; slip = SLIPPAGE; tp = TP_PCT; sl = SL_PCT

    for i in range(n - HORIZON):
        direction = None; prob = 0.0
        if long_sig[i] and not short_sig[i]:
            direction, prob = "LONG", float(lp[i])
        elif short_sig[i] and not long_sig[i]:
            direction, prob = "SHORT", float(sp[i])
        elif long_sig[i] and short_sig[i]:
            if lp[i] >= sp[i]:
                direction, prob = "LONG", float(lp[i])
            else:
                direction, prob = "SHORT", float(sp[i])

        if direction is None:
            continue

        entry    = closes[i] * (1 + slip if direction == "LONG" else 1 - slip)
        tp_price = entry * (1 + tp) if direction == "LONG" else entry * (1 - tp)
        sl_price = entry * (1 - sl) if direction == "LONG" else entry * (1 + sl)

        exit_price = None; exit_type = "timeout"
        for j in range(i + 1, min(i + HORIZON + 1, n)):
            hj, lj = highs[j], lows[j]
            if direction == "LONG":
                if hj >= tp_price: exit_price = tp_price; exit_type = "tp"; break
                if lj <= sl_price: exit_price = sl_price; exit_type = "sl"; break
            else:
                if lj <= tp_price: exit_price = tp_price; exit_type = "tp"; break
                if hj >= sl_price: exit_price = sl_price; exit_type = "sl"; break

        if exit_price is None:
            exit_price = closes[min(i + HORIZON, n - 1)] * (1 - slip if direction == "LONG" else 1 + slip)

        pnl = (exit_price / entry - 1) - 2 * fee if direction == "LONG" \
              else (entry / exit_price - 1) - 2 * fee

        trades.append({
            "entry_time": times[i],
            "direction": direction,
            "entry": round(entry, 2),
            "exit": round(exit_price, 2),
            "exit_type": exit_type,
            "pnl_pct": round(pnl, 6),
            "win": int(pnl > 0),
            "prob": round(prob, 4),
        })

    return pd.DataFrame(trades)


def calc_metrics(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"n_trades": 0}
    pnl = trades["pnl_pct"]
    cum = (1 + pnl).cumprod()
    peak = cum.cummax()
    dd = (cum / peak - 1)
    sharpe = pnl.mean() / (pnl.std() + 1e-9) * np.sqrt(252)
    return {
        "n_trades":    len(trades),
        "n_long":      int((trades["direction"] == "LONG").sum()),
        "n_short":     int((trades["direction"] == "SHORT").sum()),
        "win_rate":    round(float(trades["win"].mean()), 4),
        "win_long":    round(float(trades.loc[trades["direction"]=="LONG","win"].mean()) if (trades["direction"]=="LONG").any() else 0, 4),
        "win_short":   round(float(trades.loc[trades["direction"]=="SHORT","win"].mean()) if (trades["direction"]=="SHORT").any() else 0, 4),
        "avg_pnl":     round(float(pnl.mean() * 100), 4),
        "total_pnl":   round(float(pnl.sum() * 100), 4),
        "cum_return":  round(float(cum.iloc[-1] - 1) * 100, 2),
        "sharpe":      round(float(sharpe), 3),
        "max_dd":      round(float(dd.min() * 100), 2),
        "tp_rate":     round(float((trades["exit_type"]=="tp").mean()), 4),
        "sl_rate":     round(float((trades["exit_type"]=="sl").mean()), 4),
    }


# ══════════════════════════════════════════════════════
# 차트
# ══════════════════════════════════════════════════════

def plot_single(trades: pd.DataFrame, metrics: dict, sym: str, ivl: str):
    if trades.empty:
        print(f"  {sym} {ivl}: 거래 없음 — 차트 스킵")
        return

    fig = plt.figure(figsize=(16, 10))
    fig.patch.set_facecolor("#0f0f17")
    gs = gridspec.GridSpec(3, 3, figure=fig, hspace=0.45, wspace=0.35)

    # 색
    COL_UP   = "#00e676"
    COL_DOWN = "#ff1744"
    COL_LINE = "#40c4ff"
    COL_BG   = "#1a1a2e"
    COL_TEXT = "#e0e0e0"

    def ax_style(ax):
        ax.set_facecolor(COL_BG)
        ax.tick_params(colors=COL_TEXT, labelsize=8)
        for s in ax.spines.values():
            s.set_color("#333355")
        ax.xaxis.label.set_color(COL_TEXT)
        ax.yaxis.label.set_color(COL_TEXT)
        ax.title.set_color(COL_TEXT)

    # 1. 누적 수익률
    ax1 = fig.add_subplot(gs[0, :2])
    pnl  = trades["pnl_pct"]
    cum  = (1 + pnl).cumprod() - 1
    peak = (1 + pnl).cumprod().cummax()
    dd   = ((1 + pnl).cumprod() / peak - 1) * 100
    ax1.plot(cum.values * 100, color=COL_LINE, lw=1.5, label="누적 수익률 (%)")
    ax1.fill_between(range(len(dd)), dd.values, 0, alpha=0.35, color=COL_DOWN, label="낙폭 (%)")
    ax1.axhline(0, color="#555577", lw=0.8, ls="--")
    ax1.set_title(f"{sym}  {ivl}  누적 수익률", fontsize=11, fontweight="bold")
    ax1.set_xlabel("거래 #"); ax1.set_ylabel("%")
    ax1.legend(fontsize=8, facecolor=COL_BG, labelcolor=COL_TEXT)
    ax_style(ax1)

    # 2. 주요 지표 텍스트
    ax2 = fig.add_subplot(gs[0, 2])
    ax2.axis("off"); ax_style(ax2)
    kv = [
        ("총 거래",      f"{metrics['n_trades']} (L:{metrics['n_long']} S:{metrics['n_short']})"),
        ("승률",         f"{metrics['win_rate']*100:.1f}%"),
        ("LONG 승률",    f"{metrics['win_long']*100:.1f}%"),
        ("SHORT 승률",   f"{metrics['win_short']*100:.1f}%"),
        ("누적 수익",    f"{metrics['cum_return']:.2f}%"),
        ("평균 수익",    f"{metrics['avg_pnl']:.4f}%"),
        ("Sharpe",       f"{metrics['sharpe']:.2f}"),
        ("최대 낙폭",    f"{metrics['max_dd']:.2f}%"),
        ("TP 비율",      f"{metrics['tp_rate']*100:.1f}%"),
        ("SL 비율",      f"{metrics['sl_rate']*100:.1f}%"),
    ]
    for i, (k, v) in enumerate(kv):
        color = COL_UP if "수익" in k or "Sharpe" in k or "승률" in k else COL_TEXT
        ax2.text(0.02, 0.92 - i * 0.092, f"{k}:", color=COL_TEXT, fontsize=9,
                 transform=ax2.transAxes)
        ax2.text(0.52, 0.92 - i * 0.092, v, color=color, fontsize=9, fontweight="bold",
                 transform=ax2.transAxes)

    # 3. PnL 분포
    ax3 = fig.add_subplot(gs[1, 0])
    colors_bar = [COL_UP if x > 0 else COL_DOWN for x in pnl.values]
    ax3.bar(range(len(pnl)), pnl.values * 100, color=colors_bar, width=1.0, alpha=0.8)
    ax3.axhline(0, color="#555577", lw=0.8)
    ax3.set_title("거래별 PnL (%)", fontsize=9, fontweight="bold")
    ax3.set_xlabel("거래 #"); ax3.set_ylabel("%")
    ax_style(ax3)

    # 4. 히스토그램
    ax4 = fig.add_subplot(gs[1, 1])
    wins  = pnl[pnl > 0] * 100
    losss = pnl[pnl < 0] * 100
    bins = np.linspace(pnl.min() * 100 - 0.05, pnl.max() * 100 + 0.05, 30)
    ax4.hist(wins.values,  bins=bins, color=COL_UP,   alpha=0.7, label="수익")
    ax4.hist(losss.values, bins=bins, color=COL_DOWN,  alpha=0.7, label="손실")
    ax4.axvline(0, color="#aaaacc", lw=0.8, ls="--")
    ax4.set_title("PnL 분포", fontsize=9, fontweight="bold")
    ax4.set_xlabel("%"); ax4.legend(fontsize=7, facecolor=COL_BG, labelcolor=COL_TEXT)
    ax_style(ax4)

    # 5. 방향별 승률
    ax5 = fig.add_subplot(gs[1, 2])
    dirs = ["LONG", "SHORT"]
    wr_vals = [metrics["win_long"] * 100, metrics["win_short"] * 100]
    bars = ax5.bar(dirs, wr_vals, color=[COL_UP, COL_DOWN], alpha=0.85)
    ax5.axhline(50, color="#aaaacc", lw=0.8, ls="--")
    ax5.set_title("방향별 승률 (%)", fontsize=9, fontweight="bold")
    ax5.set_ylim(0, 100)
    for bar, v in zip(bars, wr_vals):
        ax5.text(bar.get_x() + bar.get_width() / 2, v + 1.5, f"{v:.1f}%",
                 ha="center", va="bottom", color=COL_TEXT, fontsize=9, fontweight="bold")
    ax_style(ax5)

    # 6. 월별 수익률 히트맵
    ax6 = fig.add_subplot(gs[2, :])
    trades2 = trades.copy()
    trades2["entry_time"] = pd.to_datetime(trades2["entry_time"])
    trades2["ym"] = trades2["entry_time"].dt.to_period("M").astype(str)
    monthly = trades2.groupby("ym")["pnl_pct"].sum() * 100
    bar_colors = [COL_UP if v >= 0 else COL_DOWN for v in monthly.values]
    ax6.bar(monthly.index, monthly.values, color=bar_colors, alpha=0.85)
    ax6.axhline(0, color="#555577", lw=0.8)
    ax6.set_title("월별 누적 PnL (%)", fontsize=9, fontweight="bold")
    ax6.set_xlabel("월"); ax6.set_ylabel("%")
    plt.xticks(rotation=45, ha="right")
    ax_style(ax6)

    fig.suptitle(f"📊  DirectionalEnsemble 백테스트  —  {sym}  {ivl}",
                 fontsize=14, fontweight="bold", color=COL_TEXT, y=0.98)

    path = os.path.join(CHART_DIR, f"backtest_{sym}_{ivl}.png")
    plt.savefig(path, dpi=130, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    print(f"  📊 차트 저장: {path}")


def plot_summary(summary: list):
    """전체 모델 비교 요약 차트"""
    df = pd.DataFrame(summary).set_index("label")
    if df.empty:
        return

    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    fig.patch.set_facecolor("#0f0f17")
    COL_UP = "#00e676"; COL_DOWN = "#ff1744"; COL_LINE = "#40c4ff"
    COL_BG = "#1a1a2e"; COL_TEXT = "#e0e0e0"

    metrics_plot = [
        ("win_rate", "승률 (%)", 100),
        ("cum_return", "누적 수익 (%)", 1),
        ("sharpe", "Sharpe Ratio", 1),
    ]
    for ax, (col, title, mul) in zip(axes, metrics_plot):
        vals = df[col] * mul if col == "win_rate" else df[col]
        colors = [COL_UP if v >= 0 else COL_DOWN for v in vals]
        bars = ax.bar(df.index, vals, color=colors, alpha=0.85)
        ax.set_facecolor(COL_BG)
        ax.set_title(title, color=COL_TEXT, fontsize=11, fontweight="bold")
        ax.tick_params(colors=COL_TEXT, labelsize=8)
        for s in ax.spines.values():
            s.set_color("#333355")
        plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
        ax.axhline(0, color="#555577", lw=0.8)
        if col == "win_rate":
            ax.axhline(50, color="#aaaacc", lw=0.8, ls="--")
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2,
                    v + abs(vals.max()) * 0.02,
                    f"{v:.1f}", ha="center", va="bottom",
                    color=COL_TEXT, fontsize=8, fontweight="bold")

    fig.suptitle("📊  전체 모델 비교  (아웃오브샘플 백테스트)",
                 fontsize=14, fontweight="bold", color=COL_TEXT)
    path = os.path.join(CHART_DIR, "backtest_summary.png")
    plt.savefig(path, dpi=130, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    print(f"\n  📊 요약 차트: {path}")


# ══════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════

def run_backtest(symbol: str, interval: str, from_year: int) -> dict | None:
    print(f"\n{'='*54}")
    print(f"  {symbol}  {interval}  백테스트 (from {from_year})")
    print(f"{'='*54}")

    # 모델 로드
    try:
        model, feature_cols = load_model(symbol, interval)
        print(f"  ✅ 모델 로드: directional_{symbol}_{interval}.pkl")
    except FileNotFoundError as e:
        print(f"  ❌ {e}"); return None

    # 데이터 로드
    try:
        df = load_ohlcv(symbol, interval, from_year)
        print(f"  📥 데이터: {len(df):,}행  {df['datetime'].iloc[0]} ~ {df['datetime'].iloc[-1]}")
    except FileNotFoundError as e:
        print(f"  ❌ {e}"); return None

    # 피처 생성
    df = add_features(df)
    df = df.dropna(subset=feature_cols).reset_index(drop=True)
    print(f"  🔧 피처 완성: {len(df):,}행 × {len(feature_cols)}피처")

    if len(df) < 500:
        print(f"  ⚠️  데이터 부족 ({len(df)}행) — 스킵"); return None

    # 시뮬레이션
    trades = simulate_trades(df, model, feature_cols)
    metrics = calc_metrics(trades)

    # 출력
    print(f"\n  ── 결과 ──────────────────────────────────")
    print(f"  총 거래:    {metrics.get('n_trades', 0)}  (L:{metrics.get('n_long',0)}  S:{metrics.get('n_short',0)})")
    print(f"  승률:       {metrics.get('win_rate', 0)*100:.1f}%  (LONG {metrics.get('win_long',0)*100:.1f}%  SHORT {metrics.get('win_short',0)*100:.1f}%)")
    print(f"  누적 수익:  {metrics.get('cum_return', 0):.2f}%")
    print(f"  Sharpe:     {metrics.get('sharpe', 0):.3f}")
    print(f"  최대 낙폭:  {metrics.get('max_dd', 0):.2f}%")
    print(f"  TP/SL:      {metrics.get('tp_rate',0)*100:.1f}% / {metrics.get('sl_rate',0)*100:.1f}%")

    # 차트
    plot_single(trades, metrics, symbol, interval)

    # 거래 CSV 저장
    if not trades.empty:
        csv_path = os.path.join(MODEL_DIR, f"bt_trades_{symbol}_{interval}.csv")
        trades.to_csv(csv_path, index=False)
        print(f"  💾 거래 저장: {csv_path}")

    return {"label": f"{symbol}\n{interval}", "symbol": symbol, "interval": interval, **metrics}


def main():
    parser = argparse.ArgumentParser(description="DirectionalEnsemble 백테스트")
    parser.add_argument("--symbol",    default="BTCUSDT",
                        help="심볼 또는 all (BTCUSDT/ETHUSDT/…/all)")
    parser.add_argument("--interval",  default="1h",
                        help="봉 단위 또는 all (5m/1h/4h/1d/all)")
    parser.add_argument("--from_year", type=int, default=2024,
                        help="백테스트 시작 연도 (기본 2024)")
    args = parser.parse_args()

    symbols   = ALL_SYMBOLS   if args.symbol   == "all" else [args.symbol]
    intervals = ALL_INTERVALS if args.interval == "all" else [args.interval]

    print(f"\n{'#'*56}")
    print(f"  DirectionalEnsemble 아웃오브샘플 백테스트")
    print(f"  심볼:   {symbols}")
    print(f"  봉단위: {intervals}")
    print(f"  기간:   {args.from_year}년 ~")
    print(f"{'#'*56}")

    summary = []
    for sym in symbols:
        for ivl in intervals:
            result = run_backtest(sym, ivl, args.from_year)
            if result:
                summary.append(result)

    # 요약 출력
    print(f"\n\n{'='*56}  전체 요약")
    print(f"  {'모델':<20} {'거래':>5} {'승률':>7} {'누적수익':>9} {'Sharpe':>8} {'MDD':>7}")
    print(f"  {'-'*56}")
    for r in summary:
        label = f"{r['symbol']} {r['interval']}"
        print(f"  {label:<20} {r.get('n_trades',0):>5} "
              f"{r.get('win_rate',0)*100:>6.1f}% "
              f"{r.get('cum_return',0):>8.2f}% "
              f"{r.get('sharpe',0):>8.3f} "
              f"{r.get('max_dd',0):>6.2f}%")

    if len(summary) > 1:
        plot_summary(summary)

    print(f"\n✅ 백테스트 완료")


if __name__ == "__main__":
    main()
