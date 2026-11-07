"""
ml/short_setups.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
지정된 두 가지 숏 셋업 검증

A. 120일선 이탈 마감 + 연속 음봉
   일봉 종가가 120일 이동평균 아래로 마감하고, 그 뒤 N일 연속
   음봉으로 마감하면 계속 하락한다.

B. 가격-RSI 괴리 (베어리시 다이버전스, 임계 10포인트)
   가격은 고점을 높이는데 RSI는 직전 고점보다 10포인트 이상 낮고,
   그 다음 봉이 음봉이면 하락한다.

   문장이 두 가지로 읽혀서 둘 다 시험한다.
     B1  가격 신고가 + RSI가 직전 RSI 고점 대비 -10p 이상 + 다음봉 음봉
     B2  RSI 고점 찍은 뒤 다음봉이 음봉이고 RSI가 10p 이상 하락

■ 숏을 판정할 때 반드시 같이 봐야 하는 것

암호화폐는 장기 우상향이라 아무 때나 숏을 쳐도 지는 쪽이 기본이다.
그래서 "승률 45%"만 보면 규칙이 나쁜 건지 시장이 오르는 건지 알 수
없다. 같은 기간 **무작위 시점에 숏을 쳤을 때의 성적(기준선)** 을
함께 내서, 셋업이 그보다 나은지로 판정한다.

수수료는 왕복 0.40%(ml/fill_timing.py 실측 반영)를 뗀다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, glob, argparse, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from bot.oversold import strategy as S

FEE = 0.40          # % 왕복
TE = pd.Timestamp("2024-01-01")


def rsi(c: np.ndarray, n: int = 14) -> np.ndarray:
    d = np.diff(c, prepend=c[0])
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    au = pd.Series(up).ewm(alpha=1/n, adjust=False).mean().values
    ad = pd.Series(dn).ewm(alpha=1/n, adjust=False).mean().values
    rs = np.divide(au, ad, out=np.full_like(au, np.inf), where=ad > 0)
    out = 100 - 100 / (1 + rs)
    out[:n] = np.nan
    return out


def load_daily(sym):
    f = f"data/{sym}_1d_all.csv.gz"
    if not os.path.exists(f):
        return None
    d = pd.read_csv(f, compression="gzip")
    tc = "timestamp" if "timestamp" in d.columns else "datetime"
    d[tc] = pd.to_datetime(d[tc], format="mixed", errors="coerce")
    d = (d.dropna(subset=[tc]).sort_values(tc).drop_duplicates(tc)
           .rename(columns={tc: "dt"}).reset_index(drop=True))
    return d[["dt", "open", "high", "low", "close"]].astype(
        {"open": float, "high": float, "low": float, "close": float})


def to_weekly(d):
    x = d.set_index("dt")
    w = pd.DataFrame({
        "open": x["open"].resample("W-MON").first(),
        "high": x["high"].resample("W-MON").max(),
        "low": x["low"].resample("W-MON").min(),
        "close": x["close"].resample("W-MON").last(),
    }).dropna().reset_index().rename(columns={"dt": "dt"})
    return w


# ── 셋업 ────────────────────────────────────────────────
def setup_A(d, ma=120, streak=2):
    """종가가 MA 아래로 마감 + 그 뒤 streak개 연속 음봉 마감.

    '이탈 마감'은 그 봉에서 처음 아래로 내려간 것을 말한다. 이미
    한참 아래에 있는 상태는 이탈이 아니다. 그 뒤로 연속 음봉을 세고,
    streak개째 되는 봉의 종가에 판정한다(체결은 다음 봉 시가).
    """
    c = d["close"].values
    o = d["open"].values
    m = pd.Series(c).rolling(ma).mean().values
    below = c < m
    broke = below & ~np.r_[False, below[:-1]]      # 이탈 마감 봉
    bear = c < o
    sig = []
    n = len(c)
    for i in np.where(broke)[0]:
        # 이탈 봉 다음부터 연속 음봉을 센다
        k = 0
        j = i + 1
        while j < n and bear[j] and below[j]:
            k += 1
            if k == streak:
                sig.append(j)
                break
            j += 1
    return np.array(sig, dtype=int)


def setup_B1(d, period=14, k=5, gap=10.0, max_bars=90):
    """가격은 직전 스윙 고점을 넘겼는데 RSI는 그때보다 gap 이상 낮고,
    다음 봉이 음봉."""
    c, h, o = d["close"].values, d["high"].values, d["open"].values
    r = rsi(c, period)
    n = len(c)
    piv = []
    for i in range(k, n - k):
        w = h[i - k:i + k + 1]
        if h[i] == w.max() and (w == h[i]).sum() == 1:
            piv.append(i)
    bear = c < o
    sig = []
    for a, b in zip(piv[:-1], piv[1:]):
        if b - a > max_bars or np.isnan(r[a]) or np.isnan(r[b]):
            continue
        if h[b] > h[a] and (r[a] - r[b]) >= gap:
            # 스윙 확정은 우측 k봉 뒤다. 그 이후 첫 음봉에서 진입.
            j = b + k
            while j < n and not bear[j]:
                j += 1
                if j > b + k + 5:
                    break
            if j < n and bear[j]:
                sig.append(j)
    return np.array(sorted(set(sig)), dtype=int)


def setup_B2(d, period=14, gap=10.0, look=20):
    """RSI가 최근 look봉 최고를 찍은 뒤, 다음 봉이 음봉이면서
    RSI가 gap 이상 떨어진 경우."""
    c, o = d["close"].values, d["open"].values
    r = rsi(c, period)
    n = len(c)
    hi = pd.Series(r).rolling(look).max().values
    at_peak = (r >= hi - 1e-9) & ~np.isnan(r)
    bear = c < o
    sig = []
    for i in np.where(at_peak)[0]:
        j = i + 1
        if j < n and bear[j] and not np.isnan(r[j]) and (r[i] - r[j]) >= gap:
            sig.append(j)
    return np.array(sorted(set(sig)), dtype=int)


def setup_random(d, seed=0, rate=0.02):
    """기준선 — 아무 때나 숏. 같은 기간·같은 청산 규칙으로 비교한다."""
    rng = np.random.default_rng(seed)
    n = len(d)
    return np.where(rng.random(n) < rate)[0]


# ── 평가 ────────────────────────────────────────────────
def evaluate(d, idx, hold, stop_pct=None):
    """숏. 다음 봉 시가 진입, hold봉 뒤 종가 청산. stop_pct면 손절."""
    o = d["open"].values
    h = d["high"].values
    c = d["close"].values
    dt = d["dt"].values
    n = len(c)
    out = []
    lock = -10**9
    for i in idx:
        if i <= lock or i + 1 + hold >= n:
            continue
        e = o[i + 1]
        stop = e * (1 - stop_pct / 100) if stop_pct else None  # 숏은 위가 손절
        ex = None
        if stop_pct:
            up = e * (1 + stop_pct / 100)
            for b in range(i + 1, i + 1 + hold):
                if h[b] >= up:
                    ex = up
                    break
        if ex is None:
            ex = c[i + hold]
        ret = -(ex / e - 1) * 100 - FEE          # 숏이라 부호 반전
        out.append({"dt": pd.Timestamp(dt[i]), "ret": ret})
        lock = i + hold
    return pd.DataFrame(out)


def report(name, frames, hold):
    d = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if len(d) < 20:
        return {"name": name, "n": len(d)}
    tr = d[d.dt < TE]
    ho = d[d.dt >= TE]
    return {"name": name, "n": len(d), "wr": (d.ret > 0).mean() * 100,
            "avg": d.ret.mean(), "med": d.ret.median(),
            "tr_avg": tr.ret.mean() if len(tr) > 10 else np.nan,
            "ho_avg": ho.ret.mean() if len(ho) > 10 else np.nan,
            "ho_n": len(ho),
            "best": d.ret.max(), "worst": d.ret.min()}


def run(symbols, weekly, holds, label):
    data = {}
    for s in symbols:
        d = load_daily(s)
        if d is None or len(d) < 400:
            continue
        data[s] = to_weekly(d) if weekly else d
    if not data:
        print(f"\n  {label}: 데이터 없음")
        return
    unit = "주" if weekly else "일"
    ma = 120 if not weekly else 60          # 주봉 120주는 2.3년 — 60주로도 본다
    print(f"\n{'='*94}")
    print(f"  {label}  ({len(data)}종 · {unit}봉 · 수수료 왕복 {FEE}%)")
    print("=" * 94)
    print(f"\n  {'셋업':<34s}{'거래':>7s}{'승률':>8s}{'거래당':>9s}{'중앙':>8s}"
          f"{'학습':>9s}{'홀드아웃':>10s}")
    print("  " + "-" * 86)

    cases = []
    for st in (2, 3, 4):
        cases.append((f"A. MA{ma}{unit} 이탈 + {st}연속 음봉",
                      lambda d, st=st: setup_A(d, ma, st)))
    cases.append((f"B1. 가격↑ RSI -10p 괴리 + 음봉", setup_B1))
    cases.append((f"B2. RSI고점 후 음봉 + RSI -10p", setup_B2))
    cases.append((f"(기준선) 무작위 시점 숏", setup_random))

    for hold in holds:
        print(f"\n  ── {hold}{unit} 보유")
        for nm, fn in cases:
            frames = []
            for s, d in data.items():
                idx = fn(d)
                if len(idx):
                    r = evaluate(d, idx, hold)
                    if len(r):
                        frames.append(r)
            x = report(nm, frames, hold)
            if x.get("n", 0) < 20:
                print(f"  {nm:<34s}{x.get('n',0):>7d}   표본 부족")
                continue
            ho = f"{x['ho_avg']:+.2f}%" if x['ho_avg'] == x['ho_avg'] else "   —"
            tr = f"{x['tr_avg']:+.2f}%" if x['tr_avg'] == x['tr_avg'] else "   —"
            mark = "  ✅" if x["avg"] > 0 else ""
            print(f"  {nm:<34s}{x['n']:>7d}{x['wr']:>7.1f}%{x['avg']:>8.2f}%"
                  f"{x['med']:>7.2f}%{tr:>9s}{ho:>10s}{mark}")


def main():
    ap = argparse.ArgumentParser()
    ap.parse_args()
    syms = [s for s in S.SYMBOLS if os.path.exists(f"data/{s}_1d_all.csv.gz")]
    run(syms, False, [3, 5, 10, 20], "일봉 · 42종 전체")
    run(["BTCUSDT"], False, [3, 5, 10, 20], "일봉 · 비트코인만")
    run(["BTCUSDT"], True, [2, 4, 8], "주봉 · 비트코인만")
    run(syms, True, [2, 4, 8], "주봉 · 42종 전체")
    print(f"\n  ✅ = 거래당 수익률이 플러스 (수수료 차감 후)")
    print(f"  '기준선'보다 나아야 셋업에 정보가 있는 것이다.")


if __name__ == "__main__":
    main()
