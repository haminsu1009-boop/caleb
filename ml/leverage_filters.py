"""
ml/leverage_filters.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
배율을 올리려면 무엇을 걸러야 하나

"2배는 너무 낮다, 지표를 조합해서라도 배율을 올려달라"에서 나왔다.

배율을 못 올린 이유는 이 저장소에서 한 가지로 좁혀졌다
(ml/crash_clustering.py). 청산은 평균이 아니라 꼬리가 결정하고,
그 꼬리는 **여러 코인이 한날한시에 무너지는 날**에 몰린다.
2021-05-19 하루에 25~34종목이 동시에 청산됐다. 승률을 올리는 조건을
찾는 것으로는 이걸 못 막는다 — 그날 신호도 평소처럼 "좋아 보인다".

그래서 이 파일은 조건을 **청산 위험 기준으로** 고른다.

    · 평단 대비 최대역행(MAE)의 꼬리 — 하위 1%, 5% 지점
    · 배율별 청산률 — 3·5·10배 청산선을 뚫은 거래 비율
    · 하루 최대 동시 청산 — 청산이 한 날에 몇 건 몰리는가

핵심 후보는 **동시 폭락 필터(breadth)** 다. 신호가 뜬 그 봉에
전 종목 중 몇 %가 같이 과매도인지 센다. 많으면 개별 코인의 과한
하락이 아니라 시장 전체가 무너지는 중이고, 청산이 몰리는 날이 정확히
그런 날이다. 거기에 가격 지표 조합(RSI·거래량 급증·아랫꼬리·200선·
BTC 상태)을 붙여 본다.

펀딩비·미결제약정은 쓰지 않는다. 2020·2023년부터라 2018·2020·2021·
2022년 폭락을 못 거친 데이터로는 "청산을 막는다"를 검증할 수 없다.

고르는 것은 학습구간(~2023, 폭락 네 번 포함), 채점은 홀드아웃(2024~).

사용법:
    python ml/leverage_filters.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, itertools, warnings
warnings.filterwarnings("ignore")
from collections import Counter
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from bot.oversold import strategy as S
from ml.backtest_current_bot import load, simulate, ROUND_TRIP, FUNDING_PER_8H
from ml.per_coin_rules import sim, GLOBAL

TE = pd.Timestamp("2024-01-01")
LEVS = [2, 3, 5, 10]


def liq_line(lev):
    return -100.0 / lev + 0.5


def build():
    """거래와, 신호 봉 시점의 조건값들을 같이 만든다.
    조건은 전부 신호 봉 **종가 시점에 알 수 있는 값**이다."""
    raw = {}
    for sym in S.SYMBOLS:
        g = load(sym)
        if g is None or len(g) < 400:
            continue
        g = g.rename(columns={"datetime": "dt"}).copy()
        g["dt"] = pd.to_datetime(g["dt"])
        raw[sym] = g.reset_index(drop=True)

    # 동시 폭락 비율 — 봉 시각별로 전 종목 중 과매도인 비율
    vs_all = {}
    for sym, g in raw.items():
        c = g["close"].astype(float)
        vs_all[sym] = pd.Series(((c / c.rolling(20).mean() - 1) * 100).values,
                                index=g["dt"])
    V = pd.DataFrame(vs_all)
    breadth = ((V <= S.ENTRY_THRESH).sum(axis=1) / V.notna().sum(axis=1)).fillna(0)
    breadth8 = ((V <= -8.0).sum(axis=1) / V.notna().sum(axis=1)).fillna(0)
    btc_vs = V.get("BTCUSDT")
    btc = raw.get("BTCUSDT")
    btc_r7 = pd.Series((btc["close"].pct_change(42) * 100).values, index=btc["dt"])

    trades = []
    for sym, g in raw.items():
        o, h, l, c = (g[k].astype(float).values for k in ("open", "high", "low", "close"))
        v = g["volume"].astype(float).values
        dt = g["dt"].values
        s = pd.Series(c)
        d = s.diff()
        up = d.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
        dn = (-d.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
        rsi = (100 - 100 / (1 + up / dn.replace(0, np.nan))).values
        vma = pd.Series(v).rolling(20).mean().values
        ma200 = s.rolling(200).mean().values
        body = np.abs(c - o); lw = np.minimum(o, c) - l
        ts = sim(o, h, l, c, dt, *GLOBAL, S.STOP_PCT, sym=sym)
        idx = {pd.Timestamp(x): i for i, x in enumerate(dt)}
        for t in ts:
            i = idx[pd.Timestamp(t["dt"])] - 1        # 신호 봉 (체결은 i+1)
            if i < 0:
                continue
            tt = pd.Timestamp(dt[i])
            t.update(
                breadth=float(breadth.get(tt, 0)), breadth8=float(breadth8.get(tt, 0)),
                rsi=float(rsi[i]), vol=float(v[i] / vma[i]) if vma[i] else 0.0,
                above200=bool(c[i] > ma200[i]) if not np.isnan(ma200[i]) else False,
                wick=bool(lw[i] > 1.5 * max(body[i], 1e-12)),
                btc_vs=float(btc_vs.get(tt, 0)) if btc_vs is not None else 0.0,
                btc_r7=float(btc_r7.get(tt, 0)),
            )
            trades.append(t)
    trades.sort(key=lambda t: t["dt"])
    return trades


FILTERS = {
    "없음 (지금 봇)":              lambda t: True,
    "동시폭락 <10%":              lambda t: t["breadth"] < 0.10,
    "동시폭락 <20%":              lambda t: t["breadth"] < 0.20,
    "동시폭락 <30%":              lambda t: t["breadth"] < 0.30,
    "넓은동시폭락(-8%) <30%":      lambda t: t["breadth8"] < 0.30,
    "BTC 과매도 아님(>-8%)":       lambda t: t["btc_vs"] > -8,
    "BTC 7일 > -10%":            lambda t: t["btc_r7"] > -10,
    "RSI < 25":                  lambda t: t["rsi"] < 25,
    "거래량 3배↑ (투매)":           lambda t: t["vol"] >= 3,
    "아랫꼬리":                    lambda t: t["wick"],
    "200선 위":                   lambda t: t["above200"],
}


def stats(ts):
    if not ts:
        return None
    r = np.array([(t["exit_px"] / t["entry"] - 1) * 100 - ROUND_TRIP
                  - FUNDING_PER_8H * t["bars_h"] / 8 for t in ts])
    d = np.array([t["deployed"] for t in ts])
    m = np.array([t["mae"] for t in ts])
    out = dict(n=len(ts), wr=(r > 0).mean() * 100,
               mu=np.average(r, weights=d),
               p1=np.percentile(m, 1), p5=np.percentile(m, 5))
    for L in LEVS:
        hit = m <= liq_line(L)
        out[f"liq{L}"] = hit.mean() * 100
        days = Counter(pd.Timestamp(t["dt"]).date() for t, h_ in zip(ts, hit) if h_)
        out[f"day{L}"] = max(days.values()) if days else 0
    return out


def main():
    argparse.ArgumentParser().parse_args()
    T = build()
    tr = [t for t in T if t["dt"] < TE]
    ho = [t for t in T if t["dt"] >= TE]

    # 조합: 단일 + 동시폭락 필터 × 나머지 하나
    combos = dict(FILTERS)
    base_keys = [k for k in FILTERS if k.startswith("동시폭락") or k.startswith("넓은")]
    other = [k for k in FILTERS if k not in base_keys and k != "없음 (지금 봇)"]
    for a, b in itertools.product(base_keys, other):
        combos[f"{a} + {b}"] = (lambda fa, fb: lambda t: fa(t) and fb(t))(FILTERS[a], FILTERS[b])

    print("=" * 118)
    print("  배율을 올리려면 무엇을 걸러야 하나 — 청산 꼬리 기준 (학습 ~2023: 폭락 4번 포함)")
    print("  청산선: 2배 -49.5% · 3배 -32.8% · 5배 -19.5% · 10배 -9.5%  (보유 중 저가 기준)")
    print("=" * 118)
    print(f"\n  {'조건':<34s}{'n':>6s}{'승률':>7s}{'거래당':>8s}{'MAE1%':>8s}"
          f"{'3배청산':>8s}{'5배청산':>8s}{'10배청산':>9s}{'5배하루최대':>11s}")
    print("  " + "-" * 110)
    rows = []
    for name, f in combos.items():
        s = stats([t for t in tr if f(t)])
        if not s or s["n"] < 150:
            continue
        rows.append((name, f, s))
    rows.sort(key=lambda x: (x[2]["liq5"], -x[2]["mu"]))
    base = [r for r in rows if r[0] == "없음 (지금 봇)"]
    for name, f, s in base + [r for r in rows if r[0] != "없음 (지금 봇)"][:16]:
        print(f"  {name:<34s}{s['n']:>6,}{s['wr']:>6.1f}%{s['mu']:>+7.2f}%{s['p1']:>7.1f}%"
              f"{s['liq3']:>7.1f}%{s['liq5']:>7.1f}%{s['liq10']:>8.1f}%{s['day5']:>9}건")

    # 포트폴리오 — 청산 적은 상위 후보를 배율별로 실제 복리 운용
    print("\n" + "=" * 118)
    print("  상위 후보를 배율별로 실제 운용 (진입당 1.5% · 총노출 60% · 차단기 20%)")
    print("=" * 118)
    print(f"\n  {'조건':<34s}{'배율':>5s}{'체결':>6s}{'승률':>7s}{'최종':>9s}{'연복리':>7s}"
          f"{'장중낙폭':>9s}{'청산':>5s}{'학습':>8s}{'2024~':>8s}")
    print("  " + "-" * 104)
    picks = base + [r for r in rows if r[0] != "없음 (지금 봇)"
                    and r[2]["mu"] > 0][:5]
    yrs = (T[-1]["dt"] - T[0]["dt"]).days / 365.25
    for name, f, _ in picks:
        sel = [t for t in T if f(t)]
        for L in [2, 3, 5]:
            kw = dict(leverage=float(L), per_trade=0.015, max_gross=0.6, cb=0.20,
                      cool_days=30, min_equity=0.0, compound=True)
            a = simulate(sel, **kw)
            b = simulate([t for t in sel if t["dt"] < TE], **kw)
            c = simulate([t for t in sel if t["dt"] >= TE], **kw)
            cagr = (a["final"] ** (1 / yrs) - 1) * 100 if a["final"] > 0 else -100
            print(f"  {name[:33]:<34s}{L:>4}배{a['n']:>6,}{a['wr']:>6.1f}%{a['final']:>8.2f}배"
                  f"{cagr:>6.0f}%{a['mdd_low']*100:>8.1f}%{a['liq']:>5}{b['final']:>7.2f}배"
                  f"{c['final']:>7.2f}배")
        print("  " + "·" * 104)
    print("=" * 118)


if __name__ == "__main__":
    main()
