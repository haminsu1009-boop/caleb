"""
BTC/USDT 일봉 데이터 수집 (Binance Public API)
2017-01-01 ~ 현재까지
"""

import requests
import pandas as pd
import time
import os
from datetime import datetime

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
SYMBOL = "BTCUSDT"
INTERVAL = "1d"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "btc_daily.csv")


def fetch_klines(symbol, interval, start_ms, end_ms=None, limit=1000):
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": start_ms,
        "limit": limit,
    }
    if end_ms:
        params["endTime"] = end_ms

    for attempt in range(5):
        try:
            resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"  요청 실패 (시도 {attempt+1}/5): {e}")
            time.sleep(2 ** attempt)
    return []


def collect_all():
    start_date = datetime(2017, 1, 1)
    start_ms = int(start_date.timestamp() * 1000)
    now_ms = int(datetime.utcnow().timestamp() * 1000)

    all_rows = []
    current_ms = start_ms

    print(f"BTC/USDT 일봉 수집 시작: {start_date.strftime('%Y-%m-%d')} ~ 현재")

    while current_ms < now_ms:
        data = fetch_klines(SYMBOL, INTERVAL, current_ms, now_ms)
        if not data:
            break

        for row in data:
            all_rows.append({
                "open_time": int(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "close_time": int(row[6]),
                "quote_volume": float(row[7]),
                "trades": int(row[8]),
            })

        last_close_time = data[-1][6]
        current_ms = last_close_time + 1

        dt = datetime.utcfromtimestamp(last_close_time / 1000)
        print(f"  수집 완료: ~{dt.strftime('%Y-%m-%d')} ({len(all_rows)}개 캔들)")

        time.sleep(0.3)

    df = pd.DataFrame(all_rows)
    df["date"] = pd.to_datetime(df["open_time"], unit="ms").dt.strftime("%Y-%m-%d")
    df = df.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)
    print(f"\n저장 완료: {OUTPUT_PATH}")
    print(f"총 {len(df)}개 일봉 데이터 ({df['date'].iloc[0]} ~ {df['date'].iloc[-1]})")
    return df


if __name__ == "__main__":
    collect_all()
