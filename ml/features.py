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

    # ═══════════════════════════════════════════════════
    # 추가 프로급 지표
    # SuperTrend / Keltner / Squeeze / KST / Ultimate /
    # DPO / Fisher / Z-score / KAMA / ROC / AO / HMA /
    # Efficiency Ratio / DEMA / TEMA
    # ═══════════════════════════════════════════════════

    # ── SuperTrend (ATR 기반 추세 추종) ───────────────
    tr  = pd.concat([h - l,
                     (h - c.shift()).abs(),
                     (l - c.shift()).abs()], axis=1).max(axis=1)
    atr14 = tr.ewm(span=14, adjust=False).mean()
    for mult in [2.0, 3.0]:
        upper = (h + l) / 2 + mult * atr14
        lower = (h + l) / 2 - mult * atr14
        st = c.copy()
        bull_st = True
        for i in range(1, len(c)):
            if bull_st:
                lower.iloc[i] = max(lower.iloc[i], lower.iloc[i-1])
                if c.iloc[i] < lower.iloc[i]:
                    bull_st = False; st.iloc[i] = upper.iloc[i]
                else:
                    st.iloc[i] = lower.iloc[i]
            else:
                upper.iloc[i] = min(upper.iloc[i], upper.iloc[i-1])
                if c.iloc[i] > upper.iloc[i]:
                    bull_st = True; st.iloc[i] = lower.iloc[i]
                else:
                    st.iloc[i] = upper.iloc[i]
        tag = str(mult).replace('.', '')
        df[f"supertrend_dist_{tag}"] = (c - st) / (c + 1e-9)
        df[f"supertrend_bull_{tag}"] = (c > st).astype(int)

    # ── Keltner Channel ────────────────────────────────
    ema20 = c.ewm(span=20, adjust=False).mean()
    for mult in [1.5, 2.0]:
        kc_upper = ema20 + mult * atr14
        kc_lower = ema20 - mult * atr14
        tag = str(mult).replace('.', '')
        df[f"kc_pos_{tag}"]   = (c - kc_lower) / (kc_upper - kc_lower + 1e-9)  # 0~1 위치
        df[f"kc_width_{tag}"] = (kc_upper - kc_lower) / (ema20 + 1e-9)

    # ── Squeeze Momentum (Bollinger + Keltner 결합) ────
    bb_mid = c.rolling(20).mean()
    bb_std = c.rolling(20).std()
    bb_up  = bb_mid + 2.0 * bb_std
    bb_lo  = bb_mid - 2.0 * bb_std
    kc_up  = ema20 + 1.5 * atr14
    kc_lo  = ema20 - 1.5 * atr14
    # Squeeze ON = BB 안에 KC 포함 → 변동성 압축 → 곧 폭발
    df["squeeze_on"]  = ((bb_up < kc_up) & (bb_lo > kc_lo)).astype(int)
    df["squeeze_off"] = ((bb_up > kc_up) & (bb_lo < kc_lo)).astype(int)
    # 모멘텀: 중간값 기반 선형회귀 잔차
    val = c - (c.rolling(20).max() + c.rolling(20).min()) / 2
    df["squeeze_mom"] = val.rolling(20).apply(
        lambda x: np.polyfit(range(len(x)), x, 1)[0], raw=True)
    df["squeeze_mom"] = df["squeeze_mom"] / (c + 1e-9)   # 정규화

    # ── KST (Know Sure Thing) ─────────────────────────
    def roc(s, n): return s.pct_change(n)
    def smroc(s, n, m): return roc(s, n).rolling(m).mean()
    kst = (smroc(c, 10, 10) * 1 + smroc(c, 13, 13) * 2 +
           smroc(c, 15, 15) * 3 + smroc(c, 20, 20) * 4)
    df["kst"]       = kst / (kst.abs().rolling(100, min_periods=20).max() + 1e-9)
    df["kst_sig"]   = kst.rolling(9).mean() / (kst.abs().rolling(100, min_periods=20).max() + 1e-9)
    df["kst_cross"] = ((kst > kst.rolling(9).mean()) &
                       (kst.shift(1) <= kst.shift(1).rolling(9).mean())).astype(int)

    # ── Ultimate Oscillator (3주기 모멘텀) ───────────
    bp = c - pd.concat([l, c.shift()], axis=1).min(axis=1)  # Buying Pressure
    tr2 = pd.concat([h, c.shift()], axis=1).max(axis=1) - \
          pd.concat([l, c.shift()], axis=1).min(axis=1)
    avg7  = bp.rolling(7).sum()  / (tr2.rolling(7).sum()  + 1e-9)
    avg14 = bp.rolling(14).sum() / (tr2.rolling(14).sum() + 1e-9)
    avg28 = bp.rolling(28).sum() / (tr2.rolling(28).sum() + 1e-9)
    df["ult_osc"] = (4 * avg7 + 2 * avg14 + avg28) / 7  # 0~1

    # ── DPO (Detrended Price Oscillator) ──────────────
    for p in [14, 20]:
        shift_n = p // 2 + 1
        df[f"dpo_{p}"] = c.shift(shift_n) - c.rolling(p).mean().shift(shift_n)
        df[f"dpo_{p}"] = df[f"dpo_{p}"] / (c + 1e-9)

    # ── Fisher Transform ───────────────────────────────
    for p in [14]:
        hi_p = h.rolling(p).max()
        lo_p = l.rolling(p).min()
        val  = 2 * ((c - lo_p) / (hi_p - lo_p + 1e-9)) - 1
        val  = val.clip(-0.999, 0.999)
        fish = 0.5 * np.log((1 + val) / (1 - val + 1e-9))
        df[f"fisher_{p}"]     = fish / 3   # 정규화 (보통 -3~3)
        df[f"fisher_{p}_sig"] = df[f"fisher_{p}"].shift(1)

    # ── Z-Score (가격 표준화) ──────────────────────────
    for w in [20, 60]:
        mean = c.rolling(w).mean()
        std  = c.rolling(w).std()
        df[f"zscore_{w}"] = (c - mean) / (std + 1e-9)

    # ── KAMA (Kaufman Adaptive MA) ────────────────────
    fast_sc = 2 / (2 + 1)
    slow_sc = 2 / (30 + 1)
    direction_abs = c.diff(10).abs()
    volatility    = c.diff().abs().rolling(10).sum()
    er  = direction_abs / (volatility + 1e-9)   # Efficiency Ratio 0~1
    sc  = (er * (fast_sc - slow_sc) + slow_sc) ** 2
    kama = c.copy().astype(float)
    for i in range(1, len(c)):
        kama.iloc[i] = kama.iloc[i-1] + sc.iloc[i] * (c.iloc[i] - kama.iloc[i-1])
    df["kama_dist"]        = (c - kama) / (c + 1e-9)
    df["efficiency_ratio"] = er   # 0=무작위, 1=완전한 추세

    # ── Price ROC (Rate of Change) ─────────────────────
    for p in [5, 10, 21]:
        df[f"roc_{p}"] = c.pct_change(p)   # ret_Nd와 동일하나 명시적으로 추가

    # ── Awesome Oscillator (AO) ────────────────────────
    mid = (h + l) / 2
    df["awesome_osc"] = mid.rolling(5).mean() - mid.rolling(34).mean()
    df["awesome_osc"] = df["awesome_osc"] / (c + 1e-9)   # 가격 정규화

    # ── HMA (Hull Moving Average) ──────────────────────
    for p in [20, 50]:
        half = int(p / 2)
        sqrtp = int(np.sqrt(p))
        wma_half = c.rolling(half).mean()
        wma_full = c.rolling(p).mean()
        hma = (2 * wma_half - wma_full).rolling(sqrtp).mean()
        df[f"hma_dist_{p}"] = (c / (hma + 1e-9)) - 1
        df[f"hma_slope_{p}"] = hma.pct_change(3)

    # ── DEMA / TEMA (Double/Triple EMA) ───────────────
    for p in [20, 50]:
        ema1 = c.ewm(span=p, adjust=False).mean()
        ema2 = ema1.ewm(span=p, adjust=False).mean()
        ema3 = ema2.ewm(span=p, adjust=False).mean()
        dema = 2 * ema1 - ema2
        tema = 3 * ema1 - 3 * ema2 + ema3
        df[f"dema_dist_{p}"] = (c / (dema + 1e-9)) - 1
        df[f"tema_dist_{p}"] = (c / (tema + 1e-9)) - 1

    # ── 변동성 비율 (Short/Long Vol Ratio) ────────────
    df["vol_ratio_5_20"]  = c.pct_change().rolling(5).std()  / (c.pct_change().rolling(20).std()  + 1e-9)
    df["vol_ratio_10_60"] = c.pct_change().rolling(10).std() / (c.pct_change().rolling(60).std()  + 1e-9)

    # ── 가격 레벨 상대 강도 (Rolling Quantile) ─────────
    for w in [60, 120]:
        df[f"price_pctile_{w}"] = c.rolling(w).rank(pct=True)   # 0~1 (현재가의 과거 분위수)

    # ═══════════════════════════════════════════════════
    # 스크린샷 누락 지표 추가
    # Williams Acc/Dist / BWI / AB Ratio /
    # 그물망 / 르모차트 / CMF 크로스 / DMI 크로스 /
    # Stochastic Momentum (SMI)
    # ═══════════════════════════════════════════════════

    # ── Williams Accumulation/Distribution ────────────
    # Larry Williams의 A/D: 종가가 중간보다 위면 축적, 아래면 분산
    true_high = pd.concat([h, c.shift(1)], axis=1).max(axis=1)
    true_low  = pd.concat([l, c.shift(1)], axis=1).min(axis=1)
    williams_ad = pd.Series(0.0, index=c.index)
    for i in range(1, len(c)):
        ci, hi_, li_ = float(c.iloc[i]), float(true_high.iloc[i]), float(true_low.iloc[i])
        mid = (hi_ + li_) / 2
        if ci > mid:
            williams_ad.iloc[i] = williams_ad.iloc[i-1] + (ci - li_)
        elif ci < mid:
            williams_ad.iloc[i] = williams_ad.iloc[i-1] - (hi_ - ci)
        else:
            williams_ad.iloc[i] = williams_ad.iloc[i-1]
    # 가격 대비 정규화
    w_scale = williams_ad.abs().rolling(200, min_periods=20).max() + 1e-9
    df["williams_ad"]       = williams_ad / w_scale
    df["williams_ad_slope"] = (williams_ad.diff(5) / (w_scale + 1e-9))   # 방향성

    # ── BWI (Bollinger Bandwidth Index) ───────────────
    # (UpperBB - LowerBB) / MiddleBB × 100 → 변동성 확장/수축
    for w, k in [(20, 2.0)]:
        mid_bb = c.rolling(w).mean()
        std_bb = c.rolling(w).std()
        bwi = (2 * k * std_bb) / (mid_bb + 1e-9) * 100
        df["bwi"] = bwi
        # BWI 최저점 대비 현재 위치 (Squeeze 해소 시기 탐지)
        df["bwi_vs_low"] = bwi / (bwi.rolling(100, min_periods=20).min() + 1e-9)

    # ── AB Ratio (Advance/Bearish Ratio) ──────────────
    # 상승/하락 거래량 비율: 상승일 거래량 ÷ 하락일 거래량
    up_v   = v.where(c > c.shift(1), 0.0)
    dn_v   = v.where(c < c.shift(1), 0.0)
    for w in [10, 20]:
        ab = up_v.rolling(w).sum() / (dn_v.rolling(w).sum() + 1e-9)
        df[f"ab_ratio_{w}"] = ab / (ab.rolling(60, min_periods=10).mean() + 1e-9)  # 정규화

    # ── 그물망 (Moving Average Web) ────────────────────
    # 단/중/장기 MA 5개의 배열 상태 → 정배열(1) / 역배열(-1)
    ma5   = c.rolling(5).mean()
    ma10  = c.rolling(10).mean()
    ma20  = c.rolling(20).mean()
    ma60  = c.rolling(60).mean()
    ma120 = c.rolling(120).mean()
    # 정배열: 5 > 10 > 20 > 60 > 120
    perfect_bull = ((ma5 > ma10) & (ma10 > ma20) & (ma20 > ma60) & (ma60 > ma120)).astype(int)
    # 역배열: 5 < 10 < 20 < 60 < 120
    perfect_bear = ((ma5 < ma10) & (ma10 < ma20) & (ma20 < ma60) & (ma60 < ma120)).astype(int)
    # 배열 점수 (0~4): 몇 개나 순서대로 배열됐는지
    score = ((ma5 > ma10).astype(int) + (ma10 > ma20).astype(int) +
             (ma20 > ma60).astype(int) + (ma60 > ma120).astype(int))
    df["ma_web_bull"]  = perfect_bull          # 완전 정배열
    df["ma_web_bear"]  = perfect_bear          # 완전 역배열
    df["ma_web_score"] = (score - 2) / 2       # -1(역배열)~+1(정배열) 정규화
    # 그물망 수렴도: MA들이 얼마나 뭉쳐있나 (낮을수록 돌파 임박)
    ma_spread = pd.concat([ma5, ma10, ma20, ma60, ma120], axis=1).std(axis=1)
    df["ma_web_spread"] = ma_spread / (c + 1e-9)

    # ── 르모차트 (Renko-style 피처) ────────────────────
    # Renko: ATR 기준 벽돌 단위로 움직임만 기록 (시간 무시)
    # 피처: 연속 상승/하락 벽돌 수, 방향 전환 신호
    atr10 = tr.rolling(10).mean()  # ATR10 as brick size
    brick = atr10.mean() if not atr10.empty else 1.0
    # 방향 변화 = 가격 변동이 벽돌 크기 초과
    price_chg = c.diff().abs()
    df["renko_signal"]     = (price_chg > atr10).astype(int)          # 벽돌 생성 시그널
    df["renko_bull"]       = ((c.diff() > atr10)).astype(int)         # 상승 벽돌
    df["renko_bear"]       = ((c.diff() < -atr10)).astype(int)        # 하락 벽돌
    # 연속 같은 방향 횟수 (모멘텀 강도 대리변수)
    direction_sign = np.sign(c.diff())
    df["renko_consec"] = direction_sign.groupby(
        (direction_sign != direction_sign.shift()).cumsum()).cumcount() / 10  # 정규화

    # ── Chaikin Money Flow 크로스 ─────────────────────
    # CMF가 0선 위로 돌파 → 매수, 아래로 돌파 → 매도
    cmf = df["cmf_20"]   # 이미 계산된 CMF 재사용
    df["cmf_cross_up"]  = ((cmf > 0) & (cmf.shift(1) <= 0)).astype(int)   # 0선 상향돌파
    df["cmf_cross_dn"]  = ((cmf < 0) & (cmf.shift(1) >= 0)).astype(int)   # 0선 하향돌파
    df["cmf_bull_zone"] = (cmf > 0).astype(int)                            # 강세 구간

    # ── DMI 크로스 (+DI / -DI 교차) ──────────────────
    # 이미 계산된 +DI/-DI 재계산 (전역 변수 없으므로 다시 계산)
    tr2b = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    pdm2 = h.diff().clip(lower=0)
    mdm2 = (-l.diff()).clip(lower=0)
    atr2 = tr2b.rolling(14).mean()
    pdi  = 100 * pdm2.rolling(14).mean() / (atr2 + 1e-9)
    mdi  = 100 * mdm2.rolling(14).mean() / (atr2 + 1e-9)
    df["dmi_cross_bull"] = ((pdi > mdi) & (pdi.shift(1) <= mdi.shift(1))).astype(int)  # +DI 상향돌파
    df["dmi_cross_bear"] = ((pdi < mdi) & (pdi.shift(1) >= mdi.shift(1))).astype(int)  # -DI 상향돌파
    df["dmi_bull_zone"]  = (pdi > mdi).astype(int)

    # ── Stochastic Momentum Index (SMI) ───────────────
    # 일반 스토캐스틱보다 정교: 중간값 기준 이중 스무딩
    for p in [14]:
        m = (h.rolling(p).max() + l.rolling(p).min()) / 2   # 중간값
        d = h.rolling(p).max() - l.rolling(p).min()          # 범위
        # 이중 EMA 스무딩
        ds  = (c - m).ewm(span=3, adjust=False).mean().ewm(span=3, adjust=False).mean()
        dhl = (d / 2).ewm(span=3, adjust=False).mean().ewm(span=3, adjust=False).mean()
        smi = ds / (dhl + 1e-9) * 100
        df[f"smi_{p}"]     = smi / 100                                           # -1~1 정규화
        df[f"smi_{p}_sig"] = smi.ewm(span=10, adjust=False).mean() / 100
        df[f"smi_{p}_cross"] = ((smi > smi.ewm(span=10, adjust=False).mean()) &
                                (smi.shift(1) <= smi.shift(1).ewm(span=10, adjust=False).mean())).astype(int)

    # ═══════════════════════════════════════════════════
    # 스크린샷 크로스/과매수과매도 시그널 전체 추가
    # ═══════════════════════════════════════════════════

    # ── RSI 과매수&과매도 (바이너리 시그널) ───────────
    for p in [7, 14, 21]:
        rsi_raw = df[f"rsi_{p}"] * 100   # 0~100 복원
        df[f"rsi_{p}_ob"] = (rsi_raw > 70).astype(int)   # 과매수 구간
        df[f"rsi_{p}_os"] = (rsi_raw < 30).astype(int)   # 과매도 구간
        df[f"rsi_{p}_ob_exit"] = ((rsi_raw < 70) & (rsi_raw.shift(1) >= 70)).astype(int)  # 과매수 탈출
        df[f"rsi_{p}_os_exit"] = ((rsi_raw > 30) & (rsi_raw.shift(1) <= 30)).astype(int)  # 과매도 탈출

    # ── CCI 과매수&과매도 ──────────────────────────────
    for p in [14, 20]:
        cci_raw = df[f"cci_{p}"] * 100   # 정규화 복원
        df[f"cci_{p}_ob"] = (cci_raw > 100).astype(int)    # 과매수 (>+100)
        df[f"cci_{p}_os"] = (cci_raw < -100).astype(int)   # 과매도 (<-100)
        df[f"cci_{p}_ob_exit"] = ((cci_raw < 100) & (cci_raw.shift(1) >= 100)).astype(int)
        df[f"cci_{p}_os_exit"] = ((cci_raw > -100) & (cci_raw.shift(1) <= -100)).astype(int)

    # ── Stochastic Fast 크로스 + 과매수&과매도 ─────────
    # Fast: raw %K, D = 3-period SMA of K (smoothing 없음)
    for p in [14, 21]:
        lo_p = l.rolling(p).min()
        hi_p = h.rolling(p).max()
        fast_k = (c - lo_p) / (hi_p - lo_p + 1e-9) * 100
        fast_d = fast_k.rolling(3).mean()
        # 크로스: 상향(매수) / 하향(매도)
        df[f"stoch_fast_cross_up_{p}"]  = ((fast_k > fast_d) & (fast_k.shift(1) <= fast_d.shift(1))).astype(int)
        df[f"stoch_fast_cross_dn_{p}"]  = ((fast_k < fast_d) & (fast_k.shift(1) >= fast_d.shift(1))).astype(int)
        # 과매수&과매도 구간
        df[f"stoch_fast_ob_{p}"] = (fast_k > 80).astype(int)
        df[f"stoch_fast_os_{p}"] = (fast_k < 20).astype(int)
        # 과매수/과매도 탈출 (더 강한 시그널)
        df[f"stoch_fast_ob_exit_{p}"] = ((fast_k < 80) & (fast_k.shift(1) >= 80)).astype(int)
        df[f"stoch_fast_os_exit_{p}"] = ((fast_k > 20) & (fast_k.shift(1) <= 20)).astype(int)

    # ── Stochastic Slow 크로스 + 과매수&과매도 ─────────
    # Slow: K = 3-period SMA of raw %K, D = 3-period SMA of SlowK
    for p in [14, 21]:
        lo_p = l.rolling(p).min()
        hi_p = h.rolling(p).max()
        raw_k   = (c - lo_p) / (hi_p - lo_p + 1e-9) * 100
        slow_k  = raw_k.rolling(3).mean()    # Slow %K
        slow_d  = slow_k.rolling(3).mean()   # Slow %D
        df[f"stoch_slow_cross_up_{p}"]  = ((slow_k > slow_d) & (slow_k.shift(1) <= slow_d.shift(1))).astype(int)
        df[f"stoch_slow_cross_dn_{p}"]  = ((slow_k < slow_d) & (slow_k.shift(1) >= slow_d.shift(1))).astype(int)
        df[f"stoch_slow_ob_{p}"] = (slow_k > 80).astype(int)
        df[f"stoch_slow_os_{p}"] = (slow_k < 20).astype(int)
        df[f"stoch_slow_k_{p}"]  = slow_k / 100
        df[f"stoch_slow_d_{p}"]  = slow_d / 100

    # ── TRIX 크로스 (시그널선 기준, 0선 아님) ─────────
    # 기존 trix_cross는 >0 기준 → 시그널선(9-period SMA) 기준으로 교체
    for p in [14, 20]:
        e1 = c.ewm(span=p, adjust=False).mean()
        e2 = e1.ewm(span=p, adjust=False).mean()
        e3 = e2.ewm(span=p, adjust=False).mean()
        trix = e3.pct_change() * 100
        trix_sig = trix.rolling(9).mean()   # 시그널선
        df[f"trix_{p}_sig"]          = trix_sig
        df[f"trix_{p}_sig_cross_up"] = ((trix > trix_sig) & (trix.shift(1) <= trix_sig.shift(1))).astype(int)
        df[f"trix_{p}_sig_cross_dn"] = ((trix < trix_sig) & (trix.shift(1) >= trix_sig.shift(1))).astype(int)
        df[f"trix_{p}_zero_cross_up"] = ((trix > 0) & (trix.shift(1) <= 0)).astype(int)
        df[f"trix_{p}_zero_cross_dn"] = ((trix < 0) & (trix.shift(1) >= 0)).astype(int)

    # ── MACD 크로스 하향 (기존 상향 크로스 보완) ──────
    e12 = c.ewm(span=12, adjust=False).mean()
    e26 = c.ewm(span=26, adjust=False).mean()
    macd2 = e12 - e26
    sig2  = macd2.ewm(span=9, adjust=False).mean()
    df["macd_cross_dn"]   = ((macd2 < sig2) & (macd2.shift(1) >= sig2.shift(1))).astype(int)
    df["macd_zero_cross_up"] = ((macd2 > 0) & (macd2.shift(1) <= 0)).astype(int)   # 0선 상향
    df["macd_zero_cross_dn"] = ((macd2 < 0) & (macd2.shift(1) >= 0)).astype(int)   # 0선 하향

    # ── 이격도 과열&침체 (Disparity overbought/oversold) ─
    for p in [5, 20, 60]:
        sma = c.rolling(p).mean()
        disp = (c / sma) - 1
        # 과열: 이격도 상위 10%, 침체: 하위 10%
        ob_th = disp.rolling(252, min_periods=60).quantile(0.90)
        os_th = disp.rolling(252, min_periods=60).quantile(0.10)
        df[f"disp_{p}_ob"] = (disp > ob_th).astype(int)   # 과열 구간
        df[f"disp_{p}_os"] = (disp < os_th).astype(int)   # 침체 구간

    # ── 거래대금 (Trading Value) ────────────────────────
    # quote_volume = close × volume (이미 수집됨)
    qv = df.get("quote_volume", c * v)
    qv_ma20 = qv.rolling(20).mean()
    df["qv_ratio_5"]  = qv.rolling(5).mean()  / (qv_ma20 + 1e-9)   # 5일 거래대금 비율
    df["qv_ratio_10"] = qv.rolling(10).mean() / (qv_ma20 + 1e-9)   # 10일 거래대금 비율
    df["qv_surge"]    = (qv > qv_ma20 * 2).astype(int)              # 거래대금 급증

    # ── Williams %R 과매수&과매도 ─────────────────────
    for p in [14, 21]:
        wr = df[f"williams_r_{p}"]   # -1~0 범위
        df[f"willr_{p}_ob"] = (wr > -0.2).astype(int)   # 과매수 (>-20)
        df[f"willr_{p}_os"] = (wr < -0.8).astype(int)   # 과매도 (<-80)

    # ── MFI 과매수&과매도 ──────────────────────────────
    mfi = df["mfi_14"]
    df["mfi_ob"] = (mfi > 0.8).astype(int)   # 과매수 (>80)
    df["mfi_os"] = (mfi < 0.2).astype(int)   # 과매도 (<20)

    # ── 매물대 (Volume Profile / Price Supply-Demand Zones) ─
    # 현재가가 과거 N일 중 거래량이 집중된 구간에 있는지 측정
    # 방법: 가격 범위를 20개 버킷으로 나눠 거래량 가중치 계산
    for w in [60, 120]:
        hi_w = h.rolling(w, min_periods=10).max()
        lo_w = l.rolling(w, min_periods=10).min()
        price_range = hi_w - lo_w + 1e-9

        # 현재가의 버킷 위치 (0~1)
        c_pos = (c - lo_w) / price_range   # 0=저점, 1=고점

        # 가격대별 거래량 집중도 (VWAP 근사)
        # 현재가 근방 ±10% 범위의 거래량 합 / 전체 거래량
        def vol_near(pos, v_series, c_series, lo_series, range_series, w_):
            # 현재가 ±10% 가격 버킷 내 거래량 비중
            bucket = (c_series - lo_series) / range_series
            near = v_series.where((bucket - pos).abs() < 0.1, 0.0)
            return near.rolling(w_, min_periods=10).sum() / (
                v_series.rolling(w_, min_periods=10).sum() + 1e-9)

        df[f"supply_zone_{w}"]  = vol_near(c_pos, v, c, lo_w, price_range, w)  # 현재가 밀집도
        df[f"above_supply_{w}"] = (c_pos > 0.7).astype(int)   # 상단 매물대 영역
        df[f"below_supply_{w}"] = (c_pos < 0.3).astype(int)   # 하단 매물대 영역
        df[f"mid_supply_{w}"]   = ((c_pos >= 0.4) & (c_pos <= 0.6)).astype(int)  # 중간 매물대

    # ═══════════════════════════════════════════════════
    # 누락 6종 추가
    # Balance of Power / Chaikin Volatility /
    # Ease of Movement / Force Index /
    # Momentum(단순) / Price Volume Trend
    # ═══════════════════════════════════════════════════

    # ── Momentum (단순, Simple Momentum) ──────────────
    # 가장 기본적인 모멘텀: 현재가 - N일 전 가격
    for p in [10, 20]:
        mom = c - c.shift(p)
        df[f"simple_mom_{p}"] = mom / (c + 1e-9)   # 가격 정규화

    # ── Force Index (Elder의 Force Index) ─────────────
    # (종가변화 × 거래량): 추세의 힘 측정
    force = c.diff(1) * v
    df["force_index_2"]  = force.ewm(span=2,  adjust=False).mean() / (c * v.rolling(20).mean() + 1e-9)
    df["force_index_13"] = force.ewm(span=13, adjust=False).mean() / (c * v.rolling(20).mean() + 1e-9)
    df["force_bull"]     = (df["force_index_13"] > 0).astype(int)

    # ── Balance of Power (BOP) ─────────────────────────
    # (종가 - 시가) / (고가 - 저가): 매수/매도 세력 균형
    bop = (c - o) / (h - l + 1e-9)
    df["bop"]        = bop                             # -1~+1
    df["bop_smooth"] = bop.ewm(span=14, adjust=False).mean()
    df["bop_bull"]   = (df["bop_smooth"] > 0).astype(int)

    # ── Ease of Movement (EOM) ────────────────────────
    # 가격 이동이 거래량에 비해 얼마나 쉽게 일어났나
    midpoint_move = (h + l) / 2 - (h.shift(1) + l.shift(1)) / 2
    box_ratio     = v / (1e6 * (h - l + 1e-9))        # 거래량 / 범위
    eom = midpoint_move / (box_ratio + 1e-9)
    df["eom_14"]    = eom.rolling(14).mean() / (c + 1e-9)   # 정규화
    df["eom_bull"]  = (df["eom_14"] > 0).astype(int)

    # ── Price Volume Trend (PVT) ──────────────────────
    # OBV의 개선판: 거래량에 수익률 가중
    pvt_ret = c.pct_change()
    pvt = (pvt_ret * v).cumsum()
    pvt_ema = pvt.ewm(span=21, adjust=False).mean()
    pvt_scale = pvt.abs().rolling(200, min_periods=20).max() + 1e-9
    df["pvt"]        = pvt / pvt_scale                  # 정규화
    df["pvt_signal"] = (pvt > pvt_ema).astype(int)      # PVT > EMA → 강세

    # ── Chaikin Volatility ────────────────────────────
    # 고가-저가 범위의 EMA 변화율: 변동성 팽창/수축
    hl_range = h - l
    ema_hl_10 = hl_range.ewm(span=10, adjust=False).mean()
    df["chaikin_vol"]       = (ema_hl_10 - ema_hl_10.shift(10)) / (ema_hl_10.shift(10) + 1e-9)
    df["chaikin_vol_surge"] = (df["chaikin_vol"] > df["chaikin_vol"].rolling(50, min_periods=10).quantile(0.8)).astype(int)

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
