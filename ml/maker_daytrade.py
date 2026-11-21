"""
ml/maker_daytrade.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
지정가(메이커)로만 들어가는 단타 — 수수료 벽이 무너지는가

단타 233가지가 전부 같은 자리에서 떨어졌다. 엣지가 수수료보다 작았다.
그 계산은 전부 시장가(테이커) 수수료였다 — 왕복 0.11%(바이빗 테이커)
또는 0.40%(체결지연 포함 실측). 바이빗 지정가(메이커) 수수료는 편도
0.02%다. 왕복 0.04%로 10분의 1이다.

공짜는 아니다. 지정가 주문에는 **불리한 선택(adverse selection)** 이
붙는다. 매수 지정가는 가격이 내 주문가까지 내려와야 체결되고, 내려
오지 않고 바로 오르는 좋은 경우엔 체결되지 않고 떠난다. 그래서
체결된 거래만 모으면 평균보다 나쁜 표본이 된다. 이 파일은 그걸
체결 규칙 안에서 자연스럽게 만든다.

체결 규칙 (보수적으로)
  · 매수 지정가 = 신호 봉 종가 × (1 - off). W봉 안에 저가가 지정가를
    **0.05% 넘게 뚫어야** 체결로 본다. 살짝 닿기만 하면 줄 선 앞사람이
    가져간다고 본다. 시가부터 지정가 아래로 갭이면 시가에 체결.
  · 익절 = 지정가(메이커). 고가가 목표를 0.05% 넘게 뚫어야 체결.
  · 손절 = 시장가 트리거(테이커) + 미끄러짐 0.02%. 갭이면 시가에.
  · 체결 봉 안에서는 손절만 본다(그 봉에서 목표까지 갔는지 순서를
    모르므로 유리한 쪽을 고르지 않는다).
  · 시간청산 = 시장가(테이커) + 미끄러짐.
  · 한 번에 한 포지션(청산 전 재진입 없음).

수수료: 메이커 0.02% · 테이커 0.055% · 미끄러짐 0.02% (편도)

대조군: **같은 체결 규칙으로 무작위 봉에서 진입.** 지정가로 떨어질 때
사는 것 자체가 역추세 매매라, 신호 없이도 뭔가 나올 수 있다. 신호가
그걸 넘어야 의미가 있다.

학습 ~2023에서 설정을 고르고 홀드아웃 2024~로 채점한다.

사용법:
    python ml/maker_daytrade.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, itertools, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
from numba import njit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from ml.combo_screen import load_any

MAKER, TAKER, SLIP, TT = 0.0002, 0.00055, 0.0002, 0.0005
TE = np.datetime64("2024-01-01")


@njit(cache=True)
def sim_maker(o, h, l, c, sig, off, tp, sl, H, W, maker, taker, slip, tt, taker_entry):
    n = len(c)
    out_i = np.empty(len(sig), np.int64)
    out_r = np.empty(len(sig), np.float64)
    out_k = np.empty(len(sig), np.int64)     # 0 목표 1 손절 2 시간
    m = 0
    lock = -1
    for s in sig:
        if s <= lock or s + 1 + W + H >= n:
            continue
        # ── 진입
        j = -1
        if taker_entry:
            j = s + 1; e = o[j] * (1 + slip); fe = taker
        else:
            lim = c[s] * (1 - off)
            for k in range(s + 1, s + 1 + W):
                if o[k] <= lim:
                    j = k; e = o[k]; break
                if l[k] < lim * (1 - tt):
                    j = k; e = lim; break
            fe = maker
            if j < 0:
                continue
        tgt = e * (1 + tp); stp = e * (1 - sl)
        ex = -1.0; kind = 2; xf = taker
        # 체결 봉: 손절만 본다
        if l[j] <= stp:
            ex = stp * (1 - slip); kind = 1; xf = taker; last = j
        else:
            last = j + H
            for k in range(j + 1, j + 1 + H):
                if o[k] <= stp:
                    ex = o[k] * (1 - slip); kind = 1; xf = taker; last = k; break
                if l[k] <= stp:
                    ex = stp * (1 - slip); kind = 1; xf = taker; last = k; break
                if o[k] >= tgt:
                    ex = o[k]; kind = 0; xf = maker; last = k; break
                if h[k] > tgt * (1 + tt):
                    ex = tgt; kind = 0; xf = maker; last = k; break
            if ex < 0:
                ex = c[last] * (1 - slip); kind = 2; xf = taker
        out_i[m] = j
        out_r[m] = (ex / e - 1) - fe - xf
        out_k[m] = kind
        m += 1
        lock = last
    return out_i[:m], out_r[:m], out_k[:m]


def signals(g):
    o, h, l, c, v = (g[k].astype(float).values for k in ("open", "high", "low", "close", "volume"))
    s = pd.Series(c)
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rsi = (100 - 100 / (1 + up / dn.replace(0, np.nan))).values
    ema50 = s.ewm(span=50, adjust=False).mean().values
    tp_ = (h + l + c) / 3
    vw = pd.Series(tp_ * v).rolling(24).sum() / pd.Series(v).rolling(24).sum().replace(0, np.nan)
    sd = s.rolling(24).std()
    prev_low = pd.Series(l).rolling(24).min().shift(1).values
    rng = np.random.default_rng(0)
    n = len(c)
    S = {
        "무작위(대조군)": np.sort(rng.choice(np.arange(60, n - 200), size=n // 20, replace=False)),
        "엔벨로프 -2%": np.where(c <= ema50 * 0.98)[0],
        "RSI < 30": np.where(rsi < 30)[0],
        "VWAP -2σ": np.where(c <= (vw - 2 * sd).values)[0],
        "유동성 스윕": np.where((l < prev_low) & (c > prev_low))[0],
    }
    return {k: v[v > 60].astype(np.int64) for k, v in S.items()}


GRID = list(itertools.product(
    [0.0, 0.002, 0.005, 0.01],                                   # off
    [(0.003, 0.003), (0.005, 0.005), (0.005, 0.01), (0.01, 0.01),
     (0.01, 0.02), (0.02, 0.02), (0.02, 0.04), (0.03, 0.03)],   # (tp, sl)
    [12, 48],                                                    # H
    [3, 12],                                                     # W
))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tfs", default="5m,15m,1h")
    ap.add_argument("--coins", default="BTCUSDT,ETHUSDT")
    ap.add_argument("--min-n", type=int, default=150)
    a = ap.parse_args()

    rows = []
    for sym in a.coins.split(","):
        for tf in a.tfs.split(","):
            g = load_any(sym, tf)
            if g is None or len(g) < 5000:
                continue
            o, h, l, c = (g[k].astype(float).values for k in ("open", "high", "low", "close"))
            dt = g["dt"].values
            yrs_tr = (TE - dt[0]) / np.timedelta64(365, "D")
            yrs_ho = (dt[-1] - TE) / np.timedelta64(365, "D")
            SIG = signals(g)
            for sname, sig in SIG.items():
                for off, (tp, sl), H, W in GRID:
                    for te, lab in [(False, "메이커"), (True, "테이커")]:
                        if te and off > 0:
                            continue
                        ii, rr, kk = sim_maker(o, h, l, c, sig, off, tp, sl, H, W,
                                               MAKER, TAKER, SLIP, TT, te)
                        if len(rr) < a.min_n:
                            continue
                        tr = dt[ii] < TE
                        if tr.sum() < a.min_n // 2 or (~tr).sum() < 30:
                            continue
                        rows.append(dict(sym=sym, tf=tf, sig=sname, fee=lab, off=off, tp=tp,
                                         sl=sl, H=H, W=W, fill=len(rr) / max(len(sig), 1),
                                         n_tr=int(tr.sum()), n_ho=int((~tr).sum()),
                                         mu_tr=rr[tr].mean() * 100, mu_ho=rr[~tr].mean() * 100,
                                         wr_ho=(rr[~tr] > 0).mean() * 100,
                                         yr_ho=rr[~tr].sum() * 100 / max(yrs_ho, 0.1),
                                         tp_share=(kk == 0).mean() * 100))
    df = pd.DataFrame(rows)
    df.to_csv("ml/maker_daytrade_results.csv", index=False)

    print("=" * 120)
    print("  지정가(메이커) 단타 — 불리한 체결 반영 · 학습 ~2023에서 고르고 2024~로 채점")
    print(f"  메이커 {MAKER*100:.3f}% · 테이커 {TAKER*100:.3f}% · 미끄러짐 {SLIP*100:.2f}% · 뚫림 요구 {TT*100:.2f}%")
    print("=" * 120)
    print(f"\n  {'코인':8s}{'봉':>4s} {'신호':<14s}{'수수료':<6s}{'학습1위 설정':<24s}"
          f"{'학습':>8s}{'홀드':>8s}{'홀드승률':>8s}{'홀드n':>7s}{'연간(단순합)':>12s}{'대조군홀드':>10s}")
    print("  " + "-" * 114)
    verdict = []
    for (sym, tf, fee), d in df.groupby(["sym", "tf", "fee"]):
        base = d[d.sig == "무작위(대조군)"]
        for sname, e in d.groupby("sig"):
            if sname == "무작위(대조군)":
                continue
            b = e.sort_values("mu_tr", ascending=False).iloc[0]
            same = base[(base.off == b.off) & (base.tp == b.tp) & (base.sl == b.sl)
                        & (base.H == b.H) & (base.W == b.W)]
            bho = same.mu_ho.iloc[0] if len(same) else np.nan
            cfg = f"off{b.off*100:.1f} tp{b.tp*100:.1f}/sl{b.sl*100:.1f} H{b.H} W{b.W}"
            ok = b.mu_tr > 0 and b.mu_ho > 0 and (np.isnan(bho) or b.mu_ho > bho)
            verdict.append((sym, tf, fee, sname, ok, b.mu_ho, b.yr_ho))
            print(f"  {sym[:7]:8s}{tf:>4s} {sname:<14s}{fee:<6s}{cfg:<24s}"
                  f"{b.mu_tr:>+7.3f}%{b.mu_ho:>+7.3f}%{b.wr_ho:>7.1f}%{b.n_ho:>7,}"
                  f"{b.yr_ho:>+10.1f}%{bho:>+9.3f}%" + ("  ✅" if ok else ""))
    mk = [v for v in verdict if v[2] == "메이커"]
    tk = [v for v in verdict if v[2] == "테이커"]
    print(f"\n  통과(학습·홀드 둘 다 +, 대조군보다 나음): 메이커 {sum(v[4] for v in mk)}/{len(mk)} · "
          f"테이커 {sum(v[4] for v in tk)}/{len(tk)}")
    m = df[df.fee == "메이커"]
    if len(m) > 3:
        print(f"  메이커 전체 {len(m):,}개 설정에서 학습↔홀드 상관 {m.mu_tr.corr(m.mu_ho):+.3f}")
    print("  (연간 = 홀드아웃 거래당 순수익의 연 단순합 · 배율 1배 · 한 번에 전액 기준)")
    print("=" * 120)


if __name__ == "__main__":
    main()
