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

    df = _add_extra_indicators(df)
    return df


def _add_extra_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    스크린샷 지표 전체 추가
    CCI / Williams%R / MFI / CMO / Chaikin / Aroon / TRIX /
    Stoch RSI / Mass Index / Elder Ray / RVI / NVI / PVI /
    Parabolic SAR / Ichimoku / Heikin Ashi / 신심리도 / 이격도 /
    Volume OSC / VR / Envelopes / Price Channels / Pivot / AD Line / RMI
    """
    c = df["close"]
    h = df["high"]
    l = df["low"]
    v = df["volume"]
    o = df["open"] if "open" in df.columns else c.shift(1).fillna(c)

    # ── CCI (Commodity Channel Index) ──────────────────────
    for p in [14, 20]:
        tp  = (h + l + c) / 3
        sma = tp.rolling(p).mean()
        mad = tp.rolling(p).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
        df[f"cci_{p}"] = (tp - sma) / (0.015 * mad + 1e-9) / 100  # 정규화

    # ── Williams %R ────────────────────────────────────────
    for p in [14, 21]:
        hh = h.rolling(p).max()
        ll = l.rolling(p).min()
        df[f"williams_r_{p}"] = (hh - c) / (hh - ll + 1e-9) * (-1)  # -1~0

    # ── MFI (Money Flow Index) ─────────────────────────────
    tp = (h + l + c) / 3
    tp_prev = tp.shift(1)
    pos_mf = (tp * v).where(tp > tp_prev, 0.0)
    neg_mf = (tp * v).where(tp < tp_prev, 0.0)
    for p in [14]:
        mfr = pos_mf.rolling(p).sum() / (neg_mf.rolling(p).sum() + 1e-9)
        df[f"mfi_{p}"] = (100 - 100 / (1 + mfr)) / 100  # 0~1

    # ── CMO (Chande Momentum Oscillator) ───────────────────
    diff = c.diff()
    for p in [14, 20]:
        up = diff.clip(lower=0).rolling(p).sum()
        dn = (-diff.clip(upper=0)).rolling(p).sum()
        df[f"cmo_{p}"] = (up - dn) / (up + dn + 1e-9)  # -1~1

    # ── AD Line & Chaikin Money Flow & Chaikin OSC ─────────
    mfm = ((c - l) - (h - c)) / (h - l + 1e-9)  # Money Flow Multiplier
    mfv = mfm * v                                  # Money Flow Volume
    ad  = mfv.cumsum()
    df["ad_line"] = ad / (ad.abs().rolling(200, min_periods=20).max() + 1e-9)  # 정규화
    df["cmf_20"]  = mfv.rolling(20).sum() / (v.rolling(20).sum() + 1e-9)       # Chaikin MF
    ema3  = ad.ewm(span=3,  adjust=False).mean()
    ema10 = ad.ewm(span=10, adjust=False).mean()
    df["chaikin_osc"] = (ema3 - ema10) / (c * v.rolling(20).mean() + 1e-9)

    # ── Aroon (25) ─────────────────────────────────────────
    for p in [25]:
        roll_h = h.rolling(p + 1)
        roll_l = l.rolling(p + 1)
        aroon_up = roll_h.apply(lambda x: (p - x[::-1].argmax()) / p * 100, raw=True)
        aroon_dn = roll_l.apply(lambda x: (p - x[::-1].argmin()) / p * 100, raw=True)
        df[f"aroon_up_{p}"]  = aroon_up / 100
        df[f"aroon_dn_{p}"]  = aroon_dn / 100
        df[f"aroon_osc_{p}"] = (aroon_up - aroon_dn) / 100

    # ── TRIX ───────────────────────────────────────────────
    for p in [14, 20]:
        e1 = c.ewm(span=p, adjust=False).mean()
        e2 = e1.ewm(span=p, adjust=False).mean()
        e3 = e2.ewm(span=p, adjust=False).mean()
        trix = e3.pct_change() * 100
        df[f"trix_{p}"]       = trix
        df[f"trix_{p}_cross"] = (trix > 0).astype(int)

    # ── Stochastic RSI ─────────────────────────────────────
    delta = c.diff()
    g14   = delta.clip(lower=0).rolling(14).mean()
    l14   = (-delta.clip(upper=0)).rolling(14).mean()
    rsi14 = 100 - 100 / (1 + g14 / (l14 + 1e-9))
    rsi_min = rsi14.rolling(14).min()
    rsi_max = rsi14.rolling(14).max()
    stoch_rsi_k = (rsi14 - rsi_min) / (rsi_max - rsi_min + 1e-9)
    df["stoch_rsi_k"] = stoch_rsi_k.rolling(3).mean()
    df["stoch_rsi_d"] = df["stoch_rsi_k"].rolling(3).mean()

    # ── Mass Index ─────────────────────────────────────────
    hl_range  = h - l
    ema9_hl   = hl_range.ewm(span=9, adjust=False).mean()
    ema9_ema9 = ema9_hl.ewm(span=9, adjust=False).mean()
    df["mass_index"] = (ema9_hl / (ema9_ema9 + 1e-9)).rolling(25).sum() / 27  # 정규화

    # ── Elder Ray (Bull/Bear Power) ────────────────────────
    ema13 = c.ewm(span=13, adjust=False).mean()
    df["elder_bull"] = (h - ema13) / (c + 1e-9)   # 가격 정규화
    df["elder_bear"] = (l - ema13) / (c + 1e-9)

    # ── RVI (Relative Vigor Index) ─────────────────────────
    num = ((c - o) + 2*c.shift(1) - 2*o.shift(1) +
           2*c.shift(2) - 2*o.shift(2) + c.shift(3) - o.shift(3)) / 6
    den = ((h - l) + 2*h.shift(1) - 2*l.shift(1) +
           2*h.shift(2) - 2*l.shift(2) + h.shift(3) - l.shift(3)) / 6
    df["rvi"] = num.rolling(10).mean() / (den.rolling(10).mean().abs() + 1e-9)

    # ── RMI (Relative Momentum Index) ─────────────────────
    for mom in [3, 5]:
        diff_m = c.diff(mom)
        up_m   = diff_m.clip(lower=0).rolling(14).mean()
        dn_m   = (-diff_m.clip(upper=0)).rolling(14).mean()
        df[f"rmi_{mom}"] = (100 - 100 / (1 + up_m / (dn_m + 1e-9))) / 100

    # ── NVI & PVI (Negative/Positive Volume Index) ─────────
    vol_chg  = v.pct_change()
    ret_daily = c.pct_change()
    nvi_ret  = ret_daily.where(v < v.shift(1), 0.0)
    pvi_ret  = ret_daily.where(v > v.shift(1), 0.0)
    nvi = (1 + nvi_ret).cumprod()
    pvi = (1 + pvi_ret).cumprod()
    nvi_ema = nvi.ewm(span=255, adjust=False).mean()
    pvi_ema = pvi.ewm(span=255, adjust=False).mean()
    df["nvi_signal"] = (nvi > nvi_ema).astype(int)  # NVI > EMA → 강세
    df["pvi_signal"] = (pvi > pvi_ema).astype(int)

    # ── Parabolic SAR ──────────────────────────────────────
    # 간략 구현 (AF=0.02, max=0.2)
    af_step, af_max = 0.02, 0.2
    n = len(c)
    sar = c.values.copy().astype(float)
    bull = True
    ep   = float(h.iloc[0])
    af   = af_step
    for i in range(2, n):
        prev_sar = sar[i-1]
        if bull:
            sar[i] = prev_sar + af * (ep - prev_sar)
            sar[i] = min(sar[i], float(l.iloc[i-1]), float(l.iloc[i-2]))
            if float(l.iloc[i]) < sar[i]:
                bull = False; sar[i] = ep; ep = float(l.iloc[i]); af = af_step
            else:
                if float(h.iloc[i]) > ep:
                    ep = float(h.iloc[i]); af = min(af + af_step, af_max)
        else:
            sar[i] = prev_sar - af * (prev_sar - ep)
            sar[i] = max(sar[i], float(h.iloc[i-1]), float(h.iloc[i-2]))
            if float(h.iloc[i]) > sar[i]:
                bull = True; sar[i] = ep; ep = float(h.iloc[i]); af = af_step
            else:
                if float(l.iloc[i]) < ep:
                    ep = float(l.iloc[i]); af = min(af + af_step, af_max)
    df["psar_dist"]  = (c - pd.Series(sar, index=c.index)) / (c + 1e-9)
    df["psar_bull"]  = (c > pd.Series(sar, index=c.index)).astype(int)

    # ── Ichimoku Cloud (일목균형표) ────────────────────────
    tenkan  = (h.rolling(9).max()  + l.rolling(9).min())  / 2
    kijun   = (h.rolling(26).max() + l.rolling(26).min()) / 2
    span_a  = ((tenkan + kijun) / 2).shift(26)
    span_b  = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)
    chikou  = c.shift(-26)
    df["ichi_tenkan_dist"] = (c - tenkan) / (c + 1e-9)
    df["ichi_kijun_dist"]  = (c - kijun)  / (c + 1e-9)
    df["ichi_above_cloud"] = (c > span_a.combine(span_b, max)).astype(int)
    df["ichi_cloud_width"] = (span_a - span_b) / (c + 1e-9)
    df["ichi_tk_cross"]    = ((tenkan > kijun) & (tenkan.shift(1) <= kijun.shift(1))).astype(int)

    # ── Heikin Ashi (하이킨아시) ───────────────────────────
    ha_c = (o + h + l + c) / 4
    ha_o = ((o + c) / 2)
    ha_o = ha_o.ewm(alpha=0.5, adjust=False).mean()  # 근사
    df["ha_bull"]        = (ha_c > ha_o).astype(int)
    df["ha_body_ratio"]  = (ha_c - ha_o).abs() / ((h - l) + 1e-9)
    df["ha_consecutive"] = (df["ha_bull"] == df["ha_bull"].shift(1)).rolling(5).sum() / 5

    # ── Volume OSC ────────────────────────────────────────
    df["vol_osc"] = (v.ewm(span=5,  adjust=False).mean() /
                     (v.ewm(span=20, adjust=False).mean() + 1e-9)) - 1

    # ── VR (Volume Ratio) ─────────────────────────────────
    up_vol   = v.where(c > c.shift(1), 0.0)
    dn_vol   = v.where(c < c.shift(1), 0.0)
    flat_vol = v.where(c == c.shift(1), 0.0)
    for p in [14, 26]:
        vr = (up_vol.rolling(p).sum() + flat_vol.rolling(p).sum() * 0.5) / \
             (dn_vol.rolling(p).sum() + flat_vol.rolling(p).sum() * 0.5 + 1e-9)
        df[f"vr_{p}"] = vr

    # ── Envelopes (이동평균 ±2.5%) ───────────────────────
    sma20 = c.rolling(20).mean()
    df["envelope_upper"] = (c / (sma20 * 1.025)) - 1  # 상단 대비 위치
    df["envelope_lower"] = (c / (sma20 * 0.975)) - 1  # 하단 대비 위치

    # ── Price Channels / Donchian ─────────────────────────
    for p in [20, 55]:
        dc_h = h.rolling(p).max()
        dc_l = l.rolling(p).min()
        df[f"dc_pos_{p}"]    = (c - dc_l) / (dc_h - dc_l + 1e-9)   # 채널 내 위치
        df[f"dc_break_up_{p}"]  = (c >= dc_h.shift(1)).astype(int)
        df[f"dc_break_dn_{p}"]  = (c <= dc_l.shift(1)).astype(int)

    # ── Pivot Points (일봉 기준: 전날 H/L/C) ──────────────
    prev_h = h.shift(1)
    prev_l = l.shift(1)
    prev_c = c.shift(1)
    pivot  = (prev_h + prev_l + prev_c) / 3
    r1 = 2 * pivot - prev_l
    s1 = 2 * pivot - prev_h
    df["pivot_dist"]  = (c - pivot) / (c + 1e-9)
    df["pivot_r1_dist"] = (c - r1)   / (c + 1e-9)
    df["pivot_s1_dist"] = (c - s1)   / (c + 1e-9)

    # ── 신심리도 (Psychological Line) ─────────────────────
    for p in [12, 20]:
        up_days = (c > c.shift(1)).astype(int)
        df[f"psych_line_{p}"] = up_days.rolling(p).sum() / p  # 0~1

    # ── 이격도 (Disparity Index) ──────────────────────────
    for p in [5, 20, 60]:
        sma = c.rolling(p).mean()
        df[f"disparity_{p}"] = (c / sma) - 1

    # ── 투자심리도 (12일 상승 비율) ──────────────────────
    df["invest_psych"] = (c > c.shift(1)).astype(int).rolling(12).sum() / 12

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
