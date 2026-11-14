"""
ml/backtest_grid.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
지금 코드로 세 가지를 다시 묻는다

  ① 레버리지 × 진입비율(동시보유수) 그리드 — 지금 기본값(2배·5%)이
     실제로 최선인가, 다른 조합이 더 나은가
  ② 낙폭 예산별 최적 — "낙폭 X% 이내에서 최고 수익"을 예산별로 뽑는다
  ③ 분할매수 트리거 재검증 — ml/scale_in.py·ml/scale_in_portfolio.py의
     -5% 선택은 예약노출 버그·영구정지 차단기가 있던 시절에 나온
     결론이다. 고쳐진 지금 모델로 다시 봐서 여전히 최선인지 확인한다

①·②는 build_all()을 한 번만 부르고(진입 규칙은 안 바뀌니) simulate()만
반복한다. ③은 트리거를 바꾸면 거래 자체가 달라지므로 매번 다시
build_all(trigger_pct=...)을 부른다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import argparse
import os
import sys
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from ml.backtest_current_bot import build_all, simulate, TRAIN_END

CB, COOL_DAYS = 0.25, 30
LEVS = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]
PER_TRADES = [0.025, 0.0333, 0.05, 0.0667, 0.10, 0.15, 0.25, 0.333, 0.5, 1.0]   # 40~1 동시


def run_grid(trades, ho_trades):
    rows = []
    yrs_full = (trades[-1]["dt"] - trades[0]["dt"]) / np.timedelta64(1, "D") / 365.25
    yrs_ho = (ho_trades[-1]["dt"] - ho_trades[0]["dt"]) / np.timedelta64(1, "D") / 365.25
    for lev in LEVS:
        for pt in PER_TRADES:
            rf = simulate(trades, lev, pt, 1.0, CB, COOL_DAYS, 1e-6)
            rh = simulate(ho_trades, lev, pt, 1.0, CB, COOL_DAYS, 1e-6)
            cagr_f = (rf["final"] ** (1/yrs_full) - 1) * 100 if not rf["bust"] and rf["final"] > 0 else -100
            cagr_h = (rh["final"] ** (1/yrs_ho) - 1) * 100 if not rh["bust"] and rh["final"] > 0 else -100
            rows.append({
                "lev": lev, "pt": pt, "concurrent": round(1/pt),
                "final_f": 0.0 if rf["bust"] else rf["final"], "cagr_f": cagr_f,
                "mdd_f": rf["mdd"], "mdd_low_f": rf["mdd_low"], "liq_f": rf["liq"],
                "final_h": 0.0 if rh["bust"] else rh["final"], "cagr_h": cagr_h,
                "mdd_h": rh["mdd"], "mdd_low_h": rh["mdd_low"], "liq_h": rh["liq"],
            })
    return pd.DataFrame(rows)


def section_grid(d):
    print("=" * 106)
    print("  [1] 레버리지 × 진입비율(동시보유) 그리드 — 전체구간 기준")
    print("=" * 106)
    print(f"\n  {'배율':>5s}{'동시':>5s}{'전체최종':>10s}{'전체연복리':>9s}{'전체낙폭':>9s}"
          f"{'전체청산':>7s}   {'홀드최종':>9s}{'홀드연복리':>9s}{'홀드낙폭':>9s}")
    print("  " + "-" * 96)
    for _, r in d.iterrows():
        cur = "  ← 기본값" if abs(r.lev-2.0)<1e-6 and abs(r.pt-0.05)<1e-6 else ""
        print(f"  {r.lev:>4.1f}x{r.concurrent:>5.0f}{r.final_f:>9.2f}배{r.cagr_f:>8.0f}%"
              f"{r.mdd_f*100:>8.1f}%{r.liq_f:>7.0f}   {r.final_h:>8.2f}배{r.cagr_h:>8.0f}%"
              f"{r.mdd_h*100:>8.1f}%{cur}")

    print(f"\n  전체구간 CAGR/낙폭 비율(위험 대비 수익) 상위 8개")
    d2 = d[d.mdd_f > 0.02].copy()
    d2["eff"] = d2.cagr_f / (d2.mdd_f * 100)
    top = d2.sort_values("eff", ascending=False).head(8)
    for _, r in top.iterrows():
        print(f"    {r.lev:.1f}x · 동시{r.concurrent:.0f}   전체 {r.final_f:.2f}배(연{r.cagr_f:.0f}%, "
              f"낙폭{r.mdd_f*100:.1f}%)   효율 {r.eff:.2f}")


def section_budget(d):
    print(f"\n{'='*106}")
    print("  [2] 낙폭 예산별 최적 설정 — 전체구간 기준, 그 예산 이내에서 연복리 최고")
    print("=" * 106)
    for budget in (0.15, 0.20, 0.25, 0.30, 0.40, 0.50):
        s = d[d.mdd_f <= budget]
        if s.empty:
            print(f"  낙폭 {budget*100:.0f}% 이내: 해당 설정 없음"); continue
        r = s.loc[s.cagr_f.idxmax()]
        print(f"  낙폭 {budget*100:>3.0f}% 이내 최고: {r.lev:.1f}x · 동시{r.concurrent:.0f}종  →  "
              f"전체 {r.final_f:.2f}배(연복리 {r.cagr_f:.0f}%, 실제낙폭 {r.mdd_f*100:.1f}%)  "
              f"홀드 {r.final_h:.2f}배(연{r.cagr_h:.0f}%)")


def section_trigger():
    print(f"\n{'='*106}")
    print("  [3] 분할매수 트리거 재검증 — 예약노출·재개차단기 고친 지금 모델로")
    print("=" * 106)
    print("  (2배·진입당5%·차단-25%/30일 고정, 트리거%만 바꿔 거래를 다시 만든다)")
    rows = []
    for trig in (-3, -4, -5, -6, -8, -10, -12, -15, -999):
        # -999는 절대 안 닿는 값이라 2차가 안 걸린다 — 진짜 "일괄매수만"
        # 비교 기준선이다. trigger_pct=None을 쓰면 안 된다: build_all의
        # None은 "기본값 그대로"(-5%)로 떨어지므로 -5%와 중복된 행이
        # 나온다(처음 이 버그로 헛갈렸다).
        trades, have, missing = build_all(trigger_pct=trig)
        ho = [t for t in trades if t["dt"] >= TRAIN_END]
        yrs_f = (trades[-1]["dt"] - trades[0]["dt"]) / np.timedelta64(1, "D") / 365.25
        yrs_h = (ho[-1]["dt"] - ho[0]["dt"]) / np.timedelta64(1, "D") / 365.25
        rf = simulate(trades, 2.0, 0.05, 1.0, CB, COOL_DAYS, 1e-6)
        rh = simulate(ho, 2.0, 0.05, 1.0, CB, COOL_DAYS, 1e-6)
        cagr_f = (rf["final"]**(1/yrs_f)-1)*100 if not rf["bust"] else -100
        cagr_h = (rh["final"]**(1/yrs_h)-1)*100 if not rh["bust"] else -100
        n_t2 = sum(1 for t in trades if t["tranche"] == 2)
        label = "일괄매수(2차없음)" if trig == -999 else f"{trig:>4.0f}%"
        rows.append((label, trig, len(trades), n_t2/len(trades)*100, rf["final"], cagr_f,
                    rf["mdd"], rh["final"], cagr_h, rh["mdd"]))
    print(f"\n  {'트리거':10s}{'거래':>7s}{'2차체결율':>9s}{'전체최종':>9s}{'전체연복리':>9s}"
          f"{'전체낙폭':>9s}{'홀드최종':>9s}{'홀드연복리':>9s}")
    print("  " + "-" * 90)
    for label, trig, n, r2, ff, cf, mf, fh, ch, mh in rows:
        cur = "  ← 현재값" if trig == -5 else ""
        print(f"  {label:10s}{n:>7,}{r2:>8.1f}%{ff:>8.2f}배{cf:>8.0f}%{mf*100:>8.1f}%"
              f"{fh:>8.2f}배{ch:>8.0f}%{cur}")


def section_first_frac():
    print(f"\n{'='*106}")
    print("  [3-b] 1차 비율(현재 30%) 재검증 — 트리거는 -5%로 고정")
    print("=" * 106)
    print(f"\n  {'1차비율':9s}{'거래':>7s}{'2차체결율':>9s}{'전체최종':>9s}{'전체연복리':>9s}{'전체낙폭':>9s}")
    print("  " + "-" * 60)
    for frac in (0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7):
        trades, have, missing = build_all(first_frac=frac)
        yrs_f = (trades[-1]["dt"] - trades[0]["dt"]) / np.timedelta64(1, "D") / 365.25
        rf = simulate(trades, 2.0, 0.05, 1.0, CB, COOL_DAYS, 1e-6)
        cagr_f = (rf["final"]**(1/yrs_f)-1)*100 if not rf["bust"] else -100
        n_t2 = sum(1 for t in trades if t["tranche"] == 2)
        cur = "  ← 현재값" if abs(frac-0.3) < 1e-9 else ""
        print(f"  {frac*100:>7.0f}%{len(trades):>7,}{n_t2/len(trades)*100:>8.1f}%"
              f"{rf['final']:>8.2f}배{cagr_f:>8.0f}%{rf['mdd']*100:>8.1f}%{cur}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["grid", "budget", "trigger", "frac"], default=None)
    a = ap.parse_args()

    trades, have, missing = build_all()
    ho_trades = [t for t in trades if t["dt"] >= TRAIN_END]
    print(f"  기준 신호셋: {len(have)}종 · {len(trades):,}건 (그리드/예산 섹션은 이 신호를 재사용)")

    if a.only in (None, "grid", "budget"):
        d = run_grid(trades, ho_trades)
        if a.only in (None, "grid"):
            section_grid(d)
        if a.only in (None, "budget"):
            section_budget(d)
    if a.only in (None, "trigger"):
        section_trigger()
    if a.only in (None, "frac"):
        section_first_frac()


if __name__ == "__main__":
    main()
