"""
Recommender Engine
==================
단기 / 중기 / 장기 가중 점수로 종목 순위 산출
"""

import logging
from typing import Dict, List, Tuple
from config import WEIGHTS

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 단일 종목 종합 점수 계산
# ─────────────────────────────────────────────

def compute_score(
    indicators: Dict,
    fundamental_score: float,
    horizon: str = "중기",
) -> Tuple[float, Dict]:
    """
    지표별 점수와 가중치를 결합하여 0~1 종합 점수를 반환.

    indicators: analysis/indicators.py compute_all_indicators() 결과
    fundamental_score: analysis/fundamental.py compute_fundamental_score()["score"]
    horizon: "단기" | "중기" | "장기"

    반환: (종합점수, 세부점수딕셔너리)
    """
    w = WEIGHTS.get(horizon, WEIGHTS["중기"])

    component_scores = {
        "rsi":         indicators.get("rsi",       {}).get("score", 0.5),
        "macd":        indicators.get("macd",      {}).get("score", 0.5),
        "bollinger":   indicators.get("bollinger", {}).get("score", 0.5),
        "volume":      indicators.get("volume",    {}).get("score", 0.5),
        "ma_cross":    indicators.get("ma_cross",  {}).get("score", 0.5),
        "momentum":    indicators.get("momentum",  {}).get("score", 0.5),
        "fundamental": fundamental_score,
    }

    total = sum(w[k] * component_scores[k] for k in w)
    return round(total, 4), component_scores


# ─────────────────────────────────────────────
# 전체 감시 종목 랭킹
# ─────────────────────────────────────────────

def rank_stocks(
    stock_data: Dict,          # fetch_all_stocks() 결과
    horizon: str = "중기",
    top_n: int = 10,
) -> List[Dict]:
    """
    전체 감시 종목을 분석하여 상위 top_n개 반환.

    stock_data 구조:
    {
        "NVDA": {
            "ohlcv": pd.DataFrame,
            "fundamentals": {...},
            "current_price": float,
        },
        ...
    }

    반환 (내림차순 정렬):
    [
        {
            "ticker":        str,
            "score":         float,
            "rank":          int,
            "horizon":       str,
            "current_price": float,
            "indicators":    dict,
            "fundamental":   dict,
            "component_scores": dict,
        },
        ...
    ]
    """
    from analysis.indicators  import compute_all_indicators
    from analysis.fundamental import compute_fundamental_score

    scored = []

    for ticker, data in stock_data.items():
        try:
            df   = data.get("ohlcv")
            fund = data.get("fundamentals", {})
            price = data.get("current_price")

            if df is None or df.empty:
                logger.warning(f"[recommender] {ticker}: OHLCV 없음, 스킵")
                continue

            ind = compute_all_indicators(df)
            if not ind:
                logger.warning(f"[recommender] {ticker}: 지표 계산 실패, 스킵")
                continue

            fund_result = compute_fundamental_score(fund)
            total, components = compute_score(ind, fund_result["score"], horizon)

            scored.append({
                "ticker":          ticker,
                "score":           total,
                "horizon":         horizon,
                "current_price":   price,
                "indicators":      ind,
                "fundamental":     fund_result,
                "component_scores": components,
            })

        except Exception as e:
            logger.error(f"[recommender] {ticker} 점수 계산 중 오류: {e}")

    # 내림차순 정렬
    scored.sort(key=lambda x: x["score"], reverse=True)

    # 순위 부여
    for i, item in enumerate(scored, 1):
        item["rank"] = i

    return scored[:top_n]


# ─────────────────────────────────────────────
# 세 기간 동시 추천
# ─────────────────────────────────────────────

def full_recommendation(
    stock_data: Dict,
    top_n: int = 5,
) -> Dict[str, List[Dict]]:
    """
    단기 / 중기 / 장기 추천 목록을 한 번에 반환.

    반환:
    {
        "단기": [...],
        "중기": [...],
        "장기": [...],
    }
    """
    return {
        "단기": rank_stocks(stock_data, horizon="단기", top_n=top_n),
        "중기": rank_stocks(stock_data, horizon="중기", top_n=top_n),
        "장기": rank_stocks(stock_data, horizon="장기", top_n=top_n),
    }


# ─────────────────────────────────────────────
# 콘솔 출력 유틸
# ─────────────────────────────────────────────

def print_ranking(ranked: List[Dict], horizon: str) -> None:
    """랭킹 결과 콘솔 출력"""
    print(f"\n{'='*60}")
    print(f"  [{horizon}] 상위 추천 종목")
    print(f"{'='*60}")
    for s in ranked:
        comp = s["component_scores"]
        print(
            f"  {s['rank']:2d}. ${s['ticker']:<12} "
            f"종합: {s['score']:.3f}  |  "
            f"RSI:{comp.get('rsi',0):.2f} "
            f"MACD:{comp.get('macd',0):.2f} "
            f"Fund:{comp.get('fundamental',0):.2f}"
        )
    print()
