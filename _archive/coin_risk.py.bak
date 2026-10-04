"""
coin/risk.py
리스크 관리 — 고도화 버전

포함 기능:
  ① Kelly Criterion 기반 포지션 사이징 (Half Kelly 기본)
  ② 동적 레버리지 (신호 확률 × 변동성 기반)
  ③ 롱/숏 양방향 포지션 지원
  ④ 트레일링 스탑 (고점/저점 추적)
  ⑤ 일일 손실 한도 (일별 자동 리셋)
  ⑥ 포트폴리오 최대 낙폭 한도 (전체 자산 기준)
  ⑦ 포지션 요약 출력
"""

import os
from datetime import date
from dotenv import load_dotenv

load_dotenv()

POSITION_SIZE_RATIO  = float(os.getenv("POSITION_SIZE_RATIO",  "0.10"))
STOP_LOSS_PCT        = float(os.getenv("STOP_LOSS_PCT",        "0.05"))
TAKE_PROFIT_PCT      = float(os.getenv("TAKE_PROFIT_PCT",      "0.10"))
MAX_POSITIONS        = int(os.getenv("MAX_POSITIONS",          "3"))
DAILY_LOSS_LIMIT     = float(os.getenv("DAILY_LOSS_LIMIT",     "0.03"))
MAX_DRAWDOWN_LIMIT   = float(os.getenv("MAX_DRAWDOWN_LIMIT",   "0.15"))   # 포트폴리오 -15%
TRAILING_STOP_PCT    = float(os.getenv("TRAILING_STOP_PCT",    "0.03"))   # 3% 트레일링
MAX_LEVERAGE         = float(os.getenv("MAX_LEVERAGE",         "5.0"))


class RiskManager:
    def __init__(self, initial_capital: float):
        self.initial_capital  = initial_capital
        self.peak_capital     = initial_capital          # 포트폴리오 고점 (낙폭 계산용)
        self.daily_pnl        = 0.0
        self.daily_trades     = 0
        self.today            = date.today()
        self.open_positions   = {}   # symbol → position dict
        self.trade_history    = []

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 내부 유틸
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    def _reset_daily_if_needed(self):
        today = date.today()
        if today != self.today:
            self.daily_pnl    = 0.0
            self.daily_trades = 0
            self.today        = today

    def _record_trade(self, symbol: str, pos: dict, exit_price: float) -> float:
        """공통 청산 기록 로직"""
        direction  = pos.get("direction", "long")
        entry_price = pos["entry_price"]
        usdt_inv    = pos["usdt_invested"]
        leverage    = pos.get("leverage", 1.0)

        if direction == "long":
            pnl_pct = (exit_price / entry_price - 1) * leverage
        else:  # short
            pnl_pct = (1 - exit_price / entry_price) * leverage

        pnl = usdt_inv * pnl_pct
        self.daily_pnl    += pnl
        self.daily_trades += 1

        self.trade_history.append({
            "symbol":    symbol,
            "direction": direction,
            "entry":     round(entry_price, 4),
            "exit":      round(exit_price, 4),
            "qty":       pos["qty"],
            "leverage":  leverage,
            "pnl":       round(pnl, 4),
            "pnl_pct":   round(pnl_pct * 100, 2),
        })
        return pnl

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ① 거래 가능 여부 판단
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    def can_trade(self, capital: float) -> tuple:
        """거래 가능 여부 판단 (bool, 사유 문자열)"""
        self._reset_daily_if_needed()

        # 일일 손실 한도
        daily_limit_usdt = self.initial_capital * DAILY_LOSS_LIMIT
        if self.daily_pnl < -daily_limit_usdt:
            return False, f"일일 손실 한도 초과 (${self.daily_pnl:.2f})"

        # 포트폴리오 최대 낙폭 한도
        dd = (capital / self.peak_capital) - 1
        if dd < -MAX_DRAWDOWN_LIMIT:
            return False, f"포트폴리오 낙폭 한도 초과 ({dd*100:.1f}%)"

        # 최대 포지션 수
        if len(self.open_positions) >= MAX_POSITIONS:
            return False, f"최대 포지션 수 도달 ({MAX_POSITIONS}개)"

        # 최소 자본
        if capital < 10:
            return False, f"USDT 잔고 부족 (${capital:.2f})"

        return True, "OK"

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ② Kelly Criterion 포지션 사이징
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    def position_size(self, capital: float,
                       win_rate: float = 0.55,
                       avg_win: float  = 0.05,
                       avg_loss: float = 0.03) -> float:
        """
        Kelly Criterion → Half Kelly (보수적)
        최대 POSITION_SIZE_RATIO 캡핑
        """
        b = avg_win / (avg_loss + 1e-9)
        p = win_rate
        q = 1 - p
        kelly      = max(0.0, (p * b - q) / b)
        half_kelly = kelly * 0.5
        ratio      = min(half_kelly, POSITION_SIZE_RATIO)
        return round(capital * ratio, 2)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ③ 동적 레버리지
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    def calc_leverage(self, signal_prob: float = 0.65,
                       atr_pct: float = 0.02) -> float:
        """
        신호 확률과 변동성 기반 동적 레버리지

        규칙:
          - 기본 레버리지: 1x
          - 신호가 강할수록 (prob > 0.7) → 최대 MAX_LEVERAGE
          - 변동성이 높을수록 → 레버리지 감소 (ATR 5% 이상 = 최소)
          - 계산: base × prob_factor / vol_factor

        Args:
          signal_prob: ML 확률 (0.5~1.0)
          atr_pct:     ATR / Close (0.01~0.1 정도)

        Returns:
          레버리지 (1.0 ~ MAX_LEVERAGE)
        """
        # 확률 팩터: 0.5 → 1x, 1.0 → 2x
        prob_factor = max(1.0, (signal_prob - 0.5) * 4.0 + 1.0)
        # 변동성 팩터: ATR 2% → 1x, ATR 8% → 0.5x
        vol_factor  = max(0.5, 1.0 - (atr_pct - 0.02) * 5.0)
        raw_lev     = prob_factor * vol_factor
        return round(min(max(1.0, raw_lev), MAX_LEVERAGE), 1)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ④ 포지션 열기 (롱/숏 공통)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    def open_position(self, symbol: str,
                       qty: float,
                       entry_price: float,
                       usdt_invested: float,
                       direction: str = "long",   # "long" | "short"
                       leverage: float = 1.0,
                       trailing: bool  = True):
        """
        포지션 등록

        direction: "long"  → 가격 상승 시 이익
                   "short" → 가격 하락 시 이익
        trailing:  True 이면 트레일링 스탑 활성화
        """
        if direction == "long":
            sl = entry_price * (1 - STOP_LOSS_PCT / leverage)
            tp = entry_price * (1 + TAKE_PROFIT_PCT * leverage)
            trail_price = entry_price  # 고점 추적 (롱)
        else:  # short
            sl = entry_price * (1 + STOP_LOSS_PCT / leverage)
            tp = entry_price * (1 - TAKE_PROFIT_PCT * leverage)
            trail_price = entry_price  # 저점 추적 (숏)

        self.open_positions[symbol] = {
            "direction":       direction,
            "qty":             qty,
            "entry_price":     entry_price,
            "usdt_invested":   usdt_invested,
            "leverage":        leverage,
            "stop_loss":       sl,
            "take_profit":     tp,
            "trailing":        trailing,
            "trail_price":     trail_price,  # 최고점(롱) 또는 최저점(숏)
            "trailing_sl":     sl,           # 트레일링 스탑 현재값
        }

        # 고점 자본 갱신
        if usdt_invested > 0:
            pass  # 진입 시점에서는 고점 갱신 불필요

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ⑤ 트레일링 스탑 갱신
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    def update_trailing_stop(self, symbol: str, current_price: float):
        """
        현재가로 트레일링 스탑 갱신

        롱:   현재가가 새 고점이면 스탑을 고점 × (1 - TRAILING_STOP_PCT)로 올림
        숏:   현재가가 새 저점이면 스탑을 저점 × (1 + TRAILING_STOP_PCT)로 내림
        """
        pos = self.open_positions.get(symbol)
        if not pos or not pos.get("trailing"):
            return

        if pos["direction"] == "long":
            if current_price > pos["trail_price"]:
                pos["trail_price"] = current_price
                new_sl = current_price * (1 - TRAILING_STOP_PCT)
                if new_sl > pos["trailing_sl"]:
                    pos["trailing_sl"] = new_sl
        else:  # short
            if current_price < pos["trail_price"]:
                pos["trail_price"] = current_price
                new_sl = current_price * (1 + TRAILING_STOP_PCT)
                if new_sl < pos["trailing_sl"]:
                    pos["trailing_sl"] = new_sl

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ⑥ 손절/익절 판단
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    def should_stop_loss(self, symbol: str, current_price: float) -> bool:
        pos = self.open_positions.get(symbol)
        if not pos: return False
        self.update_trailing_stop(symbol, current_price)

        if pos["direction"] == "long":
            # 고정 스탑 또는 트레일링 스탑 중 높은 것
            sl = max(pos["stop_loss"], pos["trailing_sl"])
            return current_price <= sl
        else:  # short
            # 고정 스탑 또는 트레일링 스탑 중 낮은 것
            sl = min(pos["stop_loss"], pos["trailing_sl"])
            return current_price >= sl

    def should_take_profit(self, symbol: str, current_price: float) -> bool:
        pos = self.open_positions.get(symbol)
        if not pos: return False
        if pos["direction"] == "long":
            return current_price >= pos["take_profit"]
        else:  # short
            return current_price <= pos["take_profit"]

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ⑦ 포지션 청산
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    def close_position(self, symbol: str, exit_price: float,
                        capital: float = 0.0) -> float:
        """
        포지션 청산 — PnL 반환 (USDT)
        capital: 현재 자산 (포트폴리오 고점 갱신용, 선택)
        """
        if symbol not in self.open_positions:
            return 0.0
        pos = self.open_positions.pop(symbol)
        pnl = self._record_trade(symbol, pos, exit_price)

        # 포트폴리오 고점 갱신
        if capital > 0 and capital > self.peak_capital:
            self.peak_capital = capital

        return pnl

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ⑧ 미실현 손익
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    def unrealized_pnl(self, symbol: str, current_price: float) -> float:
        pos = self.open_positions.get(symbol)
        if not pos: return 0.0
        leverage = pos.get("leverage", 1.0)
        if pos["direction"] == "long":
            pnl_pct = (current_price / pos["entry_price"] - 1) * leverage
        else:
            pnl_pct = (1 - current_price / pos["entry_price"]) * leverage
        return pos["usdt_invested"] * pnl_pct

    def total_unrealized_pnl(self, prices: dict) -> float:
        """모든 오픈 포지션 미실현 손익 합계"""
        return sum(self.unrealized_pnl(sym, price)
                   for sym, price in prices.items())

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ⑨ 포트폴리오 낙폭
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    def portfolio_drawdown(self, capital: float) -> float:
        """현재 포트폴리오 낙폭 (0 ~ -1)"""
        if self.peak_capital <= 0: return 0.0
        return (capital / self.peak_capital) - 1

    def update_peak_capital(self, capital: float):
        """자본 고점 갱신 (주기적으로 호출)"""
        if capital > self.peak_capital:
            self.peak_capital = capital

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ⑩ 요약 출력
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    def summary(self, capital: float) -> dict:
        total_pnl = sum(t["pnl"] for t in self.trade_history)
        wins      = sum(1 for t in self.trade_history if t["pnl"] > 0)
        total_wr  = wins / len(self.trade_history) if self.trade_history else 0.0
        dd        = self.portfolio_drawdown(capital)
        return {
            "capital":        round(capital, 2),
            "peak_capital":   round(self.peak_capital, 2),
            "drawdown_pct":   round(dd * 100, 2),
            "total_trades":   len(self.trade_history),
            "win_rate":       round(total_wr * 100, 1),
            "total_pnl":      round(total_pnl, 2),
            "daily_pnl":      round(self.daily_pnl, 2),
            "open_positions": len(self.open_positions),
            "daily_trades":   self.daily_trades,
        }

    def print_summary(self, capital: float):
        s = self.summary(capital)
        print(f"\n{'─'*50}")
        print(f"  포트폴리오 요약")
        print(f"  현재 자산:    ${s['capital']:,.2f}  (고점: ${s['peak_capital']:,.2f})")
        print(f"  낙폭:         {s['drawdown_pct']:+.1f}%  (한도: -{MAX_DRAWDOWN_LIMIT*100:.0f}%)")
        print(f"  총 거래수:    {s['total_trades']}회  (승률: {s['win_rate']:.1f}%)")
        print(f"  총 PnL:       ${s['total_pnl']:+,.2f}")
        print(f"  오늘 PnL:     ${s['daily_pnl']:+,.2f}  (한도: -${self.initial_capital*DAILY_LOSS_LIMIT:,.2f})")
        print(f"  오픈 포지션:  {s['open_positions']}개")
        print(f"{'─'*50}")

    def position_info(self, symbol: str, current_price: float) -> str:
        """단일 포지션 상태 문자열"""
        pos = self.open_positions.get(symbol)
        if not pos: return f"{symbol}: 포지션 없음"
        upnl = self.unrealized_pnl(symbol, current_price)
        direction = pos["direction"].upper()
        sl = max(pos["stop_loss"], pos["trailing_sl"]) if direction == "LONG" \
             else min(pos["stop_loss"], pos["trailing_sl"])
        return (
            f"{symbol} [{direction}×{pos['leverage']}]  "
            f"진입: ${pos['entry_price']:,.2f}  현재: ${current_price:,.2f}  "
            f"미실현: ${upnl:+,.2f}  SL: ${sl:,.2f}  TP: ${pos['take_profit']:,.2f}"
        )
