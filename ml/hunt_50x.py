"""
ml/hunt_50x.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"1년에 50배" 가 가능한 설정이 존재하는가 — 전수 탐색

이 세션에서 검증한 규칙의 연복리는 전체구간 28%, 홀드아웃 71%다.
50배는 연복리 4,900%를 요구한다. 그래도 "어떤 설정으로도 절대
불가능한가"는 따로 확인할 가치가 있다 — 배율을 극단으로 올리거나
진입을 더 깊게 잡으면 특정 1년 구간에서는 터질 수 있기 때문이다.

그래서 묻는 방식을 바꾼다:
    "평균적으로 50배가 되는 설정" (없다는 걸 이미 안다)
    → "어떤 설정이든, 어떤 1년 구간에서든 50배를 찍은 적이 있는가"
      그리고 "그 설정은 나머지 구간에서 무슨 일을 하는가"

두 번째 질문이 핵심이다. 한 구간에서 50배를 찍어도 나머지에서
파산한다면 그건 규칙이 아니라 복권이다.

데이터: 바이낸스 현물(data/*_4h_all.csv.gz), 42종, 2017~2026.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import argparse, os, sys, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from ml.backtest_current_bot import build_all, simulate

WINDOW_DAYS = 365
STEP_DAYS = 15


def window_stats(trades, lev, per_trade, cb, cool):
    """모든 1년 창에 대해 배수 분포를 낸다."""
    t0, t1 = trades[0]["dt"], trades[-1]["dt"]
    starts = pd.date_range(pd.Timestamp(t0),
                           pd.Timestamp(t1) - pd.Timedelta(days=WINDOW_DAYS),
                           freq=f"{STEP_DAYS}D")
    out = []
    for s in starts:
        win = [t for t in trades if s <= t["dt"] < s + pd.Timedelta(days=WINDOW_DAYS)]
        if len(win) < 10:
            continue
        r = simulate(win, lev, per_trade, 1.0, cb, cool, 1e-6)
        out.append({"start": s, "mult": 0.0 if r["bust"] else r["final"],
                    "mdd": r["mdd_low"], "n": r["n"], "liq": r["liq"]})
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=float, default=50.0)
    a = ap.parse_args()

    THRESHOLDS = [-12.26, -15.0, -18.0, -22.0]
    LEVS = [3.0, 5.0, 8.0, 10.0, 15.0, 20.0]
    PER_TRADES = [0.05, 0.10, 0.25, 0.50, 1.0]

    print("=" * 104)
    print(f"  1년에 {a.target:.0f}배가 가능한 설정 탐색 — 바이낸스 현물 42종, 2017~2026")
    print(f"  진입임계값 {len(THRESHOLDS)} × 배율 {len(LEVS)} × 동시보유 {len(PER_TRADES)} = "
          f"{len(THRESHOLDS)*len(LEVS)*len(PER_TRADES)}개 설정 × 1년 창 전부")
    print("=" * 104)

    rows = []
    for thr in THRESHOLDS:
        trades, have, missing = build_all(entry_thresh=thr)
        if len(trades) < 100:
            print(f"\n  진입 {thr}%: 신호 {len(trades)}건 — 표본 부족, 건너뜀")
            continue
        print(f"\n  진입 {thr}% → 신호 {len(trades):,}건 ({len(have)}종)")
        for lev in LEVS:
            for pt in PER_TRADES:
                d = window_stats(trades, lev, pt, 0.25, 30)
                if d.empty:
                    continue
                rows.append({
                    "thr": thr, "lev": lev, "pt": pt, "conc": round(1/pt),
                    "windows": len(d), "max": d.mult.max(), "median": d.mult.median(),
                    "p_target": (d.mult >= a.target).mean() * 100,
                    "p_10x": (d.mult >= 10).mean() * 100,
                    "p_loss": (d.mult < 1).mean() * 100,
                    "p_bust": (d.mult <= 0.01).mean() * 100,
                    "worst": d.mult.min(),
                    "best_start": d.loc[d.mult.idxmax(), "start"],
                })
    r = pd.DataFrame(rows)
    r.to_csv("ml/saved_models/hunt_50x.csv", index=False)

    hit = r[r["max"] >= a.target]
    print(f"\n{'='*104}")
    print(f"  1년 창에서 {a.target:.0f}배를 한 번이라도 찍은 설정: "
          f"{len(hit)}개 / {len(r)}개")
    print("=" * 104)

    if hit.empty:
        print(f"\n  없다. 전 설정·전 구간을 통틀어 1년 최대치는 {r['max'].max():.2f}배다.")
        top = r.sort_values("max", ascending=False).head(10)
        print(f"\n  최대치 상위 10개 설정")
        print(f"  {'진입':>8s}{'배율':>6s}{'동시':>5s}{'1년최대':>9s}{'중앙':>8s}"
              f"{'10배+':>7s}{'손실확률':>8s}{'파산확률':>8s}{'최악':>7s}")
        print("  " + "-" * 74)
        for _, x in top.iterrows():
            print(f"  {x.thr:>7.1f}%{x.lev:>5.1f}x{x.conc:>5.0f}{x['max']:>8.2f}배"
                  f"{x['median']:>7.2f}배{x.p_10x:>6.0f}%{x.p_loss:>7.0f}%"
                  f"{x.p_bust:>7.0f}%{x.worst:>6.2f}배")
    else:
        print(f"\n  {'진입':>8s}{'배율':>6s}{'동시':>5s}{'1년최대':>10s}{'달성확률':>9s}"
              f"{'중앙':>8s}{'손실확률':>8s}{'파산확률':>8s}   최고 시작월")
        print("  " + "-" * 88)
        for _, x in hit.sort_values("max", ascending=False).iterrows():
            print(f"  {x.thr:>7.1f}%{x.lev:>5.1f}x{x.conc:>5.0f}{x['max']:>9.1f}배"
                  f"{x.p_target:>8.1f}%{x['median']:>7.2f}배{x.p_loss:>7.0f}%"
                  f"{x.p_bust:>7.0f}%   {str(x.best_start)[:7]}")

    print(f"\n  참고 — 현재 봇 설정(진입 -12.26%, 2배, 동시20)")
    cur = r[(r.thr == -12.26) & (r.lev == 3.0) & (abs(r.pt - 0.05) < 1e-9)]
    if not cur.empty:
        x = cur.iloc[0]
        print(f"    (그리드 최저 배율 3배 기준) 1년최대 {x['max']:.2f}배 · 중앙 {x['median']:.2f}배 "
              f"· 손실확률 {x.p_loss:.0f}%")
    print(f"\n  저장: ml/saved_models/hunt_50x.csv")


if __name__ == "__main__":
    main()
