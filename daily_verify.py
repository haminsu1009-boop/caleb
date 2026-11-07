"""
daily_verify.py
매일 백테스트 결과를 results/검증이력.csv에 날짜 붙여서 추가

실행 방법:
  python daily_verify.py             # 오늘 날짜로 즉시 실행
  python daily_verify.py --schedule  # 매일 00:05에 자동 실행

저장 포맷 (results/검증이력.csv):
  검증날짜, 총조합수, 70%조합수, 최고승률, 평균승률, 최고수익률,
  평균수익률, 베스트조합, 베스트승률, 베스트발생횟수
"""

import os
import sys
import time
import argparse
import pandas as pd
import numpy as np
from datetime import datetime, date

ROOT          = os.path.dirname(os.path.abspath(__file__))
BACKTEST_FILE = os.path.join(ROOT, "backtest_results.csv")
RESULTS_DIR   = os.path.join(ROOT, "results")
VERIFY_FILE   = os.path.join(RESULTS_DIR, "검증이력.csv")

MIN_WIN_RATE    = 0.70
MIN_OCCURRENCES = 20

VERIFY_COLUMNS = [
    "검증날짜",
    "전체조합수",
    "70%이상조합수",
    "70%이상_발생20+조합수",
    "전체_최고승률",
    "전체_평균승률",
    "전체_최고평균수익률",
    "70%_평균승률",
    "70%_평균발생횟수",
    "베스트조합",
    "베스트_승률",
    "베스트_발생횟수",
    "베스트_평균수익률",
    "베스트_복합점수",
    "단일신호_최고승률",
    "2개조합_최고승률",
    "3개조합_최고승률",
]


def load_backtest() -> pd.DataFrame:
    if not os.path.exists(BACKTEST_FILE):
        raise FileNotFoundError(
            f"백테스트 결과 없음: {BACKTEST_FILE}\n"
            "먼저 backtest.py를 실행하세요."
        )
    return pd.read_csv(BACKTEST_FILE)


def compute_daily_stats(df: pd.DataFrame, today: str) -> dict:
    """오늘의 백테스트 통계 계산"""
    total = len(df)
    win70 = df[df["승률"] >= MIN_WIN_RATE]
    win70_cnt = df[
        (df["승률"] >= MIN_WIN_RATE) & (df["발생횟수"] >= MIN_OCCURRENCES)
    ]

    # 복합점수로 베스트 조합 선택
    df_top = win70_cnt.copy()
    if not df_top.empty:
        df_top["복합점수"] = df_top["승률"] * np.log1p(df_top["발생횟수"])
        best = df_top.sort_values("복합점수", ascending=False).iloc[0]
        best_combo   = best["조합"]
        best_wr      = round(best["승률"], 4)
        best_cnt     = int(best["발생횟수"])
        best_ret     = round(best["평균수익률"], 4)
        best_score   = round(best["복합점수"], 4)
    else:
        best_combo = "없음"
        best_wr = best_cnt = best_ret = best_score = None

    # 지표 수별 최고 승률
    def max_wr_by_n(n: int) -> float | None:
        sub = df[df["지표수"] == n]["승률"]
        return round(float(sub.max()), 4) if not sub.empty else None

    stats = {
        "검증날짜":              today,
        "전체조합수":            total,
        "70%이상조합수":         len(win70),
        "70%이상_발생20+조합수": len(win70_cnt),
        "전체_최고승률":         round(float(df["승률"].max()), 4),
        "전체_평균승률":         round(float(df["승률"].mean()), 4),
        "전체_최고평균수익률":   round(float(df["평균수익률"].max()), 4),
        "70%_평균승률":          round(float(win70_cnt["승률"].mean()), 4) if not win70_cnt.empty else None,
        "70%_평균발생횟수":      round(float(win70_cnt["발생횟수"].mean()), 1) if not win70_cnt.empty else None,
        "베스트조합":            best_combo,
        "베스트_승률":           best_wr,
        "베스트_발생횟수":       best_cnt,
        "베스트_평균수익률":     best_ret,
        "베스트_복합점수":       best_score,
        "단일신호_최고승률":     max_wr_by_n(1),
        "2개조합_최고승률":      max_wr_by_n(2),
        "3개조합_최고승률":      max_wr_by_n(3),
    }
    return stats


def load_history() -> pd.DataFrame:
    if os.path.exists(VERIFY_FILE):
        return pd.read_csv(VERIFY_FILE)
    return pd.DataFrame(columns=VERIFY_COLUMNS)


def save_daily_result(stats: dict) -> None:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    history = load_history()
    today = stats["검증날짜"]

    # 같은 날짜가 이미 있으면 업데이트, 없으면 추가
    if today in history["검증날짜"].values:
        history = history[history["검증날짜"] != today]
        print(f"  [갱신] {today} 기존 기록 교체")
    else:
        print(f"  [추가] {today} 신규 기록 추가")

    new_row = pd.DataFrame([stats])
    history = pd.concat([history, new_row], ignore_index=True)
    history = history.sort_values("검증날짜").reset_index(drop=True)

    # 컬럼 순서 통일
    for col in VERIFY_COLUMNS:
        if col not in history.columns:
            history[col] = None
    history = history[VERIFY_COLUMNS]

    history.to_csv(VERIFY_FILE, index=False, encoding="utf-8-sig")
    print(f"  저장 완료 → {VERIFY_FILE}  (총 {len(history)}일 기록)")


def print_stats(stats: dict) -> None:
    print("\n" + "=" * 55)
    print(f"  검증 날짜:          {stats['검증날짜']}")
    print(f"  전체 조합 수:       {stats['전체조합수']:,}개")
    print(f"  승률 70%+:          {stats['70%이상조합수']:,}개")
    print(f"  승률 70%+ 발생 20+: {stats['70%이상_발생20+조합수']:,}개")
    print(f"  최고 승률:          {stats['전체_최고승률']*100:.2f}%")
    print(f"  전체 평균 승률:     {stats['전체_평균승률']*100:.2f}%")
    if stats["베스트조합"] and stats["베스트조합"] != "없음":
        print(f"\n  ★ 베스트 조합:      {stats['베스트조합']}")
        print(f"    승률:             {stats['베스트_승률']*100:.2f}%")
        print(f"    발생횟수:         {stats['베스트_발생횟수']}회")
        print(f"    평균수익률:       {stats['베스트_평균수익률']*100:.2f}%")
    print("=" * 55)


def show_trend() -> None:
    """최근 검증 이력 트렌드 출력"""
    if not os.path.exists(VERIFY_FILE):
        return
    history = pd.read_csv(VERIFY_FILE)
    if len(history) < 2:
        return

    print("\n▶ 최근 검증 이력 (최근 10일)")
    print("-" * 55)
    recent = history.tail(10)[["검증날짜", "70%이상_발생20+조합수", "베스트_승률", "베스트조합"]]
    recent.columns = ["날짜", "유효조합수", "베스트승률", "베스트조합"]
    if "베스트승률" in recent.columns:
        recent["베스트승률"] = (recent["베스트승률"] * 100).round(1).astype(str) + "%"
    print(recent.to_string(index=False))


def run_verify(target_date: str | None = None) -> None:
    today = target_date or date.today().strftime("%Y-%m-%d")
    print(f"\n[일일 검증] {today}")

    df = load_backtest()
    print(f"  백테스트 결과 로드: {len(df)}개 조합")

    stats = compute_daily_stats(df, today)
    print_stats(stats)
    save_daily_result(stats)
    show_trend()
    print("\n[검증 완료]")


def schedule_daily(run_time: str = "00:05") -> None:
    """매일 지정 시간에 실행"""
    try:
        import schedule
    except ImportError:
        print("[오류] schedule 패키지 필요: pip install schedule")
        sys.exit(1)

    print(f"[자동 검증] 매일 {run_time}에 실행 예약됨 (Ctrl+C로 종료)")

    def job():
        today = date.today().strftime("%Y-%m-%d")
        print(f"\n[스케줄 실행] {today}")
        try:
            run_verify(today)
        except Exception as e:
            print(f"[오류] {e}")

    schedule.every().day.at(run_time).do(job)

    # 시작 시 즉시 1회 실행
    run_verify()

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="일일 백테스트 검증")
    parser.add_argument("--schedule", action="store_true",
                        help="매일 00:05에 자동 실행")
    parser.add_argument("--time", default="00:05",
                        help="자동 실행 시간 (기본: 00:05)")
    parser.add_argument("--date", default=None,
                        help="검증 날짜 (기본: 오늘, 형식: YYYY-MM-DD)")
    args = parser.parse_args()

    if args.schedule:
        schedule_daily(args.time)
    else:
        run_verify(args.date)
