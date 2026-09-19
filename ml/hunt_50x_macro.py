"""
ml/hunt_50x_macro.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
나스닥 필터를 얹으면 1년 50배가 되는가

ml/indicator_backtest.py에서 63개 필터 중 유일하게 필터 없음보다
전체 성적이 나았던 것이 "나스닥 20일 상승"이다(1.50배, 낙폭 25.2%
vs 기준 77.1%). 다만 학습 3.97배 / 홀드아웃 0.39배로 갈렸다.

그래도 "50배가 되느냐"는 따로 물을 값어치가 있다 — 낙폭을 25%로
낮춘다면 같은 위험예산으로 배율을 더 쓸 수 있고, 그게 50배의
경로일 수 있기 때문이다. 그래서 배율·동시보유 격자를 필터 위에
다시 얹어 189개 1년 창 전부에 돌린다.

같이 시험하는 조합
  기준선            필터 없음
  나스닥            나스닥 20일 상승
  나스닥+BTC변동성   + BTC 변동성 z>1 (코인 지표 중 승패를 가장 잘 갈랐다)
  나스닥+BTC추세     + BTC > MA200

⚠️ 나스닥 필터는 홀드아웃에서 무너진다(0.39배). 아래에서 1년
   최대치가 커 보여도 그건 학습 구간의 성질이다. 홀드아웃 성적을
   같은 표에 나란히 찍어 그 점이 가려지지 않게 한다.
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
from ml.hunt_50x import window_stats
from ml.indicator_backtest import _z, TRAIN_END
import ml.coin_indicator_backtest as ci

TARGET = 50.0


def load_macro() -> pd.DataFrame:
    f = "data/indicators/macro_yahoo_finance.csv"
    d = pd.read_csv(f, parse_dates=["date"]).dropna(subset=["date"]).set_index("date")
    m = pd.DataFrame(index=d.index)
    for c in ["nasdaq", "sp500", "vix"]:
        v = pd.to_numeric(d[c], errors="coerce")
        m[f"{c}_r20"] = (v / v.shift(20) - 1) * 100
        m[f"{c}_z"] = _z(v, 90)
    # 주말·공휴일은 값이 없다. 앞선 값을 이어 쓴다 — 미래를 보지 않는다.
    idx = pd.date_range(m.index.min(), m.index.max(), freq="D")
    return m.reindex(idx).ffill()


def main():
    macro = load_macro()
    market, volz, symvol = ci.build_coin_market()
    trades, have, _ = build_all()

    # 거시 + 코인 시장지표를 거래에 붙인다
    out = []
    for t in trades:
        dt = pd.Timestamp(t["dt"])
        t = dict(t)
        k = macro.index.searchsorted(dt, side="right") - 1
        for c in macro.columns:
            t[c] = macro[c].iloc[k] if k >= 0 else np.nan
        j = market.index.searchsorted(dt, side="right") - 1
        for c in ["btc_vol_z", "btc_ma200"]:
            t[c] = market[c].iloc[j] if j >= 0 else np.nan
        out.append(t)
    trades = out

    COMBOS = [
        ("기준선 (필터 없음)",     lambda t: True),
        ("나스닥 20일 상승",       lambda t: t["nasdaq_r20"] > 0),
        ("나스닥 + BTC변동성z>1",  lambda t: t["nasdaq_r20"] > 0 and t["btc_vol_z"] > 1),
        ("나스닥 + BTC>MA200",    lambda t: t["nasdaq_r20"] > 0 and t["btc_ma200"] > 0),
    ]
    LEVS = [2.0, 3.0, 5.0, 8.0]
    PTS = [0.05, 0.10, 0.15, 0.20]

    # 거시 데이터가 있는 거래만으로 통일한다 (2016~ 이므로 사실상 전부)
    base = [t for t in trades if not np.isnan(t.get("nasdaq_r20", np.nan))]
    print("=" * 104)
    print(f"  나스닥 필터 + 배율 격자 → 1년 {TARGET:.0f}배가 되는가")
    print("  복리 · 청산 저가판정 · 189개 1년 창 전부")
    print("=" * 104)
    print(f"\n  대조 가능한 신호 {len(base):,}건 / 전체 {len(trades):,}건\n")

    print(f"  {'조합':<22s}{'배율':>5s}{'동시':>5s}{'거래':>6s}{'1년최대':>10s}"
          f"{'50배확률':>9s}{'중앙':>8s}{'파산':>6s}{'중앙낙폭':>9s}"
          f"{'학습전체':>10s}{'홀드전체':>10s}")
    print("  " + "-" * 100)
    rows = []
    for name, fn in COMBOS:
        sub = [t for t in base if fn(t)]
        if len(sub) < 60:
            print(f"  {name:<22s}  거래 {len(sub)}건 — 표본 부족"); continue
        tr = [t for t in sub if pd.Timestamp(t["dt"]) < TRAIN_END]
        ho = [t for t in sub if pd.Timestamp(t["dt"]) >= TRAIN_END]
        for lev in LEVS:
            for pt in PTS:
                d = window_stats(sub, lev, pt, 0.25, 30, compound=True)
                if d.empty:
                    continue
                r_tr = simulate(tr, lev, pt, 1.0, 0.25, 30, 1e-6, compound=True)
                r_ho = (simulate(ho, lev, pt, 1.0, 0.25, 30, 1e-6, compound=True)
                        if len(ho) >= 20 else None)
                rec = {"combo": name, "lev": lev, "conc": round(1/pt), "n": len(sub),
                       "max": d.mult.max(), "p50": (d.mult >= TARGET).mean()*100,
                       "median": d.mult.median(),
                       "p_bust": (d.mult <= 0.01).mean()*100,
                       "mdd": d.mdd.median()*100,
                       "tr": r_tr["final"],
                       "ho": r_ho["final"] if r_ho else np.nan}
                rows.append(rec)
                print(f"  {name:<22s}{lev:>4.0f}x{rec['conc']:>5d}{len(sub):>6d}"
                      f"{rec['max']:>9.1f}배{rec['p50']:>8.1f}%{rec['median']:>7.2f}배"
                      f"{rec['p_bust']:>5.0f}%{rec['mdd']:>8.0f}%"
                      f"{rec['tr']:>9.1f}배{rec['ho']:>9.2f}배")
        print()

    r = pd.DataFrame(rows)
    os.makedirs("ml/saved_models", exist_ok=True)
    r.to_csv("ml/saved_models/hunt_50x_macro.csv", index=False)

    print("=" * 104)
    hit = r[r["max"] >= TARGET]
    print(f"  1년 {TARGET:.0f}배를 찍은 설정: {len(hit)}개 / {len(r)}개")
    if len(hit):
        ok = hit[(hit.ho >= 1) & (hit.p_bust <= 5)]
        print(f"  그중 홀드아웃에서 돈을 잃지 않고 파산확률 5% 이하: {len(ok)}개")
        if len(ok):
            for _, x in ok.sort_values("max", ascending=False).head(8).iterrows():
                print(f"    {x.combo:<22s} {x.lev:.0f}x/동시{x.conc:.0f} → "
                      f"1년최대 {x['max']:.1f}배 · 중앙 {x['median']:.2f}배 · "
                      f"학습 {x.tr:.1f}배 · 홀드 {x.ho:.2f}배")
        else:
            print("    없다.")
    print("\n  참고 — 홀드아웃 열이 기준선보다 낮으면 그 조합은 2024년 이후")
    print("  구간에서 이미 작동하지 않는다는 뜻이다. 1년최대는 학습 구간의 성질이다.")


if __name__ == "__main__":
    main()
