"""
bot/breakout/paper.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
상승장 신고가 돌파 — 모의매매 (주문 없음, 가상 지갑)

2026-10-11 사용자 요청. 백테스트(ml/bull_breakout.py, UP.make_break)에서
"돌파 2%·2배"를 지금 전략에 붙이면 2017~ 327배였다. 하지만 대부분 2021년
덕이고, 2025년은 +165%→+74%로 깎였고, 비중을 조금만 바꿔도 결과가
크게 흔들렸다. 그래서 실거래 전에 가상 지갑으로 실제 흐름을 본다.

규칙 (백테스트와 같다)
  · 하루 한 번, 일봉 마감 직후(UTC 00:10, 한국 09:10) 돈다.
  · 42종 중 어제 종가가 직전 100일 종가 최고 이상이면 신호.
  · 시장(42종 동일가중 지수)이 200일선 위일 때만 산다.
  · 오늘 시가에 산다. 가상 자본의 2%를 증거금으로, 2배.
  · 신호일 + 40일째 종가에 판다. 손절 없음. 2배 격리라 약 −49.5%면 청산(증거금 전부 손실).
  · 같은 코인은 하나만 든다. 수수료는 한쪽 0.055%(테이커).

백테스트와 다른 점
  · 백테스트는 시장 200일선 판정에 진입일 종가를 썼다(하루 미래 정보).
    모의는 신호일 종가까지만 쓴다. 실거래에서 가능한 쪽이다.
  · 실거래 봇과 자본을 나누지 않는다. 대신 실거래 봇이 같은 코인을 들고
    있으면 "겹침"으로 센다. 실제로 붙이면 그만큼 과매도 롱이 막히거나
    포지션이 합쳐진다(백테스트에서 롱 −365건의 원인).
  · 봇이 며칠 꺼져 있었으면 마지막 날만 본다. 놓친 신호는 기록에 남긴다.

알림 (텔레그램, .env 의 TG_BOT_TOKEN · TG_CHAT_ID)
  · 가상 매수·청산 순간. 하루 요약은 감시(monitor)의 아침 요약에 한 줄로 붙는다.

사용법
    python -m bot.breakout.paper            # 한 번 돈다 (타이머가 부른다)
    python -m bot.breakout.paper --status   # 가상 지갑·보유·거래 기록
    python -m bot.breakout.paper --dry      # 저장·알림 없이 화면에만
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from bot.oversold import strategy as S

STATE_PATH = os.path.join(ROOT, "state", "breakout_paper.json")
LIVE_STATE = os.path.join(ROOT, "bot", "oversold", "state_live.json")

WINDOW = 100        # 신고가 기준일 (ml/bull_breakout.WINDOW)
HOLD = 40           # 신호일부터 보유일 (ml/bull_breakout.HOLD)
MKT_MA = 200        # 시장 추세 (ml/bull_breakout.MKT_MA)
PER_TRADE = 0.02    # 가상 자본 대비 증거금
LEVERAGE = 2.0
FEE = 0.00055       # 한쪽 테이커
MMR = 0.005         # 유지증거금률(대략)
START_EQUITY = 1000.0
DAY = timedelta(days=1)


# ── 순수 계산 (test_paper.py 가 백테스트와 맞춰 본다) ─────────────────────
def is_signal(closes: np.ndarray, window: int = WINDOW) -> bool:
    """마지막 종가가 직전 window개 종가 최고 이상이면 True."""
    if len(closes) < window + 1:
        return False
    return bool(closes[-1] >= closes[-window - 1:-1].max())


def market_bull(closes: dict, ma: int = MKT_MA) -> bool:
    """42종 동일가중 지수가 200일선 위인가 (ml/bull_breakout.basket·bull_days 와 같은 식).

    closes: {sym: pd.Series(종가, 날짜 인덱스)} — 마지막 날 기준으로 판정한다.
    """
    P = pd.DataFrame(closes).sort_index()
    b = (1 + P.pct_change().clip(-.5, .5).mean(axis=1).fillna(0)).cumprod()
    if len(b) < ma:
        return False
    return bool(b.iloc[-1] > b.rolling(ma).mean().iloc[-1])


def liq_price(entry: float, lev: float = LEVERAGE) -> float:
    return entry * (1 - 1 / lev + MMR)


def settle(pos: dict, exit_px: float, liquidated: bool) -> tuple[float, float]:
    """(지갑 손익 USDT, 코인 수익률 %)."""
    m, n = pos["margin"], pos["margin"] * pos["lev"]
    r = exit_px / pos["entry"] - 1
    if liquidated:
        return -m, r * 100
    pnl = n * r - n * FEE - n * (1 + r) * FEE
    return max(pnl, -m), r * 100


# ── 데이터 ─────────────────────────────────────────────────────────────
def fetch_daily(sym: str, limit: int = 400) -> pd.DataFrame | None:
    """Bybit 선물 일봉(공개 API, 키 불필요). 마지막 행은 진행 중인 오늘 봉이다."""
    import requests
    for i in range(3):
        try:
            r = requests.get("https://api.bybit.com/v5/market/kline",
                             params={"category": "linear", "symbol": sym,
                                     "interval": "D", "limit": limit}, timeout=15)
            rows = r.json()["result"]["list"]
            break
        except Exception:
            if i == 2:
                return None
            time.sleep(2 * (i + 1))
    if not rows:
        return None
    d = pd.DataFrame([[int(x[0]), *map(float, x[1:5])] for x in rows],
                     columns=["t", "open", "high", "low", "close"])
    d["dt"] = pd.to_datetime(d["t"], unit="ms").dt.normalize()
    return d.sort_values("dt").drop(columns="t").reset_index(drop=True)


# ── 상태 ────────────────────────────────────────────────────────────────
def load_state() -> dict:
    try:
        return json.load(open(STATE_PATH, encoding="utf-8"))
    except Exception:
        return {"started": "", "equity": START_EQUITY, "peak": START_EQUITY, "mdd": 0.0,
                "last_day": "", "positions": {}, "trades": [], "overlap_days": 0,
                "skipped": []}


def save_state(st: dict):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    json.dump(st, open(tmp, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    os.replace(tmp, STATE_PATH)


def live_symbols() -> set:
    try:
        st = json.load(open(LIVE_STATE, encoding="utf-8"))
        return set(st.get("positions", {})) | set(st.get("mod_positions", {}))
    except Exception:
        return set()


# ── 하루 처리 ───────────────────────────────────────────────────────────
def step(st: dict, D: dict, day: pd.Timestamp, live: set) -> list[str]:
    """day = 어제(확정된 마지막 일봉 날짜). D[sym]은 오늘 진행 봉까지 포함한 일봉.

    상태를 바꾸고 알림 문장 목록을 돌려준다.
    """
    msgs = []
    # 1) 보유 포지션: 청산 확인 → 만기 청산
    for sym, p in list(st["positions"].items()):
        d = D.get(sym)
        if d is None:
            continue
        since = d[(d["dt"] > pd.Timestamp(p["entry_day"]) - DAY) & (d["dt"] <= day)]
        if since.empty:
            continue
        low = float(since["low"].min())
        p["mae"] = round(min(p.get("mae", 0.0), (low / p["entry"] - 1) * 100), 2)
        liq = low <= liq_price(p["entry"], p["lev"])
        exit_day = pd.Timestamp(p["exit_day"])
        if liq or day >= exit_day:
            row = since[since["dt"] == min(exit_day, day)]
            px = liq_price(p["entry"], p["lev"]) if liq else float((row if len(row) else since.tail(1))["close"].iloc[0])
            pnl, r = settle(p, px, liq)
            st["equity"] += pnl
            st["trades"].append({"sym": sym, "entry_day": p["entry_day"], "exit_day": str(min(exit_day, day).date()),
                                 "entry": p["entry"], "exit": px, "ret": round(r, 2),
                                 "pnl": round(pnl, 2), "wallet_pct": round(pnl / (st["equity"] - pnl) * 100, 2),
                                 "liq": liq, "mae": p["mae"]})
            del st["positions"][sym]
            msgs.append(f"🧪 [모의·돌파] {'⚠️ 청산(2배 격리 강제청산)' if liq else '만기 청산'} {sym}\n"
                        f"코인 {r:+.1f}% → 지갑 {pnl/(st['equity']-pnl)*100:+.2f}% ({pnl:+.2f} USDT)\n"
                        f"가상 자본 {st['equity']:,.2f} (시작 대비 {(st['equity']/START_EQUITY-1)*100:+.1f}%)")
    st["peak"] = max(st["peak"], st["equity"])
    st["mdd"] = round(max(st["mdd"], (1 - st["equity"] / st["peak"]) * 100), 2)

    # 2) 겹침: 실거래 봇이 같은 코인을 들고 있는 날 수
    ov = sorted(set(st["positions"]) & live)
    if ov:
        st["overlap_days"] += len(ov)

    # 3) 새 신호 (어제 종가 기준, 시장 200일선 위일 때만)
    closes = {s: d[d["dt"] <= day].set_index("dt")["close"] for s, d in D.items()}
    bull = market_bull(closes)
    st["bull"] = bull
    if not bull:
        return msgs
    for sym, d in D.items():
        if sym in st["positions"]:
            continue
        hist = d[d["dt"] <= day]
        if hist.empty or hist["dt"].iloc[-1] != day or not is_signal(hist["close"].values):
            continue
        today = d[d["dt"] == day + DAY]
        if today.empty:
            continue
        entry = float(today["open"].iloc[0])
        margin = st["equity"] * PER_TRADE
        st["positions"][sym] = {"entry": entry, "entry_day": str((day + DAY).date()),
                                "exit_day": str((day + HOLD * DAY).date()),
                                "margin": round(margin, 4), "lev": LEVERAGE, "mae": 0.0}
        tag = " · 실거래 봇도 보유 중(겹침)" if sym in live else ""
        msgs.append(f"🧪 [모의·돌파] 가상 매수 {sym} {entry:.6g}\n"
                    f"100일 신고가 · 시장 200일선 위 · 증거금 {margin:,.2f} (2%·2배){tag}\n"
                    f"{(day + HOLD * DAY):%m-%d} 종가에 청산 예정 (손절 없음, 강제청산가 {liq_price(entry):.6g})")
    return msgs


def run(dry: bool = False):
    from bot.oversold.executor import load_env, notify
    load_env()
    st = load_state()
    now = datetime.now(timezone.utc)
    day = pd.Timestamp(now.date()) - DAY              # 어제 = 확정된 마지막 일봉
    if st["last_day"] == str(day.date()):
        print(f"이미 처리함: {day.date()}")
        return
    D, miss = {}, []
    for s in S.SYMBOLS:
        d = fetch_daily(s)
        if d is None or d.empty:
            miss.append(s)
            continue
        D[s] = d
    if len(miss) > len(S.SYMBOLS) // 4:
        raise SystemExit(f"일봉을 못 받은 코인이 많다 ({len(miss)}개) — 다음 실행에 다시 한다")
    if st["last_day"] and pd.Timestamp(st["last_day"]) < day - DAY:
        st["skipped"].append(f"{st['last_day']}~{(day - DAY).date()}")
    if not st["started"]:
        st["started"] = str(day.date())
    msgs = step(st, D, day, live_symbols())
    st["last_day"] = str(day.date())
    if miss:
        msgs.append(f"🧪 [모의·돌파] 일봉 못 받은 코인 {len(miss)}개: {', '.join(miss)}")
    for m in msgs:
        print(m, "\n")
        if not dry:
            notify(m)
    if not dry:
        save_state(st)
        time.sleep(3)                                   # 알림 스레드가 보낼 시간
    print(status_line(st))


def status_line(st: dict) -> str:
    """감시(monitor) 아침 요약에 붙는 한 줄."""
    tr = st.get("trades", [])
    w = sum(t["pnl"] > 0 for t in tr)
    return (f"🧪 돌파 모의(2%·2배): 가상 {st['equity']:,.0f} USDT "
            f"({(st['equity']/START_EQUITY-1)*100:+.1f}%) · 보유 {len(st['positions'])} · "
            f"청산 {len(tr)}건" + (f" {w}승" if tr else "") +
            f" · 시장 {'200일선 위' if st.get('bull') else '200일선 아래(신규 없음)'}")


def status():
    st = load_state()
    print(status_line(st))
    print(f"시작 {st['started'] or '-'} · 마지막 처리 {st['last_day'] or '-'} · 최대낙폭(실현) {st['mdd']}% · "
          f"실거래와 겹친 날 {st['overlap_days']}" + (f" · 꺼져 있던 구간 {st['skipped']}" if st["skipped"] else ""))
    for s, p in st["positions"].items():
        print(f"  보유 {s:<10} {p['entry_day']} @ {p['entry']:.6g} → {p['exit_day']} 청산 예정 · 중간 최저 {p['mae']:+.1f}%")
    for t in st["trades"][-15:]:
        print(f"  {t['sym']:<10} {t['entry_day']}→{t['exit_day']} 코인 {t['ret']:+.1f}% 지갑 {t['wallet_pct']:+.2f}%"
              + (" (강제청산)" if t["liq"] else ""))


def main():
    ap = argparse.ArgumentParser(description="돌파 모듈 모의매매 (주문 없음)")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--dry", action="store_true", help="저장·알림 없이 화면에만")
    a = ap.parse_args()
    status() if a.status else run(dry=a.dry)


if __name__ == "__main__":
    main()
