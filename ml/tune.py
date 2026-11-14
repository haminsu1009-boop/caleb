"""
ml/tune.py
신호 임계값 + 하이퍼파라미터 최적화

최적 임계값 탐색:
  - 검증 구간에서 여러 임계값(0.50 ~ 0.80) 테스트
  - 승률 × log(신호수) 복합 점수로 선택
  - 국면별(BULL/NEUTRAL/BEAR) 임계값 분리

하이퍼파라미터 최적화:
  - XGBoost: n_estimators, max_depth, learning_rate 탐색
  - Random Search (빠름) 또는 Optuna (정밀)
"""

import os
import sys
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def find_optimal_threshold(
    proba:  np.ndarray,
    y_true: np.ndarray,
    returns: np.ndarray,
    regime: np.ndarray = None,
    fee: float = 0.002,
    min_signals: int = 10,
) -> dict:
    """
    여러 임계값을 테스트해 최적값 반환

    Returns:
        {
          "overall":  float,          # 전체 최적 임계값
          "by_regime": {2:.., 1:.., 0:..}  # 국면별 임계값
        }
    """
    thresholds  = np.arange(0.50, 0.82, 0.02)
    best_score  = -np.inf
    best_thresh = 0.60
    rows = []

    for thr in thresholds:
        mask = proba >= thr
        n    = mask.sum()
        if n < min_signals:
            continue

        rets_sel = returns[mask] - fee
        wr   = (rets_sel > 0).mean()
        avg  = rets_sel.mean()
        # 복합 점수: 승률 우선, 신호수 패널티 낮게
        score = wr * 0.7 + avg * 10 * 0.3

        rows.append({"threshold": round(thr, 2), "n": n,
                     "win_rate": round(wr, 4), "avg_ret": round(avg, 4),
                     "score": round(score, 4)})
        if score > best_score:
            best_score  = score
            best_thresh = thr

    df_res = pd.DataFrame(rows)

    # 국면별 최적 임계값
    by_regime = {}
    if regime is not None:
        for reg_code in [2, 1, 0]:
            mask_reg = regime == reg_code
            if mask_reg.sum() < 30:
                by_regime[reg_code] = best_thresh
                continue
            p_reg = proba[mask_reg]
            y_reg = y_true[mask_reg]
            r_reg = returns[mask_reg]
            sub   = find_optimal_threshold(p_reg, y_reg, r_reg, fee=fee, min_signals=5)
            by_regime[reg_code] = sub["overall"]

    return {
        "overall":   round(best_thresh, 2),
        "by_regime": by_regime,
        "table":     df_res,
    }


def random_search_xgb(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val:   pd.DataFrame,
    y_val:   pd.Series,
    n_iter:  int = 20,
) -> dict:
    """XGBoost 랜덤 서치"""
    from xgboost import XGBClassifier
    from sklearn.metrics import roc_auc_score

    param_grid = {
        "n_estimators":     [200, 300, 400, 500],
        "max_depth":        [3, 4, 5, 6],
        "learning_rate":    [0.01, 0.02, 0.03, 0.05],
        "subsample":        [0.6, 0.7, 0.8, 0.9],
        "colsample_bytree": [0.5, 0.6, 0.7, 0.8],
        "min_child_weight": [1, 2, 3, 5],
        "reg_alpha":        [0.0, 0.05, 0.1, 0.2],
    }

    best_auc    = 0.0
    best_params = {}
    np.random.seed(42)

    for i in range(n_iter):
        params = {k: np.random.choice(v) for k, v in param_grid.items()}
        params["use_label_encoder"] = False
        params["eval_metric"]       = "logloss"
        params["random_state"]      = 42
        params["n_jobs"]            = -1

        model = XGBClassifier(**params)
        model.fit(X_train.fillna(0), y_train, verbose=False)
        proba = model.predict_proba(X_val.fillna(0))[:, 1]

        try:
            auc = roc_auc_score(y_val, proba)
        except Exception:
            auc = 0.5

        if auc > best_auc:
            best_auc    = auc
            best_params = params.copy()

        if (i + 1) % 5 == 0:
            print(f"    [{i+1}/{n_iter}] 최고 AUC: {best_auc:.4f}")

    best_params.pop("use_label_encoder", None)
    best_params.pop("eval_metric", None)
    best_params.pop("random_state", None)
    best_params.pop("n_jobs", None)
    return {"best_params": best_params, "best_auc": best_auc}


if __name__ == "__main__":
    import pickle
    from ml.features import add_features, make_targets, get_feature_cols
    from ml.regime   import add_regime_features

    df = pd.read_csv(os.path.join(ROOT, "data", "btc_daily.csv"))
    df = add_features(df)
    df = add_regime_features(df)
    df = make_targets(df)
    df = df.dropna().reset_index(drop=True)

    feature_cols = get_feature_cols(df)
    feature_cols = [c for c in feature_cols if df[c].isna().mean() < 0.3]

    split = int(len(df) * 0.8)
    with open(os.path.join(ROOT, "ml", "saved_models", "ensemble_model.pkl"), "rb") as f:
        model = pickle.load(f)

    X_val   = df.iloc[split:][feature_cols]
    y_val   = df.iloc[split:]["target_bin"].values
    returns = df.iloc[split:]["target_ret"].fillna(0).values
    regime  = df.iloc[split:]["regime"].values
    proba   = model.predict_proba(X_val)[:, 1]

    valid   = ~np.isnan(proba)
    result  = find_optimal_threshold(
        proba[valid], y_val[valid], returns[valid], regime[valid]
    )

    print(f"전체 최적 임계값: {result['overall']}")
    if result["by_regime"]:
        labels = {2: "BULL", 1: "NEUTRAL", 0: "BEAR"}
        for code, thr in result["by_regime"].items():
            print(f"  {labels[code]}: {thr}")
    print("\n임계값별 성과:")
    print(result["table"].to_string(index=False))
