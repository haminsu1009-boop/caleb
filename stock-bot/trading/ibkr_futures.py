"""
IBKR Futures Trader (미국 선물)
================================
Interactive Brokers TWS API로 ES/NQ/CL 등 선물 자동매매

설정 방법:
1. Interactive Brokers 계좌 개설 (페이퍼: ibkr.com → Paper Trading 무료)
2. TWS (Trader Workstation) 또는 IB Gateway 설치 및 실행
3. TWS → Edit → Global Configuration → API → Settings
   - Enable ActiveX and Socket Clients: 체크
   - Port: 7497 (페이퍼) / 7496 (실거래)
4. pip install ib_insync

지원 선물 티커:
  ES  = S&P 500 선물 (최소증거금 ~$13,000)
  NQ  = 나스닥100 선물 (최소증거금 ~$18,000)
  MES = 미니 S&P 500 (최소증거금 ~$1,300) ← 소액 가능
  MNQ = 미니 나스닥 (최소증거금 ~$1,900) ← 소액 가능
  CL  = 원유 선물
  GC  = 금 선물
"""

import logging
import os
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from ib_insync import IB, Future, Contract, Order, util
    IB_AVAILABLE = True
except ImportError:
    IB_AVAILABLE = False
    logger.warning("[ibkr] ib_insync 없음. pip install ib_insync 후 사용 가능.")


# ─────────────────────────────────────────────
# 주요 선물 계약 정의
# ─────────────────────────────────────────────

FUTURES_CATALOG = {
    # symbol: (exchange, currency, description, tick_size, tick_value)
    "ES":  ("CME",   "USD", "S&P 500 선물 (표준)",      0.25,  12.50),
    "MES": ("CME",   "USD", "S&P 500 선물 (마이크로)",  0.25,   1.25),
    "NQ":  ("CME",   "USD", "나스닥100 선물 (표준)",    0.25,   5.00),
    "MNQ": ("CME",   "USD", "나스닥100 선물 (마이크로)",0.25,   0.50),
    "CL":  ("NYMEX", "USD", "원유(WTI) 선물",           0.01,  10.00),
    "GC":  ("COMEX", "USD", "금 선물",                  0.10,  10.00),
    "NG":  ("NYMEX", "USD", "천연가스 선물",             0.001,  10.00),
}


class IBKRFuturesTrader:
    """Interactive Brokers 선물 트레이더"""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = None,
        client_id: int = 1,
        paper: bool = True,
    ):
        self.host      = host
        self.port      = port or (7497 if paper else 7496)
        self.client_id = client_id
        self.paper     = paper
        self._ib: Optional["IB"] = None

        if not IB_AVAILABLE:
            logger.error("[ibkr] ib_insync 미설치. pip install ib_insync")

    @property
    def ready(self) -> bool:
        return IB_AVAILABLE and self._ib is not None and self._ib.isConnected()

    # ─────────────────────────────────────────
    # 연결
    # ─────────────────────────────────────────

    def connect(self) -> bool:
        """TWS에 연결. TWS/IB Gateway가 실행 중이어야 함."""
        if not IB_AVAILABLE:
            return False
        try:
            self._ib = IB()
            self._ib.connect(self.host, self.port, clientId=self.client_id)
            mode = "페이퍼" if self.paper else "🔴 실거래"
            logger.info(f"[ibkr] TWS 연결 완료 ({mode}, port={self.port})")
            return True
        except Exception as e:
            logger.error(f"[ibkr] 연결 실패: {e}\n→ TWS가 실행 중인지, API 포트({self.port})가 열려 있는지 확인하세요.")
            return False

    def disconnect(self) -> None:
        if self._ib and self._ib.isConnected():
            self._ib.disconnect()
            logger.info("[ibkr] 연결 해제")

    # ─────────────────────────────────────────
    # 계약 조회
    # ─────────────────────────────────────────

    def get_contract(self, symbol: str, expiry: str = "") -> Optional["Future"]:
        """
        선물 계약 생성 및 자격 확인.
        expiry: "202503" 형식 (미입력 시 가장 가까운 월물 자동)
        """
        if not self.ready:
            return None
        info = FUTURES_CATALOG.get(symbol.upper())
        if not info:
            logger.error(f"[ibkr] 미지원 심볼: {symbol}")
            return None

        exchange, currency, *_ = info
        contract = Future(symbol=symbol.upper(), exchange=exchange, currency=currency)
        if expiry:
            contract.lastTradeDateOrContractMonth = expiry

        try:
            details = self._ib.reqContractDetails(contract)
            if not details:
                logger.warning(f"[ibkr] {symbol} 계약 상세 없음")
                return None
            # 가장 가까운 월물 선택
            contract = details[0].contract
            logger.info(f"[ibkr] 계약: {contract.symbol} {contract.lastTradeDateOrContractMonth}")
            return contract
        except Exception as e:
            logger.error(f"[ibkr] {symbol} 계약 조회 실패: {e}")
            return None

    # ─────────────────────────────────────────
    # 현재가
    # ─────────────────────────────────────────

    def get_market_price(self, symbol: str) -> Optional[float]:
        if not self.ready:
            return None
        contract = self.get_contract(symbol)
        if not contract:
            return None
        try:
            ticker = self._ib.reqMktData(contract, "", False, False)
            self._ib.sleep(1)
            price = ticker.last or ticker.close
            self._ib.cancelMktData(contract)
            return float(price) if price else None
        except Exception as e:
            logger.error(f"[ibkr] {symbol} 현재가 조회 실패: {e}")
            return None

    # ─────────────────────────────────────────
    # 주문
    # ─────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        side: str,            # "BUY" | "SELL"
        qty: int = 1,
        order_type: str = "MKT",   # "MKT" | "LMT"
        limit_price: float = None,
    ) -> Dict:
        """
        선물 주문.
        symbol: "MES" (마이크로 S&P500, 소액 가능)
        side:   "BUY" | "SELL"
        qty:    계약 수 (MES 1계약 ≈ $60,000 노출, 증거금 ~$1,300)
        """
        if not self.ready:
            return {"success": False, "error": "IBKR 미연결"}

        contract = self.get_contract(symbol)
        if not contract:
            return {"success": False, "error": f"{symbol} 계약 없음"}

        try:
            if order_type == "LMT" and limit_price:
                order = Order(action=side, totalQuantity=qty, orderType="LMT", lmtPrice=limit_price)
            else:
                order = Order(action=side, totalQuantity=qty, orderType="MKT")

            trade = self._ib.placeOrder(contract, order)
            self._ib.sleep(1)
            logger.info(f"[ibkr] {side} {symbol} {qty}계약 → {trade.order.orderId}")
            return {
                "success":  True,
                "order_id": trade.order.orderId,
                "symbol":   symbol,
                "side":     side,
                "qty":      qty,
            }
        except Exception as e:
            logger.error(f"[ibkr] 주문 실패 ({symbol} {side}): {e}")
            return {"success": False, "error": str(e)}

    # ─────────────────────────────────────────
    # 포지션 조회
    # ─────────────────────────────────────────

    def get_positions(self) -> List[Dict]:
        if not self.ready:
            return []
        try:
            positions = self._ib.positions()
            return [
                {
                    "symbol":   p.contract.symbol,
                    "qty":      p.position,
                    "avg_cost": p.avgCost,
                }
                for p in positions
                if p.contract.secType == "FUT"
            ]
        except Exception as e:
            logger.error(f"[ibkr] 포지션 조회 실패: {e}")
            return []

    def close_position(self, symbol: str) -> Dict:
        """선물 포지션 청산"""
        positions = self.get_positions()
        for pos in positions:
            if pos["symbol"] == symbol.upper():
                qty = abs(int(pos["qty"]))
                side = "SELL" if pos["qty"] > 0 else "BUY"
                return self.place_order(symbol, side, qty)
        return {"success": False, "error": f"{symbol} 포지션 없음"}


# ─────────────────────────────────────────────
# 선물 계약 정보 출력 (참고용)
# ─────────────────────────────────────────────

def print_futures_info() -> None:
    print("\n지원 선물 계약:")
    print(f"{'심볼':<6} {'거래소':<8} {'설명':<28} {'틱크기':>7} {'틱가치':>8}")
    print("─" * 62)
    for sym, (exch, curr, desc, tick, tick_val) in FUTURES_CATALOG.items():
        print(f"{sym:<6} {exch:<8} {desc:<28} {tick:>7.3f} ${tick_val:>7.2f}")
    print("\n💡 소액 시작 추천: MES (마이크로S&P, 증거금~$1,300) / MNQ (마이크로나스닥, ~$1,900)")


if __name__ == "__main__":
    print_futures_info()
