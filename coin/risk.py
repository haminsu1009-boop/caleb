"""
coin/risk.py
리스크 관리 — 포지션 사이징, 손절/익절, 일일 한도

Kelly Criterion 기반 포지션 사이징:
  f = (p * b - q) / b
  p = 승률, b = 평균수익/평균손실, q = 1-p
"""

import os
import json
from datetime import date
from dotenv import load_dotenv

load_dotenv()

POSITION_SIZE_RATIO = float(os.getenv("POSITION_SIZE_RATIO", "0.10"))
STOP_LOSS_PCT       = float(os.getenv("STOP_LOSS_PCT",       "0.05"))
TAKE_PROFIT_PCT     = float(os.getenv("TAKE_PROFIT_PCT",     "0.10"))
MAX_POSITIONS       = int(os.getenv("MAX_POSITIONS",         "3"))
DAILY_LOSS_LIMIT    = float(os.getenv("DAILY_LOSS_LIMIT",    "0.03"))


class RiskManager:
    def __init__(self, initial_capital: float):
        self.initial_capital  = initial_capital
        self.daily_pnl        = 0.0
        self.daily_trades     = 0
        self.today            = date.today()
        self.open_positions   = {}   # symbol → {qty, entry_price, usdt_invested}
        self.trade_history    = []

    def _reset_daily_if_needed(self):
        today = date.today()
        if today != self.today:
            self.daily_pnl    = 0.0
            self.daily_trades = 0
            self.today        = today

    def can_trade(self, capital: float) -> tuple[bool, str]:
        """거래 가능 여부 판단"""
        self._reset_daily_if_needed()

        # 일일 손실 한도
        daily_loss_limit_usdt = self.initial_capital * DAILY_LOSS_LIMIT
        if self.daily_pnl < -daily_loss_limit_usdt:
            return False, f"일일 손실 한도 초과 (${self.daily_pnl:.2f})"

        # 최대 포지션 수
        if len(self.open_positions) >= MAX_POSITIONS:
            return False, f"최대 포지션 수 도달 ({MAX_POSITIONS}개)"

        # 최소 자본
        if capital < 10:
            return False, f"USDT 잔고 부족 (${capital:.2f})"

        return True, "OK"

    def position_size(self, capital: float,
                      win_rate: float = 0.55,
                      avg_win: float  = 0.05,
                      avg_loss: float = 0.03) -> float:
        """
        Kelly Criterion으로 포지션 크기 결정
        최대 POSITION_SIZE_RATIO까지만 투입 (Half Kelly)
        """
        b = avg_win / (avg_loss + 1e-9)
        p = win_rate
        q = 1 - p
        kelly = max(0, (p * b - q) / b)
        half_kelly = kelly * 0.5   # 반 켈리 (보수적)

        # 설정값과 반 켈리 중 작은 값 사용
        ratio = min(half_kelly, POSITION_SIZE_RATIO)
        return round(capital * ratio, 2)

    def open_position(self, symbol: str, qty: float,
                      entry_price: float, usdt_invested: float):
        self.open_positions[symbol] = {
            "qty":           qty,
            "entry_price":   entry_price,
            "usdt_invested": usdt_invested,
            "stop_loss":     entry_price * (1 - STOP_LOSS_PCT),
            "take_profit":   entry_price * (1 + TAKE_PROFIT_PCT),
        }

    def close_position(self, symbol: str, exit_price: float) -> float:
        """포지션 종료, PnL 반환"""
        if symbol not in self.open_positions:
            return 0.0
        pos  = self.open_positions.pop(symbol)
        pnl  = (exit_price - pos["entry_price"]) / pos["entry_price"] * pos["usdt_invested"]
        self.daily_pnl    += pnl
        self.daily_trades += 1
        self.trade_history.append({
            "symbol":      symbol,
            "entry":       pos["entry_price"],
            "exit":        exit_price,
            "qty":         pos["qty"],
            "pnl":         round(pnl, 4),
            "pnl_pct":     round((exit_price / pos["entry_price"] - 1) * 100, 2),
        })
        return pnl

    def should_stop_loss(self, symbol: str, current_price: float) -> bool:
        pos = self.open_positions.get(symbol)
        if not pos: return False
        return current_price <= pos["stop_loss"]

    def should_take_profit(self, symbol: str, current_price: float) -> bool:
        pos = self.open_positions.get(symbol)
        if not pos: return False
        return current_price >= pos["take_profit"]

    def unrealized_pnl(self, symbol: str, current_price: float) -> float:
        pos = self.open_positions.get(symbol)
        if not pos: return 0.0
        return (current_price - pos["entry_price"]) / pos["entry_price"] * pos["usdt_invested"]

    def summary(self, capital: float) -> dict:
        total_pnl  = sum(t["pnl"] for t in self.trade_history)
        total_wr   = (
            sum(1 for t in self.trade_history if t["pnl"] > 0) / len(self.trade_history)
            if self.trade_history else 0.0
        )
        return {
            "capital":        round(capital, 2),
            "total_trades":   len(self.trade_history),
            "win_rate":       round(total_wr * 100, 1),
            "total_pnl":      round(total_pnl, 2),
            "daily_pnl":      round(self.daily_pnl, 2),
            "open_positions": len(self.open_positions),
            "daily_trades":   self.daily_trades,
        }

    def print_summary(self, capital: float):
        s = self.summary(capital)
        print(f"\n{'─'*45}")
        print(f"  포트폴리오 요약")
        print(f"  현재 자산:    ${s['capital']:,.2f}")
        print(f"  총 거래수:    {s['total_trades']}회  (승률: {s['win_rate']:.1f}%)")
        print(f"  총 PnL:       ${s['total_pnl']:+,.2f}")
        print(f"  오늘 PnL:     ${s['daily_pnl']:+,.2f}")
        print(f"  오픈 포지션:  {s['open_positions']}개")
        print(f"{'─'*45}")
