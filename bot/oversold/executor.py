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

import pandas as pd
from bot.oversold import strategy as S
from bot.oversold import regime as REG
from bot.oversold import modules as MOD

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
        self.per_trade     = float(os.getenv("OS_PER_TRADE",      "0.015"))
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
        self.max_gross     = float(os.getenv("OS_MAX_GROSS",      "0.6"))
        # 모듈별 거래당 자본 비중. 숏·다이버는 연 2.6건·7.4건뿐이라
        # 크게 싣는다 — 작게 실으면 대부분의 시간 그 자본이 논다.
        # ml/unified_pool.py 의 3,456조합 탐색에서 나온 값이다.
        self.per_trade_short = float(os.getenv("OS_PER_TRADE_SHORT", "0.40"))
        self.per_trade_div   = float(os.getenv("OS_PER_TRADE_DIV",   "0.40"))
        # 급락반등은 기본으로 꺼져 있다(bot/oversold/regime.py 참고).
        # 그 모듈의 엣지가 전부 미래참조였다 — 고치니 거래당 -0.018%로
        # 사실상 0이고, 넣으면 포트폴리오가 21.52배에서 18.83배로 나빠진다.
        # 비중을 올려도 의미가 없으므로 0으로 둔다.
        self.per_trade_crash = float(os.getenv("OS_PER_TRADE_CRASH", "0.0"))
        self.daily_loss    = float(os.getenv("OS_DAILY_LOSS",     "0.05"))
        self.max_drawdown  = float(os.getenv("OS_MAX_DRAWDOWN",   "0.20"))
        # 백테스트(ml/sim_correct.py, ml/path_to_100x.py)가 검증한 차단기는
        # 영구 정지가 아니라 "30일간 신규진입만 중단, 그 뒤 자동 재개"다.
        # 이걸 영구 정지로 바꾸면 낙폭은 그대로 낮아지지만 100배 도달
        # 기간이 백테스트보다 길어진다 — 재개가 없으면 한 번 걸리고
        # 영영 안 도는 봇이 된다.
        self.halt_cooldown_days = float(os.getenv("OS_HALT_COOLDOWN_DAYS", "30"))
        self.min_equity    = float(os.getenv("OS_MIN_EQUITY",     "50"))
        self.poll_seconds  = int(os.getenv("OS_POLL_SECONDS",     "300"))

    def describe(self) -> str:
        return (f"배율 롱 {self.leverage:g}x·숏/다이버 1x · 거래당 "
                f"롱 {self.per_trade*100:.1f}% / 숏 {self.per_trade_short*100:.0f}% / "
                f"다이버 {self.per_trade_div*100:.0f}% · "
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
    return {"positions": {}, "mod_positions": {}, "last_daily_scan": "",
            "peak_equity": 0.0, "day": "", "day_start_equity": 0.0,
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

    def klines(self, symbol: str, limit: int = 200, interval: str = None) -> list:
        r = self.session.get_kline(category="linear", symbol=symbol,
                                   interval=interval or S.INTERVAL, limit=limit)
        if r.get("retCode") != 0:
            raise RuntimeError(f"{symbol} kline 실패: {r.get('retMsg')}")
        rows = r["result"]["list"]
        return sorted(rows, key=lambda x: int(x[0]))     # 오래된 순

    def daily(self, symbol: str, limit: int = 600) -> pd.DataFrame:
        """일봉. 주봉 숏(MA60주=420일)과 다이버전스가 같이 쓴다.

        거래소의 주봉 캔들을 쓰지 않는 이유는 modules.py에 적어뒀다 —
        주의 시작 요일이 백테스트와 다를 수 있어서다.
        """
        rows = self.klines(symbol, limit=limit, interval="D")
        if not rows:
            return pd.DataFrame()
        d = pd.DataFrame([{"dt": pd.to_datetime(int(r[0]), unit="ms"),
                           "open": float(r[1]), "high": float(r[2]),
                           "low": float(r[3]), "close": float(r[4])}
                          for r in rows])
        # 마지막 일봉은 진행 중일 수 있다 — 확정봉만 쓴다
        now = pd.Timestamp.utcnow().tz_localize(None)
        return d[d["dt"] + pd.Timedelta(days=1) <= now].reset_index(drop=True)

    def spec(self, symbol: str) -> dict:
        """수량 단위·최소주문량. 안 맞으면 주문이 거절된다."""
        if symbol in self._spec:
            return self._spec[symbol]
        r = self.session.get_instruments_info(category="linear", symbol=symbol)
        lot = r["result"]["list"][0]["lotSizeFilter"]
        # 바이빗 무기한은 수량 하한(minOrderQty)과 **별개로** 주문 금액
        # 하한(minNotionalValue, 보통 5 USDT)을 건다. 수량만 보고 주문을
        # 내면 소액 계좌에서 거래소가 조용히 거절한다 — 봇 입장에서는
        # "신호는 떴는데 포지션이 없는" 상태가 된다.
        self._spec[symbol] = {"step": float(lot["qtyStep"]),
                              "min": float(lot["minOrderQty"]),
                              "min_notional": float(lot.get("minNotionalValue") or 0)}
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
                sl = p.get("stopLoss") or "0"
                tp = p.get("takeProfit") or "0"
                out[p["symbol"]] = {"size": float(p["size"]),
                                    "entry": float(p["avgPrice"]),
                                    "side": p["side"],
                                    "stop": float(sl) if sl not in ("", "0") else 0.0,
                                    "tp": float(tp) if tp not in ("", "0") else 0.0}
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

    def set_stop(self, symbol: str, stop: float,
                 take_profit: float | None = None) -> bool:
        """포지션에 손절가를 (다시) 건다.

        진입 주문에 stopLoss를 실어 보내지만, 그게 조용히 무시되거나
        나중에 취소되는 경우가 있다. 손절이 없는 줄 모르고 도는 것이
        이 봇에서 가장 크게 잃는 경로다 — -40%에서 끊기라고 설계한
        포지션이 배율 2배 기준 -49.5%에서 강제청산될 때까지 간다.
        그래서 매 점검마다 거래소 쪽 손절가를 읽어 확인하고,
        비어 있으면 여기로 다시 건다.
        """
        if not self.live:
            log.info("  [모의] 손절 재설정 %s → %.6g%s", symbol, stop,
                     f" · 익절 {take_profit:.6g}" if take_profit else "")
            return True
        try:
            kw = {}
            if take_profit is not None:
                # 볼린저 상단에 지정가로 걸어둔다. 시장가로 받으면
                # 백테스트가 가정한 체결가(상단 가격)와 어긋난다.
                kw = {"takeProfit": f"{take_profit:.10g}",
                      "tpTriggerBy": "LastPrice", "tpslMode": "Full",
                      "tpOrderType": "Limit", "tpLimitPrice": f"{take_profit:.10g}"}
            self.session.set_trading_stop(
                category="linear", symbol=symbol, positionIdx=0,
                stopLoss=f"{stop:.10g}", slTriggerBy="LastPrice", **kw)
            return True
        except Exception as e:
            if "34040" in str(e):        # 바꿀 내용이 없음 = 이미 같은 값
                return True
            log.error("  %s 손절 설정 실패: %s", symbol, e)
            return False

    def open_long(self, symbol: str, qty: float, stop: float,
                  take_profit: float | None = None) -> bool:
        if not self.live:
            log.info("  [모의] 진입 %s qty=%s 손절=%.6f%s", symbol, qty, stop,
                     f" 목표={take_profit:.6f}" if take_profit else "")
            return True
        kw = {}
        if take_profit is not None:
            kw = {"takeProfit": f"{take_profit:.10g}", "tpTriggerBy": "LastPrice",
                  "tpOrderType": "Limit", "tpLimitPrice": f"{take_profit:.10g}"}
        r = self.session.place_order(
            category="linear", symbol=symbol, side="Buy", orderType="Market",
            qty=str(qty), stopLoss=f"{stop:.10g}", slTriggerBy="LastPrice",
            timeInForce="IOC", reduceOnly=False, **kw)
        ok = r.get("retCode") == 0
        log.info("  진입 %s qty=%s → %s", symbol, qty, "성공" if ok else r.get("retMsg"))
        return ok

    def open_short(self, symbol: str, qty: float, stop: float) -> bool:
        if not self.live:
            log.info("  [모의] 숏 진입 %s qty=%s 손절=%.6f", symbol, qty, stop)
            return True
        r = self.session.place_order(
            category="linear", symbol=symbol, side="Sell", orderType="Market",
            qty=str(qty), stopLoss=f"{stop:.10g}", slTriggerBy="LastPrice",
            timeInForce="IOC", reduceOnly=False)
        ok = r.get("retCode") == 0
        log.info("  숏 진입 %s qty=%s → %s", symbol, qty,
                 "성공" if ok else r.get("retMsg"))
        return ok

    def close_short(self, symbol: str, qty: float, reason: str) -> bool:
        if not self.live:
            log.info("  [모의] 숏 청산 %s qty=%s (%s)", symbol, qty, reason)
            return True
        r = self.session.place_order(
            category="linear", symbol=symbol, side="Buy", orderType="Market",
            qty=str(qty), reduceOnly=True, timeInForce="IOC")
        ok = r.get("retCode") == 0
        log.info("  숏 청산 %s qty=%s (%s) → %s", symbol, qty, reason,
                 "성공" if ok else r.get("retMsg"))
        return ok

    def open_bracket(self, symbol: str, qty: float, stop: float,
                     take_profit: float) -> bool:
        """익절·손절을 둘 다 거래소에 걸고 진입한다(급락반등).

        볼린저 청산과 달리 목표가 고정이라 걸어두면 끝이다. 봇이 죽어도
        거래소가 처리한다 — 시간청산만 봇이 살아 있어야 한다.
        """
        if not self.live:
            log.info("  [모의] 급락반등 진입 %s qty=%s 손절=%.6g 익절=%.6g",
                     symbol, qty, stop, take_profit)
            return True
        r = self.session.place_order(
            category="linear", symbol=symbol, side="Buy", orderType="Market",
            qty=str(qty), timeInForce="IOC", reduceOnly=False,
            stopLoss=f"{stop:.10g}", slTriggerBy="LastPrice",
            takeProfit=f"{take_profit:.10g}", tpTriggerBy="LastPrice",
            tpOrderType="Limit", tpLimitPrice=f"{take_profit:.10g}")
        ok = r.get("retCode") == 0
        log.info("  급락반등 진입 %s qty=%s → %s", symbol, qty,
                 "성공" if ok else r.get("retMsg"))
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


def round_qty(qty: float, spec: dict, price: float | None = None) -> float:
    """수량 단위로 내림. 하한에 못 미치면 0을 돌려준다(= 주문하지 않는다).

    price를 주면 금액 하한(min_notional)도 본다. 안 주면 수량 하한만
    본다 — 청산처럼 "있는 물량을 그대로 넘기는" 자리에서는 금액 하한을
    적용하면 안 된다. 하한 미만으로 남은 포지션도 닫을 수 있어야 한다
    (거래소는 감소 주문에는 하한을 걸지 않는다).
    """
    step = spec["step"]
    q = int(qty / step) * step
    q = round(q, 10)
    if q < spec["min"]:
        return 0.0
    mn = spec.get("min_notional", 0) or 0
    if price is not None and mn and q * price < mn:
        return 0.0
    return q


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
        mods = self.st.setdefault("mod_positions", {})
        for sym in list(tracked):
            if sym not in actual:
                log.warning("상태엔 있으나 거래소에 없는 포지션 제거: %s "
                            "(손절 체결로 이미 닫혔을 수 있다)", sym)
                tracked.pop(sym)
        for sym in list(mods):
            if sym not in actual:
                log.warning("상태엔 있으나 거래소에 없는 모듈 포지션 제거: %s [%s]",
                            sym, mods[sym]["kind"])
                mods.pop(sym)
        for sym, p in actual.items():
            if sym not in tracked and sym not in mods and sym in S.SYMBOLS:
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
        for sym, p in list(self.st.get("mod_positions", {}).items()):
            self._close_mod(sym, p, reason)      # 숏은 매수로 닫는다
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
        qty2 = round_qty(notional2 / price, spec, price)
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

    def _sync_tp(self, sym: str, p: dict, closes: list) -> None:
        """볼린저 상단은 봉마다 움직인다. 매 점검마다 다시 계산해 건다.

        상단이 평단 아래면 목표로 쓸 수 없으므로(손실 확정 주문이 된다)
        그때는 걸지 않고 시간청산에 맡긴다.
        """
        tp = S.take_profit_price(closes, p["entry"])
        if tp is None:
            return
        have = p.get("tp") or 0.0
        if have > 0 and abs(tp / have - 1) <= 0.005:
            return                              # 반올림 수준의 차이는 그대로 둔다
        if self.ex.set_stop(sym, p["stop"], take_profit=tp):
            p["tp"] = tp
            save_state(self.st)

    # ── 일봉 계열 모듈 (주봉 숏 · 상승 다이버전스) ────────────────
    def _mod_gross(self) -> float:
        return sum(p["reserved"] for p in self.st.get("mod_positions", {}).values())

    def _held_symbols(self) -> set:
        """한 종목을 두 모듈이 동시에 잡지 않는다 (백테스트도 그렇다)."""
        return set(self.st["positions"]) | set(self.st.get("mod_positions", {}))

    def _close_mod(self, sym: str, p: dict, reason: str) -> bool:
        spec = self.ex.spec(sym)
        q = round_qty(p["qty"], spec)
        if not q:
            log.error("  %s 청산 수량이 0 — 수동 확인 필요", sym)
            return False
        fn = self.ex.close_short if p["side"] == "Sell" else self.ex.close_long
        if not fn(sym, q, reason):
            return False
        self.st["mod_positions"].pop(sym, None)
        save_state(self.st)
        return True

    def _daily_pass(self, equity: float, can_enter: bool) -> None:
        """하루 한 번만 도는 계열. 일봉을 받아 숏·다이버전스를 판정한다.

        4시간봉 롱은 tick()마다 돌지만 이쪽은 일봉·주봉이라 하루에 한 번
        이상 볼 이유가 없다. 42종 일봉 조회가 가볍지도 않다.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.st.get("last_daily_scan") == today:
            return
        mode = REG.read()["mode"]
        mods = self.st.setdefault("mod_positions", {})
        log.info("일봉 계열 점검 — 보유 %d건 · %s", len(mods), REG.describe())

        opened_short_this_pass = 0
        gross = sum(p["reserved"] for p in self.st["positions"].values()) + self._mod_gross()
        cap = equity * self.cfg.max_gross * self.cfg.leverage

        for sym in S.SYMBOLS:
            try:
                d = self.ex.daily(sym)
            except Exception as e:
                log.warning("%s 일봉 조회 실패: %s", sym, e)
                continue
            if len(d) < 60:
                continue
            last_bar = int(pd.Timestamp(d["dt"].iloc[-1]).value // 10**6)

            # ① 보유분 — 시간 청산
            p = mods.get(sym)
            if p is not None and p["kind"] == "crash":
                continue          # 급락반등은 4시간봉이라 tick()이 관리한다
            if p is not None:
                now_bar = last_bar
                if p["kind"] == "short":
                    # 확정된 주봉만 센다. 진행 중인 주의 라벨은 미래
                    # 월요일이라 그대로 쓰면 한 봉 일찍 닫는다.
                    w = MOD.to_weekly(d, drop_partial=True)
                    if len(w) == 0:
                        continue
                    now_bar = int(pd.Timestamp(w["dt"].iloc[-1]).value // 10**6)
                held = MOD.bars_since(p["kind"], p["signal_bar"], now_bar)
                if MOD.should_exit(p["kind"], p["signal_bar"], now_bar):
                    if self._close_mod(sym, p, f"{held}봉 경과"):
                        gross -= p["reserved"]
                else:
                    px = float(d["close"].iloc[-1])
                    sgn = -1 if p["side"] == "Sell" else 1
                    log.info("  보유 %s [%s] %d/%d봉  진입 %.6g  현재 %.6g (%.1f%%)",
                             sym, p["kind"], held, MOD.hold_bars(p["kind"]),
                             p["entry"], px, sgn * (px / p["entry"] - 1) * 100)
                continue

            # ② 신규 판정
            if not can_enter or sym in self._held_symbols():
                continue
            sig = None
            if REG.enabled("short", mode):
                sig = MOD.evaluate_short(sym, d)
                if sig and opened_short_this_pass >= MOD.SHORT_MAX_CONCURRENT:
                    # 2020-03-23에 숏 2건이 동시에 터져 그 주가 -76.7%p였다.
                    log.info("  숏 신호 %s — 이번 주 동시 진입 상한으로 건너뜀", sym)
                    sig = None
            if sig is None and REG.enabled("div", mode):
                sig = MOD.evaluate_div(sym, d)
            if sig is None:
                continue

            frac = (self.cfg.per_trade_short if sig.kind == "short"
                    else self.cfg.per_trade_div)
            notional = equity * frac          # 숏·다이버는 배율 1배
            if gross + notional > cap:
                log.info("  %s 신호 %s — 총노출 상한 초과로 건너뜀", sig.kind, sym)
                continue
            px = float(d["close"].iloc[-1])
            spec = self.ex.spec(sym)
            qty = round_qty(notional / px, spec, px)
            if qty <= 0:
                log.info("  %s 신호 %s — 수량이 최소주문량 미만", sig.kind, sym)
                continue
            stop = MOD.stop_price(px, sig.side)
            log.info("🔔 %s 신호 %s  종가 %.6g  →  %.2f USDT (%.4g개) · 손절 %.6g",
                     sig.kind, sym, px, notional, qty, stop)
            self.ex.set_leverage(sym, 1)
            if not self.ex.set_isolated(sym, 1):
                log.error("  %s 격리마진 전환 실패 — 진입을 건너뜁니다", sym)
                continue
            fn = self.ex.open_short if sig.side == "Sell" else self.ex.open_long
            if fn(sym, qty, stop):
                mods[sym] = {"kind": sig.kind, "side": sig.side, "qty": qty,
                             "entry": px, "stop": stop, "signal_bar": sig.bar_time,
                             "reserved": notional,
                             "opened_at": datetime.now(timezone.utc).isoformat()}
                gross += notional
                if sig.kind == "short":
                    opened_short_this_pass += 1
                save_state(self.st)

        self.st["last_daily_scan"] = today
        save_state(self.st)

    def _try_crash(self, sym: str, closes: list, bar_time: int,
                   equity: float, gross: float, cap: float) -> bool:
        """급락반등 진입. 익절·손절을 함께 걸어 거래소에 맡긴다."""
        notional = equity * self.cfg.per_trade_crash      # 배율 1배
        if gross + notional > cap:
            log.info("  급락반등 신호 %s — 총노출 상한 초과로 건너뜀", sym)
            return False
        price = float(closes[-1])
        spec = self.ex.spec(sym)
        qty = round_qty(notional / price, spec, price)
        if qty <= 0:
            log.info("  급락반등 신호 %s — 수량이 최소주문량 미만", sym)
            return False
        drop = (closes[-1] / closes[-2] - 1) * 100
        tp = price * (1 + MOD.CRASH_TP / 100)
        sl = price * (1 - MOD.CRASH_SL / 100)
        log.info("🔔 급락반등 %s  한 봉 %.1f%%  종가 %.6g  →  %.2f USDT (%.4g개)"
                 "  · 목표 %.6g (+%.0f%%) · 손절 %.6g (-%.0f%%)",
                 sym, drop, price, notional, qty, tp, MOD.CRASH_TP,
                 sl, MOD.CRASH_SL)
        self.ex.set_leverage(sym, 1)
        if not self.ex.set_isolated(sym, 1):
            log.error("  %s 격리마진 전환 실패 — 진입을 건너뜁니다", sym)
            return False
        if not self.ex.open_bracket(sym, qty, sl, tp):
            return False
        self.st.setdefault("mod_positions", {})[sym] = {
            "kind": "crash", "side": "Buy", "qty": qty, "entry": price,
            "stop": sl, "tp": tp, "signal_bar": bar_time,
            "reserved": notional,
            "opened_at": datetime.now(timezone.utc).isoformat()}
        save_state(self.st)
        return True

    def _verify_stops(self, positions: dict) -> None:
        """거래소에 손절이 실제로 걸려 있는지 매 점검마다 확인한다.

        진입 주문에 stopLoss를 실어 보내지만 그게 무시되거나 나중에
        취소되는 일이 있다. 손절이 없는 줄 모르고 도는 것이 이 봇에서
        가장 크게 잃는 경로다 — -40%에서 끊기라고 설계한 포지션이
        배율 2배 기준 -49.5% 강제청산까지 간다. 백테스트는 손절이
        항상 걸려 있다고 가정하므로, 그 가정이 깨지면 검증한 것과
        다른 것을 굴리는 셈이다.

        0.5% 이상 어긋나면 다시 건다. 가격 소수점 반올림 때문에
        완전히 같을 수는 없다.
        """
        if not positions:
            return
        try:
            live_pos = self.ex.positions()
        except Exception as e:
            log.warning("포지션 조회 실패 — 손절 확인을 건너뜁니다: %s", e)
            return
        for sym, p in positions.items():
            lp = live_pos.get(sym)
            if lp is None:
                continue                       # reconcile이 따로 처리한다
            want = p["stop"]
            have = lp.get("stop", 0.0)
            want_tp = p.get("tp") or None
            have_tp = lp.get("tp", 0.0)
            sl_ok = have > 0 and abs(have / want - 1) <= 0.005
            tp_ok = want_tp is None or (have_tp > 0 and abs(have_tp / want_tp - 1) <= 0.005)
            if sl_ok and tp_ok:
                continue
            if not sl_ok:
                log.error("  ⚠️ %s 손절이 %s (기대 %.6g) — 다시 겁니다",
                          sym, f"{have:.6g}" if have > 0 else "없음", want)
            if not tp_ok:
                log.error("  ⚠️ %s 익절이 %s (기대 %.6g) — 다시 겁니다",
                          sym, f"{have_tp:.6g}" if have_tp > 0 else "없음", want_tp)
            self.ex.set_stop(sym, want, take_profit=want_tp)

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
        # 모듈(숏·다이버) 노출도 같은 지갑에서 나간다 — 함께 세야 한다.
        gross = (sum(p["reserved"] for p in positions.values()) + self._mod_gross())
        mods = self.st.get("mod_positions", {})
        log.info("자본 %.2f USDT · 롱 %d종목 + 모듈 %d건 · 노출 %.0f%% · %s",
                 equity, len(positions), len(mods),
                 gross / equity * 100 if equity else 0,
                 "진입 가능" if can_enter else "진입 중단")

        self._verify_stops(positions)
        self._daily_pass(equity, can_enter)

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
            # 급락반등은 익절·손절이 거래소에 걸려 있다. 봇이 할 일은
            # 시간청산뿐이고, 거래소가 이미 닫았으면 reconcile이 치운다.
            cp = self.st.get("mod_positions", {}).get(sym)
            if cp is not None and cp["kind"] == "crash":
                held = (bar_time - cp["signal_bar"]) // BAR_MS
                if held >= MOD.CRASH_MAX_BARS:
                    if self._close_mod(sym, cp, f"{held}봉 경과"):
                        gross -= cp["reserved"]
                else:
                    log.info("  보유 %s [급락반등] %d/%d봉  진입 %.6g  현재 %.6g (%.1f%%)"
                             "  목표 %.6g  손절 %.6g",
                             sym, held, MOD.CRASH_MAX_BARS, cp["entry"], price,
                             (price / cp["entry"] - 1) * 100, cp["tp"], cp["stop"])
                continue

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
                    self._sync_tp(sym, p, closes)
                    tp = p.get("tp")
                    log.info("  보유 %s %d/%d봉 · %d/2차  평단 %.6g  현재 %.6g (%.1f%%)%s",
                             sym, held, S.HOLD_BARS, p["tranche"], p["entry"], price,
                             (price / p["entry"] - 1) * 100,
                             f"  목표 {tp:.6g} (+{(tp/p['entry']-1)*100:.1f}%)" if tp else "")
                continue

            # ② 신규 진입 판정
            if not can_enter:
                continue
            if sym in self.st.get("mod_positions", {}):
                continue          # 숏·다이버가 이미 잡고 있는 종목
            if not REG.enabled("long"):
                continue
            sig = S.evaluate(sym, closes, bar_time)
            if sig is None:
                # 과매도 롱 신호가 없으면 급락반등을 본다.
                # 둘 다 4시간봉이고 방향도 같아서 한 종목에 하나만 잡는다.
                if (REG.enabled("crash")
                        and MOD.crash_signal(closes)
                        and self._try_crash(sym, closes, bar_time, equity,
                                            gross, cap=equity * self.cfg.max_gross
                                            * self.cfg.leverage)):
                    gross += equity * self.cfg.per_trade_crash
                continue
            full_notional = equity * self.cfg.per_trade * self.cfg.leverage
            cap = equity * self.cfg.max_gross * self.cfg.leverage
            if gross + full_notional > cap:
                log.info("  신호 %s (%.1f%%) — 총노출 상한 초과로 건너뜀", sym, sig.vs_ma20)
                continue
            notional1 = full_notional * S.SCALE_IN_FIRST_FRAC
            spec = self.ex.spec(sym)
            qty1 = round_qty(notional1 / price, spec, price)
            if qty1 <= 0:
                log.info("  신호 %s — 1차 수량이 최소주문량 미만", sym)
                continue
            stop1 = S.stop_price(price)
            tp1 = S.take_profit_price(closes, price)
            trigger = S.scale_in_trigger_price(price)
            log.info("🔔 신호 %s  종가 %.6g  20MA대비 %.1f%%  →  1차 진입 %.6g USDT (%.4g개)"
                     "  · 2차 트리거 %.6g%s", sym, sig.close, sig.vs_ma20, notional1, qty1, trigger,
                     f"  · 목표 {tp1:.6g}" if tp1 else "  · 목표 없음(상단이 진입가 아래)")
            self.ex.set_leverage(sym, self.cfg.leverage)
            if not self.ex.set_isolated(sym, self.cfg.leverage):
                log.error("  %s 격리마진 전환 실패 — 진입을 건너뜁니다", sym)
                continue
            if self.ex.open_long(sym, qty1, stop1, take_profit=tp1):
                positions[sym] = {"qty": qty1, "entry": price, "stop": stop1,
                                  "tp": tp1,
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
        min_notional = max(spec["min"] * price,
                           float(spec.get("min_notional", 0) or 0))
        if round_qty(notional1 / price, spec, price) > 0:
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


def capital_table(ex, cfg, symbols, levels=None):
    """자본이 얼마면 몇 종목을 실제로 거래할 수 있는가.

    소액 계좌에서 가장 먼저 부딪히는 벽이다. 1차 진입액이 거래소
    최소주문량에 못 미치면 신호가 떠도 그냥 건너뛴다. 백테스트는
    42종 전부에서 신호를 받았으므로, 종목이 빠지면 검증한 것과
    다른 것을 굴리게 된다.

    한 번 조회한 종목 정보를 여러 자본 수준에 재사용한다 — 42종을
    자본마다 다시 조회하면 레이트리밋에 걸린다.
    """
    need = {}
    err = []
    for sym in symbols:
        try:
            spec = ex.spec(sym)
            price = float(ex.klines(sym, limit=2)[-1][4])
        except Exception:
            err.append(sym)
            continue
        # round_qty가 0을 내지 않는 최소 명목가. 거래소가 minNotional을
        # 따로 두는 경우가 있어 spec 쪽 값도 같이 본다.
        need[sym] = max(spec["min"] * price, float(spec.get("min_notional", 0) or 0))
    if not need:
        return None
    frac = cfg.per_trade * cfg.leverage * S.SCALE_IN_FIRST_FRAC
    vals = sorted(need.values())
    if levels is None:
        levels = [100, 200, 300, 500, 700, 1000, 2000, 3000, 5000, 10000]
    rows = [(cap, cap * frac, sum(1 for v in vals if v <= cap * frac))
            for cap in levels]
    return dict(need=need, err=err, frac=frac, rows=rows, n=len(need))


def smoke_test(ex, cfg, symbols) -> int:
    """주문 경로가 실제로 동작하는지 최소 금액으로 확인한다.

    모의로 몇 주를 돌린 뒤에 "주문이 안 나가네"를 발견하는 것이 가장
    나쁜 순서다. 신호를 기다릴 필요 없이 지금 확인한다.

    신호와 무관하게, 최소 주문 단위가 가장 싼 종목 하나를 골라
    사고 → 포지션을 읽고 → 손절·목표를 걸고 → 바로 닫는다. 실거래에서
    쓰는 함수를 그대로 탄다. 왕복 수수료는 명목가의 0.11% 남짓이다
    (5 USDT 주문이면 약 0.006달러).

    여기서 확인되는 것
      · API 키에 주문 권한이 있는가 (읽기 전용이면 여기서 막힌다)
      · IP 제한이 이 서버를 막고 있지 않은가
      · 최소 수량·금액 계산이 거래소와 맞는가
      · 주문이 체결되고 포지션으로 읽히는가
      · 손절·목표 주문이 실제로 걸리는가 (조용히 무시되는 경우가 있다)
      · 청산이 되는가

    포지션을 열고 못 닫는 것이 유일한 실질 위험이므로, 닫기는 실패해도
    세 번 다시 시도하고 그래도 안 되면 크게 경고한다.
    """
    print("\n" + "=" * 72)
    print("  주문 경로 점검 — 최소 금액으로 사고 바로 닫는다")
    print("=" * 72)

    # 1) 가장 싸게 살 수 있는 종목 찾기
    best = None
    for sym in symbols:
        try:
            spec = ex.spec(sym)
            price = float(ex.klines(sym, limit=2)[-1][4])
        except Exception:
            continue
        need = max(spec["min"] * price, spec.get("min_notional", 0) or 0)
        if best is None or need < best[1]:
            best = (sym, need, spec, price)
    if best is None:
        print("  ❌ 종목 정보를 하나도 조회하지 못했습니다 — 연결을 확인하세요")
        return 1
    sym, need, spec, price = best
    qty = round_qty(need * 1.05 / price, spec, price)
    if qty <= 0:
        print(f"  ❌ {sym} 최소 수량을 만들지 못했습니다 (필요 {need:.2f} USDT)")
        return 1
    notional = qty * price
    eq = ex.equity()
    print(f"\n  종목 {sym} · 현재가 {price:.6g} · 수량 {qty:g} · 명목가 {notional:.2f} USDT")
    print(f"  계좌 자본 {eq:,.2f} USDT · 예상 왕복 수수료 약 {notional * 0.0011:.3f} USDT")
    if not ex.live:
        print("\n  🟢 모의 모드입니다 — 주문은 나가지 않습니다.")
        print("     실제로 확인하려면 --live 와 OS_CONFIRM_LIVE=START 가 함께 필요합니다.")
    if ex.live and notional > eq * 0.5:
        print(f"\n  ❌ 최소 주문({notional:.2f})이 자본({eq:.2f})의 절반을 넘습니다. 중단합니다.")
        return 1

    steps = []

    def step(name, fn):
        try:
            ok = fn()
        except Exception as e:
            steps.append((name, False, f"{type(e).__name__}: {e}"))
            return False
        steps.append((name, bool(ok), "" if ok else "실패 반환"))
        return bool(ok)

    # 2) 진입 — 손절은 멀리, 목표는 걸지 않는다 (바로 닫을 것이므로)
    stop = price * 0.5
    opened = step("① 진입 주문", lambda: ex.open_long(sym, qty, stop))

    # 3) 포지션 조회
    pos = {}
    if opened:
        def read():
            nonlocal pos
            pos = ex.positions()
            return sym in pos or not ex.live
        step("② 포지션 조회", read)
        if ex.live and sym in pos:
            p = pos[sym]
            print(f"\n  체결가 {p['entry']:.6g} · 수량 {p['size']:g} · "
                  f"거래소 손절 {p['stop'] or '없음'}")

    # 4) 손절·목표 재설정
    if opened:
        entry = pos.get(sym, {}).get("entry", price)
        step("③ 손절·목표 설정",
             lambda: ex.set_stop(sym, entry * 0.5, entry * 1.5))

    # 5) 청산 — 실패해도 세 번 다시
    if opened:
        def close():
            for i in range(3):
                q = ex.positions().get(sym, {}).get("size", qty) if ex.live else qty
                q = round_qty(q, spec)      # 감소 주문에는 금액 하한이 없다
                if q <= 0:
                    return True
                if ex.close_long(sym, q, "주문 경로 점검"):
                    return True
                log.warning("  청산 실패 — 재시도 %d/3", i + 2)
                time.sleep(2)
            return False
        if not step("④ 청산", close):
            print("\n  🚨 포지션을 닫지 못했습니다. 거래소 앱에서 직접 닫으세요:")
            print(f"     {sym} 롱 {qty:g}")

    print(f"\n  {'단계':<20s}{'결과':>8s}")
    print("  " + "-" * 50)
    for name, ok, why in steps:
        print(f"  {name:<20s}{'✅ 통과' if ok else '❌ 실패':>8s}"
              + (f"   {why}" if why else ""))
    bad = [n for n, ok, _ in steps if not ok]
    print("\n  " + ("✅ 주문 경로 정상입니다." if not bad
                    else f"❌ {len(bad)}단계 실패 — 위 메시지를 확인하세요."))
    print("=" * 72)
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="실거래 (기본은 모의)")
    # systemd·컨테이너에서는 START를 타이핑할 사람이 없다. 그렇다고
    # 확인 절차를 그냥 없애면 실수로 실거래가 도는 길이 생긴다.
    # 그래서 플래그와 환경변수 둘 다 있어야만 통과시킨다 —
    # 어느 한쪽만으로는 절대 켜지지 않는다.
    ap.add_argument("--live-nonint", action="store_true",
                    help="실거래 (무인). OS_CONFIRM_LIVE=START 도 함께 필요")
    ap.add_argument("--once", action="store_true", help="1회만 점검하고 종료")
    ap.add_argument("--capital-table", action="store_true",
                    help="자본이 얼마면 몇 종목을 거래할 수 있는지 표로 보고 종료")
    ap.add_argument("--smoke-test", action="store_true",
                    help="최소 금액으로 사고 바로 닫아 주문 경로만 확인하고 종료")
    ap.add_argument("--dump-candles", action="store_true", help="조회한 캔들 저장")
    ap.add_argument("--close-all", action="store_true", help="전량 청산하고 종료")
    ap.add_argument("--regime", choices=REG.MODES,
                    help="국면 스위치를 바꾸고 종료 (봇이 돌고 있어도 다음 틱에 반영된다)")
    ap.add_argument("--note", default="", help="--regime 과 함께 남길 메모")
    a = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                        datefmt="%m-%d %H:%M:%S")

    if a.regime:
        print("  " + REG.describe(REG.write(a.regime, a.note)))
        return

    load_env()
    cfg = Config()

    if a.live_nonint:
        if os.getenv("OS_CONFIRM_LIVE") != "START":
            print("  ⛔ --live-nonint 는 환경변수 OS_CONFIRM_LIVE=START 가 있어야 합니다.")
            print("     (사람이 없는 환경에서 실수로 실거래가 도는 것을 막기 위한 이중 잠금)")
            return
        a.live = True

    mode = "🔴 실거래" if a.live else "🟢 모의(dry-run)"
    print("=" * 84)
    print(f"  과매도 자동매매 — 바이빗 무기한, {len(S.SYMBOLS)}종(백테스트 {len(S.ALL_SYMBOLS)}종 중 "
          f"상장폐지 4종 제외), 4시간봉")
    print(f"  {mode}   {cfg.describe()}")
    print(f"  규칙: 20기간선 대비 {S.ENTRY_THRESH}% 이하 → 1차 {S.SCALE_IN_FIRST_FRAC*100:.0f}% 진입, "
          f"거기서 {S.SCALE_IN_TRIGGER_PCT}% 더 빠지면 2차 {(1-S.SCALE_IN_FIRST_FRAC)*100:.0f}% 추가")
    print(f"        → 볼린저 상단({S.BB_PERIOD}봉·{S.BB_K}σ) 도달 시 목표청산, "
          f"안 닿으면 {S.HOLD_BARS}봉 시간청산 · 손절(평단 대비) {S.STOP_PCT}%")
    print(f"  {REG.describe()}")
    print("=" * 84)

    if a.live and not a.live_nonint:
        print("\n  ⚠️  실제 자금으로 주문을 냅니다.")
        print(f"     배율 {cfg.leverage:g}x, 거래 1건의 전체 물량은 자본의 "
              f"{cfg.per_trade*100:.1f}%(최대 {int(1/cfg.per_trade)}건 동시), "
              f"그중 1차는 {cfg.per_trade*S.SCALE_IN_FIRST_FRAC*100:.1f}%만 즉시 나갑니다.")
        print(f"     백테스트(2배·총노출 60%·차단기 20%·복리·왕복 0.40%) 8.9년 기준:")
        print(f"       롱 단독  3.14배 · 최대낙폭 21.6% · 승률 81% · 1년 손실확률 29%")
        print(f"       숏·다이버전스까지 붙이면 21.5배 · 낙폭 21.6% · 1년 손실확률 1%")
        print(f"       (숏·다이버전스는 아직 백테스트에만 있다 — ml/report.py 참고)")
        print(f"     실제 체결은 백테스트보다 나쁠 수 있습니다.")
        if input("\n  계속하려면 START 입력: ").strip() != "START":
            print("  중단했습니다."); return
    elif a.live_nonint:
        log.warning("무인 실거래로 시작합니다 (OS_CONFIRM_LIVE 확인됨)")

    ex = Exchange(live=a.live)

    if a.smoke_test:
        raise SystemExit(smoke_test(ex, cfg, S.SYMBOLS))

    if a.capital_table:
        t = capital_table(ex, cfg, S.SYMBOLS)
        if t is None:
            raise SystemExit("종목 정보를 하나도 조회하지 못했습니다 — 연결을 확인하세요")
        print(f"\n  1차 진입액 = 자본 × {cfg.per_trade*100:.1f}% × {cfg.leverage:.0f}배"
              f" × {S.SCALE_IN_FIRST_FRAC*100:.0f}% = 자본의 {t['frac']*100:.2f}%")
        print(f"  조회된 종목 {t['n']}종"
              + (f" (실패 {len(t['err'])}종)" if t["err"] else ""))
        print(f"\n  {'자본':>9s}{'1차 진입액':>12s}{'거래 가능':>11s}")
        print("  " + "-" * 34)
        for cap, n1, k in t["rows"]:
            bar = "" if k else "   ← 한 종목도 못 산다"
            print(f"  {cap:>8,}${n1:>11.2f}${k:>8}/{t['n']}종{bar}")
        cheap = sorted(t["need"].items(), key=lambda x: x[1])[:5]
        print(f"\n  가장 싼 5종 (최소주문액):")
        for sym, v in cheap:
            print(f"    {sym:12s}{v:>8.2f}$  → 자본 {v/t['frac']:>9,.0f}$ 필요")
        print(f"\n  전 종목을 거래하려면 자본 {max(t['need'].values())/t['frac']:,.0f}$ 필요")
        return

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
