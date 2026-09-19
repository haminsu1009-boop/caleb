"""
collect_data.py
BTC/USDT 일봉 데이터 수집 (2017-01-01 ~ 현재)
출처: Binance Public REST API (API 키 불필요)
저장: data/btc_daily.csv
"""

import os
import time
import requests
import pandas as pd
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT_FILE = os.path.join(DATA_DIR, "btc_daily.csv")

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
SYMBOL = "BTCUSDT"
INTERVAL = "1d"
START_DATE = "2017-08-17"   # Binance 최초 BTC 상장일
MAX_LIMIT = 1000            # Binance 최대 반환 개수


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> list:
    """Binance에서 캔들 데이터 페이지 단위로 수집"""
    all_rows = []
    current_start = start_ms

    while current_start < end_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": current_start,
            "endTime": end_ms,
            "limit": MAX_LIMIT,
        }
        for attempt in range(5):
            try:
                resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=15)
                resp.raise_for_status()
                rows = resp.json()
                break
            except Exception as e:
                wait = 2 ** attempt
                print(f"  [재시도 {attempt+1}/5] 오류: {e}  ({wait}s 대기)")
                time.sleep(wait)
        else:
            print("  [실패] 데이터 수집 중단")
            break

        if not rows:
            break

        all_rows.extend(rows)
        last_open_time = rows[-1][0]
        current_start = last_open_time + 1  # 다음 캔들부터

        fetched_date = datetime.fromtimestamp(last_open_time / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        print(f"  수집 중... 마지막 날짜: {fetched_date}  (누적: {len(all_rows)}개)")

        if len(rows) < MAX_LIMIT:
            break

        time.sleep(0.3)  # Rate limit 방지

    return all_rows


def klines_to_dataframe(rows: list) -> pd.DataFrame:
    columns = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore",
    ]
    df = pd.DataFrame(rows, columns=columns)
    df["date"] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
        df[col] = pd.to_numeric(df[col])
    df["trades"] = pd.to_numeric(df["trades"])
    df = df[["date", "open", "high", "low", "close", "volume", "quote_volume", "trades"]].copy()
    df = df.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    return df


def load_existing() -> pd.DataFrame:
    if os.path.exists(OUTPUT_FILE):
        df = pd.read_csv(OUTPUT_FILE, parse_dates=["date"])
        df["date"] = df["date"].dt.strftime("%Y-%m-%d")
        return df
    return pd.DataFrame()


def collect():
    os.makedirs(DATA_DIR, exist_ok=True)

    existing = load_existing()
    if existing.empty:
        start_str = START_DATE
        print(f"[신규 수집] {start_str} ~ 현재")
    else:
        last_date = existing["date"].max()
        # 마지막 날짜 이후부터 다시 수집 (당일 데이터 갱신 포함)
        start_str = last_date
        print(f"[증분 수집] {last_date} 이후 데이터 갱신")

    start_dt = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt = datetime.now(tz=timezone.utc)

    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    print(f"Binance API 수집 시작: {start_str} → {end_dt.strftime('%Y-%m-%d')}")
    rows = fetch_klines(SYMBOL, INTERVAL, start_ms, end_ms)

    if not rows:
        print("[경고] 수집된 데이터 없음")
        return existing

    new_df = klines_to_dataframe(rows)

    if not existing.empty:
        # 기존 데이터에서 start_str 이전 날짜만 유지, 이후는 새 데이터로 교체
        existing_trimmed = existing[existing["date"] < start_str]
        df = pd.concat([existing_trimmed, new_df], ignore_index=True)
        df = df.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    else:
        df = new_df

    df.to_csv(OUTPUT_FILE, index=False)
    print(f"\n[완료] 총 {len(df)}개 일봉 저장 → {OUTPUT_FILE}")
    print(f"  기간: {df['date'].min()} ~ {df['date'].max()}")
    return df


if __name__ == "__main__":
    collect()
