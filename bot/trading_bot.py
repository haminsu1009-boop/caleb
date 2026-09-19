"""
bot/trading_bot.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
메인 트레이딩 봇 — 최대 승률 + 최대 실행률 + 최대 안정성

구조:
  SignalEngine   → 신호 생성 (Tier1/2/3)
  LeverageManager→ 동적 레버리지 결정
  RiskController → 리스크 관리 + TP/SL/트레일링
  BybitExecutor  → 실제 주문 (Bybit API)

실행:
  python bot/trading_bot.py --paper     # 페이퍼 트레이딩 (API 불필요)
  python bot/trading_bot.py --live      # 실거래 (API 키 필요)
  python bot/trading_bot.py --backtest  # 빠른 백테스트

환경변수 (.env):
  BYBIT_API_KEY=...
  BYBIT_API_SECRET=...
  INITIAL_CAPITAL=500000   # KRW → 자동 변환
  CAPITAL_USDT=400          # 또는 직접 USDT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os, sys, time, json, argparse, warnings
import numpy as np
import pandas as pd
from datetime import datetime

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bot.signal_engine    import SignalEngine, Signal
from bot.leverage_manager import LeverageManager
from bot.risk_controller  import RiskController


# ──────────────────────────────────────────────────────────
# 환경설정
# ──────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass

BYBIT_API_KEY    = os.getenv("BYBIT_API_KEY",    "")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")
CAPITAL_USDT     = float(os.getenv("CAPITAL_USDT", "400"))
KRW_RATE         = float(os.getenv("KRW_USDT_RATE", "1380"))  # 원/달러 환율

# 초기 자본 (KRW 입력이면 변환)
INITIAL_KRW = float(os.getenv("INITIAL_CAPITAL", "0"))
if INITIAL_KRW > 0:
    CAPITAL_USDT = INITIAL_KRW / KRW_RATE

SYMBOLS   = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]
INTERVALS = ["5m", "1h", "4h", "1d"]

# 타임프레임별 스캔 주기 (초)
SCAN_INTERVAL = {
    "5m":  300,    # 5분마다
    "1h":  3600,   # 1시간마다
    "4h":  14400,  # 4시간마다
    "1d":  86400,  # 1일마다
}


# ──────────────────────────────────────────────────────────
# 데이터 수집 (Bybit REST API)
# ──────────────────────────────────────────────────────────
def fetch_ohlcv(symbol: str, interval: str, limit: int = 300) -> pd.DataFrame:
    """Bybit에서 최신 OHLCV 데이터 로드"""
    import requests

    INTERVAL_MAP = {"5m": "5", "1h": "60", "4h": "240", "1d": "D"}
    ivl_str = INTERVAL_MAP.get(interval, interval)

    url = "https://api.bybit.com/v5/market/kline"
    params = {
        "category": "linear",
        "symbol":   symbol,
        "interval": ivl_str,
        "limit":    limit,
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if data.get("retCode", -1) != 0:
            return pd.DataFrame()
        lst = data["result"]["list"]
        if not lst:
            return pd.DataFrame()
        df = pd.DataFrame(lst, columns=["timestamp","open","high","low","close","volume","turnover"])
        for col in ["open","high","low","close","volume"]:
            df[col] = df[col].astype(float)
        df["timestamp"] = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms")
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df
    except Exception as e:
        print(f"  ⚠️ {symbol} {interval} 데이터 오류: {e}")
        return pd.DataFrame()


# ──────────────────────────────────────────────────────────
# Bybit 주문 실행기
# ──────────────────────────────────────────────────────────
class BybitExecutor:
    """Bybit 선물 주문 실행"""

    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.api_key    = api_key
        self.api_secret = api_secret
        self.testnet    = testnet
        self.base_url   = ("https://api-testnet.bybit.com" if testnet
                           else "https://api.bybit.com")
        self._ready = bool(api_key and api_secret)

    def _sign(self, params: dict) -> dict:
        import hashlib, hmac
        ts = str(int(time.time() * 1000))
        params.update({"api_key": self.api_key, "timestamp": ts})
        qs = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        sig = hmac.new(self.api_secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
        params["sign"] = sig
        return params

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        if not self._ready: return False
        import requests
        params = self._sign({"category": "linear", "symbol": symbol,
                             "buyLeverage": str(leverage),
                             "sellLeverage": str(leverage)})
        try:
            r = requests.post(f"{self.base_url}/v5/position/set-leverage",
                              json=params, timeout=10)
            return r.json().get("retCode", -1) == 0
        except Exception:
            return False

    def place_order(self, symbol: str, side: str, qty: float,
                    order_type: str = "Market") -> dict:
        """
        side: "Buy" | "Sell"
        qty:  수량 (코인)
        """
        if not self._ready:
            return {"simulated": True, "side": side, "qty": qty}
        import requests
        params = self._sign({
            "category":   "linear",
            "symbol":     symbol,
            "side":       side,
            "orderType":  order_type,
            "qty":        str(round(qty, 6)),
            "timeInForce":"IOC",
            "reduceOnly": False,
        })
        try:
            r = requests.post(f"{self.base_url}/v5/order/create",
                              json=params, timeout=10)
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def close_position(self, symbol: str, direction: str, qty: float) -> dict:
        side = "Sell" if direction == "LONG" else "Buy"
        params = dict(self.place_order.__func__.__defaults__ or ())
        return self.place_order(symbol, side, qty, "Market")


# ──────────────────────────────────────────────────────────
# 페이퍼 트레이딩 (모의)
# ──────────────────────────────────────────────────────────
class PaperExecutor:
    """실제 API 없이 모의 거래"""

    def set_leverage(self, symbol, leverage): return True

    def place_order(self, symbol, side, qty, order_type="Market"):
        print(f"    [PAPER] {symbol} {side} {qty:.4f} @ Market")
        return {"simulated": True}

    def close_position(self, symbol, direction, qty):
        side = "Sell" if direction == "LONG" else "Buy"
        print(f"    [PAPER] CLOSE {symbol} {direction} → {side} {qty:.4f}")
        return {"simulated": True}


# ──────────────────────────────────────────────────────────
# 메인 봇
# ──────────────────────────────────────────────────────────
class TradingBot:
    """
    통합 트레이딩 봇

    Args:
        capital:    초기 자본 (USDT)
        mode:       "paper" | "live" | "backtest"
        symbols:    거래 심볼 리스트
    """

    def __init__(
        self,
        capital:  float,
        mode:     str   = "paper",
        symbols:  list  = None,
        max_positions: int = 5,
    ):
        self.capital  = capital
        self.mode     = mode
        self.symbols  = symbols or SYMBOLS

        self.signal_engine  = SignalEngine(
            use_pattern_rules    = True,
            use_ml               = True,
            use_volume_explosion = True,
        )
        self.leverage_mgr = LeverageManager(
            max_lev     = 5.0,
            kelly_frac  = 0.50,
            max_pos_pct = 0.25,
        )
        self.risk = RiskController(
            initial_capital = capital,
            max_positions   = max_positions,
            daily_loss_lim  = 0.05,
            max_drawdown    = 0.15,
            consec_loss_max = 3,
            cooldown_sec    = 3600,
        )

        if mode == "live" and BYBIT_API_KEY:
            self.executor = BybitExecutor(BYBIT_API_KEY, BYBIT_API_SECRET)
        else:
            self.executor = PaperExecutor()

        self._last_scan: dict = {ivl: 0 for ivl in INTERVALS}
        self._signal_log = []

    # ── 단일 심볼/인터벌 스캔 + 진입 판단 ────────────
    def _process_symbol(self, symbol: str):
        """심볼의 모든 인터벌에서 데이터 로드 + 신호 생성"""
        dfs = {}
        for ivl in INTERVALS:
            df = fetch_ohlcv(symbol, ivl, limit=300)
            if not df.empty:
                dfs[ivl] = df

        if not dfs:
            return

        signals = self.signal_engine.scan(dfs, symbol)
        if not signals:
            return

        print(f"\n  📡 {symbol}: {len(signals)}개 신호 탐지")
        for sig in signals[:3]:   # 상위 3개만 출력
            print(f"     [Tier{sig.tier}] {sig.direction} {sig.interval} "
                  f"WR={sig.win_rate:.0f}% | {sig.reason}")

        # 최우선 신호 진입 시도
        best = signals[0]
        self._try_enter(best, dfs.get(best.interval, pd.DataFrame()))

    # ── 진입 시도 ────────────────────────────────────
    def _try_enter(self, sig: Signal, df: pd.DataFrame):
        """신호 검증 → 리스크 체크 → 주문 실행"""
        allowed, reason = self.risk.can_enter(sig.symbol, sig.direction, sig.interval)
        if not allowed:
            print(f"     ❌ 진입 차단: {reason}")
            return

        # 레버리지 결정
        usdt, leverage, dec = self.leverage_mgr.position_usdt(
            capital   = self.risk.capital,
            win_rate  = sig.win_rate,
            interval  = sig.interval,
            tier      = sig.tier,
            lift      = sig.lift,
        )
        leverage = int(leverage)

        if df.empty:
            print(f"     ⚠️ 가격 데이터 없음")
            return

        entry_price = float(df["close"].iloc[-1])
        qty         = (usdt * leverage) / entry_price

        print(f"     ✅ 진입: {sig.symbol} {sig.direction} "
              f"{leverage}x | ${usdt:.0f} USDT | {dec.reason}")

        # 레버리지 설정
        self.executor.set_leverage(sig.symbol, leverage)

        # 주문
        side = "Buy" if sig.direction == "LONG" else "Sell"
        result = self.executor.place_order(sig.symbol, side, qty)

        if "error" not in result:
            # 포지션 등록
            pos = self.risk.open_position(
                symbol      = sig.symbol,
                interval    = sig.interval,
                direction   = sig.direction,
                entry_price = entry_price,
                usdt_amount = usdt,
                leverage    = leverage,
                win_rate    = sig.win_rate,
                tier        = sig.tier,
            )
            self._signal_log.append({
                "time":      datetime.utcnow().isoformat(),
                "symbol":    sig.symbol,
                "interval":  sig.interval,
                "direction": sig.direction,
                "tier":      sig.tier,
                "win_rate":  sig.win_rate,
                "leverage":  leverage,
                "usdt":      usdt,
                "entry":     entry_price,
                "reason":    sig.reason,
            })
        else:
            print(f"     ❌ 주문 오류: {result['error']}")

    # ── 포지션 모니터링 ──────────────────────────────
    def _monitor_positions(self):
        """열린 포지션 가격 업데이트 + TP/SL 처리"""
        if not self.risk.positions:
            return

        for symbol in list(self.risk.positions.keys()):
            pos = self.risk.positions.get(symbol)
            if pos is None:
                continue

            # 현재 가격 조회 (1분봉 마지막)
            df = fetch_ohlcv(symbol, "5m", limit=2)
            if df.empty:
                continue

            current = float(df["close"].iloc[-1])
            action  = self.risk.update_price(symbol, current)

            if action["action"] != "hold":
                pnl_usdt = action["pnl_usdt"]
                win      = pnl_usdt > 0
                icon     = "✅" if win else "❌"

                print(f"\n  {icon} 청산: {symbol} {pos.direction} "
                      f"[{action['action']}] "
                      f"PnL: ${pnl_usdt:+.2f} ({action['pnl_pct']*100:+.1f}%)")

                # 실제 청산
                self.executor.close_position(symbol, pos.direction, pos.quantity)
                self.risk.close_position(symbol, pnl_usdt, win)
                self.leverage_mgr.record_result(win)

    # ── 메인 루프 ────────────────────────────────────
    def run(self):
        """봇 메인 실행 루프"""
        print(f"\n{'═'*60}")
        print(f"  🤖 트레이딩 봇 시작  [{self.mode.upper()}]")
        print(f"  자본: ${self.risk.capital:,.2f} USDT")
        print(f"  심볼: {', '.join(self.symbols)}")
        print(f"  최대 포지션: {self.risk.max_positions}")
        print(f"{'═'*60}\n")

        print(self.leverage_mgr.summary_table())
        print()

        scan_count = 0
        while True:
            try:
                now = time.time()

                # 포지션 모니터링 (매 30초)
                self._monitor_positions()

                # 신호 스캔 (5분 주기)
                if now - self._last_scan.get("5m", 0) >= 290:
                    self._last_scan["5m"] = now
                    scan_count += 1
                    print(f"\n[{datetime.utcnow().strftime('%H:%M:%S')} UTC] "
                          f"스캔 #{scan_count}")
                    for sym in self.symbols:
                        self._process_symbol(sym)
                    self.risk.print_status()

                time.sleep(30)

            except KeyboardInterrupt:
                print("\n\n봇 중단됨.")
                break
            except Exception as e:
                print(f"\n  ⚠️ 루프 오류: {e}")
                import traceback; traceback.print_exc()
                time.sleep(60)

        # 종료 시 요약
        self._print_final_summary()

    # ── 빠른 단발 스캔 ───────────────────────────────
    def scan_once(self) -> list:
        """한 번 스캔 후 신호 리스트 반환 (백테스트/테스트용)"""
        all_signals = []
        print(f"\n📡 전 심볼 스캔 중... ({len(self.symbols)}개)")
        for sym in self.symbols:
            dfs = {}
            for ivl in INTERVALS:
                df = fetch_ohlcv(sym, ivl, limit=300)
                if not df.empty:
                    dfs[ivl] = df
            if dfs:
                sigs = self.signal_engine.scan(dfs, sym)
                all_signals.extend(sigs)

        # 출력
        if all_signals:
            print(f"\n{'─'*70}")
            print(f"  {'심볼':<12} {'인터벌':<6} {'방향':<7} {'Tier':<5} "
                  f"{'WR':>6} {'레버리지':>6}  근거")
            print(f"{'─'*70}")
            for s in sorted(all_signals, key=lambda x: (x.tier, -x.win_rate)):
                usdt, lev, dec = self.leverage_mgr.position_usdt(
                    self.risk.capital, s.win_rate, s.interval, s.tier, s.lift)
                tier_icon = {1: "🔴", 2: "🟠", 3: "🟡"}.get(s.tier, "⚪")
                print(f"  {tier_icon} {s.symbol:<10} {s.interval:<6} "
                      f"{s.direction:<7} T{s.tier:<4} "
                      f"{s.win_rate:>5.0f}%  {lev:>5.1f}x  {s.reason}")
            print(f"{'─'*70}")
            print(f"  총 {len(all_signals)}개 신호")
        else:
            print("  신호 없음 (현재 진입 조건 미충족)")

        return all_signals

    def _print_final_summary(self):
        s = self.risk.status()
        roi = (s["capital"] - self.capital) / self.capital * 100
        print(f"\n{'═'*50}")
        print(f"  최종 결과")
        print(f"  시작 자본:  ${self.capital:,.2f}")
        print(f"  현재 자본:  ${s['capital']:,.2f}")
        print(f"  총 수익:    ${s['total_pnl']:+,.2f}  ({roi:+.1f}%)")
        print(f"  총 거래:    {s['total_trades']}건")
        print(f"  승률:       {s['win_rate']}%")
        print(f"  최대 낙폭:  {s['drawdown_pct']}%")
        print(f"{'═'*50}")
        # 신호 로그 저장
        if self._signal_log:
            log_path = os.path.join(ROOT, "bot_signal_log.json")
            with open(log_path, "w") as f:
                json.dump(self._signal_log, f, indent=2, ensure_ascii=False)
            print(f"  신호 로그: {log_path}")


# ──────────────────────────────────────────────────────────
# CLI 진입점
# ──────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="AI 트레이딩 봇")
    ap.add_argument("--paper",    action="store_true", help="페이퍼 트레이딩")
    ap.add_argument("--live",     action="store_true", help="실거래")
    ap.add_argument("--scan",     action="store_true", help="신호 스캔만 (1회)")
    ap.add_argument("--capital",  type=float, default=CAPITAL_USDT, help="자본 USDT")
    ap.add_argument("--symbols",  nargs="+", default=SYMBOLS, help="거래 심볼")
    ap.add_argument("--max-pos",  type=int,   default=5, help="최대 동시 포지션")
    args = ap.parse_args()

    mode = "live" if args.live else "paper"
    bot  = TradingBot(
        capital       = args.capital,
        mode          = mode,
        symbols       = args.symbols,
        max_positions = args.max_pos,
    )

    if args.scan:
        bot.scan_once()
    else:
        bot.run()


if __name__ == "__main__":
    main()
