"""
ml/majors_only.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
메이저 코인 한정 재검증

왜 따로 봐야 하나:
    지금까지의 규칙은 46종을 전부 풀링해서 찾았다. 표본을 키워 1~2%
    우위를 측정 가능하게 만드는 게 목적이었다. 하지만 실제로는 메이저
    몇 종만 거래한다면 그 표본은 더 이상 대표성이 없다.

    특히 과매도 반등은 비유동 소형주에서 강하게 나타나는 것이 정설이다.
    메이저는 참여자가 많고 차익거래가 빨라 같은 우위가 작거나 사라질 수
    있다. 임계값도 다시 잡아야 한다 — 비트코인이 4시간봉에서 20기간선
    대비 -12%까지 빠지는 일은 알트보다 훨씬 드물다.

이 스크립트가 하는 것:
    1. 기존 규칙을 메이저에만 적용했을 때 살아남는지
    2. 메이저 기준으로 임계값을 다시 잡으면 어디가 최적인지
       (임계값은 학습구간에서만 정하고 홀드아웃으로 확인)
    3. 종목별로 쪼개서 특정 코인이 끌고 가는 결과인지

사용법:
    python ml/majors_only.py
    python ml/majors_only.py --interval 1d
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ml.edge_scan_all import load_all, build, wilson_lo

ROUND_TRIP = 0.002
TRAIN_END = "2024-01-01"
FUNDING_PER_8H = 0.0001
BAR_HOURS = {"4h": 4, "1d": 24}

# 사용자가 지정한 매매 대상. 시총 상위 + 바이빗 무기한 거래량 상위 교집합.
MAJORS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "ADAUSDT", "DOTUSDT", "SOLUSDT",
          "BNBUSDT", "DOGEUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT", "TRXUSDT"]


def net(pnl: pd.Series, hold: int, interval: str, side: str) -> pd.Series:
    p = pnl - ROUND_TRIP * 100
    fee = FUNDING_PER_8H * (hold * BAR_HOURS[interval] / 8.0) * 100
    return p - fee if side == "LONG" else p + fee


def stat(p: pd.Series):
    p = p.dropna()
    n = len(p)
    if n == 0:
        return None
    w = int((p > 0).sum())
    return {"n": n, "wr": w / n * 100, "lo": wilson_lo(w, n, 1.96),
            "mean": p.mean(), "worst": p.min()}


def show(label, s, indent="    "):
    if s is None or s["n"] < 20:
        print(f"{indent}{label:30s} 표본부족 (n={0 if s is None else s['n']})")
        return
    print(f"{indent}{label:30s} n={s['n']:>6,}  승률 {s['wr']:>5.1f}% "
          f"(하한 {s['lo']:>4.1f}%)  거래당 {s['mean']:>+6.2f}%  최악 {s['worst']:>+6.1f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="4h")
    a = ap.parse_args()
    iv = a.interval

    raw = load_all(iv)
    raw = raw[raw["symbol"].isin(MAJORS)]
    have = sorted(raw["symbol"].unique())
    df = build(raw, [3, 5, 10])
    df = df.sort_values(["symbol", "datetime"]).reset_index(drop=True)
    df["ma200"] = df.groupby("symbol")["close"].transform(lambda s: s.rolling(200).mean())
    df["above200"] = (df["close"] > df["ma200"]).shift(1)
    HO = df["datetime"] >= TRAIN_END
    TR = ~HO

    print("=" * 100)
    print(f"  메이저 한정 재검증 — {iv}, {len(have)}종목")
    print(f"  {' '.join(s.replace('USDT','') for s in have)}")
    print(f"  비용 왕복 {ROUND_TRIP*100:.1f}% + 펀딩 반영")
    print("=" * 100)

    feat, hold, side = "vs_ma20", 10 if iv == "4h" else 5, "LONG"
    base_thr = -12.26 if iv == "4h" else -20.32

    print(f"\n[1] 기존 임계값({base_thr}%)을 메이저에만 적용")
    for tag, m in (("전체 46종 대비 참고용", None),):
        pass
    for label, mask in (("학습 2017~2023", TR), ("홀드아웃 2024~2026 ★", HO)):
        sub = df[(df[feat] <= base_thr) & mask]
        show(label, stat(net(sub[f"ret{hold}"], hold, iv, side)))
    sub = df[(df[feat] > base_thr) & HO]
    show("(대조) 조건 미충족", stat(net(sub[f"ret{hold}"], hold, iv, side)))
    show("(대조) 무조건 진입", stat(net(df[HO][f"ret{hold}"], hold, iv, side)))

    print(f"\n[2] 메이저 기준으로 임계값 재탐색 — 학습구간에서 고르고 홀드아웃으로 확인")
    print(f"    {'임계값':10s}{'학습n':>7s}{'학습승률':>9s}{'홀드n':>7s}{'홀드승률':>9s}{'하한':>7s}{'거래당':>9s}")
    print("    " + "-" * 66)
    grid = [-3, -4, -5, -6, -8, -10, -12, -15] if iv == "4h" else [-6, -8, -10, -12, -15, -20, -25]
    best = None
    for th in grid:
        str_ = stat(net(df[(df[feat] <= th) & TR][f"ret{hold}"], hold, iv, side))
        sho = stat(net(df[(df[feat] <= th) & HO][f"ret{hold}"], hold, iv, side))
        if not str_ or not sho or sho["n"] < 40:
            print(f"    {th:>5.0f}%     표본부족")
            continue
        print(f"    {th:>5.0f}%    {str_['n']:>7,}{str_['wr']:>8.1f}%"
              f"{sho['n']:>7,}{sho['wr']:>8.1f}%{sho['lo']:>6.1f}%{sho['mean']:>+8.2f}%")
        if str_["wr"] > 50 and (best is None or sho["lo"] > best[1]["lo"]):
            best = (th, sho)

    print(f"\n[3] 보유기간 민감도 (임계값 {base_thr}%)")
    for h in (3, 5, 10):
        show(f"{h}봉 보유", stat(net(df[(df[feat] <= base_thr) & HO][f"ret{h}"], h, iv, side)))

    print(f"\n[4] 종목별 (홀드아웃, 임계값 {base_thr}%)")
    print(f"    {'심볼':10s}{'n':>7s}{'승률':>8s}{'거래당':>9s}{'누적':>10s}")
    print("    " + "-" * 46)
    rows = []
    for sym, g in df[(df[feat] <= base_thr) & HO].groupby("symbol"):
        s = stat(net(g[f"ret{hold}"], hold, iv, side))
        if s is None:
            continue
        rows.append({"sym": sym, **s, "sum": net(g[f"ret{hold}"], hold, iv, side).sum()})
    if rows:
        r = pd.DataFrame(rows).sort_values("mean", ascending=False)
        for _, x in r.iterrows():
            flag = "" if x["n"] >= 20 else "  (표본적음)"
            print(f"    {x['sym']:10s}{x['n']:>7.0f}{x['wr']:>7.1f}%{x['mean']:>+8.2f}%"
                  f"{x['sum']:>+9.0f}%{flag}")
        print(f"\n    {int((r['mean']>0).sum())}/{len(r)}종목 플러스")

    print(f"\n[5] 연도별 발동 — 실제로 몇 번 기회가 오는가")
    sub = df[df[feat] <= base_thr].copy()
    sub["pnl"] = net(sub[f"ret{hold}"], hold, iv, side)
    sub["year"] = pd.DatetimeIndex(sub["datetime"]).year
    print(f"    {'연도':6s}{'발동':>7s}{'승률':>8s}{'거래당':>9s}{'종목':>6s}")
    for y, g in sub.groupby("year"):
        s = stat(g["pnl"])
        if s is None or s["n"] < 3:
            continue
        print(f"    {y:<6d}{s['n']:>7,}{s['wr']:>7.1f}%{s['mean']:>+8.2f}%"
              f"{g['symbol'].nunique():>6d}{'  ←홀드아웃' if y >= 2024 else ''}")


if __name__ == "__main__":
    main()
