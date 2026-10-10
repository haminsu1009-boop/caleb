"""
ml/community_strategies.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
유튜브·커뮤니티·트레이딩 블로그의 단타 전략을 최대한 모아 백테스트

ml/youtube_daytrade.py 가 10개를 시험해 0개가 살아남았다. 표본이
작았으니 이번엔 40개 넘게, 계열을 나눠서 훑는다.

판정을 두 축으로 나눈다. 이게 핵심이다.

  총수익  수수료 0. **신호에 정보가 있기는 한가?**
  순수익  수수료를 물린 뒤. **실제로 남는가?**

앞선 실험에서 5분봉 10개 중 7개가 무작위 진입을 총수익으로 이겼는데
순수익은 0개였다. 즉 "맞는 말이지만 돈은 안 되는" 규칙이 대부분이다.
그래서 수수료를 0.04%(메이커 양방향) / 0.10% / 0.20% / 0.40%(테이커,
우리 실측)로 나눠 어느 지점에서 죽는지를 본다.

기준선은 **같은 구간·같은 코인에서 무작위로 진입해 같은 봉수만큼
보유**한 것이다. 상승장에서는 아무 때나 사도 오르므로, 이걸 안 이기면
규칙이 아니라 시장을 산 것이다.

출처: 검색으로 모은 것들 — RSI 30/70, 볼린저 상·하단, 이평 교차,
정배열 눌림목, MACD, 스토캐스틱RSI, 거래량 급증, VWAP 되돌림,
오프닝 레인지 돌파, 돈치안 채널, 슈퍼트렌드, 볼린저 스퀴즈,
인사이드바, 해머·장악형·망치꼬리 같은 캔들패턴, 연속 음봉 반등 등.

실행: python ml/community_strategies.py [--tf 1h|5m] [--long-hold]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)

SYMS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT"]
TEST_START = pd.Timestamp("2024-01-01")
FEES = [0.04, 0.10, 0.20, 0.40]
RNG = np.random.default_rng(11)


def load(sym, tf):
    p = f"data/{sym}_{tf}_all.csv.gz"
    if not os.path.exists(p):
        return None
    d = pd.read_csv(p)
    d["dt"] = pd.to_datetime(d["timestamp"], format="ISO8601")
    return d.dropna(subset=["close"]).reset_index(drop=True)


# ── 지표 ────────────────────────────────────────────────────────
def _s(x):
    return pd.Series(x)


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up = _s(np.where(d > 0, d, 0.)).ewm(alpha=1/n, adjust=False).mean()
    dn = _s(np.where(d < 0, -d, 0.)).ewm(alpha=1/n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).values


def boll(c, n=20, k=2.0):
    m, sd = _s(c).rolling(n).mean(), _s(c).rolling(n).std()
    return (m - k*sd).values, m.values, (m + k*sd).values


def macd(c, f=12, s=26, sig=9):
    x = _s(c)
    line = x.ewm(span=f, adjust=False).mean() - x.ewm(span=s, adjust=False).mean()
    return line.values, line.ewm(span=sig, adjust=False).mean().values


def stoch_rsi(c, n=14, k=3):
    r = _s(rsi(c, n)); lo, hi = r.rolling(n).min(), r.rolling(n).max()
    return ((r - lo) / (hi - lo).replace(0, np.nan)).rolling(k).mean().values * 100


def atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return _s(tr).ewm(alpha=1/n, adjust=False).mean().values


def williams_r(h, l, c, n=14):
    hh, ll = _s(h).rolling(n).max(), _s(l).rolling(n).min()
    return (-100 * (hh - c) / (hh - ll).replace(0, np.nan)).values


def cci(h, l, c, n=20):
    tp = (h + l + c) / 3
    m = _s(tp).rolling(n).mean()
    md = _s(tp).rolling(n).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return ((tp - m) / (0.015 * md.replace(0, np.nan))).values


def vwap_daily(d):
    """날짜별로 리셋되는 거래량가중평균가."""
    tp = (d["high"] + d["low"] + d["close"]) / 3
    v = d["volume"]
    day = d["dt"].dt.floor("D")
    return ((tp * v).groupby(day).cumsum() / v.groupby(day).cumsum().replace(0, np.nan)).values


def _cross_up(a, b):
    return (a > b) & (np.roll(a, 1) <= np.roll(b, 1))


# ── 진입 규칙: 인덱스 배열을 돌려준다 ─────────────────────────────
def R(fn):
    return fn


def r_rsi(lo=30):
    def g(d):
        r = rsi(d["close"].values)
        return np.where((r < lo) & (np.roll(r, 1) >= lo))[0]
    return g


def r_stochrsi(lo=20):
    def g(d):
        s = stoch_rsi(d["close"].values)
        return np.where(_cross_up(s, np.full_like(s, lo)))[0]
    return g


def r_williams(lo=-80):
    def g(d):
        w = williams_r(d["high"].values, d["low"].values, d["close"].values)
        return np.where(_cross_up(w, np.full_like(w, lo)))[0]
    return g


def r_cci(lo=-100):
    def g(d):
        x = cci(d["high"].values, d["low"].values, d["close"].values)
        return np.where(_cross_up(x, np.full_like(x, lo)))[0]
    return g


def r_boll_low(n=20, k=2.0):
    def g(d):
        c = d["close"].values; lb, _, _ = boll(c, n, k)
        return np.where((c <= lb) & (np.roll(c, 1) > np.roll(lb, 1)))[0]
    return g


def r_boll_break(n=20, k=2.0, vmult=2.0):
    def g(d):
        c, v = d["close"].values, d["volume"].values
        _, _, ub = boll(c, n, k)
        va = _s(v).rolling(20).mean().values
        return np.where((c > ub) & (np.roll(c, 1) <= np.roll(ub, 1)) & (v > vmult*va))[0]
    return g


def r_squeeze(n=20, look=120):
    """볼린저 폭이 최근 look봉 중 최저 → 상단 돌파."""
    def g(d):
        c = d["close"].values
        lb, m, ub = boll(c, n, 2.0)
        w = (ub - lb) / m
        narrow = w <= _s(w).rolling(look).quantile(.1).values
        return np.where(np.roll(narrow, 1) & (c > ub))[0]
    return g


def r_high(w=20):
    def g(d):
        c = d["close"].values
        hh = _s(c).rolling(w).max().shift(1).values
        return np.where(c > hh)[0]
    return g


def r_donchian(w=20):
    def g(d):
        h, c = d["high"].values, d["close"].values
        hh = _s(h).rolling(w).max().shift(1).values
        return np.where(c > hh)[0]
    return g


def r_ma_cross(a=5, b=20):
    def g(d):
        c = _s(d["close"].values)
        return np.where(_cross_up(c.rolling(a).mean().values,
                                  c.rolling(b).mean().values))[0]
    return g


def r_px_cross_ma(n=20):
    def g(d):
        c = d["close"].values
        return np.where(_cross_up(c, _s(c).rolling(n).mean().values))[0]
    return g


def r_macd_cross():
    def g(d):
        line, sig = macd(d["close"].values)
        return np.where(_cross_up(line, sig))[0]
    return g


def r_macd_hist():
    def g(d):
        line, sig = macd(d["close"].values)
        h = line - sig
        return np.where((h > 0) & (np.roll(h, 1) <= 0))[0]
    return g


def r_pullback(ma=20, trend=60):
    """정배열 상태에서 ma까지 눌렸다가 되돌아오는 자리."""
    def g(d):
        c = _s(d["close"].values)
        m, t = c.rolling(ma).mean(), c.rolling(trend).mean()
        up = m > t
        touch = (c <= m) & (c.shift(1) > m.shift(1))
        return np.where((up & touch).values)[0]
    return g


def r_ema_pullback(ema=20, trend=50):
    def g(d):
        c = _s(d["close"].values)
        e, t = c.ewm(span=ema, adjust=False).mean(), c.rolling(trend).mean()
        return np.where(((c > t) & (c <= e) & (c.shift(1) > e.shift(1))).values)[0]
    return g


def r_vwap_pullback():
    def g(d):
        c = d["close"].values; v = vwap_daily(d)
        t = _s(c).rolling(50).mean().values
        return np.where((c > t) & (c <= v) & (np.roll(c, 1) > np.roll(v, 1)))[0]
    return g


def r_vwap_reclaim():
    def g(d):
        c = d["close"].values
        return np.where(_cross_up(c, vwap_daily(d)))[0]
    return g


def r_orb(first=6):
    """그날 첫 first봉의 고가를 넘는 첫 봉."""
    def g(d):
        day = d["dt"].dt.floor("D")
        idx = np.arange(len(d))
        pos = idx - day.map(day.groupby(day).apply(lambda x: x.index[0])).values
        hi = _s(d["high"].values).groupby(day).transform(
            lambda x: x.iloc[:first].max()).values
        c = d["close"].values
        return np.where((pos >= first) & (c > hi) & (np.roll(c, 1) <= np.roll(hi, 1)))[0]
    return g


def r_vol_spike(mult=3.0, up=True):
    def g(d):
        v, c, o = d["volume"].values, d["close"].values, d["open"].values
        va = _s(v).rolling(20).mean().values
        cond = v > mult * va
        return np.where(cond & ((c > o) if up else (c < o)))[0]
    return g


def r_vol_dryup(mult=0.5):
    def g(d):
        v, c, o = d["volume"].values, d["close"].values, d["open"].values
        va = _s(v).rolling(20).mean().values
        return np.where((v < mult*va) & (c > o))[0]
    return g


def r_hammer(wick=2.0):
    """아래꼬리가 몸통의 wick배 이상 — 망치형."""
    def g(d):
        o, h, l, c = (d["open"].values, d["high"].values,
                      d["low"].values, d["close"].values)
        body = np.abs(c - o)
        lower = np.minimum(o, c) - l
        upper = h - np.maximum(o, c)
        return np.where((body > 0) & (lower > wick*body) & (upper < body))[0]
    return g


def r_engulf():
    """상승 장악형."""
    def g(d):
        o, c = d["open"].values, d["close"].values
        po, pc = np.roll(o, 1), np.roll(c, 1)
        return np.where((pc < po) & (c > o) & (c > po) & (o < pc))[0]
    return g


def r_three_soldiers():
    def g(d):
        o, c = d["open"].values, d["close"].values
        up = c > o
        return np.where(up & np.roll(up, 1) & np.roll(up, 2)
                        & (c > np.roll(c, 1)) & (np.roll(c, 1) > np.roll(c, 2)))[0]
    return g


def r_n_red(n=3):
    """연속 n개 음봉 뒤 반등 노림."""
    def g(d):
        o, c = d["open"].values, d["close"].values
        red = c < o
        m = red.copy()
        for k in range(1, n):
            m &= np.roll(red, k)
        return np.where(m)[0]
    return g


def r_inside_bar():
    def g(d):
        h, l, c = d["high"].values, d["low"].values, d["close"].values
        ph, pl = np.roll(h, 1), np.roll(l, 1)
        inside = (h < ph) & (l > pl)
        return np.where(np.roll(inside, 1) & (c > np.roll(h, 1)))[0]
    return g


def r_supertrend(n=10, mult=3.0):
    def g(d):
        h, l, c = d["high"].values, d["low"].values, d["close"].values
        a = atr(h, l, c, n)
        basis = (h + l) / 2
        lower = basis - mult*a
        return np.where(_cross_up(c, lower))[0]
    return g


def r_gap_fill():
    """갭 하락 후 전일 종가 회복."""
    def g(d):
        o, c = d["open"].values, d["close"].values
        pc = np.roll(c, 1)
        return np.where((o < pc*0.99) & (c > pc))[0]
    return g


def r_roc(n=10, q=5.0):
    def g(d):
        c = _s(d["close"].values)
        r = (c / c.shift(n) - 1) * 100
        return np.where(_cross_up(r.values, np.full(len(c), q)))[0]
    return g


# ── 청산 ────────────────────────────────────────────────────────
def _next_true(cond, cap):
    n = len(cond); nxt = np.full(n, -1, np.int64); ahead = -1
    for j in range(n-1, -1, -1):
        nxt[j] = ahead
        if cond[j]:
            ahead = j
    too_far = (nxt < 0) | (nxt - np.arange(n) > cap)
    nxt[too_far] = -1
    return nxt


def X(kind, **kw):
    def build(d):
        c, h, l = d["close"].values, d["high"].values, d["low"].values
        n = len(c); idx = np.arange(n)
        if kind == "bars":
            return np.minimum(idx + kw["bars"], n-1)
        cap = kw.get("cap", 300)
        if kind == "rsi":
            cond = rsi(c) >= kw.get("hi", 70)
        elif kind == "boll_up":
            _, _, ub = boll(c, 20, kw.get("k", 2.0)); cond = ~np.isnan(ub) & (h >= ub)
        elif kind == "boll_mid":
            _, m, _ = boll(c, 20); cond = ~np.isnan(m) & (h >= m)
        elif kind == "vwap":
            v = vwap_daily(d); cond = ~np.isnan(v) & (h >= v)
        elif kind == "atr_tp":
            a = atr(h, l, c, 14)
            tgt = c + kw.get("mult", 2.0) * a
            cond = np.r_[False, h[1:] >= tgt[:-1]]
        else:
            raise ValueError(kind)
        nxt = _next_true(np.nan_to_num(cond).astype(bool), cap)
        return np.where(nxt >= 0, nxt, np.minimum(idx + cap, n-1))
    return build


def backtest(d, entries, exit_build, fee=0.40):
    o, c, l = d["open"].values, d["close"].values, d["low"].values
    dt = d["dt"].values; n = len(c)
    xmap = exit_build(d)
    ei, xi, lock = [], [], -1
    for i in entries:
        e = i + 1
        if i <= lock or e >= n-1:
            continue
        j = max(int(xmap[e]), e+1); j = min(j, n-1)
        ei.append(e); xi.append(j); lock = j
    if not ei:
        return pd.DataFrame()
    e, j = np.array(ei), np.array(xi)
    gross = (c[j] / o[e] - 1) * 100
    return pd.DataFrame({"dt": pd.to_datetime(dt[e]), "gross": gross,
                         "bars": j - e})


def baseline(d, hold, n=800):
    o, c, dt = d["open"].values, d["close"].values, d["dt"].values
    N = len(c)
    if N - hold - 250 < 100:
        return pd.DataFrame()
    idx = RNG.choice(np.arange(200, N-hold-2), size=min(n, N-hold-250), replace=False)
    return pd.DataFrame({"dt": pd.to_datetime(dt[idx]),
                         "gross": (c[idx+hold] / o[idx] - 1) * 100})


RULES = [
    # ── 오실레이터 되돌림
    ("RSI 30 → 70",              r_rsi(30),        X("rsi")),
    ("RSI 30 → 12봉",             r_rsi(30),        X("bars", bars=12)),
    ("RSI 20 (깊은 과매도) → 70",  r_rsi(20),        X("rsi")),
    ("RSI 30 → 볼린저 중단",       r_rsi(30),        X("boll_mid")),
    ("스토캐스틱RSI 20 반등",       r_stochrsi(20),   X("bars", bars=12)),
    ("윌리엄스%R -80 반등",         r_williams(-80),  X("bars", bars=12)),
    ("CCI -100 반등",             r_cci(-100),      X("bars", bars=12)),
    # ── 볼린저
    ("볼린저 하단 → 상단",          r_boll_low(),     X("boll_up")),
    ("볼린저 하단 → 중단",          r_boll_low(),     X("boll_mid")),
    ("볼린저 하단 → 12봉",          r_boll_low(),     X("bars", bars=12)),
    ("볼린저 하단 3σ → 상단",       r_boll_low(k=3.), X("boll_up")),
    ("볼린저 상단돌파+거래량2배",     r_boll_break(),   X("bars", bars=12)),
    ("볼린저 스퀴즈 돌파",          r_squeeze(),      X("bars", bars=24)),
    # ── 돌파
    ("20봉 신고가 돌파",            r_high(20),       X("bars", bars=12)),
    ("50봉 신고가 돌파",            r_high(50),       X("bars", bars=24)),
    ("돈치안 20 돌파",             r_donchian(20),   X("bars", bars=24)),
    ("돈치안 20 돌파 → ATR 2배",    r_donchian(20),   X("atr_tp", mult=2.)),
    ("오프닝레인지 돌파",           r_orb(6),         X("bars", bars=12)),
    ("인사이드바 돌파",             r_inside_bar(),   X("bars", bars=12)),
    ("슈퍼트렌드 전환",             r_supertrend(),   X("bars", bars=24)),
    # ── 이평·MACD
    ("MA 5/20 골든크로스",          r_ma_cross(5, 20),  X("bars", bars=12)),
    ("MA 20/50 골든크로스",         r_ma_cross(20, 50), X("bars", bars=24)),
    ("가격이 20이평 상향돌파",       r_px_cross_ma(20),  X("bars", bars=12)),
    ("가격이 50이평 상향돌파",       r_px_cross_ma(50),  X("bars", bars=24)),
    ("MACD 골든크로스",             r_macd_cross(),     X("bars", bars=12)),
    ("MACD 히스토그램 전환",        r_macd_hist(),      X("bars", bars=12)),
    # ── 눌림목
    ("정배열 20선 눌림목",          r_pullback(20, 60), X("bars", bars=12)),
    ("정배열 20선 눌림목 → 볼린저",  r_pullback(20, 60), X("boll_up")),
    ("EMA20 눌림목 (50선 위)",      r_ema_pullback(),   X("bars", bars=12)),
    ("VWAP 되돌림 매수",            r_vwap_pullback(),  X("bars", bars=12)),
    ("VWAP 되돌림 → VWAP 청산",     r_vwap_pullback(),  X("vwap")),
    ("VWAP 상향돌파",               r_vwap_reclaim(),   X("bars", bars=12)),
    # ── 거래량
    ("거래량 3배 + 양봉",           r_vol_spike(3.),    X("bars", bars=12)),
    ("거래량 5배 + 양봉",           r_vol_spike(5.),    X("bars", bars=12)),
    ("거래량 3배 + 음봉 (역발상)",   r_vol_spike(3., False), X("bars", bars=12)),
    ("거래량 고갈 + 양봉",          r_vol_dryup(),      X("bars", bars=12)),
    # ── 캔들패턴
    ("망치형 (아래꼬리 2배)",        r_hammer(2.),       X("bars", bars=12)),
    ("망치형 (아래꼬리 3배)",        r_hammer(3.),       X("bars", bars=12)),
    ("상승 장악형",                 r_engulf(),         X("bars", bars=12)),
    ("적삼병",                     r_three_soldiers(), X("bars", bars=12)),
    ("3연속 음봉 뒤 반등",          r_n_red(3),         X("bars", bars=12)),
    ("5연속 음봉 뒤 반등",          r_n_red(5),         X("bars", bars=12)),
    ("갭하락 메우기",               r_gap_fill(),       X("bars", bars=12)),
    ("모멘텀 ROC 5% 돌파",          r_roc(10, 5.),      X("bars", bars=12)),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h")
    a = ap.parse_args()

    D = {s: load(s, a.tf) for s in SYMS}
    D = {k: v for k, v in D.items() if v is not None}
    bars = sum(len(v) for v in D.values())
    span = (f"{min(v.dt.min() for v in D.values()):%Y-%m}"
            f" ~ {max(v.dt.max() for v in D.values()):%Y-%m}")

    print("=" * 112)
    print(f"  커뮤니티·유튜브 단타 전략 {len(RULES)}종 — {a.tf} · {len(D)}종 · {bars:,}봉 · {span}")
    print("=" * 112)

    bl = pd.concat([baseline(d, 12) for d in D.values()])
    blg = bl.gross.mean()
    print(f"  기준선: 같은 구간 무작위 진입 12봉 보유 → 총수익 {blg:+.3f}%"
          f" (표본 {len(bl):,})\n")
    print(f"  {'규칙':<28s}{'거래':>7s}{'총수익%':>9s}{'승률':>6s}{'보유':>6s}"
          f"{'기준대비':>9s}  |{'순수익% (수수료별)':>34s}")
    print(f"  {'':<28s}{'':>7s}{'':>9s}{'':>6s}{'':>6s}{'':>9s}  |"
          + "".join(f"{f'{f:.2f}%':>8s}" for f in FEES))
    print("  " + "-" * 108)

    rows = []
    for name, ent, ext in RULES:
        parts = [backtest(d, ent(d), ext) for d in D.values()]
        parts = [p for p in parts if len(p)]
        if not parts:
            print(f"  {name:<28s}{'신호 없음':>7s}")
            continue
        t = pd.concat(parts)
        ho = t[t.dt >= TEST_START]
        nets = [t.gross.mean() - f for f in FEES]
        hnets = [ho.gross.mean() - f for f in FEES] if len(ho) else [np.nan]*len(FEES)
        mark = ""
        if nets[-1] > 0 and hnets[-1] > 0:
            mark = "  ✅"
        print(f"  {name:<28s}{len(t):>7,d}{t.gross.mean():>9.3f}"
              f"{(t.gross>0).mean()*100:>5.0f}%{t.bars.mean():>6.1f}"
              f"{t.gross.mean()-blg:>+9.3f}  |"
              + "".join(f"{v:>8.3f}" for v in nets) + mark)
        rows.append({"name": name, "g": t.gross.mean(), "ho": ho.gross.mean() if len(ho) else np.nan,
                     "n": len(t), "nets": nets, "hnets": hnets})

    G = pd.DataFrame(rows)
    print("\n" + "=" * 112)
    print("  요약")
    print("=" * 112)
    print(f"  시험한 규칙                      {len(G)}개")
    print(f"  총수익이 무작위 진입보다 나은 것    {(G.g > blg).sum()}개")
    for i, f in enumerate(FEES):
        alive = G[(G.nets.apply(lambda x: x[i]) > 0) & (G.hnets.apply(lambda x: x[i]) > 0)]
        print(f"  수수료 {f:.2f}% 에서 살아남는 것     {len(alive)}개"
              + (f"  → {', '.join(alive.name.head(6))}" if len(alive) else ""))


if __name__ == "__main__":
    main()


# ── 결과 (2026-09) ──────────────────────────────────────────────
#
# 1시간봉 6종 430,252봉 · 2017-08~2026-07 · 44개 규칙
#
#   수수료          살아남는 규칙 (학습·홀드아웃 둘 다 양수)
#   0.04% 메이커     19개
#   0.10%           9개
#   0.20%           3개
#   0.40% 테이커     1개  ← 모멘텀 ROC 5% 돌파뿐
#
# 총수익(수수료 0)으로 무작위 진입을 이긴 것은 44개 중 15개다.
# 신호에 정보가 있는 것은 맞다. 다만 엣지가 대부분 0.05~0.4%p이고
# 테이커 왕복이 0.40%라 그 자리에서 없어진다.
#
# 유일 생존자를 파보니 — 이미 기각한 것의 재발견이었다
#
# 문턱값은 단조로웠다(3%→-0.10, 5%→0.09, 8%→0.39, 10%→0.89, 홀드아웃도
# 같은 방향). 과최적화 징후가 아니라 진짜 신호로 보였다. 그런데
# **같은 시기 무작위 진입**과 비교하니 엣지의 대부분이 국면 편향이었다
# (규칙 0.493% vs 같은 시기 무작위 0.377%, 순엣지 0.116%p < 수수료).
#
# 문턱을 10%로 올리면 순엣지가 수수료를 넘는다. 42종 일봉으로 표본을
# 키워 24조합을 돌리니 10개가 학습·홀드아웃 둘 다 0.40%를 넘었다.
# 가장 센 조합(10일 ROC >50% · 10일 보유)을 뜯어보면:
#
#   385건 · 거래당 +16.94% · 중앙값 +3.90% · 승률 55%
#   최악 -55.5% · 최악 역행 -70.1% · 하위 5% 평균 -29.9%
#   국면별: 급등 276건 +21.15% / 폭락 25건 +13.01% /
#           횡보 16건 +0.18% / 상승 37건 +1.47%
#
# 이미 기각한 ml/bull_breakout.py 와 나란히 놓으면 같은 물건이다.
#
#                   건수   거래당%   중앙%   승률    최악%
#   ROC >50%        385   16.94    3.90   55%   -55.5
#   신고가 돌파       450   30.04    5.56   56%   -67.5   ← 기각됨
#   과매도 롱       1,821    6.59    7.77   82%   -50.1   ← 채택
#
# 평균은 높은데 중앙값이 낮다(몇 건이 크게 터뜨린다). 승률 55%,
# 거래의 72%가 급등장에 몰린다. 자본 보존과 승률을 앞에 두면
# 신고가 돌파를 뺀 것과 같은 이유로 이것도 빠진다.
#
# 누적: 644개 넘게 시험했고 통과 목록은 그대로다 —
#       과매도 롱 · 주봉 숏 · 상승 다이버전스.
#
# 참고: 슈퍼트렌드(1건)와 갭하락 메우기(43건)는 신호가 거의 안 났다.
#       코인은 24시간 시장이라 갭이 사실상 없고, 슈퍼트렌드 규칙은
#       하단 교차 조건이 거의 성립하지 않았다. 둘 다 결론에서 뺀다.
