"""
bybit/live_trader.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Bybit USDT 영구선물 자동매매 봇
SignalEngine(Tier1/2/3) + RiskController + LeverageManager 통합 버전

아키텍처:
  1. SignalEngine.scan()   → 신호 탐지 (Tier1 패턴룰 / Tier2 VE / Tier3 ML)
  2. LeverageManager.decide()  → 동적 레버리지 결정
       Tier2 (VE 미검증) → 최대 2x 강제 캡
       Tier3 (ML)        → 최대 3x 강제 캡
  3. RiskController.can_enter() → 리스크 게이트키핑
       일일 손실 / 낙폭 / 연속손실 / 중복 포지션 등 체크
  4. Bybit place_order()   → 진입 + SL/TP 지정가 주문 동시 설정
       (stopLoss / takeProfit 파라미터로 한 번에 거래소에 등록)
  5. RiskController.update_price() → 루프마다 실시간 SL/TP/트레일링 체크

사용법:
    python bybit/live_trader.py             # 실거래 (주의!)
    python bybit/live_trader.py --paper     # 페이퍼 트레이딩 (가상 거래)
    python bybit/live_trader.py --paper --interval 5

.env 필수 설정:
    BYBIT_API_KEY=...
    BYBIT_SECRET=...
    BYBIT_TESTNET=false          # 테스트넷 사용 시 true
    TRADING_SYMBOL=BTCUSDT
    TRADING_LEVERAGE=3           # 기본 레버리지 (LeverageManager가 동적 결정)
    TRADE_USDT=50                # 단일 포지션 기본 투자 USDT (자본 자동 계산)
    CANDLE_INTERVAL=60           # 캔들 인터벌 (분): 5 / 60 / 240 / D
    INITIAL_CAPITAL=500          # 초기 자본 (리스크 관리 기준)

.env 선택 설정:
    MAX_POSITIONS=5
    DAILY_LOSS_LIMIT=0.05        # 일일 손실 한도 5%
    MAX_DRAWDOWN=0.15            # 최대 낙폭 15%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os, sys, time, argparse, logging
from datetime import datetime

import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from pybit.unified_trading import HTTP
from bybit.collect_bybit    import fetch_latest
from bot.signal_engine      import SignalEngine, Signal
from bot.risk_controller    import RiskController, Position
from bot.leverage_manager   import LeverageManager


# ── 환경변수 설정 ────────────────────────────────────
SYMBOL          = os.getenv("TRADING_SYMBOL",    "BTCUSDT")
DEFAULT_LEV     = int(os.getenv("TRADING_LEVERAGE",  "3"))
CANDLE_INTERVAL = os.getenv("CANDLE_INTERVAL",   "60")   # 분 단위 문자열
TESTNET         = os.getenv("BYBIT_TESTNET", "false").lower() == "true"
INITIAL_CAPITAL = float(os.getenv("INITIAL_CAPITAL", "500"))
MAX_POSITIONS   = int(os.getenv("MAX_POSITIONS",      "5"))
DAILY_LOSS_LIM  = float(os.getenv("DAILY_LOSS_LIMIT", "0.05"))
MAX_DRAWDOWN    = float(os.getenv("MAX_DRAWDOWN",      "0.15"))

# Bybit 인터벌 코드 변환: 분 문자열 → API 파라미터
_INTERVAL_MAP = {
    "1": "1", "3": "3", "5": "5", "15": "15", "30": "30",
    "60": "60", "120": "120", "240": "240", "360": "360",
    "720": "720", "D": "D", "W": "W", "M": "M",
}
_SIGNAL_INTERVAL_MAP = {
    "1": "1m", "3": "3m", "5": "5m", "15": "15m", "30": "30m",
    "60": "1h", "120": "2h", "240": "4h", "D": "1d",
}

# 로거 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bybit_trader")


# ─────────────────────────────────────────────────────────
# 캔들 데이터 → SignalEngine용 dict 변환
# ─────────────────────────────────────────────────────────
def _build_dfs(symbol: str, api_interval: str, signal_interval: str) -> dict:
    """
    여러 타임프레임 캔들 데이터 수집 → {"1h": df, "4h": df, "1d": df} 형태로 반환.
    현재 인터벌을 포함해 상위 타임프레임까지 함께 가져온다.
    """
    intervals_needed = {"60": "1h", "240": "4h", "D": "1d"}

    # 현재 인터벌이 포함되도록 조정
    if api_interval not in intervals_needed:
        intervals_needed[api_interval] = signal_interval

    dfs = {}
    for api_ivl, sig_ivl in intervals_needed.items():
        raw = fetch_latest(symbol, api_ivl, n=300)
        if raw is not None and not raw.empty:
            raw = raw.rename(columns={"timestamp": "datetime"})
            raw["datetime"] = pd.to_datetime(raw["datetime"], errors="coerce")
            dfs[sig_ivl] = raw
    return dfs


# ─────────────────────────────────────────────────────────
# Bybit 주문 래퍼
# ─────────────────────────────────────────────────────────
class BybitTrader:
    """
    Bybit V5 API 래퍼.
    진입 시 stopLoss + takeProfit을 거래소에 함께 등록.
    """

    def __init__(self, paper: bool = False):
        self.paper = paper
        # ── 리스크 / 레버리지 관리자 ──────────────────
        self.risk_ctrl = RiskController(
            initial_capital  = INITIAL_CAPITAL,
            max_positions    = MAX_POSITIONS,
            daily_loss_lim   = DAILY_LOSS_LIM,
            max_drawdown     = MAX_DRAWDOWN,
        )
        self.lev_mgr = LeverageManager(
            max_lev     = DEFAULT_LEV,   # 실제 상한은 Tier별 cap이 우선
            max_pos_pct = 0.20,          # 단일 포지션 최대 20%
        )
        self.signal_engine = SignalEngine()

        # ── 페이퍼 트레이딩 내부 상태 ─────────────────
        self._paper_capital = INITIAL_CAPITAL
        self._paper_price   = {}   # symbol → last price (paper mock)

        if not paper:
            self.session = HTTP(
                testnet    = TESTNET,
                api_key    = os.getenv("BYBIT_API_KEY"),
                api_secret = os.getenv("BYBIT_SECRET"),
            )
            log.info("Bybit 실거래 세션 연결 완료 (testnet=%s)", TESTNET)
        else:
            self.session = None
            log.info("📝 페이퍼 트레이딩 모드 — 실제 주문 없음")

    # ── 현재가 조회 ──────────────────────────────────
    def _get_price(self) -> float:
        if self.paper:
            raw = fetch_latest(SYMBOL, _INTERVAL_MAP.get(CANDLE_INTERVAL, "60"), n=3)
            return float(raw["close"].iloc[-1]) if raw is not None and not raw.empty else 0.0
        resp = self.session.get_tickers(category="linear", symbol=SYMBOL)
        return float(resp["result"]["list"][0]["lastPrice"])

    # ── 잔고 조회 ────────────────────────────────────
    def _get_capital(self) -> float:
        if self.paper:
            return self._paper_capital
        try:
            resp = self.session.get_wallet_balance(accountType="UNIFIED")
            for item in resp["result"]["list"]:
                for coin in item.get("coin", []):
                    if coin["coin"] == "USDT":
                        return float(coin["walletBalance"])
        except Exception as e:
            log.warning("잔고 조회 실패: %s", e)
        return self.risk_ctrl.capital

    # ── 레버리지 설정 (거래소) ───────────────────────
    def _set_leverage(self, lev: int):
        if self.paper:
            return
        try:
            self.session.set_leverage(
                category    = "linear",
                symbol      = SYMBOL,
                buyLeverage = str(lev),
                sellLeverage= str(lev),
            )
        except Exception as e:
            log.debug("레버리지 설정: %s", e)

    # ────────────────────────────────────────────────
    # 진입: 시장가 주문 + SL/TP 지정가 동시 등록
    # ────────────────────────────────────────────────
    def _open_position(self, signal: Signal, price: float):
        """
        신호에 따라 진입 주문 + SL/TP를 거래소에 한 번에 설정.

        Bybit V5 place_order의 stopLoss / takeProfit 파라미터를 사용.
        """
        capital = self._get_capital()
        allowed, reason = self.risk_ctrl.can_enter(
            symbol    = SYMBOL,
            direction = signal.direction,
            interval  = signal.interval,
        )
        if not allowed:
            log.info("진입 차단: %s", reason)
            return

        # 동적 레버리지 결정
        dec = self.lev_mgr.decide(
            win_rate = signal.win_rate,
            interval = signal.interval,
            tier     = signal.tier,
            lift     = signal.lift,
        )
        lev      = int(dec.leverage)
        pos_usdt = capital * dec.position_pct

        # RiskController TF_CONFIG 기반 SL/TP 계산
        cfg      = self.risk_ctrl.TF_CONFIG.get(signal.interval, self.risk_ctrl.TF_CONFIG["1h"])
        sl_r     = cfg["sl"]
        tp_r     = cfg["tp"]

        if signal.direction == "LONG":
            sl_price = round(price * (1 - sl_r), 2)
            tp_price = round(price * (1 + tp_r), 2)
            side     = "Buy"
        else:
            sl_price = round(price * (1 + sl_r), 2)
            tp_price = round(price * (1 - tp_r), 2)
            side     = "Sell"

        qty = round(pos_usdt * lev / price, 3)
        if qty <= 0:
            log.warning("수량 0 — 진입 스킵 (자본 부족?)")
            return

        log.info(
            "📌 진입: %s %s  qty=%.3f @ $%.1f  lev=%dx  "
            "SL=$%.2f  TP=$%.2f  WR=%.0f%%  Tier%d  [%s]",
            signal.direction, SYMBOL, qty, price, lev,
            sl_price, tp_price, signal.win_rate, signal.tier, dec.reason,
        )

        if self.paper:
            # 페이퍼: RiskController에만 등록
            pos = self.risk_ctrl.open_position(
                symbol      = SYMBOL,
                interval    = signal.interval,
                direction   = signal.direction,
                entry_price = price,
                usdt_amount = pos_usdt,
                leverage    = float(lev),
                win_rate    = signal.win_rate,
                tier        = signal.tier,
            )
            log.info("  [PAPER] 포지션 등록 완료  SL=$%.2f  TP=$%.2f", pos.sl_price, pos.tp_price)
            return

        # ── 실거래: 거래소에 레버리지 설정 → 시장가 진입 + SL/TP ──
        self._set_leverage(lev)
        try:
            resp = self.session.place_order(
                category      = "linear",
                symbol        = SYMBOL,
                side          = side,
                orderType     = "Market",
                qty           = str(qty),
                timeInForce   = "IOC",
                # 진입과 동시에 거래소에 SL/TP 설정
                stopLoss      = str(sl_price),
                takeProfit    = str(tp_price),
                slTriggerBy   = "LastPrice",
                tpTriggerBy   = "LastPrice",
                positionIdx   = 0,   # 단방향 포지션 모드
            )
            order_id = resp.get("result", {}).get("orderId", "N/A")
            log.info("  ✅ 주문 접수: orderId=%s", order_id)

            # RiskController에 포지션 등록 (로컬 추적용)
            self.risk_ctrl.open_position(
                symbol      = SYMBOL,
                interval    = signal.interval,
                direction   = signal.direction,
                entry_price = price,
                usdt_amount = pos_usdt,
                leverage    = float(lev),
                win_rate    = signal.win_rate,
                tier        = signal.tier,
            )
        except Exception as e:
            log.error("  ❌ 주문 실패: %s", e)

    # ────────────────────────────────────────────────
    # 청산: 시장가 reduce-only
    # ────────────────────────────────────────────────
    def _close_position(self, price: float, reason: str):
        pos = self.risk_ctrl.positions.get(SYMBOL)
        if not pos:
            return

        pnl_pct  = (price - pos.entry_price) / pos.entry_price
        if pos.direction == "SHORT":
            pnl_pct = -pnl_pct
        pnl_usdt = pos.usdt_amount * pnl_pct * pos.leverage
        is_win   = pnl_usdt > 0

        log.info(
            "🔒 청산 [%s]  %s %s  진입=$%.1f → 현재=$%.1f  "
            "PnL=%+.2f%% ($%+.2f)",
            reason, pos.direction, SYMBOL,
            pos.entry_price, price, pnl_pct * 100, pnl_usdt,
        )

        if not self.paper:
            close_side = "Sell" if pos.direction == "LONG" else "Buy"
            try:
                self.session.place_order(
                    category    = "linear",
                    symbol      = SYMBOL,
                    side        = close_side,
                    orderType   = "Market",
                    qty         = str(pos.quantity),
                    reduceOnly  = True,
                    timeInForce = "IOC",
                    positionIdx = 0,
                )
            except Exception as e:
                log.error("  ❌ 청산 주문 실패: %s", e)

        # RiskController 기록 업데이트
        self.risk_ctrl.close_position(SYMBOL, pnl_usdt, is_win)
        self.lev_mgr.record_result(is_win)
        if self.paper:
            self._paper_capital += pnl_usdt

    # ────────────────────────────────────────────────
    # 메인 루프 — 한 tick 처리
    # ────────────────────────────────────────────────
    def tick(self):
        """캔들 하나 완성될 때마다 호출"""
        price = self._get_price()
        if price <= 0:
            log.warning("가격 조회 실패")
            return

        # ① 기존 포지션 SL/TP/트레일링 체크
        result = self.risk_ctrl.update_price(SYMBOL, price)
        action = result.get("action", "none")
        if action in ("close_tp", "close_sl", "close_trail"):
            self._close_position(price, action)
            return   # 청산 tick이면 새 진입은 다음 봉에

        # ② 신호 탐지
        api_ivl    = _INTERVAL_MAP.get(CANDLE_INTERVAL, "60")
        sig_ivl    = _SIGNAL_INTERVAL_MAP.get(CANDLE_INTERVAL, "1h")
        dfs        = _build_dfs(SYMBOL, api_ivl, sig_ivl)
        signals    = self.signal_engine.scan(dfs, SYMBOL)

        if not signals:
            log.info("[%s] %s $%.1f — 신호 없음", datetime.utcnow().strftime("%H:%M"), SYMBOL, price)
            return

        best = signals[0]   # Tier 오름차순, WR 내림차순으로 정렬됨
        log.info(
            "[%s] %s $%.1f — 신호: %s Tier%d WR=%.0f%% [%s]",
            datetime.utcnow().strftime("%H:%M"), SYMBOL, price,
            best.direction, best.tier, best.win_rate, best.reason,
        )

        # ③ 포지션 변경 판단
        current_pos = self.risk_ctrl.positions.get(SYMBOL)
        if current_pos is None:
            self._open_position(best, price)
        else:
            # 반대 방향 신호 → 청산 후 재진입
            if current_pos.direction != best.direction:
                self._close_position(price, "reverse_signal")
                time.sleep(1)
                self._open_position(best, price)
            else:
                log.info("  ⏸  포지션 유지 (%s)", current_pos.direction)

    # ── 상태 출력 ────────────────────────────────────
    def print_status(self):
        self.risk_ctrl.print_status()


# ─────────────────────────────────────────────────────────
# 메인 루프
# ─────────────────────────────────────────────────────────
def run_bot(paper: bool = False, interval_min: int = 60):
    print("=" * 60)
    print(f"🤖 AI 선물 트레이딩 봇")
    print(f"   심볼: {SYMBOL}  캔들: {interval_min}분  초기자본: ${INITIAL_CAPITAL:,.0f}")
    print(f"   모드: {'📝 페이퍼' if paper else '💰 실거래 ⚠️'}")
    print(f"   리스크: 일손실 한도={DAILY_LOSS_LIM*100:.0f}%  낙폭 한도={MAX_DRAWDOWN*100:.0f}%")
    print(f"   레버리지: Tier1 최대{DEFAULT_LEV}x / Tier2(VE) 최대2x / Tier3(ML) 최대3x")
    print("=" * 60)

    if not paper:
        confirm = input("\n  ⚠️  실거래 모드입니다. 계속하시겠습니까? (YES): ").strip()
        if confirm != "YES":
            print("  취소됨")
            return

    trader      = BybitTrader(paper=paper)
    sleep_sec   = interval_min * 60
    tick_count  = 0

    while True:
        try:
            trader.tick()
            tick_count += 1

            if tick_count % 6 == 0:   # 6봉마다 상태 출력
                trader.print_status()

            log.info("  ⏰ %d분 후 다음 봉...", interval_min)
            time.sleep(sleep_sec)

        except KeyboardInterrupt:
            print("\n\n⏹  봇 종료")
            trader.print_status()
            break
        except Exception as e:
            log.error("루프 오류: %s", e, exc_info=True)
            time.sleep(30)


# ── CLI ──────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bybit 선물 자동매매 봇")
    parser.add_argument("--paper",    action="store_true", help="페이퍼 트레이딩 (기본)")
    parser.add_argument("--interval", type=int, default=int(CANDLE_INTERVAL),
                        help="캔들 인터벌(분), 예: 5 / 60 / 240")
    args = parser.parse_args()
    run_bot(paper=args.paper, interval_min=args.interval)
