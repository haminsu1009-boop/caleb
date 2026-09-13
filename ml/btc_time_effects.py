"""
ml/btc_time_effects.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
시간 효과 — 지금까지 한 번도 보지 않은 축

지금까지의 스캔은 "가격이 어떤 상태일 때"만 물었다. "언제"는 묻지
않았다. 암호화폐는 24시간 거래되지만 참여자는 그렇지 않다. 아시아
장중, 유럽 개장, 미국 개장, 미국 마감 후는 각각 다른 사람들이 다른
이유로 거래한다. 주식 시장의 개장/마감 효과는 잘 알려져 있고,
암호화폐에도 미국 주식시장 시간대와 연동된 흐름이 보고돼 있다.

보는 축:
    UTC 시각(0~23) · 요일 · 월 · 월중 위치 · 반감기 사이클 위치
    그리고 "특정 시각 + 과매도" 결합

주의:
    24개 시각 × 방향 2 × 보유기간 5를 검정하면 우연히 좋아 보이는
    시각이 반드시 나온다. Bonferroni 보정을 걸고, 학습/홀드아웃
    방향 일치를 요구한다. 인접 시각끼리 비슷한 값이 나오는지도 본다
    — 진짜 세션 효과라면 한 시각만 튀지 않고 구간으로 뭉친다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
import numpy as np
import pandas as pd
from scipy.stats import norm

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ml.btc_all_timeframes import load, features, ROUND_TRIP, TRAIN_FRAC

# 반감기 (UTC)
HALVINGS = ["2016-07-09", "2020-05-11", "2024-04-20", "2028-04-01"]


def wilson_lo(w, n, z):
    if n == 0: return 0.0
    p = w/n; den = 1+z*z/n; ctr = p+z*z/(2*n)
    return (ctr - z*np.sqrt(p*(1-p)/n + z*z/(4*n*n)))/den*100


def prep(tf, H):
    g = load(tf)
    o = g["open"].astype(float)
    entry = o.shift(-1)
    px = (o.shift(-1-H)/entry - 1) * 100
    d = pd.DataFrame({"dt": g["datetime"], "px": px})
    d["L"] = d.px - ROUND_TRIP
    d["S"] = -d.px - ROUND_TRIP
    idx = pd.DatetimeIndex(d.dt)
    d["hour"] = idx.hour
    d["dow"] = idx.dayofweek          # 0=월
    d["month"] = idx.month
    d["dom"] = idx.day
    hv = pd.to_datetime(HALVINGS)
    pos = []
    for t in idx:
        prev = hv[hv <= t]
        nxt = hv[hv > t]
        if len(prev) == 0 or len(nxt) == 0:
            pos.append(np.nan); continue
        pos.append((t - prev[-1]).days / max((nxt[0] - prev[-1]).days, 1))
    d["cycle"] = pos                   # 0=반감기 직후, 1=다음 반감기 직전
    return d.dropna(subset=["px"]).reset_index(drop=True)


def report(d, col, labels, z, min_n, title, split_i):
    tr = d.index < split_i
    print(f"\n  ── {title} ──")
    print(f"    {'구간':16s}{'학습n':>8s}{'학습평균':>10s}{'홀드n':>8s}"
          f"{'홀드승률':>9s}{'하한':>7s}{'홀드평균':>10s}{'방향':>6s}")
    hits = []
    for v, lab in labels:
        m = (d[col] == v) if not isinstance(v, tuple) else \
            ((d[col] >= v[0]) & (d[col] < v[1]))
        for side in ("L", "S"):
            a, b = m & tr, m & ~tr
            if a.sum() < min_n or b.sum() < min_n:
                continue
            pt, ph = d.loc[a, side], d.loc[b, side]
            if pt.mean() <= 0 or ph.mean() <= 0:
                continue
            w = int((ph > 0).sum())
            lo = wilson_lo(w, len(ph), z)
            base = (d.loc[~tr, side] > 0).mean()*100
            if lo <= base:
                continue
            hits.append((lab, side, len(pt), pt.mean(), len(ph),
                         w/len(ph)*100, lo, ph.mean()))
    if not hits:
        print("    보정을 견디는 구간 없음")
        return []
    for lab, side, ntr, mtr, nho, wr, lo, mho in sorted(hits, key=lambda x:-x[6]):
        print(f"    {lab:16s}{ntr:>8,}{mtr:>+9.3f}%{nho:>8,}{wr:>8.1f}%{lo:>6.1f}%"
              f"{mho:>+9.3f}%{'롱' if side=='L' else '숏':>6s}")
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--H", type=int, default=6)
    ap.add_argument("--min-n", type=int, default=150)
    a = ap.parse_args()

    d = prep(a.tf, a.H)
    split_i = int(len(d) * TRAIN_FRAC)
    n_tests = (24 + 7 + 12 + 4 + 5) * 2
    z = norm.ppf(1 - 0.05/(2*n_tests))

    print("=" * 96)
    print(f"  비트코인 시간 효과 — {a.tf}, {a.H}봉 보유, 비용 {ROUND_TRIP}% 차감")
    print(f"  검정 {n_tests}회 → Bonferroni z = {z:.3f}  ·  학습 {split_i:,} / 홀드아웃 {len(d)-split_i:,}")
    print("=" * 96)

    base_l = (d.loc[d.index>=split_i,"L"]>0).mean()*100
    base_s = (d.loc[d.index>=split_i,"S"]>0).mean()*100
    print(f"\n  기준선(홀드아웃): 롱 {base_l:.1f}%  숏 {base_s:.1f}%")

    report(d, "hour", [(h, f"{h:02d}시 UTC") for h in range(24)], z, a.min_n,
           "UTC 시각별 (한국시각 = UTC+9)", split_i)
    report(d, "dow", [(i, n) for i, n in enumerate(
           ["월","화","수","목","금","토","일"])], z, a.min_n, "요일별", split_i)
    report(d, "month", [(m, f"{m}월") for m in range(1,13)], z, a.min_n, "월별", split_i)
    report(d, "cycle", [((i/4,(i+1)/4), f"사이클 {i*25}~{(i+1)*25}%")
           for i in range(4)], z, a.min_n, "반감기 사이클 위치", split_i)
    report(d, "dom", [((1,8),"1~7일"),((8,16),"8~15일"),((16,24),"16~23일"),
           ((24,32),"24~31일")], z, a.min_n, "월중 위치", split_i)

    # 인접 시각 뭉침 검사 — 진짜 세션 효과인지
    print(f"\n  ── 시각별 원자료 (뭉치는지 확인) ──")
    ho = d[d.index >= split_i]
    print(f"    {'시각':6s}{'n':>7s}{'롱승률':>9s}{'롱평균':>10s}   {'시각':6s}{'n':>7s}{'롱승률':>9s}{'롱평균':>10s}")
    rows = []
    for h in range(24):
        m = ho.hour == h
        if m.sum() < 20: continue
        rows.append((h, m.sum(), (ho.loc[m,"L"]>0).mean()*100, ho.loc[m,"L"].mean()))
    for i in range(0, len(rows), 2):
        line = ""
        for j in (i, i+1):
            if j < len(rows):
                h,n,w,mu = rows[j]
                line += f"    {h:02d}시  {n:>6,}{w:>8.1f}%{mu:>+9.3f}%"
        print(line)


if __name__ == "__main__":
    main()
