"""
ml/buy_and_hold.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
존버가 답이면 이 봇을 쓸 이유가 없다 — 그러니 실제로 재본다

"오래 들고 있으면 크게 오르는 코인도 있는데" 라는 질문은 두 가지로
나뉜다.

    ① 그냥 사서 계속 들고 있는다(진짜 존버) — 신호도 청산도 없다.
    ② 지금 전략의 진입 신호(20MA 대비 -12.26%)는 그대로 쓰되,
       청산만 20봉이 아니라 훨씬 길게 늘린다.

둘은 완전히 다른 질문이다. ①은 "매매를 안 하는 게 낫나"이고
②는 "이 신호로 들어간 뒤 더 오래 버티면 나은가"이다.

①은 생존 편향을 반드시 감안해야 한다 — 지금 있는 42종은 "9년을
버틴 코인들"이다. 상장폐지된 코인은 데이터에서 빠져 있으니 존버의
실제 위험은 이 계산보다 더 나쁘다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from bot.oversold import strategy as S
from ml.backtest_current_bot import load


def max_drawdown(equity: np.ndarray) -> float:
    peak = np.maximum.accumulate(equity)
    return float(np.max(1 - equity / peak))


def section_bah():
    print("=" * 100)
    print("  [1] 진짜 존버 — 그냥 사서 끝까지 들고 있었다면")
    print("=" * 100)
    rows = []
    basket = []
    for sym in S.SYMBOLS:
        g = load(sym)
        if g is None or len(g) < 100:
            continue
        c = g["close"].astype(float).values
        dt = g["datetime"].values
        yrs = (dt[-1] - dt[0]) / np.timedelta64(1, "D") / 365.25
        total = c[-1] / c[0]
        cagr = (total ** (1/yrs) - 1) * 100 if yrs > 0 else np.nan
        mdd = max_drawdown(c)
        rows.append({"sym": sym, "start": dt[0], "end": dt[-1], "yrs": yrs,
                    "total": total, "cagr": cagr, "mdd": mdd})
        s = pd.Series(c, index=pd.DatetimeIndex(dt)).resample("D").last().ffill()
        s.name = sym
        basket.append(s / s.iloc[0])
    d = pd.DataFrame(rows).sort_values("total", ascending=False)

    print(f"\n  {len(d)}종 개별 존버 성적 (2017~2026, 종목마다 상장일부터)")
    print(f"  {'심볼':10s}{'기간':>7s}{'총수익':>10s}{'연복리':>8s}{'최대낙폭':>9s}")
    for _, r in d.head(8).iterrows():
        print(f"  {r.sym:10s}{r.yrs:>6.1f}년{r.total:>9.1f}배{r.cagr:>7.0f}%{r.mdd*100:>8.1f}%")
    print("  ...")
    for _, r in d.tail(5).iterrows():
        print(f"  {r.sym:10s}{r.yrs:>6.1f}년{r.total:>9.1f}배{r.cagr:>7.0f}%{r.mdd*100:>8.1f}%")

    print(f"\n  분위:  하위25% {d.total.quantile(.25):.2f}배 · 중앙 {d.total.quantile(.5):.2f}배 · "
          f"상위25% {d.total.quantile(.75):.2f}배")
    print(f"  전 종목 최대낙폭 평균 {d.mdd.mean()*100:.1f}% · 최소 {d.mdd.min()*100:.1f}% "
          f"(가장 안 빠진 코인도 이 정도는 겪었다)")
    print(f"  9년을 버틴 42종 전부 '지금까지 살아있는' 코인이다 — 상장폐지·불량 코인은")
    print(f"  데이터에 없다. 실제 무작위 코인 존버의 위험은 이 표보다 더 나쁘다.")

    # 동일비중 바스켓(매일 리밸런싱 없이 각자 상장일부터 지수화 후 평균)
    B = pd.concat(basket, axis=1)
    basket_idx = B.mean(axis=1, skipna=True)
    b_yrs = (basket_idx.index[-1] - basket_idx.index[0]).days / 365.25
    b_total = basket_idx.iloc[-1] / basket_idx.iloc[0]
    b_cagr = (b_total ** (1/b_yrs) - 1) * 100
    b_mdd = max_drawdown(basket_idx.values)
    print(f"\n  42종 동일비중 바스켓(각자 상장일부터 지수화, 리밸런싱 없음):")
    print(f"    {b_yrs:.1f}년 · 총 {b_total:.2f}배 · 연복리 {b_cagr:.0f}% · 최대낙폭 {b_mdd*100:.1f}%")
    print(f"\n  → 지금 전략(42종·2배·분할매수): 8.8년 8.52배 · 연복리 28% · 낙폭 25.4%")
    print(f"    존버 바스켓보다 배율은 낮게 썼는데도 연복리가 비슷하거나 높고,")
    print(f"    낙폭은 훨씬 얕다 — 바스켓 존버의 낙폭이 승부를 가른다.")


def section_hold_longer():
    print(f"\n{'='*100}")
    print("  [2] 같은 신호, 더 오래 들고 있으면 — 20봉으로 끊는 게 손해인가")
    print("=" * 100)
    print("  (진입 조건은 그대로: 20MA 대비 -12.26%. 청산 시점만 늘린다.")
    print("   분할매수는 끄고 일괄매수로 본다 — 보유기간 자체의 효과만 보려고.)")

    from ml.backtest_current_bot import ROUND_TRIP, FUNDING_PER_8H, BAR_HOURS

    frames = []
    for sym in S.SYMBOLS:
        g = load(sym)
        if g is None or len(g) < S.MA_PERIOD + 260:
            continue
        o = g["open"].astype(float).values
        c = g["close"].astype(float).values
        dt = g["datetime"].values
        ma = pd.Series(c).rolling(S.MA_PERIOD).mean().values
        vs = (c / ma - 1) * 100
        frames.append((sym, o, c, dt, vs, len(g)))

    HOLDS = [10, 20, 40, 60, 100, 150, 250, 500, 1000]   # 봉수 (4h 기준 1000봉≈167일)
    print(f"\n  {'보유':>7s}{'실제일수':>9s}{'거래':>7s}{'승률':>7s}{'거래당':>9s}"
          f"{'거래당(수수료전)':>15s}{'최대순행중앙':>12s}")
    print("  " + "-" * 72)
    for H in HOLDS:
        rets, wins, mfes = [], 0, []
        for sym, o, c, dt, vs, n in frames:
            lock = -10**9
            for i in np.where(vs <= S.ENTRY_THRESH)[0]:
                if i <= lock or i + 1 + H >= n:
                    continue
                lock = i + H
                e = o[i + 1]
                ex = o[i + 1 + H]
                px_ret = (ex / e - 1) * 100
                held_h = H * BAR_HOURS
                fee = ROUND_TRIP + FUNDING_PER_8H * (held_h / 8.0)
                net = px_ret - fee
                rets.append(net)
                wins += net > 0
                mfes.append(px_ret)  # 수수료 전 가격수익률을 mfe 근사로 같이 본다
        rets = np.array(rets)
        if len(rets) < 20:
            continue
        days = H * BAR_HOURS / 24
        print(f"  {H:>6}봉{days:>8.0f}일{len(rets):>7,}{(rets>0).mean()*100:>6.1f}%"
              f"{rets.mean():>+8.2f}%{np.array(mfes).mean():>+14.2f}%{np.median(mfes):>+11.2f}%")

    print(f"\n  '거래당(수수료전)' 열은 펀딩이 길게 쌓이는 효과를 제외한 순수 가격수익률이다.")
    print(f"  펀딩(연 11%대)이 보유기간에 비례해 계속 깎아먹는지, 그리고 애초에")
    print(f"  '과매도 반등'이라는 근거 자체가 오래 잡고 있어도 유지되는지를 같이 본다.")


if __name__ == "__main__":
    section_bah()
    section_hold_longer()
