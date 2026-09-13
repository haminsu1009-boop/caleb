"""
ml/validate_extended.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MA 롱온리 전략을 확장 심볼에서 재검증 + 펀딩비 반영 + 횡단면 전략

세 가지를 한 번에 처리한다.

  1. 확장 재검증
     ml/intraday_search.py는 6종에서 전략을 골랐다. 그 6종은 선택에
     쓰였으므로 재사용하면 순환논증이다. 여기서는 전략을 고를 때
     쓰이지 않은 40종에서만 성과를 낸다. 이게 진짜 out-of-sample이다.

  2. 펀딩비 반영
     지금까지의 추세 백테스트는 수수료·슬리피지만 차감했다. 무기한
     선물을 롱으로 몇 주씩 들고 가면 8시간마다 펀딩비를 낸다.
     data/funding/ 이 있으면 보유 구간에 실제 펀딩비를 붙인다.
     (숏이면 받고, 롱이면 낸다 — 부호를 포지션 방향에 맞춘다)

  3. 횡단면 전략
     6종으로는 순위를 매겨봐야 의미가 없어 테스트하지 못했던 접근.
     매 리밸런싱일에 전 종목을 모멘텀으로 정렬해 상위 N종만 보유한다.
     단일 자산 타이밍과는 다른 계열의 전략이다.

사용법:
    python ml/validate_extended.py                 # 전부
    python ml/validate_extended.py --skip-cross    # 1,2번만
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, glob, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FEE, SLIP = 0.0005, 0.0005
BASE6 = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]

# intraday_search.py 최상위 조합
FAST_DAYS, SLOW_DAYS = 3, 33
BPD = {"1d": 1, "4h": 6, "1h": 24}


# ══════════════════════════════════════════════════════════════
def load_sym(sym: str, interval: str) -> pd.DataFrame:
    allf = f"data/{sym}_{interval}_all.csv.gz"
    files = [allf] if os.path.exists(allf) else sorted(
        g for g in glob.glob(f"data/{sym}_{interval}_*.csv.gz") if "_all" not in g)
    if not files:
        return pd.DataFrame()
    df = pd.concat([pd.read_csv(f, compression="gzip") for f in files], ignore_index=True)
    tc = "timestamp" if "timestamp" in df.columns else "datetime"
    df[tc] = pd.to_datetime(df[tc], format="mixed", errors="coerce")
    df = df.dropna(subset=[tc]).sort_values(tc).drop_duplicates(tc).reset_index(drop=True)
    return df.rename(columns={tc: "datetime"})[["datetime", "open", "high", "low", "close"]]


def load_funding(sym: str) -> pd.Series | None:
    p = f"data/funding/{sym}_funding.csv.gz"
    if not os.path.exists(p):
        return None
    d = pd.read_csv(p, compression="gzip")
    d["datetime"] = pd.to_datetime(d["datetime"], errors="coerce")
    return d.dropna().set_index("datetime")["funding_rate"].sort_index()


def available_symbols(interval: str) -> list:
    out = set()
    for f in glob.glob(f"data/*_{interval}_*.csv.gz"):
        b = os.path.basename(f)
        sym = b.split(f"_{interval}_")[0]
        if sym.endswith("USDT"):
            out.add(sym)
    return sorted(out)


# ══════════════════════════════════════════════════════════════
def ma_long_only(df: pd.DataFrame, interval: str) -> np.ndarray:
    d = BPD[interval]
    f = max(2, FAST_DAYS * d); s = max(3, SLOW_DAYS * d)
    c = df["close"]
    fa = c.rolling(f).mean().shift(1); sl = c.rolling(s).mean().shift(1)
    p = np.where(fa > sl, 1.0, 0.0)
    p[np.isnan(fa.values) | np.isnan(sl.values)] = 0.0
    return p


def backtest(df: pd.DataFrame, pos: np.ndarray, funding: pd.Series | None = None) -> dict:
    c = df["close"].values
    r = np.zeros(len(c)); r[1:] = c[1:] / c[:-1] - 1.0
    held = np.roll(pos, 1); held[0] = 0.0
    turn = np.abs(np.diff(np.concatenate([[0.0], pos])))
    sr = held * r - turn * (FEE + SLIP)

    fcost = 0.0
    if funding is not None and len(funding):
        # 각 봉 구간에 속한 펀딩 지급액 합계 (롱이면 지불 → 음수)
        fr = funding.reindex(df["datetime"], method=None)
        fr = funding.groupby(pd.cut(funding.index, bins=list(df["datetime"]) + [df["datetime"].iloc[-1]],
                                    right=False)).sum() if False else None
        # 단순·안전한 방식: 봉 시각으로 asof 합산
        idx = pd.DatetimeIndex(df["datetime"])
        acc = np.zeros(len(df))
        pos_in = np.searchsorted(idx.values, funding.index.values, side="right") - 1
        ok = (pos_in >= 0) & (pos_in < len(df))
        np.add.at(acc, pos_in[ok], funding.values[ok])
        sr = sr - held * acc          # 롱 보유 중이면 펀딩 지불
        fcost = float((held * acc).sum() * 100)

    eq = np.cumprod(1 + sr)
    total = (eq[-1] - 1) * 100 if eq[-1] > 0 else -100.0
    bh = (np.prod(1 + r) - 1) * 100
    mdd = (eq / np.maximum.accumulate(eq) - 1).min() * 100 if eq[-1] > 0 else -100.0
    return {"total": total, "bh": bh, "mdd": mdd, "funding_cost": fcost,
            "trades": int((turn > 0).sum())}


# ══════════════════════════════════════════════════════════════
def run_extended(interval: str, use_funding: bool):
    syms = available_symbols(interval)
    new = [s for s in syms if s not in BASE6]
    print("=" * 96)
    print(f"  [1] MA롱온리({FAST_DAYS}d/{SLOW_DAYS}d) {interval} 재검증")
    print(f"      전략 선택에 쓴 6종 = {len(BASE6)}개 / 처음 보는 심볼 = {len(new)}개")
    print("=" * 96)
    if not new:
        print("\n  ⚠️ 확장 심볼 데이터 없음 — 워크플로 수집 완료 후 다시 실행")
        return None

    rows = []
    for s in syms:
        df = load_sym(s, interval)
        if len(df) < SLOW_DAYS * BPD[interval] + 60:
            continue
        fund = load_funding(s) if use_funding else None
        res = backtest(df, ma_long_only(df, interval), fund)
        rows.append({"symbol": s, "신규": s not in BASE6, **res,
                     "초과": res["total"] - res["bh"]})

    out = pd.DataFrame(rows)
    if out.empty:
        print("\n  데이터 부족"); return None

    for label, sub in [("기존 6종 (선택에 사용됨)", out[~out["신규"]]),
                       ("신규 심볼 (진짜 OOS)",     out[out["신규"]])]:
        if sub.empty:
            continue
        win = int((sub["초과"] > 0).sum()); n = len(sub)
        print(f"\n  ── {label} ──")
        print(f"     존버 이김: {win}/{n} ({win/n*100:.0f}%)   "
              f"전략 중앙값 {sub['total'].median():,.0f}%   존버 중앙값 {sub['bh'].median():,.0f}%")
        if use_funding and sub["funding_cost"].abs().sum() > 0:
            print(f"     펀딩비 누적: 중앙값 {sub['funding_cost'].median():.1f}%")
        try:
            from scipy import stats
            pv = stats.binomtest(win, n, 0.5, alternative="greater").pvalue
            print(f"     우연일 확률(p): {pv:.2e}")
        except Exception:
            pass

    print(f"\n  {'심볼':11s}{'구분':>6s}{'전략%':>12s}{'존버%':>12s}{'초과%p':>12s}{'MDD%':>9s}{'펀딩%':>9s}")
    print("  " + "-" * 74)
    for _, r in out.sort_values("초과", ascending=False).iterrows():
        tag = "신규" if r["신규"] else "기존"
        flag = "✅" if r["초과"] > 0 else "  "
        print(f"  {r['symbol']:11s}{tag:>6s}{r['total']:>11,.0f}%{r['bh']:>11,.0f}%"
              f"{r['초과']:>11,.0f}%{r['mdd']:>8.1f}%{r['funding_cost']:>8.1f}% {flag}")

    out.to_csv(f"ml/saved_models/extended_{interval}.csv", index=False)
    return out


def run_cross_sectional(interval: str, top_n: int, rebal_days: int, use_funding: bool):
    """매 리밸런싱일에 모멘텀 상위 N종만 보유"""
    syms = available_symbols(interval)
    print(f"\n{'='*96}")
    print(f"  [3] 횡단면 전략 — 매 {rebal_days}일 모멘텀 상위 {top_n}종 보유 ({len(syms)}종 유니버스)")
    print("=" * 96)
    if len(syms) < 12:
        print(f"\n  ⚠️ 유니버스 {len(syms)}종 — 횡단면은 최소 12종 필요. 수집 후 재실행")
        return

    closes = {}
    for s in syms:
        df = load_sym(s, interval)
        if len(df) < 300:
            continue
        closes[s] = df.set_index("datetime")["close"]
    px = pd.DataFrame(closes).sort_index()
    px = px[px.index >= "2019-01-01"]
    if px.shape[1] < 12:
        print(f"\n  ⚠️ 유효 종목 {px.shape[1]}종 — 부족"); return

    ret = px.pct_change().fillna(0.0)
    d = BPD[interval]
    lookback = 30 * d
    step = rebal_days * d

    mom = px.pct_change(lookback)
    weights = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    for i in range(lookback, len(px), step):
        row = mom.iloc[i].dropna()
        row = row[row > 0]                       # 하락 종목은 아예 제외 (롱온리)
        if row.empty:
            continue
        picks = row.nlargest(top_n).index
        weights.iloc[i:i+step, weights.columns.get_indexer(picks)] = 1.0 / top_n

    w = weights.shift(1).fillna(0.0)
    turn = w.diff().abs().sum(axis=1).fillna(0.0)
    port = (w * ret).sum(axis=1) - turn * (FEE + SLIP)
    bh = ret.mean(axis=1)

    def stat(x):
        eq = np.cumprod(1 + x.values)
        if eq[-1] <= 0: return -100.0, -100.0
        return (eq[-1]-1)*100, (eq/np.maximum.accumulate(eq)-1).min()*100

    pt, pm = stat(port); bt, bm = stat(bh)
    print(f"\n  기간 {px.index[0].date()} ~ {px.index[-1].date()}   유니버스 {px.shape[1]}종")
    print(f"\n  {'전략':28s}{'수익률%':>14s}{'MDD%':>10s}")
    print("  " + "-" * 54)
    print(f"  {'동일가중 존버':28s}{bt:>13,.0f}%{bm:>9.1f}%")
    print(f"  {f'모멘텀 상위{top_n}종':28s}{pt:>13,.0f}%{pm:>9.1f}%"
          f"   {'✅' if pt > bt else ''}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intervals", nargs="*", default=["1d", "4h"])
    ap.add_argument("--top-n", type=int, default=5)
    ap.add_argument("--rebal-days", type=int, default=7)
    ap.add_argument("--no-funding", action="store_true")
    ap.add_argument("--skip-cross", action="store_true")
    a = ap.parse_args()

    use_funding = not a.no_funding
    nf = len(glob.glob("data/funding/*_funding.csv.gz"))
    print(f"\n  펀딩비 파일: {nf}개 {'(반영함)' if use_funding and nf else '(없음 — 미반영)'}")

    for iv in a.intervals:
        run_extended(iv, use_funding)
        if not a.skip_cross:
            run_cross_sectional(iv, a.top_n, a.rebal_days, use_funding)


if __name__ == "__main__":
    main()
