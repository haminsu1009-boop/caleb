"""
bot/cycle_bot.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사이클 봇 — 강세장 롱 / 약세장 숏, 6종 바스켓 동일가중

검증 결과(ml/cycle_timing.py, ml/famous_strategies.py) 요약:
  · 사이클 전환점을 맞힌다는 가정에서, 약세장에 복잡한 롱숏 전략을
    쓰는 것보다 그냥 숏 1배가 4배 더 벌었다 (639억 vs 152억, 적립식).
  · 레버리지 2배부터는 청산으로 전부 날아간다. 그래서 1배 고정.
  · 커뮤니티 유명 기법 10개 중 존버를 이긴 건 없었다. 그래서 안 쓴다.

그래서 이 봇이 하는 일은 하나뿐이다:
    사용자가 "강세" 또는 "약세"를 선언하면 6종 전체 포지션을 그 방향으로 맞춘다.

사용법:
    python bot/cycle_bot.py status                 # 현재 상태 + 참고 판별기
    python bot/cycle_bot.py set bull  --dry-run    # 강세 전환 (모의)
    python bot/cycle_bot.py set bear  --dry-run    # 약세 전환 (모의)
    python bot/cycle_bot.py set cash  --dry-run    # 전량 청산
    python bot/cycle_bot.py set bear                # 실제 주문 (확인 프롬프트)

환경변수 (.env):
    BYBIT_API_KEY, BYBIT_SECRET, BYBIT_TESTNET=1
    ⚠️ API 키는 .env 파일에만 두고 채팅·커밋에 절대 붙여넣지 말 것.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, json, argparse
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

STATE_PATH = os.path.join(ROOT, "bot", "cycle_state.json")

# 검증에 쓴 것과 동일한 6종 동일가중 바스켓
BASKET = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]
LEVERAGE = 1                      # 2배부터 청산으로 전멸 — 고정
CATEGORY = "linear"

REGIMES = {"bull": +1, "bear": -1, "cash": 0}
LABEL   = {+1: "강세(롱)", -1: "약세(숏)", 0: "현금"}


# ══════════════════════════════════════════════════════════════
# 상태 저장
# ══════════════════════════════════════════════════════════════

def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        try:
            return json.load(open(STATE_PATH, encoding="utf-8"))
        except Exception:
            pass
    return {"regime": 0, "since": None, "history": []}


def save_state(st: dict):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    json.dump(st, open(STATE_PATH, "w", encoding="utf-8"), indent=2, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════
# 참고 판별기 (강제하지 않음 — 사용자 판단이 우선)
# ══════════════════════════════════════════════════════════════

def reference_regimes() -> dict:
    """로컬 데이터 기준 200일선 판별기. 사용자 판단과 다를 수 있으며 참고용."""
    try:
        import numpy as np, pandas as pd
        from ml.trend_backtest import load
    except Exception as e:
        return {"error": f"로컬 데이터 없음: {e}"}

    out = {}
    try:
        btc = load("BTCUSDT", "1d")[["datetime", "close"]].set_index("datetime")["close"]
        out["BTC_200MA"]  = bool(btc.iloc[-1] > btc.rolling(200).mean().iloc[-1])
        out["BTC_50_200"] = bool(btc.rolling(50).mean().iloc[-1] > btc.rolling(200).mean().iloc[-1])
        out["_asof"] = str(btc.index[-1].date())
    except Exception as e:
        out["error"] = str(e)
    return out


# ══════════════════════════════════════════════════════════════
# 거래소
# ══════════════════════════════════════════════════════════════

def get_session():
    try:
        from pybit.unified_trading import HTTP
    except ImportError:
        raise SystemExit("pybit 미설치:  pip install pybit>=5.7.0")
    key    = os.environ.get("BYBIT_API_KEY", "")
    secret = os.environ.get("BYBIT_SECRET", "")
    if not key or not secret:
        raise SystemExit("BYBIT_API_KEY / BYBIT_SECRET 미설정 (.env 확인)")
    testnet = os.environ.get("BYBIT_TESTNET", "").lower() in ("1", "true", "yes")
    return HTTP(testnet=testnet, api_key=key, api_secret=secret), testnet


def get_equity(session) -> float:
    r = session.get_wallet_balance(accountType="UNIFIED")
    lst = r["result"]["list"]
    return float(lst[0]["totalEquity"]) if lst else 0.0


def get_positions(session) -> dict:
    out = {}
    for sym in BASKET:
        try:
            r = session.get_positions(category=CATEGORY, symbol=sym)
            for p in r["result"]["list"]:
                sz = float(p.get("size") or 0)
                if sz > 0:
                    out[sym] = {"side": p["side"], "size": sz,
                                "entry": float(p.get("avgPrice") or 0),
                                "pnl": float(p.get("unrealisedPnl") or 0)}
        except Exception as e:
            out[sym] = {"error": str(e)}
    return out


def last_price(session, sym: str) -> float:
    r = session.get_tickers(category=CATEGORY, symbol=sym)
    return float(r["result"]["list"][0]["lastPrice"])


def qty_step(session, sym: str):
    r = session.get_instruments_info(category=CATEGORY, symbol=sym)
    f = r["result"]["list"][0]["lotSizeFilter"]
    return float(f["qtyStep"]), float(f["minOrderQty"])


def round_qty(q: float, step: float) -> float:
    return round(int(q / step) * step, 8)


# ══════════════════════════════════════════════════════════════
# 리밸런싱
# ══════════════════════════════════════════════════════════════

def rebalance(target: int, dry_run: bool = True):
    st = load_state()
    cur = st.get("regime", 0)

    print("=" * 76)
    print(f"  사이클 봇 — {LABEL[cur]}  →  {LABEL[target]}")
    print(f"  바스켓 {len(BASKET)}종 동일가중 · 레버리지 {LEVERAGE}배 고정")
    print("=" * 76)

    if dry_run:
        print("\n  [모의 실행] 실제 주문 없음\n")

    session, testnet = get_session()
    if testnet:
        print("  ⚠️  테스트넷 연결됨\n")

    equity = get_equity(session)
    per_sym = equity / len(BASKET) if target != 0 else 0.0
    print(f"  총자산 {equity:,.2f} USDT   심볼당 배분 {per_sym:,.2f} USDT\n")

    positions = get_positions(session)
    side = "Buy" if target > 0 else "Sell"

    print(f"  {'심볼':10s}{'현재':>18s}{'목표':>18s}{'조치':>14s}")
    print("  " + "-" * 60)

    plans = []
    for sym in BASKET:
        pos = positions.get(sym)
        cur_desc = "없음"
        if pos and "error" not in pos:
            cur_desc = f"{pos['side']} {pos['size']}"
        elif pos:
            cur_desc = "조회실패"

        if target == 0:
            tgt_desc, action = "청산", "close"
            qty = pos["size"] if pos and "error" not in pos else 0.0
        else:
            price = last_price(session, sym)
            step, minq = qty_step(session, sym)
            qty = round_qty(per_sym * LEVERAGE / price, step)
            if qty < minq:
                tgt_desc, action = f"{qty} (최소미달)", "skip"
            else:
                tgt_desc, action = f"{side} {qty}", "flip"

        plans.append((sym, action, qty, side))
        print(f"  {sym:10s}{cur_desc:>18s}{tgt_desc:>18s}{action:>14s}")

    if dry_run:
        print("\n  → --dry-run 없이 다시 실행하면 주문이 나갑니다.")
        return

    print()
    confirm = input(f"  실제 주문을 실행합니다. '{LABEL[target]}' 입력해 확인: ").strip()
    if confirm != LABEL[target]:
        print("  취소됨."); return

    for sym, action, qty, sd in plans:
        if action == "skip":
            print(f"  {sym}: 최소주문수량 미달 — 건너뜀"); continue
        try:
            # 기존 포지션 먼저 정리
            pos = positions.get(sym)
            if pos and "error" not in pos and pos["size"] > 0:
                close_side = "Sell" if pos["side"] == "Buy" else "Buy"
                session.place_order(category=CATEGORY, symbol=sym, side=close_side,
                                    orderType="Market", qty=str(pos["size"]),
                                    reduceOnly=True, timeInForce="IOC")
                print(f"  {sym}: 기존 포지션 청산")
            if action == "flip" and qty > 0:
                session.place_order(category=CATEGORY, symbol=sym, side=sd,
                                    orderType="Market", qty=str(qty),
                                    timeInForce="IOC", positionIdx=0)
                print(f"  {sym}: {sd} {qty} 체결")
        except Exception as e:
            print(f"  {sym}: ❌ 주문 실패 — {e}")

    st["regime"] = target
    st["since"] = datetime.now(timezone.utc).isoformat()
    st.setdefault("history", []).append(
        {"at": st["since"], "regime": target, "label": LABEL[target], "equity": equity})
    save_state(st)
    print(f"\n  ✅ 상태 저장: {LABEL[target]}")


# ══════════════════════════════════════════════════════════════
def cmd_status():
    st = load_state()
    print("=" * 76)
    print("  사이클 봇 상태")
    print("=" * 76)
    print(f"\n  선언된 레짐: {LABEL.get(st.get('regime', 0), '?')}")
    print(f"  선언 시각:   {st.get('since') or '없음'}")

    ref = reference_regimes()
    print(f"\n  [참고] 200일선 판별기  (기준일 {ref.get('_asof', '?')})")
    for k in ("BTC_200MA", "BTC_50_200"):
        if k in ref:
            print(f"    {k:14s}: {'강세' if ref[k] else '약세'}")
    if "error" in ref:
        print(f"    조회 실패: {ref['error']}")
    print("\n  ※ 판별기는 참고용이며 봇을 움직이지 않는다. 전환은 사용자가 직접 선언한다.")

    hist = st.get("history", [])
    if hist:
        print(f"\n  최근 전환 이력")
        for h in hist[-5:]:
            print(f"    {h['at'][:19]}  {h['label']}  (자산 {h.get('equity', 0):,.0f} USDT)")

    if os.environ.get("BYBIT_API_KEY"):
        try:
            session, _ = get_session()
            pos = get_positions(session)
            print(f"\n  현재 포지션")
            if not pos:
                print("    없음")
            for sym, p in pos.items():
                if "error" in p:
                    print(f"    {sym}: 조회실패")
                else:
                    print(f"    {sym:10s} {p['side']:5s} {p['size']:<12} "
                          f"진입 {p['entry']:<12,.4f} 미실현 {p['pnl']:+,.2f} USDT")
        except SystemExit as e:
            print(f"\n  거래소 연결 안 됨: {e}")


def main():
    ap = argparse.ArgumentParser(description="사이클 봇 — 강세 롱 / 약세 숏")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p = sub.add_parser("set")
    p.add_argument("regime", choices=["bull", "bear", "cash"])
    p.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.cmd == "status":
        cmd_status()
    else:
        rebalance(REGIMES[a.regime], dry_run=a.dry_run)


if __name__ == "__main__":
    main()
