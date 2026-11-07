"""
run_directional.py
방향성 ML 파이프라인 (롱/숏 동시 지원)

=====================================
  최종 목표: 위아래로 발라먹기
  - 롱: 상승 예측 → 매수
  - 숏: 하락 예측 → 공매도
  - 멀티코인 + 멀티 타임프레임 + 온라인학습
=====================================

실행:
  python run_directional.py            # 전체 파이프라인
  python run_directional.py --scan     # 유니버설 스캔만
  python run_directional.py --online   # 연속 학습 루프
"""

import os
import sys
import argparse
import warnings
import numpy as np
import pandas as pd
warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 유틸
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def banner(title: str):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 데이터 로드
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def load_all_data() -> pd.DataFrame:
    """멀티코인 통합 데이터 로드"""
    from ml.features        import add_features, make_directional_targets
    from ml.regime          import add_regime_features
    from ml.multi_timeframe import add_multi_timeframe_features

    # 합성 멀티코인 데이터
    data_path = os.path.join(ROOT, "data", "all_coins_daily.csv")
    if not os.path.exists(data_path):
        print("  멀티코인 데이터 없음 → 생성 중...")
        from generate_multi_coin_data import generate_all
        generate_all()

    print(f"  데이터 로드: {data_path}")
    df = pd.read_csv(data_path)

    # 심볼별로 피처 생성 후 합치기
    parts = []
    for sym, grp in df.groupby("symbol"):
        grp = grp.sort_values("date").reset_index(drop=True)
        grp = add_features(grp)
        grp = add_regime_features(grp)
        grp = add_multi_timeframe_features(grp)
        grp = make_directional_targets(grp)
        parts.append(grp)

    combined = pd.concat(parts, ignore_index=True)
    combined = combined.dropna(subset=["target_long", "target_short"])

    print(f"  샘플: {len(combined):,}개  "
          f"코인: {combined['symbol'].nunique()}개  "
          f"피처: 추가됨")
    print(f"  롱 타겟: {combined['target_long'].mean()*100:.1f}%  "
          f"숏 타겟: {combined['target_short'].mean()*100:.1f}%")

    return combined


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 방향성 워크포워드 백테스트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def walk_forward_directional(
    df:           pd.DataFrame,
    feature_cols: list,
    init_months:  int   = 18,
    step_months:  int   = 3,
    long_thr:     float = 0.60,   # 폴백 임계값 (캘리브레이션 실패 시)
    short_thr:    float = 0.58,
    fast_mode:    bool  = False,  # True = XGB+LGBM만 (TemporalXGB 스킵)
    use_regime:   bool  = True,   # True = 국면 필터 적용
    top_pct:      float = 5.0,    # 상위 N% 신호 선택 (0=disable)
) -> pd.DataFrame:
    """
    롱/숏 방향성 워크포워드 백테스트

    핵심 개선:
      - 학습 데이터 마지막 15%를 임계값 캘리브레이션에 사용
      - 승률(정밀도) 기준 임계값 최적화 (AUC 아님)
      - 국면 필터: BULL → LONG만, BEAR → SHORT만 (옵션)
      - XGB + LightGBM 앙상블

    성과 지표:
      - long_wr:     롱 신호 승률
      - short_wr:    숏 신호 승률
      - combined_wr: 롱+숏 합산 승률
      - n_long, n_short: 신호 수
    """
    from ml.models import DirectionalEnsemble

    # BTC 날짜 기준
    btc = df[df["symbol"] == "BTCUSDT"].copy() if "symbol" in df.columns else df.copy()
    btc["date"] = pd.to_datetime(btc["date"])
    btc = btc.sort_values("date").reset_index(drop=True)

    start_date  = btc["date"].min() + pd.DateOffset(months=init_months)
    end_date    = btc["date"].max() - pd.DateOffset(days=7)
    fold_starts = pd.date_range(start_date, end_date, freq=f"{step_months}MS")

    all_df = df.copy()
    all_df["date"] = pd.to_datetime(all_df["date"])

    has_regime = "regime" in all_df.columns

    rows = []
    for fold_i, val_start in enumerate(fold_starts, 1):
        val_end = val_start + pd.DateOffset(months=step_months)

        train_mask = all_df["date"] < val_start
        val_mask   = (all_df["date"] >= val_start) & (all_df["date"] < val_end)

        # 학습 데이터를 85%(모델학습) + 15%(임계값 캘리브레이션)으로 분리
        tr_idx  = all_df[train_mask].index
        split   = int(len(tr_idx) * 0.85)
        fit_idx = tr_idx[:split]
        cal_idx = tr_idx[split:]

        X_fit  = all_df.loc[fit_idx][feature_cols]
        y_lfit = all_df.loc[fit_idx]["target_long"]
        y_sfit = all_df.loc[fit_idx]["target_short"]

        X_cal  = all_df.loc[cal_idx][feature_cols]
        y_lcal = all_df.loc[cal_idx]["target_long"]
        y_scal = all_df.loc[cal_idx]["target_short"]

        X_val  = all_df[val_mask][feature_cols]
        y_lv   = all_df[val_mask]["target_long"]
        y_sv   = all_df[val_mask]["target_short"]
        ret_v  = all_df[val_mask]["target_ret"].fillna(0).values

        if len(X_fit) < 200 or len(X_val) < 10:
            continue

        print(f"  Fold {fold_i:2d}: 학습 {len(X_fit):,}개 "
              f"→ 검증 {val_start.date()}~{val_end.date()} ({len(X_val)}개)")

        try:
            # 모델 학습 (캘리브레이션 세트를 validation으로 전달 → early stopping)
            model = DirectionalEnsemble(fast_mode=fast_mode)
            model.fit(X_fit, y_lfit, y_sfit,
                      X_cal, y_lcal, y_scal,
                      feature_cols)

            # 임계값 캘리브레이션 (캘리브레이션 데이터 기준, 미래 누수 없음)
            if len(X_cal) >= 20:
                thr = model.find_precision_threshold(
                    X_cal, y_lcal, y_scal,
                    min_precision=0.54,
                    min_signals=3,
                )
                l_thr = thr["long"]
                s_thr = thr["short"]
            else:
                l_thr, s_thr = long_thr, short_thr

            lp = model.predict_proba_long(X_val)
            sp = model.predict_proba_short(X_val)

            # 국면 배열
            if use_regime and has_regime:
                regime_val = all_df[val_mask]["regime"].fillna(1).values
            else:
                regime_val = np.ones(len(lp)) * 1  # NEUTRAL everywhere

            # 신호 선택: 상위 퍼센타일 또는 임계값
            if top_pct > 0 and len(lp) > 20:
                from ml.signal_filter import top_percentile_signals
                # 캘리브레이션 임계값이 너무 높으면 신호 없음 방지
                # → 최솟값을 0.58로 제한 (의미있는 최소 확률)
                l_min = min(l_thr, 0.65)
                s_min = min(s_thr, 0.65)
                regime_arr = regime_val if use_regime and has_regime else None
                long_mask, short_mask = top_percentile_signals(
                    lp, sp,
                    regime=regime_arr,
                    pct=top_pct,
                    min_thr=max(l_min, s_min) * 0.95,  # 약간 완화
                )
            else:
                long_regime_ok  = (regime_val == 2) if use_regime and has_regime else np.ones(len(lp), bool)
                short_regime_ok = (regime_val == 0) if use_regime and has_regime else np.ones(len(sp), bool)
                long_mask  = (lp >= l_thr) & long_regime_ok
                short_mask = (sp >= s_thr) & short_regime_ok

            # 승률 계산 (수수료 0.2% 차감)
            fee = 0.002
            def wr_and_avg(mask, ret_arr, sign=1):
                if mask.sum() == 0:
                    return 0.0, 0.0
                sel_ret = ret_arr[mask] * sign - fee
                return float((sel_ret > 0).mean()), float(sel_ret.mean())

            long_wr,  long_avg  = wr_and_avg(long_mask,  ret_v,  1)
            short_wr, short_avg = wr_and_avg(short_mask, ret_v, -1)

            # 합산 승률
            combined_mask = long_mask | short_mask
            if combined_mask.sum() > 0:
                comb_ret = np.where(long_mask[combined_mask],
                                    ret_v[combined_mask],
                                    -ret_v[combined_mask]) - fee
                comb_wr  = float((comb_ret > 0).mean())
                comb_avg = float(comb_ret.mean())
            else:
                comb_wr = comb_avg = 0.0

            rows.append({
                "fold":          fold_i,
                "val_start":     val_start.date(),
                "val_end":       val_end.date(),
                "n_long":        int(long_mask.sum()),
                "n_short":       int(short_mask.sum()),
                "n_total":       int(combined_mask.sum()),
                "long_thr":      round(l_thr, 2),
                "short_thr":     round(s_thr, 2),
                "long_wr":       round(long_wr,  4),
                "short_wr":      round(short_wr, 4),
                "combined_wr":   round(comb_wr,  4),
                "combined_avg":  round(comb_avg, 4),
                "long_prob_avg": round(float(lp[long_mask].mean()) if long_mask.sum() > 0 else 0, 4),
                "short_prob_avg":round(float(sp[short_mask].mean()) if short_mask.sum() > 0 else 0, 4),
            })

        except Exception as e:
            print(f"    오류: {e}")
            import traceback; traceback.print_exc()
            continue

    return pd.DataFrame(rows)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. 최종 모델 학습 & 저장
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def train_and_save_directional(df: pd.DataFrame, feature_cols: list) -> dict:
    """전체 데이터로 최종 DirectionalEnsemble 학습 + 저장"""
    import pickle
    from ml.models import DirectionalEnsemble

    split = int(len(df) * 0.85)
    X_tr  = df.iloc[:split][feature_cols]
    y_lt  = df.iloc[:split]["target_long"]
    y_st  = df.iloc[:split]["target_short"]
    X_val = df.iloc[split:][feature_cols]
    y_lv  = df.iloc[split:]["target_long"]
    y_sv  = df.iloc[split:]["target_short"]

    print("  DirectionalEnsemble 최종 학습 (XGB + LightGBM + TemporalXGB)...")
    model = DirectionalEnsemble(fast_mode=False)
    model.fit(X_tr, y_lt, y_st, X_val, y_lv, y_sv, feature_cols)

    # 승률(정밀도) 기준 임계값 최적화
    thr = model.find_precision_threshold(
        X_val, y_lv, y_sv,
        min_precision=0.56,
        min_signals=5,
    )
    thresholds = {"long": thr["long"], "short": thr["short"]}
    print(f"  최적 임계값 — 롱: {thresholds['long']:.2f}  숏: {thresholds['short']:.2f}")

    # 저장
    save_dir = os.path.join(ROOT, "ml", "saved_models")
    os.makedirs(save_dir, exist_ok=True)

    model_path = os.path.join(save_dir, "directional_model.pkl")
    with open(model_path, "wb") as f:
        pickle.dump({"model": model, "feature_cols": feature_cols}, f)

    thr_path = os.path.join(save_dir, "directional_thresholds.json")
    import json
    with open(thr_path, "w") as f:
        json.dump(thresholds, f, indent=2)

    print(f"  모델 저장: {model_path}")
    print(f"  임계값 저장: {thr_path}")

    return {"model": model, "thresholds": thresholds, "feature_cols": feature_cols}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. 결과 시각화
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def plot_directional_results(wf_df: pd.DataFrame):
    """방향성 워크포워드 결과 차트"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    fig, axes = plt.subplots(3, 1, figsize=(14, 12))
    fig.patch.set_facecolor("#1a1a2e")
    for ax in axes:
        ax.set_facecolor("#16213e")
        ax.tick_params(colors="white")
        ax.xaxis.label.set_color("white")
        ax.yaxis.label.set_color("white")
        ax.title.set_color("white")
        for spine in ax.spines.values():
            spine.set_edgecolor("#444")

    x = np.arange(len(wf_df))
    labels = [str(r["val_start"])[:7] for _, r in wf_df.iterrows()]

    # ── 패널 1: 롱/숏 승률 ──────────────────────
    ax = axes[0]
    w = 0.35
    ax.bar(x - w/2, wf_df["long_wr"],  w, label="LONG 승률",     color="#00d4aa", alpha=0.85)
    ax.bar(x + w/2, wf_df["short_wr"], w, label="SHORT 승률",    color="#ff6b6b", alpha=0.85)
    ax.axhline(0.55, color="yellow",  ls="--", lw=1, label="55% 목표")
    ax.axhline(0.50, color="#888",    ls=":",  lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8, color="white")
    ax.set_ylabel("승률", color="white")
    ax.set_title("롱 / 숏 방향별 승률", color="white", pad=8)
    ax.set_ylim(0, 1.05)
    ax.legend(facecolor="#1a1a2e", labelcolor="white", fontsize=8)
    ax.grid(axis="y", alpha=0.2)

    # ── 패널 2: 합산 승률 + 신호 수 ─────────────
    ax  = axes[1]
    ax2 = ax.twinx()
    colors = ["#00d4aa" if v >= 0.55 else "#ff6b6b" if v < 0.50 else "#ffd700"
              for v in wf_df["combined_wr"]]
    ax.bar(x, wf_df["combined_wr"], color=colors, alpha=0.8, label="합산 승률")
    ax2.plot(x, wf_df["n_total"], color="cyan", marker="o", ms=4, lw=1.5, label="신호 수")
    ax.axhline(0.55, color="yellow", ls="--", lw=1)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8, color="white")
    ax.set_ylabel("합산 승률", color="white")
    ax2.set_ylabel("신호 수", color="cyan")
    ax2.tick_params(colors="cyan")
    ax.set_title("롱+숏 합산 승률 & 신호 횟수", color="white", pad=8)
    ax.set_ylim(0, 1.05)
    ax.grid(axis="y", alpha=0.2)

    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2,
              facecolor="#1a1a2e", labelcolor="white", fontsize=8)

    # ── 패널 3: 누적 수익 시뮬레이션 ─────────────
    ax = axes[2]
    # Equity curve 근사: avg_return * n_signals
    equity = 1.0
    equity_history = [equity]
    for _, row in wf_df.iterrows():
        n = max(row["n_total"], 1)
        r = row["combined_avg"]
        equity *= (1 + r) ** n
        equity_history.append(equity)

    color = "#00d4aa" if equity_history[-1] >= 1 else "#ff6b6b"
    ax.plot(range(len(equity_history)), equity_history,
            color=color, lw=2, marker="o", ms=4)
    ax.fill_between(range(len(equity_history)), equity_history, 1.0,
                    alpha=0.2, color=color)
    ax.axhline(1.0, color="#888", ls=":", lw=1)
    ax.set_title("누적 수익 시뮬레이션 ($1 → ...)", color="white", pad=8)
    ax.set_ylabel("자산 배수", color="white")
    ax.grid(alpha=0.2)
    final = equity_history[-1]
    ax.annotate(f"최종: {final:.2f}x ({(final-1)*100:+.1f}%)",
                xy=(len(equity_history)-1, final),
                xytext=(-40, 20), textcoords="offset points",
                color="white", fontsize=9,
                arrowprops=dict(arrowstyle="->", color="white"))

    plt.suptitle("방향성 ML 파이프라인 — 롱/숏 워크포워드",
                 color="white", fontsize=13, y=1.01)
    plt.tight_layout()

    os.makedirs(os.path.join(ROOT, "charts"), exist_ok=True)
    path = os.path.join(ROOT, "charts", "directional_results.png")
    plt.savefig(path, dpi=130, bbox_inches="tight", facecolor="#1a1a2e")
    plt.close()
    print(f"  차트 저장 → {path}")
    return path


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 메인
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def run_full_pipeline(args=None):
    banner("방향성 ML 파이프라인  (롱/숏 동시 지원 + 멀티 타임프레임)")

    # ── Step 1: 데이터 ──────────────────────────
    print("\n[1/5] 데이터 로드 & 피처 생성...")
    df = load_all_data()

    from ml.features import get_feature_cols
    feature_cols = get_feature_cols(df)
    feature_cols = [c for c in feature_cols if df[c].isna().mean() < 0.3]
    print(f"  사용 피처: {len(feature_cols)}개")

    # ── Step 2: 방향성 워크포워드 ────────────────
    fast = getattr(args, "fast", False)
    mode_str = "빠른(XGB+LGBM)" if fast else "전체(XGB+LGBM+TemporalXGB)"
    print(f"\n[2/5] 방향성 워크포워드 (롱/숏 동시 검증) — {mode_str}...")
    wf_df = walk_forward_directional(
        df, feature_cols,
        init_months=18, step_months=3,
        long_thr=0.60, short_thr=0.58,
        fast_mode=fast,
    )

    print("\n  [워크포워드 결과]")
    print(wf_df.to_string(index=False))

    # 요약 통계
    active_folds = wf_df[wf_df["n_total"] > 0]  # 신호 있는 폴드
    all_folds    = wf_df

    avg_long_wr  = active_folds["long_wr"].mean()     if not active_folds.empty else 0
    avg_short_wr = active_folds["short_wr"].mean()    if not active_folds.empty else 0
    avg_comb_wr  = active_folds["combined_wr"].mean() if not active_folds.empty else 0
    avg_all_wr   = all_folds["combined_wr"].mean()    # 0신호 폴드 포함
    n55plus      = (active_folds["combined_wr"] >= 0.55).sum()
    n60plus      = (active_folds["combined_wr"] >= 0.60).sum()

    print(f"\n  ─── 신호 있는 폴드 ({len(active_folds)}/{len(all_folds)}개) ───")
    print(f"  롱 평균 승률:    {avg_long_wr*100:.1f}%")
    print(f"  숏 평균 승률:    {avg_short_wr*100:.1f}%")
    print(f"  합산 평균 승률:  {avg_comb_wr*100:.1f}%  (전체평균: {avg_all_wr*100:.1f}%)")
    print(f"  55%+ Fold:      {n55plus}/{len(active_folds)}")
    print(f"  60%+ Fold:      {n60plus}/{len(active_folds)}")

    # ── Step 3: 최종 모델 학습 ───────────────────
    print("\n[3/5] 최종 DirectionalEnsemble 학습 & 저장...")
    result = train_and_save_directional(df, feature_cols)

    # ── Step 4: 유니버설 스캔 ────────────────────
    print("\n[4/5] 유니버설 스캐너 실행...")
    from coin.scanner import UniversalScanner
    scanner = UniversalScanner(
        long_thr = result["thresholds"]["long"],
        short_thr= result["thresholds"]["short"],
        top_n    = 5,
    )
    scanner.model        = result["model"]
    scanner.feature_cols = result["feature_cols"]

    scan_results = scanner.scan(
        kr_codes   = [],    # 주식은 다음 단계에서
        us_tickers = [],
    )
    scanner.print_report(scan_results)

    # ── Step 5: 차트 ─────────────────────────────
    print("\n[5/5] 결과 차트 생성...")
    if not wf_df.empty:
        plot_directional_results(wf_df)
    else:
        print("  워크포워드 데이터 없음 — 차트 생략")

    # ── 최종 결과 ─────────────────────────────────
    banner("최종 결과 요약")
    active = wf_df[wf_df["n_total"] > 0]
    active_wr = active["combined_wr"].mean() if not active.empty else 0

    print(f"  신호 있는 폴드: {len(active)}/{len(wf_df)}")
    print(f"  롱 평균 승률:   {avg_long_wr*100:.1f}%")
    print(f"  숏 평균 승률:   {avg_short_wr*100:.1f}%")
    print(f"  합산 승률 (활성폴드): {active_wr*100:.1f}%")
    print(f"  55%+ Fold:     {n55plus}/{len(active)}")
    print(f"  최적 임계값:   롱={result['thresholds']['long']:.2f}  "
          f"숏={result['thresholds']['short']:.2f}")
    print(f"  총 신호(롱):   {wf_df['n_long'].sum()}회")
    print(f"  총 신호(숏):   {wf_df['n_short'].sum()}회")

    comb_wr_pct = active_wr * 100
    if comb_wr_pct >= 60:
        verdict = "✅ 합산 60%+ — 실전 운용 권장"
    elif comb_wr_pct >= 55:
        verdict = "✅ 합산 55%+ — 페이퍼 트레이딩 권장"
    elif comb_wr_pct >= 50:
        verdict = "⚠ 합산 50%+ — 추가 개선 필요"
    else:
        verdict = "❌ 합산 50% 미만 — 전략 재검토 필요"

    print(f"\n  판정: {verdict}")
    print("=" * 60)

    # 결과 저장
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    wf_df.to_csv(os.path.join(ROOT, "results", "directional_wf.csv"), index=False)
    scan_results.to_csv(os.path.join(ROOT, "results", "latest_scan.csv"), index=False)

    return wf_df, scan_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan",   action="store_true", help="스캔만 실행")
    parser.add_argument("--online", action="store_true", help="연속 학습 루프")
    parser.add_argument("--fast",   action="store_true", help="XGB-only 빠른 모드 (TemporalXGB 스킵)")
    parser.add_argument("--interval", type=int, default=60, help="루프 간격(분)")
    parser.add_argument("--top",    type=int, default=5)
    args = parser.parse_args()

    if args.scan:
        from coin.scanner import UniversalScanner
        scanner = UniversalScanner(top_n=args.top)
        scanner.load_model()
        results = scanner.scan()
        scanner.print_report(results)
        scanner.save_report(results)

    elif args.online:
        from ml.online_learner import run_continuous_learning
        run_continuous_learning(interval_min=args.interval)

    else:
        run_full_pipeline(args)
