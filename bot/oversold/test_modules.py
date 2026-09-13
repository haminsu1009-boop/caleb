"""
bot/oversold/test_modules.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
숏·다이버전스 모듈이 백테스트와 같은 신호를 내는가

봇 코드와 백테스트 코드가 갈라지면 검증한 것과 다른 것을 굴리게
된다. 이 저장소에서 이미 두 번 크게 당했다(청산 종가 판정,
부분체결 무시). 그래서 같은 데이터에 두 구현을 돌려 신호 인덱스가
**한 건도** 어긋나지 않는지 본다.

실행: python bot/oversold/test_modules.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from bot.oversold import modules as M
from bot.oversold import strategy as S
import ml.short_setups as SS
import ml.divergence_scoped as DS

FAILED = 0


def check(desc, ok, detail=""):
    global FAILED
    if not ok:
        FAILED += 1
    print(f"  {'✅' if ok else '❌'} {desc}" + (f"  — {detail}" if detail else ""))


def main():
    print("=" * 84)
    print("  숏·다이버전스 모듈 ↔ 백테스트 신호 일치 검증")
    print("=" * 84)

    syms = [s for s in S.SYMBOLS if os.path.exists(f"data/{s}_1d_all.csv.gz")]
    D = {s: SS.load_daily(s) for s in syms}
    D = {k: v for k, v in D.items() if v is not None and len(v) >= 400}
    check("일봉 데이터 적재", len(D) >= 40, f"{len(D)}종")

    # ── 1. RSI
    rng = np.random.default_rng(0)
    x = list(np.cumprod(1 + rng.normal(0, .03, 300)) * 100)
    a, b = M.rsi(x), SS.rsi(np.array(x))
    worst = np.nanmax(np.abs(a - b))
    check("RSI가 백테스트와 일치", worst < 1e-12, f"최대 오차 {worst:.2e}")

    # ── 2. 주봉 묶기
    bad = 0
    for s, d in D.items():
        w1, w2 = M.to_weekly(d), SS.to_weekly(d)
        if len(w1) != len(w2) or not np.allclose(w1["close"], w2["close"]):
            bad += 1
    check("일봉 → 주봉 묶기가 백테스트와 일치", bad == 0, f"어긋난 종목 {bad}/{len(D)}")

    # ── 3. 숏 신호 인덱스
    bad, total = 0, 0
    for s, d in D.items():
        w = SS.to_weekly(d)
        m1 = M.short_signals(w)
        m2 = SS.setup_A(w, M.SHORT_MA_WEEKS, M.SHORT_STREAK)
        total += len(m2)
        if not np.array_equal(m1, m2):
            bad += 1
    check("주봉 숏 신호가 백테스트와 일치", bad == 0,
          f"어긋난 종목 {bad}/{len(D)} · 신호 {total}건")

    # ── 4. 다이버전스 신호 인덱스
    bad, total = 0, 0
    for s, d in D.items():
        m1 = M.div_signals(d)
        m2 = DS.divergence(d, bullish=True, gap=M.DIV_GAP)
        total += len(m2)
        if not np.array_equal(m1, m2):
            bad += 1
    check("상승 다이버전스 신호가 백테스트와 일치", bad == 0,
          f"어긋난 종목 {bad}/{len(D)} · 신호 {total}건")

    # ── 5. evaluate_*: 마지막 봉이 신호일 때만 발화하는가
    #    과거 신호 시점까지 자른 데이터를 넣으면 반드시 발화해야 한다.
    hit = miss = 0
    for s, d in list(D.items())[:12]:
        w = SS.to_weekly(d)
        for i in SS.setup_A(w, M.SHORT_MA_WEEKS, M.SHORT_STREAK)[:3]:
            # 그 주봉이 마지막이 되도록 일봉을 자른다
            cut = d[d["dt"] <= w["dt"].iloc[i]]
            if len(cut) < 400:
                continue
            sig = M.evaluate_short(s, cut)
            hit += sig is not None
            miss += sig is None
    check("숏: 과거 신호 시점을 다시 넣으면 발화", miss == 0,
          f"발화 {hit} · 놓침 {miss}")

    hit = miss = 0
    for s, d in list(D.items())[:12]:
        for i in M.div_signals(d)[:3]:
            cut = d.iloc[:i + 1]
            if len(cut) < 200:
                continue
            sig = M.evaluate_div(s, cut)
            hit += sig is not None
            miss += sig is None
    check("다이버: 과거 신호 시점을 다시 넣으면 발화", miss == 0,
          f"발화 {hit} · 놓침 {miss}")

    # ── 6. 신호가 아닌 봉에서는 발화하지 않는가 (거짓 양성)
    rng2 = np.random.default_rng(5)
    fp = 0; tried = 0
    for s, d in list(D.items())[:12]:
        sigset = set(M.div_signals(d))
        for i in rng2.choice(np.arange(300, len(d)), size=25, replace=False):
            if int(i) in sigset:
                continue
            tried += 1
            fp += M.evaluate_div(s, d.iloc[:int(i) + 1]) is not None
    check("다이버: 신호 아닌 봉에서는 침묵", fp == 0, f"거짓 발화 {fp}/{tried}")

    # ── 7. 미래참조 — 데이터를 뒤에서 더 줘도 과거 판정이 안 바뀐다
    changed = 0
    for s, d in list(D.items())[:8]:
        for cut in [len(d) - 200, len(d) - 100]:
            a = set(M.div_signals(d.iloc[:cut]))
            b = set(i for i in M.div_signals(d) if i < cut - M.DIV_PIVOT_K)
            if not b <= a:
                changed += 1
    check("다이버: 뒤 데이터가 과거 신호를 바꾸지 않는다", changed == 0,
          f"어긋난 구간 {changed}")

    # ── 7b. 발화 타이밍 — 백테스트 거래 89건 전부를 '정확히 하루'에만
    #        잡는가. 하루라도 이르면 미완성 봉으로 거래하는 것이고,
    #        여러 날 걸쳐 뜨면 봇이 틀린 가격에 들어간다.
    import ml.unified_pool as UP
    W = {s: SS.to_weekly(x) for s, x in D.items()}
    for nm, trades, is_short in [("숏", UP.make_short(W), True),
                                 ("다이버", UP.make_div(D), False)]:
        ok = miss = multi = 0
        for t in trades:
            sym, x = t["sym"], D[t["sym"]]
            if is_short:
                w = W[sym]
                L = w["dt"].iloc[list(w["dt"]).index(t["dt"]) - 1]
                ev = lambda c: M.evaluate_short(sym, c)
            else:
                L = t["dt"] - pd.Timedelta(days=1)
                ev = lambda c: M.evaluate_div(sym, c)
            fires = [day for day in pd.date_range(L - pd.Timedelta(days=4),
                                                  L + pd.Timedelta(days=6))
                     if ev(x[x.dt <= day].tail(600).reset_index(drop=True))]
            if fires == [L]:
                ok += 1
            elif not fires:
                miss += 1
            else:
                multi += 1
        check(f"{nm}: 백테스트 거래를 정확히 신호일 하루에만 잡는다",
              miss == 0 and multi == 0,
              f"{ok}/{len(trades)} · 미발화 {miss} · 여러날 {multi}")

    # 미완성 주봉으로 발화하지 않는가 — 실제로 있었던 버그다
    sym = "CHZUSDT"
    if sym in D:
        x = D[sym]
        early = [day for day in pd.date_range("2025-02-05", "2025-02-09")
                 if M.evaluate_short(sym, x[x.dt <= day])]
        check("진행 중인 주봉으로는 발화하지 않는다", len(early) == 0,
              f"주가 닫히기 전 발화 {len(early)}일")

    # ── 8. 손절 방향
    check("숏 손절은 진입가 위", M.stop_price(100, "Sell") == 150.0,
          f"{M.stop_price(100, 'Sell'):.1f}")
    check("롱 손절은 진입가 아래", M.stop_price(100, "Buy") == 50.0,
          f"{M.stop_price(100, 'Buy'):.1f}")
    # 8.9년 최악 거래(-45.6%)도 자르지 않아야 한다 — 순수 보험이다
    check("숏 손절이 과거 최악 거래(-45.6%)를 안 자른다",
          M.CATASTROPHE_STOP > 45.6, f"손절 {M.CATASTROPHE_STOP}%")

    # ── 9. 데이터가 모자라면 조용히 None
    short_d = D[list(D)[0]].iloc[:50]
    check("데이터 부족 시 숏 None", M.evaluate_short("X", short_d) is None)
    check("데이터 부족 시 다이버 None", M.evaluate_div("X", short_d) is None)

    print("=" * 84)
    print(f"  {'✅ 전부 통과' if FAILED == 0 else f'❌ {FAILED}건 실패'}")
    print("=" * 84)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
