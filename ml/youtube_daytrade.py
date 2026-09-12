"""
ml/youtube_daytrade.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
유튜브·블로그에 도는 "단타 성공 전략"을 그대로 백테스트

검색해서 나온 규칙들을 손대지 않고 코드로 옮겼다. 파라미터를
우리 쪽에 유리하게 고르지 않았고, 각 규칙이 원문에서 말한 값을
그대로 쓰되 흔히 같이 쓰이는 값 몇 개를 같이 돌린다.

시험 대상(검색 결과에서 반복해서 나온 것들):
  · RSI 30 이하 매수 → 70 이상 매도          (가장 많이 나온 규칙)
  · 볼린저 하단 터치 매수 → 상단 매도
  · 볼린저 상단 돌파 + 거래량 급증 추격매수
  · 이동평균선 상향 돌파 매수
  · 정배열 + 눌림목
  · MACD 골든크로스
  · 스토캐스틱 RSI 과매도 반등
  · 3틱룰(진입 지연) 적용/미적용

판정 기준 두 가지를 나눠 본다.
  총수익  수수료 0. 신호에 엣지가 있기는 한가?
  순수익  왕복 0.40%(테이커 + 실측 체결지연). 실제로 남는가?

단타는 거래가 많아서 수수료가 전부를 결정한다. 총수익이 양수여도
순수익이 음수면 "맞는 말이지만 돈은 안 되는" 규칙이다. 그리고
같은 기간·같은 코인에서 무작위로 진입한 것과 비교해야 의미가
있다 — 상승장에서는 아무 때나 사도 오른다.

실행: python ml/youtube_daytrade.py [--tf 5m|1h] [--fee 0.40]
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
RNG = np.random.default_rng(11)


def load(sym, tf):
    p = f"data/{sym}_{tf}_all.csv.gz"
    if not os.path.exists(p):
        return None
    d = pd.read_csv(p)
    d["dt"] = pd.to_datetime(d["timestamp"], format="ISO8601")
    return d.dropna(subset=["close"]).reset_index(drop=True)


# ── 지표 ────────────────────────────────────────────────────────
def rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up = pd.Series(np.where(d > 0, d, 0.0)).ewm(alpha=1/n, adjust=False).mean()
    dn = pd.Series(np.where(d < 0, -d, 0.0)).ewm(alpha=1/n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).values


def boll(c, n=20, k=2.0):
    s = pd.Series(c)
    m, sd = s.rolling(n).mean(), s.rolling(n).std()
    return (m - k * sd).values, m.values, (m + k * sd).values


def macd(c, f=12, s=26, sig=9):
    x = pd.Series(c)
    line = x.ewm(span=f, adjust=False).mean() - x.ewm(span=s, adjust=False).mean()
    return line.values, line.ewm(span=sig, adjust=False).mean().values


def stoch_rsi(c, n=14, k=3):
    r = pd.Series(rsi(c, n))
    lo, hi = r.rolling(n).min(), r.rolling(n).max()
    return ((r - lo) / (hi - lo).replace(0, np.nan)).rolling(k).mean().values * 100


# ── 규칙: 인덱스 리스트를 돌려준다 (신호 확정 봉) ──────────────────
def r_rsi(d, lo=30):
    r = rsi(d["close"].values)
    return np.where((r < lo) & (np.roll(r, 1) >= lo))[0]

def r_boll_low(d, n=20, k=2.0):
    c = d["close"].values; lb, _, _ = boll(c, n, k)
    return np.where((c <= lb) & (np.roll(c, 1) > np.roll(lb, 1)))[0]

def r_boll_break(d, n=20, k=2.0, vmult=2.0):
    c, v = d["close"].values, d["volume"].values
    _, _, ub = boll(c, n, k)
    va = pd.Series(v).rolling(20).mean().values
    return np.where((c > ub) & (np.roll(c, 1) <= np.roll(ub, 1)) & (v > vmult * va))[0]

def r_ma_cross(d, n=20):
    c = d["close"].values; m = pd.Series(c).rolling(n).mean().values
    return np.where((c > m) & (np.roll(c, 1) <= np.roll(m, 1)))[0]

def r_pullback(d, a=5, b=20, cc=60):
    c = pd.Series(d["close"].values)
    ma, mb, mc = (c.rolling(a).mean(), c.rolling(b).mean(), c.rolling(cc).mean())
    aligned = (ma > mb) & (mb > mc)                    # 정배열
    dip = (c <= mb) & (c.shift(1) > mb.shift(1))       # 20선까지 눌림
    return np.where((aligned & dip).values)[0]

def r_macd(d):
    line, sig = macd(d["close"].values)
    return np.where((line > sig) & (np.roll(line, 1) <= np.roll(sig, 1)))[0]

def r_stochrsi(d, lo=20):
    s = stoch_rsi(d["close"].values)
    return np.where((s > lo) & (np.roll(s, 1) <= lo))[0]


# ── 청산 ────────────────────────────────────────────────────────
def exit_rsi(d, i, hi=70, cap=300):
    r = rsi(d["close"].values); n = len(r)
    for j in range(i + 1, min(i + cap, n)):
        if r[j] >= hi:
            return j
    return min(i + cap, n - 1)

def exit_boll_up(d, i, n=20, k=2.0, cap=300):
    c = d["close"].values; h = d["high"].values
    _, _, ub = boll(c, n, k); N = len(c)
    for j in range(i + 1, min(i + cap, N)):
        if not np.isnan(ub[j]) and h[j] >= ub[j]:
            return j
    return min(i + cap, N - 1)

def exit_bars(d, i, bars=12):
    return min(i + bars, len(d) - 1)


def backtest(d, entries, exit_fn, *, tick_delay=0, fee=0.40, stop=None):
    """판단은 종가, 체결은 다음 봉 시가. 중복 진입 없음."""
    o, c, h, l = (d["open"].values, d["close"].values,
                  d["high"].values, d["low"].values)
    dt = d["dt"].values; n = len(c)
    out = []; lock = -1
    for i in entries:
        e_bar = i + 1 + tick_delay
        if i <= lock or e_bar >= n - 1:
            continue
        ep = o[e_bar]
        j = exit_fn(d, e_bar)
        if j <= e_bar:
            j = min(e_bar + 1, n - 1)
        xp = c[j]
        mae = (l[e_bar:j + 1].min() / ep - 1) * 100
        if stop is not None and mae <= -stop:
            xp = ep * (1 - stop / 100)
        gross = (xp / ep - 1) * 100
        out.append({"dt": pd.Timestamp(dt[e_bar]), "gross": gross,
                    "net": gross - fee, "bars": j - e_bar, "mae": mae})
        lock = j
    return pd.DataFrame(out)


def random_baseline(d, n_trades, hold_bars, fee=0.40):
    """같은 구간에서 아무 때나 사서 같은 봉수만큼 들고 있기."""
    o, c = d["open"].values, d["close"].values
    N = len(c)
    if N - hold_bars - 2 < 100 or n_trades < 1:
        return pd.DataFrame()
    idx = RNG.choice(np.arange(100, N - hold_bars - 2),
                     size=min(n_trades * 5, N - hold_bars - 200), replace=False)
    dt = d["dt"].values
    return pd.DataFrame([{"dt": pd.Timestamp(dt[i]),
                          "gross": (c[i + hold_bars] / o[i] - 1) * 100,
                          "net": (c[i + hold_bars] / o[i] - 1) * 100 - fee}
                         for i in idx])


RULES = [
    ("RSI 30 매수 → 70 매도",        r_rsi,        lambda d, i: exit_rsi(d, i)),
    ("RSI 30 매수 → 12봉 보유",       r_rsi,        lambda d, i: exit_bars(d, i, 12)),
    ("볼린저 하단 매수 → 상단 매도",    r_boll_low,   lambda d, i: exit_boll_up(d, i)),
    ("볼린저 하단 매수 → 12봉",        r_boll_low,   lambda d, i: exit_bars(d, i, 12)),
    ("볼린저 상단돌파+거래량2배 추격",   r_boll_break, lambda d, i: exit_bars(d, i, 12)),
    ("20이평 상향돌파 매수 → 12봉",     r_ma_cross,   lambda d, i: exit_bars(d, i, 12)),
    ("정배열 눌림목(5>20>60) → 12봉",  r_pullback,   lambda d, i: exit_bars(d, i, 12)),
    ("정배열 눌림목 → 볼린저 상단",     r_pullback,   lambda d, i: exit_boll_up(d, i)),
    ("MACD 골든크로스 → 12봉",        r_macd,       lambda d, i: exit_bars(d, i, 12)),
    ("스토캐스틱RSI 20 반등 → 12봉",   r_stochrsi,   lambda d, i: exit_bars(d, i, 12)),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="5m", help="5m 또는 1h")
    ap.add_argument("--fee", type=float, default=0.40, help="왕복 수수료 %%")
    ap.add_argument("--stop", type=float, default=None, help="손절 %% (양수)")
    ap.add_argument("--delay", type=int, default=0, help="3틱룰: 진입 지연 봉수")
    a = ap.parse_args()

    D = {s: load(s, a.tf) for s in SYMS}
    D = {k: v for k, v in D.items() if v is not None}
    span = f"{min(v['dt'].min() for v in D.values()):%Y-%m} ~ {max(v['dt'].max() for v in D.values()):%Y-%m}"
    bars = sum(len(v) for v in D.values())

    print("=" * 104)
    print(f"  유튜브 단타 전략 백테스트 — {a.tf} · {len(D)}종 · {bars:,}봉 · {span}")
    print(f"  왕복 수수료 {a.fee}%" + (f" · 손절 -{a.stop}%" if a.stop else "")
          + (f" · 진입 {a.delay}봉 지연" if a.delay else ""))
    print("=" * 104)
    print(f"  {'규칙':<32s}{'거래':>7s}{'총수익%':>9s}{'순수익%':>9s}{'승률':>7s}"
          f"{'보유':>6s}  |{'홀드아웃 순수익%':>17s}{'승률':>7s}")
    print("  " + "-" * 100)

    rows = []
    for name, ent, ext in RULES:
        parts = []
        for s, d in D.items():
            t = backtest(d, ent(d), ext, tick_delay=a.delay, fee=a.fee, stop=a.stop)
            if len(t):
                parts.append(t)
        if not parts:
            print(f"  {name:<32s}{'신호 없음':>7s}"); continue
        t = pd.concat(parts)
        ho = t[t.dt >= TEST_START]
        mark = "  ✅" if t.net.mean() > 0 and len(ho) and ho.net.mean() > 0 else ""
        print(f"  {name:<32s}{len(t):>7,d}{t.gross.mean():>9.3f}{t.net.mean():>9.3f}"
              f"{(t.net>0).mean()*100:>6.0f}%{t.bars.mean():>6.1f}  |"
              f"{(ho.net.mean() if len(ho) else float('nan')):>17.3f}"
              f"{((ho.net>0).mean()*100 if len(ho) else float('nan')):>6.0f}%{mark}")
        rows.append((name, t))

    # 기준선 — 같은 코인·같은 보유봉수로 무작위 진입
    print("\n  ■ 기준선: 같은 구간에서 아무 때나 사서 12봉 보유")
    bl = pd.concat([random_baseline(d, 500, 12, a.fee) for d in D.values()])
    blho = bl[bl.dt >= TEST_START]
    print(f"  {'무작위 진입':<32s}{len(bl):>7,d}{bl.gross.mean():>9.3f}{bl.net.mean():>9.3f}"
          f"{(bl.net>0).mean()*100:>6.0f}%{12:>6.1f}  |{blho.net.mean():>17.3f}"
          f"{(blho.net>0).mean()*100:>6.0f}%")

    print(f"\n  ■ 수수료가 없다면 (총수익 기준) 이기는 규칙")
    win = [(n, t.gross.mean()) for n, t in rows if t.gross.mean() > bl.gross.mean()]
    if win:
        for n, g in sorted(win, key=lambda x: -x[1]):
            print(f"    {n:<34s}{g:>8.3f}%  (무작위 {bl.gross.mean():.3f}%)")
    else:
        print("    없음 — 수수료를 0으로 놓아도 무작위 진입을 못 이긴다")

    print(f"\n  ■ 수수료를 넣으면 (순수익 > 0) 살아남는 규칙")
    alive = [(n, t.net.mean()) for n, t in rows if t.net.mean() > 0]
    print("    " + (", ".join(f"{n} ({g:+.3f}%)" for n, g in alive) if alive else "없음"))


if __name__ == "__main__":
    main()
