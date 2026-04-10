"""
매일 백테스트 검증이력 기록 시스템
- 매일 실행하여 현재 시점 기준 백테스트 결과를 results/검증이력.csv에 추가
- 날짜별로 결과가 누적되어 전략 성능 변화를 추적 가능
- 실행: python3 daily_verify.py
- cron 등록 예시: 0 0 * * * cd /path/to/quant-trading-bot && python3 src/daily_verify.py
"""

import pandas as pd
import numpy as np
import os
from datetime import datetime
from itertools import combinations

from indicators import add_all_indicators

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
DATA_PATH = os.path.join(BASE_DIR, "data", "btc_daily.csv")
VERIFY_PATH = os.path.join(BASE_DIR, "results", "검증이력.csv")

HOLD_DAYS = 5

# 상위 전략 리스트 (검증 대상)
TOP_STRATEGY_NAMES = [
    "MACD>Signal + VolSpike>1.5 + ThreeGreenDays",
    "MACD_Hist>0 + VolSpike>1.5 + ThreeGreenDays",
    "ADX>25 + VolSpike>1.5 + ThreeGreenDays",
    "SMA5>SMA20 + VolSpike>1.5 + ThreeGreenDays",
    "MACD_Hist>0 + ADX>20_PlusDI>MinusDI + ThreeGreenDays",
    "MACD>Signal + ADX>20_PlusDI>MinusDI + ThreeGreenDays",
    "SMA20>SMA100 + MACD>Signal + ThreeGreenDays",
    "SMA10>SMA50 + MACD>Signal + ADX>25",
    "SMA10>SMA50 + MACD_Hist>0 + ADX>25",
    "SMA20>SMA100 + MACD>Signal + ADX>25",
]


def define_conditions(df):
    """백테스트용 개별 조건 사전"""
    conds = {
        "SMA5>SMA20": df["sma_5"] > df["sma_20"],
        "SMA10>SMA50": df["sma_10"] > df["sma_50"],
        "SMA20>SMA100": df["sma_20"] > df["sma_100"],
        "SMA50>SMA200": df["sma_50"] > df["sma_200"],
        "Price>SMA20": df["close"] > df["sma_20"],
        "Price>SMA50": df["close"] > df["sma_50"],
        "Price>SMA200": df["close"] > df["sma_200"],
        "Price>EMA20": df["close"] > df["ema_20"],
        "EMA5>EMA20": df["ema_5"] > df["ema_20"],
        "EMA10>EMA50": df["ema_10"] > df["ema_50"],
        "MACD>Signal": df["macd"] > df["macd_signal"],
        "MACD_Hist>0": df["macd_hist"] > 0,
        "ADX>25": df["adx_14"] > 25,
        "ADX>20_PlusDI>MinusDI": (df["adx_14"] > 20) & (df["plus_di"] > df["minus_di"]),
        "VolSpike>1.5": df["vol_ratio"] > 1.5,
        "ThreeGreenDays": (
            (df["close"] > df["open"]) &
            (df["close"].shift(1) > df["open"].shift(1)) &
            (df["close"].shift(2) > df["open"].shift(2))
        ),
    }
    return conds


def evaluate_strategy(df, strategy_name, conds):
    """전략의 현재 승률/수익률 계산"""
    parts = [p.strip() for p in strategy_name.split("+")]

    mask = pd.Series(True, index=df.index)
    for part in parts:
        if part in conds:
            mask = mask & conds[part].fillna(False)
        else:
            return None

    # future return이 존재하는 행만
    valid = mask & df["future_return"].notna() & df["sma_200"].notna()
    n = valid.sum()
    if n == 0:
        return {"발생횟수": 0, "승률(%)": 0, "평균수익률(%)": 0}

    wins = df.loc[valid, "is_win"].sum()
    avg_ret = df.loc[valid, "future_return"].mean() * 100

    return {
        "발생횟수": int(n),
        "승리횟수": int(wins),
        "승률(%)": round(wins / n * 100, 2),
        "평균수익률(%)": round(avg_ret, 2),
    }


def run_daily_verification():
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"일일 검증이력 기록 시작: {today}")

    df = pd.read_csv(DATA_PATH)
    df = add_all_indicators(df)
    df["future_return"] = df["close"].shift(-HOLD_DAYS) / df["close"] - 1
    df["is_win"] = df["future_return"] > 0

    conds = define_conditions(df)

    records = []
    for strategy_name in TOP_STRATEGY_NAMES:
        result = evaluate_strategy(df, strategy_name, conds)
        if result is None:
            continue

        records.append({
            "검증일자": today,
            "전략명": strategy_name,
            "발생횟수": result["발생횟수"],
            "승리횟수": result.get("승리횟수", 0),
            "승률(%)": result["승률(%)"],
            "평균수익률(%)": result["평균수익률(%)"],
            "데이터기간": f"{df['date'].iloc[0]}~{df['date'].iloc[-1]}" if "date" in df.columns else "N/A",
            "BTC현재가": df["close"].iloc[-1],
        })

    new_df = pd.DataFrame(records)

    # 기존 이력에 추가
    os.makedirs(os.path.dirname(VERIFY_PATH), exist_ok=True)
    if os.path.exists(VERIFY_PATH):
        existing = pd.read_csv(VERIFY_PATH)
        combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        combined = new_df

    combined.to_csv(VERIFY_PATH, index=False, encoding="utf-8-sig")
    print(f"검증이력 저장: {VERIFY_PATH}")
    print(f"금일 기록: {len(records)}개 전략")
    print(f"총 누적 이력: {len(combined)}행")

    # 요약 출력
    print(f"\n{'전략명':<55} {'발생횟수':>6} {'승률(%)':>8} {'평균수익률(%)':>10}")
    print("-" * 85)
    for _, row in new_df.iterrows():
        print(f"{row['전략명']:<55} {row['발생횟수']:>6} {row['승률(%)']:>8.2f} {row['평균수익률(%)']:>10.2f}")

    return combined


if __name__ == "__main__":
    run_daily_verification()
