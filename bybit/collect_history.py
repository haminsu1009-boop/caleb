"""
bybit/collect_history.py
Binance 공개 아카이브에서 BTC 5분봉 전체 히스토리 수집
(API 키 불필요 — 완전 무료 공개 데이터)

데이터 출처: https://data.binance.vision
- BTCUSDT 현물 5분봉
- 2019년 9월 ~ 현재 (Binance BTCUSDT 상장 시점부터)

사용법:
    python bybit/collect_history.py
    python bybit/collect_history.py --interval 1m   # 1분봉
    python bybit/collect_history.py --interval 15m  # 15분봉
"""

import os, sys, io, zipfile, argparse, time
import requests
import pandas as pd
from datetime import date, datetime

# Binance 공개 데이터 아카이브
BASE_URL = "https://data.binance.vision/data/spot/monthly/klines"
SYMBOL   = "BTCUSDT"
SAVE_DIR = "data"


def download_month(year: int, month: int, interval: str = "5m") -> pd.DataFrame | None:
    """월별 kline zip 다운로드 후 DataFrame 반환"""
    url = f"{BASE_URL}/{SYMBOL}/{interval}/{SYMBOL}-{interval}-{year}-{month:02d}.zip"
    try:
        r = requests.get(url, timeout=60)
        if r.status_code == 404:
            return None   # 해당 월 데이터 없음
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"    ⚠️  네트워크 오류: {e}")
        return None

    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        csv_name = z.namelist()[0]
        df = pd.read_csv(
            z.open(csv_name),
            header=None,
            names=[
                "open_time","open","high","low","close","volume",
                "close_time","quote_volume","trades",
                "taker_buy_base","taker_buy_quote","ignore"
            ],
        )

    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms")
    df = df[["timestamp","open","high","low","close","volume","quote_volume"]].copy()
    for c in ["open","high","low","close","volume","quote_volume"]:
        df[c] = df[c].astype(float)

    return df.reset_index(drop=True)


def collect_all(interval: str = "5m", start_year: int = 2017) -> None:
    """2017(가능한 최초)부터 현재까지 전체 수집 → 연도별 gzip CSV 저장"""
    os.makedirs(SAVE_DIR, exist_ok=True)

    today      = date.today()
    end_year   = today.year
    end_month  = today.month - 1   # 이번 달은 아직 완성 안됨
    if end_month == 0:
        end_month  = 12
        end_year  -= 1

    print(f"{'='*56}")
    print(f"📥 BTC {interval} 전체 히스토리 수집 시작")
    print(f"   대상: {SYMBOL} / Binance 공개 아카이브")
    print(f"   기간: {start_year}.01 ~ {end_year}.{end_month:02d}")
    print(f"{'='*56}\n")

    for year in range(start_year, end_year + 1):
        year_frames = []
        months_ok   = 0

        for month in range(1, 13):
            if year == end_year and month > end_month:
                break

            print(f"  {year}-{month:02d} ... ", end="", flush=True)
            df = download_month(year, month, interval)

            if df is None or df.empty:
                print("데이터 없음 (건너뜀)")
                continue

            year_frames.append(df)
            months_ok += 1
            print(f"{len(df):,}개 ✓")
            time.sleep(0.05)   # 서버 부하 최소화

        if not year_frames:
            print(f"  → {year}년 데이터 없음\n")
            continue

        year_df = pd.concat(year_frames).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
        fname   = f"{SAVE_DIR}/BTCUSDT_{interval}_{year}.csv.gz"
        year_df.to_csv(fname, index=False, compression="gzip")
        size_kb = os.path.getsize(fname) // 1024
        print(f"\n  ✅ {year}년 저장 → {fname}  ({len(year_df):,}개, {size_kb}KB)\n")

    # 전체 합치기
    print("\n📦 전체 파일 합치는 중...")
    all_files = sorted([
        f for f in os.listdir(SAVE_DIR)
        if f.startswith(f"BTCUSDT_{interval}_") and f.endswith(".csv.gz")
    ])
    if all_files:
        all_dfs = [pd.read_csv(f"{SAVE_DIR}/{f}", compression="gzip") for f in all_files]
        total   = pd.concat(all_dfs).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
        out     = f"{SAVE_DIR}/BTCUSDT_{interval}_all.csv.gz"
        total.to_csv(out, index=False, compression="gzip")
        size_mb = os.path.getsize(out) / 1024 / 1024
        print(f"✅ 전체 합산: {out}  ({len(total):,}개 캔들, {size_mb:.1f}MB)")
        print(f"   기간: {total['timestamp'].iloc[0]} ~ {total['timestamp'].iloc[-1]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval",   default="5m", help="1m/3m/5m/15m/1h")
    parser.add_argument("--start_year", type=int, default=2017)
    args = parser.parse_args()

    collect_all(interval=args.interval, start_year=args.start_year)
