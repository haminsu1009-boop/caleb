# 퀀트 트레이딩 봇 — 위아래로 발라먹기

> **목표**: 코인 + 주식 전 종목을 롱/숏 양방향으로 AI가 스스로 학습해서 수익 창출  
> **현재 단계**: 페이퍼 트레이딩 검증 중

---

## 아키텍처 개요

```
데이터 수집 → 피처 엔지니어링 → ML 모델 → 신호 생성 → 실행
    ↑                                              ↓
    └──────── 온라인 학습 (연속 업데이트) ←── 결과 피드백
```

---

## 폴더 구조

```
caleb/
├── data/                      # 시장 데이터
│   ├── btc_daily.csv          # BTC 일봉 (합성)
│   ├── all_coins_daily.csv    # 멀티코인 통합
│   └── stocks/                # 주식 데이터 캐시
│
├── ml/                        # ML 엔진
│   ├── features.py            # 피처 엔지니어링 (90+ 피처)
│   ├── multi_timeframe.py     # 멀티 타임프레임 (W/M/Q/4H/1H)
│   ├── regime.py              # 시장 국면 감지 (BULL/NEUTRAL/BEAR)
│   ├── models.py              # XGBoost + TemporalXGB 앙상블
│   │                          # ← DirectionalEnsemble (롱+숏 동시)
│   ├── tune.py                # 임계값 / 하이퍼파라미터 최적화
│   ├── trainer.py             # 워크포워드 백테스트
│   ├── online_learner.py      # 연속 학습 (새 데이터 자동 반영)
│   ├── full_pipeline.py       # 개선된 롱-온리 파이프라인
│   └── saved_models/          # 저장된 모델 파일
│
├── coin/                      # 코인 트레이딩
│   ├── exchange.py            # Binance API (HMAC 서명)
│   ├── risk.py                # 리스크 관리 + Kelly Criterion
│   ├── data_fetcher.py        # 실시간 데이터 수집
│   ├── scanner.py             # 유니버설 티커 스캐너 ← NEW
│   ├── directional_trader.py  # 롱/숏 양방향 페이퍼 트레이더 ← NEW
│   ├── paper_trader.py        # 기존 롱-온리 페이퍼 트레이더
│   └── live_trader.py         # 실제 주문 실행 (위험!)
│
├── stocks/                    # 주식 통합 ← NEW
│   └── fetcher.py             # 한국주식(KRX) + 미국주식(yfinance)
│
├── charts/                    # 시각화 결과
├── results/                   # 거래 이력, 검증 결과
│
├── run_directional.py         # ★ 메인 실행 (롱/숏 파이프라인) ← NEW
├── run_all.py                 # 기존 롱-온리 파이프라인
├── generate_multi_coin_data.py # 멀티코인 합성 데이터
├── generate_sample_data.py    # BTC 합성 데이터
└── collect_data.py            # 실제 데이터 수집 (로컬 실행)
```

---

## 주요 기능

### 1. 방향성 ML (롱/숏 동시 지원)

```python
# run_directional.py
python run_directional.py          # 전체 파이프라인
python run_directional.py --scan   # 유니버설 스캔
python run_directional.py --online # 연속 학습 루프
```

**DirectionalEnsemble** 모델:
- LONG 모델 (XGBoost + TemporalXGB) — 상승 확률 예측
- SHORT 모델 (XGBoost + TemporalXGB) — 하락 확률 예측
- 신호: `long_prob ≥ threshold → LONG`, `short_prob ≥ threshold → SHORT`

### 2. 멀티 타임프레임 피처 (132개)

| 타임프레임 | 피처 수 | 예시 |
|-----------|---------|------|
| 일봉 기본  | 90개    | RSI, MACD, BB, ADX, OBV |
| 주봉(5일)  | 12개    | w_rsi, w_macd_hist, w_sma4_vs_13 |
| 월봉(21일) | 10개    | m_rsi_9, m_channel_pos, m_trend_align |
| 분기(63일) | 8개     | q_channel_pos, q_vs_52w_high |
| 4H/1H 패턴 | 12개   | h4_bull_ratio, h1_vol_cluster, wick_imbalance |

### 3. 유니버설 스캐너

```python
# 코인 + 주식 전종목 스캔
from coin.scanner import UniversalScanner
scanner = UniversalScanner(long_thr=0.62, short_thr=0.60)
results = scanner.scan()    # 코인 20 + 한국주식 10 + 미국주식 12
scanner.print_report(results)
```

출력 예시:
```
📈 LONG 기회 TOP 5
  BTCUSDT  롱확률=0.71  숏확률=0.31  BULL  +3.2%
  NVDA     롱확률=0.68  숏확률=0.29  BULL  +5.1%

📉 SHORT 기회 TOP 5
  DOGEUSDT 숏확률=0.65  롱확률=0.28  BEAR  -4.3%
  TSLA     숏확률=0.63  롱확률=0.31  BEAR  -6.2%
```

### 4. 온라인 학습

```python
from ml.online_learner import OnlineLearner
learner = OnlineLearner(window_days=500, retrain_every=7)
learner.update(new_df)          # 새 데이터 7일 누적 → 자동 재학습
signal = learner.predict_latest()
```

- **롤링 윈도우**: 최근 500일 데이터로만 학습 (오래된 패턴 자동 희석)
- **체크포인트**: 재학습마다 모델 버전 저장 (최근 3개 유지)
- **드리프트 감지**: 평균 신뢰도 < 0.52 → 즉시 재학습 트리거

### 5. 양방향 페이퍼 트레이더

```python
python coin/directional_trader.py 60   # 60분 간격 실행
```

- LONG + SHORT 동시 포지션 관리
- 방향 전환 시 기존 포지션 자동 청산
- 트레일링 스탑 (3%), 고정 손절(4%), 익절(8%)
- 공매도 대차 수수료 자동 계산

---

## 현재 백테스트 결과

### 롱-온리 파이프라인 (ml/full_pipeline.py)
| 지표 | 수치 |
|------|------|
| 평균 승률 | **56.0%** |
| 55%+ 달성 Fold | 14 / 22 |
| 60%+ 달성 Fold | 11 / 22 |
| 최적 임계값 | 0.72 |
| 총 신호 수 | 492회 |

### 방향성 파이프라인 (run_directional.py)
*진행 중*

---

## 실행 순서 (처음 시작)

```bash
# 1. 환경 설정
pip install xgboost scikit-learn pandas numpy matplotlib

# 2. 데이터 생성 (Binance API 없이)
python generate_sample_data.py
python generate_multi_coin_data.py

# 3. 롱-온리 파이프라인 (기준선)
python ml/full_pipeline.py

# 4. 방향성 파이프라인 (롱+숏)
python run_directional.py

# 5. 전종목 스캔
python run_directional.py --scan

# 6. 페이퍼 트레이딩 (자동 루프)
python coin/directional_trader.py 60

# 7. 연속 학습 루프
python run_directional.py --online --interval 60
```

---

## 실제 데이터 수집 (로컬 실행 권장)

```bash
# Binance에서 실제 BTC 데이터 수집
python collect_data.py

# 주식 데이터 수집
python stocks/fetcher.py

# API 키 설정 (.env 파일)
cp .env.example .env
# BINANCE_API_KEY, TELEGRAM_TOKEN 등 설정
```

---

## 로드맵

| 단계 | 상태 | 설명 |
|------|------|------|
| ✅ 데이터 수집 | 완료 | BTC + 멀티코인 합성 데이터 |
| ✅ 백테스트 | 완료 | 26개 지표 조합 테스트 |
| ✅ ML 모델 | 완료 | XGBoost + TemporalXGB 앙상블 |
| ✅ 시장 국면 | 완료 | BULL/NEUTRAL/BEAR 필터 |
| ✅ 임계값 최적화 | 완료 | 자동 스윕 0.50~0.82 |
| ✅ 멀티코인 | 완료 | BTC+ETH+BNB+SOL |
| ✅ 숏 신호 | 완료 | DirectionalEnsemble |
| ✅ 멀티 타임프레임 | 완료 | W/M/Q/4H/1H 피처 |
| ✅ 유니버설 스캐너 | 완료 | 코인+주식 전종목 |
| ✅ 온라인 학습 | 완료 | 롤링 윈도우 + 자동 재학습 |
| ✅ 양방향 페이퍼 트레이더 | 완료 | 롱/숏 시뮬레이션 |
| 🔄 실제 데이터 검증 | 진행중 | 로컬 Binance 데이터 필요 |
| ⏳ 분봉 데이터 | 대기중 | 1m/5m/15m/1H 실제 수집 |
| ⏳ 실거래 | 대기중 | 페이퍼 트레이딩 검증 후 |
