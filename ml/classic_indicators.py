"""
ml/classic_indicators.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
고전 기술지표 전수 검증 — 볼린저·MACD·스토캐스틱·일목·거래량

ml/rsi_divergence_short.py와 같은 틀이다. 진입 조건만 바꾸고
나머지(20봉 보유·손절 -40%·배율 2배·총노출 80%·복리·왕복 0.40%)를
전부 동일하게 맞춰 신호 자체를 비교한다. 분할매수는 기준선 규칙
고유의 장치라 여기서도 뺀다.

검증 대상
  볼린저밴드   하단 이탈 / 밴드폭 수축 후 확장 / %B
  MACD        골든크로스 / 히스토그램 바닥 반전
  스토캐스틱    %K 과매도 반등 / 슬로우 크로스
  일목균형표    구름 상향 돌파 / 전환선-기준선 크로스
  거래량       거래량 급증 하락봉 / 거래량 마름

각 지표는 흔히 쓰이는 표준 파라미터를 먼저 쓰고, 그 주변을 몇 개
같이 돌린다. 특정 값에서만 되는 것은 잡음이라고 봐야 하기 때문이다.
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
from ml.backtest_current_bot import ROUND_TRIP
import ml.rsi_divergence_short as R

TE = pd.Timestamp("2024-01-01")


def _cross_up(x, y):
    """x가 y를 아래에서 위로 뚫은 봉."""
    a = x > y
    return a & ~np.r_[False, a[:-1]]


# ── 볼린저밴드 ──────────────────────────────────────────
def sig_bb_lower(c, h, l, o, n=20, k=2.0):
    """하단 밴드 이탈 후 되돌아온 봉 (이탈 중에는 계속 참이라 진입점만 잡는다)."""
    m = pd.Series(c).rolling(n).mean()
    s = pd.Series(c).rolling(n).std()
    lower = (m - k * s).values
    below = c < lower
    # 아래로 처음 뚫은 봉
    return np.where(below & ~np.r_[False, below[:-1]])[0]


def sig_bb_reenter(c, h, l, o, n=20, k=2.0):
    """하단을 뚫었다가 다시 밴드 안으로 들어온 봉 — 되돌림 확인형."""
    m = pd.Series(c).rolling(n).mean()
    s = pd.Series(c).rolling(n).std()
    lower = (m - k * s).values
    below = c < lower
    return np.where(~below & np.r_[False, below[:-1]])[0]


def sig_bb_squeeze(c, h, l, o, n=20, k=2.0, look=120):
    """밴드폭이 최근 최저 수준에서 확장 시작 — 변동성 수축 후 방향 발생."""
    m = pd.Series(c).rolling(n).mean()
    s = pd.Series(c).rolling(n).std()
    width = (2 * k * s / m).values
    lo = pd.Series(width).rolling(look).min().values
    # 처음엔 "최저 대비 5% 이내 + 폭 10% 확대"로 잡았더니 신호가 0이었다.
    # 4시간봉에서 그 둘이 같은 봉에 겹치는 일이 사실상 없다. 수축 판정을
    # 하위 20%로 넓히고, 확장은 직전 봉 대비로만 본다.
    tight = width <= pd.Series(width).rolling(look).quantile(0.20).values
    prev_tight = np.r_[False, tight[:-1]]
    expand = np.r_[False, (width[1:] > width[:-1])]
    return np.where(prev_tight & expand & (c > m.values))[0]


# ── MACD ──────────────────────────────────────────────
def macd_lines(c, f=12, s=26, sig=9):
    ef = pd.Series(c).ewm(span=f, adjust=False).mean()
    es = pd.Series(c).ewm(span=s, adjust=False).mean()
    line = (ef - es)
    signal = line.ewm(span=sig, adjust=False).mean()
    return line.values, signal.values, (line - signal).values


def sig_macd_cross(c, h, l, o, f=12, s=26, sig=9):
    line, signal, _ = macd_lines(c, f, s, sig)
    return np.where(_cross_up(line, signal))[0]


def sig_macd_cross_below0(c, h, l, o, f=12, s=26, sig=9):
    """0선 아래에서 난 골든크로스 — 하락 뒤 반전만 잡는다."""
    line, signal, _ = macd_lines(c, f, s, sig)
    return np.where(_cross_up(line, signal) & (line < 0))[0]


def sig_macd_hist_turn(c, h, l, o, f=12, s=26, sig=9):
    """히스토그램이 음수에서 바닥을 찍고 올라오기 시작한 봉."""
    _, _, hist = macd_lines(c, f, s, sig)
    up = np.r_[False, hist[1:] > hist[:-1]]
    return np.where(up & ~np.r_[False, up[:-1]] & (hist < 0))[0]


# ── 스토캐스틱 ─────────────────────────────────────────
def stoch(c, h, l, n=14, d=3):
    hh = pd.Series(h).rolling(n).max()
    ll = pd.Series(l).rolling(n).min()
    k = 100 * (pd.Series(c) - ll) / (hh - ll).replace(0, np.nan)
    return k.values, k.rolling(d).mean().values


def sig_stoch_oversold(c, h, l, o, n=14, d=3, level=20):
    k, _ = stoch(c, h, l, n, d)
    return np.where(_cross_up(k, np.full_like(k, level)))[0]


def sig_stoch_cross(c, h, l, o, n=14, d=3, level=20):
    """%K가 %D를 과매도권에서 상향 돌파."""
    k, dd = stoch(c, h, l, n, d)
    return np.where(_cross_up(k, dd) & (k < level + 10))[0]


# ── 일목균형표 ─────────────────────────────────────────
def ichimoku(c, h, l, t=9, kj=26, sb=52):
    hs, ls = pd.Series(h), pd.Series(l)
    conv = (hs.rolling(t).max() + ls.rolling(t).min()) / 2
    base = (hs.rolling(kj).max() + ls.rolling(kj).min()) / 2
    a = ((conv + base) / 2).shift(kj)
    b = ((hs.rolling(sb).max() + ls.rolling(sb).min()) / 2).shift(kj)
    return conv.values, base.values, a.values, b.values


def sig_ichi_cloud(c, h, l, o, t=9, kj=26, sb=52):
    """구름 위로 상향 돌파."""
    _, _, a, b = ichimoku(c, h, l, t, kj, sb)
    top = np.nanmax(np.vstack([a, b]), axis=0)
    return np.where(_cross_up(c, top))[0]


def sig_ichi_tk(c, h, l, o, t=9, kj=26, sb=52):
    """전환선이 기준선을 상향 돌파 (TK 크로스)."""
    conv, base, _, _ = ichimoku(c, h, l, t, kj, sb)
    return np.where(_cross_up(conv, base))[0]


# ── 거래량 ────────────────────────────────────────────
def sig_vol_spike_down(c, h, l, o, v=None, mult=3.0, look=120):
    """평소 대비 mult배 이상 거래량 + 음봉 = 투매 (v는 build에서 넣는다)."""
    if v is None:
        return np.array([], dtype=int)
    avg = pd.Series(v).rolling(look).mean().values
    return np.where((v > avg * mult) & (c < o))[0]


def sig_vol_dry(c, h, l, o, v=None, frac=0.5, look=120):
    """거래량이 평소의 frac 이하로 마른 뒤 양봉 = 매도 소진."""
    if v is None:
        return np.array([], dtype=int)
    avg = pd.Series(v).rolling(look).mean().values
    return np.where((v < avg * frac) & (c > o))[0]


def build(fn, is_long=True, **kw):
    from ml.backtest_current_bot import load
    trades = []
    needs_v = "v" in fn.__code__.co_varnames[:fn.__code__.co_argcount]
    for sym in S.SYMBOLS:
        g = load(sym)
        if g is None or len(g) < 300:
            continue
        o = g["open"].astype(float).values
        h = g["high"].astype(float).values
        l = g["low"].astype(float).values
        c = g["close"].astype(float).values
        dt = pd.to_datetime(g["datetime"]).values
        n = len(c)
        k = dict(kw)
        if needs_v:
            if "volume" not in g.columns:
                continue
            k["v"] = g["volume"].astype(float).values
        lock = -10**9
        for i in fn(c, h, l, o, **k):
            if i <= lock or i < 60:
                continue
            t = R.resolve(sym, o, h, l, c, dt, int(i), n, is_long)
            if t:
                lock = i + R.HOLD
                trades.append(t)
    return sorted(trades, key=lambda t: t["dt"])


def main():
    argparse.ArgumentParser().parse_args()
    CASES = [
        ("기준선 · 이평 -12.26%",     R.sig_ma_long, {}),
        ("볼린저 하단 이탈 (20,2)",    sig_bb_lower, {}),
        ("볼린저 하단 이탈 (20,2.5)",  sig_bb_lower, dict(k=2.5)),
        ("볼린저 하단 이탈 (20,3)",    sig_bb_lower, dict(k=3.0)),
        ("볼린저 하단 이탈 (50,2)",    sig_bb_lower, dict(n=50)),
        ("볼린저 밴드 복귀 (20,2)",    sig_bb_reenter, {}),
        ("볼린저 밴드 복귀 (20,2.5)",  sig_bb_reenter, dict(k=2.5)),
        ("볼린저 수축후 확장",          sig_bb_squeeze, {}),
        ("MACD 골든크로스",           sig_macd_cross, {}),
        ("MACD 골든크로스 (0선 아래)",  sig_macd_cross_below0, {}),
        ("MACD 히스토그램 반전",        sig_macd_hist_turn, {}),
        ("MACD (6,13,5) 크로스",     sig_macd_cross, dict(f=6, s=13, sig=5)),
        ("스토캐스틱 20 상향돌파",       sig_stoch_oversold, {}),
        ("스토캐스틱 10 상향돌파",       sig_stoch_oversold, dict(level=10)),
        ("스토캐스틱 %K-%D 크로스",     sig_stoch_cross, {}),
        ("일목 구름 상향돌파",          sig_ichi_cloud, {}),
        ("일목 전환-기준 크로스",        sig_ichi_tk, {}),
        ("거래량 3배 + 음봉 (투매)",    sig_vol_spike_down, {}),
        ("거래량 5배 + 음봉",          sig_vol_spike_down, dict(mult=5.0)),
        ("거래량 마름 + 양봉",          sig_vol_dry, {}),
    ]
    print("=" * 100)
    print("  고전 기술지표 전수 검증 — 바이낸스 42종 4시간봉 2017~2026")
    print(f"  전부 롱 · {R.HOLD}봉 보유 · 손절 {R.STOP}% · 배율 2배 · 총노출 80% · "
          f"복리 · 왕복 {ROUND_TRIP}%")
    print("  (분할매수 제외 — 신호 자체를 비교하려고 조건을 통일했다)")
    print("=" * 100)
    print(f"\n  {'신호':<26s}{'거래':>7s}{'승률':>8s}{'거래당':>9s}"
          f"{'전체':>10s}{'학습':>9s}{'홀드아웃':>10s}{'낙폭':>8s}")
    print("  " + "-" * 90)
    rows = []
    for name, fn, kw in CASES:
        t = build(fn, True, **kw)
        if len(t) < 40:
            print(f"  {name:<26s}{len(t):>7d}   신호 부족")
            continue
        r = R.report(name, t)
        rows.append(r)
        print(f"  {name:<26s}{r['sig']:>7d}{r['wr']:>7.1f}%{r['avg']:>8.2f}%"
              f"{r['full']:>9.2f}배{r['tr']:>8.2f}배{r['ho']:>9.2f}배{r['mdd']:>7.1f}%")

    d = pd.DataFrame(rows)
    base = d.iloc[0]
    win = d.iloc[1:][(d.iloc[1:].full > base.full) & (d.iloc[1:].ho > base.ho)]
    print(f"\n  ── 기준선을 전체·홀드아웃 양쪽에서 이긴 것: {len(win)} / {len(d)-1}")
    for _, x in win.iterrows():
        print(f"     {x['name']:<26s} 거래당 {x.avg:+.2f}% · 전체 {x.full:.2f}배 · "
              f"홀드 {x.ho:.2f}배 · 거래 {x.sig}건")
    if not len(win):
        print("     없다.")
    near = d.iloc[1:][d.iloc[1:].avg > 0].sort_values("avg", ascending=False)
    print(f"\n  ── 거래당이 플러스인 것: {len(near)} / {len(d)-1}")
    for _, x in near.head(6).iterrows():
        print(f"     {x['name']:<26s} {x.avg:+.2f}%  (기준선 {base.avg:+.2f}%)")
    os.makedirs("ml/saved_models", exist_ok=True)
    d.to_csv("ml/saved_models/classic_indicators.csv", index=False)
    print(f"\n  저장: ml/saved_models/classic_indicators.csv")


if __name__ == "__main__":
    main()
