"""
ml/funding_filter.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
펀딩비가 과매도 규칙의 진입을 걸러주는가

펀딩비는 무기한 선물에서 롱↔숏이 8시간마다 주고받는 돈이다.
플러스면 롱이 숏에게 낸다 = 롱이 과밀하다. 마이너스면 그 반대다.
"한쪽이 과밀하면 되돌림이 잦다"는 건 널리 알려진 관찰이고,
우리 규칙은 이미 되돌림(과매도 반등)에 베팅하는 규칙이다.
그렇다면 진입 시점 펀딩비가 깊은 마이너스일 때 = 숏이 과밀할 때
반등이 더 세야 한다. 이게 검증할 가설이다.

이건 "지표를 더 넣으면 좋아지겠지"가 아니라 반증 가능한 질문이다.
아무 관계가 없으면 그렇게 보고한다.

데이터: data/funding/*.csv.gz (Binance 선물 아카이브, 8시간 간격)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, glob, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from ml.backtest_current_bot import build_all, ROUND_TRIP

TRAIN_END = pd.Timestamp("2024-01-01")


def load_funding() -> dict[str, pd.DataFrame]:
    out = {}
    for f in sorted(glob.glob("data/funding/*.csv.gz")):
        sym = os.path.basename(f).split("_")[0]
        d = pd.read_csv(f, compression="gzip")
        d["datetime"] = pd.to_datetime(d["datetime"], format="mixed", errors="coerce")
        d = d.dropna(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)
        # 8시간마다 한 번. 진입 시점 직전 값을 쓰려면 merge_asof(backward).
        d["fr_bps"] = d["funding_rate"] * 10000          # 만분율 → bp
        # 최근 90일(=270회) 기준 z-score. 종목마다 평상시 수준이 달라서
        # 절대값만 보면 종목 편향이 생긴다.
        r = d["fr_bps"].rolling(270, min_periods=60)
        d["fr_z"] = (d["fr_bps"] - r.mean()) / r.std()
        out[sym] = d[["datetime", "fr_bps", "fr_z"]]
    return out


def attach(trades, fund):
    rows = []
    for t in trades:
        f = fund.get(t["sym"])
        if f is None:
            continue
        dt = pd.Timestamp(t["dt"])
        # 진입 판단은 신호봉 종가(dt) 시점이다. 그 시점에 이미 확정돼
        # 있던 펀딩비만 써야 한다 — 미래를 보면 안 된다.
        k = f["datetime"].searchsorted(dt, side="right") - 1
        if k < 0:
            continue
        px = (t["exit_px"] / t["entry_avg"] - 1) * 100 - ROUND_TRIP
        rows.append({"sym": t["sym"], "dt": dt, "ret": px,
                     "fr_bps": f["fr_bps"].iloc[k], "fr_z": f["fr_z"].iloc[k],
                     "mae": t["mae"]})
    return pd.DataFrame(rows).dropna(subset=["fr_bps"])


def show(d: pd.DataFrame, col: str, label: str, edges):
    print(f"\n  ── {label} 구간별")
    print(f"  {'구간':>18s}{'n':>7s}{'승률':>8s}{'거래당':>10s}{'중앙':>9s}")
    print("  " + "-" * 52)
    d = d.dropna(subset=[col])
    b = pd.cut(d[col], edges)
    for iv, g in d.groupby(b, observed=True):
        if len(g) < 20:
            continue
        print(f"  {str(iv):>18s}{len(g):>7d}{(g.ret>0).mean()*100:>7.1f}%"
              f"{g.ret.mean():>9.2f}%{g.ret.median():>8.2f}%")


def main():
    fund = load_funding()
    trades, have, _ = build_all()
    d = attach(trades, fund)
    syms = sorted(d["sym"].unique())
    print("=" * 76)
    print("  펀딩비 × 과매도 규칙 — 진입 시점 펀딩비가 결과를 예측하는가")
    print("=" * 76)
    print(f"\n  펀딩 데이터 있는 종목 {len(syms)}종 / 전체 {len(have)}종")
    print(f"  대조 가능한 거래 {len(d):,}건 / 전체 {len(trades):,}건")
    print(f"  기간 {d.dt.min().date()} ~ {d.dt.max().date()}")
    print(f"\n  전체 기준선: 승률 {(d.ret>0).mean()*100:.1f}%  거래당 {d.ret.mean():+.2f}%")

    show(d, "fr_bps", "펀딩비 절대값(bp, 8시간당)", [-1e9, -3, -1, 0, 1, 3, 1e9])
    show(d, "fr_z", "펀딩비 z점수(최근 90일 대비)", [-1e9, -2, -1, 0, 1, 2, 1e9])

    # ── 핵심: 학습/홀드아웃을 갈라서 봐야 한다.
    tr, ho = d[d.dt < TRAIN_END], d[d.dt >= TRAIN_END]
    print(f"\n{'='*76}")
    print("  필터를 걸면 어떻게 되는가 (학습 2017~2023 / 홀드아웃 2024~)")
    print("=" * 76)
    print(f"\n  {'필터':>24s}{'학습 n':>8s}{'학습 거래당':>12s}"
          f"{'홀드 n':>8s}{'홀드 거래당':>12s}")
    print("  " + "-" * 64)
    tests = [
        ("필터 없음(현재)",        lambda x: x.index == x.index),
        ("펀딩 < 0 (숏 과밀)",      lambda x: x.fr_bps < 0),
        ("펀딩 < -1bp",            lambda x: x.fr_bps < -1),
        ("펀딩 z < -1",            lambda x: x.fr_z < -1),
        ("펀딩 z < 0",             lambda x: x.fr_z < 0),
        ("펀딩 > 0 (롱 과밀)",      lambda x: x.fr_bps > 0),
        ("펀딩 z > 1",             lambda x: x.fr_z > 1),
    ]
    for name, fn in tests:
        a, b = tr[fn(tr)], ho[fn(ho)]
        print(f"  {name:>24s}{len(a):>8d}{a.ret.mean():>11.2f}%"
              f"{len(b):>8d}{b.ret.mean():>11.2f}%")

    # ── 상관계수 (있으면 얼마나 있는가)
    print(f"\n  상관계수 (펀딩비 vs 거래수익률)")
    for col, lab in [("fr_bps", "절대값"), ("fr_z", "z점수")]:
        x = d.dropna(subset=[col])
        r_all = np.corrcoef(x[col], x.ret)[0, 1]
        xh = ho.dropna(subset=[col])
        r_ho = np.corrcoef(xh[col], xh.ret)[0, 1] if len(xh) > 30 else float("nan")
        print(f"    {lab:>6s}  전체 {r_all:+.3f}   홀드아웃 {r_ho:+.3f}")

    print(f"\n  ⚠️ 종목 {len(syms)}종만 대조했다 — 나머지 30종은 펀딩 데이터가")
    print(f"     아직 없다(bybit/collect_metrics.py + 워크플로로 수집 예정).")


if __name__ == "__main__":
    main()
