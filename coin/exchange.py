"""
coin/exchange.py
Binance REST API 래퍼

- 잔고 조회
- 현재가 조회
- 시장가 / 지정가 주문
- 오픈 포지션 조회
- 테스트넷 / 실계좌 전환
"""

import os
import hmac
import hashlib
import time
import requests
from urllib.parse import urlencode
from dotenv import load_dotenv

load_dotenv()

API_KEY    = os.getenv("BINANCE_API_KEY", "")
SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")
TESTNET    = os.getenv("BINANCE_TESTNET", "True").lower() == "true"

BASE_URL = (
    "https://testnet.binance.vision"
    if TESTNET else
    "https://api.binance.com"
)


class BinanceClient:
    def __init__(self):
        self.api_key    = API_KEY
        self.secret_key = SECRET_KEY
        self.base_url   = BASE_URL
        self.session    = requests.Session()
        self.session.headers.update({"X-MBX-APIKEY": self.api_key})

        mode = "🟡 테스트넷" if TESTNET else "🔴 실계좌"
        print(f"[Binance] {mode} 연결")

    def _sign(self, params: dict) -> dict:
        params["timestamp"] = int(time.time() * 1000)
        query = urlencode(params)
        sig   = hmac.new(self.secret_key.encode(), query.encode(), hashlib.sha256).hexdigest()
        params["signature"] = sig
        return params

    def _get(self, path: str, params: dict = None, signed: bool = False) -> dict:
        if params is None: params = {}
        if signed: params = self._sign(params)
        for attempt in range(4):
            try:
                r = self.session.get(f"{self.base_url}{path}", params=params, timeout=10)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                if attempt == 3: raise
                time.sleep(2 ** attempt)

    def _post(self, path: str, params: dict) -> dict:
        params = self._sign(params)
        for attempt in range(4):
            try:
                r = self.session.post(f"{self.base_url}{path}", params=params, timeout=10)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                if attempt == 3: raise
                time.sleep(2 ** attempt)

    def _delete(self, path: str, params: dict) -> dict:
        params = self._sign(params)
        r = self.session.delete(f"{self.base_url}{path}", params=params, timeout=10)
        r.raise_for_status()
        return r.json()

    # ── 시세 조회 ────────────────────────────
    def get_price(self, symbol: str) -> float:
        data = self._get("/api/v3/ticker/price", {"symbol": symbol})
        return float(data["price"])

    def get_prices(self, symbols: list[str]) -> dict[str, float]:
        data = self._get("/api/v3/ticker/price")
        return {d["symbol"]: float(d["price"]) for d in data if d["symbol"] in symbols}

    def get_klines(self, symbol: str, interval: str = "1d", limit: int = 300) -> list:
        return self._get("/api/v3/klines", {
            "symbol": symbol, "interval": interval, "limit": limit
        })

    # ── 계좌 조회 ────────────────────────────
    def get_balance(self) -> dict[str, float]:
        data = self._get("/api/v3/account", signed=True)
        return {
            b["asset"]: float(b["free"])
            for b in data["balances"]
            if float(b["free"]) > 0
        }

    def get_usdt_balance(self) -> float:
        bal = self.get_balance()
        return bal.get("USDT", 0.0)

    def get_open_orders(self, symbol: str = None) -> list:
        params = {}
        if symbol: params["symbol"] = symbol
        return self._get("/api/v3/openOrders", params, signed=True)

    # ── 주문 ─────────────────────────────────
    def market_buy(self, symbol: str, usdt_amount: float) -> dict:
        """USDT 금액으로 시장가 매수"""
        return self._post("/api/v3/order", {
            "symbol":    symbol,
            "side":      "BUY",
            "type":      "MARKET",
            "quoteOrderQty": round(usdt_amount, 2),
        })

    def market_sell(self, symbol: str, qty: float) -> dict:
        """수량 기준 시장가 매도"""
        return self._post("/api/v3/order", {
            "symbol":   symbol,
            "side":     "SELL",
            "type":     "MARKET",
            "quantity": qty,
        })

    def limit_buy(self, symbol: str, qty: float, price: float) -> dict:
        return self._post("/api/v3/order", {
            "symbol":      symbol,
            "side":        "BUY",
            "type":        "LIMIT",
            "timeInForce": "GTC",
            "quantity":    qty,
            "price":       price,
        })

    def limit_sell(self, symbol: str, qty: float, price: float) -> dict:
        return self._post("/api/v3/order", {
            "symbol":      symbol,
            "side":        "SELL",
            "type":        "LIMIT",
            "timeInForce": "GTC",
            "quantity":    qty,
            "price":       price,
        })

    def stop_loss_order(self, symbol: str, qty: float, stop_price: float) -> dict:
        """손절 주문"""
        return self._post("/api/v3/order", {
            "symbol":      symbol,
            "side":        "SELL",
            "type":        "STOP_LOSS_LIMIT",
            "timeInForce": "GTC",
            "quantity":    qty,
            "stopPrice":   round(stop_price, 2),
            "price":       round(stop_price * 0.995, 2),  # 0.5% 여유
        })

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        return self._delete("/api/v3/order", {"symbol": symbol, "orderId": order_id})

    def get_symbol_info(self, symbol: str) -> dict:
        data = self._get("/api/v3/exchangeInfo", {"symbol": symbol})
        return data["symbols"][0] if data.get("symbols") else {}

    def ping(self) -> bool:
        try:
            self._get("/api/v3/ping")
            return True
        except Exception:
            return False


if __name__ == "__main__":
    client = BinanceClient()
    if client.ping():
        print("연결 성공!")
        price = client.get_price("BTCUSDT")
        print(f"BTC 현재가: ${price:,.2f}")
        bal = client.get_usdt_balance()
        print(f"USDT 잔고: ${bal:,.2f}")
    else:
        print("연결 실패 — API 키를 확인하세요")
