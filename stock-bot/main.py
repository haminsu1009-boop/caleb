"""
Stock Bot - Main Runner
=======================
스케줄러 기반 자동 분석 + 즉시 실행 지원
"""

import logging
import time
import argparse
from datetime import datetime

import schedule

from config import US_WATCHLIST, KR_WATCHLIST, SCHEDULE
from data.fetcher import fetch_all_stocks
from recommender import full_recommendation, rank_stocks, print_ranking
from ai.claude_advisor import generate_recommendation_report

# ─────────────────────────────────────────────
# 로깅 설정
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")


# ─────────────────────────────────────────────
# 핵심 분석 작업
# ─────────────────────────────────────────────

def run_analysis(
    horizon: str = "중기",
    top_n: int = 5,
    with_ai: bool = True,
    stream: bool = True,
    user_note: str = "",
    us_only: bool = False,
    kr_only: bool = False,
) -> None:
    """전체 파이프라인 실행: 데이터 수집 → 지표 분석 → 순위 → AI 해설"""

    logger.info(f"📊 분석 시작: {horizon} | 상위 {top_n}개 | AI={with_ai}")
    start = time.time()

    # 종목 리스트 결정
    if us_only:
        tickers_us, tickers_kr = US_WATCHLIST, []
    elif kr_only:
        tickers_us, tickers_kr = [], KR_WATCHLIST
    else:
        tickers_us, tickers_kr = US_WATCHLIST, KR_WATCHLIST

    # 데이터 수집
    logger.info("1/3 데이터 수집 중...")
    stock_data = fetch_all_stocks(tickers_us, tickers_kr)

    # 순위 산출
    logger.info("2/3 종목 채점 및 순위 산출 중...")
    ranked = rank_stocks(stock_data, horizon=horizon, top_n=top_n)
    print_ranking(ranked, horizon)

    # AI 해설
    if with_ai and ranked:
        logger.info("3/3 Claude AI 해설 생성 중...")
        report = generate_recommendation_report(
            top_stocks=ranked,
            horizon=horizon,
            user_note=user_note,
            stream=stream,
        )
        if not stream:
            print("\n" + "="*60)
            print("AI 투자 해설 리포트")
            print("="*60)
            print(report)

    elapsed = time.time() - start
    logger.info(f"✅ 분석 완료 ({elapsed:.1f}초)")


def run_full_report(with_ai: bool = True, top_n: int = 5) -> None:
    """단기/중기/장기 세 기간 전체 리포트"""
    logger.info("📋 전체 리포트 생성 시작 (단기/중기/장기)")
    stock_data = fetch_all_stocks(US_WATCHLIST, KR_WATCHLIST)

    recs = full_recommendation(stock_data, top_n=top_n)
    for horizon, ranked in recs.items():
        print_ranking(ranked, horizon)
        if with_ai and ranked:
            print(f"\n{'─'*60}")
            print(f"  [{horizon}] AI 해설")
            print(f"{'─'*60}")
            report = generate_recommendation_report(ranked, horizon=horizon, stream=True)
            if not True:   # stream=True이면 실시간 출력됨
                print(report)


# ─────────────────────────────────────────────
# 스케줄러 작업 등록
# ─────────────────────────────────────────────

def _scheduled_daily_report():
    """매일 오전 7시 자동 실행"""
    logger.info("⏰ 스케줄 작업: 일일 리포트")
    run_full_report(with_ai=True)


def _scheduled_intraday():
    """장중 주기적 업데이트"""
    logger.info("⏰ 스케줄 작업: 장중 업데이트")
    run_analysis(horizon="단기", top_n=5, with_ai=False)


def start_scheduler():
    """스케줄러 루프 시작"""
    daily_time    = SCHEDULE.get("daily_report",     "07:00")
    interval_min  = SCHEDULE.get("interval_minutes", 30)

    schedule.every().day.at(daily_time).do(_scheduled_daily_report)
    schedule.every(interval_min).minutes.do(_scheduled_intraday)

    logger.info(f"📅 스케줄러 시작: 일일={daily_time}, 장중={interval_min}분")
    while True:
        schedule.run_pending()
        time.sleep(30)


# ─────────────────────────────────────────────
# CLI 진입점
# ─────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="AI 주식 추천 봇")
    p.add_argument("--horizon",   default="중기",  choices=["단기","중기","장기"], help="투자 기간")
    p.add_argument("--top",       default=5,        type=int,  help="상위 N개 종목")
    p.add_argument("--no-ai",     action="store_true",          help="AI 해설 비활성화")
    p.add_argument("--no-stream", action="store_true",          help="스트리밍 비활성화")
    p.add_argument("--full",      action="store_true",          help="단기/중기/장기 전체 리포트")
    p.add_argument("--schedule",  action="store_true",          help="스케줄러 모드 시작")
    p.add_argument("--us-only",   action="store_true",          help="미국 주식만 분석")
    p.add_argument("--kr-only",   action="store_true",          help="한국 주식만 분석")
    p.add_argument("--note",      default="",                   help="AI에게 전달할 추가 요청사항")
    return p.parse_args()


def main():
    args = parse_args()

    if args.schedule:
        start_scheduler()
    elif args.full:
        run_full_report(with_ai=not args.no_ai, top_n=args.top)
    else:
        run_analysis(
            horizon=args.horizon,
            top_n=args.top,
            with_ai=not args.no_ai,
            stream=not args.no_stream,
            user_note=args.note,
            us_only=args.us_only,
            kr_only=args.kr_only,
        )


if __name__ == "__main__":
    main()
