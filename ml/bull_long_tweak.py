"""
ml/bull_long_tweak.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
상승장에서만 과매도 롱을 바꾸면 더 버는가 — 남겨둔 후보 "상승장 수익" (2026-10-04)

상승장 = BTC 직전 60일 수익률 ≥ +20% (어제 마감 일봉 기준, 미래 정보 없음).
상승장엔 깊은 하락(-12.26%)이 드물어 롱이 잘 안 들어간다. 신고가 돌파
모듈은 이미 실패했으니, 지금 롱 규칙은 그대로 두고 상승장일 때만
  (1) 진입선을 얕게: -12.26% → -10 / -9 / -8%
  (2) 한 건 비중을 크게: 1.5% → 2.5 / 3.5%
를 바꿔 본다(4×3 = 12개, 지금 포함). 볼린저 익절·60봉·-40% 손절·분할 30/70 은 그대로.
나머지(숏·다이버·총노출 0.6·차단기 20%/30일·bear 4가지)는 ml/module_winrate.py 그대로.
수수료 왕복 0.40% + 펀딩.

규칙: 2019~2023(학습)에서 가장 좋은 1개를 고르고, 2019~ 결과·최대낙폭·
1년 손실확률·2024~ 결과가 폭락장 기준 4가지 모두에서 지금보다 나을 때만 채택.

━━ 결과 (2026-10-04 실행, 폭락장 기준 4가지 범위) ━━
    상승장 롱 변형        2019~           최대낙폭  1년손실  2024~
    -12.26% · 1.5% 지금   44.1~65.7배     26~31%   0~10%   8.0~11.8배
    -12.26% · 3.5%        120.7~178.7배   26~31%   0~8%    9.0~12.8배
    -8%     · 3.5%        199.8~269.8배   26~33%   3~9%    7.2~10.7배  ← 학습 1등
  학습 1등(-8%·3.5%)은 2024~ 가 지금보다 낮고 1년손실도 늘어 기각.
  진입선을 얕게 하면 거래당 수익이 +10.4% → +6% 로 떨어진다.
  반면 진입선은 그대로 두고 상승장에서 비중만 키우면 4가지가 모두
  같거나 낫다(낙폭은 4가지 기준 모두 소수점까지 같음). 대조군: 비중을
  항상 3.5%로 키우면 낙폭 31~51%·1년손실 7~17% 로 나빠진다 → 효과는
  "비중"이 아니라 "상승장에서만" 에서 나온다. 상승장 롱 거래당 +10.4%,
  그 밖 +4.5~6.2%. 다만 12개 중 결과를 본 뒤 고른 것이라 보류.
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
from ml.module_winrate import taken, T0, TE

THS = (-12.26, -10.0, -9.0, -8.0)
SIZES = (0.015, 0.025, 0.035)
BULL_N, BULL_TH = 60, 20.0


def main():
    syms = [s for s in S.SYMBOLS if os.path.exists(f"data/{s}_1d_all.csv.gz")]
    Dd = {s: SS.load_daily(s) for s in syms}
    Dd = {k: v for k, v in Dd.items() if v is not None and len(v) >= 400}
    W = {s: SS.to_weekly(d) for s, d in Dd.items()}

    ma, _, hd, fr, ou, st = MENU["A 지금 봇"]
    LONG = {th: [] for th in THS}
    for sym in S.SYMBOLS:
        g = load(sym)
        if g is None or len(g) < 400:
            continue
        o, h, l, c = (g[k].astype(float).values for k in ("open", "high", "low", "close"))
        for th in THS:
            LONG[th] += [to_up(t) for t in sim(o, h, l, c, g["datetime"].values,
                                               ma, th, hd, fr, ou, S.STOP_PCT, sym=sym, step=st)]
    cut = lambda L: [t for t in L if t["dt"] >= T0]
    LONG = {k: cut(v) for k, v in LONG.items()}
    SHORT = cut(UP.make_short(W, streak=4, hold=4))
    DIV = cut(UP.make_div(Dd, gap=8, hold=10))

    b = pd.read_csv("data/BTCUSDT_1d_all.csv.gz")
    col = "datetime" if "datetime" in b.columns else b.columns[0]
    b[col] = pd.to_datetime(b[col], format="mixed")
    b = b.rename(columns={col: "dt"}).sort_values("dt").set_index("dt")

    def flag(N, thr, up=False, lag=0):
        r = b["close"].pct_change(N) * 100; idx = r.index; v = r.values
        def f(ts):
            i = idx.searchsorted(pd.Timestamp(ts), side="right") - 1 - lag
            if i < 0 or np.isnan(v[i]):
                return False
            return v[i] >= thr if up else v[i] <= thr
        return f
    BEARS = [flag(30, -15), flag(60, -15), flag(90, -20), flag(120, -25)]
    BULL = flag(90, 30, up=True)
    UPM = flag(BULL_N, BULL_TH, up=True, lag=1)       # 이번에 보는 상승장 (어제 마감 기준)

    def run(th, size, bear, start=None, end=None):
        tr = [t for t in LONG[-12.26] if not bear(t["dt"]) and not UPM(t["dt"])]
        tr += [dict(t, kind="longb") for t in LONG[th] if not bear(t["dt"]) and UPM(t["dt"])]
        tr += [t for t in SHORT if not BULL(t["dt"])]
        tr += DIV
        if start is not None:
            tr = [t for t in tr if t["dt"] >= start]
        if end is not None:
            tr = [t for t in tr if t["exit"] < end]
        pt = {"long": .015, "longb": size, "short": .40, "div": .40}
        lv = {"long": 4.0, "longb": 4.0, "short": 1.0, "div": 1.0}
        fin, mdd, got, curve = taken(tr, pt, lv)
        w = UP.windows(curve) if len(curve) > 400 else np.array([np.nan])
        gb = [x for x in got if x[0] == "longb"]
        return dict(fin=fin, mdd=mdd * 100, loss1y=np.nanmean(w < 1) * 100, nb=len(gb),
                    avb=np.mean([x[1] for x in gb]) if gb else np.nan)

    def rng(xs, fmt):
        xs = [x for x in xs if not (isinstance(x, float) and np.isnan(x))] or [np.nan]
        lo, hi = min(xs), max(xs)
        return (fmt % lo) if abs(hi - lo) < 1e-9 else (fmt % lo) + "~" + (fmt % hi)

    print(f"{'상승장 롱 변형':<18s}{'학습19~23':>14s}{'2019~':>16s}{'최대낙폭':>10s}{'1년손실':>9s}"
          f"{'2024~':>14s}{'상승장롱':>9s}{'거래당':>16s}")
    rows = {}
    for th in THS:
        for size in SIZES:
            TR = [run(th, size, B, end=TE) for B in BEARS]
            R = [run(th, size, B) for B in BEARS]
            H = [run(th, size, B, start=TE) for B in BEARS]
            rows[(th, size)] = (TR, R, H)
            mark = " ◀지금" if (th, size) == (-12.26, .015) else ""
            print(f"{'진입 %.2f%% · %.1f%%' % (th, size * 100):<18s}"
                  f"{rng([r['fin'] for r in TR], '%.1f') + '배':>14s}"
                  f"{rng([r['fin'] for r in R], '%.1f') + '배':>16s}"
                  f"{rng([r['mdd'] for r in R], '%.0f') + '%':>10s}"
                  f"{rng([r['loss1y'] for r in R], '%.0f') + '%':>9s}"
                  f"{rng([r['fin'] for r in H], '%.1f') + '배':>14s}"
                  f"{rng([r['nb'] for r in R], '%d'):>9s}"
                  f"{rng([r['avb'] for r in R], '%+.2f') + '%':>16s}{mark}", flush=True)

    best = max(rows, key=lambda k: np.mean([r["fin"] for r in rows[k][0]]))
    print(f"\n학습 구간 1등: 진입 {best[0]}% · 비중 {best[1]*100:.1f}%")
    base = rows[(-12.26, .015)]; cand = rows[best]
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
