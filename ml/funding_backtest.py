"""
ml/funding_backtest.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
펀딩비 필터를 실제로 걸고 자본곡선을 돌린다

ml/funding_filter.py는 "거래당 평균수익률"을 구간별로 봤다. 그건
필터를 판정하는 데 부족하다 — 거래당 평균이 올라가도 거래 수가
줄면 복리로는 손해다. 연 165거래에서 연 40거래로 줄면서 거래당이
5%→8%가 되면 자본은 오히려 덜 늘어난다.

그래서 여기서는 필터를 걸어 남은 거래만으로 실제 시뮬레이션을
돌린다. 봇과 같은 조건(복리·배율 2배·진입당 5%·차단기 -25%/30일)
이고, 학습/홀드아웃을 갈라서 본다.

같이 확인하는 것:
  펀딩비가 높을 때 성적이 좋은 게 "신호"인가 "강세장 대리변수"인가.
  강세장이면 펀딩도 높고 반등도 잘 나온다. 그렇다면 펀딩비는
  아무것도 더해주지 않는다 — 이미 아는 것을 다시 말할 뿐이다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from ml.backtest_current_bot import build_all, simulate
from ml.funding_filter import load_funding

TRAIN_END = pd.Timestamp("2024-01-01")
LEV, PT, CB, COOL = 2.0, 0.05, 0.25, 30


def tag(trades, fund):
    """각 거래에 진입 시점의 펀딩비를 붙인다. 데이터 없으면 NaN."""
    out = []
    for t in trades:
        f = fund.get(t["sym"])
        fr = z = np.nan
        if f is not None:
            dt = pd.Timestamp(t["dt"])
            k = f["datetime"].searchsorted(dt, side="right") - 1
            if k >= 0:
                fr, z = f["fr_bps"].iloc[k], f["fr_z"].iloc[k]
        t = dict(t); t["fr_bps"], t["fr_z"] = fr, z
        out.append(t)
    return out


def run(trades, label):
    """전체 / 학습 / 홀드아웃 각각을 복리로 돌린다."""
    res = {}
    for lab, sub, yrs in [
        ("전체", trades, 8.8),
        ("학습", [t for t in trades if pd.Timestamp(t["dt"]) < TRAIN_END], 6.4),
        ("홀드", [t for t in trades if pd.Timestamp(t["dt"]) >= TRAIN_END], 2.5),
    ]:
        if len(sub) < 20:
            res[lab] = None; continue
        r = simulate(sub, LEV, PT, 1.0, CB, COOL, 1e-6, compound=True)
        r["cagr"] = (r["final"] ** (1 / yrs) - 1) * 100 if r["final"] > 0 else -100
        res[lab] = r
    return label, res


def main():
    fund = load_funding()
    trades, have, _ = build_all()
    trades = tag(trades, fund)
    n_have = sum(1 for t in trades if not np.isnan(t["fr_bps"]))

    print("=" * 96)
    print("  펀딩비 필터를 걸고 실제로 굴렸을 때 — 복리 · 배율 2배 · 진입당 5%")
    print("=" * 96)
    print(f"\n  신호 {len(trades):,}건 중 펀딩비 대조 가능 {n_have:,}건 "
          f"(아카이브가 2020년부터)")

    # 펀딩 데이터가 없는 거래(2017~2019)는 필터가 판정할 수 없다.
    # 그 구간을 통째로 살려두면 필터 효과가 희석되고, 버리면 구간이
    # 달라져 비교가 안 된다. 그래서 대조 가능한 거래만으로 통일한다.
    base = [t for t in trades if not np.isnan(t["fr_bps"])]
    print(f"  아래 전부 그 {len(base):,}건 위에서 비교한다 "
          f"({pd.Timestamp(base[0]['dt']).date()}~).\n")

    FILTERS = [
        ("필터 없음", lambda t: True),
        ("펀딩 < 0 (숏 과밀)", lambda t: t["fr_bps"] < 0),
        ("펀딩 < -1bp", lambda t: t["fr_bps"] < -1),
        ("펀딩 > 0 (롱 과밀)", lambda t: t["fr_bps"] > 0),
        ("펀딩 > 1bp", lambda t: t["fr_bps"] > 1),
        ("펀딩 z < -1", lambda t: t["fr_z"] < -1),
        ("펀딩 z > 0", lambda t: t["fr_z"] > 0),
        ("펀딩 z > 1", lambda t: t["fr_z"] > 1),
    ]

    print(f"  {'필터':<20s}{'거래':>7s}{'전체':>10s}{'연복리':>8s}"
          f"{'학습':>10s}{'홀드아웃':>11s}{'홀드연복리':>11s}{'낙폭':>8s}")
    print("  " + "-" * 86)
    for name, fn in FILTERS:
        sub = [t for t in base if fn(t)]
        if len(sub) < 20:
            print(f"  {name:<20s}{len(sub):>7d}   표본 부족")
            continue
        _, r = run(sub, name)
        f, tr, ho = r["전체"], r["학습"], r["홀드"]
        print(f"  {name:<20s}{len(sub):>7d}{f['final']:>9.2f}배{f['cagr']:>7.0f}%"
              f"{(tr['final'] if tr else float('nan')):>9.2f}배"
              f"{(ho['final'] if ho else float('nan')):>10.2f}배"
              f"{(ho['cagr'] if ho else float('nan')):>10.0f}%{f['mdd']*100:>7.1f}%")

    # ── 펀딩 z > 1 이 그냥 강세장 표시인가
    print(f"\n{'='*96}")
    print("  '펀딩 z > 1이 좋다'는 신호인가, 강세장 대리변수인가")
    print("=" * 96)
    hi = [t for t in base if t["fr_z"] > 1]
    d = pd.DataFrame({"dt": [pd.Timestamp(t["dt"]) for t in hi]})
    allд = pd.DataFrame({"dt": [pd.Timestamp(t["dt"]) for t in base]})
    print(f"\n  펀딩 z>1 거래 {len(hi)}건이 어느 해에 몰려 있나")
    a = d.dt.dt.year.value_counts().sort_index()
    b = allд.dt.dt.year.value_counts().sort_index()
    print(f"  {'연도':>6s}{'z>1':>7s}{'전체':>8s}{'비중':>8s}")
    for y in b.index:
        print(f"  {y:>6d}{a.get(y,0):>7d}{b[y]:>8d}{a.get(y,0)/b[y]*100:>7.1f}%")

    # 같은 해에 그냥 진입한 거래와 비교 — 해를 고정하면 차이가 남는가
    print(f"\n  같은 해 안에서 비교하면 (연도 효과 제거)")
    rows = []
    for t in base:
        rows.append({"yr": pd.Timestamp(t["dt"]).year, "hi": t["fr_z"] > 1,
                     "ret": (t["exit_px"] / t["entry_avg"] - 1) * 100})
    df = pd.DataFrame(rows)
    print(f"  {'연도':>6s}{'z>1 거래당':>12s}{'나머지 거래당':>14s}{'차이':>9s}{'n(z>1)':>8s}")
    diffs = []
    for y, g in df.groupby("yr"):
        h, l = g[g.hi], g[~g.hi]
        if len(h) < 5 or len(l) < 5:
            continue
        diffs.append(h.ret.mean() - l.ret.mean())
        print(f"  {y:>6d}{h.ret.mean():>11.2f}%{l.ret.mean():>13.2f}%"
              f"{h.ret.mean()-l.ret.mean():>8.2f}%{len(h):>8d}")
    if diffs:
        print(f"\n  연도별 차이 평균 {np.mean(diffs):+.2f}%p · "
              f"플러스인 해 {sum(x>0 for x in diffs)}/{len(diffs)}")


if __name__ == "__main__":
    main()
