"""
bybit/collect_history.py
Binance 공개 아카이브에서 OHLCV 전체 히스토리 수집
(API 키 불필요 — 완전 무료 공개 데이터)

사용법:
    python bybit/collect_history.py                          # BTC 전봉
    python bybit/collect_history.py --symbol ETHUSDT         # ETH 전봉
    python bybit/collect_history.py --interval 5m            # 5분봉만
    python bybit/collect_history.py --symbol ETHUSDT --interval 1h 4h 1d
"""

import os, io, zipfile, argparse, time
import requests
import pandas as pd
from datetime import date

BASE_URL = "https://data.binance.vision/data/spot/monthly/klines"
SAVE_DIR = "data"

INTERVAL_NAMES = {
    "1m":"1분봉","5m":"5분봉","15m":"15분봉","30m":"30분봉",
    "1h":"1시간봉","2h":"2시간봉","4h":"4시간봉","6h":"6시간봉",
    "12h":"12시간봉","1d":"일봉","3d":"3일봉","1w":"주봉","1mo":"월봉",
}

# BTC: 전체 9봉 / ETH: 주요 5봉
BTC_INTERVALS = ["1mo","1w","1d","6h","4h","1h","30m","5m","1m"]
ETH_INTERVALS = ["1d","4h","1h","5m","1m"]


def download_month(year:int, month:int, interval:str="5m",
                   symbol:str="BTCUSDT", retries:int=3) -> pd.DataFrame | None:
    url = (f"{BASE_URL}/{symbol}/{interval}/"
           f"{symbol}-{interval}-{year}-{month:02d}.zip")
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=90)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt == retries - 1:
                print(f" ⚠️  {e}"); return None
            time.sleep(2 ** attempt)

    try:
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            df = pd.read_csv(z.open(z.namelist()[0]), header=None,
                names=["open_time","open","high","low","close","volume",
                       "close_time","quote_volume","trades",
                       "taker_buy_base","taker_buy_quote","ignore"])
    except Exception as e:
        print(f" ⚠️  파싱 오류: {e}"); return None

    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms")
    df = df[["timestamp","open","high","low","close","volume","quote_volume"]].copy()
    for c in ["open","high","low","close","volume","quote_volume"]:
        df[c] = df[c].astype(float)
    return df.sort_values("timestamp").reset_index(drop=True)


def collect_interval(interval:str="5m", start_year:int=2017,
                     symbol:str="BTCUSDT") -> str | None:
    os.makedirs(SAVE_DIR, exist_ok=True)
    today = date.today()
    end_year, end_month = today.year, today.month - 1
    if end_month == 0:
        end_year -= 1; end_month = 12

    name = INTERVAL_NAMES.get(interval, interval)
    print(f"\n{'━'*52}")
    print(f"  {symbol}  {name} ({interval})  {start_year}~{end_year}")
    print(f"{'━'*52}")

    year_files = []
    for year in range(start_year, end_year + 1):
        year_out = f"{SAVE_DIR}/{symbol}_{interval}_{year}.csv.gz"
        if os.path.exists(year_out):
            print(f"  {year}: 이미 존재, 건너뜀")
            year_files.append(year_out); continue

        frames = []
        for month in range(1, 13):
            if year == end_year and month > end_month: break
            print(f"  {year}-{month:02d} ... ", end="", flush=True)
            df = download_month(year, month, interval, symbol)
            if df is None or df.empty:
                print("없음"); continue
            frames.append(df)
            print(f"{len(df):,}개 ✓")
            time.sleep(0.05)

        if not frames:
            print(f"  → {year}년 데이터 없음"); continue

        ydf = (pd.concat(frames).drop_duplicates("timestamp")
                 .sort_values("timestamp").reset_index(drop=True))
        ydf.to_csv(year_out, index=False, compression="gzip")
        kb = os.path.getsize(year_out) // 1024
        print(f"  ✅ {year} → {year_out} ({len(ydf):,}개, {kb}KB)")
        year_files.append(year_out)

    if not year_files: return None

    all_out = f"{SAVE_DIR}/{symbol}_{interval}_all.csv.gz"
    all_dfs = [pd.read_csv(f, compression="gzip") for f in sorted(year_files)]
    total = (pd.concat(all_dfs).drop_duplicates("timestamp")
               .sort_values("timestamp").reset_index(drop=True))
    total.to_csv(all_out, index=False, compression="gzip")
    mb = os.path.getsize(all_out) / 1024 / 1024
    print(f"\n  📦 {all_out}  ({len(total):,}개 · {mb:.1f}MB)")
    print(f"     {total['timestamp'].iloc[0]} ~ {total['timestamp'].iloc[-1]}")
    return all_out


def collect_all(symbol:str="BTCUSDT", intervals:list=None,
                start_year:int=2017) -> None:
    if intervals is None:
        intervals = BTC_INTERVALS if symbol == "BTCUSDT" else ETH_INTERVALS

    print(f"\n{'='*52}")
    print(f"  📥 {symbol} 히스토리 수집")
    print(f"  봉 단위: {', '.join(intervals)}")
    print(f"{'='*52}")

    results = {}
    for iv in intervals:
        results[iv] = collect_interval(iv, start_year, symbol)

    print(f"\n\n{'='*52}  완료 요약")
    total_mb = 0
    for iv, path in results.items():
        name = INTERVAL_NAMES.get(iv, iv)
        if path and os.path.exists(path):
            mb = os.path.getsize(path) / 1024 / 1024
            total_mb += mb
            print(f"  {name:>6} ({iv:>3})  ✅  {mb:.1f}MB")
        else:
            print(f"  {name:>6} ({iv:>3})  ❌  없음")
    print(f"  {'합계':>10}       {total_mb:.1f}MB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol",     default="BTCUSDT")
    parser.add_argument("--interval",   nargs="*", default=None)
    parser.add_argument("--start_year", type=int,  default=2017)
    args = parser.parse_args()
    collect_all(symbol=args.symbol, intervals=args.interval,
                start_year=args.start_year)
