"""
stocks/fetcher.py
주식 데이터 수집기

지원:
  - 한국 주식: FinanceDataReader (KRX) 또는 합성 데이터
  - 미국 주식: yfinance 또는 합성 데이터
  - 암호화폐: 기존 coin/data_fetcher.py 연계

설치:
  pip install finance-datareader yfinance

주의: 실제 주식 데이터는 로컬에서 수집 후 CSV로 저장하는 것을 권장.
     원격 환경에서는 프록시 제한으로 API 호출이 차단될 수 있음.
"""

import os
import sys
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data", "stocks")
os.makedirs(DATA_DIR, exist_ok=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 한국 주식
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KR_STOCKS = {
    "005930": dict(name="삼성전자",        price=75000,  vol=0.018, drift=0.0002),
    "000660": dict(name="SK하이닉스",      price=130000, vol=0.025, drift=0.0003),
    "035420": dict(name="NAVER",           price=210000, vol=0.020, drift=0.0001),
    "005380": dict(name="현대차",          price=220000, vol=0.015, drift=0.0002),
    "051910": dict(name="LG화학",          price=350000, vol=0.022, drift=0.0001),
    "068270": dict(name="셀트리온",        price=190000, vol=0.028, drift=0.0003),
    "035720": dict(name="카카오",          price=55000,  vol=0.025, drift=0.0001),
    "207940": dict(name="삼성바이오로직스", price=800000, vol=0.018, drift=0.0003),
    "006400": dict(name="삼성SDI",         price=270000, vol=0.022, drift=0.0002),
    "028260": dict(name="삼성물산",        price=150000, vol=0.016, drift=0.0002),
}

US_STOCKS = {
    "AAPL":  dict(name="Apple",      price=190.0, vol=0.018, drift=0.0003),
    "NVDA":  dict(name="NVIDIA",     price=800.0, vol=0.035, drift=0.0008),
    "MSFT":  dict(name="Microsoft",  price=400.0, vol=0.016, drift=0.0003),
    "TSLA":  dict(name="Tesla",      price=250.0, vol=0.042, drift=0.0003),
    "AMZN":  dict(name="Amazon",     price=190.0, vol=0.022, drift=0.0004),
    "GOOGL": dict(name="Alphabet",   price=170.0, vol=0.020, drift=0.0003),
    "META":  dict(name="Meta",       price=490.0, vol=0.025, drift=0.0005),
    "AMD":   dict(name="AMD",        price=170.0, vol=0.035, drift=0.0005),
    "INTC":  dict(name="Intel",      price=45.0,  vol=0.022, drift=0.0001),
    "SMCI":  dict(name="SuperMicro", price=900.0, vol=0.055, drift=0.0006),
    "PLTR":  dict(name="Palantir",   price=25.0,  vol=0.045, drift=0.0005),
    "COIN":  dict(name="Coinbase",   price=200.0, vol=0.060, drift=0.0005),
}


def _generate_stock(
    ticker:      str,
    start_price: float,
    vol:         float,
    drift:       float,
    n_days:      int  = 800,
    market:      str  = "KR",
) -> pd.DataFrame:
    """주식 합성 일봉 생성 (팻 꼬리 + 추세 반영)"""
    np.random.seed(abs(hash(ticker)) % 2**31)

    base  = datetime.utcnow() - timedelta(days=n_days)
    dates = pd.bdate_range(base, periods=n_days)[:n_days]  # 영업일

    ret = (np.random.normal(drift / 252, vol, n_days)
           + np.random.standard_t(df=4, size=n_days) * vol * 0.2)

    # 가끔 점프 (어닝 서프라이즈, 뉴스 등)
    jump_idx = np.random.choice(n_days, size=int(n_days * 0.03), replace=False)
    ret[jump_idx] += np.random.normal(0, vol * 3, len(jump_idx))

    prices = [start_price]
    for r in ret[1:]:
        prices.append(max(prices[-1] * (1 + r), 0.01))

    rows = []
    for i, (dt, price) in enumerate(zip(dates, prices)):
        r = ret[i]
        o = prices[i-1] if i > 0 else price
        h = price * (1 + abs(np.random.normal(0, vol * 0.4)))
        l = price * (1 - abs(np.random.normal(0, vol * 0.4)))
        h = max(h, o, price)
        l = min(l, o, price)
        rows.append({
            "date":   dt.strftime("%Y-%m-%d"),
            "symbol": ticker,
            "open":   round(o, 2),
            "high":   round(h, 2),
            "low":    round(l, 2),
            "close":  round(price, 2),
            "volume": round(abs(np.random.lognormal(12, 1)), 0),
            "market": market,
        })

    return pd.DataFrame(rows)


def fetch_kr_stock(code: str, force_synthetic: bool = False) -> pd.DataFrame:
    """한국 주식 일봉 데이터 수집"""
    cache = os.path.join(DATA_DIR, f"KR_{code}.csv")

    if os.path.exists(cache) and not force_synthetic:
        df = pd.read_csv(cache)
        print(f"  캐시 로드: KR {code} ({len(df)}일)")
        return df

    # FinanceDataReader 시도
    if not force_synthetic:
        try:
            import FinanceDataReader as fdr
            start = (datetime.utcnow() - timedelta(days=1200)).strftime("%Y-%m-%d")
            df = fdr.DataReader(code, start)
            df = df.reset_index()
            df.columns = [c.lower() for c in df.columns]
            df = df.rename(columns={"date": "date"})
            if "close" not in df.columns and "종가" in df.columns:
                df = df.rename(columns={"종가": "close", "시가": "open",
                                        "고가": "high", "저가": "low", "거래량": "volume"})
            df["symbol"] = code
            df["market"] = "KR"
            df.to_csv(cache, index=False)
            print(f"  KRX API: {code} ({len(df)}일)")
            return df
        except Exception as e:
            print(f"  FinanceDataReader 실패 ({e}) → 합성 데이터 사용")

    # 합성 데이터
    cfg = KR_STOCKS.get(code, {"price": 50000, "vol": 0.02, "drift": 0.0002})
    df  = _generate_stock(code, cfg["price"], cfg["vol"], cfg["drift"], market="KR")
    df.to_csv(cache, index=False)
    print(f"  합성 KR: {code} ({len(df)}일)")
    return df


def fetch_us_stock(ticker: str, force_synthetic: bool = False) -> pd.DataFrame:
    """미국 주식 일봉 데이터 수집"""
    cache = os.path.join(DATA_DIR, f"US_{ticker}.csv")

    if os.path.exists(cache) and not force_synthetic:
        df = pd.read_csv(cache)
        print(f"  캐시 로드: US {ticker} ({len(df)}일)")
        return df

    # yfinance 시도
    if not force_synthetic:
        try:
            import yfinance as yf
            start = (datetime.utcnow() - timedelta(days=1200)).strftime("%Y-%m-%d")
            tk  = yf.Ticker(ticker)
            df  = tk.history(start=start, interval="1d", auto_adjust=True)
            df  = df.reset_index()
            df.columns = [c.lower() for c in df.columns]
            df = df.rename(columns={"date": "date", "stock splits": "splits"})
            df["symbol"] = ticker
            df["market"] = "US"
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            df[["date", "symbol", "open", "high", "low", "close", "volume", "market"]].to_csv(
                cache, index=False)
            print(f"  yfinance: {ticker} ({len(df)}일)")
            return df
        except Exception as e:
            print(f"  yfinance 실패 ({e}) → 합성 데이터 사용")

    # 합성 데이터
    cfg = US_STOCKS.get(ticker, {"price": 100.0, "vol": 0.025, "drift": 0.0003})
    df  = _generate_stock(ticker, cfg["price"], cfg["vol"], cfg["drift"], market="US")
    df.to_csv(cache, index=False)
    print(f"  합성 US: {ticker} ({len(df)}일)")
    return df


def fetch_all_stocks(
    kr_codes: list  = None,
    us_tickers: list = None,
    force_synthetic: bool = False,
) -> pd.DataFrame:
    """전체 주식 데이터 수집 + 통합"""
    kr = kr_codes  if kr_codes  is not None else list(KR_STOCKS.keys())
    us = us_tickers if us_tickers is not None else list(US_STOCKS.keys())

    parts = []
    for code in kr:
        try:
            df = fetch_kr_stock(code, force_synthetic=force_synthetic)
            parts.append(df)
        except Exception as e:
            print(f"  {code} 오류: {e}")

    for ticker in us:
        try:
            df = fetch_us_stock(ticker, force_synthetic=force_synthetic)
            parts.append(df)
        except Exception as e:
            print(f"  {ticker} 오류: {e}")

    if not parts:
        return pd.DataFrame()

    combined = pd.concat(parts, ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"]).dt.strftime("%Y-%m-%d")
    combined = combined.sort_values(["symbol", "date"]).reset_index(drop=True)

    # 통합 파일 저장
    all_path = os.path.join(DATA_DIR, "all_stocks_daily.csv")
    combined.to_csv(all_path, index=False)
    print(f"\n  통합 저장: {len(combined):,}개 샘플 → {all_path}")
    return combined


if __name__ == "__main__":
    import sys
    force = "--synthetic" in sys.argv
    print("[주식 데이터 수집]")
    df = fetch_all_stocks(force_synthetic=force)
    print(f"\n코드별 샘플 수:")
    if not df.empty:
        print(df.groupby(["market", "symbol"]).size().to_string())
