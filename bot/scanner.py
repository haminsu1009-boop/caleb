"""
bot/scanner.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
알트코인 실시간 스캐너

기능:
  1. RSI 상승 다이버전스 감지
     - 가격: 최근 N봉 최저가가 이전 최저보다 낮음
     - RSI:  그 시점의 RSI는 이전보다 높음
     - 조건: 볼린저밴드 상단 이내 (과매수 아님)

  2. 골든크로스 감지
     - MA50이 MA200을 최근 3봉 이내에 상향 돌파
     - 또는 MA50 > MA200 상태에서 가격이 MA50 부근 지지

  3. BTC 4.5%+ 일봉 마감 알림
     - 직전 10일 낙폭 -10% 이내일 때만 유효 신호
     - 2일 연속이면 강한 신호 (★★)

실행:
  python bot/scanner.py                    # 1회 스캔
  python bot/scanner.py --watch 300        # 5분마다 반복 스캔
  python bot/scanner.py --symbol SOLUSDT   # 특정 심볼만

Bybit 공개 API 사용 (인증 불필요)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import argparse, time, sys, os
from datetime import datetime, timezone
from typing import Optional
import numpy as np
import pandas as pd

# ── Bybit API ─────────────────────────────────────────────────
try:
    from pybit.unified_trading import HTTP as BybitHTTP
    _PYBIT_OK = True
except ImportError:
    _PYBIT_OK = False

# ── 기본 스캔 대상 (Bybit USDT 선물) ──────────────────────────
DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "MATICUSDT",
    "LINKUSDT", "UNIUSDT", "ATOMUSDT", "LTCUSDT", "NEARUSDT",
    "APTUSDT", "ARBUSDT", "OPUSDT", "INJUSDT", "SUIUSDT",
    "SEIUSDT", "TIAUSDT", "JUPUSDT", "WIFUSDT", "ONDOUSDT",
]

# ── 설정 ───────────────────────────────────────────────────────
INTERVAL_MAP = {
    "1d": {"bybit": "D",  "bars": 250},   # 골든크로스 200일 필요
    "4h": {"bybit": "240","bars": 150},
    "1h": {"bybit": "60", "bars": 60 },
}
BTC_THRESHOLD = 0.045   # 4.5%


# ══════════════════════════════════════════════════════════════
#  데이터 수집
# ══════════════════════════════════════════════════════════════

def fetch_ohlcv(session: "BybitHTTP", symbol: str, interval: str, limit: int) -> pd.DataFrame:
    """Bybit에서 OHLCV 가져오기"""
    bybit_iv = INTERVAL_MAP[interval]["bybit"]
    resp = session.get_kline(
        category="linear",
        symbol=symbol,
        interval=bybit_iv,
        limit=limit,
    )
    if resp.get("retCode") != 0:
        return pd.DataFrame()

    rows = resp["result"]["list"]   # 최신봉이 앞에 있음
    rows = rows[::-1]               # 오래된봉 → 최신봉 순서로
    df = pd.DataFrame(rows, columns=["timestamp","open","high","low","close","volume","turnover"])
    for col in ["open","high","low","close","volume"]:
        df[col] = pd.to_numeric(df[col])
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype(np.int64), unit="ms")
    return df.reset_index(drop=True)


# ══════════════════════════════════════════════════════════════
#  지표 계산
# ══════════════════════════════════════════════════════════════

def _rsi(series: pd.Series, n: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(n).mean()
    loss  = (-delta.clip(upper=0)).rolling(n).mean()
    rs    = gain / (loss + 1e-9)
    return 100 - 100 / (1 + rs)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    h = df["high"]
    l = df["low"]
    o = df["open"]

    # 이동평균
    df["ma50"]  = c.rolling(50).mean()
    df["ma200"] = c.rolling(200).mean()

    # 볼린저밴드 (20일)
    sma20       = c.rolling(20).mean()
    std20       = c.rolling(20).std()
    df["bb_up"] = sma20 + 2 * std20
    df["bb_lo"] = sma20 - 2 * std20
    df["bb_pos"]= (c - df["bb_lo"]) / (df["bb_up"] - df["bb_lo"] + 1e-9)

    # RSI
    df["rsi14"] = _rsi(c, 14)

    # 일봉 수익률 (시가→종가)
    df["ret"]   = (c - o) / o
    df["cc_ret"]= c.pct_change()           # 어제종가→오늘종가
    df["cc10"]  = c.pct_change(10)         # 10일 누적

    # 저점 비교용 (로컬 저점 찾기)
    df["ll_14"] = l.rolling(14).min()      # 14봉 최저

    return df


# ══════════════════════════════════════════════════════════════
#  패턴 감지
# ══════════════════════════════════════════════════════════════

def detect_golden_cross(df: pd.DataFrame) -> dict | None:
    """
    골든크로스 감지
    - 최근 3봉 이내에 MA50이 MA200을 상향 돌파
    - 또는 이미 골든크로스 상태 + 가격이 MA50 ±2% 범위에서 지지받는 중
    """
    if df["ma200"].isna().all() or len(df) < 201:
        return None

    ma50  = df["ma50"].values
    ma200 = df["ma200"].values
    c     = df["close"].values

    # 최근 3봉 이내 골든크로스 발생 여부
    for i in range(-3, 0):
        if (ma50[i] > ma200[i]) and (ma50[i-1] <= ma200[i-1]):
            return {
                "type": "GOLDEN_CROSS",
                "strength": "★★★ 방금 골든크로스",
                "ma50": round(float(ma50[-1]), 4),
                "ma200": round(float(ma200[-1]), 4),
                "price": round(float(c[-1]), 4),
                "bars_ago": abs(i) - 1,
            }

    # 골든크로스 유지 상태 + 가격이 MA50 근처 지지
    if ma50[-1] > ma200[-1]:
        dist_from_ma50 = (c[-1] - ma50[-1]) / ma50[-1]
        if -0.03 <= dist_from_ma50 <= 0.02:   # MA50 ±3% 이내
            return {
                "type": "GOLDEN_SUPPORT",
                "strength": "★★ MA50 지지 (골든크로스 유지)",
                "ma50": round(float(ma50[-1]), 4),
                "ma200": round(float(ma200[-1]), 4),
                "price": round(float(c[-1]), 4),
                "dist_pct": round(dist_from_ma50 * 100, 2),
            }

    return None


def detect_rsi_divergence(df: pd.DataFrame) -> dict | None:
    """
    RSI 상승 다이버전스 감지
    - 최근 30봉 내에서 가격 저점이 낮아지는데 RSI는 올라가는 패턴
    - 볼린저밴드 상단 이내 (과매수 아님)
    - 과매도 구간 (RSI < 45) 에서 더 유의미
    """
    if len(df) < 40:
        return None
    if df["rsi14"].isna().iloc[-1]:
        return None

    # 볼린저 상단 돌파 여부 확인 (돌파하면 무효)
    if df["bb_pos"].iloc[-1] > 0.95:
        return None

    c    = df["close"].values
    l    = df["low"].values
    rsi  = df["rsi14"].values

    # 최근 30봉 내에서 저점 탐색
    window = 30
    recent_l   = l[-window:]
    recent_rsi = rsi[-window:]
    recent_c   = c[-window:]

    # 현재가 위치 (최근봉 기준)
    curr_low = recent_l[-1]
    curr_rsi = recent_rsi[-1]

    # 이전 구간 (10~30봉 전)에서 저점 찾기
    prev_slice_l   = recent_l[:20]
    prev_slice_rsi = recent_rsi[:20]

    if len(prev_slice_l) == 0:
        return None

    prev_min_idx = int(np.argmin(prev_slice_l))
    prev_low     = prev_slice_l[prev_min_idx]
    prev_rsi_at_low = prev_slice_rsi[prev_min_idx]

    # 다이버전스 조건:
    # 가격: 지금 저점 < 이전 저점 (더 낮아짐)
    # RSI:  지금 RSI > 이전 RSI (더 높아짐)
    price_lower = curr_low < prev_low * 0.998   # 0.2% 이상 낮아야 의미
    rsi_higher  = curr_rsi > prev_rsi_at_low + 1.0  # 1포인트 이상 높아야

    if price_lower and rsi_higher:
        rsi_now = float(curr_rsi)
        strength = "★★★ 강한 다이버전스" if rsi_now < 40 else \
                   "★★ 다이버전스" if rsi_now < 50 else \
                   "★ 약한 다이버전스"
        return {
            "type": "RSI_DIVERGENCE",
            "strength": strength,
            "curr_low": round(float(curr_low), 4),
            "prev_low": round(float(prev_low), 4),
            "curr_rsi": round(rsi_now, 1),
            "prev_rsi": round(float(prev_rsi_at_low), 1),
            "bb_pos": round(float(df["bb_pos"].iloc[-1]), 2),
        }

    return None


def detect_btc_signal(df: pd.DataFrame) -> dict | None:
    """
    BTC 4.5%+ 일봉 마감 감지
    - 오늘 4.5%+ 마감 + 직전 10일 낙폭 -10% 이내
    - 어제도 4.5%+ 이면 2연속 강한 신호
    """
    if len(df) < 12:
        return None

    last  = df.iloc[-1]
    prev  = df.iloc[-2]
    cc10  = float(df["cc10"].iloc[-1])

    today_ret = float(last["ret"])
    prev_ret  = float(prev["ret"])

    if today_ret < BTC_THRESHOLD:
        return None

    # 예외: 직전 낙폭 심하면 무효
    if cc10 < -0.10:
        return {
            "type": "BTC_BIG_UP_INVALID",
            "strength": "❌ 무효 (직전10일 낙폭 " + f"{cc10*100:.1f}%)",
            "ret": round(today_ret * 100, 2),
            "cc10": round(cc10 * 100, 1),
        }

    consec = prev_ret >= BTC_THRESHOLD
    strength = "★★★ 2일 연속 4.5%+ (72% 3봉 WR)" if consec else "★★ 4.5%+ 마감 (58% WR)"

    return {
        "type": "BTC_BIG_UP",
        "strength": strength,
        "ret": round(today_ret * 100, 2),
        "cc10": round(cc10 * 100, 1),
        "consecutive": consec,
    }


# ══════════════════════════════════════════════════════════════
#  메인 스캔
# ══════════════════════════════════════════════════════════════

def scan_symbol(session: "BybitHTTP", symbol: str, intervals: list[str]) -> list[dict]:
    """하나의 심볼을 여러 인터벌에서 스캔"""
    results = []

    for iv in intervals:
        limit = INTERVAL_MAP[iv]["bars"]
        df = fetch_ohlcv(session, symbol, iv, limit)
        if df.empty or len(df) < 50:
            continue

        df = add_indicators(df)

        # 골든크로스
        gc = detect_golden_cross(df)
        if gc:
            results.append({**gc, "symbol": symbol, "interval": iv})

        # RSI 다이버전스
        div = detect_rsi_divergence(df)
        if div:
            results.append({**div, "symbol": symbol, "interval": iv})

        # BTC 전용: 4.5%+ 신호
        if symbol == "BTCUSDT" and iv == "1d":
            btc = detect_btc_signal(df)
            if btc:
                results.append({**btc, "symbol": symbol, "interval": iv})

    return results


def print_result(r: dict):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sym  = r.get("symbol","")
    iv   = r.get("interval","")
    tp   = r.get("type","")
    st   = r.get("strength","")

    if tp == "GOLDEN_CROSS":
        print(f"[{ts}] 🌟 {sym} {iv} {st}")
        print(f"      MA50={r['ma50']:,.2f}  MA200={r['ma200']:,.2f}  Price={r['price']:,.2f}")

    elif tp == "GOLDEN_SUPPORT":
        print(f"[{ts}] 💛 {sym} {iv} {st}")
        print(f"      MA50={r['ma50']:,.2f}  Price={r['price']:,.2f}  (MA50 대비 {r['dist_pct']:+.1f}%)")

    elif tp == "RSI_DIVERGENCE":
        print(f"[{ts}] 📈 {sym} {iv} {st}")
        print(f"      저점: {r['prev_low']:,.4f} → {r['curr_low']:,.4f}  "
              f"RSI: {r['prev_rsi']:.1f} → {r['curr_rsi']:.1f}  BB위치: {r['bb_pos']:.0%}")

    elif tp == "BTC_BIG_UP":
        print(f"[{ts}] 🚀 BTC {iv} {st}")
        print(f"      당일수익: +{r['ret']:.2f}%  직전10일: {r['cc10']:+.1f}%")
        if r.get("consecutive"):
            print(f"      → 연속 신호: 알트 매수 적극 고려")

    elif tp == "BTC_BIG_UP_INVALID":
        print(f"[{ts}] ⚠️  BTC {iv} {r['strength']}")
        print(f"      당일수익: +{r['ret']:.2f}%  → 진입 보류")

    else:
        print(f"[{ts}] {sym} {iv} {tp}: {st}")


def run_scan(
    symbols: list[str],
    intervals: list[str],
    testnet: bool = False,
    api_key: str = "",
    api_secret: str = "",
) -> list[dict]:
    """전체 스캔 실행"""
    if not _PYBIT_OK:
        print("❌ pybit 미설치: pip install pybit>=5.7.0")
        return []

    session = BybitHTTP(
        testnet=testnet,
        api_key=api_key or None,
        api_secret=api_secret or None,
    )

    all_results = []
    print(f"\n{'='*60}")
    print(f"  스캔 시작: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  심볼: {len(symbols)}개  인터벌: {intervals}")
    print(f"{'='*60}")

    for i, sym in enumerate(symbols, 1):
        try:
            results = scan_symbol(session, sym, intervals)
            for r in results:
                print_result(r)
                all_results.append(r)
            # API rate limit 보호
            time.sleep(0.12)
        except Exception as e:
            print(f"  [{sym}] 오류: {e}")

    if not all_results:
        print("  → 현재 조건 만족하는 심볼 없음")

    print(f"\n  완료: {len(all_results)}개 신호 발견")
    return all_results


# ══════════════════════════════════════════════════════════════
#  로컬 데이터 모드 (인터넷 없이 히스토리 스캔)
# ══════════════════════════════════════════════════════════════

def run_local_scan(symbols: list[str], intervals: list[str], data_dir: str = "data") -> list[dict]:
    """
    로컬 CSV 파일로 스캔 (개발/테스트용)
    data/BTCUSDT_1d_*.csv.gz 형태의 파일 사용
    """
    import glob as _glob

    all_results = []
    print(f"\n{'='*60}")
    print(f"  [로컬 모드] 스캔: {symbols}  {intervals}")
    print(f"{'='*60}")

    for sym in symbols:
        for iv in intervals:
            pattern = os.path.join(data_dir, f"{sym}_{iv}_*.csv.gz")
            files = sorted(_glob.glob(pattern))
            if not files:
                continue

            dfs = []
            for f in files:
                try:
                    tmp = pd.read_csv(f, compression='gzip')
                    dfs.append(tmp)
                except Exception:
                    pass
            if not dfs:
                continue

            df = pd.concat(dfs, ignore_index=True)
            ts_col = next((c for c in df.columns if 'time' in c.lower()), df.columns[0])
            df[ts_col] = pd.to_datetime(df[ts_col], errors='coerce')
            df = df.dropna(subset=[ts_col]).sort_values(ts_col)
            df['date'] = df[ts_col].dt.date
            df = df.drop_duplicates('date', keep='last').reset_index(drop=True)

            # 컬럼명 표준화
            rename = {}
            for col in df.columns:
                if col.lower() in ['open','high','low','close','volume']:
                    rename[col] = col.lower()
            df = df.rename(columns=rename)

            if not all(c in df.columns for c in ['open','high','low','close']):
                continue

            df = add_indicators(df)

            gc = detect_golden_cross(df)
            if gc:
                r = {**gc, "symbol": sym, "interval": iv}
                print_result(r)
                all_results.append(r)

            div = detect_rsi_divergence(df)
            if div:
                r = {**div, "symbol": sym, "interval": iv}
                print_result(r)
                all_results.append(r)

            if sym == "BTCUSDT" and iv == "1d":
                btc = detect_btc_signal(df)
                if btc:
                    r = {**btc, "symbol": sym, "interval": iv}
                    print_result(r)
                    all_results.append(r)

    if not all_results:
        print("  → 현재 조건 만족하는 심볼 없음")
    print(f"\n  완료: {len(all_results)}개 신호")
    return all_results


# ══════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="알트코인 스캐너 — 골든크로스 + RSI 다이버전스")
    parser.add_argument("--symbols", nargs="*", default=None,
                        help="스캔할 심볼 (기본: 25개 주요 알트)")
    parser.add_argument("--intervals", nargs="*", default=["1d", "4h"],
                        help="스캔 인터벌 (기본: 1d 4h)")
    parser.add_argument("--watch", type=int, default=0,
                        help="반복 스캔 간격(초), 0=1회만 (예: --watch 300)")
    parser.add_argument("--testnet", action="store_true",
                        help="Bybit 테스트넷 사용")
    parser.add_argument("--local", action="store_true",
                        help="로컬 CSV 데이터로 스캔 (인터넷 불필요)")
    parser.add_argument("--data-dir", default="data",
                        help="로컬 데이터 디렉토리")
    args = parser.parse_args()

    symbols  = args.symbols or DEFAULT_SYMBOLS
    intervals = args.intervals

    api_key    = os.environ.get("BYBIT_API_KEY", "")
    api_secret = os.environ.get("BYBIT_SECRET", "")

    def do_scan():
        if args.local:
            run_local_scan(symbols, intervals, args.data_dir)
        else:
            run_scan(symbols, intervals, args.testnet, api_key, api_secret)

    if args.watch > 0:
        print(f"📡 {args.watch}초마다 반복 스캔 (Ctrl+C로 종료)")
        while True:
            do_scan()
            print(f"\n  다음 스캔까지 {args.watch}초 대기...\n")
            try:
                time.sleep(args.watch)
            except KeyboardInterrupt:
                print("\n종료")
                break
    else:
        do_scan()


if __name__ == "__main__":
    main()
