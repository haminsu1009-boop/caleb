"""
ml/regime.py
시장 국면 감지기 (Market Regime Detector) — 고도화 버전

국면 코드:
  2 = BULL   : 상승장 → 적극 매수
  1 = NEUTRAL: 횡보장 → 보수적
  0 = BEAR   : 하락장 → 매매 중단 또는 숏

추가 국면 레이블 (regime_label):
  BULL_TRENDING    : 상승 + 강한 추세 (ADX 높음)
  BULL_RANGING     : 상승 + 횡보 (ADX 낮음)
  BEAR_TRENDING    : 하락 + 강한 추세
  BEAR_RANGING     : 하락 + 횡보
  NEUTRAL          : 중립

변동성 국면 (vol_regime):
  HIGH_VOL   : 변동성 팽창 (브레이크아웃 기회)
  LOW_VOL    : 변동성 수축 (스퀴즈 — 브레이크아웃 준비)
  NORMAL_VOL : 보통
"""

import numpy as np
import pandas as pd


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 내부 헬퍼
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _compute_adx(high: pd.Series, low: pd.Series,
                  close: pd.Series, period: int = 14) -> tuple:
    """ADX, +DI, -DI 계산"""
    tr   = pd.concat([high - low,
                      (high - close.shift()).abs(),
                      (low  - close.shift()).abs()], axis=1).max(axis=1)
    pdm  = high.diff().clip(lower=0)
    mdm  = (-low.diff()).clip(lower=0)
    # Wilder smoothing
    atr  = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    pdm_s = pdm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    mdm_s = mdm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    pdi  = 100 * pdm_s / (atr + 1e-9)
    mdi  = 100 * mdm_s / (atr + 1e-9)
    dx   = (pdi - mdi).abs() / (pdi + mdi + 1e-9) * 100
    adx  = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    return adx, pdi, mdi


def _bollinger_squeeze(close: pd.Series,
                        bb_period: int = 20, bb_k: float = 2.0,
                        kc_period: int = 20, kc_mult: float = 1.5) -> pd.Series:
    """볼린저 밴드 스퀴즈 (BB < KC 이면 스퀴즈 = 변동성 수축)"""
    bb_mid = close.rolling(bb_period).mean()
    bb_std = close.rolling(bb_period).std()
    bb_upper = bb_mid + bb_k * bb_std
    bb_lower = bb_mid - bb_k * bb_std
    bb_width = bb_upper - bb_lower

    tr = pd.concat([close.diff().abs(),
                    (close.rolling(2).max() - close.rolling(2).min())], axis=1).max(axis=1)
    atr = tr.rolling(kc_period).mean()
    kc_upper = bb_mid + kc_mult * atr
    kc_lower = bb_mid - kc_mult * atr
    kc_width = kc_upper - kc_lower

    squeeze = (bb_width < kc_width).astype(int)   # 1 = 스퀴즈 중
    return squeeze


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 기본 국면 감지 (score 기반)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def detect_regime(df: pd.DataFrame) -> pd.Series:
    """
    각 행에 대한 시장 국면 반환 (0=BEAR, 1=NEUTRAL, 2=BULL)

    판단 기준 (복합 스코어):
      - 가격 vs SMA50 / SMA100 / SMA200
      - 단기/장기 모멘텀 (20일 / 60일)
      - ADX 추세 강도 + DI 방향
      - 최근 고점 대비 낙폭 (ATH 드로우다운)
      - 변동성 압축 상태
    """
    c      = df["close"]
    h      = df["high"]
    l      = df["low"]
    sma50  = c.rolling(50, min_periods=20).mean()
    sma100 = c.rolling(100, min_periods=30).mean()
    sma200 = c.rolling(200, min_periods=50).mean()

    # ADX / DI 계산
    adx, pdi, mdi = _compute_adx(h, l, c, period=14)

    # ── 스코어 집계 (0~10점) ───────────────────────
    score = pd.Series(0.0, index=df.index)

    score += (c > sma50).astype(float)                  # +1: SMA50 위
    score += (c > sma100).astype(float)                 # +1: SMA100 위
    score += (c > sma200).astype(float) * 1.5           # +1.5: SMA200 위 (중요)
    score += (sma50 > sma200).astype(float)             # +1: 골든크로스 상태
    score += (c.pct_change(20) > 0).astype(float)       # +1: 20일 수익 플러스
    score += (c.pct_change(60) > 0).astype(float)       # +1: 60일 수익 플러스
    score += (pdi > mdi).astype(float) * 0.5            # +0.5: +DI > -DI (상승 추세)
    score += (adx > 25).astype(float) * 0.5             # +0.5: 강한 추세 존재

    # ── ATH 대비 낙폭 패널티 ──────────────────────
    rolling_max = c.rolling(252, min_periods=50).max()
    drawdown    = (c / rolling_max) - 1
    forced_bear = drawdown < -0.40                       # -40% 이하 → 강제 BEAR

    # ── 국면 분류 (총 10점 만점) ───────────────────
    regime = pd.Series(1, index=df.index, dtype=int)    # 기본: NEUTRAL
    regime[score >= 5.0] = 2                             # BULL
    regime[score <= 2.0] = 0                             # BEAR
    regime[forced_bear]  = 0                             # 강제 BEAR

    return regime


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 추세 국면 (Trending vs Ranging)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def detect_trend_regime(df: pd.DataFrame, adx_threshold: float = 25.0) -> pd.Series:
    """
    추세 강도 국면
    Returns: 'TRENDING' | 'RANGING'
    """
    adx, _, _ = _compute_adx(df["high"], df["low"], df["close"], period=14)
    result = pd.Series("RANGING", index=df.index)
    result[adx >= adx_threshold] = "TRENDING"
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 변동성 국면
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def detect_vol_regime(df: pd.DataFrame) -> pd.Series:
    """
    변동성 국면 감지
    Returns: pd.Series with values 0=LOW_VOL, 1=NORMAL_VOL, 2=HIGH_VOL
    """
    c    = df["close"]
    vol  = c.pct_change().rolling(20, min_periods=5).std()
    vol_ma = vol.rolling(60, min_periods=20).mean()

    squeeze = _bollinger_squeeze(c)

    regime = pd.Series(1, index=df.index, dtype=int)    # NORMAL
    # 스퀴즈 중 OR 변동성 낮음
    regime[(squeeze == 1) | (vol < vol_ma * 0.7)] = 0   # LOW_VOL
    # 변동성 급팽창
    regime[vol > vol_ma * 1.5] = 2                       # HIGH_VOL

    return regime


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 통합 피처 추가
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def add_regime_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    시장 국면 관련 피처 전체 추가

    추가 컬럼:
      regime            : 0=BEAR / 1=NEUTRAL / 2=BULL
      is_bull/bear/neutral
      regime_days       : 현재 국면 지속 기간
      drawdown_1y / 6m  : 최근 고점 대비 낙폭
      bull_entry / bear_entry : 국면 전환 신호
      adx / pdi / mdi   : ADX 지표
      trend_regime      : 0=RANGING / 1=TRENDING
      vol_regime        : 0=LOW / 1=NORMAL / 2=HIGH
      regime_label      : 문자열 국면 레이블
      squeeze           : 볼린저 스퀴즈 여부
      regime_score      : 원시 스코어 (0~10)
    """
    df = df.copy()
    c  = df["close"]
    h  = df["high"]
    l  = df["low"]

    # ── 기본 국면 ─────────────────────────────────
    regime = detect_regime(df)
    df["regime"]     = regime
    df["is_bull"]    = (regime == 2).astype(int)
    df["is_bear"]    = (regime == 0).astype(int)
    df["is_neutral"] = (regime == 1).astype(int)

    # 국면 지속 기간
    regime_change    = (regime != regime.shift(1)).fillna(True)
    cum_change       = regime_change.cumsum()
    df["regime_days"] = cum_change.groupby(cum_change).cumcount()

    # ── 낙폭 지표 ─────────────────────────────────
    df["drawdown_1y"] = c / c.rolling(252, min_periods=50).max() - 1
    df["drawdown_6m"] = c / c.rolling(126, min_periods=30).max() - 1

    # ── 국면 전환 신호 ─────────────────────────────
    df["bull_entry"] = ((regime == 2) & (regime.shift(1) != 2)).astype(int)
    df["bear_entry"] = ((regime == 0) & (regime.shift(1) != 0)).astype(int)

    # ── ADX 지표 ──────────────────────────────────
    adx, pdi, mdi   = _compute_adx(h, l, c, period=14)
    df["adx"]        = adx / 100
    df["pdi"]        = pdi / 100
    df["mdi"]        = mdi / 100
    df["di_diff"]    = (pdi - mdi) / 100
    df["adx_strong"] = (adx > 25).astype(int)           # 강한 추세
    df["adx_weak"]   = (adx < 20).astype(int)           # 약한 추세 (횡보)

    # ── 추세 국면 ─────────────────────────────────
    trend_r = detect_trend_regime(df, adx_threshold=25.0)
    df["trend_regime"] = (trend_r == "TRENDING").astype(int)  # 1=TRENDING, 0=RANGING

    # ── 변동성 국면 ───────────────────────────────
    vol_r = detect_vol_regime(df)
    df["vol_regime"]     = vol_r                         # 0/1/2
    df["vol_regime_low"]  = (vol_r == 0).astype(int)
    df["vol_regime_high"] = (vol_r == 2).astype(int)

    # ── 볼린저 스퀴즈 ─────────────────────────────
    df["squeeze"] = _bollinger_squeeze(c)

    # ── 통합 국면 레이블 (문자열) ──────────────────
    labels = []
    for i in range(len(df)):
        r = regime.iloc[i]
        t = trend_r.iloc[i]
        if r == 2:
            labels.append("BULL_TRENDING" if t == "TRENDING" else "BULL_RANGING")
        elif r == 0:
            labels.append("BEAR_TRENDING" if t == "TRENDING" else "BEAR_RANGING")
        else:
            labels.append("NEUTRAL")
    df["regime_label"] = labels

    # ── 국면 원시 스코어 재계산 ────────────────────
    sma50  = c.rolling(50, min_periods=20).mean()
    sma200 = c.rolling(200, min_periods=50).mean()
    score  = pd.Series(0.0, index=df.index)
    score += (c > sma50).astype(float)
    score += (c > sma200).astype(float) * 1.5
    score += (sma50 > sma200).astype(float)
    score += (c.pct_change(20) > 0).astype(float)
    score += (c.pct_change(60) > 0).astype(float)
    score += (pdi > mdi).astype(float) * 0.5
    score += (adx > 25).astype(float) * 0.5
    df["regime_score"] = score / 8.0                     # 0~1 정규화

    return df


def get_regime_stats(df: pd.DataFrame) -> dict:
    """국면별 다음 수익률 통계"""
    if "regime" not in df.columns:
        df = add_regime_features(df)

    df = df.copy()
    df["next_ret"] = df["close"].pct_change().shift(-1)
    stats = {}
    labels = {2: "BULL", 1: "NEUTRAL", 0: "BEAR"}

    for code, name in labels.items():
        sub = df[df["regime"] == code]["next_ret"].dropna()
        if sub.empty:
            continue
        stats[name] = {
            "days":     len(sub),
            "win_rate": float((sub > 0).mean()),
            "avg_ret":  float(sub.mean()),
            "pct":      len(sub) / len(df) * 100,
        }

    # ADX별 통계
    if "adx_strong" in df.columns:
        for adx_state, adx_name in [(1, "TRENDING"), (0, "RANGING")]:
            sub = df[df["adx_strong"] == adx_state]["next_ret"].dropna()
            if sub.empty: continue
            stats[f"ADX_{adx_name}"] = {
                "days":     len(sub),
                "win_rate": float((sub > 0).mean()),
                "avg_ret":  float(sub.mean()),
                "pct":      len(sub) / len(df) * 100,
            }

    return stats


if __name__ == "__main__":
    import os
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    df   = pd.read_csv(os.path.join(ROOT, "data", "btc_daily.csv"))
    df   = add_regime_features(df)

    print("시장 국면 통계")
    print("=" * 60)
    stats = get_regime_stats(df)
    for name, s in stats.items():
        print(f"  {name:20s}: {s['days']:4d}일 ({s['pct']:5.1f}%)  "
              f"승률={s['win_rate']*100:.1f}%  평균수익={s['avg_ret']*100:.2f}%")

    recent_regime = df["regime_label"].iloc[-1]
    recent_vol    = {0:"LOW_VOL",1:"NORMAL_VOL",2:"HIGH_VOL"}[df["vol_regime"].iloc[-1]]
    print(f"\n현재 국면: {recent_regime}  |  변동성: {recent_vol}")
    print(f"ADX: {df['adx'].iloc[-1]*100:.1f}  |  스퀴즈: {'ON' if df['squeeze'].iloc[-1] else 'OFF'}")
