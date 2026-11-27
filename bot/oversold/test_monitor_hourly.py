"""
bot/oversold/test_monitor_hourly.py — 매시간 "현재 수익" 보고(monitor.hourly)가 숫자를 맞게 만드는지

2026-11-22 사용자 요청으로 추가. 거래소에 붙지 않고 가짜 거래소로 시험한다.

    python -m bot.oversold.test_monitor_hourly
"""
from __future__ import annotations
import os
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from bot.oversold import monitor as M

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


class FakeSession:
    def __init__(self, rows=None, boom=False):
        self.rows, self.boom = rows or [], boom

    def get_positions(self, **kw):
        if self.boom:
            raise RuntimeError("연결 실패")
        return {"result": {"list": self.rows}}


class FakeEx:
    def __init__(self, eq=805.37, rows=None, boom=False):
        self.eq = eq
        self.session = FakeSession(rows, boom)

    def equity(self):
        return self.eq


def pos(sym, side, avg, mark, upnl, liq, lev, size=10.0, cum=0.0):
    return {"symbol": sym, "side": side, "size": str(size), "avgPrice": str(avg),
            "markPrice": str(mark), "unrealisedPnl": str(upnl), "liqPrice": str(liq),
            "leverage": str(lev), "cumRealisedPnl": str(cum)}


NOW = datetime(2026, 11, 22, 14, 0, tzinfo=M.KST)
ms = lambda dt: int(dt.timestamp() * 1000)


def mon():
    return {
        "equity_hist": [[ms(NOW - timedelta(days=7)), 700.37], [ms(NOW - timedelta(hours=24)), 790.37],
                        [ms(NOW - timedelta(hours=1)), 800.37]],
        "trades": [
            {"ts": ms(NOW.replace(hour=9)), "pnl": 1.28},                     # 오늘
            {"ts": ms(NOW - timedelta(days=1)), "pnl": -3.77},                # 어제 (7일 안)
            {"ts": ms(NOW - timedelta(days=9)), "pnl": 50.0},                 # 7일 밖
        ],
        "kinds": {"ALGOUSDT": "short", "UNIUSDT": "div"},
    }


print("\n[기본 메시지]")
rows = [pos("APTUSDT", "Buy", 0.4482, 0.3449, -11.04, 0.3384, 4, cum=-0.5),
        pos("ALGOUSDT", "Sell", 0.0915, 0.08931, 6.91, 0.18119, 1, cum=-0.2)]
t = M.hourly(FakeEx(rows=rows), mon(), NOW)
print(t)
check("제목에 시각", "💹 현재 수익 11/22 14:00" in t)
check("자본 805.37", "자본 805.37 USDT" in t)
check("1시간 +5.00 (+0.6%)", "1시간 +5.00 (+0.6%)" in t)
check("24시간 +15.00 (+1.9%)", "24시간 +15.00 (+1.9%)" in t)
check("7일 +105.00 (+15.0%)", "7일 +105.00 (+15.0%)" in t)
check("누적 손익 = 미실현+누적실현 = -4.83", "누적 손익(앱 Cumulative P&L) -4.83 USDT" in t)
check("평가손익 합계 -4.13", "열린 포지션 2개 · 평가손익 합계 -4.13 USDT" in t)
check("롱 가격 -23.0%", "APT 롱 4x -23.0% (-11.04)" in t)
check("숏은 가격이 내려가면 +", "ALGO 숏 1x +2.5% (+6.91)" in t)
check("청산까지 거리(롱 2%)", "청산까지 2%" in t)
check("손실이 큰 순서(APT가 ALGO보다 위)", t.index("APT 롱") < t.index("ALGO 숏"))
check("실현손익 오늘/7일", "실현 손익: 오늘 +1.28 (1건) · 7일 -2.49 (2건)" in t)

print("\n[전략 이름 / 포지션 없음 / 조회 실패 / 많을 때]")
t2 = M.hourly(FakeEx(rows=[pos("UNIUSDT", "Buy", 5.0, 5.2, 0.4, 0, 1)]), mon(), NOW)
check("다이버 이름", "UNI 다이버 1x +4.0% (+0.40)" in t2)
check("청산가 0이면 거리 안 적음", "청산까지" not in t2)
t3 = M.hourly(FakeEx(rows=[]), mon(), NOW)
check("포지션 없음", "열린 포지션 없음" in t3)
t4 = M.hourly(FakeEx(boom=True), mon(), NOW)
check("조회 실패해도 메시지는 나감", "포지션 조회 실패: RuntimeError" in t4 and "자본 805.37" in t4)
many = [pos(f"C{i:02d}USDT", "Buy", 1.0, 1.0, -i * 0.1, 0.5, 4) for i in range(18)]
t5 = M.hourly(FakeEx(rows=many), mon(), NOW)
check("15개까지만 + 외 3개", "… 외 3개" in t5 and t5.count("USDT") >= 1 and t5.count("\n C") == 15)
t6 = M.hourly(FakeEx(rows=rows), {"trades": [], "kinds": {}}, NOW)
check("기록이 없어도 에러 없음(변화 생략)", "1시간" not in t6 and "실현 손익: 오늘 +0.00 (0건)" in t6)

print("\n[main() 연결 — 1시간에 한 번, --now 는 강제, TG_HOURLY=0 은 끔]")


def run_main(argv, store, env=None):
    """main()을 가짜 거래소·가짜 텔레그램으로 한 번 돌리고 보낸 메시지를 돌려준다."""
    sent = []
    keep = (M.E.Exchange, M.E.load_env, M.E.LIVE_STATE_PATH, M.load_mon, M.save_mon,
            M.collect_closed, M.checks, M.send, sys.argv, dict(os.environ))
    M.E.Exchange = lambda live=True: FakeEx(rows=rows)
    M.E.load_env = lambda: None
    M.E.LIVE_STATE_PATH = os.path.join(ROOT, "state", "__없는파일__.json")
    M.load_mon = lambda: store
    M.save_mon = lambda m: None
    M.collect_closed = lambda ex, m: []
    M.checks = lambda ex, m, st: []
    M.send = lambda text, dry=False: (sent.append(text), True)[1]
    sys.argv = ["monitor"] + argv
    os.environ.update(env or {})
    try:
        M.main()
    finally:
        (M.E.Exchange, M.E.load_env, M.E.LIVE_STATE_PATH, M.load_mon, M.save_mon,
         M.collect_closed, M.checks, M.send, sys.argv) = keep[:9]
        os.environ.clear(); os.environ.update(keep[9])
    return [x for x in sent if x.startswith("💹")]


store = M.load_mon.__wrapped__() if hasattr(M.load_mon, "__wrapped__") else \
    {"kinds": {}, "seen": [], "trades": [], "alerts": {}, "last_summary": "x"}
r1 = run_main([], store)
check("처음 부르면 현재 수익을 보낸다", len(r1) == 1 and "열린 포지션 2개" in r1[0])
check("보낸 시각을 기록한다", store.get("last_hourly", 0) > 0)
r2 = run_main([], store)
check("50분 안에 또 부르면 건너뛴다", len(r2) == 0)
r3 = run_main(["--now"], store)
check("--now 는 바로 보낸다", len(r3) == 1)
store2 = {"kinds": {}, "seen": [], "trades": [], "alerts": {}, "last_summary": "x"}
r4 = run_main([], store2, {"TG_HOURLY": "0"})
check("TG_HOURLY=0 이면 안 보낸다", len(r4) == 0 and "last_hourly" not in store2)

print()
if FAILS:
    print(f"실패 {len(FAILS)}건: {FAILS}")
    sys.exit(1)
print("전부 통과")
