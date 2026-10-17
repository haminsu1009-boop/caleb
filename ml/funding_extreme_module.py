"""
ml/funding_extreme_module.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
펀딩비 극단 역추세 — 숏이 과밀할 때(펀딩 깊은 마이너스) 롱 (RESEARCH_AGENDA, 2026-10-16)

펀딩비는 필터로는 이미 시험했다(ml/funding_filter.py 등). 여기선 별도 진입으로 쓴다.
신호: 코인의 직전 3회(24시간) 평균 펀딩비 ≤ Y (8시간당). 펀딩이 정산된 시각 뒤 첫
4시간봉 시가에 롱, hold 일 뒤 종가 청산, 2배. 같은 코인 보유 중 재진입 없음
(지금 롱과 코인 자리 공유). 수수료 0.40% + 펀딩 0.01%/8h(net()이 뺀다 — 실제로는
마이너스 펀딩이라 롱이 받는 쪽이므로 보수적).
데이터: data/funding (바이낸스 선물, 2020-10~; 종목마다 시작 다름). 학습 구간이
2020-10~2023 으로 짧다는 점을 감안한다.
새 kind "fund" 로 지금 봇(ml/crash_window.py 설정)에 더해 taken 으로 지갑 전체를 돌린다.

격자: Y {-0.03, -0.05, -0.10}% × 보유 {3, 7}일 × 비중 {1, 2}% = 12개.
고르기는 ~2023 결과만, 2024~ 는 고른 뒤 한 번만. 이웃(±1칸) 모두 개선돼야 한다.

━━ 결과 (2026-10-16) — 기각 ━━
                         2017~  곡선낙폭  1년손실  2024~  거래/년  fund 승률·거래당
    지금 봇               36.3배  24.9%    1.5%    6.2배   187
    ≤-0.05%·3일·2% (1등)  37.5배  25.6%    2.0%    5.8배   +75   45% · +0.5%
    ≤-0.10%·3일·2% (이웃) 39.1배  25.6%    2%      6.4배   +28   42% · +1.3%
    ≤-0.03%·3일·1%        37.9배  24.1%    2%      6.2배  +145   45% · +0.6% (2025 +165→+98)
  12개 모두 지금과 ±10% 안이고, 학습 1등은 2024~·곡선낙폭·1년손실이 조금씩 나빠진다.
  이웃 4개도 모두 한 가지 이상 나빠진다. 신호 자체가 승률 41~47%, 거래당 +0.2~+1.6%
  (2배, 비용 뒤)로 약하다. 숏 과밀(마이너스 펀딩)은 이미 급락 중인 코인에서 많이 나와
  지금 과매도 롱과 겹치고, 따로 쓰면 증거금만 나눠 먹는다(-0.03% 는 2025 를 크게 깎음).
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
from bot.oversold import regime as REG
import ml.unified_pool as UP
import ml.short_setups as SS
from ml.backtest_current_bot import load
from ml.per_coin_rules import sim
from ml.per_coin_walkforward import MENU
from ml.per_coin_portfolio import to_up
from ml.module_winrate import taken
from ml.bear_leverage import bear_series, is_on, T0, T19, TE
from ml.crash_window import crash_hits, in_window

GAPS = (-0.03, -0.05, -0.10)
HOLDS = (3, 7)
SIZES = (0.01, 0.02)
FUND = 0.01


def make_fund(G, y, hold_days):
    out = []
    hold = hold_days * 6
    for s, g in G.items():
        f = f"data/funding/{s}_funding.csv.gz"
        if not os.path.exists(f):
            continue
        fd = pd.read_csv(f)
        fd["datetime"] = pd.to_datetime(fd["datetime"], format="mixed")
        fr = fd.set_index("datetime")["funding_rate"].astype(float) * 100     # %/8h
        m = fr.rolling(3).mean()
        sig_t = m[m <= y].index
        d = g.set_index("datetime")
        t4 = pd.to_datetime(d.index); o = d["open"].astype(float).values
        c = d["close"].astype(float).values; l = d["low"].astype(float).values
        n = len(c); lock = -10**9
        for ts in sig_t:
            j = t4.searchsorted(ts, side="right")       # 정산 시각 뒤 첫 봉
            if j <= lock or j + hold >= n:
                continue
            e = o[j]
            out.append({"kind": "fund", "sym": s, "dt": pd.Timestamp(t4[j]),
                        "exit": pd.Timestamp(t4[j + hold - 1]), "entry": e, "exit_px": c[j + hold - 1],
                        "mae": (l[j:j + hold].min() / e - 1) * 100, "deployed": 1.0,
                        "bars_h": hold * 4, "long": True})
            lock = j + hold
    return out


def main():
    Dd = {s: SS.load_daily(s) for s in S.SYMBOLS}
    Dd = {k: v for k, v in Dd.items() if v is not None and len(v) >= 400}
    W = {s: SS.to_weekly(d) for s, d in Dd.items()}
    ma, th, hd, fr, ou, st = MENU["A 지금 봇"]
    L, G = [], {}
    for s in S.SYMBOLS:
        g = load(s)
        if g is None or len(g) < 400:
            continue
        G[s] = g
        o, h, l, c = (g[k].astype(float).values for k in ("open", "high", "low", "close"))
        L += [to_up(t) for t in sim(o, h, l, c, g["datetime"].values, ma, th, hd, fr, ou,
                                    S.STOP_PCT, sym=s, step=st)]
    cut = lambda X: [t for t in X if t["dt"] >= T0]
    L, Sh, Dv = cut(L), cut(UP.make_short(W)), cut(UP.make_div(Dd))
    btc = Dd["BTCUSDT"].set_index("dt")["close"]
    B = bear_series(btc, REG.AUTO_BEAR_ON, REG.AUTO_BEAR_OFF, REG.AUTO_BEAR_N)
    hits = crash_hits(load("BTCUSDT").set_index("datetime")["close"].astype(float))
    base_tr = [dict(t, kind="longb") if (is_on(B, t["dt"]) or in_window(hits, t["dt"])) else t
               for t in L] + Sh + Dv

    def run(extra, size=0.0):
        tr = base_tr + extra
        pt = {"long": .015, "longb": .015, "short": .40, "div": .40, "fund": size}
        lv = {"long": 4.0, "longb": 2.0, "short": 1.0, "div": 1.0, "fund": 2.0}
        f = lambda X: taken(X, pt, lv)
        fin, mdd, got, c = f(tr); w = UP.windows(c)
        f19, _, _, c19 = f([t for t in tr if t["dt"] >= T19]); w19 = UP.windows(c19)
        a = f([t for t in tr if t["dt"] < TE])[0]; h = f([t for t in tr if t["dt"] >= TE])[0]
        y = c.resample("YE").last(); yr = ((y / y.shift(1).fillna(1) - 1) * 100)
        yrs = (c.index[-1] - c.index[0]).days / 365
        g4 = [x for x in got if x[0] == "fund"]
        return dict(fin=fin, f19=f19, mdd=mdd * 100, cdd=float((1 - c / c.cummax()).max() * 100),
                    l1=(w < 1).mean() * 100, l19=(w19 < 1).mean() * 100, a=a, h=h,
                    yr={d.year: v for d, v in yr.items()}, n=len(got) / yrs, n4=len(g4) / yrs,
                    wr4=np.mean([x[1] > 0 for x in g4]) * 100 if g4 else np.nan,
                    av4=np.mean([x[1] for x in g4]) if g4 else np.nan)

    def show(lab, r):
        y = r["yr"]
        print(f"{lab:<22}{r['fin']:>6.1f}배{r['f19']:>6.1f}배{r['mdd']:>5.1f}%{r['cdd']:>6.1f}%"
              f"{r['l1']:>4.0f}/{r['l19']:.0f}%{r['a']:>6.1f}배{r['h']:>6.1f}배 "
              f"연{r['n']:>4.0f}건(+{r['n4']:.0f}) "
              + (f"승{r['wr4']:.0f}% {r['av4']:+.1f}% " if r['n4'] else "")
              + " ".join(f"{k%100}:{v:+.0f}" for k, v in y.items() if k >= 2018), flush=True)
        return r

    print(f"{'':<22}{'2017~':>7}{'2019~':>7}{'낙폭':>6}{'곡선':>7}{'1년손실':>8}{'~2023':>7}{'2024~':>7}  거래(연)  연도별%")
    base = show("지금 봇", run([]))
    R = {}
    for gap in GAPS:
        for hold in HOLDS:
            D4 = cut(make_fund(G, gap, hold))
            for size in SIZES:
                R[(gap, hold, size)] = show(f"펀딩≤{gap:g}%·{hold}일·{size*100:.0f}%", run(D4, size))

    best = max(R, key=lambda k: R[k]["a"])
    print(f"\n학습(~2023) 1등: {best}")
    gi, hi, si = GAPS.index(best[0]), HOLDS.index(best[1]), SIZES.index(best[2])
    nb = set()
    for dg, dh, ds in ((-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0), (0, 0, -1), (0, 0, 1)):
        a, b_, c_ = gi + dg, hi + dh, si + ds
        if 0 <= a < len(GAPS) and 0 <= b_ < len(HOLDS) and 0 <= c_ < len(SIZES):
            nb.add((GAPS[a], HOLDS[b_], SIZES[c_]))
    for k in [best] + sorted(nb):
        r = R[k]; bad = []
        for key, nm, sgn in (("fin", "2017~", 1), ("h", "2024~", 1), ("cdd", "곡선낙폭", -1), ("l1", "1년손실", -1)):
            if (r[key] - base[key]) * sgn < -1e-9:
                bad.append(f"{nm} {base[key]:.1f}→{r[key]:.1f}")
        cut_yr = [f"{yy}: {base['yr'][yy]:+.0f}→{r['yr'][yy]:+.0f}" for yy in base["yr"]
                  if yy in r["yr"] and r["yr"][yy] < base["yr"][yy] - 20]
        print(f"  {'1등' if k == best else '이웃'} {k}: {'통과' if not bad else '나빠짐 ' + ', '.join(bad)}"
              + (f" | 크게 깎인 해 {', '.join(cut_yr)}" if cut_yr else ""))


if __name__ == "__main__":
    main()
