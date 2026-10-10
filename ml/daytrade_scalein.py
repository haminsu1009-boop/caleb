"""
ml/daytrade_scalein.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
단타 전략에 분할매수를 붙이면 살아나는가

이 저장소는 이미 단타 전략 35종을 돌렸고 전부 탈락했다
(ml/youtube_daytrade.py · ml/community_strategies.py ·
 ml/wonyotti_patterns.py). RSI·볼린저·MACD·스토캐스틱·윌리엄스%R·
CCI·이평돌파·정배열눌림·스퀴즈·거래량패턴·신고가·꼬리·급등급락.

탈락 이유는 전략마다 다르지 않았다. 공통이었다 — **엣지 대비
수수료**다. 과매도 롱 규칙은 거래당 엣지가 수수료의 16배인데
단타 규칙들은 0.2~0.5배였다. 엣지보다 비용이 크면 승률이 몇 퍼센트든
결과는 마이너스다.

다만 그때는 전부 **단일 진입 + 고정 손익절**로만 쟀다. 분할매수를
걸어본 적이 없다. ml/hybrid_variants.py에서 3단 분할매수 + 분할매도가
승률을 81.9%에서 89.4%로 올리는 것을 확인했으므로, 그걸 단타 패턴에
붙이는 것은 아직 안 해본 실험이다.

여기서 새로 넣은 전략 (기존 35종에 없던 것)

    그리드 매매          -x%마다 사고 +x%마다 판다. 질문의 핵심이다.
    물타기(연속 음봉)     음봉이 이어질 때마다 추가 매수
    변동성 돌파          시가 + (전일고-전일저)×k. 래리 윌리엄스.
    VWAP 되돌림         VWAP 아래로 이탈했다가 회복
    VWAP 이탈 스캘핑     VWAP -2σ 터치
    ORB                 하루 첫 N봉의 고가 돌파
    슈퍼트렌드           ATR 기반 추세 전환
    EMA 9/21 크로스
    피벗 포인트 반등      전일 고저종으로 만든 S1 터치
    파라볼릭 SAR 전환
    ADX + DI 크로스
    하이킨아시 색 전환
    피보나치 0.618 되돌림
    유동성 스윕 + FVG     ICT/SMC. 직전 저점을 훑고 되돌아오면 진입.

각 전략을 두 가지로 돌린다.
    ① 원래 방식 — 단일 진입 + 고정 손익절(ATR 배수)
    ② 분할 방식 — 3단 분할매수 사다리 + 볼린저 분할매도

판정은 엣지/수수료 비율로 한다. 수수료는 바이빗 테이커 왕복
0.11%를 쓴다 — 실제로는 체결지연까지 더해 0.40%지만, 가장 너그러운
값으로도 못 이기면 현실에서는 확실히 못 이긴다.

━━━ 결론: 전부 탈락이다. 분할매수는 단타를 살리지 못한다 ━━━

국면 통제 기준선(같은 코인·같은 시기 ±30일·같은 청산, 진입만 무작위)
에서 6종이 통과하고 8종이 탈락했다. 탈락한 8종은 전부 p=1.000이다 —
무작위 진입이 항상 더 나았다. 그리고 전부 추세·모멘텀 추종이다.
통과한 6종은 전부 "떨어지면 산다" 계열이다.

    통과            초과      p       탈락          초과      p
    그리드 -2%    +0.45%  0.000    파라볼릭SAR  -0.09%  1.000
    VWAP -2σ     +0.37%  0.000    하이킨아시    -0.04%  1.000
    피벗 S1       +0.36%  0.000    VWAP 되돌림  -0.14%  1.000
    유동성스윕     +0.33%  0.000    ADX+DI      -0.25%  1.000
    피보나치0.618  +0.18%  0.000    EMA 9/21    -0.30%  1.000
    물타기        +0.07%  0.000    ORB         -0.29%  1.000
                                   변동성 돌파   -0.36%  1.000
                                   슈퍼트렌드    -0.40%  1.000

1위인 그리드조차 자본 단위에서는 진다.

    구성                        신호    체결    승률    최종  연복리   낙폭
    그리드 -2% (1h·6종)      10,241 10,040  74.6%  0.79배   -3%  24.5%
    과매도 롱 (4h·같은 6종)      259    259  84.6%  1.19배   +2%   7.5%
    과매도 롱 (4h·42종=봇)    1,815  1,663  83.0%  3.16배  +14%  36.2%
    둘 다                    12,056 10,975  75.4%  2.08배   +8%  41.6%

봇에 더하면 3.16배가 2.08배로 떨어진다.

거래당으로는 +0.81%인데 자본은 왜 주는가. 분할매수 사다리는 가격이
내려갈 때만 조각을 더 채우기 때문이다. 지는 거래에 이기는 거래의
2.03배가 실린다.

    그리드 -2% · 수수료 0.40%
        단순 평균        +0.807%
        투입 가중 평균    -0.047%
        이긴 거래 평균투입  0.400
        진 거래 평균투입   0.814

많이 이기고 조금 벌고, 적게 지고 크게 잃는다. 승률 74.6%가 그래서
아무 의미가 없다. stat()이 반드시 투입으로 가중하는 이유다.

이것이 단타 35종에 이어 49종이 같은 자리에서 떨어진 이유다. 분할매수는
승률을 올리지만 엣지를 만들지는 못한다. 엣지가 수수료보다 작으면
분할을 어떻게 걸어도 결과는 마이너스다.

사용법:
    python ml/daytrade_scalein.py --tf 1h
    python ml/daytrade_scalein.py --tf 5m --baseline
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
from ml.per_coin_rules import sim

SYMS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT"]
TE = pd.Timestamp("2024-01-01")
FEE = 0.11          # 바이빗 테이커 왕복. 실제는 체결지연 포함 0.40%.
RNG = np.random.default_rng(0)


def load_tf(sym, tf):
    f = f"data/{sym}_{tf}_all.csv.gz"
    if not os.path.exists(f):
        return None
    g = pd.read_csv(f)
    c0 = "datetime" if "datetime" in g.columns else g.columns[0]
    g[c0] = pd.to_datetime(g[c0], format="mixed")
    g = g.rename(columns={c0: "dt"}).sort_values("dt").reset_index(drop=True)
    return g


# ── 보조 지표 ────────────────────────────────────────────────────────
def atr(h, l, c, n=14):
    tr = np.maximum(h[1:] - l[1:],
                    np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    out = np.full(len(c), np.nan)
    out[1:] = pd.Series(tr).rolling(n).mean().values
    return out


def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().values


def rolling_vwap(c, h, l, v, n):
    tp = (h + l + c) / 3.0
    pv = pd.Series(tp * v).rolling(n).sum().values
    vv = pd.Series(v).rolling(n).sum().values
    return pv / np.where(vv == 0, np.nan, vv)


def supertrend(h, l, c, n=10, k=3.0):
    a = atr(h, l, c, n)
    mid = (h + l) / 2
    up, dn = mid + k * a, mid - k * a
    trend = np.ones(len(c))
    for i in range(1, len(c)):
        trend[i] = trend[i - 1]
        if c[i] > up[i - 1]:
            trend[i] = 1
        elif c[i] < dn[i - 1]:
            trend[i] = -1
    return trend


def psar(h, l, af0=0.02, step=0.02, mx=0.2):
    n = len(h)
    sar = np.zeros(n); bull = True
    af = af0; ep = h[0]; sar[0] = l[0]
    for i in range(1, n):
        sar[i] = sar[i - 1] + af * (ep - sar[i - 1])
        if bull:
            if l[i] < sar[i]:
                bull = False; sar[i] = ep; ep = l[i]; af = af0
            elif h[i] > ep:
                ep = h[i]; af = min(af + step, mx)
        else:
            if h[i] > sar[i]:
                bull = True; sar[i] = ep; ep = h[i]; af = af0
            elif l[i] < ep:
                ep = l[i]; af = min(af + step, mx)
    return sar


def adx_di(h, l, c, n=14):
    up = h[1:] - h[:-1]; dn = l[:-1] - l[1:]
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum(h[1:] - l[1:],
                    np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    atr_ = pd.Series(tr).rolling(n).mean().values
    pdi = 100 * pd.Series(pdm).rolling(n).mean().values / np.where(atr_ == 0, np.nan, atr_)
    ndi = 100 * pd.Series(ndm).rolling(n).mean().values / np.where(atr_ == 0, np.nan, atr_)
    P = np.full(len(c), np.nan); N = np.full(len(c), np.nan)
    P[1:] = pdi; N[1:] = ndi
    return P, N


def heikin(o, h, l, c):
    ha_c = (o + h + l + c) / 4
    ha_o = np.zeros(len(c)); ha_o[0] = (o[0] + c[0]) / 2
    for i in range(1, len(c)):
        ha_o[i] = (ha_o[i - 1] + ha_c[i - 1]) / 2
    return ha_o, ha_c


# ── 전략 — 각 함수는 "진입 봉 인덱스"를 돌려준다 ────────────────────
# 판단은 그 봉의 종가로 하고, 체결은 다음 봉 시가다(sim이 처리한다).
# 그 봉의 고가·저가를 조건에 쓰면 룩어헤드다 — 이 세션에서 그 버그
# 하나가 51.43배를 -0.018%로 만든 적이 있다.

def s_grid(d, pct=2.0):
    """그리드 — 직전 진입가 대비 -pct% 내려올 때마다 산다.
    질문의 핵심이다. 단타 분할매수의 대표 형태."""
    c = d["c"]; out = []; anchor = c[0]
    for i in range(1, len(c)):
        if c[i] <= anchor * (1 - pct / 100):
            out.append(i); anchor = c[i]
        elif c[i] >= anchor * (1 + pct / 100):
            anchor = c[i]
    return np.array(out)


def s_red_streak(d, k=2):
    """물타기 — 음봉이 k개 이어지면 산다. 5분봉 장대음봉 2개 기법."""
    o, c = d["o"], d["c"]
    red = (c < o).astype(int)
    run = pd.Series(red).rolling(k).sum().values
    return np.where(run >= k)[0]


def s_vol_breakout(d, k=0.5, span=24):
    """변동성 돌파 — 시가 + (직전 구간 고저폭)×k 를 넘으면 산다.
    래리 윌리엄스. span봉을 '전일'로 본다."""
    h, l, c, o = d["h"], d["l"], d["c"], d["o"]
    rng = (pd.Series(h).rolling(span).max() - pd.Series(l).rolling(span).min()).values
    ref = np.full(len(c), np.nan)
    ref[span:] = o[span:] + rng[span - 1:-1] * k
    return np.where(c > ref)[0]


def s_vwap_reclaim(d, n=24):
    """VWAP 되돌림 — 아래로 이탈했다가 회복하는 순간."""
    v = rolling_vwap(d["c"], d["h"], d["l"], d["v"], n)
    c = d["c"]
    below = c < v
    return np.where(~below[1:] & below[:-1])[0] + 1


def s_vwap_dev(d, n=24, k=2.0):
    """VWAP 이탈 스캘핑 — VWAP -kσ 아래로 내려가면 산다."""
    v = rolling_vwap(d["c"], d["h"], d["l"], d["v"], n)
    sd = pd.Series(d["c"]).rolling(n).std().values
    return np.where(d["c"] <= v - k * sd)[0]


def s_orb(d, n=6):
    """ORB — 하루 첫 n봉의 고가를 넘으면 산다. 암호화폐는 24시간이라
    UTC 0시를 '개장'으로 본다."""
    dt = pd.DatetimeIndex(d["dt"])
    day = dt.normalize()
    c, h = d["c"], d["h"]
    out = []
    start = 0
    for i in range(1, len(c)):
        if day[i] != day[i - 1]:
            start = i
        if i - start == n:
            hi = h[start:i].max()
            j = i
            while j < len(c) and day[j] == day[i]:
                if c[j] > hi:
                    out.append(j); break
                j += 1
    return np.array(out)


def s_supertrend(d):
    t = supertrend(d["h"], d["l"], d["c"])
    return np.where((t[1:] == 1) & (t[:-1] == -1))[0] + 1


def s_ema_cross(d, a=9, b=21):
    x, y = ema(d["c"], a), ema(d["c"], b)
    return np.where((x[1:] > y[1:]) & (x[:-1] <= y[:-1]))[0] + 1


def s_pivot_s1(d, span=24):
    """피벗 S1 터치 — 직전 구간 고저종으로 만든 지지선."""
    h, l, c = d["h"], d["l"], d["c"]
    ph = pd.Series(h).rolling(span).max().shift(1).values
    pl = pd.Series(l).rolling(span).min().shift(1).values
    pc = pd.Series(c).shift(1).values
    p = (ph + pl + pc) / 3
    s1 = 2 * p - ph
    return np.where(c <= s1)[0]


def s_psar_flip(d):
    s = psar(d["h"], d["l"]); c = d["c"]
    up = c > s
    return np.where(up[1:] & ~up[:-1])[0] + 1


def s_adx_di(d, th=25):
    P, N = adx_di(d["h"], d["l"], d["c"])
    cross = (P[1:] > N[1:]) & (P[:-1] <= N[:-1]) & (P[1:] > th)
    return np.where(cross)[0] + 1


def s_heikin(d):
    ho, hc = heikin(d["o"], d["h"], d["l"], d["c"])
    up = hc > ho
    return np.where(up[1:] & ~up[:-1])[0] + 1


def s_fib618(d, span=48):
    """피보나치 0.618 되돌림 — 구간 고점에서 61.8% 내려온 자리."""
    h, l, c = d["h"], d["l"], d["c"]
    hi = pd.Series(h).rolling(span).max().values
    lo = pd.Series(l).rolling(span).min().values
    lvl = hi - (hi - lo) * 0.618
    return np.where((c <= lvl) & (c > lo))[0]


def s_liq_sweep(d, span=24):
    """유동성 스윕 + FVG (ICT/SMC) — 직전 구간 저점을 저가로 훑었는데
    종가는 그 위로 돌아온 봉. 스톱을 털고 되돌아오는 자리다."""
    h, l, c = d["h"], d["l"], d["c"]
    prev_low = pd.Series(l).rolling(span).min().shift(1).values
    swept = (l < prev_low) & (c > prev_low)
    return np.where(swept)[0]


STRATS = [
    ("그리드 -2%",          s_grid),
    ("물타기 음봉2연속",      s_red_streak),
    ("변동성 돌파 k=0.5",    s_vol_breakout),
    ("VWAP 되돌림",         s_vwap_reclaim),
    ("VWAP -2σ 이탈",       s_vwap_dev),
    ("ORB 첫6봉 돌파",      s_orb),
    ("슈퍼트렌드 전환",       s_supertrend),
    ("EMA 9/21 크로스",     s_ema_cross),
    ("피벗 S1 터치",        s_pivot_s1),
    ("파라볼릭SAR 전환",     s_psar_flip),
    ("ADX+DI 크로스",       s_adx_di),
    ("하이킨아시 전환",       s_heikin),
    ("피보나치 0.618",      s_fib618),
    ("유동성스윕+FVG",      s_liq_sweep),
]


# ── 청산 방식 두 가지 ────────────────────────────────────────────────
def run_bracket(d, idx, tp_a=2.0, sl_a=1.0, max_bars=24):
    """① 원래 방식 — 단일 진입 + ATR 배수 손익절.

    체결은 다음 봉 시가. 조건 판단에 쓴 봉의 고저를 체결에 쓰지 않는다.
    한 봉 안에서 손절과 목표가 둘 다 닿으면 손절을 먼저 본다 —
    어느 쪽이 먼저였는지 봉 데이터로는 알 수 없고, 유리한 쪽을
    고르면 그게 곧 룩어헤드다.
    """
    o, h, l, c = d["o"], d["h"], d["l"], d["c"]
    a = atr(h, l, c)
    n = len(c); out = []
    lock = -10**9
    for i in idx:
        if i <= lock or i + 1 >= n or np.isnan(a[i]) or a[i] <= 0:
            continue
        e = o[i + 1]
        tp, sl = e + tp_a * a[i], e - sl_a * a[i]
        ex = None
        for b in range(i + 1, min(i + 1 + max_bars, n)):
            if l[b] <= sl:
                ex = (b, sl); break
            if h[b] >= tp:
                ex = (b, tp); break
        if ex is None:
            b = min(i + max_bars, n - 1); ex = (b, c[b])
        out.append(dict(dt=pd.Timestamp(d["dt"][i + 1]), entry=e,
                        exit_px=ex[1], bars=ex[0] - (i + 1)))
        lock = ex[0]
    return out


def run_ladder(d, idx, hold=24, step=1.5):
    """② 분할 방식 — 3단 분할매수 + 볼린저 분할매도.

    ml/hybrid_variants.py에서 승률을 81.9%→89.4%로 올린 그 구성이다.
    sim()을 그대로 쓴다 — 검증된 코드이고, entries를 주면 임계값 대신
    그 봉에서 진입한다.
    """
    return sim(d["o"], d["h"], d["l"], d["c"], d["dt"],
               20, -99.0, hold, [0.2, 0.3, 0.5],
               [(0.34, 1.0), (0.33, 1.5), (0.33, 2.0)],
               -40.0, sym=d["sym"], entries=np.asarray(idx), step=step)


def stat(trades, key_entry="entry", key_exit="exit_px", fee=None):
    """거래당 손익. **반드시 투입 자본으로 가중한다.**

    분할매수 사다리는 가격이 내려갈 때만 조각을 더 채운다. 그래서
    지는 거래에는 돈이 많이 실리고 이기는 거래에는 적게 실린다.
    실측으로 2.03배 차이다. 거래를 한 건씩 똑같이 세면 그게 통째로
    감춰진다 — 승률 74.6%, 단순평균 +0.81%인데 자본은 줄어든다.

        그리드 -2% · 수수료 0.40%
            단순 평균        +0.807%
            투입 가중 평균    -0.047%   ← 이쪽이 계좌에 일어나는 일

    mu는 가중값이다. mu_raw는 비교용으로만 남긴다.
    """
    f = FEE if fee is None else fee
    if not trades:
        return dict(n=0, wr=0.0, mu=0.0, mu_raw=0.0, edge=0.0, dep=0.0)
    r = np.array([(t[key_exit] / t[key_entry] - 1) * 100 for t in trades])
    dep = np.array([t.get("deployed", 1.0) for t in trades])
    net = r - f
    return dict(n=len(r), wr=float((net > 0).mean() * 100),
                mu=float(np.average(net, weights=dep)),
                mu_raw=float(net.mean()),
                edge=float(np.average(r, weights=dep)),
                dep=float(dep.mean()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h", help="5m · 1h")
    ap.add_argument("--baseline", action="store_true",
                    help="국면 통제 기준선도 돌린다 (느리다)")
    ap.add_argument("--reps", type=int, default=30)
    a = ap.parse_args()

    D = []
    for s in SYMS:
        g = load_tf(s, a.tf)
        if g is None or len(g) < 2000:
            continue
        D.append(dict(sym=s, dt=g["dt"].values,
                      o=g["open"].astype(float).values,
                      h=g["high"].astype(float).values,
                      l=g["low"].astype(float).values,
                      c=g["close"].astype(float).values,
                      v=g["volume"].astype(float).values))
    bars = sum(len(x["c"]) for x in D)
    print("=" * 112)
    print(f"  단타 전략 {len(STRATS)}종 × 청산 2방식 — {a.tf} · {len(D)}종 · {bars:,}봉")
    print(f"  수수료 왕복 {FEE}% (바이빗 테이커. 실제는 체결지연 포함 0.40%)")
    print("  ① 단일진입+ATR손익절   ② 3단 분할매수 + 볼린저 분할매도")
    print("=" * 112)
    print(f"\n  {'전략':<20s}{'① n':>8s}{'승률':>7s}{'거래당':>9s}{'엣지/수수료':>11s}"
          f"{'② n':>8s}{'승률':>7s}{'거래당':>9s}{'엣지/수수료':>11s}{'홀드아웃②':>11s}")
    print("  " + "-" * 110)

    rows = []
    for name, fn in STRATS:
        A, B = [], []
        for d in D:
            try:
                idx = fn(d)
            except Exception:
                continue
            if len(idx) == 0:
                continue
            A += run_bracket(d, idx)
            B += run_ladder(d, idx)
        sa = stat(A)
        sb = stat(B)
        ho = [t for t in B if pd.Timestamp(t["dt"]) >= TE]
        sh = stat(ho)
        ra = sa["edge"] / FEE if sa["n"] else 0.0
        rb = sb["edge"] / FEE if sb["n"] else 0.0
        rows.append((name, sa, sb, sh, ra, rb))
        print(f"  {name:<20s}{sa['n']:>8,}{sa['wr']:>6.1f}%{sa['mu']:>+8.2f}%{ra:>10.2f}배"
              f"{sb['n']:>8,}{sb['wr']:>6.1f}%{sb['mu']:>+8.2f}%{rb:>10.2f}배"
              f"{sh['mu']:>+10.2f}%")
        if sb["n"]:
            print(f"  {'':20s}{'':24s}{'(비가중 ' + f'{sb[chr(109)+chr(117)+chr(95)+chr(114)+chr(97)+chr(119)]:+.2f}' + '%)':>42s}")

    print("\n  엣지/수수료 = 수수료 빼기 전 거래당 수익 ÷ 왕복 수수료.")
    print("  1배 미만이면 수수료가 엣지보다 크다 — 승률이 몇이든 결과는 마이너스다.")
    print("  참고: 과매도 롱(4시간봉)은 이 비율이 16배다.")

    ok = [r for r in rows if r[5] >= 2.0 and r[2]["mu"] > 0 and r[3]["mu"] > 0]
    print(f"\n  1차 통과(분할 기준 엣지≥2배 · 전체·홀드아웃 둘 다 플러스): "
          f"{len(ok)}/{len(rows)}종" + (f" — {', '.join(r[0] for r in ok)}" if ok else ""))

    if a.baseline and ok:
        print("\n" + "=" * 112)
        print("  국면 통제 기준선 — 같은 코인·같은 시기(±30일)·같은 청산, 진입만 무작위")
        print("=" * 112)
        print(f"\n  {'전략':<20s}{'실제거래당':>11s}{'기준거래당':>11s}{'초과':>9s}{'p':>8s}{'판정':>8s}")
        print("  " + "-" * 70)
        W = 30 * (24 if a.tf == "1h" else 288)
        for name, fn in [(r[0], dict(STRATS)[r[0]]) for r in ok]:
            real = []
            sig = {}
            for d in D:
                idx = fn(d)
                sig[d["sym"]] = idx
                real += run_ladder(d, idx)
            rm = stat(real)["mu"]
            bs = []
            for _ in range(a.reps):
                bt = []
                for d in D:
                    s_ = sig[d["sym"]]
                    if len(s_) == 0:
                        continue
                    j = np.unique(np.clip(s_ + RNG.integers(-W, W + 1, len(s_)),
                                          25, len(d["c"]) - 30))
                    bt += run_ladder(d, j)
                if bt:
                    bs.append(stat(bt)["mu"])
            if not bs:
                continue
            bs = np.array(bs)
            p = float((bs >= rm).mean())
            print(f"  {name:<20s}{rm:>+10.2f}%{bs.mean():>+10.2f}%{rm-bs.mean():>+8.2f}%"
                  f"{p:>8.3f}{'통과' if p < 0.05 else '탈락':>8s}")
    print("=" * 112)


if __name__ == "__main__":
    main()
