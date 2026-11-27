"""
coin/notifier.py
텔레그램 알림 봇

설정:
  1. @BotFather → /newbot → 토큰 받기
  2. @userinfobot → chat_id 확인
  3. .env에 TELEGRAM_TOKEN, TELEGRAM_CHAT_ID 입력
"""

import os
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

TOKEN   = os.getenv("TELEGRAM_TOKEN",   "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
BASE    = f"https://api.telegram.org/bot{TOKEN}"


def send(message: str, silent: bool = False) -> bool:
    """텔레그램 메시지 전송"""
    if not TOKEN or not CHAT_ID:
        print(f"[텔레그램 비활성] {message[:80]}")
        return False
    try:
        r = requests.post(
            f"{BASE}/sendMessage",
            json={
                "chat_id":              CHAT_ID,
                "text":                 message,
                "parse_mode":           "HTML",
                "disable_notification": silent,
            },
            timeout=10,
        )
        return r.ok
    except Exception as e:
        print(f"[텔레그램 오류] {e}")
        return False


# ── 미리 만든 메시지 템플릿 ─────────────────

def notify_signal(symbol: str, price: float,
                  prob: float, signal_type: str = "BUY"):
    emoji = "🟢" if signal_type == "BUY" else "🔴"
    msg = (
        f"{emoji} <b>ML 신호 발생</b>\n\n"
        f"코인:     <code>{symbol}</code>\n"
        f"현재가:   <b>${price:,.2f}</b>\n"
        f"매수 확률: <b>{prob*100:.1f}%</b>\n"
        f"신호:     <b>{signal_type}</b>\n"
        f"시각:     {datetime.now().strftime('%H:%M:%S')}"
    )
    return send(msg)


def notify_trade(action: str, symbol: str, qty: float,
                 price: float, usdt: float, stop: float, tp: float):
    emoji = "📈" if action == "BUY" else "📉"
    msg = (
        f"{emoji} <b>{'매수 체결' if action == 'BUY' else '매도 체결'}</b>\n\n"
        f"코인:    <code>{symbol}</code>\n"
        f"수량:    {qty:.6f}\n"
        f"가격:    ${price:,.2f}\n"
        f"투자금:  ${usdt:,.2f}\n"
    )
    if action == "BUY":
        msg += (
            f"손절:    ${stop:,.2f}  (-{(1-stop/price)*100:.1f}%)\n"
            f"익절:    ${tp:,.2f}   (+{(tp/price-1)*100:.1f}%)\n"
        )
    msg += f"시각:    {datetime.now().strftime('%H:%M:%S')}"
    return send(msg)


def notify_close(symbol: str, pnl: float, pnl_pct: float, reason: str):
    emoji = "✅" if pnl > 0 else "❌"
    msg = (
        f"{emoji} <b>포지션 종료</b>  [{reason}]\n\n"
        f"코인:   <code>{symbol}</code>\n"
        f"PnL:    <b>${pnl:+,.2f}  ({pnl_pct:+.2f}%)</b>\n"
        f"시각:   {datetime.now().strftime('%H:%M:%S')}"
    )
    return send(msg)


def notify_daily_report(summary: dict):
    wr_emoji = "🎯" if summary["win_rate"] >= 55 else "⚠️"
    msg = (
        f"📊 <b>일일 리포트</b>  {datetime.now().strftime('%Y-%m-%d')}\n\n"
        f"현재 자산:  <b>${summary['capital']:,.2f}</b>\n"
        f"오늘 PnL:   <b>${summary['daily_pnl']:+,.2f}</b>\n"
        f"총 거래:    {summary['total_trades']}회\n"
        f"승률:       {wr_emoji} {summary['win_rate']:.1f}%\n"
        f"누적 PnL:   ${summary['total_pnl']:+,.2f}\n"
        f"오픈 포지션: {summary['open_positions']}개"
    )
    return send(msg)


def notify_error(error: str):
    msg = f"🚨 <b>봇 오류 발생</b>\n\n<code>{error[:300]}</code>"
    return send(msg, silent=False)


def notify_start(mode: str, coins: list[str], capital: float):
    msg = (
        f"🤖 <b>퀀트 봇 시작</b>\n\n"
        f"모드:   <b>{mode}</b>\n"
        f"코인:   {', '.join(coins)}\n"
        f"자본:   ${capital:,.2f}\n"
        f"시각:   {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    return send(msg)


if __name__ == "__main__":
    ok = send("✅ 텔레그램 연결 테스트 성공!")
    print("전송 성공" if ok else "전송 실패 — .env 설정 확인")
