"""
ml/per_coin_portfolio.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
코인마다 다른 롱 규칙 — 실제 운용 설정(4배 · 롱+숏+다이버 · 폭락장 롱 끔)으로

앞의 코인별 실험들은 롱 모듈만 따로 봤다. 여기서는 실제로 굴릴 전체
포트폴리오 안에서 본다 — 롱 4배, 주봉 숏·상승 다이버전스 1배(자본 40%),
한 지갑, 폭락장(BTC 직전 N일 수익률 ≤ 기준)엔 롱 신규 진입 끔.

롱 규칙만 코인마다 다르게 고른다. 후보는 ml/per_coin_walkforward.py의
메뉴 다섯 개 + "그 코인은 롱 안 함".

세 가지를 나란히 둔다.
  · 전 종목 같은 규칙(A, 지금 봇)
  · 코인별 — 과거 전체를 보고 코인마다 최고를 고른 것. 미래를 미리 본
    셈이라 부풀려진다. 흔히 보는 "코인별 최적화" 결과가 이런 모양이다.
  · 코인별 — 워크포워드. 매년 초 그 전 데이터만으로 코인마다 고른다
    (수축 K=20). 실제 운용과 같은 방식이라 이 줄을 믿으면 된다.

폭락장 기준은 네 가지로 흔들어 범위로 보인다.

━━ 결과: 코인별이 크게 진다. 미래를 미리 봐도 진다 ━━

    (2019~2026, 폭락장 기준 4가지 범위)
    롱 규칙                        결과         연복리     1년손실   2024~
    전 종목 같은 규칙(지금 봇)     43.8~65.3배   66~77%    0~10%   8.0~11.7배

    고르는 기준 = 거래당 평균
      코인별 · 과거 전체 보고       9.5~17.2배   36~48%   12~29%   6.4~7.4배
      코인별 · 워크포워드           8.6~17.3배   34~46%    4~18%   5.1~5.7배

    고르는 기준 = 거래당 × 거래 수(총량)  (--by-total)
      코인별 · 과거 전체 보고      14.9~33.4배   45~62%   10~24%   8.3~10.0배
      코인별 · 워크포워드          11.3~18.1배   40~49%   14~22%   5.7~7.2배

거래당 평균으로 고르면 42종 중 40종이 드물고 깊은 규칙(C)으로 몰려
거래 수가 줄어든다. 총량으로 고르면 배정이 흩어지지만 역시 진다.
과거 전체를 보고 골라도(미래 참조) 공통 규칙을 못 이긴다 — 코인 하나
하나의 성적을 최적화해도, 한 지갑에서 동시에 굴릴 때의 결과(배율 4배,
총노출 상한, 차단기, 겹치는 타이밍)는 좋아지지 않는다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations
import os, sys, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from bot.oversold import strategy as S
import ml.unified_pool as UP
import ml.short_setups as SS
from ml.backtest_current_bot import load, ROUND_TRIP, FUNDING_PER_8H
from ml.per_coin_rules import sim
from ml.per_coin_walkforward import MENU

YEARS = list(range(2019, 2027))
K = 20.0
TE = pd.Timestamp("2024-01-01")


def to_up(t):
    return {"kind": "long", "sym": t["sym"], "dt": pd.Timestamp(t["dt"]),
            "exit": pd.Timestamp(t["exit_dt"]), "entry": t["entry"],
            "exit_px": t["exit_px"], "mae": t["mae"], "deployed": t["deployed"],
            "bars_h": t["bars_h"], "long": True}


def net(t):
    return (t["exit_px"] / t["entry"] - 1) * 100 - ROUND_TRIP - FUNDING_PER_8H * t["bars_h"] / 8


def wmean(ts):
    if not ts:
        return np.nan, 0
    r = np.array([net(t) for t in ts]); d = np.array([t["deployed"] for t in ts])
    return float(np.average(r, weights=d)), len(ts)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--by-total", action="store_true",
                    help="거래당 평균이 아니라 '거래당 × 거래 수'(총량)로 고른다")
    a = ap.parse_args()
    syms = [s for s in S.SYMBOLS if os.path.exists(f"data/{s}_1d_all.csv.gz")]
    Dd = {s: SS.load_daily(s) for s in syms}
    Dd = {k: v for k, v in Dd.items() if v is not None and len(v) >= 400}
    W = {s: SS.to_weekly(d) for s, d in Dd.items()}
    Sh = UP.make_short(W); Dv = UP.make_div(Dd)

    T = {}
    for sym in S.SYMBOLS:
        g = load(sym)
        if g is None or len(g) < 400:
            continue
        o, h, l, c = (g[k].astype(float).values for k in ("open", "high", "low", "close"))
        for name, (ma, th, hd, fr, ou, st) in MENU.items():
            T[(sym, name)] = [to_up(t) for t in sim(o, h, l, c, g["datetime"].values,
                                                     ma, th, hd, fr, ou, S.STOP_PCT, sym=sym, step=st)]
    coins = sorted({s for s, _ in T})
    yr = lambda t: t["dt"].year

    # 전 종목 같은 규칙
    glob = [t for s in coins for t in T[(s, "A 지금 봇")]]
    # 과거 전체를 보고 고른 코인별 (미래 참조)
    ins_pick = {}
    for s in coins:
        def sc_ins(n):
            mu, k = wmean(T[(s, n)])
            if k < 5: return -9e9
            return mu * k if a.by_total else mu
        best = max(MENU, key=sc_ins)
        ins_pick[s] = best if wmean(T[(s, best)])[0] > 0 else None
    ins = [t for s in coins if ins_pick[s] for t in T[(s, ins_pick[s])]]
    # 워크포워드 코인별
    wf, picks = [], {}
    for Y in YEARS:
        gm = {n: wmean([t for s in coins for t in T[(s, n)] if yr(t) < Y])[0] for n in MENU}
        for s in coins:
            best, bs = None, -9e9
            for n in MENU:
                mu, k = wmean([t for t in T[(s, n)] if yr(t) < Y])
                g_ = gm[n] if not np.isnan(gm[n]) else 0.0
                sc = g_ if (k < 5 or np.isnan(mu)) else (k * mu + K * g_) / (k + K)
                if a.by_total:
                    sc = sc * max(k, 1)
                if sc > bs:
                    best, bs = n, sc
            picks[(Y, s)] = best if bs > 0 else None
            if picks[(Y, s)]:
                wf += [t for t in T[(s, best)] if yr(t) == Y]
    # 비교를 같은 기간(2019~)으로 맞춘다
    t0 = pd.Timestamp(f"{YEARS[0]}-01-01")
    glob = [t for t in glob if t["dt"] >= t0]
    ins = [t for t in ins if t["dt"] >= t0]
    sh = [t for t in Sh if t["dt"] >= t0]; dv = [t for t in Dv if t["dt"] >= t0]

    b = pd.read_csv("data/BTCUSDT_1d_all.csv.gz")
    col = "datetime" if "datetime" in b.columns else b.columns[0]
    b[col] = pd.to_datetime(b[col], format="mixed")
    b = b.rename(columns={col: "dt"}).sort_values("dt").set_index("dt")

    def bearset(N, th):
        r = (b["close"].pct_change(N) * 100); idx = r.index; v = r.values
        def f(ts):
            i = idx.searchsorted(pd.Timestamp(ts), side="right") - 2   # 전날 종가까지만 (그날 종가는 아직 모른다)
            return i >= 0 and not np.isnan(v[i]) and v[i] <= th
        return f
    PROX = [bearset(30, -15), bearset(60, -15), bearset(90, -20), bearset(120, -25)]

    pt = {"long": .015, "short": .40, "div": .40}
    lv = {"long": 4.0, "short": 1.0, "div": 1.0}

    def run(longs, bear, start=None):
        tr = [t for t in longs if not bear(t["dt"])] + sh + dv
        if start is not None:
            tr = [t for t in tr if t["dt"] >= start]
        r = UP.simulate(tr, per_trade=pt, leverage=lv, max_gross=0.6, cb=0.20, cool_days=30)
        c = r["curve"]; w = UP.windows(c) if len(c) > 400 else np.array([np.nan])
        cg = (r["final"] ** (365 / len(c)) - 1) * 100 if r["final"] > 0 else -100
        return r["final"], cg, r["mdd"] * 100, np.nanmean(w < 1) * 100, r["n"]["long"]

    print("=" * 110)
    print("  코인마다 다른 롱 규칙 · 롱 4배 + 숏·다이버 1배 · 폭락장 롱 끔 · 2019~2026")
    print("  (폭락장 기준 4가지 범위)")
    print("=" * 110)
    print(f"\n  {'롱 규칙':<36s}{'결과':>16s}{'연복리':>11s}{'낙폭':>10s}{'1년손실':>10s}{'2024~':>16s}")
    print("  " + "-" * 102)
    for lab, longs in [("전 종목 같은 규칙 (지금 봇)", glob),
                       ("코인별 · 과거 전체 보고 고름 (부풀려짐)", ins),
                       ("코인별 · 워크포워드 (실제 운용 방식)", wf)]:
        v = [run(longs, B) for B in PROX]
        h = [run(longs, B, TE) for B in PROX]
        g = lambda i: (min(x[i] for x in v), max(x[i] for x in v))
        print(f"  {lab:<36s}{g(0)[0]:>7.1f}~{g(0)[1]:<6.1f}배{g(1)[0]:>4.0f}~{g(1)[1]:<3.0f}%"
              f"{g(2)[0]:>4.0f}~{g(2)[1]:<3.0f}%{g(3)[0]:>4.0f}~{g(3)[1]:<3.0f}%"
              f"{min(x[0] for x in h):>7.2f}~{max(x[0] for x in h):<5.2f}배")

    last = YEARS[-1]
    cnt = pd.Series([picks[(last, s)] or "안 함" for s in coins]).value_counts()
    print(f"\n  워크포워드 {last}년 코인별 배정")
    for k, n in cnt.items():
        print(f"    {k:<16s}{n:>3}종")
    ic = pd.Series([ins_pick[s] or "안 함" for s in coins]).value_counts()
    print(f"\n  과거 전체 보고 고른 배정")
    for k, n in ic.items():
        print(f"    {k:<16s}{n:>3}종")
    print("=" * 110)


if __name__ == "__main__":
    main()
