"""
ml/indicator_backtest.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
수집된 전 지표를 진입 필터로 걸고 자본곡선으로 판정한다

지금까지 지표를 하나씩 따로 봤다(펀딩비, 고래지표). 여기서는
수집된 것 전부를 같은 기준으로 한 번에 돌린다.

판정 기준은 "거래당 평균수익률"이 아니라 **자본곡선**이다.
거래당이 올라가도 거래 수가 줄면 복리로는 손해다. 펀딩 z>1이
정확히 그랬다 — 거래당 +11%로 전 구간 최고였는데 자본은
1.98배(필터 없음 89.91배)였다.

검증하는 지표
  종목별   펀딩비 (2020~), 미결제약정·고래/개미 롱숏비율 (2023~)
  시장전체 공포탐욕지수 (2018~), 구글트렌드 (2017~),
           거시경제 S&P·나스닥·금·달러·VIX·미10년 (2016~)

공정한 비교를 위해
  · 지표마다 덮는 구간이 다르다. 필터를 건 것과 안 건 것을 비교할 때
    반드시 **같은 거래 집합** 위에서 비교한다(그 지표를 대조할 수
    있는 거래만 기준선으로 삼는다).
  · 학습(2017~2023)/홀드아웃(2024~)을 갈라서 따로 보고한다.
    학습에서만 좋은 것은 채택하지 않는다.
  · 수십 개를 시험하면 그중 몇 개는 우연히 좋아 보인다. 시험 횟수를
    세서 본페로니 기준을 같이 표시한다.

⚠️ 미결제약정·롱숏비율은 아카이브가 2023-01부터라 학습 구간을
   못 덮는다. 그 지표들은 교차검증이 불가능하므로 관찰로만 읽는다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, glob, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from ml.backtest_current_bot import build_all, simulate

LEV, PT, CB, COOL = 2.0, 0.05, 0.25, 30
TRAIN_END = pd.Timestamp("2024-01-01")
Z_WIN_D = 90        # 일 단위 지표의 z 기간
Z_WIN_4H = 120      # 4시간봉 지표의 z 기간 (=20일)


def _z(s: pd.Series, win: int) -> pd.Series:
    r = s.rolling(win, min_periods=max(20, win // 4))
    return (s - r.mean()) / r.std()


# ── 시장 전체 지표: 하나의 일자 인덱스 표로 합친다 ──────────────
def load_market() -> pd.DataFrame:
    frames = []

    f = "data/indicators/fear_greed_index.csv"
    if os.path.exists(f):
        d = pd.read_csv(f, parse_dates=["date"]).dropna(subset=["date"])
        d = d.set_index("date").sort_index()
        m = pd.DataFrame(index=d.index)
        m["fng"] = pd.to_numeric(d["fear_greed"], errors="coerce")
        m["fng_z"] = _z(m["fng"], Z_WIN_D)
        # 20일 전 대비 변화 — 수준보다 방향이 뜻이 있을 수 있다
        m["fng_chg"] = m["fng"] - m["fng"].shift(20)
        frames.append(m)

    f = "data/indicators/google_trends_bitcoin.csv"
    if os.path.exists(f):
        d = pd.read_csv(f, parse_dates=["date"]).dropna(subset=["date"])
        d = d.set_index("date").sort_index()
        m = pd.DataFrame(index=d.index)
        m["gt"] = pd.to_numeric(d["google_trend_bitcoin"], errors="coerce")
        m["gt_z"] = _z(m["gt"], 26)          # 주간 데이터 — 26주
        frames.append(m)

    f = "data/indicators/macro_yahoo_finance.csv"
    if os.path.exists(f):
        d = pd.read_csv(f, parse_dates=["date"]).dropna(subset=["date"])
        d = d.set_index("date").sort_index()
        m = pd.DataFrame(index=d.index)
        for c in ["sp500", "nasdaq", "gold", "dxy", "vix", "us10y"]:
            if c not in d.columns:
                continue
            v = pd.to_numeric(d[c], errors="coerce")
            m[f"{c}_z"] = _z(v, Z_WIN_D)
            # 지수는 수준보다 최근 추세가 뜻이 있다 (20일 수익률)
            m[f"{c}_r20"] = (v / v.shift(20) - 1) * 100
        frames.append(m)

    if not frames:
        return pd.DataFrame()
    # 각기 다른 주기(일/주)를 일자로 펴서 앞선 값을 이어 쓴다.
    # ffill이라 미래를 보지 않는다 — 항상 "그 시점에 이미 알던 값"이다.
    idx = pd.date_range(min(f.index.min() for f in frames),
                        max(f.index.max() for f in frames), freq="D")
    out = pd.concat([f.reindex(idx).ffill() for f in frames], axis=1)
    return out


# ── 종목별 지표 ────────────────────────────────────────────
def load_funding() -> dict[str, pd.DataFrame]:
    out = {}
    for f in sorted(glob.glob("data/funding/*_funding.csv.gz")):
        sym = os.path.basename(f).split("_")[0]
        d = pd.read_csv(f, compression="gzip", parse_dates=["datetime"])
        d = d.dropna(subset=["datetime"]).sort_values("datetime")
        d["fr_bps"] = d["funding_rate"] * 10000
        d["fr_z"] = _z(d["fr_bps"], 270)
        out[sym] = d[["datetime", "fr_bps", "fr_z"]].rename(
            columns={"datetime": "timestamp"})
    return out


def load_metrics() -> dict[str, pd.DataFrame]:
    out = {}
    for f in sorted(glob.glob("data/metrics/*_metrics_4h.csv.gz")):
        sym = os.path.basename(f).split("_")[0]
        d = pd.read_csv(f, compression="gzip", parse_dates=["timestamp"])
        d = d.dropna(subset=["timestamp"]).sort_values("timestamp")
        d["whale_z"] = _z(d["sum_toptrader_long_short_ratio"], Z_WIN_4H)
        d["retail_z"] = _z(d["count_long_short_ratio"], Z_WIN_4H)
        d["taker_z"] = _z(d["sum_taker_long_short_vol_ratio"], Z_WIN_4H)
        oi = d["sum_open_interest"]
        d["oi_z"] = _z((oi / oi.shift(Z_WIN_4H) - 1) * 100, Z_WIN_4H)
        d["gap"] = d["whale_z"] - d["retail_z"]
        out[sym] = d[["timestamp", "whale_z", "retail_z", "taker_z", "oi_z", "gap"]]
    return out


def attach(trades, market, per_sym: dict[str, dict]):
    """각 거래에 진입 판단 시점(신호봉 종가)에 이미 확정돼 있던 값만 붙인다."""
    mcols = list(market.columns)
    midx = market.index
    out = []
    for t in trades:
        dt = pd.Timestamp(t["dt"])
        t = dict(t)
        k = midx.searchsorted(dt, side="right") - 1
        for c in mcols:
            t[c] = market[c].iloc[k] if k >= 0 else np.nan
        for _, tbl in per_sym.items():
            d = tbl.get(t["sym"])
            cols = [c for c in (d.columns if d is not None else []) if c != "timestamp"]
            if d is None:
                continue
            j = d["timestamp"].searchsorted(dt, side="right") - 1
            for c in cols:
                t[c] = d[c].iloc[j] if j >= 0 else np.nan
        out.append(t)
    return out


def curve(sub, yrs):
    r = simulate(sub, LEV, PT, 1.0, CB, COOL, 1e-6, compound=True)
    r["cagr"] = (r["final"] ** (1 / yrs) - 1) * 100 if r["final"] > 0 else -100
    return r


def span_years(sub):
    a, b = pd.Timestamp(sub[0]["dt"]), pd.Timestamp(sub[-1]["dt"])
    return max((b - a).days / 365, 0.5)


def evaluate(base, name, fn, min_n=40):
    """같은 거래 집합 위에서 필터 유무를 비교한다."""
    have = [t for t in base if not pd.isna(t.get(fn.col, np.nan))]
    if len(have) < min_n:
        return None
    sub = [t for t in have if fn(t)]
    if len(sub) < min_n:
        return None
    yrs = span_years(have)
    ref, got = curve(have, yrs), curve(sub, yrs)
    tr_h = [t for t in have if pd.Timestamp(t["dt"]) < TRAIN_END]
    tr_s = [t for t in sub if pd.Timestamp(t["dt"]) < TRAIN_END]
    ho_h = [t for t in have if pd.Timestamp(t["dt"]) >= TRAIN_END]
    ho_s = [t for t in sub if pd.Timestamp(t["dt"]) >= TRAIN_END]
    def ratio(a, b):
        if len(a) < 20 or len(b) < 20:
            return np.nan
        return curve(a, span_years(b))["final"] / curve(b, span_years(b))["final"]
    return {"name": name, "n": len(sub), "n_ref": len(have),
            "mult": got["final"], "ref": ref["final"],
            "gain": got["final"] / ref["final"] if ref["final"] > 0 else np.nan,
            "tr_gain": ratio(tr_s, tr_h), "ho_gain": ratio(ho_s, ho_h),
            "mdd": got["mdd"] * 100, "ref_mdd": ref["mdd"] * 100,
            "cover": f"{pd.Timestamp(have[0]['dt']).year}~"}


class F:
    """필터 하나. col은 '이 지표를 대조할 수 있는가' 판정에 쓴다."""
    def __init__(self, col, fn):
        self.col, self.fn = col, fn
    def __call__(self, t):
        return bool(self.fn(t))


def main():
    market = load_market()
    per_sym = {"funding": load_funding(), "metrics": load_metrics()}
    trades, have, _ = build_all()
    trades = attach(trades, market, per_sym)

    print("=" * 104)
    print("  수집된 전 지표 × 과매도 규칙 — 자본곡선으로 판정 (복리 · 2배 · 진입당 5%)")
    print("=" * 104)
    print(f"\n  신호 {len(trades):,}건 · 종목 {len(have)}종")
    print(f"  시장지표 {market.shape[1]}개 컬럼, {market.index.min().date()}~{market.index.max().date()}")
    print(f"  종목별지표 펀딩 {len(per_sym['funding'])}종 · 메트릭 {len(per_sym['metrics'])}종")

    TESTS = [
        # ── 공포탐욕지수 (2018~) — 학습·홀드아웃 모두 덮는다
        ("공포탐욕 < 20 (극단공포)",   F("fng", lambda t: t["fng"] < 20)),
        ("공포탐욕 < 30",             F("fng", lambda t: t["fng"] < 30)),
        ("공포탐욕 < 50",             F("fng", lambda t: t["fng"] < 50)),
        ("공포탐욕 > 50",             F("fng", lambda t: t["fng"] > 50)),
        ("공포탐욕 > 70 (극단탐욕)",   F("fng", lambda t: t["fng"] > 70)),
        ("공포탐욕 z < -1",           F("fng_z", lambda t: t["fng_z"] < -1)),
        ("공포탐욕 z > 1",            F("fng_z", lambda t: t["fng_z"] > 1)),
        ("공포탐욕 20일 하락",         F("fng_chg", lambda t: t["fng_chg"] < -10)),
        ("공포탐욕 20일 상승",         F("fng_chg", lambda t: t["fng_chg"] > 10)),
        # ── 구글트렌드 (2017~)
        ("구글트렌드 z > 1 (관심급증)", F("gt_z", lambda t: t["gt_z"] > 1)),
        ("구글트렌드 z < -0.5",        F("gt_z", lambda t: t["gt_z"] < -0.5)),
        # ── 거시경제 (2016~)
        ("VIX z > 1 (공포)",          F("vix_z", lambda t: t["vix_z"] > 1)),
        ("VIX z < 0 (안정)",          F("vix_z", lambda t: t["vix_z"] < 0)),
        ("S&P 20일 상승",             F("sp500_r20", lambda t: t["sp500_r20"] > 0)),
        ("S&P 20일 하락",             F("sp500_r20", lambda t: t["sp500_r20"] < 0)),
        ("나스닥 20일 상승",           F("nasdaq_r20", lambda t: t["nasdaq_r20"] > 0)),
        ("나스닥 20일 -5% 이하",       F("nasdaq_r20", lambda t: t["nasdaq_r20"] < -5)),
        ("달러 약세 (dxy 20일 하락)",  F("dxy_r20", lambda t: t["dxy_r20"] < 0)),
        ("달러 강세 (dxy 20일 상승)",  F("dxy_r20", lambda t: t["dxy_r20"] > 0)),
        ("금 20일 상승",              F("gold_r20", lambda t: t["gold_r20"] > 0)),
        ("미10년 z > 1 (금리급등)",    F("us10y_z", lambda t: t["us10y_z"] > 1)),
        ("미10년 z < -1 (금리급락)",   F("us10y_z", lambda t: t["us10y_z"] < -1)),
        # ── 펀딩비 (2020~)
        ("펀딩 < 0 (숏 과밀)",         F("fr_bps", lambda t: t["fr_bps"] < 0)),
        ("펀딩 > 0 (롱 과밀)",         F("fr_bps", lambda t: t["fr_bps"] > 0)),
        ("펀딩 z < -1",               F("fr_z", lambda t: t["fr_z"] < -1)),
        ("펀딩 z > 1",                F("fr_z", lambda t: t["fr_z"] > 1)),
        # ── 고래지표 (2023~, 교차검증 불가)
        ("고래 롱 쏠림 z>0.5",         F("whale_z", lambda t: t["whale_z"] > 0.5)),
        ("고래 숏 쏠림 z<-0.5",        F("whale_z", lambda t: t["whale_z"] < -0.5)),
        ("개미 롱 쏠림 z>0.5",         F("retail_z", lambda t: t["retail_z"] > 0.5)),
        ("고래>개미 괴리 >0.5",        F("gap", lambda t: t["gap"] > 0.5)),
        ("고래<개미 괴리 <-0.5",       F("gap", lambda t: t["gap"] < -0.5)),
        ("OI 급증 z>1",               F("oi_z", lambda t: t["oi_z"] > 1)),
        ("OI 급감 z<-1",              F("oi_z", lambda t: t["oi_z"] < -1)),
        ("시장가 매도우위 z<-0.5",      F("taker_z", lambda t: t["taker_z"] < -0.5)),
    ]

    rows = []
    for name, fn in TESTS:
        r = evaluate(trades, name, fn)
        if r:
            rows.append(r)

    print(f"\n  시험한 필터 {len(rows)}개 "
          f"(본페로니 기준: 우연히 하나쯤 좋아 보일 확률을 5%로 묶으려면 "
          f"개별 유의수준 {5/max(len(rows),1):.2f}% 필요)")
    print(f"\n  '배수'는 같은 거래집합에서 필터 없이 굴린 결과 대비다. "
          f"1.00 미만이면 필터가 손해다.")
    print(f"\n  {'필터':<26s}{'거래':>7s}{'/기준':>7s}{'배수':>7s}"
          f"{'학습배수':>9s}{'홀드배수':>9s}{'낙폭':>8s}{'기준낙폭':>9s}  덮는구간")
    print("  " + "-" * 96)
    for r in sorted(rows, key=lambda x: -x["gain"]):
        tr = f"{r['tr_gain']:.2f}" if not np.isnan(r["tr_gain"]) else "  —"
        ho = f"{r['ho_gain']:.2f}" if not np.isnan(r["ho_gain"]) else "  —"
        mark = "  ✅" if (r["gain"] > 1 and (np.isnan(r["tr_gain"]) or r["tr_gain"] > 1)
                          and (np.isnan(r["ho_gain"]) or r["ho_gain"] > 1)) else ""
        print(f"  {r['name']:<26s}{r['n']:>7d}{r['n_ref']:>7d}{r['gain']:>7.2f}"
              f"{tr:>9s}{ho:>9s}{r['mdd']:>7.1f}%{r['ref_mdd']:>8.1f}%  {r['cover']}{mark}")

    win = [r for r in rows if r["gain"] > 1]
    both = [r for r in win if (np.isnan(r["tr_gain"]) or r["tr_gain"] > 1)
            and (np.isnan(r["ho_gain"]) or r["ho_gain"] > 1)]
    print(f"\n  ── 정리")
    print(f"    필터 없음보다 나은 것            {len(win):>2d} / {len(rows)}")
    print(f"    학습·홀드아웃 양쪽에서 나은 것     {len(both):>2d} / {len(rows)}")
    if both:
        print(f"\n    양쪽 통과 목록")
        for r in sorted(both, key=lambda x: -x["gain"]):
            print(f"      {r['name']:<26s} 전체 {r['gain']:.2f}배 "
                  f"(학습 {r['tr_gain']:.2f} · 홀드 {r['ho_gain']:.2f}) · 거래 {r['n']}건")
    else:
        print(f"\n    없다. 지표 어느 것도 이 규칙을 개선하지 못한다.")


if __name__ == "__main__":
    main()
