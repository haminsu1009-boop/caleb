"""
quick_test.py
시스템 빠른 검증 스크립트 (~30초)

저장된 모델을 사용해서 핵심 모듈 동작 확인:
  1. 데이터 로드 & 피처 생성
  2. 방향성 타겟 검증 (누수 없음)
  3. 저장된 모델 로드 & 예측
  4. 유니버설 스캐너 (코인 4개)
  5. 온라인 학습기 업데이트 (기존 모델 사용)
  6. 멀티 타임프레임 피처

실행: python quick_test.py
"""

import os, sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
import pickle, json

PASS = "✅"
FAIL = "❌"

def test(name, fn):
    try:
        result = fn()
        print(f"  {PASS} {name}: {result}")
        return True
    except Exception as e:
        print(f"  {FAIL} {name}: {e}")
        return False


print("=" * 55)
print("  퀀트 트레이딩 봇 — 빠른 시스템 테스트")
print("=" * 55)

# ── 1. 데이터 ──────────────────────────────────────
print("\n[1] 데이터 & 피처 파이프라인")
from ml.features        import add_features, make_directional_targets, get_feature_cols
from ml.regime          import add_regime_features
from ml.multi_timeframe import add_multi_timeframe_features

test("BTC 데이터 로드", lambda: f"{len(pd.read_csv('data/btc_daily.csv'))}일")

df = pd.read_csv("data/btc_daily.csv")
df = add_features(df)
df = add_regime_features(df)
df = add_multi_timeframe_features(df)
df = make_directional_targets(df)

feature_cols = get_feature_cols(df)
test("피처 생성", lambda: f"{len(feature_cols)}개")

leaked = [c for c in ["target_long", "target_short", "direction"] if c in feature_cols]
test("타겟 누수 없음", lambda: f"OK — 누수={leaked}")
assert not leaked, f"타겟 누수 감지됨: {leaked}"

# ── 2. 멀티 타임프레임 피처 ──────────────────────────
print("\n[2] 멀티 타임프레임 피처")
from ml.multi_timeframe import get_mtf_feature_cols
mtf_cols = get_mtf_feature_cols(df)
test("주봉(W) 피처",   lambda: f"{sum(1 for c in mtf_cols if c.startswith('w_'))}개")
test("월봉(M) 피처",   lambda: f"{sum(1 for c in mtf_cols if c.startswith('m_'))}개")
test("분기(Q) 피처",   lambda: f"{sum(1 for c in mtf_cols if c.startswith('q_'))}개")
test("4H/1H 패턴",    lambda: f"{sum(1 for c in mtf_cols if c.startswith('h4_') or c.startswith('h1_'))}개")

# ── 3. 저장된 모델 로드 & 예측 ──────────────────────
print("\n[3] 저장된 모델 로드 & 예측")
from ml.models import DirectionalEnsemble

model_path = "ml/saved_models/directional_model.pkl"
thr_path   = "ml/saved_models/directional_thresholds.json"

def _load_model():
    if not os.path.exists(model_path):
        return "파일 없음 (run_directional.py 먼저 실행)"
    with open(model_path, "rb") as f:
        data = pickle.load(f)
    return f"피처 {len(data['feature_cols'])}개"

test("모델 파일 로드", _load_model)

def _load_thresh():
    if not os.path.exists(thr_path):
        return "없음"
    with open(thr_path) as f:
        t = json.load(f)
    return f"롱={t['long']:.2f}  숏={t['short']:.2f}"

test("임계값 파일",  _load_thresh)

def _predict_btc():
    if not os.path.exists(model_path):
        return "모델 없음"
    with open(model_path, "rb") as f:
        d = pickle.load(f)
    m  = d["model"]
    fc = d["feature_cols"]
    fc_in = [c for c in fc if c in df.columns]
    rows = df.iloc[-30:][fc_in].fillna(0)
    lp = float(m.predict_proba_long(rows)[-1])
    sp = float(m.predict_proba_short(rows)[-1])
    sig = "LONG" if lp >= 0.70 and lp >= sp else ("SHORT" if sp >= 0.68 else "NEUTRAL")
    return f"BTC 현재 신호: {sig}  (롱={lp:.3f}  숏={sp:.3f})"

test("BTC 예측", _predict_btc)

# ── 4. 스캐너 ────────────────────────────────────────
print("\n[4] 유니버설 스캐너 (코인 4개)")
from coin.scanner import UniversalScanner

def _scan():
    s = UniversalScanner(long_thr=0.70, short_thr=0.68)
    if not s.load_model():
        return "모델 없음 — 스킵"
    res = s.scan(
        crypto_symbols=["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"],
        kr_codes=[],
        us_tickers=[],
        verbose=False,
    )
    sigs = res["signal"].value_counts().to_dict()
    probs = res[["long_prob", "short_prob"]].mean().round(3)
    return (f"L={sigs.get('LONG',0)}  S={sigs.get('SHORT',0)}  N={sigs.get('NEUTRAL',0)}  "
            f"| 평균 롱확률={probs['long_prob']}  숏확률={probs['short_prob']}")

test("스캐너 코인 4개", _scan)

# ── 5. 온라인 학습기 (기존 모델 사용) ──────────────────
print("\n[5] 온라인 학습기 (업데이트 테스트)")
from ml.online_learner import OnlineLearner

def _online_update():
    learner = OnlineLearner(
        window_days=200,
        retrain_every=100,
        min_samples=500,   # 500 > 200 → 재학습 트리거 안 됨 (빠른 테스트)
    )
    df_small = df.dropna(subset=["target_long", "target_short"]).tail(200)
    result = learner.update(df_small, symbol="BTCUSDT")
    perf   = learner.get_performance()
    return f"버퍼={result['n_samples']}  재학습={result['retrained']}  상태={perf['status']}"

test("OnlineLearner 업데이트", _online_update)

# ── 6. 국면 감지 ─────────────────────────────────────
print("\n[6] 시장 국면 감지")
from ml.regime import get_regime_stats

def _regime():
    stats = get_regime_stats(df)
    lines = [f"{k}: {v['win_rate']*100:.1f}% ({v['days']}일)" for k, v in stats.items()]
    return "  ".join(lines)

test("국면 통계", _regime)

def _current_regime():
    reg_map = {2: "BULL", 1: "NEUTRAL", 0: "BEAR"}
    cur = df["regime"].dropna().iloc[-1]
    label = reg_map.get(int(cur), "UNKNOWN")
    return f"현재 BTC 국면: {label}"

test("현재 국면", _current_regime)

# ── 결과 요약 ─────────────────────────────────────────
print("\n" + "=" * 55)
print("  시스템 테스트 완료!")
print("")
print("  📌 명령어 가이드:")
print("  python run_directional.py            # 전체 파이프라인")
print("  python run_directional.py --scan     # 유니버설 스캔")
print("  python run_directional.py --online   # 연속 학습 루프")
print("  python coin/directional_trader.py 60 # 페이퍼 트레이딩")
print("  python stocks/fetcher.py             # 주식 데이터 수집")
print("=" * 55)
