"""
coin/directional_trader.py
양방향 페이퍼 트레이더 (롱 + 숏)

위아래로 발라먹는 핵심 실행기:
  - LONG  신호 → 매수 포지션 진입
  - SHORT 신호 → 공매도 포지션 진입
  - 수익 실현 / 손절 자동 관리
  - 포지션 중립화 (롱→숏 전환 시 기존 포지션 청산)

상태 파일: results/directional_state.json
로그 파일: results/directional_trades.csv
"""

import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ── 설정 ──────────────────────────────────────────────
INITIAL_CAPITAL     = 10_000.0   # 시작 자본 ($)
POSITION_SIZE_PCT   = 0.10       # 포지션당 자본 비율 (10%)
MAX_POSITIONS       = 5          # 최대 동시 보유 포지션
STOP_LOSS_PCT       = 0.04       # 손절 비율 (4%)
TAKE_PROFIT_PCT     = 0.08       # 목표 수익 (8%)
TRAILING_STOP_PCT   = 0.03       # 트레일링 스탑 (3%)
FEE_RATE            = 0.002      # 수수료 (0.2%)
SHORT_FEE_RATE      = 0.001      # 공매도 대차 수수료/일 (0.1%)

RESULTS_DIR = os.path.join(ROOT, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 포지션
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class Position:
    def __init__(
        self,
        symbol:    str,
        direction: str,   # "LONG" or "SHORT"
        entry_price: float,
        size_usd:  float,
        timestamp: str = None,
        long_prob: float = 0.0,
        short_prob:float = 0.0,
    ):
        self.symbol      = symbol
        self.direction   = direction
        self.entry_price = entry_price
        self.size_usd    = size_usd
        self.quantity    = size_usd / entry_price
        self.timestamp   = timestamp or datetime.utcnow().isoformat()
        self.long_prob   = long_prob
        self.short_prob  = short_prob

        # 추적
        self.peak_price      = entry_price  # 트레일링 스탑용 고점 (LONG)
        self.trough_price    = entry_price  # 트레일링 스탑용 저점 (SHORT)
        self.stop_price      = (entry_price * (1 - STOP_LOSS_PCT)
                                if direction == "LONG"
                                else entry_price * (1 + STOP_LOSS_PCT))
        self.take_profit_price = (entry_price * (1 + TAKE_PROFIT_PCT)
                                  if direction == "LONG"
                                  else entry_price * (1 - TAKE_PROFIT_PCT))

    def current_pnl(self, current_price: float) -> float:
        """현재 미실현 손익 ($)"""
        if self.direction == "LONG":
            return (current_price - self.entry_price) * self.quantity
        else:  # SHORT
            return (self.entry_price - current_price) * self.quantity

    def current_pnl_pct(self, current_price: float) -> float:
        """현재 미실현 손익 (%)"""
        if self.direction == "LONG":
            return (current_price / self.entry_price) - 1
        else:
            return (self.entry_price / current_price) - 1

    def update_trailing(self, current_price: float):
        """트레일링 스탑 가격 업데이트"""
        if self.direction == "LONG":
            if current_price > self.peak_price:
                self.peak_price  = current_price
                self.stop_price  = current_price * (1 - TRAILING_STOP_PCT)
        else:  # SHORT
            if current_price < self.trough_price:
                self.trough_price = current_price
                self.stop_price   = current_price * (1 + TRAILING_STOP_PCT)

    def should_stop(self, current_price: float) -> bool:
        """손절 조건"""
        if self.direction == "LONG":
            return current_price <= self.stop_price
        else:
            return current_price >= self.stop_price

    def should_take_profit(self, current_price: float) -> bool:
        """익절 조건"""
        if self.direction == "LONG":
            return current_price >= self.take_profit_price
        else:
            return current_price <= self.take_profit_price

    def to_dict(self) -> dict:
        return {
            "symbol":            self.symbol,
            "direction":         self.direction,
            "entry_price":       self.entry_price,
            "size_usd":          self.size_usd,
            "quantity":          self.quantity,
            "timestamp":         self.timestamp,
            "peak_price":        self.peak_price,
            "trough_price":      self.trough_price,
            "stop_price":        self.stop_price,
            "take_profit_price": self.take_profit_price,
            "long_prob":         self.long_prob,
            "short_prob":        self.short_prob,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Position":
        pos = cls(
            symbol      = d["symbol"],
            direction   = d["direction"],
            entry_price = d["entry_price"],
            size_usd    = d["size_usd"],
            timestamp   = d.get("timestamp"),
            long_prob   = d.get("long_prob", 0),
            short_prob  = d.get("short_prob", 0),
        )
        pos.peak_price        = d.get("peak_price",        pos.entry_price)
        pos.trough_price      = d.get("trough_price",      pos.entry_price)
        pos.stop_price        = d.get("stop_price",        pos.stop_price)
        pos.take_profit_price = d.get("take_profit_price", pos.take_profit_price)
        return pos


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 방향성 페이퍼 트레이더
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class DirectionalPaperTrader:
    """롱/숏 양방향 가상 거래 시뮬레이터"""

    def __init__(self, state_path: str = None):
        self.state_path = state_path or os.path.join(RESULTS_DIR, "directional_state.json")
        self.trade_log  = os.path.join(RESULTS_DIR, "directional_trades.csv")
        self._load_state()

    def _load_state(self):
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path) as f:
                    s = json.load(f)
                self.capital    = s.get("capital",   INITIAL_CAPITAL)
                self.positions  = {k: Position.from_dict(v)
                                   for k, v in s.get("positions", {}).items()}
                self.total_trades    = s.get("total_trades", 0)
                self.total_wins      = s.get("total_wins",   0)
                self.total_pnl       = s.get("total_pnl",    0.0)
                self.long_trades     = s.get("long_trades",  0)
                self.short_trades    = s.get("short_trades", 0)
                self.long_wins       = s.get("long_wins",    0)
                self.short_wins      = s.get("short_wins",   0)
                return
            except Exception:
                pass

        self.capital      = INITIAL_CAPITAL
        self.positions    = {}       # symbol → Position
        self.total_trades = 0
        self.total_wins   = 0
        self.total_pnl    = 0.0
        self.long_trades  = 0
        self.short_trades = 0
        self.long_wins    = 0
        self.short_wins   = 0

    def _save_state(self):
        state = {
            "capital":      self.capital,
            "positions":    {k: v.to_dict() for k, v in self.positions.items()},
            "total_trades": self.total_trades,
            "total_wins":   self.total_wins,
            "total_pnl":    self.total_pnl,
            "long_trades":  self.long_trades,
            "short_trades": self.short_trades,
            "long_wins":    self.long_wins,
            "short_wins":   self.short_wins,
            "updated":      datetime.utcnow().isoformat(),
        }
        with open(self.state_path, "w") as f:
            json.dump(state, f, indent=2)

    def _log_trade(self, action: str, pos: Position, current_price: float,
                   pnl: float, reason: str):
        row = {
            "timestamp":    datetime.utcnow().isoformat(),
            "action":       action,
            "symbol":       pos.symbol,
            "direction":    pos.direction,
            "entry_price":  pos.entry_price,
            "exit_price":   current_price,
            "size_usd":     pos.size_usd,
            "pnl_usd":      round(pnl, 4),
            "pnl_pct":      round(pos.current_pnl_pct(current_price) * 100, 2),
            "reason":       reason,
            "capital_after":round(self.capital, 2),
        }
        header = not os.path.exists(self.trade_log)
        pd.DataFrame([row]).to_csv(self.trade_log, mode="a", header=header, index=False)

    def get_price(self, symbol: str) -> float:
        """현재가 조회 (로컬 데이터 최신 종가)"""
        from coin.data_fetcher import get_latest_features
        try:
            df = get_latest_features(symbol)
            return float(df["close"].iloc[-1])
        except Exception:
            # Fallback: 합성 가격
            return float(np.random.lognormal(np.log(50000), 0.01))

    def open_position(
        self,
        symbol:     str,
        direction:  str,   # "LONG" or "SHORT"
        price:      float,
        long_prob:  float = 0.0,
        short_prob: float = 0.0,
    ) -> bool:
        """포지션 진입"""
        if len(self.positions) >= MAX_POSITIONS:
            return False

        # 같은 심볼 반대 방향 → 기존 포지션 청산
        pos_key = f"{symbol}_{direction}"
        opp_key = f"{symbol}_{'SHORT' if direction == 'LONG' else 'LONG'}"
        if opp_key in self.positions:
            self.close_position(opp_key, price, "방향 전환")

        if pos_key in self.positions:
            return False  # 이미 보유 중

        size_usd = self.capital * POSITION_SIZE_PCT
        fee      = size_usd * FEE_RATE
        if self.capital < size_usd + fee:
            return False

        self.capital -= fee
        pos = Position(symbol, direction, price, size_usd,
                       long_prob=long_prob, short_prob=short_prob)
        self.positions[pos_key] = pos

        icon = "📈" if direction == "LONG" else "📉"
        print(f"  {icon} [{direction}] {symbol}  "
              f"진입가=${price:.2f}  규모=${size_usd:.0f}  "
              f"{'롱' if direction=='LONG' else '숏'}확률={max(long_prob,short_prob):.3f}")
        return True

    def close_position(self, pos_key: str, price: float, reason: str = "수동청산") -> float:
        """포지션 청산 → 실현 손익 반환"""
        if pos_key not in self.positions:
            return 0.0

        pos = self.positions.pop(pos_key)
        pnl = pos.current_pnl(price)
        fee = pos.size_usd * FEE_RATE

        # 공매도 대차 수수료
        if pos.direction == "SHORT":
            days_held = max(1, (datetime.utcnow() -
                               datetime.fromisoformat(pos.timestamp)).days)
            short_fee = pos.size_usd * SHORT_FEE_RATE * days_held
            pnl -= short_fee

        net_pnl     = pnl - fee
        self.capital += pos.size_usd + net_pnl  # 원금 + 손익 반환

        self.total_trades += 1
        self.total_pnl    += net_pnl
        if pos.direction == "LONG":
            self.long_trades += 1
            if net_pnl > 0:
                self.long_wins += 1
                self.total_wins += 1
        else:
            self.short_trades += 1
            if net_pnl > 0:
                self.short_wins += 1
                self.total_wins += 1

        self._log_trade("CLOSE", pos, price, net_pnl, reason)

        pnl_pct = pos.current_pnl_pct(price) * 100
        icon    = "✅" if net_pnl > 0 else "❌"
        print(f"  {icon} [{pos.direction} 청산] {pos.symbol}  "
              f"${price:.2f}  {pnl_pct:+.2f}%  ${net_pnl:+.2f}  ({reason})")
        return net_pnl

    def check_exits(self, prices: dict) -> list:
        """모든 포지션 손절/익절 체크"""
        closed = []
        for pos_key, pos in list(self.positions.items()):
            price = prices.get(pos.symbol, self.get_price(pos.symbol))
            pos.update_trailing(price)

            if pos.should_take_profit(price):
                self.close_position(pos_key, price, "익절(TP)")
                closed.append((pos.symbol, pos.direction, "TP"))
            elif pos.should_stop(price):
                self.close_position(pos_key, price, "손절(SL)")
                closed.append((pos.symbol, pos.direction, "SL"))

        return closed

    def summary(self) -> dict:
        """성과 요약"""
        wr  = self.total_wins / max(self.total_trades, 1)
        lwr = self.long_wins  / max(self.long_trades,  1)
        swr = self.short_wins / max(self.short_trades, 1)
        ret = (self.capital - INITIAL_CAPITAL) / INITIAL_CAPITAL

        # 미실현 손익
        unrealized = 0.0
        for pos_key, pos in self.positions.items():
            try:
                price      = self.get_price(pos.symbol)
                unrealized += pos.current_pnl(price)
            except Exception:
                pass

        return {
            "capital":         round(self.capital, 2),
            "initial_capital": INITIAL_CAPITAL,
            "total_return":    round(ret * 100, 2),
            "total_trades":    self.total_trades,
            "total_wins":      self.total_wins,
            "win_rate":        round(wr * 100, 2),
            "long_trades":     self.long_trades,
            "long_win_rate":   round(lwr * 100, 2),
            "short_trades":    self.short_trades,
            "short_win_rate":  round(swr * 100, 2),
            "total_pnl":       round(self.total_pnl, 2),
            "unrealized_pnl":  round(unrealized, 2),
            "open_positions":  len(self.positions),
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 방향성 트레이딩 루프
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def run_directional_paper_trading(
    symbols:       list  = None,
    interval_min:  int   = 60,
    long_thr:      float = None,
    short_thr:     float = None,
):
    """
    양방향 페이퍼 트레이딩 루프

    매 interval_min 분마다:
      1. 포지션 손절/익절 체크
      2. 신호 스캔 (롱 + 숏)
      3. 신규 포지션 진입
      4. 성과 보고
    """
    import json as _json
    from coin.scanner import UniversalScanner

    if symbols is None:
        symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]

    # 임계값 로드
    thr_path = os.path.join(ROOT, "ml", "saved_models", "directional_thresholds.json")
    if long_thr is None or short_thr is None:
        if os.path.exists(thr_path):
            with open(thr_path) as f:
                t = _json.load(f)
            long_thr  = t.get("long",  0.62)
            short_thr = t.get("short", 0.60)
        else:
            long_thr, short_thr = 0.62, 0.60

    trader  = DirectionalPaperTrader()
    scanner = UniversalScanner(long_thr=long_thr, short_thr=short_thr)
    scanner.load_model()

    print("\n" + "=" * 65)
    print("  양방향 페이퍼 트레이딩 시작")
    print(f"  심볼: {symbols}")
    print(f"  롱 임계값: {long_thr:.2f}  숏 임계값: {short_thr:.2f}")
    print(f"  포지션당 {POSITION_SIZE_PCT*100:.0f}%  "
          f"손절 {STOP_LOSS_PCT*100:.0f}%  익절 {TAKE_PROFIT_PCT*100:.0f}%")
    print("=" * 65)

    iteration = 0
    while True:
        iteration += 1
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
        print(f"\n[{ts}] 이터레이션 {iteration}")

        # ── 현재가 수집 ───────────────────────────
        prices = {}
        for sym in symbols:
            try:
                prices[sym] = trader.get_price(sym)
            except Exception:
                pass

        # ── 손절/익절 체크 ────────────────────────
        closed = trader.check_exits(prices)
        if closed:
            print(f"  청산: {closed}")

        # ── 스캔 & 신규 진입 ──────────────────────
        scan_df = scanner.scan(
            crypto_symbols = symbols,
            kr_codes       = [],
            us_tickers     = [],
            verbose        = False,
        )

        for _, row in scan_df.iterrows():
            sym = row["symbol"]
            sig = row.get("signal", "NEUTRAL")
            lp  = row.get("long_prob",  0.5)
            sp  = row.get("short_prob", 0.5)
            price = prices.get(sym, row.get("price", 0))

            if sig == "LONG" and price > 0:
                trader.open_position(sym, "LONG", price, long_prob=lp, short_prob=sp)
            elif sig == "SHORT" and price > 0:
                trader.open_position(sym, "SHORT", price, long_prob=lp, short_prob=sp)

        # ── 성과 보고 ─────────────────────────────
        s = trader.summary()
        print(f"\n  📊 성과 요약")
        print(f"     자본:     ${s['capital']:,.2f}  ({s['total_return']:+.2f}%)")
        print(f"     승률:     {s['win_rate']:.1f}%  "
              f"(롱 {s['long_win_rate']:.1f}%  숏 {s['short_win_rate']:.1f}%)")
        print(f"     거래수:   {s['total_trades']}  "
              f"(롱 {s['long_trades']}  숏 {s['short_trades']})")
        print(f"     미실현:   ${s['unrealized_pnl']:+,.2f}  "
              f"오픈포지션: {s['open_positions']}")

        trader._save_state()
        print(f"\n  → {interval_min}분 후 다시 실행...")
        time.sleep(interval_min * 60)


if __name__ == "__main__":
    import sys
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    run_directional_paper_trading(interval_min=interval)
