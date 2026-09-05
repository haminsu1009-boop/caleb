"""
bot/oversold/test_parity.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
실거래 신호 == 백테스트 신호 인가

자동매매에서 가장 조용하게 손해를 내는 실패는 주문 오류가 아니라
"검증한 것과 다른 규칙이 돌아가는 것"이다. 백테스트는 pandas 롤링
평균으로, 실거래는 리스트 슬라이싱으로 이동평균을 구한다. 둘이
한 봉이라도 어긋나면 승률 80%짜리 규칙이 아닌 것을 돌리게 된다.

이 테스트는 저장된 과거 데이터를 실거래 코드에 한 봉씩 흘려 넣어
백테스트가 뽑은 신호 집합과 정확히 같은지 대조한다.

    python bot/oversold/test_parity.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, glob
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from bot.oversold import strategy as S

FAILED = 0


def check(name: str, ok: bool, detail: str = ""):
    global FAILED
    print(f"  {'✅' if ok else '❌'} {name}" + (f"  — {detail}" if detail else ""))
    if not ok:
        FAILED += 1


def main():
    print("=" * 84)
    print("  실거래 신호 ↔ 백테스트 신호 일치 검증")
    print("=" * 84)

    # ── 1. 이동평균 계산이 pandas와 같은가
    rng = np.random.default_rng(0)
    x = list(rng.normal(100, 5, 200))
    pd_ma = pd.Series(x).rolling(S.MA_PERIOD).mean().iloc[-1]
    check("20기간 이동평균이 pandas rolling과 일치",
          abs(S.sma(x, S.MA_PERIOD) - pd_ma) < 1e-9,
          f"차이 {abs(S.sma(x, S.MA_PERIOD) - pd_ma):.2e}")

    # ── 2. 표본 부족 시 신호 없음
    check("20봉 미만이면 신호를 내지 않음",
          S.evaluate("X", [100.0] * 19, 0) is None)

    # ── 3. 임계값 경계
    # 주의: 마지막 봉도 이동평균에 들어가므로 종가를 그냥 -12.26% 내려도
    # vs_ma20은 그만큼 안 내려간다(희석). 경계를 역산해서 만든다.
    #   MA = (19*100 + X)/20,  X/MA - 1 = t/100   →   X = 1900t' / (20 - t')
    #   단 t' = 1 + t/100
    t = 1 + S.ENTRY_THRESH / 100
    boundary = 1900 * t / (20 - t)          # 이 종가에서 vs_ma20 == 임계값
    base = [100.0] * 19
    s_deep = S.evaluate("X", base + [boundary * 0.99], 0)
    s_shallow = S.evaluate("X", base + [boundary * 1.01], 0)
    check("경계보다 깊은 하락은 신호 발생",
          s_deep is not None,
          f"vs_ma20={s_deep.vs_ma20:.2f}%" if s_deep else "신호 없음")
    check("경계보다 얕은 하락은 신호 없음", s_shallow is None)

    # ── 4. 실제 데이터로 백테스트와 대조
    files = sorted(glob.glob("data/*_4h_all.csv.gz"))
    files = [f for f in files if os.path.basename(f).split("_")[0] in S.MAJORS]
    if not files:
        check("과거 데이터 존재", False, "data/*_4h_all.csv.gz 없음")
    total_bt = total_live = total_match = 0
    for f in files[:12]:
        sym = os.path.basename(f).split("_")[0]
        d = pd.read_csv(f, compression="gzip")
        tc = "timestamp" if "timestamp" in d.columns else "datetime"
        d[tc] = pd.to_datetime(d[tc], format="mixed", errors="coerce")
        d = d.dropna(subset=[tc]).sort_values(tc).reset_index(drop=True)
        d = d.tail(3000).reset_index(drop=True)
        closes = d["close"].astype(float).tolist()

        # 백테스트 방식 — 벡터 연산
        ma = pd.Series(closes).rolling(S.MA_PERIOD).mean()
        vs = (pd.Series(closes) / ma - 1) * 100
        bt = set(np.where(vs <= S.ENTRY_THRESH)[0])

        # 실거래 방식 — 봉을 하나씩 흘려 넣는다
        live = set()
        for i in range(len(closes)):
            sig = S.evaluate(sym, closes[: i + 1], i)
            if sig is not None:
                live.add(i)

        total_bt += len(bt); total_live += len(live); total_match += len(bt & live)
        if bt != live:
            check(f"{sym} 신호 일치", False,
                  f"백테스트 {len(bt)} / 실거래 {len(live)} / 공통 {len(bt & live)}")

    check(f"전 종목 신호 완전 일치 (백테스트 {total_bt:,}개)",
          total_bt == total_live == total_match,
          f"실거래 {total_live:,} · 공통 {total_match:,}")

    # ── 5. 손절가·청산 조건
    expect = 100.0 * (1 + S.STOP_PCT / 100)
    check(f"손절가가 진입가의 {S.STOP_PCT}%",
          abs(S.stop_price(100.0) - expect) < 1e-9, f"{S.stop_price(100.0):.2f}")
    check("10봉 미만은 보유 유지", not S.should_exit(9))
    check("10봉 도달 시 청산", S.should_exit(10))

    print("=" * 84)
    print(f"  {'✅ 전부 통과' if FAILED == 0 else f'❌ {FAILED}건 실패'}")
    print("=" * 84)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
