"""
ml/collect_all_timeframes.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
전 심볼 × 전 타임프레임 OHLCV 데이터 수집기
Binance Public REST API (API 키 불필요)

수집 타임프레임:
  1m 3m 5m 15m 30m 1h 2h 4h 6h 12h 1d 3d 1w 1mo

저장 형식:
  data/{SYMBOL}_{TF}_{YEAR}.csv.gz   (연도별)
  data/{SYMBOL}_{TF}_all.csv.gz      (전기간 통합)

사용:
  python ml/collect_all_timeframes.py                        # 전체
  python ml/collect_all_timeframes.py --symbols ETHUSDT SOLUSDT
  python ml/collect_all_timeframes.py --timeframes 5m 1h 4h
  python ml/collect_all_timeframes.py --missing-only         # 누락만 수집
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os, sys, time, argparse, logging
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# ─────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────

# 수집 심볼 + 상장일
SYMBOLS = {
    "BTCUSDT":  "2017-08-17",
    "ETHUSDT":  "2017-08-17",
    "BNBUSDT":  "2017-11-06",
    "XRPUSDT":  "2018-05-04",
    "ADAUSDT":  "2018-04-17",
    "SOLUSDT":  "2020-09-11",
    "DOGEUSDT": "2019-07-05",
    "DOTUSDT":  "2020-08-19",
    "AVAXUSDT": "2020-09-23",
    "MATICUSDT":"2019-04-26",
    "LINKUSDT": "2019-01-16",
    "LTCUSDT":  "2017-12-13",
    "UNIUSDT":  "2020-09-18",
    "ATOMUSDT": "2019-04-23",
    "NEARUSDT": "2020-10-14",
}

# 수집 타임프레임 (Binance 지원 값)
TIMEFRAMES = ["1m","3m","5m","15m","30m","1h","2h","4h","6h","12h","1d","3d","1w","1mo"]

# 분 단위 (수집 간격 계산용)
TF_MINUTES = {
    "1m":1,"3m":3,"5m":5,"15m":15,"30m":30,
    "1h":60,"2h":120,"4h":240,"6h":360,"12h":720,
    "1d":1440,"3d":4320,"1w":10080,"1mo":43200,
}

BINANCE_URL = "https://api.binance.com/api/v3/klines"
LIMIT       = 1000   # 요청당 최대 캔들 수
MAX_RETRIES = 5


# ─────────────────────────────────────────────
# Binance API 수집
# ─────────────────────────────────────────────
def _ms(dt_str: str) -> int:
    return int(pd.Timestamp(dt_str, tz="UTC").timestamp() * 1000)

def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)

def fetch_klines(symbol: str, interval: str,
                 start_ms: int, end_ms: int) -> list:
    """Binance klines API 페이지 단위 수집"""
    all_rows = []
    cur      = start_ms

    while cur < end_ms:
        params = {
            "symbol":    symbol,
            "interval":  interval,
            "startTime": cur,
            "endTime":   min(end_ms, cur + LIMIT * TF_MINUTES[interval] * 60000),
            "limit":     LIMIT,
        }
        for attempt in range(MAX_RETRIES):
            try:
                r = requests.get(BINANCE_URL, params=params, timeout=20)
                r.raise_for_status()
                rows = r.json()
                break
            except Exception as e:
                wait = 2 ** attempt
                log.warning(f"재시도 {attempt+1}/{MAX_RETRIES}: {e} ({wait}s)")
                time.sleep(wait)
        else:
            log.error(f"  수집 실패: {symbol} {interval}")
            break

        if not rows:
            cur = params["endTime"] + 1
            continue

        all_rows.extend(rows)
        cur = rows[-1][0] + 1  # 마지막 캔들 다음 시점

        if len(rows) < LIMIT:
            break

        time.sleep(0.2)   # rate limit

    return all_rows

def rows_to_df(rows: list) -> pd.DataFrame:
    cols = ["timestamp","open","high","low","close","volume",
            "close_time","quote_volume","trades",
            "taker_buy_base","taker_buy_quote","ignore"]
    df = pd.DataFrame(rows, columns=cols)
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms")
    for c in ["open","high","low","close","volume","quote_volume"]:
        df[c] = df[c].astype(float)
    df["trades"] = df["trades"].astype(int)
    return df[["timestamp","open","high","low","close","volume","quote_volume"]].copy()


# ─────────────────────────────────────────────
# 저장 / 로드
# ─────────────────────────────────────────────
def save_annual(df: pd.DataFrame, symbol: str, interval: str):
    """연도별 분할 저장 + 전기간 통합"""
    df = df.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)

    # 연도별 저장
    years = df["timestamp"].dt.year.unique()
    for yr in years:
        sub = df[df["timestamp"].dt.year == yr]
        path = os.path.join(DATA_DIR, f"{symbol}_{interval}_{yr}.csv.gz")
        sub.to_csv(path, index=False, compression="gzip")

    # 전기간 통합
    all_path = os.path.join(DATA_DIR, f"{symbol}_{interval}_all.csv.gz")
    df.to_csv(all_path, index=False, compression="gzip")
    return len(df)

def load_existing(symbol: str, interval: str) -> pd.DataFrame:
    """이미 저장된 데이터 로드 (없으면 빈 DataFrame)"""
    path = os.path.join(DATA_DIR, f"{symbol}_{interval}_all.csv.gz")
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, compression="gzip")
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        return df.dropna(subset=["timestamp"])
    except Exception:
        return pd.DataFrame()

def check_missing(symbol: str, interval: str, start_date: str) -> tuple:
    """
    수집 필요 여부 확인

    Returns:
        (need_collect: bool, start_ms: int, reason: str)
    """
    existing = load_existing(symbol, interval)
    start_ms = _ms(start_date)
    now_ms   = _now_ms()

    if existing.empty:
        return True, start_ms, "데이터 없음"

    last_ts  = existing["timestamp"].max()
    last_ms  = int(last_ts.timestamp() * 1000)
    gap_min  = (now_ms - last_ms) / 60000

    if gap_min < TF_MINUTES[interval] * 2:
        return False, 0, f"최신 ({last_ts.date()})"

    return True, last_ms, f"마지막: {last_ts.date()} → 업데이트 필요"


# ─────────────────────────────────────────────
# 단일 심볼+인터벌 수집
# ─────────────────────────────────────────────
def collect_one(symbol: str, interval: str,
                start_date: str,
                missing_only: bool = False,
                append: bool = True) -> bool:
    """
    단일 심볼+인터벌 전체 수집

    Args:
        append: True이면 기존 데이터에 이어 수집 (최신화)
    """
    need, start_ms, reason = check_missing(symbol, interval, start_date)

    if missing_only and not need:
        return True   # 스킵

    log.info(f"  [{symbol} {interval}] {reason}")

    if not need:
        return True

    now_ms = _now_ms()
    rows   = fetch_klines(symbol, interval, start_ms, now_ms)

    if not rows:
        log.warning(f"  [{symbol} {interval}] 데이터 없음 (거래소 미지원?)")
        return False

    new_df = rows_to_df(rows)

    # 기존 데이터와 병합
    if append:
        existing = load_existing(symbol, interval)
        if not existing.empty:
            new_df = pd.concat([existing, new_df], ignore_index=True)

    n = save_annual(new_df, symbol, interval)
    log.info(f"  [{symbol} {interval}] ✅ {n:,}건 저장 "
             f"({new_df['timestamp'].min().date()} ~ {new_df['timestamp'].max().date()})")
    return True


# ─────────────────────────────────────────────
# 전체 수집
# ─────────────────────────────────────────────
def collect_all(
    symbols:      list = None,
    timeframes:   list = None,
    missing_only: bool = False,
    skip_1m:      bool = True,   # 1m 봉은 용량 엄청 큼 — 기본 건너뜀
):
    symbols    = symbols    or list(SYMBOLS.keys())
    timeframes = timeframes or TIMEFRAMES

    # 1m 봉은 기본 제외 (6개 심볼 × 1분봉 전기간 = 수십 GB)
    if skip_1m and "1m" in timeframes:
        timeframes = [t for t in timeframes if t != "1m"]
        log.info("1m봉 제외 (용량: 심볼당 ~5GB). --include-1m 옵션으로 포함 가능")

    total = len(symbols) * len(timeframes)
    done  = 0
    fail  = []

    print(f"\n{'═'*60}")
    print(f"  전체 수집: {len(symbols)}개 심볼 × {len(timeframes)}개 타임프레임")
    print(f"  = 총 {total}개 조합")
    print(f"{'═'*60}\n")

    for sym in symbols:
        start_date = SYMBOLS.get(sym, "2020-01-01")
        print(f"\n{'─'*50}")
        print(f"  ▶ {sym}  (상장일: {start_date})")
        print(f"{'─'*50}")

        for tf in timeframes:
            try:
                ok = collect_one(sym, tf, start_date,
                                 missing_only=missing_only,
                                 append=True)
                if not ok:
                    fail.append(f"{sym}_{tf}")
            except Exception as e:
                log.error(f"  [{sym} {tf}] 오류: {e}")
                fail.append(f"{sym}_{tf}")
            done += 1
            time.sleep(0.3)

    # 결과 요약
    print(f"\n{'═'*60}")
    print(f"  수집 완료: {done - len(fail)}/{total}")
    if fail:
        print(f"  실패: {', '.join(fail)}")
    print(f"{'═'*60}\n")

    # 전체 데이터 용량 출력
    total_size = sum(
        os.path.getsize(os.path.join(DATA_DIR, f))
        for f in os.listdir(DATA_DIR)
        if f.endswith(".csv.gz")
    )
    print(f"  총 데이터 용량: {total_size / 1024**2:.1f} MB")


# ─────────────────────────────────────────────
# 현황 리포트
# ─────────────────────────────────────────────
def print_coverage():
    """심볼별 타임프레임 수집 현황"""
    tfs_core = ["1m","5m","15m","1h","4h","1d","1w"]
    print(f"\n{'심볼':<12}", end="")
    for tf in tfs_core:
        print(f"{tf:>6}", end="")
    print(f"  {'총 캔들':>10}")
    print("─"*70)

    for sym in SYMBOLS:
        print(f"{sym:<12}", end="")
        total_candles = 0
        for tf in tfs_core:
            path = os.path.join(DATA_DIR, f"{sym}_{tf}_all.csv.gz")
            if os.path.exists(path):
                try:
                    n = len(pd.read_csv(path, compression="gzip"))
                    total_candles += n
                    print(f"{'✅':>5}", end="")
                except Exception:
                    print(f"{'⚠️':>5}", end="")
            else:
                print(f"{'─':>5}", end="")
        print(f"  {total_candles:>10,}")

    print()


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="전 심볼 × 전 타임프레임 데이터 수집")
    ap.add_argument("--symbols",      nargs="+", default=None,
                    help="수집 심볼 (기본: 전체 15개)")
    ap.add_argument("--timeframes",   nargs="+", default=None,
                    help="수집 타임프레임 (기본: 1m제외 전체)")
    ap.add_argument("--missing-only", action="store_true",
                    help="없는 데이터만 수집 (최신화 건너뜀)")
    ap.add_argument("--include-1m",   action="store_true",
                    help="1m봉 포함 (주의: 심볼당 ~5GB)")
    ap.add_argument("--coverage",     action="store_true",
                    help="현황만 출력")
    ap.add_argument("--core-only",    action="store_true",
                    help="핵심 타임프레임만: 5m 15m 1h 4h 1d")
    args = ap.parse_args()

    if args.coverage:
        print_coverage()
        return

    tfs = args.timeframes
    if args.core_only:
        tfs = ["5m","15m","1h","4h","1d"]

    collect_all(
        symbols      = args.symbols,
        timeframes   = tfs,
        missing_only = args.missing_only,
        skip_1m      = not args.include_1m,
    )

    print_coverage()


if __name__ == "__main__":
    main()
