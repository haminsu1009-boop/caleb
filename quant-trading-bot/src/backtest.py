"""
백테스트 엔진
다양한 기술적 지표 조합으로 매수 신호를 생성하고,
N일 후 수익률을 기준으로 승률/수익률을 계산.
"""

import pandas as pd
import numpy as np
import os
from itertools import combinations

from indicators import add_all_indicators

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "btc_daily.csv")
RESULT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "backtest_results.csv")

# 매수 후 평가 기간 (일)
HOLD_DAYS = 5


def define_conditions(df):
    """
    개별 매수 조건 정의.
    각 조건은 (이름, bool Series) 형태.
    """
    conditions = []

    # --- 이동평균 관련 ---
    conditions.append(("SMA5>SMA20", df["sma_5"] > df["sma_20"]))
    conditions.append(("SMA10>SMA50", df["sma_10"] > df["sma_50"]))
    conditions.append(("SMA20>SMA100", df["sma_20"] > df["sma_100"]))
    conditions.append(("SMA50>SMA200", df["sma_50"] > df["sma_200"]))
    conditions.append(("EMA5>EMA20", df["ema_5"] > df["ema_20"]))
    conditions.append(("EMA10>EMA50", df["ema_10"] > df["ema_50"]))
    conditions.append(("Price>SMA20", df["close"] > df["sma_20"]))
    conditions.append(("Price>SMA50", df["close"] > df["sma_50"]))
    conditions.append(("Price>SMA200", df["close"] > df["sma_200"]))
    conditions.append(("Price>EMA20", df["close"] > df["ema_20"]))

    # SMA 골든크로스 (전일 하회 → 당일 상회)
    conditions.append(("GoldenCross_5_20",
                        (df["sma_5"] > df["sma_20"]) & (df["sma_5"].shift(1) <= df["sma_20"].shift(1))))
    conditions.append(("GoldenCross_50_200",
                        (df["sma_50"] > df["sma_200"]) & (df["sma_50"].shift(1) <= df["sma_200"].shift(1))))

    # --- RSI 관련 ---
    conditions.append(("RSI14<30", df["rsi_14"] < 30))
    conditions.append(("RSI14<40", df["rsi_14"] < 40))
    conditions.append(("RSI14_30_50", (df["rsi_14"] > 30) & (df["rsi_14"] < 50)))
    conditions.append(("RSI7<25", df["rsi_7"] < 25))
    conditions.append(("RSI14_Rising",
                        (df["rsi_14"] > df["rsi_14"].shift(1)) & (df["rsi_14"].shift(1) < 40)))

    # --- MACD 관련 ---
    conditions.append(("MACD>Signal", df["macd"] > df["macd_signal"]))
    conditions.append(("MACD_Cross_Up",
                        (df["macd"] > df["macd_signal"]) & (df["macd"].shift(1) <= df["macd_signal"].shift(1))))
    conditions.append(("MACD_Hist>0", df["macd_hist"] > 0))
    conditions.append(("MACD_Hist_Rising",
                        df["macd_hist"] > df["macd_hist"].shift(1)))

    # --- Bollinger Bands ---
    conditions.append(("BB_Lower_Touch", df["close"] <= df["bb_lower"]))
    conditions.append(("BB_PctB<0.2", df["bb_pctb"] < 0.2))
    conditions.append(("BB_PctB<0.5", df["bb_pctb"] < 0.5))
    conditions.append(("BB_Squeeze",
                        (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"] <
                        ((df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]).rolling(50).mean() * 0.8))

    # --- Stochastic ---
    conditions.append(("Stoch_K<20", df["stoch_k"] < 20))
    conditions.append(("Stoch_Cross_Up",
                        (df["stoch_k"] > df["stoch_d"]) & (df["stoch_k"].shift(1) <= df["stoch_d"].shift(1))))
    conditions.append(("Stoch_K<30", df["stoch_k"] < 30))

    # --- CCI ---
    conditions.append(("CCI<-100", df["cci_20"] < -100))
    conditions.append(("CCI_Rising",
                        (df["cci_20"] > df["cci_20"].shift(1)) & (df["cci_20"] < 0)))

    # --- ADX ---
    conditions.append(("ADX>25", df["adx_14"] > 25))
    conditions.append(("ADX>20_PlusDI>MinusDI",
                        (df["adx_14"] > 20) & (df["plus_di"] > df["minus_di"])))

    # --- Williams %R ---
    conditions.append(("WillR<-80", df["williams_r"] < -80))
    conditions.append(("WillR_Rising",
                        (df["williams_r"] > df["williams_r"].shift(1)) & (df["williams_r"] < -50)))

    # --- MFI ---
    conditions.append(("MFI<20", df["mfi_14"] < 20))
    conditions.append(("MFI<40", df["mfi_14"] < 40))

    # --- Volume ---
    conditions.append(("VolSpike>1.5", df["vol_ratio"] > 1.5))
    conditions.append(("VolSpike>2.0", df["vol_ratio"] > 2.0))

    # --- 가격 패턴 ---
    conditions.append(("Bullish_Engulf",
                        (df["close"] > df["open"]) & (df["close"].shift(1) < df["open"].shift(1)) &
                        (df["close"] > df["open"].shift(1)) & (df["open"] < df["close"].shift(1))))
    conditions.append(("Hammer",
                        (df["close"] > df["open"]) &
                        ((df["open"] - df["low"]) > 2 * (df["close"] - df["open"])) &
                        ((df["high"] - df["close"]) < (df["close"] - df["open"]))))
    conditions.append(("ThreeGreenDays",
                        (df["close"] > df["open"]) &
                        (df["close"].shift(1) > df["open"].shift(1)) &
                        (df["close"].shift(2) > df["open"].shift(2))))

    return conditions


def run_backtest():
    print("데이터 로드 중...")
    df = pd.read_csv(DATA_PATH)
    df = add_all_indicators(df)

    # N일 후 수익률
    df["future_return"] = df["close"].shift(-HOLD_DAYS) / df["close"] - 1
    df["is_win"] = df["future_return"] > 0

    # 유효 데이터만 (지표 계산 + 미래 수익률 존재)
    valid_mask = df["future_return"].notna() & df["adx_14"].notna() & df["sma_200"].notna()

    conditions = define_conditions(df)
    print(f"총 {len(conditions)}개 개별 조건 정의됨")

    results = []

    # 개별 조건 테스트
    print("개별 조건 백테스트 중...")
    for name, cond in conditions:
        mask = valid_mask & cond.fillna(False)
        n = mask.sum()
        if n < 5:
            continue
        wins = df.loc[mask, "is_win"].sum()
        avg_ret = df.loc[mask, "future_return"].mean() * 100
        results.append({
            "조합": name,
            "조건수": 1,
            "발생횟수": int(n),
            "승리횟수": int(wins),
            "승률(%)": round(wins / n * 100, 2),
            "평균수익률(%)": round(avg_ret, 2),
            "구성지표": name,
        })

    # 2개 조합
    print("2개 조합 백테스트 중...")
    for (n1, c1), (n2, c2) in combinations(conditions, 2):
        mask = valid_mask & c1.fillna(False) & c2.fillna(False)
        n = mask.sum()
        if n < 5:
            continue
        wins = df.loc[mask, "is_win"].sum()
        avg_ret = df.loc[mask, "future_return"].mean() * 100
        combo_name = f"{n1} + {n2}"
        results.append({
            "조합": combo_name,
            "조건수": 2,
            "발생횟수": int(n),
            "승리횟수": int(wins),
            "승률(%)": round(wins / n * 100, 2),
            "평균수익률(%)": round(avg_ret, 2),
            "구성지표": combo_name,
        })

    # 3개 조합 (유망한 조건만 선별하여 조합)
    print("3개 조합 백테스트 중...")
    # 개별 승률 55% 이상인 조건만 3개 조합에 사용
    good_conditions = []
    for name, cond in conditions:
        mask = valid_mask & cond.fillna(False)
        n = mask.sum()
        if n < 10:
            continue
        wins = df.loc[mask, "is_win"].sum()
        if wins / n >= 0.55:
            good_conditions.append((name, cond))

    print(f"  유망 조건 {len(good_conditions)}개로 3개 조합 생성 중...")
    for (n1, c1), (n2, c2), (n3, c3) in combinations(good_conditions, 3):
        mask = valid_mask & c1.fillna(False) & c2.fillna(False) & c3.fillna(False)
        n = mask.sum()
        if n < 5:
            continue
        wins = df.loc[mask, "is_win"].sum()
        avg_ret = df.loc[mask, "future_return"].mean() * 100
        combo_name = f"{n1} + {n2} + {n3}"
        results.append({
            "조합": combo_name,
            "조건수": 3,
            "발생횟수": int(n),
            "승리횟수": int(wins),
            "승률(%)": round(wins / n * 100, 2),
            "평균수익률(%)": round(avg_ret, 2),
            "구성지표": combo_name,
        })

    result_df = pd.DataFrame(results)
    result_df = result_df.sort_values("승률(%)", ascending=False).reset_index(drop=True)

    os.makedirs(os.path.dirname(RESULT_PATH), exist_ok=True)
    result_df.to_csv(RESULT_PATH, index=False, encoding="utf-8-sig")
    print(f"\n백테스트 완료: {len(result_df)}개 조합 분석")
    print(f"결과 저장: {RESULT_PATH}")

    # 요약
    high_wr = result_df[(result_df["승률(%)"] >= 70) & (result_df["발생횟수"] >= 20)]
    print(f"\n승률 70%+ & 발생횟수 20회+ 조합: {len(high_wr)}개")
    if len(high_wr) > 0:
        print(high_wr.head(20).to_string(index=False))

    return result_df


if __name__ == "__main__":
    run_backtest()
