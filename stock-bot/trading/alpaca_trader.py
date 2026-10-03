"""
Alpaca Auto Trader (미국 주식)
==============================
페이퍼(모의) + 실거래 자동매매
https://alpaca.markets — 계좌 개설 무료, 페이퍼트레이딩 무제한

설정:
  ALPACA_API_KEY, ALPACA_SECRET_KEY → .env
  ALPACA_PAPER=true  (페이퍼트레이딩, 기본값)
  ALPACA_PAPER=false (실거래 - 계좌 자금 필요)
"""

import os
import logging
from typing import Dict, List, Optional
from trading.strategy import TradingSignal

logger = logging.getLogger(__name__)

# alpaca-py 설치 필요: pip install alpaca-py
try:
    from alpaca.trading.client     import TradingClient
    from alpaca.trading.requests   import MarketOrderRequest, LimitOrderRequest, GetOrdersRequest
    from alpaca.trading.enums      import OrderSide, TimeInForce, OrderStatus
    from alpaca.data.historical    import StockHistoricalDataClient
    ALPACA_AVAILABLE = True
except ImportError:
    ALPACA_AVAILABLE = False
    logger.warning("[alpaca] alpaca-py 없음. pip install alpaca-py 실행 후 사용 가능.")


class AlpacaTrader:
    def __init__(self):
        self.api_key    = os.getenv("ALPACA_API_KEY",    "")
        self.secret_key = os.getenv("ALPACA_SECRET_KEY", "")
        self.paper      = os.getenv("ALPACA_PAPER", "true").lower() != "false"

        if not ALPACA_AVAILABLE:
            self._client = None
            return

        if not self.api_key or not self.secret_key:
            logger.warning("[alpaca] API 키 없음. .env 파일에 ALPACA_API_KEY / ALPACA_SECRET_KEY 설정 필요.")
            self._client = None
            return

        self._client = TradingClient(
            api_key    = self.api_key,
            secret_key = self.secret_key,
            paper      = self.paper,
        )
        mode = "페이퍼" if self.paper else "🔴 실거래"
        logger.info(f"[alpaca] 연결 완료 ({mode})")

    @property
    def ready(self) -> bool:
        return self._client is not None

    # ─────────────────────────────────────────
    # 계좌 정보
    # ─────────────────────────────────────────

    def get_account(self) -> Dict:
        """계좌 잔고·자산 조회"""
        if not self.ready:
            return {}
        try:
            acc = self._client.get_account()
            return {
                "equity":          float(acc.equity),
                "cash":            float(acc.cash),
                "buying_power":    float(acc.buying_power),
                "unrealized_pnl":  float(acc.unrealized_pl),
                "pnl_pct":         float(acc.unrealized_plpc) * 100,
                "day_trade_count": acc.daytrade_count,
                "pattern_day_trader": acc.pattern_day_trader,
            }
        except Exception as e:
            logger.error(f"[alpaca] 계좌 조회 실패: {e}")
            return {}

    def get_positions(self) -> List[Dict]:
        """보유 포지션 목록"""
        if not self.ready:
            return []
        try:
            positions = self._client.get_all_positions()
            return [
                {
                    "ticker":               p.symbol,
                    "qty":                  float(p.qty),
                    "avg_entry":            float(p.avg_entry_price),
                    "current_price":        float(p.current_price),
                    "market_value":         float(p.market_value),
                    "unrealized_pnl":       float(p.unrealized_pl),
                    "unrealized_pnl_pct":   float(p.unrealized_plpc) * 100,
                }
                for p in positions
            ]
        except Exception as e:
            logger.error(f"[alpaca] 포지션 조회 실패: {e}")
            return []

    # ─────────────────────────────────────────
    # 주문
    # ─────────────────────────────────────────

    def _calc_qty(self, ticker: str, pct_of_portfolio: float = 0.05) -> int:
        """포트폴리오의 pct_of_portfolio 비율만큼 수량 계산"""
        acc = self.get_account()
        equity = acc.get("equity", 0)
        if equity <= 0:
            return 0
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests   import StockLatestQuoteRequest
            data_client = StockHistoricalDataClient(self.api_key, self.secret_key)
            quote = data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=ticker))
            price = float(quote[ticker].ask_price or 1)
        except Exception:
            price = 1  # 가격 조회 실패 시 스킵
        target_value = equity * pct_of_portfolio
        qty = int(target_value / price)
        return max(qty, 1)

    def buy(
        self,
        ticker: str,
        qty: Optional[int] = None,
        pct_of_portfolio: float = 0.05,
        order_type: str = "market",
    ) -> Dict:
        """
        시장가 매수.
        qty=None이면 포트폴리오의 pct_of_portfolio% 자동 계산.
        """
        if not self.ready:
            return {"success": False, "error": "Alpaca 미연결"}
        if qty is None:
            qty = self._calc_qty(ticker, pct_of_portfolio)
        if qty <= 0:
            return {"success": False, "error": "수량 0"}
        try:
            req = MarketOrderRequest(
                symbol     = ticker,
                qty        = qty,
                side       = OrderSide.BUY,
                time_in_force = TimeInForce.DAY,
            )
            order = self._client.submit_order(req)
            logger.info(f"[alpaca] 매수 주문: {ticker} {qty}주 → {order.id}")
            return {"success": True, "order_id": str(order.id), "qty": qty, "ticker": ticker, "side": "BUY"}
        except Exception as e:
            logger.error(f"[alpaca] 매수 실패 ({ticker}): {e}")
            return {"success": False, "error": str(e)}

    def sell(self, ticker: str, qty: Optional[int] = None) -> Dict:
        """보유 수량 전체 또는 qty만큼 시장가 매도"""
        if not self.ready:
            return {"success": False, "error": "Alpaca 미연결"}
        try:
            if qty is None:
                # 전량 매도
                self._client.close_position(ticker)
                logger.info(f"[alpaca] 전량 매도: {ticker}")
                return {"success": True, "ticker": ticker, "side": "SELL", "qty": "all"}
            req = MarketOrderRequest(
                symbol        = ticker,
                qty           = qty,
                side          = OrderSide.SELL,
                time_in_force = TimeInForce.DAY,
            )
            order = self._client.submit_order(req)
            return {"success": True, "order_id": str(order.id), "qty": qty, "ticker": ticker, "side": "SELL"}
        except Exception as e:
            logger.error(f"[alpaca] 매도 실패 ({ticker}): {e}")
            return {"success": False, "error": str(e)}

    # ─────────────────────────────────────────
    # 신호 일괄 실행
    # ─────────────────────────────────────────

    def execute_signals(
        self,
        signals: List[TradingSignal],
        pct_per_trade: float = 0.05,
        dry_run: bool = False,
    ) -> List[Dict]:
        """
        TradingSignal 목록을 받아 자동 주문 실행.
        dry_run=True이면 실제 주문 없이 로그만 출력.
        """
        results = []
        for sig in signals:
            ticker = sig.ticker
            # 한국 주식 형식 제외 (Alpaca는 US 전용)
            if "." in ticker or len(ticker) == 6 and ticker.isdigit():
                logger.info(f"[alpaca] {ticker}: 한국 주식 → 스킵")
                continue

            logger.info(f"[alpaca] 신호: {sig.side} {ticker} (신뢰도 {sig.confidence:.0%}) — {sig.reason}")

            if dry_run:
                results.append({"ticker": ticker, "side": sig.side, "dry_run": True})
                continue

            if sig.side == "BUY":
                result = self.buy(ticker, pct_of_portfolio=pct_per_trade)
            elif sig.side == "SELL":
                result = self.sell(ticker)
            else:
                continue

            result["signal_reason"] = sig.reason
            results.append(result)

        return results

    def close_all(self) -> bool:
        """전체 포지션 청산 (긴급용)"""
        if not self.ready:
            return False
        try:
            self._client.close_all_positions(cancel_orders=True)
            logger.warning("[alpaca] ⚠️ 전체 포지션 청산")
            return True
        except Exception as e:
            logger.error(f"[alpaca] 전체 청산 실패: {e}")
            return False
