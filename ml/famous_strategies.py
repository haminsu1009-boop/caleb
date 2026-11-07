"""
ml/famous_strategies.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
코인 커뮤니티에서 유명한 기법들을 실제 데이터로 검증

커뮤니티나 유튜브에 도는 "승률 80%" 같은 수치는 대부분 출처가 없거나
체리피킹이다. 여기서는 각 기법을 기계적으로 구현해 2017~2026 실제
데이터에 돌리고, 강세장/약세장을 나눠 성과를 낸다.

검증 대상 (기계적 구현이 가능한 것만):
    1. 골든/데드크로스     50/200일선 교차
    2. RSI 과매도 반등     RSI<30 매수 / >70 매도
    3. RSI 다이버전스      가격 저점↓ + RSI 저점↑
    4. 볼린저 평균회귀     하단터치 매수 / 상단터치 매도
    5. 볼린저 스퀴즈 돌파  밴드 수축 후 이탈 방향 추종
    6. MACD 크로스        시그널선 교차
    7. 일목균형표 구름돌파  구름 상단/하단 이탈
    8. 유동성 스윕(ICT)    직전 저점 꼬리로 이탈 후 회복 시 매수
    9. 그리드 매매         일정 간격 분할매수/매도
   10. 추세추종 돌파       Donchian 채널 (터틀)

⚠️ 기계적 구현이 불가능해 제외한 것:
    엘리엇 파동, 와이코프, 하모닉 패턴 — 파동/구간 판정이 주관적이라
    구현자마다 결과가 달라진다. 이런 기법의 "승률"은 검증 불가능하다.

측정:
    각 기법을 롱숏 포지션 시계열로 바꿔 전체/강세장/약세장 수익률과
    최대낙폭, 거래당 승률을 낸다. 존버 대비도 함께 표시.

사용법:
    python ml/famous_strategies.py
    python ml/famous_strategies.py --symbol ETHUSDT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ml.trend_backtest import load, sig_donchian, FEE, SLIP

SYMS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]

# 사이클 구간 (BTC 기준 사후 확정)
BULL = [("2018-12-15", "2021-11-10"), ("2022-11-21", "2025-10-06")]
BEAR = [("2017-12-17", "2018-12-15"), ("2021-11-10", "2022-11-21"),
        ("2025-10-06", "2026-12-31")]


# ══════════════════════════════════════════════════════════════
# 지표
# ══════════════════════════════════════════════════════════════

def rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    g = d.clip(lower=0).rolling(n).mean()
    l = (-d.clip(upper=0)).rolling(n).mean()
    return 100 - 100 / (1 + g / (l + 1e-12))


def bb(c: pd.Series, n: int = 20, k: float = 2.0):
    ma = c.rolling(n).mean(); sd = c.rolling(n).std()
    return ma + k*sd, ma, ma - k*sd, (sd / (ma + 1e-12))


def macd(c: pd.Series):
    e12 = c.ewm(span=12).mean(); e26 = c.ewm(span=26).mean()
    line = e12 - e26; sig = line.ewm(span=9).mean()
    return line, sig


# ══════════════════════════════════════════════════════════════
# 기법별 포지션 (+1 롱 / -1 숏 / 0 관망), 모두 shift(1) 확정봉 기준
# ══════════════════════════════════════════════════════════════

def s_golden_cross(df):
    c = df["close"]
    f = c.rolling(50).mean().shift(1); s = c.rolling(200).mean().shift(1)
    p = np.where(f > s, 1.0, -1.0)
    p[np.isnan(f.values) | np.isnan(s.values)] = 0.0
    return p


def s_rsi_reversal(df):
    r = rsi(df["close"], 14).shift(1).values
    p = np.zeros(len(df)); cur = 0
    for i in range(len(df)):
        if np.isnan(r[i]): p[i] = 0; continue
        if r[i] < 30: cur = 1
        elif r[i] > 70: cur = -1
        p[i] = cur
    return p


def s_rsi_divergence(df, look: int = 20):
    c = df["close"].values; r = rsi(df["close"], 14).values
    lo = pd.Series(df["low"]).rolling(look).min().values
    rl = pd.Series(r).rolling(look).min().values
    p = np.zeros(len(df)); cur = 0
    for i in range(look*2, len(df)):
        if np.isnan(lo[i]) or np.isnan(rl[i-look]): continue
        # 강세 다이버전스: 가격은 신저점, RSI는 더 높음
        if df["low"].values[i] <= lo[i] and r[i] > rl[i-look] + 2:
            cur = 1
        # 약세 다이버전스
        elif df["high"].values[i] >= pd.Series(df["high"]).rolling(look).max().values[i] \
             and r[i] < pd.Series(r).rolling(look).max().values[i-look] - 2:
            cur = -1
        p[i] = cur
    return p


def s_bb_meanrev(df):
    u, m, l, _ = bb(df["close"], 20, 2.0)
    c = df["close"].shift(1); u = u.shift(1); l = l.shift(1); m = m.shift(1)
    p = np.zeros(len(df)); cur = 0
    cv, uv, lv, mv = c.values, u.values, l.values, m.values
    for i in range(len(df)):
        if np.isnan(uv[i]): p[i] = 0; continue
        if cv[i] <= lv[i]: cur = 1
        elif cv[i] >= uv[i]: cur = -1
        elif cur == 1 and cv[i] >= mv[i]: cur = 0
        elif cur == -1 and cv[i] <= mv[i]: cur = 0
        p[i] = cur
    return p


def s_bb_squeeze(df):
    u, m, l, w = bb(df["close"], 20, 2.0)
    wq = w.rolling(120).quantile(0.25)
    c = df["close"].shift(1); u = u.shift(1); l = l.shift(1)
    sq = (w.shift(1) <= wq.shift(1))
    p = np.zeros(len(df)); cur = 0
    for i in range(len(df)):
        if np.isnan(u.values[i]) or np.isnan(wq.values[i]): p[i] = 0; continue
        if sq.values[i]:
            if c.values[i] > u.values[i]: cur = 1
            elif c.values[i] < l.values[i]: cur = -1
        p[i] = cur
    return p


def s_macd_cross(df):
    line, sig = macd(df["close"])
    line = line.shift(1); sig = sig.shift(1)
    p = np.where(line > sig, 1.0, -1.0)
    p[np.isnan(line.values) | np.isnan(sig.values)] = 0.0
    return p


def s_ichimoku(df):
    h, l, c = df["high"], df["low"], df["close"]
    ten = (h.rolling(9).max() + l.rolling(9).min()) / 2
    kij = (h.rolling(26).max() + l.rolling(26).min()) / 2
    a = ((ten + kij) / 2).shift(26)
    b = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)
    top = pd.concat([a, b], axis=1).max(axis=1).shift(1)
    bot = pd.concat([a, b], axis=1).min(axis=1).shift(1)
    cs = c.shift(1)
    p = np.zeros(len(df)); cur = 0
    for i in range(len(df)):
        if np.isnan(top.values[i]): p[i] = 0; continue
        if cs.values[i] > top.values[i]: cur = 1
        elif cs.values[i] < bot.values[i]: cur = -1
        p[i] = cur
    return p


def s_liquidity_sweep(df, look: int = 20):
    """ICT식 유동성 스윕: 직전 저점을 꼬리로 깨고 종가는 위에서 마감 → 롱"""
    lo = df["low"].rolling(look).min().shift(1)
    hi = df["high"].rolling(look).max().shift(1)
    p = np.zeros(len(df)); cur = 0
    lv, hv = lo.values, hi.values
    L, H, C, O = df["low"].values, df["high"].values, df["close"].values, df["open"].values
    for i in range(len(df)):
        if np.isnan(lv[i]): p[i] = 0; continue
        swept_low  = (L[i] < lv[i]) and (C[i] > lv[i])
        swept_high = (H[i] > hv[i]) and (C[i] < hv[i])
        if swept_low:  cur = 1
        elif swept_high: cur = -1
        p[i] = cur
    return p


def s_grid(df, band: float = 0.10):
    """그리드: 20일선 대비 -band% 이하면 롱, +band% 이상이면 숏"""
    ma = df["close"].rolling(20).mean().shift(1)
    dev = (df["close"].shift(1) - ma) / (ma + 1e-12)
    p = np.zeros(len(df))
    p[dev.values <= -band] = 1.0
    p[dev.values >= band] = -1.0
    # 유지
    cur = 0
    for i in range(len(df)):
        if p[i] != 0: cur = p[i]
        else: p[i] = cur
    return p


def s_donchian(df):
    return sig_donchian(df, 20, 10)


STRATS = {
    "골든/데드크로스(50,200)": s_golden_cross,
    "RSI 과매도반등(30/70)":   s_rsi_reversal,
    "RSI 다이버전스":          s_rsi_divergence,
    "볼린저 평균회귀":          s_bb_meanrev,
    "볼린저 스퀴즈돌파":        s_bb_squeeze,
    "MACD 크로스":            s_macd_cross,
    "일목 구름돌파":           s_ichimoku,
    "유동성스윕(ICT)":         s_liquidity_sweep,
    "그리드(±10%)":           s_grid,
    "터틀 돌파(20,10)":        s_donchian,
}


# ══════════════════════════════════════════════════════════════
def eval_strategy(fn) -> pd.DataFrame:
    """6종 동일가중 포트폴리오 일간 수익률 + 거래 승률"""
    S, B, WINS, TRADES = {}, {}, 0, 0
    for s in SYMS:
        df = load(s, "1d")[["datetime", "open", "high", "low", "close"]].copy()
        pos = fn(df)
        c = df["close"].values
        r = np.zeros(len(c)); r[1:] = c[1:] / c[:-1] - 1.0
        held = np.roll(pos, 1); held[0] = 0.0
        turn = np.abs(np.diff(np.concatenate([[0.0], pos])))
        sr = held * r - turn * (FEE + SLIP)
        S[s] = pd.Series(sr, index=df["datetime"])
        B[s] = pd.Series(r, index=df["datetime"])

        # 거래 단위 승률: 포지션 유지 구간의 누적손익 부호
        ch = np.where(np.diff(np.concatenate([[0.0], pos])) != 0)[0]
        for a, b in zip(ch, list(ch[1:]) + [len(pos)]):
            if pos[a] == 0: continue
            seg = sr[a:b]
            if len(seg) == 0: continue
            TRADES += 1
            if np.prod(1 + seg) - 1 > 0: WINS += 1
    port = pd.DataFrame(S).mean(axis=1, skipna=True).fillna(0.0)
    bh   = pd.DataFrame(B).mean(axis=1, skipna=True).fillna(0.0)
    return port, bh, (WINS / TRADES * 100 if TRADES else 0.0), TRADES


def perf(r: np.ndarray, per: int = 365):
    if len(r) == 0: return 0.0, 0.0, 0.0
    eq = np.cumprod(1 + r)
    if eq[-1] <= 0: return -100.0, -100.0, -100.0
    total = (eq[-1] - 1) * 100
    cagr = (eq[-1] ** (per / len(r)) - 1) * 100
    mdd = (eq / np.maximum.accumulate(eq) - 1).min() * 100
    return total, cagr, mdd


def seg_mask(idx, segs):
    idx = pd.DatetimeIndex(idx)
    m = np.zeros(len(idx), dtype=bool)
    for lo, hi in segs:
        m |= np.asarray((idx >= lo) & (idx <= hi))
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="ml/saved_models/famous_strategies.csv")
    a = ap.parse_args()

    print("=" * 108)
    print("  코인 커뮤니티 유명 기법 검증 — 6종 동일가중, 2017~2026 실제 데이터")
    print("=" * 108)

    rows = []
    bh_ref = None
    for name, fn in STRATS.items():
        try:
            port, bh, wr, n = eval_strategy(fn)
        except Exception as e:
            print(f"  {name}: 오류 {e}"); continue
        idx = port.index
        if bh_ref is None:
            bh_ref = (bh, idx)
        bull_m = seg_mask(idx, BULL); bear_m = seg_mask(idx, BEAR)
        t, c, m = perf(port.values)
        bt, bc, bm = perf(port.values[bull_m])
        rt, rc, rm = perf(port.values[bear_m])
        rows.append({"기법": name, "전체수익%": t, "CAGR%": c, "MDD%": m,
                     "승률%": wr, "거래수": n, "강세장%": bt, "약세장%": rt})

    bh, idx = bh_ref
    bull_m = seg_mask(idx, BULL); bear_m = seg_mask(idx, BEAR)
    ht, hc, hm = perf(bh.values)
    hbt, _, _ = perf(bh.values[bull_m])
    hrt, _, _ = perf(bh.values[bear_m])

    print(f"\n  [기준] 존버: 전체 {ht:+,.0f}%  CAGR {hc:.1f}%  MDD {hm:.1f}%  "
          f"| 강세장 {hbt:+,.0f}%  약세장 {hrt:+.1f}%\n")
    print(f"  {'기법':24s}{'전체수익%':>13s}{'CAGR%':>9s}{'MDD%':>8s}{'승률%':>8s}{'거래':>7s}"
          f"{'강세장%':>12s}{'약세장%':>11s}")
    print("  " + "-" * 96)
    out = pd.DataFrame(rows).sort_values("전체수익%", ascending=False)
    for _, r in out.iterrows():
        flag = "✅" if r["전체수익%"] > ht else "  "
        print(f"  {r['기법']:24s}{r['전체수익%']:>12,.0f}%{r['CAGR%']:>8.1f}%{r['MDD%']:>7.1f}%"
              f"{r['승률%']:>7.1f}%{r['거래수']:>7.0f}{r['강세장%']:>11,.0f}%{r['약세장%']:>10.1f}% {flag}")

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    out.to_csv(a.out, index=False)
    print(f"\n  저장: {a.out}")
    print("\n  ⚠️ 엘리엇 파동 / 와이코프 / 하모닉은 파동·구간 판정이 주관적이라")
    print("     기계적 검증이 불가능하다. 이런 기법의 '승률'은 검증된 수치가 아니다.")


if __name__ == "__main__":
    main()
