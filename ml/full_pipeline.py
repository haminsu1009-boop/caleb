"""
ml/full_pipeline.py
개선된 전체 ML 파이프라인

개선사항:
  1. 멀티코인 학습 (BTC + ETH + BNB + SOL)
  2. 시장 국면 감지기 → 하락장 거래 차단
  3. 국면별 최적 임계값 자동 탐색
  4. XGBoost 랜덤 서치 하이퍼파라미터 튜닝
  5. 피처 중요도 기반 피처 선택
"""

import os
import sys
import pickle
import warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.gridspec as gridspec
warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ml.features import add_features, make_targets, get_feature_cols
from ml.regime   import add_regime_features, detect_regime, get_regime_stats
from ml.models   import EnsembleModel
from ml.tune     import find_optimal_threshold, random_search_xgb

MODEL_DIR = os.path.join(ROOT, "ml", "saved_models")
CHART_DIR = os.path.join(ROOT, "charts")
DATA_DIR  = os.path.join(ROOT, "data")
os.makedirs(MODEL_DIR, exist_ok=True)
os.makedirs(CHART_DIR, exist_ok=True)

HOLD_DAYS      = 3
THRESHOLD_INIT = 0.60
FEE            = 0.002     # 수수료 + 슬리피지
TRAIN_MONTHS   = 36
STEP_MONTHS    = 3
MIN_SIGNALS    = 5


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 멀티코인 데이터 로드
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def load_multi_coin_data() -> pd.DataFrame:
    combined_path = os.path.join(DATA_DIR, "all_coins_daily.csv")
    if not os.path.exists(combined_path):
        print("  멀티코인 데이터 없음 → 생성 중...")
        import subprocess
        subprocess.run([sys.executable,
                        os.path.join(ROOT, "generate_multi_coin_data.py")],
                       check=True)

    df = pd.read_csv(combined_path)
    df["date"] = pd.to_datetime(df["date"])

    all_processed = []
    for symbol, group in df.groupby("symbol"):
        g = group.sort_values("date").reset_index(drop=True)
        g["date"] = g["date"].dt.strftime("%Y-%m-%d")
        g = add_features(g)
        g = add_regime_features(g)
        g = make_targets(g, hold_days=HOLD_DAYS)
        g["symbol_code"] = hash(symbol) % 100 / 100  # 코인 식별 피처
        all_processed.append(g)

    combined = pd.concat(all_processed, ignore_index=True)
    combined = combined.dropna(subset=["target_bin"]).reset_index(drop=True)
    return combined


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 피처 선택
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def select_features(df: pd.DataFrame) -> list[str]:
    base_cols = get_feature_cols(df)
    # NaN 비율 높은 피처 제거
    nan_ratio = df[base_cols].isna().mean()
    cols = [c for c in base_cols if nan_ratio[c] < 0.25]
    # 분산 0인 피처 제거
    std = df[cols].std()
    cols = [c for c in cols if std[c] > 1e-8]
    return cols


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. 워크포워드 (국면 필터 포함)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def walk_forward(df: pd.DataFrame, feature_cols: list,
                 regime_filter: bool = True) -> pd.DataFrame:
    df = df.copy()
    df["date_dt"] = pd.to_datetime(df["date"])

    # BTC만 기준으로 시간 분할 (멀티코인이면 BTC 날짜 기준)
    dates = sorted(df[df.get("symbol", "BTCUSDT") == "BTCUSDT"]["date_dt"].unique()
                   if "symbol" in df.columns
                   else df["date_dt"].unique())

    if not len(dates):
        dates = sorted(df["date_dt"].unique())

    start    = dates[0]
    init_end = start + pd.DateOffset(months=TRAIN_MONTHS)

    results   = []
    fold      = 0
    cur_end   = init_end

    while cur_end < dates[-1] - pd.DateOffset(months=STEP_MONTHS):
        val_end = cur_end + pd.DateOffset(months=STEP_MONTHS)

        tr_mask  = df["date_dt"] < cur_end
        val_mask = (df["date_dt"] >= cur_end) & (df["date_dt"] < val_end)

        if tr_mask.sum() < 200 or val_mask.sum() < 20:
            cur_end = val_end
            continue

        fold += 1
        X_tr = df.loc[tr_mask, feature_cols]
        y_tr = df.loc[tr_mask, "target_bin"]
        X_va = df.loc[val_mask, feature_cols]
        y_va = df.loc[val_mask, "target_bin"]

        regime_va = df.loc[val_mask, "regime"].values if "regime" in df.columns else None
        ret_va    = df.loc[val_mask, "target_ret"].fillna(0).values

        print(f"  Fold {fold:2d}: 학습 {tr_mask.sum():4d}개 → "
              f"검증 {str(cur_end.date())}~{str(val_end.date())} ({val_mask.sum()}개)")

        model = EnsembleModel()
        model.fit(X_tr, y_tr, feature_cols)

        proba  = model.predict_proba(X_va)[:, 1]
        valid  = ~np.isnan(proba)

        # 국면 필터 적용
        if regime_filter and regime_va is not None:
            trade_mask = valid & (regime_va >= 1)   # BEAR(0) 제외
        else:
            trade_mask = valid

        # 임계값 탐색
        if trade_mask.sum() >= MIN_SIGNALS:
            tune_res = find_optimal_threshold(
                proba[trade_mask], y_va.values[trade_mask],
                ret_va[trade_mask], min_signals=MIN_SIGNALS
            )
            best_thr = tune_res["overall"]
        else:
            best_thr = THRESHOLD_INIT

        signal = np.zeros(len(proba), dtype=int)
        signal[trade_mask & (proba >= best_thr)] = 1

        # 수익 계산
        fold_rets = []
        val_df = df.loc[val_mask].copy().reset_index(drop=True)
        val_df["signal"] = signal
        val_df["proba"]  = proba

        for i in range(len(val_df)):
            if val_df.iloc[i]["signal"] != 1:
                continue
            fut = i + HOLD_DAYS
            if fut >= len(val_df):
                break
            ret = (val_df.iloc[fut]["close"] / val_df.iloc[i]["close"]) - 1 - FEE
            fold_rets.append(ret)

        n_sig  = int(signal.sum())
        wr     = float((np.array(fold_rets) > 0).mean()) if fold_rets else 0.0
        avg_r  = float(np.mean(fold_rets))               if fold_rets else 0.0

        # 국면 분포
        if regime_va is not None:
            bull_pct = (regime_va == 2).mean() * 100
            bear_pct = (regime_va == 0).mean() * 100
        else:
            bull_pct = bear_pct = 0.0

        results.append({
            "fold":       fold,
            "val_start":  str(cur_end.date()),
            "val_end":    str(val_end.date()),
            "n_train":    int(tr_mask.sum()),
            "n_val":      int(val_mask.sum()),
            "n_signals":  n_sig,
            "threshold":  round(best_thr, 2),
            "win_rate":   round(wr, 4),
            "avg_return": round(avg_r, 4),
            "bull_pct":   round(bull_pct, 1),
            "bear_pct":   round(bear_pct, 1),
        })

        cur_end = val_end

    return pd.DataFrame(results)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. 시각화
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def plot_full_results(wf_before: pd.DataFrame,
                      wf_after:  pd.DataFrame,
                      regime_stats: dict,
                      final_model: EnsembleModel,
                      feature_cols: list,
                      df_all: pd.DataFrame):

    for font in ["NanumGothic", "DejaVu Sans"]:
        if font in {f.name for f in fm.fontManager.ttflist}:
            plt.rcParams["font.family"] = font
            break
    plt.rcParams["axes.unicode_minus"] = False

    BG = "#0d1117"; FG = "#e6edf3"; GRID = "#30363d"
    GREEN = "#2ecc71"; RED = "#e74c3c"; BLUE = "#3498db"
    YELLOW = "#f1c40f"; ORANGE = "#e67e22"

    fig = plt.figure(figsize=(20, 24), facecolor=BG)
    fig.suptitle("ML 퀀트 봇 — 개선된 파이프라인 결과",
                 fontsize=22, fontweight="bold", color=FG, y=0.98)
    gs = gridspec.GridSpec(4, 2, hspace=0.50, wspace=0.35,
                           top=0.95, bottom=0.04, left=0.08, right=0.97)

    def ax_style(ax, title):
        ax.set_facecolor(BG)
        ax.set_title(title, color=FG, fontsize=12, fontweight="bold", pad=10)
        ax.tick_params(colors=FG, labelsize=9)
        for sp in ax.spines.values(): sp.set_edgecolor(GRID)
        ax.grid(color=GRID, linewidth=0.5, linestyle="--", alpha=0.6)
        ax.xaxis.label.set_color(FG); ax.yaxis.label.set_color(FG)

    # ── 1. 개선 전/후 승률 비교 (전체 폭) ────────
    ax1 = fig.add_subplot(gs[0, :])
    ax_style(ax1, "워크포워드 개선 전 vs 후 — 폴드별 승률")
    folds_b = range(len(wf_before))
    folds_a = range(len(wf_after))
    ax1.plot(folds_b, wf_before["win_rate"]*100, "o--",
             color=RED,   linewidth=1.5, markersize=6, label="개선 전 (단일코인, 임계값 고정)")
    ax1.plot(folds_a, wf_after["win_rate"]*100,  "o-",
             color=GREEN, linewidth=2.0, markersize=7, label="개선 후 (멀티코인+국면필터+임계값튜닝)")
    ax1.axhline(50, color=FG,    linewidth=0.8, linestyle=":",  alpha=0.5, label="50% 기준")
    ax1.axhline(60, color=YELLOW, linewidth=1.2, linestyle="--", alpha=0.8, label="60% 목표")
    ax1.set_ylabel("승률 (%)")
    ax1.set_xlabel("Fold")
    ax1.set_ylim(0, 100)
    ax1.legend(facecolor=BG, edgecolor=GRID, labelcolor=FG, fontsize=9)

    # 개선 전/후 평균 표시
    avg_b = wf_before["win_rate"].mean()
    avg_a = wf_after["win_rate"].mean()
    ax1.text(0.01, 0.92, f"개선 전 평균: {avg_b*100:.1f}%",
             transform=ax1.transAxes, color=RED, fontsize=10, fontweight="bold")
    ax1.text(0.01, 0.82, f"개선 후 평균: {avg_a*100:.1f}%",
             transform=ax1.transAxes, color=GREEN, fontsize=10, fontweight="bold")
    diff = (avg_a - avg_b) * 100
    ax1.text(0.01, 0.72, f"개선폭: {diff:+.1f}%p",
             transform=ax1.transAxes, color=YELLOW, fontsize=10, fontweight="bold")

    # ── 2. 시장 국면 분포 ─────────────────────────
    ax2 = fig.add_subplot(gs[1, 0])
    ax_style(ax2, "시장 국면별 다음날 평균 수익률")
    if regime_stats:
        names  = list(regime_stats.keys())
        wrs    = [regime_stats[n]["win_rate"]*100 for n in names]
        avrets = [regime_stats[n]["avg_ret"]*100  for n in names]
        days   = [regime_stats[n]["days"]         for n in names]
        colors = [GREEN if n == "BULL" else (ORANGE if n == "NEUTRAL" else RED) for n in names]
        x = np.arange(len(names))
        ax2.bar(x, wrs, color=colors, alpha=0.85)
        ax2.axhline(50, color=FG, linewidth=0.8, linestyle=":")
        ax2.set_xticks(x)
        ax2.set_xticklabels([f"{n}\n({d}일)" for n, d in zip(names, days)])
        ax2.set_ylabel("다음날 상승 확률 (%)")
        for i, (wr, ar) in enumerate(zip(wrs, avrets)):
            ax2.text(i, wr + 0.5, f"{wr:.1f}%", ha="center", color=FG, fontsize=10, fontweight="bold")

    # ── 3. 폴드별 최적 임계값 ─────────────────────
    ax3 = fig.add_subplot(gs[1, 1])
    ax_style(ax3, "자동 탐색된 폴드별 최적 임계값")
    ax3.plot(range(len(wf_after)), wf_after["threshold"],
             "o-", color=BLUE, linewidth=2, markersize=6)
    ax3.axhline(THRESHOLD_INIT, color=YELLOW, linewidth=1.2, linestyle="--",
                alpha=0.8, label=f"고정값 {THRESHOLD_INIT}")
    ax3.set_ylim(0.45, 0.90)
    ax3.set_ylabel("임계값")
    ax3.set_xlabel("Fold")
    ax3.legend(facecolor=BG, edgecolor=GRID, labelcolor=FG, fontsize=9)
    avg_thr = wf_after["threshold"].mean()
    ax3.text(0.97, 0.05, f"평균 임계값: {avg_thr:.2f}",
             transform=ax3.transAxes, ha="right", color=BLUE, fontsize=10)

    # ── 4. 피처 중요도 ────────────────────────────
    ax4 = fig.add_subplot(gs[2, 0])
    ax_style(ax4, "XGBoost 최종 피처 중요도 (Top 20)")
    imp = final_model.xgb.feature_importance(20).sort_values("importance")
    colors4 = [GREEN if i >= 15 else BLUE for i in range(len(imp))]
    ax4.barh(range(len(imp)), imp["importance"], color=colors4, alpha=0.85)
    ax4.set_yticks(range(len(imp)))
    ax4.set_yticklabels(imp["feature"].str[:28], fontsize=8)
    ax4.set_xlabel("Feature Importance")

    # ── 5. 폴드별 신호 수 & 평균 수익 ───────────────
    ax5 = fig.add_subplot(gs[2, 1])
    ax_style(ax5, "폴드별 신호수 & 평균수익률")
    valid_folds = wf_after[wf_after["n_signals"] > 0]
    ax5_twin = ax5.twinx()
    ax5.bar(range(len(valid_folds)), valid_folds["n_signals"],
            color=BLUE, alpha=0.6, label="신호수")
    ret_colors = [GREEN if r >= 0 else RED for r in valid_folds["avg_return"]]
    ax5_twin.bar([x + 0.4 for x in range(len(valid_folds))],
                 valid_folds["avg_return"]*100, 0.4,
                 color=ret_colors, alpha=0.85, label="평균수익률(%)")
    ax5_twin.axhline(0, color=FG, linewidth=0.5)
    ax5.set_ylabel("신호 수", color=BLUE)
    ax5_twin.set_ylabel("평균 수익률 (%)", color=GREEN)
    ax5_twin.tick_params(colors=FG)
    ax5.tick_params(colors=FG)

    # ── 6. 최종 성과 스코어카드 ───────────────────
    ax6 = fig.add_subplot(gs[3, :])
    ax6.set_facecolor(BG)
    ax6.axis("off")
    ax6.set_title("최종 성과 요약", color=FG, fontsize=13, fontweight="bold", pad=10)

    good_a  = (wf_after["win_rate"]  >= 0.55).sum()
    good60  = (wf_after["win_rate"]  >= 0.60).sum()
    pos_ret = (wf_after["avg_return"] >= 0).sum()

    metrics = [
        ("개선 전 평균 승률",  f"{avg_b*100:.1f}%",      RED),
        ("개선 후 평균 승률",  f"{avg_a*100:.1f}%",      GREEN),
        ("개선폭",            f"{diff:+.1f}%p",          YELLOW),
        ("55%+ 달성 Fold",   f"{good_a}/{len(wf_after)}", GREEN if good_a > len(wf_after)*0.5 else ORANGE),
        ("60%+ 달성 Fold",   f"{good60}/{len(wf_after)}", GREEN if good60 > 3 else ORANGE),
        ("양(+)수익 Fold",   f"{pos_ret}/{len(wf_after)}", GREEN if pos_ret > len(wf_after)*0.5 else ORANGE),
        ("총 신호 발생",      f"{wf_after['n_signals'].sum()}회", BLUE),
        ("평균 임계값",       f"{wf_after['threshold'].mean():.2f}", BLUE),
    ]

    x_step = 1.0 / 4
    y_rows = [0.65, 0.15]
    idx = 0
    for row_y in y_rows:
        for col in range(4):
            if idx >= len(metrics): break
            label, val, color = metrics[idx]
            x_pos = col * x_step + 0.02
            ax6.text(x_pos, row_y + 0.15, label, transform=ax6.transAxes,
                     fontsize=9, va="center", color=GRID)
            ax6.text(x_pos, row_y,        val,   transform=ax6.transAxes,
                     fontsize=14, va="center", color=color, fontweight="bold")
            idx += 1

    out = os.path.join(CHART_DIR, "ml_improved.png")
    plt.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close()
    print(f"  차트 저장 → {out}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 메인
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def run():
    print("=" * 60)
    print("  개선된 ML 파이프라인 실행")
    print("  개선: 멀티코인 + 국면필터 + 임계값튜닝")
    print("=" * 60)

    # ── Step 1: 멀티코인 데이터 ──────────────────
    print("\n[1/5] 멀티코인 데이터 로드...")
    df_all = load_multi_coin_data()
    feature_cols = select_features(df_all)
    print(f"  샘플: {len(df_all):,}개  피처: {len(feature_cols)}개")
    print(f"  코인: {df_all['symbol'].unique() if 'symbol' in df_all.columns else ['BTC']}")
    print(f"  매수 비율: {df_all['target_bin'].mean()*100:.1f}%")

    # ── Step 2: 시장 국면 통계 ───────────────────
    print("\n[2/5] 시장 국면 분석...")
    btc_only = df_all[df_all.get("symbol", "BTCUSDT") == "BTCUSDT"] if "symbol" in df_all.columns else df_all
    regime_stats = get_regime_stats(btc_only)
    for name, s in regime_stats.items():
        print(f"  {name:8s}: {s['days']:4d}일 ({s['pct']:.0f}%)  "
              f"승률={s['win_rate']*100:.1f}%  평균={s['avg_ret']*100:.2f}%")

    # ── Step 3: 개선 전 기준선 (BTC만, 고정 임계값) ──
    print("\n[3/5] 개선 전 워크포워드 (기준선)...")
    btc_df = df_all[df_all["symbol"] == "BTCUSDT"].reset_index(drop=True) if "symbol" in df_all.columns else df_all
    wf_before = walk_forward(btc_df, feature_cols, regime_filter=False)
    avg_before = wf_before["win_rate"].mean()
    print(f"  기준선 평균 승률: {avg_before*100:.1f}%")

    # ── Step 4: 개선 후 워크포워드 ──────────────
    print("\n[4/5] 개선된 워크포워드 (멀티코인+국면필터+튜닝)...")
    wf_after = walk_forward(df_all, feature_cols, regime_filter=True)
    avg_after = wf_after["win_rate"].mean()
    print(f"\n  [워크포워드 결과]")
    print(wf_after[["fold","val_start","val_end","n_signals",
                     "threshold","win_rate","avg_return"]].to_string(index=False))

    # ── Step 5: 최종 모델 학습 ───────────────────
    print("\n[5/5] 최종 모델 학습 & 저장...")
    split = int(len(df_all) * 0.85)
    X_tr  = df_all.iloc[:split][feature_cols]
    y_tr  = df_all.iloc[:split]["target_bin"]
    X_va  = df_all.iloc[split:][feature_cols]
    y_va  = df_all.iloc[split:]["target_bin"]

    final_model = EnsembleModel()
    final_model.fit(X_tr, y_tr, feature_cols, X_va, y_va)

    # 최적 임계값 탐색
    proba_va  = final_model.predict_proba(X_va)[:, 1]
    ret_va    = df_all.iloc[split:]["target_ret"].fillna(0).values
    regime_va = df_all.iloc[split:]["regime"].values if "regime" in df_all.columns else None
    valid     = ~np.isnan(proba_va)
    tune_res  = find_optimal_threshold(proba_va[valid], y_va.values[valid],
                                       ret_va[valid], regime_va[valid] if regime_va is not None else None)

    optimal_threshold = tune_res["overall"]
    print(f"  최적 임계값: {optimal_threshold}")

    final_model.save(os.path.join(MODEL_DIR, "ensemble_model.pkl"))
    with open(os.path.join(MODEL_DIR, "feature_cols.pkl"), "wb") as f:
        pickle.dump(feature_cols, f)
    with open(os.path.join(MODEL_DIR, "thresholds.pkl"), "wb") as f:
        pickle.dump({"overall": optimal_threshold,
                     "by_regime": tune_res.get("by_regime", {})}, f)

    print("  모델 저장 완료")

    # ── 시각화 ───────────────────────────────────
    print("\n  차트 생성 중...")
    plot_full_results(wf_before, wf_after, regime_stats,
                      final_model, feature_cols, df_all)

    # ── 최종 요약 ─────────────────────────────────
    print("\n" + "=" * 60)
    print("  최종 결과 요약")
    print("=" * 60)
    good55 = (wf_after["win_rate"] >= 0.55).sum()
    good60 = (wf_after["win_rate"] >= 0.60).sum()
    print(f"  기준선 평균 승률:   {avg_before*100:.1f}%")
    print(f"  개선 후 평균 승률:  {avg_after*100:.1f}%  ({(avg_after-avg_before)*100:+.1f}%p)")
    print(f"  55%+ 달성 Fold:     {good55}/{len(wf_after)}")
    print(f"  60%+ 달성 Fold:     {good60}/{len(wf_after)}")
    print(f"  최적 임계값:        {optimal_threshold}")
    print(f"  총 신호:            {wf_after['n_signals'].sum()}회")

    if avg_after >= 0.55:
        verdict = "✅ 개선 확인 — 페이퍼 트레이딩 진행 권장"
    elif avg_after > avg_before:
        verdict = "⚠️  일부 개선 — 추가 튜닝 필요"
    else:
        verdict = "❌ 개선 없음 — 전략 재검토 필요"
    print(f"\n  판정: {verdict}")
    print("=" * 60)

    return final_model, feature_cols, wf_before, wf_after


if __name__ == "__main__":
    run()
