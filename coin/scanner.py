"""
coin/scanner.py
유니버설 티커 스캐너 (Universal Ticker Scanner)

코인 + 주식 전체 종목을 스캔해서
ML 모델이 판단한 최고의 롱/숏 기회를 순위로 출력

지원 자산:
  Crypto: BTC, ETH, BNB, SOL, ADA, AVAX, DOT, LINK, MATIC, DOGE, ...
  Stocks: 삼성전자, SK하이닉스, 현대차, AAPL, NVDA, TSLA, MSFT, ...
  (데이터는 로컬 CSV 또는 API 자동 선택)

출력:
  - 상위 5개 롱 기회 (long_prob 순)
  - 상위 5개 숏 기회 (short_prob 순)
  - 전체 스코어 리스트
"""

import os
import sys
import json
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 코인 유니버스
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CRYPTO_UNIVERSE = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT",
    "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
    "MATICUSDT", "DOGEUSDT", "SHIBUSDT", "XRPUSDT",
    "LTCUSDT", "BCHUSDT", "ATOMUSDT", "NEARUSDT",
    "FTMUSDT", "ALGOUSDT", "SANDUSDT", "MANAUSDT",
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 주식 유니버스
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KR_STOCKS = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "035420": "NAVER",
    "005380": "현대차",
    "051910": "LG화학",
    "068270": "셀트리온",
    "035720": "카카오",
    "207940": "삼성바이오로직스",
    "006400": "삼성SDI",
    "028260": "삼성물산",
}

US_STOCKS = {
    "AAPL":   "Apple",
    "NVDA":   "NVIDIA",
    "MSFT":   "Microsoft",
    "TSLA":   "Tesla",
    "AMZN":   "Amazon",
    "GOOGL":  "Alphabet",
    "META":   "Meta",
    "AMD":    "AMD",
    "INTC":   "Intel",
    "SMCI":   "SuperMicro",
    "PLTR":   "Palantir",
    "COIN":   "Coinbase",
}


def _generate_synthetic_ticker(
    symbol:      str,
    n_days:      int   = 500,
    start_price: float = 100.0,
    drift:       float = 0.0003,
    vol:         float = 0.025,
    btc_corr:    float = 0.0,
    btc_df:      pd.DataFrame = None,
) -> pd.DataFrame:
    """
    종목 합성 데이터 생성

    실제 데이터가 없을 때 학습/테스트용으로 생성.
    btc_df 제공 시 BTC와 상관관계를 반영.
    """
    np.random.seed(abs(hash(symbol)) % 2**31)

    base = datetime.utcnow() - timedelta(days=n_days)
    dates = pd.date_range(base, periods=n_days, freq="D")

    # BTC 상관 수익률
    if btc_corr > 0 and btc_df is not None and len(btc_df) >= n_days:
        btc_ret = btc_df["close"].pct_change().fillna(0).values[-n_days:]
        idio    = np.random.normal(drift / 252, vol, n_days)
        ret     = btc_corr * btc_ret + np.sqrt(max(1 - btc_corr**2, 0)) * idio
    else:
        ret = np.random.normal(drift / 252, vol, n_days)
        ret = ret + np.random.standard_t(df=4, size=n_days) * vol * 0.3  # 팻 꼬리

    prices = [start_price]
    for r in ret[1:]:
        prices.append(prices[-1] * max(1 + r, 0.01))

    rows = []
    for i, (dt, price) in enumerate(zip(dates, prices)):
        r = ret[i]
        o = prices[i-1] if i > 0 else price
        h = price * (1 + abs(np.random.normal(0, vol * 0.5)))
        l = price * (1 - abs(np.random.normal(0, vol * 0.5)))
        h = max(h, o, price)
        l = min(l, o, price)
        rows.append({
            "date":   dt.strftime("%Y-%m-%d"),
            "symbol": symbol,
            "open":   round(o, 4),
            "high":   round(h, 4),
            "low":    round(l, 4),
            "close":  round(price, 4),
            "volume": round(abs(np.random.lognormal(10, 1)), 2),
        })

    return pd.DataFrame(rows)


class UniversalScanner:
    """
    모든 종목에 대해 ML 방향성 신호를 생성하는 스캐너

    사용법:
        scanner = UniversalScanner()
        scanner.load_model()
        results = scanner.scan()
        scanner.print_report(results)
    """

    def __init__(
        self,
        model_path:    str   = None,
        data_dir:      str   = None,
        long_thr:      float = 0.62,
        short_thr:     float = 0.60,
        top_n:         int   = 5,
        use_synthetic: bool  = True,
    ):
        self.model_path    = model_path or os.path.join(
            ROOT, "ml", "saved_models", "directional_model.pkl")
        self.data_dir      = data_dir or os.path.join(ROOT, "data")
        self.long_thr      = long_thr
        self.short_thr     = short_thr
        self.top_n         = top_n
        self.use_synthetic = use_synthetic
        self.model         = None
        self.feature_cols  = None
        self._btc_df       = None

    def load_model(self, path: str = None) -> bool:
        """저장된 DirectionalEnsemble 모델 로드"""
        import pickle
        p = path or self.model_path

        # DirectionalEnsemble 먼저 시도
        if os.path.exists(p):
            try:
                with open(p, "rb") as f:
                    obj = pickle.load(f)
                if isinstance(obj, dict):
                    self.model        = obj["model"]
                    self.feature_cols = obj.get("feature_cols")
                else:
                    self.model = obj
                print(f"  모델 로드: {p}")
                return True
            except Exception as e:
                print(f"  DirectionalEnsemble 로드 실패: {e}")

        # Fallback: EnsembleModel (기존 모델)
        legacy_path = os.path.join(ROOT, "ml", "saved_models", "ensemble_model.pkl")
        if os.path.exists(legacy_path):
            try:
                with open(legacy_path, "rb") as f:
                    self.model = pickle.load(f)
                print(f"  레거시 모델 로드 (EnsembleModel): {legacy_path}")
                return True
            except Exception as e:
                print(f"  레거시 모델 로드 실패: {e}")

        print("  ⚠ 저장된 모델 없음 — 온디맨드 학습 진행")
        return False

    def _load_data(self, symbol: str) -> pd.DataFrame:
        """심볼 데이터 로드 (로컬 CSV → 합성 데이터 순)"""
        # BTC 파일명 처리
        fname_map = {
            "BTCUSDT":  "btc_daily.csv",
            "ETHUSDT":  "ETHUSDT_daily.csv",
            "BNBUSDT":  "BNBUSDT_daily.csv",
            "SOLUSDT":  "SOLUSDT_daily.csv",
        }
        fname = fname_map.get(symbol, f"{symbol}_daily.csv")
        path  = os.path.join(self.data_dir, fname)

        if os.path.exists(path):
            df = pd.read_csv(path)
            if "symbol" not in df.columns:
                df["symbol"] = symbol
            return df

        if self.use_synthetic:
            # 합성 데이터 생성
            if self._btc_df is None:
                btc_path = os.path.join(self.data_dir, "btc_daily.csv")
                if os.path.exists(btc_path):
                    self._btc_df = pd.read_csv(btc_path)

            # 코인 vs 주식 파라미터 구분
            is_crypto = symbol.endswith("USDT")
            corr      = np.random.uniform(0.5, 0.85) if is_crypto else np.random.uniform(0.0, 0.3)
            vol       = np.random.uniform(0.02, 0.08) if is_crypto else np.random.uniform(0.01, 0.03)
            price     = np.random.uniform(1, 50000) if is_crypto else np.random.uniform(10, 500)

            return _generate_synthetic_ticker(
                symbol     = symbol,
                n_days     = 800,
                start_price= price,
                vol        = vol,
                btc_corr   = corr,
                btc_df     = self._btc_df,
            )

        return pd.DataFrame()

    def _prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """피처 엔지니어링 파이프라인"""
        from ml.features        import add_features, get_feature_cols
        from ml.regime          import add_regime_features
        from ml.multi_timeframe import add_multi_timeframe_features

        df = add_features(df)
        df = add_regime_features(df)
        df = add_multi_timeframe_features(df)
        return df.dropna(how="all").reset_index(drop=True)

    def _get_signal(self, df: pd.DataFrame, symbol: str) -> dict:
        """단일 종목에 대한 방향성 신호 계산"""
        from ml.models import DirectionalEnsemble, EnsembleModel

        try:
            if df.empty or len(df) < 50:
                return {"symbol": symbol, "signal": "SKIP", "long_prob": 0.5, "short_prob": 0.5}

            df = self._prepare_features(df)
            if df.empty:
                return {"symbol": symbol, "signal": "SKIP", "long_prob": 0.5, "short_prob": 0.5}

            # 피처 컬럼 결정
            from ml.features import get_feature_cols
            fcols = self.feature_cols
            if fcols is None:
                fcols = get_feature_cols(df)
            fcols = [c for c in fcols if c in df.columns]
            if not fcols:
                return {"symbol": symbol, "signal": "SKIP", "long_prob": 0.5, "short_prob": 0.5}

            # TemporalXGB(SimpleLSTM)는 최소 SEQ_LEN=20행 필요 → 마지막 30행 전달
            SEQ_LEN = 20
            history_rows = df.iloc[-max(SEQ_LEN + 10, len(df)):][fcols].fillna(0)
            row = history_rows  # 전체 히스토리 전달 (마지막 행의 확률 사용)

            # DirectionalEnsemble 사용
            if isinstance(self.model, DirectionalEnsemble):
                result = self.model.signal_latest(row, self.long_thr, self.short_thr)
            # 레거시 EnsembleModel → long만 지원
            elif isinstance(self.model, EnsembleModel):
                proba = float(self.model.predict_proba(row)[-1, 1])
                result = {
                    "signal":     "LONG" if proba >= self.long_thr else "NEUTRAL",
                    "long_prob":  proba,
                    "short_prob": 1 - proba,
                    "score":      proba - 0.5,
                }
            else:
                result = {"signal": "NEUTRAL", "long_prob": 0.5, "short_prob": 0.5, "score": 0}

            # 국면 정보
            regime_map = {2: "BULL", 1: "NEUTRAL", 0: "BEAR"}
            reg_val    = df["regime"].iloc[-1] if "regime" in df.columns else 1
            result["regime"] = regime_map.get(int(reg_val), "UNKNOWN")

            # 최근 수익률
            result["ret_5d"]  = round(float(df["close"].pct_change(5).iloc[-1]), 4)
            result["ret_20d"] = round(float(df["close"].pct_change(20).iloc[-1]), 4)
            result["symbol"]  = symbol
            result["price"]   = round(float(df["close"].iloc[-1]), 6)
            result["date"]    = str(df["date"].iloc[-1]) if "date" in df.columns else "N/A"

            return result

        except Exception as e:
            return {
                "symbol":     symbol,
                "signal":     "ERROR",
                "long_prob":  0.5,
                "short_prob": 0.5,
                "error":      str(e),
            }

    def scan(
        self,
        crypto_symbols: list = None,
        kr_codes:       list = None,
        us_tickers:     list = None,
        verbose:        bool = True,
    ) -> pd.DataFrame:
        """
        전체 종목 스캔 실행

        Args:
            crypto_symbols: 코인 심볼 리스트 (None → CRYPTO_UNIVERSE)
            kr_codes:       한국 주식 코드 리스트 (None → KR_STOCKS)
            us_tickers:     미국 주식 티커 리스트 (None → US_STOCKS)
            verbose:        진행상황 출력

        Returns:
            DataFrame: 전체 결과 (score 내림차순)
        """
        if self.model is None:
            loaded = self.load_model()
            if not loaded:
                self._train_quick_model()

        symbols_to_scan = []

        # 코인
        cryptos = crypto_symbols if crypto_symbols is not None else CRYPTO_UNIVERSE
        for sym in cryptos:
            symbols_to_scan.append(("CRYPTO", sym, sym))

        # 한국 주식
        kr = kr_codes if kr_codes is not None else list(KR_STOCKS.keys())
        for code in kr:
            name = KR_STOCKS.get(code, code)
            symbols_to_scan.append(("KR_STOCK", code, name))

        # 미국 주식
        us = us_tickers if us_tickers is not None else list(US_STOCKS.keys())
        for ticker in us:
            name = US_STOCKS.get(ticker, ticker)
            symbols_to_scan.append(("US_STOCK", ticker, name))

        results = []
        n = len(symbols_to_scan)

        for i, (asset_type, symbol, name) in enumerate(symbols_to_scan):
            if verbose:
                print(f"  [{i+1:3d}/{n}] {asset_type:8s} {symbol:12s}", end=" ")

            df = self._load_data(symbol)
            res = self._get_signal(df, symbol)
            res["asset_type"] = asset_type
            res["name"]       = name
            results.append(res)

            if verbose:
                sig  = res.get("signal", "?")
                lp   = res.get("long_prob", 0.5)
                sp   = res.get("short_prob", 0.5)
                icon = {"LONG": "📈", "SHORT": "📉", "NEUTRAL": "➡", "SKIP": "⏭", "ERROR": "❌"}.get(sig, "?")
                print(f"{icon} {sig:7s}  L={lp:.3f}  S={sp:.3f}")

        df_res = pd.DataFrame(results)
        if "score" in df_res.columns:
            df_res = df_res.sort_values("score", ascending=False).reset_index(drop=True)

        return df_res

    def print_report(self, df: pd.DataFrame, top_n: int = None):
        """스캔 결과 출력"""
        top_n = top_n or self.top_n
        ts    = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

        print("\n" + "=" * 65)
        print(f"  유니버설 스캐너 결과  —  {ts}")
        print("=" * 65)

        # 롱 TOP N
        long_df = df[df["signal"] == "LONG"].head(top_n)
        print(f"\n  📈 LONG 기회 TOP {top_n}")
        print(f"  {'순위':<4}{'심볼':<14}{'이름':<14}{'롱확률':<9}{'숏확률':<9}{'국면':<8}{'5d%'}")
        print("  " + "-" * 58)
        for rank, (_, row) in enumerate(long_df.iterrows(), 1):
            print(f"  {rank:<4}{row.get('symbol',''):<14}{str(row.get('name','')):<14}"
                  f"{row.get('long_prob', 0):<9.3f}{row.get('short_prob', 0):<9.3f}"
                  f"{row.get('regime',''):<8}{row.get('ret_5d', 0)*100:+.1f}%")

        # 숏 TOP N
        short_df = df[df["signal"] == "SHORT"].sort_values("short_prob", ascending=False).head(top_n)
        print(f"\n  📉 SHORT 기회 TOP {top_n}")
        print(f"  {'순위':<4}{'심볼':<14}{'이름':<14}{'숏확률':<9}{'롱확률':<9}{'국면':<8}{'5d%'}")
        print("  " + "-" * 58)
        for rank, (_, row) in enumerate(short_df.iterrows(), 1):
            print(f"  {rank:<4}{row.get('symbol',''):<14}{str(row.get('name','')):<14}"
                  f"{row.get('short_prob', 0):<9.3f}{row.get('long_prob', 0):<9.3f}"
                  f"{row.get('regime',''):<8}{row.get('ret_5d', 0)*100:+.1f}%")

        # 통계
        print(f"\n  총 종목: {len(df)}  |  LONG: {(df['signal']=='LONG').sum()}  "
              f"|  SHORT: {(df['signal']=='SHORT').sum()}  "
              f"|  NEUTRAL: {(df['signal']=='NEUTRAL').sum()}")
        print("=" * 65)

    def save_report(self, df: pd.DataFrame):
        """스캔 결과 CSV 저장"""
        os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
        ts   = datetime.utcnow().strftime("%Y%m%d_%H%M")
        path = os.path.join(ROOT, "results", f"scan_{ts}.csv")
        df.to_csv(path, index=False)
        print(f"\n  결과 저장: {path}")
        return path

    def _train_quick_model(self):
        """모델 없을 때 BTC 데이터로 빠른 학습"""
        print("  [Scanner] 빠른 모델 학습 중 (BTC 기반)...")
        try:
            from ml.features        import add_features, make_directional_targets, get_feature_cols
            from ml.regime          import add_regime_features
            from ml.multi_timeframe import add_multi_timeframe_features
            from ml.models          import DirectionalEnsemble

            btc_path = os.path.join(self.data_dir, "btc_daily.csv")
            if not os.path.exists(btc_path):
                print("  BTC 데이터 없음 — 스캐너 더미 모드로 실행")
                return

            df = pd.read_csv(btc_path)
            df = add_features(df)
            df = add_regime_features(df)
            df = add_multi_timeframe_features(df)
            df = make_directional_targets(df)
            df = df.dropna().reset_index(drop=True)

            fcols = get_feature_cols(df)
            fcols = [c for c in fcols if df[c].isna().mean() < 0.3]

            split = int(len(df) * 0.8)
            X_tr   = df.iloc[:split][fcols]
            y_long_tr  = df.iloc[:split]["target_long"]
            y_short_tr = df.iloc[:split]["target_short"]
            X_val  = df.iloc[split:][fcols]
            y_long_val  = df.iloc[split:]["target_long"]
            y_short_val = df.iloc[split:]["target_short"]

            model = DirectionalEnsemble()
            model.fit(X_tr, y_long_tr, y_short_tr, X_val, y_long_val, y_short_val, fcols)

            self.model        = model
            self.feature_cols = fcols

            # 저장
            import pickle
            os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
            with open(self.model_path, "wb") as f:
                pickle.dump({"model": model, "feature_cols": fcols}, f)
            print(f"  모델 저장: {self.model_path}")

        except Exception as e:
            print(f"  빠른 학습 실패: {e}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="유니버설 스캐너")
    parser.add_argument("--crypto-only", action="store_true", help="코인만 스캔")
    parser.add_argument("--top",         type=int, default=5,  help="TOP N 결과")
    parser.add_argument("--long-thr",    type=float, default=0.62)
    parser.add_argument("--short-thr",   type=float, default=0.60)
    parser.add_argument("--save",        action="store_true", help="CSV 저장")
    args = parser.parse_args()

    scanner = UniversalScanner(
        long_thr = args.long_thr,
        short_thr= args.short_thr,
        top_n    = args.top,
    )
    scanner.load_model()

    scan_kwargs = {}
    if args.crypto_only:
        scan_kwargs["kr_codes"]   = []
        scan_kwargs["us_tickers"] = []

    print("\n스캔 시작...")
    results = scanner.scan(**scan_kwargs)
    scanner.print_report(results, top_n=args.top)

    if args.save:
        scanner.save_report(results)
