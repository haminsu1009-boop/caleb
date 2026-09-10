"""
Technical Indicators
====================
RSI, MACD, 볼린저 밴드, 이동평균, 거래량 분석
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 이동평균
# ─────────────────────────────────────────────

def calc_ma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=1).mean()


def calc_ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False).mean()


# ─────────────────────────────────────────────
# RSI (Relative Strength Index)
# ─────────────────────────────────────────────

def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_g = gain.ewm(com=period - 1, adjust=False).mean()
    avg_l = loss.ewm(com=period - 1, adjust=False).mean()
    rs    = avg_g / avg_l.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


# ─────────────────────────────────────────────
# MACD
# ─────────────────────────────────────────────

def calc_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict:
    ema_fast   = calc_ema(close, fast)
    ema_slow   = calc_ema(close, slow)
    macd_line  = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    histogram  = macd_line - signal_line
    return {
        "macd":      macd_line,
        "signal":    signal_line,
        "histogram": histogram,
    }


# ─────────────────────────────────────────────
# 볼린저 밴드
# ─────────────────────────────────────────────

def calc_bollinger(close: pd.Series, period: int = 20, std_mult: float = 2.0) -> Dict:
    mid   = calc_ma(close, period)
    std   = close.rolling(window=period, min_periods=1).std()
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    # %B: 0 = 하단, 1 = 상단
    pct_b = (close - lower) / (upper - lower + 1e-10)
    # Bandwidth
    bw    = (upper - lower) / (mid + 1e-10)
    return {
        "upper":     upper,
        "mid":       mid,
        "lower":     lower,
        "pct_b":     pct_b,
        "bandwidth": bw,
    }


# ─────────────────────────────────────────────
# 거래량 분석
# ─────────────────────────────────────────────

def calc_volume_signal(volume: pd.Series, window: int = 20, surge_ratio: float = 1.5) -> Dict:
    vol_ma   = calc_ma(volume, window)
    ratio    = volume / (vol_ma + 1e-10)
    surge    = ratio > surge_ratio   # True = 거래량 급증
    obv      = (np.sign(volume.diff()) * volume).fillna(0).cumsum()
    return {
        "vol_ma":    vol_ma,
        "ratio":     ratio,
        "surge":     surge,
        "obv":       obv,
    }


# ─────────────────────────────────────────────
# 모멘텀 (단기 수익률 평균)
# ─────────────────────────────────────────────

def calc_momentum(close: pd.Series, windows: list = [5, 20, 60]) -> Dict:
    """각 기간 수익률. 양수 = 상승 모멘텀"""
    result = {}
    for w in windows:
        ret = close.pct_change(w)
        result[f"mom_{w}"] = ret
    return result


# ─────────────────────────────────────────────
# 핵심 함수: 전체 지표 계산 및 점수화
# ─────────────────────────────────────────────

def compute_all_indicators(df: pd.DataFrame, cfg=None) -> Dict:
    """
    OHLCV DataFrame을 받아 모든 지표를 계산하고,
    각 지표의 최신값(스칼라)과 0~1 점수를 반환.

    반환 예시:
    {
        "rsi":        {"value": 45.3, "score": 0.55},
        "macd":       {"value": 12.5, "histogram": 3.1, "score": 0.70},
        "bollinger":  {"pct_b": 0.35, "bandwidth": 0.08, "score": 0.60},
        "volume":     {"ratio": 1.8, "obv_trend": 0.5, "score": 0.75},
        "ma_cross":   {"price_vs_ma20": 0.03, "ma5_vs_ma20": 0.01, "score": 0.65},
        "momentum":   {"mom_5": 0.02, "mom_20": 0.05, "score": 0.60},
    }
    """
    if df.empty or "Close" not in df.columns:
        return {}

    from config import INDICATOR_CONFIG as IC
    if cfg is None:
        cfg = IC

    close  = df["Close"].dropna()
    volume = df["Volume"].dropna() if "Volume" in df.columns else pd.Series(dtype=float)

    if len(close) < 30:
        logger.warning("데이터 부족 (30봉 미만)")
        return {}

    result = {}

    # ── RSI ──────────────────────────────────
    rsi_series = calc_rsi(close, cfg.RSI_PERIOD)
    rsi_val    = float(rsi_series.iloc[-1])
    # 점수: 30 이하 → 과매도(매수 기회), 70 이상 → 과매수
    if rsi_val <= cfg.RSI_OVERSOLD:
        rsi_score = 0.85      # 과매도 = 강한 매수 신호
    elif rsi_val <= 45:
        rsi_score = 0.65
    elif rsi_val <= 55:
        rsi_score = 0.50
    elif rsi_val <= cfg.RSI_OVERBOUGHT:
        rsi_score = 0.40
    else:
        rsi_score = 0.20      # 과매수 = 매수 리스크
    result["rsi"] = {"value": round(rsi_val, 2), "score": rsi_score}

    # ── MACD ─────────────────────────────────
    macd_dict = calc_macd(close, cfg.MACD_FAST, cfg.MACD_SLOW, cfg.MACD_SIGNAL)
    macd_val  = float(macd_dict["macd"].iloc[-1])
    hist_val  = float(macd_dict["histogram"].iloc[-1])
    hist_prev = float(macd_dict["histogram"].iloc[-2]) if len(macd_dict["histogram"]) >= 2 else 0

    if hist_val > 0 and hist_val > hist_prev:
        macd_score = 0.85    # 양의 히스토그램 확대
    elif hist_val > 0:
        macd_score = 0.65    # 양이지만 축소 중
    elif hist_val < 0 and hist_val > hist_prev:
        macd_score = 0.45    # 음이지만 회복 중
    else:
        macd_score = 0.20    # 음의 히스토그램 확대
    result["macd"] = {
        "value":     round(macd_val, 4),
        "histogram": round(hist_val, 4),
        "score":     macd_score,
    }

    # ── 볼린저 밴드 ───────────────────────────
    bb = calc_bollinger(close, cfg.BB_PERIOD, cfg.BB_STD)
    pct_b = float(bb["pct_b"].iloc[-1])
    bw    = float(bb["bandwidth"].iloc[-1])

    if pct_b < 0.1:
        bb_score = 0.80      # 하단 터치 = 반등 기대
    elif pct_b < 0.3:
        bb_score = 0.65
    elif pct_b < 0.7:
        bb_score = 0.50
    elif pct_b < 0.9:
        bb_score = 0.35
    else:
        bb_score = 0.20      # 상단 돌파 = 과열
    result["bollinger"] = {
        "pct_b":     round(pct_b, 3),
        "bandwidth": round(bw, 4),
        "score":     bb_score,
    }

    # ── 거래량 ───────────────────────────────
    if not volume.empty and len(volume) >= 20:
        vol_sig   = calc_volume_signal(volume, surge_ratio=cfg.VOLUME_SURGE_RATIO)
        vol_ratio = float(vol_sig["ratio"].iloc[-1])
        obv       = vol_sig["obv"]
        obv_trend = float(obv.iloc[-1] - obv.iloc[-5]) if len(obv) >= 5 else 0.0

        if vol_ratio >= cfg.VOLUME_SURGE_RATIO:
            vol_score = 0.80 if obv_trend > 0 else 0.40
        else:
            vol_score = 0.55 if obv_trend > 0 else 0.45
        result["volume"] = {
            "ratio":     round(vol_ratio, 2),
            "obv_trend": round(obv_trend, 2),
            "score":     vol_score,
        }
    else:
        result["volume"] = {"ratio": 1.0, "obv_trend": 0.0, "score": 0.5}

    # ── 이동평균 교차 ────────────────────────
    ma5  = float(calc_ma(close, cfg.MA_SHORT).iloc[-1])
    ma20 = float(calc_ma(close, cfg.MA_MID).iloc[-1])
    ma60 = float(calc_ma(close, cfg.MA_LONG).iloc[-1])
    price_now = float(close.iloc[-1])

    p_vs_20 = (price_now - ma20) / (ma20 + 1e-10)
    m5_vs_20 = (ma5 - ma20) / (ma20 + 1e-10)

    if p_vs_20 > 0.05 and m5_vs_20 > 0:
        ma_score = 0.80     # 가격 + 단기MA 모두 중기MA 상회
    elif p_vs_20 > 0:
        ma_score = 0.65
    elif p_vs_20 > -0.05:
        ma_score = 0.45
    else:
        ma_score = 0.25     # 강한 하락 추세
    result["ma_cross"] = {
        "price_vs_ma20": round(p_vs_20, 4),
        "ma5_vs_ma20":   round(m5_vs_20, 4),
        "price_vs_ma60": round((price_now - ma60) / (ma60 + 1e-10), 4),
        "score":         ma_score,
    }

    # ── 모멘텀 ───────────────────────────────
    mom = calc_momentum(close)
    m5  = float(mom["mom_5"].iloc[-1])  if not mom["mom_5"].isna().all()  else 0.0
    m20 = float(mom["mom_20"].iloc[-1]) if not mom["mom_20"].isna().all() else 0.0
    m60 = float(mom["mom_60"].iloc[-1]) if not mom["mom_60"].isna().all() else 0.0

    pos_count = sum(1 for v in [m5, m20, m60] if v > 0)
    mom_score = 0.25 + pos_count * 0.20
    result["momentum"] = {
        "mom_5":  round(m5,  4),
        "mom_20": round(m20, 4),
        "mom_60": round(m60, 4),
        "score":  mom_score,
    }

    return result
