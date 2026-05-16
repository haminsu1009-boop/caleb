"""
퀀트 트레이딩 신호 체크 봇
- 매 1시간마다 최신 데이터를 기반으로 상위 전략 조건을 체크
- 조건 충족 시 signals.log에 기록 (실제 주문 X)
- 실행: python3 signal_bot.py
- 중단: Ctrl+C
"""

import pandas as pd
import numpy as np
import os
import time
import logging
from datetime import datetime

from indicators import add_all_indicators

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
DATA_PATH = os.path.join(BASE_DIR, "data", "btc_daily.csv")
LOG_PATH = os.path.join(BASE_DIR, "signals.log")

CHECK_INTERVAL_SEC = 3600  # 1시간

# 상위 전략 정의 (백테스트 결과 기반)
TOP_STRATEGIES = [
    {
        "name": "MACD>Signal + VolSpike>1.5 + ThreeGreenDays",
        "win_rate": 92.31,
        "avg_return": 3.83,
        "check": lambda df: (
            (df["macd"].iloc[-1] > df["macd_signal"].iloc[-1]) &
            (df["vol_ratio"].iloc[-1] > 1.5) &
            (df["close"].iloc[-1] > df["open"].iloc[-1]) &
            (df["close"].iloc[-2] > df["open"].iloc[-2]) &
            (df["close"].iloc[-3] > df["open"].iloc[-3])
        ),
    },
    {
        "name": "ADX>25 + VolSpike>1.5 + ThreeGreenDays",
        "win_rate": 90.91,
        "avg_return": 3.98,
        "check": lambda df: (
            (df["adx_14"].iloc[-1] > 25) &
            (df["vol_ratio"].iloc[-1] > 1.5) &
            (df["close"].iloc[-1] > df["open"].iloc[-1]) &
            (df["close"].iloc[-2] > df["open"].iloc[-2]) &
            (df["close"].iloc[-3] > df["open"].iloc[-3])
        ),
    },
    {
        "name": "SMA5>SMA20 + VolSpike>1.5 + ThreeGreenDays",
        "win_rate": 90.62,
        "avg_return": 3.41,
        "check": lambda df: (
            (df["sma_5"].iloc[-1] > df["sma_20"].iloc[-1]) &
            (df["vol_ratio"].iloc[-1] > 1.5) &
            (df["close"].iloc[-1] > df["open"].iloc[-1]) &
            (df["close"].iloc[-2] > df["open"].iloc[-2]) &
            (df["close"].iloc[-3] > df["open"].iloc[-3])
        ),
    },
    {
        "name": "MACD_Hist>0 + ADX>20_PlusDI>MinusDI + ThreeGreenDays",
        "win_rate": 87.77,
        "avg_return": 4.18,
        "check": lambda df: (
            (df["macd_hist"].iloc[-1] > 0) &
            (df["adx_14"].iloc[-1] > 20) &
            (df["plus_di"].iloc[-1] > df["minus_di"].iloc[-1]) &
            (df["close"].iloc[-1] > df["open"].iloc[-1]) &
            (df["close"].iloc[-2] > df["open"].iloc[-2]) &
            (df["close"].iloc[-3] > df["open"].iloc[-3])
        ),
    },
    {
        "name": "SMA10>SMA50 + MACD>Signal + ADX>25",
        "win_rate": 87.37,
        "avg_return": 4.06,
        "check": lambda df: (
            (df["sma_10"].iloc[-1] > df["sma_50"].iloc[-1]) &
            (df["macd"].iloc[-1] > df["macd_signal"].iloc[-1]) &
            (df["adx_14"].iloc[-1] > 25)
        ),
    },
    {
        "name": "SMA20>SMA100 + MACD>Signal + ADX>25",
        "win_rate": 86.85,
        "avg_return": 4.47,
        "check": lambda df: (
            (df["sma_20"].iloc[-1] > df["sma_100"].iloc[-1]) &
            (df["macd"].iloc[-1] > df["macd_signal"].iloc[-1]) &
            (df["adx_14"].iloc[-1] > 25)
        ),
    },
]


def setup_logger():
    logger = logging.getLogger("signal_bot")
    logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file_handler.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    fmt = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    file_handler.setFormatter(fmt)
    console_handler.setFormatter(fmt)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


def check_signals(logger):
    """현재 데이터로 모든 전략 조건 체크"""
    try:
        df = pd.read_csv(DATA_PATH)
        df = add_all_indicators(df)

        if len(df) < 200:
            logger.warning("데이터 부족: %d행 (최소 200행 필요)", len(df))
            return

        price = df["close"].iloc[-1]
        date = df["date"].iloc[-1] if "date" in df.columns else "N/A"
        logger.info("=" * 60)
        logger.info("신호 체크 | BTC 가격: $%s | 기준일: %s", f"{price:,.2f}", date)

        triggered = []
        for strategy in TOP_STRATEGIES:
            try:
                if strategy["check"](df):
                    triggered.append(strategy)
                    logger.info(
                        "  [매수 신호] %s | 승률: %.1f%% | 평균수익률: %.2f%%",
                        strategy["name"], strategy["win_rate"], strategy["avg_return"]
                    )
            except Exception as e:
                logger.error("  전략 체크 실패 (%s): %s", strategy["name"], e)

        if not triggered:
            logger.info("  현재 매수 신호 없음")
        else:
            logger.info("  총 %d개 전략 신호 발생 (실제 주문 X)", len(triggered))

        logger.info("=" * 60)

    except Exception as e:
        logger.error("신호 체크 오류: %s", e)


def run_bot():
    logger = setup_logger()
    logger.info("퀀트 트레이딩 신호 봇 시작 (체크 간격: %d초)", CHECK_INTERVAL_SEC)
    logger.info("로그 경로: %s", LOG_PATH)
    logger.info("실제 주문 없음 - 신호 기록만 수행")

    # 즉시 첫 체크 실행
    check_signals(logger)

    # 이후 매 1시간마다 반복
    try:
        while True:
            time.sleep(CHECK_INTERVAL_SEC)
            check_signals(logger)
    except KeyboardInterrupt:
        logger.info("봇 종료 (Ctrl+C)")


if __name__ == "__main__":
    run_bot()
