"""
ml/cycle_timing.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"사이클 전환점을 안다면" 그 능력의 금전적 가치를 계산한다.

regime_switch.py의 완벽판별(oracle)은 강세=존버 / 약세=추세추종으로
전환했고, 그 결과 존버에 졌다. 하지만 약세장인 줄 안다면 추세추종
같은 간접적 방법이 아니라 그냥 숏을 잡는 게 맞다. 여기서는 전환점을
안다는 가정 아래 다음을 계산한다:

  1. 완벽한 타이밍의 가치 — 강세 롱 / 약세 숏, 레버리지별
  2. 타이밍 오차의 비용   — 전환점을 N일 늦게 알아챘을 때
  3. 절반만 맞힐 때       — 고점은 맞히고 저점은 놓치는 경우 등

사이클 전환점 (BTC 기준, 사후 확정된 실제 날짜):
    2017-12-17  고점  →  약세 시작
    2018-12-15  저점  →  강세 시작
    2021-11-10  고점  →  약세 시작
    2022-11-21  저점  →  강세 시작
    2025-10-06  고점  →  약세 시작 (데이터상 사상 최고 $126,200)

⚠️ 이 날짜들은 사후에 확정된 것이다. 실전에서 같은 정확도로
   맞힐 수 있는지는 이 스크립트가 답하지 않는다. 이 스크립트는
   "맞힌다면 얼마인가"와 "얼마나 정확해야 하는가"만 답한다.

사용법:
    python ml/cycle_timing.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ml.trend_backtest import load, FEE, SLIP

INITIAL = 1_000_000
MONTHLY =   300_000
SYMS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]

# (날짜, 전환후_레짐)  bull=True → 강세 시작
TURNS = [
    ("2017-12-17", False),
    ("2018-12-15", True),
    ("2021-11-10", False),
    ("2022-11-21", True),
    ("2025-10-06", False),
]


def basket_returns() -> pd.Series:
    cols = {}
    for s in SYMS:
        df = load(s, "1d")[["datetime", "close"]]
        c = df["close"].values
        r = np.zeros(len(c)); r[1:] = c[1:] / c[:-1] - 1.0
        cols[s] = pd.Series(r, index=df["datetime"])
    return pd.DataFrame(cols).mean(axis=1, skipna=True).fillna(0.0)


def regime_from_turns(index: pd.DatetimeIndex, lag_days: int = 0) -> pd.Series:
    """전환점 기반 레짐. lag_days만큼 늦게 알아챈 것으로 반영."""
    # 첫 구간은 2017년 상승장 → 강세로 시작
    reg = pd.Series(True, index=index)
    for date, bull in TURNS:
        eff = pd.Timestamp(date) + pd.Timedelta(days=lag_days)
        reg.loc[reg.index >= eff] = bull
    return reg


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
            "mdd": (curve / peak - 1).min() * 100}


def strat_returns(bull: pd.Series, r: pd.Series,
                  bull_lev: float, bear_lev: float,
                  bear_short: bool = True) -> np.ndarray:
    """강세=롱(bull_lev), 약세=숏(bear_lev) 또는 현금"""
    b = bull.reindex(r.index).ffill().fillna(True).values
    pos = np.where(b, bull_lev, (-bear_lev if bear_short else 0.0))
    held = np.roll(pos, 1); held[0] = 0.0
    turn = np.abs(np.diff(np.concatenate([[0.0], pos])))
    return held * r.values - turn * (FEE + SLIP)


def main():
    r = basket_returns()
    idx = r.index
    print("=" * 100)
    print(f"  사이클 전환점을 안다면? — 6종 동일가중, 적립식 {INITIAL:,}원 + 매월 {MONTHLY:,}원")
    print(f"  기간 {idx[0].date()} ~ {idx[-1].date()}")
    print("=" * 100)

    # 기준: 존버
    hold = dca(strat_returns(pd.Series(True, index=idx), r, 1.0, 0.0), idx)
    print(f"\n  [기준] 순수 존버:  {hold['final']:>15,.0f}원   수익률 {hold['ret_pct']:>8.1f}%   MDD {hold['mdd']:>6.1f}%")

    # ── 1. 완벽 타이밍의 가치 ────────────────────────────
    print(f"\n{'='*100}")
    print("  1. 완벽한 타이밍 (전환 당일 반영) — 강세 롱 / 약세 숏")
    print("=" * 100)
    bull0 = regime_from_turns(idx, 0)
    print(f"\n  {'구성':32s}{'최종자산':>17s}{'수익률':>11s}{'MDD':>9s}{'존버대비':>17s}")
    print("  " + "-" * 86)
    combos = [
        ("강세 롱1x / 약세 현금",      1.0, 0.0, False),
        ("강세 롱1x / 약세 숏1x",      1.0, 1.0, True),
        ("강세 롱2x / 약세 숏1x",      2.0, 1.0, True),
        ("강세 롱2x / 약세 숏2x",      2.0, 2.0, True),
        ("강세 롱3x / 약세 숏2x",      3.0, 2.0, True),
        ("강세 롱3x / 약세 숏3x",      3.0, 3.0, True),
        ("강세 롱5x / 약세 숏3x",      5.0, 3.0, True),
    ]
    for label, bl, brl, sh in combos:
        d = dca(strat_returns(bull0, r, bl, brl, sh), idx)
        diff = d["final"] - hold["final"]
        flag = "✅" if diff > 0 else "  "
        print(f"  {label:32s}{d['final']:>16,.0f}원{d['ret_pct']:>10.1f}%{d['mdd']:>8.1f}%"
              f"{diff:>+16,.0f}원 {flag}")

    # ── 2. 타이밍 오차의 비용 ────────────────────────────
    print(f"\n{'='*100}")
    print("  2. 타이밍 오차 비용 — 전환점을 N일 늦게 알아챘을 때 (강세 롱2x / 약세 숏2x)")
    print("=" * 100)
    print(f"\n  {'지연':12s}{'최종자산':>17s}{'수익률':>11s}{'MDD':>9s}{'완벽대비':>17s}")
    print("  " + "-" * 66)
    perfect = dca(strat_returns(regime_from_turns(idx, 0), r, 2.0, 2.0), idx)
    for lag in [0, 7, 14, 30, 60, 90]:
        d = dca(strat_returns(regime_from_turns(idx, lag), r, 2.0, 2.0), idx)
        diff = d["final"] - perfect["final"]
        print(f"  {f'{lag}일 지연':12s}{d['final']:>16,.0f}원{d['ret_pct']:>10.1f}%{d['mdd']:>8.1f}%"
              f"{diff:>+16,.0f}원")

    # ── 3. 절반만 맞히기 ─────────────────────────────────
    print(f"\n{'='*100}")
    print("  3. 절반만 맞힐 때 (강세 롱1x / 약세 숏1x)")
    print("=" * 100)
    top_only = pd.Series(True, index=idx)
    for date, bull in TURNS:
        if not bull:                       # 고점만 맞힘 → 약세 진입은 하되
            top_only.loc[top_only.index >= pd.Timestamp(date)] = False
        else:                              # 저점은 3개월 늦게 알아챔
            eff = pd.Timestamp(date) + pd.Timedelta(days=90)
            top_only.loc[top_only.index >= eff] = True

    bot_only = pd.Series(True, index=idx)
    for date, bull in TURNS:
        if bull:
            bot_only.loc[bot_only.index >= pd.Timestamp(date)] = True
        else:                              # 고점은 3개월 늦게 알아챔
            eff = pd.Timestamp(date) + pd.Timedelta(days=90)
            bot_only.loc[bot_only.index >= eff] = False

    print(f"\n  {'시나리오':34s}{'최종자산':>17s}{'수익률':>11s}{'존버대비':>17s}")
    print("  " + "-" * 80)
    for label, reg in [("고점 정확 / 저점 3개월 지연", top_only),
                       ("저점 정확 / 고점 3개월 지연", bot_only),
                       ("둘 다 정확", bull0)]:
        d = dca(strat_returns(reg, r, 1.0, 1.0), idx)
        diff = d["final"] - hold["final"]
        flag = "✅" if diff > 0 else "  "
        print(f"  {label:34s}{d['final']:>16,.0f}원{d['ret_pct']:>10.1f}%{diff:>+16,.0f}원 {flag}")

    print(f"\n{'='*100}")
    print("  ⚠️ 전환 날짜는 사후 확정치다. 실전에서 같은 정확도로 맞힐 수 있는지는")
    print("     이 계산이 답하지 않는다. '맞힌다면 얼마'와 '얼마나 정확해야 하는가'만 답한다.")
    print("=" * 100)


if __name__ == "__main__":
    main()
