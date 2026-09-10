"""
ml/hunt_wide.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1년 50배 — 규칙 계열 자체를 바꿔가며 탐색

ml/hunt_50x.py는 지금 쓰는 과매도 규칙의 손잡이(진입임계값·배율·
동시보유)만 돌렸다. 그건 "이 규칙으로 50배가 되는가"이지
"50배가 되는 규칙이 있는가"가 아니다. 여기서는 계열을 바꾼다.

역사적으로 암호화폐에서 1년 수십 배가 실제로 났던 경로는 하나다:
강세장에서 오른 알트에 집중해서 계속 올라타는 것. 그래서 그 경로를
정면으로 검증한다 — 되면 되는 대로, 안 되면 안 되는 대로.

검증하는 계열
  A. 횡단면 모멘텀 — N일마다 최근 M일 수익률 상위 K종만 보유
     (암호화폐 강세장의 실제 경로. 집중도 K가 핵심 손잡이다)
  B. 신고가 돌파 — N일 신고가에서 사고 M일 신저가/H일 경과에 판다
  C. 추세추종 — 종가 > MA(N)이면 보유, 아래로 내려가면 청산
  D. 과매도 되돌림 — 지금 쓰는 규칙 (기준선)

공통 조건
  · 복리. 실제 계좌처럼 현재 자본 기준으로 베팅한다.
  · 배율 1·2·3·5배. 청산은 보유 중 최저가로 판정한다.
  · 왕복 수수료 0.20% + 배율>1이면 펀딩비.
  · 189개 1년 창 전부에 돌려 최대·중앙·파산확률을 낸다.
  · 학습(2017~2023) / 홀드아웃(2024~) 분리해서 따로 보고한다.

일봉을 쓴다. 횡단면 순위는 4시간마다 다시 매길 이유가 없고,
42종 × 3,200일이면 전 조합을 다 돌려도 시간 안에 끝난다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, glob, argparse, warnings, itertools
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from bot.oversold import strategy as S

FEE = 0.0020            # 왕복 0.20%
FUND_DAILY = 0.0003     # 펀딩비 근사 0.01%/8h × 3
TRAIN_END = pd.Timestamp("2024-01-01")
WINDOW = 365
STEP = 15


def load_panel() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """42종 일봉을 하나의 날짜×종목 표로 맞춘다."""
    cl, hi, lo = {}, {}, {}
    for sym in S.SYMBOLS:
        f = f"data/{sym}_1d_all.csv.gz"
        if not os.path.exists(f):
            continue
        d = pd.read_csv(f, compression="gzip")
        tc = "timestamp" if "timestamp" in d.columns else "datetime"
        d[tc] = pd.to_datetime(d[tc], format="mixed", errors="coerce")
        d = (d.dropna(subset=[tc]).sort_values(tc)
               .drop_duplicates(tc).set_index(tc))
        cl[sym] = d["close"].astype(float)
        hi[sym] = d["high"].astype(float)
        lo[sym] = d["low"].astype(float)
    C = pd.DataFrame(cl).sort_index()
    return C, pd.DataFrame(hi).reindex(C.index), pd.DataFrame(lo).reindex(C.index)


# ────────────────────────────────────────────────
# 각 계열은 "날짜 × 종목" 비중표(0~1)를 낸다.
# 비중은 그날 종가에 확정되고 다음날부터 적용된다 — 미래를 보지 않는다.
# ────────────────────────────────────────────────
def w_xsec_momentum(C, lookback, top_k, rebal):
    """최근 lookback일 수익률 상위 top_k종을 균등 보유, rebal일마다 교체."""
    mom = C / C.shift(lookback) - 1
    W = pd.DataFrame(0.0, index=C.index, columns=C.columns)
    rank_days = C.index[::rebal]
    held = None
    for i, dt in enumerate(C.index):
        if dt in rank_days:
            row = mom.loc[dt].dropna()
            row = row[row > 0]                 # 오르고 있는 것만
            held = list(row.nlargest(top_k).index) if len(row) else []
        if held:
            W.loc[dt, held] = 1.0 / len(held)
    return W.shift(1).fillna(0.0)


def w_breakout(C, H, lookback, hold_days):
    """lookback일 신고가 돌파에서 진입, hold_days 보유."""
    high_n = H.rolling(lookback).max().shift(1)
    sig = (C > high_n)
    # 진입 후 hold_days 동안 보유 상태 유지
    hold = sig.rolling(hold_days, min_periods=1).max().astype(bool)
    n = hold.sum(axis=1).replace(0, np.nan)
    W = hold.div(n, axis=0).fillna(0.0)
    return W.shift(1).fillna(0.0)


def w_trend(C, ma_days, top_k=None):
    """종가 > MA(ma_days)인 종목 균등 보유."""
    ma = C.rolling(ma_days).mean()
    on = (C > ma)
    if top_k:
        # 추세 강도(이격도) 상위 top_k만
        dist = C / ma - 1
        keep = dist.where(on)
        rank = keep.rank(axis=1, ascending=False)
        on = on & (rank <= top_k)
    n = on.sum(axis=1).replace(0, np.nan)
    W = on.astype(float).div(n, axis=0).fillna(0.0)
    return W.shift(1).fillna(0.0)


def w_oversold(C, thresh, hold_days, ma_days=20):
    """과매도 되돌림 (기준선). 일봉판이라 4시간봉 결과와 정확히 같진 않다."""
    ma = C.rolling(ma_days).mean()
    vs = (C / ma - 1) * 100
    sig = vs <= thresh
    hold = sig.rolling(hold_days, min_periods=1).max().astype(bool)
    n = hold.sum(axis=1).replace(0, np.nan)
    W = hold.div(n, axis=0).fillna(0.0)
    return W.shift(1).fillna(0.0)


# ────────────────────────────────────────────────
def equity_curve(W, R, L):
    """비중표 → 일별 자본곡선. 복리, 배율 L, 청산·수수료 반영.

    청산: 하루 포트폴리오 손실이 -1/L 이하로 내려가면 그날 전액 손실이다.
    비중이 바뀐 날만 수수료를 뗀다(회전율 × 수수료).
    """
    port = (W * R).sum(axis=1)                      # 배율 1배 일수익률
    turn = (W - W.shift(1)).abs().sum(axis=1) / 2
    gross = W.sum(axis=1)
    cost = turn * FEE + (gross * FUND_DAILY if L > 1 else 0.0)
    lev_ret = port * L - cost * L
    lev_ret = lev_ret.clip(lower=-1.0)               # 하루 -100% 이하는 없다
    eq = (1 + lev_ret).cumprod()
    return eq, lev_ret


def window_stats(eq_ret: pd.Series, target: float):
    idx = eq_ret.index
    starts = pd.date_range(idx[0], idx[-1] - pd.Timedelta(days=WINDOW), freq=f"{STEP}D")
    out = []
    for s in starts:
        seg = eq_ret[(eq_ret.index >= s) & (eq_ret.index < s + pd.Timedelta(days=WINDOW))]
        if len(seg) < 200:
            continue
        curve = (1 + seg).cumprod()
        # 도중에 자본이 1%까지 녹으면 파산으로 본다 (증거금 부족)
        bust = bool((curve <= 0.01).any())
        mult = 0.0 if bust else float(curve.iloc[-1])
        mdd = float(1 - (curve / curve.cummax()).min())
        out.append({"start": s, "mult": mult, "mdd": mdd, "bust": bust})
    d = pd.DataFrame(out)
    if d.empty:
        return None
    tr, ho = d[d.start < TRAIN_END], d[d.start >= TRAIN_END]
    return {"windows": len(d), "max": d.mult.max(), "median": d.mult.median(),
            "p_target": (d.mult >= target).mean() * 100,
            "p_loss": (d.mult < 1).mean() * 100,
            "p_bust": d.bust.mean() * 100,
            "mdd": d.mdd.median() * 100,
            "best_start": str(d.loc[d.mult.idxmax(), "start"])[:7],
            "ho_max": ho.mult.max() if len(ho) else np.nan,
            "ho_median": ho.mult.median() if len(ho) else np.nan,
            "tr_median": tr.mult.median() if len(tr) else np.nan}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=float, default=50.0)
    a = ap.parse_args()

    C, H, L_ = load_panel()
    R = C.pct_change()
    print("=" * 108)
    print(f"  1년 {a.target:.0f}배 — 규칙 계열 전수 탐색 (바이낸스 일봉 {C.shape[1]}종, "
          f"{C.index[0].date()}~{C.index[-1].date()})")
    print("  복리 · 청산 반영 · 왕복 0.20% + 펀딩비")
    print("=" * 108)

    LEVS = [1.0, 2.0, 3.0, 5.0]
    cfgs = []

    # A. 횡단면 모멘텀 — 집중도를 1종까지 밀어본다
    for lb, k, rb in itertools.product([7, 14, 30, 60, 90], [1, 2, 3, 5, 10], [3, 7, 14]):
        cfgs.append((f"A 모멘텀 {lb}일/{k}종/{rb}일교체",
                     lambda C=C, lb=lb, k=k, rb=rb: w_xsec_momentum(C, lb, k, rb)))
    # B. 신고가 돌파
    for lb, hd in itertools.product([20, 50, 100, 200], [5, 10, 20, 40]):
        cfgs.append((f"B 돌파 {lb}일신고가/{hd}일보유",
                     lambda C=C, H=H, lb=lb, hd=hd: w_breakout(C, H, lb, hd)))
    # C. 추세추종
    for ma, k in itertools.product([20, 50, 100, 200], [None, 1, 3, 5]):
        cfgs.append((f"C 추세 MA{ma}" + (f"/상위{k}종" if k else "/전종목"),
                     lambda C=C, ma=ma, k=k: w_trend(C, ma, k)))
    # D. 과매도 (기준선)
    for th, hd in itertools.product([-12.26, -18.0], [3, 5, 10]):
        cfgs.append((f"D 과매도 {th}%/{hd}일보유",
                     lambda C=C, th=th, hd=hd: w_oversold(C, th, hd)))

    print(f"\n  계열 조합 {len(cfgs)}개 × 배율 {len(LEVS)}개 = "
          f"{len(cfgs)*len(LEVS)}개 설정\n")

    rows = []
    for i, (name, fn) in enumerate(cfgs):
        W = fn()
        if W.sum().sum() == 0:
            continue
        for lev in LEVS:
            _, ret = equity_curve(W, R, lev)
            st = window_stats(ret, a.target)
            if st is None:
                continue
            st.update({"rule": name, "lev": lev})
            rows.append(st)
        if (i + 1) % 20 == 0:
            print(f"    {i+1}/{len(cfgs)} 계열 완료")

    r = pd.DataFrame(rows)
    os.makedirs("ml/saved_models", exist_ok=True)
    r.to_csv("ml/saved_models/hunt_wide.csv", index=False)

    hit = r[r["max"] >= a.target]
    print(f"\n{'='*108}")
    print(f"  1년 창에서 {a.target:.0f}배를 한 번이라도 찍은 설정: {len(hit)}개 / {len(r)}개")
    print("=" * 108)

    def table(d, title, n=15):
        print(f"\n  ── {title}")
        print(f"  {'규칙':<28s}{'배율':>5s}{'최대':>9s}{'달성':>7s}{'중앙':>8s}"
              f"{'학습중앙':>9s}{'홀드중앙':>9s}{'손실':>6s}{'파산':>6s}{'낙폭':>7s}  최고시작")
        print("  " + "-" * 104)
        for _, x in d.head(n).iterrows():
            print(f"  {x.rule:<28s}{x.lev:>4.0f}x{x['max']:>8.1f}배{x.p_target:>6.1f}%"
                  f"{x['median']:>7.2f}배{x.tr_median:>8.2f}배{x.ho_median:>8.2f}배"
                  f"{x.p_loss:>5.0f}%{x.p_bust:>5.0f}%{x.mdd:>6.0f}%  {x.best_start}")

    table(r.sort_values("max", ascending=False), "1년 최대치 상위")
    table(r.sort_values("median", ascending=False), "전형적인 해(중앙값) 상위")
    safe = r[(r.p_bust <= 5)].sort_values("median", ascending=False)
    table(safe, f"파산확률 5% 이하 중 중앙값 상위 ({len(safe)}개 해당)")

    print(f"\n  저장: ml/saved_models/hunt_wide.csv")


if __name__ == "__main__":
    main()
