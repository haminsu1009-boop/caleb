"""
ml/long_short.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
롱/숏 결합 — 낙폭이 실제로 줄어드는가

발상:
    롱 규칙(20MA 대비 -12% 과매도 매수)은 2022년에 졌다(승률 40.4%).
    거울상 규칙(20MA 대비 +X% 과매수 매도)이 그 해에 벌어준다면
    합쳐서 낙폭이 줄어든다.

    다만 "숏도 승률이 높다"는 것만으로는 부족하다. 두 규칙이 **같은
    시기에 같이 벌고 같이 잃으면** 낙폭은 그대로다. 필요한 것은
    손익의 음의 상관이다. 그래서 상관계수와 연도별 엇갈림을 같이 본다.

    또 하나: 암호화폐는 장기 우상향이라 숏은 구조적으로 불리하다.
    펀딩은 숏에 유리하지만(수취), 추세는 불리하다. 실제로 남는지 본다.

검증 방식은 롱과 동일하다 — 임계값은 학습구간에서만 정하고, 보유 중
재진입 금지, 손절은 봉 안 고가로 판정(숏이므로 고가가 역행 방향).
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

ROUND_TRIP = 0.002
FUNDING_PER_8H = 0.0001
TRAIN_END = "2024-01-01"
HOLD = 10


def build(side: str, thr: float, hold: int = HOLD, interval: str = "4h") -> pd.DataFrame:
    """side='LONG': vs_ma20 <= thr 매수.  side='SHORT': vs_ma20 >= thr 매도."""
    raw = load_all(interval)
    raw = raw[raw["symbol"].isin(MAJORS)]
    rows = []
    for sym, g in raw.groupby("symbol", sort=False):
        g = g.sort_values("datetime").reset_index(drop=True)
        c = g["close"].astype(float)
        o, h, l = g["open"].astype(float), g["high"].astype(float), g["low"].astype(float)
        vs = (c / c.rolling(20).mean() - 1) * 100
        idx = np.where(vs <= thr)[0] if side == "LONG" else np.where(vs >= thr)[0]
        lock = -10**9
        for i in idx:
            if i <= lock or i + 1 + hold >= len(g):
                continue
            lock = i + hold
            entry = o.iloc[i + 1]
            seg = slice(i + 1, i + 1 + hold)
            exit_px = o.iloc[i + 1 + hold]
            if side == "LONG":
                mae = (l.iloc[seg].min() / entry - 1) * 100
                ret = (exit_px / entry - 1) * 100
            else:
                mae = (1 - h.iloc[seg].max() / entry) * 100   # 숏의 역행은 고가
                ret = (1 - exit_px / entry) * 100
            rows.append({"symbol": sym, "datetime": g.loc[i, "datetime"], "side": side,
                         "vs": vs.iloc[i], "mae": mae, "ret": ret,
                         "exit_dt": g.loc[i + 1 + hold, "datetime"]})
    d = pd.DataFrame(rows)
    fee = ROUND_TRIP * 100 + FUNDING_PER_8H * (hold * 4 / 8.0) * 100
    # 숏은 펀딩을 받는다 — 부호 반대
    d["pnl"] = d["ret"] - ROUND_TRIP * 100 + (
        -FUNDING_PER_8H * (hold * 4 / 8.0) * 100 if side == "LONG"
        else FUNDING_PER_8H * (hold * 4 / 8.0) * 100)
    return d


def summarize(d, label, indent="    "):
    if len(d) < 10:
        print(f"{indent}{label:24s} 표본부족 (n={len(d)})")
        return None
    w = int((d["pnl"] > 0).sum())
    print(f"{indent}{label:24s} n={len(d):>5,}  승률 {w/len(d)*100:>5.1f}% "
          f"(하한 {wilson_lo(w,len(d),1.96):>4.1f}%)  거래당 {d['pnl'].mean():>+6.2f}%  "
          f"최악 {d['pnl'].min():>+6.1f}%")
    return {"n": len(d), "wr": w/len(d)*100, "mean": d["pnl"].mean()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="4h")
    a = ap.parse_args()

    print("=" * 98)
    print(f"  롱/숏 결합 검증 — 메이저 12종, {a.interval}, {HOLD}봉 보유")
    print("=" * 98)

    print(f"\n[1] 숏 임계값 탐색 — 학습구간에서 고르고 홀드아웃으로 확인")
    print(f"    {'임계값':9s}{'학습n':>7s}{'학습승률':>9s}{'학습평균':>10s}"
          f"{'홀드n':>7s}{'홀드승률':>9s}{'홀드평균':>10s}")
    print("    " + "-" * 62)
    cands = []
    for thr in (8, 10, 12, 15, 20, 25, 30):
        d = build("SHORT", thr, interval=a.interval)
        if d.empty:
            continue
        tr, ho = d[d.datetime < TRAIN_END], d[d.datetime >= TRAIN_END]
        if len(tr) < 50 or len(ho) < 20:
            print(f"    +{thr:<8}표본부족")
            continue
        wtr = (tr.pnl > 0).mean() * 100
        who = (ho.pnl > 0).mean() * 100
        print(f"    +{thr:<8}{len(tr):>7,}{wtr:>8.1f}%{tr.pnl.mean():>+9.2f}%"
              f"{len(ho):>7,}{who:>8.1f}%{ho.pnl.mean():>+9.2f}%")
        cands.append((thr, tr.pnl.mean(), ho.pnl.mean()))

    # 학습구간에서 플러스인 것 중 가장 좋은 것을 고른다 (홀드아웃은 확인용)
    ok = [c for c in cands if c[1] > 0]
    if not ok:
        print("\n    ⚠️ 학습구간에서 플러스인 숏 임계값이 없다.")
        print("       암호화폐의 장기 우상향 때문에 과매수 매도는 구조적으로 불리하다.")
        best_thr = max(cands, key=lambda c: c[1])[0] if cands else None
    else:
        best_thr = max(ok, key=lambda c: c[1])[0]
    print(f"\n    → 학습구간 기준 최선: +{best_thr}%")

    L = build("LONG", -12.26, interval=a.interval)
    Sd = build("SHORT", best_thr, interval=a.interval)

    print(f"\n[2] 연도별 — 롱이 지는 해에 숏이 버는가")
    L["y"] = pd.DatetimeIndex(L.datetime).year
    Sd["y"] = pd.DatetimeIndex(Sd.datetime).year
    print(f"    {'연도':6s}{'롱n':>6s}{'롱승률':>8s}{'롱평균':>9s}   "
          f"{'숏n':>6s}{'숏승률':>8s}{'숏평균':>9s}   엇갈림")
    print("    " + "-" * 72)
    for y in sorted(set(L.y) | set(Sd.y)):
        lg, sg = L[L.y == y], Sd[Sd.y == y]
        lm = lg.pnl.mean() if len(lg) else np.nan
        sm = sg.pnl.mean() if len(sg) else np.nan
        mark = ""
        if not np.isnan(lm) and not np.isnan(sm):
            # 부호가 반대라고 '상쇄'가 아니다. 롱이 벌 때 숏이 잃는 것은
            # 분산이 아니라 그냥 지는 전략이다. 상쇄는 롱이 잃는 해에
            # 숏이 버는 경우만 해당한다.
            mark = ("✅ 상쇄(롱 손실을 숏이 보전)" if lm < 0 < sm else
                    "숏이 발목" if lm > 0 > sm else
                    "둘 다 손실" if lm < 0 and sm < 0 else "둘 다 이익")
        lw = f"{(lg.pnl>0).mean()*100:>7.1f}%" if len(lg) else "      —"
        sw = f"{(sg.pnl>0).mean()*100:>7.1f}%" if len(sg) else "      —"
        print(f"    {y:<6d}{len(lg):>6,}{lw}{lm:>+8.2f}%   "
              f"{len(sg):>6,}{sw}{sm:>+8.2f}%   {mark}")

    print(f"\n[3] 손익 상관 — 같은 달에 같이 벌고 같이 잃는가")
    lm = L.set_index("datetime").pnl.resample("ME").mean()
    sm = Sd.set_index("datetime").pnl.resample("ME").mean()
    j = pd.concat([lm, sm], axis=1, keys=["long", "short"]).dropna()
    if len(j) > 12:
        r = j["long"].corr(j["short"])
        print(f"    월별 수익 상관계수 {r:+.3f}  (겹치는 달 {len(j)}개)")
        print(f"    {'음의 상관 — 결합 시 낙폭 감소 기대' if r < -0.2 else ''}"
              f"{'거의 무상관 — 분산 효과는 있으나 상쇄는 아님' if -0.2 <= r <= 0.2 else ''}"
              f"{'양의 상관 — 같이 움직여 낙폭 감소 효과 없음' if r > 0.2 else ''}")

    print(f"\n[4] 전체 성적")
    summarize(L[L.datetime < TRAIN_END], "롱 학습")
    summarize(L[L.datetime >= TRAIN_END], "롱 홀드아웃")
    summarize(Sd[Sd.datetime < TRAIN_END], "숏 학습")
    summarize(Sd[Sd.datetime >= TRAIN_END], "숏 홀드아웃")


if __name__ == "__main__":
    main()
