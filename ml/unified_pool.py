"""
ml/unified_pool.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
세 전략을 하나의 자본 풀에서 굴린다

앞선 ml/final_config.py는 자본을 고정 비율로 쪼갰다(롱60·숏30·
다이버10). 그건 틀린 구조다. 숏은 연 2건, 다이버전스는 연 7건뿐인데
자본의 40%를 거기 묶어두면 대부분의 시간 동안 그 돈이 논다.
그래서 수익률이 낮게 나왔다.

옳은 구조는 하나의 풀이다.
  · 자본은 하나다. 세 전략이 같은 지갑에서 꺼내 쓴다.
  · 각 전략은 신호가 날 때만 정해진 비율(per_trade)만큼 쓴다.
  · 총노출 상한과 차단기는 계좌 전체에 하나로 건다.
  · 숏이 안 나오는 동안 그 자본은 롱이 쓴다.

이러면 드물게 나오는 전략을 넣는 비용이 "자본을 놀리는 것"이
아니라 "가끔 롱 자리 하나를 양보하는 것"이 된다.

거래를 시간순으로 하나의 큐에 넣고 순서대로 처리한다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from bot.oversold import strategy as S
from ml.backtest_current_bot import (ROUND_TRIP, FUNDING_PER_8H, BAR_HOURS,
                                     pnl_pct, bb_upper, load)
import ml.short_setups as SS
import ml.divergence_scoped as DS
import ml.bull_breakout as BB
from ml.final_config import build

TE = pd.Timestamp("2024-01-01")


def make_long(**kw):
    """4시간봉 과매도 롱 → 공통 형식으로."""
    out = []
    for t in build(**kw):
        out.append({"kind": "long", "sym": t["sym"], "dt": pd.Timestamp(t["dt"]),
                    "exit": pd.Timestamp(t["exit_dt"]),
                    "entry": t["entry_avg"], "exit_px": t["exit_px"],
                    "mae": t["mae"], "deployed": t["deployed"],
                    "bars_h": (t["exit_bar"] - t["entry_bar"]) * BAR_HOURS,
                    "long": True})
    return out


def make_short(W, streak=4, hold=4):
    out = []
    for s, d in W.items():
        o, c, h, l, dt = (d["open"].values, d["close"].values, d["high"].values,
                          d["low"].values, d["dt"].values)
        n = len(c); lock = -10**9
        for i in SS.setup_A(d, 60, streak):
            if i <= lock or i + 1 + hold >= n:
                continue
            e = o[i + 1]
            out.append({"kind": "short", "sym": s, "dt": pd.Timestamp(dt[i + 1]),
                        "exit": pd.Timestamp(dt[i + hold]),
                        "entry": e, "exit_px": c[i + hold],
                        # 숏의 역행은 고가 기준
                        "mae": (1 - h[i + 1:i + hold + 1].max() / e) * 100,
                        "deployed": 1.0,
                        "bars_h": hold * 24 * 7, "long": False})
            lock = i + hold
    return out


def make_div(D, gap=8.0, hold=10):
    out = []
    for s, d in D.items():
        o, c, l, dt = (d["open"].values, d["close"].values,
                       d["low"].values, d["dt"].values)
        n = len(c); lock = -10**9
        for i in DS.divergence(d, bullish=True, gap=gap):
            if i <= lock or i + 1 + hold >= n:
                continue
            e = o[i + 1]
            out.append({"kind": "div", "sym": s, "dt": pd.Timestamp(dt[i + 1]),
                        "exit": pd.Timestamp(dt[i + hold]),
                        "entry": e, "exit_px": c[i + hold],
                        "mae": (l[i + 1:i + hold + 1].min() / e - 1) * 100,
                        "deployed": 1.0,
                        "bars_h": hold * 24, "long": True})
            lock = i + hold
    return out


def make_break(D, window=BB.WINDOW, hold=BB.HOLD, regime_exit=False):
    """상승장 신고가 돌파 롱. 시장이 200일선 위일 때만."""
    bull = BB.bull_days(D)
    out = []
    for s, d in D.items():
        o, c, l, dt = (d["open"].values, d["close"].values,
                       d["low"].values, pd.to_datetime(d["dt"]).values)
        n = len(c); lock = -10**9
        for i in BB.signals(d, window):
            if i <= lock or i + 1 + hold >= n:
                continue
            t = pd.Timestamp(dt[i + 1])
            if not bool(bull.get(t, False)):
                continue
            # 국면 이탈 청산: 보유 중 시장이 200일선 아래로 내려가면 그날 종가로 나온다.
            # 돌파는 상승장 엔진이다. 장이 꺾이면 자리를 비워야 과매도 롱이 들어간다.
            j = i + hold
            if regime_exit:
                for k in range(i + 1, i + hold + 1):
                    if not bool(bull.get(pd.Timestamp(dt[k]), True)):
                        j = k
                        break
            e = o[i + 1]
            out.append({"kind": "break", "sym": s, "dt": t,
                        "exit": pd.Timestamp(dt[j]),
                        "entry": e, "exit_px": c[j],
                        "mae": (l[i + 1:j + 1].min() / e - 1) * 100,
                        "deployed": 1.0,
                        "bars_h": (j - i) * 24, "long": True})
            lock = j
    return out


def simulate(trades, *, per_trade, leverage, max_gross=0.8,
             cb=0.25, cool_days=30):
    """하나의 풀. per_trade/leverage는 전략별 dict."""
    cash = peak = 1.0
    mdd = 0.0
    open_ = []          # (exit_dt, reserved, pl)
    halted = None
    kinds = sorted({t["kind"] for t in trades})
    n = {k: 0 for k in kinds}
    wins = {k: 0 for k in kinds}
    held_syms = set()
    curve = {}
    ts = sorted(trades, key=lambda x: x["dt"])
    days = pd.date_range(ts[0]["dt"].normalize(), ts[-1]["dt"].normalize(), freq="D")
    di = 0

    def mark(upto):
        nonlocal di
        while di < len(days) and days[di] <= upto:
            curve[days[di]] = cash
            di += 1

    for t in ts:
        now = t["dt"]
        mark(now)
        keep = []
        for ex, res, pl, sym in open_:
            if ex <= now:
                cash += pl
                held_syms.discard(sym)
            else:
                keep.append((ex, res, pl, sym))
        open_ = keep
        if cash <= 1e-9:
            return {"final": 0.0, "mdd": 1.0, "n": n, "wins": wins,
                    "curve": pd.Series(curve), "bust": True}
        peak = max(peak, cash)
        mdd = max(mdd, 1 - cash / peak)
        if halted is not None and now < halted:
            continue
        halted = None
        if 1 - cash / peak >= cb:
            halted = now + pd.Timedelta(days=cool_days)
            peak = cash
            continue
        k = t["kind"]
        if t["sym"] in held_syms:
            continue
        lev = leverage[k]
        m = per_trade[k] * cash
        reserved = m * lev
        if sum(r for _, r, _, _ in open_) + reserved > max_gross * cash * max(leverage.values()):
            continue
        liq = 100.0 / lev - 0.5
        raw = (t["exit_px"] / t["entry"] - 1) * 100
        px = raw if t["long"] else -raw
        if t["mae"] <= -liq:
            px = -liq
        fee = ROUND_TRIP + (FUNDING_PER_8H * (t["bars_h"] / 8.0) if lev > 1 else 0)
        net = px - fee
        dep = t["deployed"]
        pl = max(m * dep * lev * net / 100, -m * dep)
        open_.append((t["exit"], reserved, pl, t["sym"]))
        held_syms.add(t["sym"])
        n[k] += 1
        wins[k] += net > 0
    mark(days[-1])
    for _, _, pl, _ in open_:
        cash += pl
    return {"final": cash, "mdd": mdd, "n": n, "wins": wins,
            "curve": pd.Series(curve), "bust": False}


def windows(curve, target=1.0):
    r = curve.pct_change().fillna(0)
    out = []
    for s in pd.date_range(r.index[0], r.index[-1] - pd.Timedelta(days=365), freq="15D"):
        seg = r[(r.index >= s) & (r.index < s + pd.Timedelta(days=365))]
        if len(seg) > 200:
            out.append((1 + seg).prod())
    return np.array(out)


def main():
    argparse.ArgumentParser().parse_args()
    syms = [s for s in S.SYMBOLS if os.path.exists(f"data/{s}_1d_all.csv.gz")]
    D = {s: SS.load_daily(s) for s in syms}
    D = {k: v for k, v in D.items() if v is not None and len(v) >= 400}
    W = {s: SS.to_weekly(d) for s, d in D.items()}

    L = make_long(fracs=[.30, .70], hold=60, bb=True, bb_k=1.5)
    Sh = make_short(W)
    Dv = make_div(D)
    print("=" * 96)
    print("  하나의 자본 풀에서 세 전략 — 신호가 날 때만 꺼내 쓴다")
    print("=" * 96)
    print(f"\n  거래 후보: 롱 {len(L):,}건 · 숏 {len(Sh)}건 · 다이버전스 {len(Dv)}건")

    LEV = {"long": 2.0, "short": 1.0, "div": 1.0}
    print(f"\n  {'구성':<34s}{'전체':>9s}{'연복리':>7s}{'1년중앙':>9s}{'손실':>6s}"
          f"{'낙폭':>7s}{'롱':>6s}{'숏':>5s}{'다이버':>7s}")
    print("  " + "-" * 90)
    CASES = [
        ("롱만 (진입당 5%)", {"long": .05, "short": 0, "div": 0}),
        ("롱5% + 숏5% + 다이버5%", {"long": .05, "short": .05, "div": .05}),
        ("롱5% + 숏10% + 다이버10%", {"long": .05, "short": .10, "div": .10}),
        ("롱5% + 숏20% + 다이버10%", {"long": .05, "short": .20, "div": .10}),
        ("롱5% + 숏30% + 다이버20%", {"long": .05, "short": .30, "div": .20}),
        ("롱5% + 숏50% + 다이버30%", {"long": .05, "short": .50, "div": .30}),
    ]
    for lab, pt in CASES:
        tr = L + ([] if pt["short"] == 0 else Sh) + ([] if pt["div"] == 0 else Dv)
        r = simulate(tr, per_trade=pt, leverage=LEV)
        w = windows(r["curve"])
        yrs = len(r["curve"]) / 365
        cg = (r["final"] ** (1 / yrs) - 1) * 100 if r["final"] > 0 else -100
        print(f"  {lab:<34s}{r['final']:>8.2f}배{cg:>6.0f}%{np.median(w):>8.2f}배"
              f"{(w<1).mean()*100:>5.0f}%{r['mdd']*100:>6.0f}%"
              f"{r['n']['long']:>6d}{r['n']['short']:>5d}{r['n']['div']:>7d}")


if __name__ == "__main__":
    main()
