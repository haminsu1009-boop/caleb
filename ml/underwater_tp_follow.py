"""
ml/underwater_tp_follow.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
많이 물린 롱의 익절 목표를 "볼린저 상단"이 아니라 "현재가 근처"로 끌어내리면 나아지나 (2026-11-22, 사용자 요청)

배경: 급락 중에는 20봉 표준편차가 커져서 볼린저 상단이 잘 안 내려온다(APT 11/18~19:
평균 0.4526→0.4401로 내려가는 동안 표준편차 0.009→0.015, 상단 0.466→0.462). 그래서 익절 목표가
현재가보다 20~30% 위에 남는다. 사용자가 "손실을 줄이려면 목표가 내려와야 하는 것 아니냐"고 물었다.

변형: 직전 봉 종가가 평단보다 U% 넘게 아래인 동안(그 봉이 닫힌 뒤부터), 익절 목표를
(직전 봉 종가 × (1 + M%)) 에 건다(지정가). 고가가 닿으면 그 가격(시가가 더 높으면 시가)에 체결.
평단 아래에서 닫히므로 손실이 확정된다. 그 밖의 정상 익절(상단 > 평단)·손절·시간청산은 그대로다.
격자: U {8, 12, 16}% × M {5, 10}% = 6개. 판정: 지갑 전체에서 2017~ · 2024~ · 곡선낙폭 ·
1년손실이 모두 지금 이상. 학습 ~2023 / 검증 2024~.
(앞서 시험한 ml/underwater_exit.py 는 "K봉 뒤 평단-X% 에 청산"이었고 기각됐다. 이번에는 목표가
평단이 아니라 움직이는 현재가에 붙는다.)

━━ 결과 ━━
기각 (2026-11-22) — 12개 변형 중 네 지표를 모두 지키는 것이 없다.
[전체 거래에 적용]  (2017~ / 곡선낙폭 / 1년손실 / 2024~ / 반등탈출 비율)
    지금 봇              37.2배 25%  2%  6.39배
    평단-8%↓ 현재가+5%   25.3배 28%  6%  5.90배  461/2068
    평단-8%↓ 현재가+10%  31.9배 24%  5%  6.31배  238/1934   ← 학습 1등
    평단-12%↓ 현재가+5%  18.5배 27% 21%  6.10배
    평단-12%↓ 현재가+10% 30.3배 25%  6%  6.29배
    평단-16%↓ 현재가+5%  24.9배 27% 17%  6.43배
    평단-16%↓ 현재가+10% 31.8배 25%  6%  6.32배
[폭락장·급락 때 들어간 롱(2배)에만 적용]
    폭락장만 -8%↓ +5%   34.4배 28%  8%  6.43배
    폭락장만 -8%↓ +10%  32.6배 25%  3%  6.37배
    폭락장만 -12%↓ +10% 32.4배 25%  3%  6.37배
    폭락장만 -12%↓ +5%  26.7배 25% 14%  6.38배
  연도별로 보면 하락장(2022 +21→+31, 2025 +165→+172)에는 도움이 되고 반등장(2021 +136→+76~129,
  2019 등)에는 손해다. 급락 중에 목표를 현재가에 붙이면 하락장 손실은 줄지만, 곧 반등할 거래의
  이익도 같이 잘라서 평균은 나빠진다. ml/underwater_exit.py(평단-X% 청산) 와 같은 결론이다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import os, sys, inspect, warnings
warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import numpy as np, pandas as pd
from bot.oversold import strategy as S
from bot.oversold import regime as REG
import ml.unified_pool as UP, ml.short_setups as SS
import ml.module_winrate as MW
import ml.per_coin_rules as PCR
from ml.backtest_current_bot import load
from ml.per_coin_walkforward import MENU
from ml.per_coin_portfolio import to_up
from ml.bear_leverage import bear_series, is_on, T0, TE
from ml.crash_window import crash_hits, in_window

# per_coin_rules.sim 을 복사해 "K봉 뒤 평단×(1−X%) 지정가 청산"을 끼운다.
_src = inspect.getsource(PCR.sim).replace("def sim(", "def sim_u(")
_hook = '''            if left <= 1e-9:
                ex_bar, reason = bar, "tp"; break
'''
_new = _hook + '''            if UND["u"] is not None and und_on and bar >= i + 2 and c[bar - 1] <= avg * (1 - UND["u"] / 100):
                lvl = c[bar - 1] * (1 + UND["m"] / 100)
                if h[bar] >= lvl:
                    sold.append((left, max(lvl, o[bar]))); left = 0.0
                    ex_bar, reason = bar, "und"; break
'''
_avg_line = "        avg = e1\n"
assert _src.count(_avg_line) == 1
_src = _src.replace(_avg_line, _avg_line + "        und_on = UND['act'](pd.Timestamp(dt[i + 1]))\n")
assert _src.count(_hook) == 1
_src = _src.replace(_hook, _new)
UND = {"u": None, "m": 0.0, "act": lambda ts: True}
_ns = dict(PCR.__dict__); _ns["UND"] = UND
exec(_src, _ns); sim_u = _ns["sim_u"]


def main():
    Dd = {s: SS.load_daily(s) for s in S.SYMBOLS}
    Dd = {k: v for k, v in Dd.items() if v is not None and len(v) >= 400}
    W = {s: SS.to_weekly(d) for s, d in Dd.items()}
    ma, th, hd, fr, ou, st = MENU["A 지금 봇"]
    G = {}
    for s in S.SYMBOLS:
        g = load(s)
        if g is not None and len(g) >= 400:
            G[s] = g
    cut = lambda X: [t for t in X if t["dt"] >= T0]
    Sh, Dv = cut(UP.make_short(W)), cut(UP.make_div(Dd))
    btc = Dd["BTCUSDT"].set_index("dt")["close"]
    B = bear_series(btc, REG.AUTO_BEAR_ON, REG.AUTO_BEAR_OFF, REG.AUTO_BEAR_N)
    hits = crash_hits(G["BTCUSDT"].set_index("datetime")["close"].astype(float))
    lv = {"long": 4.0, "longb": 2.0, "short": 1.0, "div": 1.0}
    pt = {"long": .015, "longb": .015, "short": .40, "div": .40}

    def win(c):
        v = c.values
        return np.array([v[i + 365] / v[i] for i in range(0, len(c) - 365, 15)])

    def run(lab, u, m, bear_only=False):
        UND["u"], UND["m"] = u, m
        UND["act"] = (lambda ts: is_on(B, ts) or in_window(hits, ts)) if bear_only else (lambda ts: True)
        L, reasons = [], []
        for s, g in G.items():
            o, h, l, c = (g[q].astype(float).values for q in ("open", "high", "low", "close"))
            ts = sim_u(o, h, l, c, g["datetime"].values, ma, th, hd, fr, ou, S.STOP_PCT, sym=s, step=st)
            for t in ts:
                u = to_up(t); u["reason"] = t["reason"]; L.append(u)
        L = cut(L)
        tr = [dict(t, kind="longb") if (is_on(B, t["dt"]) or in_window(hits, t["dt"])) else t
              for t in L] + Sh + Dv
        fin, mdd, got, c = MW.taken(tr, pt, lv)
        a = MW.taken([t for t in tr if t["dt"] < TE], pt, lv)[0]
        h = MW.taken([t for t in tr if t["dt"] >= TE], pt, lv)[0]
        y = c.resample("YE").last(); yr = ((y / y.shift(1).fillna(1) - 1) * 100)
        nu = sum(1 for t in L if t.get("reason") == "und")
        r = dict(fin=fin, cdd=float((1 - c / c.cummax()).max() * 100), l1=(win(c) < 1).mean() * 100,
                 a=a, h=h, n=len(got), nu=nu, nl=len(L),
                 yr={d.year: v for d, v in yr.items()})
        print(f"{lab:<18}{fin:>6.1f}배 곡선{r['cdd']:>4.0f}% 1년손실{r['l1']:>3.0f}% ~2023 {a:>5.1f}배 "
              f"2024~ {h:>5.2f}배 반등탈출 {nu}/{len(L)}건 | "
              + " ".join(f"{d%100}:{v:+.0f}" for d, v in r["yr"].items() if d >= 2018), flush=True)
        return r

    base = run("지금 봇", None, 0.0)
    if "--bear" in sys.argv:
        print("\n[폭락장·급락 때 들어간 롱에만 적용]")
        for u, m in ((8.0, 5.0), (8.0, 10.0), (12.0, 10.0), (12.0, 5.0)):
            r = run(f"폭락장만 -{u:g}%↓ +{m:g}%", u, m, bear_only=True)
            bad = [f"{nm} {base[key]:.1f}→{r[key]:.1f}" for key, nm, sg in
                   (("fin", "2017~", 1), ("h", "2024~", 1), ("cdd", "곡선낙폭", -1), ("l1", "1년손실", -1))
                   if (r[key] - base[key]) * sg < -1e-9]
            print("     ", "통과" if not bad else "나빠짐 " + ", ".join(bad))
        return
    R = {}
    for u in (8.0, 12.0, 16.0):
        for m in (5.0, 10.0):
            R[(u, m)] = run(f"평단-{u:g}%↓ 현재가+{m:g}%", u, m)
    best = max(R, key=lambda q: R[q]["a"])
    print(f"\n학습(~2023) 1등: {best}")
    for q in [best] + [q for q in R if q != best]:
        r = R[q]; bad = []
        for key, nm, sg in (("fin", "2017~", 1), ("h", "2024~", 1), ("cdd", "곡선낙폭", -1), ("l1", "1년손실", -1)):
            if (r[key] - base[key]) * sg < -1e-9:
                bad.append(f"{nm} {base[key]:.1f}→{r[key]:.1f}")
        print(f"  {'1등' if q == best else '   '} {q}: {'통과' if not bad else '나빠짐 ' + ', '.join(bad)}")


if __name__ == "__main__":
    main()
