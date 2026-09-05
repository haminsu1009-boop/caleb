"""
backtest.py
지표 조합 백테스팅 엔진
- 다양한 기술적 지표 신호 정의
- 2~3개 지표 조합 테스트
- 조합별 승률(다음 날 수익률 > 0) 및 발생 횟수 계산
- 결과 저장: backtest_results.csv
"""

import os
import itertools
import pandas as pd
import numpy as np

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "btc_daily.csv")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "backtest_results.csv")

HOLD_DAYS = 3          # 매수 후 보유 기간 (일)
MIN_WIN_RATE = 0.70    # 최소 승률
MIN_OCCURRENCES = 20   # 최소 발생 횟수


# ───────────────────────────────────────────────
# 지표 계산
# ───────────────────────────────────────────────

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """모든 지표 컬럼 계산 후 반환"""
    df = df.copy()
    close = df["close"]
    high  = df["high"]
    low   = df["low"]
    vol   = df["volume"]

    # ── 이동평균 ──────────────────────────────
    for p in [7, 20, 50, 100, 200]:
        df[f"sma{p}"] = close.rolling(p).mean()
        df[f"ema{p}"] = close.ewm(span=p, adjust=False).mean()

    # ── RSI ──────────────────────────────────
    for p in [7, 14, 21]:
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(p).mean()
        loss  = (-delta.clip(upper=0)).rolling(p).mean()
        rs    = gain / loss.replace(0, np.nan)
        df[f"rsi{p}"] = 100 - (100 / (1 + rs))

    # ── MACD ─────────────────────────────────
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd"]        = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"]   = df["macd"] - df["macd_signal"]

    # ── 볼린저 밴드 (20일, 2σ) ───────────────
    for p, std_k in [(20, 2), (20, 1.5)]:
        mid  = close.rolling(p).mean()
        std  = close.rolling(p).std()
        df[f"bb{p}_upper_{std_k}"] = mid + std_k * std
        df[f"bb{p}_lower_{std_k}"] = mid - std_k * std
        df[f"bb{p}_mid"]           = mid
        df[f"bb{p}_%b_{std_k}"]    = (close - (mid - std_k*std)) / (2 * std_k * std)

    # ── 스토캐스틱 ───────────────────────────
    for p in [14, 21]:
        lowest  = low.rolling(p).min()
        highest = high.rolling(p).max()
        df[f"stoch_k{p}"] = (close - lowest) / (highest - lowest + 1e-9) * 100
        df[f"stoch_d{p}"] = df[f"stoch_k{p}"].rolling(3).mean()

    # ── ADX ──────────────────────────────────
    for p in [14]:
        tr  = pd.concat([high - low,
                         (high - close.shift()).abs(),
                         (low  - close.shift()).abs()], axis=1).max(axis=1)
        plus_dm  = high.diff().clip(lower=0)
        minus_dm = (-low.diff()).clip(lower=0)
        # 실제 교차 필터
        cond = plus_dm < minus_dm
        plus_dm[cond] = 0
        cond2 = minus_dm < plus_dm
        minus_dm[cond2] = 0

        atr      = tr.rolling(p).mean()
        plus_di  = 100 * plus_dm.rolling(p).mean()  / atr.replace(0, np.nan)
        minus_di = 100 * minus_dm.rolling(p).mean() / atr.replace(0, np.nan)
        dx       = (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9) * 100
        df[f"adx{p}"]       = dx.rolling(p).mean()
        df[f"plus_di{p}"]   = plus_di
        df[f"minus_di{p}"]  = minus_di

    # ── 거래량 지표 ───────────────────────────
    df["vol_sma20"]  = vol.rolling(20).mean()
    df["vol_ratio"]  = vol / df["vol_sma20"]

    # ── OBV ──────────────────────────────────
    obv = (np.sign(close.diff()) * vol).fillna(0).cumsum()
    df["obv"]       = obv
    df["obv_sma20"] = obv.rolling(20).mean()

    return df


# ───────────────────────────────────────────────
# 개별 신호 정의
# ───────────────────────────────────────────────

def define_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    각 신호: 1(매수 조건 충족), 0(미충족)
    NaN 행은 신호 계산 불가 처리
    """
    s = pd.DataFrame(index=df.index)
    c = df["close"]

    # RSI 계열
    s["RSI14_과매도(30이하)"]   = (df["rsi14"] < 30).astype(int)
    s["RSI14_과매도(35이하)"]   = (df["rsi14"] < 35).astype(int)
    s["RSI14_중립반등(40~50)"]  = ((df["rsi14"] >= 40) & (df["rsi14"] <= 50)).astype(int)
    s["RSI7_과매도(25이하)"]    = (df["rsi7"]  < 25).astype(int)
    s["RSI21_과매도(30이하)"]   = (df["rsi21"] < 30).astype(int)

    # MACD 계열
    s["MACD_골든크로스"]       = ((df["macd"] > df["macd_signal"]) &
                                   (df["macd"].shift(1) <= df["macd_signal"].shift(1))).astype(int)
    s["MACD_히스토_전환(+)"]   = ((df["macd_hist"] > 0) &
                                   (df["macd_hist"].shift(1) <= 0)).astype(int)
    s["MACD_히스토_증가"]      = (df["macd_hist"] > df["macd_hist"].shift(1)).astype(int)

    # 이동평균 계열
    s["SMA20_골든크로스(50)"]   = ((c > df["sma20"]) & (c.shift(1) <= df["sma20"].shift(1))).astype(int)
    s["SMA50_골든크로스(200)"]  = ((df["sma50"] > df["sma200"]) &
                                    (df["sma50"].shift(1) <= df["sma200"].shift(1))).astype(int)
    s["EMA20_골든크로스(50)"]   = ((df["ema20"] > df["ema50"]) &
                                    (df["ema20"].shift(1) <= df["ema50"].shift(1))).astype(int)
    s["EMA7_골든크로스(20)"]    = ((df["ema7"] > df["ema20"]) &
                                    (df["ema7"].shift(1) <= df["ema20"].shift(1))).astype(int)
    s["가격_SMA200_위"]         = (c > df["sma200"]).astype(int)
    s["가격_SMA50_위"]          = (c > df["sma50"]).astype(int)

    # 볼린저 밴드
    s["BB_하단터치(2σ)"]        = (c < df["bb20_lower_2"]).astype(int)
    s["BB_하단터치(1.5σ)"]      = (c < df["bb20_lower_1.5"]).astype(int)
    s["BB_%B_과매도(0.2이하)"]  = (df["bb20_%b_2"] < 0.2).astype(int)
    s["BB_%B_중간반등"]         = ((df["bb20_%b_2"] > 0.4) & (df["bb20_%b_2"] < 0.6)).astype(int)

    # 스토캐스틱
    s["STOCH14_과매도(20이하)"] = (df["stoch_k14"] < 20).astype(int)
    s["STOCH14_골든크로스"]     = ((df["stoch_k14"] > df["stoch_d14"]) &
                                    (df["stoch_k14"].shift(1) <= df["stoch_d14"].shift(1))).astype(int)
    s["STOCH21_과매도(20이하)"] = (df["stoch_k21"] < 20).astype(int)

    # ADX
    s["ADX14_강세(25이상)"]     = (df["adx14"] > 25).astype(int)
    s["ADX14_추세상승(+DI>-DI)"] = (df["plus_di14"] > df["minus_di14"]).astype(int)

    # 거래량
    s["거래량_급증(2배이상)"]    = (df["vol_ratio"] > 2.0).astype(int)
    s["거래량_증가(1.5배)"]      = (df["vol_ratio"] > 1.5).astype(int)
    s["OBV_SMA위"]              = (df["obv"] > df["obv_sma20"]).astype(int)

    return s


# ───────────────────────────────────────────────
# 백테스트
# ───────────────────────────────────────────────

def backtest_combination(df: pd.DataFrame, signals: pd.DataFrame,
                          combo: tuple, hold_days: int = HOLD_DAYS) -> dict | None:
    """
    combo에 속한 모든 신호가 동시에 1인 날 매수 → hold_days 후 종가 기준 승/패
    """
    combined = signals[list(combo)].prod(axis=1)  # AND 조합
    signal_dates = df.index[combined == 1]

    if len(signal_dates) < MIN_OCCURRENCES:
        return None

    wins = 0
    total = 0
    returns = []

    for idx in signal_dates:
        future_idx = idx + hold_days
        if future_idx >= len(df):
            continue
        entry_price  = df.loc[idx, "close"]
        exit_price   = df.loc[future_idx, "close"]
        ret = (exit_price - entry_price) / entry_price
        returns.append(ret)
        total += 1
        if ret > 0:
            wins += 1

    if total < MIN_OCCURRENCES:
        return None

    avg_return = float(np.mean(returns)) if returns else 0.0
    win_rate   = wins / total

    return {
        "조합": " + ".join(combo),
        "지표수": len(combo),
        "발생횟수": total,
        "승률": round(win_rate, 4),
        "평균수익률": round(avg_return, 4),
        "총수익률(누적)": round(float(np.prod([1 + r for r in returns])) - 1, 4),
    }


def run_backtest() -> pd.DataFrame:
    print(f"[백테스트] 데이터 로딩: {DATA_FILE}")
    df = pd.read_csv(DATA_FILE)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    print("  지표 계산 중...")
    df = compute_indicators(df)

    print("  신호 정의 중...")
    signals = define_signals(df)

    signal_cols = list(signals.columns)
    print(f"  정의된 신호 수: {len(signal_cols)}")

    results = []

    # 단일 신호
    print("  단일 신호 테스트...")
    for sig in signal_cols:
        res = backtest_combination(df, signals, (sig,))
        if res:
            results.append(res)

    # 2개 조합
    print("  2개 조합 테스트...")
    combos2 = list(itertools.combinations(signal_cols, 2))
    for i, combo in enumerate(combos2):
        res = backtest_combination(df, signals, combo)
        if res:
            results.append(res)
        if (i + 1) % 100 == 0:
            print(f"    {i+1}/{len(combos2)} 완료...")

    # 3개 조합
    print("  3개 조합 테스트...")
    combos3 = list(itertools.combinations(signal_cols, 3))
    for i, combo in enumerate(combos3):
        res = backtest_combination(df, signals, combo)
        if res:
            results.append(res)
        if (i + 1) % 500 == 0:
            print(f"    {i+1}/{len(combos3)} 완료...")

    result_df = pd.DataFrame(results)
    if result_df.empty:
        print("[경고] 조건을 만족하는 조합 없음")
        return result_df

    result_df = result_df.sort_values(["승률", "발생횟수"], ascending=False).reset_index(drop=True)
    result_df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    print(f"\n[완료] 총 {len(result_df)}개 조합 결과 저장 → {OUTPUT_FILE}")
    print(f"  승률 70%+ 조합: {(result_df['승률'] >= 0.70).sum()}개")
    return result_df


if __name__ == "__main__":
    run_backtest()
