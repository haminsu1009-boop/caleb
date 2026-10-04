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
# 봉마다 "이 조건을 만족하는 다음 봉"을 미리 한 번에 구해둔다.
# 5분봉 94만 개에 파이썬 루프를 돌리면 규칙 하나에 수 분이 걸린다.
def _next_true(cond, cap):
    """cond[j]가 True인 가장 이른 j>i 를 각 i에 대해. 없으면 -1.
    뒤에서 앞으로 한 번 훑으면 O(n)이다."""
    n = len(cond)
    nxt = np.full(n, -1, dtype=np.int64)
    ahead = -1
    for j in range(n - 1, -1, -1):
        nxt[j] = ahead
        if cond[j]:
            ahead = j
    # cap 초과는 없는 것으로 본다
    too_far = (nxt < 0) | (nxt - np.arange(n) > cap)
    nxt[too_far] = -1
    return nxt


def make_exit(kind, **kw):
    """데이터를 받아 '진입봉 → 청산봉' 배열을 돌려주는 함수를 만든다."""
    def build(d):
        c = d["close"].values; h = d["high"].values; n = len(c)
        idx = np.arange(n)
        if kind == "bars":
            return np.minimum(idx + kw.get("bars", 12), n - 1)
        cap = kw.get("cap", 300)
        if kind == "rsi":
            cond = rsi(c) >= kw.get("hi", 70)
        elif kind == "boll_up":
            _, _, ub = boll(c, kw.get("n", 20), kw.get("k", 2.0))
            cond = ~np.isnan(ub) & (h >= ub)
        else:
            raise ValueError(kind)
        nxt = _next_true(np.nan_to_num(cond).astype(bool), cap)
        # 조건을 못 만나면 cap 봉에서 시간청산
        return np.where(nxt >= 0, nxt, np.minimum(idx + cap, n - 1))
    return build


def backtest(d, entries, exit_build, *, tick_delay=0, fee=0.40, stop=None):
    """판단은 종가, 체결은 다음 봉 시가. 보유 중 재진입 없음."""
    o, c, l = d["open"].values, d["close"].values, d["low"].values
    dt = d["dt"].values; n = len(c)
    xmap = exit_build(d)
    # 보유 중 재진입 금지 — 청산봉을 넘긴 신호만 취한다
    keep_i, keep_j = [], []
    lock = -1
    for i in entries:
        e = i + 1 + tick_delay
        if i <= lock or e >= n - 1:
            continue
        j = max(int(xmap[e]), e + 1)
        keep_i.append(e); keep_j.append(min(j, n - 1))
        lock = j
    if not keep_i:
        return pd.DataFrame()
    e = np.array(keep_i); j = np.array(keep_j)
    ep, xp = o[e], c[j]
    mae = np.array([(l[a:b + 1].min() / p - 1) * 100 for a, b, p in zip(e, j, ep)])
    if stop is not None:
        xp = np.where(mae <= -stop, ep * (1 - stop / 100), xp)
    gross = (xp / ep - 1) * 100
    return pd.DataFrame({"dt": pd.to_datetime(dt[e]), "gross": gross,
                         "net": gross - fee, "bars": j - e, "mae": mae})


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
    ("RSI 30 매수 → 70 매도",        r_rsi,        make_exit("rsi")),
    ("RSI 30 매수 → 12봉 보유",       r_rsi,        make_exit("bars", bars=12)),
    ("볼린저 하단 매수 → 상단 매도",    r_boll_low,   make_exit("boll_up")),
    ("볼린저 하단 매수 → 12봉",        r_boll_low,   make_exit("bars", bars=12)),
    ("볼린저 상단돌파+거래량2배 추격",   r_boll_break, make_exit("bars", bars=12)),
    ("20이평 상향돌파 매수 → 12봉",     r_ma_cross,   make_exit("bars", bars=12)),
    ("정배열 눌림목(5>20>60) → 12봉",  r_pullback,   make_exit("bars", bars=12)),
    ("정배열 눌림목 → 볼린저 상단",     r_pullback,   make_exit("boll_up")),
    ("MACD 골든크로스 → 12봉",        r_macd,       make_exit("bars", bars=12)),
    ("스토캐스틱RSI 20 반등 → 12봉",   r_stochrsi,   make_exit("bars", bars=12)),
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


# ── 결과 (2026-09) ──────────────────────────────────────────────
#
# 1시간봉 6종 430,252봉 · 5분봉 6종 940,297봉 · 2017-08 ~ 2026-07
#
#   왕복 수수료          1시간봉 생존   5분봉 생존
#   0.40% (테이커·실측)      0/10        0/10
#   0.20%                  1/10         —
#   0.10%                  5/10         —
#   0.04% (메이커 양방향)     7/10        —
#
# 수수료가 전부를 결정한다. 규칙의 품질이 아니라 비용 구조의 문제다.
#
# 신호 자체는 정보가 있다. 5분봉에서 10개 중 7개가 무작위 진입을
# 총수익 기준으로 이긴다(무작위 0.009%). 다만 엣지가 0.006~0.090%
# 이고 테이커 왕복이 0.40%다 — 엣지의 4~65배다.
#
# 1시간봉에서 홀드아웃까지 통과하는 것은 넷이다. 전부 메이커
# 수수료를 전제로 한다.
#
#   볼린저 상단돌파+거래량2배   총 0.405%  홀드아웃 순 +0.152%
#   볼린저 하단 → 상단          총 0.129%  홀드아웃 순 +0.090%
#   정배열 눌림목               총 0.146%  홀드아웃 순 +0.035%
#   MACD 골든크로스            총 0.105%  홀드아웃 순 +0.024%
#
# 그런데 이 중 가장 센 "볼린저 상단 돌파 + 거래량 급증"은 메이커로
# 체결할 수 없는 규칙이다. 돌파를 쫓아가는 주문이라 본질적으로
# 테이커다. 지정가를 걸어두면 돌파가 안 온 경우에만 체결된다.
# 즉 0.04%를 가정한 +0.365%는 실현 불가능한 숫자다.
#
# 나머지 셋(볼린저 하단·눌림목·MACD)은 되돌림을 기다리는 진입이라
# 지정가가 가능하다. 대신 엣지가 0.024~0.090%로 작아서, 슬리피지가
# 조금만 생기거나 지정가가 안 채워지는 비율이 조금만 높아도 사라진다.
#
# 두 가지가 더 드러났다.
#
# 1. 승률과 수익은 다른 축이다. RSI 30→70은 1시간봉 승률 61%로
#    1등인데 총수익은 -0.027%로 꼴찌다. 이기면 조금 벌고 지면 크게
#    잃는다. 평균 130봉(5.5일)을 들고 있어 단타도 아니다.
#
# 2. 테이커 기준 1시간봉에서 무작위 진입(-0.285%)이 10개 중 7개를
#    이긴다. 지표를 보는 것이 안 보는 것보다 나쁘다.
#
# 우리 과매도 롱이 거래당 6.59%인 이유가 여기 있다. 4시간봉·20봉
# 보유라 연 204건이고 엣지가 수수료의 16배다. 단타에서 이기려면
# 엣지를 키우는 게 아니라 거래 횟수를 줄여야 한다.
