"""
ml/break_separate.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
상승장 100일 신고가 돌파 2배 — 과매도 롱과 코인 자리를 따로 쓰는 경우 정식 재검증 (2026-10-14)

RESEARCH_AGENDA 에서 "가장 유망·보류" 로 남은 것. 10-13 대화에서 "검증 구간이 나쁜 건
2025년 한 해 때문 아니냐" 는 지적이 있었고, 연도별로 보니 맞았다(2023·2024 는 이김,
2025 만 짐). 그래서 정해진 절차로 다시 잰다.

모듈: UP.make_break (시장 200일선 위일 때 100일 신고가 마감 → 다음날 시가, 40일 보유)
  2배, 같은 코인 과매도 롱과 동시 보유 허용(sym 분리 — 실거래는 별도 처리 필요).
  지금 봇(ml/crash_window.py 설정, 증거금 상한 95%)에 kind "break" 로 더해 taken 으로 돌린다.
격자: 비중 {0.25, 0.5, 0.75, 1.0}% × 200일선 이탈 정리 {없음, 있음} = 8개.
고르기는 ~2023 결과만(2024~ 는 고른 뒤 한 번). 이웃 = 비중 ±1칸 + 정리 방식 반대.
판정(RESEARCH_AGENDA): 2017~·2024~·곡선낙폭·1년손실 이 모두 지금 이상, 크게 깎인 해 없음,
이웃도 안정.

⚠️ 2026-10-17 정정: UP.make_break 는 시장 200일선 판단에 진입일 종가를 쓴다(미래참조).
  신호일 종가로 고치면 결과가 나빠진다 — 동적 비중은 2024~ 6.62→5.25배(지금 봇 6.22배).
  아래 숫자는 미래참조가 섞인 값이다. reports/research/2026-10-17.md 정정 참고.
━━ 결과 (2026-10-14) — 기준 미달(기각), 단 2024~ 는 8개 모두 개선 ━━
                       2017~  곡선낙폭  1년손실  ~2023  2024~  2023  2024  2025  체결/년
    지금 봇             36.3배  24.9%    1.5%    5.8배  6.2배  +15   +84  +165   187
    0.25% 정리없음      58.2배  26.1%    1.5%    8.8배  6.6배  +22  +143  +109   238(돌파51)
    0.5%  정리없음      87.5배  29.3%    1.5%   12.7배  6.9배  +30  +158  +104
    0.75% 정리없음     124.6배  32.5%    1.5%   17.5배  7.1배  +37  +170   +99
    1%    정리없음(1등)171.1배  35.7%    1.5%   23.0배  7.4배  +44  +183   +95
    1%    200일선정리  123.0배  39.0%   10.2%   18.0배  6.9배  +35  +184   +86
  비중을 키울수록 2017~·2024~·2023·2024 는 늘고 곡선낙폭은 한 칸에 3%p씩 커진다
  (단조 — 학습 1등이 격자 끝인 1%). 가장 작은 0.25% 도 곡선낙폭 24.9→26.1%,
  2025 +165→+109%. 8개 모두 곡선낙폭이 나빠지고 2025 가 크게 깎여 판정 기준 미달.
  반면 2024~ 는 8개 모두 지금보다 높고(6.4~7.4배), 1년손실은 정리없음이면 그대로다.
  즉 "낙폭을 조금 더 지는 대신 수익을 더 버는" 맞교환이고, 공짜 개선은 아니다.
  실거래는 바이빗 단방향 모드에서 같은 코인 롱 두 개가 합쳐지므로 구현 방법이 먼저다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
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
from ml.bear_leverage import bear_series, is_on, T0, T19, TE
from ml.crash_window import crash_hits, in_window

SIZES = (0.0025, 0.005, 0.0075, 0.01)


def main():
    Dd = {s: SS.load_daily(s) for s in S.SYMBOLS}; Dd = {k: v for k, v in Dd.items() if v is not None and len(v) >= 400}
    W = {s: SS.to_weekly(d) for s, d in Dd.items()}
    ma, th, hd, fr, ou, st = MENU["A 지금 봇"]; L = []
    for s in S.SYMBOLS:
        g = load(s); o, h, l, c = (g[k].astype(float).values for k in ("open", "high", "low", "close"))
        L += [to_up(t) for t in sim(o, h, l, c, g["datetime"].values, ma, th, hd, fr, ou, S.STOP_PCT, sym=s, step=st)]
    cut = lambda X: [t for t in X if t["dt"] >= T0]
    L, Sh, Dv = cut(L), cut(UP.make_short(W)), cut(UP.make_div(Dd))
    btc = Dd["BTCUSDT"].set_index("dt")["close"]; B = bear_series(btc)
    hits = crash_hits(load("BTCUSDT").set_index("datetime")["close"].astype(float))
    base = [dict(t, kind="longb") if (is_on(B, t["dt"]) or in_window(hits, t["dt"])) else t for t in L] + Sh + Dv
    BR = {rx: [dict(t, sym=t["sym"] + "_B") for t in cut(UP.make_break(Dd, regime_exit=rx))] for rx in (False, True)}

    def run(extra, size):
        pt = {"long": .015, "longb": .015, "short": .40, "div": .40, "break": size}
        lv = {"long": 4., "longb": 2., "short": 1., "div": 1., "break": 2.}
        tr = base + extra
        fin, mdd, got, c = taken(tr, pt, lv); w = UP.windows(c)
        a = taken([t for t in tr if t["dt"] < TE], pt, lv)[0]
        h = taken([t for t in tr if t["dt"] >= TE], pt, lv)[0]
        y = c.resample("YE").last(); yr = (y / y.shift(1).fillna(1) - 1) * 100
        yrs = (c.index[-1] - c.index[0]).days / 365
        return dict(fin=fin, mdd=mdd * 100, cdd=float((1 - c / c.cummax()).max() * 100), l1=(w < 1).mean() * 100,
                    a=a, h=h, yr={d.year: v for d, v in yr.items()}, n=len(got) / yrs,
                    nb=sum(1 for x in got if x[0] == "break") / yrs)

    def show(lab, r):
        print(f"{lab:<24}{r['fin']:>6.1f}배{r['mdd']:>5.1f}%{r['cdd']:>5.1f}%{r['l1']:>5.1f}%{r['a']:>6.1f}배{r['h']:>6.1f}배"
              f" 연{r['n']:>4.0f}건(돌파{r['nb']:.0f}) " + " ".join(f"{k%100}:{v:+.0f}" for k, v in r["yr"].items() if k >= 2018), flush=True)
        return r
    print(f"{'':<24}{'2017~':>7}{'낙폭':>6}{'곡선':>6}{'1년손':>6}{'~2023':>7}{'2024~':>7}")
    b = show("지금 봇", run([], 0))
    R = {}
    for rx in (False, True):
        for sz in SIZES:
            R[(rx, sz)] = show(f"{sz*100:.2g}% {'200일선 정리' if rx else '정리 없음'}", run(BR[rx], sz))
    best = max(R, key=lambda k: R[k]["a"])
    i = SIZES.index(best[1])
    nb = [(best[0], SIZES[j]) for j in (i - 1, i + 1) if 0 <= j < len(SIZES)] + [(not best[0], best[1])]
    print(f"\n학습(~2023) 1등: {best}")
    for k in [best] + nb:
        r = R[k]; bad = []
        for key, nm, sg in (("fin", "2017~", 1), ("h", "2024~", 1), ("cdd", "곡선낙폭", -1), ("l1", "1년손실", -1)):
            if (r[key] - b[key]) * sg < -1e-9:
                bad.append(f"{nm} {b[key]:.1f}→{r[key]:.1f}")
        cutyr = [f"{y}: {b['yr'][y]:+.0f}→{r['yr'][y]:+.0f}" for y in b["yr"] if r["yr"].get(y, 0) < b["yr"][y] - 20]
        win = sum(1 for y in b["yr"] if y >= 2018 and r["yr"][y] > b["yr"][y] + 1)
        lose = sum(1 for y in b["yr"] if y >= 2018 and r["yr"][y] < b["yr"][y] - 1)
        print(f"  {'1등' if k == best else '이웃'} {k}: {'통과' if not bad else '나빠짐 ' + ', '.join(bad)}"
              f" | 이긴 해 {win} · 진 해 {lose}" + (f" | 크게 깎인 해 {', '.join(cutyr)}" if cutyr else ""))


if __name__ == "__main__":
    main()
