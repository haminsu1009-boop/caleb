"""
ml/episode_check.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
중복 거래 보정 — n=394가 정말 394개의 독립 관측인가

문제:
    "20기간선 대비 -12% 이하"는 한 번 성립하면 여러 봉 연속으로 성립한다.
    급락 한 번에 신호가 20개 뜨고, 10봉 보유라 그 20개가 거의 같은 구간을
    거래한다. 결과는 20개의 독립 표본이 아니라 사실상 사건 1개다.

    이러면 승률 점추정치는 크게 안 틀려도 신뢰구간이 실제보다 훨씬 좁게
    나온다. "하한 78.4%"는 독립 표본 394개를 가정한 값이고, 실제 독립
    사건이 30개라면 하한은 훨씬 낮다. 좋은 급락 몇 번이 승률 전체를
    만들어낸 것일 수도 있다.

이 스크립트:
    연속/근접 신호를 하나의 '사건'으로 묶고, 사건당 첫 신호 하나만
    거래했다고 가정해 다시 계산한다. 이게 실제로 봇을 돌렸을 때
    (포지션 보유 중엔 재진입 안 함) 나오는 숫자에 훨씬 가깝다.
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
from ml.majors_only import MAJORS, net, stat, show

TRAIN_END = "2024-01-01"


def episodes(df, feat, thr, hold):
    """포지션 보유 중 재진입 금지 — 실제 봇 동작과 같게 만든다"""
    keep = []
    for sym, g in df.groupby("symbol", sort=False):
        g = g.sort_values("datetime").reset_index(drop=True)
        sig = np.where(g[feat] <= thr)[0]
        last_exit = -10**9
        for i in sig:
            if i <= last_exit:          # 아직 이전 포지션 보유 중
                continue
            keep.append(g.index[i] if False else (sym, g.loc[i, "datetime"]))
            last_exit = i + hold        # 청산 시점까지 잠금
    return set(keep)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="4h")
    ap.add_argument("--threshold", type=float, default=-12.26)
    ap.add_argument("--hold", type=int, default=10)
    a = ap.parse_args()
    iv, thr, hold = a.interval, a.threshold, a.hold

    raw = load_all(iv)
    raw = raw[raw["symbol"].isin(MAJORS)]
    df = build(raw, [hold]).sort_values(["symbol", "datetime"]).reset_index(drop=True)
    df["pnl"] = net(df[f"ret{hold}"], hold, iv, "LONG")
    df["year"] = pd.DatetimeIndex(df["datetime"]).year
    HO = df["datetime"] >= TRAIN_END

    ep = episodes(df, "vs_ma20", thr, hold)
    df["is_ep"] = [ (s, d) in ep for s, d in zip(df["symbol"], df["datetime"]) ]
    cond = df["vs_ma20"] <= thr

    print("=" * 96)
    print(f"  중복 거래 보정 — 메이저 {df['symbol'].nunique()}종, {iv}, "
          f"20기간선 대비 {thr}% 이하, {hold}봉 보유")
    print("=" * 96)

    print(f"\n[1] 모든 신호를 세는 경우 vs 사건당 1회만 거래하는 경우 (홀드아웃)")
    show("모든 신호 (중복 포함)", stat(df[cond & HO]["pnl"]))
    show("사건당 1회 ★ (실제 봇)", stat(df[cond & HO & df.is_ep]["pnl"]))

    print(f"\n[2] 학습구간에서도 같은 비교")
    show("모든 신호", stat(df[cond & ~HO]["pnl"]))
    show("사건당 1회 ★", stat(df[cond & ~HO & df.is_ep]["pnl"]))

    print(f"\n[3] 사건 기준 연도별 — 1년에 실제로 몇 번 진입하는가")
    sub = df[cond & df.is_ep]
    print(f"    {'연도':6s}{'진입':>6s}{'승률':>8s}{'거래당':>9s}{'누적':>9s}{'종목':>6s}")
    for y, g in sub.groupby("year"):
        s = stat(g["pnl"])
        if s is None: continue
        print(f"    {y:<6d}{s['n']:>6,}{s['wr']:>7.1f}%{s['mean']:>+8.2f}%"
              f"{g['pnl'].sum():>+8.0f}%{g['symbol'].nunique():>6d}"
              f"{'  ←홀드아웃' if y >= 2024 else ''}")

    print(f"\n[4] 사건 기준 종목별 (홀드아웃)")
    print(f"    {'심볼':10s}{'진입':>6s}{'승률':>8s}{'거래당':>9s}")
    rows = []
    for sym, g in sub[sub["datetime"] >= TRAIN_END].groupby("symbol"):
        s = stat(g["pnl"])
        if s: rows.append({"sym": sym, **s})
    r = pd.DataFrame(rows).sort_values("mean", ascending=False)
    for _, x in r.iterrows():
        print(f"    {x['sym']:10s}{x['n']:>6.0f}{x['wr']:>7.1f}%{x['mean']:>+8.2f}%")
    print(f"\n    {int((r['mean']>0).sum())}/{len(r)}종목 플러스")

    print(f"\n[5] 최대 연속 손실 (사건 기준, 시간순 전체)")
    s = sub.sort_values("datetime")["pnl"].values
    mx = c = 0
    for x in s:
        c = c + 1 if x <= 0 else 0
        mx = max(mx, c)
    print(f"    {mx}회 연속 손실이 실제로 있었다  ·  최악 1회 {s.min():+.1f}%")


if __name__ == "__main__":
    main()
