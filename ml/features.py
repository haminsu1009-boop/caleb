"""
ml/features.py
피처 엔지니어링 — 60개 이상의 특성 생성

단순 지표 수치가 아니라, 모델이 학습할 수 있는
'변화율', '상대위치', '패턴'으로 변환
"""

import numpy as np
import pandas as pd


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]

    # ── 수익률 (Returns) ───────────────────────
    for d in [1, 2, 3, 5, 7, 10, 14, 20, 30]:
        df[f"ret_{d}d"] = c.pct_change(d)

    # ── 변동성 (Volatility) ────────────────────
    for w in [5, 10, 20, 30]:
        df[f"vol_{w}d"] = c.pct_change().rolling(w).std()

    # ── RSI ───────────────────────────────────
    for p in [7, 14, 21]:
        delta = c.diff()
        g = delta.clip(lower=0).rolling(p).mean()
        ls = (-delta.clip(upper=0)).rolling(p).mean()
        rsi = 100 - 100 / (1 + g / ls.replace(0, np.nan))
        df[f"rsi_{p}"] = rsi / 100              # 0~1 정규화
        df[f"rsi_{p}_slope"] = rsi.diff(3) / 3  # RSI 기울기

    # ── MACD ──────────────────────────────────
    e12 = c.ewm(span=12, adjust=False).mean()
    e26 = c.ewm(span=26, adjust=False).mean()
    macd = e12 - e26
    sig  = macd.ewm(span=9, adjust=False).mean()
    df["macd_norm"]      = macd / c              # 가격 정규화
    df["macd_sig_norm"]  = sig  / c
    df["macd_hist_norm"] = (macd - sig) / c
    df["macd_cross"]     = ((macd > sig) & (macd.shift(1) <= sig.shift(1))).astype(int)

    # ── 볼린저 밴드 ───────────────────────────
    for w, k in [(20, 2.0), (20, 1.5)]:
        mid = c.rolling(w).mean()
        std = c.rolling(w).std()
        df[f"bb_pct_{k}"]   = (c - (mid - k*std)) / (2*k*std + 1e-9)  # 0~1 위치
        df[f"bb_width_{k}"] = (2*k*std) / mid                          # 밴드 폭

    # ── 스토캐스틱 ────────────────────────────
    for p in [14, 21]:
        lo = l.rolling(p).min()
        hi = h.rolling(p).max()
        k_val = (c - lo) / (hi - lo + 1e-9) * 100
        d_val = k_val.rolling(3).mean()
        df[f"stoch_k_{p}"] = k_val / 100
        df[f"stoch_d_{p}"] = d_val / 100
        df[f"stoch_cross_{p}"] = ((k_val > d_val) & (k_val.shift(1) <= d_val.shift(1))).astype(int)

    # ── ADX ───────────────────────────────────
    tr  = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    pdm = h.diff().clip(lower=0)
    mdm = (-l.diff()).clip(lower=0)
    atr = tr.rolling(14).mean()
    plus_di  = 100 * pdm.rolling(14).mean() / atr.replace(0, np.nan)
    minus_di = 100 * mdm.rolling(14).mean() / atr.replace(0, np.nan)
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9) * 100
    df["adx"]            = dx.rolling(14).mean() / 100
    df["di_diff"]        = (plus_di - minus_di) / 100
    df["di_ratio"]       = plus_di / (minus_di + 1e-9)

    # ── ATR (변동성 척도) ─────────────────────
    df["atr_pct"] = atr / c                      # 가격 대비 ATR

    # ── 이동평균 대비 위치 ────────────────────
    for p in [7, 20, 50, 100, 200]:
        sma = c.rolling(p).mean()
        ema = c.ewm(span=p, adjust=False).mean()
        df[f"close_vs_sma{p}"] = (c / sma) - 1
        df[f"close_vs_ema{p}"] = (c / ema) - 1

    # ── 이동평균 크로스 ───────────────────────
    sma20  = c.rolling(20).mean()
    sma50  = c.rolling(50).mean()
    sma200 = c.rolling(200).mean()
    df["sma20_vs_50"]   = (sma20  / sma50)  - 1
    df["sma50_vs_200"]  = (sma50  / sma200) - 1
    df["golden_cross"]  = ((sma50 > sma200) & (sma50.shift(1) <= sma200.shift(1))).astype(int)
    df["death_cross"]   = ((sma50 < sma200) & (sma50.shift(1) >= sma200.shift(1))).astype(int)

    # ── 거래량 지표 ───────────────────────────
    for w in [5, 10, 20]:
        df[f"vol_ratio_{w}d"] = v / v.rolling(w).mean()
    obv = (np.sign(c.diff()) * v).fillna(0).cumsum()
    df["obv_slope"]  = obv.diff(5) / (obv.rolling(20).std() + 1e-9)  # 정규화된 OBV 기울기

    # ── 캔들 패턴 ─────────────────────────────
    body   = (c - df["open"]).abs()
    candle = (h - l).replace(0, np.nan)
    df["body_ratio"]   = body / candle            # 몸통 비율
    df["upper_shadow"]  = (h - c.clip(lower=df["open"])) / candle
    df["lower_shadow"]  = (c.clip(upper=df["open"]) - l) / candle
    df["is_bullish"]    = (c > df["open"]).astype(int)
    df["is_doji"]       = (body / candle < 0.1).astype(int)

    # ── 고점/저점 돌파 ────────────────────────
    for w in [10, 20, 52]:
        df[f"at_high_{w}d"] = ((h >= h.rolling(w).max()) & (h >= h.rolling(w).max().shift(1))).astype(int)
        df[f"at_low_{w}d"]  = ((l <= l.rolling(w).min()) & (l <= l.rolling(w).min().shift(1))).astype(int)
        df[f"high_pct_{w}d"] = c / h.rolling(w).max()  # 고점 대비 현재가
        df[f"low_pct_{w}d"]  = c / l.rolling(w).min()  # 저점 대비 현재가

    # ── 모멘텀 가속도 ─────────────────────────
    ret5  = c.pct_change(5)
    ret20 = c.pct_change(20)
    df["momentum_accel"]  = ret5  - ret5.shift(5)
    df["momentum_div"]    = ret5 / (ret20 + 1e-9)   # 단기/장기 모멘텀 비율

    # ── 시장 국면 (Market Regime) ─────────────
    df["is_uptrend"]    = (sma20 > sma50).astype(int)
    df["is_bull_market"] = (c > sma200).astype(int)
    df["trend_strength"] = df["close_vs_sma50"].rolling(10).mean()

    # ── 날짜 특성 (계절성) ────────────────────
    dates = pd.to_datetime(df["date"])
    df["day_of_week"] = dates.dt.dayofweek / 6
    df["month"]       = dates.dt.month
    df["month_sin"]   = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"]   = np.cos(2 * np.pi * df["month"] / 12)
    df["quarter"]     = dates.dt.quarter

    # ── BTC/크립토 전용 피처 ──────────────────
    # ATH 대비 하락률 (강력한 BTC 사이클 지표)
    rolling_ath = c.expanding().max()
    df["drawdown_from_ath"] = (c / rolling_ath) - 1   # 0=ATH, -0.8=-80% drawdown

    # 52주 상·하단 위치 (연간 사이클)
    hi_52w = h.rolling(365, min_periods=30).max()
    lo_52w = l.rolling(365, min_periods=30).min()
    df["price_in_52w_range"] = (c - lo_52w) / (hi_52w - lo_52w + 1e-9)

    # BTC 4년 반감기 사이클 (halvings: 2012-11-28, 2016-07-09, 2020-05-11, 2024-04-19)
    halvings = pd.to_datetime(["2012-11-28", "2016-07-09", "2020-05-11", "2024-04-19"])
    def days_since_halving(dt):
        past = halvings[halvings <= dt]
        if len(past) == 0:
            return 365 * 4   # 반감기 전 → 최대값
        days = (dt - past[-1]).days
        return min(days, 365 * 4)

    halving_days = dates.apply(days_since_halving)
    df["halving_cycle_pct"] = halving_days / (365 * 4)   # 0=직후, 1=4년 후
    df["halving_cycle_sin"]  = np.sin(2 * np.pi * df["halving_cycle_pct"])
    df["halving_cycle_cos"]  = np.cos(2 * np.pi * df["halving_cycle_pct"])

    # 누적 수익률 주기 (단/중/장기 모멘텀 팩터)
    for p in [30, 60, 90, 180]:
        df[f"cum_ret_{p}d"] = c / c.shift(p) - 1

    # 변동성 국면 (낮은 변동성 → 돌파 준비, Bollinger Squeeze)
    vol_20 = c.pct_change().rolling(20).std()
    vol_60 = c.pct_change().rolling(60).std()
    df["vol_compression"] = vol_20 / (vol_60 + 1e-9)   # <0.8 = squeeze 진행 중

    # 가격 가속도 (모멘텀 변화율)
    ret1  = c.pct_change(1)
    ret3  = c.pct_change(3)
    ret10 = c.pct_change(10)
    df["accel_1_3"]  = ret1  - ret3  / 3     # 최근 가속/감속
    df["accel_3_10"] = ret3  - ret10 / 10 * 3

    # 분봉 가중 가격 (VWAP 근사: Close × Volume / MA(Volume))
    vwap_approx = (c * v).rolling(20).sum() / (v.rolling(20).sum() + 1e-9)
    df["vwap_deviation"] = (c / vwap_approx) - 1

    return df


def make_targets(df: pd.DataFrame, hold_days: int = 3, threshold: float = 0.01) -> pd.DataFrame:
    """
    타겟 변수 생성
    - target_ret:  hold_days 후 실제 수익률
    - target_bin:  2진 분류 (수익 > threshold → 1)
    - target_3cls: 3진 분류 (강매수/중립/강매도)
    """
    future_close = df["close"].shift(-hold_days)
    ret = (future_close / df["close"]) - 1

    df["target_ret"]  = ret
    df["target_bin"]  = (ret > threshold).astype(int)

    # 3분류: 상위 33% = 매수, 하위 33% = 매도, 중간 = 보류
    df["target_3cls"] = 1  # 기본값: 중립
    df.loc[ret > ret.quantile(0.67), "target_3cls"] = 2  # 매수
    df.loc[ret < ret.quantile(0.33), "target_3cls"] = 0  # 매도

    return df


def make_directional_targets(
    df: pd.DataFrame,
    hold_days: int   = 3,
    threshold: float = 0.015,
) -> pd.DataFrame:
    """
    롱/숏 방향성 타겟 생성 (위아래 발라먹기용)

    - target_long:  수익률 > +threshold  → 1 (롱 기회)
    - target_short: 수익률 < -threshold  → 1 (숏 기회)
    - target_ret:   미래 수익률 (실수)
    - direction:    +1(LONG) / -1(SHORT) / 0(NEUTRAL)
    """
    df = df.copy()
    future_close = df["close"].shift(-hold_days)
    ret = (future_close / df["close"]) - 1

    df["target_ret"]   = ret
    df["target_long"]  = (ret >  threshold).astype(int)   # 롱 타겟
    df["target_short"] = (ret < -threshold).astype(int)   # 숏 타겟

    # 3방향: +1=LONG, -1=SHORT, 0=NEUTRAL
    direction = pd.Series(0, index=df.index)
    direction[ret >  threshold] =  1
    direction[ret < -threshold] = -1
    df["direction"] = direction

    # 기존 target_bin 호환성 유지
    df["target_bin"] = df["target_long"]

    return df


def get_feature_cols(df: pd.DataFrame) -> list:
    """학습에 사용할 피처 컬럼 반환 (타겟/원시 가격 제외)"""
    exclude = {
        "date", "open", "high", "low", "close", "volume",
        "quote_volume", "trades",
        # 타겟 변수 — 절대 피처로 사용하면 안 됨 (데이터 누수!)
        "target_ret", "target_bin", "target_3cls",
        "target_long", "target_short", "direction",
        # 심볼 / 시장 구분자
        "symbol", "_symbol", "market",
    }
    return [c for c in df.columns
            if c not in exclude
            and df[c].dtype in (np.float64, np.int64, float, int)]


if __name__ == "__main__":
    import os
    DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "btc_daily.csv")
    df = pd.read_csv(DATA_FILE)
    df = add_features(df)
    df = make_targets(df)
    fcols = get_feature_cols(df)
    print(f"피처 수: {len(fcols)}개")
    print(f"샘플 수: {len(df.dropna())}개")
    print(f"피처 목록:\n{fcols}")
