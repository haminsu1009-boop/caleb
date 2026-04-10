"""
BTC/USDT 일봉 데이터 생성기
실제 BTC 역사적 가격 마일스톤 기반으로 현실적인 OHLCV 데이터 생성.
(Binance API 접근 불가 시 대체용 - 나중에 collect_data.py로 실제 데이터 교체 가능)
"""

import numpy as np
import pandas as pd
import os
from datetime import datetime, timedelta

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "btc_daily.csv")

# 실제 BTC 역사적 가격 마일스톤 (날짜, 종가)
MILESTONES = [
    ("2017-01-01", 1000),
    ("2017-03-10", 1200),
    ("2017-05-25", 2700),
    ("2017-08-01", 2800),
    ("2017-09-15", 3200),
    ("2017-11-01", 6400),
    ("2017-12-17", 19783),
    ("2018-02-06", 6900),
    ("2018-05-01", 9200),
    ("2018-07-01", 6400),
    ("2018-09-01", 7000),
    ("2018-11-15", 5600),
    ("2018-12-15", 3200),
    ("2019-02-01", 3400),
    ("2019-04-02", 5000),
    ("2019-06-26", 13000),
    ("2019-09-01", 9600),
    ("2019-12-18", 6600),
    ("2020-02-14", 10300),
    ("2020-03-13", 5000),
    ("2020-05-11", 8700),
    ("2020-08-01", 11800),
    ("2020-10-21", 12800),
    ("2020-12-31", 29000),
    ("2021-01-08", 40700),
    ("2021-01-27", 30500),
    ("2021-02-21", 57000),
    ("2021-03-13", 61200),
    ("2021-04-14", 64800),
    ("2021-05-19", 36700),
    ("2021-06-22", 29500),
    ("2021-08-01", 39800),
    ("2021-09-07", 52700),
    ("2021-09-21", 40000),
    ("2021-10-20", 66000),
    ("2021-11-10", 69000),
    ("2021-12-04", 49000),
    ("2022-01-01", 46300),
    ("2022-01-24", 33000),
    ("2022-03-28", 47400),
    ("2022-05-12", 27000),
    ("2022-06-18", 17600),
    ("2022-08-15", 24400),
    ("2022-09-21", 18500),
    ("2022-11-09", 15500),
    ("2023-01-01", 16500),
    ("2023-01-14", 21100),
    ("2023-03-14", 24700),
    ("2023-04-14", 30400),
    ("2023-06-22", 30000),
    ("2023-07-13", 31400),
    ("2023-08-18", 26000),
    ("2023-10-24", 34000),
    ("2023-12-08", 44000),
    ("2024-01-10", 46000),
    ("2024-01-23", 39500),
    ("2024-02-28", 62000),
    ("2024-03-14", 73000),
    ("2024-04-20", 64000),
    ("2024-05-21", 70000),
    ("2024-06-24", 61300),
    ("2024-07-29", 66800),
    ("2024-08-05", 49000),
    ("2024-09-06", 53500),
    ("2024-09-27", 65600),
    ("2024-10-29", 72300),
    ("2024-11-05", 68000),
    ("2024-11-22", 99000),
    ("2024-12-05", 97000),
    ("2024-12-17", 108000),
    ("2025-01-07", 102000),
    ("2025-01-20", 109000),
    ("2025-02-03", 98000),
    ("2025-02-28", 84000),
    ("2025-03-11", 77000),
    ("2025-03-24", 88000),
    ("2025-04-02", 83000),
    ("2025-04-10", 80000),
]


def generate_btc_daily():
    np.random.seed(42)

    milestone_dates = [datetime.strptime(d, "%Y-%m-%d") for d, _ in MILESTONES]
    milestone_prices = [p for _, p in MILESTONES]

    start = milestone_dates[0]
    end = milestone_dates[-1]
    days = (end - start).days + 1

    all_dates = [start + timedelta(days=i) for i in range(days)]

    closes = np.interp(
        [d.timestamp() for d in all_dates],
        [d.timestamp() for d in milestone_dates],
        milestone_prices,
    )

    # 일간 변동성 추가 (가격 수준에 비례)
    noise_pct = np.random.normal(0, 0.012, len(closes))
    closes = closes * (1 + noise_pct)
    closes = np.maximum(closes, 100)

    rows = []
    for i, (date, close) in enumerate(zip(all_dates, closes)):
        daily_vol = abs(np.random.normal(0, 0.025))
        high = close * (1 + daily_vol * np.random.uniform(0.3, 1.2))
        low = close * (1 - daily_vol * np.random.uniform(0.3, 1.2))
        open_price = low + (high - low) * np.random.uniform(0.2, 0.8)

        # 거래량: 가격과 변동성에 비례
        base_vol = close * np.random.uniform(15000, 60000)
        vol_multiplier = 1 + daily_vol * 10
        volume = base_vol * vol_multiplier

        open_time = int(date.timestamp() * 1000)
        close_time = int((date + timedelta(days=1) - timedelta(milliseconds=1)).timestamp() * 1000)

        rows.append({
            "open_time": open_time,
            "open": round(open_price, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2),
            "volume": round(volume, 2),
            "close_time": close_time,
            "quote_volume": round(volume * close, 2),
            "trades": int(np.random.uniform(50000, 500000)),
            "date": date.strftime("%Y-%m-%d"),
        })

    df = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)
    print(f"BTC 일봉 데이터 생성 완료: {OUTPUT_PATH}")
    print(f"총 {len(df)}개 ({df['date'].iloc[0]} ~ {df['date'].iloc[-1]})")
    print(f"가격 범위: ${df['close'].min():,.0f} ~ ${df['close'].max():,.0f}")
    return df


if __name__ == "__main__":
    generate_btc_daily()
