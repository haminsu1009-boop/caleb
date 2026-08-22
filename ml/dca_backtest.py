"""
ml/dca_backtest.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BTC 1h 후보 신호로 적립식(DCA) 시뮬레이션
초기 100만원 + 매월 30만원 적립, 2017년 ~ 현재

비교 대상 4가지:
  V0. Buy & Hold DCA         — 매월 그냥 BTC 매수 (기준선)
  V1. 마이닝 룰 단독          — ml/mine_and_validate.py 최상위 후보 (LONG)
                                ⚠️ 2017~2024는 그 룰을 "찾아낸" 구간(학습) —
                                   여기 구간 성과는 참고용, 진짜 검증은 2025~
  V2. 마이닝 룰 + 레짐필터    — V1 + 일봉 200일선 위에서만 진입 (상승장 한정)
  V3. ML 캘리브레이션 SHORT   — bot/signal_engine이 실제 쓰는 신호
                                (calibration_BTCUSDT_1h.json)
                                ⚠️ 모델 학습기간(~2025-08 이전)은 in-sample —
                                   진짜 검증은 2025-08 이후뿐
  V4. ML SHORT + 레짐필터     — V3 + 일봉 200일선 아래에서만 진입 (하락장 한정)

자금 처리:
  - 자금은 KRW·USDT 환율 변동 없이 "자본 단위" 그대로 사용
    (100만원 → 1,000,000 단위, 30만원 → 300,000 단위)
  - 신호 미발동 구간은 현금 대기 (수익 0%) — 안전 가정
  - 레버리지는 bot/leverage_manager.py의 수수료 반영 켈리 그대로 사용
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os, sys, pickle
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ml.train_directional import (
    load_ohlcv, load_indicators, merge_indicators, add_features,
    make_targets, get_feature_cols, get_tp_sl, ROUND_TRIP_COST,
)
from ml.mine_and_validate import eval_rule, wilson_lower
from bot.leverage_manager import LeverageManager

SCRATCH = "/tmp/claude-0/-home-user-caleb/62d6caa3-a2e8-5314-baa9-dfd48bdd6fd3/scratchpad"
INITIAL   = 1_000_000
MONTHLY   = 300_000
INTERVAL  = "1h"
HORIZON   = 12

# 최상위 후보 (mine_and_validate.py 재현 결과)
BEST_RULE = ("LONG", "ret_std_20 ≤ 0.00231 AND dxy_ret20d > -0.00263 "
                      "AND vs_sma576 ≤ 0.10429 AND ema50_vs_200 > 0.03287")
RULE_TRAIN_WR = 73.81


# ══════════════════════════════════════════════════════════════
# 데이터 준비
# ══════════════════════════════════════════════════════════════

def load_full_df():
    cache = f"{SCRATCH}/btc1h_full_df.pkl"
    if os.path.exists(cache):
        return pd.read_pickle(cache)
    df = load_ohlcv("BTCUSDT", INTERVAL, from_year=2017)
    try:
        df = merge_indicators(df, load_indicators())
    except Exception:
        pass
    df = add_features(df)
    tp, sl = get_tp_sl(INTERVAL)
    df = make_targets(df, horizon=HORIZON, tp=tp, sl=sl)
    fc = get_feature_cols(df)
    df = df.dropna(subset=fc[:20]).reset_index(drop=True)
    df[fc] = df[fc].replace([np.inf, -np.inf], np.nan).fillna(0)
    return df


def add_regime(df: pd.DataFrame) -> pd.DataFrame:
    """일봉 200일 SMA 기준 상승/하락장 레짐 (룩어헤드 없음 — 전일 종가까지만)"""
    daily = load_ohlcv("BTCUSDT", "1d", from_year=2017)
    daily = daily.sort_values("datetime").reset_index(drop=True)
    daily["sma200"] = daily["close"].rolling(200).mean()
    daily["bull"] = daily["close"] > daily["sma200"]
    daily["date"] = daily["datetime"].dt.date
    # 전일까지 확정된 레짐만 사용 (당일 미확정 봉 제외)
    daily["bull_lag1"] = daily["bull"].shift(1)
    reg = daily[["date", "bull_lag1"]].dropna()

    df = df.copy()
    df["date"] = df["datetime"].dt.date
    df = df.merge(reg, on="date", how="left")
    df["bull_lag1"] = df["bull_lag1"].fillna(False)
    return df


# ══════════════════════════════════════════════════════════════
# 거래 청산 판정 (SL 우선, make_targets와 동일 로직)
# ══════════════════════════════════════════════════════════════

def resolve_exit(highs, lows, i, direction, tp, sl, horizon, n):
    entry = None  # placeholder, entry price supplied by caller via closes
    return None  # 미사용 — 아래 simulate 안에서 인라인 처리


# ══════════════════════════════════════════════════════════════
# DCA 시뮬레이션 엔진
# ══════════════════════════════════════════════════════════════

def simulate(df: pd.DataFrame, signal_mask: np.ndarray, direction: str,
             sizing_wr: float, tier: int, label: str,
             fee: float = 0.0005, slip: float = 0.0005) -> dict:
    tp, sl = get_tp_sl(INTERVAL)
    lev_mgr = LeverageManager()
    dec = lev_mgr.decide(sizing_wr, interval=INTERVAL, tier=tier)

    dt = df["datetime"].values
    closes = df["close"].values
    highs  = df["high"].values
    lows   = df["low"].values
    n = len(df)

    months = pd.to_datetime(dt).to_period("M")

    cash = 0.0
    invested = 0.0
    exit_idx = -1
    exit_pnl = 0.0
    contributed = 0.0
    n_trades = 0
    n_wins = 0
    equity_curve = []
    last_month = None

    for i in range(n - HORIZON):
        m = months[i]
        if last_month is None:
            cash += INITIAL
            contributed += INITIAL
            last_month = m
        elif m != last_month:
            cash += MONTHLY
            contributed += MONTHLY
            last_month = m

        # 포지션 청산 처리
        if exit_idx == i:
            cash += invested * (1 + exit_pnl)
            if exit_pnl > 0:
                n_wins_local = 1
            invested = 0.0
            exit_idx = -1

        # 신규 진입
        if invested == 0.0 and signal_mask[i] and dec.leverage > 0:
            entry = closes[i] * (1 + slip if direction == "LONG" else 1 - slip)
            tp_p = entry * (1 + tp) if direction == "LONG" else entry * (1 - tp)
            sl_p = entry * (1 - sl) if direction == "LONG" else entry * (1 + sl)

            ex_price, ex_type, ex_j = None, "timeout", min(i + HORIZON, n - 1)
            for j in range(i + 1, min(i + HORIZON + 1, n)):
                hj, lj = highs[j], lows[j]
                if direction == "LONG":
                    hit_sl, hit_tp = lj <= sl_p, hj >= tp_p
                else:
                    hit_sl, hit_tp = hj >= sl_p, lj <= tp_p
                if hit_sl:
                    ex_price, ex_type, ex_j = sl_p, "sl", j; break
                if hit_tp:
                    ex_price, ex_type, ex_j = tp_p, "tp", j; break
            if ex_price is None:
                ex_price = closes[ex_j] * (1 - slip if direction == "LONG" else 1 + slip)

            gross = (ex_price/entry - 1) if direction == "LONG" else (entry/ex_price - 1)
            raw_pnl = gross - 2*fee
            lev_pnl = raw_pnl * dec.leverage

            pos_amt = cash * dec.position_pct
            cash -= pos_amt
            invested = pos_amt
            exit_idx = ex_j
            exit_pnl = lev_pnl
            n_trades += 1
            if raw_pnl > 0:
                n_wins += 1

        equity_curve.append(cash + invested)

    # 마지막 미청산 포지션 시가 정산
    total = cash + invested
    wr_real = (n_wins / n_trades * 100) if n_trades else 0.0

    return {
        "label": label, "final": total, "contributed": contributed,
        "n_trades": n_trades, "wr_real": wr_real,
        "leverage": dec.leverage, "position_pct": dec.position_pct,
        "equity_curve": equity_curve, "dt": dt[:len(equity_curve)],
    }


def simulate_buyhold(df: pd.DataFrame) -> dict:
    dt = df["datetime"].values
    closes = df["close"].values
    months = pd.to_datetime(dt).to_period("M")

    cash = 0.0
    btc_qty = 0.0
    contributed = 0.0
    last_month = None
    equity_curve = []

    for i in range(len(df)):
        m = months[i]
        amt = 0.0
        if last_month is None:
            amt = INITIAL; last_month = m
        elif m != last_month:
            amt = MONTHLY; last_month = m
        if amt:
            btc_qty += amt / closes[i]
            contributed += amt
        equity_curve.append(btc_qty * closes[i])

    return {"label": "V0. Buy&Hold DCA", "final": btc_qty*closes[-1],
            "contributed": contributed, "n_trades": 0, "wr_real": None,
            "leverage": 1.0, "position_pct": 1.0,
            "equity_curve": equity_curve, "dt": dt}


# ══════════════════════════════════════════════════════════════
# 실행
# ══════════════════════════════════════════════════════════════

def main():
    print("데이터 로딩...")
    df = load_full_df()
    df = add_regime(df)
    print(f"기간: {df['datetime'].iloc[0]} ~ {df['datetime'].iloc[-1]}  ({len(df):,}봉)\n")

    # V1: 마이닝 룰
    rule_mask = eval_rule(df, BEST_RULE[1])
    print(f"[V1] 마이닝 룰 발동 횟수: {rule_mask.sum():,}회 (전체 기간)")

    # V2: 룰 + 레짐(상승장만)
    rule_regime_mask = rule_mask & df["bull_lag1"].values
    print(f"[V2] 룰+레짐(상승장) 발동 횟수: {rule_regime_mask.sum():,}회")

    # V3: ML 캘리브레이션 SHORT
    import json
    cal = json.load(open("ml/saved_models/calibration_BTCUSDT_1h.json", encoding="utf-8"))
    model_path = "ml/saved_models/directional_BTCUSDT_1h.pkl"
    fcol_path  = "ml/saved_models/feature_cols_BTCUSDT_1h.pkl"
    model = pickle.load(open(model_path, "rb"))
    mcols = pickle.load(open(fcol_path, "rb"))
    X = df[mcols].replace([np.inf, -np.inf], np.nan).fillna(0)
    sp = model.predict_proba_short(X)
    ml_mask = sp >= cal["short"]["cut_score"]
    print(f"[V3] ML SHORT 발동 횟수: {ml_mask.sum():,}회 (전체 기간, "
          f"OOS는 {cal['oos_from'][:10]} 이후만)")

    # V4: ML SHORT + 레짐(하락장만)
    ml_regime_mask = ml_mask & (~df["bull_lag1"].values)
    print(f"[V4] ML SHORT+레짐(하락장) 발동 횟수: {ml_regime_mask.sum():,}회\n")

    results = []
    results.append(simulate_buyhold(df))
    results.append(simulate(df, rule_mask, "LONG", RULE_TRAIN_WR, tier=1,
                             label="V1. 마이닝룰 단독(LONG)"))
    results.append(simulate(df, rule_regime_mask, "LONG", RULE_TRAIN_WR, tier=1,
                             label="V2. 마이닝룰+레짐필터"))
    results.append(simulate(df, ml_mask, "SHORT", cal["short"]["wr"], tier=3,
                             label="V3. ML캘리브레이션 SHORT"))
    results.append(simulate(df, ml_regime_mask, "SHORT", cal["short"]["wr"], tier=3,
                             label="V4. ML SHORT+레짐필터"))

    print("="*100)
    print(f"{'전략':28s}{'투입원금':>14s}{'최종자산':>16s}{'수익률':>10s}{'거래수':>8s}{'실현WR':>9s}{'레버리지':>8s}")
    print("-"*100)
    for r in results:
        ret = (r["final"]/r["contributed"] - 1)*100 if r["contributed"] else 0
        wr = f"{r['wr_real']:.1f}%" if r['wr_real'] is not None else "-"
        print(f"{r['label']:28s}{r['contributed']:>13,.0f}원{r['final']:>15,.0f}원"
              f"{ret:>9.1f}%{r['n_trades']:>8d}{wr:>9s}{r['leverage']:>7.1f}x")

    # 저장
    out = pd.DataFrame([{
        "전략": r["label"], "투입원금": r["contributed"], "최종자산": round(r["final"]),
        "수익률%": round((r["final"]/r["contributed"]-1)*100, 1) if r["contributed"] else 0,
        "거래수": r["n_trades"],
        "실현WR%": round(r["wr_real"],1) if r["wr_real"] is not None else None,
        "레버리지": r["leverage"],
    } for r in results])
    out.to_csv(f"{SCRATCH}/dca_results.csv", index=False)

    # 에쿼티 커브 저장 (차트용)
    for r in results:
        s = pd.DataFrame({"datetime": r["dt"], "equity": r["equity_curve"]})
        s.to_csv(f"{SCRATCH}/equity_{r['label'][:2]}.csv", index=False)

    print(f"\n저장: {SCRATCH}/dca_results.csv")


if __name__ == "__main__":
    main()
