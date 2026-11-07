"""
ml/crash_rebound.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
급락 후 반등 — 사용자가 준 원래 스펙 그대로

앞서 두 번 시험해서 두 번 기각했다. 이번엔 조건을 사용자가 처음
적어준 대로 되돌렸다. 두 가지가 달랐다.

  · 시장 필터를 **BTC 4시간봉 MA200**으로 (내가 쓰던 건 종목별 48봉 이평)
  · 청산을 고정 괄호가 아니라 **볼린저 상단**으로 (과매도 롱과 같은 방식)

━━━ 1. 반등 확률 자체는 진짜다 ━━━

    조건                  표본     1봉후      3봉후      5봉후     10봉후
    -5% 급락            11,452  56%/+0.77  54%/+1.11  60%/+2.13  57%/+2.18
    -5% + BTC MA200↑     4,415  58%/+1.07  53%/+1.23  59%/+2.27  57%/+2.97
    -5% + BTC MA200↓     7,037  55%/+0.58  55%/+1.03  60%/+2.05  57%/+1.69
    기준: 모든 봉       596,250  49%/+0.04  49%/+0.09  49%/+0.14  48%/+0.25

상승 확률 49% → 56~60%, 평균 +0.14% → +2.13%다. 신호에 정보가 있다.

━━━ 2. 청산 방식이 전부를 가른다 ━━━

    같은 진입(-5% + BTC MA200↑)에 청산만 바꾸면

    고정 괄호 +10%/-5%    3,768건  승률 38%  거래당 +0.22%
    고정 괄호 +20%/-5%    3,430건  승률 27%  거래당 +0.58%
    고정 괄호 +30%/-10%   2,682건  승률 40%  거래당 +1.82%
    **볼린저 상단 청산**   3,033건  승률 70%  거래당 +2.14%

볼린저는 변동성에 맞춰 목표가 움직인다. 고정 %는 조용할 때 너무 일찍
팔고 시끄러울 때 손절에 걸린다. 과매도 롱에서 배운 것과 같다.

문턱을 깊게 할수록 좋아진다(단조):
    -3%  8,661건 +0.72%  |  -5% 3,033건 +2.14%
    -7%  1,136건 +3.46%  |  -10%  309건 +7.09%

BTC 필터도 일한다: 있으면 +2.14%, 없으면 +1.21%.

━━━ 3. 미래참조가 아니다 (앞선 실패와 다른 점) ━━━

    BTC 필터를 신호봉 i        3,033건  +2.14%
    한 봉 전 i-1              3,617건  +1.80%
    체결봉 i+1 (미래참조)       2,972건  +2.42%

i와 i-1이 비슷하다. i+1만 좋았다면 가짜지만 그렇지 않다.
과매도 롱과 겹치는 거래도 7%뿐이라 다른 신호다.

━━━ 4. 그런데 채택하기엔 걸리는 것이 셋 ━━━

(a) 여전히 급등장 편중이다
      폭락  200건( 7%) -5.14%   하락 323건(11%) +0.56%
      횡보  230건( 8%) +2.34%   상승 261건( 9%) +0.93%
      급등 2,017건(67%) +3.24%
    폭락장에서 -5.14%다. 과매도 롱이 폭락장에서 제일 많이 버는 것과
    정반대라 그 구간에 서로 상쇄한다.

(b) 최근 연도가 나쁘다
      2021 +3.56%  2023 +3.45%  2024 +1.95%
      2025 +0.22%  2026 -4.15% (승률 31%)

(c) 비중이 절벽에 얹혀 있다 — 이게 가장 큰 문제다
      비중    전체     낙폭   1년손실  홀드아웃
      0%    21.52배  21.6%    1%    4.94배   ← 기준
      1.0%  14.54배  26.1%    4%    4.65배
      1.5%  19.04배  26.6%    5%    4.85배
      2.0%  37.93배  20.9%    1%    4.99배
      2.5%  49.44배  21.0%    1%    4.89배
      3.0%  66.50배  21.3%    1%    5.31배
      4.0%  87.43배  21.8%    1%    3.87배
      5.0% 112.15배  22.3%    3%    3.50배

    1.5% → 2.0%에서 19배가 38배로 뛰고 낙폭이 26.6%에서 20.9%로
    떨어진다. 차단기 발동 시점이 갈리는 자리다. 홀드아웃도
    4.65 → 4.85 → 4.99 → 4.89 → 5.31 → 3.87로 들쭉날쭉하고,
    기준(4.94배)을 넘는 것은 8개 중 2개뿐이다.

━━━ 결론 ━━━

세 번 시험한 것 중 가장 좋은 판이고, 미래참조도 아니다. 그런데
"기준보다 낫다"가 비중 두 자리에서만 성립하고 그 주변이 절벽이다.
**유망하지만 증명되지 않았다.** 실거래 검증 없이 올릴 만한 근거는
아직 아니다.

실행: python ml/crash_rebound.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from bot.oversold import strategy as S
from ml.backtest_current_bot import ROUND_TRIP

TE = pd.Timestamp("2024-01-01")
DROP = -5.0          # 한 봉 수익률 문턱
BTC_MA = 200         # BTC 4시간봉 시장 필터
HOLD = 60            # 볼린저에 못 닿으면 시간청산


def load(sym, tf="4h"):
    p = f"data/{sym}_{tf}_all.csv.gz"
    if not os.path.exists(p):
        return None
    d = pd.read_csv(p)
    d["dt"] = pd.to_datetime(d["timestamp"], format="ISO8601")
    return d.dropna(subset=["close"]).reset_index(drop=True)


def bb_upper(c, k=1.5, n=20):
    s = pd.Series(c)
    return (s.rolling(n).mean() + k * s.rolling(n).std()).values


def trades(D, btc_up, drop=DROP, hold=HOLD, use_btc=True, shift=0):
    """판단은 종가, 체결은 다음 봉 시가. 볼린저 상단 또는 시간청산."""
    out = []
    for sym, d in D.items():
        o, h, l, c = (d["open"].values, d["high"].values,
                      d["low"].values, d["close"].values)
        dt = d["dt"].values
        n = len(c)
        ret = np.r_[0, np.diff(c) / c[:-1]] * 100
        up = bb_upper(c)
        bu = np.nan_to_num(btc_up.reindex(pd.DatetimeIndex(dt),
                                          method="ffill").values).astype(bool)
        lock = -1
        for i in np.where(ret <= drop)[0]:
            e = i + 1
            if i <= lock or e >= n - 1:
                continue
            k = i + shift
            if use_btc and (k < 0 or k >= n or not bu[k]):
                continue
            ep = o[e]
            j, px = min(e + hold, n - 1), c[min(e + hold, n - 1)]
            for b in range(e, j + 1):
                if not np.isnan(up[b]) and h[b] >= up[b]:
                    j, px = b, up[b]
                    break
            out.append({"sym": sym, "dt": pd.Timestamp(dt[e]),
                        "ret": (px / ep - 1) * 100 - ROUND_TRIP,
                        "bars": j - e})
            lock = j
    return pd.DataFrame(out)


def main():
    argparse.ArgumentParser().parse_args()
    D = {s: load(s) for s in S.SYMBOLS}
    D = {k: v for k, v in D.items() if v is not None and len(v) > 500}
    btc = load("BTCUSDT").set_index("dt")
    btc_up = btc["close"] > btc["close"].rolling(BTC_MA).mean()

    print("=" * 84)
    print(f"  급락 반등 — -5% + BTC 4H MA200 + 볼린저 상단 청산")
    print(f"  {len(D)}종 · {sum(len(v) for v in D.values()):,}봉 "
          f"· BTC가 MA200 위인 기간 {btc_up.mean()*100:.0f}%")
    print("=" * 84)

    print(f"\n  {'설정':<26s}{'거래':>8s}{'승률':>7s}{'거래당%':>9s}"
          f"{'중앙%':>8s}{'학습%':>9s}{'홀드아웃%':>11s}")
    print("  " + "-" * 78)
    for drop, btcf, hold, lab in [
            (-3., True, 60, "-3% · BTC↑ · 60봉"),
            (-5., True, 60, "-5% · BTC↑ · 60봉  ← 기본"),
            (-5., False, 60, "-5% · 필터없음 · 60봉"),
            (-7., True, 60, "-7% · BTC↑ · 60봉"),
            (-10., True, 60, "-10% · BTC↑ · 60봉")]:
        t = trades(D, btc_up, drop, hold, btcf)
        tr, ho = t[t.dt < TE], t[t.dt >= TE]
        print(f"  {lab:<26s}{len(t):>8,d}{(t.ret>0).mean()*100:>6.0f}%"
              f"{t.ret.mean():>9.2f}{t.ret.median():>8.2f}"
              f"{tr.ret.mean():>9.2f}{ho.ret.mean():>11.2f}")

    print(f"\n  ■ 미래참조 점검 — BTC 필터를 어느 봉에서 보는가")
    print(f"      {'기준봉':<22s}{'거래':>8s}{'거래당%':>9s}")
    print("      " + "-" * 40)
    for sh, lab in [(-1, "한 봉 전 i-1"), (0, "신호봉 i (사용)"),
                    (1, "체결봉 i+1 (미래참조)")]:
        t = trades(D, btc_up, shift=sh)
        print(f"      {lab:<22s}{len(t):>8,d}{t.ret.mean():>9.2f}")
    print("      → i와 i-1이 비슷하면 미래참조가 아니다.")

    t = trades(D, btc_up)
    t["y"] = t.dt.dt.year
    print(f"\n  ■ 연도별")
    print(f"      {'연도':<8s}{'건수':>7s}{'거래당%':>10s}{'승률':>7s}")
    print("      " + "-" * 34)
    for y in sorted(t.y.unique()):
        g = t[t.y == y]
        print(f"      {y:<8d}{len(g):>7d}{g.ret.mean():>10.2f}"
              f"{(g.ret>0).mean()*100:>6.0f}%")

    print("\n  참고: 과매도 롱(20MA -12.26% + 볼린저)은 거래당 +6.59% · 승률 82%")
    print("  이 모듈의 채택 여부는 파일 상단 주석의 '결론'을 보라 —"
          " 비중 민감도가 절벽이다.")


if __name__ == "__main__":
    main()
