"""
Telegram Alert Bot
==================
매매 신호·모닝 브리핑·오류 알림을 텔레그램으로 전송

설정 방법:
1. 텔레그램 앱에서 @BotFather 검색
2. /newbot → 이름 입력 → 토큰 받기
3. 봇에게 아무 메시지 전송
4. https://api.telegram.org/bot{TOKEN}/getUpdates 에서 chat_id 확인
5. .env에 TELEGRAM_TOKEN, TELEGRAM_CHAT_ID 입력
"""

import os
import logging
import requests
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


class TelegramBot:
    def __init__(self):
        self.token   = os.getenv("TELEGRAM_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self._enabled = bool(self.token and self.chat_id)
        if not self._enabled:
            logger.warning("[telegram] TELEGRAM_TOKEN 또는 TELEGRAM_CHAT_ID 없음. 알림 비활성화.")

    def _post(self, method: str, **kwargs) -> bool:
        if not self._enabled:
            return False
        url = TELEGRAM_API.format(token=self.token, method=method)
        try:
            resp = requests.post(url, json=kwargs, timeout=10)
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"[telegram] 전송 실패: {e}")
            return False

    def send(self, text: str, parse_mode: str = "HTML") -> bool:
        """일반 메시지 전송"""
        return self._post("sendMessage",
            chat_id=self.chat_id,
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
        )

    # ─────────────────────────────────────────
    # 포맷 헬퍼
    # ─────────────────────────────────────────

    @staticmethod
    def _arrow(val: Optional[float]) -> str:
        if val is None: return "—"
        return f"📈 +{val:.1f}%" if val > 0 else f"📉 {val:.1f}%"

    @staticmethod
    def _ticker_tag(ticker: str) -> str:
        return f"<code>${ticker}</code>"

    # ─────────────────────────────────────────
    # 모닝 브리핑 (매일 오전 7시)
    # ─────────────────────────────────────────

    def send_morning_brief(self, brief_text: str, insights: List[Dict]) -> bool:
        now = datetime.now(timezone.utc).strftime("%m/%d %H:%M UTC")
        header = f"🌅 <b>모닝 브리핑</b> · {now}\n{'─'*30}\n"
        footer = "\n\n⚠️ <i>이 알림은 AI 분석이며 투자 책임은 본인에게 있습니다.</i>"
        return self.send(header + brief_text + footer)

    # ─────────────────────────────────────────
    # 인사이트 알림 (원자재 → 종목 연결)
    # ─────────────────────────────────────────

    def send_insight_alert(self, insight: Dict) -> bool:
        """
        insight: {event, tickers_up, tickers_down, confidence, horizon, reasoning}
        """
        conf_bar = "🟢" * round(insight["confidence"] * 5) + "⚪" * (5 - round(insight["confidence"] * 5))
        up_tickers   = " ".join(self._ticker_tag(t) for t in insight.get("tickers_up",   []))
        down_tickers = " ".join(self._ticker_tag(t) for t in insight.get("tickers_down", []))

        text = (
            f"💡 <b>시장 인사이트</b>\n"
            f"{'─'*28}\n"
            f"📌 <b>{insight['event']}</b>\n\n"
            + (f"📈 <b>수혜</b>: {up_tickers}\n"   if up_tickers   else "")
            + (f"📉 <b>악재</b>: {down_tickers}\n" if down_tickers else "")
            + f"\n신뢰도: {conf_bar} {insight['confidence']:.0%} · 기간: {insight.get('horizon','중기')}\n"
            + f"\n<i>{insight['reasoning']}</i>"
        )
        return self.send(text)

    def send_bulk_insights(self, insights: List[Dict]) -> None:
        """여러 인사이트를 하나의 메시지로 묶어 전송"""
        if not insights:
            return
        lines = [f"🔍 <b>오늘의 시장 인사이트</b> ({len(insights)}건)\n{'─'*28}\n"]
        for i, ins in enumerate(insights, 1):
            up   = ", ".join(f"${t}" for t in ins.get("tickers_up",   [])[:3])
            down = ", ".join(f"${t}" for t in ins.get("tickers_down", [])[:2])
            conf = f"{ins['confidence']:.0%}"
            lines.append(
                f"{i}. {ins['event']}\n"
                + (f"   ▲ {up}\n"   if up   else "")
                + (f"   ▼ {down}\n" if down else "")
                + f"   신뢰도 {conf} · {ins.get('horizon','중기')}\n"
            )
        self.send("".join(lines))

    # ─────────────────────────────────────────
    # 매매 주문 알림
    # ─────────────────────────────────────────

    def send_trade_executed(
        self,
        ticker: str,
        side: str,           # "BUY" | "SELL"
        qty: float,
        price: float,
        reason: str,
        order_type: str = "MARKET",
    ) -> bool:
        emoji = "🟢 <b>매수</b>" if side == "BUY" else "🔴 <b>매도</b>"
        text = (
            f"{emoji} 주문 체결\n"
            f"{'─'*28}\n"
            f"종목: {self._ticker_tag(ticker)}\n"
            f"수량: {qty}주 @ ${price:,.2f}  ({order_type})\n"
            f"금액: ${qty * price:,.0f}\n\n"
            f"📋 <i>{reason}</i>"
        )
        return self.send(text)

    def send_trade_signal(self, signals: List[Dict]) -> bool:
        """매매 신호 예고 (아직 주문 전)"""
        if not signals:
            return False
        lines = [f"⚡ <b>매매 신호</b> ({len(signals)}건)\n{'─'*28}\n"]
        for s in signals:
            emoji = "🟢" if s["side"] == "BUY" else "🔴"
            lines.append(
                f"{emoji} {self._ticker_tag(s['ticker'])}  "
                f"{s['side']} · 신뢰도 {s.get('confidence', 0):.0%}\n"
                f"   {s.get('reason','')}\n"
            )
        return self.send("".join(lines))

    # ─────────────────────────────────────────
    # 포트폴리오 현황
    # ─────────────────────────────────────────

    def send_portfolio_summary(self, account: Dict, positions: List[Dict]) -> bool:
        equity = account.get("equity", 0)
        cash   = account.get("cash",   0)
        pnl    = account.get("unrealized_pnl", 0)
        pnl_pct = account.get("pnl_pct", 0)

        lines = [
            f"💼 <b>포트폴리오 현황</b>\n{'─'*28}\n",
            f"총 자산: <b>${equity:,.0f}</b>  현금: ${cash:,.0f}\n",
            f"평가손익: {'▲' if pnl >= 0 else '▼'} ${abs(pnl):,.0f} ({pnl_pct:+.1f}%)\n\n",
        ]
        if positions:
            lines.append("<b>보유 종목</b>\n")
            for p in positions[:8]:
                pnl_emoji = "📈" if p.get("unrealized_pnl_pct", 0) >= 0 else "📉"
                lines.append(
                    f"{pnl_emoji} {self._ticker_tag(p['ticker'])} "
                    f"{p.get('qty','?')}주 · "
                    f"{p.get('unrealized_pnl_pct', 0):+.1f}%\n"
                )
        return self.send("".join(lines))

    # ─────────────────────────────────────────
    # 오류 알림
    # ─────────────────────────────────────────

    def send_error(self, module: str, error: str) -> bool:
        text = f"🚨 <b>오류 발생</b>\n모듈: <code>{module}</code>\n<code>{error[:300]}</code>"
        return self.send(text)


# 싱글톤
_bot: Optional[TelegramBot] = None

def get_bot() -> TelegramBot:
    global _bot
    if _bot is None:
        _bot = TelegramBot()
    return _bot
