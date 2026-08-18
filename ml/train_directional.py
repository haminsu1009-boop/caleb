"""
ml/train_directional.py
BTC 5분봉 LONG/SHORT 방향성 앙상블 — 학습 + 워크포워드 백테스트

핵심 설계:
  - 타겟: 12봉(60분) 안에 TP(+0.5%) 먼저 도달하면 LONG/SHORT = 1
  - 모델: DirectionalEnsemble  XGB(0.45) + LGBM(0.40) + TemporalXGB(0.15)
  - 검증: 워크포워드 9폴드 (2022-01 ~ 2026-07)
  - 수수료: 테이커 0.05% × 2 = 0.1%, 슬리피지 0.05%

사용법:
    python ml/train_directional.py             # BTC 5m 전체
    python ml/train_directional.py --interval 1h
    python ml/train_directional.py --fast      # TemporalXGB 스킵 (빠른 실행)
    python ml/train_directional.py --from 2022 # 2022년부터 데이터 사용
"""

import os, sys, glob, argparse, warnings, pickle
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ml.models import DirectionalEnsemble

# ─────────────────────────────────────────────────────
# 하이퍼파라미터
# ─────────────────────────────────────────────────────
SYMBOL       = "BTCUSDT"
INTERVAL     = "5m"           # --interval 으로 변경 가능
FEE_RATE     = 0.0005         # 편도 0.05% (taker)
SLIPPAGE     = 0.0005         # 슬리피지
TP_PCT       = 0.005          # Take-Profit 0.5%
SL_PCT       = 0.003          # Stop-Loss  0.3%
HORIZON      = 12             # 타겟 계산 봉 수 (5m × 12 = 60분)
SIGNAL_THR   = 0.58           # 신호 발생 확률 임계값
TRAIN_START  = "2020-01-01"   # 학습 시작
WF_START     = "2022-01-01"   # 워크포워드 시작
WF_FOLDS     = 9              # 폴드 수
WF_MONTHS    = 3              # 폴드당 검증 기간 (개월)
MIN_TRAIN_ROWS = 3_000        # 최소 학습 행 수 (1h=3k, 5m=50k 등 봉 수 기준)

DATA_DIR   = os.path.join(ROOT, "data")
IND_DIR    = os.path.join(DATA_DIR, "indicators")
MODEL_DIR  = os.path.join(ROOT, "ml", "saved_models")
CHART_DIR  = os.path.join(ROOT, "charts")
os.makedirs(MODEL_DIR, exist_ok=True)
os.makedirs(CHART_DIR, exist_ok=True)


# ══════════════════════════════════════════════════════
# 1. 데이터 로딩
# ══════════════════════════════════════════════════════

def load_ohlcv(symbol: str = SYMBOL, interval: str = INTERVAL,
               from_year: int = 2020) -> pd.DataFrame:
    """연도별 csv.gz 파일 전부 합산"""
    pattern = os.path.join(DATA_DIR, f"{symbol}_{interval}_*.csv.gz")
    files   = sorted(f for f in glob.glob(pattern)
                     if "_all" not in f
                     and int(os.path.basename(f).split("_")[-1].replace(".csv.gz","")) >= from_year)
    if not files:
        raise FileNotFoundError(f"파일 없음: {pattern} (from {from_year})")

    dfs = []
    for f in files:
        df = pd.read_csv(f, compression="gzip")
        # 타임스탬프 파싱 — 연도가 비정상(>2100)이면 ms 에포크로 재해석
        ts_raw = df["timestamp"].astype(str).iloc[0]
        try:
            ts_test = pd.to_datetime(ts_raw)
            if ts_test.year > 2100 or ts_test.year < 2010:
                raise ValueError("비정상 연도")
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        except Exception:
            # ms 에포크 시도
            try:
                df["timestamp"] = pd.to_datetime(
                    df["timestamp"].astype(float).astype("int64"), unit="ms", errors="coerce")
            except Exception:
                df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        # 여전히 비정상 연도 → 행 제거
        df = df[df["timestamp"].dt.year.between(2010, 2030)]
        if df.empty:
            continue
        dfs.append(df)

    df = (pd.concat(dfs)
            .drop_duplicates("timestamp")
            .sort_values("timestamp")
            .reset_index(drop=True))

    # 컬럼 표준화
    df = df.rename(columns={"timestamp":"datetime"})
    df["open"]  = df["open"].astype(float)
    df["high"]  = df["high"].astype(float)
    df["low"]   = df["low"].astype(float)
    df["close"] = df["close"].astype(float)
    df["volume"]= df["volume"].astype(float)
    print(f"  OHLCV: {len(df):,}행  {df['datetime'].iloc[0]} ~ {df['datetime'].iloc[-1]}")
    return df


def load_indicators() -> dict:
    """외부 지표 로딩 (일봉/주봉 → forward-fill)"""
    ind = {}

    # 공포탐욕지수 (일봉)
    fg_path = os.path.join(IND_DIR, "fear_greed_index.csv")
    if os.path.exists(fg_path):
        fg = pd.read_csv(fg_path)
        fg["date"] = pd.to_datetime(fg["date"])
        fg = fg[["date","fear_greed"]].dropna()
        fg["fear_greed"] = fg["fear_greed"].astype(float)
        ind["fear_greed"] = fg
        print(f"  공포탐욕: {len(fg)}일")

    # 거시경제 (일봉)
    mac_path = os.path.join(IND_DIR, "macro_yahoo_finance.csv")
    if os.path.exists(mac_path):
        mac = pd.read_csv(mac_path)
        mac["date"] = pd.to_datetime(mac["date"])
        # sp500, nasdaq, gold, dxy, vix, us10y
        num_cols = [c for c in mac.columns if c != "date"]
        mac[num_cols] = mac[num_cols].astype(float)
        ind["macro"] = mac
        print(f"  거시경제: {len(mac)}일  컬럼={num_cols}")

    return ind


def merge_indicators(df: pd.DataFrame, ind: dict) -> pd.DataFrame:
    """5분봉 df에 외부 지표 병합 (날짜 기준 forward-fill)"""
    df = df.copy()
    df["_date"] = df["datetime"].dt.normalize()  # 날짜 키

    if "fear_greed" in ind:
        fg = ind["fear_greed"].rename(columns={"date":"_date"})
        df = df.merge(fg, on="_date", how="left")
        df["fear_greed"] = df["fear_greed"].ffill()

    if "macro" in ind:
        mac = ind["macro"].rename(columns={"date":"_date"})
        df = df.merge(mac, on="_date", how="left")
        for c in [col for col in mac.columns if col != "_date"]:
            if c in df.columns:
                df[c] = df[c].ffill()

    df = df.drop(columns=["_date"], errors="ignore")
    return df


# ══════════════════════════════════════════════════════
# 2. 피처 엔지니어링
# ══════════════════════════════════════════════════════

def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c  = df["close"]
    h  = df["high"]
    l  = df["low"]
    v  = df["volume"]
    o  = df["open"]

    # ══════════════════════════════════════════════
    # A. 수익률 & 변동성
    # ══════════════════════════════════════════════
    for n in [1, 2, 3, 5, 6, 12, 24, 48, 96, 288]:
        df[f"ret_{n}"] = c.pct_change(n)
    for w in [6, 12, 24, 48, 96, 288]:
        df[f"vol_{w}"] = c.pct_change().rolling(w).std()
    # 실현변동성 (고저 기반)
    df["hl_vol"]   = (np.log(h / l)).rolling(14).mean()
    # 왜도 / 첨도
    ret1 = c.pct_change()
    df["skew_24"]  = ret1.rolling(24).skew()
    df["kurt_24"]  = ret1.rolling(24).kurt()
    df["skew_96"]  = ret1.rolling(96).skew()

    # ══════════════════════════════════════════════
    # B. RSI (다중 기간 + 다이버전스 근사)
    # ══════════════════════════════════════════════
    rsi_dict = {}
    for p in [6, 9, 14, 21, 24]:
        delta = c.diff()
        g  = delta.clip(lower=0).ewm(span=p, adjust=False).mean()
        ls = (-delta.clip(upper=0)).ewm(span=p, adjust=False).mean()
        rsi = 100 - 100 / (1 + g / (ls + 1e-9))
        df[f"rsi_{p}"]       = rsi / 100
        df[f"rsi_{p}_slope"] = rsi.diff(3)
        rsi_dict[p] = rsi
    # RSI 다이버전스 근사: 가격은 상승인데 RSI는 하락
    df["rsi_div_bull"] = ((c > c.shift(14)) & (rsi_dict[14] < rsi_dict[14].shift(14))).astype(int)
    df["rsi_div_bear"] = ((c < c.shift(14)) & (rsi_dict[14] > rsi_dict[14].shift(14))).astype(int)

    # ══════════════════════════════════════════════
    # C. MACD
    # ══════════════════════════════════════════════
    for fast, slow, sig_p in [(12, 26, 9), (5, 13, 5)]:
        ef = c.ewm(span=fast, adjust=False).mean()
        es = c.ewm(span=slow, adjust=False).mean()
        macd = ef - es
        sig  = macd.ewm(span=sig_p, adjust=False).mean()
        tag  = f"macd_{fast}_{slow}"
        df[f"{tag}"]      = macd / c
        df[f"{tag}_sig"]  = sig  / c
        df[f"{tag}_hist"] = (macd - sig) / c
        df[f"{tag}_cross_up"]  = ((macd > sig) & (macd.shift(1) <= sig.shift(1))).astype(int)
        df[f"{tag}_cross_dn"]  = ((macd < sig) & (macd.shift(1) >= sig.shift(1))).astype(int)

    # ══════════════════════════════════════════════
    # D. 볼린저 밴드
    # ══════════════════════════════════════════════
    for w in [14, 20, 48]:
        mid = c.rolling(w).mean()
        std = c.rolling(w).std()
        df[f"bb_pos_{w}"]     = (c - mid) / (2 * std + 1e-9)
        df[f"bb_width_{w}"]   = (4 * std) / (mid + 1e-9)
        df[f"bb_squeeze_{w}"] = (std < std.rolling(w * 2).mean() * 0.75).astype(int)
        df[f"bb_upper_{w}"]   = (c >= mid + 2 * std).astype(int)  # 상단 터치
        df[f"bb_lower_{w}"]   = (c <= mid - 2 * std).astype(int)  # 하단 터치

    # ══════════════════════════════════════════════
    # E. 켈트너 채널 (Keltner Channel)
    # ══════════════════════════════════════════════
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr14 = tr.ewm(span=14, adjust=False).mean()
    for mult in [1.5, 2.0]:
        ema20 = c.ewm(span=20, adjust=False).mean()
        kc_upper = ema20 + mult * atr14
        kc_lower = ema20 - mult * atr14
        m = str(mult).replace(".", "")
        df[f"kc_pos_{m}"] = (c - ema20) / (mult * atr14 + 1e-9)
        df[f"kc_above_{m}"] = (c > kc_upper).astype(int)
        df[f"kc_below_{m}"] = (c < kc_lower).astype(int)
    # 스퀴즈 (BB < KC)
    bb20_std = c.rolling(20).std()
    bb20_mid = c.rolling(20).mean()
    df["squeeze_kc"] = (4 * bb20_std < 2.0 * atr14).astype(int)

    # ══════════════════════════════════════════════
    # F. 스토캐스틱
    # ══════════════════════════════════════════════
    for p in [9, 14, 24]:
        lo = l.rolling(p).min()
        hi = h.rolling(p).max()
        k  = (c - lo) / (hi - lo + 1e-9)
        d  = k.rolling(3).mean()
        df[f"stoch_k_{p}"]  = k
        df[f"stoch_d_{p}"]  = d
        df[f"stoch_kd_{p}"] = k - d
        df[f"stoch_os_{p}"] = (k < 0.2).astype(int)
        df[f"stoch_ob_{p}"] = (k > 0.8).astype(int)

    # ══════════════════════════════════════════════
    # G. ADX / DI
    # ══════════════════════════════════════════════
    pdm = h.diff().clip(lower=0)
    mdm = (-l.diff()).clip(lower=0)
    pdi   = 100 * pdm.ewm(span=14, adjust=False).mean() / (atr14 + 1e-9)
    mdi   = 100 * mdm.ewm(span=14, adjust=False).mean() / (atr14 + 1e-9)
    dx    = (pdi - mdi).abs() / (pdi + mdi + 1e-9) * 100
    adx   = dx.ewm(span=14, adjust=False).mean()
    df["adx"]          = adx / 100
    df["di_diff"]      = (pdi - mdi) / 100
    df["adx_trending"] = (adx > 25).astype(int)
    df["adx_slope"]    = adx.diff(3) / 100

    # ══════════════════════════════════════════════
    # H. ATR + Normalized
    # ══════════════════════════════════════════════
    df["atr"]     = atr14 / c
    atr7  = tr.ewm(span=7,  adjust=False).mean()
    atr28 = tr.ewm(span=28, adjust=False).mean()
    df["atr7"]    = atr7  / c
    df["atr28"]   = atr28 / c
    df["atr_ratio"] = atr7 / (atr28 + 1e-9)  # 단기/장기 변동성 비율

    # ══════════════════════════════════════════════
    # I. CCI (Commodity Channel Index)
    # ══════════════════════════════════════════════
    tp_cci = (h + l + c) / 3
    for p in [14, 20]:
        mean_tp = tp_cci.rolling(p).mean()
        mad     = tp_cci.rolling(p).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
        df[f"cci_{p}"] = (tp_cci - mean_tp) / (0.015 * mad + 1e-9) / 200

    # ══════════════════════════════════════════════
    # J. Williams %R
    # ══════════════════════════════════════════════
    for p in [14, 28]:
        hi_p = h.rolling(p).max()
        lo_p = l.rolling(p).min()
        df[f"willr_{p}"] = -100 * (hi_p - c) / (hi_p - lo_p + 1e-9) / 100

    # ══════════════════════════════════════════════
    # K. 이동평균 위치 (SMA + EMA)
    # ══════════════════════════════════════════════
    for p in [12, 24, 48, 96, 200, 288, 576]:
        sma = c.rolling(p).mean()
        df[f"vs_sma{p}"] = (c / sma) - 1
    ema_map = {}
    for sp in [9, 21, 50, 55, 100, 200]:
        ema_map[sp] = c.ewm(span=sp, adjust=False).mean()
    df["ema9_vs_21"]   = (ema_map[9]  / ema_map[21])  - 1
    df["ema21_vs_55"]  = (ema_map[21] / ema_map[55])  - 1
    df["ema50_vs_200"] = (ema_map[50] / ema_map[200]) - 1
    df["ema9_slope"]   = ema_map[9].pct_change(3)
    df["ema21_slope"]  = ema_map[21].pct_change(5)
    # 골든크로스 / 데드크로스
    df["golden_cross"] = ((ema_map[50] > ema_map[200]) & (ema_map[50].shift(1) <= ema_map[200].shift(1))).astype(int)
    df["dead_cross"]   = ((ema_map[50] < ema_map[200]) & (ema_map[50].shift(1) >= ema_map[200].shift(1))).astype(int)

    # ══════════════════════════════════════════════
    # L. Parabolic SAR (근사)
    # ══════════════════════════════════════════════
    # 단순 근사: 최근 고점/저점 기반 추세 방향
    high_5  = h.rolling(5).max()
    low_5   = l.rolling(5).min()
    df["sar_bull"] = (c > high_5.shift(1)).astype(int)  # SAR 상승 신호
    df["sar_bear"] = (c < low_5.shift(1)).astype(int)   # SAR 하락 신호

    # ══════════════════════════════════════════════
    # M. Donchian Channel
    # ══════════════════════════════════════════════
    for p in [20, 55]:
        dc_high = h.rolling(p).max()
        dc_low  = l.rolling(p).min()
        dc_mid  = (dc_high + dc_low) / 2
        df[f"dc_pos_{p}"]      = (c - dc_mid) / (dc_high - dc_low + 1e-9)
        df[f"dc_breakout_up_{p}"]  = (c >= dc_high.shift(1)).astype(int)
        df[f"dc_breakout_dn_{p}"]  = (c <= dc_low.shift(1)).astype(int)

    # ══════════════════════════════════════════════
    # N. 일목균형표 (Ichimoku Cloud)
    # ══════════════════════════════════════════════
    tenkan  = (h.rolling(9).max()  + l.rolling(9).min())  / 2
    kijun   = (h.rolling(26).max() + l.rolling(26).min()) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(26)
    senkou_b = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)
    df["ichi_tk"]       = (tenkan - kijun) / c              # 전환-기준 차이
    df["ichi_above_cloud"] = (c > senkou_a.clip(lower=senkou_b)).astype(int)
    df["ichi_below_cloud"] = (c < senkou_a.clip(upper=senkou_b)).astype(int)
    df["ichi_cloud_bull"]  = (senkou_a > senkou_b).astype(int)  # 구름 색상
    df["ichi_tk_cross_up"] = ((tenkan > kijun) & (tenkan.shift(1) <= kijun.shift(1))).astype(int)
    df["ichi_tk_cross_dn"] = ((tenkan < kijun) & (tenkan.shift(1) >= kijun.shift(1))).astype(int)

    # ══════════════════════════════════════════════
    # O. Aroon 오실레이터
    # ══════════════════════════════════════════════
    for p in [14, 25]:
        aroon_up = h.rolling(p + 1).apply(lambda x: (np.argmax(x) / p) * 100, raw=True)
        aroon_dn = l.rolling(p + 1).apply(lambda x: (np.argmin(x) / p) * 100, raw=True)
        df[f"aroon_{p}"] = (aroon_up - aroon_dn) / 100

    # ══════════════════════════════════════════════
    # P. MFI (Money Flow Index)
    # ══════════════════════════════════════════════
    tp2 = (h + l + c) / 3
    mf  = tp2 * v
    for p in [14]:
        pos_mf = mf.where(tp2 > tp2.shift(1), 0).rolling(p).sum()
        neg_mf = mf.where(tp2 < tp2.shift(1), 0).rolling(p).sum()
        df[f"mfi_{p}"] = 100 - 100 / (1 + pos_mf / (neg_mf + 1e-9))
        df[f"mfi_{p}"] /= 100
        df[f"mfi_os_{p}"] = (df[f"mfi_{p}"] < 0.2).astype(int)
        df[f"mfi_ob_{p}"] = (df[f"mfi_{p}"] > 0.8).astype(int)

    # ══════════════════════════════════════════════
    # Q. CMF (Chaikin Money Flow)
    # ══════════════════════════════════════════════
    clv = ((c - l) - (h - c)) / (h - l + 1e-9)
    for p in [14, 21]:
        df[f"cmf_{p}"] = (clv * v).rolling(p).sum() / (v.rolling(p).sum() + 1e-9)

    # ══════════════════════════════════════════════
    # R. ROC (Rate of Change)
    # ══════════════════════════════════════════════
    for p in [9, 14, 21]:
        df[f"roc_{p}"] = c.pct_change(p)

    # ══════════════════════════════════════════════
    # S. TRIX
    # ══════════════════════════════════════════════
    ema1 = c.ewm(span=15, adjust=False).mean()
    ema2 = ema1.ewm(span=15, adjust=False).mean()
    ema3 = ema2.ewm(span=15, adjust=False).mean()
    df["trix"] = ema3.pct_change()

    # ══════════════════════════════════════════════
    # T. 거래량 지표
    # ══════════════════════════════════════════════
    for w in [12, 24, 48, 96]:
        df[f"vol_ratio_{w}"] = v / (v.rolling(w).mean() + 1e-9)
    df["vol_slope"] = v.pct_change(5)
    df["vol_burst"] = (v / (v.rolling(48).mean() + 1e-9) > 2.5).astype(int)
    # OBV
    obv = (np.sign(c.diff()) * v).fillna(0).cumsum()
    df["obv_slope"]  = obv.pct_change(12)
    df["obv_slope2"] = obv.pct_change(24)
    # 거래량 가중 가격 (VWAP)
    for vw in [48, 96, 288]:
        vwap = (c * v).rolling(vw).sum() / (v.rolling(vw).sum() + 1e-9)
        df[f"vwap_pos_{vw}"] = (c / (vwap + 1e-9)) - 1
    # Force Index
    df["force_idx"] = c.diff() * v / (v.rolling(14).mean() + 1e-9)

    # ══════════════════════════════════════════════
    # U. 캔들 패턴 (완전판)
    # ══════════════════════════════════════════════
    body   = (c - o)
    body_a = body.abs()
    rng    = (h - l).replace(0, np.nan)
    up_shd = (h - c.where(c > o, o))
    dn_shd = (c.where(c < o, o) - l)

    df["body_ratio"]   = body_a / (rng + 1e-9)
    df["upper_shadow"] = up_shd / (rng + 1e-9)
    df["lower_shadow"] = dn_shd / (rng + 1e-9)
    df["is_bullish"]   = (c > o).astype(int)
    df["gap"]          = (o - c.shift()) / (c.shift() + 1e-9)
    df["gap_up"]       = (o > h.shift(1)).astype(int)
    df["gap_down"]     = (o < l.shift(1)).astype(int)

    # 도지
    df["doji"]         = (body_a / (rng + 1e-9) < 0.1).astype(int)
    df["dragonfly"]    = ((dn_shd > body_a * 2) & (up_shd < body_a * 0.5)).astype(int)
    df["gravestone"]   = ((up_shd > body_a * 2) & (dn_shd < body_a * 0.5)).astype(int)
    # 망치형 / 슈팅스타
    df["hammer"]       = ((dn_shd >= body_a * 2) & (up_shd <= body_a * 0.5) & (c > o)).astype(int)
    df["inv_hammer"]   = ((up_shd >= body_a * 2) & (dn_shd <= body_a * 0.5) & (c > o)).astype(int)
    df["shooting_star"]= ((up_shd >= body_a * 2) & (dn_shd <= body_a * 0.5) & (c < o)).astype(int)
    df["hanging_man"]  = ((dn_shd >= body_a * 2) & (up_shd <= body_a * 0.5) & (c < o)).astype(int)
    # 마루보주
    df["marubozu_bull"]= ((up_shd < rng * 0.05) & (dn_shd < rng * 0.05) & (c > o)).astype(int)
    df["marubozu_bear"]= ((up_shd < rng * 0.05) & (dn_shd < rng * 0.05) & (c < o)).astype(int)
    # 장악형 (Engulfing)
    df["engulf_bull"]  = ((c > o) & (c.shift(1) < o.shift(1)) &
                          (o < c.shift(1)) & (c > o.shift(1))).astype(int)
    df["engulf_bear"]  = ((c < o) & (c.shift(1) > o.shift(1)) &
                          (o > c.shift(1)) & (c < o.shift(1))).astype(int)
    # 관통형 / 먹구름
    df["piercing"]     = ((c > o) & (c.shift(1) < o.shift(1)) &
                          (o < l.shift(1)) & (c > (o.shift(1) + c.shift(1)) / 2)).astype(int)
    df["dark_cloud"]   = ((c < o) & (c.shift(1) > o.shift(1)) &
                          (o > h.shift(1)) & (c < (o.shift(1) + c.shift(1)) / 2)).astype(int)
    # 샛별형 / 저녁별형
    mid_body_1 = (o.shift(2) + c.shift(2)) / 2
    df["morning_star"] = ((c.shift(2) < o.shift(2)) &
                          (body_a.shift(1) < rng.shift(1) * 0.3) &
                          (c > o) & (c > mid_body_1)).astype(int)
    df["evening_star"] = ((c.shift(2) > o.shift(2)) &
                          (body_a.shift(1) < rng.shift(1) * 0.3) &
                          (c < o) & (c < mid_body_1)).astype(int)
    # 세 병사 / 세 까마귀
    df["three_soldiers"]= ((c > o) & (c.shift(1) > o.shift(1)) & (c.shift(2) > o.shift(2)) &
                            (o > o.shift(1)) & (o.shift(1) > o.shift(2))).astype(int)
    df["three_crows"]   = ((c < o) & (c.shift(1) < o.shift(1)) & (c.shift(2) < o.shift(2)) &
                            (o < o.shift(1)) & (o.shift(1) < o.shift(2))).astype(int)
    # 핀바 (Pin Bar) — 꼬리가 몸통의 3배 이상
    df["pinbar_bull"]  = ((dn_shd >= body_a * 3) & (up_shd <= dn_shd * 0.3)).astype(int)
    df["pinbar_bear"]  = ((up_shd >= body_a * 3) & (dn_shd <= up_shd * 0.3)).astype(int)
    # 인사이드바 (IB)
    df["inside_bar"]   = ((h < h.shift(1)) & (l > l.shift(1))).astype(int)
    # 아웃사이드바 (OB)
    df["outside_bar"]  = ((h > h.shift(1)) & (l < l.shift(1))).astype(int)

    # ══════════════════════════════════════════════
    # V. 차트 구조 (지지/저항 / 고점저점 패턴)
    # ══════════════════════════════════════════════
    # 프랙탈 고점/저점
    df["fractal_high"] = ((h > h.shift(1)) & (h > h.shift(2)) &
                          (h > h.shift(-1)) & (h > h.shift(-2))).astype(int)
    df["fractal_low"]  = ((l < l.shift(1)) & (l < l.shift(2)) &
                          (l < l.shift(-1)) & (l < l.shift(-2))).astype(int)
    # HH/HL/LH/LL 패턴 (추세 구조)
    recent_high = h.rolling(20).max()
    recent_low  = l.rolling(20).min()
    df["near_high"]    = (c >= recent_high * 0.99).astype(int)   # 고점 근접
    df["near_low"]     = (c <= recent_low  * 1.01).astype(int)   # 저점 근접
    df["hh"]           = (h > h.rolling(20).max().shift(1)).astype(int)  # 더 높은 고점
    df["ll"]           = (l < l.rolling(20).min().shift(1)).astype(int)  # 더 낮은 저점
    # 피봇 레벨 대비 위치
    pivot = (h.shift(1) + l.shift(1) + c.shift(1)) / 3
    r1    = 2 * pivot - l.shift(1)
    s1    = 2 * pivot - h.shift(1)
    df["vs_pivot"]    = (c - pivot) / (atr14 + 1e-9)
    df["above_r1"]    = (c > r1).astype(int)
    df["below_s1"]    = (c < s1).astype(int)
    # 지지/저항 근접
    df["vs_high_20"]  = (c / (h.rolling(20).max() + 1e-9)) - 1
    df["vs_low_20"]   = (c / (l.rolling(20).min() + 1e-9)) - 1
    df["vs_high_55"]  = (c / (h.rolling(55).max() + 1e-9)) - 1
    df["vs_low_55"]   = (c / (l.rolling(55).min() + 1e-9)) - 1

    # ══════════════════════════════════════════════
    # W. 외부 지표 파생 (공포탐욕 + 거시경제)
    # ══════════════════════════════════════════════
    if "fear_greed" in df.columns:
        fg = df["fear_greed"]
        df["fg_norm"]          = fg / 100
        df["fg_extreme_fear"]  = (fg < 20).astype(int)
        df["fg_extreme_greed"] = (fg > 80).astype(int)
        df["fg_fear"]          = (fg < 40).astype(int)
        df["fg_greed"]         = (fg > 60).astype(int)
        df["fg_change_7d"]     = (fg - fg.shift(7)).fillna(0)
        df["fg_change_30d"]    = (fg - fg.shift(30)).fillna(0)
        df["fg_ma14"]          = (fg / (fg.rolling(14).mean() + 1e-9)) - 1

    for col in ["sp500", "nasdaq", "gold", "dxy", "vix", "us10y"]:
        if col in df.columns:
            s = df[col]
            df[f"{col}_ret1d"]   = s.pct_change(1)
            df[f"{col}_ret5d"]   = s.pct_change(5)
            df[f"{col}_ret20d"]  = s.pct_change(20)
            df[f"{col}_above_ma"]= (s > s.rolling(50).mean()).astype(int)
            df[f"{col}_above_ma200"] = (s > s.rolling(200).mean()).astype(int)
            if col == "vix":
                df["vix_spike"]  = (s > s.shift(1) * 1.1).astype(int)
                df["vix_high"]   = (s > 30).astype(int)
                df["vix_low"]    = (s < 15).astype(int)
            if col == "dxy":
                df["dxy_rising"] = (s > s.shift(5)).astype(int)
                df["dxy_vs_ma"]  = (s / (s.rolling(20).mean() + 1e-9)) - 1
            if col == "gold":
                df["gold_vs_ma"] = (s / (s.rolling(20).mean() + 1e-9)) - 1
            if col == "us10y":
                df["yield_rising"] = (s > s.shift(5)).astype(int)

    # ══════════════════════════════════════════════
    # X. 시간 주기성 (확장)
    # ══════════════════════════════════════════════
    dt = df["datetime"]
    df["hour"]       = dt.dt.hour / 23
    df["dow"]        = dt.dt.dayofweek / 6
    df["month"]      = dt.dt.month / 12
    df["hour_sin"]   = np.sin(2 * np.pi * dt.dt.hour / 24)
    df["hour_cos"]   = np.cos(2 * np.pi * dt.dt.hour / 24)
    df["dow_sin"]    = np.sin(2 * np.pi * dt.dt.dayofweek / 7)
    df["dow_cos"]    = np.cos(2 * np.pi * dt.dt.dayofweek / 7)
    df["month_sin"]  = np.sin(2 * np.pi * dt.dt.month / 12)
    df["month_cos"]  = np.cos(2 * np.pi * dt.dt.month / 12)
    # 아시아/유럽/미국 세션
    hr = dt.dt.hour
    df["session_asia"]   = ((hr >= 0)  & (hr < 8)).astype(int)
    df["session_europe"] = ((hr >= 8)  & (hr < 16)).astype(int)
    df["session_us"]     = ((hr >= 14) & (hr < 22)).astype(int)
    df["session_overlap"]= ((hr >= 14) & (hr < 16)).astype(int)  # 유럽+미국 겹침
    # 주말 여부
    df["is_weekend"]     = (dt.dt.dayofweek >= 5).astype(int)

    return df


def make_targets(df: pd.DataFrame,
                 horizon: int = HORIZON,
                 tp: float = TP_PCT,
                 sl: float = SL_PCT) -> pd.DataFrame:
    """
    LONG:  향후 horizon봉 내에서 TP(+tp%) 먼저 도달하면 1
    SHORT: 향후 horizon봉 내에서 SL(-sl%) 먼저 도달하면 1
    (즉 숏 포지션이 이익인 경우)

    look-ahead bias 없음 — 모두 미래 봉 기준
    """
    df = df.copy()
    close = df["close"].values
    high  = df["high"].values
    low   = df["low"].values
    n     = len(df)

    long_target  = np.zeros(n, dtype=np.int8)
    short_target = np.zeros(n, dtype=np.int8)

    for i in range(n - horizon):
        entry = close[i]
        tp_price_l = entry * (1 + tp)
        sl_price_l = entry * (1 - sl)
        tp_price_s = entry * (1 - tp)
        sl_price_s = entry * (1 + sl)

        long_win = short_win = False
        for j in range(i + 1, min(i + horizon + 1, n)):
            h_j = high[j]
            l_j = low[j]
            # LONG: high가 TP에 닿으면 이익
            if h_j >= tp_price_l:
                long_win = True; break
            # LONG: low가 SL에 닿으면 손실 → 종료
            if l_j <= sl_price_l:
                break

        for j in range(i + 1, min(i + horizon + 1, n)):
            h_j = high[j]
            l_j = low[j]
            # SHORT: low가 TP에 닿으면 이익
            if l_j <= tp_price_s:
                short_win = True; break
            # SHORT: high가 SL에 닿으면 손실 → 종료
            if h_j >= sl_price_s:
                break

        long_target[i]  = int(long_win)
        short_target[i] = int(short_win)

    df["y_long"]  = long_target
    df["y_short"] = short_target
    return df


def get_feature_cols(df: pd.DataFrame) -> list:
    exclude = {"datetime","open","high","low","close","volume",
               "quote_volume","y_long","y_short",
               "fear_greed","sentiment","sp500","nasdaq",
               "gold","dxy","vix","us10y"}
    cols = [c for c in df.columns if c not in exclude and df[c].dtype in [np.float64, np.int64, np.int8, np.float32]]
    # NaN 비율 50% 이상 제거
    nan_ratio = df[cols].isna().mean()
    return [c for c in cols if nan_ratio[c] < 0.5]


# ══════════════════════════════════════════════════════
# 3. 워크포워드 백테스트
# ══════════════════════════════════════════════════════

def simulate_trades(df_val: pd.DataFrame,
                    long_sig: np.ndarray,
                    short_sig: np.ndarray,
                    long_prob: np.ndarray,
                    short_prob: np.ndarray,
                    horizon: int = HORIZON,
                    tp: float = TP_PCT,
                    sl: float = SL_PCT,
                    fee: float = FEE_RATE,
                    slip: float = SLIPPAGE) -> pd.DataFrame:
    """신호별 거래 시뮬레이션 → 거래 기록 반환"""
    trades = []
    n = len(df_val)
    closes = df_val["close"].values
    highs  = df_val["high"].values
    lows   = df_val["low"].values
    times  = df_val["datetime"].values

    for i in range(n - horizon):
        direction = None
        prob      = 0.0
        if long_sig[i] and not short_sig[i]:
            direction, prob = "LONG",  float(long_prob[i])
        elif short_sig[i] and not long_sig[i]:
            direction, prob = "SHORT", float(short_prob[i])
        elif long_sig[i] and short_sig[i]:
            # 둘 다 신호 → 높은 확률 우선
            if long_prob[i] >= short_prob[i]:
                direction, prob = "LONG",  float(long_prob[i])
            else:
                direction, prob = "SHORT", float(short_prob[i])

        if direction is None:
            continue

        entry = closes[i] * (1 + slip if direction == "LONG" else 1 - slip)
        tp_price = entry * (1 + tp) if direction == "LONG" else entry * (1 - tp)
        sl_price = entry * (1 - sl) if direction == "LONG" else entry * (1 + sl)

        exit_price = None
        exit_type  = "timeout"
        for j in range(i + 1, min(i + horizon + 1, n)):
            h_j, l_j = highs[j], lows[j]
            if direction == "LONG":
                if h_j >= tp_price:
                    exit_price = tp_price; exit_type = "tp"; break
                if l_j <= sl_price:
                    exit_price = sl_price; exit_type = "sl"; break
            else:
                if l_j <= tp_price:
                    exit_price = tp_price; exit_type = "tp"; break
                if h_j >= sl_price:
                    exit_price = sl_price; exit_type = "sl"; break

        if exit_price is None:
            exit_price = closes[min(i + horizon, n - 1)] * (1 - slip if direction == "LONG" else 1 + slip)

        if direction == "LONG":
            pnl_pct = (exit_price / entry - 1) - 2 * fee
        else:
            pnl_pct = (entry / exit_price - 1) - 2 * fee

        trades.append({
            "entry_time": times[i],
            "direction":  direction,
            "entry":      round(entry, 2),
            "exit":       round(exit_price, 2),
            "exit_type":  exit_type,
            "pnl_pct":    round(pnl_pct, 6),
            "win":        int(pnl_pct > 0),
            "prob":       round(prob, 4),
        })

    return pd.DataFrame(trades)


def walk_forward(df: pd.DataFrame, feature_cols: list,
                 fast_mode: bool = False) -> tuple:
    """
    워크포워드 검증
    Returns: (fold_results_list, all_trades_df)
    """
    df["datetime"] = pd.to_datetime(df["datetime"])
    wf_start = pd.Timestamp(WF_START)

    fold_results = []
    all_trades   = []

    for fold in range(WF_FOLDS):
        val_start = wf_start + pd.DateOffset(months=fold * WF_MONTHS)
        val_end   = val_start + pd.DateOffset(months=WF_MONTHS)

        if val_end > df["datetime"].max():
            break

        # 학습: WF_START 이전까지 전부 + 이전 fold까지
        train_mask = (df["datetime"] >= TRAIN_START) & (df["datetime"] < val_start)
        val_mask   = (df["datetime"] >= val_start)   & (df["datetime"] < val_end)

        n_train = train_mask.sum()
        n_val   = val_mask.sum()

        if n_train < MIN_TRAIN_ROWS or n_val < 500:
            print(f"  Fold {fold+1}: 데이터 부족 (학습 {n_train}, 검증 {n_val}) → 스킵")
            continue

        print(f"\n  Fold {fold+1}/{WF_FOLDS}: 학습 {n_train:,} | 검증 {n_val:,} ({val_start.date()}~{val_end.date()})")

        X_tr  = df.loc[train_mask, feature_cols].fillna(0)
        yl_tr = df.loc[train_mask, "y_long"]
        ys_tr = df.loc[train_mask, "y_short"]
        X_va  = df.loc[val_mask,   feature_cols].fillna(0)
        yl_va = df.loc[val_mask,   "y_long"]
        ys_va = df.loc[val_mask,   "y_short"]

        long_rate  = float(yl_tr.mean())
        short_rate = float(ys_tr.mean())
        print(f"    LONG 비율: {long_rate*100:.1f}%  SHORT 비율: {short_rate*100:.1f}%")

        model = DirectionalEnsemble(fast_mode=fast_mode)
        try:
            model.fit(X_tr, yl_tr, ys_tr,
                      X_va, yl_va, ys_va,
                      feature_cols=feature_cols)
        except Exception as e:
            print(f"    ⚠️  학습 실패: {e}"); continue

        # 검증 확률 & 신호
        lp = model.predict_proba_long(X_va)
        sp = model.predict_proba_short(X_va)

        # 최적 임계값 탐색 (학습셋 기준)
        # 너무 높으면 검증셋에서 신호가 0건이 될 수 있어 SIGNAL_THR로 하한 설정
        thr = model.find_precision_threshold(
            X_tr, yl_tr, ys_tr,
            min_precision=0.54, min_signals=20
        )
        l_thr = min(thr["long"],  0.65)  # 상한 0.65 — 검증셋 신호 보장
        s_thr = min(thr["short"], 0.65)
        print(f"    임계값: LONG {l_thr:.2f}  SHORT {s_thr:.2f}")

        long_sig  = (lp >= l_thr).astype(int)
        short_sig = (sp >= s_thr).astype(int)

        # 거래 시뮬레이션
        df_val_fold = df.loc[val_mask].reset_index(drop=True)
        trades_fold = simulate_trades(
            df_val_fold, long_sig, short_sig, lp, sp)

        n_long  = int(long_sig.sum())
        n_short = int(short_sig.sum())
        n_trades= len(trades_fold)

        if n_trades > 0:
            wr    = float(trades_fold["win"].mean())
            avg_r = float(trades_fold["pnl_pct"].mean())
            total_r = float(trades_fold["pnl_pct"].sum())
            n_l_t = int((trades_fold["direction"] == "LONG").sum())
            n_s_t = int((trades_fold["direction"] == "SHORT").sum())
            wr_l  = float(trades_fold.loc[trades_fold["direction"]=="LONG",  "win"].mean()) if n_l_t else 0.0
            wr_s  = float(trades_fold.loc[trades_fold["direction"]=="SHORT", "win"].mean()) if n_s_t else 0.0
        else:
            wr = avg_r = total_r = wr_l = wr_s = 0.0
            n_l_t = n_s_t = 0

        fold_results.append({
            "fold":       fold + 1,
            "val_start":  str(val_start.date()),
            "val_end":    str(val_end.date()),
            "n_train":    n_train,
            "n_val":      n_val,
            "n_trades":   n_trades,
            "n_long":     n_l_t,
            "n_short":    n_s_t,
            "win_rate":   round(wr, 4),
            "win_long":   round(wr_l, 4),
            "win_short":  round(wr_s, 4),
            "avg_pnl":    round(avg_r * 100, 3),
            "total_pnl":  round(total_r * 100, 3),
            "l_thr":      l_thr,
            "s_thr":      s_thr,
        })

        if len(trades_fold):
            trades_fold["fold"] = fold + 1
            all_trades.append(trades_fold)

        print(f"    거래: {n_trades}건 (L:{n_l_t} S:{n_s_t})  "
              f"승률: {wr*100:.1f}%  평균 수익: {avg_r*100:.3f}%  합계: {total_r*100:.2f}%")

    all_trades_df = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    return fold_results, all_trades_df


# ══════════════════════════════════════════════════════
# 4. 최종 모델 학습
# ══════════════════════════════════════════════════════

def train_final(df: pd.DataFrame, feature_cols: list,
                sym: str = "BTCUSDT", ivl: str = "5m",
                fast_mode: bool = False) -> DirectionalEnsemble:
    """전체 데이터(85%)로 최종 모델 학습"""
    print("\n[최종 모델] 전체 데이터 학습...")
    split = int(len(df) * 0.85)
    X_tr  = df.iloc[:split][feature_cols].fillna(0)
    yl_tr = df.iloc[:split]["y_long"]
    ys_tr = df.iloc[:split]["y_short"]
    X_va  = df.iloc[split:][feature_cols].fillna(0)
    yl_va = df.iloc[split:]["y_long"]
    ys_va = df.iloc[split:]["y_short"]

    model = DirectionalEnsemble(fast_mode=fast_mode)
    model.fit(X_tr, yl_tr, ys_tr,
              X_va, yl_va, ys_va,
              feature_cols=feature_cols)

    path = os.path.join(MODEL_DIR, f"directional_{sym}_{ivl}.pkl")
    model.save(path)
    fcol_path = os.path.join(MODEL_DIR, f"feature_cols_{sym}_{ivl}.pkl")
    with open(fcol_path, "wb") as f:
        pickle.dump(feature_cols, f)
    print(f"  모델 저장 → {path}")
    return model


# ══════════════════════════════════════════════════════
# 5. 결과 시각화
# ══════════════════════════════════════════════════════

def plot_results(fold_results: list, all_trades: pd.DataFrame,
                 model: DirectionalEnsemble, feature_cols: list,
                 sym: str = "BTCUSDT", ivl: str = "5m"):
    if not fold_results:
        print("  ⚠️  결과 없음 — 차트 생략"); return

    wf = pd.DataFrame(fold_results)
    BG, FG = "#0d1117", "#e6edf3"
    GRID = "#30363d"
    GREEN, RED, BLUE, YEL = "#2ecc71", "#e74c3c", "#3498db", "#f1c40f"
    ORG = "#e67e22"

    fig = plt.figure(figsize=(20, 22), facecolor=BG)
    fig.suptitle(f"DirectionalEnsemble 워크포워드 백테스트 — {SYMBOL} {INTERVAL}",
                 fontsize=18, color=FG, fontweight="bold", y=0.99)
    gs = gridspec.GridSpec(4, 2, hspace=0.48, wspace=0.32,
                           top=0.96, bottom=0.04, left=0.07, right=0.97)

    def ax_style(ax, title):
        ax.set_facecolor(BG)
        ax.set_title(title, color=FG, fontsize=11, fontweight="bold", pad=8)
        ax.tick_params(colors=FG, labelsize=8)
        for sp in ax.spines.values(): sp.set_edgecolor(GRID)
        ax.grid(color=GRID, linewidth=0.4, linestyle="--", alpha=0.7)
        ax.xaxis.label.set_color(FG); ax.yaxis.label.set_color(FG)

    folds = wf["fold"].values
    x = np.arange(len(folds))
    labels = [f"F{f}\n{s[:7]}" for f,s in zip(wf["fold"], wf["val_start"])]

    # ── 1. 폴드별 승률 ──────────────────────────────
    ax1 = fig.add_subplot(gs[0, :])
    ax_style(ax1, "폴드별 승률: 전체 / LONG / SHORT")
    w = 0.26
    ax1.bar(x - w, wf["win_rate"] * 100,  w, color=[GREEN if v>=55 else RED for v in wf["win_rate"]],  label="전체", alpha=0.9)
    ax1.bar(x,     wf["win_long"] * 100,  w, color=BLUE,  label="LONG",  alpha=0.75)
    ax1.bar(x + w, wf["win_short"]* 100,  w, color=ORG,   label="SHORT", alpha=0.75)
    ax1.axhline(55, color=YEL, linewidth=1.2, linestyle=":", label="목표 55%")
    ax1.axhline(50, color=RED, linewidth=0.8, linestyle="--", alpha=0.5)
    ax1.set_xticks(x); ax1.set_xticklabels(labels)
    ax1.set_ylabel("승률 (%)"); ax1.set_ylim(0, 100)
    ax1.legend(facecolor=BG, edgecolor=GRID, labelcolor=FG, fontsize=9, loc="upper right")
    for xi, v in zip(x - w, wf["win_rate"]):
        ax1.text(xi, v*100+1.5, f"{v*100:.0f}%", ha="center", color=FG, fontsize=8, fontweight="bold")

    # ── 2. 폴드별 누적 PnL ──────────────────────────
    ax2 = fig.add_subplot(gs[1, 0])
    ax_style(ax2, "폴드별 누적 수익률 (%)")
    cols_pnl = [GREEN if v >= 0 else RED for v in wf["total_pnl"]]
    ax2.bar(x, wf["total_pnl"], color=cols_pnl, alpha=0.85)
    ax2.axhline(0, color=FG, linewidth=0.8)
    ax2.set_xticks(x); ax2.set_xticklabels(labels)
    ax2.set_ylabel("누적 수익률 (%)")
    for xi, v in zip(x, wf["total_pnl"]):
        ax2.text(xi, v + (0.5 if v >= 0 else -1.5), f"{v:.1f}%",
                 ha="center", color=FG, fontsize=8)

    # ── 3. 폴드별 거래 수 ───────────────────────────
    ax3 = fig.add_subplot(gs[1, 1])
    ax_style(ax3, "폴드별 거래 수 (LONG / SHORT)")
    ax3.bar(x - 0.2, wf["n_long"],  0.4, color=BLUE, label="LONG",  alpha=0.85)
    ax3.bar(x + 0.2, wf["n_short"], 0.4, color=ORG,  label="SHORT", alpha=0.85)
    ax3.set_xticks(x); ax3.set_xticklabels(labels)
    ax3.set_ylabel("거래 수")
    ax3.legend(facecolor=BG, edgecolor=GRID, labelcolor=FG, fontsize=9)

    # ── 4. 전체 거래 PnL 분포 ──────────────────────
    ax4 = fig.add_subplot(gs[2, 0])
    ax_style(ax4, "거래별 수익률 분포")
    if len(all_trades):
        pnl_vals = all_trades["pnl_pct"] * 100
        l_pnl = all_trades.loc[all_trades["direction"]=="LONG",  "pnl_pct"] * 100
        s_pnl = all_trades.loc[all_trades["direction"]=="SHORT", "pnl_pct"] * 100
        ax4.hist(l_pnl, bins=40, color=BLUE, alpha=0.6, label="LONG",  density=True)
        ax4.hist(s_pnl, bins=40, color=ORG,  alpha=0.6, label="SHORT", density=True)
        ax4.axvline(0, color=FG, linewidth=1.0)
        ax4.axvline(float(pnl_vals.mean()), color=YEL, linewidth=1.5,
                    linestyle="--", label=f"평균 {pnl_vals.mean():.3f}%")
        ax4.legend(facecolor=BG, edgecolor=GRID, labelcolor=FG, fontsize=9)
        ax4.set_xlabel("수익률 (%)")

    # ── 5. 누적 수익률 곡선 ─────────────────────────
    ax5 = fig.add_subplot(gs[2, 1])
    ax_style(ax5, "누적 수익 곡선 (시간순)")
    if len(all_trades):
        all_trades_sorted = all_trades.sort_values("entry_time")
        cumret = (all_trades_sorted["pnl_pct"] + 1).cumprod() - 1
        ax5.plot(range(len(cumret)), cumret * 100, color=GREEN, linewidth=1.0)
        ax5.axhline(0, color=RED, linewidth=0.8, linestyle="--")
        ax5.set_xlabel("거래 번호"); ax5.set_ylabel("누적 수익률 (%)")
        ax5.fill_between(range(len(cumret)), cumret * 100, 0,
                         where=cumret >= 0, alpha=0.15, color=GREEN)
        ax5.fill_between(range(len(cumret)), cumret * 100, 0,
                         where=cumret < 0,  alpha=0.15, color=RED)

    # ── 6. 성과 요약 ────────────────────────────────
    ax6 = fig.add_subplot(gs[3, :])
    ax6.set_facecolor(BG); ax6.axis("off")
    ax6.set_title("종합 성과 요약", color=FG, fontsize=12, fontweight="bold", pad=8)
    for sp in ax6.spines.values(): sp.set_edgecolor(GRID)

    if len(all_trades):
        at = all_trades.copy()
        wr_total = float(at["win"].mean())
        avg_pnl  = float(at["pnl_pct"].mean()) * 100
        tot_pnl  = float((at["pnl_pct"] + 1).prod() - 1) * 100
        wr_l = float(at.loc[at["direction"]=="LONG",  "win"].mean()) if (at["direction"]=="LONG").any()  else 0
        wr_s = float(at.loc[at["direction"]=="SHORT", "win"].mean()) if (at["direction"]=="SHORT").any() else 0
        n_l  = int((at["direction"]=="LONG").sum())
        n_s  = int((at["direction"]=="SHORT").sum())

        # Sharpe (일별 그룹)
        at["entry_time"] = pd.to_datetime(at["entry_time"])
        daily_pnl = at.groupby(at["entry_time"].dt.date)["pnl_pct"].sum()
        sharpe = (daily_pnl.mean() / (daily_pnl.std() + 1e-9)) * np.sqrt(252)

        # Max Drawdown
        cumret_arr = (at.sort_values("entry_time")["pnl_pct"] + 1).cumprod()
        roll_max = cumret_arr.cummax()
        drawdown = (cumret_arr - roll_max) / roll_max
        mdd = float(drawdown.min()) * 100

        tp_cnt = int((at["exit_type"] == "tp").sum())
        sl_cnt = int((at["exit_type"] == "sl").sum())
        to_cnt = int((at["exit_type"] == "timeout").sum())

        stats = [
            ("총 거래",       f"{len(at)}건  (L:{n_l}  S:{n_s})"),
            ("전체 승률",     f"{wr_total*100:.1f}%"),
            ("LONG 승률",     f"{wr_l*100:.1f}%"),
            ("SHORT 승률",    f"{wr_s*100:.1f}%"),
            ("평균 수익/거래", f"{avg_pnl:.3f}%"),
            ("최종 누적 수익", f"{tot_pnl:.1f}%"),
            ("Sharpe Ratio",  f"{sharpe:.2f}"),
            ("최대 낙폭(MDD)", f"{mdd:.1f}%"),
            ("TP/SL/시간종료", f"{tp_cnt} / {sl_cnt} / {to_cnt}"),
            ("수수료 반영",    "편도 0.05% (taker)"),
        ]
        cols_per_row = 5
        for i, (label, val) in enumerate(stats):
            col = i % cols_per_row
            row = i // cols_per_row
            x_pos = 0.05 + col * 0.20
            y_pos = 0.80 - row * 0.38
            color = GREEN if any(k in label for k in ["승률","수익","Sharpe"]) and "낙폭" not in label and "SL" not in label else FG
            ax6.text(x_pos,   y_pos, f"{label}:", transform=ax6.transAxes,
                     fontsize=10, color=GRID, va="center")
            ax6.text(x_pos,   y_pos - 0.18, val, transform=ax6.transAxes,
                     fontsize=12, color=color, va="center", fontweight="bold")

    out = os.path.join(CHART_DIR, f"directional_bt_{sym}_{ivl}.png")
    plt.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close()
    print(f"  차트 저장 → {out}")


# ══════════════════════════════════════════════════════
# 6. 메인
# ══════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol",   default="BTCUSDT")
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--from",     type=int, default=2020, dest="from_year")
    parser.add_argument("--fast",     action="store_true", help="TemporalXGB 스킵")
    args = parser.parse_args()

    sym = args.symbol
    ivl = args.interval

    print("=" * 65)
    print(f"  DirectionalEnsemble 학습 & 워크포워드 백테스트")
    print(f"  {sym} {ivl}  |  fast={args.fast}")
    print("=" * 65)

    # ── 데이터 로딩 ───────────────────────────────
    print("\n[1/5] OHLCV 로딩...")
    df = load_ohlcv(sym, ivl, from_year=args.from_year)

    print("\n[2/5] 외부 지표 로딩 & 병합...")
    ind = load_indicators()
    df  = merge_indicators(df, ind)

    # ── 피처 & 타겟 생성 ─────────────────────────
    print("\n[3/5] 피처 엔지니어링...")
    df = add_features(df)
    df = make_targets(df, horizon=HORIZON, tp=TP_PCT, sl=SL_PCT)
    feature_cols = get_feature_cols(df)

    # NaN 행 제거 (앞부분 지표 계산 안정화 구간)
    df = df.dropna(subset=feature_cols[:20]).reset_index(drop=True)

    long_rate  = df["y_long"].mean()
    short_rate = df["y_short"].mean()
    print(f"  피처: {len(feature_cols)}개  전체 샘플: {len(df):,}")
    print(f"  LONG 타겟 비율: {long_rate*100:.1f}%  SHORT 타겟 비율: {short_rate*100:.1f}%")
    print(f"  피처 예시: {feature_cols[:8]}")

    # ── 워크포워드 ────────────────────────────────
    print(f"\n[4/5] 워크포워드 ({WF_FOLDS}폴드, {WF_START} ~)...")
    fold_results, all_trades = walk_forward(df, feature_cols, fast_mode=args.fast)

    if fold_results:
        wf_df = pd.DataFrame(fold_results)
        wf_path = os.path.join(MODEL_DIR, f"wf_results_{sym}_{ivl}.csv")
        wf_df.to_csv(wf_path, index=False)
        trades_path = os.path.join(MODEL_DIR, f"trades_{sym}_{ivl}.csv")
        if len(all_trades): all_trades.to_csv(trades_path, index=False)

    # ── 최종 모델 학습 ────────────────────────────
    print("\n[5/5] 최종 모델 학습...")
    final_model = train_final(df, feature_cols, sym=sym, ivl=ivl, fast_mode=args.fast)

    # ── 결과 시각화 ───────────────────────────────
    plot_results(fold_results, all_trades, final_model, feature_cols, sym=sym, ivl=ivl)

    # ── 최종 요약 출력 ────────────────────────────
    print("\n" + "=" * 65)
    print("  📊 워크포워드 최종 요약")
    print("=" * 65)
    if fold_results:
        wf_df = pd.DataFrame(fold_results)
        print(wf_df[["fold","val_start","val_end","n_trades","win_rate",
                      "win_long","win_short","avg_pnl","total_pnl"]].to_string(index=False))
        print()
        if len(all_trades):
            at = all_trades
            wr  = float(at["win"].mean())
            tot = float((at["pnl_pct"] + 1).prod() - 1) * 100
            avg = float(at["pnl_pct"].mean()) * 100
            at_sorted = at.sort_values("entry_time")
            cum = (at_sorted["pnl_pct"] + 1).cumprod()
            mdd = float(((cum - cum.cummax()) / cum.cummax()).min()) * 100
            daily = at.groupby(pd.to_datetime(at["entry_time"]).dt.date)["pnl_pct"].sum()
            sharpe = (daily.mean() / (daily.std() + 1e-9)) * np.sqrt(252)

            print(f"  총 거래:       {len(at)}건")
            print(f"  전체 승률:     {wr*100:.1f}%")
            print(f"  평균 수익:     {avg:.3f}%/거래")
            print(f"  누적 수익:     {tot:.1f}%")
            print(f"  Sharpe:        {sharpe:.2f}")
            print(f"  MDD:           {mdd:.1f}%")

            verdict = "✅ 실전 투입 가능" if wr >= 0.54 and tot > 0 and sharpe > 0.5 else \
                      "⚠️  추가 튜닝 권장" if wr >= 0.50 else "❌ 재설계 필요"
            print(f"\n  판정: {verdict}")

    print("=" * 65)


if __name__ == "__main__":
    main()
