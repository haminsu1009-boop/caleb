"""수집 결과 요약 — 러너 로그에서 어떤 종목이 얼마나 받아졌는지 한눈에 보기 위한 것"""
import glob, os
import pandas as pd

files = sorted(glob.glob("data/bybit/*.csv.gz"))
if not files:
    print("  data/bybit/ 비어 있음 — 수집 실패")
    raise SystemExit(1)

print(f"  {'파일':32s}{'건수':>9s}   시작 ~ 끝")
print("  " + "-" * 70)
for f in files:
    d = pd.read_csv(f, compression="gzip")
    print(f"  {os.path.basename(f):32s}{len(d):>9,}   "
          f"{str(d['datetime'].min())[:10]} ~ {str(d['datetime'].max())[:10]}")
print(f"\n  총 {len(files)}개 파일")
