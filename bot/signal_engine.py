"""
bot/signal_engine.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
멀티 타임프레임 신호 엔진 — 최대 승률 + 최대 실행률

신호 우선순위 (Tier):
  Tier-1 (WR 90%+):  패턴룰 매칭 (DecisionTree 마이닝, Wilson 95% CI 필터)
  Tier-2 (WR 70%+):  볼륨폭발 패턴 [추정 70~75%, 다심볼 OOS 검증 필요]
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
    symbol:           str
    interval:         str
    direction:        str          # "LONG" | "SHORT"
    tier:             int          # 1=패턴룰, 2=볼륨폭발, 3=ML
    win_rate:         float        # 0~100
    confidence:       float        # 0~1 (ML 확률 or 규칙 WR/100)
    reason:           str          # 신호 근거 텍스트
    rule_text:        str = ""     # 패턴룰 전문 (Tier1)
    lift:             float = 1.0  # 패턴룰 lift
    count:            int   = 0    # 룰 샘플 수
    extra:            dict  = field(default_factory=dict)
    # ── 트레일링 스탑 설정 ──────────────────────────────────
    trailing_stop_pct: float = 0.0   # 고점 대비 청산 비율 (예: 0.15 = 15%)
    hold_style:        str   = ""    # "trend" | "swing" | "scalp"


# ──────────────────────────────────────────────────────────
# 트레일링 스탑 계산 유틸
# ──────────────────────────────────────────────────────────
# 레버리지별 권장 트레일링 스탑 비율
_TRAILING_BY_LEV = {
    2:  0.25,   # 2x → 25%
    3:  0.20,   # 3x → 20%
    5:  0.13,   # 5x → 13%
    7:  0.09,   # 7x → 9%
    10: 0.07,   # 10x → 7%
    12: 0.06,   # 12x → 6%
}

# 인터벌별 기본 트레일링 스탑 (레버리지 정보 없을 때)
_TRAILING_BY_INTERVAL = {
    "1d": 0.20,   # 일봉 — 큰 추세 보존
    "4h": 0.12,   # 4h 스윙
    "1h": 0.08,   # 1h 단기
    "30m": 0.06,
    "15m": 0.05,
    "5m": 0.04,
}

# 인터벌별 홀딩 스타일
_HOLD_STYLE = {
    "1d": "trend",   "3d": "trend",
    "4h": "swing",   "12h": "swing",
    "1h": "scalp",   "30m": "scalp",
    "15m": "scalp",  "5m": "scalp",
}


def calc_trailing_stop(interval: str, leverage: float = None) -> float:
    """
    레버리지 또는 인터벌 기준으로 트레일링 스탑 비율 반환.

    Args:
        interval:  "1d", "4h", "1h" 등
        leverage:  포지션 레버리지 (없으면 인터벌 기준)

    Returns:
        float: 0.0~1.0 (예: 0.15 = 고점 대비 -15% 시 청산)
    """
    if leverage is not None and leverage > 0:
        # 가장 가까운 레버리지 키 찾기
        levs = sorted(_TRAILING_BY_LEV.keys())
        closest = min(levs, key=lambda x: abs(x - leverage))
        return _TRAILING_BY_LEV[closest]
    return _TRAILING_BY_INTERVAL.get(interval, 0.12)


class TrailingStopTracker:
    """
    포지션별 트레일링 스탑 추적기.
    매 캔들마다 update() 호출 → should_exit() True 시 청산.

    사용 예:
        tracker = TrailingStopTracker(entry=4100, pct=0.20)
        for price in prices:
            if tracker.update(price).should_exit:
                break
    """

    def __init__(self, entry: float, pct: float):
        """
        Args:
            entry: 진입가
            pct:   트레일링 비율 (0.15 = 15%)
        """
        self.entry       = float(entry)
        self.pct         = float(pct)
        self.peak        = float(entry)
        self.stop_price  = entry * (1 - pct)
        self.current     = float(entry)
        self.should_exit = False
        self.bars_held   = 0

    def update(self, price: float) -> "TrailingStopTracker":
        """새 가격으로 스탑 갱신. self 반환 (체이닝 가능)"""
        self.current = float(price)
        self.bars_held += 1
        if price > self.peak:
            self.peak       = price
            self.stop_price = price * (1 - self.pct)
        if price <= self.stop_price:
            self.should_exit = True
        return self

    @property
    def return_pct(self) -> float:
        """현재 수익률 (진입가 기준)"""
        return (self.current - self.entry) / self.entry

    @property
    def peak_return_pct(self) -> float:
        """고점 수익률"""
        return (self.peak - self.entry) / self.entry

    def __repr__(self):
        return (f"TrailingStop(entry={self.entry:.0f}, peak={self.peak:.0f}, "
                f"stop={self.stop_price:.0f}, ret={self.return_pct*100:.1f}%, "
                f"exit={self.should_exit})")


# ──────────────────────────────────────────────────────────
# 패턴룰 평가기
# ──────────────────────────────────────────────────────────
def _wilson_lower(wins: float, n: int, z: float = 1.645) -> float:
    """Wilson Score 95% 신뢰구간 하한 (단측).

    샘플 수가 적을 때 WR이 과장되는 문제를 보정.
    예: n=35, WR=94% → Wilson 하한 = 85% (실제 기대 WR)
        n=10, WR=100% → Wilson 하한 = 74% (매우 불확실)
    """
    if n <= 0:
        return 0.0
    p = wins / n
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    margin = z * np.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return max(0.0, (center - margin) / denom)


class PatternRuleEvaluator:
    """패턴룰 CSV 로드 → DataFrame 행에 적용.

    통계 필터: n≥100 AND Wilson 하한 ≥80% 기준으로 룰 선별.
    (전체 302개 → 58개로 줄지만 이 58개가 통계적으로 신뢰 가능)
    """

    # 통계 유효성 기준 (변경 시 SignalEngine 상수와 동기화)
    DEFAULT_MIN_N       = 100
    DEFAULT_MIN_WILSON  = 80.0

    def __init__(self, rules_path: str = None,
                 min_n: int = None, min_wilson: float = None):
        if rules_path is None:
            rules_path = os.path.join(MODEL_DIR, "pattern_rules.csv")
        self.rules = pd.DataFrame()

        _min_n      = min_n      if min_n      is not None else self.DEFAULT_MIN_N
        _min_wilson = min_wilson if min_wilson is not None else self.DEFAULT_MIN_WILSON

        if os.path.exists(rules_path):
            raw = pd.read_csv(rules_path)
            # win_rate가 0~100 스케일인지 확인
            if raw["win_rate"].max() <= 1.01:
                raw["win_rate"] = raw["win_rate"] * 100

            # ── Wilson 신뢰구간 필터 ──────────────────────────
            raw["_wins"]    = (raw["win_rate"] / 100 * raw["count"]).round()
            raw["_wilson"]  = raw.apply(
                lambda r: _wilson_lower(r["_wins"], int(r["count"])) * 100, axis=1
            )
            before = len(raw)
            filtered = raw[(raw["count"] >= _min_n) &
                           (raw["_wilson"] >= _min_wilson)].copy()
            after = len(filtered)

            self.rules = filtered.drop(columns=["_wins", "_wilson"])
            import logging
            logging.getLogger(__name__).info(
                f"PatternRules 통계 필터: {before}개 → {after}개 "
                f"(n≥{_min_n}, Wilson하한≥{_min_wilson}%)"
            )

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

    TIER1_MIN_WR = 90.0   # 패턴룰 Tier1 최소 WR (Wilson CI 필터 통과 58개)
    TIER2_MIN_WR = 70.0   # 볼륨폭발 — 보수적 추정 (다심볼 검증 전 70% 하한)
    TIER3_MIN_WR = 70.0   # ML Tier3 최소 WR

    # ── 통계 유효성 필터 (Wilson 95% 신뢰구간 하한 기준) ──────
    # 근거: n=35에서 WR=94%를 신뢰할 수 없음 (실제 CI: 41~72%)
    # Wilson 하한 = 진짜 WR의 보수적 추정값 (95% 신뢰)
    MIN_SAMPLE_COUNT    = 100    # 최소 샘플 수 — 미만이면 룰 제외
    MIN_WILSON_LOWER    = 80.0   # Wilson 95% 하한 — 미만이면 룰 제외
    # 위 기준으로 302개 패턴룰 중 58개만 통과 (검증일: 2026-08-19)

    # 볼륨폭발 파라미터 (BTC 1d n=35로 통계 불충분 — 다심볼 합산 후 재검증 필요)
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
    # ⚠ 통계 주의: BTC 1d VE 단독 검증 n=35, WR=57.1% (CI 41~72%) — 불충분.
    # 현재 WR은 15개 심볼 합산 추정치. count=0 으로 기록하고, 반드시
    # 다심볼 OOS 검증 후 실제 WR 로 업데이트 필요.
    # 트레일링 스탑: 모멘텀 스파이크 특성상 디폴트의 절반 → 빠른 청산.
    _VE_TRAILING_FACTOR = 0.60   # 인터벌 기본 트레일링의 60% (더 빡빡하게)

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

        # 모멘텀 트레일링 스탑: 빠른 추세 포착 후 빠르게 이익 실현
        # (VE = 진입 트리거, 트레일링 스탑 = 청산 결정)
        ve_trailing = calc_trailing_stop(interval) * self._VE_TRAILING_FACTOR

        # LONG 볼륨폭발: 상승추세 + 볼륨 폭발 + 양봉
        # WR 근거: 15심볼 추정치 (미검증). 강한 VE(3x+)=75%, 중간(2x)=70%
        # BTC 1d 단독 WR=57.1%이므로 보수적 추정값 사용.
        if (bull_trend and
            vol_ratio >= cfg["mult"] and
            ret1 >= cfg["ret_min"] and
            rsi < 80):
            wr = 75.0 if vol_ratio >= 3.0 else 70.0
            signals.append(Signal(
                symbol           = symbol,
                interval         = interval,
                direction        = "LONG",
                tier             = 2,
                win_rate         = wr,
                confidence       = wr / 100,
                reason           = f"볼륨폭발 {vol_ratio:.1f}x, +{ret1*100:.1f}%, 상승추세 [통계미검증]",
                count            = 0,           # 다심볼 OOS 검증 전 — Wilson 필터 미적용
                trailing_stop_pct= ve_trailing,  # 모멘텀 청산: 빠른 트레일링
                hold_style       = "scalp" if interval in ("5m","15m","1h") else "swing",
                extra            = {"vol_ratio": vol_ratio, "ret1": ret1,
                                    "ve_stat": "pending_verification"},
            ))

        # SHORT 볼륨폭발: 하락추세 + 볼륨 폭발 + 음봉
        if (not bull_trend and
            vol_ratio >= cfg["mult"] and
            ret1 <= -cfg["ret_min"] and
            rsi > 20):
            wr = 73.0 if vol_ratio >= 3.0 else 68.0
            # SHORT WR은 LONG보다 낮게: 크립토 상방 바이어스 고려
            signals.append(Signal(
                symbol           = symbol,
                interval         = interval,
                direction        = "SHORT",
                tier             = 2,
                win_rate         = wr,
                confidence       = wr / 100,
                reason           = f"볼륨폭발(숏) {vol_ratio:.1f}x, {ret1*100:.1f}%, 하락추세 [통계미검증]",
                count            = 0,
                trailing_stop_pct= ve_trailing,
                hold_style       = "scalp" if interval in ("5m","15m","1h") else "swing",
                extra            = {"vol_ratio": vol_ratio, "ret1": ret1,
                                    "ve_stat": "pending_verification"},
            ))

        # 상승다이버전스 + 볼륨증가
        bull_div = bool(last.get("bull_div", 0))
        if bull_div and vol_ratio >= 1.2 and rsi < 65:
            signals.append(Signal(
                symbol           = symbol,
                interval         = interval,
                direction        = "LONG",
                tier             = 2,
                win_rate         = 72.0,
                confidence       = 0.72,
                reason           = f"상승다이버전스 + 볼륨{vol_ratio:.1f}x [통계미검증]",
                count            = 0,
                trailing_stop_pct= ve_trailing,
                hold_style       = "swing",
                extra            = {"divergence": True, "split_entry": True,
                                    "ve_stat": "pending_verification"},
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

        # ── 트레일링 스탑 & 홀딩 스타일 자동 설정 ────────────
        for s in result:
            if s.trailing_stop_pct == 0.0:
                s.trailing_stop_pct = calc_trailing_stop(s.interval)
            if not s.hold_style:
                s.hold_style = _HOLD_STYLE.get(s.interval, "swing")

        # 정렬: tier → win_rate 내림차순
        result.sort(key=lambda x: (x.tier, -x.win_rate))
        return result
