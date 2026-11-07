"""
ml/limit_execution.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
① 지정가 실행 — 체결 지연 비용을 줄일 수 있는가

ml/fill_timing.py에서 시장가 체결의 지연 비용을 +0.196%p로 실측했다.
봇이 5분마다 도는 사이 과매도 반등이 시작돼 비싸게 사는 것이다.

지정가로 걸면 그 비용을 없앨 수 있다. 대신 체결이 안 되면 신호를
통째로 놓친다. 이 교환이 남는지 5분봉으로 잰다.

  · 지정가를 신호봉 종가(또는 그보다 낮은 값)에 건다
  · 다음 N분 안에 저가가 그 값에 닿으면 체결로 본다
  · 안 닿으면 미체결 — 그 신호는 버린다
  · 체결된 거래의 수익과 놓친 거래의 수익을 각각 집계한다

메이커 수수료도 반영한다(바이빗 기준 테이커 0.055% → 메이커 0.02%).

5분봉이 있는 6종(BTC/ETH/BNB/SOL/XRP/ADA)으로만 잰다. 표본이
작으므로 방향을 보는 용도다.
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
from ml.backtest_current_bot import build_all, load

TAKER, MAKER = 0.055, 0.02      # % 편도


def load5(sym):
    ds = []
    for f in sorted(glob.glob(f"data/{sym}_5m_*.csv.gz")):
        d = pd.read_csv(f, compression="gzip")
        tc = "timestamp" if "timestamp" in d.columns else "datetime"
        d[tc] = pd.to_datetime(d[tc], format="mixed", errors="coerce")
        ds.append(d.dropna(subset=[tc]).rename(columns={tc: "dt"})
                  [["dt", "open", "high", "low", "close"]])
    if not ds:
        return None
    return (pd.concat(ds).sort_values("dt").drop_duplicates("dt")
              .reset_index(drop=True))


def main():
    ap = argparse.ArgumentParser(); ap.parse_args()
    syms = sorted({os.path.basename(f).split("_")[0]
                   for f in glob.glob("data/*_5m_*.csv.gz")})
    syms = [s for s in syms if s in S.SYMBOLS]
    D5 = {s: load5(s) for s in syms}
    D5 = {k: v for k, v in D5.items() if v is not None}
    trades, _, _ = build_all()
    by = {s: [t for t in trades if t["sym"] == s] for s in D5}
    n = sum(len(v) for v in by.values())

    print("=" * 92)
    print(f"  지정가 실행 — 5분봉 {len(D5)}종 · 거래 {n}건")
    print(f"  테이커 {TAKER}% vs 메이커 {MAKER}% (편도)")
    print("=" * 92)

    print(f"\n  {'지정가':>10s}{'대기':>7s}{'체결률':>8s}{'체결 거래당':>12s}"
          f"{'미체결 거래당':>14s}{'실효 거래당':>12s}{'시장가 대비':>12s}")
    print("  " + "-" * 82)

    # 시장가 기준선: 봉 확정 5분 뒤 가격에 사고, 20봉 뒤 종가에 판다
    base_rets = []
    for s, d5 in D5.items():
        t5 = d5["dt"].values; c5 = d5["close"].values
        for t in by[s]:
            be = pd.Timestamp(t["dt"]) + pd.Timedelta(hours=4)
            k = np.searchsorted(t5, np.datetime64(be), side="left")
            if k >= len(t5):
                continue
            e = float(c5[k])
            base_rets.append((t["exit_px"] / e - 1) * 100 - TAKER * 2)
    base = np.mean(base_rets)
    print(f"  {'(기준) 시장가':>10s}{'':>7s}{'100%':>8s}{'':>12s}{'':>14s}"
          f"{base:>11.2f}%{'':>12s}")

    for off in (0.0, -0.2, -0.5, -1.0):
        for wait in (30, 60, 240):
            filled, missed = [], []
            for s, d5 in D5.items():
                t5 = d5["dt"].values
                lo5 = d5["low"].values
                for t in by[s]:
                    be = pd.Timestamp(t["dt"]) + pd.Timedelta(hours=4)
                    k = np.searchsorted(t5, np.datetime64(be), side="left")
                    if k >= len(t5):
                        continue
                    # 지정가 = 신호봉 종가 × (1 + off%)
                    limit = t["e1"] * (1 + off / 100)
                    end = np.searchsorted(t5, np.datetime64(
                        be + pd.Timedelta(minutes=wait)), side="left")
                    seg = lo5[k:end]
                    hit = len(seg) > 0 and seg.min() <= limit
                    ret = (t["exit_px"] / limit - 1) * 100 - MAKER - TAKER
                    if hit:
                        filled.append(ret)
                    else:
                        # 놓친 거래 — 시장가로 샀다면 얻었을 수익
                        e = float(d5["close"].iloc[k])
                        missed.append((t["exit_px"] / e - 1) * 100 - TAKER * 2)
            if not filled:
                continue
            fr = len(filled) / (len(filled) + len(missed))
            # 실효 = 체결된 것만 거래한다. 미체결은 자본이 놀았다(수익 0).
            eff = np.mean(filled) * fr
            print(f"  {off:>9.1f}%{wait:>6d}분{fr*100:>7.0f}%{np.mean(filled):>11.2f}%"
                  f"{(np.mean(missed) if missed else 0):>13.2f}%{eff:>11.2f}%"
                  f"{eff-base:>11.2f}%p")

    print(f"""
  ── 읽는 법
     '실효 거래당' = 체결된 거래의 수익 × 체결률. 미체결이면 그 신호는
     자본을 안 쓰고 지나간 것이므로 수익 0으로 친다.

     '미체결 거래당'이 '체결 거래당'보다 높으면, 지정가가 걸러낸 것이
     하필 좋은 거래였다는 뜻이다. 그게 지정가의 숨은 비용이다.
""")


if __name__ == "__main__":
    main()
