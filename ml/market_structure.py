"""
ml/market_structure.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
캔들이 아닌 데이터 — 펀딩비·미결제약정·롱숏비율·공포탐욕

지금까지 단타 169가지를 돌렸고 전부 떨어졌다. 그런데 전부 **캔들과
거래량**만 봤다. 가격에서 만든 지표는 가격이 이미 아는 것을 다시
말해줄 뿐이다.

여기서 보는 것은 성격이 다르다.

    펀딩비          롱이 숏에게 내는 돈. 포지션이 어느 쪽에 몰렸는지.
    미결제약정       열려 있는 계약의 총량. 레버리지가 얼마나 쌓였는지.
    롱숏비율        상위 트레이더와 전체가 각각 어느 쪽인지.
    테이커 매수/매도  시장가로 때리는 쪽이 어디인지.
    공포탐욕지수     심리.

이것들은 가격에 없는 정보다 — "지금 값이 얼마인가"가 아니라 "누가
어떻게 들고 있는가"다. 강제청산 연쇄가 일어나려면 먼저 레버리지가
쌓여 있어야 하고, 그건 미결제약정에만 보인다.

━━ 두 갈래로 본다 ━━

① 방향성 신호 — 극단값이 반대 방향을 예고하는가.
   판정은 늘 같다. 조건이 맞은 봉의 이후 수익률을, **아무 때나
   샀을 때의 같은 기간 평균**과 비교한다. 그 차이가 조건이 보탠
   값이고, 왕복 수수료보다 커야 한다.

② 펀딩비 차익거래 — 방향을 맞히지 않는 쪽.
   BTC 펀딩비는 평균 +0.0108%/8h이고 시간의 85.9% 동안 양수다.
   현물을 사고 같은 양의 무기한을 숏으로 잡으면 가격 방향과 무관하게
   이 돈을 받는다. 우리 봇은 롱이라 이걸 **내는** 쪽이다.

사용법:
    python ml/market_structure.py --funding-yield
    python ml/market_structure.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, glob, argparse, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from bot.oversold import strategy as S
from ml.backtest_current_bot import load

FEE = 0.40          # 왕복. 체결지연 포함 실측값.
TE = pd.Timestamp("2024-01-01")


def load_ctx(sym):
    """4시간봉에 펀딩비·지표·심리를 붙인다.

    시점 정렬이 핵심이다. 펀딩비는 8시간마다, 지표는 4시간마다,
    공포탐욕은 하루마다 나온다. 전부 **그 시점에 이미 공표된 값만**
    쓰도록 merge_asof로 뒤쪽에서 당겨온다 — 앞에서 당겨오면
    미래를 보는 것이다.
    """
    g = load(sym)
    if g is None or len(g) < 400:
        return None
    g = g.rename(columns={"datetime": "dt"})[
        ["dt", "open", "high", "low", "close", "volume"]].copy()
    g["dt"] = pd.to_datetime(g["dt"])
    g = g.sort_values("dt").reset_index(drop=True)

    f = f"data/funding/{sym}_funding.csv.gz"
    if os.path.exists(f):
        fd = pd.read_csv(f)
        fd["dt"] = pd.to_datetime(fd["datetime"], format="mixed")
        fd = fd[["dt", "funding_rate"]].sort_values("dt")
        g = pd.merge_asof(g, fd, on="dt", direction="backward")

    m = f"data/metrics/{sym}_metrics_4h.csv.gz"
    if os.path.exists(m):
        md = pd.read_csv(m)
        md["dt"] = pd.to_datetime(md["timestamp"])
        md = md.drop(columns=["timestamp"]).sort_values("dt")
        g = pd.merge_asof(g, md, on="dt", direction="backward")

    fg = "data/indicators/fear_greed_index.csv"
    if os.path.exists(fg):
        d = pd.read_csv(fg)
        d["dt"] = pd.to_datetime(d["date"])
        d = d[["dt", "fear_greed"]].sort_values("dt")
        g = pd.merge_asof(g, d, on="dt", direction="backward")
    return g


def conds(g):
    """조건은 전부 **그 봉 종가 시점에 알 수 있는 값**으로 만든다.
    분위수도 과거만 보는 rolling quantile을 쓴다 — 전체 기간
    분위수를 쓰면 미래를 아는 것이다."""
    C = {}
    W = 500        # 약 83일

    def q(s, p):
        return s.rolling(W, min_periods=100).quantile(p)

    if "funding_rate" in g:
        fr = g["funding_rate"]
        C["펀딩비 극단+ (롱 쏠림)"] = (fr >= q(fr, 0.95)).values
        C["펀딩비 극단- (숏 쏠림)"] = (fr <= q(fr, 0.05)).values
        C["펀딩비 음수"] = (fr < 0).values
    if "sum_open_interest" in g:
        oi = g["sum_open_interest"]
        d = oi.pct_change(6)        # 하루 변화
        C["미결제약정 급증"] = (d >= q(d, 0.95)).values
        C["미결제약정 급감"] = (d <= q(d, 0.05)).values
    for col, lab in [("count_long_short_ratio", "전체 롱숏비율"),
                     ("count_toptrader_long_short_ratio", "상위 롱숏비율"),
                     ("sum_taker_long_short_vol_ratio", "테이커 매수비율")]:
        if col in g:
            s = g[col]
            C[f"{lab} 극단↑"] = (s >= q(s, 0.95)).values
            C[f"{lab} 극단↓"] = (s <= q(s, 0.05)).values
    if ("count_toptrader_long_short_ratio" in g
            and "count_long_short_ratio" in g):
        a = g["count_toptrader_long_short_ratio"]
        b = g["count_long_short_ratio"]
        sp = a / b.replace(0, np.nan)
        C["상위>전체 (스마트머니 롱)"] = (sp >= q(sp, 0.95)).values
        C["상위<전체 (스마트머니 숏)"] = (sp <= q(sp, 0.05)).values
    if "fear_greed" in g:
        fgv = g["fear_greed"]
        C["극단적 공포(≤20)"] = (fgv <= 20).values
        C["극단적 탐욕(≥80)"] = (fgv >= 80).values
    # 가격 조건 하나 — 조합용
    ma = g["close"].rolling(S.MA_PERIOD).mean()
    C["과매도(봇 규칙)"] = ((g["close"] / ma - 1) * 100 <= S.ENTRY_THRESH).values
    return {k: np.nan_to_num(np.asarray(v, dtype=bool)) for k, v in C.items()}


def funding_yield():
    """펀딩비 차익거래 — 현물 롱 + 무기한 숏. 방향을 맞히지 않는다."""
    print("=" * 92)
    print("  펀딩비 차익거래 — 현물을 사고 같은 양을 무기한 숏. 가격 방향과 무관.")
    print("  (우리 봇은 롱이라 이 돈을 '내는' 쪽이다)")
    print("=" * 92)
    rows = []
    for f in sorted(glob.glob("data/funding/*_funding.csv.gz")):
        sym = os.path.basename(f).replace("_funding.csv.gz", "")
        d = pd.read_csv(f)
        d["dt"] = pd.to_datetime(d["datetime"], format="mixed")
        if len(d) < 500:
            continue
        r = d["funding_rate"]
        ho = d[d.dt >= TE]["funding_rate"]
        rows.append(dict(sym=sym, n=len(d),
                         yr=r.mean() * 3 * 365 * 100,
                         pos=(r > 0).mean() * 100,
                         yr_ho=ho.mean() * 3 * 365 * 100 if len(ho) else np.nan,
                         worst=r.min() * 100))
    df = pd.DataFrame(rows).sort_values("yr", ascending=False)
    print(f"\n  {'종목':12s}{'표본':>8s}{'연 수익률':>11s}{'양수비율':>9s}"
          f"{'홀드아웃 연':>12s}{'최악 1회':>10s}")
    print("  " + "-" * 64)
    for _, r in pd.concat([df.head(8), df.tail(4)]).iterrows():
        print(f"  {r['sym']:12s}{r['n']:>8,}{r['yr']:>10.1f}%{r['pos']:>8.1f}%"
              f"{r['yr_ho']:>11.1f}%{r['worst']:>9.3f}%")
    print(f"\n  43종 평균 연 {df.yr.mean():.1f}% · 중앙값 {df.yr.median():.1f}%"
          f" · 홀드아웃 평균 연 {df.yr_ho.mean():.1f}%")
    print(f"  양수 비율 평균 {df.pos.mean():.1f}%")
    print("\n  빠진 비용: 현물·선물 양쪽 수수료, 베이시스 변동, 현물 보관 리스크.")
    print("  거래소가 파산하거나 두 다리가 어긋나면 중립이 아니다(FTX 2022).")
    print("=" * 92)
    return df


def directional(syms, holds=(6, 12, 30, 60)):
    print("\n" + "=" * 104)
    print("  방향성 신호 — 극단값이 이후 수익률을 예고하는가")
    print(f"  기준선은 '아무 때나 샀을 때'의 같은 기간 평균 · 왕복 수수료 {FEE}%")
    print("=" * 104)
    acc = {}
    base_acc = {h: [] for h in holds}
    for sym in syms:
        g = load_ctx(sym)
        if g is None:
            continue
        C = conds(g)
        o = g["open"].values; c = g["close"].values
        dt = pd.DatetimeIndex(g["dt"]); n = len(c)
        for h in holds:
            fwd = np.full(n, np.nan)
            e = o[1:n - h + 1]; x = c[h:n]
            fwd[:len(e)] = (x / e - 1) * 100
            ok = ~np.isnan(fwd)
            base_acc[h].append(fwd[ok])
            for k, m in C.items():
                mm = ok & m
                if mm.sum() < 20:
                    continue
                a = acc.setdefault((k, h), {"r": [], "tr": [], "ho": []})
                a["r"].append(fwd[mm])
                a["tr"].append(fwd[mm & (dt < TE)])
                a["ho"].append(fwd[mm & (dt >= TE)])
    base = {h: np.concatenate(v).mean() for h, v in base_acc.items() if v}

    print(f"\n  {'조건':<26s}{'보유':>5s}{'n':>8s}{'승률':>7s}{'초과':>9s}"
          f"{'학습초과':>10s}{'홀드초과':>10s}{'홀드n':>8s}{'수수료대비':>11s}")
    print("  " + "-" * 96)
    rows = []
    for (k, h), a in acc.items():
        r = np.concatenate(a["r"])
        tr = np.concatenate([x for x in a["tr"] if len(x)])
        ho = np.concatenate([x for x in a["ho"] if len(x)]) if any(
            len(x) for x in a["ho"]) else np.array([])
        if len(r) < 100 or len(ho) < 30:
            continue
        rows.append(dict(k=k, h=h, n=len(r), wr=(r > 0).mean() * 100,
                         exc=r.mean() - base[h], tr=tr.mean() - base[h],
                         ho=ho.mean() - base[h], nho=len(ho)))
    df = pd.DataFrame(rows).sort_values("tr", ascending=False)
    for _, r in df.head(22).iterrows():
        print(f"  {r['k']:<26s}{r['h']:>5}{r['n']:>8,}{r['wr']:>6.1f}%"
              f"{r['exc']:>+8.3f}%{r['tr']:>+9.3f}%{r['ho']:>+9.3f}%"
              f"{r['nho']:>8,}{r['ho']/FEE:>10.2f}배")
    ok = df[(df.tr > FEE) & (df.ho > FEE)]
    print(f"\n  학습·홀드아웃 둘 다 초과 > 수수료({FEE}%): {len(ok)}개 / {len(df)}개"
          + (f" — {', '.join(ok.k.unique())}" if len(ok) else ""))
    if len(df) > 3:
        print(f"  학습초과 ↔ 홀드아웃초과 상관 = {df.tr.corr(df.ho):+.3f}")
    print("=" * 104)
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--funding-yield", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="종목 수 제한(빠른 확인)")
    a = ap.parse_args()
    if a.funding_yield:
        funding_yield()
        return
    funding_yield()
    syms = list(S.SYMBOLS)[: a.limit] if a.limit else list(S.SYMBOLS)
    directional(syms)


if __name__ == "__main__":
    main()
