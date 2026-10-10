"""
ml/scale_in.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
분할매수 검증 — 평단을 낮추는가, 위험을 키우는가

이 규칙은 진입 후 저가가 중앙값 -7.1%까지 더 내려간다(MAE 분석).
그렇다면 한 번에 다 사지 말고 나눠 사면 평균 단가가 내려간다.
직관은 맞다. 문제는 **레버리지가 걸린 상태에서 물타기는 잘못된
방향으로 노출을 키운다**는 것이다. 이미 지고 있는 포지션에 돈을
더 넣는 행위이고, 계속 빠지면 손실이 선형이 아니라 가속된다.

시험하는 방식 네 가지:
    일괄        -12.26%에서 100% (현재 규칙)
    깊이분할    -8% 33% · -12% 33% · -16% 34%  (미리 정한 가격대)
    추격분할    -12.26%에서 50%, 거기서 -5% 더 빠지면 나머지 50%
    시간분할    -12.26%에서 50%, 3봉 뒤 나머지 50% (가격 무관)

모두 같은 총 투입금액으로 맞춘다. 그래야 비교가 성립한다.
비용도 분할 횟수만큼 더 나간다 — 두 번 사면 수수료도 두 번이다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ml.edge_scan_all import load_all, wilson_lo
from ml.majors_only import MAJORS

RT_ONE = 0.1        # 편도 수수료+슬리피지 (%) — 분할하면 매수 쪽만 늘어난다
FUND8 = 0.01
HOLD = 20
MAXB = 60
HO = pd.Timestamp("2024-01-01")


def build(symbols=None, interval="4h"):
    raw = load_all(interval)
    raw = raw[raw["symbol"].isin(symbols or MAJORS)]
    out = []
    for sym, g in raw.groupby("symbol", sort=False):
        g = g.sort_values("datetime").reset_index(drop=True)
        o = g["open"].astype(float).values; h = g["high"].astype(float).values
        l = g["low"].astype(float).values;  c = g["close"].astype(float).values
        vs = (c / pd.Series(c).rolling(20).mean().values - 1) * 100
        lock = -10**9
        for i in np.where(vs <= -12.26)[0]:
            if i <= lock or i + 1 + MAXB >= len(g): continue
            lock = i + HOLD
            out.append({"sym": sym, "dt": g["datetime"].iloc[i], "vs": vs[i],
                        "o": o[i+1:i+1+MAXB], "h": h[i+1:i+1+MAXB],
                        "l": l[i+1:i+1+MAXB], "c": c[i+1:i+1+MAXB],
                        "ma_vs": vs[i+1:i+1+MAXB]})
    return out


def lump(t):
    """일괄 — 다음봉 시가에 전액"""
    e = t["o"][0]
    return e, 1, HOLD


def depth_split(t, levels=(-8.0, -12.26, -16.0), w=(1/3, 1/3, 1/3)):
    """미리 정한 이격 구간마다 나눠 산다.
    신호는 이미 -12.26%이므로 -8%와 -12.26%는 즉시 체결된 것으로 본다.
    -16%는 이후 이격이 그 아래로 내려가야 체결된다."""
    e0 = t["o"][0]
    fills = []; wsum = 0.0
    for lv, ww in zip(levels, w):
        if t["vs"] <= lv:
            fills.append((e0, ww)); wsum += ww
        else:
            hit = np.where(t["ma_vs"][:HOLD] <= lv)[0]
            if len(hit):
                k = hit[0]
                fills.append((t["c"][k], ww)); wsum += ww
    if not fills: return None, 0, HOLD
    avg = sum(p*ww for p, ww in fills) / wsum
    return avg, len(fills), HOLD


def chase_split(t, drop=-5.0, w1=0.5):
    """1차 50%, 거기서 drop% 더 빠지면 2차 50%"""
    e0 = t["o"][0]
    trigger = e0 * (1 + drop/100)
    hit = np.where(t["l"][:HOLD] <= trigger)[0]
    if len(hit):
        avg = e0*w1 + trigger*(1-w1)
        return avg, 2, HOLD
    return e0, 1, HOLD


def time_split(t, bars=3, w1=0.5):
    """1차 50%, 가격과 무관하게 bars봉 뒤 나머지"""
    e0 = t["o"][0]
    if bars < len(t["o"]):
        return e0*w1 + t["o"][bars]*(1-w1), 2, HOLD
    return e0, 1, HOLD


def evaluate(T, fn, label, lev=1.0):
    rows = []
    for t in T:
        avg, nfill, hold = fn(t)
        if avg is None or not np.isfinite(avg) or avg <= 0: continue
        ex = t["o"][min(hold, len(t["o"])-1)]
        gross = (ex/avg - 1) * 100
        # 비용: 매수 nfill회 + 매도 1회 + 펀딩
        cost = RT_ONE * (nfill + 1) + FUND8*(hold*4/8)
        mae = (t["l"][:hold].min()/avg - 1) * 100
        rows.append({"sym": t["sym"], "dt": t["dt"], "pnl": gross - cost,
                     "avg": avg, "e0": t["o"][0], "nfill": nfill, "mae": mae})
    d = pd.DataFrame(rows)
    if d.empty: return None
    ho = d[d.dt >= HO]
    w = int((ho.pnl > 0).sum())
    return {"label": label, "n": len(d), "all": d.pnl.mean(),
            "n_ho": len(ho), "wr": w/max(len(ho),1)*100,
            "lo": wilson_lo(w, len(ho), 1.96), "ho": ho.pnl.mean(),
            "fills": d.nfill.mean(),
            "improve": ((d.e0/d.avg - 1)*100).mean(),
            "mae": d.mae.median(), "worst": d.pnl.min()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all46", action="store_true")
    a = ap.parse_args()
    syms = None
    if a.all46:
        import glob
        syms = [os.path.basename(f).split("_4h_")[0]
                for f in sorted(glob.glob("data/*_4h_all.csv.gz"))]
        syms = [s for s in syms if s.endswith("USDT")]
    T = build(syms)
    print("=" * 100)
    print(f"  분할매수 검증 — {'46종' if a.all46 else '메이저 12종'} · 4h · "
          f"{HOLD}봉 보유 · 신호 {len(T):,}건")
    print(f"  편도 비용 {RT_ONE}% — 분할하면 매수 횟수만큼 더 나간다")
    print("=" * 100)
    METHODS = [
        (lump, "일괄 (현재 규칙)"),
        (lambda t: depth_split(t), "깊이분할 -8/-12/-16%"),
        (lambda t: depth_split(t, (-12.26,-16,-20), (1/3,1/3,1/3)), "깊이분할 -12/-16/-20%"),
        (lambda t: chase_split(t, -5.0), "추격분할 50%+ -5%에 50%"),
        (lambda t: chase_split(t, -8.0), "추격분할 50%+ -8%에 50%"),
        (lambda t: chase_split(t, -5.0, 0.3), "추격분할 30%+ -5%에 70%"),
        (lambda t: time_split(t, 3), "시간분할 50%+3봉뒤 50%"),
        (lambda t: time_split(t, 6), "시간분할 50%+6봉뒤 50%"),
    ]
    res = [evaluate(T, fn, lab) for fn, lab in METHODS]
    res = [r for r in res if r]
    base = res[0]
    print(f"\n  {'방식':26s}{'평균매수':>7s}{'평단개선':>9s}{'전체거래당':>11s}"
          f"{'홀드승률':>9s}{'하한':>7s}{'홀드거래당':>11s}{'최악':>8s}")
    print("  " + "-" * 90)
    for r in res:
        mark = "  ← 기준" if r is base else ("  ✅" if r["ho"] > base["ho"] else "")
        print(f"  {r['label']:26s}{r['fills']:>7.2f}{r['improve']:>+8.2f}%"
              f"{r['all']:>+10.2f}%{r['wr']:>8.1f}%{r['lo']:>6.1f}%"
              f"{r['ho']:>+10.2f}%{r['worst']:>+7.1f}%{mark}")
    print(f"\n  '평단개선' = 일괄 대비 평균 매수단가가 얼마나 낮아졌나")
    print(f"  '평균매수' = 실제 체결된 분할 횟수 (2.00이면 항상 2번 나눠 샀다는 뜻)")


if __name__ == "__main__":
    main()
