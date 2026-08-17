"""
bybit/collect_history.py
Binance 공개 아카이브에서 BTC 전체 히스토리 수집
(API 키 불필요 — 완전 무료 공개 데이터)

지원 봉:
    1m 5m 15m 30m 1h 2h 4h 6h 12h 1d 3d 1w 1mo

사용법:
    python bybit/collect_history.py                  # 모든 봉 수집
    python bybit/collect_history.py --interval 5m    # 특정 봉만
    python bybit/collect_history.py --interval 1m --start_year 2020
"""

import os, sys, io, zipfile, argparse, time
import requests
import pandas as pd
from datetime import date

BASE_URL = "https://data.binance.vision/data/spot/monthly/klines"
SYMBOL   = "BTCUSDT"
SAVE_DIR = "data"

# Binance 봉 단위 → 한국어 이름
INTERVAL_NAMES = {
    "1m":  "1분봉",
    "5m":  "5분봉",
    "15m": "15분봉",
    "30m": "30분봉",
    "1h":  "1시간봉",
    "2h":  "2시간봉",
    "4h":  "4시간봉",
    "6h":  "6시간봉",
    "12h": "12시간봉",
    "1d":  "일봉",
    "3d":  "3일봉",
    "1w":  "주봉",
    "1mo": "월봉",
}

# 수집할 기본 봉 목록 (작은 것 → 큰 것 순)
DEFAULT_INTERVALS = ["1mo", "1w", "1d", "6h", "4h", "1h", "30m", "5m", "1m"]


def download_month(
    year:     int,
    month:    int,
    interval: str = "5m",
    retries:  int = 3,
) -> pd.DataFrame | None:
    """월별 kline zip 다운로드 → DataFrame 반환"""
    url = (f"{BASE_URL}/{SYMBOL}/{interval}/"
           f"{SYMBOL}-{interval}-{year}-{month:02d}.zip")

    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=90)
            if r.status_code == 404:
                return None      # 해당 월 데이터 없음 (정상)
            r.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt == retries - 1:
                print(f" ⚠️  실패: {e}")
                return None
            time.sleep(2 ** attempt)

    try:
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            df = pd.read_csv(
                z.open(z.namelist()[0]),
                header=None,
                names=[
                    "open_time","open","high","low","close","volume",
                    "close_time","quote_volume","trades",
                    "taker_buy_base","taker_buy_quote","ignore"
                ],
            )
    except Exception as e:
        print(f" ⚠️  파싱 오류: {e}")
        return None

    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms")
    df = df[["timestamp","open","high","low","close","volume","quote_volume"]].copy()
    for c in ["open","high","low","close","volume","quote_volume"]:
        df[c] = df[c].astype(float)

    return df.sort_values("timestamp").reset_index(drop=True)


def collect_interval(
    interval:   str = "5m",
    start_year: int = 2017,
) -> str | None:
    """
    단일 봉 단위 전체 수집 → 연도별 gzip + 전체 합산 gzip 저장
    Returns: 저장된 전체 파일 경로 (없으면 None)
    """
    os.makedirs(SAVE_DIR, exist_ok=True)

    today     = date.today()
    end_year  = today.year
    end_month = today.month - 1
    if end_month == 0:
        end_month = 12
        end_year -= 1

    name = INTERVAL_NAMES.get(interval, interval)
    print(f"\n{'━'*52}")
    print(f"  {name} ({interval})  {start_year}.01 ~ {end_year}.{end_month:02d}")
    print(f"{'━'*52}")

    year_files = []

    for year in range(start_year, end_year + 1):
        year_out = f"{SAVE_DIR}/BTCUSDT_{interval}_{year}.csv.gz"

        # 이미 수집된 연도는 건너뜀
        if os.path.exists(year_out):
            print(f"  {year}: 이미 존재, 건너뜀")
            year_files.append(year_out)
            continue

        year_frames = []
        for month in range(1, 13):
            if year == end_year and month > end_month:
                break
            print(f"  {year}-{month:02d} ... ", end="", flush=True)

            df = download_month(year, month, interval)
            if df is None or df.empty:
                print("없음")
                continue

            year_frames.append(df)
            print(f"{len(df):,}개 ✓")
            time.sleep(0.05)

        if not year_frames:
            print(f"  → {year}년 데이터 없음")
            continue

        ydf = (pd.concat(year_frames)
                 .drop_duplicates("timestamp")
                 .sort_values("timestamp")
                 .reset_index(drop=True))
        ydf.to_csv(year_out, index=False, compression="gzip")
        kb = os.path.getsize(year_out) // 1024
        print(f"  ✅ {year}년 → {year_out} ({len(ydf):,}개, {kb}KB)")
        year_files.append(year_out)

    if not year_files:
        return None

    # 전체 합산
    all_out = f"{SAVE_DIR}/BTCUSDT_{interval}_all.csv.gz"
    all_dfs = [pd.read_csv(f, compression="gzip") for f in sorted(year_files)]
    total = (pd.concat(all_dfs)
               .drop_duplicates("timestamp")
               .sort_values("timestamp")
               .reset_index(drop=True))
    total.to_csv(all_out, index=False, compression="gzip")
    mb = os.path.getsize(all_out) / 1024 / 1024
    print(f"\n  📦 전체 합산: {all_out}")
    print(f"     {len(total):,}개 캔들 · {mb:.1f}MB")
    print(f"     {total['timestamp'].iloc[0]} ~ {total['timestamp'].iloc[-1]}")

    return all_out


def collect_all(
    intervals:  list[str] = None,
    start_year: int = 2017,
) -> None:
    """모든 봉 단위 순서대로 수집"""
    if intervals is None:
        intervals = DEFAULT_INTERVALS

    print(f"\n{'='*52}")
    print(f"  📥 BTC 전체 히스토리 수집")
    print(f"  대상: {', '.join(intervals)}")
    print(f"  출처: Binance 공개 아카이브 (무료)")
    print(f"{'='*52}")

    results = {}
    for iv in intervals:
        out = collect_interval(iv, start_year=start_year)
        results[iv] = out

    print(f"\n\n{'='*52}")
    print("  🎉 수집 완료 요약")
    print(f"{'='*52}")
    total_mb = 0
    for iv, path in results.items():
        name = INTERVAL_NAMES.get(iv, iv)
        if path and os.path.exists(path):
            mb = os.path.getsize(path) / 1024 / 1024
            total_mb += mb
            print(f"  {name:>6} ({iv:>3})  ✅  {mb:.1f}MB")
        else:
            print(f"  {name:>6} ({iv:>3})  ❌  데이터 없음")
    print(f"{'─'*52}")
    print(f"  {'합계':>10}       {total_mb:.1f}MB")


# ── CLI ─────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BTC 전체 히스토리 수집")
    parser.add_argument(
        "--interval",
        nargs="*",
        default=None,
        help="수집할 봉 (없으면 전체). 예: --interval 5m 1h 1d"
    )
    parser.add_argument("--start_year", type=int, default=2017)
    args = parser.parse_args()

    intervals = args.interval if args.interval else DEFAULT_INTERVALS
    collect_all(intervals=intervals, start_year=args.start_year)
