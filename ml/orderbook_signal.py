"""
ml/orderbook_signal.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
호가창 불균형이 다음 가격을 예고하는가

사람 단타 고수의 무기 중 하나가 "호가창을 읽는 것"이다. 캔들에는 없는
정보다 — 지금 누가 얼마를 사려고, 팔려고 대기 중인가. data/orderbook에
6종목 1분 간격 호가창 요약이 2026-03-16부터 있다.

    imbalance_1pct = (현재가 ±1% 안의 매수 대기 - 매도 대기) / 합

매수 쪽이 두꺼우면 가격이 오르는가? 5분봉 종가 시점에 이미 공표된
호가창 값만 붙이고(merge_asof, backward), 이후 1·3·12봉 수익률을
전체 평균과 비교한다. 극단 10%(두꺼운 매수 / 두꺼운 매도)에서 초과
수익이 수수료(메이커 왕복 0.04%, 테이커 0.11%)를 넘는지 본다.

기간이 짧다(5분봉 가격이 2026-07-31까지라 겹치는 구간 약 4.5개월,
폭락장 없음). 앞 2/3로 방향을 정하고 뒤 1/3로 채점한다.

사용법:
    python ml/orderbook_signal.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations
import os, sys, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from ml.combo_screen import load_any

SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "BNBUSDT"]


def main():
    rows = []
    for sym in SYMS:
        p = load_any(sym, "5m")
        b = pd.read_csv(f"data/orderbook/{sym}_book_1m.csv.gz")
        b["dt"] = pd.to_datetime(b["dt"])
        b = b.sort_values("dt")[["dt", "imbalance", "imbalance_1pct"]]
        # 5분봉의 dt는 봉 시작이다. 종가 시점 = 시작 + 5분. 그때까지 공표된 값만.
        p = p[(p.dt >= b.dt.min()) & (p.dt <= b.dt.max())].copy()
        p["t_close"] = p["dt"] + pd.Timedelta(minutes=5)
        m = pd.merge_asof(p.sort_values("t_close"), b.rename(columns={"dt": "t_close"}),
                          on="t_close", direction="backward", tolerance=pd.Timedelta(minutes=3))
        m = m.dropna(subset=["imbalance_1pct"]).reset_index(drop=True)
        o = m["open"].values; c = m["close"].values
        n = len(m)
        cut = m["dt"].iloc[int(n * 2 / 3)]
        for H in [1, 3, 12]:
            fwd = np.full(n, np.nan)
            fwd[:n - H] = (c[H:] / o[1:n - H + 1] - 1) * 100   # 다음 봉 시가 진입
            m[f"f{H}"] = fwd
        for col in ["imbalance_1pct", "imbalance"]:
            tr = m[m.dt < cut]
            lo, hi = tr[col].quantile(0.1), tr[col].quantile(0.9)
            for H in [1, 3, 12]:
                for part, d in [("학습", m[m.dt < cut]), ("홀드", m[m.dt >= cut])]:
                    base = d[f"f{H}"].mean()
                    top = d[d[col] >= hi][f"f{H}"]; bot = d[d[col] <= lo][f"f{H}"]
                    rows.append(dict(sym=sym, col=col, H=H, part=part,
                                     long_exc=top.mean() - base, short_exc=-(bot.mean() - base),
                                     n=len(top), bars=len(d)))
    df = pd.DataFrame(rows)
    print("=" * 104)
    print("  호가창 불균형 → 다음 수익률  (극단 10%의 초과수익 · 5분봉 · 다음 봉 시가 진입)")
    print("  롱 = 매수 호가가 두꺼울 때 사면 · 숏 = 매도 호가가 두꺼울 때 팔면")
    print("=" * 104)
    for col in ["imbalance_1pct", "imbalance"]:
        print(f"\n  [{col}]")
        print(f"  {'코인':9s}{'보유':>5s}{'학습 롱':>10s}{'홀드 롱':>10s}{'학습 숏':>10s}{'홀드 숏':>10s}{'극단 n(홀드)':>13s}")
        for (sym, H), d in df[df.col == col].groupby(["sym", "H"]):
            t = d[d.part == "학습"].iloc[0]; h = d[d.part == "홀드"].iloc[0]
            print(f"  {sym:9s}{H*5:>4}분{t.long_exc:>+9.3f}%{h.long_exc:>+9.3f}%"
                  f"{t.short_exc:>+9.3f}%{h.short_exc:>+9.3f}%{h.n:>12,}")
    h = df[df.part == "홀드"]
    best = max(h.long_exc.max(), h.short_exc.max())
    print(f"\n  홀드아웃 최대 초과수익 {best:+.3f}% · 메이커 왕복 0.04% · 테이커 왕복 0.11%")
    print("=" * 104)


if __name__ == "__main__":
    main()
