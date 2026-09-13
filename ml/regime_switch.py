"""
ml/regime_switch.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
레짐 전환 전략 검증 — "강세장 존버 / 약세장 숏·레버리지"가 실제로 되는가

앞선 분석(dca_trend.py)은 구간을 사후에 잘라 비교했다. "2022년은
약세장이었다"는 건 지나고 나서 아는 것이고, 실전에서는 오늘이 어느
레짐인지 그날 알아야 한다. 이 스크립트는 그 판별을 실시간 가능한
정보만으로 하고, 그 판별이 틀리는 비용까지 포함해 다시 계산한다.

레짐 판별기 (모두 shift(1) — 확정된 과거 봉만 사용):
    BTC_200MA  : BTC 종가 > 200일 이동평균  → 강세
    BTC_50_200 : BTC 50일선 > 200일선        → 강세
    BASKET_MA  : 6종 동일가중 지수 > 200일선 → 강세

전략:
    강세 판정 → 현물 존버 (롱 100%, 레버리지 없음)
    약세 판정 → 추세추종 롱/숏 (레버리지 조절 대상)

비교군:
    - 순수 존버
    - 순수 추세추종
    - 레짐 전환 (레버리지 1x ~ 3x)
    - 사후 완벽 판별(oracle) — 실시간 판별의 손실이 얼마인지 상한선

사용법:
    python ml/regime_switch.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ml.trend_backtest import load, sig_ma_cross, sig_donchian, FEE, SLIP

INITIAL = 1_000_000
MONTHLY =   300_000
SYMS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]


# ══════════════════════════════════════════════════════════════
# 기초 수익률
# ══════════════════════════════════════════════════════════════

def build_panel(sigfn):
    """심볼별 (전략수익, 존버수익)을 날짜 정렬해 반환"""
    S, B = {}, {}
    for s in SYMS:
        df = load(s, "1d")[["datetime", "open", "high", "low", "close"]].copy()
        pos = sigfn(df)
        c = df["close"].values
        r = np.zeros(len(c)); r[1:] = c[1:] / c[:-1] - 1.0
        held = np.roll(pos, 1); held[0] = 0.0
        turn = np.abs(np.diff(np.concatenate([[0.0], pos])))
        S[s] = pd.Series(held * r - turn * (FEE + SLIP), index=df["datetime"])
        B[s] = pd.Series(r, index=df["datetime"])
    S = pd.DataFrame(S); B = pd.DataFrame(B)
    return S.mean(axis=1, skipna=True).fillna(0.0), B.mean(axis=1, skipna=True).fillna(0.0)


def regime_series(kind: str, basket_ret: pd.Series) -> pd.Series:
    """True=강세. 모두 shift(1)로 미래참조 없음."""
    if kind == "BASKET_MA":
        idx = (1 + basket_ret).cumprod()
        ma = idx.rolling(200).mean()
        return (idx > ma).shift(1).fillna(False)

    btc = load("BTCUSDT", "1d")[["datetime", "close"]].set_index("datetime")["close"]
    if kind == "BTC_200MA":
        sig = btc > btc.rolling(200).mean()
    elif kind == "BTC_50_200":
        sig = btc.rolling(50).mean() > btc.rolling(200).mean()
    else:
        raise ValueError(kind)
    return sig.shift(1).reindex(basket_ret.index).ffill().fillna(False)


def oracle_regime(basket_ret: pd.Series, fwd: int = 60) -> pd.Series:
    """사후 완벽 판별 — 향후 fwd일 수익이 양수면 강세. 실전 불가, 상한선 참고용."""
    idx = (1 + basket_ret).cumprod()
    fut = idx.shift(-fwd) / idx - 1
    return (fut > 0).fillna(False)


# ══════════════════════════════════════════════════════════════
# 적립식 시뮬레이션
# ══════════════════════════════════════════════════════════════

def dca(returns: np.ndarray, index) -> dict:
    months = pd.DatetimeIndex(index).to_period("M")
    cap = 0.0; contributed = 0.0; last = None; curve = []
    for i, r in enumerate(returns):
        m = months[i]
        if last is None:
            cap += INITIAL; contributed += INITIAL; last = m
        elif m != last:
            cap += MONTHLY; contributed += MONTHLY; last = m
        cap = max(cap * (1.0 + r), 0.0)
        curve.append(cap)
    curve = np.array(curve)
    peak = np.maximum.accumulate(np.maximum(curve, 1e-9))
    return {"final": cap, "contributed": contributed,
            "ret_pct": (cap / contributed - 1) * 100 if contributed else 0.0,
            "mdd": (curve / peak - 1).min() * 100, "curve": curve}


def switched(bull: pd.Series, hold_r: pd.Series, trend_r: pd.Series,
             bear_lev: float) -> np.ndarray:
    """강세=존버, 약세=추세추종(레버리지 적용)"""
    b = bull.reindex(hold_r.index).fillna(False).values
    return np.where(b, hold_r.values, trend_r.values * bear_lev)


# ══════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="MA교차(50,200)")
    a = ap.parse_args()

    SIG = {"MA교차(50,200)": lambda d: sig_ma_cross(d, 50, 200),
           "MA교차(20,100)": lambda d: sig_ma_cross(d, 20, 100),
           "Donchian(55,20)": lambda d: sig_donchian(d, 55, 20)}
    trend_r, hold_r = build_panel(SIG[a.strategy])
    idx = hold_r.index

    print("=" * 100)
    print(f"  레짐 전환 검증 — 강세장 존버 / 약세장 추세추종({a.strategy})")
    print(f"  적립식 초기 {INITIAL:,}원 + 매월 {MONTHLY:,}원   기간 {idx[0].date()} ~ {idx[-1].date()}")
    print("=" * 100)

    base_hold  = dca(hold_r.values, idx)
    base_trend = dca(trend_r.values, idx)

    print(f"\n  {'전략':34s}{'최종자산':>16s}{'수익률':>10s}{'MDD':>9s}{'강세비중':>9s}{'존버대비':>15s}")
    print("  " + "-" * 94)
    print(f"  {'[A] 순수 존버':34s}{base_hold['final']:>15,.0f}원{base_hold['ret_pct']:>9.1f}%"
          f"{base_hold['mdd']:>8.1f}%{'100%':>9s}{'—':>15s}")
    print(f"  {'[B] 순수 추세추종':34s}{base_trend['final']:>15,.0f}원{base_trend['ret_pct']:>9.1f}%"
          f"{base_trend['mdd']:>8.1f}%{'0%':>9s}{base_trend['final']-base_hold['final']:>+14,.0f}원")

    print()
    for kind in ["BTC_200MA", "BTC_50_200", "BASKET_MA"]:
        bull = regime_series(kind, hold_r)
        share = bull.reindex(idx).fillna(False).mean() * 100
        for lev in [1.0, 1.5, 2.0, 3.0]:
            r = switched(bull, hold_r, trend_r, lev)
            d = dca(r, idx)
            diff = d["final"] - base_hold["final"]
            flag = "✅" if diff > 0 else "  "
            print(f"  {f'[{kind}] 약세 레버 {lev:.1f}x':34s}{d['final']:>15,.0f}원{d['ret_pct']:>9.1f}%"
                  f"{d['mdd']:>8.1f}%{share:>8.0f}%{diff:>+14,.0f}원 {flag}")
        print()

    # 사후 완벽 판별 (상한선)
    orc = oracle_regime(hold_r)
    share = orc.mean() * 100
    for lev in [1.0, 2.0]:
        r = switched(orc, hold_r, trend_r, lev)
        d = dca(r, idx)
        diff = d["final"] - base_hold["final"]
        print(f"  {f'[사후완벽판별] 약세 레버 {lev:.1f}x':34s}{d['final']:>15,.0f}원{d['ret_pct']:>9.1f}%"
              f"{d['mdd']:>8.1f}%{share:>8.0f}%{diff:>+14,.0f}원  ⚠️실전불가")

    print()
    print("  ⚠️ '사후완벽판별'은 향후 60일 수익을 미리 아는 가정 — 실전에서는 불가능하다.")
    print("     실시간 판별기와의 격차가 곧 '레짐을 못 맞히는 비용'이다.")

    # 최근 하락장 구간만
    print(f"\n{'='*100}")
    print("  구간별: 사이클 고점 이후 (2025-10-06 ~ )")
    print("=" * 100)
    m = idx >= "2025-10-06"
    sub_idx = idx[m]
    h = dca(hold_r.values[m], sub_idx)
    t = dca(trend_r.values[m], sub_idx)
    print(f"  {'순수 존버':30s}{h['final']:>14,.0f}원{h['ret_pct']:>9.1f}%{h['mdd']:>8.1f}%")
    print(f"  {'순수 추세추종 1x':30s}{t['final']:>14,.0f}원{t['ret_pct']:>9.1f}%{t['mdd']:>8.1f}%")
    for lev in [1.5, 2.0, 3.0]:
        d = dca(trend_r.values[m] * lev, sub_idx)
        print(f"  {f'순수 추세추종 {lev:.1f}x':30s}{d['final']:>14,.0f}원{d['ret_pct']:>9.1f}%{d['mdd']:>8.1f}%")

    # 현재 레짐
    print(f"\n{'='*100}")
    print("  현재 레짐 판정 (최신 데이터 기준)")
    print("=" * 100)
    for kind in ["BTC_200MA", "BTC_50_200", "BASKET_MA"]:
        bull = regime_series(kind, hold_r).reindex(idx).ffill()
        cur = bull.iloc[-1]
        print(f"    {kind:14s}: {'강세(존버)' if cur else '약세(추세추종)'}")


if __name__ == "__main__":
    main()
