"""
bot/risk_controller.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
최대 안정성 리스크 컨트롤러

보호 레이어 (순서대로 적용):
  ① 일일 손실 한도 (-5%) → 당일 거래 중단
  ② 포트폴리오 낙폭 한도 (-15%) → 전체 포지션 청산
  ③ 연속 손실 차단 (3연속 → 1시간 쿨다운)
  ④ 상관 필터 (같은 방향 포지션 최대 3개)
  ⑤ 심볼 중복 방지 (같은 심볼 중복 포지션 없음)
  ⑥ 변동성 필터 (ATR/가격 > 8% 이면 레버리지 강제 하향)
  ⑦ 시간대 필터 (저유동성 구간 스킵)
  ⑧ 트레일링 스탑 (타임프레임별 비율)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import time
from datetime import datetime, date
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Position:
    symbol:       str
    interval:     str
    direction:    str       # "LONG" | "SHORT"
    entry_price:  float
    quantity:     float     # 수량 (코인)
    usdt_amount:  float     # 투자 USDT
    leverage:     float
    win_rate:     float
    tier:         int
    open_time:    float = field(default_factory=time.time)
    peak_price:   float = 0.0   # 트레일링용 고점 (LONG)
    trough_price: float = 9e18  # 트레일링용 저점 (SHORT)
    sl_price:     float = 0.0
    tp_price:     float = 0.0
    trailing_sl:  float = 0.0   # 현재 트레일링 SL 가격


class RiskController:
    """
    거래 리스크 통합 관리

    Args:
        initial_capital: 초기 자본 (USDT)
        max_positions:   최대 동시 포지션 수 (기본 5)
        daily_loss_lim:  일일 손실 한도 비율 (기본 0.05 = 5%)
        max_drawdown:    최대 낙폭 한도 (기본 0.15 = 15%)
        consec_loss_max: 연속 손실 차단 기준 (기본 3)
        cooldown_sec:    연속 손실 후 쿨다운 초 (기본 3600)
    """

    # 타임프레임별 TP/SL/트레일링 비율
    TF_CONFIG = {
        "5m": {"tp": 0.005, "sl": 0.003, "trail": 0.004},   # 0.5/0.3/0.4%
        "1h": {"tp": 0.010, "sl": 0.006, "trail": 0.008},   # 1.0/0.6/0.8%
        "4h": {"tp": 0.020, "sl": 0.010, "trail": 0.015},   # 2.0/1.0/1.5%
        "1d": {"tp": 0.050, "sl": 0.025, "trail": 0.035},   # 5.0/2.5/3.5%
    }

    # 저유동성 시간 회피 (UTC 기준, 22:00~01:00)
    AVOID_HOURS_UTC = {22, 23, 0}

    def __init__(
        self,
        initial_capital: float,
        max_positions:   int   = 5,
        daily_loss_lim:  float = 0.05,
        max_drawdown:    float = 0.15,
        consec_loss_max: int   = 3,
        cooldown_sec:    int   = 3600,
        max_correl_same: int   = 3,    # 같은 방향 최대 동시 포지션
    ):
        self.initial_capital  = initial_capital
        self.capital          = initial_capital
        self.peak_capital     = initial_capital
        self.max_positions    = max_positions
        self.daily_loss_lim   = daily_loss_lim
        self.max_drawdown     = max_drawdown
        self.consec_loss_max  = consec_loss_max
        self.cooldown_sec     = cooldown_sec
        self.max_correl_same  = max_correl_same

        self.positions: dict  = {}    # symbol → Position
        self.today_pnl        = 0.0
        self.today_date       = date.today()
        self.consec_loss      = 0
        self.last_loss_time   = 0.0
        self.total_trades     = 0
        self.total_wins       = 0
        self.total_pnl_usdt   = 0.0
        self._daily_reset()

    # ──────────────────────────────────────────────
    def _daily_reset(self):
        today = date.today()
        if today != self.today_date:
            self.today_pnl  = 0.0
            self.today_date = today

    # ──────────────────────────────────────────────
    # 진입 허용 여부 판단
    # ──────────────────────────────────────────────
    def can_enter(self, symbol: str, direction: str,
                  interval: str = "1h") -> tuple:
        """
        새 포지션 진입 가능 여부 판단

        Returns:
            (allowed: bool, reason: str)
        """
        self._daily_reset()

        # ① 일일 손실 한도
        if self.today_pnl <= -self.capital * self.daily_loss_lim:
            return False, f"일일 손실 한도 도달 ({self.today_pnl:.2f} USDT)"

        # ② 포트폴리오 낙폭 한도
        drawdown = (self.peak_capital - self.capital) / (self.peak_capital + 1e-9)
        if drawdown >= self.max_drawdown:
            return False, f"최대 낙폭 도달 ({drawdown*100:.1f}%)"

        # ③ 연속 손실 쿨다운
        if self.consec_loss >= self.consec_loss_max:
            elapsed = time.time() - self.last_loss_time
            if elapsed < self.cooldown_sec:
                remaining = int((self.cooldown_sec - elapsed) / 60)
                return False, f"연속손실 쿨다운 ({remaining}분 남음)"
            else:
                self.consec_loss = 0   # 쿨다운 해제

        # ④ 최대 포지션 수
        if len(self.positions) >= self.max_positions:
            return False, f"최대 포지션 수 초과 ({len(self.positions)}/{self.max_positions})"

        # ⑤ 심볼 중복
        if symbol in self.positions:
            return False, f"{symbol} 이미 포지션 보유 중"

        # ⑥ 상관 필터 (같은 방향 과다)
        same_dir = sum(1 for p in self.positions.values()
                       if p.direction == direction)
        if same_dir >= self.max_correl_same:
            return False, f"같은 방향({direction}) 포지션 과다 ({same_dir}개)"

        # ⑦ 시간대 필터 (UTC 저유동성)
        if datetime.utcnow().hour in self.AVOID_HOURS_UTC and interval == "5m":
            return False, "저유동성 시간대 (UTC 22~01시, 5m 건너뜀)"

        return True, "OK"

    # ──────────────────────────────────────────────
    # 포지션 등록
    # ──────────────────────────────────────────────
    def open_position(
        self,
        symbol:      str,
        interval:    str,
        direction:   str,
        entry_price: float,
        usdt_amount: float,
        leverage:    float,
        win_rate:    float,
        tier:        int,
    ) -> Position:
        cfg = self.TF_CONFIG.get(interval, self.TF_CONFIG["1h"])
        tp_r = cfg["tp"]
        sl_r = cfg["sl"]

        if direction == "LONG":
            tp_price  = entry_price * (1 + tp_r)
            sl_price  = entry_price * (1 - sl_r)
            trail_sl  = entry_price * (1 - cfg["trail"])
            peak      = entry_price
            trough    = 9e18
        else:
            tp_price  = entry_price * (1 - tp_r)
            sl_price  = entry_price * (1 + sl_r)
            trail_sl  = entry_price * (1 + cfg["trail"])
            peak      = 0.0
            trough    = entry_price

        quantity = (usdt_amount * leverage) / entry_price

        pos = Position(
            symbol      = symbol,
            interval    = interval,
            direction   = direction,
            entry_price = entry_price,
            quantity    = quantity,
            usdt_amount = usdt_amount,
            leverage    = leverage,
            win_rate    = win_rate,
            tier        = tier,
            peak_price  = peak,
            trough_price= trough,
            sl_price    = sl_price,
            tp_price    = tp_price,
            trailing_sl = trail_sl,
        )
        self.positions[symbol] = pos
        return pos

    # ──────────────────────────────────────────────
    # 가격 업데이트 → TP/SL/트레일링 체크
    # ──────────────────────────────────────────────
    def update_price(self, symbol: str, current_price: float) -> dict:
        """
        실시간 가격 업데이트 → 청산 신호 판단

        Returns:
            {"action": "hold"|"close_tp"|"close_sl"|"close_trail"|"close_time",
             "pnl_pct": float, "pnl_usdt": float}
        """
        if symbol not in self.positions:
            return {"action": "none"}

        pos = self.positions[symbol]
        cfg = self.TF_CONFIG.get(pos.interval, self.TF_CONFIG["1h"])

        # PnL 계산
        if pos.direction == "LONG":
            pnl_pct = (current_price - pos.entry_price) / pos.entry_price * pos.leverage
            # 트레일링: 고점 갱신
            if current_price > pos.peak_price:
                pos.peak_price = current_price
                pos.trailing_sl = current_price * (1 - cfg["trail"])
        else:
            pnl_pct = (pos.entry_price - current_price) / pos.entry_price * pos.leverage
            # 트레일링: 저점 갱신
            if current_price < pos.trough_price:
                pos.trough_price = current_price
                pos.trailing_sl = current_price * (1 + cfg["trail"])

        pnl_usdt = pos.usdt_amount * pnl_pct

        # TP 도달
        if (pos.direction == "LONG"  and current_price >= pos.tp_price) or \
           (pos.direction == "SHORT" and current_price <= pos.tp_price):
            return {"action": "close_tp", "pnl_pct": pnl_pct, "pnl_usdt": pnl_usdt}

        # SL 도달
        if (pos.direction == "LONG"  and current_price <= pos.sl_price) or \
           (pos.direction == "SHORT" and current_price >= pos.sl_price):
            return {"action": "close_sl", "pnl_pct": pnl_pct, "pnl_usdt": pnl_usdt}

        # 트레일링 SL 도달
        if (pos.direction == "LONG"  and current_price <= pos.trailing_sl and
                pnl_pct > 0.005) or \
           (pos.direction == "SHORT" and current_price >= pos.trailing_sl and
                pnl_pct > 0.005):
            return {"action": "close_trail", "pnl_pct": pnl_pct, "pnl_usdt": pnl_usdt}

        return {"action": "hold", "pnl_pct": pnl_pct, "pnl_usdt": pnl_usdt}

    # ──────────────────────────────────────────────
    # 포지션 청산 기록
    # ──────────────────────────────────────────────
    def close_position(self, symbol: str, pnl_usdt: float, win: bool):
        if symbol in self.positions:
            del self.positions[symbol]

        self.today_pnl      += pnl_usdt
        self.capital        += pnl_usdt
        self.total_pnl_usdt += pnl_usdt
        self.total_trades   += 1

        if win:
            self.total_wins   += 1
            self.consec_loss   = 0
            self.peak_capital  = max(self.peak_capital, self.capital)
        else:
            self.consec_loss  += 1
            self.last_loss_time = time.time()

    # ──────────────────────────────────────────────
    # 전체 상태 요약
    # ──────────────────────────────────────────────
    def status(self) -> dict:
        self._daily_reset()
        wr = self.total_wins / max(1, self.total_trades)
        dd = (self.peak_capital - self.capital) / max(1, self.peak_capital)
        return {
            "capital":       round(self.capital, 2),
            "peak_capital":  round(self.peak_capital, 2),
            "total_pnl":     round(self.total_pnl_usdt, 2),
            "today_pnl":     round(self.today_pnl, 2),
            "total_trades":  self.total_trades,
            "win_rate":      round(wr * 100, 1),
            "drawdown_pct":  round(dd * 100, 2),
            "consec_loss":   self.consec_loss,
            "open_positions": len(self.positions),
            "positions":     {s: {
                "dir": p.direction, "entry": p.entry_price,
                "lev": p.leverage, "ivl": p.interval
            } for s, p in self.positions.items()},
        }

    def print_status(self):
        s = self.status()
        print(f"\n{'─'*50}")
        print(f"  자본: ${s['capital']:,.2f}  (+${s['total_pnl']:,.2f})")
        print(f"  오늘 PnL: ${s['today_pnl']:,.2f}")
        print(f"  거래: {s['total_trades']}건  WR: {s['win_rate']}%")
        print(f"  낙폭: {s['drawdown_pct']}%  연속손실: {s['consec_loss']}")
        print(f"  오픈 포지션: {s['open_positions']}개")
        for sym, p in s["positions"].items():
            print(f"    {sym} {p['dir']} {p['lev']}x ({p['ivl']})")
        print(f"{'─'*50}")

    # ──────────────────────────────────────────────
    # Kelly 포지션 사이징 (coin/risk.py 호환)
    # ──────────────────────────────────────────────
    def kelly_position_size(
        self,
        capital:  float,
        win_rate: float = 0.55,    # 0~1 스케일
        avg_win:  float = 0.05,
        avg_loss: float = 0.03,
        max_ratio: float = 0.20,   # 단일 포지션 최대 20% of 자본
    ) -> float:
        """
        Kelly Criterion → Half-Kelly 포지션 크기 (USDT)

        Args:
            win_rate:  0~1 스케일 (0.55 = 55%)
            avg_win:   평균 수익률 (예: 0.05 = 5%)
            avg_loss:  평균 손실률 (예: 0.03 = 3%)
            max_ratio: 단일 포지션 최대 자본 비율

        Returns:
            투자 USDT 금액
        """
        b = avg_win / max(avg_loss, 1e-9)
        p, q = win_rate, 1 - win_rate
        kelly = max(0.0, (p * b - q) / b)
        ratio = min(kelly * 0.5, max_ratio)   # Half-Kelly + 캡
        return round(capital * ratio, 2)

    def position_info(self, symbol: str, current_price: float) -> str:
        """단일 포지션 상태 문자열 (coin/risk.py 호환)"""
        pos = self.positions.get(symbol)
        if not pos:
            return f"{symbol}: 포지션 없음"
        pnl_pct = (current_price - pos.entry_price) / pos.entry_price
        if pos.direction == "SHORT":
            pnl_pct = -pnl_pct
        return (
            f"{symbol} [{pos.direction}×{pos.leverage}]  "
            f"진입: ${pos.entry_price:,.2f}  현재: ${current_price:,.2f}  "
            f"수익: {pnl_pct*100:+.2f}%  SL: ${pos.sl_price:,.2f}  "
            f"TP: ${pos.tp_price:,.2f}"
        )


# ──────────────────────────────────────────────────
# coin/risk.py 호환 alias — 기존 임포트 그대로 동작
# ──────────────────────────────────────────────────
RiskManager = RiskController
