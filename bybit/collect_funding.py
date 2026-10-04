"""
bybit/collect_funding.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
무기한 선물 펀딩비 수집 (Binance 공개 아카이브)

왜 필요한가:
  · ml/trend_backtest.py 계열은 수수료와 슬리피지만 차감하고 펀딩비는
    빼지 않았다. 추세추종은 포지션을 몇 주씩 들고 가므로 8시간마다
    내는 펀딩비가 누적되면 결과가 달라질 수 있다. 특히 롱을 오래
    들고 가는 MA 롱온리는 강세장에서 펀딩비를 계속 내는 쪽이다.
  · 동시에 신호이기도 하다. 펀딩비가 극단으로 치우치면 한쪽 포지션이
    과밀하다는 뜻이라 되돌림이 잦다는 것이 널리 알려진 관찰이다.
    지금 데이터에는 이 정보가 아예 없어 검증조차 못 했다.

데이터 출처:
    https://data.binance.vision/data/futures/um/monthly/fundingRate/
    API 키 불필요, 지역 차단 없음 (data.binance.vision은 정적 CDN).

주의:
    2025년 아카이브부터 타임스탬프가 마이크로초로 바뀌었다.
    collect_history.py와 동일하게 자릿수로 단위를 판별한다.

사용법:
    python bybit/collect_funding.py --symbol BTCUSDT
    python bybit/collect_funding.py --all
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, io, sys, time, zipfile, argparse
from datetime import date

import requests
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BASE_URL = "https://data.binance.vision/data/futures/um/monthly/fundingRate"
SAVE_DIR = os.path.join(ROOT, "data", "funding")
os.makedirs(SAVE_DIR, exist_ok=True)

# 선물 상장 시점이 현물보다 늦다
# 전략이 실제로 거래하는 42종 전부. 이전엔 12종만 있어서
# ml/funding_filter.py가 1,923건 중 394건밖에 대조하지 못했다 —
# "펀딩비는 신호가 없다"를 그 표본으로 단정할 수 없었던 이유다.
# 연도는 Binance USDⓈ-M 선물 상장 시점(현물보다 늦다). 틀려도
# 404는 조용히 건너뛰므로 안전한 방향(이르게)으로 잡는다.
FUTURES_START = {
    "BTCUSDT": 2019, "ETHUSDT": 2019, "BNBUSDT": 2020, "SOLUSDT": 2020,
    "XRPUSDT": 2020, "ADAUSDT": 2020, "DOGEUSDT": 2020, "AVAXUSDT": 2020,
    "DOTUSDT": 2020, "MATICUSDT": 2020, "LINKUSDT": 2020, "LTCUSDT": 2020,
    "UNIUSDT": 2020, "ATOMUSDT": 2020, "NEARUSDT": 2021, "FILUSDT": 2020,
    "ETCUSDT": 2020, "TRXUSDT": 2020, "APTUSDT": 2022, "ARBUSDT": 2023,
    "OPUSDT": 2022, "INJUSDT": 2021, "SUIUSDT": 2023, "SEIUSDT": 2023,
    "TIAUSDT": 2023, "ALGOUSDT": 2020, "VETUSDT": 2020, "ICPUSDT": 2021,
    "HBARUSDT": 2021, "AAVEUSDT": 2020, "GRTUSDT": 2021, "SANDUSDT": 2021,
    "MANAUSDT": 2021, "AXSUSDT": 2021, "THETAUSDT": 2021, "XLMUSDT": 2020,
    "IOTAUSDT": 2020, "NEOUSDT": 2020, "QNTUSDT": 2021, "RUNEUSDT": 2021,
    "EGLDUSDT": 2020, "FLOWUSDT": 2021, "CHZUSDT": 2021,
}


def _ts_unit(v: float) -> str:
    """1.7e12 → 밀리초, 1.7e15 → 마이크로초 (2025년 아카이브부터 변경됨)"""
    return "us" if float(v) > 1e14 else "ms"


def download_month(symbol: str, year: int, month: int, retries: int = 3):
    url = f"{BASE_URL}/{symbol}/{symbol}-fundingRate-{year}-{month:02d}.zip"
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt == retries - 1:
                print(f" ⚠️ {e}")
                return None
            time.sleep(2 ** attempt)

    try:
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            raw = pd.read_csv(z.open(z.namelist()[0]))
    except Exception as e:
        print(f" ⚠️ 파싱 오류: {e}")
        return None

    # 헤더가 있는 달과 없는 달이 섞여 있다
    cols = [c.lower() for c in raw.columns]
    if "calc_time" not in cols and "fundingtime" not in cols:
        raw = pd.read_csv(io.BytesIO(r.content), header=None,
                          names=["calc_time", "funding_interval_hours", "last_funding_rate"])
        cols = list(raw.columns)
    raw.columns = cols

    tcol = "calc_time" if "calc_time" in cols else "fundingtime"
    rcol = ("last_funding_rate" if "last_funding_rate" in cols
            else ("fundingrate" if "fundingrate" in cols else cols[-1]))

    out = pd.DataFrame({
        "datetime": pd.to_datetime(raw[tcol], unit=_ts_unit(raw[tcol].iloc[0])),
        "funding_rate": pd.to_numeric(raw[rcol], errors="coerce"),
    }).dropna()
    return out.sort_values("datetime").reset_index(drop=True)


def collect(symbol: str, start_year: int | None = None) -> str | None:
    if start_year is None:
        start_year = FUTURES_START.get(symbol, 2020)
    today = date.today()
    end_y, end_m = today.year, today.month - 1
    if end_m == 0:
        end_y -= 1; end_m = 12

    print(f"\n{'━'*54}")
    print(f"  {symbol} 펀딩비 수집 ({start_year}년 ~)")
    print(f"{'━'*54}")

    # 이미 받아둔 달은 다시 받지 않는다. 매일 도는 워크플로가
    # 6년치 × 42종을 매번 통째로 내려받으면 몇 시간이 걸린다.
    # 마지막으로 확보한 달의 "다음 달"부터 이어받는다. 진행 중인
    # 달의 아카이브는 아직 안 올라오므로 end_m은 지난달이다.
    path = os.path.join(SAVE_DIR, f"{symbol}_funding.csv.gz")
    frames = []
    resume_y, resume_m = start_year, 1
    if os.path.exists(path):
        try:
            prev = pd.read_csv(path, compression="gzip",
                               parse_dates=["datetime"])
            if not prev.empty:
                frames.append(prev)
                last = prev["datetime"].max()
                resume_y, resume_m = last.year, last.month + 1
                if resume_m == 13:
                    resume_y += 1; resume_m = 1
                print(f"  기존 {len(prev):,}건 (~{last.date()}), "
                      f"{resume_y}-{resume_m:02d}부터 이어받음")
        except Exception as e:
            print(f"  ⚠️ 기존 파일 무시: {e}")

    got_new = False
    for y in range(resume_y, end_y + 1):
        m0 = resume_m if y == resume_y else 1
        for m in range(m0, 13):
            if y == end_y and m > end_m:
                break
            df = download_month(symbol, y, m)
            if df is None or df.empty:
                continue
            frames.append(df); got_new = True
            time.sleep(0.05)
        if got_new:
            print(f"  {y}: 누적 {sum(len(f) for f in frames):,}건")

    if not frames:
        print("  ⚠️ 데이터 없음")
        return None
    if not got_new:
        print(f"  변경 없음 — {path}")
        return path

    out = (pd.concat(frames).drop_duplicates("datetime")
             .sort_values("datetime").reset_index(drop=True))
    # mtime=0 — 내용이 같으면 바이트도 같아야 git diff가 안 생긴다
    out.to_csv(path, index=False,
               compression={"method": "gzip", "mtime": 0})

    ann = out["funding_rate"].mean() * 3 * 365 * 100      # 8시간마다 → 연율
    print(f"  ✅ {path}  ({len(out):,}건)")
    print(f"     {out['datetime'].iloc[0]} ~ {out['datetime'].iloc[-1]}")
    print(f"     평균 {out['funding_rate'].mean()*100:.4f}%/8h  → 롱 보유 연간비용 약 {ann:.1f}%")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--start-year", type=int, default=None)
    a = ap.parse_args()

    if a.symbols:
        syms = a.symbols
    elif a.all:
        syms = list(FUTURES_START)
    else:
        syms = [a.symbol]

    print("=" * 54)
    print(f"  펀딩비 수집 — {len(syms)}종목")
    print("=" * 54)
    for s in syms:
        try:
            collect(s, a.start_year)
        except Exception as e:
            print(f"  {s}: 실패 — {e}")


if __name__ == "__main__":
    main()
