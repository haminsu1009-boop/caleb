"""
Market News Analyzer (Gemini)
=============================
뉴스·원자재 데이터를 읽고 "어떤 주식이 왜 오를지" 분석
예: RAM 가격 상승 → MU, NVDA 매수 신호
"""

import json
import logging
import os
from typing import Dict, List
import google.generativeai as genai

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Gemini 클라이언트
# ─────────────────────────────────────────────

def _get_model():
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        raise ValueError("GEMINI_API_KEY 없음")
    genai.configure(api_key=key)
    return genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        generation_config={"temperature": 0.4, "max_output_tokens": 3000},
    )


# ─────────────────────────────────────────────
# 시장 분석 프롬프트 빌더
# ─────────────────────────────────────────────

WATCHLIST_BRIEF = """
미국: NVDA(엔비디아), MSFT(마이크로소프트), AAPL(애플), GOOGL(알파벳), META(메타),
      AMZN(아마존), TSLA(테슬라), AVGO(브로드컴), TSM(TSMC), ASML(ASML),
      LLY(일라이릴리), NVO(노보노디스크), UNH(유나이티드헬스), JPM(JP모건), V(비자),
      QQQ(나스닥ETF), SOXX(반도체ETF), VOO(S&P500ETF)

한국: 005930(삼성전자), 000660(SK하이닉스), 035420(NAVER), 035720(카카오),
      207940(삼성바이오로직스), 068270(셀트리온), 003550(LG), 373220(LG에너지솔루션),
      086520(에코프로), 247540(에코프로비엠)
"""


def _build_analysis_prompt(snapshot: Dict) -> str:
    # 뉴스 정리
    news_lines = []
    for n in snapshot.get("news", [])[:20]:
        news_lines.append(f"• [{n['source']}] {n['title']}")
    news_text = "\n".join(news_lines) if news_lines else "뉴스 없음"

    # 원자재·지수 정리
    comm_lines = []
    for name, data in snapshot.get("commodities", {}).items():
        p   = data.get("price")
        chg = data.get("change_pct")
        if p is not None:
            arrow = ("▲" if chg > 0 else "▼") if chg else "−"
            comm_lines.append(f"  {name}: {p:,.2f}  {arrow}{abs(chg):.1f}%" if chg is not None else f"  {name}: {p:,.2f}")
    comm_text = "\n".join(comm_lines)

    return f"""
당신은 매크로 → 개별 종목 연결 전문 퀀트 애널리스트입니다.
분석 시각: {snapshot.get('timestamp', '')}

## 감시 종목 목록
{WATCHLIST_BRIEF}

## 오늘 주요 뉴스
{news_text}

## 시장 원자재 / 지수 현황
{comm_text}

## 요청

### 1. 매크로 → 개별 주식 연결 분석
뉴스와 원자재 가격 변동을 바탕으로, **감시 목록 종목들 중** 오늘/이번 주 영향받을 종목들을 찾아내세요.
예: "RAM 현물 가격 3개월 만에 최고 → MU, SK하이닉스 (+), PC 조립 브랜드 (−)"

**형식 (JSON 배열로만 출력):**
[
  {{
    "event": "이벤트/원인 요약 (한국어)",
    "tickers_up":   ["TICKER1", "TICKER2"],
    "tickers_down": ["TICKER3"],
    "confidence":   0~1,
    "horizon":      "단기|중기|장기",
    "reasoning":    "상세 근거 (2-3문장, 한국어)"
  }},
  ...
]

분석이 가능한 인사이트만 포함하세요. 근거 없는 항목은 제외.
JSON 이외의 텍스트는 출력하지 마세요.
""".strip()


def _build_brief_prompt(snapshot: Dict, insights: List[Dict]) -> str:
    """텔레그램용 모닝 브리핑 프롬프트"""
    insights_text = "\n".join([
        f"- {i['event']} → UP: {i['tickers_up']} / DOWN: {i['tickers_down']} (신뢰도 {i['confidence']:.0%})"
        for i in insights
    ])
    comm_lines = []
    for name, data in snapshot.get("commodities", {}).items():
        p = data.get("price"); chg = data.get("change_pct")
        if p and chg is not None:
            arrow = "▲" if chg > 0 else "▼"
            comm_lines.append(f"{name}: {arrow}{abs(chg):.1f}%")

    return f"""
아래 시장 분석 결과를 바탕으로 **투자자를 위한 한국어 모닝 브리핑**을 작성하세요.

시각: {snapshot.get('timestamp','')}

## 원자재 현황
{', '.join(comm_lines)}

## AI 분석 인사이트
{insights_text}

## 출력 형식 (Telegram HTML 스타일)
- <b>제목</b>: 굵게, <i>이탤릭</i>
- 이모지 적극 활용 (📈 📉 🔥 ⚠️ 💡)
- 300자 이내로 간결하게
- 티커는 $TICKER 형식
- 마지막에: "⚡ 오늘의 핵심 포인트" 1줄 요약
""".strip()


# ─────────────────────────────────────────────
# 핵심 분석 함수
# ─────────────────────────────────────────────

def analyze_market(snapshot: Dict) -> List[Dict]:
    """
    시장 스냅샷 → 구조화된 인사이트 목록 반환.
    반환: [{event, tickers_up, tickers_down, confidence, horizon, reasoning}]
    """
    model = _get_model()
    prompt = _build_analysis_prompt(snapshot)
    try:
        resp = model.generate_content(prompt)
        text = resp.text.strip()
        # JSON만 추출
        start = text.find("[")
        end   = text.rfind("]") + 1
        if start == -1 or end == 0:
            logger.warning("[analyzer] JSON 파싱 불가, 원문 반환")
            return []
        return json.loads(text[start:end])
    except Exception as e:
        logger.error(f"[analyzer] 분석 실패: {e}")
        return []


def generate_morning_brief(snapshot: Dict, insights: List[Dict]) -> str:
    """
    분석 인사이트 → 텔레그램용 모닝 브리핑 텍스트 생성.
    """
    if not insights:
        return "📊 오늘은 특별한 시장 신호가 없습니다. 기존 전략 유지."
    model = _get_model()
    prompt = _build_brief_prompt(snapshot, insights)
    try:
        resp = model.generate_content(prompt)
        return resp.text.strip()
    except Exception as e:
        logger.error(f"[analyzer] 브리핑 생성 실패: {e}")
        return f"⚠️ 브리핑 생성 실패: {e}"
