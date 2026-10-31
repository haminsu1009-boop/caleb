"""
ml/rsi_divergence_short.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RSI · 다이버전스 · 숏 — 세 가지 미검증 항목

이 세션에서 지금까지 검증한 것은 전부 "이동평균 대비 과매도 롱"
하나의 변형이었다. 다음 셋은 한 번도 안 봤다.

  ① RSI 과매도/과매수 진입
     지금 규칙은 이동평균 이격도로 과매도를 잰다. RSI는 다른 방식으로
     같은 것을 재는데, 둘이 같은 신호인지 다른 신호인지 모른다.

  ② 다이버전스
     상승(강세) — 가격은 저점을 낮추는데 RSI는 저점을 높인다 → 매수
     하락(약세) — 가격은 고점을 높이는데 RSI는 고점을 낮춘다 → 매도/숏
     차트 분석에서 가장 널리 쓰이는 신호 중 하나인데 검증한 적이 없다.

  ③ 숏
     strategy.py의 SIDE는 "Buy" 고정이다. 롱만 본 이유가 검증된 게
     아니라 처음부터 그렇게 짜여 있었을 뿐이다. 암호화폐가 장기
     우상향이라 롱이 유리하다는 건 맞지만, 2022년 같은 해에는
     숏이 있었어야 할 수도 있다.

판정 기준은 앞선 분석과 같다.
  · 복리, 배율 2배, 거래당 5%, 총노출 80%
  · 왕복 0.40% (실측 체결지연 포함)
  · 강제청산은 보유 중 최저가(롱)/최고가(숏)로 판정
  · 학습 2017~2023 / 홀드아웃 2024~ 분리
  · 기준선은 현재 규칙(이동평균 -12.26% 롱)

숏은 손익 계산이 롱과 다르다는 점에 주의한다. 가격이 x% 오르면
숏은 x% 손실이고, 청산선도 위쪽에 생긴다. 그리고 무기한 선물에서
숏은 펀딩비를 대체로 *받는* 쪽이지만, 여기서는 보수적으로 롱과
같은 비용을 물린다(펀딩비 방향은 시기마다 뒤집힌다).
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
from ml.backtest_current_bot import load, ROUND_TRIP, FUNDING_PER_8H, BAR_HOURS

TRAIN_END = pd.Timestamp("2024-01-01")
LEV, PT, MG = 2.0, 0.05, 0.8
CB, COOL = 0.25, 30
HOLD = S.HOLD_BARS          # 20봉 — 기준선과 같게 둔다
STOP = S.STOP_PCT           # -40%


def rsi(c: np.ndarray, n: int = 14) -> np.ndarray:
    """와일더 RSI. 표준 정의 그대로."""
    d = np.diff(c, prepend=c[0])
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    au = pd.Series(up).ewm(alpha=1/n, adjust=False).mean().values
    ad = pd.Series(dn).ewm(alpha=1/n, adjust=False).mean().values
    rs = np.divide(au, ad, out=np.full_like(au, np.inf), where=ad > 0)
    out = 100 - 100 / (1 + rs)
    out[:n] = np.nan
    return out


def pivots(x: np.ndarray, k: int = 5):
    """좌우 k봉보다 낮은(높은) 지점 = 스윙 저점(고점).

    확정은 k봉 뒤에야 되므로, 신호를 쓸 때 그 지연을 반드시 반영한다.
    """
    n = len(x)
    lo = np.zeros(n, bool)
    hi = np.zeros(n, bool)
    for i in range(k, n - k):
        w = x[i - k:i + k + 1]
        if x[i] == w.min() and (w == x[i]).sum() == 1:
            lo[i] = True
        if x[i] == w.max() and (w == x[i]).sum() == 1:
            hi[i] = True
    return lo, hi


# ── 신호 생성기 ─────────────────────────────────────────
def sig_ma_long(c, h, l, o, thresh=S.ENTRY_THRESH):
    ma = pd.Series(c).rolling(S.MA_PERIOD).mean().values
    return np.where((c / ma - 1) * 100 <= thresh)[0]


def sig_ma_short(c, h, l, o, thresh=12.26):
    ma = pd.Series(c).rolling(S.MA_PERIOD).mean().values
    return np.where((c / ma - 1) * 100 >= thresh)[0]


def sig_rsi_long(c, h, l, o, period=14, level=30):
    r = rsi(c, period)
    ok = (r <= level) & ~np.isnan(r)
    # 구간 내내 참이면 매 봉 신호가 된다 — 아래로 처음 뚫은 봉만 쓴다
    return np.where(ok & ~np.r_[False, ok[:-1]])[0]


def sig_rsi_short(c, h, l, o, period=14, level=70):
    r = rsi(c, period)
    ok = (r >= level) & ~np.isnan(r)
    return np.where(ok & ~np.r_[False, ok[:-1]])[0]


def sig_div(c, h, l, o, bullish=True, period=14, k=5, max_gap=60):
    """다이버전스. 직전 스윙과 비교한다.

    강세: 가격 저점은 더 낮은데 RSI 저점은 더 높다
    약세: 가격 고점은 더 높은데 RSI 고점은 더 낮다

    스윙은 우측 k봉이 지나야 확정되므로, 신호 시점을 i+k 로 미룬다.
    이걸 빼먹으면 미래를 보는 백테스트가 된다.
    """
    r = rsi(c, period)
    src = l if bullish else h
    lo, hi = pivots(src, k)
    piv = np.where(lo if bullish else hi)[0]
    out = []
    for a, b in zip(piv[:-1], piv[1:]):
        if b - a > max_gap:
            continue
        if np.isnan(r[a]) or np.isnan(r[b]):
            continue
        if bullish:
            if src[b] < src[a] and r[b] > r[a]:
                out.append(b + k)
        else:
            if src[b] > src[a] and r[b] < r[a]:
                out.append(b + k)
    return np.array([i for i in out if i < len(c)], dtype=int)


# ── 거래 판정 ───────────────────────────────────────────
def resolve(sym, o, h, l, c, dt, i, n, is_long: bool):
    """신호봉 i에서 시작. 체결은 다음 봉 시가. HOLD봉 뒤 청산, 손절 -40%.

    분할매수는 기준선 규칙 고유의 장치라 여기서는 쓰지 않는다.
    비교 대상 전부에 같은 조건을 적용해야 신호 자체를 비교할 수 있다.
    """
    if i + 1 + HOLD >= n:
        return None
    e = o[i + 1]
    stop = e * (1 + STOP / 100) if is_long else e * (1 - STOP / 100)
    ex_bar = ex_px = None
    for bar in range(i + 1, i + 1 + HOLD):
        if is_long and l[bar] <= stop:
            ex_bar, ex_px = bar, stop; break
        if not is_long and h[bar] >= stop:
            ex_bar, ex_px = bar, stop; break
    if ex_bar is None:
        ex_bar, ex_px = i + 1 + HOLD, o[i + 1 + HOLD]
    seg_l, seg_h = l[i + 1:ex_bar + 1], h[i + 1:ex_bar + 1]
    # 최대 역행폭: 롱이면 저가, 숏이면 고가
    mae = ((seg_l.min() / e - 1) * 100 if is_long
           else (1 - seg_h.max() / e) * 100)
    return {"sym": sym, "dt": dt[i], "entry": e, "exit_px": ex_px,
            "bars": ex_bar - (i + 1), "long": is_long, "mae": mae}


def build(fn, is_long, **kw):
    trades = []
    for sym in S.SYMBOLS:
        g = load(sym)
        if g is None or len(g) < 300:
            continue
        o = g["open"].astype(float).values
        h = g["high"].astype(float).values
        l = g["low"].astype(float).values
        c = g["close"].astype(float).values
        dt = g["datetime"].values
        n = len(c)
        lock = -10**9
        for i in fn(c, h, l, o, **kw):
            if i <= lock:
                continue
            t = resolve(sym, o, h, l, c, dt, int(i), n, is_long)
            if t:
                lock = i + HOLD
                trades.append(t)
    return sorted(trades, key=lambda t: t["dt"])


def simulate(trades, lev=LEV, pt=PT, mg=MG):
    """복리·동시보유 한도·차단기. 롱/숏 손익 부호를 구분한다."""
    if len(trades) < 20:
        return None
    liq = 100.0 / lev - 0.5          # 역행 몇 %에서 청산되나
    cash = peak = 1.0
    mdd = 0.0
    open_ = []                        # (exit_dt, reserved, realized)
    halted = None
    n = wins = liqs = halts = 0
    for t in trades:
        now = t["dt"]
        keep = []
        for ex, res, pl in open_:
            if ex <= now:
                cash += pl
            else:
                keep.append((ex, res, pl))
        open_ = keep
        if cash <= 1e-6:
            return {"final": 0.0, "mdd": 1.0, "n": n, "wr": 0.0,
                    "liq": liqs, "halts": halts, "bust": True}
        peak = max(peak, cash)
        mdd = max(mdd, 1 - cash / peak)
        if halted is not None and now < halted:
            continue
        halted = None
        if 1 - cash / peak >= CB:
            halted = now + pd.Timedelta(days=COOL)
            halts += 1
            peak = cash
            continue
        margin = pt * cash
        notional = margin * lev
        if sum(r for _, r, _ in open_) + notional > mg * lev * cash:
            continue
        # 가격 수익률 → 포지션 수익률
        raw = (t["exit_px"] / t["entry"] - 1) * 100
        px = raw if t["long"] else -raw
        was_liq = t["mae"] <= -liq
        if was_liq:
            px = -liq
        fee = ROUND_TRIP + FUNDING_PER_8H * (t["bars"] * BAR_HOURS / 8.0)
        net = px - fee
        pl = max(margin * lev * net / 100, -margin)
        exit_dt = now + pd.Timedelta(hours=BAR_HOURS * (t["bars"] + 1))
        open_.append((np.datetime64(exit_dt), notional, pl))
        n += 1; wins += net > 0; liqs += was_liq
    for _, _, pl in open_:
        cash += pl
    return {"final": cash, "mdd": mdd, "n": n, "wr": wins / max(n, 1) * 100,
            "liq": liqs, "halts": halts, "bust": False}


def report(name, trades):
    tr = [t for t in trades if pd.Timestamp(t["dt"]) < TRAIN_END]
    ho = [t for t in trades if pd.Timestamp(t["dt"]) >= TRAIN_END]
    a, b, cft = simulate(tr), simulate(ho), simulate(trades)
    px = np.array([((t["exit_px"] / t["entry"] - 1) * 100
                    * (1 if t["long"] else -1)) - ROUND_TRIP for t in trades])
    return {"name": name, "sig": len(trades),
            "wr": (px > 0).mean() * 100 if len(px) else np.nan,
            "avg": px.mean() if len(px) else np.nan,
            "full": cft["final"] if cft else np.nan,
            "tr": a["final"] if a else np.nan,
            "ho": b["final"] if b else np.nan,
            "mdd": cft["mdd"] * 100 if cft else np.nan,
            "liq": cft["liq"] if cft else 0}


def main():
    ap = argparse.ArgumentParser()
    ap.parse_args()

    CASES = [
        ("기준선 · 이평 -12.26% 롱", sig_ma_long, True, {}),
        ("RSI(14) ≤ 30 롱",        sig_rsi_long, True, dict(period=14, level=30)),
        ("RSI(14) ≤ 25 롱",        sig_rsi_long, True, dict(period=14, level=25)),
        ("RSI(14) ≤ 20 롱",        sig_rsi_long, True, dict(period=14, level=20)),
        ("RSI(7)  ≤ 20 롱",        sig_rsi_long, True, dict(period=7, level=20)),
        ("RSI(21) ≤ 30 롱",        sig_rsi_long, True, dict(period=21, level=30)),
        ("상승 다이버전스 롱",         sig_div, True, dict(bullish=True, period=14, k=5)),
        ("상승 다이버전스 롱 (k=3)",   sig_div, True, dict(bullish=True, period=14, k=3)),
        ("이평 +12.26% 숏",         sig_ma_short, False, {}),
        ("이평 +15% 숏",           sig_ma_short, False, dict(thresh=15.0)),
        ("RSI(14) ≥ 70 숏",        sig_rsi_short, False, dict(period=14, level=70)),
        ("RSI(14) ≥ 75 숏",        sig_rsi_short, False, dict(period=14, level=75)),
        ("RSI(14) ≥ 80 숏",        sig_rsi_short, False, dict(period=14, level=80)),
        ("하락 다이버전스 숏",         sig_div, False, dict(bullish=False, period=14, k=5)),
        ("하락 다이버전스 숏 (k=3)",   sig_div, False, dict(bullish=False, period=14, k=3)),
    ]

    print("=" * 100)
    print("  RSI · 다이버전스 · 숏 — 바이낸스 42종 4시간봉, 2017~2026")
    print(f"  복리 · 배율 {LEV:g}배 · 거래당 {PT*100:g}% · 총노출 {MG*100:g}% · "
          f"왕복 {ROUND_TRIP}% · {HOLD}봉 보유 · 손절 {STOP}%")
    print("=" * 100)
    print(f"\n  {'신호':<26s}{'거래':>7s}{'승률':>8s}{'거래당':>9s}"
          f"{'전체':>10s}{'학습':>9s}{'홀드아웃':>10s}{'낙폭':>8s}{'청산':>6s}")
    print("  " + "-" * 94)
    rows = []
    for name, fn, is_long, kw in CASES:
        t = build(fn, is_long, **kw)
        if len(t) < 30:
            print(f"  {name:<26s}{len(t):>7d}   신호 부족")
            continue
        r = report(name, t)
        rows.append(r)
        print(f"  {name:<26s}{r['sig']:>7d}{r['wr']:>7.1f}%{r['avg']:>8.2f}%"
              f"{r['full']:>9.2f}배{r['tr']:>8.2f}배{r['ho']:>9.2f}배"
              f"{r['mdd']:>7.1f}%{r['liq']:>6d}")

    d = pd.DataFrame(rows)
    base = d.iloc[0]
    print(f"\n  ── 기준선(이평 -12.26% 롱) 대비")
    print(f"  {'신호':<26s}{'거래당 차이':>13s}{'전체':>10s}{'홀드아웃':>11s}")
    print("  " + "-" * 62)
    for _, x in d.iloc[1:].iterrows():
        print(f"  {x['name']:<26s}{x.avg-base.avg:>12.2f}%p"
              f"{x.full/base.full:>9.2f}배{x.ho/base.ho:>10.2f}배")

    win = d.iloc[1:][(d.iloc[1:].full > base.full) & (d.iloc[1:].ho > base.ho)]
    print(f"\n  ── 기준선을 전체·홀드아웃 양쪽에서 이긴 것: {len(win)} / {len(d)-1}")
    if len(win):
        for _, x in win.iterrows():
            print(f"     {x['name']}  전체 {x.full:.2f}배 · 홀드 {x.ho:.2f}배")
    else:
        print("     없다.")
    os.makedirs("ml/saved_models", exist_ok=True)
    d.to_csv("ml/saved_models/rsi_div_short.csv", index=False)
    print(f"\n  저장: ml/saved_models/rsi_div_short.csv")


if __name__ == "__main__":
    main()
