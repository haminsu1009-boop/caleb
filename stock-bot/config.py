"""
Stock Bot Configuration
=======================
미국 + 한국 주식 AI 추천 봇 설정 파일
"""

import os
from dataclasses import dataclass, field
from typing import List

# ─────────────────────────────────────────────
# API 키 설정 (.env 파일 또는 환경변수로 관리)
# ─────────────────────────────────────────────

# Google Gemini (무료 티어)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# 한국투자증권 KIS Developers (https://apiportal.koreainvestment.com/)
KIS_APP_KEY    = os.getenv("KIS_APP_KEY", "")
KIS_APP_SECRET = os.getenv("KIS_APP_SECRET", "")
KIS_ACCOUNT_NO = os.getenv("KIS_ACCOUNT_NO", "")   # 계좌번호 앞 8자리
KIS_ACCOUNT_SUFFIX = os.getenv("KIS_ACCOUNT_SUFFIX", "01")

# Alpha Vantage (무료: https://www.alphavantage.co/)
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY", "demo")

# Alpaca (미국 주식 실거래/페이퍼트레이딩: https://alpaca.markets/)
ALPACA_API_KEY    = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL   = "https://paper-api.alpaca.markets"  # 페이퍼 트레이딩

# ─────────────────────────────────────────────
# 분석 대상 종목 목록
# ─────────────────────────────────────────────

# 미국 주식 (Yahoo Finance 티커)
US_WATCHLIST = [
    "NVDA", "MSFT", "AAPL", "GOOGL", "META",
    "AMZN", "TSLA", "AVGO", "TSM", "ASML",
    "LLY", "NVO", "UNH", "JPM", "V",
    "QQQ", "SOXX", "VGT", "VOO", "SPY",
]

# 한국 주식 (Yahoo Finance: 티커.KS = 코스피, 티커.KQ = 코스닥)
KR_WATCHLIST = [
    "005930.KS",   # 삼성전자
    "000660.KS",   # SK하이닉스
    "035420.KS",   # NAVER
    "035720.KS",   # 카카오
    "051910.KS",   # LG화학
    "006400.KS",   # 삼성SDI
    "207940.KS",   # 삼성바이오로직스
    "068270.KS",   # 셀트리온
    "003550.KS",   # LG
    "373220.KS",   # LG에너지솔루션
    "086520.KQ",   # 에코프로
    "247540.KQ",   # 에코프로비엠
]

# ─────────────────────────────────────────────
# 기술적 분석 파라미터
# ─────────────────────────────────────────────

@dataclass
class IndicatorConfig:
    # 이동평균
    MA_SHORT:  int = 5
    MA_MID:    int = 20
    MA_LONG:   int = 60
    MA_200:    int = 200

    # RSI
    RSI_PERIOD:      int = 14
    RSI_OVERSOLD:    int = 30
    RSI_OVERBOUGHT:  int = 70

    # MACD
    MACD_FAST:   int = 12
    MACD_SLOW:   int = 26
    MACD_SIGNAL: int = 9

    # 볼린저 밴드
    BB_PERIOD: int = 20
    BB_STD:    float = 2.0

    # 거래량
    VOLUME_SURGE_RATIO: float = 1.5   # 평균 대비 1.5배 이상 = 거래량 급증

INDICATOR_CONFIG = IndicatorConfig()

# ─────────────────────────────────────────────
# 투자 기간별 점수 가중치
# ─────────────────────────────────────────────

WEIGHTS = {
    "단기":  # 1~3개월: 기술적 지표 위주
    {
        "rsi":          0.20,
        "macd":         0.20,
        "bollinger":    0.15,
        "volume":       0.15,
        "ma_cross":     0.15,
        "momentum":     0.10,
        "fundamental":  0.05,
    },
    "중기":  # 3~12개월: 기술 + 펀더멘털 혼합
    {
        "rsi":          0.10,
        "macd":         0.10,
        "bollinger":    0.10,
        "volume":       0.10,
        "ma_cross":     0.15,
        "momentum":     0.10,
        "fundamental":  0.35,
    },
    "장기":  # 1년+: 펀더멘털 위주
    {
        "rsi":          0.05,
        "macd":         0.05,
        "bollinger":    0.05,
        "volume":       0.05,
        "ma_cross":     0.10,
        "momentum":     0.05,
        "fundamental":  0.65,
    },
}

# ─────────────────────────────────────────────
# 스케줄러 설정
# ─────────────────────────────────────────────

SCHEDULE = {
    "us_market_open":   "09:30",   # 미국 동부시간 (한국 22:30)
    "kr_market_open":   "09:00",   # 한국시간
    "daily_report":     "07:00",   # 매일 오전 7시 (한국시간) 리포트
    "interval_minutes": 30,         # 장중 30분마다 업데이트
}

# 데이터 캐시 유효시간 (초)
CACHE_TTL = {
    "price":       60,      # 가격: 1분
    "indicators":  300,     # 지표: 5분
    "fundamental": 86400,   # 펀더멘털: 1일
}
