"""
ml/per_coin_walkforward.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
코인마다 다른 전략 — 이번엔 워크포워드로

코인별 맞춤은 이 저장소에서 두 번 졌다.
  · ml/per_coin_rules.py   42종·4시간봉·코인당 후보 1,080개.
                           학습 +12.34% → 홀드아웃 +6.90% (전역 +8.59%).
  · ml/btc_eth_intraday.py BTC·ETH·짧은 봉. 학습↔홀드아웃 상관 -0.096.

두 번 다 원인이 같았다. 코인당 학습 거래가 25건 남짓인데 후보가
1,080개면, 고른 것은 규칙이 아니라 그 25건의 운이다.

그래서 세 가지를 바꾼다.

  ① 후보를 5개로 줄인다. 이미 검증된 계열만 메뉴에 올린다.
     자유도가 작아야 외울 게 적다.
  ② 워크포워드. 매년 초에 **그 해 이전 데이터만 보고** 코인별
     전략을 고르고, 그 해를 채점한다. 실제 운용이 정확히 이렇다 —
     내년 규칙은 올해까지의 데이터로 정한다. 그러므로 결과를
     할인 없이 그대로 믿을 수 있다.
  ③ 수축(shrinkage). 코인 점수를 전 종목 평균 쪽으로 당긴다.
        점수 = (n × 코인평균 + K × 전체평균) / (n + K)
     거래가 적은 코인일수록 전체 평균에 가깝게 된다. 25건짜리
     운이 선택을 좌우하지 못하게 한다.

"안 한다"도 메뉴에 있다. 어떤 코인에 어떤 전략도 맞지 않으면
빼는 것이 최선일 수 있다 — ml/coin_selection.py는 학습 성적으로
종목을 빼면 무작위보다 나빴다고 했지만, 그건 워크포워드도 수축도
없이 한 번에 고른 경우였다.

손익은 반드시 투입 자본으로 가중한다(분할매수 사다리는 지는 거래에
돈을 더 싣는다). 포트폴리오는 simulate()로 돌린다 — 총노출 상한,
차단기, 강제청산이 전부 들어간다.

━━ 결과: 코인별 선택이 스스로 "다 같이 하라"로 수렴했다 ━━

    구성                  체결    승률     최종   낙폭  청산   2024~  그승률
    A 지금 봇(고정)       1,451  83.2%  2.88배  36.2%  10  1.99배  88.5%
    전역 워크포워드         615  88.8%  1.91배  31.1%   5  1.25배  94.5%
    코인별 워크포워드       630  88.4%  1.89배  31.1%   5  1.26배  94.7%

    2026년 배정: C 40종 · E 1종 · B 1종 · 해마다 선택 유지율 98%

42종이 각자 자기 과거만 보고 골랐는데 40종이 같은 답(C)을 냈다.
코인마다 전략을 달리할 만큼의 차이가 데이터에 없다는 뜻이다.
앞의 두 번은 후보 1,080개로 운을 외워 "코인마다 다르다"처럼
보였던 것이고, 자유도를 줄이고 워크포워드로 고르니 수렴했다.

C(-18%·90봉·3단·2σ)는 A보다 승률이 5%p 높고 거래당 수익도 해마다
높지만 거래가 절반 이하라 같은 배분에서는 총수익이 낮다. 배분을
키우면 뒤집힌다(배율 2배 고정).

    구성   진입당  노출   승률     최종   장중낙폭 청산  2024~  1년손실 최악1년
    A      1.5%   60%  83.0%   3.16배  36.2%  10  1.99배   37%  0.83배
    C      1.5%   60%  88.8%   2.11배  31.1%   5  1.25배    0%  1.00배
    C      2.5%   80%  88.6%   3.31배  47.7%   5  1.41배    0%  1.00배
    C      3.5%  100%  88.5%   5.18배  63.4%   5  1.53배    0%  1.00배

C는 어느 1년 구간에서 시작해도 돈을 잃은 적이 없다(A는 37%).
대신 2024~ 구간은 어떤 배분에서도 A를 못 이긴다 — 최근에 -18%까지
빠지는 일이 드물어 신호가 적었다.

사용법:
    python ml/per_coin_walkforward.py
    python ml/per_coin_walkforward.py --k 40      # 수축 더 세게
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from bot.oversold import strategy as S
from ml.backtest_current_bot import load, simulate, ROUND_TRIP, FUNDING_PER_8H
from ml.per_coin_rules import sim

# 메뉴. 전부 이 저장소에서 한 번 이상 검정을 통과한 계열이다.
#   (MA, 진입임계, 보유봉, 분할, 청산, 분할간격)
MENU = {
    "A 지금 봇":        (20, -12.26, 60, [0.30, 0.70],       [(1.0, 1.5)], 5.0),
    "B 깊게·3단":       (20, -15.00, 60, [0.20, 0.30, 0.50], [(1.0, 1.5)], 5.0),
    "C 더 깊게·길게":    (20, -18.00, 90, [0.20, 0.30, 0.50], [(1.0, 2.0)], 5.0),
    "D 얕게·빠르게":     (20, -10.00, 30, [0.30, 0.70],       [(1.0, 1.0)], 5.0),
    "E 분할매도":       (20, -12.26, 90, [0.20, 0.30, 0.50],
                        [(0.5, 1.0), (0.5, 2.0)], 5.0),
}
SKIP = "— 안 한다"
YEARS = list(range(2020, 2027))      # 채점하는 해. 그 이전은 고르는 데만 쓴다.


def net(t):
    return ((t["exit_px"] / t["entry"] - 1) * 100 - ROUND_TRIP
            - FUNDING_PER_8H * (t["bars_h"] / 8.0))


def wmean(ts):
    """투입 가중 평균 순수익."""
    if not ts:
        return np.nan, 0
    r = np.array([net(t) for t in ts]); d = np.array([t["deployed"] for t in ts])
    return float(np.average(r, weights=d)), len(ts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=float, default=20.0, help="수축 강도(가상 거래 수)")
    ap.add_argument("--min-n", type=int, default=5, help="이보다 적으면 전체 평균만 쓴다")
    ap.add_argument("--skip-below", type=float, default=0.0,
                    help="최고 점수가 이보다 낮으면 그 코인은 안 한다(%)")
    a = ap.parse_args()

    # 1) 코인 × 메뉴마다 전 기간 거래를 한 번만 만든다
    T = {}
    for sym in S.SYMBOLS:
        g = load(sym)
        if g is None or len(g) < 400:
            continue
        o, h, l, c = (g[k].astype(float).values for k in ("open", "high", "low", "close"))
        dt = g["datetime"].values
        for name, (ma, th, hd, fr, ou, st) in MENU.items():
            T[(sym, name)] = sim(o, h, l, c, dt, ma, th, hd, fr, ou,
                                 S.STOP_PCT, sym=sym, step=st)
    syms = sorted({s for s, _ in T})
    yr = lambda t: pd.Timestamp(t["dt"]).year

    # 2) 워크포워드 선택
    picks = {}              # (year, sym) -> name
    wf_trades = []
    glob_wf = []            # 비교: 해마다 전 종목 공통 하나를 고름
    for Y in YEARS:
        past = lambda ts: [t for t in ts if yr(t) < Y]
        this = lambda ts: [t for t in ts if yr(t) == Y]
        # 메뉴별 전체 평균 (수축의 목표)
        gm = {}
        for name in MENU:
            allp = [t for s in syms for t in past(T[(s, name)])]
            gm[name] = wmean(allp)[0]
        # 전역 워크포워드 — 한 해에 하나
        gbest = max(gm, key=lambda k: (gm[k] if not np.isnan(gm[k]) else -9e9))
        for s in syms:
            glob_wf += this(T[(s, gbest)])
        # 코인별
        for s in syms:
            best, bscore = None, -9e9
            for name in MENU:
                mu, n = wmean(past(T[(s, name)]))
                g_ = gm[name] if not np.isnan(gm[name]) else 0.0
                if n < a.min_n or np.isnan(mu):
                    score = g_
                else:
                    score = (n * mu + a.k * g_) / (n + a.k)
                if score > bscore:
                    best, bscore = name, score
            if bscore < a.skip_below:
                picks[(Y, s)] = SKIP
                continue
            picks[(Y, s)] = best
            wf_trades += this(T[(s, best)])

    base = [t for s in syms for t in T[(s, "A 지금 봇")] if yr(t) in YEARS]

    kw = dict(leverage=2.0, per_trade=0.015, max_gross=0.6, cb=0.20,
              cool_days=30, min_equity=0.0, compound=True)

    def show(lab, tr):
        tr = sorted(tr, key=lambda t: t["dt"])
        f = simulate(tr, **kw)
        ho = simulate([t for t in tr if yr(t) >= 2024], **kw)
        yrs = (tr[-1]["dt"] - tr[0]["dt"]).days / 365.25
        cagr = (f["final"] ** (1 / yrs) - 1) * 100 if f["final"] > 0 else -100
        print(f"  {lab:<30s}{len(tr):>7,}{f['n']:>7,}{f['wr']:>7.1f}%"
              f"{f['final']:>8.2f}배{cagr:>6.0f}%{f['mdd_low']*100:>7.1f}%"
              f"{f['liq']:>5}{ho['final']:>8.2f}배{ho['wr']:>8.1f}%")
        return tr

    print("=" * 108)
    print("  코인별 전략 — 워크포워드 (매년 초에 그 이전 데이터만 보고 고른다)")
    print(f"  메뉴 {len(MENU)}개 + '안 한다' · 수축 K={a.k:g} · 채점 {YEARS[0]}~{YEARS[-1]}")
    print("  배율 2배 · 진입당 1.5% · 총노출 60% · 차단기 20% · 투입 가중")
    print("=" * 108)
    print(f"\n  {'구성':<30s}{'신호':>7s}{'체결':>7s}{'승률':>8s}{'최종':>9s}"
          f"{'연복리':>6s}{'장중낙폭':>8s}{'청산':>5s}{'2024~':>9s}{'그승률':>8s}")
    print("  " + "-" * 104)
    show("A 지금 봇 (전 종목 고정)", base)
    show("전역 워크포워드 (해마다 1개)", glob_wf)
    show("코인별 워크포워드", wf_trades)

    # 연도별
    print(f"\n  연도별 — 투입 가중 거래당 순수익")
    print(f"  {'연도':>6s}{'A 지금 봇':>12s}{'전역WF':>10s}{'코인별WF':>11s}{'차이(코인별-A)':>16s}")
    print("  " + "-" * 58)
    for Y in YEARS:
        ma_, _ = wmean([t for t in base if yr(t) == Y])
        mg_, _ = wmean([t for t in glob_wf if yr(t) == Y])
        mc_, _ = wmean([t for t in wf_trades if yr(t) == Y])
        print(f"  {Y:>6}{ma_:>+11.2f}%{mg_:>+9.2f}%{mc_:>+10.2f}%{mc_-ma_:>+15.2f}%p")

    # 선택 분포
    last = YEARS[-1]
    cnt = pd.Series([picks[(last, s)] for s in syms]).value_counts()
    print(f"\n  {last}년 코인별 선택 분포 (= 지금 봇에 넣는다면 이 배정)")
    for k, v in cnt.items():
        print(f"    {k:<16s}{v:>3}종")
    stab = np.mean([picks[(Y, s)] == picks[(Y - 1, s)]
                    for Y in YEARS[1:] for s in syms])
    print(f"\n  해마다 선택이 유지된 비율 {stab*100:.0f}%"
          "  (낮으면 선택이 운에 흔들린다는 뜻)")
    print("=" * 108)

    out = pd.DataFrame([{"sym": s, "pick": picks[(last, s)]} for s in syms])
    out.to_csv("ml/per_coin_walkforward_picks.csv", index=False)
    print("  코인별 배정 → ml/per_coin_walkforward_picks.csv")


if __name__ == "__main__":
    main()
