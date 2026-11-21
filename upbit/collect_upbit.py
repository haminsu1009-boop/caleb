"""
upbit/collect_upbit.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
업비트 공개 API로 KRW 마켓 캔들 수집 (API 키 불필요)

업비트 공식 문서: https://docs.upbit.com/reference/시세-캔들-조회
    /v1/candles/days            일봉
    /v1/candles/minutes/{unit}  분봉 (1/3/5/10/15/30/60/240)

⚠️ 이 세션의 프록시는 api.upbit.com을 막는다(바이낸스·야후파이낸스와 동일 증상).
   GitHub Actions 러너에서는 정상 동작하므로 수집은 워크플로로만 돌린다.

페이징: count 최대 200, to 파라미터로 과거로 이동. rate limit은
초당 10회 정도라 요청 사이 0.15초 대기.

사용법:
    python upbit/collect_upbit.py --market KRW-BTC --unit day
    python upbit/collect_upbit.py --all --unit day
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, time, argparse
from datetime import datetime, timezone

import requests
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAVE_DIR = os.path.join(ROOT, "data", "upbit")
os.makedirs(SAVE_DIR, exist_ok=True)

BASE = "https://api.upbit.com/v1/candles"

# 원화마켓 주요 종목 — 업비트 실제 상장 티커
MARKETS = [
    "KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-ADA",
    "KRW-DOGE", "KRW-AVAX", "KRW-DOT", "KRW-LINK", "KRW-TRX",
    "KRW-MATIC", "KRW-UNI", "KRW-ATOM", "KRW-NEAR", "KRW-ETC",
    "KRW-XLM",   # 참고: BNB는 업비트에 상장돼 있지 않음
    "KRW-SAND", "KRW-MANA", "KRW-SEI", "KRW-INJ",
]

UNIT_ENDPOINT = {
    "day":  f"{BASE}/days",
    "1":    f"{BASE}/minutes/1",
    "5":    f"{BASE}/minutes/5",
    "10":   f"{BASE}/minutes/10",
    "15":   f"{BASE}/minutes/15",
    "30":   f"{BASE}/minutes/30",
    "60":   f"{BASE}/minutes/60",
    "240":  f"{BASE}/minutes/240",
}


def fetch_batch(url: str, market: str, to: str | None, count: int = 200) -> list:
    params = {"market": market, "count": count}
    if to:
        params["to"] = to
    r = requests.get(url, params=params, timeout=15,
                     headers={"Accept": "application/json"})
    if r.status_code == 429:
        time.sleep(2)
        return fetch_batch(url, market, to, count)
    r.raise_for_status()
    return r.json()


def collect(market: str, unit: str = "day", max_batches: int = 100) -> pd.DataFrame:
    url = UNIT_ENDPOINT[unit]
    rows = []
    to = None
    for _ in range(max_batches):
        batch = fetch_batch(url, market, to)
        if not batch:
            break
        rows.extend(batch)
        oldest = batch[-1]["candle_date_time_utc"]
        if to == oldest:
            break
        to = oldest
        time.sleep(0.15)
        if len(batch) < 200:
            break

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    out = pd.DataFrame({
        "datetime": pd.to_datetime(df["candle_date_time_utc"]),
        "open":  df["opening_price"].astype(float),
        "high":  df["high_price"].astype(float),
        "low":   df["low_price"].astype(float),
        "close": df["trade_price"].astype(float),
        "volume": df["candle_acc_trade_volume"].astype(float),
    })
    return out.drop_duplicates("datetime").sort_values("datetime").reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="KRW-BTC")
    ap.add_argument("--markets", nargs="*", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--unit", default="day", choices=list(UNIT_ENDPOINT.keys()))
    ap.add_argument("--max-batches", type=int, default=100)
    a = ap.parse_args()

    targets = a.markets if a.markets else (MARKETS if a.all else [a.market])

    print("=" * 60)
    print(f"  업비트 캔들 수집 — {len(targets)}종목, unit={a.unit}")
    print("=" * 60)

    for m in targets:
        try:
            df = collect(m, a.unit, a.max_batches)
        except Exception as e:
            print(f"  {m}: 실패 — {e}")
            continue
        if df.empty:
            print(f"  {m}: 데이터 없음")
            continue
        path = os.path.join(SAVE_DIR, f"{m}_{a.unit}.csv.gz")
        df.to_csv(path, index=False, compression="gzip")
        print(f"  {m:10s} {len(df):>6,}건  {df['datetime'].iloc[0].date()} ~ {df['datetime'].iloc[-1].date()}")


if __name__ == "__main__":
    main()
