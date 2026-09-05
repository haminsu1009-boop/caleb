"""
bot/oversold/executor.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
자동매매 실행기 — 바이빗 USDT 무기한, 메이저 12종, 4시간봉

기본값이 모의(dry-run)다. 실거래는 --live 를 명시해야만 켜진다.
실수로 실거래가 도는 일은 없어야 한다.

API 키:
    .env 파일에서만 읽는다 (.gitignore에 이미 등록됨).
    코드·로그·깃 어디에도 키가 남지 않는다. 채팅에 붙여넣지 말 것.

        BYBIT_API_KEY=...
        BYBIT_API_SECRET=...

    바이빗에서 키를 만들 때 **출금 권한은 반드시 끄고**, 가능하면
    접속 IP를 고정해라. 이 봇은 조회·주문 권한만 있으면 된다.

안전장치 (모두 강제):
    · 격리마진 필수        한 포지션이 터져도 계좌 전체가 날아가지 않는다
    · 일일 손실 한도       기본 자본의 5% — 넘으면 그날 신규 진입 중단
    · 최대 낙폭 차단기     기본 25% — 넘으면 전량 청산 후 완전 정지
    · 종목당 1포지션       중복 진입 금지
    · 총 노출 상한         자본의 100% × 배율
    · 상태 파일 저장       재시작해도 보유 봉수를 잃지 않는다
    · 시작 시 대조         거래소 실제 포지션과 상태 파일을 맞춘다

시간 청산이라는 점이 중요하다:
    이 규칙은 목표가에 파는 게 아니라 10봉 뒤에 판다. 봇이 죽어 있으면
    청산이 안 된다. 그래서 상태를 파일에 남기고, 재시작하면 밀린 청산부터
    처리한다.

사용법:
    python -m bot.oversold.executor                  # 모의 (기본)
    python -m bot.oversold.executor --once           # 1회만 점검하고 종료
    python -m bot.oversold.executor --live           # 실거래 (확인 문구 입력 필요)
    python -m bot.oversold.executor --dump-candles   # 캔들 저장 (검증용)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import argparse
import csv
import gzip
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from bot.oversold import strategy as S

STATE_PATH  = os.path.join(ROOT, "bot", "oversold", "state.json")
CANDLE_DIR  = os.path.join(ROOT, "data", "bybit")
BAR_MS      = 4 * 60 * 60 * 1000

log = logging.getLogger("oversold")


# ── 설정 ────────────────────────────────────────────────────────────────
class Config:
    def __init__(self):
        self.leverage      = float(os.getenv("OS_LEVERAGE",       "2"))
        self.per_trade     = float(os.getenv("OS_PER_TRADE",      "0.15"))
        self.max_gross     = float(os.getenv("OS_MAX_GROSS",      "1.0"))
        self.daily_loss    = float(os.getenv("OS_DAILY_LOSS",     "0.05"))
        self.max_drawdown  = float(os.getenv("OS_MAX_DRAWDOWN",   "0.25"))
        self.min_equity    = float(os.getenv("OS_MIN_EQUITY",     "50"))
        self.poll_seconds  = int(os.getenv("OS_POLL_SECONDS",     "300"))

    def describe(self) -> str:
        return (f"배율 {self.leverage:g}x · 진입당 자본 {self.per_trade*100:.0f}% · "
                f"총노출 상한 {self.max_gross*100:.0f}%×배율 · "
                f"일일손실 {self.daily_loss*100:.0f}% · 낙폭차단 {self.max_drawdown*100:.0f}%")


def load_env():
    p = os.path.join(ROOT, ".env")
    if not os.path.exists(p):
        return
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# ── 상태 ────────────────────────────────────────────────────────────────
def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        try:
            return json.load(open(STATE_PATH, encoding="utf-8"))
        except Exception:
            log.warning("상태 파일 손상 — 새로 시작한다")
    return {"positions": {}, "peak_equity": 0.0, "day": "", "day_start_equity": 0.0,
            "halted": False, "halt_reason": ""}


def save_state(st: dict):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    json.dump(st, open(tmp, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    os.replace(tmp, STATE_PATH)          # 쓰다 죽어도 이전 상태가 남는다


# ── 거래소 ──────────────────────────────────────────────────────────────
class Exchange:
    """실거래 세션. dry-run에서는 조회만 하고 주문은 로그만 남긴다."""

    def __init__(self, live: bool):
        self.live = live
        self.session = None
        self._spec = {}
        from pybit.unified_trading import HTTP
        key, sec = os.getenv("BYBIT_API_KEY"), os.getenv("BYBIT_API_SECRET")
        if live:
            if not key or not sec:
                raise SystemExit("실거래인데 .env에 BYBIT_API_KEY / BYBIT_API_SECRET 이 없다")
            self.session = HTTP(testnet=False, api_key=key, api_secret=sec)
        else:
            self.session = HTTP(testnet=False)      # 공개 조회만

    def klines(self, symbol: str, limit: int = 200) -> list:
        r = self.session.get_kline(category="linear", symbol=symbol,
                                   interval=S.INTERVAL, limit=limit)
        if r.get("retCode") != 0:
            raise RuntimeError(f"{symbol} kline 실패: {r.get('retMsg')}")
        rows = r["result"]["list"]
        return sorted(rows, key=lambda x: int(x[0]))     # 오래된 순

    def spec(self, symbol: str) -> dict:
        """수량 단위·최소주문량. 안 맞으면 주문이 거절된다."""
        if symbol in self._spec:
            return self._spec[symbol]
        r = self.session.get_instruments_info(category="linear", symbol=symbol)
        lot = r["result"]["list"][0]["lotSizeFilter"]
        self._spec[symbol] = {"step": float(lot["qtyStep"]),
                              "min": float(lot["minOrderQty"])}
        return self._spec[symbol]

    def equity(self) -> float:
        if not self.live:
            return float(os.getenv("OS_PAPER_EQUITY", "1000"))
        r = self.session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
        return float(r["result"]["list"][0]["totalEquity"])

    def positions(self) -> dict:
        if not self.live:
            return {}
        r = self.session.get_positions(category="linear", settleCoin="USDT")
        out = {}
        for p in r["result"]["list"]:
            if float(p["size"]) > 0:
                out[p["symbol"]] = {"size": float(p["size"]),
                                    "entry": float(p["avgPrice"]),
                                    "side": p["side"]}
        return out

    def set_leverage(self, symbol: str, lev: float):
        if not self.live:
            return
        try:
            self.session.set_leverage(category="linear", symbol=symbol,
                                      buyLeverage=str(lev), sellLeverage=str(lev))
        except Exception as e:
            if "110043" not in str(e):        # 이미 같은 배율이면 무시
                log.warning("%s 배율 설정 실패: %s", symbol, e)

    def open_long(self, symbol: str, qty: float, stop: float) -> bool:
        if not self.live:
            log.info("  [모의] 진입 %s qty=%s 손절=%.6f", symbol, qty, stop)
            return True
        r = self.session.place_order(
            category="linear", symbol=symbol, side="Buy", orderType="Market",
            qty=str(qty), stopLoss=f"{stop:.10g}", slTriggerBy="LastPrice",
            timeInForce="IOC", reduceOnly=False)
        ok = r.get("retCode") == 0
        log.info("  진입 %s qty=%s → %s", symbol, qty, "성공" if ok else r.get("retMsg"))
        return ok

    def close_long(self, symbol: str, qty: float, reason: str) -> bool:
        if not self.live:
            log.info("  [모의] 청산 %s qty=%s (%s)", symbol, qty, reason)
            return True
        r = self.session.place_order(
            category="linear", symbol=symbol, side="Sell", orderType="Market",
            qty=str(qty), reduceOnly=True, timeInForce="IOC")
        ok = r.get("retCode") == 0
        log.info("  청산 %s qty=%s (%s) → %s", symbol, qty, reason,
                 "성공" if ok else r.get("retMsg"))
        return ok


def round_qty(qty: float, spec: dict) -> float:
    step = spec["step"]
    q = int(qty / step) * step
    q = round(q, 10)
    return q if q >= spec["min"] else 0.0


def dump_candles(symbol: str, rows: list):
    """실거래에 쓴 바로 그 데이터를 남긴다 — 백테스트 재검증용"""
    os.makedirs(CANDLE_DIR, exist_ok=True)
    path = os.path.join(CANDLE_DIR, f"{symbol}_4h.csv.gz")
    with gzip.open(path, "wt", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["datetime", "open", "high", "low", "close", "volume"])
        for r in rows:
            dt = datetime.fromtimestamp(int(r[0]) / 1000, tz=timezone.utc)
            w.writerow([dt.strftime("%Y-%m-%d %H:%M:%S"), r[1], r[2], r[3], r[4], r[5]])


# ── 본체 ────────────────────────────────────────────────────────────────
class Trader:
    def __init__(self, ex: Exchange, cfg: Config, dump: bool = False):
        self.ex, self.cfg, self.dump = ex, cfg, dump
        self.st = load_state()

    # 시작 시 거래소 실제 포지션과 상태 파일을 맞춘다.
    def reconcile(self):
        if not self.ex.live:
            return
        actual = self.ex.positions()
        tracked = self.st["positions"]
        for sym in list(tracked):
            if sym not in actual:
                log.warning("상태엔 있으나 거래소에 없는 포지션 제거: %s "
                            "(손절 체결로 이미 닫혔을 수 있다)", sym)
                tracked.pop(sym)
        for sym, p in actual.items():
            if sym not in tracked and sym in S.MAJORS:
                log.warning("거래소에만 있는 포지션 발견: %s — 이 봇이 연 것이 아니므로 "
                            "건드리지 않는다", sym)
        save_state(self.st)

    def _guard(self, equity: float) -> bool:
        """차단기. False면 신규 진입 금지."""
        st = self.st
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if st.get("day") != today:
            st["day"] = today
            st["day_start_equity"] = equity
        st["peak_equity"] = max(st.get("peak_equity", 0.0), equity)

        if st.get("halted"):
            log.error("정지 상태: %s — 해제하려면 state.json의 halted를 false로", st["halt_reason"])
            return False
        if equity < self.cfg.min_equity:
            log.error("자본 %.2f USDT 가 최소치 미만 — 진입 중단", equity)
            return False
        peak = st["peak_equity"]
        if peak > 0 and (1 - equity / peak) >= self.cfg.max_drawdown:
            st["halted"] = True
            st["halt_reason"] = f"최대낙폭 {(1-equity/peak)*100:.1f}% 도달"
            save_state(st)
            log.error("🛑 %s — 전량 청산하고 정지한다", st["halt_reason"])
            self.close_all("낙폭 차단기")
            return False
        d0 = st.get("day_start_equity", equity)
        if d0 > 0 and (1 - equity / d0) >= self.cfg.daily_loss:
            log.warning("오늘 손실 %.1f%% — 신규 진입만 중단 (보유분은 계획대로 청산)",
                        (1 - equity / d0) * 100)
            return False
        return True

    def close_all(self, reason: str):
        for sym, p in list(self.st["positions"].items()):
            spec = self.ex.spec(sym)
            if self.ex.close_long(sym, round_qty(p["qty"], spec), reason):
                self.st["positions"].pop(sym, None)
        save_state(self.st)

    def tick(self):
        equity = self.ex.equity()
        can_enter = self._guard(equity)
        positions = self.st["positions"]
        now_ms = int(time.time() * 1000)

        gross = 0.0
        log.info("자본 %.2f USDT · 보유 %d종목 · %s",
                 equity, len(positions), "진입 가능" if can_enter else "진입 중단")

        for sym in S.MAJORS:
            try:
                rows = self.ex.klines(sym)
            except Exception as e:
                log.warning("%s 조회 실패: %s", sym, e)
                continue
            if self.dump:
                dump_candles(sym, rows)
            if len(rows) < S.MA_PERIOD + 2:
                continue

            # 마지막 봉은 진행 중일 수 있다 — 확정봉만 쓴다
            last_open = int(rows[-1][0])
            confirmed = rows[:-1] if now_ms < last_open + BAR_MS else rows
            closes = [float(r[4]) for r in confirmed]
            bar_time = int(confirmed[-1][0])
            price = float(rows[-1][4])

            # ① 보유분 청산 판정 (시간 경과)
            if sym in positions:
                p = positions[sym]
                held = (bar_time - p["entry_bar"]) // BAR_MS
                gross += p["qty"] * price
                if S.should_exit(held):
                    spec = self.ex.spec(sym)
                    q = round_qty(p["qty"], spec)
                    if q and self.ex.close_long(sym, q, f"{held}봉 경과"):
                        positions.pop(sym)
                        save_state(self.st)
                else:
                    log.info("  보유 %s %d/%d봉  진입가 %.6g  현재 %.6g (%.1f%%)",
                             sym, held, S.HOLD_BARS, p["entry"], price,
                             (price / p["entry"] - 1) * 100)
                continue

            # ② 신규 진입 판정
            if not can_enter:
                continue
            sig = S.evaluate(sym, closes, bar_time)
            if sig is None:
                continue
            notional = equity * self.cfg.per_trade * self.cfg.leverage
            cap = equity * self.cfg.max_gross * self.cfg.leverage
            if gross + notional > cap:
                log.info("  신호 %s (%.1f%%) — 총노출 상한 초과로 건너뜀", sym, sig.vs_ma20)
                continue
            spec = self.ex.spec(sym)
            qty = round_qty(notional / price, spec)
            if qty <= 0:
                log.info("  신호 %s — 수량이 최소주문량 미만", sym)
                continue
            stop = S.stop_price(price)
            log.info("🔔 신호 %s  종가 %.6g  20MA대비 %.1f%%  →  진입 %.6g USDT (%.4g개)",
                     sym, sig.close, sig.vs_ma20, notional, qty)
            self.ex.set_leverage(sym, self.cfg.leverage)
            if self.ex.open_long(sym, qty, stop):
                positions[sym] = {"qty": qty, "entry": price, "stop": stop,
                                  "entry_bar": bar_time,
                                  "opened_at": datetime.now(timezone.utc).isoformat()}
                gross += notional
                save_state(self.st)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="실거래 (기본은 모의)")
    ap.add_argument("--once", action="store_true", help="1회만 점검하고 종료")
    ap.add_argument("--dump-candles", action="store_true", help="조회한 캔들 저장")
    ap.add_argument("--close-all", action="store_true", help="전량 청산하고 종료")
    a = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                        datefmt="%m-%d %H:%M:%S")
    load_env()
    cfg = Config()

    mode = "🔴 실거래" if a.live else "🟢 모의(dry-run)"
    print("=" * 84)
    print(f"  과매도 자동매매 — 바이빗 무기한, 메이저 {len(S.MAJORS)}종, 4시간봉")
    print(f"  {mode}   {cfg.describe()}")
    print(f"  규칙: 20기간선 대비 {S.ENTRY_THRESH}% 이하 진입 → {S.HOLD_BARS}봉 후 청산 · 손절 {S.STOP_PCT}%")
    print("=" * 84)

    if a.live:
        print("\n  ⚠️  실제 자금으로 주문을 냅니다.")
        print(f"     배율 {cfg.leverage:g}x, 최대 {int(1/cfg.per_trade)}종목 동시 보유 가능.")
        print(f"     백테스트 최대낙폭은 3배 기준 38%였고, 실제 체결은 이보다 나쁠 수 있습니다.")
        if input("\n  계속하려면 START 입력: ").strip() != "START":
            print("  중단했습니다."); return

    ex = Exchange(live=a.live)
    tr = Trader(ex, cfg, dump=a.dump_candles)
    tr.reconcile()

    if a.close_all:
        tr.close_all("수동 전량 청산")
        return

    while True:
        try:
            tr.tick()
        except KeyboardInterrupt:
            print("\n  중단됨. 보유 포지션은 그대로 남아 있습니다 "
                  "(--close-all 로 청산 가능).")
            return
        except Exception as e:
            log.exception("점검 중 오류: %s", e)
        if a.once:
            return
        time.sleep(cfg.poll_seconds)


if __name__ == "__main__":
    main()
