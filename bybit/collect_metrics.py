"""
bybit/collect_metrics.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Binance 선물 메트릭 수집 — "고래 지표"의 공개 데이터 버전

무엇을 받는가 (data.binance.vision, API 키 불필요):
    sum_open_interest              미결제약정 수량
    sum_open_interest_value        미결제약정 USDT 가치
    count_toptrader_long_short_ratio   상위 트레이더 계좌수 롱/숏 비율
    sum_toptrader_long_short_ratio     상위 트레이더 포지션 롱/숏 비율  ← 고래
    count_long_short_ratio             전체 계좌수 롱/숏 비율          ← 개미
    sum_taker_long_short_vol_ratio     시장가 매수/매도 체결량 비율

왜 이게 "고래 신호"인가:
  Binance는 증거금 기준 상위 20% 계좌를 따로 집계해 준다.
  sum_toptrader(고래 포지션)와 count_long_short(전체 계좌수)가
  반대로 벌어질 때가 흔히 말하는 "고래는 팔고 개미는 사는" 상태다.
  체인 위 지갑을 추적하는 유료 데이터는 못 구하지만, 이건
  거래소가 직접 집계해서 무료로 공개하는 것이고 정의가 명확하다.

한계 (미리 밝힌다):
  · 이 아카이브는 2023년경부터만 있다. 우리 홀드아웃(2024~)은
    덮지만 학습 구간(2017~2023)은 거의 못 덮는다. 즉 이 지표로
    규칙을 만들면 "학습에서 찾고 홀드아웃에서 검증"이 불가능하다.
    지금 할 수 있는 건 기존 규칙에 대한 사후 대조뿐이다.
  · 5분 간격 원본을 4시간봉에 맞춰 리샘플해서 저장한다.
  · 일별 파일이라 종목당 요청이 많다. 이미 받은 날은 건너뛴다.

사용법:
    python bybit/collect_metrics.py --symbol BTCUSDT
    python bybit/collect_metrics.py --all
    python bybit/collect_metrics.py --all --since 2024-01-01
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, io, sys, time, zipfile, argparse
from datetime import date, timedelta

import requests
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BASE_URL = "https://data.binance.vision/data/futures/um/daily/metrics"
SAVE_DIR = os.path.join(ROOT, "data", "metrics")
os.makedirs(SAVE_DIR, exist_ok=True)

# 아카이브 자체가 이 무렵부터 존재한다. 더 이르게 잡으면 404만 잔뜩 친다.
ARCHIVE_START = date(2023, 1, 1)

NUM_COLS = ["sum_open_interest", "sum_open_interest_value",
            "count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio",
            "count_long_short_ratio", "sum_taker_long_short_vol_ratio"]

from bybit.collect_funding import FUTURES_START      # 42종 목록 재사용


def download_day(symbol: str, d: date, retries: int = 3):
    """하루치 5분 간격 메트릭. 없으면 None (404는 정상 — 상장 전/누락일)."""
    url = f"{BASE_URL}/{symbol}/{symbol}-metrics-{d}.zip"
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            break
        except requests.RequestException:
            if attempt == retries - 1:
                return None
            time.sleep(2 ** attempt)
    try:
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            raw = pd.read_csv(z.open(z.namelist()[0]))
    except Exception:
        return None
    if "create_time" not in raw.columns:
        return None
    raw["timestamp"] = pd.to_datetime(raw["create_time"], errors="coerce")
    for c in NUM_COLS:
        raw[c] = pd.to_numeric(raw.get(c), errors="coerce")
    return raw.dropna(subset=["timestamp"])[["timestamp"] + NUM_COLS]


def to_4h(df: pd.DataFrame) -> pd.DataFrame:
    """5분 원본을 4시간봉 경계에 맞춘다.

    OI는 잔량(stock)이라 구간 마지막 값이 맞고, 비율들은 구간 평균이
    맞다. last를 일괄로 쓰면 5분짜리 튐 하나가 4시간을 대표하게 된다.
    """
    d = df.set_index("timestamp").sort_index()
    agg = {c: ("last" if c.startswith("sum_open_interest") else "mean")
           for c in NUM_COLS}
    out = d.resample("4h", label="left", closed="left").agg(agg)
    return out.dropna(how="all").reset_index()


def collect(symbol: str, since: date | None = None) -> str | None:
    path = os.path.join(SAVE_DIR, f"{symbol}_metrics_4h.csv.gz")
    start = since or ARCHIVE_START
    # 어제까지. 오늘 파일은 아직 안 올라온다.
    end = date.today() - timedelta(days=1)

    print(f"\n{'━'*54}")
    print(f"  {symbol} 선물 메트릭 수집")
    print(f"{'━'*54}")

    prev = None
    if os.path.exists(path):
        try:
            prev = pd.read_csv(path, compression="gzip", parse_dates=["timestamp"])
            if not prev.empty:
                # 마지막으로 확보한 날의 다음 날부터. 그날 자체는 4시간
                # 리샘플이 하루를 다 못 채웠을 수 있으니 다시 받는다.
                last_day = prev["timestamp"].max().date()
                start = max(start, last_day)
                print(f"  기존 {len(prev):,}행 (~{last_day}), {start}부터 이어받음")
        except Exception as e:
            print(f"  ⚠️ 기존 파일 무시: {e}")
            prev = None

    if start > end:
        print(f"  변경 없음 — {path}")
        return path

    days = (end - start).days + 1
    frames, got, miss = [], 0, 0
    for i in range(days):
        d = start + timedelta(days=i)
        one = download_day(symbol, d)
        if one is None or one.empty:
            miss += 1
        else:
            frames.append(one); got += 1
        if (i + 1) % 100 == 0:
            print(f"    {d}  받음 {got} / 없음 {miss}")
        time.sleep(0.03)

    if not frames:
        print(f"  ⚠️ 새 데이터 없음 (요청 {days}일, 전부 404)")
        return path if prev is not None else None

    new = to_4h(pd.concat(frames, ignore_index=True))
    out = pd.concat([prev, new]) if prev is not None else new
    out = (out.dropna(subset=["timestamp"]).sort_values("timestamp")
              .drop_duplicates("timestamp", keep="last").reset_index(drop=True))
    out.to_csv(path, index=False, compression={"method": "gzip", "mtime": 0})
    print(f"  ✅ {path}  ({len(out):,}행, 새로 받은 날 {got}/{days})")
    print(f"     {out['timestamp'].iloc[0]} ~ {out['timestamp'].iloc[-1]}")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--since", default=None, help="YYYY-MM-DD")
    a = ap.parse_args()

    if a.symbols:
        syms = a.symbols
    elif a.all:
        syms = list(FUTURES_START)
    else:
        syms = [a.symbol]
    since = date.fromisoformat(a.since) if a.since else None

    print("=" * 54)
    print(f"  Binance 선물 메트릭 수집 — {len(syms)}종목")
    print("=" * 54)
    for s in syms:
        try:
            collect(s, since)
        except Exception as e:
            print(f"  {s}: 실패 — {e}")


if __name__ == "__main__":
    main()
