"""
ml/coin_indicator_backtest.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
코인 데이터에서 나오는 지표만으로 진입 필터를 판정한다

ml/indicator_backtest.py는 거시경제(나스닥·S&P·금·달러·VIX·미10년)
까지 섞어 32개를 돌렸다. 여기서는 그걸 빼고 코인 안에서 나오는
것만 본다. 대신 **아직 한 번도 안 본 것들**을 추가한다 —
지금까지 검증한 지표는 전부 외부에서 받아온 것이었고,
정작 이미 가진 시세 데이터로 만들 수 있는 것을 안 봤다.

새로 만드는 지표 (전부 2017년부터 있어 교차검증이 제대로 된다)
  BTC 추세      BTC가 MA50/MA200 위인가 — 강세장/약세장 구분
  BTC 변동성    최근 20일 실현변동성
  시장 폭       42종 중 MA20 위에 있는 비율 — 시장 전체 건강도
  동시 신호     같은 날 몇 종목이 과매도인가
                (혼자 빠진 것 vs 시장 전체가 무너진 것은 다른 사건이다.
                 이 규칙이 되돌림에 베팅하는 이상 이 구분이 핵심일 수 있다)
  알트 상대강도 BTC 대비 알트 전체의 20일 초과수익
  종목 거래량   그 종목의 거래량이 평소 대비 얼마나 터졌나
  종목 변동성   그 종목의 최근 변동성

기존 지표 (외부 수집)
  펀딩비 (2020~) · 미결제약정/고래·개미 롱숏 (2023~)
  크립토 공포탐욕 (2018~) · 구글트렌드 비트코인 (2017~)

판정은 자본곡선이다. 거래당 평균이 아니라. 그리고 필터마다 덮는
구간이 다르므로 같은 거래집합 위에서만 비교한다.
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
from bot.oversold import strategy as S
from ml.backtest_current_bot import build_all, simulate, load
from ml.indicator_backtest import (_z, load_funding, load_metrics,
                                   curve, span_years, TRAIN_END, F)


def build_coin_market() -> pd.DataFrame:
    """42종 4시간봉에서 시장 전체 상태를 만든다.

    4시간봉 그대로 쓴다 — 신호도 4시간봉이라 시점이 정확히 맞는다.
    모든 값은 해당 봉 종가까지만 쓰므로 미래를 보지 않는다.
    """
    closes, vols = {}, {}
    for sym in S.SYMBOLS:
        g = load(sym)
        if g is None:
            continue
        d = g.set_index("datetime")
        closes[sym] = d["close"].astype(float)
        if "volume" in d.columns:
            vols[sym] = d["volume"].astype(float)
    C = pd.DataFrame(closes).sort_index()
    V = pd.DataFrame(vols).reindex(C.index)

    m = pd.DataFrame(index=C.index)

    # ── BTC 추세 (4시간봉 기준: 50일=300봉, 200일=1200봉)
    btc = C["BTCUSDT"] if "BTCUSDT" in C else C.iloc[:, 0]
    m["btc_ma50"] = (btc / btc.rolling(300).mean() - 1) * 100
    m["btc_ma200"] = (btc / btc.rolling(1200).mean() - 1) * 100
    r = btc.pct_change()
    m["btc_vol"] = r.rolling(120).std() * np.sqrt(6 * 365) * 100   # 연율 변동성
    m["btc_vol_z"] = _z(m["btc_vol"], 720)
    m["btc_r20d"] = (btc / btc.shift(120) - 1) * 100

    # ── 시장 폭: MA20(4h) 위에 있는 종목 비율
    ma20 = C.rolling(20).mean()
    above = (C > ma20)
    listed = C.notna()
    m["breadth"] = (above.sum(axis=1) / listed.sum(axis=1).replace(0, np.nan)) * 100

    # ── 동시 신호 개수: 같은 봉에 과매도 조건을 만족한 종목 수
    vs = (C / ma20 - 1) * 100
    sig = (vs <= S.ENTRY_THRESH)
    m["n_signal"] = sig.sum(axis=1)
    m["n_signal_pct"] = (sig.sum(axis=1) / listed.sum(axis=1).replace(0, np.nan)) * 100

    # ── 알트 상대강도: BTC 제외 균등 대비 BTC의 20일 초과수익
    alt = C.drop(columns=["BTCUSDT"], errors="ignore")
    alt_r = (alt / alt.shift(120) - 1).mean(axis=1) * 100
    m["alt_minus_btc"] = alt_r - m["btc_r20d"]

    # ── 종목별: 거래량 급증 / 변동성 (여기선 표로 두고 나중에 붙인다)
    volz = (V / V.rolling(120).mean()) if not V.empty else None
    symvol = C.pct_change().rolling(120).std() * np.sqrt(6 * 365) * 100
    return m, volz, symvol


def attach(trades, market, per_sym, volz, symvol):
    mcols = list(market.columns)
    midx = market.index
    out = []
    for t in trades:
        dt = pd.Timestamp(t["dt"])
        t = dict(t)
        k = midx.searchsorted(dt, side="right") - 1
        for c in mcols:
            t[c] = market[c].iloc[k] if k >= 0 else np.nan
        # 종목별 시세 파생
        for tbl, name in [(volz, "vol_ratio"), (symvol, "sym_vol")]:
            v = np.nan
            if tbl is not None and t["sym"] in tbl.columns:
                j = tbl.index.searchsorted(dt, side="right") - 1
                if j >= 0:
                    v = tbl[t["sym"]].iloc[j]
            t[name] = v
        # 외부 수집 지표
        for tbl in per_sym.values():
            d = tbl.get(t["sym"])
            if d is None:
                continue
            j = d["timestamp"].searchsorted(dt, side="right") - 1
            for c in d.columns:
                if c == "timestamp":
                    continue
                t[c] = d[c].iloc[j] if j >= 0 else np.nan
        out.append(t)
    return out


def load_crypto_sentiment() -> pd.DataFrame:
    """크립토 공포탐욕 + 비트코인 구글트렌드 (둘 다 코인 지표다)."""
    frames = []
    f = "data/indicators/fear_greed_index.csv"
    if os.path.exists(f):
        d = pd.read_csv(f, parse_dates=["date"]).dropna(subset=["date"]).set_index("date")
        m = pd.DataFrame(index=d.index)
        m["fng"] = pd.to_numeric(d["fear_greed"], errors="coerce")
        m["fng_z"] = _z(m["fng"], 90)
        frames.append(m)
    f = "data/indicators/google_trends_bitcoin.csv"
    if os.path.exists(f):
        d = pd.read_csv(f, parse_dates=["date"]).dropna(subset=["date"]).set_index("date")
        m = pd.DataFrame(index=d.index)
        m["gt_z"] = _z(pd.to_numeric(d["google_trend_bitcoin"], errors="coerce"), 26)
        frames.append(m)
    if not frames:
        return pd.DataFrame()
    idx = pd.date_range(min(f.index.min() for f in frames),
                        max(f.index.max() for f in frames), freq="D")
    return pd.concat([f.reindex(idx).ffill() for f in frames], axis=1)


def evaluate(base, name, fn, min_n=40):
    have = [t for t in base if not pd.isna(t.get(fn.col, np.nan))]
    if len(have) < min_n:
        return None
    sub = [t for t in have if fn(t)]
    if len(sub) < min_n:
        return None
    yrs = span_years(have)
    ref, got = curve(have, yrs), curve(sub, yrs)
    def ratio(a, b):
        if len(a) < 20 or len(b) < 20:
            return np.nan
        return curve(a, span_years(b))["final"] / curve(b, span_years(b))["final"]
    tr_h = [t for t in have if pd.Timestamp(t["dt"]) < TRAIN_END]
    tr_s = [t for t in sub if pd.Timestamp(t["dt"]) < TRAIN_END]
    ho_h = [t for t in have if pd.Timestamp(t["dt"]) >= TRAIN_END]
    ho_s = [t for t in sub if pd.Timestamp(t["dt"]) >= TRAIN_END]
    return {"name": name, "n": len(sub), "n_ref": len(have),
            "gain": got["final"] / ref["final"] if ref["final"] > 0 else np.nan,
            "tr_gain": ratio(tr_s, tr_h), "ho_gain": ratio(ho_s, ho_h),
            "mdd": got["mdd"] * 100, "ref_mdd": ref["mdd"] * 100,
            "cover": f"{pd.Timestamp(have[0]['dt']).year}~"}


def main():
    market, volz, symvol = build_coin_market()
    senti = load_crypto_sentiment()
    if not senti.empty:
        market = market.join(senti.reindex(market.index, method="ffill"))
    per_sym = {"funding": load_funding(), "metrics": load_metrics()}
    trades, have, _ = build_all()
    trades = attach(trades, market, per_sym, volz, symvol)

    print("=" * 104)
    print("  코인 지표만 × 과매도 규칙 — 자본곡선으로 판정 (복리 · 2배 · 진입당 5%)")
    print("  거시경제(나스닥·S&P·금·달러·VIX·미10년) 제외")
    print("=" * 104)
    print(f"\n  신호 {len(trades):,}건 · 종목 {len(have)}종 · "
          f"시장지표 {market.index[0].date()}~{market.index[-1].date()}")

    TESTS = [
        # ── 시세에서 직접 만든 것 (2017~, 교차검증 제대로 됨)
        ("BTC > MA50 (강세)",        F("btc_ma50",  lambda t: t["btc_ma50"] > 0)),
        ("BTC < MA50 (약세)",        F("btc_ma50",  lambda t: t["btc_ma50"] < 0)),
        ("BTC > MA200 (장기강세)",    F("btc_ma200", lambda t: t["btc_ma200"] > 0)),
        ("BTC < MA200 (장기약세)",    F("btc_ma200", lambda t: t["btc_ma200"] < 0)),
        ("BTC 20일 상승",            F("btc_r20d",  lambda t: t["btc_r20d"] > 0)),
        ("BTC 20일 -10% 이하",       F("btc_r20d",  lambda t: t["btc_r20d"] < -10)),
        ("BTC 변동성 z > 1 (급등락)", F("btc_vol_z", lambda t: t["btc_vol_z"] > 1)),
        ("BTC 변동성 z < 0 (잔잔)",   F("btc_vol_z", lambda t: t["btc_vol_z"] < 0)),
        ("시장 폭 > 50% (건강)",      F("breadth",   lambda t: t["breadth"] > 50)),
        ("시장 폭 < 30% (약세)",      F("breadth",   lambda t: t["breadth"] < 30)),
        ("시장 폭 < 15% (투매)",      F("breadth",   lambda t: t["breadth"] < 15)),
        ("동시신호 1~2종 (개별하락)",  F("n_signal",  lambda t: t["n_signal"] <= 2)),
        ("동시신호 3~5종",            F("n_signal",  lambda t: 3 <= t["n_signal"] <= 5)),
        ("동시신호 6종 이상 (동반폭락)", F("n_signal", lambda t: t["n_signal"] >= 6)),
        ("동시신호 10종 이상",         F("n_signal",  lambda t: t["n_signal"] >= 10)),
        ("알트 > BTC (알트강세)",      F("alt_minus_btc", lambda t: t["alt_minus_btc"] > 0)),
        ("알트 < BTC (BTC강세)",      F("alt_minus_btc", lambda t: t["alt_minus_btc"] < 0)),
        ("거래량 평소 2배 이상",        F("vol_ratio", lambda t: t["vol_ratio"] > 2)),
        ("거래량 평소 이하",           F("vol_ratio", lambda t: t["vol_ratio"] < 1)),
        ("종목 변동성 상위 (>150%)",   F("sym_vol",   lambda t: t["sym_vol"] > 150)),
        ("종목 변동성 하위 (<80%)",    F("sym_vol",   lambda t: t["sym_vol"] < 80)),
        # ── 크립토 심리 (2017~2018~)
        ("공포탐욕 < 20 (극단공포)",   F("fng", lambda t: t["fng"] < 20)),
        ("공포탐욕 > 50",             F("fng", lambda t: t["fng"] > 50)),
        ("공포탐욕 z > 1",            F("fng_z", lambda t: t["fng_z"] > 1)),
        ("구글트렌드 z > 1",          F("gt_z", lambda t: t["gt_z"] > 1)),
        # ── 파생시장 (2020~ / 2023~)
        ("펀딩 > 0 (롱 과밀)",        F("fr_bps", lambda t: t["fr_bps"] > 0)),
        ("펀딩 < 0 (숏 과밀)",        F("fr_bps", lambda t: t["fr_bps"] < 0)),
        ("펀딩 z > 1",               F("fr_z", lambda t: t["fr_z"] > 1)),
        ("고래 숏 쏠림 z<-0.5",       F("whale_z", lambda t: t["whale_z"] < -0.5)),
        ("고래<개미 괴리 <-0.5",      F("gap", lambda t: t["gap"] < -0.5)),
        ("OI 급증 z>1",              F("oi_z", lambda t: t["oi_z"] > 1)),
        ("시장가 매도우위 z<-0.5",     F("taker_z", lambda t: t["taker_z"] < -0.5)),
    ]

    rows = [r for r in (evaluate(trades, n, f) for n, f in TESTS) if r]
    print(f"\n  시험한 필터 {len(rows)}개 (본페로니 개별 유의수준 "
          f"{5/max(len(rows),1):.2f}% 필요)")
    print(f"  '배수' = 같은 거래집합에서 필터 없이 굴린 결과 대비. 1.00 미만이면 손해.\n")
    print(f"  {'필터':<26s}{'거래':>7s}{'/기준':>7s}{'배수':>7s}"
          f"{'학습배수':>9s}{'홀드배수':>9s}{'낙폭':>8s}{'기준낙폭':>9s}  구간")
    print("  " + "-" * 96)
    for r in sorted(rows, key=lambda x: -x["gain"]):
        tr = f"{r['tr_gain']:.2f}" if not np.isnan(r["tr_gain"]) else "  —"
        ho = f"{r['ho_gain']:.2f}" if not np.isnan(r["ho_gain"]) else "  —"
        ok = (r["gain"] > 1 and (np.isnan(r["tr_gain"]) or r["tr_gain"] > 1)
              and (np.isnan(r["ho_gain"]) or r["ho_gain"] > 1))
        print(f"  {r['name']:<26s}{r['n']:>7d}{r['n_ref']:>7d}{r['gain']:>7.2f}"
              f"{tr:>9s}{ho:>9s}{r['mdd']:>7.1f}%{r['ref_mdd']:>8.1f}%  "
              f"{r['cover']}{'  ✅' if ok else ''}")

    win = [r for r in rows if r["gain"] > 1]
    both = [r for r in win if (np.isnan(r["tr_gain"]) or r["tr_gain"] > 1)
            and (np.isnan(r["ho_gain"]) or r["ho_gain"] > 1)]
    print(f"\n  ── 정리")
    print(f"    필터 없음보다 나은 것          {len(win):>2d} / {len(rows)}")
    print(f"    학습·홀드아웃 양쪽에서 나은 것   {len(both):>2d} / {len(rows)}")
    if both:
        print(f"\n    ✅ 양쪽 통과")
        for r in sorted(both, key=lambda x: -x["gain"]):
            print(f"      {r['name']:<26s} 전체 {r['gain']:.2f}배 "
                  f"(학습 {r['tr_gain']:.2f} · 홀드 {r['ho_gain']:.2f}) · "
                  f"거래 {r['n']}/{r['n_ref']}건 · 낙폭 {r['mdd']:.0f}%(기준 {r['ref_mdd']:.0f}%)")
    else:
        print(f"\n    없다.")


if __name__ == "__main__":
    main()
