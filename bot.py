"""
bot.py
매 1시간마다 BTC 신호 체크 → signals.log에 기록 (실제 주문 없음)

동작:
  1. Binance에서 최신 일봉 데이터 가져오기
  2. backtest_results.csv에서 상위 전략 로드
  3. 현재 데이터에 각 전략 신호 계산
  4. 신호 발생 시 signals.log에 기록
  5. 1시간 대기 후 반복
"""

import os
import sys
import time
import json
import logging
import datetime
import requests
import pandas as pd
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))

DATA_FILE     = os.path.join(ROOT, "data", "btc_daily.csv")
BACKTEST_FILE = os.path.join(ROOT, "backtest_results.csv")
LOG_FILE      = os.path.join(ROOT, "signals.log")

MIN_WIN_RATE    = 0.70
MIN_OCCURRENCES = 20
TOP_N_STRATEGIES = 10   # 상위 N개 전략만 모니터링
CHECK_INTERVAL  = 3600  # 1시간 (초)

BINANCE_URL = "https://api.binance.com/api/v3/klines"


# ── 로거 설정 ──────────────────────────────────
def setup_logger() -> logging.Logger:
    logger = logging.getLogger("quant_bot")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    # 파일 핸들러
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # 콘솔 핸들러
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger


# ── 최신 데이터 가져오기 ───────────────────────
def fetch_recent_candles(n: int = 250) -> pd.DataFrame:
    """Binance에서 최근 n일 일봉 데이터 수신"""
    params = {
        "symbol": "BTCUSDT",
        "interval": "1d",
        "limit": n,
    }
    for attempt in range(4):
        try:
            resp = requests.get(BINANCE_URL, params=params, timeout=15)
            resp.raise_for_status()
            rows = resp.json()
            break
        except Exception as e:
            wait = 2 ** attempt
            time.sleep(wait)
    else:
        return pd.DataFrame()

    cols = ["open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_vol", "trades", "tb_base", "tb_quote", "ignore"]
    df = pd.DataFrame(rows, columns=cols)
    df["date"] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c])
    return df[["date", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


# ── 지표 계산 ──────────────────────────────────
def compute_indicators_safe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]

    for p in [7, 20, 50, 100, 200]:
        df[f"sma{p}"] = c.rolling(p).mean()
        df[f"ema{p}"] = c.ewm(span=p, adjust=False).mean()

    for p in [7, 14, 21]:
        delta = c.diff()
        gain  = delta.clip(lower=0).rolling(p).mean()
        loss  = (-delta.clip(upper=0)).rolling(p).mean()
        rs    = gain / loss.replace(0, np.nan)
        df[f"rsi{p}"] = 100 - (100 / (1 + rs))

    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["macd"]        = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"]   = df["macd"] - df["macd_signal"]

    mid = c.rolling(20).mean()
    for std_k in [2, 1.5]:
        std = c.rolling(20).std()
        df[f"bb20_upper_{std_k}"] = mid + std_k * std
        df[f"bb20_lower_{std_k}"] = mid - std_k * std
        df[f"bb20_%b_{std_k}"]    = (c - (mid - std_k*std)) / (2*std_k*std)

    for p in [14, 21]:
        lo = l.rolling(p).min()
        hi = h.rolling(p).max()
        df[f"stoch_k{p}"] = (c - lo) / (hi - lo + 1e-9) * 100
        df[f"stoch_d{p}"] = df[f"stoch_k{p}"].rolling(3).mean()

    tr  = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    pdm = h.diff().clip(lower=0)
    mdm = (-l.diff()).clip(lower=0)
    atr14 = tr.rolling(14).mean()
    df["plus_di14"]  = 100 * pdm.rolling(14).mean() / atr14.replace(0, np.nan)
    df["minus_di14"] = 100 * mdm.rolling(14).mean() / atr14.replace(0, np.nan)
    dx = (df["plus_di14"] - df["minus_di14"]).abs() / \
         (df["plus_di14"] + df["minus_di14"] + 1e-9) * 100
    df["adx14"] = dx.rolling(14).mean()

    df["vol_sma20"] = v.rolling(20).mean()
    df["vol_ratio"] = v / df["vol_sma20"]
    obv = (np.sign(c.diff()) * v).fillna(0).cumsum()
    df["obv"]       = obv
    df["obv_sma20"] = obv.rolling(20).mean()
    return df


# ── 신호 계산 ──────────────────────────────────
def compute_signals(df: pd.DataFrame) -> dict[str, bool]:
    """마지막 행 기준 각 신호 True/False"""
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else last

    c, h, l = last["close"], last["high"], last["low"]

    signals: dict[str, bool] = {
        "RSI14_과매도(30이하)":     last.get("rsi14", 50) < 30,
        "RSI14_과매도(35이하)":     last.get("rsi14", 50) < 35,
        "RSI14_중립반등(40~50)":    40 <= last.get("rsi14", 50) <= 50,
        "RSI7_과매도(25이하)":      last.get("rsi7",  50) < 25,
        "RSI21_과매도(30이하)":     last.get("rsi21", 50) < 30,

        "MACD_골든크로스":
            last.get("macd", 0) > last.get("macd_signal", 0) and
            prev.get("macd", 0) <= prev.get("macd_signal", 0),
        "MACD_히스토_전환(+)":
            last.get("macd_hist", 0) > 0 and prev.get("macd_hist", 0) <= 0,
        "MACD_히스토_증가":
            last.get("macd_hist", 0) > prev.get("macd_hist", 0),

        "SMA20_골든크로스(50)":
            c > last.get("sma20", c) and prev["close"] <= prev.get("sma20", prev["close"]),
        "SMA50_골든크로스(200)":
            last.get("sma50", 0) > last.get("sma200", 0) and
            prev.get("sma50", 0) <= prev.get("sma200", 0),
        "EMA20_골든크로스(50)":
            last.get("ema20", 0) > last.get("ema50", 0) and
            prev.get("ema20", 0) <= prev.get("ema50", 0),
        "EMA7_골든크로스(20)":
            last.get("ema7", 0) > last.get("ema20", 0) and
            prev.get("ema7", 0) <= prev.get("ema20", 0),
        "가격_SMA200_위":           c > last.get("sma200", 0),
        "가격_SMA50_위":            c > last.get("sma50", 0),

        "BB_하단터치(2σ)":          c < last.get("bb20_lower_2", 0),
        "BB_하단터치(1.5σ)":        c < last.get("bb20_lower_1.5", 0),
        "BB_%B_과매도(0.2이하)":    last.get("bb20_%b_2", 0.5) < 0.2,
        "BB_%B_중간반등":
            0.4 <= last.get("bb20_%b_2", 0.5) <= 0.6,

        "STOCH14_과매도(20이하)":   last.get("stoch_k14", 50) < 20,
        "STOCH14_골든크로스":
            last.get("stoch_k14", 50) > last.get("stoch_d14", 50) and
            prev.get("stoch_k14", 50) <= prev.get("stoch_d14", 50),
        "STOCH21_과매도(20이하)":   last.get("stoch_k21", 50) < 20,

        "ADX14_강세(25이상)":       last.get("adx14", 0) > 25,
        "ADX14_추세상승(+DI>-DI)":  last.get("plus_di14", 0) > last.get("minus_di14", 0),

        "거래량_급증(2배이상)":      last.get("vol_ratio", 1.0) > 2.0,
        "거래량_증가(1.5배)":        last.get("vol_ratio", 1.0) > 1.5,
        "OBV_SMA위":                last.get("obv", 0) > last.get("obv_sma20", 0),
    }
    return signals


# ── 전략 로드 ──────────────────────────────────
def load_top_strategies() -> list[dict]:
    if not os.path.exists(BACKTEST_FILE):
        return []
    df = pd.read_csv(BACKTEST_FILE)
    df["복합점수"] = df["승률"] * np.log1p(df["발생횟수"])
    top = df[
        (df["승률"] >= MIN_WIN_RATE) & (df["발생횟수"] >= MIN_OCCURRENCES)
    ].sort_values("복합점수", ascending=False).head(TOP_N_STRATEGIES)

    strategies = []
    for _, row in top.iterrows():
        strategies.append({
            "조합":    row["조합"],
            "지표들":  [s.strip() for s in row["조합"].split(" + ")],
            "승률":    row["승률"],
            "발생횟수": row["발생횟수"],
            "복합점수": row["복합점수"],
        })
    return strategies


# ── 메인 루프 ──────────────────────────────────
def check_signals(logger: logging.Logger):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"{'='*50}")
    logger.info(f"신호 체크 시작: {now}")

    # 최신 데이터 수신
    df = fetch_recent_candles(250)
    if df.empty:
        logger.warning("데이터 수신 실패 - 다음 사이클에 재시도")
        return

    current_price = df.iloc[-1]["close"]
    current_date  = df.iloc[-1]["date"]
    logger.info(f"현재 BTC 가격: ${current_price:,.2f}  ({current_date})")

    # 지표 계산
    try:
        df = compute_indicators_safe(df)
    except Exception as e:
        logger.error(f"지표 계산 실패: {e}")
        return

    # 신호 계산
    signals = compute_signals(df)
    active_signals = [name for name, val in signals.items() if val]
    logger.info(f"활성 신호 ({len(active_signals)}개): {', '.join(active_signals) if active_signals else '없음'}")

    # 전략 매칭
    strategies = load_top_strategies()
    if not strategies:
        logger.warning("전략 없음 - backtest.py 및 analyze.py 실행 후 재시도")
    else:
        triggered = []
        for strat in strategies:
            indicators = strat["지표들"]
            if all(signals.get(ind, False) for ind in indicators):
                triggered.append(strat)

        if triggered:
            logger.info(f"*** 매수 신호 발생! {len(triggered)}개 전략 매칭 ***")
            for s in triggered:
                logger.info(
                    f"  [신호] {s['조합']}  "
                    f"| 승률: {s['승률']*100:.1f}%  "
                    f"| 발생횟수: {s['발생횟수']}  "
                    f"| 현재가: ${current_price:,.2f}"
                )
        else:
            logger.info("매수 신호 없음 (전략 조건 미충족)")

    # 현재 지표 값 요약
    last = df.iloc[-1]
    summary = {
        "date":     current_date,
        "price":    round(current_price, 2),
        "rsi14":    round(last.get("rsi14", float("nan")), 2),
        "macd":     round(last.get("macd", float("nan")), 4),
        "adx14":    round(last.get("adx14", float("nan")), 2),
        "vol_ratio": round(last.get("vol_ratio", float("nan")), 2),
        "bb_%b":    round(last.get("bb20_%b_2", float("nan")), 4),
        "active_signals": active_signals,
    }
    logger.info(f"지표 요약: {json.dumps(summary, ensure_ascii=False)}")
    logger.info(f"체크 완료")


def run_bot():
    logger = setup_logger()
    logger.info("퀀트 트레이딩 봇 시작 (신호 감시 모드 - 실제 주문 없음)")
    logger.info(f"체크 주기: {CHECK_INTERVAL}초 (1시간)")
    logger.info(f"모니터링 전략 수: 상위 {TOP_N_STRATEGIES}개")

    while True:
        try:
            check_signals(logger)
        except KeyboardInterrupt:
            logger.info("봇 종료 (사용자 중단)")
            break
        except Exception as e:
            logger.error(f"예외 발생: {e}", exc_info=True)

        logger.info(f"다음 체크까지 {CHECK_INTERVAL}초 대기...")
        try:
            time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            logger.info("봇 종료 (사용자 중단)")
            break


if __name__ == "__main__":
    run_bot()
