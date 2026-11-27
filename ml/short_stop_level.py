"""
ml/short_stop_level.py — 주봉 숏 손절선(+X%) 비교 (2026-11-23, 사용자 요청). 방법은 short_take_profit.py 와 같다.
결과 (기준선 = 손절 +50%: 31.5배·곡선낙폭 25%·1년손실 9%·2024~ 5.79배, 숏 23건):
  손절 +25%  22.3배 / 2024~ 4.71 / 1년손실 12%  나빠짐 (정상 거래가 일찍 잘림: 5건 손절)
  손절 +30%  26.0배 / 4.80                      나빠짐
  손절 +35%  31.5배 / 5.79, 평균 +12.3%, 최악 -35%  통과 (지갑 결과 동일)
  손절 +40%  31.5배 / 5.79, 평균 +11.8%, 최악 -40%  통과 (동일)
  손절 +60·80%·없음  31.5배 / 5.79 (동일; 없음이면 최악 -46%, 평균 +12.0%)
  트레일25/12 + 손절 +40%·+50%  34.6배 / 5.79 / 통과, +30% 는 28.7배로 나빠짐
해석: 23건 중 +50% 닿은 것은 1건뿐이고 그 거래는 4주 끝에 -46%였다. 즉 +50% 손절은 이번 표본에서 -4%p 더 잃게
했을 뿐 지갑 결과는 같다. 35~40% 로 낮춰도 같은 결과이면서 최악이 -35~-40%. 30% 이하는 악화.
결론: 보류(사용자 판단). 후보는 +40% (지갑 동일, 최악 10%p 개선). 표본 1~2건이라 방향 확인용.
"""
import os, sys, warnings
warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import numpy as np, pandas as pd
import ml.tp_band_below_entry as T
import ml.unified_pool as UP, ml.short_setups as SS
import ml.module_winrate as MW
from bot.oversold import strategy as S
from bot.oversold import regime as REG
from ml.backtest_current_bot import load
from ml.per_coin_walkforward import MENU
from ml.per_coin_portfolio import to_up
from ml.bear_leverage import bear_series, is_on, T0, TE
from ml.crash_window import crash_hits, in_window


def make_short2(W, hold=4, tp=None, trail=None, stop=50.0):
    out = []
    for s, d in W.items():
        o, c, h, l, dt = (d[k].values for k in ("open", "close", "high", "low", "dt"))
        n = len(c); lock = -10**9
        for i in SS.setup_A(d, 60, 4):
            if i <= lock or i + 1 + hold >= n:
                continue
            e = o[i + 1]
            stop_lvl = e * (1 + stop / 100) if stop else None
            tp_lvl = e * (1 - tp / 100) if tp else None
            lowest = e
            ex_bar, ex_px, why = i + hold, c[i + hold], "time"
            for b in range(i + 1, i + 1 + hold):
                if stop_lvl is not None and h[b] >= stop_lvl:
                    ex_bar, ex_px, why = b, max(stop_lvl, o[b]), "stop"; break
                if trail and lowest <= e * (1 - trail[0] / 100):
                    lvl = lowest * (1 + trail[1] / 100)
                    if h[b] >= lvl:
                        ex_bar, ex_px, why = b, max(lvl, o[b]), "trail"; break
                lowest = min(lowest, l[b])
                if tp_lvl is not None and l[b] <= tp_lvl:
                    ex_bar, ex_px, why = b, min(tp_lvl, o[b]), "tp"; break
            out.append({"kind": "short", "sym": s, "dt": pd.Timestamp(dt[i + 1]),
                        "exit": pd.Timestamp(dt[ex_bar]), "entry": e, "exit_px": ex_px,
                        "mae": (1 - h[i + 1:ex_bar + 1].max() / e) * 100, "deployed": 1.0,
                        "bars_h": (ex_bar - i) * 24 * 7, "long": False, "why": why, "wk": ex_bar - i})
            lock = ex_bar
    return out


def main():
    Dd = {s: SS.load_daily(s) for s in S.SYMBOLS}
    Dd = {k: v for k, v in Dd.items() if v is not None and len(v) >= 400}
    W = {s: SS.to_weekly(d) for s, d in Dd.items()}
    # 점검: 변형 없이(손절 없음) 돌리면 기존 make_short 와 같아야 한다
    a, b = UP.make_short(W), make_short2(W, stop=None)
    assert len(a) == len(b) and all(abs(x["exit_px"] / y["exit_px"] - 1) < 1e-12 and x["dt"] == y["dt"]
                                    for x, y in zip(sorted(a, key=lambda t: (t["sym"], t["dt"])),
                                                    sorted(b, key=lambda t: (t["sym"], t["dt"])))), "make_short2 불일치"
    ma, th, hd, fr, ou, st = MENU["A 지금 봇"]
    G = {s: load(s) for s in S.SYMBOLS}
    G = {s: g for s, g in G.items() if g is not None and len(g) >= 400}
    cut = lambda X: [t for t in X if t["dt"] >= T0]
    Dv = cut(UP.make_div(Dd))
    btc = Dd["BTCUSDT"].set_index("dt")["close"]
    B = bear_series(btc, REG.AUTO_BEAR_ON, REG.AUTO_BEAR_OFF, REG.AUTO_BEAR_N)
    hits = crash_hits(G["BTCUSDT"].set_index("datetime")["close"].astype(float))
    bearf = lambda ts: is_on(B, ts) or in_window(hits, ts)
    T.UND["prev"], T.UND["nocond"], T.UND["act"] = True, False, (lambda ts: True)
    L = []
    for s, g in G.items():
        o, h, l, c = (g[q].astype(float).values for q in ("open", "high", "low", "close"))
        L += [to_up(t) for t in T.sim_u(o, h, l, c, g["datetime"].values, ma, th, hd, fr, ou, S.STOP_PCT, sym=s, step=st)]
    L = [dict(t, kind="longb") if bearf(t["dt"]) else t for t in cut(L)]
    lv = {"long": 4.0, "longb": 2.0, "short": 1.0, "div": 1.0}
    pt = {"long": .015, "longb": .015, "short": .40, "div": .40}

    def win(c):
        v = c.values
        return np.array([v[i + 365] / v[i] for i in range(0, len(c) - 365, 15)])

    def run(lab, **kw):
        Sh = cut(make_short2(W, **kw))
        tr = L + Sh + Dv
        fin, mdd, got, c = MW.taken(tr, pt, lv)
        a = MW.taken([t for t in tr if t["dt"] < TE], pt, lv)[0]
        h = MW.taken([t for t in tr if t["dt"] >= TE], pt, lv)[0]
        y = c.resample("YE").last(); yr = ((y / y.shift(1).fillna(1) - 1) * 100)
        ret = np.array([(1 - t["exit_px"] / t["entry"]) * 100 - 0.40 for t in Sh])
        r = dict(fin=fin, cdd=float((1 - c / c.cummax()).max() * 100), l1=(win(c) < 1).mean() * 100, a=a, h=h)
        why = pd.Series([t["why"] for t in Sh]).value_counts().to_dict()
        print(f"{lab:<22}{fin:>6.1f}배 곡선{r['cdd']:>4.0f}% 1년손실{r['l1']:>3.0f}% ~2023 {a:>5.1f}배 2024~ {h:>5.2f}배 | "
              f"숏 {len(Sh)}건 승률 {np.mean(ret > 0)*100:.0f}% 평균 {ret.mean():+.1f}% 최악 {ret.min():+.0f}% 최고 {ret.max():+.0f}% {why}",
              flush=True)
        return r

    base = run("손절 +50% (지금)")
    R = {}
    for st in (25, 30, 35, 40, 60, 80, None):
        R[f"손절 {st}"] = run(f"손절 +{st}%" if st else "손절 없음", stop=st)
    for st in (30, 40, 50):
        R[f"트레일25/12+손절{st}"] = run(f"트레일25/12 + 손절 +{st}%", trail=(25, 12), stop=st)
    print()
    for k, r in R.items():
        bad = [f"{nm} {base[key]:.1f}→{r[key]:.1f}" for key, nm, sg in
               (("fin", "2017~", 1), ("h", "2024~", 1), ("cdd", "곡선낙폭", -1), ("l1", "1년손실", -1))
               if (r[key] - base[key]) * sg < -1e-9]
        print(f"  {k}: {'통과' if not bad else '나빠짐 ' + ', '.join(bad)}")


if __name__ == "__main__":
    main()
