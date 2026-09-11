"""
ml/dca_projection.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
적립식으로 1년 굴리면 얼마가 되나

"100만원으로 시작해서 매달 30만원씩 넣으면 1년 뒤 얼마?"

일시불과 계산이 다르다.
  · 매달 현금이 들어오므로 복리 경로가 달라진다. 늦게 넣은 돈은
    그만큼 덜 굴러간다. 원금 460만원을 1년 내내 굴린 것과 같지 않다.
  · 자본이 작을 때는 거래 가능 종목이 줄어든다. 1차 진입액이
    자본의 3%(= per_trade 5% × 배율 2배 × 1차 30%)뿐이라,
    거래소 최소주문량에 못 미치는 종목은 신호가 떠도 건너뛴다.
    100만원이면 1차가 3만원이다. 이걸 반영하지 않으면 실제보다
    좋게 나온다.

그래서 자본 수준에 따라 거래 가능 종목을 제한하며 시뮬레이션한다.
정확한 최소주문량은 거래소에 붙어야 알 수 있으므로(이 세션에서는
바이빗이 막혀 있다), 일반적인 값으로 근사한다 — 실제 숫자는 봇이
시작할 때 찍어주는 "거래 가능 종목 XX/42종"으로 확인해야 한다.

1년 창 189개 전부에 돌려 분포를 낸다. 한 번의 결과가 아니라
"어떤 해에 시작했느냐"에 따른 범위를 봐야 한다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from bot.oversold import strategy as S
from ml.backtest_current_bot import (build_all, Pos, pnl_pct,
                                     ROUND_TRIP, FUNDING_PER_8H, BAR_HOURS)

# 바이빗 USDT 무기한의 최소 주문 명목금액 근사 (USD).
# BTC는 최소 0.001개라 가격에 비례해 커진다. 나머지는 대체로 5달러
# 안팎이다. 정확한 값은 거래소에 붙어야 알 수 있다.
MIN_NOTIONAL = {"BTCUSDT": 100.0, "ETHUSDT": 40.0}
MIN_DEFAULT = 5.0


def simulate_dca(trades, *, start_krw, monthly_krw, fx,
                 leverage=2.0, per_trade=0.05, max_gross=0.8,
                 cb=0.25, cool_days=30, apply_min_order=True):
    """적립식 시뮬레이션. 현금이 매달 들어온다.

    반환 단위는 원이다. 내부 계산은 달러로 하고 마지막에 환산한다.
    """
    liq_line = -100.0 / leverage + 0.5
    cash = start_krw / fx
    deposited = start_krw
    peak = cash
    positions: dict[str, Pos] = {}
    halted_until = None
    n_trades = wins = liqs = halts = skipped = 0
    mdd = 0.0
    t0 = pd.Timestamp(trades[0]["dt"])
    next_deposit = t0 + pd.DateOffset(months=1)
    n_deposits = 0

    for t in trades:
        now = pd.Timestamp(t["dt"])
        # 만기된 포지션 정산
        for s in [s for s, p in positions.items() if p.exit_dt <= now.to_datetime64()]:
            cash += positions.pop(s).realized
        # 월 적립
        while now >= next_deposit and n_deposits < 12:
            cash += monthly_krw / fx
            deposited += monthly_krw
            n_deposits += 1
            next_deposit += pd.DateOffset(months=1)

        eq = cash + sum(p.unreal(t["dt"]) for p in positions.values())
        if eq <= 1e-9:
            return {"final_krw": 0.0, "deposited": deposited, "bust": True,
                    "n": n_trades, "wr": 0.0, "mdd": 1.0, "skipped": skipped,
                    "liq": liqs, "halts": halts}
        peak = max(peak, eq)
        mdd = max(mdd, 1 - eq / peak)

        if halted_until is not None and now < halted_until:
            continue
        halted_until = None
        if 1 - eq / peak >= cb:
            halted_until = now + pd.Timedelta(days=cool_days)
            halts += 1
            peak = eq
            continue
        if t["sym"] in positions:
            continue

        margin = per_trade * eq
        full_notional = margin * leverage
        # 1차만 즉시 나간다. 이게 최소주문량을 못 넘으면 진입 자체가 안 된다.
        if apply_min_order:
            first = full_notional * S.SCALE_IN_FIRST_FRAC
            if first < MIN_NOTIONAL.get(t["sym"], MIN_DEFAULT):
                skipped += 1
                continue
        gross = sum(p.reserved for p in positions.values())
        if gross + full_notional > max_gross * leverage * eq:
            continue

        px_ret, was_liq = pnl_pct(t["entry_avg"], t["exit_px"], leverage,
                                  liq_line, t["mae"])
        held_h = (t["exit_bar"] - t["entry_bar"]) * BAR_HOURS
        fee = ROUND_TRIP + FUNDING_PER_8H * (held_h / 8.0)
        net = px_ret - fee
        realized = max(margin * leverage * net / 100, -margin)
        n_trades += 1
        wins += net > 0
        liqs += was_liq
        positions[t["sym"]] = Pos(t, margin, leverage, liq_line, fee, realized)

    for p in positions.values():
        cash += p.realized
    # 12회를 못 채웠으면 나머지도 넣은 것으로 친다 (원금 비교를 맞추려고)
    while n_deposits < 12:
        cash += monthly_krw / fx
        deposited += monthly_krw
        n_deposits += 1
    return {"final_krw": cash * fx, "deposited": deposited, "bust": False,
            "n": n_trades, "wr": wins / max(n_trades, 1) * 100, "mdd": mdd,
            "skipped": skipped, "liq": liqs, "halts": halts}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=float, default=1_000_000)
    ap.add_argument("--monthly", type=float, default=300_000)
    ap.add_argument("--fx", type=float, default=1400.0, help="원/달러")
    ap.add_argument("--no-min-order", action="store_true",
                    help="최소주문량 제약을 무시 (비교용)")
    a = ap.parse_args()

    trades, have, _ = build_all()
    t0, t1 = pd.Timestamp(trades[0]["dt"]), pd.Timestamp(trades[-1]["dt"])
    starts = pd.date_range(t0, t1 - pd.Timedelta(days=365), freq="15D")

    print("=" * 86)
    print(f"  적립식 1년 — 시작 {a.start:,.0f}원 + 매달 {a.monthly:,.0f}원 × 12회")
    print(f"  총 원금 {a.start + a.monthly*12:,.0f}원 · 환율 {a.fx:,.0f}원/$")
    print(f"  배율 2배 · 거래당 5% · 총노출 80% · 왕복 {ROUND_TRIP}% · 시장가")
    print("=" * 86)

    for tag, mino in [("최소주문량 반영 (현실)", True),
                      ("최소주문량 무시 (참고)", False)]:
        if a.no_min_order and mino:
            continue
        rows = []
        for s in starts:
            win = [t for t in trades
                   if s <= pd.Timestamp(t["dt"]) < s + pd.Timedelta(days=365)]
            if len(win) < 10:
                continue
            r = simulate_dca(win, start_krw=a.start, monthly_krw=a.monthly,
                             fx=a.fx, apply_min_order=mino)
            r["start"] = s
            rows.append(r)
        d = pd.DataFrame(rows)
        dep = a.start + a.monthly * 12
        d["ret"] = (d.final_krw / dep - 1) * 100

        print(f"\n  ── {tag}   (1년 창 {len(d)}개)")
        print(f"     거래 중앙 {d.n.median():.0f}건 · 최소주문량으로 놓친 신호 "
              f"중앙 {d.skipped.median():.0f}건 · 승률 중앙 {d.wr.median():.1f}%")
        print(f"\n     {'':>10s}{'최종 금액':>14s}{'원금 대비':>11s}")
        print("     " + "-" * 36)
        for lab, q in [("최악", 0.0), ("하위 5%", 0.05), ("하위 25%", 0.25),
                       ("중앙값", 0.5), ("상위 25%", 0.75), ("상위 5%", 0.95),
                       ("최고", 1.0)]:
            v = d.final_krw.quantile(q)
            print(f"     {lab:>10s}{v:>13,.0f}원{(v/dep-1)*100:>10.1f}%")
        print(f"\n     원금({dep:,.0f}원)보다 적을 확률  {(d.final_krw < dep).mean()*100:.1f}%")
        print(f"     2배 이상                    {(d.final_krw >= dep*2).mean()*100:.1f}%")
        print(f"     3배 이상                    {(d.final_krw >= dep*3).mean()*100:.1f}%")
        print(f"     계좌 소멸                    {d.bust.mean()*100:.1f}%")
        print(f"     최대낙폭 중앙값               {d.mdd.median()*100:.0f}%")

    print(f"""
  ── 읽는 법
     '원금 대비'는 넣은 돈 {a.start + a.monthly*12:,.0f}원 기준이다.
     매달 넣는 돈은 늦게 들어올수록 덜 굴러가므로, 같은 수익률이라도
     일시불보다 낮게 나온다. 12월에 넣은 30만원은 사실상 안 굴렀다.

     '최소주문량 반영'이 현실에 가깝다. 시작 자본 {a.start:,.0f}원이면
     1차 진입액이 {a.start*0.05*2*0.3:,.0f}원뿐이라 BTC·ETH 같은 종목은
     신호가 떠도 못 들어간다. 자본이 쌓일수록 풀린다.

     정확한 최소주문량은 거래소에 붙어야 알 수 있다. 봇이 시작할 때
     찍어주는 "거래 가능 종목 XX/42종"으로 확인해라.
""")


if __name__ == "__main__":
    main()
