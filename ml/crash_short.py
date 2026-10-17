"""
ml/crash_short.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
폭락장을 안다면 숏으로 크게 벌 수 있는가

앞선 ml/rsi_divergence_short.py에서 시험한 숏은 전부 "과매수를
되받는" 숏이었다(이평 +12% 위, RSI 80 위). 그건 강세를 역행하는
평균회귀 숏이고, 폭락장 숏과는 모양이 정반대다. 폭락장 숏은
이미 무너진 것을 따라가는 추세추종 숏이다. 다시 시험할 값어치가 있다.

질문을 셋으로 나눈다.

  ① 안다면 얼마인가 (상한선)
     실제 폭락 구간만 골라 숏을 쳤다면 얼마를 벌었나. 미래를 보고
     고르는 것이라 현실에서 도달 불가능한 값이지만, 기회의 크기를
     재는 데는 이게 정확한 상한선이다.

  ② 알 수 있는가
     폭락 직전에 미리 켜지는 신호가 있는가. 있다면 적중률과
     헛발질 비율이 얼마인가. 여기가 진짜 질문이다.

  ③ 몰라도 되는 방법이 있는가
     예측하지 않고 "이미 무너진 뒤" 따라 들어가는 돌파하락 숏.
     예측이 필요 없으므로 현실적으로 유일하게 굴릴 수 있는 형태다.

폭락 정의: 42종 균등 바스켓이 고점 대비 N일 안에 X% 이상 빠진 구간.
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
from ml.backtest_current_bot import load, ROUND_TRIP
import ml.rsi_divergence_short as R

TE = pd.Timestamp("2024-01-01")


def panel():
    cl, hi, lo, op = {}, {}, {}, {}
    for sym in S.SYMBOLS:
        g = load(sym)
        if g is None:
            continue
        d = g.set_index("datetime")
        cl[sym] = d["close"].astype(float)
        hi[sym] = d["high"].astype(float)
        lo[sym] = d["low"].astype(float)
        op[sym] = d["open"].astype(float)
    C = pd.DataFrame(cl).sort_index()
    return C, pd.DataFrame(hi).reindex(C.index), pd.DataFrame(lo).reindex(C.index), \
           pd.DataFrame(op).reindex(C.index)


def basket(C):
    """42종 균등 바스켓 지수. 상장 전 구간은 자동으로 빠진다."""
    r = C.pct_change()
    return (1 + r.mean(axis=1).fillna(0)).cumprod()


# ── 신호 생성기 (4시간봉 인덱스 기준) ──────────────────────
def sig_breakdown(c, h, l, o, look=120):
    """look봉 신저가를 아래로 뚫은 봉 = 이미 무너진 뒤 따라 들어간다."""
    low_n = pd.Series(l).rolling(look).min().shift(1).values
    ok = c < low_n
    return np.where(ok & ~np.r_[False, ok[:-1]])[0]


def sig_ma_cross_down(c, h, l, o, fast=300, slow=1200):
    """MA50이 MA200 아래로 내려간 뒤, 종가가 MA50 아래인 봉 (데드크로스 국면)."""
    mf = pd.Series(c).rolling(fast).mean().values
    ms = pd.Series(c).rolling(slow).mean().values
    ok = (mf < ms) & (c < mf)
    return np.where(ok & ~np.r_[False, ok[:-1]])[0]


def make_regime_sig(base_fn, regime_ok, **kw):
    """신호를 만든 뒤 시장 국면 마스크로 거른다."""
    def fn(c, h, l, o, _idx=None):
        raw = base_fn(c, h, l, o, **kw)
        return np.array([i for i in raw if _idx is not None and regime_ok[_idx[i]]],
                        dtype=int) if _idx is not None else raw
    return fn


def build_with_regime(base_fn, is_long, regime: pd.Series | None, **kw):
    """regime은 datetime 인덱스의 bool 시리즈. None이면 전 구간 허용."""
    trades = []
    for sym in S.SYMBOLS:
        g = load(sym)
        if g is None or len(g) < 1300:
            continue
        o = g["open"].astype(float).values
        h = g["high"].astype(float).values
        l = g["low"].astype(float).values
        c = g["close"].astype(float).values
        dt = pd.to_datetime(g["datetime"]).values
        n = len(c)
        idx = base_fn(c, h, l, o, **kw)
        if regime is not None:
            rv = regime.reindex(pd.DatetimeIndex(dt), method="ffill").fillna(False).values
            idx = [i for i in idx if rv[i]]
        lock = -10**9
        for i in idx:
            if i <= lock:
                continue
            t = R.resolve(sym, o, h, l, c, dt, int(i), n, is_long)
            if t:
                lock = i + R.HOLD
                trades.append(t)
    return sorted(trades, key=lambda t: t["dt"])


def show(rows):
    print(f"\n  {'구성':<30s}{'거래':>7s}{'승률':>8s}{'거래당':>9s}"
          f"{'전체':>10s}{'학습':>9s}{'홀드아웃':>10s}{'낙폭':>8s}")
    print("  " + "-" * 92)
    for name, ts in rows:
        if len(ts) < 25:
            print(f"  {name:<30s}{len(ts):>7d}   신호 부족")
            continue
        tr = [t for t in ts if pd.Timestamp(t["dt"]) < TE]
        ho = [t for t in ts if pd.Timestamp(t["dt"]) >= TE]
        a, b, cft = R.simulate(tr), R.simulate(ho), R.simulate(ts)
        px = np.array([((t["exit_px"] / t["entry"] - 1) * 100
                        * (1 if t["long"] else -1)) - ROUND_TRIP for t in ts])
        f = lambda r: r["final"] if r else float("nan")
        print(f"  {name:<30s}{len(ts):>7d}{(px>0).mean()*100:>7.1f}%{px.mean():>8.2f}%"
              f"{f(cft):>9.2f}배{f(a):>8.2f}배{f(b):>9.2f}배"
              f"{(cft['mdd']*100 if cft else float('nan')):>7.1f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--crash-pct", type=float, default=25.0)
    ap.add_argument("--crash-days", type=int, default=30)
    a = ap.parse_args()

    C, H, L, O = panel()
    B = basket(C)
    # 폭락 구간: 바스켓이 앞으로 crash_days 안에 crash_pct 이상 빠지는 시점
    bars = int(a.crash_days * 6)
    fwd_min = B[::-1].rolling(bars, min_periods=1).min()[::-1]
    fwd_dd = (fwd_min / B - 1) * 100
    crash_ahead = fwd_dd <= -a.crash_pct          # ← 미래를 본다 (상한선 계산용)
    # 이미 진행 중인 폭락: 지난 crash_days 동안 고점 대비 낙폭
    past_max = B.rolling(bars, min_periods=1).max()
    now_dd = (B / past_max - 1) * 100
    in_crash = now_dd <= -a.crash_pct             # ← 과거만 본다 (실전 가능)

    print("=" * 100)
    print(f"  폭락장 숏 — 바스켓 42종이 {a.crash_days}일 안에 {a.crash_pct:.0f}% 이상 빠지는 구간")
    print(f"  복리 · 배율 2배 · 거래당 5% · 총노출 80% · 왕복 0.40% · "
          f"{R.HOLD}봉 보유 · 손절 {R.STOP}%")
    print("=" * 100)
    print(f"\n  전체 {len(B):,}봉 중")
    print(f"    앞으로 폭락이 올 구간(미래를 봄)  {crash_ahead.sum():,}봉 "
          f"({crash_ahead.mean()*100:.1f}%)")
    print(f"    이미 폭락 중인 구간(과거만 봄)    {in_crash.sum():,}봉 "
          f"({in_crash.mean()*100:.1f}%)")

    print("\n" + "=" * 100)
    print("  ① 안다면 얼마인가 — 폭락을 미리 알고 그 구간에만 숏 (도달 불가능한 상한선)")
    print("=" * 100)
    rows = [
        ("롱만 (현재 규칙)", build_with_regime(R.sig_ma_long, True, None)),
        ("★ 폭락 예지 숏 · 과매수 되받기",
         build_with_regime(R.sig_ma_short, False, crash_ahead)),
        ("★ 폭락 예지 숏 · 신저가 돌파",
         build_with_regime(sig_breakdown, False, crash_ahead, look=120)),
    ]
    show(rows)
    print("\n  ↑ 이 줄들은 '앞으로 30일 안에 25% 빠진다'를 미리 아는 경우다.")
    print("    현실에서 도달 불가능하다. 기회의 크기를 재는 상한선으로만 읽는다.")

    print("\n" + "=" * 100)
    print("  ② 몰라도 되는 방법 — 이미 무너진 뒤 따라 들어가는 추세추종 숏")
    print("=" * 100)
    rows2 = [
        ("신저가(20일) 돌파 숏 · 전구간",
         build_with_regime(sig_breakdown, False, None, look=120)),
        ("신저가(50일) 돌파 숏 · 전구간",
         build_with_regime(sig_breakdown, False, None, look=300)),
        ("데드크로스 국면 숏 · 전구간",
         build_with_regime(sig_ma_cross_down, False, None)),
        ("신저가(20일) 숏 · 폭락 진행 중에만",
         build_with_regime(sig_breakdown, False, in_crash, look=120)),
        ("신저가(50일) 숏 · 폭락 진행 중에만",
         build_with_regime(sig_breakdown, False, in_crash, look=300)),
        ("과매수 되받기 숏 · 폭락 진행 중에만",
         build_with_regime(R.sig_ma_short, False, in_crash)),
    ]
    show(rows2)

    print("\n" + "=" * 100)
    print("  ③ 알 수 있는가 — '이미 폭락 중'이 '앞으로 더 빠진다'를 맞히는가")
    print("=" * 100)
    tp = int((in_crash & crash_ahead).sum())
    fp = int((in_crash & ~crash_ahead).sum())
    fn_ = int((~in_crash & crash_ahead).sum())
    print(f"\n  '이미 {a.crash_pct:.0f}% 빠졌다'를 폭락 경보로 쓸 때")
    print(f"    경보를 켠 봉 {tp+fp:,}개 중 실제로 더 빠진 것 {tp:,}개 "
          f"→ 적중률 {tp/max(tp+fp,1)*100:.1f}%")
    print(f"    실제 폭락 {tp+fn_:,}봉 중 경보가 켜져 있던 것 {tp:,}개 "
          f"→ 포착률 {tp/max(tp+fn_,1)*100:.1f}%")
    print(f"    헛발질 {fp:,}봉 ({fp/max(tp+fp,1)*100:.1f}%)")

    print("\n  ── 폭락이 실제로 몇 번 있었나 (바스켓 기준)")
    ev, on, start = [], False, None
    for t, v in crash_ahead.items():
        if v and not on:
            on, start = True, t
        elif not v and on:
            on = False
            seg = B[start:t]
            ev.append((start, t, (seg.min() / seg.iloc[0] - 1) * 100))
    if on:
        seg = B[start:]
        ev.append((start, B.index[-1], (seg.min() / seg.iloc[0] - 1) * 100))
    print(f"    {len(ev)}번 · 8.8년 동안")
    for s, e, dd in ev:
        print(f"      {str(s)[:10]} ~ {str(e)[:10]}  최대 {dd:.1f}%  "
              f"({(e-s).days}일)")


if __name__ == "__main__":
    main()
