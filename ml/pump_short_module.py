"""
ml/pump_short_module.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
과열 숏 — 약세장(BTC 200일선 아래)에서 개별 코인이 3일 급등하면 숏 (RESEARCH_AGENDA, 2026-10-15)

신호(일봉 마감): BTC 종가 < BTC 200일 이동평균, 그리고 코인 3일 수익률 ≥ +X%.
다음날 시가에 숏, hold 일 뒤 종가 청산, 1배(청산선 +99.5%). 같은 코인 보유 중 재진입 없음
(지금 롱과 코인 자리 공유 — taken 규칙). 수수료 왕복 0.40%. 1배라 펀딩은 빼지 않는다
(약세장에서 숏은 보통 펀딩을 받거나 거의 안 낸다).
새 kind "pump" 로 지금 봇(ml/crash_window.py 설정)에 더해 taken 으로 지갑 전체를 돌린다.

격자: X {20, 30, 40}% × 보유 {5, 10}일 × 비중 {5, 10}% = 12개.
고르기는 ~2023 결과만, 2024~ 는 고른 뒤 한 번만. 이웃(±1칸) 모두 개선돼야 한다.

━━ 결과 (2026-10-15) — 기각 ━━
                         2017~  곡선낙폭  1년손실  2024~  거래/년  pump 승률·거래당
    지금 봇               36.3배  24.9%    1.5%    6.2배   187
    +40%·5일·5% (학습1등) 30.7배  24.9%    7.1%    6.6배   +5    43% · -7.2%
    +30%·5일·5% (이웃)    26.8배  24.9%    5.6%    6.0배   +14   51% · -3.7%
    +20%·5일·5%           24.2배  33.7%    4%      6.6배   +35   53% · -1.8%
  12개 전부 2017~ 가 지금보다 낮고 1년손실이 4~30% 로 늘어난다. 숏 거래 자체가
  거래당 -1.8~-8.1%(수수료 뒤)로 손해다. 약세장에서도 3일 +20~40% 급등한 코인은
  그 뒤 5~10일 더 오르거나 버티는 쪽이 많다(모멘텀). 숏 이익은 막혀 있고 손실은
  열려 있어 몇 번의 추가 급등이 전부 깎아 먹는다. 2021년(+136%)이 특히 깎인다
  (200일선 아래 구간의 알트 급등이 그대로 이어졌다).
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

GAPS = (20.0, 30.0, 40.0)
HOLDS = (5, 10)
SIZES = (0.05, 0.10)
FUND = 0.01


def make_pump(Dd, x, hold):
    b = Dd["BTCUSDT"].set_index("dt")["close"]
    bear = b < b.rolling(200).mean()
    out = []
    for s, d in Dd.items():
        d = d.set_index("dt")
        c = d["close"].astype(float); o = d["open"].astype(float).values; h = d["high"].astype(float).values
        r = (c / c.shift(3) - 1) * 100
        sig = (r >= x) & bear.reindex(c.index).fillna(False)
        idx = np.flatnonzero(sig.values); cv = c.values; dt = c.index
        n = len(cv); lock = -10**9
        for i in idx:
            if i <= lock or i + 1 + hold >= n:
                continue
            e = o[i + 1]
            out.append({"kind": "pump", "sym": s, "dt": pd.Timestamp(dt[i + 1]),
                        "exit": pd.Timestamp(dt[i + hold]), "entry": e, "exit_px": cv[i + hold],
                        "mae": -(h[i + 1:i + hold + 1].max() / e - 1) * 100, "deployed": 1.0,
                        "bars_h": hold * 24, "long": False})
            lock = i + hold
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
        pt = {"long": .015, "longb": .015, "short": .40, "div": .40, "pump": size}
        lv = {"long": 4.0, "longb": 2.0, "short": 1.0, "div": 1.0, "pump": 1.0}
        f = lambda X: taken(X, pt, lv)
        fin, mdd, got, c = f(tr); w = UP.windows(c)
        f19, _, _, c19 = f([t for t in tr if t["dt"] >= T19]); w19 = UP.windows(c19)
        a = f([t for t in tr if t["dt"] < TE])[0]; h = f([t for t in tr if t["dt"] >= TE])[0]
        y = c.resample("YE").last(); yr = ((y / y.shift(1).fillna(1) - 1) * 100)
        yrs = (c.index[-1] - c.index[0]).days / 365
        g4 = [x for x in got if x[0] == "pump"]
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
            D4 = cut(make_pump(Dd, gap, hold))
            for size in SIZES:
                R[(gap, hold, size)] = show(f"급등+{gap:g}%·{hold}일·{size*100:.0f}%", run(D4, size))

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
