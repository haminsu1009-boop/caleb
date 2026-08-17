"""
ml/regime.py
시장 국면 감지기 (Market Regime Detector)

국면 정의:
  2 = BULL   : 상승장 → 적극 매수
  1 = NEUTRAL: 횡보장 → 보수적 매수
  0 = BEAR   : 하락장 → 매매 중단

근거: 워크포워드 분석에서 하락장 Fold들의 승률이 14~37%로 급락
     → 하락장 진입 차단만으로 평균 승률 크게 개선 가능
"""

import numpy as np
import pandas as pd


def detect_regime(df: pd.DataFrame) -> pd.Series:
    """
    각 행(날짜)에 대한 시장 국면 반환 (0=BEAR, 1=NEUTRAL, 2=BULL)

    판단 기준 (복합):
      - 가격 vs SMA50, SMA100, SMA200
      - 단기/장기 모멘텀
      - ADX 추세 강도
      - 최근 고점 대비 낙폭
    """
    c   = df["close"]
    sma50  = c.rolling(50).mean()
    sma100 = c.rolling(100).mean()
    sma200 = c.rolling(200).mean()

    # ── 기술적 국면 점수 (0~6점) ───────────────
    score = pd.Series(0, index=df.index)

    score += (c > sma50).astype(int)             # +1: SMA50 위
    score += (c > sma100).astype(int)            # +1: SMA100 위
    score += (c > sma200).astype(int)            # +1: SMA200 위 (가장 중요)
    score += (sma50 > sma200).astype(int)        # +1: 골든크로스 상태
    score += (c.pct_change(20) > 0).astype(int)  # +1: 20일 수익 플러스
    score += (c.pct_change(60) > 0).astype(int)  # +1: 60일 수익 플러스

    # ── ATH 대비 낙폭 패널티 ───────────────────
    rolling_max = c.rolling(252).max()           # 1년 고점
    drawdown    = (c / rolling_max) - 1

    # -40% 이상 낙폭이면 BEAR 강제
    forced_bear = drawdown < -0.40

    # ── 국면 분류 ──────────────────────────────
    regime = pd.Series(1, index=df.index)        # 기본: NEUTRAL
    regime[score >= 4] = 2                       # BULL
    regime[score <= 2] = 0                       # BEAR
    regime[forced_bear] = 0                      # 강제 BEAR

    return regime


def add_regime_features(df: pd.DataFrame) -> pd.DataFrame:
    """국면 관련 피처 추가"""
    df = df.copy()
    c = df["close"]

    regime = detect_regime(df)
    df["regime"]       = regime
    df["is_bull"]      = (regime == 2).astype(int)
    df["is_bear"]      = (regime == 0).astype(int)
    df["is_neutral"]   = (regime == 1).astype(int)

    # 국면 지속 기간
    regime_change = (regime != regime.shift(1))
    df["regime_days"]  = regime_change.cumsum().groupby(
        regime_change.cumsum()
    ).cumcount()

    # ATH 대비 낙폭
    df["drawdown_1y"]  = c / c.rolling(252).max() - 1
    df["drawdown_6m"]  = c / c.rolling(126).max() - 1

    # 국면 전환 신호
    df["bull_entry"]   = ((regime == 2) & (regime.shift(1) != 2)).astype(int)
    df["bear_entry"]   = ((regime == 0) & (regime.shift(1) != 0)).astype(int)

    return df


def get_regime_stats(df: pd.DataFrame) -> dict:
    """국면별 다음날 수익률 통계"""
    if "regime" not in df.columns:
        df = add_regime_features(df)

    df["next_ret"] = df["close"].pct_change().shift(-1)
    stats = {}
    labels = {2: "BULL", 1: "NEUTRAL", 0: "BEAR"}

    for code, name in labels.items():
        sub = df[df["regime"] == code]["next_ret"].dropna()
        if sub.empty:
            continue
        stats[name] = {
            "days":     len(sub),
            "win_rate": (sub > 0).mean(),
            "avg_ret":  sub.mean(),
            "pct":      len(sub) / len(df) * 100,
        }
    return stats


if __name__ == "__main__":
    import os
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    df   = pd.read_csv(os.path.join(ROOT, "data", "btc_daily.csv"))
    df   = add_regime_features(df)

    print("시장 국면 통계")
    print("=" * 50)
    stats = get_regime_stats(df)
    for name, s in stats.items():
        print(f"  {name:8s}: {s['days']:4d}일 ({s['pct']:.0f}%)  "
              f"승률={s['win_rate']*100:.1f}%  평균수익={s['avg_ret']*100:.2f}%")

    recent = df["regime"].iloc[-1]
    label  = {2:"BULL", 1:"NEUTRAL", 0:"BEAR"}[recent]
    print(f"\n현재 국면: {label}")
