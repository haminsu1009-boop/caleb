"""
Data Fetcher
============
yfinance 기반 미국 + 한국 주식 데이터 수집 모듈
"""

import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 캐시 (메모리)
# ─────────────────────────────────────────────

_cache: Dict[str, Tuple[float, object]] = {}


def _get_cache(key: str, ttl: int) -> Optional[object]:
    if key in _cache:
        ts, val = _cache[key]
        if time.time() - ts < ttl:
            return val
    return None


def _set_cache(key: str, val: object) -> None:
    _cache[key] = (time.time(), val)


# ─────────────────────────────────────────────
# 가격 데이터
# ─────────────────────────────────────────────

def fetch_ohlcv(ticker: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
    """
    OHLCV 데이터 조회.
    period: 1d / 5d / 1mo / 3mo / 6mo / 1y / 2y / 5y / 10y / ytd / max
    interval: 1m / 2m / 5m / 15m / 30m / 60m / 90m / 1h / 1d / 5d / 1wk / 1mo / 3mo
    """
    cache_key = f"ohlcv:{ticker}:{period}:{interval}"
    from config import CACHE_TTL
    cached = _get_cache(cache_key, CACHE_TTL["price"])
    if cached is not None:
        return cached

    try:
        tk = yf.Ticker(ticker)
        df = tk.history(period=period, interval=interval, auto_adjust=True)
        if df.empty:
            logger.warning(f"[fetcher] {ticker}: 데이터 없음")
            return pd.DataFrame()
        df.index = pd.to_datetime(df.index)
        _set_cache(cache_key, df)
        return df
    except Exception as e:
        logger.error(f"[fetcher] {ticker} OHLCV 조회 실패: {e}")
        return pd.DataFrame()


def fetch_current_price(ticker: str) -> Optional[float]:
    """현재가 조회 (fast_info 우선, 실패 시 history 사용)"""
    try:
        tk = yf.Ticker(ticker)
        info = tk.fast_info
        price = getattr(info, "last_price", None) or getattr(info, "regularMarketPrice", None)
        if price:
            return float(price)
        df = fetch_ohlcv(ticker, period="2d", interval="1d")
        if not df.empty:
            return float(df["Close"].iloc[-1])
    except Exception as e:
        logger.error(f"[fetcher] {ticker} 현재가 조회 실패: {e}")
    return None


# ─────────────────────────────────────────────
# 펀더멘털 데이터
# ─────────────────────────────────────────────

def fetch_fundamentals(ticker: str) -> Dict:
    """
    주요 펀더멘털 지표 반환.
    반환 키: pe_ratio, forward_pe, eps, eps_growth, roe, revenue_growth,
             debt_to_equity, market_cap, sector, industry, dividend_yield
    """
    cache_key = f"fundamental:{ticker}"
    from config import CACHE_TTL
    cached = _get_cache(cache_key, CACHE_TTL["fundamental"])
    if cached is not None:
        return cached

    result = {
        "pe_ratio":       None,
        "forward_pe":     None,
        "eps":            None,
        "eps_growth":     None,   # YoY EPS 증가율 (소수, 예: 0.25 = 25%)
        "roe":            None,   # Return on Equity
        "revenue_growth": None,   # YoY 매출 증가율
        "debt_to_equity": None,
        "market_cap":     None,
        "sector":         None,
        "industry":       None,
        "dividend_yield": None,
    }

    try:
        tk = yf.Ticker(ticker)
        info = tk.info or {}

        result["pe_ratio"]       = info.get("trailingPE")
        result["forward_pe"]     = info.get("forwardPE")
        result["eps"]            = info.get("trailingEps")
        result["roe"]            = info.get("returnOnEquity")
        result["debt_to_equity"] = info.get("debtToEquity")
        result["market_cap"]     = info.get("marketCap")
        result["sector"]         = info.get("sector")
        result["industry"]       = info.get("industry")
        result["dividend_yield"] = info.get("dividendYield")

        # EPS 성장률: earnings_quarterly에서 YoY 계산
        try:
            earnings = tk.quarterly_earnings
            if earnings is not None and not earnings.empty and len(earnings) >= 4:
                eps_vals = earnings["Earnings"].values
                if eps_vals[-1] and eps_vals[-5 if len(eps_vals) >= 5 else -4]:
                    prev = eps_vals[-5] if len(eps_vals) >= 5 else eps_vals[-4]
                    curr = eps_vals[-1]
                    if prev != 0:
                        result["eps_growth"] = (curr - prev) / abs(prev)
        except Exception:
            pass

        # 매출 성장률: financials에서 YoY 계산
        try:
            fin = tk.financials
            if fin is not None and not fin.empty and "Total Revenue" in fin.index:
                rev = fin.loc["Total Revenue"]
                if len(rev) >= 2:
                    r0, r1 = rev.iloc[0], rev.iloc[1]   # 최신, 전년도
                    if r1 != 0:
                        result["revenue_growth"] = (r0 - r1) / abs(r1)
        except Exception:
            pass

    except Exception as e:
        logger.error(f"[fetcher] {ticker} 펀더멘털 조회 실패: {e}")

    _set_cache(cache_key, result)
    return result


# ─────────────────────────────────────────────
# 배치 조회
# ─────────────────────────────────────────────

def fetch_batch_ohlcv(tickers: list, period: str = "6mo") -> Dict[str, pd.DataFrame]:
    """여러 티커 OHLCV 일괄 조회 (yfinance download 활용)"""
    try:
        raw = yf.download(tickers, period=period, auto_adjust=True, progress=False, group_by="ticker")
        result = {}
        if len(tickers) == 1:
            result[tickers[0]] = raw
        else:
            for t in tickers:
                try:
                    result[t] = raw[t].dropna(how="all")
                except KeyError:
                    result[t] = pd.DataFrame()
        return result
    except Exception as e:
        logger.error(f"[fetcher] batch OHLCV 실패: {e}")
        return {t: pd.DataFrame() for t in tickers}


def fetch_all_stocks(us_list: list, kr_list: list) -> Dict[str, Dict]:
    """
    전체 감시 종목 데이터 수집.
    반환: {ticker: {"ohlcv": df, "fundamentals": dict, "current_price": float}}
    """
    all_tickers = us_list + kr_list
    ohlcv_map = fetch_batch_ohlcv(all_tickers, period="6mo")

    result = {}
    for ticker in all_tickers:
        logger.info(f"[fetcher] {ticker} 수집 중...")
        df = ohlcv_map.get(ticker, pd.DataFrame())
        if df.empty:
            df = fetch_ohlcv(ticker, period="6mo")

        price = None
        if not df.empty:
            price = float(df["Close"].iloc[-1])

        fundamentals = fetch_fundamentals(ticker)

        result[ticker] = {
            "ohlcv":         df,
            "fundamentals":  fundamentals,
            "current_price": price,
        }
        time.sleep(0.3)   # rate limit 방지

    return result
