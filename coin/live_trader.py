"""
coin/live_trader.py
실계좌 자동매매 — Binance API로 실제 주문 실행

⚠️  경고:
  - 반드시 paper_trader.py로 2주 이상 검증 후 사용
  - .env의 BINANCE_TESTNET=False로 변경해야 실계좌 연동
  - 손실 발생 시 책임은 본인에게 있음
"""

import os
import sys
import time
import logging
import numpy as np
import pandas as pd
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from coin.exchange import BinanceClient
from coin.risk     import RiskManager
from coin.notifier import (notify_signal, notify_trade, notify_close,
                            notify_daily_report, notify_start, notify_error)
from coin.paper_trader import load_model, get_signal, setup_logger

LOG_FILE   = os.path.join(ROOT, "signals.log")
COINS      = os.getenv("COINS", "BTCUSDT,ETHUSDT").split(",")
SIGNAL_THR = float(os.getenv("SIGNAL_THRESHOLD", "0.65"))
INTERVAL   = 3600


def run_live_trading():
    # ── 안전 확인 ────────────────────────────────
    print("\n" + "=" * 55)
    print("  ⚠️  실계좌 자동매매 모드")
    print("=" * 55)
    print("  - 실제 자금으로 매매가 실행됩니다")
    print("  - 손실이 발생할 수 있습니다")
    print("  - 페이퍼 트레이딩 검증 후 사용하세요")
    print()
    confirm = input("  계속 진행하시겠습니까? (YES 입력): ").strip()
    if confirm != "YES":
        print("  취소됨")
        return

    logger = setup_logger()
    client = BinanceClient()

    if not client.ping():
        logger.error("Binance 연결 실패 — API 키 확인")
        return

    model, feature_cols = load_model()

    # 초기 잔고
    initial_usdt = client.get_usdt_balance()
    risk = RiskManager(initial_usdt)
    logger.info(f"실계좌 봇 시작  초기 USDT: ${initial_usdt:,.2f}")
    notify_start("🔴 실계좌 거래", COINS, initial_usdt)

    cycle = 0
    while True:
        cycle += 1
        logger.info(f"\n[사이클 {cycle}] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        capital = client.get_usdt_balance()

        # ── 포지션 손절/익절 체크 ──────────────────
        for symbol in list(risk.open_positions.keys()):
            try:
                price = client.get_price(symbol)
                pos   = risk.open_positions[symbol]

                if risk.should_stop_loss(symbol, price):
                    client.market_sell(symbol, pos["qty"])
                    pnl = risk.close_position(symbol, price)
                    logger.info(f"  [손절 실행] {symbol}  ${price:,.2f}  PnL=${pnl:+.2f}")
                    notify_close(symbol, pnl, pnl / pos["usdt_invested"] * 100, "손절")

                elif risk.should_take_profit(symbol, price):
                    client.market_sell(symbol, pos["qty"])
                    pnl = risk.close_position(symbol, price)
                    logger.info(f"  [익절 실행] {symbol}  ${price:,.2f}  PnL=${pnl:+.2f}")
                    notify_close(symbol, pnl, pnl / pos["usdt_invested"] * 100, "익절")

            except Exception as e:
                logger.error(f"  [포지션 오류] {symbol}: {e}")
                notify_error(str(e))

        # ── 신호 체크 & 매수 ───────────────────────
        for symbol in COINS:
            if symbol in risk.open_positions: continue
            try:
                sig = get_signal(symbol, model, feature_cols)
                if sig["signal"] != "BUY": continue

                can, reason = risk.can_trade(capital)
                if not can:
                    logger.info(f"  {symbol} 거래 불가: {reason}")
                    continue

                invest = risk.position_size(capital)
                if invest < 10: continue

                price  = client.get_price(symbol)
                result = client.market_buy(symbol, invest)
                qty    = float(result.get("executedQty", invest / price))

                risk.open_position(symbol, qty, price, invest)
                stop = price * (1 - float(os.getenv("STOP_LOSS_PCT", "0.05")))
                tp   = price * (1 + float(os.getenv("TAKE_PROFIT_PCT", "0.10")))

                # 손절 주문 등록
                try:
                    client.stop_loss_order(symbol, qty, stop)
                except Exception:
                    pass  # 손절 주문 실패해도 계속

                logger.info(f"  ★ 매수 실행 [{symbol}] ${price:,.2f}  수량={qty:.6f}")
                notify_signal(symbol, price, sig["proba"])
                notify_trade("BUY", symbol, qty, price, invest, stop, tp)

            except Exception as e:
                logger.error(f"  [매수 오류] {symbol}: {e}")
                notify_error(f"매수 실패 {symbol}: {e}")

        # 일일 리포트
        if cycle % 24 == 0:
            notify_daily_report(risk.summary(capital))

        logger.info(f"  잔고: ${capital:,.2f}  대기 {INTERVAL}s...")
        try:
            time.sleep(INTERVAL)
        except KeyboardInterrupt:
            logger.info("봇 종료")
            break


if __name__ == "__main__":
    run_live_trading()
