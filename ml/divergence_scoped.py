"""
ml/divergence_scoped.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
범위를 좁힌 다이버전스 재검증

  상승 다이버전스 → 전 종목(42종) 롱
  하락 다이버전스 → 비트코인만 숏, RSI 격차 10p 이상

앞선 검증에서 비트코인 단독은 신호가 6~16건뿐이라 판정을 못 했다.
스윙 판정폭(k)과 최대 간격을 넓혀 표본을 확보하고 다시 본다.
표본이 작으면 작다고 밝히고, 억지로 결론내지 않는다.

숏은 반드시 자본곡선까지 본다. 앞서 하락 다이버전스(주봉 42종)가
거래당 +2.73%·승률 65%인데도 자본은 0.47배로 무너졌다 — 숏은
이익이 +100%로 막히고 손실은 무한이라(최악 -173.7%) 평균만 보면
안 된다.
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
import ml.short_setups as SS

FEE = 0.40
TE = pd.Timestamp("2024-01-01")


def divergence(d, *, bullish, period=14, k=5, gap=0.0, max_gap=120):
    """스윙 간 다이버전스. gap은 RSI 격차 최소 요구치(포인트).

    스윙은 우측 k봉이 지나야 확정된다. 진입 시점을 b+k로 미뤄
    미래를 보지 않는다.
    """
    c, o, h, l = (d["close"].values, d["open"].values,
                  d["high"].values, d["low"].values)
    r = SS.rsi(c, period)
    src = l if bullish else h
    n = len(c)
    piv = []
    for i in range(k, n - k):
        w = src[i - k:i + k + 1]
        ok = (src[i] == w.min()) if bullish else (src[i] == w.max())
        if ok and (w == src[i]).sum() == 1:
            piv.append(i)
    want_bar = (c > o) if bullish else (c < o)     # 확인 캔들
    out = []
    for a, b in zip(piv[:-1], piv[1:]):
        if b - a > max_gap or np.isnan(r[a]) or np.isnan(r[b]):
            continue
        if bullish:
            hit = src[b] < src[a] and (r[b] - r[a]) >= gap
        else:
            hit = src[b] > src[a] and (r[a] - r[b]) >= gap
        if not hit:
            continue
        j = b + k
        end = min(j + 5, n)
        while j < end and not want_bar[j]:
            j += 1
        if j < end and want_bar[j]:
            out.append(j)
    return np.array(sorted(set(out)), dtype=int)


def trades(d, idx, hold, is_long):
    o, c, dt = d["open"].values, d["close"].values, d["dt"].values
    n = len(c)
    out, lock = [], -10**9
    for i in idx:
        if i <= lock or i + 1 + hold >= n:
            continue
        e = o[i + 1]
        ex = c[i + hold]
        ret = (ex / e - 1) * 100 if is_long else -(ex / e - 1) * 100
        out.append({"dt": pd.Timestamp(dt[i + 1]),
                    "exit": pd.Timestamp(dt[i + hold]), "ret": ret - FEE})
        lock = i + hold
    return out


def equity(ts, per, maxc):
    cash = 1.0; open_ = []; peak = 1.0; mdd = 0.0; n = 0; w = 0
    for t in sorted(ts, key=lambda x: x["dt"]):
        done = [p for e, p in open_ if e <= t["dt"]]
        open_ = [(e, p) for e, p in open_ if e > t["dt"]]
        for p in done:
            cash += p
        peak = max(peak, cash); mdd = max(mdd, 1 - cash / peak)
        if cash <= 1e-9:
            return dict(final=0.0, mdd=1.0, n=n, wr=0.0)
        if len(open_) >= maxc:
            continue
        m = per * cash
        open_.append((t["exit"], max(m * t["ret"] / 100, -m)))
        n += 1; w += t["ret"] > 0
    for _, p in open_:
        cash += p
    return dict(final=cash, mdd=mdd, n=n, wr=w / max(n, 1) * 100)


def show(name, ts, per=0.30, maxc=3):
    if len(ts) < 15:
        print(f"  {name:<34s}{len(ts):>6d}   표본 부족")
        return
    d = pd.DataFrame(ts)
    tr, ho = d[d.dt < TE], d[d.dt >= TE]
    e = equity(ts, per, maxc)
    eh = equity([t for t in ts if t["dt"] >= TE], per, maxc)
    f = lambda x: f"{x.ret.mean():+.2f}%" if len(x) > 8 else "   —"
    print(f"  {name:<34s}{len(ts):>6d}{(d.ret>0).mean()*100:>6.1f}%{d.ret.mean():>8.2f}%"
          f"{f(tr):>9s}{f(ho):>9s}{e['final']:>8.2f}배{eh['final']:>8.2f}배"
          f"{e['mdd']*100:>7.0f}%{d.ret.min():>8.0f}%")


def load(sym, weekly):
    d = SS.load_daily(sym)
    if d is None or len(d) < 400:
        return None
    return SS.to_weekly(d) if weekly else d


def main():
    argparse.ArgumentParser().parse_args()
    syms = [s for s in S.SYMBOLS if os.path.exists(f"data/{s}_1d_all.csv.gz")]

    for weekly in (False, True):
        unit = "주" if weekly else "일"
        holds = (4, 8) if weekly else (5, 10, 20)
        data = {s: load(s, weekly) for s in syms}
        data = {k: v for k, v in data.items() if v is not None}

        print("\n" + "=" * 104)
        print(f"  상승 다이버전스 · 전 종목({len(data)}종) 롱 — {unit}봉 · 수수료 {FEE}%")
        print("=" * 104)
        print(f"\n  {'설정':<34s}{'거래':>6s}{'승률':>6s}{'거래당':>8s}{'학습':>9s}"
              f"{'홀드아웃':>9s}{'자본30%':>8s}{'홀드':>8s}{'낙폭':>7s}{'최악':>8s}")
        print("  " + "-" * 100)
        for hold in holds:
            for gap in (0.0, 5.0, 10.0):
                ts = []
                for s, d in data.items():
                    ts += trades(d, divergence(d, bullish=True, gap=gap), hold, True)
                show(f"{hold}{unit} 보유 · RSI 격차 ≥{gap:.0f}p", ts)

        print("\n" + "=" * 104)
        print(f"  하락 다이버전스 · 비트코인만 숏 — {unit}봉 · RSI 격차 10p 이상")
        print("=" * 104)
        print(f"\n  {'설정':<34s}{'거래':>6s}{'승률':>6s}{'거래당':>8s}{'학습':>9s}"
              f"{'홀드아웃':>9s}{'자본30%':>8s}{'홀드':>8s}{'낙폭':>7s}{'최악':>8s}")
        print("  " + "-" * 100)
        btc = data.get("BTCUSDT")
        if btc is None:
            print("  BTC 데이터 없음")
            continue
        for hold in holds:
            for k in (3, 5, 8):
                idx = divergence(btc, bullish=False, k=k, gap=10.0)
                show(f"{hold}{unit} 보유 · 스윙폭 k={k}", trades(btc, idx, hold, False))
        # 비교: 같은 기간 BTC 무작위 숏
        rng = np.random.default_rng(0)
        ridx = np.where(rng.random(len(btc)) < 0.02)[0]
        for hold in holds:
            show(f"(기준선) BTC 무작위 숏 · {hold}{unit}",
                 trades(btc, ridx, hold, False))


if __name__ == "__main__":
    main()


# ── 왜 승률이 62%인가 (2026-09 조사) ─────────────────────────────
#
# 과매도 롱 82% · 주봉 숏 83% 옆에서 다이버전스만 62%다. 이유는
# 진 거래를 뜯어보면 나온다.
#
#   이긴 41건: 평균 +12.12% · 보유 중 최고 순행 중앙 +18.45%
#   진   25건: 평균  -8.31% · 보유 중 최고 순행 중앙  +3.30%
#
# 진 거래의 92%가 보유 중 한 번은 수수료를 넘겼다가 되돌아왔다.
# 10일 고정 시간청산이 그 되돌림을 그대로 맞는 구조다.
#
# 고치는 방법은 둘 다 있었다.
#   볼린저 1.5σ 목표청산   승률 62%→70% (홀드아웃 69%→79%)
#                          그런데 거래당 4.38%→1.87%. 이익을 일찍 자른다.
#   RSI 격차 ≥10p          승률 62%→69%, 거래당 4.38%→6.28%. 둘 다 개선.
#
# 격차 10p가 모듈 성적으로는 명백히 낫다. 그런데 포트폴리오에 넣으면
# 더 나빠진다 — 거래가 66건에서 32건으로 반토막 나기 때문이다.
#
#   구성              전체      낙폭   샤프  1년손실  최악1년
#   다이버 없음       7.74배   21.6%  1.13   22%    0.94
#   격차 ≥8p (현재)  21.52배   21.6%  1.38    1%    1.04
#   격차 ≥10p       11.23배   21.6%  1.16   15%    0.94
#
# 그래서 8p를 유지한다. 모듈 하나의 승률을 올리는 것과 계좌를
# 지키는 것은 다른 문제다. 롱·숏·다이버의 일간 수익 상관은
# 각각 0.003 / -0.001 / -0.001 로 사실상 0이다. 승률 62%짜리가
# 1년 손실확률을 22%에서 1%로 낮추는 건 잘 맞혀서가 아니라
# 다른 때에 맞히기 때문이다. 포트폴리오 전체 승률은 어느 쪽이든
# 81%로 같다 — 거래 수의 대부분이 롱이라서다.
#
# 주의: 비중 40%는 매끄러운 구간이 아니다(30% 12.45배·손실확률 10%
# → 40% 21.52배·1% → 50% 22.47배·4%). 차단기 발동 시점이 갈리는
# 자리라 1%라는 숫자를 액면 그대로 믿으면 안 된다. 40~60% 구간의
# 4~5%가 더 정직한 값이다. 그리고 다이버 최악 거래는 -36.1%였으므로
# 비중 40%면 한 건에 계좌의 14.4%가 꽂힌다.
