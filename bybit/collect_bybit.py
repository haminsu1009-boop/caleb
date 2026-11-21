"""
bybit/collect_bybit.py
Bybit에서 분봉 OHLCV 데이터 수집

사용법:
    python bybit/collect_bybit.py              # 기본: BTCUSDT 5분봉
    python bybit/collect_bybit.py --interval 1  # 1분봉
    python bybit/collect_bybit.py --symbol ETHUSDT --interval 15
    python bybit/collect_bybit.py --days 30     # 최근 30일치
"""

import os, sys, time, argparse
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from pybit.unified_trading import HTTP


def get_session():
    """Bybit 세션 생성 (API키 없어도 공개 데이터는 조회 가능)"""
    api_key = os.getenv("BYBIT_API_KEY", "")
    secret  = os.getenv("BYBIT_SECRET", "")
    testnet = os.getenv("BYBIT_TESTNET", "false").lower() == "true"

    return HTTP(
        testnet=testnet,
        api_key=api_key or None,
        api_secret=secret or None,
    )


def fetch_klines(
    session,
    symbol:   str = "BTCUSDT",
    interval: str = "5",       # 1, 3, 5, 15, 30, 60, 120, 240, D
    start_ms: int = None,      # 시작 타임스탬프 (ms)
    end_ms:   int = None,
    limit:    int = 200,       # 최대 200
) -> pd.DataFrame:
    """캔들 데이터 한 배치 가져오기"""
    params = dict(
        category="linear",
        symbol=symbol,
        interval=interval,
        limit=limit,
    )
    if start_ms:
        params["start"] = start_ms
    if end_ms:
        params["end"] = end_ms

    resp = session.get_kline(**params)
    rows = resp["result"]["list"]
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["timestamp","open","high","low","close","volume","turnover"])
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="ms")
    for c in ["open","high","low","close","volume","turnover"]:
        df[c] = df[c].astype(float)

    return df.sort_values("timestamp").reset_index(drop=True)


def collect_history(
    symbol:   str = "BTCUSDT",
    interval: str = "5",
    days:     int = 180,
    save_dir: str = "data",
) -> pd.DataFrame:
    """
    최근 N일치 분봉 데이터 수집 (페이징)
    Bybit은 한 번에 최대 200개 → 반복 호출로 전체 수집
    """
    session = get_session()

    interval_min = int(interval) if interval.isdigit() else 1440  # D = 1440분
    candles_per_day = (24 * 60) // interval_min
    total_candles   = candles_per_day * days

    end_ms   = int(datetime.utcnow().timestamp() * 1000)
    start_ms = end_ms - days * 24 * 3600 * 1000

    all_frames = []
    cur_start  = start_ms
    batch_size = 200
    n_batches  = 0

    print(f"📥 {symbol} {interval}분봉 {days}일치 수집 중 (예상 ~{total_candles:,}개 캔들)...")

    while cur_start < end_ms:
        df = fetch_klines(session, symbol, interval,
                          start_ms=cur_start, limit=batch_size)
        if df.empty:
            break

        all_frames.append(df)
        last_ts = int(df["timestamp"].iloc[-1].timestamp() * 1000)

        # 다음 배치 시작점
        step_ms  = interval_min * 60 * 1000 * batch_size
        cur_start = last_ts + interval_min * 60 * 1000

        n_batches += 1
        if n_batches % 10 == 0:
            pct = min(100, (last_ts - start_ms) / (end_ms - start_ms) * 100)
            print(f"  {pct:.0f}% ... {df['timestamp'].iloc[-1].strftime('%Y-%m-%d %H:%M')}")

        time.sleep(0.1)   # rate limit 여유

        if last_ts >= end_ms:
            break

    if not all_frames:
        print("⚠️  데이터 없음")
        return pd.DataFrame()

    result = pd.concat(all_frames).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)

    # 저장
    os.makedirs(save_dir, exist_ok=True)
    fname = f"{save_dir}/{symbol}_{interval}m.csv"
    result.to_csv(fname, index=False)
    print(f"\n✅ 저장 완료: {fname}  ({len(result):,}개 캔들)")
    print(f"   기간: {result['timestamp'].iloc[0]} ~ {result['timestamp'].iloc[-1]}")

    return result


def fetch_latest(
    symbol:      str  = "BTCUSDT",
    interval:    str  = "5",
    n:           int  = 800,     # 최신 N개 (피처 계산용)
    drop_forming: bool = True,   # 진행 중인 미완성 봉 제거
) -> pd.DataFrame:
    """
    최신 N개 캔들 가져오기 (실시간 봇용)

    ※ Bybit은 1회 최대 200개만 반환하므로 페이징으로 n개를 채운다.
      vs_sma288 / vs_sma576 / ret_288 / ema50_vs_200 등 장기 룩백 피처가
      NaN이 되지 않으려면 최소 600봉 이상 필요.

    ※ drop_forming=True 이면 마지막(진행 중) 봉을 버린다.
      학습은 종가 확정 봉으로 했으므로 실시간도 확정 봉만 써야
      신호가 깜빡이지 않는다.
    """
    session   = get_session()
    BATCH     = 200
    frames    = []
    end_ms    = None

    while sum(len(f) for f in frames) < n:
        df = fetch_klines(session, symbol, interval,
                          end_ms=end_ms, limit=BATCH)
        if df is None or df.empty:
            break
        frames.append(df)
        oldest_ms = int(df["timestamp"].iloc[0].timestamp() * 1000)
        if end_ms is not None and oldest_ms >= end_ms:
            break                      # 더 이상 과거로 못 감
        end_ms = oldest_ms - 1
        if len(df) < BATCH:
            break                      # 거래소에 더 이상 데이터 없음
        time.sleep(0.1)

    if not frames:
        return pd.DataFrame()

    out = (pd.concat(frames)
             .drop_duplicates("timestamp")
             .sort_values("timestamp")
             .reset_index(drop=True))

    if drop_forming and len(out) > 1:
        out = out.iloc[:-1].reset_index(drop=True)

    return out.tail(n).reset_index(drop=True)


# ── CLI 진입점 ──────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bybit 분봉 데이터 수집")
    parser.add_argument("--symbol",   default="BTCUSDT")
    parser.add_argument("--interval", default="5", help="1/3/5/15/30/60")
    parser.add_argument("--days",     type=int, default=180)
    parser.add_argument("--dir",      default="data")
    args = parser.parse_args()

    df = collect_history(
        symbol   = args.symbol,
        interval = args.interval,
        days     = args.days,
        save_dir = args.dir,
    )

    if not df.empty:
        print("\n📊 샘플 데이터 (최근 5개):")
        print(df.tail().to_string(index=False))
