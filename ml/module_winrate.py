"""
ml/module_winrate.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
모듈별(롱·숏·다이버) 변형 — 승률·거래 수·수익률, 실제 운용 설정으로

설정: 롱 4배, 숏·다이버 1배, 한 지갑(롱 1.5% · 숏 40% · 다이버 40%),
총노출 0.6, 차단기 20%/30일. 2019~2026.
  bear(폭락장) = BTC 직전 N일 수익률 ≤ 기준 → 롱 신규 끔 (4가지 기준 범위)
  bull(상승장) = BTC 직전 90일 ≥ +30% → 숏 신규 끔

변형 하나를 바꿀 때 나머지 두 모듈은 지금 봇 설정 그대로 둔다.
표의 거래 수·승률은 지갑에서 실제로 체결된 거래 기준(자리 없어서
못 들어간 신호는 뺀다). 거래당은 수수료·펀딩 뺀 가격 변동(배율 전).

⚠️ 2026-10-03 정정 — 아래 숫자에는 미래 정보가 섞여 있었다.
   폭락장 판단이 "그날 일봉 종가"를 썼다. 그 종가는 그날 밤에야 나오므로
   낮에 진입할 때는 알 수 없다. 전날 종가로 고치면 (롱 4배·폭락장 롱 끔):
       2019~ 44~66배 → 24~48배 · 최대낙폭 26~31% → 26~39%
       1년 손실확률 0~10% → 12~17% · 2024~ 8.0~11.8배 → 8.0~11.4배
   폭락장 끔 없이 4배는 22배 · 낙폭 48% · 1년손실 18% · 2024~ 11.1배.
   2배는 오히려 폭락장 롱 끔이 손해다(끔 없이 15배·낙폭 21% 대 8~14배·36~43%).
   flag()는 이제 전날 종가를 쓴다. 다른 스크립트도 이 방식을 따를 것.

━━ (정정 전) 결과 (2019~2026, 폭락장 기준 4가지 범위) ━━

    모듈      최고 승률 변형           거래     승률    거래당(배율전)
    롱 4배    E 분할매도             1108~1231  92~93%  +7.7~+8.7%
    숏 1배    연속 4주·4주 (지금)       15~19   76~89%  +8.4~+16.3%
    다이버    RSI차 12·10일            11~13   69~82%  +6.4~+11.0%

    조합                 지갑 결과      연복리   1년손실   2024~
    지금 봇             43.8~65.3배   66~77%    0~10%   7.9~11.7배
    모듈마다 최고 승률   16.1~24.5배   44~55%    4~20%   6.6~8.2배

승률을 끝까지 올리면 돈이 준다. E는 절반을 일찍 팔아 이기는 횟수는
늘지만 크게 오르는 구간을 덜 먹고, RSI차 12는 이기는 비율은 높아도
신호가 1/5로 줄어든다. 숏은 지금 설정이 이미 최고 승률이다.
다이버 20일 보유가 전체 기간엔 64~88배로 더 크지만 2024~ 구간은
6.1~8.9배로 지금(7.9~11.7배)보다 낮고, 9개 중 골라낸 값이라 안 바꾼다.
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
from ml.backtest_current_bot import load, ROUND_TRIP, FUNDING_PER_8H
from ml.per_coin_rules import sim
from ml.per_coin_walkforward import MENU
from ml.per_coin_portfolio import to_up

T0 = pd.Timestamp("2019-01-01")
TE = pd.Timestamp("2024-01-01")
PT = {"long": .015, "short": .40, "div": .40}
LV = {"long": 4.0, "short": 1.0, "div": 1.0}


def net(t, lev):
    raw = (t["exit_px"] / t["entry"] - 1) * 100
    px = raw if t["long"] else -raw
    liq = 100.0 / lev - 0.5
    if t["mae"] <= -liq:
        px = -liq
    return px - ROUND_TRIP - (FUNDING_PER_8H * t["bars_h"] / 8 if lev > 1 else 0)


def taken(trades, per_trade, leverage, max_gross=0.6, cb=0.20, cool_days=30, mcap=0.95):
    """UP.simulate와 같은 규칙으로 돌리고, 실제 체결된 거래를 돌려준다.

    mcap — 열려 있는 증거금 합이 자본의 이 비율을 넘는 진입은 건너뛴다.
    거래소는 잔고보다 큰 증거금 주문을 거절한다(2026-10-04 추가). 이게
    없으면 숏·다이버(각 40%, 1배)와 롱이 겹칠 때 증거금이 자본의 120%를
    넘는 불가능한 상태를 허용해 결과가 부풀려졌다. None이면 끈다(옛 결과 재현용).
    """
    cash = peak = 1.0; mdd = 0.0; open_ = []; halted = None; held = set(); got = []
    curve = {}
    ts = sorted(trades, key=lambda x: x["dt"])
    days = pd.date_range(ts[0]["dt"].normalize(), ts[-1]["dt"].normalize(), freq="D"); di = 0
    for t in ts:
        now = t["dt"]
        while di < len(days) and days[di] <= now:
            curve[days[di]] = cash; di += 1
        keep = []
        for ex, res, pl, sym, mar in open_:
            if ex <= now:
                cash += pl; held.discard(sym)
            else:
                keep.append((ex, res, pl, sym, mar))
        open_ = keep
        if cash <= 1e-9:
            return 0.0, 1.0, got, pd.Series(curve)
        peak = max(peak, cash); mdd = max(mdd, 1 - cash / peak)
        if halted is not None and now < halted:
            continue
        halted = None
        if 1 - cash / peak >= cb:
            halted = now + pd.Timedelta(days=cool_days); peak = cash; continue
        k = t["kind"]
        if t["sym"] in held:
            continue
        lev = leverage[k]; m = per_trade[k] * cash; reserved = m * lev
        if sum(o[1] for o in open_) + reserved > max_gross * cash * max(leverage.values()):
            continue
        if mcap is not None and sum(o[4] for o in open_) + m > mcap * cash:
            continue
        n_ = net(t, lev)
        pl = max(m * t["deployed"] * lev * n_ / 100, -m * t["deployed"])
        open_.append((t["exit"], reserved, pl, t["sym"], m)); held.add(t["sym"])
        got.append((k, n_, pl / cash * 100))
    for o in open_:
        cash += o[2]
    return cash, mdd, got, pd.Series(curve)


def main():
    syms = [s for s in S.SYMBOLS if os.path.exists(f"data/{s}_1d_all.csv.gz")]
    Dd = {s: SS.load_daily(s) for s in syms}
    Dd = {k: v for k, v in Dd.items() if v is not None and len(v) >= 400}
    W = {s: SS.to_weekly(d) for s, d in Dd.items()}

    LONG = {}
    for sym in S.SYMBOLS:
        g = load(sym)
        if g is None or len(g) < 400:
            continue
        o, h, l, c = (g[k].astype(float).values for k in ("open", "high", "low", "close"))
        for name, (ma, th, hd, fr, ou, st) in MENU.items():
            LONG.setdefault(name, []).extend(
                to_up(t) for t in sim(o, h, l, c, g["datetime"].values,
                                      ma, th, hd, fr, ou, S.STOP_PCT, sym=sym, step=st))
    SHORT = {f"연속 {k}주 · {h}주 보유": UP.make_short(W, streak=k, hold=h)
             for k in (3, 4, 5) for h in (2, 4, 6)}
    DIV = {f"RSI차 {g:g} · {h}일 보유": UP.make_div(Dd, gap=g, hold=h)
           for g in (5, 8, 12) for h in (5, 10, 20)}
    cut = lambda L: [t for t in L if t["dt"] >= T0]
    LONG = {k: cut(v) for k, v in LONG.items()}
    SHORT = {k: cut(v) for k, v in SHORT.items()}
    DIV = {k: cut(v) for k, v in DIV.items()}
    base = {"long": "A 지금 봇", "short": "연속 4주 · 4주 보유", "div": "RSI차 8 · 10일 보유"}
    POOL = {"long": LONG, "short": SHORT, "div": DIV}

    b = pd.read_csv("data/BTCUSDT_1d_all.csv.gz")
    col = "datetime" if "datetime" in b.columns else b.columns[0]
    b[col] = pd.to_datetime(b[col], format="mixed")
    b = b.rename(columns={col: "dt"}).sort_values("dt").set_index("dt")

    def flag(N, th, up=False):
        r = b["close"].pct_change(N) * 100; idx = r.index; v = r.values
        def f(ts):
            i = idx.searchsorted(pd.Timestamp(ts), side="right") - 2   # 전날 종가까지만 (그날 종가는 아직 모른다)
            if i < 0 or np.isnan(v[i]):
                return False
            return v[i] >= th if up else v[i] <= th
        return f
    BEARS = [flag(30, -15), flag(60, -15), flag(90, -20), flag(120, -25)]
    BULL = flag(90, 30, up=True)

    def run(sel, bear, start=None):
        tr = [t for t in POOL["long"][sel["long"]] if not bear(t["dt"])]
        tr += [t for t in POOL["short"][sel["short"]] if not BULL(t["dt"])]
        tr += POOL["div"][sel["div"]]
        if start is not None:
            tr = [t for t in tr if t["dt"] >= start]
        fin, mdd, got, curve = taken(tr, PT, LV)
        w = UP.windows(curve) if len(curve) > 400 else np.array([np.nan])
        cg = (fin ** (365 / max(len(curve), 1)) - 1) * 100 if fin > 0 else -100
        per = {}
        for k in ("long", "short", "div"):
            g = [x for x in got if x[0] == k]
            per[k] = (len(g), np.mean([x[1] > 0 for x in g]) * 100 if g else np.nan,
                      np.mean([x[1] for x in g]) if g else np.nan,
                      sum(x[2] for x in g))
        return fin, cg, mdd * 100, np.nanmean(w < 1) * 100, per

    def rng(xs, fmt):
        lo, hi = min(xs), max(xs)
        return (fmt % lo) if abs(hi - lo) < 1e-9 else (fmt % lo) + "~" + (fmt % hi)

    yrs = (pd.Timestamp("2026-09-27") - T0).days / 365
    best = {}
    for mod, lab in (("long", "과매도 롱 (4배)"), ("short", "주봉 숏 (1배)"), ("div", "상승 다이버전스 (1배)")):
        print("=" * 118)
        print(f"  {lab} — 변형별 · 나머지 두 모듈은 지금 설정 · bear=롱 끔, bull=숏 끔 · 2019~")
        print("=" * 118)
        print(f"  {'변형':<22s}{'거래':>9s}{'연간':>7s}{'승률':>12s}{'거래당(배율전)':>16s}"
              f"{'이 모듈 기여':>14s}{'지갑 결과':>16s}{'1년손실':>10s}{'2024~':>14s}")
        rows = []
        for name in POOL[mod]:
            sel = dict(base); sel[mod] = name
            R = [run(sel, B) for B in BEARS]
            H = [run(sel, B, TE)[0] for B in BEARS]
            n = [r[4][mod][0] for r in R]; wr = [r[4][mod][1] for r in R]
            av = [r[4][mod][2] for r in R]; ct = [r[4][mod][3] for r in R]
            rows.append((np.mean(wr), name))
            mark = " ◀지금" if name == base[mod] else ""
            print(f"  {name:<22s}{rng(n, '%d'):>9s}{np.mean(n)/yrs:>7.1f}{rng(wr, '%.0f') + '%':>12s}"
                  f"{rng(av, '%+.2f') + '%':>16s}{rng(ct, '%+.0f') + '%':>14s}"
                  f"{rng([r[0] for r in R], '%.1f') + '배':>16s}{rng([r[3] for r in R], '%.0f') + '%':>10s}"
                  f"{rng(H, '%.1f') + '배':>14s}{mark}")
        best[mod] = max(rows)[1]
        print(f"\n  → 최고 승률: {best[mod]}\n")

    print("=" * 118)
    print("  조합 비교 — bear=롱 끔, bull=숏 끔")
    print("=" * 118)
    for lab, sel in (("지금 봇", base), ("모듈마다 최고 승률", best)):
        R = [run(sel, B) for B in BEARS]; H = [run(sel, B, TE)[0] for B in BEARS]
        print(f"\n  [{lab}]  롱 {sel['long']} / 숏 {sel['short']} / 다이버 {sel['div']}")
        print(f"    지갑 {rng([r[0] for r in R], '%.1f')}배 · 연복리 {rng([r[1] for r in R], '%.0f')}% · "
              f"최대낙폭 {rng([r[2] for r in R], '%.0f')}% · 1년손실 {rng([r[3] for r in R], '%.0f')}% · "
              f"2024~ {rng(H, '%.1f')}배")
        for k, kl in (("long", "롱"), ("short", "숏"), ("div", "다이버")):
            n = [r[4][k][0] for r in R]; wr = [r[4][k][1] for r in R]
            av = [r[4][k][2] for r in R]; ct = [r[4][k][3] for r in R]
            print(f"      {kl:<6s} 거래 {rng(n, '%d'):>9s} · 승률 {rng(wr, '%.0f')}% · "
                  f"거래당 {rng(av, '%+.2f')}% · 기여 {rng(ct, '%+.0f')}%")


if __name__ == "__main__":
    main()
