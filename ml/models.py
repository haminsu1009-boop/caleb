"""
ml/models.py
XGBoost + LSTM 앙상블 모델

XGBoost: 비선형 패턴 + 피처 중요도 해석 가능
LSTM:    시계열 순서 학습 (최근 N일 패턴)
Ensemble: 두 모델 확률 가중 평균
"""

import os
import pickle
import warnings
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, classification_report, roc_auc_score
from sklearn.calibration import CalibratedClassifierCV
from xgboost import XGBClassifier
warnings.filterwarnings("ignore")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# XGBoost 모델
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class XGBModel:
    def __init__(self):
        self.model = XGBClassifier(
            n_estimators     = 400,
            max_depth        = 5,
            learning_rate    = 0.03,
            subsample        = 0.8,
            colsample_bytree = 0.7,
            min_child_weight = 3,
            reg_alpha        = 0.1,
            reg_lambda       = 1.0,
            use_label_encoder= False,
            eval_metric      = "logloss",
            random_state     = 42,
            n_jobs           = -1,
        )
        self.scaler    = StandardScaler()
        self.feature_cols = None
        self.is_fitted = False

    def fit(self, X: pd.DataFrame, y: pd.Series,
            X_val: pd.DataFrame = None, y_val: pd.Series = None):
        self.feature_cols = list(X.columns)
        X_s = self.scaler.fit_transform(X.fillna(0))

        if X_val is not None and y_val is not None:
            X_val_s = self.scaler.transform(X_val.fillna(0))
            self.model.fit(
                X_s, y,
                eval_set=[(X_val_s, y_val)],
                verbose=False,
            )
        else:
            self.model.fit(X_s, y, verbose=False)

        self.is_fitted = True
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        X_s = self.scaler.transform(X[self.feature_cols].fillna(0))
        return self.model.predict_proba(X_s)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)

    def feature_importance(self, top_n: int = 20) -> pd.DataFrame:
        imp = pd.DataFrame({
            "feature":    self.feature_cols,
            "importance": self.model.feature_importances_,
        }).sort_values("importance", ascending=False)
        return imp.head(top_n)

    def save(self, path: str):
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @classmethod
    def load(cls, path: str) -> "XGBModel":
        with open(path, "rb") as f:
            return pickle.load(f)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LSTM 모델 (순수 NumPy 구현 — 의존성 없음)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class SimpleLSTM:
    """
    경량 LSTM 대신 Sliding Window + Gradient Boosting
    (TensorFlow 없이 동작하는 시계열 모델)

    최근 SEQ_LEN 일의 피처를 flatten해서 XGBoost에 넣는
    "Temporal XGBoost" 방식 — LSTM과 유사한 시계열 패턴 포착
    """
    SEQ_LEN = 20   # 최근 20일 시퀀스

    def __init__(self, feature_cols: list[str]):
        self.feature_cols = feature_cols
        self.model = XGBClassifier(
            n_estimators     = 300,
            max_depth        = 4,
            learning_rate    = 0.05,
            subsample        = 0.7,
            colsample_bytree = 0.6,
            reg_alpha        = 0.2,
            use_label_encoder= False,
            eval_metric      = "logloss",
            random_state     = 99,
            n_jobs           = -1,
        )
        self.scaler    = StandardScaler()
        self.is_fitted = False

    def _make_sequences(self, X: np.ndarray) -> np.ndarray:
        """각 시점 t에 대해 [t-SEQ_LEN+1 .. t] 구간 flatten"""
        n, f = X.shape
        out = []
        for i in range(self.SEQ_LEN - 1, n):
            seq = X[i - self.SEQ_LEN + 1 : i + 1]  # (SEQ_LEN, f)
            out.append(seq.flatten())
        return np.array(out)

    def fit(self, X: pd.DataFrame, y: pd.Series):
        X_arr = self.scaler.fit_transform(X[self.feature_cols].fillna(0))
        X_seq = self._make_sequences(X_arr)
        y_seq = y.values[self.SEQ_LEN - 1:]   # 앞 SEQ_LEN-1개 제거
        self.model.fit(X_seq, y_seq, verbose=False)
        self.is_fitted = True
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        X_arr = self.scaler.transform(X[self.feature_cols].fillna(0))
        X_seq = self._make_sequences(X_arr)
        proba = self.model.predict_proba(X_seq)
        # 앞 SEQ_LEN-1 행은 NaN 패딩
        pad   = np.full((self.SEQ_LEN - 1, proba.shape[1]), np.nan)
        return np.vstack([pad, proba])

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        proba = self.predict_proba(X)
        return (proba[:, 1] >= 0.5).astype(float)

    def save(self, path: str):
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @classmethod
    def load(cls, path: str) -> "SimpleLSTM":
        with open(path, "rb") as f:
            return pickle.load(f)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 앙상블 모델
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class EnsembleModel:
    """
    XGBoost(0.6) + TemporalXGB(0.4) 가중 앙상블
    두 모델이 서로 다른 각도로 패턴을 학습
    """
    def __init__(self, w_xgb: float = 0.6, w_lstm: float = 0.4):
        self.w_xgb  = w_xgb
        self.w_lstm = w_lstm
        self.xgb    = None
        self.lstm   = None
        self.is_fitted = False

    def fit(self, X: pd.DataFrame, y: pd.Series,
            feature_cols: list[str],
            X_val: pd.DataFrame = None, y_val: pd.Series = None):

        print("  XGBoost 학습 중...")
        self.xgb = XGBModel()
        self.xgb.fit(X[feature_cols], y, X_val[feature_cols] if X_val is not None else None, y_val)

        print("  Temporal-XGB(LSTM 대체) 학습 중...")
        self.lstm = SimpleLSTM(feature_cols)
        self.lstm.fit(X[feature_cols], y)

        self.is_fitted = True
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        p_xgb  = self.xgb.predict_proba(X)[:, 1]
        p_lstm = self.lstm.predict_proba(X)[:, 1]

        # LSTM NaN 처리
        valid = ~np.isnan(p_lstm)
        p_ens = np.where(valid,
                         self.w_xgb * p_xgb + self.w_lstm * p_lstm,
                         p_xgb)
        return np.column_stack([1 - p_ens, p_ens])

    def signal(self, X: pd.DataFrame, threshold: float = 0.60) -> np.ndarray:
        """
        임계값 초과 → 1(매수), 미만 → 0(관망)
        threshold 높을수록 신호 드물지만 정확도 ↑
        """
        proba = self.predict_proba(X)[:, 1]
        return (proba >= threshold).astype(int)

    def save(self, path: str):
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @classmethod
    def load(cls, path: str) -> "EnsembleModel":
        with open(path, "rb") as f:
            return pickle.load(f)


def evaluate(y_true: np.ndarray, proba: np.ndarray, label: str = "") -> dict:
    """모델 성능 평가"""
    pred = (proba >= 0.5).astype(int)
    valid = ~np.isnan(proba)
    y_true_v = np.array(y_true)[valid]
    proba_v  = proba[valid]
    pred_v   = pred[valid]

    acc  = accuracy_score(y_true_v, pred_v)
    try:
        auc = roc_auc_score(y_true_v, proba_v)
    except Exception:
        auc = 0.5

    wr   = pred_v[pred_v == 1].shape[0]  # dummy
    print(f"\n  [{label}]")
    print(f"  정확도: {acc*100:.2f}%  |  AUC: {auc:.4f}  |  예측 샘플: {valid.sum()}")
    print(classification_report(y_true_v, pred_v,
                                 target_names=["관망/매도", "매수"],
                                 zero_division=0))
    return {"acc": acc, "auc": auc, "n": valid.sum()}
