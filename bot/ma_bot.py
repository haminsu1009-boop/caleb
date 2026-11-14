"""
bot/ma_bot.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MA 롱온리 봇 — 4h 기준 3일선 > 33일선일 때만 보유, 아니면 현금

ml/intraday_search.py 검증 요약:
  · 4h·1h 양쪽 탐색에서 55개 조합 중 1위. 6/6 심볼이 존버를 이겼고
    3/3 워크포워드 구간이 양수였다.
  · 파라미터 평원: fast 2~6일 × slow 20~50일 25칸이 전부 통했다
    (중앙값 1,190~8,444%, 존버 이김 4~6/6). 한 칸만 튀는 과적합과
    구분되는 지점.
  · 구간별 존버 대비: 1차불장 +786.0%p / 고점+약세 +100.8%p /
    회복장 -170.1%p / 현재 하락장 +33.6%p → 4구간 중 3승.
  · 상위권이 전부 롱온리였다. 숏을 지표로 치는 롱숏 변형은 한참 아래.
    그래서 이 봇은 숏을 치지 않는다 — 하락추세엔 현금으로 빠진다.

동작:
    각 심볼을 독립 판정한다. 3일선 > 33일선이면 자본의 1/N만큼 롱,
    아니면 그 심볼은 현금. 6종 중 3종만 조건을 만족하면 자본의 3/6만
    시장에 있고 나머지는 현금으로 남는다.

사용법:
    python bot/ma_bot.py signal                  # 신호만 확인 (주문 없음)
    python bot/ma_bot.py run --dry-run           # 리밸런싱 계획 출력
    python bot/ma_bot.py run                     # 실제 주문 (확인 프롬프트)
    python bot/ma_bot.py run --yes               # 확인 없이 실행 (크론용)

환경변수 (.env):
    BYBIT_API_KEY, BYBIT_SECRET, BYBIT_TESTNET=1
    ⚠️ API 키는 .env 에만 두고 채팅·커밋에 붙여넣지 말 것.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, json, argparse
from datetime import datetime, timezone

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

STATE_PATH = os.path.join(ROOT, "bot", "ma_bot_state.json")

BASKET   = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]
INTERVAL = "240"          # Bybit 표기: 240분 = 4h
BARS_PER_DAY = 6          # 4h 기준

FAST_DAYS, SLOW_DAYS = 3, 33
FAST = FAST_DAYS * BARS_PER_DAY      # 18봉
SLOW = SLOW_DAYS * BARS_PER_DAY      # 198봉
NEED_BARS = SLOW + 10                # 여유분

CATEGORY = "linear"
LEVERAGE = 1              # 레버리지 검증에서 2배부터 청산 → 1배 고정


# ══════════════════════════════════════════════════════════════
# 상태
# ══════════════════════════════════════════════════════════════

def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        try:
            return json.load(open(STATE_PATH, encoding="utf-8"))
        except Exception:
            pass
    return {"last_run": None, "signals": {}, "history": []}


def save_state(st: dict):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    json.dump(st, open(STATE_PATH, "w", encoding="utf-8"), indent=2, ensure_ascii=False)


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


def fetch_bars(session, symbol: str, need: int) -> pd.DataFrame:
    """확정봉만 반환 — 진행 중인 마지막 봉은 버린다(신호 깜빡임 방지)"""
    frames, end_ms = [], None
    while sum(len(f) for f in frames) < need + 5:
        params = dict(category=CATEGORY, symbol=symbol, interval=INTERVAL, limit=200)
        if end_ms is not None:
            params["end"] = end_ms
        r = session.get_kline(**params)
        rows = r["result"]["list"]
        if not rows:
            break
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "vol", "to"])
        df["ts"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms")
        for c in ["open", "high", "low", "close"]:
            df[c] = df[c].astype(float)
        frames.append(df)
        oldest = int(df["ts"].min().timestamp() * 1000)
        if end_ms is not None and oldest >= end_ms:
            break
        end_ms = oldest - 1
        if len(rows) < 200:
            break

    if not frames:
        return pd.DataFrame()
    out = (pd.concat(frames).drop_duplicates("ts")
             .sort_values("ts").reset_index(drop=True))
    return out.iloc[:-1].reset_index(drop=True)      # 미완성 봉 제거


def compute_signal(df: pd.DataFrame) -> dict | None:
    """3일선 > 33일선 → 보유(True)"""
    if len(df) < NEED_BARS:
        return None
    c = df["close"]
    fast = c.rolling(FAST).mean().iloc[-1]
    slow = c.rolling(SLOW).mean().iloc[-1]
    if np.isnan(fast) or np.isnan(slow):
        return None
    return {"hold": bool(fast > slow), "fast": float(fast), "slow": float(slow),
            "price": float(c.iloc[-1]), "gap_pct": float((fast/slow - 1) * 100),
            "asof": str(df["ts"].iloc[-1])}


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
                                "pnl": float(p.get("unrealisedPnl") or 0)}
        except Exception as e:
            out[sym] = {"error": str(e)}
    return out


def qty_step(session, sym: str):
    r = session.get_instruments_info(category=CATEGORY, symbol=sym)
    f = r["result"]["list"][0]["lotSizeFilter"]
    return float(f["qtyStep"]), float(f["minOrderQty"])


# ══════════════════════════════════════════════════════════════
# 명령
# ══════════════════════════════════════════════════════════════

def cmd_signal():
    session, testnet = get_session()
    print("=" * 84)
    print(f"  MA 롱온리 신호 — {FAST_DAYS}일선({FAST}봉) > {SLOW_DAYS}일선({SLOW}봉), 4h 기준")
    if testnet:
        print("  ⚠️  테스트넷")
    print("=" * 84)
    print(f"\n  {'심볼':10s}{'현재가':>14s}{'3일선':>14s}{'33일선':>14s}{'괴리':>9s}{'판정':>10s}")
    print("  " + "-" * 72)

    n_hold = 0
    sigs = {}
    for sym in BASKET:
        try:
            df = fetch_bars(session, sym, NEED_BARS)
            s = compute_signal(df)
        except Exception as e:
            print(f"  {sym:10s}  조회 실패: {e}"); continue
        if s is None:
            print(f"  {sym:10s}  데이터 부족"); continue
        sigs[sym] = s
        if s["hold"]:
            n_hold += 1
        print(f"  {sym:10s}{s['price']:>14,.4f}{s['fast']:>14,.4f}{s['slow']:>14,.4f}"
              f"{s['gap_pct']:>+8.2f}%{('보유' if s['hold'] else '현금'):>10s}")

    print(f"\n  보유 대상 {n_hold}/{len(BASKET)}종 → 자본의 {n_hold/len(BASKET)*100:.0f}%가 시장에, "
          f"{(1-n_hold/len(BASKET))*100:.0f}%는 현금")
    if sigs:
        print(f"  기준봉: {list(sigs.values())[0]['asof']} (확정봉)")
    return sigs


def cmd_run(dry_run: bool, assume_yes: bool):
    session, testnet = get_session()
    print("=" * 84)
    print(f"  MA 롱온리 리밸런싱 — {FAST_DAYS}일선 > {SLOW_DAYS}일선, 레버리지 {LEVERAGE}배")
    if testnet:
        print("  ⚠️  테스트넷")
    if dry_run:
        print("  [모의 실행] 실제 주문 없음")
    print("=" * 84)

    sigs = {}
    for sym in BASKET:
        try:
            s = compute_signal(fetch_bars(session, sym, NEED_BARS))
            if s:
                sigs[sym] = s
        except Exception as e:
            print(f"  {sym}: 신호 계산 실패 — {e}")

    if not sigs:
        print("  신호 없음 — 중단"); return

    equity  = get_equity(session)
    per_sym = equity / len(BASKET)          # 분모는 항상 전체 종목 수
    positions = get_positions(session)

    print(f"\n  총자산 {equity:,.2f} USDT   심볼당 배분 {per_sym:,.2f} USDT\n")
    print(f"  {'심볼':10s}{'신호':>8s}{'현재포지션':>16s}{'조치':>22s}")
    print("  " + "-" * 60)

    plans = []
    for sym in BASKET:
        s = sigs.get(sym)
        pos = positions.get(sym)
        has = pos and "error" not in pos and pos["size"] > 0
        cur = f"{pos['side']} {pos['size']}" if has else "없음"

        if s is None:
            print(f"  {sym:10s}{'?':>8s}{cur:>16s}{'신호없음 — 유지':>22s}"); continue

        want = s["hold"]
        if want and not has:
            price = s["price"]
            step, minq = qty_step(session, sym)
            qty = round(int(per_sym * LEVERAGE / price / step) * step, 8)
            if qty < minq:
                act, plan = f"최소수량미달({qty})", None
            else:
                act, plan = f"신규 롱 {qty}", ("open", sym, qty)
        elif want and has:
            act, plan = "보유 유지", None
        elif (not want) and has:
            act, plan = f"청산 {pos['size']}", ("close", sym, pos["size"])
        else:
            act, plan = "현금 유지", None

        if plan:
            plans.append(plan)
        print(f"  {sym:10s}{('보유' if want else '현금'):>8s}{cur:>16s}{act:>22s}")

    if not plans:
        print("\n  변경할 포지션 없음 — 종료")
        return

    if dry_run:
        print(f"\n  → 실행할 주문 {len(plans)}건. --dry-run 없이 다시 실행하면 주문이 나갑니다.")
        return

    if not assume_yes:
        ok = input(f"\n  주문 {len(plans)}건을 실행합니다. 'yes' 입력: ").strip().lower()
        if ok != "yes":
            print("  취소됨."); return

    print()
    for kind, sym, qty in plans:
        try:
            if kind == "close":
                pos = positions[sym]
                side = "Sell" if pos["side"] == "Buy" else "Buy"
                session.place_order(category=CATEGORY, symbol=sym, side=side,
                                    orderType="Market", qty=str(qty),
                                    reduceOnly=True, timeInForce="IOC")
                print(f"  {sym}: 청산 {qty}")
            else:
                session.place_order(category=CATEGORY, symbol=sym, side="Buy",
                                    orderType="Market", qty=str(qty),
                                    timeInForce="IOC", positionIdx=0)
                print(f"  {sym}: 롱 진입 {qty}")
        except Exception as e:
            print(f"  {sym}: ❌ 실패 — {e}")

    st = load_state()
    st["last_run"] = datetime.now(timezone.utc).isoformat()
    st["signals"] = {k: v["hold"] for k, v in sigs.items()}
    st.setdefault("history", []).append(
        {"at": st["last_run"], "equity": equity,
         "holding": [k for k, v in sigs.items() if v["hold"]]})
    save_state(st)
    print(f"\n  ✅ 완료 — 보유 {sum(1 for v in sigs.values() if v['hold'])}종")


def main():
    ap = argparse.ArgumentParser(description="MA 롱온리 봇 (4h, 3일선>33일선)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("signal")
    r = sub.add_parser("run")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--yes", action="store_true", help="확인 프롬프트 생략 (크론용)")
    a = ap.parse_args()

    if a.cmd == "signal":
        cmd_signal()
    else:
        cmd_run(a.dry_run, a.yes)


if __name__ == "__main__":
    main()
