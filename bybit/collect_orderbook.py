"""
bybit/collect_orderbook.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
호가창 데이터 수집 — 지금까지 한 번도 안 본 영역

이 저장소의 모든 검증은 OHLCV(시가·고가·저가·종가·거래량)만 썼다.
지표 63개, 규칙 계열 452개를 뒤져 통과가 0개였던 것은 가격
데이터에서 짜낼 수 있는 걸 대체로 다 짜냈다는 뜻이기도 하다.

한 번도 안 본 것이 시장미시구조다.
  · 호가 불균형 (매수호가 총량 vs 매도호가 총량)
  · 스프레드 (최우선 매수/매도 호가 차이)
  · 호가창 깊이 (얼마나 큰 주문을 받아낼 수 있나)

이건 가격에 드러나기 전의 수급이라 알파가 실재하는 영역이고,
동시에 우리가 실측한 체결 비용(지연 0.196%p, 스프레드 미측정)의
정체이기도 하다.

받는 것 (data.binance.vision, API 키 불필요)
  bookTicker  최우선 매수/매도 호가와 수량 — 스프레드를 잰다
  bookDepth   호가창 깊이 스냅샷 — 불균형을 잰다

⚠️ 용량 주의
  bookTicker는 체결 단위라 하루치가 종목당 수십~수백 MB다.
  전 종목 전 기간을 받으면 저장소가 감당 못 한다. 그래서
  · 종목을 지정해서 받고
  · 받는 즉시 1분 단위로 요약해 저장한다(원본은 버린다)
  요약 항목: 평균 스프레드(bp), 호가 불균형, 최우선 호가 수량.

사용법
    python bybit/collect_orderbook.py --symbol BTCUSDT --days 30
    python bybit/collect_orderbook.py --symbols BTCUSDT ETHUSDT --days 90
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, io, sys, time, zipfile, argparse
from datetime import date, timedelta

import requests
import pandas as pd
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BASE = "https://data.binance.vision/data/futures/um/daily"
SAVE_DIR = os.path.join(ROOT, "data", "orderbook")
os.makedirs(SAVE_DIR, exist_ok=True)


def fetch_zip(url: str, retries: int = 3):
    for a in range(retries):
        try:
            r = requests.get(url, timeout=120)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return zipfile.ZipFile(io.BytesIO(r.content))
        except requests.RequestException:
            if a == retries - 1:
                return None
            time.sleep(2 ** a)
    return None


def day_bookticker(symbol: str, d: date):
    """최우선 호가 → 1분 요약. 원본은 버린다(하루치가 수백 MB다)."""
    z = fetch_zip(f"{BASE}/bookTicker/{symbol}/{symbol}-bookTicker-{d}.zip")
    if z is None:
        return None
    try:
        raw = pd.read_csv(z.open(z.namelist()[0]))
    except Exception:
        return None
    cols = {c.lower(): c for c in raw.columns}
    need = ["best_bid_price", "best_bid_qty", "best_ask_price", "best_ask_qty"]
    if not all(n in cols for n in need):
        return None
    tcol = cols.get("transaction_time") or cols.get("event_time")
    if tcol is None:
        return None
    df = pd.DataFrame({
        "dt": pd.to_datetime(raw[tcol], unit="ms", errors="coerce"),
        "bid": pd.to_numeric(raw[cols["best_bid_price"]], errors="coerce"),
        "bq": pd.to_numeric(raw[cols["best_bid_qty"]], errors="coerce"),
        "ask": pd.to_numeric(raw[cols["best_ask_price"]], errors="coerce"),
        "aq": pd.to_numeric(raw[cols["best_ask_qty"]], errors="coerce"),
    }).dropna()
    if df.empty:
        return None
    mid = (df.bid + df.ask) / 2
    df["spread_bp"] = (df.ask - df.bid) / mid * 10000
    # 호가 불균형: +1이면 매수호가만, -1이면 매도호가만
    df["imbalance"] = (df.bq - df.aq) / (df.bq + df.aq).replace(0, np.nan)
    g = df.set_index("dt").resample("1min")
    return pd.DataFrame({
        "spread_bp": g["spread_bp"].mean(),
        "spread_bp_max": g["spread_bp"].max(),
        "imbalance": g["imbalance"].mean(),
        "bid_qty": g["bq"].mean(),
        "ask_qty": g["aq"].mean(),
        "ticks": g.size(),
    }).dropna(how="all")


def collect(symbol: str, days: int):
    path = os.path.join(SAVE_DIR, f"{symbol}_book_1m.csv.gz")
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    prev = None
    if os.path.exists(path):
        try:
            prev = pd.read_csv(path, compression="gzip", parse_dates=["dt"])
            if not prev.empty:
                last = prev["dt"].max().date()
                start = max(start, last + timedelta(days=1))
                print(f"  기존 {len(prev):,}행 (~{last}), {start}부터")
        except Exception as e:
            print(f"  ⚠️ 기존 파일 무시: {e}")
            prev = None
    if start > end:
        print(f"  변경 없음 — {path}")
        return path

    frames, got, miss = [], 0, 0
    n = (end - start).days + 1
    print(f"\n  {symbol} 호가창 {start} ~ {end} ({n}일)")
    for i in range(n):
        d = start + timedelta(days=i)
        one = day_bookticker(symbol, d)
        if one is None or one.empty:
            miss += 1
        else:
            frames.append(one.reset_index())
            got += 1
        if (i + 1) % 10 == 0:
            print(f"    {d}  받음 {got} / 없음 {miss}")
        time.sleep(0.05)

    if not frames:
        print(f"  ⚠️ 새 데이터 없음 (요청 {n}일)")
        return path if prev is not None else None
    new = pd.concat(frames, ignore_index=True)
    out = pd.concat([prev, new]) if prev is not None else new
    out = (out.dropna(subset=["dt"]).sort_values("dt")
              .drop_duplicates("dt", keep="last").reset_index(drop=True))
    out.to_csv(path, index=False, compression={"method": "gzip", "mtime": 0})
    mb = os.path.getsize(path) / 1e6
    print(f"  ✅ {path}  ({len(out):,}행, {mb:.1f}MB, 새로 받은 날 {got}/{n})")
    print(f"     평균 스프레드 {out.spread_bp.mean():.2f}bp · "
          f"평균 불균형 {out.imbalance.mean():+.4f}")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--days", type=int, default=30)
    a = ap.parse_args()
    syms = a.symbols or [a.symbol]
    print("=" * 60)
    print(f"  호가창 수집 — {len(syms)}종 × 최근 {a.days}일")
    print("  bookTicker를 받아 1분 요약만 저장한다 (원본은 버린다)")
    print("=" * 60)
    for s in syms:
        try:
            collect(s, a.days)
        except Exception as e:
            print(f"  {s}: 실패 — {e}")


if __name__ == "__main__":
    main()
