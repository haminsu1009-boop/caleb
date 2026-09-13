"""
stocks/collect_us.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
미국 주식 일봉 수집 (yfinance)

코인 대비 유리한 점:
  · 무료 수수료 브로커 기준 왕복비용이 코인(0.2%)보다 훨씬 낮다
    → timeframe_rules.py에서 확인한 비용 장벽이 크게 내려간다.
  · 종목이 수천 개라 횡단면 전략(같은 날 상위 N개 롱)이 가능하다.
    단일 자산 시계열 패턴보다 검증 사례가 많은 접근.
  · 데이터 기간이 수십 년이라 워크포워드 구간을 더 나눌 수 있다.

주의:
  · yfinance는 이 세션의 프록시에서 403으로 막힌다. GitHub Actions
    러너에서는 정상 동작하므로 .github/workflows/collect_stocks.yml 로
    실행한다.
  · auto_adjust=True — 분할·배당 조정가를 쓴다. 조정하지 않으면
    액면분할이 폭락으로 잡혀 전략이 엉뚱하게 반응한다.

사용법:
    python stocks/collect_us.py --universe sp100
    python stocks/collect_us.py --tickers AAPL MSFT NVDA --start 2000-01-01
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, time, argparse, warnings
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

OUT_DIR = os.path.join(ROOT, "data", "stocks")
os.makedirs(OUT_DIR, exist_ok=True)

# S&P 100 — 유동성이 충분해 스프레드 비용 가정이 현실적인 대형주
SP100 = """AAPL MSFT NVDA AMZN META GOOGL GOOG BRK-B AVGO TSLA JPM LLY V UNH XOM
MA JNJ PG COST HD ABBV WMT NFLX BAC KO CRM CVX MRK AMD PEP TMO LIN ADBE ORCL
ACN MCD CSCO ABT WFC IBM GE DIS CAT QCOM NOW TXN VZ INTU DHR AXP AMGN PM MS
PFE NEE UNP RTX LOW SPGI GS T BLK HON COP BKNG SYK PLD ETN LMT BMY MDT ADP
VRTX C SBUX MMC CB TJX ADI CI SO MU DE UPS BSX SCHW MDLZ PGR REGN ELV DUK
CVS ISRG ZTS BA GILD MO CL EOG SLB ITW""".split()

# 벤치마크 + 섹터 ETF
ETFS = "SPY QQQ IWM DIA VTI XLK XLF XLE XLV XLI XLY XLP XLU XLB XLRE TLT GLD".split()


def fetch(ticker: str, start: str, end: str | None) -> pd.DataFrame:
    import yfinance as yf
    df = yf.download(ticker, start=start, end=end, progress=False,
                     auto_adjust=True, threads=False)
    if df is None or df.empty:
        return pd.DataFrame()
    # yfinance 최신 버전은 MultiIndex 컬럼을 반환한다
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    df.columns = [str(c).lower() for c in df.columns]
    ren = {"date": "datetime", "adj close": "close"}
    df = df.rename(columns=ren)
    keep = ["datetime", "open", "high", "low", "close", "volume"]
    df = df[[c for c in keep if c in df.columns]]
    return df.dropna().reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", choices=["sp100", "etf", "all"], default="all")
    ap.add_argument("--tickers", nargs="*", default=None)
    ap.add_argument("--start", default="2000-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--sleep", type=float, default=0.4)
    a = ap.parse_args()

    if a.tickers:
        tickers = a.tickers
    elif a.universe == "sp100":
        tickers = SP100
    elif a.universe == "etf":
        tickers = ETFS
    else:
        tickers = ETFS + SP100

    print("=" * 76)
    print(f"  미국 주식 일봉 수집 — {len(tickers)}종목, {a.start} 이후")
    print("=" * 76)

    ok = fail = 0
    for i, t in enumerate(tickers, 1):
        path = os.path.join(OUT_DIR, f"{t}_1d.csv.gz")
        try:
            df = fetch(t, a.start, a.end)
            if df.empty:
                print(f"  [{i:3d}/{len(tickers)}] {t:8s} 데이터 없음"); fail += 1
            else:
                df.to_csv(path, index=False, compression="gzip")
                print(f"  [{i:3d}/{len(tickers)}] {t:8s} {len(df):>6,}행  "
                      f"{df['datetime'].iloc[0].date()} ~ {df['datetime'].iloc[-1].date()}")
                ok += 1
        except Exception as e:
            print(f"  [{i:3d}/{len(tickers)}] {t:8s} 실패: {str(e)[:60]}"); fail += 1
        time.sleep(a.sleep)

    print(f"\n  완료: 성공 {ok} / 실패 {fail}   저장 위치: {OUT_DIR}")


if __name__ == "__main__":
    main()
