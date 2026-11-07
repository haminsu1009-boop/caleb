"""
ml/whale_backtest.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
고래 지표(미결제약정·상위트레이더 롱숏비율)를 필터로 걸어본다

바이낸스는 증거금 상위 20% 계좌를 따로 집계해 공개한다.
  sum_toptrader_long_short_ratio  고래의 포지션 롱/숏 비율
  count_long_short_ratio          전체 계좌수 롱/숏 비율 (개미)
  sum_open_interest               미결제약정 (잔량)
  sum_taker_long_short_vol_ratio  시장가 매수/매도 체결량 비율

흔히 말하는 "고래는 팔고 개미는 산다"는 두 비율의 괴리다.
그래서 괴리(고래 z − 개미 z)를 직접 만들어 검증한다.

⚠️ 결정적 한계 — 미리 밝힌다
  이 아카이브는 2023-01부터다. 우리 학습 구간(2017~2023)을 거의
  못 덮으므로 "학습에서 찾고 홀드아웃에서 검증"이 구조적으로
  불가능하다. 여기서 뭐가 좋아 보여도 그건 검증이 아니라 관찰이다.
  표본도 작다. 그 점을 감안해서 읽어야 한다.
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
from ml.backtest_current_bot import build_all, simulate

LEV, PT, CB, COOL = 2.0, 0.05, 0.25, 30
Z_WIN = 120          # 4시간봉 120개 = 20일


def load_metrics() -> dict[str, pd.DataFrame]:
    out = {}
    for f in sorted(glob.glob("data/metrics/*_metrics_4h.csv.gz")):
        sym = os.path.basename(f).split("_")[0]
        d = pd.read_csv(f, compression="gzip", parse_dates=["timestamp"])
        d = d.dropna(subset=["timestamp"]).sort_values("timestamp")
        # 종목마다 평상시 수준이 달라 절대값은 비교가 안 된다. z로 통일.
        for src, name in [("sum_toptrader_long_short_ratio", "whale"),
                          ("count_long_short_ratio", "retail"),
                          ("sum_taker_long_short_vol_ratio", "taker")]:
            if src not in d.columns:
                d[name + "_z"] = np.nan; continue
            r = d[src].rolling(Z_WIN, min_periods=30)
            d[name + "_z"] = (d[src] - r.mean()) / r.std()
        # OI는 잔량이라 수준보다 변화율이 뜻이 있다 (20일 전 대비)
        oi = d["sum_open_interest"]
        d["oi_chg"] = (oi / oi.shift(Z_WIN) - 1) * 100
        r = d["oi_chg"].rolling(Z_WIN, min_periods=30)
        d["oi_z"] = (d["oi_chg"] - r.mean()) / r.std()
        # 고래−개미 괴리
        d["gap"] = d["whale_z"] - d["retail_z"]
        out[sym] = d[["timestamp", "whale_z", "retail_z", "taker_z",
                      "oi_chg", "oi_z", "gap"]]
    return out


def tag(trades, met):
    out = []
    for t in trades:
        m = met.get(t["sym"])
        vals = {k: np.nan for k in ["whale_z", "retail_z", "taker_z",
                                    "oi_chg", "oi_z", "gap"]}
        if m is not None:
            dt = pd.Timestamp(t["dt"])
            k = m["timestamp"].searchsorted(dt, side="right") - 1
            if k >= 0:
                # 신호봉 종가 시점에 이미 확정된 값만 쓴다 — 미래를 안 본다
                vals = {c: m[c].iloc[k] for c in vals}
        t = dict(t); t.update(vals)
        out.append(t)
    return out


def main():
    met = load_metrics()
    trades, have, _ = build_all()
    trades = tag(trades, met)
    base = [t for t in trades if not np.isnan(t["whale_z"])]

    print("=" * 92)
    print("  고래 지표 필터 — 복리 · 배율 2배 · 진입당 5%")
    print("=" * 92)
    print(f"\n  신호 {len(trades):,}건 중 메트릭 대조 가능 {len(base):,}건 "
          f"(아카이브가 2023년부터)")
    if len(base) < 50:
        print("  표본 부족 — 중단"); return
    d0, d1 = pd.Timestamp(base[0]['dt']).date(), pd.Timestamp(base[-1]['dt']).date()
    print(f"  기간 {d0} ~ {d1}  ·  아래 전부 이 구간 위에서 비교한다\n")

    yrs = (pd.Timestamp(base[-1]["dt"]) - pd.Timestamp(base[0]["dt"])).days / 365

    FILTERS = [
        ("필터 없음", lambda t: True),
        ("고래 롱 쏠림 (whale z>0.5)",  lambda t: t["whale_z"] > 0.5),
        ("고래 숏 쏠림 (whale z<-0.5)", lambda t: t["whale_z"] < -0.5),
        ("개미 롱 쏠림 (retail z>0.5)", lambda t: t["retail_z"] > 0.5),
        ("개미 숏 쏠림 (retail z<-0.5)",lambda t: t["retail_z"] < -0.5),
        ("고래>개미 괴리 (gap>0.5)",    lambda t: t["gap"] > 0.5),
        ("고래<개미 괴리 (gap<-0.5)",   lambda t: t["gap"] < -0.5),
        ("OI 급증 (oi z>1)",           lambda t: t["oi_z"] > 1),
        ("OI 급감 (oi z<-1)",          lambda t: t["oi_z"] < -1),
        ("시장가 매수 우위 (taker z>0.5)", lambda t: t["taker_z"] > 0.5),
        ("시장가 매도 우위 (taker z<-0.5)",lambda t: t["taker_z"] < -0.5),
    ]

    print(f"  {'필터':<28s}{'거래':>7s}{'승률':>8s}{'거래당':>9s}"
          f"{'최종':>9s}{'연복리':>8s}{'낙폭':>8s}")
    print("  " + "-" * 78)
    rows = []
    for name, fn in FILTERS:
        sub = [t for t in base if fn(t)]
        if len(sub) < 25:
            print(f"  {name:<28s}{len(sub):>7d}   표본 부족")
            continue
        r = simulate(sub, LEV, PT, 1.0, CB, COOL, 1e-6, compound=True)
        px = np.array([(t["exit_px"] / t["entry_avg"] - 1) * 100 for t in sub])
        cagr = (r["final"] ** (1 / yrs) - 1) * 100 if r["final"] > 0 else -100
        rows.append((name, len(sub), r["final"], cagr))
        print(f"  {name:<28s}{len(sub):>7d}{(px>0).mean()*100:>7.1f}%"
              f"{px.mean():>8.2f}%{r['final']:>8.2f}배{cagr:>7.0f}%{r['mdd']*100:>7.1f}%")

    print(f"\n  ── 상관계수 (지표 vs 거래 가격수익률)")
    px = np.array([(t["exit_px"] / t["entry_avg"] - 1) * 100 for t in base])
    for c, lab in [("whale_z", "고래 롱숏 z"), ("retail_z", "개미 롱숏 z"),
                   ("gap", "고래−개미 괴리"), ("oi_z", "OI 변화 z"),
                   ("taker_z", "시장가 매수우위 z")]:
        v = np.array([t[c] for t in base], dtype=float)
        ok = ~np.isnan(v)
        if ok.sum() > 30:
            print(f"    {lab:>16s}  {np.corrcoef(v[ok], px[ok])[0,1]:+.3f}   (n={ok.sum():,})")

    best = max(rows, key=lambda x: x[2])
    nof = [r for r in rows if r[0] == "필터 없음"][0]
    print(f"\n  최고 필터: {best[0]} → {best[2]:.2f}배 "
          f"(필터 없음 {nof[2]:.2f}배 대비 {best[2]/nof[2]:.2f}배)")
    print(f"\n  ⚠️ 이 구간은 홀드아웃과 겹친다. 학습 구간 데이터가 없어")
    print(f"     교차검증이 불가능하므로, 위 숫자는 검증이 아니라 관찰이다.")


if __name__ == "__main__":
    main()
