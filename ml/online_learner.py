"""
ml/online_learner.py
온라인 / 연속 학습 (Online / Continuous Learning)

새로운 캔들이 들어올 때마다 모델을 점진적으로 업데이트:
  - 롤링 윈도우: 최근 N일 데이터로만 학습 (오래된 패턴 희석)
  - 체크포인트: 주기적으로 모델 저장
  - 성능 모니터링: 실시간 승률 추적
  - 드리프트 감지: 성능 급락 시 재학습 트리거

사용법:
  learner = OnlineLearner(model_dir="ml/saved_models")
  learner.update(new_bars_df)       # 새 데이터 추가 + 필요 시 재학습
  signal = learner.predict_latest() # 최신 신호 반환
"""

import os
import pickle
import json
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class OnlineLearner:
    """
    롤링 윈도우 기반 온라인 학습기

    파라미터:
      window_days     : 학습에 사용할 최근 일수 (기본 500일)
      retrain_every   : N개 새 데이터마다 재학습 (기본 7일)
      min_samples     : 최소 학습 샘플 수 (기본 200)
      threshold       : 신호 임계값 (기본 0.60)
      perf_window     : 성능 평가 기간 (최근 N 신호)
      drift_threshold : 이 이하 승률이면 즉시 재학습
    """
    def __init__(
        self,
        model_dir:       str   = None,
        window_days:     int   = 500,
        retrain_every:   int   = 7,
        min_samples:     int   = 200,
        threshold:       float = 0.60,
        perf_window:     int   = 30,
        drift_threshold: float = 0.45,
    ):
        self.model_dir       = Path(model_dir or os.path.join(ROOT, "ml", "saved_models"))
        self.window_days     = window_days
        self.retrain_every   = retrain_every
        self.min_samples     = min_samples
        self.threshold       = threshold
        self.perf_window     = perf_window
        self.drift_threshold = drift_threshold

        self.model_dir.mkdir(parents=True, exist_ok=True)

        # 내부 상태
        self._buffer     = pd.DataFrame()   # 누적 데이터
        self._new_count  = 0                # 재학습 트리거 카운터
        self._model      = None             # 현재 모델
        self._history    = []               # 예측 이력 (성능 추적용)
        self._state_path = self.model_dir / "online_state.json"

        self._load_state()

    # ── 공개 메서드 ───────────────────────────────────────────────────

    def update(self, new_df: pd.DataFrame, symbol: str = "BTCUSDT") -> dict:
        """
        새 캔들 데이터 추가 + 필요 시 재학습

        Args:
            new_df: OHLCV + 피처가 포함된 DataFrame (add_features 완료)
            symbol: 심볼명

        Returns:
            dict: {retrained, n_samples, model_version}
        """
        from ml.features  import make_targets, get_feature_cols, make_directional_targets
        from ml.regime    import add_regime_features
        from ml.multi_timeframe import add_multi_timeframe_features

        # 버퍼에 추가 (중복 제거)
        new_df = new_df.copy()
        if "date" in new_df.columns:
            new_df["_symbol"] = symbol

        if self._buffer.empty:
            self._buffer = new_df
        else:
            combined = pd.concat([self._buffer, new_df], ignore_index=True)
            if "date" in combined.columns:
                combined = combined.drop_duplicates("date").sort_values("date").reset_index(drop=True)
            self._buffer = combined

        self._new_count += len(new_df)

        # 롤링 윈도우 적용
        if len(self._buffer) > self.window_days:
            self._buffer = self._buffer.iloc[-self.window_days:].reset_index(drop=True)

        retrained = False
        should_retrain = (
            self._new_count >= self.retrain_every
            or self._model is None
            or self._detect_drift()
        )

        if should_retrain and len(self._buffer) >= self.min_samples:
            retrained = self._retrain()
            self._new_count = 0

        return {
            "retrained":     retrained,
            "n_samples":     len(self._buffer),
            "model_version": self._get_version(),
        }

    def predict_latest(self, df: pd.DataFrame = None) -> dict:
        """
        최신 행에 대한 신호 예측

        Args:
            df: 예측할 데이터. None이면 내부 버퍼 사용

        Returns:
            dict: {long_prob, short_prob, signal, threshold, regime}
        """
        if self._model is None:
            return {"signal": "NEUTRAL", "long_prob": 0.5, "short_prob": 0.5,
                    "threshold": self.threshold, "regime": "UNKNOWN"}

        from ml.features import get_feature_cols
        from ml.regime   import detect_regime

        data = df if df is not None else self._buffer
        if data.empty:
            return {"signal": "NEUTRAL", "long_prob": 0.5, "short_prob": 0.5,
                    "threshold": self.threshold, "regime": "UNKNOWN"}

        try:
            fcols = [c for c in self._feature_cols if c in data.columns]
            row   = data.iloc[[-1]][fcols].fillna(0)

            result = self._model.predict_directional(row)
            result["threshold"] = self.threshold

            # 예측 이력 저장 (성능 추적)
            self._history.append({
                "time":       datetime.utcnow().isoformat(),
                "long_prob":  result["long_prob"],
                "short_prob": result["short_prob"],
                "signal":     result["signal"],
            })
            if len(self._history) > 200:
                self._history = self._history[-200:]

            self._save_state()
            return result

        except Exception as e:
            return {"signal": "NEUTRAL", "long_prob": 0.5, "short_prob": 0.5,
                    "threshold": self.threshold, "regime": "UNKNOWN", "error": str(e)}

    def get_performance(self) -> dict:
        """최근 예측 성능 요약"""
        if len(self._history) < 5:
            return {"status": "insufficient_data", "n": len(self._history)}

        recent = self._history[-self.perf_window:]
        signals = [h for h in recent if h["signal"] in ("LONG", "SHORT")]
        n_sig   = len(signals)

        return {
            "status":        "ok",
            "n_predictions": len(recent),
            "n_signals":     n_sig,
            "signal_rate":   round(n_sig / len(recent), 3),
            "model_version": self._get_version(),
            "window_days":   self.window_days,
            "buffer_size":   len(self._buffer),
        }

    def save(self):
        """모델 + 상태 저장"""
        if self._model is not None:
            path = self.model_dir / f"online_model_{self._get_version()}.pkl"
            with open(path, "wb") as f:
                pickle.dump({"model": self._model, "feature_cols": self._feature_cols}, f)
        self._save_state()

    # ── 내부 메서드 ───────────────────────────────────────────────────

    def _retrain(self) -> bool:
        """롤링 윈도우 데이터로 모델 재학습"""
        try:
            from ml.features import make_directional_targets, get_feature_cols, add_features
            from ml.models   import DirectionalEnsemble

            data = self._buffer.copy()

            # 타겟 생성
            if "target_long" not in data.columns:
                data = make_directional_targets(data)

            data = data.dropna(subset=["target_long", "target_short"]).reset_index(drop=True)
            if len(data) < self.min_samples:
                return False

            feature_cols = get_feature_cols(data)
            feature_cols = [c for c in feature_cols
                           if c in data.columns and data[c].isna().mean() < 0.3]

            X = data[feature_cols]
            y_long  = data["target_long"]
            y_short = data["target_short"]

            # 80/20 분리 (시계열)
            split = int(len(data) * 0.8)

            model = DirectionalEnsemble()
            model.fit(
                X.iloc[:split], y_long.iloc[:split], y_short.iloc[:split],
                X.iloc[split:],  y_long.iloc[split:],  y_short.iloc[split:],
                feature_cols,
            )

            self._model       = model
            self._feature_cols = feature_cols
            self._version     = datetime.utcnow().strftime("%Y%m%d_%H%M")

            # 체크포인트 저장
            ckpt_path = self.model_dir / f"online_ckpt_{self._version}.pkl"
            with open(ckpt_path, "wb") as f:
                pickle.dump({"model": model, "feature_cols": feature_cols}, f)

            # 오래된 체크포인트 정리 (최근 3개만 유지)
            self._cleanup_checkpoints()

            print(f"  [OnlineLearner] 재학습 완료 v{self._version} "
                  f"(샘플 {len(data)}개, 피처 {len(feature_cols)}개)")
            return True

        except Exception as e:
            print(f"  [OnlineLearner] 재학습 실패: {e}")
            return False

    def _detect_drift(self) -> bool:
        """성능 드리프트 감지 (단순 신호 비율 기반)"""
        if len(self._history) < self.perf_window:
            return False
        recent = self._history[-self.perf_window:]
        long_probs  = [h["long_prob"] for h in recent]
        short_probs = [h["short_prob"] for h in recent]
        avg_conf = np.mean([max(lp, sp) for lp, sp in zip(long_probs, short_probs)])
        # 평균 신뢰도가 0.52 미만이면 모델이 무작위 수준 → 드리프트
        return avg_conf < 0.52

    def _get_version(self) -> str:
        return getattr(self, "_version", "init")

    def _load_state(self):
        """저장된 상태 복원"""
        self._version      = "init"
        self._feature_cols = []

        if self._state_path.exists():
            try:
                with open(self._state_path) as f:
                    state = json.load(f)
                self._version  = state.get("version", "init")
                self._history  = state.get("history", [])
            except Exception:
                pass

        # 최신 모델 파일 로드
        ckpts = sorted(self.model_dir.glob("online_ckpt_*.pkl"))
        if ckpts:
            try:
                with open(ckpts[-1], "rb") as f:
                    data = pickle.load(f)
                self._model        = data["model"]
                self._feature_cols = data["feature_cols"]
                print(f"  [OnlineLearner] 체크포인트 로드: {ckpts[-1].name}")
            except Exception:
                pass

    def _save_state(self):
        state = {
            "version":  self._get_version(),
            "history":  self._history[-100:],
            "updated":  datetime.utcnow().isoformat(),
        }
        try:
            with open(self._state_path, "w") as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass

    def _cleanup_checkpoints(self, keep: int = 3):
        ckpts = sorted(self.model_dir.glob("online_ckpt_*.pkl"))
        for old in ckpts[:-keep]:
            try:
                old.unlink()
            except Exception:
                pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 연속 학습 루프 (데몬 프로세스 용)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_continuous_learning(
    symbols:      list  = None,
    interval_min: int   = 60,     # 갱신 주기 (분)
    window_days:  int   = 500,
    threshold:    float = 0.65,
):
    """
    연속 학습 루프

    매 interval_min 분마다:
      1. 각 심볼 최신 캔들 수집
      2. 피처 생성
      3. OnlineLearner.update() 호출
      4. 신호 생성 + 로그
    """
    import time
    from ml.features        import add_features, make_directional_targets
    from ml.regime          import add_regime_features
    from ml.multi_timeframe import add_multi_timeframe_features

    if symbols is None:
        symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]

    learners = {sym: OnlineLearner(window_days=window_days, threshold=threshold)
                for sym in symbols}

    print("=" * 60)
    print("  연속 학습 루프 시작")
    print(f"  심볼: {symbols}")
    print(f"  갱신 주기: {interval_min}분")
    print(f"  윈도우: {window_days}일")
    print("=" * 60)

    iteration = 0
    while True:
        iteration += 1
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[{ts}] 이터레이션 {iteration}")

        signals = []
        for sym in symbols:
            try:
                # 데이터 로드 (실제 환경에서는 API 호출)
                data_path = os.path.join(ROOT, "data", f"{sym}_daily.csv")
                if sym == "BTCUSDT":
                    data_path = os.path.join(ROOT, "data", "btc_daily.csv")

                if not os.path.exists(data_path):
                    continue

                df = pd.read_csv(data_path)
                df = add_features(df)
                df = add_regime_features(df)
                df = add_multi_timeframe_features(df)
                df = make_directional_targets(df)

                result = learners[sym].update(df, symbol=sym)
                signal = learners[sym].predict_latest(df)

                signals.append({
                    "symbol":     sym,
                    "signal":     signal.get("signal", "NEUTRAL"),
                    "long_prob":  round(signal.get("long_prob", 0.5), 4),
                    "short_prob": round(signal.get("short_prob", 0.5), 4),
                    "retrained":  result["retrained"],
                })

                action = signal.get("signal", "NEUTRAL")
                lp = signal.get("long_prob", 0.5)
                sp = signal.get("short_prob", 0.5)
                r_flag = "🔄재학습" if result["retrained"] else ""
                print(f"  {sym}: {action:7s} (L={lp:.3f} S={sp:.3f}) {r_flag}")

            except Exception as e:
                print(f"  {sym}: 오류 — {e}")

        # 신호 로그
        if signals:
            log_path = os.path.join(ROOT, "results", "online_signals.csv")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            sig_df = pd.DataFrame(signals)
            sig_df["timestamp"] = ts
            header = not os.path.exists(log_path)
            sig_df.to_csv(log_path, mode="a", header=header, index=False)

        print(f"  → {interval_min}분 후 다시 실행...")
        time.sleep(interval_min * 60)


if __name__ == "__main__":
    import sys
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    run_continuous_learning(interval_min=interval)
