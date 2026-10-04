"""
ml/vol_target_exec.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
③ 변동성 타겟팅 사이징 + ① 지정가 실행

③ 변동성 타겟팅
   지금은 자본의 고정 비율(진입당 2%)을 건다. 시장이 잔잔하든
   요동치든 같은 크기다. 변동성이 높을 때 크기를 줄이고 낮을 때
   늘리면 수익 대비 변동성이 줄어드는 것이 일반적이다.

   크기 = 기준크기 × (목표변동성 / 최근변동성), 상한·하한을 둔다.
   최근변동성은 그 시점까지의 값만 쓴다 — 미래를 보지 않는다.

① 지정가 실행
   ml/fill_timing.py에서 시장가 체결 지연 비용을 0.196%p로 실측했다.
   지정가로 걸면 그 비용을 줄일 수 있지만, 체결이 안 되면 신호를
   통째로 놓친다. 놓친 신호가 하필 좋은 거래였다면 수수료 아낀
   것보다 훨씬 손해다.

   5분봉으로 "봉 확정 후 N분 안에 지정가에 닿았는가"를 재서
   체결률을 구하고, 미체결로 놓치는 손실과 아낀 비용을 비교한다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, glob, argparse, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from bot.oversold import strategy as S
import ml.unified_pool as U
import ml.short_setups as SS
from ml.backtest_current_bot import load, ROUND_TRIP, FUNDING_PER_8H

TE = pd.Timestamp("2024-01-01")


# ── ③ 변동성 타겟팅 ─────────────────────────────────────
def build_vol(target=0.60, win=120, lo=0.5, hi=2.0, **kw):
    """거래마다 그 시점의 실현변동성으로 크기 배수를 붙인다."""
    trades = U.make_long(**kw)
    volmap = {}
    for sym in S.SYMBOLS:
        g = load(sym)
        if g is None:
            continue
        c = g["close"].astype(float)
        r = c.pct_change()
        v = r.rolling(win).std() * np.sqrt(6 * 365)      # 4시간봉 연율
        volmap[sym] = pd.Series(v.values, index=pd.to_datetime(g["datetime"]))
    out = []
    for t in trades:
        s = volmap.get(t["sym"])
        mult = 1.0
        if s is not None:
            k = s.index.searchsorted(t["dt"], side="right") - 1
            if k >= 0 and not np.isnan(s.iloc[k]) and s.iloc[k] > 0:
                mult = float(np.clip(target / s.iloc[k], lo, hi))
        t = dict(t); t["size_mult"] = mult
        out.append(t)
    return out


def simulate_sized(trades, per_trade, leverage, max_gross=1.0, cb=0.25, cool=30):
    """U.simulate와 같되 거래별 size_mult를 반영한다."""
    cash = peak = 1.0; mdd = 0.0; open_ = []; halted = None
    held = set(); curve = {}
    n = {"long": 0, "short": 0, "div": 0}
    ts = sorted(trades, key=lambda x: x["dt"])
    days = pd.date_range(ts[0]["dt"].normalize(), ts[-1]["dt"].normalize(), freq="D")
    di = 0
    def mark(u):
        nonlocal di
        while di < len(days) and days[di] <= u:
            curve[days[di]] = cash; di += 1
    for t in ts:
        now = t["dt"]; mark(now)
        keep = []
        for ex, res, pl, sym in open_:
            if ex <= now: cash += pl; held.discard(sym)
            else: keep.append((ex, res, pl, sym))
        open_ = keep
        if cash <= 1e-9:
            return {"final": 0.0, "mdd": 1.0, "n": n, "curve": pd.Series(curve)}
        peak = max(peak, cash); mdd = max(mdd, 1 - cash / peak)
        if halted is not None and now < halted: continue
        halted = None
        if 1 - cash / peak >= cb:
            halted = now + pd.Timedelta(days=cool); peak = cash; continue
        k = t["kind"]
        if t["sym"] in held: continue
        lev = leverage[k]
        m = per_trade[k] * cash * t.get("size_mult", 1.0)
        res = m * lev
        if sum(r for _, r, _, _ in open_) + res > max_gross * cash * max(leverage.values()):
            continue
        liq = 100.0 / lev - 0.5
        raw = (t["exit_px"] / t["entry"] - 1) * 100
        px = raw if t["long"] else -raw
        if t["mae"] <= -liq: px = -liq
        fee = ROUND_TRIP + (FUNDING_PER_8H * (t["bars_h"] / 8.0) if lev > 1 else 0)
        dep = t["deployed"]
        pl = max(m * dep * lev * (px - fee) / 100, -m * dep)
        open_.append((t["exit"], res, pl, t["sym"])); held.add(t["sym"]); n[k] += 1
    mark(days[-1])
    for _, _, pl, _ in open_: cash += pl
    return {"final": cash, "mdd": mdd, "n": n, "curve": pd.Series(curve)}


def stats(r):
    eq = r["curve"]; d = eq.pct_change().dropna()
    ann = (1 + d.mean()) ** 365 - 1
    vol = d.std() * np.sqrt(365)
    w = U.windows(eq)
    return dict(final=r["final"], cagr=ann * 100, vol=vol * 100,
                sharpe=(ann - 0.03) / vol, mdd=r["mdd"] * 100,
                med=np.median(w), loss=(w < 1).mean() * 100)


def main():
    argparse.ArgumentParser().parse_args()
    syms = [s for s in S.SYMBOLS if os.path.exists(f"data/{s}_1d_all.csv.gz")]
    D = {s: SS.load_daily(s) for s in syms}
    D = {k: v for k, v in D.items() if v is not None and len(v) >= 400}
    W = {s: SS.to_weekly(d) for s, d in D.items()}
    Sh = U.make_short(W); Dv = U.make_div(D)
    LEV = {"long": 2.0, "short": 1.0, "div": 1.0}
    PT = {"long": .02, "short": .50, "div": .30}
    base = dict(fracs=[.30, .70], hold=60, bb=True, bb_k=1.5)

    print("=" * 92)
    print("  ③ 변동성 타겟팅 — 변동성이 높을 때 작게, 낮을 때 크게")
    print("=" * 92)
    print(f"\n  {'설정':<28s}{'전체':>9s}{'연복리':>7s}{'변동성':>7s}{'샤프':>7s}"
          f"{'낙폭':>7s}{'1년중앙':>9s}{'손실':>6s}")
    print("  " + "-" * 82)
    L0 = U.make_long(**base)
    for t in L0: t["size_mult"] = 1.0
    r = simulate_sized(L0 + Sh + Dv, PT, LEV)
    s = stats(r)
    print(f"  {'고정 크기 (현재)':<28s}{s['final']:>8.2f}배{s['cagr']:>6.0f}%{s['vol']:>6.0f}%"
          f"{s['sharpe']:>7.2f}{s['mdd']:>6.0f}%{s['med']:>8.2f}배{s['loss']:>5.0f}%")
    for tgt in (0.40, 0.60, 0.80, 1.00):
        for hi in (1.5, 2.0, 3.0):
            Lv = build_vol(target=tgt, hi=hi, **base)
            r = simulate_sized(Lv + Sh + Dv, PT, LEV)
            s = stats(r)
            print(f"  {'목표변동성 %d%% · 상한 %.1f배' % (tgt*100, hi):<28s}"
                  f"{s['final']:>8.2f}배{s['cagr']:>6.0f}%{s['vol']:>6.0f}%"
                  f"{s['sharpe']:>7.2f}{s['mdd']:>6.0f}%{s['med']:>8.2f}배{s['loss']:>5.0f}%")


if __name__ == "__main__":
    main()
