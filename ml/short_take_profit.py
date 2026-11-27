"""
ml/short_take_profit.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
주봉 숏에 익절을 넣으면 나아지나 (2026-11-22, 사용자 요청)

지금 숏: 신호 다음 주봉 시가에 진입해서 4주 뒤 종가에 청산한다. 익절 없음, 손절은 진입가 +50%.
(봇은 `modules.py`, 백테스트는 `ml/unified_pool.py` 의 `make_short`.)

변형 (주봉이라 봉 안 순서를 모르므로 불리한 쪽으로 가정: 한 봉에서 손절과 익절이 같이 닿으면 손절,
트레일링은 직전 봉까지의 저점 기준):
  고정 익절  진입가 대비 가격이 X% 내려가면 청산 (X ∈ 10·15·20·30%)
  트레일링   진입가 대비 A% 내려간 뒤, 저점에서 R% 되돌려 오르면 청산 ((A,R) ∈ (15,8)·(15,12)·(25,8)·(25,12))
모두 손절 +50%·시간청산 4주는 그대로다. 기준선 = 지금 규칙(손절 +50% 포함)이고, 롱은 실거래와 같은
직전 봉 밴드 기준(ml/tp_band_below_entry.py)으로 한 번만 계산해 같이 쓴다.
판정: 지갑 전체에서 2017~ · 2024~ · 곡선낙폭 · 1년손실이 모두 기준선 이상. 숏 신호가 23건뿐이라
어떤 결과도 표본이 작다.

━━ 결과 ━━
기준선(지금 규칙): 31.5배 · 곡선낙폭 25% · 1년손실 9% · ~2023 5.4배 · 2024~ 5.79배 (숏 23건, 승률 83%, 평균 +11.8%)
  익절 10%      22.3배 / 2024~ 5.26  → 나빠짐 (수익을 너무 일찍 자름)
  익절 15%      28.7배 / 5.73        → 나빠짐
  익절 20%      31.8배 / 5.93        → 통과(근소: +1%)
  익절 30%      30.4배 / 5.52        → 나빠짐
  트레일 15/8   23.8배 / 4.52        → 나빠짐
  트레일 15/12  25.8배 / 4.79        → 나빠짐
  트레일 25/8   34.0배 / 5.79        → 통과(+8%)
  트레일 25/12  34.6배 / 5.79        → 통과(+10%)
결론: 보류. 통과한 3개는 차이가 작고(23건 표본), 이웃 값(15%·30%·트레일 15)은 모두 나빠져서 값이 조금만
움직여도 결과가 뒤집힌다 = 우연일 가능성이 큼. 9개를 본 뒤 고른 것이라 사후 선택 위험도 있다.
곡선낙폭·1년손실은 전 변형이 기준선과 같다(숏이 낙폭을 만드는 구간이 아님).
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
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

    base = run("지금 규칙(손절+50%)")
    R = {}
    for x in (10, 15, 20, 30):
        R[f"익절 {x}%"] = run(f"익절 {x}%", tp=x)
    for A, Rr in ((15, 8), (15, 12), (25, 8), (25, 12)):
        R[f"트레일 {A}/{Rr}"] = run(f"트레일링 {A}%↓ 후 {Rr}%↑", trail=(A, Rr))
    print()
    for k, r in R.items():
        bad = [f"{nm} {base[key]:.1f}→{r[key]:.1f}" for key, nm, sg in
               (("fin", "2017~", 1), ("h", "2024~", 1), ("cdd", "곡선낙폭", -1), ("l1", "1년손실", -1))
               if (r[key] - base[key]) * sg < -1e-9]
        print(f"  {k}: {'통과' if not bad else '나빠짐 ' + ', '.join(bad)}")


if __name__ == "__main__":
    main()
