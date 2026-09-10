"""
Fundamental Analysis
====================
P/E, EPS 성장, ROE, 매출 성장, 부채비율 등 기초 분석
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 개별 지표 점수화 (0 ~ 1)
# ─────────────────────────────────────────────

def score_pe(pe: Optional[float], forward_pe: Optional[float]) -> float:
    """
    P/E 비율 점수.
    낮을수록 저평가 → 높은 점수. 섹터 평균 고려 없이 절대값 기준.
    """
    use_pe = forward_pe if forward_pe is not None else pe
    if use_pe is None or use_pe <= 0:
        return 0.50   # 데이터 없음 → 중립
    if use_pe < 10:
        return 0.90
    elif use_pe < 15:
        return 0.80
    elif use_pe < 20:
        return 0.70
    elif use_pe < 30:
        return 0.55
    elif use_pe < 50:
        return 0.35
    else:
        return 0.20


def score_eps_growth(eps_growth: Optional[float]) -> float:
    """YoY EPS 성장률 점수."""
    if eps_growth is None:
        return 0.50
    if eps_growth > 0.50:
        return 0.95
    elif eps_growth > 0.30:
        return 0.85
    elif eps_growth > 0.15:
        return 0.75
    elif eps_growth > 0.05:
        return 0.65
    elif eps_growth > 0:
        return 0.55
    elif eps_growth > -0.10:
        return 0.40
    else:
        return 0.20


def score_roe(roe: Optional[float]) -> float:
    """ROE (자기자본이익률) 점수. 높을수록 좋음."""
    if roe is None:
        return 0.50
    if roe > 0.30:
        return 0.95
    elif roe > 0.20:
        return 0.85
    elif roe > 0.15:
        return 0.75
    elif roe > 0.10:
        return 0.65
    elif roe > 0.05:
        return 0.50
    else:
        return 0.25


def score_revenue_growth(rev_growth: Optional[float]) -> float:
    """YoY 매출 성장률 점수."""
    if rev_growth is None:
        return 0.50
    if rev_growth > 0.40:
        return 0.95
    elif rev_growth > 0.20:
        return 0.85
    elif rev_growth > 0.10:
        return 0.75
    elif rev_growth > 0.05:
        return 0.65
    elif rev_growth > 0:
        return 0.55
    elif rev_growth > -0.05:
        return 0.40
    else:
        return 0.20


def score_debt_to_equity(de: Optional[float]) -> float:
    """
    부채/자기자본 비율 점수.
    낮을수록 재무 안정성 ↑ → 높은 점수.
    단, 너무 낮으면 성장 투자 미흡일 수도 있어 0.85 상한.
    """
    if de is None:
        return 0.50
    if de < 0.20:
        return 0.85
    elif de < 0.50:
        return 0.80
    elif de < 1.00:
        return 0.70
    elif de < 2.00:
        return 0.55
    elif de < 5.00:
        return 0.35
    else:
        return 0.15


# ─────────────────────────────────────────────
# 종합 펀더멘털 점수
# ─────────────────────────────────────────────

FUNDAMENTAL_WEIGHTS = {
    "pe":           0.25,
    "eps_growth":   0.25,
    "roe":          0.20,
    "revenue":      0.20,
    "debt":         0.10,
}


def compute_fundamental_score(fund: Dict) -> Dict:
    """
    fetch_fundamentals() 결과를 받아 0~1 종합 펀더멘털 점수 반환.

    반환:
    {
        "score":          float,  # 종합 점수 0~1
        "pe_score":       float,
        "eps_score":      float,
        "roe_score":      float,
        "revenue_score":  float,
        "debt_score":     float,
        "pe_ratio":       float|None,
        "forward_pe":     float|None,
        "eps_growth":     float|None,
        "roe":            float|None,
        "revenue_growth": float|None,
        "debt_to_equity": float|None,
        "market_cap":     int|None,
        "sector":         str|None,
        "dividend_yield": float|None,
    }
    """
    pe_s  = score_pe(fund.get("pe_ratio"), fund.get("forward_pe"))
    eps_s = score_eps_growth(fund.get("eps_growth"))
    roe_s = score_roe(fund.get("roe"))
    rev_s = score_revenue_growth(fund.get("revenue_growth"))
    de_s  = score_debt_to_equity(fund.get("debt_to_equity"))

    composite = (
        FUNDAMENTAL_WEIGHTS["pe"]         * pe_s +
        FUNDAMENTAL_WEIGHTS["eps_growth"] * eps_s +
        FUNDAMENTAL_WEIGHTS["roe"]        * roe_s +
        FUNDAMENTAL_WEIGHTS["revenue"]    * rev_s +
        FUNDAMENTAL_WEIGHTS["debt"]       * de_s
    )

    return {
        "score":          round(composite, 4),
        "pe_score":       pe_s,
        "eps_score":      eps_s,
        "roe_score":      roe_s,
        "revenue_score":  rev_s,
        "debt_score":     de_s,
        # 원본 수치
        "pe_ratio":       fund.get("pe_ratio"),
        "forward_pe":     fund.get("forward_pe"),
        "eps_growth":     fund.get("eps_growth"),
        "roe":            fund.get("roe"),
        "revenue_growth": fund.get("revenue_growth"),
        "debt_to_equity": fund.get("debt_to_equity"),
        "market_cap":     fund.get("market_cap"),
        "sector":         fund.get("sector"),
        "dividend_yield": fund.get("dividend_yield"),
    }


# ─────────────────────────────────────────────
# 종목 요약 텍스트 생성 (Claude 프롬프트용)
# ─────────────────────────────────────────────

def fundamental_summary(ticker: str, fs: Dict) -> str:
    """
    펀더멘털 점수 딕셔너리를 한국어 요약 문자열로 변환.
    Claude 프롬프트에 컨텍스트로 주입.
    """
    lines = [f"[{ticker}] 펀더멘털 요약"]

    def fmt(val, fmt_str=":.2f", unit=""):
        if val is None:
            return "N/A"
        return f"{val{fmt_str}}{unit}"

    pe = fs.get("pe_ratio")
    fpe = fs.get("forward_pe")
    lines.append(f"  • P/E: {fmt(pe)} / Forward P/E: {fmt(fpe)}")
    lines.append(f"  • EPS 성장(YoY): {fmt(fs.get('eps_growth'), ':.1%')}")
    lines.append(f"  • ROE: {fmt(fs.get('roe'), ':.1%')}")
    lines.append(f"  • 매출 성장(YoY): {fmt(fs.get('revenue_growth'), ':.1%')}")
    lines.append(f"  • 부채/자본: {fmt(fs.get('debt_to_equity'))}")
    lines.append(f"  • 섹터: {fs.get('sector') or 'N/A'}")
    mc = fs.get("market_cap")
    if mc:
        mc_b = mc / 1e9
        lines.append(f"  • 시가총액: ${mc_b:.1f}B")
    dy = fs.get("dividend_yield")
    if dy:
        lines.append(f"  • 배당수익률: {dy:.2%}")
    lines.append(f"  ▶ 종합 점수: {fs.get('score', 0):.2f} / 1.00")
    return "\n".join(lines)
