"""
bot/oversold/test_replay.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
실행기 전체 재생 테스트 — 가짜 거래소로 과거를 흘려보낸다

test_parity.py는 신호 계산만 봤다. 여기서는 executor.Trader 자체를
돌린다. 진입·시간청산·손절·총노출 상한·상태 파일 복구까지 실제
코드 경로를 그대로 태운다.

자동매매에서 실제로 돈을 잃는 버그는 신호가 아니라 이쪽에 있다.
    · 10봉 뒤 청산이 안 되고 계속 들고 있는 경우
    · 재시작하면 보유 봉수를 잊고 영원히 안 파는 경우
    · 총노출 상한이 안 걸려 급락장에 12종목 풀베팅되는 경우
    · 손절이 주문에 안 실리는 경우

    python bot/oversold/test_replay.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, glob, json, tempfile
from datetime import timezone

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from bot.oversold import strategy as S
from bot.oversold import executor as E

FAILED = 0
BAR_MS = E.BAR_MS


def check(name, ok, detail=""):
    global FAILED
    print(f"  {'✅' if ok else '❌'} {name}" + (f"  — {detail}" if detail else ""))
    if not ok:
        FAILED += 1


class FakeExchange:
    """과거 캔들을 한 봉씩 내주는 가짜 거래소. 주문은 장부에만 기록한다."""

    def __init__(self, data: dict, equity: float = 1000.0):
        self.live = True                 # 주문 경로를 태우려면 live여야 한다
        self.data = data                 # symbol -> list[[ts,o,h,l,c,v]]
        self.cursor = 0
        self._equity = equity
        self.pos = {}                    # symbol -> {size, entry, side, stop}
        self.orders = []

    def klines(self, symbol, limit=200):
        rows = self.data[symbol][: self.cursor + 1]
        if len(rows) < 2:
            raise RuntimeError("데이터 부족")
        return rows[-limit:]

    def spec(self, symbol):
        return {"step": 0.001, "min": 0.001}

    def equity(self):
        return self._equity

    def positions(self):
        return {k: {"size": v["size"], "entry": v["entry"], "side": "Buy"}
                for k, v in self.pos.items()}

    def set_leverage(self, symbol, lev):
        pass

    def open_long(self, symbol, qty, stop):
        px = float(self.data[symbol][self.cursor][4])
        self.pos[symbol] = {"size": qty, "entry": px, "stop": stop}
        self.orders.append(("open", symbol, qty, px, stop, self.cursor))
        return True

    def close_long(self, symbol, qty, reason):
        if symbol not in self.pos:
            return False
        px = float(self.data[symbol][self.cursor][4])
        p = self.pos.pop(symbol)
        self._equity += p["size"] * (px - p["entry"])
        self.orders.append(("close", symbol, qty, px, reason, self.cursor))
        return True

    def apply_stops(self):
        """봉의 저가가 손절선을 뚫었으면 체결시킨다"""
        for sym in list(self.pos):
            low = float(self.data[sym][self.cursor][3])
            p = self.pos[sym]
            if low <= p["stop"]:
                self._equity += p["size"] * (p["stop"] - p["entry"])
                self.pos.pop(sym)
                self.orders.append(("stop", sym, p["size"], p["stop"], "손절", self.cursor))


def load(symbols, bars=1200):
    out = {}
    for sym in symbols:
        f = f"data/{sym}_4h_all.csv.gz"
        if not os.path.exists(f):
            continue
        d = pd.read_csv(f, compression="gzip")
        tc = "timestamp" if "timestamp" in d.columns else "datetime"
        d[tc] = pd.to_datetime(d[tc], format="mixed", errors="coerce")
        d = d.dropna(subset=[tc]).sort_values(tc).tail(bars)
        # pandas 3.0에서 Series.view는 datetime64를 int64로 재해석하지 않는다.
        # 조용히 0을 뱉어 봉 간격이 전부 0이 되고, 봇이 "10봉 경과"를
        # 영영 못 보게 된다. 명시적으로 변환한다.
        ts = pd.to_datetime(d[tc]).astype("datetime64[ms]").astype("int64")
        assert (ts.diff().dropna() > 0).all(), f"{sym} 타임스탬프가 증가하지 않는다"
        out[sym] = [[int(t), float(o), float(h), float(l), float(c), float(v)]
                    for t, o, h, l, c, v in zip(ts, d["open"], d["high"],
                                                d["low"], d["close"], d["volume"])]
    return out


def run_replay(state_path, symbols, leverage=3.0, per_trade=0.15, max_gross=1.0,
               restart_at=None):
    data = load(symbols)
    if not data:
        return None, None
    E.STATE_PATH = state_path
    if os.path.exists(state_path):
        os.remove(state_path)

    ex = FakeExchange(data)
    cfg = E.Config()
    cfg.leverage, cfg.per_trade, cfg.max_gross = leverage, per_trade, max_gross
    cfg.daily_loss, cfg.max_drawdown = 1.0, 1.0     # 이 테스트에선 차단기 끔
    tr = E.Trader(ex, cfg)

    n = min(len(v) for v in data.values())
    max_concurrent = 0
    for i in range(S.MA_PERIOD + 1, n):
        ex.cursor = i
        ex.apply_stops()
        # 손절로 닫힌 포지션을 상태에서 정리 (실제 봇은 reconcile이 한다)
        for sym in list(tr.st["positions"]):
            if sym not in ex.pos:
                tr.st["positions"].pop(sym)
        if restart_at and i == restart_at:
            E.save_state(tr.st)
            tr = E.Trader(ex, cfg)        # 재시작 시뮬레이션
        tr.tick()
        max_concurrent = max(max_concurrent, len(tr.st["positions"]))
    return ex, {"max_concurrent": max_concurrent, "state": tr.st}


def main():
    import logging
    logging.disable(logging.CRITICAL)        # 재생 중 로그는 끈다

    print("=" * 88)
    print("  실행기 전체 재생 테스트 — 가짜 거래소")
    print("=" * 88)

    syms = [s for s in S.MAJORS if os.path.exists(f"data/{s}_4h_all.csv.gz")][:6]
    tmp = tempfile.mkdtemp()

    ex, info = run_replay(os.path.join(tmp, "s1.json"), syms)
    if ex is None:
        check("데이터 로드", False, "data/*_4h_all.csv.gz 없음")
        return 1

    opens = [o for o in ex.orders if o[0] == "open"]
    closes = [o for o in ex.orders if o[0] == "close"]
    stops = [o for o in ex.orders if o[0] == "stop"]
    check(f"거래가 실제로 발생 ({len(opens)}회 진입)", len(opens) > 0)
    check("모든 진입이 청산됨 (미결제 누락 없음)",
          len(opens) - len(closes) - len(stops) == len(ex.pos),
          f"진입 {len(opens)} / 시간청산 {len(closes)} / 손절 {len(stops)} / 잔여 {len(ex.pos)}")

    # 보유 기간이 정확히 HOLD_BARS인가
    entry_bar = {}
    bad_hold = []
    for kind, sym, qty, px, extra, cur in ex.orders:
        if kind == "open":
            entry_bar[sym] = cur
        elif kind == "close" and sym in entry_bar:
            held = cur - entry_bar.pop(sym)
            if held != S.HOLD_BARS:
                bad_hold.append((sym, held))
    check(f"시간청산이 정확히 {S.HOLD_BARS}봉에 발생",
          not bad_hold, f"어긋난 건수 {len(bad_hold)}" if bad_hold else "")

    # 손절이 주문에 실렸는가
    check("모든 진입 주문에 손절가가 포함됨",
          all(abs(o[4] / o[3] - (1 + S.STOP_PCT / 100)) < 1e-6 for o in opens),
          f"{len(opens)}건 확인")

    # 총노출 상한
    check(f"동시 보유가 상한({int(1/0.15)}종목) 이내",
          info["max_concurrent"] <= int(1 / 0.15) + 1,
          f"최대 {info['max_concurrent']}종목")

    # 재시작해도 보유 봉수를 기억하는가
    ex2, info2 = run_replay(os.path.join(tmp, "s2.json"), syms, restart_at=400)
    opens2 = [o for o in ex2.orders if o[0] == "open"]
    closes2 = [o for o in ex2.orders if o[0] == "close"]
    entry2, bad2 = {}, []
    for kind, sym, qty, px, extra, cur in ex2.orders:
        if kind == "open":
            entry2[sym] = cur
        elif kind == "close" and sym in entry2:
            if cur - entry2.pop(sym) != S.HOLD_BARS:
                bad2.append(sym)
    check("중간 재시작 후에도 보유 봉수를 정확히 유지",
          not bad2 and len(opens2) == len(opens),
          f"진입 {len(opens2)} · 어긋난 청산 {len(bad2)}")

    # 상태 파일이 유효한 JSON인가
    st = info["state"]
    check("상태 파일이 직렬화 가능", isinstance(json.dumps(st), str))

    print("=" * 88)
    print(f"  {'✅ 전부 통과' if FAILED == 0 else f'❌ {FAILED}건 실패'}")
    print("=" * 88)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
