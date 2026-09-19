"""
generate_multi_coin_data.py
ETH, BNB, SOL 합성 일봉 데이터 생성 (BTC와 상관관계 반영)

멀티코인 데이터로 학습 샘플 수 4배 확보:
  BTC 3,157일 + ETH 3,157일 + BNB 2,500일 + SOL 1,500일 ≈ 10,000개
"""

import os
import numpy as np
import pandas as pd
from datetime import date, timedelta

SEED = 42
np.random.seed(SEED)

ROOT     = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# BTC 로드
BTC_FILE = os.path.join(DATA_DIR, "btc_daily.csv")
btc_df   = pd.read_csv(BTC_FILE)
btc_df["date"] = pd.to_datetime(btc_df["date"])
btc_df = btc_df.sort_values("date").reset_index(drop=True)
btc_returns = btc_df["close"].pct_change().fillna(0).values


def generate_correlated_coin(
    symbol: str,
    start_date: str,
    start_price: float,
    btc_corr: float,     # BTC와 상관계수
    alpha: float,        # 독자 드리프트
    extra_vol: float,    # 추가 변동성
) -> pd.DataFrame:
    """BTC와 상관관계를 가진 코인 데이터 생성"""

    start_dt = pd.Timestamp(start_date)
    mask     = btc_df["date"] >= start_dt
    btc_sub  = btc_df[mask].reset_index(drop=True)
    btc_ret  = btc_sub["close"].pct_change().fillna(0).values
    n        = len(btc_sub)

    # 코인 수익률 = BTC 상관 부분 + 독자적 움직임
    idio_ret = np.random.normal(alpha / 252, extra_vol, n)
    coin_ret = btc_corr * btc_ret + np.sqrt(1 - btc_corr**2) * idio_ret

    # 가격 재구성
    prices = [start_price]
    for r in coin_ret[1:]:
        prices.append(prices[-1] * (1 + r))

    # OHLCV 생성
    rows = []
    for i, (price, d) in enumerate(zip(prices, btc_sub["date"])):
        vol_mult  = abs(coin_ret[i]) * 10 + 1
        open_     = prices[i-1] if i > 0 else price * (1 + np.random.normal(0, extra_vol*0.3))
        high_     = price * (1 + abs(np.random.normal(0, extra_vol * 0.7)))
        low_      = price * (1 - abs(np.random.normal(0, extra_vol * 0.7)))
        high_     = max(high_, open_, price)
        low_      = min(low_,  open_, price)
        vol_base  = btc_sub.iloc[i]["volume"] * (start_price / btc_sub.iloc[i]["close"]) * 3
        volume    = abs(vol_base * vol_mult * np.exp(np.random.normal(0, 0.3)))

        rows.append({
            "date":   d.strftime("%Y-%m-%d"),
            "symbol": symbol,
            "open":   round(open_, 4),
            "high":   round(high_, 4),
            "low":    round(low_,  4),
            "close":  round(price, 4),
            "volume": round(volume, 2),
        })

    df = pd.DataFrame(rows)
    df = df.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    return df


def generate_4h_from_daily(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """
    일봉 → 4시간봉 합성 (6캔들/일)
    패턴: 새벽 저점 → 오전 고점 → 오후 조정 형태
    """
    rows = []
    for _, row in df.iterrows():
        o, h, l, c = row["open"], row["high"], row["low"], row["close"]
        vol = row["volume"]
        date_str = row["date"]

        # 6개 4H 캔들 (0, 4, 8, 12, 16, 20시)
        pivots = np.sort(np.random.uniform(l, h, 4))
        path   = np.concatenate([[o], pivots, [c]])
        vol_parts = np.random.dirichlet(np.ones(6)) * vol

        for i in range(6):
            co = path[i]
            cc = path[i+1]
            ch = max(co, cc) * (1 + abs(np.random.normal(0, 0.003)))
            cl = min(co, cc) * (1 - abs(np.random.normal(0, 0.003)))
            rows.append({
                "date":   f"{date_str}T{i*4:02d}:00",
                "symbol": symbol,
                "open":   round(co, 4),
                "high":   round(ch, 4),
                "low":    round(cl,  4),
                "close":  round(cc, 4),
                "volume": round(vol_parts[i], 2),
            })
    return pd.DataFrame(rows)


COIN_CONFIGS = {
    "ETHUSDT": dict(
        start_date="2017-08-17", start_price=300,
        btc_corr=0.82, alpha=0.25, extra_vol=0.062
    ),
    "BNBUSDT": dict(
        start_date="2017-11-01", start_price=0.10,
        btc_corr=0.74, alpha=0.45, extra_vol=0.068
    ),
    "SOLUSDT": dict(
        start_date="2020-04-10", start_price=0.52,
        btc_corr=0.78, alpha=0.60, extra_vol=0.080
    ),
}


def generate_all():
    print("[멀티코인 데이터 생성]")
    print(f"  기준: BTC {btc_df['date'].min().date()} ~ {btc_df['date'].max().date()}")

    all_dfs = []

    # BTC에 symbol 컬럼 추가
    btc_copy = btc_df.copy()
    btc_copy["symbol"] = "BTCUSDT"
    btc_copy["date"] = btc_copy["date"].dt.strftime("%Y-%m-%d")
    all_dfs.append(btc_copy[["date","symbol","open","high","low","close","volume"]])

    for symbol, cfg in COIN_CONFIGS.items():
        df = generate_correlated_coin(symbol, **cfg)
        path = os.path.join(DATA_DIR, f"{symbol}_daily.csv")
        df.to_csv(path, index=False)
        all_dfs.append(df)
        print(f"  {symbol}: {len(df):,}일  "
              f"{df['date'].min()} ~ {df['date'].max()}  "
              f"시작가=${cfg['start_price']}  "
              f"최근가=${df['close'].iloc[-1]:,.2f}")

    # 전체 통합 파일
    combined = pd.concat(all_dfs, ignore_index=True)
    combined_path = os.path.join(DATA_DIR, "all_coins_daily.csv")
    combined.to_csv(combined_path, index=False)

    print(f"\n  통합 파일: {len(combined):,}개 샘플 → {combined_path}")
    print(f"  코인별: {combined.groupby('symbol').size().to_dict()}")
    return combined


if __name__ == "__main__":
    generate_all()
