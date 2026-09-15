"""
ml/mine_and_validate.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
지표 기반 고승률 룰 마이닝 + 순수 홀드아웃 검증 (2017~현재)

기존 pattern_analysis.py는 ML 모델의 bt_trades(진입 시점) 위에
메타 룰을 마이닝했다. backtest.py를 진짜 OOS 평가로 고친 뒤로는
bt_trades가 최근 11개월치(수백 건)만 남아 마이닝 표본이 되지 않는다.

이 스크립트는 그 대신 원 가격 데이터에 직접 룰을 마이닝한다:
  1. 학습 구간(2017-01-01 ~ TRAIN_END)에서 매 봉을 가상 진입점으로 보고
     DecisionTree로 고승률 조건 조합을 찾는다 (mine_rules 재사용).
  2. 찾은 룰을 홀드아웃 구간(TRAIN_END ~ 현재, 학습에 전혀 안 씀)에
     그대로 대입해 실제 발동 횟수와 승률을 다시 센다.
  3. Wilson 95% CI 하한이 해당 인터벌의 손익분기 승률(수수료 반영)을
     충분히 상회하는 룰만 "검증됨"으로 보고한다.

라벨은 train_directional.make_targets() 그대로 사용 — SL 우선 판정,
인터벌별 TP/SL, look-ahead 없는 피처. 학습에 쓰이는 add_features()도
동일 — 이미 fractal_high/btcd_peak 미래참조를 제거한 버전.

사용법:
    python ml/mine_and_validate.py --symbol BTCUSDT --interval 1h
    python ml/mine_and_validate.py --all
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, re, json, argparse, warnings
import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeClassifier

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ml.train_directional import (
    load_ohlcv, load_indicators, merge_indicators, add_features,
    make_targets, get_feature_cols, get_tp_sl, ROUND_TRIP_COST,
)

MODEL_DIR   = os.path.join(ROOT, "ml", "saved_models")
OUT_CSV     = os.path.join(MODEL_DIR, "mined_rules_holdout.csv")

HORIZON_MAP = {"1h": 12, "4h": 6, "1d": 2}
TRAIN_END   = "2025-01-01"      # 이전=학습, 이후=순수 홀드아웃 (한 번도 안 씀)
MIN_N_TRAIN = {"1h": 40, "4h": 25, "1d": 8}
MIN_N_OOS   = 30                 # 홀드아웃에서 이보다 적게 발동하면 신뢰 불가로 폐기
MARGIN_PP   = 5.0                # 손익분기 대비 최소 여유(%p)


# ── Wilson 95% CI 하한 ──────────────────────────────────────
def wilson_lower(wins: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 0.0
    p = wins / n
    denom  = 1 + z**2 / n
    center = p + z**2 / (2 * n)
    margin = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return max(0.0, (center - margin) / denom * 100)


# ── 룰 마이닝 (DecisionTree 리프 → AND 조건) ─────────────────
def mine_rules(df: pd.DataFrame, direction: str, feature_cols: list,
               min_n: int) -> list:
    y_col = "y_long" if direction == "LONG" else "y_short"
    X = df[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0).astype(np.float32)
    y = df[y_col].astype(int)

    tree = DecisionTreeClassifier(
        max_depth=5,
        min_samples_leaf=min_n,
        min_impurity_decrease=0.0003,
        random_state=42,
    )
    tree.fit(X, y)

    leaf_ids = tree.apply(X.values)
    tr = tree.tree_
    feat_names = np.array(feature_cols)

    # 각 리프까지의 경로(AND 조건) 복원
    def leaf_path(leaf_id: int) -> list:
        # DFS로 leaf_id에 도달하는 경로의 (feature, threshold, direction) 목록
        path = []
        def walk(node, trail):
            if tr.children_left[node] == tr.children_right[node] == -1:
                if node == leaf_id:
                    path.extend(trail)
                return
            f = feat_names[tr.feature[node]]
            t = tr.threshold[node]
            if tr.children_left[node] != -1:
                walk(tr.children_left[node], trail + [(f, "≤", t)])
            if tr.children_right[node] != -1:
                walk(tr.children_right[node], trail + [(f, ">", t)])
        walk(0, [])
        return path

    rules = []
    for leaf in np.unique(leaf_ids):
        mask = leaf_ids == leaf
        n = int(mask.sum())
        if n < min_n:
            continue
        wins = int(y[mask].sum())
        wr = wins / n * 100
        if wr < 55.0:          # 학습 단계 최소 필터 (느슨하게, 진짜 필터는 홀드아웃)
            continue
        cond = leaf_path(leaf)
        if not cond:
            continue
        # 같은 피처의 중복 조건은 가장 타이트한 것만 남김
        tight = {}
        for f, op, t in cond:
            key = (f, op)
            if key not in tight:
                tight[key] = t
            else:
                tight[key] = min(tight[key], t) if op == "≤" else max(tight[key], t)
        rule_str = " AND ".join(f"{f} {op} {tight[(f,op)]:.5f}" for f, op in tight)
        rules.append({
            "direction": direction, "rule": rule_str,
            "train_wr": round(wr, 2), "train_n": n,
        })
    rules.sort(key=lambda r: -r["train_wr"])
    return rules


# ── 룰 평가기 (문자열 → 불리언 마스크) ───────────────────────
_OP = {"≤": np.less_equal, ">": np.greater}

def eval_rule(df: pd.DataFrame, rule_str: str) -> np.ndarray:
    mask = np.ones(len(df), dtype=bool)
    for part in rule_str.split(" AND "):
        m = re.match(r"^(.+?)\s+(≤|>)\s+(-?[\d.eE+-]+)$", part.strip())
        if not m:
            return np.zeros(len(df), dtype=bool)
        feat, op, val = m.group(1), m.group(2), float(m.group(3))
        if feat not in df.columns:
            return np.zeros(len(df), dtype=bool)
        mask &= _OP[op](df[feat].values, val)
    return mask


# ── 심볼×인터벌 1건 처리 ─────────────────────────────────────
def run_one(symbol: str, interval: str, verbose: bool = True) -> list:
    horizon = HORIZON_MAP.get(interval, 12)
    tp, sl  = get_tp_sl(interval)
    net_tp, net_sl = tp - ROUND_TRIP_COST, sl + ROUND_TRIP_COST
    breakeven = net_sl / (net_tp + net_sl) * 100 if net_tp > 0 else 100.0

    df = load_ohlcv(symbol, interval, from_year=2017)
    try:
        df = merge_indicators(df, load_indicators())
    except Exception:
        pass
    df = add_features(df)
    df = make_targets(df, horizon=horizon, tp=tp, sl=sl)

    feature_cols = get_feature_cols(df)
    df = df.dropna(subset=feature_cols[:20]).reset_index(drop=True)
    df[feature_cols] = df[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0)

    split = df["datetime"] < TRAIN_END
    train, holdout = df[split].reset_index(drop=True), df[~split].reset_index(drop=True)

    if verbose:
        print(f"\n{'='*70}")
        print(f"  {symbol} {interval}  손익분기 {breakeven:.1f}%  "
              f"(실질익 {net_tp*100:.2f}% / 실질손 {net_sl*100:.2f}%)")
        print(f"  학습 {len(train):,}행 ({train['datetime'].min()} ~ {train['datetime'].max()})"
              f"  |  홀드아웃 {len(holdout):,}행 ({holdout['datetime'].min() if len(holdout) else '-'} ~ {holdout['datetime'].max() if len(holdout) else '-'})")

    if len(train) < 500 or len(holdout) < 200:
        if verbose: print("  ⚠️ 데이터 부족 — 스킵")
        return []

    min_n = MIN_N_TRAIN.get(interval, 25)
    mined = (mine_rules(train, "LONG", feature_cols, min_n) +
             mine_rules(train, "SHORT", feature_cols, min_n))

    if verbose:
        print(f"  학습 단계 후보 룰: {len(mined)}개 (WR≥55%, n≥{min_n})")

    verified = []
    for r in mined:
        mask = eval_rule(holdout, r["rule"])
        n = int(mask.sum())
        if n < MIN_N_OOS:
            continue
        y_col = "y_long" if r["direction"] == "LONG" else "y_short"
        wins = int(holdout.loc[mask, y_col].sum())
        wr = wins / n * 100
        wl = wilson_lower(wins, n)
        if wl >= breakeven + MARGIN_PP:
            verified.append({
                "symbol": symbol, "interval": interval,
                "direction": r["direction"], "rule": r["rule"],
                "train_wr": r["train_wr"], "train_n": r["train_n"],
                "oos_n": n, "oos_wins": wins, "oos_wr": round(wr, 2),
                "oos_wilson_lower": round(wl, 2),
                "breakeven_wr": round(breakeven, 2),
                "margin_pp": round(wl - breakeven, 2),
            })

    verified.sort(key=lambda r: -r["oos_wilson_lower"])
    if verbose:
        print(f"  ✅ 홀드아웃 검증 통과 (Wilson≥손익분기+{MARGIN_PP:.0f}%p, n≥{MIN_N_OOS}): {len(verified)}개")
        for r in verified[:5]:
            print(f"     [{r['direction']}] OOS {r['oos_wr']:.1f}% (Wilson {r['oos_wilson_lower']:.1f}%) "
                  f"n={r['oos_n']}  여유+{r['margin_pp']:.1f}%p")
            print(f"       {r['rule'][:110]}")

        # 진단: 학습 후보 상위 5개가 홀드아웃에서 실제 어떻게 됐는지 (통과 실패해도 표시)
        if mined:
            print(f"  ── 학습 상위 후보 → 홀드아웃 실측 (참고, 통과 여부 무관) ──")
            diag = sorted(mined, key=lambda r: -r["train_wr"])[:5]
            for r in diag:
                mask = eval_rule(holdout, r["rule"])
                n = int(mask.sum())
                if n == 0:
                    print(f"     [{r['direction']}] 학습WR {r['train_wr']:.1f}%(n={r['train_n']}) "
                          f"→ 홀드아웃 0회 발동 (조건 불충족)")
                    continue
                y_col = "y_long" if r["direction"] == "LONG" else "y_short"
                wins = int(holdout.loc[mask, y_col].sum())
                wr = wins / n * 100
                wl = wilson_lower(wins, n)
                drift = wr - r["train_wr"]
                print(f"     [{r['direction']}] 학습WR {r['train_wr']:.1f}%(n={r['train_n']}) "
                      f"→ 홀드아웃 WR {wr:.1f}%(n={n}, Wilson {wl:.1f}%)  드리프트 {drift:+.1f}%p")
    return verified


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--symbols", nargs="*",
                    default=["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"])
    ap.add_argument("--intervals", nargs="*", default=["1h", "4h", "1d"])
    a = ap.parse_args()

    print("=" * 70)
    print("  지표 기반 룰 마이닝 + 순수 홀드아웃 검증")
    print(f"  학습: 2017 ~ {TRAIN_END}   홀드아웃: {TRAIN_END} ~ 현재 (한 번도 학습에 안 씀)")
    print("=" * 70)

    all_verified = []
    pairs = [(s, i) for s in a.symbols for i in a.intervals] if a.all else [(a.symbol, a.interval)]
    for sym, ivl in pairs:
        try:
            all_verified.extend(run_one(sym, ivl))
        except FileNotFoundError as e:
            print(f"  ⚠️ {sym} {ivl}: {e}")
        except Exception as e:
            print(f"  ⚠️ {sym} {ivl}: 오류 {e}")

    if all_verified:
        out = pd.DataFrame(all_verified).sort_values("oos_wilson_lower", ascending=False)
        out.to_csv(OUT_CSV, index=False)
        print(f"\n{'='*70}")
        print(f"  전체 검증 통과 룰: {len(out)}개 → {OUT_CSV}")
        print(f"{'='*70}")
        print(out[["symbol","interval","direction","oos_n","oos_wr",
                   "oos_wilson_lower","breakeven_wr","margin_pp"]].to_string(index=False))
    else:
        print("\n  검증 통과 룰 없음")


if __name__ == "__main__":
    main()
