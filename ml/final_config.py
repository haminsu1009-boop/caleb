"""
ml/final_config.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
검증된 개선을 전부 합치고 숏까지 얹어 최종 설정을 고른다

이 세션에서 살아남은 것만 넣는다.
  · 진입    이평 -12.26% (다이버전스·RSI·볼린저하단 등은 전부 탈락)
  · 분할    1차 비중을 낮추고 뒤를 크게 (비중 훑기가 단조로웠다)
  · 청산    볼린저 상단 도달 (시간청산보다 낫고 낙폭을 줄인다)
  · 숏      주봉 MA60 이탈 + 연속 음봉 (일봉·다른 셋업은 전부 탈락)

⚠️ 투입 비율을 정확히 센다
2차·3차가 안 걸리면 그만큼만 투입된 것이다. 이걸 전량 투입으로
세던 버그가 결과를 46배 부풀렸었다(커밋 6173729). 여기서는
deployed = 체결된 회차의 비중 합 으로 기록하고 손익에 곱한다.
노출 한도(reserved)는 여전히 전체 물량 기준이다 — 뒤 회차가
들어올 자리를 비워둬야 하기 때문이다.
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
from ml.backtest_current_bot import load, ROUND_TRIP, bb_upper
from ml.breaker_designs import run, windows, TRAIN_END
import ml.short_setups as SS

KW = dict(leverage=2.0, per_trade=0.05, max_gross=0.8)


def build(fracs, step=-5.0, hold=S.HOLD_BARS, bb=False, bb_k=2.0):
    """4시간봉 · 이평 -12.26% 진입 · 다단 분할 · (선택) 볼린저 상단 청산."""
    nt = len(fracs)
    out = []
    for sym in S.SYMBOLS:
        g = load(sym)
        if g is None:
            continue
        o = g["open"].astype(float).values
        h = g["high"].astype(float).values
        l = g["low"].astype(float).values
        c = g["close"].astype(float).values
        dt = g["datetime"].values
        n = len(c)
        ma = pd.Series(c).rolling(S.MA_PERIOD).mean().values
        vs = (c / ma - 1) * 100
        up = bb_upper(c, 20, bb_k) if bb else None
        lock = -10**9
        for i in np.where(vs <= S.ENTRY_THRESH)[0]:
            if i <= lock or i + 1 + hold >= n:
                continue
            e1 = o[i + 1]
            px = [e1]; w = [fracs[0]]; filled = 1
            stop = S.stop_price(e1)
            ex_bar = ex_px = None; reason = "time"
            for bar in range(i + 1, i + 1 + hold):
                avg = float(np.average(px, weights=w))
                if l[bar] <= stop:
                    ex_bar, ex_px, reason = bar, stop, "stop"; break
                if up is not None and not np.isnan(up[bar]) and h[bar] >= up[bar]:
                    ex_bar, ex_px, reason = bar, up[bar], "bb"; break
                while filled < nt and c[bar] <= e1 * (1 + step * filled / 100) and bar + 1 < n:
                    px.append(o[bar + 1]); w.append(fracs[filled]); filled += 1
                    avg = float(np.average(px, weights=w)); stop = S.stop_price(avg)
            if ex_bar is None:
                ex_bar = i + 1 + hold; ex_px = o[ex_bar]
            avg = float(np.average(px, weights=w))
            seg = slice(i + 1, ex_bar + 1)
            out.append({"sym": sym, "dt": dt[i], "entry_bar": i + 1, "e1": e1,
                        "entry_avg": avg, "tranche": filled,
                        "deployed": float(sum(w)),      # ← 실제 투입 비율
                        "exit_dt": dt[ex_bar], "exit_bar": ex_bar,
                        "exit_px": ex_px, "reason": reason,
                        "path_dt": dt[seg], "path_o": o[seg], "path_l": l[seg],
                        "mae": (l[i + 1:ex_bar + 1].min() / avg - 1) * 100})
            lock = i + (ex_bar - i)
    return sorted(out, key=lambda x: x["dt"])


def row(lab, t):
    tr = [x for x in t if pd.Timestamp(x["dt"]) < TRAIN_END]
    ho = [x for x in t if pd.Timestamp(x["dt"]) >= TRAIN_END]
    a, b, c = run(t, **KW), run(tr, **KW), run(ho, **KW)
    d = windows(t, **KW)
    px = np.mean([(x["exit_px"] / x["entry_avg"] - 1) * 100 - ROUND_TRIP for x in t])
    dep = np.mean([x["deployed"] for x in t])
    cagr = (a["final"] ** (1 / 8.8) - 1) * 100 if a["final"] > 0 else -100
    print(f"  {lab:<26s}{px:>7.2f}%{a['final']:>8.2f}배{cagr:>6.0f}%{b['final']:>8.2f}배"
          f"{c['final']:>8.2f}배{d['mult'].median():>8.2f}배"
          f"{(d['mult']<1).mean()*100:>5.0f}%{a['mdd_low']*100:>7.1f}%{dep:>7.2f}")
    return dict(lab=lab, full=a["final"], tr=b["final"], ho=c["final"],
                med=d["mult"].median(), loss=(d["mult"] < 1).mean() * 100,
                mdd=a["mdd_low"] * 100, px=px)


def header():
    print(f"\n  {'설정':<26s}{'거래당':>8s}{'전체':>9s}{'연복리':>6s}{'학습':>8s}"
          f"{'홀드':>8s}{'1년중앙':>8s}{'손실':>5s}{'장중낙폭':>7s}{'투입':>7s}")
    print("  " + "-" * 92)


def main():
    ap = argparse.ArgumentParser(); ap.parse_args()
    print("=" * 100)
    print("  최종 설정 탐색 — 투입 비율 정확히 반영 (배율 2배 · 진입당 5% · 총노출 80%)")
    print("=" * 100)

    print("\n  ── ① 청산 방식 (분할은 현재 30/70 고정)")
    header()
    row("시간청산 20봉 (현재)", build([.30, .70]))
    for k, hb in [(2.0, 20), (2.0, 60), (1.5, 60), (1.5, 100)]:
        row(f"볼린저 {k}σ · {hb}봉 한도", build([.30, .70], hold=hb, bb=True, bb_k=k))

    print("\n  ── ② 분할 비중 (청산은 볼린저 1.5σ · 60봉 고정)")
    header()
    for fr in [[.30, .70], [.20, .80], [.10, .90],
               [.20, .30, .50], [.15, .30, .55], [.10, .30, .60],
               [.10, .20, .30, .40], [.05, .15, .30, .50]]:
        lab = "/".join(f"{x*100:.0f}" for x in fr)
        row(f"{lab}  ({len(fr)}분할)", build(fr, hold=60, bb=True, bb_k=1.5))

    print("\n  ── ③ 추가 간격 (분할 10/30/60 · 볼린저 1.5σ · 60봉)")
    header()
    for st in (-3.0, -5.0, -8.0, -12.0):
        row(f"추가 간격 {st:.0f}%", build([.10, .30, .60], step=st, hold=60, bb=True, bb_k=1.5))


if __name__ == "__main__":
    main()
