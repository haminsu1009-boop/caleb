"""
ml/predictor.py
학습된 모델로 실시간 신호 생성

사용:
  python ml/predictor.py            # 현재 신호 출력
  python ml/predictor.py --retrain  # 모델 재학습 후 신호
"""

import os
import sys
import json
import pickle
import argparse
import warnings
import numpy as np
import pandas as pd
from datetime import datetime

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ml.features import add_features, make_targets, get_feature_cols

MODEL_DIR  = os.path.join(ROOT, "ml", "saved_models")
DATA_FILE  = os.path.join(ROOT, "data", "btc_daily.csv")
SIGNAL_LOG = os.path.join(ROOT, "signals.log")
SIGNAL_PROB = 0.60


def load_model():
    model_path   = os.path.join(MODEL_DIR, "ensemble_model.pkl")
    feature_path = os.path.join(MODEL_DIR, "feature_cols.pkl")

    if not os.path.exists(model_path):
        raise FileNotFoundError("모델 없음. 먼저 ml/trainer.py 실행하세요.")

    with open(model_path,   "rb") as f: model = pickle.load(f)
    with open(feature_path, "rb") as f: feature_cols = pickle.load(f)
    return model, feature_cols


def get_current_signal(verbose: bool = True) -> dict:
    model, feature_cols = load_model()

    df = pd.read_csv(DATA_FILE)
    df = add_features(df)
    df = df.dropna(subset=feature_cols[:10]).reset_index(drop=True)

    X = df[feature_cols]
    proba = model.predict_proba(X)[:, 1]

    last_idx   = len(df) - 1
    last_proba = float(proba[last_idx]) if not np.isnan(proba[last_idx]) else 0.0
    last_date  = df.iloc[last_idx]["date"]
    last_price = df.iloc[last_idx]["close"]
    last_rsi   = float(df.iloc[last_idx].get("rsi_14", 0)) * 100
    last_bb    = float(df.iloc[last_idx].get("bb_pct_2.0", 0.5))

    signal_str = "🟢 매수" if last_proba >= SIGNAL_PROB else "⚪ 관망"

    result = {
        "datetime":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "date":        str(last_date),
        "price":       round(last_price, 2),
        "buy_prob":    round(last_proba, 4),
        "signal":      "BUY" if last_proba >= SIGNAL_PROB else "HOLD",
        "signal_str":  signal_str,
        "threshold":   SIGNAL_PROB,
        "rsi14":       round(last_rsi, 2),
        "bb_pct":      round(last_bb,  4),
    }

    if verbose:
        print(f"\n{'='*50}")
        print(f"  ML 신호 체크  {result['datetime']}")
        print(f"{'='*50}")
        print(f"  날짜:     {result['date']}")
        print(f"  BTC 가격: ${result['price']:,.2f}")
        print(f"  매수 확률: {result['buy_prob']*100:.1f}%  (임계값: {SIGNAL_PROB*100:.0f}%)")
        print(f"  신호:     {result['signal_str']}")
        print(f"  RSI(14):  {result['rsi14']:.1f}")
        print(f"  BB_%B:    {result['bb_pct']:.3f}")
        print(f"{'='*50}")

    # signals.log에 기록
    with open(SIGNAL_LOG, "a", encoding="utf-8") as f:
        f.write(f"{result['datetime']} | ML | "
                f"가격=${result['price']:,.0f} | "
                f"확률={result['buy_prob']*100:.1f}% | "
                f"신호={result['signal']} | "
                f"RSI={result['rsi14']:.1f}\n")

    return result


def predict_all(threshold: float = SIGNAL_PROB) -> pd.DataFrame:
    """전체 데이터에 대한 신호 예측 (백테스트용)"""
    model, feature_cols = load_model()

    df = pd.read_csv(DATA_FILE)
    df = add_features(df)
    df = df.dropna(subset=feature_cols[:10]).reset_index(drop=True)

    proba  = model.predict_proba(df[feature_cols])[:, 1]
    signal = (proba >= threshold).astype(int)

    df["ml_proba"]  = proba
    df["ml_signal"] = signal

    return df[["date", "close", "ml_proba", "ml_signal"]]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--retrain", action="store_true", help="모델 재학습")
    args = parser.parse_args()

    if args.retrain:
        from ml.trainer import run
        run()

    get_current_signal(verbose=True)
