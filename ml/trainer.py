"""
ml/trainer.py
워크포워드(Walk-Forward) 학습 & 평가

과적합 방지를 위해 항상 미래 데이터로만 검증:
  학습: [0 ~ split]  →  검증: [split ~ split+step]
  학습: [0 ~ split+step] → 검증: [split+step ~ ...]
  ...
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
from ml.models   import EnsembleModel, evaluate

DATA_FILE  = os.path.join(ROOT, "data", "btc_daily.csv")
MODEL_DIR  = os.path.join(ROOT, "ml", "saved_models")
CHART_DIR  = os.path.join(ROOT, "charts")
os.makedirs(MODEL_DIR, exist_ok=True)
os.makedirs(CHART_DIR, exist_ok=True)

# ── 파라미터 ──────────────────────────────────
HOLD_DAYS    = 3
THRESHOLD    = 0.01   # 수익 기준 (1%)
SIGNAL_PROB  = 0.60   # 매수 신호 확률 임계값
FEE_RATE     = 0.001
SLIPPAGE     = 0.0005
TRAIN_MONTHS = 36     # 초기 학습 기간 (개월)
STEP_MONTHS  = 3      # 워크포워드 스텝 (분기)


def load_data() -> tuple[pd.DataFrame, list[str]]:
    df = pd.read_csv(DATA_FILE)
    df = add_features(df)
    df = make_targets(df, hold_days=HOLD_DAYS, threshold=THRESHOLD)
    df = df.dropna(subset=["target_bin"]).reset_index(drop=True)
    feature_cols = get_feature_cols(df)

    # NaN 비율 높은 피처 제거
    nan_ratio = df[feature_cols].isna().mean()
    feature_cols = [c for c in feature_cols if nan_ratio[c] < 0.3]

    return df, feature_cols


def walk_forward_backtest(df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    """
    워크포워드 백테스트
    각 구간별로 학습→예측→기록
    """
    df["date"] = pd.to_datetime(df["date"])
    start_date = df["date"].min()
    init_end   = start_date + pd.DateOffset(months=TRAIN_MONTHS)

    results = []
    fold = 0

    current_end = init_end
    while current_end < df["date"].max() - pd.DateOffset(months=STEP_MONTHS):
        val_end = current_end + pd.DateOffset(months=STEP_MONTHS)

        train_mask = df["date"] < current_end
        val_mask   = (df["date"] >= current_end) & (df["date"] < val_end)

        if train_mask.sum() < 200 or val_mask.sum() < 20:
            current_end = val_end
            continue

        fold += 1
        X_tr = df.loc[train_mask, feature_cols]
        y_tr = df.loc[train_mask, "target_bin"]
        X_va = df.loc[val_mask,   feature_cols]
        y_va = df.loc[val_mask,   "target_bin"]

        print(f"  Fold {fold}: 학습 {train_mask.sum()}일 → 검증 {current_end.date()}~{val_end.date()}")

        model = EnsembleModel()
        model.fit(X_tr, y_tr, feature_cols, X_va, y_va)

        proba  = model.predict_proba(X_va)[:, 1]
        signal = (proba >= SIGNAL_PROB).astype(int)

        # 거래 수익 계산
        val_df = df.loc[val_mask].copy().reset_index(drop=True)
        val_df["signal"]  = signal
        val_df["proba"]   = proba

        fold_rets = []
        for i, row in val_df.iterrows():
            if row["signal"] != 1: continue
            fut_i = i + HOLD_DAYS
            if fut_i >= len(val_df): break
            entry = val_df.loc[i,     "close"] * (1 + SLIPPAGE)
            exit_ = val_df.loc[fut_i, "close"] * (1 - SLIPPAGE)
            ret   = (exit_ - entry) / entry - 2 * FEE_RATE
            fold_rets.append(ret)

        n_sig  = int(signal.sum())
        wr     = float((np.array(fold_rets) > 0).mean()) if fold_rets else 0.0
        avg_r  = float(np.mean(fold_rets))               if fold_rets else 0.0
        acc    = accuracy_safe(y_va.values, signal)

        results.append({
            "fold":        fold,
            "train_end":   str(current_end.date()),
            "val_start":   str(current_end.date()),
            "val_end":     str(val_end.date()),
            "train_size":  int(train_mask.sum()),
            "val_size":    int(val_mask.sum()),
            "n_signals":   n_sig,
            "win_rate":    round(wr, 4),
            "avg_return":  round(avg_r, 4),
            "accuracy":    round(acc, 4),
        })

        current_end = val_end

    return pd.DataFrame(results)


def accuracy_safe(y_true, y_pred):
    from sklearn.metrics import accuracy_score
    try:
        return accuracy_score(y_true, y_pred)
    except Exception:
        return 0.0


def train_final_model(df: pd.DataFrame, feature_cols: list[str]) -> EnsembleModel:
    """전체 데이터로 최종 모델 학습"""
    print("\n[최종 모델] 전체 데이터로 학습 중...")
    split = int(len(df) * 0.85)
    X_tr  = df.iloc[:split][feature_cols]
    y_tr  = df.iloc[:split]["target_bin"]
    X_va  = df.iloc[split:][feature_cols]
    y_va  = df.iloc[split:]["target_bin"]

    model = EnsembleModel()
    model.fit(X_tr, y_tr, feature_cols, X_va, y_va)

    model_path = os.path.join(MODEL_DIR, "ensemble_model.pkl")
    model.save(model_path)
    print(f"  모델 저장 → {model_path}")
    return model


def plot_results(wf_df: pd.DataFrame, df: pd.DataFrame, model: EnsembleModel, feature_cols: list[str]):
    """워크포워드 결과 시각화"""
    for font in ["NanumGothic", "DejaVu Sans"]:
        if font in {f.name for f in fm.fontManager.ttflist}:
            plt.rcParams["font.family"] = font
            break
    plt.rcParams["axes.unicode_minus"] = False

    BG = "#0d1117"; FG = "#e6edf3"; GRID = "#30363d"
    GREEN = "#2ecc71"; RED = "#e74c3c"; BLUE = "#3498db"; YELLOW = "#f1c40f"

    fig = plt.figure(figsize=(18, 20), facecolor=BG)
    fig.suptitle("ML 앙상블 모델 — 워크포워드 백테스트 결과",
                 fontsize=20, fontweight="bold", color=FG, y=0.98)
    gs = gridspec.GridSpec(3, 2, hspace=0.45, wspace=0.35,
                           top=0.95, bottom=0.04, left=0.08, right=0.97)

    def ax_style(ax, title):
        ax.set_facecolor(BG)
        ax.set_title(title, color=FG, fontsize=12, fontweight="bold", pad=10)
        ax.tick_params(colors=FG, labelsize=9)
        for sp in ax.spines.values(): sp.set_edgecolor(GRID)
        ax.grid(color=GRID, linewidth=0.5, linestyle="--", alpha=0.7)
        ax.xaxis.label.set_color(FG); ax.yaxis.label.set_color(FG)

    # ── 1. 폴드별 승률 & 신호수 ───────────────
    ax1 = fig.add_subplot(gs[0, :])
    ax_style(ax1, f"워크포워드 폴드별 승률 & 신호 수 (신호 임계값: {SIGNAL_PROB})")
    folds = wf_df["fold"].astype(str)
    x = np.arange(len(folds))
    w = 0.4
    colors = [GREEN if r >= 0.6 else RED for r in wf_df["win_rate"]]
    bars = ax1.bar(x, wf_df["win_rate"] * 100, w, color=colors, alpha=0.85, label="승률")
    ax2_twin = ax1.twinx()
    ax2_twin.plot(x, wf_df["n_signals"], "o--", color=YELLOW, linewidth=1.5,
                  markersize=6, label="신호수")
    ax2_twin.set_ylabel("신호 발생 수", color=YELLOW)
    ax2_twin.tick_params(colors=YELLOW)
    ax1.axhline(60, color=RED, linewidth=1.2, linestyle=":", alpha=0.8)
    ax1.set_xticks(x)
    ax1.set_xticklabels([f"Fold{f}\n({s}~{e})"
                          for f, s, e in zip(wf_df["fold"],
                                              [v[:7] for v in wf_df["val_start"]],
                                              [v[:7] for v in wf_df["val_end"]])],
                         fontsize=8)
    ax1.set_ylabel("승률 (%)")
    ax1.set_ylim(0, 100)
    for bar, v in zip(bars, wf_df["win_rate"]):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                 f"{v*100:.0f}%", ha="center", color=FG, fontsize=9, fontweight="bold")

    # ── 2. 폴드별 평균 수익률 ─────────────────
    ax3 = fig.add_subplot(gs[1, 0])
    ax_style(ax3, "폴드별 평균 수익률 (%)")
    c3 = [GREEN if v >= 0 else RED for v in wf_df["avg_return"]]
    ax3.bar(range(len(wf_df)), wf_df["avg_return"] * 100, color=c3, alpha=0.85)
    ax3.axhline(0, color=FG, linewidth=0.8)
    ax3.set_xlabel("Fold")
    ax3.set_ylabel("평균 수익률 (%)")

    # ── 3. 피처 중요도 (XGBoost) ───────────────
    ax4 = fig.add_subplot(gs[1, 1])
    ax_style(ax4, "XGBoost 피처 중요도 (Top 15)")
    imp = model.xgb.feature_importance(15)
    imp_s = imp.sort_values("importance")
    colors4 = [BLUE if i < 5 else "#5dade2" for i in range(len(imp_s))]
    ax4.barh(range(len(imp_s)), imp_s["importance"], color=colors4, alpha=0.85)
    ax4.set_yticks(range(len(imp_s)))
    ax4.set_yticklabels(imp_s["feature"].str[:25], fontsize=8)
    ax4.set_xlabel("Feature Importance")

    # ── 4. 전체 확률 분포 ─────────────────────
    ax5 = fig.add_subplot(gs[2, 0])
    ax_style(ax5, "매수 확률 분포 (전체 데이터)")
    X_all = df[feature_cols]
    proba_all = model.predict_proba(X_all)[:, 1]
    proba_clean = proba_all[~np.isnan(proba_all)]
    ax5.hist(proba_clean, bins=50, color=BLUE, alpha=0.8, edgecolor=GRID)
    ax5.axvline(SIGNAL_PROB, color=YELLOW, linewidth=2, linestyle="--",
                label=f"신호 임계값 ({SIGNAL_PROB})")
    ax5.set_xlabel("매수 확률")
    ax5.set_ylabel("빈도")
    ax5.legend(facecolor=BG, edgecolor=GRID, labelcolor=FG, fontsize=9)
    n_signals = (proba_clean >= SIGNAL_PROB).sum()
    ax5.text(0.97, 0.95, f"신호 {n_signals}회\n전체 {len(proba_clean)}일",
             transform=ax5.transAxes, ha="right", va="top", color=FG, fontsize=10)

    # ── 5. 워크포워드 누적 성과 요약 ──────────
    ax6 = fig.add_subplot(gs[2, 1])
    ax6.set_facecolor(BG)
    ax6.axis("off")
    ax6.set_title("워크포워드 종합 성과", color=FG, fontsize=12,
                  fontweight="bold", pad=10)
    for sp in ax6.spines.values(): sp.set_edgecolor(GRID)

    total_signals = wf_df["n_signals"].sum()
    avg_wr   = wf_df[wf_df["n_signals"] > 0]["win_rate"].mean()
    avg_ret  = wf_df[wf_df["n_signals"] > 0]["avg_return"].mean()
    good_folds = (wf_df["win_rate"] >= 0.60).sum()

    lines = [
        ("총 Fold 수",          f"{len(wf_df)}회"),
        ("총 신호 발생",        f"{total_signals}회"),
        ("평균 승률",           f"{avg_wr*100:.1f}%"),
        ("평균 수익률",         f"{avg_ret*100:.2f}%/거래"),
        ("60%+ 달성 Fold",      f"{good_folds}/{len(wf_df)}"),
        ("신호 임계값",         f"{SIGNAL_PROB} (확률)"),
        ("수수료 반영",         "0.1% + 슬리피지 0.05%"),
    ]
    y_p = 0.85
    for label, val in lines:
        ax6.text(0.05, y_p, f"{label}:", transform=ax6.transAxes,
                 fontsize=10, va="center", color=GRID)
        ax6.text(0.60, y_p, val, transform=ax6.transAxes,
                 fontsize=10, va="center", color=GREEN if "%" in val and "0." not in val else FG,
                 fontweight="bold")
        y_p -= 0.12

    out = os.path.join(CHART_DIR, "ml_backtest.png")
    plt.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close()
    print(f"  차트 저장 → {out}")


def run():
    print("=" * 60)
    print("  ML 앙상블 모델 — 워크포워드 학습 & 검증")
    print("=" * 60)

    print("\n[1/4] 데이터 & 피처 로딩...")
    df, feature_cols = load_data()
    print(f"  샘플: {len(df)}개  피처: {len(feature_cols)}개")
    print(f"  매수 비율: {df['target_bin'].mean()*100:.1f}%")

    print("\n[2/4] 워크포워드 백테스트...")
    wf_df = walk_forward_backtest(df, feature_cols)
    if wf_df.empty:
        print("[경고] 워크포워드 결과 없음")
        return

    print("\n  [워크포워드 요약]")
    print(wf_df[["fold","val_start","val_end","n_signals","win_rate","avg_return"]].to_string(index=False))

    print("\n[3/4] 최종 모델 학습...")
    model = train_final_model(df, feature_cols)

    # 피처 컬럼 저장
    with open(os.path.join(MODEL_DIR, "feature_cols.pkl"), "wb") as f:
        pickle.dump(feature_cols, f)

    print("\n[4/4] 결과 시각화...")
    plot_results(wf_df, df, model, feature_cols)

    # 최종 평가
    print("\n" + "=" * 60)
    print("  최종 결과 요약")
    print("=" * 60)
    total_sig = wf_df["n_signals"].sum()
    avg_wr    = wf_df[wf_df["n_signals"] > 0]["win_rate"].mean()
    avg_ret   = wf_df[wf_df["n_signals"] > 0]["avg_return"].mean()
    good      = (wf_df["win_rate"] >= 0.60).sum()

    print(f"  워크포워드 Fold:  {len(wf_df)}개")
    print(f"  총 신호 발생:     {total_sig}회")
    print(f"  평균 승률:        {avg_wr*100:.1f}%")
    print(f"  평균 수익률:      {avg_ret*100:.2f}%/거래")
    print(f"  60%+ 달성:        {good}/{len(wf_df)} Fold")

    if avg_wr >= 0.55 and total_sig >= 10:
        verdict = "✅ ML 모델 유효 — 실전 진행 권장"
    else:
        verdict = "⚠️  추가 튜닝 필요"
    print(f"\n  판정: {verdict}")
    print("=" * 60)

    return model, feature_cols, wf_df


if __name__ == "__main__":
    run()
