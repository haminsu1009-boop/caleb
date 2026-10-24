"""
ml/oversold_strategy.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
과매도 반등 전략 — candle_edge.py에서 발견한 우위의 실전 검증

발견 내용 (46종 풀링, 학습 2017~2023 / 홀드아웃 2024~2026):
    "종가가 20일선 대비 -14% 이하" 조건에서 N봉 후 수익이
    시장 평균을 유의하게 상회했다.

        보유  1봉: 홀드아웃 우위 +0.693%  승률 53.3% (CI 51.6~55.0)
        보유  3봉: +1.745%  58.3% (56.7~60.0)
        보유  5봉: +2.115%  60.3% (58.6~62.0)   ← 정점
        보유 10봉: +1.856%  56.1% (54.4~57.8)
        보유 20봉: 우위 소멸

    이 세션 초반에 "RSI 과매도 반등 = 원금 -100%"라고 결론냈던 것과
    모순돼 보이지만 원인은 보유기간이다. 당시 구현은 "RSI가 70을 넘을
    때까지 보유"라 수 주~수 개월을 들고 갔고, 위 표대로 우위는 20봉
    시점에 이미 사라진다. 짧게 끊어야 존재하는 우위였다.

이 스크립트가 검증하는 것:
    1. 실제 거래로 만들었을 때 비용(왕복 0.2%) 차감 후에도 남는가
    2. 진입 조건을 조합(RSI + 이격도)하면 개선되는가
    3. 강세장에서만 되는 "눌림목 매수" 착시가 아닌가 — 약세장 분리 검증
    4. 특정 종목에만 쏠린 결과가 아닌가 — 종목별 일관성

사용법:
    python ml/oversold_strategy.py
    python ml/oversold_strategy.py --hold 5 --threshold -14
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, glob, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ROUND_TRIP = 0.002
TRAIN_END = "2024-01-01"

BULL = [("2018-12-15", "2021-11-10"), ("2022-11-21", "2025-10-06")]
BEAR = [("2017-12-17", "2018-12-15"), ("2021-11-10", "2022-11-21"),
        ("2025-10-06", "2026-12-31")]


def load_all(interval: str) -> pd.DataFrame:
    frames = []
    for f in sorted(glob.glob(f"data/*_{interval}_all.csv.gz")):
        sym = os.path.basename(f).split(f"_{interval}_")[0]
        if not sym.endswith("USDT"):
            continue
        try:
            d = pd.read_csv(f, compression="gzip")
        except Exception:
            continue
        tc = "timestamp" if "timestamp" in d.columns else "datetime"
        d[tc] = pd.to_datetime(d[tc], format="mixed", errors="coerce")
        d = d.dropna(subset=[tc]).sort_values(tc).drop_duplicates(tc)
        if len(d) < 300:
            continue
        d = d.rename(columns={tc: "datetime"})
        d["symbol"] = sym
        frames.append(d[["datetime", "symbol", "open", "high", "low", "close"]])
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def build(d: pd.DataFrame, hold: int) -> pd.DataFrame:
    out = []
    for sym, g in d.groupby("symbol", sort=False):
        g = g.sort_values("datetime").reset_index(drop=True)
        c = g["close"]
        g["vs_ma20"] = (c / c.rolling(20).mean() - 1) * 100
        delta = c.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        g["rsi14"] = 100 - 100 / (1 + gain / (loss + 1e-12))
        # 진입은 다음 봉 시가 체결, 청산은 hold봉 뒤 시가 — 미래참조 없음
        g["entry"] = g["open"].shift(-1)
        g["exit"] = g["open"].shift(-1 - hold)
        g["trade_ret"] = (g["exit"] / g["entry"] - 1) * 100 - ROUND_TRIP * 100
        out.append(g)
    return pd.concat(out, ignore_index=True)


def wilson(w: int, n: int, z: float = 1.96) -> tuple:
    if n == 0: return 0.0, 0.0
    p = w / n; den = 1 + z*z/n; ctr = p + z*z/(2*n)
    mar = z * np.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return (ctr-mar)/den*100, (ctr+mar)/den*100


def seg_mask(dt: pd.Series, segs) -> np.ndarray:
    idx = pd.DatetimeIndex(dt)
    m = np.zeros(len(idx), dtype=bool)
    for lo, hi in segs:
        m |= np.asarray((idx >= lo) & (idx <= hi))
    return m


def report(sub: pd.DataFrame, label: str, indent: str = "  "):
    t = sub["trade_ret"].dropna()
    if len(t) < 20:
        print(f"{indent}{label:34s} 표본부족 (n={len(t)})")
        return None
    w = int((t > 0).sum())
    lo, hi = wilson(w, len(t))
    print(f"{indent}{label:34s} n={len(t):>6,}  승률 {w/len(t)*100:>5.1f}% "
          f"(CI {lo:.1f}~{hi:.1f})  거래당평균 {t.mean():>+6.3f}%  총합 {t.sum():>+9.1f}%")
    return {"n": len(t), "wr": w/len(t)*100, "lo": lo, "mean": t.mean()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1d")
    ap.add_argument("--hold", type=int, default=5)
    ap.add_argument("--threshold", type=float, default=-14.0)
    a = ap.parse_args()

    print("=" * 104)
    print(f"  과매도 반등 전략 검증 — {a.interval}, 20일선 대비 {a.threshold}% 이하 진입, {a.hold}봉 보유")
    print(f"  비용 왕복 {ROUND_TRIP*100:.1f}% 차감 · 진입/청산 모두 다음봉 시가")
    print("=" * 104)

    raw = load_all(a.interval)
    df = build(raw, a.hold)
    print(f"\n  {raw['symbol'].nunique()}종목 × {len(raw):,}봉")

    cond = df["vs_ma20"] <= a.threshold
    tr = df["datetime"] < TRAIN_END
    ho = ~tr

    print(f"\n[1] 기본 조건: 20일선 대비 {a.threshold}% 이하")
    report(df[cond & tr], "학습 2017~2023")
    r_base = report(df[cond & ho], "홀드아웃 2024~2026 ★")
    print()
    report(df[~cond & ho], "(대조군) 조건 미충족 구간")
    report(df[ho], "(대조군) 전체 무조건 진입")

    print(f"\n[2] 조건 조합 — RSI를 추가하면 개선되는가")
    for rsi_th in [35, 30, 25, 20]:
        c2 = cond & (df["rsi14"] <= rsi_th)
        report(df[c2 & ho], f"+ RSI <= {rsi_th}")

    print(f"\n[3] 이격도 임계값 민감도 — 한 값만 튀는가")
    for th in [-8, -10, -12, -14, -16, -20, -25]:
        c3 = df["vs_ma20"] <= th
        report(df[c3 & ho], f"20일선 대비 {th}% 이하")

    print(f"\n[4] 강세장 / 약세장 분리 — 눌림목 착시인가")
    bull_m = seg_mask(df["datetime"], BULL)
    bear_m = seg_mask(df["datetime"], BEAR)
    report(df[cond & bull_m], "강세 사이클")
    report(df[cond & bear_m], "약세 사이클 ★")

    print(f"\n[5] 종목별 일관성 (홀드아웃, n>=30인 종목만)")
    rows = []
    for sym, g in df[cond & ho].groupby("symbol"):
        t = g["trade_ret"].dropna()
        if len(t) < 30:
            continue
        w = int((t > 0).sum())
        rows.append({"symbol": sym, "n": len(t), "wr": w/len(t)*100, "mean": t.mean()})
    if rows:
        r = pd.DataFrame(rows).sort_values("mean", ascending=False)
        pos = int((r["mean"] > 0).sum())
        print(f"     {pos}/{len(r)}종목이 평균 플러스   "
              f"승률 중앙값 {r['wr'].median():.1f}%   거래당평균 중앙값 {r['mean'].median():+.3f}%")
        print(f"\n     {'심볼':12s}{'n':>7s}{'승률':>8s}{'거래당평균':>12s}")
        print("     " + "-" * 40)
        for _, x in r.head(8).iterrows():
            print(f"     {x['symbol']:12s}{x['n']:>7.0f}{x['wr']:>7.1f}%{x['mean']:>11.3f}%")
        if len(r) > 8:
            print(f"     ... 외 {len(r)-8}종목")
        for _, x in r.tail(3).iterrows():
            print(f"     {x['symbol']:12s}{x['n']:>7.0f}{x['wr']:>7.1f}%{x['mean']:>11.3f}%")


if __name__ == "__main__":
    main()
