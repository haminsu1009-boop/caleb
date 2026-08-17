"""
bybit/collect_indicators.py
외부 시장 지표 전체 수집 — ML 피처 보강용

수집 항목 (전부 무료, API 키 불필요):
  ① 공포탐욕지수      — alternative.me
  ② BTC 자금조달비율  — Bybit 공개 API
  ③ ETH 자금조달비율  — Bybit 공개 API
  ④ 미결제약정 (OI)   — Bybit 공개 API
  ⑤ 롱숏 비율        — Bybit 공개 API
  ⑥ BTC 도미넌스     — CoinGecko 공개 API
  ⑦ 전체 시총        — CoinGecko 공개 API
  ⑧ 구글 트렌드      — pytrends (키워드: bitcoin)
  ⑨ BTC 해시레이트   — blockchain.com 공개 API
  ⑩ BTC 활성주소수   — blockchain.com 공개 API
  ⑪ BTC 가격(CoinGecko) — 보조
  ⑫ 거시경제 지표    — Yahoo Finance (S&P500, NASDAQ, Gold, DXY, VIX, 10Y국채)
  ⑬ 청산 데이터      — Binance 공개 아카이브 (일별 청산 집계)
  ⑭ Binance 선물 메트릭 — OI/펀딩비 아카이브 (분봉/시봉 대응)
"""

import os, sys, time, requests, io, zipfile
import pandas as pd
from datetime import datetime, timedelta, date

SAVE_DIR = "data/indicators"
os.makedirs(SAVE_DIR, exist_ok=True)


def save(df: pd.DataFrame, name: str):
    path = f"{SAVE_DIR}/{name}.csv"
    df.to_csv(path, index=False)
    kb = os.path.getsize(path) // 1024
    print(f"  💾 저장: {path}  ({len(df):,}행, {kb}KB)")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ① 공포탐욕지수
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def fetch_fear_greed():
    print("\n📥 ① 공포탐욕지수 (Fear & Greed Index)...")
    r = requests.get("https://api.alternative.me/fng/?limit=3000&format=json", timeout=30)
    r.raise_for_status()
    data = r.json()["data"]
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["timestamp"].astype(int), unit="s").dt.date.astype(str)
    df["fear_greed"] = df["value"].astype(int)
    df["sentiment"]  = df["value_classification"]
    df = df[["date","fear_greed","sentiment"]].sort_values("date").reset_index(drop=True)
    print(f"  ✅ {len(df)}일치  {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")
    save(df, "fear_greed_index")
    return df


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ② ③ 자금조달비율 (Funding Rate)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def fetch_funding_rate(symbol="BTCUSDT", days=730):
    print(f"\n📥 자금조달비율 ({symbol})...")
    url = "https://api.bybit.com/v5/market/funding/history"
    rows, cur_end = [], int(datetime.utcnow().timestamp() * 1000)
    start_ms = cur_end - days * 86400 * 1000

    while cur_end > start_ms:
        try:
            data = requests.get(url, params=dict(
                category="linear", symbol=symbol, limit=200, endTime=cur_end
            ), timeout=30).json()["result"]["list"]
        except Exception as e:
            print(f"  ⚠️  {e}"); break
        if not data: break
        rows.extend(data)
        cur_end = int(data[-1]["fundingRateTimestamp"]) - 1
        time.sleep(0.05)

    if not rows: return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["timestamp"]    = pd.to_datetime(df["fundingRateTimestamp"].astype(int), unit="ms")
    df["funding_rate"] = df["fundingRate"].astype(float)
    df = df[["timestamp","funding_rate"]].sort_values("timestamp").reset_index(drop=True)
    print(f"  ✅ {len(df):,}건  {df['timestamp'].iloc[0]} ~ {df['timestamp'].iloc[-1]}")
    save(df, f"{symbol[:3]}_funding_rate")
    return df


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ④ 미결제약정 (Open Interest)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def fetch_open_interest(symbol="BTCUSDT", interval="1h", days=365):
    print(f"\n📥 미결제약정 OI ({symbol} {interval})...")
    url = "https://api.bybit.com/v5/market/open-interest"
    rows, cur = [], int((datetime.utcnow() - timedelta(days=days)).timestamp() * 1000)
    end_ms = int(datetime.utcnow().timestamp() * 1000)

    while cur < end_ms:
        try:
            data = requests.get(url, params=dict(
                category="linear", symbol=symbol,
                intervalTime=interval, limit=200,
                startTime=cur, endTime=end_ms
            ), timeout=30).json()["result"]["list"]
        except Exception as e:
            print(f"  ⚠️  {e}"); break
        if not data: break
        rows.extend(data)
        last = int(data[-1]["timestamp"])
        if last <= cur: break
        cur = last + 1
        time.sleep(0.05)

    if not rows: return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["timestamp"]     = pd.to_datetime(df["timestamp"].astype(int), unit="ms")
    df["open_interest"] = df["openInterest"].astype(float)
    df = df[["timestamp","open_interest"]].sort_values("timestamp").reset_index(drop=True)
    print(f"  ✅ {len(df):,}건")
    save(df, f"{symbol[:3]}_open_interest_{interval}")
    return df


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⑤ 롱숏 비율
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def fetch_long_short_ratio(symbol="BTCUSDT", period="1h", days=365):
    print(f"\n📥 롱숏 비율 ({symbol} {period})...")
    url = "https://api.bybit.com/v5/market/account-ratio"
    rows, cur = [], int((datetime.utcnow() - timedelta(days=days)).timestamp() * 1000)
    end_ms = int(datetime.utcnow().timestamp() * 1000)

    while cur < end_ms:
        try:
            data = requests.get(url, params=dict(
                category="linear", symbol=symbol,
                period=period, limit=500,
                startTime=cur, endTime=end_ms
            ), timeout=30).json()["result"]["list"]
        except Exception as e:
            print(f"  ⚠️  {e}"); break
        if not data: break
        rows.extend(data)
        last = int(data[-1]["timestamp"])
        if last <= cur: break
        cur = last + 1
        time.sleep(0.05)

    if not rows: return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["timestamp"]   = pd.to_datetime(df["timestamp"].astype(int), unit="ms")
    df["long_ratio"]  = df["buyRatio"].astype(float)
    df["short_ratio"] = df["sellRatio"].astype(float)
    df["ls_ratio"]    = df["long_ratio"] / (df["short_ratio"] + 1e-9)
    df = df[["timestamp","long_ratio","short_ratio","ls_ratio"]].sort_values("timestamp").reset_index(drop=True)
    print(f"  ✅ {len(df):,}건")
    save(df, f"{symbol[:3]}_long_short_{period}")
    return df


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⑥ ⑦ BTC 도미넌스 & 전체 시총 (CoinGecko)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def fetch_coingecko_global(days=365):
    print(f"\n📥 BTC 도미넌스 & 전체 시총 (CoinGecko)...")
    # CoinGecko global market chart (BTC dominance, total market cap)
    url = "https://api.coingecko.com/api/v3/global/market_cap_chart"
    try:
        r = requests.get(url, params={"days": days}, timeout=30,
                         headers={"accept": "application/json"})
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  ⚠️  CoinGecko 실패: {e}"); return pd.DataFrame()

    cap_list = data.get("market_cap_percentage", {}).get("btc", [])
    total_list = data.get("market_cap", {}).get("usd", [])

    if not cap_list:
        print("  ⚠️  데이터 없음"); return pd.DataFrame()

    df_dom = pd.DataFrame(cap_list, columns=["ts","btc_dominance"])
    df_dom["timestamp"] = pd.to_datetime(df_dom["ts"], unit="ms")
    df_dom["btc_dominance"] = df_dom["btc_dominance"].astype(float)

    if total_list:
        df_tot = pd.DataFrame(total_list, columns=["ts","total_market_cap"])
        df_tot["timestamp"] = pd.to_datetime(df_tot["ts"], unit="ms")
        df_tot["total_market_cap"] = df_tot["total_market_cap"].astype(float)
        df = df_dom.merge(df_tot[["timestamp","total_market_cap"]], on="timestamp", how="left")
    else:
        df = df_dom

    df = df[["timestamp","btc_dominance"] + (["total_market_cap"] if "total_market_cap" in df else [])].sort_values("timestamp").reset_index(drop=True)
    print(f"  ✅ {len(df):,}일치")
    save(df, "btc_dominance_market_cap")
    return df


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⑧ 구글 트렌드 (bitcoin 검색량)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def fetch_google_trends():
    print(f"\n📥 구글 트렌드 (bitcoin 검색량)...")
    try:
        from pytrends.request import TrendReq
    except ImportError:
        print("  pip install pytrends 필요")
        return pd.DataFrame()

    try:
        pt = TrendReq(hl="en-US", tz=0, timeout=(10, 30))
        all_dfs = []

        # 5년 단위로 나눠서 수집 (구글 트렌드 제한)
        periods = [
            ("2017-01-01", "2020-12-31"),
            ("2021-01-01", "2024-12-31"),
            ("2024-01-01", date.today().strftime("%Y-%m-%d")),
        ]
        for start, end in periods:
            pt.build_payload(["bitcoin"], timeframe=f"{start} {end}")
            df = pt.interest_over_time()
            if df.empty: continue
            df = df.reset_index()[["date","bitcoin"]]
            df.columns = ["date","google_trend_bitcoin"]
            all_dfs.append(df)
            time.sleep(1)

        if not all_dfs:
            print("  ⚠️  데이터 없음"); return pd.DataFrame()

        result = (pd.concat(all_dfs)
                    .drop_duplicates("date")
                    .sort_values("date")
                    .reset_index(drop=True))
        result["date"] = result["date"].astype(str)
        print(f"  ✅ {len(result):,}주치  {result['date'].iloc[0]} ~ {result['date'].iloc[-1]}")
        save(result, "google_trends_bitcoin")
        return result
    except Exception as e:
        print(f"  ⚠️  구글 트렌드 실패: {e}")
        return pd.DataFrame()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⑨ BTC 해시레이트 (blockchain.com)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def fetch_hash_rate(days: int = 3650):
    print(f"\n📥 BTC 해시레이트 & 채굴 난이도 (blockchain.com)...")
    results = {}
    endpoints = {
        "hash_rate":        "https://api.blockchain.info/charts/hash-rate?timespan=all&format=json&sampled=true",
        "mining_difficulty":"https://api.blockchain.info/charts/difficulty?timespan=all&format=json&sampled=true",
    }
    for name, url in endpoints.items():
        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            vals = r.json()["values"]
            df = pd.DataFrame(vals, columns=["ts", name])
            df["date"] = pd.to_datetime(df["ts"], unit="s").dt.date.astype(str)
            df[name] = df[name].astype(float)
            df = df[["date", name]].sort_values("date").reset_index(drop=True)
            results[name] = df
            print(f"  ✅ {name}: {len(df):,}일치")
            time.sleep(0.5)
        except Exception as e:
            print(f"  ⚠️  {name} 실패: {e}")

    if results:
        merged = list(results.values())[0]
        for df in list(results.values())[1:]:
            merged = merged.merge(df, on="date", how="outer")
        merged = merged.sort_values("date").reset_index(drop=True)
        save(merged, "btc_hashrate_difficulty")
        return merged
    return pd.DataFrame()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⑩ BTC 활성 주소수 & 거래수 (blockchain.com)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def fetch_onchain_metrics():
    print(f"\n📥 온체인 지표 (활성주소/거래수/수수료)...")
    endpoints = {
        "active_addresses": "https://api.blockchain.info/charts/n-unique-addresses?timespan=all&format=json&sampled=true",
        "tx_count":         "https://api.blockchain.info/charts/n-transactions?timespan=all&format=json&sampled=true",
        "avg_fee_usd":      "https://api.blockchain.info/charts/cost-per-transaction?timespan=all&format=json&sampled=true",
    }
    results = {}
    for name, url in endpoints.items():
        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            vals = r.json()["values"]
            df = pd.DataFrame(vals, columns=["ts", name])
            df["date"] = pd.to_datetime(df["ts"], unit="s").dt.date.astype(str)
            df[name]   = df[name].astype(float)
            df = df[["date", name]].sort_values("date").reset_index(drop=True)
            results[name] = df
            print(f"  ✅ {name}: {len(df):,}일치")
            time.sleep(0.5)
        except Exception as e:
            print(f"  ⚠️  {name} 실패: {e}")

    if results:
        merged = list(results.values())[0]
        for df in list(results.values())[1:]:
            merged = merged.merge(df, on="date", how="outer")
        merged = merged.sort_values("date").reset_index(drop=True)
        save(merged, "btc_onchain_metrics")
        return merged
    return pd.DataFrame()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⑪ BTC 가격 (CoinGecko — 일봉 보조)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def fetch_coingecko_btc_price(days: int = 3650):
    print(f"\n📥 BTC 가격 (CoinGecko 일봉 보조)...")
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart",
            params={"vs_currency": "usd", "days": days, "interval": "daily"},
            headers={"accept": "application/json"}, timeout=60
        )
        r.raise_for_status()
        data = r.json()
        df_p = pd.DataFrame(data["prices"],        columns=["ts","price"])
        df_v = pd.DataFrame(data["total_volumes"], columns=["ts","cg_volume"])
        df_m = pd.DataFrame(data["market_caps"],   columns=["ts","market_cap"])

        df = df_p.copy()
        df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
        df["cg_volume"] = df_v["cg_volume"].values
        df["market_cap"]= df_m["market_cap"].values
        df = df[["timestamp","price","cg_volume","market_cap"]].sort_values("timestamp").reset_index(drop=True)
        print(f"  ✅ {len(df):,}일치")
        save(df, "btc_coingecko_daily")
        return df
    except Exception as e:
        print(f"  ⚠️  CoinGecko BTC 가격 실패: {e}")
        return pd.DataFrame()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⑫ 거시경제 지표 (Yahoo Finance)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def fetch_yahoo_finance(days: int = 3650):
    """S&P500, NASDAQ, Gold, DXY, VIX, 미국10년물 — Yahoo Finance (yfinance)"""
    print(f"\n📥 거시경제 지표 (Yahoo Finance)...")
    try:
        import yfinance as yf
    except ImportError:
        print("  pip install yfinance 필요"); return pd.DataFrame()

    tickers = {
        "sp500":   "SPY",       # S&P 500
        "nasdaq":  "QQQ",       # NASDAQ 100
        "gold":    "GC=F",      # 금 선물
        "dxy":     "DX-Y.NYB",  # 달러 인덱스
        "vix":     "^VIX",      # VIX 변동성지수
        "us10y":   "^TNX",      # 미국 10년물 국채 금리
    }

    start = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    frames = {}
    for name, ticker in tickers.items():
        try:
            raw = yf.download(ticker, start=start, progress=False, auto_adjust=True)
            if raw.empty:
                print(f"  ⚠️  {name} ({ticker}) 없음"); continue
            s = raw["Close"]
            if hasattr(s, "squeeze"):
                s = s.squeeze()
            s.index = pd.to_datetime(s.index).strftime("%Y-%m-%d")
            frames[name] = s
            print(f"  ✅ {name} ({ticker}): {len(s):,}일치")
            time.sleep(0.3)
        except Exception as e:
            print(f"  ⚠️  {name} ({ticker}) 실패: {e}")

    if not frames:
        return pd.DataFrame()

    df = pd.DataFrame(frames)
    df.index.name = "date"
    df = df.reset_index().sort_values("date")
    save(df, "macro_yahoo_finance")
    return df


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⑬ 청산 데이터 (Binance 공개 아카이브)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def fetch_binance_liquidations(symbol: str = "BTCUSDT", days: int = 365):
    """바이낸스 선물 청산 스냅샷 일별 집계 (공개 아카이브, 무료)"""
    print(f"\n📥 청산 데이터 ({symbol}, 최근 {days}일)...")
    BASE = "https://data.binance.vision/data/futures/um/daily/liquidationSnapshot"
    rows = []
    today = date.today()

    for d in range(days):
        target = today - timedelta(days=d + 1)
        url = f"{BASE}/{symbol}/{symbol}-liquidationSnapshot-{target}.zip"
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                df_day = pd.read_csv(z.open(z.namelist()[0]), header=None,
                    names=["symbol","side","order_type","time_in_force",
                           "original_qty","price","average_price","order_status",
                           "last_fill_qty","accumulated_fill_qty","trade_time"])

            # SELL side = 롱 포지션 청산 (매도 청산)
            # BUY  side = 숏 포지션 청산 (매수 청산)
            long_df  = df_day[df_day["side"] == "SELL"].copy()
            short_df = df_day[df_day["side"] == "BUY"].copy()
            for x in [long_df, short_df]:
                x["usd_val"] = pd.to_numeric(x["average_price"], errors="coerce") * \
                               pd.to_numeric(x["accumulated_fill_qty"], errors="coerce")
            rows.append({
                "date":           str(target),
                "liq_long_usd":   long_df["usd_val"].sum(),
                "liq_short_usd":  short_df["usd_val"].sum(),
                "liq_total_usd":  long_df["usd_val"].sum() + short_df["usd_val"].sum(),
                "liq_count_long": len(long_df),
                "liq_count_short":len(short_df),
            })
            time.sleep(0.1)
        except Exception:
            continue

    if not rows:
        print("  ⚠️  청산 데이터 없음"); return pd.DataFrame()

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    print(f"  ✅ {len(df):,}일치  {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")
    save(df, f"{symbol[:3]}_liquidations_daily")
    return df


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⑭ Binance 선물 메트릭 (월별 아카이브 — OI/펀딩비/거래량)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def fetch_binance_futures_metrics(symbol: str = "BTCUSDT",
                                   interval: str = "1h",
                                   start_year: int = 2021):
    """
    Binance 선물 메트릭 아카이브
    컬럼: open_time, open, high, low, close, volume, close_time,
          quote_asset_volume, n_trades, taker_buy_base, taker_buy_quote,
          open_interest  ← 시간별 OI 포함!
    """
    print(f"\n📥 Binance 선물 메트릭 ({symbol} {interval})...")
    BASE = "https://data.binance.vision/data/futures/um/monthly/metrics"
    rows = []
    today = date.today()
    yr, mo = start_year, 1

    while (yr, mo) <= (today.year, today.month):
        url = f"{BASE}/{symbol}/{interval}/{symbol}-{interval}-metrics-{yr}-{mo:02d}.zip"
        try:
            r = requests.get(url, timeout=90)
            if r.status_code == 404:
                if mo == 12: yr += 1; mo = 1
                else: mo += 1
                continue
            r.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                df_m = pd.read_csv(z.open(z.namelist()[0]))
            rows.append(df_m)
            print(f"    {yr}-{mo:02d}: {len(df_m):,}행")
        except Exception as e:
            print(f"    ⚠️  {yr}-{mo:02d}: {e}")
        if mo == 12: yr += 1; mo = 1
        else: mo += 1
        time.sleep(0.2)

    if not rows:
        print("  ⚠️  데이터 없음"); return pd.DataFrame()

    df = pd.concat(rows, ignore_index=True)
    if "open_time" in df.columns:
        df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms")
    df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    print(f"  ✅ {len(df):,}행  {df['timestamp'].iloc[0]} ~ {df['timestamp'].iloc[-1]}")
    save(df, f"{symbol[:3]}_futures_metrics_{interval}")
    return df


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 메인
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def collect_all_indicators():
    print("=" * 60)
    print("  📊 외부 시장 지표 전체 수집 (14종)")
    print("=" * 60)

    tasks = [
        ("① 공포탐욕지수",              fetch_fear_greed,                {}),
        ("② BTC 자금조달비율",           fetch_funding_rate,              {"symbol":"BTCUSDT","days":730}),
        ("③ ETH 자금조달비율",           fetch_funding_rate,              {"symbol":"ETHUSDT","days":730}),
        ("④ BTC 미결제약정(1h)",         fetch_open_interest,             {"symbol":"BTCUSDT","interval":"1h","days":365}),
        ("⑤ BTC 롱숏비율(1h)",          fetch_long_short_ratio,          {"symbol":"BTCUSDT","period":"1h","days":365}),
        ("⑥ BTC 도미넌스/시총",          fetch_coingecko_global,          {"days":365}),
        ("⑦ 구글 트렌드",               fetch_google_trends,             {}),
        ("⑧ 해시레이트/난이도",          fetch_hash_rate,                 {}),
        ("⑨ 온체인 지표",               fetch_onchain_metrics,           {}),
        ("⑩ BTC 가격(CoinGecko)",       fetch_coingecko_btc_price,      {"days":3650}),
        ("⑪ 거시경제(Yahoo Finance)",    fetch_yahoo_finance,             {"days":3650}),
        ("⑫ BTC 청산 데이터",           fetch_binance_liquidations,      {"symbol":"BTCUSDT","days":365}),
        ("⑬ ETH 청산 데이터",           fetch_binance_liquidations,      {"symbol":"ETHUSDT","days":365}),
        ("⑭ BTC 선물메트릭(1h)",        fetch_binance_futures_metrics,   {"symbol":"BTCUSDT","interval":"1h","start_year":2021}),
    ]

    success, fail = 0, 0
    for label, fn, kwargs in tasks:
        try:
            result = fn(**kwargs)
            if result is not None and not (hasattr(result, "empty") and result.empty):
                success += 1
            else:
                fail += 1
        except Exception as e:
            print(f"  ❌ {label}: {e}")
            fail += 1

    print(f"\n{'='*60}")
    print(f"  완료: {success}개 성공 / {fail}개 실패")
    print(f"\n  저장된 파일:")
    for f in sorted(os.listdir(SAVE_DIR)):
        path = f"{SAVE_DIR}/{f}"
        kb = os.path.getsize(path) // 1024
        print(f"    {f:<48} {kb:>6}KB")


if __name__ == "__main__":
    collect_all_indicators()
