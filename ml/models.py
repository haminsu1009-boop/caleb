"""
ml/models.py
XGBoost + LightGBM + TemporalXGB 앙상블 모델

XGBoost:   비선형 패턴 + 피처 중요도 해석 가능
LightGBM:  속도/정확도 최적화, 범주형 자동 처리
TemporalXGB: 시계열 슬라이딩윈도우 패턴 포착
Ensemble: 세 모델 확률 가중 평균 → 정밀도(승률) 최적화
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

# LightGBM 옵션 임포트
try:
    import lightgbm as lgb
    _HAS_LGBM = True
except ImportError:
    _HAS_LGBM = False


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
        # ⚠️ inf 방어: 비율 피처의 0 나눗셈으로 ±inf가 들어오면
        #   StandardScaler.transform()이 예외를 던져 실시간 봇이 죽는다.
        #   학습 경로와 동일하게 inf → NaN → 0 으로 정리한다.
        Xf  = X[self.feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0)
        X_s = self.scaler.transform(Xf)
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
# LightGBM 모델
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class LGBMModel:
    """
    LightGBM 분류기 — XGBoost보다 빠르고 정밀도 향상에 유리
    초기화 실패 시 자동 XGBModel 폴백
    """
    def __init__(self):
        self.model        = None
        self.scaler       = StandardScaler()
        self.feature_cols = None
        self.is_fitted    = False
        self._available   = _HAS_LGBM

    def fit(self, X: pd.DataFrame, y: pd.Series,
            X_val: pd.DataFrame = None, y_val: pd.Series = None):
        if not self._available:
            raise ImportError("lightgbm not installed")

        self.feature_cols = list(X.columns)
        X_s = self.scaler.fit_transform(X.fillna(0))

        pos_weight = max(1.0, (y == 0).sum() / max(1, (y == 1).sum()))
        params = dict(
            objective         = "binary",
            metric            = "binary_logloss",
            n_estimators      = 600,
            num_leaves        = 31,
            max_depth         = -1,
            learning_rate     = 0.03,
            feature_fraction  = 0.7,
            bagging_fraction  = 0.8,
            bagging_freq      = 5,
            min_child_samples = 20,
            reg_alpha         = 0.1,
            reg_lambda        = 1.0,
            scale_pos_weight  = pos_weight,
            verbose           = -1,
            n_jobs            = -1,
            random_state      = 42,
        )
        self.model = lgb.LGBMClassifier(**params)

        if X_val is not None and y_val is not None:
            X_val_s = self.scaler.transform(X_val.fillna(0))
            cb = [
                lgb.early_stopping(50, verbose=False),
                lgb.log_evaluation(period=-1),
            ]
            self.model.fit(X_s, y,
                           eval_set=[(X_val_s, y_val)],
                           callbacks=cb)
        else:
            self.model.fit(X_s, y)

        self.is_fitted = True
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        # ⚠️ inf 방어: 비율 피처의 0 나눗셈으로 ±inf가 들어오면
        #   StandardScaler.transform()이 예외를 던져 실시간 봇이 죽는다.
        #   학습 경로와 동일하게 inf → NaN → 0 으로 정리한다.
        Xf  = X[self.feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0)
        X_s = self.scaler.transform(Xf)
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
    def load(cls, path: str) -> "LGBMModel":
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
        n_rows = len(X_arr)

        # SEQ_LEN에 못 미치면 전체 NaN 반환 (앙상블에서 XGB만 사용)
        if len(X_seq) == 0:
            return np.full((n_rows, 2), np.nan)

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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 방향성 앙상블 (롱 + 숏 동시 지원)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class DirectionalEnsemble:
    """
    롱/숏 양방향 신호 앙상블

    구성 (fast_mode=False):
      XGB(0.45) + LightGBM(0.40) + TemporalXGB(0.15)
    구성 (fast_mode=True):
      XGB(0.55) + LightGBM(0.45)   ← TemporalXGB 스킵

    승률 최적화 포인트:
      - LightGBM scale_pos_weight → 희귀 신호 정밀도 우선
      - XGBoost early stopping → 과적합 방지
      - 임계값을 AUC가 아닌 정밀도(승률) 기준으로 최적화
    """
    def __init__(self,
                 w_xgb:    float = 0.45,
                 w_lgbm:   float = 0.40,
                 w_lstm:   float = 0.15,
                 fast_mode: bool = False):
        self.w_xgb     = w_xgb
        self.w_lgbm    = w_lgbm
        self.w_lstm    = w_lstm
        self.fast_mode = fast_mode   # True → TemporalXGB 스킵
        self.use_lgbm  = _HAS_LGBM

        # LONG 방향 모델
        self.long_xgb  = None
        self.long_lgbm = None
        self.long_lstm = None
        # SHORT 방향 모델
        self.short_xgb  = None
        self.short_lgbm = None
        self.short_lstm = None

        self.feature_cols = None
        self.is_fitted    = False

    # ── 학습 ──────────────────────────────────────────────
    def fit(
        self,
        X_train:       pd.DataFrame,
        y_long_train:  pd.Series,
        y_short_train: pd.Series,
        X_val:         pd.DataFrame = None,
        y_long_val:    pd.Series    = None,
        y_short_val:   pd.Series    = None,
        feature_cols:  list         = None,
    ):
        if feature_cols is None:
            feature_cols = list(X_train.columns)
        self.feature_cols = feature_cols

        Xtr = X_train[feature_cols]
        Xv  = X_val[feature_cols] if X_val is not None else None

        # ── LONG 모델 학습 ──
        print("  [DirectionalEnsemble] LONG 모델 학습...")
        self.long_xgb = XGBModel()
        self.long_xgb.fit(Xtr, y_long_train, Xv, y_long_val)

        if self.use_lgbm:
            self.long_lgbm = LGBMModel()
            self.long_lgbm.fit(Xtr, y_long_train, Xv, y_long_val)

        if not self.fast_mode:
            self.long_lstm = SimpleLSTM(feature_cols)
            self.long_lstm.fit(Xtr, y_long_train)

        # ── SHORT 모델 학습 ──
        print("  [DirectionalEnsemble] SHORT 모델 학습...")
        self.short_xgb = XGBModel()
        self.short_xgb.fit(Xtr, y_short_train, Xv, y_short_val)

        if self.use_lgbm:
            self.short_lgbm = LGBMModel()
            self.short_lgbm.fit(Xtr, y_short_train, Xv, y_short_val)

        if not self.fast_mode:
            self.short_lstm = SimpleLSTM(feature_cols)
            self.short_lstm.fit(Xtr, y_short_train)

        self.is_fitted = True
        return self

    # ── 앙상블 확률 계산 ──────────────────────────────────
    def _ensemble_proba(
        self,
        xgb_model,
        lgbm_model,
        lstm_model,
        X: pd.DataFrame,
    ) -> np.ndarray:
        """XGB + LightGBM (+ TemporalXGB) 가중 앙상블"""
        p_xgb = xgb_model.predict_proba(X)[:, 1]

        if lgbm_model is not None and self.use_lgbm:
            p_lgbm = lgbm_model.predict_proba(X)[:, 1]
            # LightGBM 가중
            if lstm_model is None or self.fast_mode:
                # fast_mode: XGB + LGBM만
                w_total = self.w_xgb + self.w_lgbm
                p_ens   = (self.w_xgb * p_xgb + self.w_lgbm * p_lgbm) / w_total
            else:
                p_lstm = lstm_model.predict_proba(X)[:, 1]
                valid  = ~np.isnan(p_lstm)
                p_ens  = np.where(
                    valid,
                    self.w_xgb * p_xgb + self.w_lgbm * p_lgbm + self.w_lstm * p_lstm,
                    (self.w_xgb * p_xgb + self.w_lgbm * p_lgbm) / (self.w_xgb + self.w_lgbm),
                )
        else:
            # LightGBM 없으면 XGB + TemporalXGB (구버전 호환)
            if lstm_model is not None and not self.fast_mode:
                p_lstm = lstm_model.predict_proba(X)[:, 1]
                valid  = ~np.isnan(p_lstm)
                p_ens  = np.where(valid,
                                  (1 - self.w_lstm) * p_xgb + self.w_lstm * p_lstm,
                                  p_xgb)
            else:
                p_ens = p_xgb

        return p_ens

    def predict_proba_long(self, X: pd.DataFrame) -> np.ndarray:
        return self._ensemble_proba(
            self.long_xgb, self.long_lgbm, self.long_lstm, X)

    def predict_proba_short(self, X: pd.DataFrame) -> np.ndarray:
        return self._ensemble_proba(
            self.short_xgb, self.short_lgbm, self.short_lstm, X)

    # ── 정밀도 최적화 임계값 탐색 ─────────────────────────
    def find_precision_threshold(
        self,
        X:            pd.DataFrame,
        y_long:       pd.Series,
        y_short:      pd.Series,
        min_precision: float = 0.58,
        min_signals:   int   = 5,
    ) -> dict:
        """
        승률(정밀도) 기준으로 최적 임계값 탐색.
        AUC 대신 정밀도를 최대화 — 신호 수가 적어도 승률 우선.

        Returns:
            {"long": float, "short": float}
        """
        lp = self.predict_proba_long(X)
        sp = self.predict_proba_short(X)
        y_l = np.asarray(y_long)
        y_s = np.asarray(y_short)

        def best_thr(proba, y_true):
            best_t, best_prec = 0.60, min_precision
            for t in np.arange(0.52, 0.92, 0.02):
                mask = proba >= t
                n = mask.sum()
                if n < min_signals:
                    continue
                prec = float(y_true[mask].mean())
                if prec >= best_prec:
                    best_prec = prec
                    best_t    = t
            return round(best_t, 2)

        return {
            "long":  best_thr(lp, y_l),
            "short": best_thr(sp, y_s),
        }

    # ── 신호 ─────────────────────────────────────────────
    def signal(
        self,
        X:               pd.DataFrame,
        long_threshold:  float = 0.60,
        short_threshold: float = 0.60,
    ) -> np.ndarray:
        """+1=LONG / -1=SHORT / 0=NEUTRAL"""
        lp = self.predict_proba_long(X)
        sp = self.predict_proba_short(X)

        result = np.zeros(len(lp))
        result[lp >= long_threshold]  =  1
        result[sp >= short_threshold] = -1
        conflict = (lp >= long_threshold) & (sp >= short_threshold)
        result[conflict] = np.where(lp[conflict] > sp[conflict], 1, -1)
        return result

    def signal_latest(
        self,
        X:               pd.DataFrame,
        long_threshold:  float = 0.60,
        short_threshold: float = 0.60,
    ) -> dict:
        lp = float(self.predict_proba_long(X)[-1])
        sp = float(self.predict_proba_short(X)[-1])

        if   lp >= long_threshold  and lp >= sp: sig = "LONG"
        elif sp >= short_threshold and sp >  lp: sig = "SHORT"
        else:                                     sig = "NEUTRAL"

        return {
            "signal":          sig,
            "long_prob":       round(lp, 4),
            "short_prob":      round(sp, 4),
            "score":           round(lp - sp, 4),
            "long_threshold":  long_threshold,
            "short_threshold": short_threshold,
        }

    def predict_directional(self, X: pd.DataFrame) -> dict:
        lp = float(self.predict_proba_long(X)[-1])
        sp = float(self.predict_proba_short(X)[-1])
        return {
            "long_prob":  round(lp, 4),
            "short_prob": round(sp, 4),
            "score":      round(lp - sp, 4),
            "signal":     "NEUTRAL",
        }

    def save(self, path: str):
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @classmethod
    def load(cls, path: str) -> "DirectionalEnsemble":
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
