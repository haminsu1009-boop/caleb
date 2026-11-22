"""
bot/oversold/test_short_manage.py — 주봉 숏 손절 +40%·트레일 25/12 (2026-11-23)

    python -m bot.oversold.test_short_manage
"""
from __future__ import annotations
import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from bot.oversold import executor as E
from bot.oversold import modules as M

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


NOW = datetime.now(timezone.utc)
OPEN = (NOW - timedelta(days=10)).isoformat()
OPEN_MS = int((NOW - timedelta(days=10)).timestamp() * 1000)


class FakeEx:
    live = True

    def __init__(self, entry, stop, rows):
        self.pos = {"LTCUSDT": {"size": 1.0, "entry": entry, "side": "Sell", "stop": stop, "tp": 0.0}}
        self.rows = rows
        self.set_calls, self.closed = [], []

    def positions(self):
        return self.pos

    def klines(self, symbol, limit=200, interval=None):
        return self.rows

    def set_stop(self, sym, stop, take_profit=None):
        self.set_calls.append((sym, stop))
        return True

    def spec(self, sym):
        return {"step": 0.01, "min": 0.01}

    def close_short(self, sym, qty, reason):
        self.closed.append((sym, reason))
        return True


def rows(lows, last):
    """4시간봉 행: [ts, open, high, low, close]. 진입 이후 봉들, 마지막 봉 종가 = last."""
    out = [[OPEN_MS - 8 * 3600_000, 99, 99, 99, 99]]            # 진입 전 봉 (섞이면 안 된다)
    for k, lo in enumerate(lows):
        out.append([OPEN_MS + k * E.BAR_MS, lo, lo, lo, lo])
    out[-1][4] = last
    return out


def trader(ex, low=None):
    E.STATE_PATH = os.path.join(tempfile.mkdtemp(), "state.json")
    E.notify = lambda t: None
    tr = E.Trader(ex, E.Config())
    p = {"kind": "short", "side": "Sell", "qty": 1.0, "entry": 51.41, "stop": 77.115,
         "signal_bar": 0, "reserved": 100.0, "opened_at": OPEN}
    if low:
        p["low"] = low
    tr.st["mod_positions"] = {"LTCUSDT": p}
    return tr


def main():
    print("① 순수 함수")
    check("숏 손절 40%·다이버 50%", M.stop_pct("short") == 40.0 and M.stop_pct("div") == 50.0)
    check("숏 손절가 = 평단×1.4", abs(M.stop_price(100, "Sell", M.stop_pct("short")) - 140.0) < 1e-9)
    check("트레일: 최저가가 -25% 못 갔으면 안 판다", not M.trail_hit(100, 80, 95))
    check("트레일: -25% 갔지만 반등 12% 미만이면 안 판다", not M.trail_hit(100, 70, 78))
    check("트레일: -25% 갔고 최저가+12% 이상이면 판다", M.trail_hit(100, 70, 78.4))
    check("트레일: 딱 -25%(75)에서 +12%(84.1)", M.trail_hit(100, 75, 84.1))

    print("② 기존 포지션(+50% 손절)을 +40%로 고친다")
    ex = FakeEx(51.41, 77.115, rows([45, 44], 44))
    tr = trader(ex)
    tr._manage_shorts()
    check("손절을 평단×1.4=71.974 로 다시 건다", len(ex.set_calls) == 1 and abs(ex.set_calls[0][1] - 71.974) < 1e-3,
          str(ex.set_calls))
    check("상태에도 반영", abs(tr.st["mod_positions"]["LTCUSDT"]["stop"] - 71.974) < 1e-3)
    ex.pos["LTCUSDT"]["stop"] = 71.974
    ex.set_calls.clear()
    tr._manage_shorts()
    check("이미 맞으면 다시 안 건다", not ex.set_calls)

    print("③ 트레일")
    ex = FakeEx(51.41, 71.974, rows([45, 37.42, 38], 39.81))      # 최저 -27.2%, 지금 +6.4%
    tr = trader(ex)
    tr._manage_shorts()
    check("LTC 지금 상태(최저 37.42, 현재 39.81)는 아직 안 판다", not ex.closed)
    check("최저가를 상태에 저장", abs(tr.st["mod_positions"]["LTCUSDT"]["low"] - 37.42) < 1e-9)
    ex.rows = rows([45, 37.42, 38], 41.95)                          # 37.42×1.12 = 41.91
    tr._manage_shorts()
    check("최저+12%(41.91) 넘으면 시장가 청산", len(ex.closed) == 1 and "트레일" in ex.closed[0][1], str(ex.closed))
    check("청산하면 상태에서 지운다", "LTCUSDT" not in tr.st["mod_positions"])

    print("④ 진입 전 저가·다른 경우")
    ex = FakeEx(51.41, 71.974, rows([50, 49], 50))
    ex.rows[0][3] = 10.0                                            # 진입 전 봉의 저가 10 — 무시해야 한다
    tr = trader(ex)
    tr._manage_shorts()
    check("진입 전 봉의 저가는 섞지 않는다", abs(tr.st["mod_positions"]["LTCUSDT"]["low"] - 49) < 1e-9)
    check("안 떨어졌으면 청산 안 함", not ex.closed)
    ex = FakeEx(51.41, 71.974, rows([45], 45))
    tr = trader(ex, low=37.0)
    tr.st["mod_positions"]["LTCUSDT"]["opened_at"] = ""
    tr._manage_shorts()
    check("진입 시각을 모르면 트레일은 건너뛴다", not ex.closed)
    ex = FakeEx(51.41, 71.974, rows([45, 36], 41.0))              # 상태에 저장된 더 낮은 최저 36
    tr = trader(ex, low=30.0)
    tr._manage_shorts()
    check("저장된 최저(30)가 봉 저가보다 낮으면 그걸 쓴다 → 30×1.12=33.6 이상이라 청산", len(ex.closed) == 1)

    print("⑤ 신규 진입 손절은 40%")
    src = open(E.__file__, encoding="utf-8").read()
    check("진입 코드가 stop_pct(kind)를 쓴다", "MOD.stop_price(px, sig.side, MOD.stop_pct(sig.kind))" in src)

    print()
    print("전부 통과" if not FAILS else f"실패 {len(FAILS)}건: {FAILS}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
