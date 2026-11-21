"""
ml/fetch_futures_data.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Bybit Futures 공개 API에서 추가 데이터 수집 (API 키 불필요)

수집 항목:
  1. Funding Rate (8시간 단위) — api.bybit.com/v5/market/funding/history
  2. Open Interest History (1h 단위) — api.bybit.com/v5/market/open-interest
  3. Long/Short Ratio (1h 단위) — api.bybit.com/v5/market/account-ratio

저장 위치: data/futures/{symbol}_funding.csv.gz
                         {symbol}_oi_1h.csv.gz
                         {symbol}_lsr_1h.csv.gz

사용법:
    python ml/fetch_futures_data.py
    python ml/fetch_futures_data.py --symbol BTCUSDT --from_year 2021
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os, sys, time, argparse, requests
import pandas as pd
import numpy as np

ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data", "futures")
os.makedirs(DATA_DIR, exist_ok=True)

SYMBOLS  = ["BTCUSDT","ETHUSDT","BNBUSDT","ADAUSDT","SOLUSDT","XRPUSDT"]
BASE_URL = "https://api.bybit.com"

def _ms(dt_str: str) -> int:
    return int(pd.Timestamp(dt_str).timestamp() * 1000)

def _get(url, params, retries=5):
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=20)
            r.raise_for_status()
            data = r.json()
            if data.get("retCode", 0) != 0:
                raise ValueError(f"Bybit API 오류: {data.get('retMsg')}")
            return data["result"]["list"]
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(2 ** i)

# ──────────────────────────────────────────────
# 1. Funding Rate
# ──────────────────────────────────────────────
def fetch_funding(symbol: str, from_year: int = 2021) -> pd.DataFrame:
    """Bybit 펀딩비 전체 히스토리 수집"""
    url   = f"{BASE_URL}/v5/market/funding/history"
    start = _ms(f"{from_year}-01-01")
    end   = int(pd.Timestamp.utcnow().timestamp() * 1000)
    rows  = []
    limit = 200

    while start < end:
        batch_end = min(start + limit * 8 * 3600 * 1000, end)
        try:
            data = _get(url, {
                "category": "linear",
                "symbol":   symbol,
                "startTime": start,
                "endTime":   batch_end,
                "limit":     limit,
            })
        except Exception as e:
            print(f"    ⚠️ 펀딩비 배치 실패: {e}")
            break
        if not data:
            start = batch_end + 1
            continue
        rows.extend(data)
        last_t = int(data[0]["fundingRateTimestamp"])  # Bybit은 역순 반환
        if len(data) < limit:
            start = batch_end + 1
        else:
            # 마지막 항목(가장 오래된 것)의 다음 시점으로
            oldest_t = int(data[-1]["fundingRateTimestamp"])
            start = oldest_t + 1
        time.sleep(0.2)

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["datetime"]    = pd.to_datetime(df["fundingRateTimestamp"].astype("int64"), unit="ms")
    df["fundingRate"] = df["fundingRate"].astype(float)
    df = df[["datetime","fundingRate"]].drop_duplicates("datetime").sort_values("datetime")
    return df.reset_index(drop=True)


# ──────────────────────────────────────────────
# 2. Open Interest History (1h)
# ──────────────────────────────────────────────
def fetch_oi(symbol: str, interval: str = "1h", from_year: int = 2021) -> pd.DataFrame:
    """Bybit 오픈인터레스트 히스토리"""
    url   = f"{BASE_URL}/v5/market/open-interest"
    start = _ms(f"{from_year}-01-01")
    end   = int(pd.Timestamp.utcnow().timestamp() * 1000)
    rows  = []
    limit = 200
    step  = limit * 3600 * 1000  # 1h 기준 200개 = 200시간

    while start < end:
        batch_end = min(start + step, end)
        try:
            data = _get(url, {
                "category":    "linear",
                "symbol":      symbol,
                "intervalTime": interval,
                "startTime":   start,
                "endTime":     batch_end,
                "limit":       limit,
            })
        except Exception as e:
            print(f"    ⚠️ OI 배치 실패: {e}")
            start = batch_end + 1
            continue
        if not data:
            start = batch_end + 1
            continue
        rows.extend(data)
        start = batch_end + 1
        time.sleep(0.3)

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms")
    df["oi"]       = df["openInterest"].astype(float)
    df = df[["datetime","oi"]].drop_duplicates("datetime").sort_values("datetime")
    return df.reset_index(drop=True)


# ──────────────────────────────────────────────
# 3. Long/Short Ratio (1h)
# ──────────────────────────────────────────────
def fetch_lsr(symbol: str, from_year: int = 2021) -> pd.DataFrame:
    """Bybit 롱숏 비율 — 최대 500개 (약 20일치 1h, 또는 60일치 4h)"""
    url  = f"{BASE_URL}/v5/market/account-ratio"
    rows = []

    for period in ["1h", "4h"]:
        try:
            data = _get(url, {
                "category": "linear",
                "symbol":   symbol,
                "period":   period,
                "limit":    500,
            })
            if data:
                for row in data:
                    rows.append({
                        "timestamp": int(row["timestamp"]),
                        "lsr":       float(row["buyRatio"]) / float(row["sellRatio"]) if float(row["sellRatio"]) > 0 else None,
                        "buy_ratio": float(row["buyRatio"]),
                        "sell_ratio": float(row["sellRatio"]),
                        "period":    period,
                    })
        except Exception as e:
            print(f"    ⚠️ LSR {period} 실패: {e}")
        time.sleep(0.2)

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms")
    df = df[["datetime","lsr","buy_ratio","sell_ratio","period"]].drop_duplicates(["datetime","period"]).sort_values("datetime")
    # 1h만 저장
    df1h = df[df["period"]=="1h"].drop(columns=["period"]).reset_index(drop=True)
    return df1h


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
        print(f"  {sym}  (Bybit API)")
        print(f"{'='*50}")

        # 펀딩비
        try:
            print("  펀딩비 수집 중...")
            df = fetch_funding(sym, from_year=args.from_year)
            if not df.empty:
                path = os.path.join(DATA_DIR, f"{sym}_funding.csv.gz")
                df.to_csv(path, index=False, compression="gzip")
                print(f"  ✅ 펀딩비: {len(df):,}건 ({df['datetime'].min().date()} ~ {df['datetime'].max().date()})")
            else:
                print(f"  ⚠️ 펀딩비: 데이터 없음")
        except Exception as e:
            print(f"  ⚠️ 펀딩비 실패: {e}")

        # OI 1h
        try:
            print("  OI 수집 중...")
            df = fetch_oi(sym, interval="1h", from_year=args.from_year)
            if not df.empty:
                path = os.path.join(DATA_DIR, f"{sym}_oi_1h.csv.gz")
                df.to_csv(path, index=False, compression="gzip")
                print(f"  ✅ OI 1h: {len(df):,}건 ({df['datetime'].min().date()} ~ {df['datetime'].max().date()})")
            else:
                print(f"  ⚠️ OI: 데이터 없음")
        except Exception as e:
            print(f"  ⚠️ OI 실패: {e}")

        # LSR 1h
        try:
            print("  롱숏 비율 수집 중...")
            df = fetch_lsr(sym, from_year=args.from_year)
            if not df.empty:
                path = os.path.join(DATA_DIR, f"{sym}_lsr_1h.csv.gz")
                df.to_csv(path, index=False, compression="gzip")
                print(f"  ✅ LSR 1h: {len(df):,}건 ({df['datetime'].min().date()} ~ {df['datetime'].max().date()})")
            else:
                print(f"  ⚠️ LSR: 데이터 없음")
        except Exception as e:
            print(f"  ⚠️ LSR 실패: {e}")

    print("\n✅ Bybit 선물 데이터 수집 완료")


if __name__ == "__main__":
    main()
