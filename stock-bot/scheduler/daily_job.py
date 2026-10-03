"""
Daily Job Scheduler
===================
매일 자동 실행 파이프라인

스케줄 (한국시간 기준):
  06:30 KST  — 모닝 브리핑 (뉴스 분석 + 텔레그램 알림)
  08:00 KST  — 프리마켓 신호 스캔
  22:30 KST  — 미국 장 시작: 신호 재확인 → 자동매매 실행
  23:00 KST  — 장중 모니터링 시작
  04:00 KST  — 미국 장 마감: 포트폴리오 현황 알림
"""

import logging
import time
from datetime import datetime, timezone

import schedule
import pytz

from news.fetcher     import fetch_market_snapshot
from news.analyzer    import analyze_market, generate_morning_brief
from alerts.telegram_bot import get_bot
from data.fetcher     import fetch_all_stocks
from trading.strategy import generate_signals
from trading.alpaca_trader import AlpacaTrader
from config           import US_WATCHLIST, KR_WATCHLIST

logger = logging.getLogger(__name__)
KST = pytz.timezone("Asia/Seoul")


# ─────────────────────────────────────────────
# 싱글톤
# ─────────────────────────────────────────────

_alpaca: AlpacaTrader = None

def _get_alpaca() -> AlpacaTrader:
    global _alpaca
    if _alpaca is None:
        _alpaca = AlpacaTrader()
    return _alpaca


# ─────────────────────────────────────────────
# 작업 1: 모닝 브리핑 (06:30 KST)
# ─────────────────────────────────────────────

def job_morning_brief() -> None:
    """뉴스·원자재 분석 → 인사이트 추출 → 텔레그램 알림"""
    logger.info("=== 모닝 브리핑 시작 ===")
    bot = get_bot()

    try:
        snapshot = fetch_market_snapshot()
        insights = analyze_market(snapshot)

        if insights:
            bot.send_bulk_insights(insights)

        brief = generate_morning_brief(snapshot, insights)
        bot.send_morning_brief(brief, insights)

        logger.info(f"모닝 브리핑 완료: 인사이트 {len(insights)}건")
    except Exception as e:
        logger.error(f"모닝 브리핑 실패: {e}")
        bot.send_error("morning_brief", str(e))


# ─────────────────────────────────────────────
# 작업 2: 매매 신호 스캔 (08:00 + 22:30 KST)
# ─────────────────────────────────────────────

def job_scan_signals(auto_trade: bool = False) -> None:
    """
    전체 감시 종목 지표 분석 → 신호 생성 → 텔레그램 알림.
    auto_trade=True이면 Alpaca로 자동 주문 실행.
    """
    logger.info(f"=== 신호 스캔 {'+ 자동매매' if auto_trade else ''} ===")
    bot = get_bot()

    try:
        # 뉴스 인사이트 (캐시 1시간이면 재사용 가능하나 단순화)
        snapshot = fetch_market_snapshot()
        insights = analyze_market(snapshot)

        # 주가 데이터 수집
        stock_data = fetch_all_stocks(US_WATCHLIST, KR_WATCHLIST)

        # 신호 생성
        signals = generate_signals(stock_data, insights, min_confidence=0.60)

        if not signals:
            logger.info("신호 없음")
            return

        # 텔레그램 알림
        bot.send_trade_signal([
            {"ticker": s.ticker, "side": s.side, "confidence": s.confidence, "reason": s.reason}
            for s in signals
        ])

        # 자동매매 실행
        if auto_trade:
            alpaca = _get_alpaca()
            if alpaca.ready:
                results = alpaca.execute_signals(signals, pct_per_trade=0.05, dry_run=False)
                for r in results:
                    if r.get("success"):
                        price = 0.0
                        bot.send_trade_executed(
                            ticker=r["ticker"], side=r["side"],
                            qty=r.get("qty", 0), price=price,
                            reason=r.get("signal_reason", ""),
                        )
            else:
                logger.warning("Alpaca 미연결 → 자동매매 스킵")

    except Exception as e:
        logger.error(f"신호 스캔 실패: {e}")
        bot.send_error("scan_signals", str(e))


# ─────────────────────────────────────────────
# 작업 3: 장중 모니터링 (30분 간격)
# ─────────────────────────────────────────────

def job_intraday_monitor() -> None:
    """장중 빠른 스캔: 과열 신호만 체크"""
    logger.info("=== 장중 모니터링 ===")
    try:
        # US 주식만 빠르게 스캔
        stock_data = fetch_all_stocks(US_WATCHLIST, [])
        signals = generate_signals(stock_data, [], min_confidence=0.75)  # 높은 신뢰도만
        if signals:
            bot = get_bot()
            bot.send_trade_signal([
                {"ticker": s.ticker, "side": s.side, "confidence": s.confidence, "reason": s.reason}
                for s in signals
            ])
    except Exception as e:
        logger.error(f"장중 모니터링 실패: {e}")


# ─────────────────────────────────────────────
# 작업 4: 마감 리포트 (04:00 KST)
# ─────────────────────────────────────────────

def job_close_report() -> None:
    """미국 장 마감 후 포트폴리오 현황 전송"""
    logger.info("=== 마감 리포트 ===")
    bot    = get_bot()
    alpaca = _get_alpaca()
    if not alpaca.ready:
        bot.send("📊 마감 리포트: Alpaca 미연결")
        return
    account   = alpaca.get_account()
    positions = alpaca.get_positions()
    bot.send_portfolio_summary(account, positions)


# ─────────────────────────────────────────────
# 스케줄러 실행
# ─────────────────────────────────────────────

def run_scheduler(auto_trade: bool = False) -> None:
    """
    스케줄러 메인 루프.
    auto_trade=True: 미국 장 시작 시 자동 주문 실행
    """
    logger.info(f"📅 스케줄러 시작 (자동매매={'ON' if auto_trade else 'OFF'})")

    # 모닝 브리핑: 매일 06:30 KST
    schedule.every().day.at("06:30").do(job_morning_brief)

    # 프리마켓 신호 스캔: 08:00 KST
    schedule.every().day.at("08:00").do(job_scan_signals, auto_trade=False)

    # 미국 장 시작: 22:30 KST (신호 재확인 + 자동매매)
    schedule.every().day.at("22:30").do(job_scan_signals, auto_trade=auto_trade)

    # 장중 모니터링: 22:30 ~ 05:00 KST, 30분 간격
    schedule.every(30).minutes.do(job_intraday_monitor)

    # 마감 리포트: 04:00 KST
    schedule.every().day.at("04:00").do(job_close_report)

    # 즉시 한 번 실행
    logger.info("→ 즉시 모닝 브리핑 실행")
    job_morning_brief()

    logger.info("→ 스케줄러 루프 시작")
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--auto-trade", action="store_true", help="자동매매 활성화")
    args = p.parse_args()
    run_scheduler(auto_trade=args.auto_trade)
