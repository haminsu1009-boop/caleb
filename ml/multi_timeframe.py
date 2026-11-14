"""
ml/multi_timeframe.py
멀티 타임프레임 피처 엔지니어링

일봉 OHLCV → 다음 타임프레임 패턴을 재구성:
  1D (기존):    단기 트레이딩 피처
  W  (주봉 근사): 5일 집계 → 추세 흐름
  M  (월봉 근사): 21일 집계 → 중기 방향
  Q  (분기 근사): 63일 집계 → 장기 국면

또한 분봉/시봉 피처를 시뮬레이션:
  4H: 일봉을 4H 변동성 분포로 분해
  1H: 4H를 1H 변동성 분포로 분해
"""

import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")


def _rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    g  = delta.clip(lower=0).rolling(period).mean()
    ls = (-delta.clip(upper=0)).rolling(period).mean()
    return 100 - 100 / (1 + g / ls.replace(0, np.nan))


def _atr(high, low, close, period: int = 14) -> pd.Series:
    tr = pd.concat([high - low,
                    (high - close.shift()).abs(),
                    (low  - close.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def add_weekly_features(df: pd.DataFrame) -> pd.DataFrame:
    """주봉 근사 (5일 집계) 피처"""
    df = df.copy()
    c = df["close"]

    W = 5  # 주봉 = 5거래일

    # 주봉 OHLCV 재구성
    w_close = c.rolling(W).mean()         # 주 평균가
    w_high  = df["high"].rolling(W).max()
    w_low   = df["low"].rolling(W).min()
    w_vol   = df["volume"].rolling(W).sum()

    # 주봉 RSI
    df["w_rsi_14"] = _rsi(w_close, 14) / 100

    # 주봉 모멘텀
    df["w_ret_1"] = w_close.pct_change(W)     # 1주 수익률
    df["w_ret_4"] = w_close.pct_change(W * 4) # 4주 수익률

    # 주봉 위치 (최근 4주 중)
    df["w_high_pct"] = c / w_high
    df["w_low_pct"]  = c / w_low

    # 주봉 변동성
    df["w_vol_ratio"] = w_vol / w_vol.rolling(4 * W).mean()

    # 주봉 추세
    w_sma4  = w_close.rolling(4).mean()   # 4주 이평
    w_sma13 = w_close.rolling(13).mean()  # 13주 이평
    df["w_above_sma4"]  = (c > w_sma4).astype(int)
    df["w_above_sma13"] = (c > w_sma13).astype(int)
    df["w_sma4_vs_13"]  = (w_sma4 / w_sma13) - 1

    # 주봉 MACD
    we12 = w_close.ewm(span=12, adjust=False).mean()
    we26 = w_close.ewm(span=26, adjust=False).mean()
    w_macd = we12 - we26
    w_sig  = w_macd.ewm(span=9, adjust=False).mean()
    df["w_macd_hist"] = (w_macd - w_sig) / (w_close + 1e-9)

    return df


def add_monthly_features(df: pd.DataFrame) -> pd.DataFrame:
    """월봉 근사 (21일 집계) 피처"""
    df = df.copy()
    c = df["close"]

    M = 21

    m_close = c.rolling(M).mean()
    m_high  = df["high"].rolling(M).max()
    m_low   = df["low"].rolling(M).min()

    # 월봉 RSI
    df["m_rsi_9"] = _rsi(m_close, 9) / 100

    # 월봉 추세 방향
    df["m_ret_1"]  = m_close.pct_change(M)
    df["m_ret_3"]  = m_close.pct_change(M * 3)
    df["m_ret_12"] = m_close.pct_change(M * 12)

    # 월봉 채널 위치
    m_range = m_high - m_low
    df["m_channel_pos"] = (c - m_low) / (m_range + 1e-9)

    # 월봉 변동성 대비
    df["m_atr_pct"] = _atr(df["high"], df["low"], c, M) / (c + 1e-9)

    # 장기 추세 정렬도 (Short vs Long)
    m_sma3  = m_close.rolling(3).mean()
    m_sma12 = m_close.rolling(12).mean()
    df["m_trend_align"] = (m_sma3 > m_sma12).astype(int) * 2 - 1  # -1 or +1

    # Donchian Channel
    df["m_dc_break_up"]   = (c >= m_high).astype(int)
    df["m_dc_break_down"] = (c <= m_low).astype(int)

    return df


def add_quarterly_features(df: pd.DataFrame) -> pd.DataFrame:
    """분기봉 근사 (63일 집계) 피처"""
    df = df.copy()
    c = df["close"]

    Q = 63

    q_close = c.rolling(Q).mean()
    q_high  = df["high"].rolling(Q).max()
    q_low   = df["low"].rolling(Q).min()

    # 분기 추세
    df["q_ret_1"] = q_close.pct_change(Q)
    df["q_ret_4"] = q_close.pct_change(Q * 4)

    # 분기 채널 위치 (0~1)
    q_range = q_high - q_low
    df["q_channel_pos"] = (c - q_low) / (q_range + 1e-9)

    # 분기 모멘텀 방향
    q_sma2 = q_close.rolling(2).mean()
    q_sma8 = q_close.rolling(8).mean()
    df["q_above_sma2"] = (q_close > q_sma2).astype(int)
    df["q_trend_score"] = (q_sma2 / q_sma8) - 1

    # 연간 고점 대비
    df["q_vs_52w_high"] = c / df["high"].rolling(252).max()
    df["q_vs_52w_low"]  = c / df["low"].rolling(252).min()

    return df


def add_intraday_sim_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    일봉 OHLCV로부터 시간봉/분봉 패턴 시뮬레이션

    원리: 하루의 High-Low 범위와 Open-Close 방향을 이용해
          4H/1H 수준의 변동성 패턴을 추정
    """
    df = df.copy()
    c, h, l, o, v = df["close"], df["high"], df["low"], df["open"], df["volume"]

    # ── 4H 패턴 근사 ─────────────────────────
    # 일일 범위의 각 4H 구간 비율 (시장 개장/마감 패턴)
    daily_range = h - l
    daily_body  = (c - o).abs()
    daily_move  = c - o  # 양수 = 상승일

    # 상승일/하락일 비율 (최근 5일)
    df["h4_bull_ratio_5d"]  = (daily_move > 0).rolling(5).mean()
    df["h4_bull_ratio_20d"] = (daily_move > 0).rolling(20).mean()

    # 4H 변동성 (일일 범위를 6으로 나눔 = 4H 6개)
    df["h4_vol_sim"]   = (daily_range / 6) / (c + 1e-9)
    df["h4_range_ma5"] = df["h4_vol_sim"].rolling(5).mean()

    # 당일 오픈 대비 현재 위치 (4H 에너지)
    df["h4_open_gap"]  = (c - o) / (daily_range + 1e-9)

    # ── 1H 패턴 근사 ─────────────────────────
    # 일일 범위의 24분의 1 = 1H 근사
    df["h1_vol_sim"]  = (daily_range / 24) / (c + 1e-9)
    df["h1_range_ratio"] = daily_range / daily_range.rolling(20).mean()

    # 상위 25% / 하위 25% 변동성 비교 (변동성 클러스터링)
    vol_q75 = daily_range.rolling(20).quantile(0.75)
    vol_q25 = daily_range.rolling(20).quantile(0.25)
    df["h1_vol_cluster"] = (daily_range > vol_q75).astype(int) - (daily_range < vol_q25).astype(int)

    # ── 일봉 미세 구조 ────────────────────────
    # 위/아래 wick 비율 (매수세/매도세 판단)
    upper_wick = h - pd.concat([c, o], axis=1).max(axis=1)
    lower_wick = pd.concat([c, o], axis=1).min(axis=1) - l
    df["upper_wick_pct"] = upper_wick / (daily_range + 1e-9)
    df["lower_wick_pct"] = lower_wick / (daily_range + 1e-9)

    # 위/아래 wick 차이 (양수 = 매수 우위)
    df["wick_imbalance"] = (lower_wick - upper_wick) / (daily_range + 1e-9)

    # 연속 상승/하락 캔들 수
    up_streak = pd.Series(0, index=df.index)
    dn_streak = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        if daily_move.iloc[i] > 0:
            up_streak.iloc[i] = up_streak.iloc[i-1] + 1
            dn_streak.iloc[i] = 0
        elif daily_move.iloc[i] < 0:
            dn_streak.iloc[i] = dn_streak.iloc[i-1] + 1
            up_streak.iloc[i] = 0
    df["up_streak"] = up_streak / 10   # 0~1 정규화
    df["dn_streak"] = dn_streak / 10

    # 갭 (전일 종가 vs 당일 시가)
    df["gap_pct"] = (o - c.shift(1)) / (c.shift(1) + 1e-9)
    df["gap_filled"] = ((daily_move * df["gap_pct"]) < 0).astype(int)  # 갭 매움

    return df


def add_multi_timeframe_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    모든 타임프레임 피처 통합 추가
    일봉 → 주봉 + 월봉 + 분기봉 + 시간봉 패턴
    """
    df = add_weekly_features(df)
    df = add_monthly_features(df)
    df = add_quarterly_features(df)
    df = add_intraday_sim_features(df)
    return df


def get_mtf_feature_cols(df: pd.DataFrame) -> list:
    """멀티 타임프레임 피처 컬럼명 반환"""
    prefixes = ["w_", "m_", "q_", "h4_", "h1_",
                "upper_wick_pct", "lower_wick_pct", "wick_imbalance",
                "up_streak", "dn_streak", "gap_pct", "gap_filled"]
    cols = []
    for c in df.columns:
        for p in prefixes:
            if c.startswith(p) or c == p:
                cols.append(c)
                break
    return cols


if __name__ == "__main__":
    import os
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    df = pd.read_csv(os.path.join(ROOT, "data", "btc_daily.csv"))
    orig_cols = len(df.columns)

    df = add_multi_timeframe_features(df)
    mtf_cols = get_mtf_feature_cols(df)

    print(f"멀티 타임프레임 피처 추가 완료")
    print(f"  기존 컬럼: {orig_cols}개  →  추가 후: {len(df.columns)}개")
    print(f"  추가된 MTF 피처: {len(mtf_cols)}개")
    print(f"\n  주봉(W) 피처:  {[c for c in mtf_cols if c.startswith('w_')]}")
    print(f"  월봉(M) 피처:  {[c for c in mtf_cols if c.startswith('m_')]}")
    print(f"  분기(Q) 피처:  {[c for c in mtf_cols if c.startswith('q_')]}")
    print(f"  시간봉 피처:   {[c for c in mtf_cols if c.startswith('h4_') or c.startswith('h1_')]}")
