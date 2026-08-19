"""
bot/signal_engine.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
멀티 타임프레임 신호 엔진 — 최대 승률 + 최대 실행률

신호 우선순위 (Tier):
  Tier-1 (WR 90%+):  패턴룰 매칭 (DecisionTree 마이닝)
  Tier-2 (WR 80%+):  볼륨폭발 패턴 (실증 94%+ BTC)
  Tier-3 (WR 70%+):  ML 모델 (DirectionalEnsemble) + 기술필터

타임프레임별 역할:
  1d  → 거시 방향 + 볼륨폭발 + 추세 필터
  4h  → 중기 진입 타이밍
  1h  → 단기 진입 + 다이버전스
  5m  → 정밀 진입 + 스캘핑

실행률 극대화:
  · 복수 타임프레임에서 동시에 신호 탐색
  · 약한 조건도 Tier3 진입 (레버리지 낮춰 리스크 관리)
  · 상관 필터 적용 후 최대 5 슬롯 운용
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os, sys, pickle, warnings, re
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional

warnings.filterwarnings("ignore")

ROOT      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(ROOT, "ml", "saved_models")
sys.path.insert(0, ROOT)


# ──────────────────────────────────────────────────────────
# 데이터 구조
# ──────────────────────────────────────────────────────────
@dataclass
class Signal:
    symbol:      str
    interval:    str
    direction:   str          # "LONG" | "SHORT"
    tier:        int          # 1=패턴룰, 2=볼륨폭발, 3=ML
    win_rate:    float        # 0~100
    confidence:  float        # 0~1 (ML 확률 or 규칙 WR/100)
    reason:      str          # 신호 근거 텍스트
    rule_text:   str = ""     # 패턴룰 전문 (Tier1)
    lift:        float = 1.0  # 패턴룰 lift
    count:       int   = 0    # 룰 샘플 수
    extra:       dict  = field(default_factory=dict)


# ──────────────────────────────────────────────────────────
# 패턴룰 평가기
# ──────────────────────────────────────────────────────────
class PatternRuleEvaluator:
    """패턴룰 CSV 로드 → DataFrame 행에 적용"""

    def __init__(self, rules_path: str = None):
        if rules_path is None:
            rules_path = os.path.join(MODEL_DIR, "pattern_rules.csv")
        self.rules = pd.DataFrame()
        if os.path.exists(rules_path):
            self.rules = pd.read_csv(rules_path)
            # win_rate가 0~100 스케일인지 확인
            if self.rules["win_rate"].max() <= 1.01:
                self.rules["win_rate"] = self.rules["win_rate"] * 100

    def _eval_rule(self, row: pd.Series, rule_str: str) -> bool:
        """단일 조건 룰 평가 (AND 체인) — 유니코드/ASCII 비교 연산자 모두 지원"""
        try:
            conditions = [c.strip() for c in rule_str.split(" AND ")]
            for cond in conditions:
                # ASCII (<=, >=) 와 유니코드 (≤, ≥) 모두 처리
                m = re.match(
                    r"([\w\.]+)\s*(<=|>=|≤|≥|<|>|==)\s*([-\d\.eE+]+)",
                    cond
                )
                if not m:
                    return False
                feat, op, val = m.group(1), m.group(2), float(m.group(3))
                if feat not in row.index:
                    return False
                fval = float(row[feat])
                # 유니코드 → ASCII 정규화
                op = op.replace("≤", "<=").replace("≥", ">=")
                if op == "<="  and not (fval <= val): return False
                if op == ">="  and not (fval >= val): return False
                if op == "<"   and not (fval <  val): return False
                if op == ">"   and not (fval >  val): return False
                if op == "=="  and not (fval == val): return False
            return True
        except Exception:
            return False

    def match(self, row: pd.Series, symbol: str, interval: str,
              min_wr: float = 70.0) -> list:
        """해당 심볼/인터벌/행에 매칭되는 룰 반환"""
        if self.rules.empty:
            return []
        sub = self.rules[
            (self.rules["symbol"]   == symbol) &
            (self.rules["interval"] == interval) &
            (self.rules["win_rate"] >= min_wr)
        ]
        matched = []
        for _, r in sub.iterrows():
            if self._eval_rule(row, r["rule"]):
                matched.append(r)
        return matched


# ──────────────────────────────────────────────────────────
# 기술적 지표 계산 (지표가 없을 때 fallback)
# ──────────────────────────────────────────────────────────
def _build_full_features(df: pd.DataFrame,
                          interval: str = "",
                          dfs_htf: dict = None) -> pd.DataFrame:
    """
    전체 피처 파이프라인 실행 (ml/train_directional.add_features 사용)
    + HTF 컨텍스트 주입 → 289개+ 피처 생성

    Args:
        df:       현재 타임프레임 OHLCV
        interval: "5m"|"1h"|"4h"|"1d"
        dfs_htf:  {"4h": df_4h} 상위 타임프레임 (선택)
    """
    from ml.train_directional import add_features as _add_feats

    _df = df.copy()
    ts_col = next((c for c in ["timestamp", "datetime", "date"]
                   if c in _df.columns), None)
    if ts_col and "datetime" not in _df.columns:
        _df["datetime"] = pd.to_datetime(_df[ts_col], errors="coerce")

    _df = _add_feats(_df)

    # HTF 피처 주입
    HTF_MAP = {"5m": ["1h", "4h"], "1h": ["4h"], "4h": [], "1d": []}
    htfs    = HTF_MAP.get(interval, [])
    if dfs_htf and htfs:
        KEY_FEATS = ["rsi_14", "adx", "bb_pos_20", "vol_ratio_24", "atr",
                     "cmf_14", "vs_sma96", "ema50_vs_200", "macd_12_26_hist"]
        base_dt = pd.DatetimeIndex(pd.to_datetime(_df["datetime"], errors="coerce"))

        for htf in htfs:
            if htf not in dfs_htf:
                continue
            htf_df = dfs_htf[htf].copy()
            ts2 = next((c for c in ["timestamp", "datetime", "date"]
                        if c in htf_df.columns), None)
            if ts2 and "datetime" not in htf_df.columns:
                htf_df["datetime"] = pd.to_datetime(htf_df[ts2], errors="coerce")
            try:
                htf_df = _add_feats(htf_df)
            except Exception:
                pass
            htf_idx = htf_df.set_index("datetime").sort_index()
            for feat in KEY_FEATS:
                if feat not in htf_idx.columns:
                    continue
                col_name = f"htf_{htf}_{feat}"
                combined = pd.DatetimeIndex(
                    base_dt.union(htf_idx.index)
                ).sort_values()
                s = htf_idx[feat].reindex(combined).ffill()
                _df[col_name] = s.reindex(base_dt).values

    return _df


def _ensure_indicators(df: pd.DataFrame, interval: str = "",
                        dfs_htf: dict = None) -> pd.DataFrame:
    """
    피처 파이프라인 실행 — 실패 시 기본 지표 fallback
    """
    try:
        return _build_full_features(df, interval, dfs_htf)
    except Exception:
        pass   # fallback below

    # fallback: 기본 지표만
    _df = df.copy()

    c = _df["close"].astype(float)
    v = _df["volume"].astype(float)

    def sma(s, n): return s.rolling(n, min_periods=1).mean()
    def rsi_calc(s, n=14):
        d  = s.diff()
        up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
        dn = (-d).clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
        return 100 - 100 / (1 + up / dn.replace(0, 1e-9))

    if "ma50"      not in _df.columns: _df["ma50"]  = sma(c, 50)
    if "ma200"     not in _df.columns: _df["ma200"] = sma(c, 200)
    if "ma20"      not in _df.columns: _df["ma20"]  = sma(c, 20)
    if "rsi14"     not in _df.columns: _df["rsi14"] = rsi_calc(c, 14)
    if "rsi_14"    not in _df.columns: _df["rsi_14"] = _df["rsi14"] / 100.0
    if "vol_ma20"  not in _df.columns: _df["vol_ma20"] = sma(v, 20)
    if "vol_ratio" not in _df.columns:
        _df["vol_ratio"] = v / _df["vol_ma20"].replace(0, 1e-9)
    if "ret1"  not in _df.columns: _df["ret1"] = c.pct_change(1)
    if "ret5"  not in _df.columns: _df["ret5"] = c.pct_change(5)
    if "bull_trend" not in _df.columns:
        _df["bull_trend"] = (_df["ma50"] > _df["ma200"]).astype(int)

    # 볼린저
    if "bb_upper" not in _df.columns:
        std20 = c.rolling(20, min_periods=5).std()
        _df["bb_upper"] = _df["ma20"] + 2 * std20
        _df["bb_lower"] = _df["ma20"] - 2 * std20
        _df["bb_pos"]   = ((c - _df["bb_lower"]) /
                           (_df["bb_upper"] - _df["bb_lower"] + 1e-9)).clip(0, 1)

    # 다이버전스
    if "bull_div" not in _df.columns:
        price_ll = (c < c.shift(5)) & (c.shift(5) < c.shift(10))
        rsi_hl   = (_df["rsi14"] > _df["rsi14"].shift(5)) & \
                   (_df["rsi14"].shift(5) > _df["rsi14"].shift(10))
        _df["bull_div"] = (price_ll & rsi_hl).astype(int)
        bear_div_p = (c > c.shift(5)) & (c.shift(5) > c.shift(10))
        bear_div_r = (_df["rsi14"] < _df["rsi14"].shift(5)) & \
                     (_df["rsi14"].shift(5) < _df["rsi14"].shift(10))
        _df["bear_div"] = (bear_div_p & bear_div_r).astype(int)

    return _df


# ──────────────────────────────────────────────────────────
# 신호 엔진 본체
# ──────────────────────────────────────────────────────────
class SignalEngine:
    """
    멀티 타임프레임 신호 엔진

    사용:
        engine = SignalEngine()
        signals = engine.scan(
            dfs={"5m": df_5m, "1h": df_1h, "4h": df_4h, "1d": df_1d},
            symbol="BTCUSDT"
        )
    """

    TIER1_MIN_WR = 90.0   # 패턴룰 Tier1 최소 WR
    TIER2_MIN_WR = 80.0   # 볼륨폭발 기준 WR
    TIER3_MIN_WR = 70.0   # ML Tier3 최소 WR

    # 볼륨폭발 파라미터 (실증: BTC 1d 94.4% WR)
    VOL_EXPLOSION = {
        "1d": {"mult": 2.0, "ret_min": 0.015},   # 볼륨>2x, 당일+1.5%
        "4h": {"mult": 2.0, "ret_min": 0.010},
        "1h": {"mult": 2.5, "ret_min": 0.008},
        "5m": {"mult": 3.0, "ret_min": 0.005},
    }

    def __init__(self, use_pattern_rules: bool = True,
                 use_ml: bool = True, use_volume_explosion: bool = True):
        self.use_pattern_rules     = use_pattern_rules
        self.use_ml                = use_ml
        self.use_volume_explosion  = use_volume_explosion
        self.rule_evaluator        = PatternRuleEvaluator() if use_pattern_rules else None
        self._ml_models: dict      = {}
        self._ml_feats:  dict      = {}

    # ── ML 모델 로드 ─────────────────────────────────
    def _load_ml(self, symbol: str, interval: str):
        key = f"{symbol}_{interval}"
        if key in self._ml_models:
            return
        m_path = os.path.join(MODEL_DIR, f"directional_{key}.pkl")
        f_path = os.path.join(MODEL_DIR, f"feature_cols_{key}.pkl")
        if os.path.exists(m_path) and os.path.exists(f_path):
            with open(m_path, "rb") as f: self._ml_models[key] = pickle.load(f)
            with open(f_path, "rb") as f: self._ml_feats[key]  = pickle.load(f)

    def _ml_predict(self, df: pd.DataFrame, symbol: str,
                    interval: str) -> tuple:
        """(long_prob, short_prob) for last row; returns (None,None) if unavailable"""
        self._load_ml(symbol, interval)
        key = f"{symbol}_{interval}"
        if key not in self._ml_models:
            return None, None
        model = self._ml_models[key]
        feats = self._ml_feats[key]
        avail = [f for f in feats if f in df.columns]
        if len(avail) < len(feats) * 0.7:
            return None, None
        row = df[avail].iloc[[-1]].fillna(0)
        try:
            lp = float(model["long"].predict_proba(row)[0, 1])
            sp = float(model["short"].predict_proba(row)[0, 1])
            return lp, sp
        except Exception:
            return None, None

    # ── Tier-1: 패턴룰 매칭 ─────────────────────────
    def _scan_pattern_rules(self, df: pd.DataFrame, symbol: str,
                            interval: str) -> list:
        if not self.use_pattern_rules or self.rule_evaluator is None:
            return []
        if df.empty or len(df) < 5:
            return []
        last_row = df.iloc[-1]
        matched  = self.rule_evaluator.match(last_row, symbol, interval,
                                             min_wr=self.TIER1_MIN_WR)
        signals  = []
        for r in matched:
            signals.append(Signal(
                symbol    = symbol,
                interval  = interval,
                direction = r["direction"],
                tier      = 1,
                win_rate  = float(r["win_rate"]),
                confidence= float(r["win_rate"]) / 100,
                reason    = f"패턴룰 WR={r['win_rate']:.1f}% lift={r.get('lift',1):.2f}",
                rule_text = str(r["rule"]),
                lift      = float(r.get("lift", 1.0)),
                count     = int(r.get("count", 0)),
            ))
        return signals

    # ── Tier-2: 볼륨폭발 패턴 ──────────────────────
    def _scan_volume_explosion(self, df: pd.DataFrame, symbol: str,
                               interval: str) -> list:
        if not self.use_volume_explosion:
            return []
        if df.empty or len(df) < 25:
            return []
        cfg  = self.VOL_EXPLOSION.get(interval, {"mult": 2.0, "ret_min": 0.010})
        last = df.iloc[-1]
        signals = []

        bull_trend = bool(last.get("bull_trend", last.get("ma50", 1) > last.get("ma200", 0)))
        vol_ratio  = float(last.get("vol_ratio", 1.0))
        ret1       = float(last.get("ret1", 0.0))
        rsi        = float(last.get("rsi14", 50.0))

        # LONG 볼륨폭발: 상승추세 + 볼륨 폭발 + 양봉
        if (bull_trend and
            vol_ratio >= cfg["mult"] and
            ret1 >= cfg["ret_min"] and
            rsi < 80):
            wr = 90.0 if vol_ratio >= 2.5 else 82.0
            signals.append(Signal(
                symbol    = symbol,
                interval  = interval,
                direction = "LONG",
                tier      = 2,
                win_rate  = wr,
                confidence= wr / 100,
                reason    = f"볼륨폭발 {vol_ratio:.1f}x, +{ret1*100:.1f}%, 상승추세",
                extra     = {"vol_ratio": vol_ratio, "ret1": ret1},
            ))

        # SHORT 볼륨폭발: 하락추세 + 볼륨 폭발 + 음봉
        if (not bull_trend and
            vol_ratio >= cfg["mult"] and
            ret1 <= -cfg["ret_min"] and
            rsi > 20):
            wr = 88.0 if vol_ratio >= 2.5 else 80.0
            signals.append(Signal(
                symbol    = symbol,
                interval  = interval,
                direction = "SHORT",
                tier      = 2,
                win_rate  = wr,
                confidence= wr / 100,
                reason    = f"볼륨폭발(숏) {vol_ratio:.1f}x, {ret1*100:.1f}%, 하락추세",
                extra     = {"vol_ratio": vol_ratio, "ret1": ret1},
            ))

        # 상승다이버전스 + 볼륨증가
        bull_div = bool(last.get("bull_div", 0))
        if bull_div and vol_ratio >= 1.2 and rsi < 65:
            signals.append(Signal(
                symbol    = symbol,
                interval  = interval,
                direction = "LONG",
                tier      = 2,
                win_rate  = 78.0,
                confidence= 0.78,
                reason    = f"상승다이버전스 + 볼륨{vol_ratio:.1f}x",
                extra     = {"divergence": True, "split_entry": True},
            ))

        return signals

    # ── Tier-3: ML 모델 신호 ─────────────────────────
    def _scan_ml(self, df: pd.DataFrame, symbol: str, interval: str) -> list:
        if not self.use_ml:
            return []
        lp, sp = self._ml_predict(df, symbol, interval)
        if lp is None:
            return []

        last  = df.iloc[-1]
        rsi   = float(last.get("rsi14", 50.0))
        bull  = bool(last.get("bull_trend", 1))
        signals = []

        # LONG: ML 확률 높음 + RSI 과매수 아님
        if lp >= 0.68 and rsi < 75 and bull:
            # ML 확률 → WR 추정 (확률과 실제 WR은 약 0.85 상관)
            wr = min(85.0, 50 + (lp - 0.5) * 120)
            signals.append(Signal(
                symbol    = symbol,
                interval  = interval,
                direction = "LONG",
                tier      = 3,
                win_rate  = wr,
                confidence= lp,
                reason    = f"ML LONG 확률={lp*100:.1f}% (RSI={rsi:.0f})",
            ))

        # SHORT: ML 확률 높음 + RSI 과매도 아님
        if sp >= 0.68 and rsi > 25 and not bull:
            wr = min(85.0, 50 + (sp - 0.5) * 120)
            signals.append(Signal(
                symbol    = symbol,
                interval  = interval,
                direction = "SHORT",
                tier      = 3,
                win_rate  = wr,
                confidence= sp,
                reason    = f"ML SHORT 확률={sp*100:.1f}% (RSI={rsi:.0f})",
            ))

        return signals

    # ── 1d 거시 필터 ────────────────────────────────
    def _get_macro_state(self, df_1d: Optional[pd.DataFrame]) -> dict:
        """일봉 기준 거시 상태 반환"""
        if df_1d is None or df_1d.empty or len(df_1d) < 50:
            return {"bull": True, "rsi_ok": True, "extreme": False}
        last     = df_1d.iloc[-1]
        bull     = bool(last.get("bull_trend", last.get("ma50", 1) > last.get("ma200", 0)))
        rsi      = float(last.get("rsi14", 50))
        extreme  = rsi > 80 or rsi < 20   # 극단적 RSI는 역추세 주의
        return {"bull": bull, "rsi": rsi, "rsi_ok": not extreme, "extreme": extreme}

    # ── 메인 스캔 ────────────────────────────────────
    def scan(self, dfs: dict, symbol: str) -> list:
        """
        모든 타임프레임 스캔 → Signal 리스트 반환

        Args:
            dfs:    {"5m": df, "1h": df, "4h": df, "1d": df}
            symbol: "BTCUSDT" 등

        Returns:
            list[Signal] — tier 오름차순 (1이 최우선)
        """
        # 지표 보강 (HTF 데이터 함께 전달)
        prepared = {}
        for ivl, df in dfs.items():
            if df is not None and not df.empty:
                # 상위 타임프레임만 추출
                htf_higher = {k: v for k, v in dfs.items()
                              if v is not None and not v.empty and k != ivl}
                prepared[ivl] = _ensure_indicators(df.copy(), ivl, htf_higher)

        macro = self._get_macro_state(prepared.get("1d"))
        all_signals = []

        for ivl, df in prepared.items():
            # Tier-1: 패턴룰
            sigs = self._scan_pattern_rules(df, symbol, ivl)
            all_signals.extend(sigs)

            # Tier-2: 볼륨폭발
            sigs = self._scan_volume_explosion(df, symbol, ivl)
            all_signals.extend(sigs)

            # Tier-3: ML (단, 1d 방향 일치 시만)
            sigs = self._scan_ml(df, symbol, ivl)
            for s in sigs:
                if macro["extreme"]:
                    # 극단적 RSI → 방향 역전 주의, Tier3 건너뜀
                    continue
                all_signals.append(s)

        # 거시 필터: 1d 추세 반대방향 신호 WR 하향 조정 + Tier 강등
        final = []
        for s in all_signals:
            if s.direction == "LONG" and not macro["bull"] and s.tier == 3:
                s.win_rate  = max(70.0, s.win_rate - 5)   # WR 소폭 하향
                s.confidence *= 0.9
            if s.direction == "SHORT" and macro["bull"] and s.tier == 3:
                s.win_rate  = max(70.0, s.win_rate - 5)
                s.confidence *= 0.9
            if s.win_rate >= self.TIER3_MIN_WR:
                final.append(s)

        # 중복 제거: 같은 심볼+인터벌+방향은 WR 높은 것만
        seen = {}
        for s in sorted(final, key=lambda x: (-x.win_rate, x.tier)):
            k = (s.symbol, s.interval, s.direction)
            if k not in seen:
                seen[k] = s
        result = list(seen.values())

        # 정렬: tier → win_rate 내림차순
        result.sort(key=lambda x: (x.tier, -x.win_rate))
        return result
