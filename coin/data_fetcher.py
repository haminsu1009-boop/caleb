"""
coin/data_fetcher.py
실시간 멀티코인 데이터 + 공포탐욕지수 수집
"""

import os
import sys
import time
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BINANCE_URL = "https://api.binance.com/api/v3/klines"
FNG_URL     = "https://api.alternative.me/fng/?limit=1"

COINS = os.getenv("COINS", "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT").split(",")


def fetch_klines(symbol: str, interval: str = "1d", limit: int = 300) -> pd.DataFrame:
    """Binance에서 OHLCV 캔들 수신"""
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    for attempt in range(4):
        try:
            r = requests.get(BINANCE_URL, params=params, timeout=15)
            r.raise_for_status()
            rows = r.json()
            break
        except Exception as e:
            if attempt == 3:
                print(f"[오류] {symbol} 데이터 수신 실패: {e}")
                return pd.DataFrame()
            time.sleep(2 ** attempt)

    cols = ["open_time","open","high","low","close","volume",
            "close_time","quote_vol","trades","tb_base","tb_quote","ignore"]
    df = pd.DataFrame(rows, columns=cols)
    df["date"]   = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    df["symbol"] = symbol
    for c in ["open","high","low","close","volume"]:
        df[c] = pd.to_numeric(df[c])
    return df[["date","symbol","open","high","low","close","volume"]].reset_index(drop=True)


def fetch_fear_greed() -> int:
    """공포탐욕지수 (0=극도공포 ~ 100=극도탐욕)"""
    try:
        r = requests.get(FNG_URL, timeout=10)
        r.raise_for_status()
        val = int(r.json()["data"][0]["value"])
        return val
    except Exception:
        return 50  # 기본값: 중립


def fetch_all_coins(interval: str = "1d", limit: int = 300) -> dict[str, pd.DataFrame]:
    """모든 코인 데이터 수집"""
    result = {}
    for symbol in COINS:
        df = fetch_klines(symbol, interval, limit)
        if not df.empty:
            result[symbol] = df
        time.sleep(0.2)
    return result


def save_coin_data(symbol: str, df: pd.DataFrame):
    """data/{symbol}_daily.csv 저장"""
    data_dir = os.path.join(ROOT, "data")
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, f"{symbol}_daily.csv")

    if os.path.exists(path):
        existing = pd.read_csv(path)
        df = pd.concat([existing, df]).drop_duplicates("date").sort_values("date")

    df.to_csv(path, index=False)
    return path


def get_latest_features(symbol: str) -> pd.DataFrame | None:
    """ML 예측용 최신 피처 데이터 반환"""
    from ml.features import add_features

    # 실시간 데이터 우선, 없으면 저장된 데이터 사용
    df = fetch_klines(symbol, "1d", 300)

    if df.empty:
        path = os.path.join(ROOT, "data", f"{symbol}_daily.csv")
        fallback = os.path.join(ROOT, "data", "btc_daily.csv")
        target = path if os.path.exists(path) else fallback
        if not os.path.exists(target):
            return None
        df = pd.read_csv(target)

    fng = fetch_fear_greed()
    df  = add_features(df)
    df["fear_greed"] = fng / 100.0   # 0~1 정규화

    return df


if __name__ == "__main__":
    print("공포탐욕지수:", fetch_fear_greed())
    for symbol in ["BTCUSDT"]:
        df = fetch_klines(symbol)
        if not df.empty:
            print(f"{symbol}: {len(df)}개  최근가=${df['close'].iloc[-1]:,.2f}")
