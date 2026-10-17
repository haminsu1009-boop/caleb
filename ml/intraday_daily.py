"""
ml/intraday_daily.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"매일 수익"이 가능한가 — 단타의 일별 손익 분포

지금 전략은 3~4일 스윙이다. 단타로 바꾸면 매일 벌 수 있는지 묻는
것은 두 가지를 따로 확인해야 답할 수 있다.

    1. 짧은 시간축에도 우위가 존재하는가
    2. 존재한다면 그것이 '매일' 플러스로 나타나는가

2번이 핵심이다. 승률 60%짜리 전략이라도 하루에 3거래를 하면
그날 전부 지는 확률이 6.4%다. 거래를 늘려도 사라지지 않는다.
"매일 수익"은 승률의 문제가 아니라 하루 안에 몇 번 독립적으로
베팅할 수 있느냐의 문제다. 그리고 코인은 상관 0.575라 같은 날
여러 종목에 걸어도 독립 베팅이 아니다.

비용이 결정적이다. 5분봉의 우위는 거래당 0.3% 수준인데 왕복
수수료가 0.12%다. 보유가 짧을수록 비용 비중이 커진다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, glob, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

RT = 0.12          # 바이빗 테이커 왕복
TF_MIN = {"5m":5, "15m":15, "30m":30, "1h":60, "4h":240}


def load(sym, tf):
    f = f"data/{sym}_{tf}_all.csv.gz"
    if not os.path.exists(f): return None
    d = pd.read_csv(f, compression="gzip")
    tc = "timestamp" if "timestamp" in d.columns else "datetime"
    d[tc] = pd.to_datetime(d[tc], format="mixed", errors="coerce")
    d = d.dropna(subset=[tc])
    d = d[(d[tc] >= "2017-01-01") & (d[tc] <= "2027-01-01")]
    return d.sort_values(tc).drop_duplicates(tc).rename(columns={tc:"datetime"}).reset_index(drop=True)


def trades(sym, tf, thr, hold):
    g = load(sym, tf)
    if g is None or len(g) < 3000: return pd.DataFrame()
    o = g["open"].astype(float).values
    c = g["close"].astype(float).values
    vs = (c / pd.Series(c).rolling(20).mean().values - 1) * 100
    rows = []; lock = -10**9
    for i in np.where(vs <= thr)[0]:
        if i <= lock or i + 1 + hold >= len(g): continue
        lock = i + hold
        e = o[i+1]
        rows.append({"sym": sym, "dt": g["datetime"].iloc[i],
                     "pnl": (o[i+1+hold]/e - 1)*100 - RT})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--syms", nargs="*", default=None)
    a = ap.parse_args()
    syms = a.syms or [os.path.basename(f).split("_5m_")[0]
                      for f in sorted(glob.glob("data/*_5m_all.csv.gz"))]
    syms = [s for s in syms if s.endswith("USDT")]

    print("=" * 96)
    print(f"  단타의 일별 손익 — {len(syms)}종 ({', '.join(s.replace('USDT','') for s in syms)})")
    print(f"  비용 왕복 {RT}% · 이격 임계값은 각 시간축의 하위 5% 분위")
    print("=" * 96)

    SPEC = [("5m", -1.5, 12, "1시간 보유"), ("5m", -2.0, 24, "2시간 보유"),
            ("15m", -2.5, 8, "2시간 보유"), ("15m", -3.5, 16, "4시간 보유"),
            ("30m", -3.5, 8, "4시간 보유"), ("30m", -5.0, 16, "8시간 보유"),
            ("1h", -5.0, 6, "6시간 보유")]

    for tf, thr, hold, hlab in SPEC:
        allt = []
        for s in syms:
            t = trades(s, tf, thr, hold)
            if not t.empty: allt.append(t)
        if not allt: continue
        T = pd.concat(allt, ignore_index=True)
        T["day"] = pd.DatetimeIndex(T["dt"]).normalize()
        # 하루 단위 집계: 그날 진입한 거래들의 평균 손익
        day = T.groupby("day")["pnl"].agg(["mean","count","sum"])
        n_days = len(day)
        span = (T["dt"].max() - T["dt"].min()).days
        print(f"\n  [{tf} · 이격 {thr}% · {hlab}]")
        print(f"    거래 {len(T):,}건 · 거래한 날 {n_days:,}일 / 전체 {span:,}일 "
              f"({n_days/span*100:.0f}%) · 하루 평균 {day['count'].mean():.1f}건")
        print(f"    거래당 평균 {T.pnl.mean():+.3f}%  ·  승률 {(T.pnl>0).mean()*100:.1f}%")
        print(f"    ▸ 플러스로 끝난 날 {(day['mean']>0).mean()*100:.1f}%  "
              f"·  연속 손실일 최대 {max_streak(day['mean'])}일")
        print(f"    ▸ 하루 손익  중앙 {day['mean'].median():+.3f}%  "
              f"최악 {day['mean'].min():+.1f}%  최고 {day['mean'].max():+.1f}%")


def max_streak(s):
    mx = c = 0
    for x in s.values:
        c = c+1 if x <= 0 else 0
        mx = max(mx, c)
    return mx


if __name__ == "__main__":
    main()
