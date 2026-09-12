# 📈 AI 주식 추천 봇

미국 + 한국 주식을 **단기 / 중기 / 장기** 투자 기간에 맞춰 AI가 분석·추천하는 Python 봇입니다.

---

## 아키텍처

```
stock-bot/
├── config.py              # API 키, 감시 종목, 지표 파라미터, 가중치
├── main.py                # CLI 진입점 & 스케줄러
├── recommender.py         # 점수 계산 및 종목 순위 산출
├── requirements.txt
├── .env.example           # 환경변수 템플릿
│
├── data/
│   ├── fetcher.py         # yfinance 기반 OHLCV + 펀더멘털 수집
│   └── kis_api.py         # 한국투자증권 KIS REST API 래퍼
│
├── analysis/
│   ├── indicators.py      # 기술적 지표 (RSI, MACD, 볼린저, 거래량, 모멘텀)
│   └── fundamental.py     # 펀더멘털 분석 (P/E, EPS, ROE, 매출 성장)
│
└── ai/
    └── claude_advisor.py  # Claude API 자연어 투자 해설 생성
```

---

## 설치

```bash
cd stock-bot
pip install -r requirements.txt

# 환경변수 설정
cp .env.example .env
# .env 파일에서 API 키 입력
```

---

## 사용법

### 즉시 분석 (중기 기본값)
```bash
python main.py
```

### 단기 추천 (상위 10개)
```bash
python main.py --horizon 단기 --top 10
```

### 단기/중기/장기 전체 리포트
```bash
python main.py --full
```

### AI 해설 없이 점수만 출력
```bash
python main.py --no-ai
```

### 미국 주식만 분석
```bash
python main.py --us-only
```

### 한국 주식만 분석
```bash
python main.py --kr-only
```

### 추가 요청 사항 전달 (예: 반도체 섹터 집중)
```bash
python main.py --note "반도체 섹터 종목에 집중해서 분석해줘"
```

### 스케줄러 모드 (매일 오전 7시 + 30분 간격 업데이트)
```bash
python main.py --schedule
```

---

## 지표 상세

### 기술적 지표 (단기 투자에 비중↑)

| 지표 | 설명 | 매수 신호 |
|------|------|-----------|
| **RSI** (14일) | 과매수/과매도 | RSI < 30 (과매도) |
| **MACD** | 추세 방향·강도 | 히스토그램 양전환 |
| **볼린저밴드** | 변동성·돌파 | %B < 0.1 (하단 터치) |
| **거래량** | 수급 확인 | 평균 대비 1.5배↑ + OBV 상승 |
| **이동평균** | 추세 판단 | 가격 > MA20, MA5 > MA20 |
| **모멘텀** | 수익률 모멘텀 | 5/20/60일 모두 플러스 |

### 펀더멘털 지표 (장기 투자에 비중↑)

| 지표 | 설명 | 좋은 기준 |
|------|------|-----------|
| **P/E** | 주가수익비율 | Forward P/E < 20 |
| **EPS 성장** | 주당순이익 YoY | > 15% |
| **ROE** | 자기자본이익률 | > 15% |
| **매출 성장** | YoY 매출 증가율 | > 10% |
| **부채/자본** | 재무 안정성 | < 1.0 |

### 투자 기간별 가중치

| 지표 | 단기 | 중기 | 장기 |
|------|------|------|------|
| RSI | 20% | 10% | 5% |
| MACD | 20% | 10% | 5% |
| 볼린저밴드 | 15% | 10% | 5% |
| 거래량 | 15% | 10% | 5% |
| 이동평균 | 15% | 15% | 10% |
| 모멘텀 | 10% | 10% | 5% |
| **펀더멘털** | **5%** | **35%** | **65%** |

---

## API 키 발급 안내

- **Gemini (무료)**: https://aistudio.google.com → Get API key
- **KIS (한국투자증권)**: https://apiportal.koreainvestment.com/
- **Alpha Vantage**: https://www.alphavantage.co/support/#api-key
- **Alpaca**: https://alpaca.markets/ (페이퍼트레이딩 무료)

---

## ⚠️ 면책 조항

이 봇은 투자 참고 자료를 제공할 뿐이며, 특정 수익률을 보장하지 않습니다.  
투자 결정의 최종 책임은 본인에게 있으며, 원금 손실 위험이 있습니다.
