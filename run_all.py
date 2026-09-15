"""
run_all.py
퀀트 트레이딩 봇 - 전체 파이프라인 실행

실행 순서:
  1. collect_data.py  → data/btc_daily.csv
  2. backtest.py      → backtest_results.csv
  3. analyze.py       → 콘솔 분석 출력
  4. visualize.py     → charts/결과.png
  5. daily_verify.py  → results/검증이력.csv

봇 실행 (별도):
  python bot.py       → signals.log (매 1시간 자동 실행)

사용법:
  python run_all.py              # 전체 파이프라인
  python run_all.py --skip-bt    # 백테스트 스킵 (기존 결과 사용)
  python run_all.py --bot        # 파이프라인 후 봇 실행
"""

import os
import sys
import time
import argparse
import subprocess
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))


def run_step(name: str, script: str, args: list[str] | None = None) -> bool:
    """단계 실행 및 결과 반환"""
    print(f"\n{'='*60}")
    print(f"  [{datetime.now().strftime('%H:%M:%S')}] {name}")
    print(f"{'='*60}")

    cmd = [sys.executable, os.path.join(ROOT, script)] + (args or [])
    start = time.time()

    result = subprocess.run(cmd, capture_output=False, text=True)
    elapsed = time.time() - start

    if result.returncode == 0:
        print(f"\n  [완료] {name}  ({elapsed:.1f}초)")
        return True
    else:
        print(f"\n  [실패] {name}  (종료코드: {result.returncode})")
        return False


def check_dependencies() -> bool:
    """필수 패키지 확인"""
    required = ["pandas", "numpy", "requests", "matplotlib"]
    missing = []
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"[경고] 누락된 패키지: {', '.join(missing)}")
        print(f"  설치: pip install -r {os.path.join(ROOT, 'requirements.txt')}")
        return False
    return True


def print_summary():
    """결과 파일 요약"""
    print(f"\n{'='*60}")
    print("  실행 결과 요약")
    print(f"{'='*60}")

    files = {
        "BTC 일봉 데이터":   os.path.join(ROOT, "data", "btc_daily.csv"),
        "백테스트 결과":     os.path.join(ROOT, "backtest_results.csv"),
        "분석 차트":         os.path.join(ROOT, "charts", "결과.png"),
        "검증 이력":         os.path.join(ROOT, "results", "검증이력.csv"),
        "신호 로그":         os.path.join(ROOT, "signals.log"),
    }

    for label, path in files.items():
        if os.path.exists(path):
            size = os.path.getsize(path)
            size_str = f"{size/1024:.1f} KB" if size < 1024*1024 else f"{size/1024/1024:.1f} MB"
            mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
            print(f"  ✓ {label:<16} {size_str:<10} {path.replace(ROOT+'/', '')}")
        else:
            print(f"  ✗ {label:<16} (없음)")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="퀀트 트레이딩 봇 전체 파이프라인",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--skip-bt",  action="store_true", help="백테스트 스킵 (기존 결과 사용)")
    parser.add_argument("--skip-data", action="store_true", help="데이터 수집 스킵")
    parser.add_argument("--bot",      action="store_true", help="파이프라인 후 봇 실행")
    parser.add_argument("--only-bot", action="store_true", help="봇만 실행")
    args = parser.parse_args()

    print(f"\n{'#'*60}")
    print(f"  퀀트 트레이딩 봇 - 파이프라인 시작")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*60}")

    if args.only_bot:
        print("\n[봇 실행 모드]")
        os.execv(sys.executable, [sys.executable, os.path.join(ROOT, "bot.py")])
        return

    # 패키지 확인
    if not check_dependencies():
        ans = input("\n계속 진행하시겠습니까? (y/N): ").strip().lower()
        if ans != "y":
            sys.exit(1)

    success_all = True

    # 1. 데이터 수집
    if not args.skip_data:
        ok = run_step("1/5  BTC 일봉 데이터 수집 (Binance)", "collect_data.py")
        if not ok:
            print("[중단] 데이터 수집 실패. 기존 데이터가 있으면 계속 진행합니다.")
            data_path = os.path.join(ROOT, "data", "btc_daily.csv")
            if not os.path.exists(data_path):
                print("[오류] 데이터 없음 - 종료")
                sys.exit(1)
    else:
        print("\n[스킵] 데이터 수집")

    # 2. 백테스트
    if not args.skip_bt:
        ok = run_step("2/5  지표 조합 백테스팅", "backtest.py")
        success_all = success_all and ok
    else:
        print("\n[스킵] 백테스트 (기존 backtest_results.csv 사용)")

    # 3. 분석
    ok = run_step("3/5  결과 분석 (승률 70%+ / 발생 20+)", "analyze.py")
    success_all = success_all and ok

    # 4. 시각화
    ok = run_step("4/5  결과 시각화 → charts/결과.png", "visualize.py")
    success_all = success_all and ok

    # 5. 일일 검증
    ok = run_step("5/5  일일 검증 이력 기록", "daily_verify.py")
    success_all = success_all and ok

    # 결과 요약
    print_summary()

    if success_all:
        print("[전체 완료] 모든 단계 성공\n")
    else:
        print("[경고] 일부 단계 실패 - 로그를 확인하세요\n")

    # 봇 실행
    if args.bot:
        print("봇 시작 중... (Ctrl+C로 종료)")
        time.sleep(1)
        os.execv(sys.executable, [sys.executable, os.path.join(ROOT, "bot.py")])


if __name__ == "__main__":
    main()
