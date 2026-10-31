"""
bybit/collect_bybit_history.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
바이빗 실거래소 캔들 수집 (공개 API, 키 불필요)

왜 필요한가:
  이 세션의 모든 백테스트는 지금까지 bybit/collect_history.py를 통해
  data.binance.vision(바이낸스)에서 받은 데이터를 썼다. 실거래는
  바이빗에서 돌 예정인데, 검증은 다른 거래소 가격으로 해온 셈이다.

  종가 기준 지표(이동평균 교차, %변동)는 두 거래소가 차익거래로
  거의 같이 움직여 차이가 미미하다. 하지만 사용자 규칙#1처럼
  "저가/고가 꼬리가 특정 선을 터치"하는 조건은 다르다 — 급변동 시
  거래소별 청산 캐스케이드로 꼬리 길이가 갈리는 경우가 실제로 있다.
  이런 룰은 반드시 실제 거래할 거래소의 데이터로 재검증해야 한다.

⚠️ 이 세션의 프록시는 api.bybit.com을 막는다(업비트·바이낸스 API와
   동일 증상). GitHub Actions 러너에서는 정상 동작하므로 수집은
   워크플로로만 돌린다.

사용법:
    python bybit/collect_bybit_history.py --symbol BTCUSDT --interval D
    python bybit/collect_bybit_history.py --all --interval D
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, time, argparse

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAVE_DIR = os.path.join(ROOT, "data", "bybit")
os.makedirs(SAVE_DIR, exist_ok=True)

SYMBOLS = ["AAVEUSDT", "ADAUSDT", "ALGOUSDT", "APTUSDT", "ARBUSDT", "ATOMUSDT", "AVAXUSDT",
           "AXSUSDT", "BNBUSDT", "BTCUSDT", "CHZUSDT", "DOGEUSDT", "DOTUSDT", "EGLDUSDT",
           "EOSUSDT", "ETCUSDT", "ETHUSDT", "FILUSDT", "FLOWUSDT", "FTMUSDT", "GRTUSDT",
           "HBARUSDT", "ICPUSDT", "INJUSDT", "IOTAUSDT", "LINKUSDT", "LTCUSDT", "MANAUSDT",
           "MATICUSDT", "MKRUSDT", "NEARUSDT", "NEOUSDT", "OPUSDT", "QNTUSDT", "RUNEUSDT",
           "SANDUSDT", "SEIUSDT", "SOLUSDT", "SUIUSDT", "THETAUSDT", "TIAUSDT", "TRXUSDT",
           "UNIUSDT", "VETUSDT", "XLMUSDT", "XRPUSDT"]

# Bybit V5 kline interval 표기: 분 단위 숫자 또는 D/W/M
INTERVAL_MAP = {"1d": "D", "D": "D", "4h": "240", "1h": "60"}


def get_session():
    from pybit.unified_trading import HTTP
    return HTTP(testnet=False)   # 공개 kline 조회는 키 불필요


def collect(symbol: str, interval: str = "D", max_batches: int = 200) -> pd.DataFrame:
    session = get_session()
    biv = INTERVAL_MAP.get(interval, interval)
    rows = []
    end = None

    for _ in range(max_batches):
        params = dict(category="linear", symbol=symbol, interval=biv, limit=1000)
        if end is not None:
            params["end"] = end
        r = session.get_kline(**params)
        if r.get("retCode") != 0:
            break
        batch = r["result"]["list"]
        if not batch:
            break
        rows.extend(batch)
        oldest_ms = int(batch[-1][0])   # V5는 최신순 정렬이라 마지막이 가장 오래된 봉
        if end == oldest_ms:
            break
        end = oldest_ms - 1
        time.sleep(0.1)
        if len(batch) < 1000:
            break

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume", "turnover"])
    out = pd.DataFrame({
        "datetime": pd.to_datetime(df["ts"].astype("int64"), unit="ms"),
        "open": df["open"].astype(float), "high": df["high"].astype(float),
        "low": df["low"].astype(float), "close": df["close"].astype(float),
        "volume": df["volume"].astype(float),
    })
    return out.drop_duplicates("datetime").sort_values("datetime").reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--interval", default="D")
    a = ap.parse_args()

    targets = a.symbols if a.symbols else (SYMBOLS if a.all else [a.symbol])
    iv_label = {"D": "1d", "240": "4h", "60": "1h"}.get(
        INTERVAL_MAP.get(a.interval, a.interval), a.interval)

    print("=" * 60)
    print(f"  바이빗 실거래소 캔들 수집 — {len(targets)}종목, {iv_label}")
    print("=" * 60)

    for i, s in enumerate(targets, 1):
        try:
            print(f"  [{i}/{len(targets)}] {s} ...", flush=True)
            df = collect(s, a.interval)
        except Exception as e:
            print(f"  {s}: 실패 — {e}")
            continue
        if df.empty:
            print(f"  {s}: 데이터 없음")
            continue
        path = os.path.join(SAVE_DIR, f"{s}_{iv_label}.csv.gz")
        df.to_csv(path, index=False, compression="gzip")
        print(f"  {s:10s} {len(df):>6,}건  {df['datetime'].iloc[0].date()} ~ {df['datetime'].iloc[-1].date()}")


if __name__ == "__main__":
    main()
