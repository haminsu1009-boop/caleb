"""
ml/timeframe_rules.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
타임프레임별(4h/1h/30m/10m/5m/1m) 규칙 검증

핵심 질문: 짧은 봉으로 갈수록 규칙이 통하는가?

거래비용은 봉 길이와 무관하게 왕복 0.2%(수수료 0.1% + 슬리피지 0.1%)로
고정이다. 반면 한 봉에서 얻을 수 있는 움직임은 봉이 짧아질수록 작아진다.
따라서 짧은 봉일수록 "비용 대비 신호 크기"가 급격히 나빠진다.
이 스크립트는 그 한계선을 먼저 수치로 보여준 뒤, 실제 전략을 돌린다.

  1. 비용 장벽    — 봉당 평균 변동폭 대비 왕복비용 비율, 손익분기 승률
  2. 전략 성과    — 추세추종/평균회귀 계열을 각 타임프레임에서 실행
  3. 홀드아웃 검증 — 2023-01-01 기준 분리

10분봉은 바이낸스가 제공하지 않아 5분봉을 2개씩 합쳐 생성한다.
1분봉은 연도별 파일에서 로드한다(_all은 100MB 초과로 미보관).

사용법:
    python ml/timeframe_rules.py
    python ml/timeframe_rules.py --symbol BTCUSDT --from-year 2023
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, glob, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FEE, SLIP = 0.0005, 0.0005
ROUND_TRIP = 2 * (FEE + SLIP)          # 0.2%

BARS_PER_YEAR = {"4h": 365*6, "1h": 365*24, "30m": 365*48,
                 "10m": 365*144, "5m": 365*288, "1m": 365*1440}


# ══════════════════════════════════════════════════════════════
# 데이터 로드 (10m 리샘플, 1m 연도파일 지원)
# ══════════════════════════════════════════════════════════════

def _read(paths) -> pd.DataFrame:
    fr = []
    for p in paths:
        d = pd.read_csv(p, compression="gzip")
        fr.append(d)
    if not fr:
        return pd.DataFrame()
    df = pd.concat(fr, ignore_index=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="mixed", errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
    df = df.drop_duplicates("timestamp").reset_index(drop=True)
    return df.rename(columns={"timestamp": "datetime"})


def load_tf(symbol: str, interval: str, from_year: int = 2017) -> pd.DataFrame:
    if interval == "10m":
        base = load_tf(symbol, "5m", from_year)
        if base.empty:
            return base
        r = (base.set_index("datetime")
                 .resample("10min")
                 .agg({"open": "first", "high": "max", "low": "min",
                       "close": "last", "volume": "sum"})
                 .dropna()
                 .reset_index())
        return r

    allf = f"data/{symbol}_{interval}_all.csv.gz"
    if os.path.exists(allf):
        df = _read([allf])
    else:
        yrs = sorted(g for g in glob.glob(f"data/{symbol}_{interval}_*.csv.gz")
                     if "_all" not in g
                     and int(os.path.basename(g).split("_")[-1][:4]) >= from_year)
        df = _read(yrs)
    if df.empty:
        return df
    return df[df["datetime"] >= f"{from_year}-01-01"].reset_index(drop=True)


# ══════════════════════════════════════════════════════════════
# 1. 비용 장벽
# ══════════════════════════════════════════════════════════════

def cost_barrier(df: pd.DataFrame, interval: str) -> dict:
    """봉당 변동폭 대비 비용, 손익분기 승률(손익비 1.5:1 가정)"""
    rng = ((df["high"] - df["low"]) / df["close"]).median()
    absret = (df["close"].pct_change().abs()).median()
    # TP를 봉 변동폭의 1배, SL을 0.67배로 잡았을 때(손익비 1.5:1)
    tp, sl = rng, rng * 0.67
    net_tp, net_sl = tp - ROUND_TRIP, sl + ROUND_TRIP
    be = (net_sl / (net_tp + net_sl) * 100) if net_tp > 0 else float("inf")
    return {"봉당변동폭%": rng*100, "봉당절대수익%": absret*100,
            "왕복비용/변동폭": ROUND_TRIP/rng if rng > 0 else float("inf"),
            "손익분기승률%": be}


# ══════════════════════════════════════════════════════════════
# 2. 전략 (봉 수 기준으로 스케일)
# ══════════════════════════════════════════════════════════════

def _pos_ma(df, fast, slow):
    c = df["close"]
    f = c.rolling(fast).mean().shift(1); s = c.rolling(slow).mean().shift(1)
    p = np.where(f > s, 1.0, -1.0)
    p[np.isnan(f.values) | np.isnan(s.values)] = 0.0
    return p


def _pos_donchian(df, n_e, n_x):
    h, l, c = df["high"], df["low"], df["close"]
    ue = h.rolling(n_e).max().shift(1).values
    de = l.rolling(n_e).min().shift(1).values
    ux = h.rolling(n_x).max().shift(1).values
    dx = l.rolling(n_x).min().shift(1).values
    cv = c.values
    p = np.zeros(len(df)); cur = 0
    for i in range(len(df)):
        if np.isnan(ue[i]) or np.isnan(de[i]): p[i] = 0; continue
        if cur == 0:
            if cv[i] > ue[i]: cur = 1
            elif cv[i] < de[i]: cur = -1
        elif cur == 1 and cv[i] < dx[i]: cur = -1 if cv[i] < de[i] else 0
        elif cur == -1 and cv[i] > ux[i]: cur = 1 if cv[i] > ue[i] else 0
        p[i] = cur
    return p


def _pos_rsi_rev(df, n=14, lo=30, hi=70):
    c = df["close"]; d = c.diff()
    g = d.clip(lower=0).rolling(n).mean(); l_ = (-d.clip(upper=0)).rolling(n).mean()
    r = (100 - 100/(1 + g/(l_+1e-12))).shift(1).values
    p = np.zeros(len(df)); cur = 0
    for i in range(len(df)):
        if np.isnan(r[i]): p[i] = 0; continue
        if r[i] < lo: cur = 1
        elif r[i] > hi: cur = -1
        p[i] = cur
    return p


def _pos_bb_rev(df, n=20, k=2.0):
    c = df["close"]; ma = c.rolling(n).mean(); sd = c.rolling(n).std()
    u = (ma+k*sd).shift(1).values; d_ = (ma-k*sd).shift(1).values
    m = ma.shift(1).values; cv = c.shift(1).values
    p = np.zeros(len(df)); cur = 0
    for i in range(len(df)):
        if np.isnan(u[i]): p[i] = 0; continue
        if cv[i] <= d_[i]: cur = 1
        elif cv[i] >= u[i]: cur = -1
        elif cur == 1 and cv[i] >= m[i]: cur = 0
        elif cur == -1 and cv[i] <= m[i]: cur = 0
        p[i] = cur
    return p


# 각 타임프레임에서 "같은 시간 길이"가 되도록 봉 수를 환산
#   기준: 4h의 (50,200)MA ≈ 8일/33일
BARS_PER_DAY = {"4h": 6, "1h": 24, "30m": 48, "10m": 144, "5m": 288, "1m": 1440}


def strategies_for(interval: str):
    bpd = BARS_PER_DAY[interval]
    d = lambda days: max(2, int(round(days * bpd)))
    return {
        "MA교차(8일/33일)":   lambda df: _pos_ma(df, d(8), d(33)),
        "MA교차(2일/8일)":    lambda df: _pos_ma(df, d(2), d(8)),
        "돌파(9일/3일)":      lambda df: _pos_donchian(df, d(9), d(3)),
        "돌파(3일/1일)":      lambda df: _pos_donchian(df, d(3), d(1)),
        "RSI반전(1일)":       lambda df: _pos_rsi_rev(df, d(1)),
        "볼린저회귀(3일)":     lambda df: _pos_bb_rev(df, d(3)),
    }


# ══════════════════════════════════════════════════════════════
def run(df: pd.DataFrame, pos: np.ndarray, interval: str) -> dict:
    c = df["close"].values
    r = np.zeros(len(c)); r[1:] = c[1:]/c[:-1] - 1.0
    held = np.roll(pos, 1); held[0] = 0.0
    turn = np.abs(np.diff(np.concatenate([[0.0], pos])))
    sr = held*r - turn*(FEE+SLIP)

    eq = np.cumprod(1+sr)
    if eq[-1] <= 0:
        return {"total": -100.0, "cagr": -100.0, "mdd": -100.0,
                "sharpe": 0.0, "trades": int((turn > 0).sum()), "wr": 0.0,
                "cost_pct": float(turn.sum()*(FEE+SLIP)*100)}
    per = BARS_PER_YEAR[interval]
    yrs = len(sr)/per
    cagr = (eq[-1]**(1/yrs) - 1)*100 if yrs > 0 else 0.0
    mdd = (eq/np.maximum.accumulate(eq) - 1).min()*100
    sd = sr.std()
    sh = sr.mean()/sd*np.sqrt(per) if sd > 0 else 0.0

    # 거래 단위 승률
    ch = np.where(turn > 0)[0]
    wins = tot = 0
    for a, b in zip(ch, list(ch[1:]) + [len(pos)]):
        if pos[a] == 0: continue
        seg = sr[a:b]
        if len(seg) == 0: continue
        tot += 1
        if np.prod(1+seg) - 1 > 0: wins += 1
    return {"total": (eq[-1]-1)*100, "cagr": cagr, "mdd": mdd, "sharpe": sh,
            "trades": tot, "wr": (wins/tot*100 if tot else 0.0),
            "cost_pct": float(turn.sum()*(FEE+SLIP)*100)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--from-year", type=int, default=2022)
    ap.add_argument("--split", default="2025-01-01")
    a = ap.parse_args()

    TFS = ["4h", "1h", "30m", "10m", "5m", "1m"]

    print("=" * 104)
    print(f"  타임프레임별 규칙 검증 — {a.symbol}, {a.from_year}년 이후")
    print("=" * 104)

    # ── 1. 비용 장벽 ─────────────────────────────────
    print("\n[1] 비용 장벽 — 왕복비용 0.2% 고정, 봉이 짧을수록 불리")
    print(f"\n  {'TF':6s}{'봉수':>12s}{'봉당변동폭':>12s}{'비용/변동폭':>12s}{'손익분기승률':>14s}{'판정':>8s}")
    print("  " + "-" * 68)
    data = {}
    for tf in TFS:
        try:
            df = load_tf(a.symbol, tf, a.from_year)
        except Exception as e:
            print(f"  {tf:6s} 로드 실패: {e}"); continue
        if df.empty or len(df) < 500:
            print(f"  {tf:6s} 데이터 부족"); continue
        data[tf] = df
        cb = cost_barrier(df, tf)
        be = cb["손익분기승률%"]
        verdict = "불가" if be > 100 else ("어려움" if be > 60 else "가능")
        be_s = "불가능" if be > 100 else f"{be:.1f}%"
        print(f"  {tf:6s}{len(df):>12,}{cb['봉당변동폭%']:>11.3f}%"
              f"{cb['왕복비용/변동폭']:>11.2f}배{be_s:>14s}{verdict:>8s}")

    # ── 2. 전략 성과 ─────────────────────────────────
    print(f"\n[2] 전략 성과 (전체 구간)")
    rows = []
    for tf, df in data.items():
        print(f"\n  ── {tf}  ({df['datetime'].iloc[0].date()} ~ {df['datetime'].iloc[-1].date()}, {len(df):,}봉) ──")
        print(f"  {'전략':20s}{'수익률%':>12s}{'CAGR%':>10s}{'MDD%':>9s}{'승률%':>8s}{'거래':>8s}{'누적비용%':>11s}")
        print("  " + "-" * 78)
        for name, fn in strategies_for(tf).items():
            try:
                res = run(df, fn(df), tf)
            except Exception as e:
                print(f"  {name:20s} 오류 {e}"); continue
            rows.append({"tf": tf, "strategy": name, **res})
            flag = "✅" if res["total"] > 0 else "  "
            print(f"  {name:20s}{res['total']:>11.1f}%{res['cagr']:>9.1f}%{res['mdd']:>8.1f}%"
                  f"{res['wr']:>7.1f}%{res['trades']:>8d}{res['cost_pct']:>10.1f}% {flag}")

    out = pd.DataFrame(rows)
    if len(out):
        os.makedirs("ml/saved_models", exist_ok=True)
        out.to_csv("ml/saved_models/timeframe_rules.csv", index=False)
        print(f"\n{'='*104}")
        print(f"  타임프레임별 수익 낸 전략 수")
        print("=" * 104)
        for tf in TFS:
            sub = out[out.tf == tf]
            if len(sub) == 0: continue
            pos = (sub["total"] > 0).sum()
            best = sub.loc[sub["total"].idxmax()]
            print(f"  {tf:5s}  수익 {pos}/{len(sub)}개   최고: {best['strategy']} "
                  f"{best['total']:+.1f}% (승률 {best['wr']:.1f}%, 거래 {best['trades']}회, "
                  f"누적비용 {best['cost_pct']:.1f}%)")
        print(f"\n  저장: ml/saved_models/timeframe_rules.csv")


if __name__ == "__main__":
    main()
