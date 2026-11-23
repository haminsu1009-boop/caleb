"""
ml/activity_filter.py — 거래대금·변동성으로 롱 신호를 거르면 나아지나 (2026-11-24, 웹 검색 아이디어)
출처: Günther·Fieberg·Poddig 2020(1,200종, 단기 반전이 가장 강한 특성), Riksbank WP 413 / CERGE-EI WP 730
(반전 수익은 거래가 한산한 쌍에 몰림), Lee·Wang 2024 JFQA(분산 큰 코인은 이후 수익이 낮음).
가설: 과매도 롱 수익은 한산한 코인(거래대금 낮음)에서 더 크다 / 변동성 큰 코인에서 더 작다.
방법: 롱 신호 시점 직전 30일 평균 거래대금·실현변동성을 42종 안에서 순위로 3등분. 신호 수준 표 +
(상위 1/3 건너뛰기, 하위 1/3 건너뛰기)를 지갑에 넣어 비교. 롱은 실거래와 같은 직전 봉 밴드 기준 31.5배 기준선.
판정: 2017~ · 2024~ · 곡선낙폭 · 1년손실 모두 기준선 이상, 학습 ~2023 / 검증 2024~.
결과 (기준선 31.5배·곡선낙폭 25%·1년손실 9%·~2023 5.4배·2024~ 5.79배, 롱 1812건):
  신호 수준: 거래대금 하위1/3 평균 ~2023 +7.3%·2024~ +8.4%, 중간 +3.9%·+7.1%, 상위1/3 +5.3%·+9.1% → 방향이 학습/검증에서 뒤집힘
            (학습에선 한산한 쪽이 낫고 검증에선 붐비는 쪽이 낫다). 변동성은 낮을수록 2024~ 약간 낫지만 ~2023엔 반대.
  지갑: 거래대금 상위1/3 제외 13.2배 / 하위1/3 제외 7.0배 / 변동성 상위1/3 제외 8.2배 / 하위1/3 제외 14.9배 — 4개 모두 전 지표 악화.
결론: 기각. 논문의 '한산한 코인에서 반전이 크다'는 우리 데이터에서 일관되지 않고, 어느 쪽을 걸러도 거래 수가 줄어
      복리·분산이 깨져 지갑이 크게 나빠진다. 거래대금·변동성은 신호를 거르는 기준이 못 된다.
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


def main():
    Dd = {s: SS.load_daily(s) for s in S.SYMBOLS}
    Dd = {k: v for k, v in Dd.items() if v is not None and len(v) >= 400}
    ma, th, hd, fr, ou, st = MENU["A 지금 봇"]
    G = {s: load(s) for s in S.SYMBOLS}
    G = {s: g for s, g in G.items() if g is not None and len(g) >= 400}
    cut = lambda X: [t for t in X if t["dt"] >= T0]
    Dv = cut(UP.make_div(Dd))
    Sh = cut(UP.make_short(  {s: SS.to_weekly(d) for s, d in Dd.items()} ))
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

    # 활동·변동성 순위 (직전 30일, 하루 지연 — 신호 시점에 이미 아는 값)
    V, R = {}, {}
    for s, g in G.items():
        x = g.set_index("datetime")
        qv = x["quote_volume"].astype(float).resample("1D").sum()
        V[s] = qv.rolling(30).mean().shift(1)
        r = x["close"].astype(float).resample("1D").last().pct_change()
        R[s] = r.rolling(30).std().shift(1)
    V, R = pd.DataFrame(V), pd.DataFrame(R)
    Vr, Rr = V.rank(axis=1, pct=True), R.rank(axis=1, pct=True)
    for t in L:
        d = pd.Timestamp(t["dt"]).floor("1D")
        t["vr"] = Vr.at[d, t["sym"]] if d in Vr.index else np.nan
        t["rr"] = Rr.at[d, t["sym"]] if d in Rr.index else np.nan

    lv = {"long": 4.0, "longb": 2.0, "short": 1.0, "div": 1.0}
    pt = {"long": .015, "longb": .015, "short": .40, "div": .40}
    net = lambda t: (t["exit_px"] / t["entry"] - 1) * 100 - 0.40

    def win(c):
        v = c.values
        return np.array([v[i + 365] / v[i] for i in range(0, len(c) - 365, 15)])

    def run(lab, keep=lambda t: True):
        Lk = [t for t in L if keep(t)]
        tr = Lk + Sh + Dv
        fin, mdd, got, c = MW.taken(tr, pt, lv)
        a = MW.taken([t for t in tr if t["dt"] < TE], pt, lv)[0]
        h = MW.taken([t for t in tr if t["dt"] >= TE], pt, lv)[0]
        r = dict(fin=fin, cdd=float((1 - c / c.cummax()).max() * 100), l1=(win(c) < 1).mean() * 100, a=a, h=h)
        print(f"{lab:<28}{len(Lk):>5}건 {fin:>6.1f}배 곡선{r['cdd']:>4.0f}% 1년손실{r['l1']:>3.0f}% ~2023 {a:>5.1f}배 2024~ {h:>5.2f}배", flush=True)
        return r

    print("신호 수준 (롱, 수수료 후 거래당 수익, 승률): 기준 = 42종 안 순위")
    for nm, key in (("거래대금", "vr"), ("변동성", "rr")):
        for per, f in (("~2023", lambda t: t["dt"] < TE), ("2024~", lambda t: t["dt"] >= TE)):
            row = []
            for lab, lo, hi in (("하위1/3", 0, 1 / 3), ("중간", 1 / 3, 2 / 3), ("상위1/3", 2 / 3, 1.01)):
                x = [net(t) for t in L if f(t) and lo <= t[key] < hi]
                row.append(f"{lab} {len(x)}건 승률 {np.mean(np.array(x) > 0)*100:.0f}% 평균 {np.mean(x):+.1f}%" if x else f"{lab} 0건")
            print(f"  {nm:<5}{per:<6}" + " | ".join(row))
    print()
    base = run("지금 규칙")
    R_ = {}
    for nm, key in (("거래대금", "vr"), ("변동성", "rr")):
        R_[f"{nm} 상위1/3 제외"] = run(f"{nm} 상위1/3 제외", lambda t, k=key: not (t[k] >= 2 / 3))
        R_[f"{nm} 하위1/3 제외"] = run(f"{nm} 하위1/3 제외", lambda t, k=key: not (t[k] < 1 / 3))
    print()
    for k, r in R_.items():
        bad = [f"{nm} {base[key]:.1f}→{r[key]:.1f}" for key, nm, sg in
               (("fin", "2017~", 1), ("h", "2024~", 1), ("cdd", "곡선낙폭", -1), ("l1", "1년손실", -1))
               if (r[key] - base[key]) * sg < -1e-9]
        print(f"  {k}: {'통과' if not bad else '나빠짐 ' + ', '.join(bad)}")


if __name__ == "__main__":
    main()
