"""
ml/fill_timing.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
백테스트 체결가와 실거래 체결가가 얼마나 다른가

이 세션 내내 남아 있던 미검증 항목이다.
  백테스트  다음 봉 시가에 체결된다고 가정 (resolve_trade의 o[i+1])
  실거래    executor.py가 5분마다 돌면서 rows[-1][4](현재가)로 주문

봉이 확정된 직후 다음 폴링까지 최대 5분이 뜬다. 그 사이 가격이
움직이면 백테스트와 다른 가격에 산다. 문제는 방향이다 — 과매도
신호는 정의상 반등 직전이라, 5분 늦게 사면 체계적으로 비싸게
살 가능성이 있다. 무작위 오차라면 상쇄되지만 편향이면 안 된다.

측정 방법
  1. 4시간봉 종가 ↔ 다음 봉 시가 (연속시장이면 같아야 한다)
  2. 5분봉이 있는 6종(BTC/ETH/BNB/SOL/XRP/ADA)으로 실제 지연 효과
  3. 지연 시간을 늘려가며 편향이 어떻게 변하는가
  4. 청산 쪽도 같이 (진입만 보면 왕복 비용을 절반만 세는 것이다)

결과 요약 (자세한 건 실행해서 볼 것)
  종가↔다음시가 편향  +0.0016%   무시 가능
  5분 지연 진입 편향  +0.2252%   봇이 더 비싸게 산다
  5분 지연 청산 편향  +0.0295%   봇이 더 비싸게 판다(이득)
  왕복 순비용        +0.1957%p  ← ROUND_TRIP 가정에 더해야 할 값

그래서 ml/backtest_current_bot.py의 ROUND_TRIP을 0.20 → 0.40으로
올렸다. 그래도 규칙은 살아남는다(전체 179→135배, 홀드 9.94→9.24배).
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
from bot.oversold import strategy as S
from ml.backtest_current_bot import load, build_all

BAR_HOURS = 4


def load5(sym: str):
    ds = []
    for f in sorted(glob.glob(f"data/{sym}_5m_*.csv.gz")):
        d = pd.read_csv(f, compression="gzip")
        tc = "timestamp" if "timestamp" in d.columns else "datetime"
        d[tc] = pd.to_datetime(d[tc], format="mixed", errors="coerce")
        ds.append(d.dropna(subset=[tc]).rename(columns={tc: "dt"})[["dt", "close"]])
    if not ds:
        return None
    return (pd.concat(ds).sort_values("dt").drop_duplicates("dt")
              .reset_index(drop=True))


def px_at(d5, when: pd.Timestamp):
    """when 시점 이후 첫 5분봉의 종가 = 그 시점 직후 실제로 낼 수 있는 가격."""
    k = np.searchsorted(d5["dt"].values, np.datetime64(when), side="left")
    return float(d5["close"].iloc[k]) if k < len(d5) else None


def main():
    print("=" * 88)
    print("  ① 4시간봉 종가 == 다음 봉 시가 인가 (연속시장이면 같아야 한다)")
    print("=" * 88)
    gaps = []
    for sym in S.SYMBOLS:
        g = load(sym)
        if g is None:
            continue
        c = g["close"].astype(float).values
        o = g["open"].astype(float).values
        ma = pd.Series(c).rolling(S.MA_PERIOD).mean().values
        vs = (c / ma - 1) * 100
        for i in np.where(vs <= S.ENTRY_THRESH)[0]:
            if i + 1 < len(o):
                gaps.append((o[i + 1] / c[i] - 1) * 100)
    gaps = np.array(gaps)
    print(f"\n  과매도 신호 {len(gaps):,}건 (42종)")
    print(f"    편향 {gaps.mean():+.4f}%  ·  |차이| 평균 {np.abs(gaps).mean():.4f}%"
          f"  ·  95분위 {np.percentile(np.abs(gaps),95):.4f}%")
    print(f"    → 편향이 0에 가깝다. 봉 경계 자체는 문제가 아니다.")

    syms = sorted({os.path.basename(f).split("_")[0]
                   for f in glob.glob("data/*_5m_*.csv.gz")})
    syms = [s for s in syms if s in S.SYMBOLS]
    if not syms:
        print("\n  5분봉 데이터가 없어 ②~④를 건너뛴다.")
        return
    D5 = {s: load5(s) for s in syms}
    trades, _, _ = build_all()
    by = {s: [t for t in trades if t["sym"] == s] for s in syms}
    n = sum(len(v) for v in by.values())

    print("\n" + "=" * 88)
    print(f"  ② 폴링 지연이 진입가를 얼마나 바꾸나 — 5분봉 {len(syms)}종 · 거래 {n}건")
    print("=" * 88)
    print(f"\n  {'지연':>8s}{'대조':>8s}{'편향':>10s}{'|차이|평균':>12s}"
          f"{'5분위':>9s}{'95분위':>9s}")
    print("  " + "-" * 58)
    for delay in [5, 10, 15, 30, 60, 120, 240]:
        sl = []
        for s in syms:
            d5 = D5[s]
            if d5 is None:
                continue
            for t in by[s]:
                # 봇은 봉이 확정된 뒤 다음 폴링에 넣는다. 그 폴링 시각을
                # bar_end + (delay-5)분 으로 잡고, 그 직후 5분봉 종가를 본다.
                be = pd.Timestamp(t["dt"]) + pd.Timedelta(hours=BAR_HOURS)
                p = px_at(d5, be + pd.Timedelta(minutes=delay - 5))
                if p and t["e1"] > 0:
                    sl.append((p / t["e1"] - 1) * 100)
        sl = np.array(sl)
        print(f"  {delay:>6d}분{len(sl):>8d}{sl.mean():>9.4f}%{np.abs(sl).mean():>11.4f}%"
              f"{np.percentile(sl,5):>8.3f}%{np.percentile(sl,95):>8.3f}%")
    print(f"\n  '+'는 더 비싸게 샀다는 뜻이다(롱 진입). 편향이 지연을 줄여도")
    print(f"  잘 안 줄어든다 — 반등이 봉 확정 직후 5분 안에 일어나기 때문이다.")

    print("\n" + "=" * 88)
    print("  ③ 청산 쪽 · 왕복 순비용")
    print("=" * 88)
    print(f"\n  {'지연':>8s}{'진입 편향':>12s}{'청산 편향':>12s}{'왕복 순비용':>14s}")
    print("  " + "-" * 48)
    for delay in [5, 15, 30, 60]:
        ein, eout = [], []
        for s in syms:
            d5 = D5[s]
            for t in by[s]:
                be = pd.Timestamp(t["dt"]) + pd.Timedelta(hours=BAR_HOURS)
                p = px_at(d5, be + pd.Timedelta(minutes=delay - 5))
                if p and t["e1"] > 0:
                    ein.append((p / t["e1"] - 1) * 100)
                # 손절은 지정가라 지연 영향이 다르다. 시간청산만 본다.
                if t["reason"] == "time":
                    q = px_at(d5, pd.Timestamp(t["exit_dt"])
                              + pd.Timedelta(minutes=delay - 5))
                    if q and t["exit_px"] > 0:
                        eout.append((q / t["exit_px"] - 1) * 100)
        a, b = np.mean(ein), np.mean(eout)
        print(f"  {delay:>6d}분{a:>11.4f}%{b:>11.4f}%{a-b:>13.4f}%p")
    print(f"\n  왕복 순비용 = 진입 편향 − 청산 편향. 이만큼을 ROUND_TRIP에")
    print(f"  더해야 백테스트가 실거래와 맞는다.")


if __name__ == "__main__":
    main()
