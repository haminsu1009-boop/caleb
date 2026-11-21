"""
ml/cross_market.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
같은 규칙, 다른 시장 — 진짜 우위인가 곡선 맞추기인가

지금까지 찾은 규칙은 바이낸스 현물 46종에서 나왔다. 표본을 아무리
나눠도 같은 데이터를 계속 쓰면 "이 데이터에만 맞는 규칙"일 위험이
남는다. 진짜로 시장 구조에서 나오는 우위라면 **다른 거래소, 다른
자산군, 다른 시대**에서도 약해질지언정 방향은 유지돼야 한다.

이제 세 개의 독립된 데이터가 있다:

    바이낸스 46종 · 4h/1d · 2017~2026   ← 규칙을 찾은 곳
    업비트   38종 · 4h    · 2017~2026   ← 다른 거래소, 원화 마켓, 다른 참여자
    미국주식 117종 · 1d   · 2000~2026   ← 완전히 다른 자산군, 26년

업비트는 거래소 이전 가능성을, 미국주식은 규칙의 보편성을 시험한다.
주식은 변동성이 훨씬 낮으므로 -12.26%를 그대로 쓸 수 없다. 임계값은
각 시장의 학습구간에서 다시 잡고 홀드아웃으로 확인한다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, glob, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ml.edge_scan_all import wilson_lo

COST = 0.25          # 왕복 수수료 + 펀딩 근사


def load_dir(pattern, min_rows=300):
    frames = {}
    for f in sorted(glob.glob(pattern)):
        name = os.path.basename(f).split(".")[0]
        try:
            d = pd.read_csv(f, compression="gzip")
        except Exception:
            continue
        tc = "datetime" if "datetime" in d.columns else "timestamp"
        if tc not in d.columns:
            continue
        d[tc] = pd.to_datetime(d[tc], format="mixed", errors="coerce", utc=True)
        d = d.dropna(subset=[tc]).sort_values(tc).drop_duplicates(tc)
        if len(d) < min_rows:
            continue
        d = d.rename(columns={tc: "datetime"})
        d["datetime"] = d["datetime"].dt.tz_localize(None)
        frames[name] = d.reset_index(drop=True)
    return frames


def trades(frames, thr, hold, train_end):
    """보유 중 재진입 금지. 진입은 다음 봉 시가, 청산은 hold봉 뒤 시가."""
    rows = []
    for sym, g in frames.items():
        c = g["close"].astype(float); o = g["open"].astype(float)
        l = g["low"].astype(float)
        ma = c.rolling(20).mean()
        vs = (c / ma - 1) * 100
        lock = -10**9
        for i in np.where(vs <= thr)[0]:
            if i <= lock or i + 1 + hold >= len(g):
                continue
            lock = i + hold
            e = o.iloc[i + 1]
            if not np.isfinite(e) or e <= 0:
                continue
            rows.append({"symbol": sym, "datetime": g.loc[i, "datetime"],
                         "ret": (o.iloc[i + 1 + hold] / e - 1) * 100 - COST,
                         "mae": (l.iloc[i + 1:i + 1 + hold].min() / e - 1) * 100})
    d = pd.DataFrame(rows)
    if d.empty:
        return d, d
    return d[d.datetime < train_end], d[d.datetime >= train_end]


def baseline(frames, hold, train_end):
    """무조건 진입했을 때 — 비교 기준. 강세장이면 아무거나 사도 이긴다."""
    rr = []
    for sym, g in frames.items():
        o = g["open"].astype(float)
        r = (o.shift(-1 - hold) / o.shift(-1) - 1) * 100 - COST
        rr.append(pd.DataFrame({"datetime": g["datetime"], "ret": r}))
    d = pd.concat(rr).dropna()
    return d[d.datetime < train_end], d[d.datetime >= train_end]


def line(d, label, indent="    "):
    if len(d) < 20:
        print(f"{indent}{label:26s} 표본부족 (n={len(d)})"); return None
    w = int((d["ret"] > 0).sum())
    print(f"{indent}{label:26s} n={len(d):>6,}  승률 {w/len(d)*100:>5.1f}% "
          f"(하한 {wilson_lo(w,len(d),1.96):>4.1f}%)  거래당 {d['ret'].mean():>+6.2f}%")
    return {"n": len(d), "wr": w/len(d)*100, "mean": d["ret"].mean()}


def scan(name, frames, grid, hold, train_end):
    print("=" * 100)
    print(f"  {name}  —  {len(frames)}종목")
    print("=" * 100)
    btr, bho = baseline(frames, hold, train_end)
    print(f"\n  기준선(무조건 진입):  학습 {(btr.ret>0).mean()*100:.1f}% / "
          f"{btr.ret.mean():+.2f}%     홀드아웃 {(bho.ret>0).mean()*100:.1f}% / {bho.ret.mean():+.2f}%")
    print(f"\n  {'임계값':9s}{'학습n':>7s}{'학습승률':>9s}{'학습평균':>10s}"
          f"{'홀드n':>7s}{'홀드승률':>9s}{'홀드평균':>10s}{'초과':>8s}")
    print("  " + "-" * 70)
    best = None
    for thr in grid:
        tr, ho = trades(frames, thr, hold, train_end)
        if len(tr) < 40 or len(ho) < 20:
            print(f"  {thr:>6.1f}%   표본부족 (학습 {len(tr)} / 홀드 {len(ho)})")
            continue
        wtr = (tr.ret > 0).mean() * 100
        who = (ho.ret > 0).mean() * 100
        edge = who - (bho.ret > 0).mean() * 100
        print(f"  {thr:>6.1f}%{len(tr):>8,}{wtr:>8.1f}%{tr.ret.mean():>+9.2f}%"
              f"{len(ho):>7,}{who:>8.1f}%{ho.ret.mean():>+9.2f}%{edge:>+7.1f}%")
        if tr.ret.mean() > 0 and (best is None or tr.ret.mean() > best[1]):
            best = (thr, tr.ret.mean(), ho, who, edge)
    if best:
        thr, _, ho, who, edge = best
        print(f"\n  → 학습구간 최선 {thr}%  ·  홀드아웃 승률 {who:.1f}% "
              f"(기준선 대비 {edge:+.1f}%p)  ·  거래당 {ho.ret.mean():+.2f}%")
        return {"market": name, "thr": thr, "n": len(ho), "wr": who,
                "edge": edge, "mean": ho.ret.mean()}
    print("\n  → 학습구간에서 플러스인 임계값 없음")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="all")
    a = ap.parse_args()
    out = []

    if a.market in ("all", "upbit"):
        fr = load_dir("data/upbit/*_240.csv.gz")
        if fr:
            out.append(scan("업비트 4시간봉 (원화마켓, 2017~2026)", fr,
                            [-6, -8, -10, -12.26, -15, -18], 10, "2024-01-01"))
    if a.market in ("all", "stocks"):
        fr = load_dir("data/stocks/*_1d.csv.gz", min_rows=1000)
        if fr:
            out.append(scan("미국주식 일봉 (2000~2026)", fr,
                            [-5, -8, -10, -12.26, -15, -20], 5, "2019-01-01"))

    ok = [o for o in out if o]
    if len(ok) >= 1:
        print("\n" + "=" * 100)
        print("  요약 — 같은 형태의 규칙이 시장을 건너 살아남는가")
        print("=" * 100)
        print(f"  {'시장':38s}{'임계값':>8s}{'홀드n':>8s}{'승률':>8s}{'기준선대비':>11s}{'거래당':>9s}")
        for o in ok:
            print(f"  {o['market']:38s}{o['thr']:>7.1f}%{o['n']:>8,}"
                  f"{o['wr']:>7.1f}%{o['edge']:>+10.1f}%{o['mean']:>+8.2f}%")


if __name__ == "__main__":
    main()
