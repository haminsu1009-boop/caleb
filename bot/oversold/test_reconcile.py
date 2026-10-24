"""
bot/oversold/test_reconcile.py — 거래소가 닫은 포지션을 봇이 따라 정리하는지

2026-10-12 실거래: 익절이 거래소에서 체결됐는데 봇은 시작할 때만 기록을
맞춰서 그 포지션을 계속 들고 있다고 믿었다. 60봉이 되자 없는 포지션을
팔려다 110017(포지션 0)이 매 분 났고, 그 예외가 점검 전체를 끊었다.

    python -m bot.oversold.test_reconcile
"""
from __future__ import annotations
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from bot.oversold import executor as E

FAILS = []


def check(name, ok, detail=""):
    print(f"  {'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


class FakeEx:
    live = True

    def __init__(self, pos, last=1.0):
        self.pos = pos
        self.last = last

    def klines(self, symbol, limit=200, interval=None):
        return [[0, self.last, self.last, self.last, self.last]]

    def positions(self):
        return {s: {"size": 1.0, "entry": 1.0, "side": "Buy", "stop": 0.6, "tp": 0.0}
                for s in self.pos}


class Zero110017:
    """pybit 가 retCode≠0 에 던지는 예외와 같은 문구."""
    def place_order(self, **kw):
        raise Exception("current position is zero, cannot fix reduce-only order qty "
                        "(ErrCode: 110017) (ErrTime: 00:00:00)")


class OtherError:
    def place_order(self, **kw):
        raise Exception("insufficient balance (ErrCode: 110007)")


def main():
    sent = []
    E.notify = lambda text: sent.append(text)
    E.STATE_PATH = os.path.join(tempfile.mkdtemp(), "state.json")

    print("① 점검 중 거래소에서 닫힌 포지션 정리")
    ex = FakeEx({"AAAUSDT"})
    tr = E.Trader(ex, E.Config())
    tr.st["positions"] = {"AAAUSDT": {"qty": 1}, "BBBUSDT": {"qty": 1}}
    tr.st["mod_positions"] = {"CCCUSDT": {"kind": "div", "qty": 1, "side": "Buy"}}
    tr.reconcile(startup=False)
    check("한 번 없으면 아직 지우지 않는다 (주문 직후 지연 대비)",
          set(tr.st["positions"]) == {"AAAUSDT", "BBBUSDT"} and "CCCUSDT" in tr.st["mod_positions"])
    tr.reconcile(startup=False)
    check("두 번 연속 없으면 지운다", set(tr.st["positions"]) == {"AAAUSDT"}
          and not tr.st["mod_positions"])
    check("텔레그램으로 종료를 알린다", len(sent) == 2, f"{len(sent)}건")
    check("거래소에 있는 포지션은 그대로", "AAAUSDT" in tr.st["positions"])

    print("② 한 번 빠졌다가 다시 보이면 지우지 않는다")
    tr.st["positions"]["DDDUSDT"] = {"qty": 1}
    tr.reconcile(startup=False)
    ex.pos.add("DDDUSDT")
    tr.reconcile(startup=False)
    ex.pos.discard("DDDUSDT")
    tr.reconcile(startup=False)
    check("연속이 아니면 유지", "DDDUSDT" in tr.st["positions"])

    print("③ 시작할 때는 바로 정리")
    tr2 = E.Trader(FakeEx(set()), E.Config())
    tr2.st["positions"] = {"EEEUSDT": {"qty": 1}}
    tr2.reconcile()
    check("시작 시 한 번에 제거", not tr2.st["positions"])

    print("④ 4배 손실 청산 뒤 재매수 잠금 (백테스트와 같게)")
    H = E.BAR_MS
    ex5 = FakeEx({"AAAUSDT"}, last=70.0)          # 평단 100 → 지금 70 = 손실로 닫힘
    tr5 = E.Trader(ex5, E.Config())
    tr5.st["positions"] = {"LIQUSDT": {"qty": 1, "entry": 100.0, "stop": 60.0, "lev": 4.0,
                                       "entry_bar": 0}}
    tr5.reconcile()
    lk = tr5.st.get("relock", {}).get("LIQUSDT")
    check("4배가 손실로 닫히면 잠근다", bool(lk) and lk["until"] == E.S.HOLD_BARS * H)
    check("알림에 잠금 안내", "다시 사지 않습니다" in sent[-1])
    flat = [[0, 70, 72, 69, 70]]
    closes = [70.0] * 30
    check("잠금 중엔 진입 막음", tr5._relocked("LIQUSDT", 10 * H, closes, flat))
    check("60봉 지나면 풀림", not tr5._relocked("LIQUSDT", E.S.HOLD_BARS * H, closes, flat))
    tr5.st["positions"] = {"LIQUSDT": {"qty": 1, "entry": 100.0, "stop": 60.0, "lev": 4.0,
                                       "entry_bar": 0}}
    tr5.reconcile()
    check("-40% 손절선에 닿으면 풀림 (백테스트에선 그때 거래가 끝난다)",
          not tr5._relocked("LIQUSDT", 10 * H, closes, [[0, 60, 61, 59, 60]]))
    ex6 = FakeEx(set(), last=110.0)                # 평단 위에서 닫힘 = 익절
    tr6 = E.Trader(ex6, E.Config())
    tr6.st["positions"] = {"TPUSDT": {"qty": 1, "entry": 100.0, "stop": 60.0, "lev": 4.0,
                                      "entry_bar": 0}}
    tr6.reconcile()
    check("익절로 닫히면 잠그지 않는다", not tr6.st.get("relock"))
    ex7 = FakeEx(set(), last=70.0)
    tr7 = E.Trader(ex7, E.Config())
    tr7.st["positions"] = {"B2USDT": {"qty": 1, "entry": 100.0, "stop": 60.0, "lev": 2.0,
                                      "entry_bar": 0}}
    tr7.reconcile()
    check("2배는 잠그지 않는다 (손절이 청산보다 먼저 = 백테스트와 같음)", not tr7.st.get("relock"))

    print("⑤ 이미 닫힌 포지션 청산 주문(110017)")
    x = E.Exchange.__new__(E.Exchange)
    x.live = True
    x.session = Zero110017()
    check("close_long 은 닫힌 것으로 처리(True)", x.close_long("AAAUSDT", 1, "60봉 경과") is True)
    check("close_short 도 같다", x.close_short("AAAUSDT", 1, "보유 끝") is True)
    x.session = OtherError()
    try:
        x.close_long("AAAUSDT", 1, "x")
        check("다른 오류는 그대로 올린다", False)
    except Exception:
        check("다른 오류는 그대로 올린다", True)

    print()
    if FAILS:
        print(f"❌ 실패 {len(FAILS)}건: {FAILS}")
        sys.exit(1)
    print("✅ 전부 통과")


if __name__ == "__main__":
    main()
