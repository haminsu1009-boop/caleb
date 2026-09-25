"""
ml/per_coin_rules.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
코인마다 규칙을 따로 맞추는 것이 전역 규칙보다 나은가

지금 봇은 42종 전부에 같은 규칙을 쓴다(20기간선 -12.26%, 60봉 보유,
볼린저 1.5σ 청산). "코인마다 성격이 다르니 규칙도 달라야 한다"는
말은 직관적으로 옳게 들린다. 문제는 그 직관이 맞는지 아닌지를
백테스트 점수로는 구별할 수 없다는 것이다 — 코인별로 맞추면
백테스트 점수는 **항상** 올라간다. 고를 자유도가 늘었으니까.

그래서 판정 기준을 하나만 쓴다.

    학습구간(2017~2023)에서만 고르고,
    홀드아웃(2024~)에서 전역 규칙을 이기는가.

코인당 학습 거래가 25건 남짓이다. 거기서 5개 파라미터를 고르면
대부분 노이즈를 외운다. 그게 사실이면 홀드아웃에서 드러난다.

같이 재는 것: 분할매도(스케일아웃). 목표가를 한 번에 잡지 않고
볼린저 1σ에서 절반, 1.5σ에서 나머지 식으로 쪼개면 승률이 오르는가.

사용법:
    python ml/per_coin_rules.py                # 전체
    python ml/per_coin_rules.py --quick        # 그리드 축소(빠른 확인)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, itertools, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from bot.oversold import strategy as S
from ml.backtest_current_bot import ROUND_TRIP, FUNDING_PER_8H, BAR_HOURS, load

TRAIN_END = np.datetime64("2024-01-01")


# ── 코인 하나 · 규칙 하나 ────────────────────────────────────────────
def sim(o, h, l, c, dt, ma_p, thresh, hold, fracs, outs, stop_pct, sym="",
        entries=None):
    """판단은 종가, 체결은 다음 봉 시가. 기존 build()와 같은 규약이다.

    outs: [(비중, 볼린저k), ...] — 분할매도. 높은 k가 뒤에 온다.
          [(1.0, 1.5)] 면 지금 봇과 같은 "한 번에 전량 청산"이다.
    """
    n = len(c)
    ma = pd.Series(c).rolling(ma_p).mean().values
    vs = (c / ma - 1) * 100
    # 볼린저는 봇과 동일하게 20봉 · 표본표준편차(ddof=1)
    m20 = pd.Series(c).rolling(20).mean()
    s20 = pd.Series(c).rolling(20).std()
    lv = {k: (m20 + k * s20).values for k in {k for _, k in outs}}

    nt = len(fracs)
    trades = []
    lock = -10**9
    # entries를 주면 임계값 대신 그 봉에서 진입한다 — 국면 통제
    # 기준선용이다. "같은 코인, 같은 시기, 같은 청산 규칙, 진입
    # 시점만 무작위"로 돌려서 규칙이 국면 이상의 것을 보는지 잰다.
    sig = np.where(vs <= thresh)[0] if entries is None else np.asarray(entries)
    for i in sig:
        if i <= lock or i + 1 + hold >= n:
            continue
        e1 = o[i + 1]
        px, w, filled = [e1], [fracs[0]], 1
        avg = e1
        stop = e1 * (1 + stop_pct / 100)
        # 분할매도 상태: 아직 안 판 비중과, 판 조각들의 (비중, 가격)
        left = 1.0
        sold = []
        ex_bar = None
        reason = "time"
        for bar in range(i + 1, i + 1 + hold):
            if l[bar] <= stop:
                sold.append((left, stop)); left = 0.0
                ex_bar, reason = bar, "stop"; break
            # 분할매도 — 낮은 목표부터 순서대로
            for frac, k in outs:
                if frac <= 0 or left <= 1e-9:
                    continue
                up = lv[k][bar]
                if not np.isnan(up) and h[bar] >= up and up > avg:
                    take = min(frac, left)
                    sold.append((take, up)); left -= take
            if left <= 1e-9:
                ex_bar, reason = bar, "tp"; break
            while filled < nt and c[bar] <= e1 * (1 - 5.0 * filled / 100) and bar + 1 < n:
                px.append(o[bar + 1]); w.append(fracs[filled]); filled += 1
                avg = float(np.average(px, weights=w))
                stop = avg * (1 + stop_pct / 100)
                # 2차가 들어오면 이미 판 조각의 비중은 그대로 두고
                # 남은 비중만 새 평단으로 본다 (보수적)
        if ex_bar is None:
            ex_bar = i + 1 + hold
            if left > 1e-9:
                sold.append((left, o[ex_bar])); left = 0.0
        avg = float(np.average(px, weights=w))
        tw = sum(f for f, _ in sold)
        exit_px = sum(f * p for f, p in sold) / tw if tw > 0 else avg
        seg = slice(i + 1, ex_bar + 1)
        trades.append(dict(
            dt=pd.Timestamp(dt[i + 1]), sym=sym,
            entry=avg, exit_px=exit_px,
            deployed=float(sum(w)),
            bars_h=(ex_bar - (i + 1)) * BAR_HOURS, reason=reason,
            # 강제청산 판정용 — 보유 구간의 최저가가 평단 대비 얼마나
            # 내려갔는가. 종가가 아니라 저가로 본다(스치기만 해도 청산).
            mae=float(l[i + 1:ex_bar + 1].min() / avg - 1) * 100,
            # ml/backtest_current_bot.simulate()가 요구하는 이름들.
            # 이름을 맞춰두면 검증된 포트폴리오 시뮬레이터를 그대로
            # 쓸 수 있다 — 총노출 상한·차단기·평가낙폭이 거기 있다.
            entry_avg=avg, entry_bar=i + 1, exit_bar=ex_bar,
            exit_dt=pd.Timestamp(dt[ex_bar]),
            path_dt=dt[seg], path_o=o[seg], path_l=l[seg]))
        lock = ex_bar
    return trades


def score(trades):
    """거래당 순수익(%)과 승률. 배율은 여기서 곱하지 않는다 —
    배율은 모든 규칙에 똑같이 곱해지므로 규칙 비교에는 영향이 없고,
    강제청산은 별도 단계에서 본다."""
    if not trades:
        return dict(n=0, wr=0.0, mu=0.0, tot=0.0)
    r = np.array([(t["exit_px"] / t["entry"] - 1) * 100 - ROUND_TRIP
                  - FUNDING_PER_8H * (t["bars_h"] / 8.0) for t in trades])
    return dict(n=len(r), wr=float((r > 0).mean() * 100), mu=float(r.mean()),
                tot=float(r.sum()))


def split(trades):
    tr = [t for t in trades if t["dt"] < TRAIN_END]
    ho = [t for t in trades if t["dt"] >= TRAIN_END]
    return tr, ho


# ── 그리드 ────────────────────────────────────────────────────────────
def grid(quick=False):
    mas = [20] if quick else [10, 20, 30, 50]
    ths = [-10.0, -12.26, -16.0] if quick else [-8.0, -10.0, -12.26, -15.0, -18.0]
    hos = [60] if quick else [30, 60, 90]
    fr = [[0.3, 0.7]] if quick else [[1.0], [0.3, 0.7], [0.2, 0.3, 0.5]]
    ou = ([[(1.0, 1.5)]] if quick else
          [[(1.0, 1.0)], [(1.0, 1.5)], [(1.0, 2.0)],
           [(0.5, 1.0), (0.5, 1.5)],
           [(0.5, 1.0), (0.5, 2.0)],
           [(0.34, 1.0), (0.33, 1.5), (0.33, 2.0)]])
    return list(itertools.product(mas, ths, hos, fr, ou))


GLOBAL = (S.MA_PERIOD, S.ENTRY_THRESH, S.HOLD_BARS,
          [S.SCALE_IN_FIRST_FRAC, 1 - S.SCALE_IN_FIRST_FRAC], [(1.0, S.BB_K)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--min-train", type=int, default=8,
                    help="학습구간 최소 거래 수 (이하면 그 규칙은 후보에서 뺀다)")
    a = ap.parse_args()

    G = grid(a.quick)
    print("=" * 104)
    print("  코인별 맞춤 규칙 vs 전역 규칙 — 학습구간에서만 고르고 홀드아웃으로 채점")
    print(f"  후보 {len(G)}개/코인 · 종목 {len(S.SYMBOLS)}종 · "
          f"학습 ~2023 · 홀드아웃 2024~ · 최소 학습거래 {a.min_train}건")
    print("=" * 104)

    rows = []
    for sym in S.SYMBOLS:
        g = load(sym)
        if g is None or len(g) < 400:
            continue
        o = g["open"].astype(float).values
        h = g["high"].astype(float).values
        l = g["low"].astype(float).values
        c = g["close"].astype(float).values
        dt = g["datetime"].values

        # 전역 규칙
        gt = sim(o, h, l, c, dt, *GLOBAL, S.STOP_PCT)
        gtr, gho = split(gt)

        # 후보 전수
        best = None
        for (ma_p, th, ho_, fr, ou) in G:
            t = sim(o, h, l, c, dt, ma_p, th, ho_, fr, ou, S.STOP_PCT)
            tr, _ = split(t)
            s = score(tr)
            if s["n"] < a.min_train:
                continue
            # 고르는 기준은 학습구간 "거래당 순수익". 승률만 보고 고르면
            # 한 번 크게 잃는 규칙이 뽑힌다.
            key = s["mu"]
            if best is None or key > best[0]:
                best = (key, (ma_p, th, ho_, fr, ou), t)
        if best is None:
            continue
        _, cfg, bt = best
        btr, bho = split(bt)
        rows.append(dict(sym=sym, cfg=cfg,
                         g_tr=score(gtr), g_ho=score(gho),
                         b_tr=score(btr), b_ho=score(bho)))

    # ── 집계 ─────────────────────────────────────────────────────────
    def agg(key):
        n = sum(r[key]["n"] for r in rows)
        tot = sum(r[key]["tot"] for r in rows)
        wr = (sum(r[key]["wr"] * r[key]["n"] for r in rows) / n) if n else 0
        return n, wr, (tot / n if n else 0)

    print(f"\n  {'':22s}{'거래':>8s}{'승률':>8s}{'거래당':>10s}")
    print("  " + "-" * 50)
    for lab, k in [("전역 · 학습", "g_tr"), ("코인별 · 학습", "b_tr"),
                   ("전역 · 홀드아웃", "g_ho"), ("코인별 · 홀드아웃", "b_ho")]:
        n, wr, mu = agg(k)
        print(f"  {lab:<22s}{n:>8,}{wr:>7.1f}%{mu:>+9.2f}%")

    gn, gwr, gmu = agg("g_ho")
    bn, bwr, bmu = agg("b_ho")
    print(f"\n  홀드아웃 차이: 거래당 {bmu - gmu:+.2f}%p · 승률 {bwr - gwr:+.1f}%p")
    better = sum(1 for r in rows if r["b_ho"]["mu"] > r["g_ho"]["mu"])
    print(f"  코인별이 이긴 종목: {better}/{len(rows)}종")

    # 학습에서 이긴 폭 대비 홀드아웃에서 남은 폭 = 과적합 비율
    d_tr = agg("b_tr")[2] - agg("g_tr")[2]
    d_ho = bmu - gmu
    print(f"  학습에서 앞선 폭 {d_tr:+.2f}%p → 홀드아웃에 남은 폭 {d_ho:+.2f}%p"
          f"  (유지율 {d_ho / d_tr * 100:.0f}%)" if abs(d_tr) > 1e-9 else "")

    print(f"\n  코인별로 뽑힌 규칙 (학습구간 기준)")
    print(f"  {'심볼':11s}{'MA':>4s}{'진입':>8s}{'보유':>5s}{'분할매수':>10s}"
          f"{'분할매도':>22s}{'학습n':>6s}{'홀드n':>6s}{'홀드거래당':>10s}{'전역대비':>9s}")
    for r in sorted(rows, key=lambda x: -(x["b_ho"]["mu"] - x["g_ho"]["mu"])):
        ma_p, th, ho_, fr, ou = r["cfg"]
        fs = "+".join(f"{x*100:.0f}" for x in fr)
        os_ = " ".join(f"{f*100:.0f}%@{k}σ" for f, k in ou)
        print(f"  {r['sym']:11s}{ma_p:>4}{th:>7.2f}%{ho_:>5}{fs:>10s}{os_:>22s}"
              f"{r['b_tr']['n']:>6}{r['b_ho']['n']:>6}{r['b_ho']['mu']:>+9.2f}%"
              f"{r['b_ho']['mu'] - r['g_ho']['mu']:>+8.2f}%")

    print("=" * 104)


if __name__ == "__main__":
    main()
