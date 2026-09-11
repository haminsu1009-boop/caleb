"""
bot/oversold/test_replay.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
실행기 전체 재생 테스트 — 가짜 거래소로 과거를 흘려보낸다

test_parity.py는 신호 계산만 봤다. 여기서는 executor.Trader 자체를
돌린다. 진입·2차 분할매수·시간청산·손절·총노출 상한·상태 파일
복구까지 실제 코드 경로를 그대로 태운다.

자동매매에서 실제로 돈을 잃는 버그는 신호가 아니라 이쪽에 있다.
    · 20봉 뒤 청산이 안 되고 계속 들고 있는 경우
    · 2차 매수가 1차를 덮어쓰거나 평단을 잘못 계산하는 경우
    · 재시작하면 보유 봉수를 잊고 영원히 안 파는 경우
    · 총노출 상한이 안 걸려 급락장에 풀베팅되는 경우
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
        # 실제 거래소는 손절가도 함께 돌려준다. _verify_stops가 이걸
        # 읽어 손절이 빠졌는지 본다. drop_stops에 넣은 심볼은 손절이
        # 사라진 상황을 흉내낸다.
        return {k: {"size": v["size"], "entry": v["entry"], "side": "Buy",
                    "stop": 0.0 if k in getattr(self, "drop_stops", set())
                            else v.get("stop", 0.0)}
                for k, v in self.pos.items()}

    def set_stop(self, symbol, stop):
        if symbol in self.pos:
            self.pos[symbol]["stop"] = stop
            self.orders.append(("setstop", symbol, 0.0, stop, "재설정", self.cursor))
        return True

    def set_leverage(self, symbol, lev):
        pass

    def set_isolated(self, symbol, lev):
        # 실거래에서는 여기서 실패하면 그 종목을 건너뛴다. 재생
        # 테스트는 신호·수량·노출을 보는 것이라 항상 성공으로 둔다.
        # (전환 실패 경로는 fail_isolated로 따로 시험한다)
        return symbol not in getattr(self, "fail_isolated", set())

    def open_long(self, symbol, qty, stop):
        px = float(self.data[symbol][self.cursor][4])
        if symbol in self.pos:
            # 이미 포지션이 있다 — 2차 분할매수다. 실제 거래소처럼 같은
            # 심볼에 시장가를 또 내면 수량이 합쳐지고 평단이 갱신된다.
            old = self.pos[symbol]
            new_qty = old["size"] + qty
            new_entry = (old["entry"] * old["size"] + px * qty) / new_qty
            self.pos[symbol] = {"size": new_qty, "entry": new_entry, "stop": stop}
            self.orders.append(("add", symbol, qty, px, stop, self.cursor))
        else:
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

    syms = [s for s in S.SYMBOLS if os.path.exists(f"data/{s}_4h_all.csv.gz")][:10]
    tmp = tempfile.mkdtemp()

    ex, info = run_replay(os.path.join(tmp, "s1.json"), syms)
    if ex is None:
        check("데이터 로드", False, "data/*_4h_all.csv.gz 없음")
        return 1

    opens = [o for o in ex.orders if o[0] == "open"]     # 1차(신규 포지션)만
    adds  = [o for o in ex.orders if o[0] == "add"]       # 2차 분할매수
    closes = [o for o in ex.orders if o[0] == "close"]
    stops = [o for o in ex.orders if o[0] == "stop"]
    check(f"거래가 실제로 발생 ({len(opens)}회 진입)", len(opens) > 0)
    check(f"분할매수 2차가 실제로 걸림 ({len(adds)}회)", len(adds) > 0)
    check("모든 진입이 청산됨 (미결제 누락 없음)",
          len(opens) - len(closes) - len(stops) == len(ex.pos),
          f"진입 {len(opens)} / 시간청산 {len(closes)} / 손절 {len(stops)} / 잔여 {len(ex.pos)}")

    # 보유 기간이 정확히 HOLD_BARS인가 (1차 진입 시점부터 — 2차는 기준점을 안 바꾼다)
    entry_bar = {}
    bad_hold = []
    for kind, sym, qty, px, extra, cur in ex.orders:
        if kind == "open":
            entry_bar[sym] = cur
        elif kind == "close" and sym in entry_bar:
            held = cur - entry_bar.pop(sym)
            if held != S.HOLD_BARS:
                bad_hold.append((sym, held))
    check(f"시간청산이 정확히 {S.HOLD_BARS}봉에 발생 (1차 기준)",
          not bad_hold, f"어긋난 건수 {len(bad_hold)}" if bad_hold else "")

    # 1차 진입 주문의 손절가 — 1차 체결가 기준으로 정확한가
    check("1차 진입 주문에 손절가가 정확히 실림",
          all(abs(o[4] / o[3] - (1 + S.STOP_PCT / 100)) < 1e-6 for o in opens),
          f"{len(opens)}건 확인")

    # 2차 진입 주문을 주문 로그만으로 재구성해서 두 가지를 같이 대조한다
    # (executor의 실제 계산과 별개 경로로 다시 계산해야 검증 의미가 있다).
    # 심볼이 여러 번 진입/청산을 반복할 수 있으므로 close/stop에서
    # 추적을 반드시 리셋해야 다음 사이클의 add가 이전 사이클의 open과
    # 잘못 짝지어지지 않는다.
    track, bad_stop, bad_dir = {}, [], []
    for kind, sym, qty, px, stop_or_reason, cur in ex.orders:
        if kind == "open":
            track[sym] = {"qty": qty, "entry": px}
        elif kind == "add":
            old = track.get(sym)
            if old is None:
                bad_stop.append((sym, "1차 기록 없음")); continue
            if px >= old["entry"]:
                bad_dir.append((sym, px, old["entry"]))
            expect_entry = S.blended_entry(old["entry"], old["qty"], px, qty)
            expect_stop = S.stop_price(expect_entry)
            if abs(stop_or_reason - expect_stop) > 1e-6:
                bad_stop.append((sym, f"{stop_or_reason:.6g} != {expect_stop:.6g}"))
            track[sym] = {"qty": old["qty"] + qty, "entry": expect_entry}
        elif kind in ("close", "stop"):
            track.pop(sym, None)
    check("2차 진입 주문의 손절가가 재구성한 평단과 일치",
          not bad_stop, f"불일치 {len(bad_stop)}건: {bad_stop[:3]}" if bad_stop else "")
    # 2차가 1차보다 같거나 비싼 값에 걸리면 시간분할과 같은 문제가 된다
    # (평단이 나빠짐) — ml/scale_in.py가 확인한 "가격 조건이라야 한다"는
    # 전제가 실거래 코드에서도 지켜지는지 보는 것이다.
    check("2차 매수는 전부 1차보다 낮은 가격에서만 체결됨",
          not bad_dir, f"위반 {len(bad_dir)}건: {bad_dir[:3]}" if bad_dir else "")

    # 총노출 상한 — per_trade는 이제 전체(1차+2차) 물량 기준이므로 동시
    # "포지션 수" 상한 자체는 바뀌지 않는다
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

    # ── 손절이 거래소에서 사라지면 다시 거는가
    # 진입 주문에 stopLoss를 실어 보내도 무시되거나 나중에 취소되는
    # 일이 있다. 손절 없이 도는 것이 이 봇에서 가장 크게 잃는 경로다.
    data = load(syms)
    E.STATE_PATH = os.path.join(tmp, "s3.json")
    if os.path.exists(E.STATE_PATH):
        os.remove(E.STATE_PATH)
    ex3 = FakeExchange(data)
    cfg3 = E.Config()
    cfg3.leverage, cfg3.per_trade, cfg3.max_gross = 3.0, 0.15, 1.0
    cfg3.daily_loss, cfg3.max_drawdown = 1.0, 1.0
    tr3 = E.Trader(ex3, cfg3)
    n3 = min(len(v) for v in data.values())
    dropped_once = False
    for i in range(S.MA_PERIOD + 1, n3):
        ex3.cursor = i
        ex3.apply_stops()
        for sym in list(tr3.st["positions"]):
            if sym not in ex3.pos:
                tr3.st["positions"].pop(sym)
        # 포지션이 생기면 한 번 손절을 지워보고, 봇이 되살리는지 본다
        if not dropped_once and tr3.st["positions"]:
            ex3.drop_stops = set(tr3.st["positions"])
            dropped_once = True
        tr3.tick()
        if dropped_once and getattr(ex3, "drop_stops", None):
            ex3.drop_stops = set()          # 한 번만 지운다
    resets = [o for o in ex3.orders if o[0] == "setstop"]
    check("손절이 사라지면 다시 건다", dropped_once and len(resets) > 0,
          f"재설정 {len(resets)}회")
    if resets:
        bad_stop = [o for o in resets
                    if abs(o[3] / (ex3.pos.get(o[1], {}).get("entry", o[3])
                                   * (1 + S.STOP_PCT / 100)) - 1) > 0.05
                    and o[1] in ex3.pos]
        check("다시 건 손절가가 평단 기준으로 맞다", not bad_stop,
              f"어긋난 건수 {len(bad_stop)}")

    # 상태 파일이 유효한 JSON인가
    st = info["state"]
    check("상태 파일이 직렬화 가능", isinstance(json.dumps(st), str))

    print("=" * 88)
    print(f"  {'✅ 전부 통과' if FAILED == 0 else f'❌ {FAILED}건 실패'}")
    print("=" * 88)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
