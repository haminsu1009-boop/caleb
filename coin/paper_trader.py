"""
coin/paper_trader.py
페이퍼 트레이딩 — 가짜 돈으로 실전처럼 시뮬레이션

실계좌 연동 없이 ML 신호 기반 자동매매를 시뮬레이션
수익/손실을 실시간으로 추적하고 signals.log에 기록
"""

import os
import sys
import json
import time
import pickle
import logging
import numpy as np
import pandas as pd
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from coin.risk     import RiskManager
from coin.notifier import (notify_signal, notify_trade, notify_close,
                            notify_daily_report, notify_start, notify_error)
from ml.features   import add_features, get_feature_cols

LOG_FILE      = os.path.join(ROOT, "signals.log")
MODEL_DIR     = os.path.join(ROOT, "ml", "saved_models")
RESULT_DIR    = os.path.join(ROOT, "results")
os.makedirs(RESULT_DIR, exist_ok=True)

COINS            = os.getenv("COINS", "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT").split(",")
SIGNAL_THRESHOLD = float(os.getenv("SIGNAL_THRESHOLD", "0.65"))
CHECK_INTERVAL   = 3600          # 1시간
INITIAL_CAPITAL  = 10_000.0      # 초기 가상 자본 (USD)


# ── 로거 ──────────────────────────────────────
def setup_logger() -> logging.Logger:
    logger = logging.getLogger("paper_trader")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


# ── 모델 로드 ─────────────────────────────────
def load_model():
    model_path   = os.path.join(MODEL_DIR, "ensemble_model.pkl")
    feature_path = os.path.join(MODEL_DIR, "feature_cols.pkl")
    if not os.path.exists(model_path):
        raise FileNotFoundError("모델 없음 — python ml/trainer.py 먼저 실행")
    with open(model_path,   "rb") as f: model = pickle.load(f)
    with open(feature_path, "rb") as f: feature_cols = pickle.load(f)
    return model, feature_cols


# ── 데이터 수집 (오프라인 폴백 포함) ────────────
def get_data(symbol: str, feature_cols: list) -> pd.DataFrame | None:
    # 실시간 시도
    try:
        from coin.data_fetcher import fetch_klines
        df = fetch_klines(symbol, "1d", 300)
        if not df.empty:
            df = add_features(df)
            missing = [c for c in feature_cols if c not in df.columns]
            for m in missing: df[m] = 0.0
            return df
    except Exception:
        pass

    # 오프라인 폴백
    local_files = [
        os.path.join(ROOT, "data", f"{symbol}_daily.csv"),
        os.path.join(ROOT, "data", "btc_daily.csv"),
    ]
    for path in local_files:
        if os.path.exists(path):
            df = pd.read_csv(path)
            df = add_features(df)
            missing = [c for c in feature_cols if c not in df.columns]
            for m in missing: df[m] = 0.0
            return df
    return None


# ── 신호 생성 ─────────────────────────────────
def get_signal(symbol: str, model, feature_cols: list) -> dict:
    df = get_data(symbol, feature_cols)
    if df is None:
        return {"symbol": symbol, "signal": "NO_DATA", "proba": 0.0, "price": 0.0}

    clean = df.dropna(subset=feature_cols[:5])
    if clean.empty:
        return {"symbol": symbol, "signal": "NO_DATA", "proba": 0.0, "price": 0.0}

    X     = clean[feature_cols].fillna(0)
    proba = model.predict_proba(X)[:, 1]
    last_proba = float(proba[-1]) if not np.isnan(proba[-1]) else 0.0
    last_price = float(clean["close"].iloc[-1])

    return {
        "symbol": symbol,
        "proba":  round(last_proba, 4),
        "price":  last_price,
        "signal": "BUY" if last_proba >= SIGNAL_THRESHOLD else "HOLD",
    }


# ── 메인 루프 ─────────────────────────────────
def run_paper_trading():
    logger  = setup_logger()
    model, feature_cols = load_model()
    risk    = RiskManager(INITIAL_CAPITAL)
    capital = INITIAL_CAPITAL

    logger.info("=" * 55)
    logger.info("페이퍼 트레이딩 봇 시작")
    logger.info(f"초기 자본: ${capital:,.0f}  |  코인: {', '.join(COINS)}")
    logger.info(f"신호 임계값: {SIGNAL_THRESHOLD}  |  체크 주기: {CHECK_INTERVAL}s")
    logger.info("=" * 55)

    notify_start("페이퍼 트레이딩", COINS, capital)

    cycle = 0

    while True:
        cycle += 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"\n[사이클 {cycle}] {now}")

        # ── 현재 포지션 손절/익절 체크 ──────────
        for symbol in list(risk.open_positions.keys()):
            try:
                sig = get_signal(symbol, model, feature_cols)
                price = sig["price"]
                if price <= 0: continue

                if risk.should_stop_loss(symbol, price):
                    pnl = risk.close_position(symbol, price)
                    logger.info(f"  [손절] {symbol}  가격=${price:,.2f}  PnL=${pnl:+.2f}")
                    notify_close(symbol, pnl, pnl/risk.open_positions.get(symbol, {}).get("usdt_invested", 1)*100, "손절")
                    capital += pnl

                elif risk.should_take_profit(symbol, price):
                    pnl = risk.close_position(symbol, price)
                    logger.info(f"  [익절] {symbol}  가격=${price:,.2f}  PnL=${pnl:+.2f}")
                    notify_close(symbol, pnl, pnl/100, "익절")
                    capital += pnl

                else:
                    upnl = risk.unrealized_pnl(symbol, price)
                    pos  = risk.open_positions[symbol]
                    pct  = (price / pos["entry_price"] - 1) * 100
                    logger.info(f"  [보유] {symbol}  가격=${price:,.2f}  "
                                f"미실현={pct:+.1f}%  (${upnl:+.2f})")
            except Exception as e:
                logger.error(f"  [포지션 체크 오류] {symbol}: {e}")

        # ── 새 신호 체크 ─────────────────────────
        logger.info("  신호 스캔 중...")
        for symbol in COINS:
            if symbol in risk.open_positions:
                continue  # 이미 보유 중

            try:
                sig = get_signal(symbol, model, feature_cols)
                logger.info(f"  {symbol}: 확률={sig['proba']*100:.1f}%  "
                            f"가격=${sig['price']:,.2f}  신호={sig['signal']}")

                if sig["signal"] != "BUY":
                    continue

                can, reason = risk.can_trade(capital)
                if not can:
                    logger.info(f"    → 거래 불가: {reason}")
                    continue

                # 매수 실행 (페이퍼)
                invest = risk.position_size(capital, win_rate=0.55)
                if invest < 10:
                    logger.info(f"    → 투자 금액 너무 작음 (${invest:.2f})")
                    continue

                price = sig["price"]
                qty   = round(invest / price, 6)
                capital -= invest
                risk.open_position(symbol, qty, price, invest)

                stop = price * (1 - float(os.getenv("STOP_LOSS_PCT", "0.05")))
                tp   = price * (1 + float(os.getenv("TAKE_PROFIT_PCT", "0.10")))

                logger.info(f"  ★ 매수 [{symbol}] 가격=${price:,.2f}  "
                            f"수량={qty:.6f}  투자=${invest:.2f}  "
                            f"손절=${stop:,.2f}  익절=${tp:,.2f}")

                notify_signal(symbol, price, sig["proba"])
                notify_trade("BUY", symbol, qty, price, invest, stop, tp)

            except Exception as e:
                logger.error(f"  [신호 처리 오류] {symbol}: {e}")
                notify_error(f"{symbol}: {e}")

        # ── 포트폴리오 현황 ───────────────────────
        total_upnl = sum(
            risk.unrealized_pnl(sym, get_signal(sym, model, feature_cols)["price"])
            for sym in risk.open_positions
        )
        effective_capital = capital + total_upnl
        logger.info(f"\n  현금: ${capital:,.2f}  미실현PnL: ${total_upnl:+.2f}  "
                    f"총자산: ${effective_capital:,.2f}")
        risk.print_summary(effective_capital)

        # 일일 리포트 (매 24사이클마다)
        if cycle % 24 == 0:
            notify_daily_report(risk.summary(effective_capital))

        # 결과 저장
        _save_state(risk, capital, cycle)

        logger.info(f"  다음 체크까지 {CHECK_INTERVAL}초 대기...\n")
        try:
            time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            logger.info("\n봇 종료 (Ctrl+C)")
            risk.print_summary(capital)
            break


def _save_state(risk, capital, cycle):
    """현재 상태 저장"""
    state = {
        "cycle":          cycle,
        "capital":        capital,
        "open_positions": {
            sym: {k: float(v) if isinstance(v, (int, float)) else v
                  for k, v in pos.items()}
            for sym, pos in risk.open_positions.items()
        },
        "trade_history":  risk.trade_history[-20:],  # 최근 20개
        "summary":        risk.summary(capital),
        "updated_at":     datetime.now().isoformat(),
    }
    path = os.path.join(RESULT_DIR, "paper_trading_state.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    run_paper_trading()
