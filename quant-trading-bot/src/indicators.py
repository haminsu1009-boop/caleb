"""
기술적 지표 계산 모듈
SMA, EMA, RSI, MACD, Bollinger Bands, Stochastic, ATR, OBV, CCI, ADX 등
"""

import numpy as np
import pandas as pd


def sma(series, period):
    return series.rolling(window=period, min_periods=period).mean()


def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series, fast=12, slow=26, signal=9):
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger_bands(series, period=20, std_dev=2):
    mid = sma(series, period)
    std = series.rolling(window=period, min_periods=period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    pct_b = (series - lower) / (upper - lower)
    return upper, mid, lower, pct_b


def stochastic(high, low, close, k_period=14, d_period=3):
    lowest_low = low.rolling(window=k_period, min_periods=k_period).min()
    highest_high = high.rolling(window=k_period, min_periods=k_period).max()
    k = 100 * (close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)
    d = sma(k, d_period)
    return k, d


def atr(high, low, close, period=14):
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period, min_periods=period).mean()


def obv(close, volume):
    direction = np.sign(close.diff())
    direction.iloc[0] = 0
    return (volume * direction).cumsum()


def cci(high, low, close, period=20):
    tp = (high + low + close) / 3
    sma_tp = sma(tp, period)
    mad = tp.rolling(window=period, min_periods=period).apply(
        lambda x: np.mean(np.abs(x - np.mean(x))), raw=True
    )
    return (tp - sma_tp) / (0.015 * mad)


def adx(high, low, close, period=14):
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    atr_val = atr(high, low, close, period)

    plus_di = 100 * pd.Series(plus_dm, index=close.index).rolling(period).mean() / atr_val
    minus_di = 100 * pd.Series(minus_dm, index=close.index).rolling(period).mean() / atr_val

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_val = dx.rolling(window=period, min_periods=period).mean()
    return adx_val, plus_di, minus_di


def williams_r(high, low, close, period=14):
    highest_high = high.rolling(window=period, min_periods=period).max()
    lowest_low = low.rolling(window=period, min_periods=period).min()
    return -100 * (highest_high - close) / (highest_high - lowest_low).replace(0, np.nan)


def mfi(high, low, close, volume, period=14):
    tp = (high + low + close) / 3
    raw_mf = tp * volume
    direction = tp.diff()
    pos_mf = raw_mf.where(direction > 0, 0.0).rolling(period).sum()
    neg_mf = raw_mf.where(direction <= 0, 0.0).rolling(period).sum()
    ratio = pos_mf / neg_mf.replace(0, np.nan)
    return 100 - (100 / (1 + ratio))


def add_all_indicators(df):
    """DataFrame에 모든 기술적 지표 추가"""
    c = df["close"]
    h = df["high"]
    l = df["low"]
    v = df["volume"]

    # 이동평균
    for p in [5, 10, 20, 50, 100, 200]:
        df[f"sma_{p}"] = sma(c, p)
        df[f"ema_{p}"] = ema(c, p)

    # RSI
    df["rsi_14"] = rsi(c, 14)
    df["rsi_7"] = rsi(c, 7)

    # MACD
    df["macd"], df["macd_signal"], df["macd_hist"] = macd(c)

    # Bollinger Bands
    df["bb_upper"], df["bb_mid"], df["bb_lower"], df["bb_pctb"] = bollinger_bands(c)

    # Stochastic
    df["stoch_k"], df["stoch_d"] = stochastic(h, l, c)

    # ATR
    df["atr_14"] = atr(h, l, c, 14)

    # OBV
    df["obv"] = obv(c, v)

    # CCI
    df["cci_20"] = cci(h, l, c, 20)

    # ADX
    df["adx_14"], df["plus_di"], df["minus_di"] = adx(h, l, c, 14)

    # Williams %R
    df["williams_r"] = williams_r(h, l, c, 14)

    # MFI
    df["mfi_14"] = mfi(h, l, c, v, 14)

    # 수익률
    df["return_1d"] = c.pct_change(1)
    df["return_5d"] = c.pct_change(5)

    # 거래량 이동평균
    df["vol_sma_20"] = sma(v, 20)
    df["vol_ratio"] = v / df["vol_sma_20"]

    return df
