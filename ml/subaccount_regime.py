"""
ml/subaccount_regime.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
돌파 2배를 바이빗 하위계정으로 따로 굴리고, 상승장일 때만 자금을 넘기는 방식 (2026-10-17)

배경(10-16 대화): 돌파를 같은 계정에 넣으면 같은 코인 포지션이 합쳐지는 문제(단방향
모드)로 실거래가 안 된다. 하위계정이면 그 문제가 없다. 대화 중 빠른 계산에서 "상승장일
때만 30%"가 위험 지표를 안 바꾸고 2017~ 를 키웠다. 그 가설을 미리 정해 두고 여기서
정식으로 잰다(숫자를 보고 다시 고르지 않는다).

  본 계정 = 지금 봇 그대로 (ml/crash_window.py 설정, taken, 증거금 상한 95%)
  돌파 계정 = UP.make_break 만, 건당 5%·2배, 같은 taken 규칙(자기 계정 안에서)
  두 계정의 일별 잔고를 합친다. 판단일마다 상승장(BTC 60일 ≥ +X%, 전날 종가)이면
  돌파 계정을 전체의 W 로, 아니면 0 으로 맞춘다. 옮긴 금액의 0.20% 를 비용으로 뺀다
  (돌파 포지션 일부를 팔아야 하므로 편도 수수료+미끄러짐).

미리 정한 가설: X=20%, 판단 매달 1일, W=30%.
이웃: X {15, 25}%, 판단 2주, W {20, 40}%. 판정은 RESEARCH_AGENDA 기준.

⚠️ 2026-10-17 정정: UP.make_break 는 시장 200일선 판단에 진입일 종가를 쓴다(미래참조).
  신호일 종가로 고치면 결과가 나빠진다 — 동적 비중은 2024~ 6.62→5.25배(지금 봇 6.22배).
  아래 숫자는 미래참조가 섞인 값이다. reports/research/2026-10-17.md 정정 참고.
━━ 결과 (2026-10-17) — 기준 미달(2024~ 소폭 하락), 보류 ━━
                          2017~  곡선낙폭  1년손실  ~2023  2024~  2021  2023  2024  2025  2026
    지금 봇                36.1배  24.9%    2.3%    5.8배  6.22배 +136  +15   +84  +165  +27
    ★가설 +20%·30%·매달    83.3배  24.9%    2.3%   13.8배  6.05배 +321  +34   +99  +148  +23
    이웃 +15%·30%·매달    111.9배  17.6%    2.3%   19.1배  5.87배 +451  +34   +97  +148  +20
    이웃 +25%·30%·매달     82.1배  24.9%    2.3%   13.4배  6.12배 +321  +34  +101  +148  +23
    이웃 +20%·30%·2주      86.2배  24.9%    3.3%   14.1배  6.11배 +326  +32  +103  +144  +23
    이웃 +20%·20%·매달     64.3배  24.9%    1.9%   10.5배  6.12배 +252  +28   +94  +154  +24
    이웃 +20%·40%·매달    106.0배  24.9%    3.3%   17.7배  5.98배 +398  +41  +103  +142  +21
  (회수 비용 0.20% 포함.) 곡선낙폭·1년손실은 가설과 이웃 대부분에서 지금과 같고, 2017~ 는
  2~3배가 된다. 2023(+15→+28~41%)·2024(+84→+94~103%) 도 오른다. 그러나 2024~ 합계는
  가설·이웃 6개 모두 지금보다 1~6% 낮다(5.87~6.12배) — 2025(+165→+142~154%)와 2026
  일부를 깎는 몫이 2024 이득보다 조금 크다. 판정 기준(2024~ 지금 이상) 미달 → 보류.
  성격: 위험은 그대로, 대상승장(2021형) 몫을 사는 대신 2025형(돌파 직후 꺾임) 해에 조금
  덜 번다. 실거래 장벽은 없다(하위계정 + 계정 간 이체 API).
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import sys, os; ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT); os.chdir(ROOT)
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from bot.oversold import strategy as S
import ml.unified_pool as UP, ml.short_setups as SS
from ml.backtest_current_bot import load
from ml.per_coin_rules import sim
from ml.per_coin_walkforward import MENU
from ml.per_coin_portfolio import to_up
from ml.module_winrate import taken
from ml.bear_leverage import bear_series, is_on, T0, TE
from ml.crash_window import crash_hits, in_window

COST = 0.0020


def main():
    Dd = {s: SS.load_daily(s) for s in S.SYMBOLS}; Dd = {k: v for k, v in Dd.items() if v is not None and len(v) >= 400}
    W_ = {s: SS.to_weekly(d) for s, d in Dd.items()}
    ma, th, hd, fr, ou, st = MENU["A 지금 봇"]; L = []
    for s in S.SYMBOLS:
        g = load(s); o, h, l, c = (g[k].astype(float).values for k in ("open", "high", "low", "close"))
        L += [to_up(t) for t in sim(o, h, l, c, g["datetime"].values, ma, th, hd, fr, ou, S.STOP_PCT, sym=s, step=st)]
    cut = lambda X: [t for t in X if t["dt"] >= T0]
    L, Sh, Dv = cut(L), cut(UP.make_short(W_)), cut(UP.make_div(Dd))
    btc = Dd["BTCUSDT"].set_index("dt")["close"]; B = bear_series(btc)
    hits = crash_hits(load("BTCUSDT").set_index("datetime")["close"].astype(float))
    base = [dict(t, kind="longb") if (is_on(B, t["dt"]) or in_window(hits, t["dt"])) else t for t in L] + Sh + Dv
    days = pd.date_range(T0, btc.index[-1], freq="D")
    cm = taken(base, {"long": .015, "longb": .015, "short": .40, "div": .40},
               {"long": 4., "longb": 2., "short": 1., "div": 1.})[3].reindex(days).ffill().bfill()
    cb = taken(cut(UP.make_break(Dd)), {"break": .05}, {"break": 2.})[3].reindex(days).ffill().fillna(1.0)
    rm, rb = cm.pct_change().fillna(0).values, cb.pct_change().fillna(0).values
    r60 = (btc / btc.shift(60) - 1) * 100

    def combo(x, w, period, start=None):
        bull = (r60 >= x).shift(1).reindex(days).fillna(False).values
        a, b = 1 - 0, 0.0; eq = []; last = None
        for k, d in enumerate(days):
            if start is not None and d < start:
                eq.append(np.nan); continue
            key = (d.year, d.month) if period == "m" else (d.year, d.isocalendar()[1] // 2)
            if key != last:
                tot = a + b; tgt = tot * (w if bull[k] else 0.0)
                tot -= abs(tgt - b) * COST; b = tot * (w if bull[k] else 0.0); a = tot - b; last = key
            if k:
                a *= 1 + rm[k]; b *= 1 + rb[k]
            eq.append(a + b)
        return pd.Series(eq, index=days).dropna()

    def stats(eq):
        eq = eq / eq.iloc[0]; w = UP.windows(eq)
        y = eq.resample("YE").last(); yr = (y / y.shift(1).fillna(1) - 1) * 100
        return dict(fin=eq.iloc[-1], cdd=float((1 - eq / eq.cummax()).max() * 100), l1=(w < 1).mean() * 100,
                    yr={d.year: v for d, v in yr.items()})

    def full(eqf):
        s = stats(eqf(None)); s["a"] = stats(eqf(None)[:TE])["fin"]; s["h"] = stats(eqf(TE))["fin"]; return s

    bs = full(lambda st_: (cm[cm.index >= st_] if st_ is not None else cm))
    print(f"{'':<30}{'2017~':>7}{'곡선':>6}{'1년손':>6}{'~2023':>7}{'2024~':>7}   2020  2021  2022  2023  2024  2025  2026")
    def show(lab, s):
        print(f"{lab:<30}{s['fin']:>6.1f}배{s['cdd']:>5.1f}%{s['l1']:>5.1f}%{s['a']:>6.1f}배{s['h']:>6.1f}배 "
              + " ".join(f"{s['yr'].get(y, 0):>+5.0f}" for y in range(2020, 2027)), flush=True)
    show("지금 봇", bs)
    hyp = (20, 0.30, "m")
    grid = [hyp, (15, 0.30, "m"), (25, 0.30, "m"), (20, 0.30, "2w"), (20, 0.20, "m"), (20, 0.40, "m")]
    R = {}
    for x, w, p in grid:
        R[(x, w, p)] = full(lambda st_, x=x, w=w, p=p: combo(x, w, p, st_))
        show(f"{'★가설 ' if (x, w, p) == hyp else '  이웃 '}+{x}%·{w*100:.0f}%·{'매달' if p == 'm' else '2주'}", R[(x, w, p)])
    print()
    for k, s in R.items():
        bad = []
        for key, nm, sg in (("fin", "2017~", 1), ("h", "2024~", 1), ("cdd", "곡선낙폭", -1), ("l1", "1년손실", -1)):
            if (s[key] - bs[key]) * sg < -1e-9:
                bad.append(f"{nm} {bs[key]:.2f}→{s[key]:.2f}")
        cuty = [f"{y}: {bs['yr'][y]:+.0f}→{s['yr'][y]:+.0f}" for y in bs["yr"] if s["yr"].get(y, 0) < bs["yr"][y] - 20]
        print(f"  {k}: {'통과' if not bad else '나빠짐 ' + ', '.join(bad)}" + (f" | 크게 깎인 해 {', '.join(cuty)}" if cuty else ""))


if __name__ == "__main__":
    main()
