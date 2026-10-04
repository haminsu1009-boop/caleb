"""
generate_sample_data.py
네트워크 접근 불가 환경에서 실행 가능한
실제 BTC 가격 흐름을 반영한 합성 일봉 데이터 생성기

주요 이벤트 반영:
  2017-08 ~ 2017-12: 1차 불장 ($4k → $20k)
  2018-01 ~ 2018-12: 1차 하락 ($20k → $3k)
  2019-01 ~ 2019-12: 횡보/소폭 반등 ($3k → $7k)
  2020-01 ~ 2020-12: 코로나 급락 후 2차 불장 ($7k → $29k)
  2021-01 ~ 2021-04: 고점 ($64k)
  2021-05 ~ 2021-07: 급락 ($30k)
  2021-08 ~ 2021-11: 2차 고점 ($69k)
  2022-01 ~ 2022-11: 하락장 ($69k → $16k)
  2023-01 ~ 2023-12: 회복 ($16k → $44k)
  2024-01 ~ 2024-12: ETF 승인 + 4차 반감기 ($44k → $100k)
  2025-01 ~ 2026-04: 상승/조정 ($100k 전후)
"""

import os
import numpy as np
import pandas as pd
from datetime import date, timedelta

SEED = 42
np.random.seed(SEED)

ROOT      = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(ROOT, "data")
OUT_FILE  = os.path.join(DATA_DIR, "btc_daily.csv")

# ── 주요 구간 정의 (날짜, 목표가격, 변동성) ────────────
SEGMENTS = [
    # (start, end, start_price, end_price, daily_vol)
    ("2017-08-17", "2017-11-30", 4_000,   10_000,  0.060),
    ("2017-12-01", "2017-12-17", 10_000,  20_000,  0.080),
    ("2017-12-18", "2018-02-05", 20_000,   8_000,  0.075),
    ("2018-02-06", "2018-06-30",  8_000,   6_000,  0.055),
    ("2018-07-01", "2018-11-14",  6_000,   6_200,  0.045),
    ("2018-11-15", "2018-12-31",  6_200,   3_200,  0.065),
    ("2019-01-01", "2019-04-01",  3_200,   4_100,  0.040),
    ("2019-04-02", "2019-06-26",  4_100,  13_800,  0.065),
    ("2019-06-27", "2019-12-31", 13_800,   7_200,  0.050),
    ("2020-01-01", "2020-03-12",  7_200,   4_100,  0.045),
    ("2020-03-13", "2020-03-13",  4_100,   3_800,  0.200),  # 코로나 블랙스완
    ("2020-03-14", "2020-07-31",  3_800,   9_200,  0.040),
    ("2020-08-01", "2020-12-31",  9_200,  29_000,  0.055),
    ("2021-01-01", "2021-04-14", 29_000,  64_000,  0.060),
    ("2021-04-15", "2021-07-20", 64_000,  29_000,  0.065),
    ("2021-07-21", "2021-11-10", 29_000,  67_500,  0.055),
    ("2021-11-11", "2022-01-23", 67_500,  34_000,  0.060),
    ("2022-01-24", "2022-05-09", 34_000,  35_500,  0.045),
    ("2022-05-10", "2022-06-18", 35_500,  17_500,  0.080),  # LUNA 붕괴
    ("2022-06-19", "2022-11-07", 17_500,  20_800,  0.045),
    ("2022-11-08", "2022-11-14", 20_800,  15_700,  0.090),  # FTX 붕괴
    ("2022-11-15", "2022-12-31", 15_700,  16_500,  0.045),
    ("2023-01-01", "2023-03-31", 16_500,  28_000,  0.040),
    ("2023-04-01", "2023-06-30", 28_000,  30_500,  0.040),
    ("2023-07-01", "2023-10-22", 30_500,  29_000,  0.035),
    ("2023-10-23", "2023-12-31", 29_000,  42_000,  0.045),
    ("2024-01-01", "2024-03-10", 42_000,  72_000,  0.050),  # ETF 승인
    ("2024-03-11", "2024-04-19", 72_000,  64_000,  0.055),
    ("2024-04-20", "2024-07-31", 64_000,  65_000,  0.045),  # 4차 반감기
    ("2024-08-01", "2024-10-31", 65_000,  70_000,  0.040),
    ("2024-11-01", "2024-12-17", 70_000, 106_000,  0.055),  # 트럼프 당선
    ("2024-12-18", "2024-12-31",106_000,  93_000,  0.060),
    ("2025-01-01", "2025-03-31", 93_000, 110_000,  0.045),
    ("2025-04-01", "2025-06-30",110_000,  85_000,  0.050),
    ("2025-07-01", "2025-09-30", 85_000,  95_000,  0.040),
    ("2025-10-01", "2025-12-31", 95_000, 120_000,  0.045),
    ("2026-01-01", "2026-04-08",120_000, 105_000,  0.050),
]


def generate_segment(start_date: str, end_date: str,
                     p_start: float, p_end: float,
                     daily_vol: float) -> pd.DataFrame:
    d0 = date.fromisoformat(start_date)
    d1 = date.fromisoformat(end_date)
    days = (d1 - d0).days + 1
    if days <= 0:
        return pd.DataFrame()

    # 로그 가격의 선형 drift 계산
    log_drift = (np.log(p_end) - np.log(p_start)) / days

    prices = [p_start]
    for _ in range(days - 1):
        shock = np.random.normal(log_drift, daily_vol)
        # 가끔 지방 꼬리 (fat tail) 이벤트
        if np.random.random() < 0.02:
            shock *= np.random.choice([-2.5, 2.5])
        prices.append(prices[-1] * np.exp(shock))

    # OHLCV 생성
    rows = []
    for i, (close, d) in enumerate(zip(prices, [d0 + timedelta(days=j) for j in range(days)])):
        open_  = prices[i-1] if i > 0 else close * np.exp(np.random.normal(0, daily_vol*0.3))
        high_  = close * np.exp(abs(np.random.normal(0, daily_vol * 0.6)))
        low_   = close * np.exp(-abs(np.random.normal(0, daily_vol * 0.6)))
        # 고가/저가 보정
        high_ = max(high_, open_, close)
        low_  = min(low_,  open_, close)
        # 거래량 (BTC 기준, 약 $500M~$5B 범위)
        base_vol = 50_000 + abs(np.random.normal(0, 20_000))
        # 큰 움직임에는 거래량 증가
        price_move = abs(close / (prices[i-1] if i > 0 else close) - 1)
        vol = base_vol * (1 + price_move * 10) * np.exp(np.random.normal(0, 0.3))

        rows.append({
            "date":       d.isoformat(),
            "open":       round(open_, 2),
            "high":       round(high_, 2),
            "low":        round(low_,  2),
            "close":      round(close, 2),
            "volume":     round(vol, 2),
            "quote_volume": round(vol * close, 2),
            "trades":     int(base_vol * 0.5),
        })

    return pd.DataFrame(rows)


def generate_all():
    os.makedirs(DATA_DIR, exist_ok=True)
    all_dfs = []

    for seg in SEGMENTS:
        df = generate_segment(*seg)
        if not df.empty:
            all_dfs.append(df)

    full = pd.concat(all_dfs, ignore_index=True)
    full = full.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    full.to_csv(OUT_FILE, index=False)

    print(f"[합성 데이터 생성 완료]")
    print(f"  기간: {full['date'].min()} ~ {full['date'].max()}")
    print(f"  총  : {len(full)}개 일봉")
    print(f"  저장: {OUT_FILE}")
    print(f"  시작가: ${full.iloc[0]['close']:,.0f}")
    print(f"  종료가: ${full.iloc[-1]['close']:,.0f}")
    return full


if __name__ == "__main__":
    generate_all()
