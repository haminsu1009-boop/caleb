"""
ml/underwater_exit.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
물린 롱에 "평단 아래 반등 탈출"을 허용하면 손실이 줄고 전체 성적이 나아지나 (2026-11-21, 사용자 요청)

지금 규칙: 볼린저 상단이 평단 아래면 익절을 걸지 않는다(`take_profit_price` 가 None).
그래서 평단보다 한참 아래에 있는 포지션은 -40% 손절(4배는 사실상 청산 -24.5%) 또는
60봉(10일) 시간청산까지 기다리기만 한다. 사용자가 "손절까지 기다리기만 하는 건 아니지 않나"고 물었다.

변형: 보유 K봉이 지나도 익절이 안 됐으면, 평단 × (1 − X%) 에 지정가 청산을 건다
(고가가 닿으면 그 가격에 체결, 그 봉 시가가 더 높으면 시가). 정상 익절(볼린저 상단 > 평단)과
손절은 그대로다. 격자: K {18, 30}봉 × X {2, 5, 8}% = 6개.
판정: 지갑 전체(폭락장·급락 2배, 숏·다이버 40%, 증거금 95%)에서 2017~ · 2024~ · 곡선낙폭 ·
1년손실이 모두 지금 이상. 학습 ~2023 / 검증 2024~.

━━ 결과 ━━
기각 (2026-11-21) — 6개 변형 전부 4개 지표가 모두 나빠진다.
                          2017~  곡선낙폭  1년손실  ~2023  2024~  반등탈출 비율
    지금 봇                37.2배   25%      2%     5.8배  6.39배      –
    18봉 뒤 평단-2%        15.8배   38%     19%     2.6배  5.98배   1017/1916 (53%)
    18봉 뒤 평단-5%        14.8배   39%     22%     2.5배  5.94배   1049/1933
    18봉 뒤 평단-8%        14.4배   40%     21%     2.4배  5.92배   1077/1948
    30봉 뒤 평단-2% (학습1등) 27.0배   35%      6%     4.2배  6.31배    448/1842 (24%)
    30봉 뒤 평단-5%        25.4배   35%      2%     4.0배  6.25배    485/1849
    30봉 뒤 평단-8%        19.3배   34%     11%     3.0배  6.34배    508/1858
  이유: 물린 거래를 평단 근처에서 일찍 닫으면 작은 손실이 확정되고, 규칙대로 두면 평단 위
  볼린저 상단까지 올라가 이익으로 끝났을 거래의 반등을 포기한다. 18봉 변형은 거래의 절반 이상이
  반등 탈출로 닫히고, 자본이 일찍 풀려 폭락장에 진입이 더 몰려 낙폭도 커진다(25→34~40%).
  이전에 시험한 손절 -15~-22%·시간청산 3~166일과 같은 결론이다.
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
_new = _hook + '''            if UND["k"] is not None and bar - (i + 1) >= UND["k"]:
                lvl = avg * (1 - UND["x"] / 100)
                if h[bar] >= lvl:
                    sold.append((left, max(lvl, o[bar]))); left = 0.0
                    ex_bar, reason = bar, "und"; break
'''
assert _src.count(_hook) == 1
_src = _src.replace(_hook, _new)
UND = {"k": None, "x": 0.0}
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

    def run(lab, k, x):
        UND["k"], UND["x"] = k, x
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
    R = {}
    for k in (18, 30):
        for x in (2.0, 5.0, 8.0):
            R[(k, x)] = run(f"{k}봉 뒤 평단-{x:g}%", k, x)
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
