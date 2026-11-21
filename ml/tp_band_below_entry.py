"""
ml/tp_band_below_entry.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
볼린저 상단이 평단 아래로 내려오면 익절 목표도 평단 아래로 내린다 (2026-11-22, 사용자 요청)

지금 규칙: 상단이 평단 아래면 익절을 걸지 않는다(`take_profit_price` 가 None, 백테스트의
`up > avg`). 변형: 이 조건을 없앤다. 즉 익절 목표는 언제나 볼린저 상단(20봉, 1.5σ)이고,
상단이 평단 아래면 가격이 거기까지 반등할 때 손실을 안고 청산한다.

밴드 기준 두 가지로 돈다.
  같은 봉   baseline 시뮬레이터 규칙(그 봉 종가까지 넣은 상단과 그 봉 고가를 비교). 지금 봇의
            37.2배가 이 규칙이다.
  직전 봉   실거래와 같다. 봉이 닫힌 뒤 계산한 상단으로 다음 봉에 지정가를 건다. 지정가라
            시가가 더 높으면 시가에 체결된다. 공정한 비교를 위해 "지금 규칙 + 직전 봉"도 돈다.
폭락장·급락 때 들어간 롱(2배)에만 적용하는 변형도 같이 본다.
판정: 지갑 전체에서 2017~ · 2024~ · 곡선낙폭 · 1년손실이 모두 지금 이상. 학습 ~2023 / 검증 2024~.

━━ 결과 ━━
요약 (2026-11-22)
                                  2017~ 곡선낙폭 1년손실 ~2023  2024~  평단아래 익절
    지금 봇 (같은 봉 밴드)        37.2배  25%     2%    5.8배  6.39배      0
    지금 봇 (직전 봉 밴드)        31.5배  25%     9%    5.4배  5.79배      0
    상단 아래도 익절 (같은 봉)    39.5배  25%     2%    6.1배  6.40배  198/1833
    상단 아래도 익절 (직전 봉)    30.9배  25%     8%    5.4배  5.73배  216/1816
    폭락장만 (같은 봉)            38.3배  25%     2%    6.0배  6.43배  113/1832
    폭락장만 (직전 봉)            31.2배  25%     8%    5.3배  5.83배  122/1815
  ① 사용자가 요청한 변형(상단이 평단 아래여도 그 상단에 익절)은 효과가 작다. 같은 봉 규칙에서는
     네 지표를 모두 지키지만 이득이 +6%(37.2→39.5배)와 +0.2%(2024~)뿐이고, 직전 봉 규칙(실거래와 같음)
     에서는 오히려 2017~(31.5→30.9)와 2024~(5.79→5.73)가 조금 나빠진다. 하락장 연도(2022 +21→+30%,
     2025 +165→+168%)는 좋아지고 2020·2021은 조금 나빠지는 차이가 상쇄된다. 채택하지 않는다.
  ② ⚠️ 부수 발견 — 지금 봇의 백테스트 기준값이 낙관적이다. per_coin_rules.sim 은 익절 판정에
     "그 봉 종가까지 넣은 볼린저 상단"(lv[k][bar])과 그 봉 고가를 비교한다. 실거래는 봉이 닫힌 뒤의
     상단으로 지정가를 걸고 다음 봉에서 체결된다(직전 봉 밴드, 시가가 더 높으면 시가). 실거래와 같게
     고치면 같은 규칙인데 37.2배→31.5배, 1년손실 2%→9%, 2024~ 6.39→5.79배가 된다. 진입은 신호 봉
     종가 판단 · 다음 봉 시가 체결이라 영향이 없고, 익절 체결 규칙만의 차이다. 이전의 모든 비교
     시험은 같은 기준선을 썼으므로 상대 비교는 대체로 유효하지만, 절대 수치(36배·1년손실 2%)는
     과대하다. 사용자 확인 후 기준값을 31.5배·곡선낙폭 25%·1년손실 9%·~2023 5.4배·2024~ 5.8배로 바꿀지 정한다.
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

_src = inspect.getsource(PCR.sim).replace("def sim(", "def sim_u(")
_a = "        avg = e1\n"
assert _src.count(_a) == 1
_src = _src.replace(_a, _a + "        und_on = UND['act'](pd.Timestamp(dt[i + 1]))\n")
_b = "                up = lv[k][bar]\n"
_c = "                if not np.isnan(up) and h[bar] >= up and up > avg:\n"
_d = "                    sold.append((take, up)); left -= take\n"
for x in (_b, _c, _d):
    assert _src.count(x) == 1, x
_src = _src.replace(_b, "                up = lv[k][bar - 1] if UND['prev'] else lv[k][bar]\n")
_src = _src.replace(_c, "                if not np.isnan(up) and h[bar] >= up and (up > avg or (UND['nocond'] and und_on)):\n")
_src = _src.replace(_d, "                    sold.append((take, max(up, o[bar]) if UND['prev'] else up)); left -= take\n")
UND = {"prev": False, "nocond": False, "act": lambda ts: True}
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
    bearf = lambda ts: is_on(B, ts) or in_window(hits, ts)

    def win(c):
        v = c.values
        return np.array([v[i + 365] / v[i] for i in range(0, len(c) - 365, 15)])

    def run(lab, prev, nocond, bear_only=False):
        UND["prev"], UND["nocond"] = prev, nocond
        UND["act"] = bearf if bear_only else (lambda ts: True)
        L = []
        for s, g in G.items():
            o, h, l, c = (g[q].astype(float).values for q in ("open", "high", "low", "close"))
            ts = sim_u(o, h, l, c, g["datetime"].values, ma, th, hd, fr, ou, S.STOP_PCT, sym=s, step=st)
            L += [dict(to_up(t), reason=t["reason"]) for t in ts]
        L = cut(L)
        tr = [dict(t, kind="longb") if bearf(t["dt"]) else t for t in L] + Sh + Dv
        fin, mdd, got, c = MW.taken(tr, pt, lv)
        a = MW.taken([t for t in tr if t["dt"] < TE], pt, lv)[0]
        h = MW.taken([t for t in tr if t["dt"] >= TE], pt, lv)[0]
        y = c.resample("YE").last(); yr = ((y / y.shift(1).fillna(1) - 1) * 100)
        neg = [t for t in L if t["reason"] == "tp" and t["exit_px"] < t["entry"]]
        r = dict(fin=fin, cdd=float((1 - c / c.cummax()).max() * 100), l1=(win(c) < 1).mean() * 100,
                 a=a, h=h, neg=len(neg), n=len(L), yr={d.year: v for d, v in yr.items()})
        print(f"{lab:<28}{fin:>6.1f}배 곡선{r['cdd']:>4.0f}% 1년손실{r['l1']:>3.0f}% ~2023 {a:>5.1f}배 "
              f"2024~ {h:>5.2f}배 평단아래 익절 {len(neg)}/{len(L)}건 | "
              + " ".join(f"{d%100}:{v:+.0f}" for d, v in r["yr"].items() if d >= 2018), flush=True)
        return r

    base = run("지금 봇 (같은 봉 밴드)", False, False)
    base_p = run("지금 봇 (직전 봉 밴드)", True, False)
    runs = {
        "상단 아래도 익절(같은 봉)": run("상단 아래도 익절(같은 봉)", False, True),
        "상단 아래도 익절(직전 봉)": run("상단 아래도 익절(직전 봉)", True, True),
        "폭락장만(같은 봉)": run("폭락장만(같은 봉)", False, True, True),
        "폭락장만(직전 봉)": run("폭락장만(직전 봉)", True, True, True),
    }
    print()
    for lab, r in runs.items():
        for bn, b in (("같은 봉 기준선", base), ("직전 봉 기준선", base_p)):
            bad = [f"{nm} {b[key]:.1f}→{r[key]:.1f}" for key, nm, sg in
                   (("fin", "2017~", 1), ("h", "2024~", 1), ("cdd", "곡선낙폭", -1), ("l1", "1년손실", -1))
                   if (r[key] - b[key]) * sg < -1e-9]
            print(f"  {lab} vs {bn}: {'통과' if not bad else '나빠짐 ' + ', '.join(bad)}")


if __name__ == "__main__":
    main()
