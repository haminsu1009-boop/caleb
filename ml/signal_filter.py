"""
ml/signal_filter.py
다중 조건 신호 필터 — 승률 극대화

핵심 원리:
  단일 모델 확률만으로는 ~50% 승률이 한계.
  여러 독립 조건이 동시 충족될 때만 신호 → 승률 대폭 향상.

확인 조건:
  1. ML 모델 확률 (XGB+LGBM 앙상블)
  2. 시장 국면 (BULL→롱 / BEAR→숏)
  3. 모멘텀 방향 (최근 5일 추세)
  4. 볼륨 확인 (평균 대비 거래량)
  5. RSI 존 (과매수/과매도 회피)
  6. 변동성 필터 (급등락 직후 회피)
"""

import numpy as np
import pandas as pd
from typing import Tuple


class SignalFilter:
    """
    ML 신호 + 기술적 조건 다중 필터

    사용 예시:
        sf = SignalFilter(
            ml_long_thr=0.62,   # ML 모델 임계값
            ml_short_thr=0.62,
            regime_filter=True, # 국면 필터
            momentum_window=5,  # 모멘텀 확인 기간
            vol_multiplier=0.8, # 거래량 최소 배율 (1.0=평균 이상)
            rsi_long_max=65,    # 롱: RSI 이 값 미만만 (과매수 회피)
            rsi_short_min=35,   # 숏: RSI 이 값 초과만 (과매도 회피)
            max_atr_pct=5.0,    # 최대 ATR%% 허용 (고변동 회피)
        )
        long_sig, short_sig = sf.filter(df, long_prob, short_prob)
    """

    def __init__(
        self,
        ml_long_thr:    float = 0.62,
        ml_short_thr:   float = 0.62,
        regime_filter:  bool  = True,
        momentum_window: int  = 5,
        vol_multiplier: float = 0.8,   # 거래량 평균 대비 최소 배율 (0=off)
        rsi_long_max:   float = 68,    # 롱 진입 최대 RSI (과매수 회피)
        rsi_short_min:  float = 32,    # 숏 진입 최소 RSI (과매도 회피)
        max_atr_pct:    float = 6.0,   # ATR/Close % 최대값 (변동성 필터)
        require_all:    bool  = False, # True=모든 조건 필요, False=ML+1개 충족
    ):
        self.ml_long_thr     = ml_long_thr
        self.ml_short_thr    = ml_short_thr
        self.regime_filter   = regime_filter
        self.momentum_window = momentum_window
        self.vol_multiplier  = vol_multiplier
        self.rsi_long_max    = rsi_long_max
        self.rsi_short_min   = rsi_short_min
        self.max_atr_pct     = max_atr_pct
        self.require_all     = require_all

    def filter(
        self,
        df:         pd.DataFrame,
        long_prob:  np.ndarray,
        short_prob: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        다중 조건 필터 적용

        Args:
            df:         피처 포함 DataFrame (close, volume, rsi_14, atr_14, regime 등)
            long_prob:  ML 롱 확률 배열 (len(df))
            short_prob: ML 숏 확률 배열 (len(df))

        Returns:
            (long_signal, short_signal) — bool 배열
        """
        n = len(df)
        idx = df.index

        # ── 조건 1: ML 확률 임계값 ──────────────────────
        cond_ml_long  = long_prob  >= self.ml_long_thr
        cond_ml_short = short_prob >= self.ml_short_thr

        # ── 조건 2: 국면 필터 ──────────────────────────
        if self.regime_filter and "regime" in df.columns:
            regime = df["regime"].fillna(1).values
            cond_reg_long  = (regime == 2)  # BULL
            cond_reg_short = (regime == 0)  # BEAR
        else:
            cond_reg_long = cond_reg_short = np.ones(n, bool)

        # ── 조건 3: 모멘텀 ─────────────────────────────
        if "close" in df.columns and self.momentum_window > 0:
            close = df["close"].values.astype(float)
            mom = np.full(n, np.nan)
            w = self.momentum_window
            for i in range(w, n):
                mom[i] = close[i] / close[i - w] - 1
            cond_mom_long  = (mom > 0)
            cond_mom_short = (mom < 0)
        else:
            cond_mom_long = cond_mom_short = np.ones(n, bool)

        # ── 조건 4: 거래량 확인 ─────────────────────────
        if "volume" in df.columns and self.vol_multiplier > 0:
            vol = df["volume"].values.astype(float)
            vol_ma = pd.Series(vol).rolling(20, min_periods=5).mean().values
            cond_vol = vol >= vol_ma * self.vol_multiplier
        else:
            cond_vol = np.ones(n, bool)

        # ── 조건 5: RSI 존 ─────────────────────────────
        rsi_col = next((c for c in ["rsi_14", "rsi14", "rsi"] if c in df.columns), None)
        if rsi_col:
            rsi = df[rsi_col].values.astype(float)
            # 롱: RSI < rsi_long_max (과매수 회피), 숏: RSI > rsi_short_min (과매도 회피)
            cond_rsi_long  = (rsi < self.rsi_long_max)
            cond_rsi_short = (rsi > self.rsi_short_min)
        else:
            cond_rsi_long = cond_rsi_short = np.ones(n, bool)

        # ── 조건 6: 변동성 필터 ─────────────────────────
        atr_col  = next((c for c in ["atr_14", "atr14", "atr"] if c in df.columns), None)
        if atr_col and "close" in df.columns:
            atr   = df[atr_col].values.astype(float)
            close = df["close"].values.astype(float)
            atr_pct = atr / (close + 1e-9) * 100
            cond_vol_ok = (atr_pct <= self.max_atr_pct)
        else:
            cond_vol_ok = np.ones(n, bool)

        # ── 신호 결합 ──────────────────────────────────
        if self.require_all:
            # 엄격: 모든 조건 동시 충족
            long_signal  = (cond_ml_long  & cond_reg_long  & cond_mom_long
                            & cond_vol & cond_rsi_long & cond_vol_ok)
            short_signal = (cond_ml_short & cond_reg_short & cond_mom_short
                            & cond_vol & cond_rsi_short & cond_vol_ok)
        else:
            # 완화: ML 필수 + 기술적 조건 과반(2/4) 충족
            tech_long  = (cond_mom_long.astype(int) + cond_vol.astype(int)
                          + cond_rsi_long.astype(int) + cond_vol_ok.astype(int))
            tech_short = (cond_mom_short.astype(int) + cond_vol.astype(int)
                          + cond_rsi_short.astype(int) + cond_vol_ok.astype(int))
            long_signal  = cond_ml_long  & cond_reg_long  & (tech_long  >= 2)
            short_signal = cond_ml_short & cond_reg_short & (tech_short >= 2)

        return long_signal, short_signal

    def analyze(
        self,
        df:         pd.DataFrame,
        long_prob:  np.ndarray,
        short_prob: np.ndarray,
        ret:        np.ndarray,
        fee:        float = 0.002,
    ) -> dict:
        """필터 성능 분석"""
        long_sig, short_sig = self.filter(df, long_prob, short_prob)

        def stats(mask, r, sign=1):
            if mask.sum() == 0:
                return {"n": 0, "wr": 0.0, "avg": 0.0}
            sel = r[mask] * sign - fee
            return {"n": int(mask.sum()), "wr": float((sel > 0).mean()),
                    "avg": float(sel.mean())}

        l_stats = stats(long_sig,  ret,  1)
        s_stats = stats(short_sig, ret, -1)

        comb = long_sig | short_sig
        if comb.sum() > 0:
            cr = np.where(long_sig[comb], ret[comb], -ret[comb]) - fee
            c_wr = float((cr > 0).mean())
        else:
            c_wr = 0.0

        # ML-only 비교 (기준선)
        ml_l = (long_prob  >= self.ml_long_thr)
        ml_s = (short_prob >= self.ml_short_thr)
        base_l = stats(ml_l, ret, 1)
        base_s = stats(ml_s, ret, -1)

        return {
            "long":      l_stats,
            "short":     s_stats,
            "combined_wr": c_wr,
            "n_total":   l_stats["n"] + s_stats["n"],
            "baseline_long":  base_l,
            "baseline_short": base_s,
            "signal_reduction_pct": round(
                (1 - (l_stats["n"] + s_stats["n"])
                 / max(1, base_l["n"] + base_s["n"])) * 100, 1
            ),
        }


# ── 상위 퍼센타일 신호 선택 ─────────────────────────────────
def top_percentile_signals(
    long_prob:  np.ndarray,
    short_prob: np.ndarray,
    regime:     np.ndarray = None,
    pct:        float = 5.0,    # 상위 N% 선택
    min_thr:    float = 0.60,   # 최소 임계값 (퍼센타일이 낮아도 이 값 이상만)
) -> tuple:
    """
    확률 상위 N%만 선택 (threshold 고정 대신 상대적 선택)

    이점: 시장 상황에 따라 자동으로 임계값 조정
    - 강한 신호가 많을 때 → 높은 threshold 자동 적용
    - 약한 신호만 있을 때 → min_thr 유지로 진입 차단

    Args:
        pct: 상위 N% 선택 (5.0 = 상위 5%)
        min_thr: 퍼센타일 임계값이 이 값 미만이면 신호 없음

    Returns:
        (long_mask, short_mask) — bool arrays
    """
    n = len(long_prob)

    # 상위 N% 임계값
    l_pct_thr = np.percentile(long_prob,  100 - pct) if n > 20 else min_thr
    s_pct_thr = np.percentile(short_prob, 100 - pct) if n > 20 else min_thr

    l_thr = max(l_pct_thr, min_thr)
    s_thr = max(s_pct_thr, min_thr)

    long_mask  = long_prob  >= l_thr
    short_mask = short_prob >= s_thr

    # 국면 필터 (BULL→롱, BEAR→숏)
    if regime is not None:
        long_mask  = long_mask  & (regime == 2)
        short_mask = short_mask & (regime == 0)

    return long_mask, short_mask


# ── 편의 함수 ──────────────────────────────────────────────
def apply_signal_filter(
    df:         pd.DataFrame,
    long_prob:  np.ndarray,
    short_prob: np.ndarray,
    long_thr:   float = 0.62,
    short_thr:  float = 0.62,
    regime_filter: bool = True,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    기본 설정으로 SignalFilter 적용

    Returns:
        (long_mask, short_mask) — bool arrays
    """
    sf = SignalFilter(
        ml_long_thr   = long_thr,
        ml_short_thr  = short_thr,
        regime_filter = regime_filter,
    )
    return sf.filter(df, long_prob, short_prob)
