"""
ml/holdout_validate.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
패턴룰 홀드아웃(OOS) 검증 스크립트

목적:
  패턴룰이 마이닝된 학습 구간 이외의 데이터(홀드아웃)에서
  실제로 얼마나 잘 동작하는지를 Wilson CI와 함께 검증.

  "학습에 쓰인 규칙이 처음 보는 데이터에서도 통할까?"
  → 과적합 여부를 객관적으로 판단하는 최소한의 체크.

검증 방식:
  · 마이닝 기간: 2017-01-01 ~ 2023-12-31  (학습 구간)
  · 홀드아웃:   2024-01-01 ~ 현재          (미래 데이터)
  · 각 룰마다 홀드아웃 기간에 매칭 횟수(n_oos) / 승리 횟수 계산
  · Wilson 95% 신뢰구간 하한으로 정직한 WR 추정

지표 생성:
  · data/ 디렉터리의 gz 압축 OHLCV 파일 + ml/train_directional.add_features()
  · 피처가 없으면 기본 지표 fallback

출력:
  · 콘솔: 룰별 [학습 WR → OOS WR (Wilson 하한)] 비교
  · CSV:  ml/saved_models/holdout_results.csv

사용법:
    python ml/holdout_validate.py
    python ml/holdout_validate.py --holdout-from 2024-01-01
    python ml/holdout_validate.py --min-n 100 --min-wilson 80
    python ml/holdout_validate.py --output results/holdout.csv
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os, sys, re, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR  = os.path.join(ROOT, "data")
MODEL_DIR = os.path.join(ROOT, "ml", "saved_models")
sys.path.insert(0, ROOT)

RULES_CSV      = os.path.join(MODEL_DIR, "pattern_rules.csv")
DEFAULT_OUTPUT = os.path.join(MODEL_DIR, "holdout_results.csv")

# ── 홀드아웃 기간 기본값 ────────────────────────────────
HOLDOUT_FROM  = "2024-01-01"   # 이 날짜 이후가 OOS

# 피처 계산 컨텍스트: 홀드아웃 시작일 이전 N일 로드
# (가장 긴 Rolling window = vs_sma576 = 576봉)
# 인터벌별 컨텍스트 기간 (가장 긴 rolling window = vs_sma576봉 대비)
# vs_sma576 × 인터벌_길이 = 필요 일수
_CONTEXT_DAYS_BY_INTERVAL = {
    "5m":  4,    # 576봉 × 5min = 48h → 4일이면 충분
    "15m": 8,
    "30m": 15,
    "1h":  30,
    "4h":  120,
    "1d":  400,
}

# ── 지표 생성 (add_features 실패 시 fallback) ──────────
def _add_basic_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """기본 기술 지표 fallback (외부 의존 없이 계산)"""
    c = df["close"].astype(float)
    v = df["volume"].astype(float)

    def sma(s, n): return s.rolling(n, min_periods=1).mean()
    def ema(s, n): return s.ewm(span=n, adjust=False).mean()
    def rsi(s, n=14):
        d  = s.diff()
        up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
        dn = (-d).clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
        return 100 - 100 / (1 + up / dn.replace(0, 1e-9))

    df = df.copy()
    if "ma50"        not in df.columns: df["ma50"]        = sma(c, 50)
    if "ma200"       not in df.columns: df["ma200"]       = sma(c, 200)
    if "ma20"        not in df.columns: df["ma20"]        = sma(c, 20)
    if "ema12"       not in df.columns: df["ema12"]       = ema(c, 12)
    if "ema26"       not in df.columns: df["ema26"]       = ema(c, 26)
    if "rsi14"       not in df.columns: df["rsi14"]       = rsi(c, 14)
    if "rsi_14"      not in df.columns: df["rsi_14"]      = df["rsi14"] / 100.0
    if "vol_ma20"    not in df.columns: df["vol_ma20"]    = sma(v, 20)
    if "vol_ratio"   not in df.columns:
        df["vol_ratio"] = v / df["vol_ma20"].replace(0, 1e-9)
    if "vol_ratio_24" not in df.columns:
        df["vol_ratio_24"] = v / sma(v, 24).replace(0, 1e-9)

    # 수익률
    for k in [1, 2, 3, 5, 10]:
        col = f"ret_{k}"
        if col not in df.columns:
            df[col] = c.pct_change(k)

    # 장기 수익률
    for k in [48, 96, 144, 288]:
        col = f"ret_{k}"
        if col not in df.columns:
            df[col] = c.pct_change(k)

    # 볼린저
    if "bb_pos" not in df.columns:
        std20 = c.rolling(20, min_periods=5).std()
        bb_u  = df["ma20"] + 2 * std20
        bb_l  = df["ma20"] - 2 * std20
        df["bb_upper"] = bb_u
        df["bb_lower"] = bb_l
        df["bb_pos"]   = ((c - bb_l) / (bb_u - bb_l + 1e-9)).clip(0, 1)
        df["bb_pos_20"] = df["bb_pos"]

    # ATR
    if "atr" not in df.columns:
        hi, lo, cl = df["high"].astype(float), df["low"].astype(float), c
        tr = pd.concat([hi - lo, (hi - cl.shift()).abs(), (lo - cl.shift()).abs()], axis=1).max(axis=1)
        df["atr"] = tr.ewm(span=14, adjust=False).mean()
        df["atr_pct"] = df["atr"] / c.replace(0, 1e-9)

    # 추세
    if "bull_trend" not in df.columns:
        df["bull_trend"] = (df["ma50"] > df["ma200"]).astype(int)
    if "vs_sma24" not in df.columns:
        df["vs_sma24"]  = c / sma(c, 24).replace(0, 1e-9) - 1
    if "vs_sma12" not in df.columns:
        df["vs_sma12"]  = c / sma(c, 12).replace(0, 1e-9) - 1

    # MACD histogram
    if "macd_12_26_hist" not in df.columns:
        macd = df["ema12"] - df["ema26"]
        sig  = macd.ewm(span=9, adjust=False).mean()
        df["macd_12_26_hist"] = macd - sig

    # Shadow 비율
    if "lower_shadow" not in df.columns:
        o, h, l_ = df["open"].astype(float), df["high"].astype(float), df["low"].astype(float)
        body_lo = pd.concat([o, c], axis=1).min(axis=1)
        total   = (h - l_).replace(0, 1e-9)
        df["lower_shadow"] = (body_lo - l_) / total
        df["upper_shadow"] = (h - pd.concat([o, c], axis=1).max(axis=1)) / total

    # ichi_tk (Ichimoku Tenkan-Kijun spread)
    if "ichi_tk" not in df.columns:
        ten = (df["high"].rolling(9).max() + df["low"].rolling(9).min()) / 2
        kij = (df["high"].rolling(26).max() + df["low"].rolling(26).min()) / 2
        df["ichi_tk"] = (ten - kij) / c.replace(0, 1e-9)

    # hma_21_vs_c
    if "hma_21_vs_c" not in df.columns:
        wma = lambda s, n: s.rolling(n).apply(lambda x: np.dot(x, np.arange(1, n+1)) / np.arange(1, n+1).sum(), raw=True)
        try:
            hma = wma(2 * wma(c, 10) - wma(c, 21), int(21 ** 0.5))
            df["hma_21_vs_c"] = (hma - c) / c.replace(0, 1e-9)
        except Exception:
            df["hma_21_vs_c"] = 0.0

    # cmf_14
    if "cmf_14" not in df.columns:
        hi, lo_ = df["high"].astype(float), df["low"].astype(float)
        mfv = ((c - lo_) - (hi - c)) / (hi - lo_ + 1e-9) * v
        df["cmf_14"] = mfv.rolling(14, min_periods=1).sum() / v.rolling(14, min_periods=1).sum().replace(0, 1e-9)

    # adx
    if "adx" not in df.columns:
        hi, lo_, cl_shift = df["high"].astype(float), df["low"].astype(float), c.shift(1)
        plus_dm  = (hi - hi.shift(1)).clip(lower=0)
        minus_dm = (lo_.shift(1) - lo_).clip(lower=0)
        tr       = pd.concat([hi - lo_, (hi - cl_shift).abs(), (lo_ - cl_shift).abs()], axis=1).max(axis=1)
        atr14    = tr.ewm(span=14, adjust=False).mean().replace(0, 1e-9)
        plus_di  = 100 * plus_dm.ewm(span=14, adjust=False).mean() / atr14
        minus_di = 100 * minus_dm.ewm(span=14, adjust=False).mean() / atr14
        dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
        df["adx"] = dx.ewm(span=14, adjust=False).mean() / 100.0

    # vs_s3 (가격 vs 3기간 전)
    if "vs_s3" not in df.columns:
        df["vs_s3"] = c / c.shift(3).replace(0, 1e-9) - 1

    # lr_dev_10 (선형회귀 이탈도)
    if "lr_dev_10" not in df.columns:
        def lr_dev(s, n):
            out = np.full(len(s), np.nan)
            arr = s.values.astype(float)
            x   = np.arange(n)
            for i in range(n - 1, len(arr)):
                y    = arr[i - n + 1 : i + 1]
                if np.any(np.isnan(y)): continue
                c_   = np.polyfit(x, y, 1)
                pred = np.polyval(c_, n - 1)
                out[i] = (y[-1] - pred) / (abs(pred) + 1e-9)
            return pd.Series(out, index=s.index)
        df["lr_dev_10"] = lr_dev(c, 10)

    # vol_288 (5m 기준 288봉 = 1일 볼륨 평균 대비)
    if "vol_288" not in df.columns:
        df["vol_288"] = v / sma(v, 288).replace(0, 1e-9)

    # htf proxy (없으면 0 채움)
    for htf_feat in ["htf_1h_bb_pos_20", "htf_4h_adx", "htf_1h_rsi_14",
                     "htf_4h_rsi_14", "ema50_vs_200", "vs_sma96"]:
        if htf_feat not in df.columns:
            df[htf_feat] = 0.0

    return df


def _add_features_safe(df: pd.DataFrame, interval: str,
                        use_full_pipeline: bool = True) -> pd.DataFrame:
    """
    지표 생성.
    기본: ml.train_directional.add_features — 패턴룰 289피처 전체 커버.
    fallback: _add_basic_indicators (피처 불완전, 일부 룰 매칭 불가).

    Note: 전체 히스토리가 아닌 최근 데이터만 전달해야 속도가 빠름.
    """
    if use_full_pipeline:
        try:
            from ml.train_directional import add_features
            return add_features(df.copy())
        except Exception as e:
            print(f"  ⚠️  add_features 실패 ({e}) → 기본 지표 fallback")
    return _add_basic_indicators(df)


# ── 데이터 로드 ──────────────────────────────────────────
def _load_data(symbol: str, interval: str,
               from_date: str = None) -> pd.DataFrame:
    """
    data/ 디렉터리에서 OHLCV 로드 (gz 압축 파일).

    Args:
        from_date: 이 날짜 이후만 로드 (None = 전체). 피처 계산 컨텍스트 포함.
    """
    fname = os.path.join(DATA_DIR, f"{symbol}_{interval}_all.csv.gz")
    if not os.path.exists(fname):
        return pd.DataFrame()
    try:
        df = pd.read_csv(fname, compression="gzip")
        ts_col = "timestamp" if "timestamp" in df.columns else df.columns[0]
        df[ts_col] = df[ts_col].astype(str)
        # 유효 날짜 패턴: 2017~2029 연도로 시작하는 것만
        df = df[df[ts_col].str.match(r"^20[12][0-9]-")].copy()
        df["datetime"] = pd.to_datetime(df[ts_col], errors="coerce")
        df = df.dropna(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)
        if from_date:
            dt = pd.Timestamp(from_date)
            df = df[df["datetime"] >= dt].copy().reset_index(drop=True)
        return df
    except Exception as e:
        print(f"  ⚠️  데이터 로드 실패 {fname}: {e}")
        return pd.DataFrame()


# ── Wilson Score 95% 신뢰구간 하한 ───────────────────────
def wilson_lower(wins: float, n: int, z: float = 1.645) -> float:
    if n <= 0:
        return 0.0
    p     = wins / n
    denom = 1 + z * z / n
    ctr   = p + z * z / (2 * n)
    marg  = z * np.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return max(0.0, (ctr - marg) / denom)


# ── 룰 평가 (단일 행) ────────────────────────────────────
def eval_rule(row: pd.Series, rule_str: str) -> bool:
    try:
        for cond in [c.strip() for c in rule_str.split(" AND ")]:
            m = re.match(r"([\w\.]+)\s*(<=|>=|≤|≥|<|>|==)\s*([-\d\.eE+]+)", cond)
            if not m:
                return False
            feat, op, val = m.group(1), m.group(2).replace("≤","<=").replace("≥",">="), float(m.group(3))
            if feat not in row.index:
                return False
            fval = float(row[feat])
            if op == "<="  and not (fval <= val): return False
            if op == ">="  and not (fval >= val): return False
            if op == "<"   and not (fval <  val): return False
            if op == ">"   and not (fval >  val): return False
            if op == "=="  and not (fval == val): return False
        return True
    except Exception:
        return False


# ── 전방 수익률 계산 ─────────────────────────────────────
def _forward_return(df: pd.DataFrame, idx: int,
                    direction: str, hold_bars: int = 1) -> float:
    """
    인덱스 idx 진입 → hold_bars 봉 후 청산 수익률 반환.
    direction: "LONG" 또는 "SHORT"
    """
    if idx + hold_bars >= len(df):
        return np.nan
    entry = df["close"].iloc[idx]
    exit_ = df["close"].iloc[idx + hold_bars]
    if entry <= 0:
        return np.nan
    ret = (exit_ - entry) / entry
    return ret if direction == "LONG" else -ret


# ── 메인 검증 루프 ────────────────────────────────────────
def run_holdout(
    holdout_from:  str   = HOLDOUT_FROM,
    min_n:         int   = 100,
    min_wilson:    float = 80.0,
    hold_bars:     int   = 1,        # 진입 후 몇 봉 만에 청산 판단
    output_path:   str   = DEFAULT_OUTPUT,
    verbose:       bool  = True,
):
    """
    Args:
        holdout_from: OOS 시작일 (이 날짜 이후 데이터만 평가)
        min_n:        학습 기간 최소 샘플 수 필터
        min_wilson:   학습 기간 Wilson 하한 필터 (%)
        hold_bars:    진입 후 N봉 뒤 청산 (기본 1봉 = 즉시 다음 봉)
        output_path:  결과 저장 경로
    """
    if not os.path.exists(RULES_CSV):
        print(f"❌ 패턴룰 파일 없음: {RULES_CSV}")
        return pd.DataFrame()

    # ── 룰 로드 + Wilson 필터 ───────────────────────────
    rules = pd.read_csv(RULES_CSV)
    if rules["win_rate"].max() <= 1.01:
        rules["win_rate"] = rules["win_rate"] * 100
    rules["_wins"]   = (rules["win_rate"] / 100 * rules["count"]).round()
    rules["_wilson"] = rules.apply(
        lambda r: wilson_lower(r["_wins"], int(r["count"])) * 100, axis=1
    )
    rules_f = rules[(rules["count"] >= min_n) & (rules["_wilson"] >= min_wilson)].copy()
    n_total, n_pass = len(rules), len(rules_f)
    print(f"\n📋 패턴룰: 전체 {n_total}개 → Wilson 필터 통과 {n_pass}개")
    print(f"   홀드아웃 기간: {holdout_from} ~ 현재 (n_bars 기준: {hold_bars}봉 후 청산)\n")

    holdout_dt   = pd.Timestamp(holdout_from)

    # ── 심볼/인터벌별 데이터 캐시 ───────────────────────
    df_cache: dict = {}

    def _context_start(ivl: str) -> str:
        """인터벌별 rolling window 계산에 필요한 컨텍스트 시작일 계산"""
        days = _CONTEXT_DAYS_BY_INTERVAL.get(ivl, 120)
        return (holdout_dt - pd.Timedelta(days=days)).strftime("%Y-%m-%d")

    results = []

    for idx, rule in rules_f.iterrows():
        sym      = rule["symbol"]
        ivl      = rule["interval"]
        rule_str = rule["rule"]
        direction= rule["direction"]
        train_wr = rule["win_rate"]
        train_n  = int(rule["count"])
        train_wilson = rule["_wilson"]

        cache_key = f"{sym}_{ivl}"
        if cache_key not in df_cache:
            # 인터벌별 최소 컨텍스트만 로드 (5m은 4일, 4h는 120일 등)
            raw = _load_data(sym, ivl, from_date=_context_start(ivl))
            if raw.empty:
                df_cache[cache_key] = None
                print(f"  ⚠️  데이터 없음: {sym} {ivl} — 스킵")
                continue
            # 5m은 OOS 행이 너무 많아 add_features가 너무 느림 → 기본 지표만 사용
            # 결과: 일부 피처 미매칭으로 OOS n이 줄어들지만, 과적합 탐지에는 충분.
            use_full = (ivl not in ("5m", "15m", "30m"))
            if not use_full:
                print(f"  ℹ️  {sym} {ivl}: 기본 지표만 사용 (5m 속도 최적화)")
            df_with_feats = _add_features_safe(raw, ivl, use_full_pipeline=use_full)
            df_cache[cache_key] = df_with_feats

        df = df_cache.get(cache_key)
        if df is None:
            continue

        # 홀드아웃 구간만
        oos_df = df[df["datetime"] >= holdout_dt].copy()
        if len(oos_df) < 10:
            results.append({
                "symbol": sym, "interval": ivl, "direction": direction,
                "rule": rule_str[:60] + "...",
                "train_wr": round(train_wr, 1),
                "train_n": train_n,
                "train_wilson": round(train_wilson, 1),
                "oos_n": 0, "oos_wins": 0, "oos_wr": np.nan,
                "oos_wilson_lower": np.nan,
                "verdict": "insufficient_data",
            })
            continue

        # 룰 매칭 + 수익률 계산
        oos_df = oos_df.reset_index(drop=True)
        matched_idx = [
            i for i, row_s in oos_df.iterrows()
            if eval_rule(row_s, rule_str)
        ]

        oos_n = len(matched_idx)
        if oos_n == 0:
            results.append({
                "symbol": sym, "interval": ivl, "direction": direction,
                "rule": rule_str[:60] + "...",
                "train_wr": round(train_wr, 1),
                "train_n": train_n,
                "train_wilson": round(train_wilson, 1),
                "oos_n": 0, "oos_wins": 0, "oos_wr": np.nan,
                "oos_wilson_lower": np.nan,
                "verdict": "no_matches_in_oos",
            })
            continue

        fwds   = [_forward_return(oos_df, i, direction, hold_bars) for i in matched_idx]
        fwds   = [f for f in fwds if not np.isnan(f)]
        oos_n_valid = len(fwds)
        if oos_n_valid == 0:
            results.append({
                "symbol": sym, "interval": ivl, "direction": direction,
                "rule": rule_str[:60] + "...",
                "train_wr": round(train_wr, 1),
                "train_n": train_n,
                "train_wilson": round(train_wilson, 1),
                "oos_n": oos_n, "oos_wins": 0, "oos_wr": np.nan,
                "oos_wilson_lower": np.nan,
                "verdict": "no_exit_data",
            })
            continue

        oos_wins   = sum(1 for f in fwds if f > 0)
        oos_wr     = oos_wins / oos_n_valid * 100
        oos_wilson = wilson_lower(oos_wins, oos_n_valid) * 100
        drift      = oos_wr - train_wr

        # 판정 기준:
        # ✅ PASS:  OOS Wilson 하한 ≥ 70% → 여전히 유효
        # ⚠️ WARN:  OOS WR ≥ 55% but Wilson < 70% → 약화됨 (n 작음 or WR 하락)
        # ❌ FAIL:  OOS WR < 55% → 패턴 붕괴 (coin flip 수준)
        if oos_wilson >= 70:
            verdict = "PASS"
        elif oos_wr >= 55:
            verdict = "WARN_WEAKENED"
        else:
            verdict = "FAIL_BROKEN"

        if verbose:
            icon = {"PASS": "✅", "WARN_WEAKENED": "⚠️ ", "FAIL_BROKEN": "❌"}.get(verdict, "?")
            print(
                f"{icon} {sym:12} {ivl:4} {direction:5}  "
                f"학습WR={train_wr:.0f}%({train_n}n) → "
                f"OOS WR={oos_wr:.0f}%({oos_n_valid}n) "
                f"Wilson하한={oos_wilson:.0f}%  "
                f"[드리프트{drift:+.0f}%] {verdict}"
            )

        results.append({
            "symbol":           sym,
            "interval":         ivl,
            "direction":        direction,
            "rule":             rule_str[:80] + ("..." if len(rule_str) > 80 else ""),
            "train_wr":         round(train_wr, 1),
            "train_n":          train_n,
            "train_wilson":     round(train_wilson, 1),
            "oos_n":            oos_n_valid,
            "oos_wins":         oos_wins,
            "oos_wr":           round(oos_wr, 1),
            "oos_wilson_lower": round(oos_wilson, 1),
            "wr_drift":         round(drift, 1),
            "verdict":          verdict,
        })

    df_res = pd.DataFrame(results)
    if df_res.empty:
        print("\n❌ 결과 없음 (데이터 부족 또는 룰 0개)")
        return df_res

    # ── 요약 출력 ────────────────────────────────────────
    evaluated = df_res[df_res["oos_n"] > 0]
    n_pass_oos = (evaluated["verdict"] == "PASS").sum()
    n_warn     = (evaluated["verdict"] == "WARN_WEAKENED").sum()
    n_fail     = (evaluated["verdict"] == "FAIL_BROKEN").sum()
    n_no_match = (df_res["oos_n"] == 0).sum()

    print("\n" + "═" * 65)
    print("  홀드아웃 검증 요약")
    print("═" * 65)
    print(f"  Wilson 필터 통과 룰: {n_pass}개")
    print(f"  OOS 매칭 있음:       {len(evaluated)}개")
    print(f"    ✅ PASS     (OOS Wilson ≥70%):   {n_pass_oos}개")
    print(f"    ⚠️  WARN     (OOS WR ≥55%):       {n_warn}개")
    print(f"    ❌ FAIL     (OOS WR < 55%):       {n_fail}개")
    print(f"  OOS 매칭 없음:       {n_no_match}개 (룰이 홀드아웃 구간에 발화 안 함)")

    if len(evaluated) > 0:
        avg_train = evaluated["train_wr"].mean()
        avg_oos   = evaluated["oos_wr"].mean()
        print(f"\n  평균 학습 WR:        {avg_train:.1f}%")
        print(f"  평균 OOS WR:         {avg_oos:.1f}%")
        print(f"  평균 WR 드리프트:    {avg_oos - avg_train:+.1f}%")

    print("═" * 65)

    # 가장 좋은 OOS 룰 Top-5
    top5 = evaluated.nlargest(5, "oos_wilson_lower")
    if len(top5):
        print("\n  ── OOS Wilson 하한 기준 Top-5 룰 ──")
        for _, r in top5.iterrows():
            print(
                f"  {r['symbol']:12} {r['interval']:4} {r['direction']:5}  "
                f"학습={r['train_wr']:.0f}% → OOS={r['oos_wr']:.0f}%  "
                f"Wilson하한={r['oos_wilson_lower']:.0f}%  n={r['oos_n']}"
            )

    # CSV 저장
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df_res.to_csv(output_path, index=False)
    print(f"\n  💾 결과 저장: {output_path}")

    return df_res


# ── CLI ──────────────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="패턴룰 홀드아웃(OOS) 검증")
    ap.add_argument("--holdout-from", default=HOLDOUT_FROM,
                    help="OOS 시작일 (기본: 2024-01-01)")
    ap.add_argument("--min-n",        type=int,   default=100,
                    help="학습 기간 최소 샘플 수 (기본: 100)")
    ap.add_argument("--min-wilson",   type=float, default=80.0,
                    help="학습 기간 Wilson 하한 %% (기본: 80)")
    ap.add_argument("--hold-bars",    type=int,   default=1,
                    help="진입 후 N봉 뒤 청산 판단 (기본: 1)")
    ap.add_argument("--output",       default=DEFAULT_OUTPUT,
                    help="결과 CSV 저장 경로")
    ap.add_argument("--quiet",        action="store_true",
                    help="룰별 출력 숨김 (요약만 표시)")
    ap.add_argument("--full-features", action="store_true",
                    help="ml.train_directional.add_features 사용 (느림, 289피처)")
    args = ap.parse_args()

    run_holdout(
        holdout_from = args.holdout_from,
        min_n        = args.min_n,
        min_wilson   = args.min_wilson,
        hold_bars    = args.hold_bars,
        output_path  = args.output,
        verbose      = not args.quiet,
    )
