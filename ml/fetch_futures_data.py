"""
ml/fetch_futures_data.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Binance Futures 공개 API에서 추가 데이터 수집 (API 키 불필요)

수집 항목:
  1. Funding Rate (8시간 단위) — fapi.binance.com
  2. Open Interest History (1h 단위) — fapi.binance.com
  3. Long/Short Ratio (top trader) (1h 단위) — futures.binance.com

저장 위치: data/futures/{symbol}_funding.csv.gz
                         {symbol}_oi_1h.csv.gz
                         {symbol}_lsr_1h.csv.gz

사용법:
    python ml/fetch_futures_data.py
    python ml/fetch_futures_data.py --symbol BTCUSDT --from_year 2022
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os, sys, time, argparse, requests
import pandas as pd
import numpy as np

ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data", "futures")
os.makedirs(DATA_DIR, exist_ok=True)

SYMBOLS  = ["BTCUSDT","ETHUSDT","BNBUSDT","ADAUSDT","SOLUSDT","XRPUSDT"]

FAPI     = "https://fapi.binance.com"
DAPI     = "https://futures.binance.com"

def _ms(dt_str: str) -> int:
    return int(pd.Timestamp(dt_str).timestamp() * 1000)

def _get(url, params, retries=5):
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(2 ** i)

# ──────────────────────────────────────────────
# 1. Funding Rate (8h 간격)
# ──────────────────────────────────────────────
def fetch_funding(symbol: str, from_year: int = 2021) -> pd.DataFrame:
    """펀딩비 전체 히스토리 수집"""
    url    = f"{FAPI}/fapi/v1/fundingRate"
    start  = _ms(f"{from_year}-01-01")
    end    = int(pd.Timestamp.utcnow().timestamp() * 1000)
    rows   = []
    limit  = 1000

    while start < end:
        data = _get(url, {"symbol": symbol, "startTime": start,
                          "limit": limit})
        if not data:
            break
        rows.extend(data)
        last_t = int(data[-1]["fundingTime"])
        if last_t <= start or len(data) < limit:
            break
        start = last_t + 1
        time.sleep(0.2)

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["datetime"]    = pd.to_datetime(df["fundingTime"].astype("int64"), unit="ms")
    df["fundingRate"] = df["fundingRate"].astype(float)
    df["markPrice"]   = df["markPrice"].astype(float)
    df = df[["datetime","fundingRate","markPrice"]].drop_duplicates("datetime").sort_values("datetime")
    return df.reset_index(drop=True)


# ──────────────────────────────────────────────
# 2. Open Interest History (1h)
# ──────────────────────────────────────────────
def fetch_oi(symbol: str, period: str = "1h", from_year: int = 2021) -> pd.DataFrame:
    """오픈인터레스트 히스토리"""
    url    = f"{DAPI}/futures/data/openInterestHist"
    start  = _ms(f"{from_year}-01-01")
    end    = int(pd.Timestamp.utcnow().timestamp() * 1000)
    rows   = []
    limit  = 500

    while start < end:
        data = _get(url, {"symbol": symbol, "period": period,
                          "startTime": start, "limit": limit})
        if not data:
            break
        rows.extend(data)
        last_t = int(data[-1]["timestamp"])
        if last_t <= start or len(data) < limit:
            break
        start = last_t + 1
        time.sleep(0.3)

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["datetime"]           = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms")
    df["oi"]                 = df["sumOpenInterest"].astype(float)
    df["oi_value"]           = df["sumOpenInterestValue"].astype(float)
    df = df[["datetime","oi","oi_value"]].drop_duplicates("datetime").sort_values("datetime")
    return df.reset_index(drop=True)


# ──────────────────────────────────────────────
# 3. Long/Short Ratio (Top Trader, 1h)
# ──────────────────────────────────────────────
def fetch_lsr(symbol: str, period: str = "1h", from_year: int = 2021) -> pd.DataFrame:
    """탑 트레이더 롱숏 비율"""
    url    = f"{DAPI}/futures/data/topLongShortPositionRatio"
    start  = _ms(f"{from_year}-01-01")
    end    = int(pd.Timestamp.utcnow().timestamp() * 1000)
    rows   = []
    limit  = 500

    while start < end:
        data = _get(url, {"symbol": symbol, "period": period,
                          "startTime": start, "limit": limit})
        if not data:
            break
        rows.extend(data)
        last_t = int(data[-1]["timestamp"])
        if last_t <= start or len(data) < limit:
            break
        start = last_t + 1
        time.sleep(0.3)

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["datetime"] = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms")
    df["lsr"]      = df["longShortRatio"].astype(float)
    df["long_pct"] = df["longAccount"].astype(float)
    df = df[["datetime","lsr","long_pct"]].drop_duplicates("datetime").sort_values("datetime")
    return df.reset_index(drop=True)


# ──────────────────────────────────────────────
# main
# ──────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol",    default="ALL")
    ap.add_argument("--from_year", type=int, default=2021)
    args = ap.parse_args()

    syms = SYMBOLS if args.symbol == "ALL" else [args.symbol]

    for sym in syms:
        print(f"\n{'='*50}")
        print(f"  {sym}")
        print(f"{'='*50}")

        # 펀딩비
        try:
            print("  펀딩비 수집 중...")
            df = fetch_funding(sym, from_year=args.from_year)
            if not df.empty:
                path = os.path.join(DATA_DIR, f"{sym}_funding.csv.gz")
                df.to_csv(path, index=False, compression="gzip")
                print(f"  ✅ 펀딩비: {len(df):,}건 → {path}")
        except Exception as e:
            print(f"  ⚠️ 펀딩비 실패: {e}")

        # OI 1h
        try:
            print("  OI 수집 중...")
            df = fetch_oi(sym, period="1h", from_year=args.from_year)
            if not df.empty:
                path = os.path.join(DATA_DIR, f"{sym}_oi_1h.csv.gz")
                df.to_csv(path, index=False, compression="gzip")
                print(f"  ✅ OI 1h: {len(df):,}건 → {path}")
        except Exception as e:
            print(f"  ⚠️ OI 실패: {e}")

        # LSR 1h
        try:
            print("  롱숏 비율 수집 중...")
            df = fetch_lsr(sym, period="1h", from_year=args.from_year)
            if not df.empty:
                path = os.path.join(DATA_DIR, f"{sym}_lsr_1h.csv.gz")
                df.to_csv(path, index=False, compression="gzip")
                print(f"  ✅ LSR 1h: {len(df):,}건 → {path}")
        except Exception as e:
            print(f"  ⚠️ LSR 실패: {e}")

    print("\n✅ 완료")


if __name__ == "__main__":
    main()
