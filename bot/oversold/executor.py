"""
bot/oversold/executor.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
자동매매 실행기 — 바이빗 USDT 무기한, 42종(실거래), 4시간봉

기본값이 모의(dry-run)다. 실거래는 --live 를 명시해야만 켜진다.
실수로 실거래가 도는 일은 없어야 한다.

분할매수(scale-in):
    신호가 뜨면 자본의 30%만 즉시 매수한다. 1차 체결가 대비 -5% 더
    빠지면 나머지 70%를 추가한다(strategy.SCALE_IN_*). 실제 주문은
    시장가라서, "저가가 트리거를 스쳤다"만으로 쏘면 안 된다 —
    확인하는 시점에 가격이 이미 되돌아와 있으면 1차보다 비싸게
    사게 되고, 그건 분할매수의 목적(평단을 낮춘다)을 정확히
    거스른다(ml/scale_in.py에서 시간분할이 전부 손해였던 것과
    같은 실패 모양). 그래서 트리거는 "지금 가격이 트리거 이하"
    일 때만 발동한다(_try_scale_in). 폴링 사이에 스쳤다가 돌아온
    저가는 놓친다 — 놓치는 쪽이 평단을 나쁘게 만드는 쪽보다 항상
    안전하다.

    노출 계산(총노출 상한)은 "실제 체결액"이 아니라 "예약액"(1차+2차
    전체 물량)으로 한다. 1차만 체결된 포지션을 실제 체결분(30%)만
    잡으면, 2차가 아직 안 걸린 포지션이 여러 개 쌓여 있다가 한꺼번에
    2차가 걸리는 순간 의도한 동시보유 한도(1/per_trade)를 몇 배
    넘길 수 있다(재생 테스트 test_replay.py에서 실제로 잡아냈다 —
    6종목 한도인데 9종목까지 열렸다). 예약액 기준이면 1차만 있어도
    이미 풀사이즈 자리를 잡으므로 이 문제가 없다. 대신 2차가 끝내
    안 걸리는 신호는 실제로는 30%만 썼는데도 자리는 100%만큼
    비워둔 것이 되어, 그만큼 다른 신호를 못 받는 손해를 본다 —
    안전 방향으로 보수적인 트레이드오프다.

API 키:
    .env 파일에서만 읽는다 (.gitignore에 이미 등록됨).
    코드·로그·깃 어디에도 키가 남지 않는다. 채팅에 붙여넣지 말 것.

        BYBIT_API_KEY=...
        BYBIT_API_SECRET=...

    바이빗에서 키를 만들 때 **출금 권한은 반드시 끄고**, 가능하면
    접속 IP를 고정해라. 이 봇은 조회·주문 권한만 있으면 된다.

안전장치 (모두 강제):
    · 격리마진 필수        진입 직전에 종목별로 전환한다. 전환에 실패하면
                          그 종목은 건너뛴다 — 교차마진으로는 안 들어간다
    · 일일 손실 한도       기본 자본의 5% — 넘으면 그날 신규 진입 중단
    · 최대 낙폭 차단기     기본 25% — 신규 진입만 30일 중단, 보유분은 그대로
                          두고 자동 재개한다. 전량 청산하지 않는다
    · 종목당 1포지션       중복 진입 금지
    · 총 노출 상한         자본의 80% × 배율
    · 상태 파일 저장       재시작해도 보유 봉수를 잃지 않는다
    · 시작 시 대조         거래소 실제 포지션과 상태 파일을 맞춘다

차단기가 총낙폭을 25%로 묶어주지는 않는다:
    발동할 때 고점을 현재 자본으로 다시 잡기 때문에 -25%가 겹쳐 쌓인다.
    백테스트에서 8.8년 동안 5번 발동했고 누적 낙폭은 68.7%(장중 78.0%)
    였다. 총노출 80% 제한이 그나마 이걸 묶는 장치다(ml/breaker_designs.py).

시간 청산이라는 점이 중요하다:
    이 규칙은 목표가에 파는 게 아니라 20봉(80시간) 뒤에 판다. 봇이 죽어
    있으면 청산이 안 된다. 그래서 상태를 파일에 남기고, 재시작하면 밀린
    청산부터 처리한다.

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
        # per_trade는 한 거래의 "전체" 의도 물량 비율이다(1차+2차 합산).
        # 1차는 이 중 SCALE_IN_FIRST_FRAC(30%)만 즉시 나간다. 0.05 =
        # 최대 20종목 동시 보유, ml/scale_in_portfolio.py --all46의
        # 검증값과 동일하다.
        self.per_trade     = float(os.getenv("OS_PER_TRADE",      "0.05"))
        # 1.0 → 0.8. ml/breaker_designs.py 참고.
        # 총노출 100%에서는 1년 창 189개 중 13%에서 장중 낙폭이
        # -90%를 넘는다. -25% 차단기가 그걸 못 막는 이유는 발동할 때
        # 고점을 현재 자본으로 리셋해서 -25%가 겹쳐 쌓이기 때문이다
        # (0.75^6 ≈ -82%). 차단기 문턱을 손대는 건 답이 아니다 —
        # 5~40%를 훑어보면 단조롭지 않고(20%→498배, 25%→148배,
        # 30%→196배) 홀드아웃에서는 15/20/25% 전부 발동 0회라
        # 교차검증 자체가 불가능하다.
        #
        # 총노출은 매끄럽고 단조롭다. 차단기 문턱과 무관하게
        # (15/20/25% 전부) 100%→80%면 장중 -90% 확률이 13% → 0%다.
        #   총노출 100%  전체 147.6배  홀드 13.68배  중앙낙폭 45%  -90% 13%
        #   총노출  80%  전체 179.2배  홀드  9.94배  중앙낙폭 37%  -90%  0%
        # 전체 수익과 1년 중앙값(1.53→1.62배)은 오히려 올라간다.
        # 대가는 홀드아웃 13.68 → 9.94배다.
        self.max_gross     = float(os.getenv("OS_MAX_GROSS",      "0.8"))
        self.daily_loss    = float(os.getenv("OS_DAILY_LOSS",     "0.05"))
        self.max_drawdown  = float(os.getenv("OS_MAX_DRAWDOWN",   "0.25"))
        # 백테스트(ml/sim_correct.py, ml/path_to_100x.py)가 검증한 차단기는
        # 영구 정지가 아니라 "30일간 신규진입만 중단, 그 뒤 자동 재개"다.
        # 이걸 영구 정지로 바꾸면 낙폭은 그대로 낮아지지만 100배 도달
        # 기간이 백테스트보다 길어진다 — 재개가 없으면 한 번 걸리고
        # 영영 안 도는 봇이 된다.
        self.halt_cooldown_days = float(os.getenv("OS_HALT_COOLDOWN_DAYS", "30"))
        self.min_equity    = float(os.getenv("OS_MIN_EQUITY",     "50"))
        self.poll_seconds  = int(os.getenv("OS_POLL_SECONDS",     "300"))

    def describe(self) -> str:
        return (f"배율 {self.leverage:g}x · 거래당 전체물량 {self.per_trade*100:.0f}% · "
                f"총노출 상한 {self.max_gross*100:.0f}%×배율 · "
                f"일일손실 {self.daily_loss*100:.0f}% · "
                f"낙폭차단 {self.max_drawdown*100:.0f}%({self.halt_cooldown_days:.0f}일 재개)")


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
            "halted_until": None, "halt_count": 0}


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

    def set_isolated(self, symbol: str, lev: float) -> bool:
        """격리마진으로 전환한다.

        문서에는 "격리마진 필수"라고 적혀 있었지만 실제로 설정하는
        코드가 없었다. 교차마진이면 한 종목이 크게 틀어졌을 때 계좌
        전체 증거금을 끌어다 쓰다가 다 같이 청산된다. 동시에 20종목을
        드는 규칙에서 이건 치명적이다.

        tradeMode=1 이 격리다. 이미 격리면 110026이 돌아오는데
        그건 성공으로 친다. 실패하면 True를 돌려주지 않는다 —
        호출부가 "설정했다"고 착각하면 안 된다.
        """
        if not self.live:
            return True
        try:
            self.session.switch_margin_mode(
                category="linear", symbol=symbol, tradeMode=1,
                buyLeverage=str(lev), sellLeverage=str(lev))
            return True
        except Exception as e:
            if "110026" in str(e):            # 이미 격리마진
                return True
            log.warning("%s 격리마진 전환 실패: %s", symbol, e)
            return False

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
            if sym not in tracked and sym in S.SYMBOLS:
                log.warning("거래소에만 있는 포지션 발견: %s — 이 봇이 연 것이 아니므로 "
                            "건드리지 않는다", sym)
        save_state(self.st)

    def _guard(self, equity: float) -> bool:
        """차단기. False면 신규 진입 금지 — 보유 중인 포지션은 건드리지
        않는다(시간 청산으로 자연스럽게 정리된다). 백테스트와 같은
        모양을 유지하려면 여기서 강제청산을 하면 안 된다: 검증한 차단기
        (ml/sim_correct.py, ml/path_to_100x.py)는 트리거 시점에 열려
        있던 포지션을 그대로 두고 신규 진입만 막는다."""
        st = self.st
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        if st.get("day") != today:
            st["day"] = today
            st["day_start_equity"] = equity
        st["peak_equity"] = max(st.get("peak_equity", 0.0), equity)

        halted_until = st.get("halted_until")
        if halted_until:
            until = datetime.fromisoformat(halted_until)
            if now < until:
                remain = (until - now).total_seconds() / 86400
                log.warning("차단기 재개까지 %.1f일 남음 — 신규 진입 중단, 보유분은 정상 청산", remain)
                return False
            log.info("차단기 %d일 경과 — 신규 진입 재개", self.cfg.halt_cooldown_days)
            st["halted_until"] = None
            save_state(st)

        if equity < self.cfg.min_equity:
            log.error("자본 %.2f USDT 가 최소치 미만 — 진입 중단", equity)
            return False
        peak = st["peak_equity"]
        if peak > 0 and (1 - equity / peak) >= self.cfg.max_drawdown:
            until = now + timedelta(days=self.cfg.halt_cooldown_days)
            st["halted_until"] = until.isoformat()
            st["halt_count"] = st.get("halt_count", 0) + 1
            st["peak_equity"] = equity   # 여기서부터 새로 고점을 잡는다(백테스트와 동일)
            save_state(st)
            log.error("🛑 최대낙폭 %.1f%% 도달 — %d일간 신규 진입 중단(%d번째). "
                      "보유분은 강제청산하지 않고 시간청산으로 정리한다.",
                      (1 - equity / peak) * 100, self.cfg.halt_cooldown_days, st["halt_count"])
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

    def _try_scale_in(self, sym: str, p: dict, price: float) -> None:
        """1차만 체결된 포지션의 2차 매수 트리거를 확인하고, 걸렸으면 채운다.

        시장가 주문이라 "저가가 트리거를 스쳤다"만으로 쏘면 안 된다 —
        확인하는 시점에 이미 되돌아와 있으면 1차보다 비싸게 사게 되고,
        그건 분할매수의 목적(평단을 낮춘다)을 정확히 거스른다. 이게
        ml/scale_in.py에서 시간분할이 전부 손해였던 것과 같은 실패
        모양이다. 그래서 "지금 가격"이 트리거 이하일 때만 쏜다.
        폴링 사이에 스쳤다가 돌아온 저가는 놓친다 — 놓치는 쪽이
        평단을 더 나쁘게 만드는 쪽보다 항상 안전하다.
        """
        if price > p["trigger"]:
            return
        notional2 = p["full_notional"] * (1 - S.SCALE_IN_FIRST_FRAC)
        spec = self.ex.spec(sym)
        qty2 = round_qty(notional2 / price, spec)
        if qty2 <= 0:
            return
        new_entry = S.blended_entry(p["entry"], p["qty"], price, qty2)
        new_stop = S.stop_price(new_entry)
        log.info("🔔 2차 매수 %s  트리거 %.6g 이하 확인(현재 %.6g)  →  +%.6g USDT (%.4g개)",
                 sym, p["trigger"], price, notional2, qty2)
        if self.ex.open_long(sym, qty2, new_stop):
            p["qty"] = p["qty"] + qty2
            p["entry"] = new_entry
            p["stop"] = new_stop
            p["notional"] = p["notional"] + notional2
            p["tranche"] = 2
            save_state(self.st)

    def tick(self):
        equity = self.ex.equity()
        can_enter = self._guard(equity)
        positions = self.st["positions"]
        now_ms = int(time.time() * 1000)

        # 총노출은 "지금까지 순회하며 본 것"이 아니라 "현재 열려 있는
        # 전부"로 시작해야 한다. S.SYMBOLS는 고정된 순서(알파벳)라서,
        # 0.0에서 시작해 순회하며 누적하면 이미 열려 있는 포지션이
        # 이번 순회 뒤쪽 심볼일 경우 앞쪽 심볼의 신규 진입 판정 시점에는
        # 아직 그 노출이 안 잡힌다 — cap을 넘겨서 진입을 허용하게 된다
        # (test_replay.py가 실제로 잡아냈다: cap 2990인데 예약합 4036).
        gross = sum(p["reserved"] for p in positions.values())
        log.info("자본 %.2f USDT · 보유 %d종목 · %s",
                 equity, len(positions), "진입 가능" if can_enter else "진입 중단")

        for sym in S.SYMBOLS:
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

            # ① 보유분 처리 — 시간 청산 또는 2차 분할매수 트리거
            # (노출은 "예약액" reserved = 1차+2차 전체 물량 기준이고,
            # 이미 tick() 맨 앞에서 현재 열린 전 종목분을 gross에 합쳐
            # 뒀다. 여기서 또 더하면 중복 계산이다 — 청산될 때만 뺀다.)
            if sym in positions:
                p = positions[sym]
                held = (bar_time - p["entry_bar"]) // BAR_MS
                if S.should_exit(held):
                    spec = self.ex.spec(sym)
                    q = round_qty(p["qty"], spec)
                    if q and self.ex.close_long(sym, q, f"{held}봉 경과"):
                        positions.pop(sym)
                        gross -= p["reserved"]
                        save_state(self.st)
                else:
                    if p["tranche"] == 1:
                        self._try_scale_in(sym, p, price)
                    log.info("  보유 %s %d/%d봉 · %d/2차  평단 %.6g  현재 %.6g (%.1f%%)",
                             sym, held, S.HOLD_BARS, p["tranche"], p["entry"], price,
                             (price / p["entry"] - 1) * 100)
                continue

            # ② 신규 진입 판정
            if not can_enter:
                continue
            sig = S.evaluate(sym, closes, bar_time)
            if sig is None:
                continue
            full_notional = equity * self.cfg.per_trade * self.cfg.leverage
            cap = equity * self.cfg.max_gross * self.cfg.leverage
            if gross + full_notional > cap:
                log.info("  신호 %s (%.1f%%) — 총노출 상한 초과로 건너뜀", sym, sig.vs_ma20)
                continue
            notional1 = full_notional * S.SCALE_IN_FIRST_FRAC
            spec = self.ex.spec(sym)
            qty1 = round_qty(notional1 / price, spec)
            if qty1 <= 0:
                log.info("  신호 %s — 1차 수량이 최소주문량 미만", sym)
                continue
            stop1 = S.stop_price(price)
            trigger = S.scale_in_trigger_price(price)
            log.info("🔔 신호 %s  종가 %.6g  20MA대비 %.1f%%  →  1차 진입 %.6g USDT (%.4g개)"
                     "  · 2차 트리거 %.6g", sym, sig.close, sig.vs_ma20, notional1, qty1, trigger)
            self.ex.set_leverage(sym, self.cfg.leverage)
            if not self.ex.set_isolated(sym, self.cfg.leverage):
                log.error("  %s 격리마진 전환 실패 — 진입을 건너뜁니다", sym)
                continue
            if self.ex.open_long(sym, qty1, stop1):
                positions[sym] = {"qty": qty1, "entry": price, "stop": stop1,
                                  "entry_bar": bar_time, "tranche": 1,
                                  "notional": notional1, "reserved": full_notional,
                                  "full_notional": full_notional, "trigger": trigger,
                                  "opened_at": datetime.now(timezone.utc).isoformat()}
                # 이번 폴링에서 아직 안 본 다른 종목들의 노출 계산도 예약액
                # (전체 물량) 기준으로 더한다 — 1차만 체결됐어도 2차가 걸릴
                # 자리를 이미 잡아둔 것으로 본다.
                gross += full_notional
                save_state(self.st)


def capital_check(ex, cfg, symbols) -> dict:
    """이 자본으로 42종 중 몇 종을 실제로 거래할 수 있는가.

    1차 진입액 = 자본 × per_trade × 배율 × 분할1차비율 이다.
    기본값이면 자본의 3%뿐이라, 소액 계좌에서는 상당수 종목이
    최소주문량에 못 미쳐 신호가 떠도 그냥 건너뛴다. 지금까지는
    그 사실을 "신호가 떴을 때 로그 한 줄"로만 알 수 있었다 —
    돈을 넣기 전에 알아야 하는 정보다.

    거래 가능 종목이 줄면 백테스트와 다른 것을 굴리게 된다.
    백테스트는 42종 전부에서 신호를 받았다.
    """
    eq = ex.equity()
    notional1 = eq * cfg.per_trade * cfg.leverage * S.SCALE_IN_FIRST_FRAC
    ok, bad, err, need = [], [], [], {}
    for sym in symbols:
        try:
            spec = ex.spec(sym)
            rows = ex.klines(sym, limit=2)
            price = float(rows[-1][4])
        except Exception:
            # 조회 실패는 "거래 불가"와 다르다. 섞어 세면 네트워크가
            # 잠깐 끊겼을 때 "0/42종 거래 가능"이라는 거짓 경보가 뜬다.
            err.append(sym)
            continue
        min_notional = spec["min"] * price
        if round_qty(notional1 / price, spec) > 0:
            ok.append(sym)
        else:
            bad.append(sym)
            need[sym] = min_notional
    return {"equity": eq, "notional1": notional1, "ok": ok, "bad": bad,
            "err": err, "need": need,
            # 전 종목을 커버하려면 필요한 자본
            "need_equity": (max(need.values()) /
                            (cfg.per_trade * cfg.leverage * S.SCALE_IN_FIRST_FRAC)
                            if need else 0.0)}


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
    print(f"  과매도 자동매매 — 바이빗 무기한, {len(S.SYMBOLS)}종(백테스트 {len(S.ALL_SYMBOLS)}종 중 "
          f"상장폐지 4종 제외), 4시간봉")
    print(f"  {mode}   {cfg.describe()}")
    print(f"  규칙: 20기간선 대비 {S.ENTRY_THRESH}% 이하 → 1차 {S.SCALE_IN_FIRST_FRAC*100:.0f}% 진입, "
          f"거기서 {S.SCALE_IN_TRIGGER_PCT}% 더 빠지면 2차 {(1-S.SCALE_IN_FIRST_FRAC)*100:.0f}% 추가")
    print(f"        → {S.HOLD_BARS}봉 후 청산 · 손절(평단 대비) {S.STOP_PCT}%")
    print("=" * 84)

    if a.live:
        print("\n  ⚠️  실제 자금으로 주문을 냅니다.")
        print(f"     배율 {cfg.leverage:g}x, 거래 1건의 전체 물량은 자본의 "
              f"{cfg.per_trade*100:.1f}%(최대 {int(1/cfg.per_trade)}건 동시), "
              f"그중 1차는 {cfg.per_trade*S.SCALE_IN_FIRST_FRAC*100:.1f}%만 즉시 나갑니다.")
        print(f"     백테스트(2배·총노출 80%·복리·왕복 0.40%) 8.8년 기준:")
        print(f"       전체 135배 · 최대낙폭 68.7%(장중 78.0%) · 1년 구간 5번 중 1번은 손실")
        print(f"       1년 구간 189개 중 -70% 이상 겪을 확률 13%")
        print(f"     실제 체결은 백테스트보다 나쁠 수 있습니다.")
        if input("\n  계속하려면 START 입력: ").strip() != "START":
            print("  중단했습니다."); return

    ex = Exchange(live=a.live)

    try:
        cc = capital_check(ex, cfg, S.SYMBOLS)
        print(f"\n  자본 {cc['equity']:,.2f} USDT · 1차 진입액 {cc['notional1']:,.2f} USDT"
              f" (자본의 {cfg.per_trade*cfg.leverage*S.SCALE_IN_FIRST_FRAC*100:.1f}%)")
        checked = len(cc["ok"]) + len(cc["bad"])
        if checked == 0:
            print(f"  ⚠️  종목 정보를 하나도 조회하지 못했습니다 "
                  f"({len(cc['err'])}종 실패) — 거래소 연결을 확인하세요")
        else:
            print(f"  거래 가능 종목 {len(cc['ok'])}/{checked}종"
                  + (f" (조회 실패 {len(cc['err'])}종)" if cc["err"] else ""))
        if cc["bad"]:
            print(f"  ⚠️  최소주문량 미달로 건너뛸 종목 {len(cc['bad'])}종: "
                  f"{', '.join(cc['bad'][:8])}{' …' if len(cc['bad']) > 8 else ''}")
            print(f"     42종 전부를 거래하려면 자본 약 {cc['need_equity']:,.0f} USDT 필요")
            print(f"     (백테스트는 42종 전부에서 신호를 받았다 — 종목이 빠지면")
            print(f"      검증한 것과 다른 것을 굴리게 된다)")
    except Exception as e:
        log.warning("자본 점검 실패: %s", e)

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
