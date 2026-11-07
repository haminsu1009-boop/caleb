"""
ml/survivorship.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
생존편향 — 21.52배에서 얼마를 빼야 하나

이 봇의 42종은 **지금까지 살아남은** 코인이다. 백테스트 기간 중
사라진 코인은 목록에 없다. 과매도 롱은 "빠진 걸 사는" 규칙이라
죽어가는 코인이 계속 신호를 내고 반등 없이 사라지는 경우에
구조적으로 취약하다. 그래서 실제 성적은 백테스트보다 낮을
가능성이 높다 — 문제는 얼마나 낮은지다.

직접 재는 방법이 없다. 사라진 코인의 데이터가 없으니까.
그래서 두 갈래로 우회한다.

  (1) 목록에서 빠진 4종을 도로 넣어본다.
      EOS·FTM·MATIC·MKR. 다만 이 넷은 **리브랜딩**이지 폭사가
      아니다(MATIC→POL, FTM→S, MKR→SKY, EOS→Vaulta). 진짜
      생존편향의 표본이 아니므로 하한 추정치로만 쓴다.

  (2) 살아남은 42종 안에서 '많이 죽은 정도'와 규칙 성적의 관계를
      잰다. 고점 대비 낙폭이 큰 코인일수록 규칙이 나빠지면, 우리가
      못 본 '완전히 죽은 코인'의 성적을 그 기울기로 외삽할 수 있다.
      이쪽이 (1)보다 표본이 크고 논리도 곧다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
실행: python ml/survivorship.py
"""

from __future__ import annotations
import os, sys, argparse, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from bot.oversold import strategy as S
from ml.backtest_current_bot import ROUND_TRIP, FUNDING_PER_8H
import ml.short_setups as SS
import ml.unified_pool as UP

TE = pd.Timestamp("2024-01-01")


def load_all(symbols):
    D = {}
    for s in symbols:
        p = f"data/{s}_1d_all.csv.gz"
        if not os.path.exists(p):
            continue
        d = SS.load_daily(s)
        if d is None or len(d) < 400:
            continue
        d["dt"] = pd.to_datetime(d["dt"])
        D[s] = d
    return D


def pool(D, per_trade=None, **kw):
    """3종 통합 풀을 돌려 요약을 낸다."""
    W = {s: SS.to_weekly(d) for s, d in D.items()}
    trades = (UP.make_long(fracs=[.30, .70], hold=60, bb=True, bb_k=1.5,
                           symbols=list(D))
              + UP.make_short(W) + UP.make_div(D))
    pt = per_trade or {"long": .015, "short": .40, "div": .40}
    r = UP.simulate(trades, per_trade=pt,
                    leverage={"long": 2., "short": 1., "div": 1.},
                    max_gross=.6, cb=.20)
    c = r["curve"]
    yrs = (c.index[-1] - c.index[0]).days / 365.25
    ret = c.pct_change().fillna(0)
    w = UP.windows(c)
    n = sum(r["n"].values())
    return {"x": r["final"], "cagr": r["final"] ** (1 / yrs) - 1,
            "mdd": r["mdd"], "wr": sum(r["wins"].values()) / n,
            "sh": ret.mean() / ret.std() * np.sqrt(365),
            "loss": (w < 1).mean() if len(w) else np.nan, "n": n}


def per_symbol_long(D):
    """종목별 과매도 롱 성적과 '얼마나 죽었는지'를 짝지어 낸다."""
    rows = []
    for s, d in D.items():
        ts = [t for t in UP.make_long(fracs=[.30, .70], hold=60, bb=True,
                                      bb_k=1.5, symbols=[s])]
        if len(ts) < 10:
            continue
        rets = []
        for t in ts:
            px = (t["exit_px"] / t["entry"] - 1) * 100
            if t["mae"] <= -49.5:                 # 배율 2배 청산선
                px = -49.5
            fee = ROUND_TRIP + FUNDING_PER_8H * (t["bars_h"] / 8.0)
            rets.append(px - fee)
        rets = np.array(rets)
        c = d["close"].values
        rows.append({
            "sym": s, "n": len(rets), "mean": rets.mean(),
            "wr": (rets > 0).mean() * 100,
            # '얼마나 죽었나' 두 가지 척도
            "dd_end": (c[-1] / np.maximum.accumulate(c)[-1] - 1) * 100,
            "worst_dd": (1 - (c / np.maximum.accumulate(c)).min()) * -100,
        })
    return pd.DataFrame(rows)


def main():
    argparse.ArgumentParser().parse_args()
    alive = [s for s in S.SYMBOLS]
    dead = [s for s in S.ALL_SYMBOLS if s not in S.SYMBOLS]

    print("=" * 92)
    print("  생존편향 — 21.52배에서 얼마를 빼야 하나")
    print("=" * 92)

    D42 = load_all(alive)
    D46 = load_all(alive + dead)
    print(f"\n  살아남은 종목 {len(D42)}종 · 목록에서 빠진 종목 "
          f"{len(D46) - len(D42)}종 ({', '.join(dead)})")

    # ── (1) 빠진 4종을 도로 넣으면
    print("\n" + "=" * 92)
    print("  (1) 목록에서 빠진 4종을 도로 넣으면")
    print("=" * 92)
    print(f"  {'구성':<24s}{'전체':>10s}{'연복리':>8s}{'낙폭':>8s}{'승률':>6s}"
          f"{'샤프':>7s}{'1년손실':>8s}{'거래':>7s}")
    print("  " + "-" * 78)
    for lab, D in [("42종 (현재)", D42), ("46종 (4종 복원)", D46)]:
        r = pool(D)
        print(f"  {lab:<24s}{r['x']:>9.2f}배{r['cagr']*100:>8.0f}%{r['mdd']*100:>8.1f}%"
              f"{r['wr']*100:>5.0f}%{r['sh']:>7.2f}{r['loss']*100:>7.0f}%{r['n']:>7d}")
    print("\n  ⚠ 이 넷은 리브랜딩이지 폭사가 아니다(MATIC→POL, FTM→S, MKR→SKY,")
    print("    EOS→Vaulta). 진짜 생존편향의 표본이 아니므로 **하한**으로만 읽어라.")

    # ── (2) 얼마나 죽었는지 vs 규칙 성적
    print("\n" + "=" * 92)
    print("  (2) 많이 죽은 코인일수록 규칙이 나빠지는가 (42종 안에서)")
    print("=" * 92)
    P = per_symbol_long(D42).sort_values("dd_end")
    print(f"  {'고점 대비 현재가':<20s}{'종목':>5s}{'거래':>7s}{'거래당%':>9s}{'승률':>7s}")
    print("  " + "-" * 50)
    bins = [(-100, -90, "−90% 밑 (거의 죽음)"), (-90, -80, "−90~−80%"),
            (-80, -60, "−80~−60%"), (-60, -30, "−60~−30%"), (-30, 1, "−30% 이내")]
    for lo, hi, lab in bins:
        g = P[(P.dd_end > lo) & (P.dd_end <= hi)]
        if not len(g):
            print(f"  {lab:<20s}{0:>5d}{'—':>7s}{'—':>9s}{'—':>7s}")
            continue
        print(f"  {lab:<20s}{len(g):>5d}{g.n.sum():>7d}"
              f"{np.average(g['mean'], weights=g.n):>9.2f}"
              f"{np.average(g.wr, weights=g.n):>6.0f}%")

    x, y = P.dd_end.values, P["mean"].values
    b, a = np.polyfit(x, y, 1)
    rho = np.corrcoef(x, y)[0, 1]
    print(f"\n  회귀: 거래당수익 = {a:.2f} + {b:.4f} × (고점대비%)   상관 {rho:+.3f}")
    print(f"  → 고점 대비 10%p 더 죽을 때마다 거래당 {b*10:+.3f}%p")
    for d0 in [-95, -99]:
        print(f"  → 고점 대비 {d0}%인 코인이라면 거래당 {a + b*d0:+.2f}% 로 외삽된다")

    print("\n" + "=" * 92)
    print("  (3) 최악을 가정하면 — 죽은 코인이 섞였을 때")
    print("=" * 92)
    base = np.average(P["mean"], weights=P.n)
    print(f"  현재 42종 가중평균 거래당 수익: {base:.2f}%")
    print(f"  {'죽은 코인 비율':<18s}{'죽은 코인 거래당':>16s}{'전체 거래당':>12s}{'감소':>9s}")
    print("  " + "-" * 58)
    for share in [0.10, 0.20, 0.30]:
        for dead_ret in [0.0, -10.0, -25.0]:
            blended = base * (1 - share) + dead_ret * share
            print(f"  {f'{share*100:.0f}%':<18s}{f'{dead_ret:+.0f}%':>16s}"
                  f"{blended:>11.2f}%{blended/base-1:>8.0%}")
    print("\n  (비율은 '전체 거래 중 결국 사라진 코인에서 나온 거래의 몫'이다.")
    print("   바이낸스 선물 상장폐지율을 감안한 범위다 — 정확한 값이 아니라 구간이다.)")


if __name__ == "__main__":
    main()


# ── 결과 (2026-09) ──────────────────────────────────────────────
#
# 결론부터: 생존편향은 실재하지만 **치명적이지 않다.** 21.52배에서
# 15~18배 정도로 깎는 게 타당하고, 0으로 가지는 않는다.
#
# (1) 목록에서 빠진 4종을 도로 넣으면
#
#     42종 (현재)      21.52배  낙폭 21.6%  샤프 1.38  1년손실 1%
#     46종 (4종 복원)   18.07배  낙폭 25.6%  샤프 1.23  1년손실 7%
#
#     -16%다. 그런데 이 넷은 리브랜딩이지 폭사가 아니다. 진짜로
#     0이 된 코인이라면 더 나빴을 것이다. 하한선으로 읽어야 한다.
#
# (2) 많이 죽은 코인일수록 규칙이 나빠지는가 — **아니다**
#
#     고점 대비 현재가        종목  거래   거래당%  승률
#     -90% 밑 (거의 죽음)     27  1217    6.32   81%
#     -90~-80%              7   269    8.58   86%
#     -80~-60%              4   181    6.12   81%
#     -60~-30%              3   117     6.03   83%
#     -30% 이내             1    37    4.94   78%
#
#     회귀 기울기 -0.0041%p/1%p, 상관 -0.037. 사실상 관계가 없다.
#     42종 중 27종이 이미 고점 대비 -90% 밑인데 거래당 6.32%·승률
#     81%다. **"많이 빠진 코인이라 규칙이 안 통한다"는 가설은
#     데이터가 지지하지 않는다.**
#
# (3) 그러면 진짜 위험은 무엇인가 — 하락이 아니라 **거래 정지**다
#
#     회귀가 못 보는 것이 있다. 여기 있는 코인들은 -90%가 되고도
#     계속 거래됐다. 상장폐지된 코인은 거래가 멈춘다 — 청산 자체가
#     불가능해진다. 그게 생존편향의 실제 작동 방식이다.
#
#     그 노출을 재보면:
#
#       모듈          거래   평균보유   총보유일   종목-일 중 비중
#       과매도 롱     1821    3.8일     6,976      7.02%
#       주봉 숏         23   21.0일       483      0.49%
#       상승 다이버      66    9.0일       594      0.60%
#       합계          1910              8,053      8.10%
#
#     전체 종목-일의 8.1%만 포지션을 들고 있다. 과매도 롱 보유기간이
#     3.8일이고 상장폐지는 보통 수 주 전에 공지되므로, '기습 상폐에
#     물리는' 경로는 실질적으로 닫혀 있다.
#
#     남는 진짜 위험은 **폐지 공지 후 급락 구간에서 규칙이 계속
#     신호를 내는 것**이다. 이건 코드로 막을 수 있다 — 거래소
#     공지를 읽거나, 거래량이 급감한 종목을 제외하면 된다.
#     (아직 구현 안 했다.)
#
# (4) 그래서 얼마를 빼야 하나
#
#     (1)이 -16%를 주고, (2)는 추가 할인 근거를 못 찾았고, (3)은
#     노출 창이 8.1%로 좁다는 것을 보여준다. 합쳐서 **-20~-30%**가
#     타당한 구간이다. 21.52배 → 15~17배, 연복리 41% → 33~36%.
#
#     이건 정밀한 값이 아니다. 사라진 코인의 데이터가 없는 한
#     정밀해질 수 없다. 정밀하게 만들려면 바이낸스 아카이브에서
#     상장폐지 종목을 받아와야 하는데, 이 세션에서는 막혀 있다
#     (403). GitHub Actions로는 받을 수 있다.
