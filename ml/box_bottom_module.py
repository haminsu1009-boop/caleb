"""
ml/box_bottom_module.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
횡보장 박스권 하단 매수 — RESEARCH_AGENDA 마지막 후보 (2026-10-18)

10-06 sideways_long.py 는 "횡보장에서 지금 롱을 끄기·줄이기·깊게"였다. 이건 다른 진입이다.
신호(일봉 마감, 신호일까지의 데이터만):
  · 횡보장: BTC 60일 수익률 -5% ~ +5% (신호일 종가 기준)
  · 박스: 코인의 직전 30일 고저 폭 (고-저)/저 ≤ R
  · 하단: 신호일 종가가 박스 하단 10% 안 (종가 ≤ 저 + 0.1×(고-저)), 박스 저점 위
다음날 시가에 롱 2배. 청산: 종가가 박스 중간 이상이면 그날 종가, 저가가 박스 저점 −5% 를
닿으면 그 값(시가가 이미 아래면 시가), 아니면 hold 일 뒤 종가. 같은 코인 보유 중 재진입 없음
(지금 롱과 코인 자리 공유). 수수료 0.40% + 펀딩(2배라 net()이 뺀다).
새 kind "box" 로 지금 봇(ml/crash_window.py 설정)에 더해 taken 으로 지갑 전체를 돌린다.

격자: R {20, 30, 40}% × 보유 {7, 14}일 × 비중 {1, 2}% = 12개.
고르기는 ~2023 결과만, 2024~ 는 고른 뒤 한 번만. 이웃(±1칸) 모두 개선돼야 한다.

━━ 결과 (2026-10-18) — 기각 ━━
                         2017~  곡선낙폭  1년손실  2024~  거래/년  box 승률·거래당  2022
    지금 봇               36.3배  24.9%    1.5%    6.2배   187                    +21%
    ≤20%·7일·2% (학습1등) 36.4배  24.9%    2%      6.2배    +4    49% · +0.8%      +21%
    ≤30%·7일·2% (이웃)    21.6배  35.2%   14.7%    6.1배   +16    34% · −1.0%      −25%
    ≤40%·7일·1%           19.4배  34.7%   11%      5.3배   +32    38% · −0.9%      −24%
  좁은 박스(≤20%)는 신호가 연 4건뿐이라 지금과 같다(효과 없음). 박스를 넓히면 거래는
  늘지만 승률 32~38%·거래당 손해다. 특히 2022년 횡보 뒤 하락(박스 하단 이탈)에서 크게
  잃는다(+21→−25%). 박스 하단은 지지선이 아니라 이탈 직전 자리인 경우가 많았다.
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
HOLDS = (7, 14)
SIZES = (0.01, 0.02)
FUND = 0.01


def make_box(Dd, R, hold, N=30):
    b = Dd["BTCUSDT"].set_index("dt")["close"]
    r60 = (b / b.shift(60) - 1) * 100
    side = (r60 >= -5) & (r60 <= 5)                     # 신호일 종가 기준
    out = []
    for s, d in Dd.items():
        d = d.set_index("dt")
        o, h, l, c = (d[k].astype(float).values for k in ("open", "high", "low", "close"))
        hi = pd.Series(h).rolling(N).max().values; lo = pd.Series(l).rolling(N).min().values
        sd = side.reindex(d.index).fillna(False).values
        dt = d.index; n = len(c); lock = -10**9
        for i in range(N, n - 1):
            if i <= lock or not sd[i]:
                continue
            H, Lo = hi[i], lo[i]
            if not (Lo > 0 and (H - Lo) / Lo * 100 <= R):
                continue
            if not (Lo < c[i] <= Lo + 0.1 * (H - Lo)):
                continue
            if i + 1 + hold >= n:
                continue
            e = o[i + 1]; mid = (H + Lo) / 2; stop = Lo * 0.95
            j, xp = i + hold, c[i + hold]
            for k in range(i + 1, i + hold + 1):
                if l[k] <= stop:
                    j, xp = k, min(o[k], stop) if k > i + 1 else min(e, stop); break
                if c[k] >= mid:
                    j, xp = k, c[k]; break
            out.append({"kind": "box", "sym": s, "dt": pd.Timestamp(dt[i + 1]),
                        "exit": pd.Timestamp(dt[j]), "entry": e, "exit_px": xp,
                        "mae": max((l[i + 1:j + 1].min() / e - 1) * 100, (stop / e - 1) * 100 - 0.5),
                        "deployed": 1.0, "bars_h": (j - i) * 24, "long": True})
            lock = j
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
        pt = {"long": .015, "longb": .015, "short": .40, "div": .40, "box": size}
        lv = {"long": 4.0, "longb": 2.0, "short": 1.0, "div": 1.0, "box": 2.0}
        f = lambda X: taken(X, pt, lv)
        fin, mdd, got, c = f(tr); w = UP.windows(c)
        f19, _, _, c19 = f([t for t in tr if t["dt"] >= T19]); w19 = UP.windows(c19)
        a = f([t for t in tr if t["dt"] < TE])[0]; h = f([t for t in tr if t["dt"] >= TE])[0]
        y = c.resample("YE").last(); yr = ((y / y.shift(1).fillna(1) - 1) * 100)
        yrs = (c.index[-1] - c.index[0]).days / 365
        g4 = [x for x in got if x[0] == "box"]
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
            D4 = cut(make_box(Dd, gap, hold))
            for size in SIZES:
                R[(gap, hold, size)] = show(f"박스≤{gap:g}%·{hold}일·{size*100:.0f}%", run(D4, size))

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
