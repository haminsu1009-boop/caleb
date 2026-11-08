"""
ml/max_momentum_module.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MAX 모멘텀 롱 모듈 (2026-11-09, RESEARCH_AGENDA "웹 검색으로 새 후보")

근거: 주식은 "최대 일간 수익률(MAX)이 큰 종목이 다음에 부진"(복권 효과)인데,
코인은 반대로 MAX가 큰 코인이 다음 주에 더 오른다는 연구가 여럿 있다
(Grobys·Junttila 2021, Özdamar 외 2021, Lin 외 2021 — 최저/최고 MAX 5분위
차이 주 1.5% 이상, BTC 위험 통제 뒤에도 유지). 누적 수익률 모멘텀
(ml/xs_momentum_module.py, 기각)과 달리 "하루 급등" 하나를 본다.

규칙: 매주 월요일 주봉 마감 때 지난 L주 동안의 최대 일간 수익률(종가/전일종가)로
42종을 줄 세워 상위 K개를 다음날 시가에 1배 롱, 1주 보유. 나머지는 xs_momentum과
같다(수수료 0.40%, 펀딩 0.01%/8h, 과매도 롱과 같은 코인이면 건너뜀).
격자: L {1,2,4}주 × K {3,5} × 비중 {5,10}% = 12개. 고르기는 ~2023만.

━━ 결과 ━━
기각 (2026-11-09)
                          2017~  곡선낙폭  1년손실  ~2023  2024~  MAX 승률·거래당   2022   2025
    지금 봇                36.6배  24.9%    2%     5.8배  6.3배        –          +21%  +165%
    2주·상위5·10% (학습1등)  47.0배  66.1%   26%    29.5배 1.6배    44% · +1.4%     −43%    +8%
    4주·상위3·5%            39.9배  35.4%   23%     8.9배 4.5배    44% · +1.7%     −23%   +79%
    2주·상위3·5%            30.1배  30.7%   26%     6.3배 4.7배    44% · +1.5%     −24%   +93%
  12개 전부 곡선낙폭 31~71%, 1년손실 23~44%, 2024~ 1.3~4.7배(지금 6.3) — 전부 나빠진다.
  거래당 +0.8~1.8%로 양수지만 승률 43~45%이고, 수익은 2021(+149~1368%)에 몰리고
  2018·2022에 크게 잃는다. 누적 모멘텀(xs_momentum)과 같은 실패 양상이다.
  논문의 주 1.5% 차이는 수천 종(소형 코인 포함)·롱숏 기준이라 42종 롱만·수수료
  0.40%에선 남지 않는다.
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
import ml.divergence_scoped as DS
from ml.backtest_current_bot import load
from ml.per_coin_rules import sim
from ml.per_coin_walkforward import MENU
from ml.per_coin_portfolio import to_up
from ml.module_winrate import taken
from ml.bear_leverage import bear_series, is_on, T0, T19, TE
from ml.crash_window import crash_hits, in_window

GAPS = (1, 2, 4)        # MAX 룩백 주
HOLDS = (3, 5)          # 상위 K
SIZES = (0.05, 0.10)
FUND = 0.01


def make_div4(W, look, k, Dd=None):
    """W: {sym: 주봉}. 이름은 div4h_module 틀을 재사용해서 그대로 둔다(kind='div4')."""
    C = pd.DataFrame({s: w.set_index("dt")["close"] for s, w in W.items()})
    O = pd.DataFrame({s: w.set_index("dt")["open"] for s, w in W.items()})
    L_ = pd.DataFrame({s: w.set_index("dt")["low"] for s, w in W.items()})
    idx = C.index; out = []
    DC = pd.DataFrame({s: d.set_index("dt")["close"] for s, d in Dd.items()})
    dmax = (DC / DC.shift(1) - 1).rolling(7 * look, min_periods=5 * look).max()
    R = dmax.reindex(idx, method="ffill")
    for i in range(look, len(idx) - 2):
        r = R.iloc[i].dropna()
        r = r.nlargest(k)
        for s in r.index:
            e = O[s].iloc[i + 1]; x = C[s].iloc[i + 1]
            if not (np.isfinite(e) and np.isfinite(x)) or e <= 0:
                continue
            x *= (1 - FUND / 100 * 21)
            out.append({"kind": "div4", "sym": s, "dt": idx[i] + pd.Timedelta(days=1),
                        "exit": idx[i + 1] + pd.Timedelta(days=1), "entry": e, "exit_px": x,
                        "mae": (L_[s].iloc[i + 1] / e - 1) * 100, "deployed": 1.0,
                        "bars_h": 7 * 24, "long": True})
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
        pt = {"long": .015, "longb": .015, "short": .40, "div": .40, "div4": size}
        lv = {"long": 4.0, "longb": 2.0, "short": 1.0, "div": 1.0, "div4": 1.0}
        f = lambda X: taken(X, pt, lv)
        fin, mdd, got, c = f(tr); w = UP.windows(c)
        f19, _, _, c19 = f([t for t in tr if t["dt"] >= T19]); w19 = UP.windows(c19)
        a = f([t for t in tr if t["dt"] < TE])[0]; h = f([t for t in tr if t["dt"] >= TE])[0]
        y = c.resample("YE").last(); yr = ((y / y.shift(1).fillna(1) - 1) * 100)
        yrs = (c.index[-1] - c.index[0]).days / 365
        g4 = [x for x in got if x[0] == "div4"]
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
            D4 = cut(make_div4(W, gap, hold, Dd))
            for size in SIZES:
                R[(gap, hold, size)] = show(f"{gap}주·상위{hold}·{size*100:.0f}%", run(D4, size))

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
