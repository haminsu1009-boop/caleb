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
  bookDepth   호가창 깊이 스냅샷 — 불균형과 두께를 잰다
  (bookTicker는 아카이브에 없다 — 최근·과거 전부 404다.
   scripts/orderbook_probe.py 로 확인했다.)

⚠️ 용량 주의
  bookDepth는 하루 0.5MB로 가볍다(bookTicker와 달리).
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

# 첫 실행에서 futures/um/daily/bookTicker 가 30일 전부 404였다.
# 아카이브 종류가 시장(spot/futures)마다 다를 수 있으므로 후보를
# 순서대로 시도한다. scripts/orderbook_probe.py 가 실제로 어느 것이
# 존재하는지 확인해 준다.
BASES = [
    "https://data.binance.vision/data/futures/um/daily",
    "https://data.binance.vision/data/spot/daily",
]
BASE = BASES[0]          # 하위 호환
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


def day_bookdepth(symbol: str, d: date):
    """호가창 깊이 스냅샷 → 1분 요약.

    bookTicker(최우선 호가)는 아카이브에 없다 — 최근·과거 전부 404다
    (scripts/orderbook_probe.py 로 확인). 대신 bookDepth가 있고
    하루 0.5MB로 가볍다.

    bookDepth 형식
        timestamp, percentage, depth, notional
      percentage는 중간가로부터의 거리(%)다. 양수는 매도호가 쪽,
      음수는 매수호가 쪽이다. 보통 ±1~5% 구간이 들어 있다.
      depth는 그 구간까지의 누적 수량, notional은 명목가치다.

    여기서 뽑는 것
      imbalance   (매수쪽 명목 − 매도쪽 명목) / 합
                  +1이면 매수벽만, -1이면 매도벽만
      depth_1pct  ±1% 안의 총 명목가치 — 시장 두께
      ratio_5_1   5% 명목 ÷ 1% 명목 — 호가가 얼마나 퍼져 있나
    """
    z = fetch_zip(f"{BASE}/bookDepth/{symbol}/{symbol}-bookDepth-{d}.zip")
    if z is None:
        return None
    try:
        raw = pd.read_csv(z.open(z.namelist()[0]))
    except Exception:
        return None
    cols = {c.lower().strip(): c for c in raw.columns}
    tcol = cols.get("timestamp")
    pcol = cols.get("percentage")
    ncol = cols.get("notional")
    dcol = cols.get("depth")
    if not all([tcol, pcol, ncol]):
        return None
    df = pd.DataFrame({
        "dt": pd.to_datetime(raw[tcol], errors="coerce"),
        "pct": pd.to_numeric(raw[pcol], errors="coerce"),
        "notional": pd.to_numeric(raw[ncol], errors="coerce"),
        "depth": pd.to_numeric(raw[dcol], errors="coerce") if dcol else np.nan,
    }).dropna(subset=["dt", "pct", "notional"])
    if df.empty:
        return None

    df["side"] = np.where(df["pct"] < 0, "bid", "ask")
    df["band"] = df["pct"].abs()
    g = df.groupby([pd.Grouper(key="dt", freq="1min"), "side"])["notional"].sum()
    wide = g.unstack("side")
    if "bid" not in wide or "ask" not in wide:
        return None
    tot = (wide["bid"] + wide["ask"]).replace(0, np.nan)
    out = pd.DataFrame({
        "imbalance": (wide["bid"] - wide["ask"]) / tot,
        "notional_total": tot,
    })
    # ±1% 구간만 따로 — 가까운 호가가 진짜 유동성이다
    near = df[df["band"] <= 1.0]
    if not near.empty:
        gn = near.groupby([pd.Grouper(key="dt", freq="1min"), "side"])["notional"].sum()
        wn = gn.unstack("side")
        if "bid" in wn and "ask" in wn:
            tn = (wn["bid"] + wn["ask"]).replace(0, np.nan)
            out["imbalance_1pct"] = (wn["bid"] - wn["ask"]) / tn
            out["notional_1pct"] = tn
    out["spread_proxy"] = out["notional_1pct"] / out["notional_total"] \
        if "notional_1pct" in out else np.nan
    return out.dropna(how="all")


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
        one = day_bookdepth(symbol, d)
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
    print(f"     평균 불균형 {out.imbalance.mean():+.4f} · "
          f"±1% 불균형 {out.get('imbalance_1pct', pd.Series([np.nan])).mean():+.4f}")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--days", type=int, default=30)
    # 첫 실행에서 30일 전부 404였는데 스크립트가 정상 종료해 워크플로가
    # "성공"으로 끝났다. 아무것도 못 받았으면 실패로 끝내야 한다.
    ap.add_argument("--fail-if-empty", action="store_true",
                    help="한 종목도 못 받으면 종료코드 1")
    a = ap.parse_args()
    syms = a.symbols or [a.symbol]
    print("=" * 60)
    print(f"  호가창 수집 — {len(syms)}종 × 최근 {a.days}일")
    print("  bookTicker를 받아 1분 요약만 저장한다 (원본은 버린다)")
    print("=" * 60)
    got_any = False
    for s in syms:
        try:
            p = collect(s, a.days)
            if p and os.path.exists(p):
                got_any = True
        except Exception as e:
            print(f"  {s}: 실패 — {e}")
    if a.fail_if_empty and not got_any:
        print("\n  ⛔ 한 종목도 받지 못했다. 경로나 접근 권한을 확인해야 한다.")
        sys.exit(1)


if __name__ == "__main__":
    main()
