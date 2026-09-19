"""
ml/trend_backtest.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
추세추종 롱/숏 백테스트 — Buy&Hold를 이기는 것이 목표

이전 dca_backtest.py의 설계 결함을 고친 버전:

  1. 고정 TP 제거
     기존은 TP +1% / SL -0.6% 고정이라 34배 오른 시장에서
     모든 승자를 +1%에 잘라냈다. 여기서는 익절 목표 없이
     추세가 꺾일 때까지 들고 간다(트레일링/채널 이탈 청산).
     → 손익비가 1.67:1 고정에서 무제한으로 바뀐다.

  2. 자본 전액 투입
     기존은 켈리 비중 13~18%만 넣고 나머지는 현금 대기라
     100% 노출인 Buy&Hold와 비교 자체가 성립하지 않았다.
     여기서는 신호가 있으면 자본 전액을 넣는다(레버리지 별도).

  3. 롱·숏 양방향 상시 포지션
     추세 상승이면 롱, 하락이면 숏. 하락장 수익도 가져간다.

전략:
  A. Donchian 채널 돌파 (터틀)  — N봉 최고가 상향돌파=롱, 최저가 하향돌파=숏
  B. 이동평균 교차               — 단기MA > 장기MA = 롱, 반대 = 숏
  C. Supertrend (ATR 밴드)      — ATR 밴드 이탈로 추세 전환 판정

평가:
  - 파라미터 그리드 전체를 출력한다. 최고값만 보여주면
    그게 우연인지 견고한지 구분할 수 없기 때문.
  - 학습(2017~2022) / 홀드아웃(2023~2026) 분리해 안정성 확인.
  - CAGR, MDD, Sharpe, 손익비(profit factor)를 Buy&Hold와 나란히 비교.

사용법:
    python ml/trend_backtest.py --symbol BTCUSDT --interval 1d
    python ml/trend_backtest.py --all
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ml.train_directional import load_ohlcv

FEE  = 0.0005      # 편도 수수료 0.05%
SLIP = 0.0005      # 슬리피지 0.05%
BARS_PER_YEAR = {"1d": 365, "4h": 365*6, "1h": 365*24}


# ══════════════════════════════════════════════════════════════
# 데이터
# ══════════════════════════════════════════════════════════════

def load(symbol: str, interval: str, from_year: int = 2017) -> pd.DataFrame:
    df = load_ohlcv(symbol, interval, from_year=from_year)
    df = df.sort_values("datetime").drop_duplicates("datetime").reset_index(drop=True)
    return df[["datetime", "open", "high", "low", "close", "volume"]]


# ══════════════════════════════════════════════════════════════
# 신호 생성 — 모두 "포지션 방향" 시계열(+1 롱 / -1 숏 / 0 관망)을 반환
#   ⚠️ 모든 지표는 shift(1)로 확정봉만 사용 — 미래참조 없음
# ══════════════════════════════════════════════════════════════

def sig_donchian(df: pd.DataFrame, n_entry: int, n_exit: int) -> np.ndarray:
    """터틀식 채널 돌파: N봉 최고 돌파=롱, 최저 돌파=숏, 반대 채널 이탈 시 청산"""
    h, l, c = df["high"], df["low"], df["close"]
    up_e   = h.rolling(n_entry).max().shift(1)
    dn_e   = l.rolling(n_entry).min().shift(1)
    up_x   = h.rolling(n_exit).max().shift(1)
    dn_x   = l.rolling(n_exit).min().shift(1)

    pos = np.zeros(len(df))
    cur = 0
    cv, uev, dev, uxv, dxv = c.values, up_e.values, dn_e.values, up_x.values, dn_x.values
    for i in range(len(df)):
        if np.isnan(uev[i]) or np.isnan(dev[i]):
            pos[i] = 0; continue
        if cur == 0:
            if cv[i] > uev[i]:   cur = 1
            elif cv[i] < dev[i]: cur = -1
        elif cur == 1:
            if cv[i] < dxv[i]:   cur = -1 if cv[i] < dev[i] else 0
        elif cur == -1:
            if cv[i] > uxv[i]:   cur = 1 if cv[i] > uev[i] else 0
        pos[i] = cur
    return pos


def sig_ma_cross(df: pd.DataFrame, fast: int, slow: int) -> np.ndarray:
    """이동평균 교차: 단기>장기 = 롱, 반대 = 숏 (항상 포지션 보유)"""
    c = df["close"]
    f = c.rolling(fast).mean().shift(1)
    s = c.rolling(slow).mean().shift(1)
    pos = np.where(f > s, 1.0, -1.0)
    pos[np.isnan(f.values) | np.isnan(s.values)] = 0.0
    return pos


def sig_supertrend(df: pd.DataFrame, period: int, mult: float) -> np.ndarray:
    """Supertrend: ATR 밴드를 종가가 이탈하면 추세 전환"""
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = pd.Series(tr).rolling(period).mean().shift(1).values
    hl2 = (h + l) / 2.0

    upper = hl2 + mult * atr
    lower = hl2 - mult * atr

    pos = np.zeros(len(df))
    cur = 0
    fu, fl = np.nan, np.nan
    for i in range(len(df)):
        if np.isnan(atr[i]):
            pos[i] = 0; continue
        # 밴드는 추세 방향으로만 좁아지도록 갱신
        fu = upper[i] if np.isnan(fu) else (min(upper[i], fu) if c[i-1] <= fu else upper[i])
        fl = lower[i] if np.isnan(fl) else (max(lower[i], fl) if c[i-1] >= fl else lower[i])
        if cur <= 0 and c[i] > fu:   cur = 1
        elif cur >= 0 and c[i] < fl: cur = -1
        pos[i] = cur
    return pos


# ══════════════════════════════════════════════════════════════
# 백테스트 엔진 — 포지션 시계열 → 자본곡선
# ══════════════════════════════════════════════════════════════

def run(df: pd.DataFrame, pos: np.ndarray, interval: str,
        leverage: float = 1.0, allow_short: bool = True) -> dict:
    c = df["close"].values
    if not allow_short:
        pos = np.clip(pos, 0, 1)

    ret = np.zeros(len(c))
    ret[1:] = c[1:] / c[:-1] - 1.0

    # 전봉 포지션으로 이번 봉 수익 실현 (체결 지연 반영)
    held = np.roll(pos, 1); held[0] = 0.0
    strat_ret = held * ret * leverage

    # 포지션 변경 시 거래비용
    turn = np.abs(np.diff(np.concatenate([[0.0], pos])))
    cost = turn * (FEE + SLIP) * leverage
    strat_ret = strat_ret - cost

    equity = np.cumprod(1 + strat_ret)
    bh     = c / c[0]

    def stats(eq, rets):
        total = eq[-1] - 1
        yrs = len(eq) / BARS_PER_YEAR.get(interval, 365)
        cagr = (eq[-1] ** (1/yrs) - 1) if yrs > 0 and eq[-1] > 0 else -1.0
        dd = eq / np.maximum.accumulate(eq) - 1
        mdd = dd.min()
        sd = rets.std()
        sharpe = (rets.mean()/sd*np.sqrt(BARS_PER_YEAR.get(interval,365))) if sd > 0 else 0.0
        return total, cagr, mdd, sharpe

    s_tot, s_cagr, s_mdd, s_sharpe = stats(equity, strat_ret)
    b_tot, b_cagr, b_mdd, b_sharpe = stats(bh, ret)

    # 거래 단위 통계
    changes = np.where(turn > 0)[0]
    n_trades = len(changes)
    gains = strat_ret[strat_ret > 0].sum()
    losses = -strat_ret[strat_ret < 0].sum()
    pf = gains / losses if losses > 0 else np.inf
    win_bars = (strat_ret > 0).sum() / max((strat_ret != 0).sum(), 1) * 100

    return {
        "total": s_tot, "cagr": s_cagr, "mdd": s_mdd, "sharpe": s_sharpe,
        "bh_total": b_tot, "bh_cagr": b_cagr, "bh_mdd": b_mdd, "bh_sharpe": b_sharpe,
        "n_trades": n_trades, "profit_factor": pf, "win_bars": win_bars,
        "equity": equity, "bh_equity": bh,
        "exposure": (pos != 0).mean() * 100,
    }


# ══════════════════════════════════════════════════════════════
# 파라미터 그리드
# ══════════════════════════════════════════════════════════════

def build_grid(interval: str):
    if interval == "1d":
        don = [(20,10), (55,20), (20,5), (40,15), (100,25)]
        mac = [(10,50), (20,100), (50,200), (5,20), (20,50)]
        stt = [(10,3.0), (14,2.5), (7,2.0), (20,3.0)]
    else:
        don = [(48,24), (120,48), (24,12), (96,36)]
        mac = [(24,120), (48,200), (12,48), (50,200)]
        stt = [(24,3.0), (48,2.5), (14,2.0)]
    return (
        [(f"Donchian({a},{b})", lambda d,a=a,b=b: sig_donchian(d,a,b)) for a,b in don] +
        [(f"MA교차({a},{b})",    lambda d,a=a,b=b: sig_ma_cross(d,a,b)) for a,b in mac] +
        [(f"Supertrend({a},{b})",lambda d,a=a,b=b: sig_supertrend(d,a,b)) for a,b in stt]
    )


# ══════════════════════════════════════════════════════════════
# 심볼 1건 실행
# ══════════════════════════════════════════════════════════════

def run_symbol(symbol: str, interval: str, leverage: float = 1.0,
               split_date: str = "2023-01-01", verbose: bool = True) -> pd.DataFrame:
    df = load(symbol, interval)
    grid = build_grid(interval)

    tr = df[df["datetime"] < split_date].reset_index(drop=True)
    ho = df[df["datetime"] >= split_date].reset_index(drop=True)

    rows = []
    for name, fn in grid:
        try:
            full = run(df, fn(df), interval, leverage)
            r_tr = run(tr, fn(tr), interval, leverage) if len(tr) > 300 else None
            r_ho = run(ho, fn(ho), interval, leverage) if len(ho) > 300 else None
        except Exception as e:
            if verbose: print(f"  {name}: 오류 {e}")
            continue
        rows.append({
            "symbol": symbol, "interval": interval, "strategy": name,
            "전체_수익률%": full["total"]*100, "전체_CAGR%": full["cagr"]*100,
            "MDD%": full["mdd"]*100, "Sharpe": full["sharpe"],
            "손익비": full["profit_factor"], "거래수": full["n_trades"],
            "노출%": full["exposure"],
            "학습_CAGR%": r_tr["cagr"]*100 if r_tr else np.nan,
            "홀드아웃_CAGR%": r_ho["cagr"]*100 if r_ho else np.nan,
            "BH_수익률%": full["bh_total"]*100, "BH_CAGR%": full["bh_cagr"]*100,
            "BH_MDD%": full["bh_mdd"]*100, "BH_Sharpe": full["bh_sharpe"],
            "BH대비_CAGR차": (full["cagr"]-full["bh_cagr"])*100,
        })
    out = pd.DataFrame(rows)
    if verbose and len(out):
        bh = out.iloc[0]
        print(f"\n{'='*112}")
        print(f"  {symbol} {interval}  레버리지 {leverage:.0f}x   "
              f"[Buy&Hold: 수익률 {bh['BH_수익률%']:,.0f}%  CAGR {bh['BH_CAGR%']:.1f}%  "
              f"MDD {bh['BH_MDD%']:.1f}%  Sharpe {bh['BH_Sharpe']:.2f}]")
        print(f"{'='*112}")
        print(f"{'전략':22s}{'수익률%':>12s}{'CAGR%':>8s}{'MDD%':>8s}{'Sharpe':>8s}"
              f"{'손익비':>7s}{'거래':>6s}{'학습CAGR':>9s}{'홀드CAGR':>9s}{'BH대비':>8s}")
        print("-"*112)
        for _, r in out.sort_values("전체_CAGR%", ascending=False).iterrows():
            flag = "✅" if r["BH대비_CAGR차"] > 0 else "  "
            print(f"{r['strategy']:22s}{r['전체_수익률%']:>11,.0f}%{r['전체_CAGR%']:>7.1f}%"
                  f"{r['MDD%']:>7.1f}%{r['Sharpe']:>8.2f}{r['손익비']:>7.2f}"
                  f"{r['거래수']:>6.0f}{r['학습_CAGR%']:>8.1f}%{r['홀드아웃_CAGR%']:>8.1f}%"
                  f"{r['BH대비_CAGR차']:>+7.1f}%p {flag}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--interval", default="1d")
    ap.add_argument("--leverage", type=float, default=1.0)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--symbols", nargs="*",
                    default=["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT"])
    ap.add_argument("--intervals", nargs="*", default=["1d","4h"])
    ap.add_argument("--out", default="ml/saved_models/trend_results.csv")
    a = ap.parse_args()

    print("="*112)
    print("  추세추종 롱/숏 백테스트 — 고정TP 없음(승자 끝까지) · 자본 전액 투입 · 양방향")
    print(f"  학습 2017~2022 / 홀드아웃 2023~현재   레버리지 {a.leverage:.0f}x")
    print("="*112)

    frames = []
    pairs = [(s,i) for s in a.symbols for i in a.intervals] if a.all else [(a.symbol, a.interval)]
    for sym, ivl in pairs:
        try:
            frames.append(run_symbol(sym, ivl, a.leverage))
        except Exception as e:
            print(f"  ⚠️ {sym} {ivl}: {e}")

    if frames:
        allr = pd.concat(frames, ignore_index=True)
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        allr.to_csv(a.out, index=False)
        beat = allr[allr["BH대비_CAGR차"] > 0]
        print(f"\n{'='*112}")
        print(f"  Buy&Hold를 CAGR로 이긴 조합: {len(beat)} / {len(allr)}")
        if len(beat):
            print(f"{'='*112}")
            top = beat.sort_values("BH대비_CAGR차", ascending=False).head(15)
            print(top[["symbol","interval","strategy","전체_CAGR%","BH_CAGR%",
                       "BH대비_CAGR차","MDD%","BH_MDD%","Sharpe","홀드아웃_CAGR%"]].to_string(index=False))
        print(f"\n  저장: {a.out}")


if __name__ == "__main__":
    main()
