"""
Trading Strategy
================
기술 지표 + 뉴스 인사이트 → 매매 신호 생성
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TradingSignal:
    ticker:     str
    side:       str           # "BUY" | "SELL" | "HOLD"
    confidence: float         # 0 ~ 1
    reason:     str
    sources:    List[str] = field(default_factory=list)   # ["rsi", "macd", "news"]
    stop_loss_pct:   float = 0.05    # 손절 5%
    take_profit_pct: float = 0.15    # 익절 15%


# ─────────────────────────────────────────────
# 기술 지표 기반 신호
# ─────────────────────────────────────────────

def _tech_signal(ticker: str, indicators: Dict) -> Optional[TradingSignal]:
    """
    기술적 지표만으로 매매 신호 생성.
    indicators: analysis/indicators.py compute_all_indicators() 결과
    """
    if not indicators:
        return None

    rsi    = indicators.get("rsi",       {})
    macd   = indicators.get("macd",      {})
    bb     = indicators.get("bollinger", {})
    vol    = indicators.get("volume",    {})
    ma     = indicators.get("ma_cross",  {})
    mom    = indicators.get("momentum",  {})

    rsi_val   = rsi.get("value",     50)
    macd_hist = macd.get("histogram", 0)
    bb_pctb   = bb.get("pct_b",      0.5)
    vol_ratio = vol.get("ratio",     1.0)
    p_vs_ma20 = ma.get("price_vs_ma20", 0)
    mom20     = mom.get("mom_20",    0)

    buy_score  = 0.0
    sell_score = 0.0
    reasons    = []
    sources    = []

    # RSI
    if rsi_val < 30:
        buy_score += 0.30; reasons.append(f"RSI 과매도 ({rsi_val:.0f})"); sources.append("rsi")
    elif rsi_val > 70:
        sell_score += 0.30; reasons.append(f"RSI 과매수 ({rsi_val:.0f})"); sources.append("rsi")

    # MACD 히스토그램 방향
    if macd_hist > 0:
        buy_score  += 0.20; reasons.append("MACD 히스토그램 양전환"); sources.append("macd")
    else:
        sell_score += 0.20; reasons.append("MACD 히스토그램 음전환"); sources.append("macd")

    # 볼린저밴드 위치
    if bb_pctb < 0.15:
        buy_score  += 0.15; reasons.append(f"볼린저 하단 접근 (%B={bb_pctb:.2f})")
    elif bb_pctb > 0.85:
        sell_score += 0.15; reasons.append(f"볼린저 상단 돌파 (%B={bb_pctb:.2f})")
    sources.append("bollinger")

    # 거래량
    if vol_ratio > 1.5:
        if buy_score > sell_score:
            buy_score  += 0.10; reasons.append(f"거래량 급증 ({vol_ratio:.1f}x)")
        else:
            sell_score += 0.10; reasons.append(f"거래량 급증 ({vol_ratio:.1f}x) + 하락")
        sources.append("volume")

    # MA 교차
    if p_vs_ma20 > 0.02:
        buy_score  += 0.10; reasons.append("MA20 상향 돌파")
    elif p_vs_ma20 < -0.03:
        sell_score += 0.10; reasons.append("MA20 하향 이탈")
    sources.append("ma_cross")

    # 모멘텀
    if mom20 > 0.05:
        buy_score += 0.10
    elif mom20 < -0.05:
        sell_score += 0.10
    sources.append("momentum")

    # 결정
    if buy_score >= 0.55:
        return TradingSignal(
            ticker=ticker, side="BUY",
            confidence=min(buy_score, 1.0),
            reason=" / ".join(reasons[:4]),
            sources=list(set(sources)),
        )
    elif sell_score >= 0.55:
        return TradingSignal(
            ticker=ticker, side="SELL",
            confidence=min(sell_score, 1.0),
            reason=" / ".join(reasons[:4]),
            sources=list(set(sources)),
        )
    return None


# ─────────────────────────────────────────────
# 뉴스 인사이트 보정
# ─────────────────────────────────────────────

def _apply_news_boost(
    signal: Optional[TradingSignal],
    ticker: str,
    insights: List[Dict],
) -> Optional[TradingSignal]:
    """
    뉴스 인사이트에서 해당 티커에 대한 방향 정보를 가져와
    기술적 신호의 신뢰도를 조정.
    """
    news_direction = 0.0   # +1 = 매수, -1 = 매도
    news_reasons   = []

    for ins in insights:
        up_list   = [t.upper() for t in ins.get("tickers_up",   [])]
        down_list = [t.upper() for t in ins.get("tickers_down", [])]
        conf      = ins.get("confidence", 0.5)

        if ticker.upper() in up_list:
            news_direction += conf
            news_reasons.append(ins["event"])
        elif ticker.upper() in down_list:
            news_direction -= conf
            news_reasons.append(ins["event"] + " (악재)")

    if news_direction == 0:
        return signal   # 뉴스에 해당 종목 없음 → 원래 신호 유지

    news_reason_str = " / ".join(news_reasons[:2])

    # 기존 기술적 신호가 없으면 뉴스만으로 신호 생성 (신뢰도 낮게)
    if signal is None:
        if abs(news_direction) >= 0.5:
            side = "BUY" if news_direction > 0 else "SELL"
            return TradingSignal(
                ticker=ticker, side=side,
                confidence=min(abs(news_direction) * 0.6, 0.7),
                reason=f"뉴스 인사이트: {news_reason_str}",
                sources=["news"],
            )
        return None

    # 기존 신호와 뉴스가 같은 방향이면 신뢰도 ↑, 반대면 ↓
    aligned = (signal.side == "BUY" and news_direction > 0) or \
              (signal.side == "SELL" and news_direction < 0)

    if aligned:
        signal.confidence = min(signal.confidence + abs(news_direction) * 0.15, 0.95)
        signal.reason    += f" + {news_reason_str}"
        signal.sources.append("news")
    else:
        # 뉴스가 반대 → 신뢰도 절반으로 감소
        signal.confidence *= 0.5
        if signal.confidence < 0.4:
            return None   # 신호 취소

    return signal


# ─────────────────────────────────────────────
# 메인: 전체 신호 생성
# ─────────────────────────────────────────────

def generate_signals(
    stock_data: Dict,          # fetch_all_stocks() 결과
    insights: List[Dict] = [], # analyze_market() 결과
    min_confidence: float = 0.55,
    max_signals: int = 5,
) -> List[TradingSignal]:
    """
    stock_data의 모든 종목에 대해 신호 생성.
    신뢰도 순으로 정렬, max_signals개 반환.
    """
    from analysis.indicators import compute_all_indicators

    signals = []
    for ticker, data in stock_data.items():
        try:
            df = data.get("ohlcv")
            if df is None or df.empty:
                continue
            ind    = compute_all_indicators(df)
            signal = _tech_signal(ticker, ind)
            signal = _apply_news_boost(signal, ticker, insights)
            if signal and signal.confidence >= min_confidence:
                signals.append(signal)
        except Exception as e:
            logger.error(f"[strategy] {ticker} 신호 생성 오류: {e}")

    signals.sort(key=lambda s: s.confidence, reverse=True)
    return signals[:max_signals]
