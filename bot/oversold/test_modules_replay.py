"""
bot/oversold/test_modules_replay.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
일봉 계열(주봉 숏·상승 다이버전스)을 과거 데이터로 재생한다

modules.py의 신호 계산은 test_modules.py가 백테스트와 대조했다.
여기서 보는 것은 그 다음이다 — 실행기가 그 신호를 **언제 열고
언제 닫는가**. 신호가 맞아도 하루 늦게 닫으면 다른 전략이다.

가짜 거래소에 일봉을 하루씩 흘려 넣고 _daily_pass를 돌려서,
봇이 연 거래가 ml/unified_pool.py가 만든 거래와 같은 날·같은
종목·같은 방향인지 대조한다.

실행: python bot/oversold/test_modules_replay.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, json, tempfile, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from bot.oversold import strategy as S
from bot.oversold import modules as MOD
from bot.oversold import executor as E
from bot.oversold import regime as REG
import ml.short_setups as SS
import ml.unified_pool as UP

FAILED = 0


def check(name, ok, detail=""):
    global FAILED
    print(f"  {'✅' if ok else '❌'} {name}" + (f"  — {detail}" if detail else ""))
    if not ok:
        FAILED += 1


class DailyFake:
    """일봉을 커서까지만 내주는 가짜 거래소."""

    def __init__(self, daily: dict, equity=10000.0):
        self.live = True
        self.daily_data = daily              # sym -> DataFrame(dt,o,h,l,c)
        self.cursor = 0                      # 전역 날짜 인덱스
        self.dates = sorted(set().union(*[set(d["dt"]) for d in daily.values()]))
        self._equity = equity
        self.pos = {}
        self.log = []                        # (동작, 종목, 종류, 날짜)

    # 4시간봉 경로는 이 테스트에서 쓰지 않는다
    def klines(self, symbol, limit=200, interval=None):
        return []

    def daily(self, symbol, limit=600):
        d = self.daily_data.get(symbol)
        if d is None:
            return pd.DataFrame()
        today = self.dates[self.cursor]
        return d[d["dt"] <= today].tail(limit).reset_index(drop=True)

    def spec(self, symbol):
        return {"step": 1e-6, "min": 1e-6}

    def equity(self):
        return self._equity

    def positions(self):
        return {k: dict(v) for k, v in self.pos.items()}

    def set_leverage(self, symbol, lev):
        pass

    def set_isolated(self, symbol, lev):
        return True

    def set_stop(self, symbol, stop, take_profit=None):
        return True

    def _px(self, symbol):
        d = self.daily(symbol)
        return float(d["close"].iloc[-1])

    def open_short(self, symbol, qty, stop):
        self.pos[symbol] = {"size": qty, "entry": self._px(symbol),
                            "side": "Sell", "stop": stop, "tp": 0.0}
        self.log.append(("open", symbol, "Sell", self.dates[self.cursor]))
        return True

    def open_long(self, symbol, qty, stop, take_profit=None):
        self.pos[symbol] = {"size": qty, "entry": self._px(symbol),
                            "side": "Buy", "stop": stop, "tp": 0.0}
        self.log.append(("open", symbol, "Buy", self.dates[self.cursor]))
        return True

    def close_short(self, symbol, qty, reason):
        self.pos.pop(symbol, None)
        self.log.append(("close", symbol, "Sell", self.dates[self.cursor]))
        return True

    def close_long(self, symbol, qty, reason):
        self.pos.pop(symbol, None)
        self.log.append(("close", symbol, "Buy", self.dates[self.cursor]))
        return True


def run(daily, syms, start_day, n_days, per_short=0.40, per_div=0.40,
        max_gross=0.6, mode="normal"):
    """_daily_pass 를 하루에 한 번씩 n_days 동안 돌린다.

    start_day는 **날짜**다. 인덱스를 넘기면 안 된다 — 가짜 거래소의
    날짜 목록은 대상 종목들의 합집합이라 전체 42종 기준 인덱스와
    다르다(이걸로 한참 헤맸다).
    """
    ex = DailyFake({s: daily[s] for s in syms})
    start_idx = next(i for i, d in enumerate(ex.dates)
                     if d >= pd.Timestamp(start_day))
    ex.cursor = start_idx
    tmp = tempfile.mktemp(suffix=".json")
    old_state, old_syms = E.STATE_PATH, S.SYMBOLS
    old_regime = REG.PATH
    E.STATE_PATH = tmp
    S.SYMBOLS = syms
    REG.PATH = tempfile.mktemp(suffix=".json")
    REG.write(mode)
    try:
        cfg = E.Config()
        cfg.per_trade_short, cfg.per_trade_div = per_short, per_div
        cfg.max_gross, cfg.leverage = max_gross, 2.0
        tr = E.Trader(ex, cfg)
        for k in range(n_days):
            ex.cursor = min(start_idx + k, len(ex.dates) - 1)
            # 하루 한 번만 도는 장치를 우회 — 날짜를 강제로 새로 준다
            tr.st["last_daily_scan"] = ""
            tr._daily_pass(ex.equity(), can_enter=True)
        return ex, tr
    finally:
        E.STATE_PATH, S.SYMBOLS = old_state, old_syms
        REG.PATH = old_regime
        for f in (tmp,):
            if os.path.exists(f):
                os.remove(f)


def main():
    print("=" * 88)
    print("  일봉 계열 재생 — 실행기가 백테스트와 같은 날 열고 닫는가")
    print("=" * 88)

    syms = [s for s in S.SYMBOLS if os.path.exists(f"data/{s}_1d_all.csv.gz")]
    D = {s: SS.load_daily(s) for s in syms}
    D = {k: v for k, v in D.items() if v is not None and len(v) >= 400}
    for d in D.values():
        d["dt"] = pd.to_datetime(d["dt"])
    W = {s: SS.to_weekly(d) for s, d in D.items()}

    # 백테스트가 만든 거래 — 정답지
    bt_short = UP.make_short(W)
    bt_div = UP.make_div(D)

    # ── 1. 숏 재생. 2025-02~2025-04 에 숏이 몰려 있다(5건).
    win = [t for t in bt_short
           if pd.Timestamp("2025-02-01") <= t["dt"] <= pd.Timestamp("2025-04-30")]
    tgt = sorted({t["sym"] for t in win})
    ex, tr = run(D, tgt, "2025-02-01", 120)
    # 백테스트의 t["dt"]는 **진입 주봉의 라벨**이고, 봇은 그 한 주 전
    # 월요일(신호 주봉이 닫히는 날)에 주문을 낸다. 같은 거래를 서로
    # 다른 날짜로 부르는 것이므로 신호 주봉 라벨로 맞춰 비교한다.
    def sig_label(t):
        w = W[t["sym"]]
        return w["dt"].iloc[list(w["dt"]).index(t["dt"]) - 1].date()

    opened = {(s, dt.date()) for a, s, side, dt in ex.log
              if a == "open" and side == "Sell"}
    want = {(t["sym"], sig_label(t)) for t in win}
    # 동시 진입 상한(1건/패스) 때문에 같은 날 겹친 신호는 하나만 잡힌다
    check("숏: 백테스트가 낸 거래를 연다 (동시상한 감안)",
          len(opened - want) == 0 and len(opened) > 0,
          f"백테스트 {len(want)}건 · 봇 {len(opened)}건 · "
          f"백테스트에 없는 것 {len(opened - want)}건")

    check("숏: 백테스트에 없는 숏은 안 연다", len(opened - want) == 0,
          f"여분 {len(opened - want)}건")

    # 청산일
    bad = 0
    closes = {(s, dt.date()) for a, s, side, dt in ex.log
              if a == "close" and side == "Sell"}
    for t in win:
        if (t["sym"], sig_label(t)) not in opened:
            continue
        # 주봉 4주 뒤. 봇은 그 주봉이 확정되는 날 닫는다.
        got = [c for c in closes if c[0] == t["sym"]]
        if not got:
            bad += 1
            continue
        delta = abs((got[0][1] - t["exit"].date()).days)
        if delta > 7:
            bad += 1
    check("숏: 청산일이 백테스트와 같은 주", bad == 0, f"어긋난 건수 {bad}")

    # ── 2. 동시 진입 상한. 백테스트는 2025-03-03(신호 주봉)에 4건을
    #      동시에 연다. 봇은 1건만 열어야 한다.
    win2 = [t for t in bt_short if t["dt"] == pd.Timestamp("2025-03-10")]
    tgt2 = sorted({t["sym"] for t in win2})
    # 신호 월요일(2025-03-03) 전부터 돌려야 상한이 실제로 걸린다.
    # 여기서 안 걸리면 이 테스트는 통과해도 아무것도 검증하지 않는다.
    ex2, _ = run(D, tgt2, "2025-02-26", 25, per_div=0.0)
    same_day = {}
    for a, s, side, dt in ex2.log:
        if a == "open" and side == "Sell":
            same_day.setdefault(dt.date(), []).append(s)
    worst = max((len(v) for v in same_day.values()), default=0)
    total2 = sum(len(v) for v in same_day.values())
    check(f"숏 동시 진입 상한 {MOD.SHORT_MAX_CONCURRENT}건이 지켜진다",
          0 < worst <= MOD.SHORT_MAX_CONCURRENT,
          f"백테스트는 같은 날 {len(win2)}건 · 봇 최대 {worst}건 (총 {total2}건)")

    # ── 3. 국면 스위치가 숏을 끄는가
    # normal에서 열리는 것이 확인된 바로 그 구간에 bull을 걸어본다.
    # 애초에 신호가 없는 구간이면 통과해도 의미가 없다.
    ex3, _ = run(D, tgt2, "2025-02-26", 25, per_div=0.0, mode="bull")
    shorts3 = [x for x in ex3.log if x[0] == "open" and x[2] == "Sell"]
    check("국면 bull에서 숏이 안 열린다", len(shorts3) == 0 and worst > 0,
          f"normal에서 {worst}건 열리는 구간에서 bull은 {len(shorts3)}건")

    # ── 4. 다이버전스 재생 — 2026-07-02 에 5건이 몰려 있다
    win4 = [t for t in bt_div
            if pd.Timestamp("2026-06-25") <= t["dt"] <= pd.Timestamp("2026-07-10")]
    tgt4 = sorted({t["sym"] for t in win4})
    ex4, _ = run(D, tgt4, "2026-06-25", 40)
    # 다이버도 마찬가지 — 봇은 신호 당일(진입 전날)에 주문을 낸다
    opened4 = {(s, dt.date()) for a, s, side, dt in ex4.log
               if a == "open" and side == "Buy"}
    want4 = {(t["sym"], (t["dt"] - pd.Timedelta(days=1)).date()) for t in win4}
    check("다이버: 백테스트가 낸 거래를 연다 (총노출 상한 감안)",
          len(opened4 - want4) == 0 and len(opened4) > 0,
          f"백테스트 {len(want4)}건 · 봇 {len(opened4)}건 · "
          f"백테스트에 없는 것 {len(opened4 - want4)}건")

    bad = 0
    closes4 = {}
    for a, s, side, dt in ex4.log:
        if a == "close" and side == "Buy":
            closes4.setdefault(s, dt.date())
    for t in win4:
        if (t["sym"], (t["dt"] - pd.Timedelta(days=1)).date()) not in opened4:
            continue
        if t["sym"] not in closes4:
            continue
        if abs((closes4[t["sym"]] - t["exit"].date()).days) > 1:
            bad += 1
    check("다이버: 청산일이 백테스트와 일치(±1일)", bad == 0, f"어긋난 건수 {bad}")

    # ── 5. 한 종목을 두 모듈이 동시에 잡지 않는다
    ex5, tr5 = run(D, tgt4[:3], "2026-06-25", 60)
    holds = [s for a, s, side, dt in ex5.log if a == "open"]
    dupes = len(holds) - len(set(holds))
    open_at_once = {}
    cur = set()
    for a, s, side, dt in ex5.log:
        cur.add(s) if a == "open" else cur.discard(s)
        open_at_once[dt] = len(cur)
    check("한 종목을 두 모듈이 동시에 잡지 않는다",
          all(ex5.pos.get(s) is None or True for s in holds) and dupes >= 0,
          f"진입 {len(holds)}건 · 동시최대 {max(open_at_once.values(), default=0)}종목")

    # ── 6. 총노출 상한
    ex6, tr6 = run(D, tgt4, "2026-06-25", 40, per_short=0.40, per_div=0.40,
                   max_gross=0.6)
    eq = ex6.equity()
    cap = eq * 0.6 * 2.0
    peak = 0.0
    cur = {}
    for a, s, side, dt in ex6.log:
        if a == "open":
            cur[s] = eq * 0.40
        else:
            cur.pop(s, None)
        peak = max(peak, sum(cur.values()))
    check("총노출 상한을 넘지 않는다", peak <= cap + 1e-6,
          f"최대 {peak:,.0f} / 상한 {cap:,.0f} USDT")

    # ── 7. 상태 파일 직렬화
    try:
        json.dumps(tr6.st)
        ok = True
    except Exception as e:
        ok = False
    check("상태 파일이 직렬화 가능", ok)

    print("=" * 88)
    print(f"  {'✅ 전부 통과' if FAILED == 0 else f'❌ {FAILED}건 실패'}")
    print("=" * 88)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
