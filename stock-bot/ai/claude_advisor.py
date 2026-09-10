"""
Claude AI Advisor
=================
추천 결과를 바탕으로 Claude가 자연어 투자 해설을 생성
"""

import logging
from typing import Dict, List, Optional
import anthropic

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 클라이언트 초기화
# ─────────────────────────────────────────────

def _get_client() -> anthropic.Anthropic:
    from config import ANTHROPIC_API_KEY
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ─────────────────────────────────────────────
# 시스템 프롬프트
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """
당신은 10년 경력의 퀀트 애널리스트이자 AI 주식 투자 어드바이저입니다.

역할:
- 미국 주식(NYSE/NASDAQ)과 한국 주식(KOSPI/KOSDAQ) 전문가
- RSI, MACD, 볼린저밴드, 이동평균, 거래량, 모멘텀 등 기술적 지표와
  P/E, EPS 성장, ROE, 매출 성장, 부채비율 등 펀더멘털을 종합 분석
- 투자 기간(단기 1~3개월 / 중기 3~12개월 / 장기 1년+)에 따라 다른 관점 제공

출력 형식 규칙:
1. 반드시 한국어로 답변하세요.
2. 티커는 $기호를 붙여서 표기하세요 (예: $NVDA, $005930).
3. 점수가 높은 종목부터 서술하세요.
4. 각 종목에 대해: 추천 이유, 주요 지표 해석, 리스크 요인을 명시하세요.
5. 면책 조항: 마지막에 "이 분석은 AI가 생성한 정보이며 투자 결정의 최종 책임은 본인에게 있습니다." 추가.

주의: 투자는 원금 손실 위험이 있으며, 특정 수익률을 보장하지 않습니다.
""".strip()


# ─────────────────────────────────────────────
# 추천 해설 생성
# ─────────────────────────────────────────────

def generate_recommendation_report(
    top_stocks: List[Dict],
    horizon: str = "중기",
    user_note: str = "",
    stream: bool = False,
) -> str:
    """
    상위 추천 종목 리스트 → Claude 자연어 리포트.

    top_stocks 예시:
    [
        {
            "ticker": "NVDA",
            "score": 0.82,
            "rank": 1,
            "indicators": {"rsi": {"value": 52, "score": 0.55}, ...},
            "fundamental": {"pe_ratio": 45.2, "eps_growth": 0.85, ...},
            "current_price": 875.0,
        },
        ...
    ]
    horizon: "단기" | "중기" | "장기"
    """
    client = _get_client()

    # 종목 정보 직렬화
    stock_lines = []
    for s in top_stocks[:8]:  # 최대 8개
        ticker = s["ticker"]
        score  = s.get("score", 0)
        price  = s.get("current_price")
        ind    = s.get("indicators", {})
        fund   = s.get("fundamental", {})

        rsi_val    = ind.get("rsi",      {}).get("value",     "N/A")
        macd_hist  = ind.get("macd",     {}).get("histogram", "N/A")
        bb_pctb    = ind.get("bollinger",{}).get("pct_b",     "N/A")
        vol_ratio  = ind.get("volume",   {}).get("ratio",     "N/A")
        mom20      = ind.get("momentum", {}).get("mom_20",    "N/A")

        pe         = fund.get("pe_ratio")
        fpe        = fund.get("forward_pe")
        eps_g      = fund.get("eps_growth")
        roe        = fund.get("roe")
        rev_g      = fund.get("revenue_growth")
        sector     = fund.get("sector", "")

        line = (
            f"종목: ${ticker} | 종합점수: {score:.2f} | "
            f"현재가: {price} | 섹터: {sector}\n"
            f"  기술지표 - RSI: {rsi_val}, MACD히스토그램: {macd_hist}, "
            f"볼린저%B: {bb_pctb}, 거래량배수: {vol_ratio}, 20일모멘텀: {mom20}\n"
            f"  펀더멘털 - P/E: {pe}, Forward P/E: {fpe}, "
            f"EPS성장(YoY): {eps_g}, ROE: {roe}, 매출성장: {rev_g}"
        )
        stock_lines.append(line)

    user_msg = f"""
투자 기간: {horizon}
분석 대상 상위 종목:

{chr(10).join(stock_lines)}

{"추가 요청 사항: " + user_note if user_note else ""}

위 데이터를 바탕으로 {horizon} 투자 관점에서 상위 종목들에 대한 투자 해설 리포트를 작성해주세요.
각 종목에 대해 핵심 투자 포인트, 지표 해석, 목표 수익 가능성, 리스크를 설명하세요.
최종적으로 {horizon} 포트폴리오 배분 제안도 포함해주세요.
""".strip()

    try:
        if stream:
            full_text = ""
            with client.messages.stream(
                model="claude-opus-4-5",
                max_tokens=2000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            ) as s:
                for chunk in s.text_stream:
                    full_text += chunk
                    print(chunk, end="", flush=True)
            print()  # newline
            return full_text
        else:
            resp = client.messages.create(
                model="claude-opus-4-5",
                max_tokens=2000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            return resp.content[0].text
    except Exception as e:
        logger.error(f"[claude_advisor] API 호출 실패: {e}")
        return f"⚠️ Claude API 오류: {e}"


# ─────────────────────────────────────────────
# 단일 종목 심층 분석
# ─────────────────────────────────────────────

def analyze_single_stock(ticker: str, data: Dict, horizon: str = "중기") -> str:
    """
    단일 종목 심층 분석 리포트.
    data: fetch_all_stocks()의 단일 엔트리
    """
    client = _get_client()

    ind  = data.get("indicators", {})
    fund = data.get("fundamental", {})

    user_msg = f"""
종목: ${ticker}
투자 기간: {horizon}

기술 지표:
- RSI: {ind.get('rsi',{}).get('value', 'N/A')}
- MACD 히스토그램: {ind.get('macd',{}).get('histogram', 'N/A')}
- 볼린저밴드 %B: {ind.get('bollinger',{}).get('pct_b', 'N/A')}
- 거래량 배수: {ind.get('volume',{}).get('ratio', 'N/A')}
- 20일 모멘텀: {ind.get('momentum',{}).get('mom_20', 'N/A')}
- 가격 vs MA20: {ind.get('ma_cross',{}).get('price_vs_ma20', 'N/A')}

펀더멘털:
- P/E: {fund.get('pe_ratio')} | Forward P/E: {fund.get('forward_pe')}
- EPS 성장(YoY): {fund.get('eps_growth')}
- ROE: {fund.get('roe')}
- 매출 성장(YoY): {fund.get('revenue_growth')}
- 부채/자본: {fund.get('debt_to_equity')}
- 섹터: {fund.get('sector')}

${ticker}에 대해 {horizon} 투자 관점에서 심층 분석 리포트를 작성해주세요.
매수/관망/매도 의견과 그 근거를 명확히 제시하세요.
""".strip()

    try:
        resp = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        return resp.content[0].text
    except Exception as e:
        logger.error(f"[claude_advisor] {ticker} 심층분석 실패: {e}")
        return f"⚠️ 분석 실패: {e}"
