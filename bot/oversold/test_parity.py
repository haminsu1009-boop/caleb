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

    # ── 4. 실제 데이터로 백테스트와 대조 (실거래 목록 42종 전부)
    files = sorted(glob.glob("data/*_4h_all.csv.gz"))
    files = [f for f in files if os.path.basename(f).split("_")[0] in S.SYMBOLS]
    if not files:
        check("과거 데이터 존재", False, "data/*_4h_all.csv.gz 없음")
    check(f"실거래 목록 {len(S.SYMBOLS)}종 중 데이터 존재",
          len(files) >= len(S.SYMBOLS) - 2,   # 신규 상장 등으로 파일이 아직 없는 종목 소수는 허용
          f"{len(files)}/{len(S.SYMBOLS)}종")
    total_bt = total_live = total_match = 0
    for f in files:
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
    check(f"손절가가 진입가(평단)의 {S.STOP_PCT}%",
          abs(S.stop_price(100.0) - expect) < 1e-9, f"{S.stop_price(100.0):.2f}")
    check(f"{S.HOLD_BARS - 1}봉 미만은 보유 유지", not S.should_exit(S.HOLD_BARS - 1))
    check(f"{S.HOLD_BARS}봉 도달 시 청산", S.should_exit(S.HOLD_BARS))

    # ── 6. 분할매수 헬퍼 — ml/scale_in.py의 chase_split과 같은 계산인가
    trig = S.scale_in_trigger_price(100.0)
    expect_trig = 100.0 * (1 + S.SCALE_IN_TRIGGER_PCT / 100)
    check(f"2차 트리거가 1차 진입가의 {S.SCALE_IN_TRIGGER_PCT}%",
          abs(trig - expect_trig) < 1e-9, f"{trig:.4f}")

    # 1차 30개를 100원에, 2차 70개를 90원에 샀다면 평단은 수량가중평균
    avg = S.blended_entry(100.0, 30.0, 90.0, 70.0)
    expect_avg = (100.0 * 30.0 + 90.0 * 70.0) / 100.0
    check("분할매수 평단이 수량가중평균과 일치",
          abs(avg - expect_avg) < 1e-9, f"{avg:.4f} (기대 {expect_avg:.4f})")

    # 2차가 아예 안 걸렸으면(qty2=0) 평단은 1차 그대로여야 한다
    avg_no_fill = S.blended_entry(100.0, 30.0, 90.0, 0.0)
    check("2차 미체결 시 평단은 1차 진입가 그대로",
          abs(avg_no_fill - 100.0) < 1e-9, f"{avg_no_fill:.4f}")

    # ── 볼린저 상단 목표 청산 ─────────────────────────────────────
    # 백테스트는 pandas .std()(ddof=1)를 쓴다. 봇이 모집단 표준편차를
    # 쓰면 상단이 낮게 잡혀 더 일찍 팔게 되고, 검증한 것과 다른 것을
    # 굴리게 된다.
    from ml.backtest_current_bot import bb_upper as bt_bb
    rng2 = np.random.default_rng(3)
    worst = 0.0
    for _ in range(200):
        c = list(np.cumprod(1 + rng2.normal(0, .03, 60)) * 100)
        worst = max(worst, abs(S.bb_upper(c) / bt_bb(c, S.BB_PERIOD, S.BB_K)[-1] - 1))
    check("볼린저 상단이 백테스트와 일치", worst < 1e-12, f"최대 오차 {worst:.2e}")

    check("봉이 모자라면 상단 없음", S.bb_upper([1.0] * (S.BB_PERIOD - 1)) is None)

    # 상단이 평단 아래면 목표를 걸면 안 된다 — 손실 확정 주문이 된다.
    cc = [100.0] * 19 + [50.0]
    up = S.bb_upper(cc)
    check("상단이 평단 아래면 목표 없음",
          S.take_profit_price(cc, up + 1) is None, f"상단 {up:.4f}")
    check("상단이 평단 위면 그 값이 목표",
          S.take_profit_price(cc, up - 1) == up, f"목표 {up:.4f}")

    # ── 봇 상수 ↔ 백테스트 인자 ─────────────────────────────────
    # 21.52배는 백테스트가 쓴 값으로 나온 숫자다. 봇이 다른 값을 쓰면
    # 검증한 것과 다른 것을 굴리는 셈이다. 실제로 HOLD_BARS가 봇 20 /
    # 백테스트 60으로 갈려 있었고, 그 차이가 9.13배 대 21.52배였다
    # (낙폭 33.6% 대 21.6%, 1년 손실확률 21% 대 1%).
    #
    # ml/ 쪽 호출부를 문자열로 읽어 대조한다. 백테스트를 돌리지 않고도
    # 어긋남을 잡으려면 이 방법이 가장 싸다.
    import re
    mism = []
    for path in ["ml/unified_pool.py", "ml/report.py", "ml/survivorship.py"]:
        if not os.path.exists(path):
            continue
        src = open(path, encoding="utf-8").read()
        for m in re.finditer(r"make_long\(([^)]*)\)", src):
            args = m.group(1)
            h = re.search(r"hold\s*=\s*(\d+)", args)
            if h and int(h.group(1)) != S.HOLD_BARS:
                mism.append(f"{path} hold={h.group(1)} ≠ 봇 {S.HOLD_BARS}")
            k = re.search(r"bb_k\s*=\s*([\d.]+)", args)
            if k and abs(float(k.group(1)) - S.BB_K) > 1e-9:
                mism.append(f"{path} bb_k={k.group(1)} ≠ 봇 {S.BB_K}")
            f = re.search(r"fracs\s*=\s*\[\s*([\d.]+)", args)
            if f and abs(float(f.group(1)) - S.SCALE_IN_FIRST_FRAC) > 1e-9:
                mism.append(f"{path} fracs[0]={f.group(1)} ≠ 봇 {S.SCALE_IN_FIRST_FRAC}")
    check("백테스트 호출부가 봇 상수와 일치", not mism,
          "; ".join(mism) if mism else "hold · bb_k · 1차비율 대조")

    # ── 백테스트 CLI 기본값 ↔ 봇 Config ─────────────────────────
    # 위 검사는 make_long() 호출 인자만 본다. 자본배분(진입당 비율,
    # 총노출 상한, 차단기)은 거기 안 들어가는데, 바로 그쪽이 갈려
    # 있었다 — 스크립트 5%/80%/25% 대 봇 1.5%/60%/20%. 인자 없이
    # ml/backtest_current_bot.py를 돌리면 0.71배(손실)가, 봇 설정으로
    # 돌리면 1.71배가 나왔다. 같은 전략을 두고 결론이 뒤집힌다.
    from bot.oversold.executor import Config
    import importlib
    bc = importlib.import_module("ml.backtest_current_bot")
    defaults = {a.dest: a.default for a in bc.build_parser()._actions}
    cfg = Config()
    pairs = [("per_trade", cfg.per_trade), ("max_gross", cfg.max_gross),
             ("cb", cfg.max_drawdown), ("leverage", cfg.leverage),
             ("cool_days", cfg.halt_cooldown_days)]
    drift = [f"--{d.replace('_','-')} {defaults[d]} ≠ 봇 {v}"
             for d, v in pairs if abs(defaults[d] - v) > 1e-9]
    # build_all()의 기본값도 본다. bb_exit=False, bb_k=2.0으로 박혀
    # 있었다 — 봇은 볼린저 1.5σ 목표청산을 실제로 거는데, "봇 그대로"를
    # 표방하는 백테스트가 그 청산을 통째로 빼고 돌리고 있었다.
    # 2.92배·승률 83.2%가 1.71배·승률 64.6%로 나왔다.
    import inspect
    d = {k: v.default for k, v in
         inspect.signature(bc.build_all).parameters.items()}
    bb_drift = []
    if d.get("bb_exit") is not True:
        bb_drift.append(f"bb_exit={d.get('bb_exit')} — 봇은 목표청산을 건다")
    # bb_k=None이면 함수 안에서 S.BB_K를 쓴다. 숫자가 박혀 있으면 갈라진다.
    if d.get("bb_k") is not None and abs(float(d["bb_k"]) - S.BB_K) > 1e-9:
        bb_drift.append(f"bb_k={d['bb_k']} ≠ 봇 {S.BB_K}")
    check("백테스트 청산 규칙이 봇과 일치", not bb_drift,
          "; ".join(bb_drift) if bb_drift else
          f"볼린저 {S.BB_PERIOD}봉·{S.BB_K}σ 목표청산 켜짐")

    # ── 재진입 잠금 ────────────────────────────────────────────
    # 봇은 executor.py의 `if sym in positions` 하나로만 재진입을 막는다.
    # 포지션이 닫히는 순간 그 종목은 다시 열린다. 백테스트가
    # lock = i + hold로 두면 목표청산으로 일찍 나간 거래도 보유기간을
    # 꽉 채울 때까지 막아, 봇이 잡을 신호를 버린다(1,592건 대 1,815건).
    #
    # 실제 거래 목록에서 "같은 종목이 보유기간 안에 다시 진입한" 사례가
    # 하나라도 있어야 한다. lock을 되돌리면 0건이 되어 여기서 잡힌다.
    tr_all, _, _ = bc.build_all()
    by_sym = {}
    for t in tr_all:
        by_sym.setdefault(t["sym"], []).append(t)
    early = 0
    for ts in by_sym.values():
        ts.sort(key=lambda t: t["entry_bar"])
        for p, q in zip(ts, ts[1:]):
            if q["entry_bar"] < p["entry_bar"] + S.HOLD_BARS:
                early += 1
    check("재진입 잠금이 '청산 시점'까지다 (봇과 동일)", early > 0,
          f"보유기간 안 재진입 {early}건 / 전체 {len(tr_all):,}건")

    check("백테스트 CLI 기본값이 봇 Config와 일치", not drift,
          "; ".join(drift) if drift else
          f"진입당 {cfg.per_trade*100:.1f}% · 총노출 {cfg.max_gross*100:.0f}% · "
          f"차단기 {cfg.max_drawdown*100:.0f}%")

    print("=" * 84)
    print(f"  {'✅ 전부 통과' if FAILED == 0 else f'❌ {FAILED}건 실패'}")
    print("=" * 84)
    return 1 if FAILED else 0




if __name__ == "__main__":
    sys.exit(main())
