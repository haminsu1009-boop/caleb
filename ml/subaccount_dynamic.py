"""
ml/subaccount_dynamic.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
돌파 하위계정 — 장의 세기에 따라 비중을 바꾸고, 돌파 계정이 빠지면 멈춘다 (2026-10-17)

ml/subaccount_regime.py(상승장만 30%)는 위험 지표는 같았지만 2024~ 가 6.22→6.05배로
조금 낮아 보류였다. 대화 중 빠른 계산에서 (1) 돌파 계정이 180일 고점 대비 −15% 빠지면
멈추기, (2) BTC 60일 +40% 이상 급등장에선 50% 로 늘리기가 2024~ 를 지금 이상으로
올렸다. 그 규칙을 아래처럼 **먼저 고정**하고, 이웃 설정으로 버티는지 본다.

  본 계정 = 지금 봇 그대로 (ml/crash_window.py 설정)
  돌파 계정 = UP.make_break 만, 건당 5%·2배
  매달 1일(전날 종가 기준)에 돌파 계정 비중을 정한다:
     BTC 60일 < +20%                         → 0%
     +20% ≤ BTC 60일 < +40%                  → 30%
     BTC 60일 ≥ +40%                         → 50%
     단, 돌파 계정이 180일 고점 대비 −15% 이상 빠져 있으면 → 0%
  옮긴 금액의 0.20% 를 비용으로 뺀다.

※ 돌파 신호는 2019년부터 나온다(200일선·100일 신고가 계산에 데이터가 필요). 첫 신호
  전에는 자금을 옮기지 않는다 — 안 그러면 2017 상승장에 빈 계정에 돈을 놀려 1년손실이
  거짓으로 늘어난다(처음 실행에서 확인, 2.34→3.27% 의 원인이 전부 2017~18 구간이었다).
이웃: 급등 기준 {35, 45}%, 급등 비중 {40, 60}%, 멈춤 {−10, −20}%, 판단 2주.
판정(RESEARCH_AGENDA): 2017~·2024~·곡선낙폭·1년손실 모두 지금 이상, 크게 깎인 해 없음,
이웃도 안정.

━━ 결과 (2026-10-17) — 판정 기준 통과(이웃 8개 중 7개), 사용자 확인 필요 ━━
                          2017~  곡선낙폭  1년손실  ~2023  2024~  2021  2023  2024  2025  2026
    지금 봇                36.1배  24.9%    2.3%    5.8배  6.22배 +136  +15   +84  +165  +27
    상승장만 30% (참고)     85.0배  24.9%    1.9%   14.0배  6.05배 +321  +34   +99  +148  +23
    ★가설                 157.1배  24.9%    1.9%   23.7배  6.62배 +564  +34  +110  +148  +27
    이웃 급등 35/45%      155~158배 24.9%   1.9%           6.53~6.62배
    이웃 급등비중 40/60%  123~199배 24.9%   1.9%           6.45~6.79배
    이웃 멈춤 −20%         157.1배  24.9%    1.9%           6.62배
    이웃 멈춤 −10%         136.2배  24.9%    1.9%           5.71배 ← 2024 +84→+81, 유일한 탈락
    이웃 판단 2주          164.5배  24.9%    1.9%           6.84배 (2025 +165→+144, −21%p)
  달 비중: 0% 81% · 30% 11% · 50% 8%. 2025 는 모든 설정에서 +165→+142~148%.
  ⚠ 이 규칙(멈춤 −15%, 급등 +40%→50%)은 2024~ 를 포함한 전체 결과를 보면서 대화 중에
    찾은 것이다. 2024~ 는 진짜 미사용 검증 구간이 아니다. 진짜 검증은 앞으로의 실거래다.
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
HYP = dict(bull=20, surge=40, w=0.30, ws=0.50, stop=15, period="m")


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
    BRK = cut(UP.make_break(Dd))
    cb = taken(BRK, {"break": .05}, {"break": 2.})[3].reindex(days).ffill().fillna(1.0)
    live = days >= min(t["dt"] for t in BRK).normalize()      # 돌파 신호가 처음 생긴 날 전에는 자금을 옮기지 않는다
    rm, rb = cm.pct_change().fillna(0).values, cb.pct_change().fillna(0).values
    r60 = ((btc / btc.shift(60) - 1) * 100).shift(1).reindex(days).values           # 전날 종가
    dd = ((1 - cb / cb.rolling(180, min_periods=1).max()) * 100).shift(1).fillna(0).values

    def combo(p, start=None):
        a, b = 1.0, 0.0; eq = []; last = None; used = []
        for k, d in enumerate(days):
            if start is not None and d < start:
                eq.append(np.nan); continue
            key = (d.year, d.month) if p["period"] == "m" else (d.year, d.isocalendar()[1] // 2)
            if key != last:
                x = r60[k]
                w = 0.0 if (not live[k] or np.isnan(x) or x < p["bull"] or dd[k] >= p["stop"]) else (p["ws"] if x >= p["surge"] else p["w"])
                tot = a + b; tot -= abs(tot * w - b) * COST; b = tot * w; a = tot - b; last = key; used.append(w)
            if k:
                a *= 1 + rm[k]; b *= 1 + rb[k]
            eq.append(a + b)
        return pd.Series(eq, index=days).dropna(), used

    def stats(eq):
        eq = eq / eq.iloc[0]; w = UP.windows(eq)
        y = eq.resample("YE").last(); yr = (y / y.shift(1).fillna(1) - 1) * 100
        return dict(fin=eq.iloc[-1], cdd=float((1 - eq / eq.cummax()).max() * 100), l1=(w < 1).mean() * 100,
                    yr={d.year: v for d, v in yr.items()})

    def full(p):
        e, used = combo(p); s = stats(e); s["h"] = stats(combo(p, TE)[0])["fin"]; s["a"] = stats(e[:TE])["fin"]
        s["mix"] = (np.mean([u == 0 for u in used]) * 100, np.mean([0 < u <= p["w"] for u in used]) * 100,
                    np.mean([u > p["w"] for u in used]) * 100)
        return s

    bs = stats(cm); bs["h"] = stats(cm[cm.index >= TE])["fin"]; bs["a"] = stats(cm[:TE])["fin"]
    print(f"{'':<30}{'2017~':>7}{'곡선':>6}{'1년손':>6}{'~2023':>7}{'2024~':>7}   2019  2020  2021  2022  2023  2024  2025  2026   달 비중(0/기본/급등)")
    def show(lab, s):
        mix = f"   {s['mix'][0]:.0f}/{s['mix'][1]:.0f}/{s['mix'][2]:.0f}%" if "mix" in s else ""
        print(f"{lab:<30}{s['fin']:>6.1f}배{s['cdd']:>5.1f}%{s['l1']:>5.1f}%{s['a']:>6.1f}배{s['h']:>6.2f}배 "
              + " ".join(f"{s['yr'].get(y, 0):>+5.0f}" for y in range(2019, 2027)) + mix, flush=True)
    show("지금 봇", bs)
    show("참고: 상승장만 30%", full(dict(HYP, ws=0.30, stop=999)))
    V = {"★가설": HYP}
    for k, v in (("surge", 35), ("surge", 45), ("ws", 0.40), ("ws", 0.60), ("stop", 10), ("stop", 20), ("period", "2w")):
        V[f"이웃 {k}={v}"] = dict(HYP, **{k: v})
    R = {}
    for lab, p in V.items():
        R[lab] = full(p); show(lab, R[lab])
    print()
    for lab, s in R.items():
        bad = []
        for key, nm, sg in (("fin", "2017~", 1), ("h", "2024~", 1), ("cdd", "곡선낙폭", -1), ("l1", "1년손실", -1)):
            if (s[key] - bs[key]) * sg < -1e-9:
                bad.append(f"{nm} {bs[key]:.2f}→{s[key]:.2f}")
        cuty = [f"{y}: {bs['yr'][y]:+.0f}→{s['yr'][y]:+.0f}" for y in bs["yr"] if s["yr"].get(y, 0) < bs["yr"][y] - 20]
        print(f"  {lab}: {'통과' if not bad else '나빠짐 ' + ', '.join(bad)}" + (f" | 크게 깎인 해 {', '.join(cuty)}" if cuty else ""))


if __name__ == "__main__":
    main()
