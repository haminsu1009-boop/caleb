"""
ml/divergence_scalein.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
강세 다이버전스 + 양봉 확인 + 분할매수 → 볼린저 상단 목표

규칙
  1. 가격은 직전 스윙 저점보다 낮은 저점을 만드는데 RSI는 그때보다
     높다 (강세 다이버전스)
  2. 그 저점 다음 봉이 양봉으로 마감하면 진입 (확인 캔들)
  3. 더 빠지면 2차·3차 추가 (분할매수)
  4. 볼린저 밴드 상단에 닿으면 청산

앞서 ml/rsi_divergence_short.py에서 시험한 "상승 다이버전스 롱"과
다른 점이 셋이다. 그때는 거래당 -0.18%로 졌는데, 차이가 결과를
바꾸는지 확인한다.
  · 양봉 확인을 요구한다 (그때는 다이버전스만 보고 바로 들어갔다)
  · 볼린저 상단을 목표로 판다 (그때는 20봉 시간청산이었다)
  · 1~3차 분할매수를 한다 (그때는 일시 진입이었다)

1분할·2분할·3분할을 따로 보고한다. 분할을 늘리면 평단은 낮아지지만
자본이 더 묶이고, 3차까지 가는 거래는 대체로 더 깊이 빠진 거래다.
어느 쪽이 이기는지는 재봐야 안다.

비교 기준
  · 같은 종목·같은 기간에서 무작위 시점에 같은 방식으로 산 경우
  · 지금 쓰는 과매도 규칙 (이평 -12.26%)

수수료는 진입 회차마다 편도, 청산에 편도를 뗀다. 3분할이면
왕복이 아니라 4번의 편도 수수료가 든다.
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
import ml.short_setups as SS          # load_daily, to_weekly, rsi 재사용

ONE_WAY = 0.20        # % 편도 (테이커 0.055 + 체결지연 여유)
TE = pd.Timestamp("2024-01-01")


def bollinger(c, n=20, k=2.0):
    m = pd.Series(c).rolling(n).mean()
    s = pd.Series(c).rolling(n).std()
    return (m - k * s).values, m.values, (m + k * s).values


def find_signals(d, period=14, k=5, max_gap=90, require_bull=True):
    """강세 다이버전스 + (선택) 양봉 확인. 진입 봉 인덱스를 낸다.

    스윙 저점은 우측 k봉이 지나야 확정된다. 그 지연을 반드시 지켜야
    미래를 보지 않는다 — 확정 시점 이후에 나오는 첫 양봉에서 들어간다.
    """
    c, o, l = d["close"].values, d["open"].values, d["low"].values
    r = SS.rsi(c, period)
    n = len(c)
    piv = []
    for i in range(k, n - k):
        w = l[i - k:i + k + 1]
        if l[i] == w.min() and (w == l[i]).sum() == 1:
            piv.append(i)
    bull = c > o
    sig = []
    for a, b in zip(piv[:-1], piv[1:]):
        if b - a > max_gap or np.isnan(r[a]) or np.isnan(r[b]):
            continue
        if l[b] < l[a] and r[b] > r[a]:          # 가격 낮은 저점, RSI 높은 저점
            j = b + k                             # 스윙 확정 시점
            if not require_bull:
                if j < n:
                    sig.append(j)
                continue
            end = min(j + 5, n)                   # 확정 후 5봉 안에 양봉이 나와야
            while j < end and not bull[j]:
                j += 1
            if j < end and bull[j]:
                sig.append(j)
    return np.array(sorted(set(sig)), dtype=int)


def run_trade(d, i, *, tranches, add_pct, max_hold, stop_pct, bb_n, bb_k):
    """i봉 종가에 판정, i+1 시가에 1차 진입. 더 빠지면 추가.
    볼린저 상단 도달 시 청산, 아니면 max_hold 경과 후 종가 청산."""
    o, h, l, c = (d["open"].values, d["high"].values,
                  d["low"].values, d["close"].values)
    _, _, up = bollinger(c, bb_n, bb_k)
    n = len(c)
    if i + 1 + max_hold >= n:
        return None
    e1 = o[i + 1]
    qty = [1.0]
    px = [e1]
    filled = 1
    next_trigger = e1 * (1 + add_pct / 100)
    exit_bar = exit_px = None
    reason = "time"
    for bar in range(i + 1, i + 1 + max_hold):
        avg = float(np.average(px, weights=qty))
        # 추가 매수 — 종가가 트리거 이하일 때만 (저가만 스쳐서는 안 산다)
        while filled < tranches and c[bar] <= next_trigger:
            px.append(c[bar]); qty.append(1.0)
            filled += 1
            next_trigger = e1 * (1 + add_pct * filled / 100)
            avg = float(np.average(px, weights=qty))
        if stop_pct and l[bar] <= avg * (1 + stop_pct / 100):
            exit_bar, exit_px, reason = bar, avg * (1 + stop_pct / 100), "stop"
            break
        if not np.isnan(up[bar]) and h[bar] >= up[bar]:
            exit_bar, exit_px, reason = bar, up[bar], "bb"
            break
    if exit_bar is None:
        exit_bar, exit_px = i + max_hold, c[i + max_hold]
    avg = float(np.average(px, weights=qty))
    gross = (exit_px / avg - 1) * 100
    fee = ONE_WAY * (filled + 1)          # 진입 회차 + 청산
    return {"dt": pd.Timestamp(d["dt"].values[i]), "ret": gross - fee,
            "filled": filled, "reason": reason, "bars": exit_bar - (i + 1)}


def evaluate(data, signal_fn, *, tranches, add_pct, max_hold, stop_pct,
             bb_n=20, bb_k=2.0):
    rows = []
    for sym, d in data.items():
        idx = signal_fn(d)
        lock = -10**9
        for i in idx:
            if i <= lock:
                continue
            t = run_trade(d, int(i), tranches=tranches, add_pct=add_pct,
                          max_hold=max_hold, stop_pct=stop_pct,
                          bb_n=bb_n, bb_k=bb_k)
            if t:
                t["sym"] = sym
                rows.append(t)
                lock = i + t["bars"]
    return pd.DataFrame(rows)


def summarize(name, d):
    if len(d) < 20:
        return f"  {name:<30s}{len(d):>7d}   표본 부족"
    tr, ho = d[d.dt < TE], d[d.dt >= TE]
    bb = (d.reason == "bb").mean() * 100
    f = lambda x: f"{x.ret.mean():+.2f}%" if len(x) > 10 else "   —"
    return (f"  {name:<30s}{len(d):>7d}{(d.ret>0).mean()*100:>7.1f}%"
            f"{d.ret.mean():>8.2f}%{d.ret.median():>8.2f}%"
            f"{f(tr):>9s}{f(ho):>9s}{bb:>8.0f}%{d.filled.mean():>7.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weekly", action="store_true")
    a = ap.parse_args()

    syms = [s for s in S.SYMBOLS if os.path.exists(f"data/{s}_1d_all.csv.gz")]
    data = {}
    for s in syms:
        d = SS.load_daily(s)
        if d is None or len(d) < 400:
            continue
        data[s] = SS.to_weekly(d) if a.weekly else d
    unit = "주" if a.weekly else "일"
    hold = 8 if a.weekly else 30

    print("=" * 104)
    print(f"  강세 다이버전스 + 양봉 확인 + 분할매수 → 볼린저 상단 목표"
          f"  ({len(data)}종 · {unit}봉)")
    print(f"  편도 수수료 {ONE_WAY}% × (진입 회차 + 1) · 최대 보유 {hold}{unit} · "
          f"볼린저(20, 2)")
    print("=" * 104)
    print(f"\n  {'설정':<30s}{'거래':>7s}{'승률':>8s}{'거래당':>8s}{'중앙':>8s}"
          f"{'학습':>9s}{'홀드아웃':>9s}{'목표도달':>8s}{'평균분할':>8s}")
    print("  " + "-" * 96)

    sig_bull = lambda d: find_signals(d, require_bull=True)
    sig_nobull = lambda d: find_signals(d, require_bull=False)

    for tr_n in (1, 2, 3):
        for add in (-5.0, -8.0):
            if tr_n == 1 and add != -5.0:
                continue
            lab = f"{tr_n}분할" + ("" if tr_n == 1 else f" (추가 {add:.0f}%마다)")
            d = evaluate(data, sig_bull, tranches=tr_n, add_pct=add,
                         max_hold=hold, stop_pct=-40.0)
            print(summarize(lab, d))

    print()
    d = evaluate(data, sig_nobull, tranches=3, add_pct=-5.0,
                 max_hold=hold, stop_pct=-40.0)
    print(summarize("3분할 · 양봉 확인 없음", d))

    # 기준선 — 같은 방식으로 아무 때나
    rng = np.random.default_rng(0)
    sig_rand = lambda d: np.where(rng.random(len(d)) < 0.01)[0]
    d = evaluate(data, sig_rand, tranches=3, add_pct=-5.0,
                 max_hold=hold, stop_pct=-40.0)
    print(summarize("(기준선) 무작위 시점 3분할", d))

    # 지금 쓰는 규칙
    def sig_oversold(d):
        c = d["close"].values
        ma = pd.Series(c).rolling(20).mean().values
        return np.where((c / ma - 1) * 100 <= S.ENTRY_THRESH)[0]
    d = evaluate(data, sig_oversold, tranches=3, add_pct=-5.0,
                 max_hold=hold, stop_pct=-40.0)
    print(summarize("(현재 규칙) 이평 -12.26% 3분할", d))

    print(f"\n  '목표도달' = 볼린저 상단에 닿아서 청산된 비율. "
          f"나머지는 시간 만료나 손절이다.")
    print(f"  '평균분할' = 실제로 몇 차까지 채워졌나.")


if __name__ == "__main__":
    main()
