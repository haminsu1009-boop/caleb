"""
ml/calibrate.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ML 모델 점수 캘리브레이션

왜 필요한가:
  DirectionalEnsemble이 내는 확률값은 보정되어 있지 않다.
  정직한 라벨(인터벌별 TP/SL, SL 우선 판정)로 재학습하면
  확률이 0.58을 거의 넘지 못하는데, signal_engine은
  `lp >= 0.68`이라는 절대 임계값을 쓰고 있어 실전 신호가 0건이 된다.

  → 절대 확률 대신 "점수 상위 N%" 백분위 기준으로 바꾸고,
    각 백분위에서 OOS로 실측한 승률을 함께 저장한다.
    레버리지/포지션 계산은 이 실측 승률을 쓴다(추정식 금지).

산출물:
  ml/saved_models/calibration_{SYMBOL}_{INTERVAL}.json
    {
      "long":  {"enabled": bool, "cut_score": float, "wr": float, "n": int, "ev_pct": float},
      "short": {...},
      "breakeven_wr": float, "pct": 3.0, "oos_from": "...", "oos_to": "..."
    }

사용법:
  python ml/calibrate.py --symbol BTCUSDT --interval 4h
  python ml/calibrate.py --all
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, json, pickle, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ml.train_directional import (
    load_ohlcv, load_indicators, merge_indicators, add_features,
    make_targets, get_tp_sl, ROUND_TRIP_COST,
)

MODEL_DIR   = os.path.join(ROOT, "ml", "saved_models")
HORIZON_MAP = {"1m":30, "3m":20, "5m":12, "15m":8, "30m":6,
               "1h":12, "2h":8, "4h":6, "6h":4, "12h":3, "1d":2}
TRAIN_FRAC  = 0.85          # train_final()이 쓰는 학습 비율
CAND_PCTS   = [1.0, 2.0, 3.0, 5.0, 10.0]
MIN_TRADES  = 15            # 이보다 표본이 적으면 채택하지 않음
MIN_MARGIN  = 3.0           # 손익분기 대비 최소 여유 승률(%p)


def wilson_lower(wins: int, n: int, z: float = 1.645) -> float:
    """Wilson 95% CI 하한 (단측 z=1.645) — 소표본 과신 방지"""
    if n == 0:
        return 0.0
    p = wins / n
    denom  = 1 + z**2 / n
    center = p + z**2 / (2 * n)
    margin = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return max(0.0, (center - margin) / denom * 100)


def calibrate(symbol: str, interval: str, from_year: int = 2020,
              verbose: bool = True) -> dict | None:
    mp = os.path.join(MODEL_DIR, f"directional_{symbol}_{interval}.pkl")
    fp = os.path.join(MODEL_DIR, f"feature_cols_{symbol}_{interval}.pkl")
    if not (os.path.exists(mp) and os.path.exists(fp)):
        if verbose:
            print(f"  ⚠️  {symbol} {interval}: 모델 없음 — 스킵")
        return None

    model = pickle.load(open(mp, "rb"))
    cols  = pickle.load(open(fp, "rb"))

    df = load_ohlcv(symbol, interval, from_year)
    try:
        df = merge_indicators(df, load_indicators())
    except Exception:
        pass
    df = add_features(df)

    horizon = HORIZON_MAP.get(interval, 12)
    tp, sl  = get_tp_sl(interval)
    df = make_targets(df, horizon=horizon, tp=tp, sl=sl)
    df = df.dropna(subset=cols).reset_index(drop=True)

    # 학습에 쓰이지 않은 뒤쪽 구간만 사용
    oos = df.iloc[int(len(df) * TRAIN_FRAC):].reset_index(drop=True)
    if len(oos) < 200:
        if verbose:
            print(f"  ⚠️  {symbol} {interval}: OOS 부족({len(oos)}행) — 스킵")
        return None

    X  = oos[cols].replace([np.inf, -np.inf], np.nan).fillna(0)
    lp = model.predict_proba_long(X)
    sp = model.predict_proba_short(X)

    net_tp = tp - ROUND_TRIP_COST
    net_sl = sl + ROUND_TRIP_COST
    breakeven = net_sl / (net_tp + net_sl) * 100

    out = {
        "symbol": symbol, "interval": interval,
        "breakeven_wr": round(breakeven, 2),
        "tp": tp, "sl": sl,
        "net_tp": round(net_tp, 5), "net_sl": round(net_sl, 5),
        "oos_from": str(oos["datetime"].iloc[0]),
        "oos_to":   str(oos["datetime"].iloc[-1]),
        "oos_bars": len(oos),
    }

    for side, probs, y in [("long", lp, oos["y_long"].values),
                           ("short", sp, oos["y_short"].values)]:
        best = None
        for pct in CAND_PCTS:
            k = max(1, int(len(probs) * pct / 100))
            idx = np.argsort(probs)[-k:]
            wins = int(y[idx].sum())
            wr   = wins / k * 100
            wl   = wilson_lower(wins, k)
            ev   = (wr / 100) * net_tp - (1 - wr / 100) * net_sl

            # 채택 조건: 표본 충분 + Wilson 하한이 손익분기를 여유있게 상회
            ok = (k >= MIN_TRADES) and (wl >= breakeven + MIN_MARGIN)
            if ok and (best is None or ev > best["ev"]):
                best = {"pct": pct, "cut": float(np.sort(probs)[-k]),
                        "wr": wr, "wilson": wl, "n": k, "wins": wins, "ev": ev}

        if best:
            out[side] = {
                "enabled":   True,
                "pct":       best["pct"],
                "cut_score": round(best["cut"], 6),
                # ⚠️ 레버리지 계산에는 실측 WR이 아니라 Wilson 하한을 쓴다.
                #   소표본에서 승률을 과신해 포지션이 커지는 것을 막는다.
                "wr":        round(best["wilson"], 2),
                "wr_raw":    round(best["wr"], 2),
                "n":         best["n"],
                "wins":      best["wins"],
                "ev_pct":    round(best["ev"] * 100, 4),
            }
        else:
            out[side] = {"enabled": False, "reason": "손익분기 대비 우위 미검증"}

    path = os.path.join(MODEL_DIR, f"calibration_{symbol}_{interval}.json")
    json.dump(out, open(path, "w"), indent=2, ensure_ascii=False)

    if verbose:
        print(f"  {symbol} {interval}  손익분기 {breakeven:.1f}%  "
              f"OOS {out['oos_bars']:,}봉")
        for side in ("long", "short"):
            d = out[side]
            if d["enabled"]:
                print(f"    {side.upper():5s} ✅ 상위{d['pct']:.0f}%  "
                      f"실측WR {d['wr_raw']:.1f}% (Wilson {d['wr']:.1f}%)  "
                      f"n={d['n']}  EV {d['ev_pct']:+.3f}%/거래")
            else:
                print(f"    {side.upper():5s} ❌ 비활성 — {d['reason']}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol",   default="BTCUSDT")
    ap.add_argument("--interval", default="4h")
    ap.add_argument("--from",     type=int, default=2020, dest="from_year")
    ap.add_argument("--all",      action="store_true")
    a = ap.parse_args()

    print("=" * 66)
    print("  ML 점수 캘리브레이션 (OOS 실측 기반)")
    print("=" * 66)

    if a.all:
        import glob
        pairs = []
        for f in sorted(glob.glob(os.path.join(MODEL_DIR, "directional_*.pkl"))):
            stem = os.path.basename(f)[len("directional_"):-4]
            sym, _, ivl = stem.rpartition("_")
            pairs.append((sym, ivl))
        for sym, ivl in pairs:
            calibrate(sym, ivl, a.from_year)
    else:
        calibrate(a.symbol, a.interval, a.from_year)


if __name__ == "__main__":
    main()
