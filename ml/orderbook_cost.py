"""
ml/orderbook_cost.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
호가창으로 왕복 비용 0.40% 가정을 검증한다

백테스트는 왕복 비용을 0.40%로 잡는다. 이 숫자 하나가 전략의
생사를 가른다 — ml/youtube_daytrade.py 에서 단타 규칙 10개가
0.40%에서 전부 죽고 0.04%에서 7개가 살아났다.

0.40%의 내역:
    테이커 왕복 수수료 0.055% × 2   = 0.110%p
    5분 폴링 체결지연 (실측)         = 0.196%p
    ──────────────────────────────────────────
    소계                             = 0.306%p
    남는 여유                        = 0.094%p  ← 시장충격 몫

데이터: data/orderbook/*_book_1m.csv.gz
        6종(BTC/ETH/BNB/XRP/ADA/SOL) · 각 25.4만 분 · 2026-03-16~09-11
        바이낸스 USDⓈ-M 선물 bookDepth 아카이브 (bybit/collect_orderbook.py)

━━━ 수집 데이터를 읽을 때 반드시 알아야 할 것 두 가지 ━━━

(1) notional_1pct 는 실제 호가 규모의 약 2배다.
    collect_orderbook.py 가 groupby(1min).sum() 을 쓰는데, 바이낸스
    아카이브는 분당 스냅샷을 2장(30초 간격) 담고 있어서 두 장이
    합산된다. 검증: notional_total 을 자기 121분 이동중앙값으로 나눈
    비율의 분포가 봉우리 두 개만 갖는다 — 1.00배 92.1%, 0.50배 3.1%,
    1.5·2.0·3.0배는 0.0%. 정상은 2장이고 3%의 분에서 1장이 빠진다.
    한쪽(매수 또는 매도) 깊이를 쓰려면 추가로 2로 나눈다 → 총 ÷4.

(2) spread_proxy 는 스프레드가 아니고, 방향이 반대다.
    정의는 notional_1pct / notional_total, 즉 ±1% 구간이 ±5% 전체에서
    차지하는 비중이다. **값이 크면 중간가 근처가 두껍다(좋다).**
    이름대로 "크면 나쁘다"로 읽으면 정확히 거꾸로 해석한다. 실측:

        BTC 변동성 상위10%  ±1% 호가 0.869배  spread_proxy 0.0887
            변동성 하위10%  ±1% 호가 1.163배  spread_proxy 0.0941
        ADA 변동성 상위10%  ±1% 호가 0.782배  spread_proxy 0.0750
            변동성 하위10%  ±1% 호가 1.190배  spread_proxy 0.0938

━━━ 결론 ━━━

한쪽 ±1% 깊이 중앙값($): BTC 210.5M · ETH 96.7M · SOL 22.2M ·
XRP 10.7M · BNB 7.9M · ADA 3.1M

슬리피지 상한은 모델 없이 구할 수 있다. ±1% 안의 호가를 f 비율만
먹으면 가격은 ±1%를 **넘을 수 없다**. 균등밀도 가정에서 평균 체결
슬리피지는 f/2 × 1%이고, 이게 보수적 상한이다. 멱함수 적합 같은
모델을 끼우면 더 낮은 값이 나오지만 모델에 기대지 않으려고 상한을
썼다.

가장 얇은 ADA에 숏/다이버(자본의 40%, 시장가 왕복)를 낸다고 할 때:

    자본        호가 잠식     왕복 상한     고정비+상한
    1,180만원     0.11%      0.001%p      0.307%
    1억원         0.93%      0.009%p      0.315%
    5억원         4.64%      0.046%p      0.352%
    10억원        9.28%      0.093%p      0.399%   ← 여유 소진 직전

    0.40% 가정이 깨지는 자본: 평시 10.2억원 / 급락(깊이 -19%) 8.3억원

과매도 롱은 명목이 자본의 3%뿐이라 훨씬 더 여유가 있다.

→ **수억원대까지 0.40%는 안전하다.** 생존편향과 달리 이 항목은
   추가 할인이 필요 없다.

━━━ 이 숫자는 하한이다 ━━━

  · 스프레드 크로싱이 빠져 있다. bookTicker 가 아카이브에 없어서
    최우선 호가를 한 번도 재지 못했다. 0.40%에도 이 계산에도 없다.
  · 6종만 쟀다. 나머지 36종은 더 얇다. ADA가 '측정된 것 중' 최하다.
  · 데이터는 바이낸스, 체결은 바이빗이다. 바이빗이 더 얇다.
  · 30초 스냅샷은 ms 단위로 취소되는 호가를 못 거른다(유령 유동성).
  · 180일 표본에 2020-03·2022-11급 사건이 없다. 진짜 위기의
    유동성 증발은 이 데이터로 배제되지 않는다.

실행: python ml/orderbook_cost.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)

SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "ADAUSDT"]
KRW = 1380.0
FEE, DELAY = 0.110, 0.196          # 왕복 수수료 · 실측 체결지연 (%p)
BUDGET = 0.40 - FEE - DELAY        # 시장충격에 쓸 수 있는 여유
SNAPSHOTS = 2                      # 분당 스냅샷 수 (아래에서 검증한다)
CRASH_DEPTH = 0.81                 # 급락 시 깊이 배수 (ADA 실측 -18.9%)


def load(sym):
    p = f"data/orderbook/{sym}_book_1m.csv.gz"
    if not os.path.exists(p):
        return None
    d = pd.read_csv(p)
    d["dt"] = pd.to_datetime(d["dt"], format="ISO8601")
    return d


def one_side_depth(d):
    """한쪽 ±1% 깊이. 스냅샷 합산(÷2)과 양쪽 합산(÷2)을 되돌린다."""
    return d["notional_1pct"].median() / (SNAPSHOTS * 2)


def verify_snapshots(d):
    """분당 스냅샷이 합산되는지 확인한다. 봉우리가 1.00과 0.50에만 있어야."""
    r = d["notional_total"] / d["notional_total"].rolling(
        121, center=True, min_periods=60).median()
    v = r.dropna()
    return {lab: float(((v > lo) & (v < hi)).mean() * 100)
            for lo, hi, lab in [(.45, .55, "0.50배"), (.95, 1.05, "1.00배"),
                                (1.45, 1.55, "1.50배"), (1.95, 2.05, "2.00배")]}


def roundtrip_cap(capital_krw, depth_usd, frac=0.40):
    """왕복 슬리피지 상한(%p). 모델 없이: 잠식률 f → f/2 × 1% × 왕복 2회."""
    f = capital_krw * 10000 / KRW * frac / depth_usd
    return 2 * (f / 2 * 1.0), f


def break_capital(depth_usd, frac=0.40, budget=BUDGET):
    """0.40% 가정의 여유가 소진되는 자본(만원)."""
    # 상한식이 자본에 선형이므로 직접 푼다
    return budget / 2 * 2 * depth_usd / frac * KRW / 10000


def main():
    argparse.ArgumentParser().parse_args()
    D = {s: load(s) for s in SYMS}
    D = {k: v for k, v in D.items() if v is not None}
    if not D:
        print("  data/orderbook/ 에 데이터가 없다. "
              ".github/workflows/collect_orderbook.yml 을 먼저 돌려라.")
        return

    print("=" * 88)
    print("  호가창으로 본 왕복 비용 — 0.40% 가정은 타당한가")
    print("=" * 88)
    n = sum(len(v) for v in D.values())
    span = f"{min(v.dt.min() for v in D.values()):%Y-%m-%d} ~ {max(v.dt.max() for v in D.values()):%Y-%m-%d}"
    print(f"  {len(D)}종 · {n:,}분 · {span}")
    print(f"  고정비 {FEE}%p(수수료) + {DELAY}%p(체결지연) = {FEE+DELAY:.3f}%p "
          f"· 시장충격 여유 {BUDGET:.3f}%p")

    print(f"\n  ■ 스냅샷 합산 검증 (BTC) — 1.00과 0.50에만 봉우리가 있어야 한다")
    for k, v in verify_snapshots(D["BTCUSDT"]).items():
        print(f"      {k}: {v:5.1f}%")

    print(f"\n  ■ 한쪽 ±1% 깊이 중앙값")
    print(f"      {'종목':<10s}{'보정 전':>16s}{'보정 후(÷4)':>16s}")
    print("      " + "-" * 42)
    depth = {}
    for s, d in sorted(D.items(), key=lambda kv: -one_side_depth(kv[1])):
        depth[s] = one_side_depth(d)
        print(f"      {s:<10s}{d['notional_1pct'].median():>16,.0f}{depth[s]:>16,.0f}")

    thin = min(depth, key=depth.get)
    print(f"\n  ■ 가장 얇은 {thin} 에 숏/다이버(자본의 40%) 시장가 왕복")
    print(f"      {'자본':<12s}{'주문($)':>12s}{'호가 잠식':>11s}"
          f"{'왕복 상한':>11s}{'고정비+상한':>13s}")
    print("      " + "-" * 60)
    for c in [1180, 5000, 10000, 50000, 100000]:
        rt, f = roundtrip_cap(c, depth[thin])
        print(f"      {f'{c:,}만원':<12s}{c*10000/KRW*.40:>12,.0f}{f*100:>10.2f}%"
              f"{rt:>10.3f}%{FEE+DELAY+rt:>12.3f}%")

    print(f"\n  ■ 0.40% 가정이 깨지는 자본")
    print(f"      {'종목':<10s}{'평시':>14s}{'급락(깊이 -19%)':>18s}")
    print("      " + "-" * 44)
    for s in sorted(depth, key=lambda x: depth[x]):
        a = break_capital(depth[s])
        b = break_capital(depth[s] * CRASH_DEPTH)
        fmt = lambda v: f"{v/10000:.1f}억원" if v >= 10000 else f"{v:,.0f}만원"
        print(f"      {s:<10s}{fmt(a):>14s}{fmt(b):>18s}")

    print(f"\n  → 수억원대까지 0.40%는 안전하다. 이 항목은 추가 할인이 필요 없다.")
    print(f"     다만 스프레드 크로싱·바이빗 격차·36종 미측정이 빠져 있어 하한이다.")


if __name__ == "__main__":
    main()
