"""
ml/div_leverage_stop.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
상승 다이버전스 2배 + 손절 — 남겨둔 후보 "다이버 2배+손절" 검증 (2026-10-03)

지금 다이버는 1배·손절 없음·10일 보유다. 다이버 거래당 평균이 +4~9%로
롱보다 크고 신호는 1년에 몇 건뿐이라, 같은 증거금(40%)에 배율만 2배로
올리면 돈이 더 벌릴 수 있다. 대신 2배는 -49.5%에서 청산이므로 손절을
같이 걸어 꼬리를 자르는 안을 본다.

변형: 배율 {1, 2} × 손절 {없음, -8, -12, -16, -20%} (가격 기준, 일봉 저가가
닿으면 그 값에 청산 · 시가가 이미 아래면 시가에 청산 · 자리도 그날 비운다).
나머지(롱 4배 1.5%, 숏 1배 40%, 총노출 0.6, 차단기 20%/30일, bear 4가지,
bull 숏 끔)는 ml/module_winrate.py 그대로. 수수료 왕복 0.40%, 2배는 펀딩 포함.

규칙: 손절값은 2019~2023(학습) 지갑 결과만 보고 고른다. 2024~ 는 검증용.
최종 채택은 2019~ 결과·최대낙폭·1년 손실확률·2024~ 결과가 모두 지금보다
나을 때만. 10개 변형 중 1개를 고르는 것이라 그만큼 부풀려졌다고 본다.

━━ 결과 (2026-10-03 실행, 폭락장 기준 4가지 범위) ━━
    변형            2019~         최대낙폭  1년손실   2024~
    1배 손절없음    44.1~65.7배   26~31%    0~10%    8.0~11.8배  ◀지금
    1배 손절-16%    49.6~79.6배   22~31%    0~2%     7.7~11.2배
    2배 손절없음    45.8~93.5배   22~39%    3~20%    9.9~14.5배
    2배 손절-16%    52.0~76.0배   25~31%    3~11%    6.5~9.5배   ← 학습구간 1등

  학습(2019~23)으로 고른 2배 손절-16%는 2024~ 에서 지금보다 낮고 1년
  손실확률도 높다 → 기각. 2배 손절없음은 2024~ 는 좋지만 낙폭 39%·1년손실
  20%까지 늘어 기각. 손절을 걸면 다이버 승률이 65%→57%로 떨어진다 —
  다이버는 10일 안에 한 번 깊게 빠졌다가 회복하는 거래가 많다는 뜻.
  1배 손절-16%도 2024~ 가 조금 낮아 채택 안 함(10개 중 고른 값이기도 함).
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations
import os, sys, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from bot.oversold import strategy as S
import ml.unified_pool as UP
import ml.short_setups as SS
from ml.backtest_current_bot import load
from ml.per_coin_rules import sim
from ml.per_coin_walkforward import MENU
from ml.per_coin_portfolio import to_up
from ml.module_winrate import taken, PT, T0, TE
from ml import unified_pool as _up
DS = _up.DS

STOPS = (None, 8, 12, 16, 20)
LEVS = (1.0, 2.0)


def make_div_stop(D, stop=None, gap=8.0, hold=10):
    """UP.make_div 와 같은 신호, 손절이 닿으면 그날 청산."""
    out = []
    for s, d in D.items():
        o, c, l, dt = (d["open"].values, d["close"].values,
                       d["low"].values, d["dt"].values)
        n = len(c); lock = -10**9
        for i in DS.divergence(d, bullish=True, gap=gap):
            if i <= lock or i + 1 + hold >= n:
                continue
            e = o[i + 1]; j = i + hold; xp = c[i + hold]
            if stop is not None:
                sp = e * (1 - stop / 100)
                for k in range(i + 1, i + hold + 1):
                    if l[k] <= sp:
                        j = k; xp = min(o[k], sp) if k > i + 1 else sp
                        break
            out.append({"kind": "div", "sym": s, "dt": pd.Timestamp(dt[i + 1]),
                        "exit": pd.Timestamp(dt[j]), "entry": e, "exit_px": xp,
                        "mae": (l[i + 1:j + 1].min() / e - 1) * 100 if stop is None
                        else max((l[i + 1:j + 1].min() / e - 1) * 100, -stop),
                        "deployed": 1.0, "bars_h": (j - i) * 24, "long": True})
            lock = i + hold
    return out


def main():
    syms = [s for s in S.SYMBOLS if os.path.exists(f"data/{s}_1d_all.csv.gz")]
    Dd = {s: SS.load_daily(s) for s in syms}
    Dd = {k: v for k, v in Dd.items() if v is not None and len(v) >= 400}
    W = {s: SS.to_weekly(d) for s, d in Dd.items()}

    ma, th, hd, fr, ou, st = MENU["A 지금 봇"]
    LONG = []
    for sym in S.SYMBOLS:
        g = load(sym)
        if g is None or len(g) < 400:
            continue
        o, h, l, c = (g[k].astype(float).values for k in ("open", "high", "low", "close"))
        LONG += [to_up(t) for t in sim(o, h, l, c, g["datetime"].values,
                                       ma, th, hd, fr, ou, S.STOP_PCT, sym=sym, step=st)]
    SHORT = UP.make_short(W, streak=4, hold=4)
    DIVS = {sp: make_div_stop(Dd, sp) for sp in STOPS}
    cut = lambda L: [t for t in L if t["dt"] >= T0]
    LONG, SHORT = cut(LONG), cut(SHORT)
    DIVS = {k: cut(v) for k, v in DIVS.items()}

    b = pd.read_csv("data/BTCUSDT_1d_all.csv.gz")
    col = "datetime" if "datetime" in b.columns else b.columns[0]
    b[col] = pd.to_datetime(b[col], format="mixed")
    b = b.rename(columns={col: "dt"}).sort_values("dt").set_index("dt")

    def flag(N, thr, up=False):
        r = b["close"].pct_change(N) * 100; idx = r.index; v = r.values
        def f(ts):
            i = idx.searchsorted(pd.Timestamp(ts), side="right") - 1
            if i < 0 or np.isnan(v[i]):
                return False
            return v[i] >= thr if up else v[i] <= thr
        return f
    BEARS = [flag(30, -15), flag(60, -15), flag(90, -20), flag(120, -25)]
    BULL = flag(90, 30, up=True)

    def run(sp, lev, bear, start=None, end=None):
        tr = [t for t in LONG if not bear(t["dt"])]
        tr += [t for t in SHORT if not BULL(t["dt"])]
        tr += DIVS[sp]
        if start is not None:
            tr = [t for t in tr if t["dt"] >= start]
        if end is not None:
            tr = [t for t in tr if t["exit"] < end]
        LVx = {"long": 4.0, "short": 1.0, "div": lev}
        fin, mdd, got, curve = taken(tr, PT, LVx)
        w = UP.windows(curve) if len(curve) > 400 else np.array([np.nan])
        g = [x for x in got if x[0] == "div"]
        return dict(fin=fin, mdd=mdd * 100, loss1y=np.nanmean(w < 1) * 100,
                    n=len(g), wr=np.mean([x[1] > 0 for x in g]) * 100 if g else np.nan,
                    av=np.mean([x[1] for x in g]) if g else np.nan)

    def rng(xs, fmt):
        lo, hi = min(xs), max(xs)
        return (fmt % lo) if abs(hi - lo) < 1e-9 else (fmt % lo) + "~" + (fmt % hi)

    print(f"{'변형':<16s}{'학습19~23':>14s}{'2019~':>16s}{'최대낙폭':>12s}{'1년손실':>10s}"
          f"{'2024~':>14s}{'다이버거래':>10s}{'승률':>10s}{'거래당':>16s}")
    rows = {}
    for lev in LEVS:
        for sp in STOPS:
            TR = [run(sp, lev, B, end=TE) for B in BEARS]
            R = [run(sp, lev, B) for B in BEARS]
            H = [run(sp, lev, B, start=TE) for B in BEARS]
            rows[(lev, sp)] = (TR, R, H)
            name = f"{lev:g}배 손절{'없음' if sp is None else '-%d%%' % sp}"
            mark = " ◀지금" if (lev, sp) == (1.0, None) else ""
            print(f"{name:<16s}{rng([r['fin'] for r in TR], '%.1f') + '배':>14s}"
                  f"{rng([r['fin'] for r in R], '%.1f') + '배':>16s}"
                  f"{rng([r['mdd'] for r in R], '%.0f') + '%':>12s}"
                  f"{rng([r['loss1y'] for r in R], '%.0f') + '%':>10s}"
                  f"{rng([r['fin'] for r in H], '%.1f') + '배':>14s}"
                  f"{rng([r['n'] for r in R], '%d'):>10s}"
                  f"{rng([r['wr'] for r in R], '%.0f') + '%':>10s}"
                  f"{rng([r['av'] for r in R], '%+.2f') + '%':>16s}{mark}", flush=True)

    # 학습 구간(2019~2023)만 보고 2배 손절값 고르기 — 4가지 기준 평균 지갑 결과
    best = max([(2.0, sp) for sp in STOPS], key=lambda k: np.mean([r["fin"] for r in rows[k][0]]))
    print(f"\n학습 구간으로 고른 2배 변형: 손절 {best[1]}")
    base = rows[(1.0, None)]; cand = rows[best]
    checks = {
        "2019~ 결과": all(c["fin"] > b_["fin"] for c, b_ in zip(cand[1], base[1])),
        "최대낙폭": all(c["mdd"] <= b_["mdd"] for c, b_ in zip(cand[1], base[1])),
        "1년 손실확률": all(c["loss1y"] <= b_["loss1y"] for c, b_ in zip(cand[1], base[1])),
        "2024~ 결과": all(c["fin"] > b_["fin"] for c, b_ in zip(cand[2], base[2])),
    }
    for k, v in checks.items():
        print(f"  {k}: {'나음' if v else '나빠짐/같음'}")
    print("판정:", "채택 후보(사용자 확인 필요)" if all(checks.values()) else "기각")


if __name__ == "__main__":
    main()
