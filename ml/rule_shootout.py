"""
ml/rule_shootout.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
규칙 후보를 자본 단위로 맞붙인다 — 청산 0건 제약 아래 수익 최대

ml/global_retune.py는 "거래당 순수익"으로 규칙을 골랐다. 그 기준은
자본 성장과 다르다. 재튜닝 규칙은 거래당 +12.07%로 지금 봇(+8.68%)을
이기지만 거래 수가 6분의 1이다. 거래가 드물면 그만큼 크게 실을 수
있으므로, 어느 쪽이 실제로 돈을 더 버는지는 배분까지 넣고 돌려야
나온다.

제약은 요청받은 그대로다.
    · 강제청산 0건 (보유 중 최저가 기준 — 스치기만 해도 청산이다)
    · 그 안에서 최종 배수 최대

배율을 올리면 거래소 청산선이 전략 손절선 위로 올라온다.

    배율   청산선     전략 손절 -40%
     2배  -49.5%    손절이 먼저 걸린다
     3배  -32.8%    청산이 먼저 걸린다
     5배  -19.5%    청산이 먼저 걸린다

그래서 배율을 올리려면 손절을 같이 조여야 하고, 손절을 조이면
평균회귀 전략은 반등 전에 털린다. 그 맞교환도 같이 잰다.

사용법:
    python ml/rule_shootout.py
    python ml/rule_shootout.py --stops        # 손절·배율 맞교환만
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
from ml.backtest_current_bot import load, simulate
from ml.per_coin_rules import sim, GLOBAL, TRAIN_END

# ml/global_retune.py가 **학습구간만 보고** 고른 상위 규칙들이다.
# 홀드아웃 성적은 고르는 데 쓰지 않았다. 여기서 자본 단위로 다시 맞붙인다.
CANDIDATES = [
    ("지금 봇",              GLOBAL),
    ("재튜닝 #1",  (10, -18.0, 90, [0.2, 0.3, 0.5], [(1.0, 2.0)])),
    ("재튜닝 #2",  (10, -18.0, 60, [0.2, 0.3, 0.5], [(1.0, 2.0)])),
    ("재튜닝 #5",  (10, -18.0, 90, [0.3, 0.7],      [(1.0, 2.0)])),
    ("재튜닝 #7",  (20, -18.0, 90, [0.2, 0.3, 0.5], [(1.0, 2.0)])),
    # 분할매도가 자본 단위에서도 살아남는지 — 거래당 기준으로는
    # 한 번에 파는 쪽이 이겼지만 승률은 분할이 높았다.
    ("재튜닝+분할매도", (10, -18.0, 90, [0.2, 0.3, 0.5],
                        [(0.5, 1.0), (0.5, 2.0)])),
]

PER_TRADE = [0.015, 0.03, 0.05, 0.08, 0.12, 0.20, 0.30]
GROSS = [0.6, 1.0]


def load_all():
    d = {}
    for sym in S.SYMBOLS:
        g = load(sym)
        if g is None or len(g) < 400:
            continue
        d[sym] = tuple(g[k].astype(float).values
                       for k in ("open", "high", "low", "close")) + (g["datetime"].values,)
    return d


def trades_for(data, cfg, stop_pct=None):
    stop = S.STOP_PCT if stop_pct is None else stop_pct
    out = []
    for sym, (o, h, l, c, dt) in data.items():
        out += sim(o, h, l, c, dt, *cfg, stop, sym=sym)
    out.sort(key=lambda t: t["dt"])
    return out


def rolling_year(trades, **kw):
    """1년 구간을 30일씩 밀며 돌린다 — 언제 시작했느냐 운을 걷어낸다."""
    if not trades:
        return np.array([])
    t0, t1 = trades[0]["dt"], trades[-1]["dt"]
    if (t1 - t0).days < 400:
        return np.array([])
    outs = []
    for s in pd.date_range(t0, t1 - pd.Timedelta(days=365), freq="30D"):
        w = [t for t in trades if s <= t["dt"] < s + pd.Timedelta(days=365)]
        if len(w) < 5:
            continue
        r = simulate(w, **kw)
        outs.append(0.0 if r["bust"] else r["final"])
    return np.array(outs)


def run_one(trades, lev, pt, gross, cb=0.20):
    kw = dict(leverage=lev, per_trade=pt, max_gross=gross, cb=cb,
              cool_days=30, min_equity=0.0, compound=True)
    full = simulate(trades, **kw)
    ho = simulate([t for t in trades if t["dt"] >= TRAIN_END], **kw)
    yr = rolling_year(trades, **kw)
    yrs = (trades[-1]["dt"] - trades[0]["dt"]).days / 365.25
    cagr = (full["final"] ** (1 / yrs) - 1) * 100 if full["final"] > 0 else -100
    return dict(final=full["final"], cagr=cagr, wr=full["wr"],
                mdd=full["mdd_low"] * 100, liq=full["liq"], n=full["n"],
                ho=ho["final"], ho_wr=ho["wr"], ho_liq=ho["liq"],
                loss1y=float((yr < 1).mean() * 100) if len(yr) else float("nan"),
                worst1y=float(yr.min()) if len(yr) else float("nan"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stops", action="store_true", help="손절·배율 맞교환만")
    a = ap.parse_args()

    data = load_all()
    print("=" * 112)

    if not a.stops:
        print("  규칙 × 배분 맞붙이기 — 강제청산 0건 제약 아래 최종 배수 최대")
        print(f"  종목 {len(data)}종 · 배율 2배 고정 · 차단기 20% · 2017~2026")
        print("=" * 112)
        print(f"\n  {'규칙':<16s}{'진입당':>7s}{'노출':>6s}{'거래':>7s}{'승률':>7s}"
              f"{'최종':>9s}{'연복리':>7s}{'낙폭':>7s}{'청산':>6s}"
              f"{'홀드':>8s}{'홀드승률':>9s}{'1년손실':>8s}{'최악1년':>8s}")
        print("  " + "-" * 110)
        best = {}
        for lab, cfg in CANDIDATES:
            tr = trades_for(data, cfg)
            for gross in GROSS:
                for pt in PER_TRADE:
                    r = run_one(tr, 2.0, pt, gross)
                    if r["liq"] > 0:
                        continue
                    if lab not in best or r["final"] > best[lab][0]["final"]:
                        best[lab] = (r, pt, gross)
        for lab, _ in CANDIDATES:
            if lab not in best:
                print(f"  {lab:<16s}  청산 0건을 만족하는 배분이 없다")
                continue
            r, pt, gross = best[lab]
            print(f"  {lab:<16s}{pt*100:>6.1f}%{gross*100:>5.0f}%{r['n']:>7,}"
                  f"{r['wr']:>6.1f}%{r['final']:>8.2f}배{r['cagr']:>6.0f}%"
                  f"{r['mdd']:>6.1f}%{r['liq']:>6}{r['ho']:>7.2f}배"
                  f"{r['ho_wr']:>8.1f}%{r['loss1y']:>7.0f}%{r['worst1y']:>7.2f}배")

    # ── 손절 × 배율 ──────────────────────────────────────────────────
    print("\n" + "=" * 112)
    print("  손절 × 배율 — 배율을 올리려면 손절을 조여야 한다. 그 대가는?")
    print("  (규칙은 지금 봇 고정 · 진입당 1.5% · 총노출 60%)")
    print("=" * 112)
    print(f"\n  {'손절':>7s}{'배율':>6s}{'청산선':>8s}{'거래':>7s}{'승률':>7s}"
          f"{'최종':>9s}{'연복리':>7s}{'낙폭':>7s}{'청산':>6s}{'1년손실':>8s}")
    print("  " + "-" * 76)
    for stop in [-40.0, -30.0, -22.0, -16.0, -12.0]:
        tr = trades_for(data, GLOBAL, stop_pct=stop)
        for lev in [2.0, 3.0, 4.0, 5.0]:
            liq_line = -100.0 / lev + 0.5
            if stop <= liq_line:
                continue   # 손절이 청산선보다 깊다 = 청산이 먼저 걸린다
            r = run_one(tr, lev, 0.015, 0.6)
            print(f"  {stop:>6.0f}%{lev:>5.0f}배{liq_line:>7.1f}%{r['n']:>7,}"
                  f"{r['wr']:>6.1f}%{r['final']:>8.2f}배{r['cagr']:>6.0f}%"
                  f"{r['mdd']:>6.1f}%{r['liq']:>6}{r['loss1y']:>7.0f}%")
    print("=" * 112)


if __name__ == "__main__":
    main()
