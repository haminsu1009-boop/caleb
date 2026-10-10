"""
ml/cross_asset.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
자산군을 넓혀 무상관 베팅을 늘린다

ml 분석에서 우리 샤프 1.41의 한계가 드러났다.
  샤프 = (엣지의 질 0.492) × √(독립 베팅 수)
  연 207거래를 하는데 독립 베팅은 8.2번어치다.
  42종 코인끼리 평균 상관이 0.587이라 분산이 거의 작동하지 않는다.

거래를 더 많이 해도 같은 방향이면 샤프는 안 오른다. 필요한 건
**서로 상관 없는 베팅**이다. 그래서 자산군을 넓힌다.

  코인 42종   4시간봉 (현재)
  미국 주식    일봉 117종
  업비트 KRW  4시간봉 (원화 시장 — 김치 프리미엄 때문에 따로 움직일 수 있다)

같은 과매도 규칙을 그대로 적용한다. 규칙을 자산군마다 다시
최적화하면 그건 과최적화다. 같은 규칙이 다른 시장에서도 통하는지가
그 규칙이 진짜인지 보는 시험이기도 하다.

핵심 측정: 각 자산군 전략의 수익률이 서로 얼마나 상관 없는가.
상관이 낮아야 합쳐서 샤프가 오른다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, glob, argparse, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from bot.oversold import strategy as S

FEE = 0.20          # % 왕복 (주식은 더 싸지만 보수적으로 코인과 같게)
TE = pd.Timestamp("2024-01-01")


def load_csv(path, tcol_candidates=("datetime", "timestamp")):
    d = pd.read_csv(path, compression="gzip")
    tc = next((c for c in tcol_candidates if c in d.columns), None)
    if tc is None:
        return None
    d[tc] = pd.to_datetime(d[tc], format="mixed", errors="coerce")
    d = (d.dropna(subset=[tc]).sort_values(tc).drop_duplicates(tc)
           .rename(columns={tc: "dt"}).reset_index(drop=True))
    for c in ("open", "high", "low", "close"):
        if c not in d.columns:
            return None
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d.dropna(subset=["close"])


def universe(kind):
    out = {}
    if kind == "crypto":
        for s in S.SYMBOLS:
            f = f"data/{s}_4h_all.csv.gz"
            if os.path.exists(f):
                d = load_csv(f)
                if d is not None and len(d) > 400:
                    out[s] = d
    elif kind == "stock":
        for f in sorted(glob.glob("data/stocks/*_1d.csv.gz")):
            s = os.path.basename(f).split("_")[0]
            d = load_csv(f)
            if d is not None and len(d) > 400:
                out[s] = d
    elif kind == "upbit":
        for f in sorted(glob.glob("data/upbit/*_240.csv.gz")):
            s = os.path.basename(f).split("_")[0]
            d = load_csv(f)
            if d is not None and len(d) > 400:
                out[s] = d
    return out


def bb_up(c, n=20, k=1.5):
    m = pd.Series(c).rolling(n).mean()
    sd = pd.Series(c).rolling(n).std()
    return (m + k * sd).values


def trades_of(data, thresh=S.ENTRY_THRESH, hold=60, first=0.30, step=-5.0):
    """과매도 롱 + 분할매수 + 볼린저 상단 청산. 코인과 동일한 규칙."""
    out = []
    for sym, d in data.items():
        o, h, l, c = (d["open"].values, d["high"].values,
                      d["low"].values, d["close"].values)
        dt = d["dt"].values
        n = len(c)
        ma = pd.Series(c).rolling(20).mean().values
        vs = (c / ma - 1) * 100
        up = bb_up(c)
        lock = -10**9
        for i in np.where(vs <= thresh)[0]:
            if i <= lock or i + 1 + hold >= n:
                continue
            e1 = o[i + 1]
            px, w, filled = [e1], [first], 1
            stop = e1 * 0.60
            ex_bar = ex_px = None
            for bar in range(i + 1, i + 1 + hold):
                avg = float(np.average(px, weights=w))
                if l[bar] <= stop:
                    ex_bar, ex_px = bar, stop; break
                if not np.isnan(up[bar]) and h[bar] >= up[bar]:
                    ex_bar, ex_px = bar, up[bar]; break
                if filled < 2 and c[bar] <= e1 * (1 + step / 100) and bar + 1 < n:
                    px.append(o[bar + 1]); w.append(1 - first); filled = 2
                    avg = float(np.average(px, weights=w)); stop = avg * 0.60
            if ex_bar is None:
                ex_bar = i + 1 + hold; ex_px = o[ex_bar]
            avg = float(np.average(px, weights=w))
            out.append({"sym": sym, "dt": pd.Timestamp(dt[i + 1]),
                        "exit": pd.Timestamp(dt[ex_bar]),
                        "ret": (ex_px / avg - 1) * 100 - FEE,
                        "deployed": sum(w)})
            lock = i + (ex_bar - i)
    return sorted(out, key=lambda x: x["dt"])


def curve(ts, per=0.05, lev=1.0, maxc=20, days=None):
    cash = 1.0; open_ = []; out = {}; k = 0
    ts = sorted(ts, key=lambda x: x["dt"])
    if days is None:
        days = pd.date_range(ts[0]["dt"].normalize(), ts[-1]["dt"].normalize(), freq="D")
    for d in days:
        for e, p in [x for x in open_ if x[0] <= d]:
            cash += p
        open_ = [x for x in open_ if x[0] > d]
        while k < len(ts) and ts[k]["dt"] <= d:
            t = ts[k]; k += 1
            if len(open_) >= maxc:
                continue
            m = per * cash * t["deployed"]
            open_.append((t["exit"], max(m * lev * t["ret"] / 100, -m)))
        out[d] = cash
    return pd.Series(out)


def stats(c, lab):
    r = c.pct_change().dropna()
    if len(r) < 100 or c.iloc[-1] <= 0:
        return None
    ann = (1 + r.mean()) ** 365 - 1
    vol = r.std() * np.sqrt(365)
    mdd = (1 - (c / c.cummax()).min()) * 100
    return dict(lab=lab, final=c.iloc[-1], cagr=ann * 100, vol=vol * 100,
                sharpe=(ann - 0.03) / vol, mdd=mdd)


def main():
    argparse.ArgumentParser().parse_args()
    print("=" * 92)
    print("  같은 과매도 규칙을 자산군별로 — 무상관 베팅을 만들 수 있는가")
    print("=" * 92)

    TS, CV = {}, {}
    for kind, lab in [("crypto", "코인 4시간봉"), ("stock", "미국주식 일봉"),
                      ("upbit", "업비트 4시간봉")]:
        data = universe(kind)
        if not data:
            print(f"\n  {lab}: 데이터 없음")
            continue
        t = trades_of(data)
        TS[lab] = t
        print(f"\n  {lab}: {len(data)}종 · 거래 {len(t):,}건 · "
              f"{t[0]['dt'].date()} ~ {t[-1]['dt'].date()}")
        px = np.array([x["ret"] for x in t])
        print(f"    거래당 {px.mean():+.2f}% · 승률 {(px>0).mean()*100:.1f}%")

    # 공통 날짜축
    lo = max(min(x["dt"] for x in t) for t in TS.values())
    hi = min(max(x["dt"] for x in t) for t in TS.values())
    days = pd.date_range(lo.normalize(), hi.normalize(), freq="D")
    print(f"\n  공통 구간 {lo.date()} ~ {hi.date()} ({len(days):,}일)")

    print(f"\n  {'자산군':<16s}{'최종':>9s}{'연복리':>8s}{'변동성':>8s}{'샤프':>7s}{'낙폭':>7s}")
    print("  " + "-" * 56)
    for lab, t in TS.items():
        c = curve([x for x in t if lo <= x["dt"] <= hi], days=days)
        CV[lab] = c
        s = stats(c, lab)
        if s:
            print(f"  {lab:<16s}{s['final']:>8.2f}배{s['cagr']:>7.0f}%"
                  f"{s['vol']:>7.0f}%{s['sharpe']:>7.2f}{s['mdd']:>6.0f}%")

    R = pd.DataFrame({k: v.pct_change().fillna(0) for k, v in CV.items()})
    print(f"\n  ── 전략 간 상관계수 (일별 수익률)")
    print(R.corr().round(3).to_string())

    print(f"\n  ── 균등 배분으로 합치면")
    for ks in [list(CV)[:2], list(CV)]:
        if len(ks) < 2:
            continue
        rr = R[ks].mean(axis=1)
        c = (1 + rr).cumprod()
        s = stats(c, "+".join(ks))
        if s:
            print(f"     {' + '.join(ks):<40s} 샤프 {s['sharpe']:>5.2f} · "
                  f"연복리 {s['cagr']:>4.0f}% · 낙폭 {s['mdd']:>3.0f}%")
    best = max((stats(v, k)["sharpe"] for k, v in CV.items() if stats(v, k)))
    print(f"\n     단독 최고 샤프 {best:.2f}")


if __name__ == "__main__":
    main()
