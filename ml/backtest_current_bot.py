"""
ml/backtest_current_bot.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
지금 bot/oversold/에 있는 코드 그대로를 백테스트한다

임계값·보유기간·분할매수 비율·손절폭은 strategy.py에서 직접
가져온다 — 여기 따로 적으면 봇이 바뀔 때 이 파일이 안 따라가서
둘이 갈라진다. 대상 종목도 실거래 목록(S.SYMBOLS, 42종)을 그대로
쓴다 — 지금까지 여러 ml/ 스크립트가 써온 46종(상장폐지 4종 포함)
전체가 아니다.

노출·차단기 계산은 executor.py가 test_replay.py로 검증된 뒤의
모습을 옮긴다:
    · 노출은 "실제 체결액"이 아니라 "예약액"(1차+2차 전체 물량) 기준
    · 매 시점 예약합은 그 순간 열려 있는 전 종목을 다시 더해서 구한다
      (심볼 순회 순서에 기댄 점진적 누적이 아니다 — 그 버그를
      test_replay.py가 잡았다)
    · 차단기는 고점대비 -25%에서 신규진입만 30일 막고, 그 뒤 자동
      재개한다(보유 포지션은 강제청산하지 않는다)
    · 평가손익(mtm)은 보유 구간의 실제 시가 경로로 매 시점 다시
      계산한다(ml/sim_correct.py의 Pos.unreal과 동일한 방식) —
      "최종 손익을 처음부터 고정값으로 본다" 같은 근사를 쓰지 않는다

이전 스크립트(ml/scale_in_portfolio.py)와 다른 점: 2차 매수를
"트리거 가격에 정확히 체결"로 가정했었다(가상의 리밋 주문). 이번엔
"판단은 종가, 체결은 다음봉 시가"로 통일한다 — 진입과 같은 규칙이고
이게 더 보수적이다.

⚠️ 남는 캐벗: executor.py의 실제 폴링 로직은 신호가 확정된 바로
그 봉의 종가로 체결한다(다음 봉 시가가 아니다) — 폴링이 봉 마감을
놓치지 않을 만큼 자주(기본 5분) 돌기 때문이다. 이 스크립트를 포함해
이 세션의 모든 백테스트는 "다음 봉 시가 체결"을 가정해왔는데, 그건
더 보수적인 가정이지 실행기가 실제로 하는 동작은 아니다. 둘의 차이는
24시간 끊김 없이 거래되는 코인 시장에서는 보통 작지만(종가↔다음시가
갭이 거의 없음), 검증된 적은 없다 — 이건 2단계(dry-run) 슬리피지
측정이 실제로 답해야 하는 질문이다.

사용법:
    python ml/backtest_current_bot.py
    python ml/backtest_current_bot.py --leverage 1
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from bot.oversold import strategy as S

ROUND_TRIP = 0.20          # % 왕복 — 바이빗 테이커 근사 + 슬리피지 여유
FUNDING_PER_8H = 0.01      # %/8h
BAR_HOURS = 4.0
TRAIN_END = pd.Timestamp("2024-01-01")


def load(sym: str):
    f = f"data/{sym}_4h_all.csv.gz"
    if not os.path.exists(f):
        return None
    d = pd.read_csv(f, compression="gzip")
    tc = "timestamp" if "timestamp" in d.columns else "datetime"
    d[tc] = pd.to_datetime(d[tc], format="mixed", errors="coerce")
    d = d.dropna(subset=[tc]).sort_values(tc).drop_duplicates(tc).reset_index(drop=True)
    return d.rename(columns={tc: "datetime"})


def resolve_trade(sym, o, h, l, c, dt, i, n, *, hold_bars=None,
                  trigger_pct=None, first_frac=None):
    """신호 바로 i에서 시작하는 거래 하나를 끝까지 판정한다.
    (판단은 종가, 체결은 다음봉 시가 — 진입·2차·시간청산 전부 동일 규칙)
    보유 구간의 시가·저가 경로도 같이 담아 mtm 평가에 쓴다.

    키워드 인자를 안 주면 strategy.py의 실거래 값 그대로 쓴다 —
    build_all()의 기본 호출은 이 봇이 실제로 하는 것과 정확히
    같아야 한다. 인자는 ml/backtest_grid.py의 민감도 분석에서만
    다른 값으로 재실험할 때 쓴다.
    """
    hold = S.HOLD_BARS if hold_bars is None else hold_bars
    trig_pct = S.SCALE_IN_TRIGGER_PCT if trigger_pct is None else trigger_pct
    frac = S.SCALE_IN_FIRST_FRAC if first_frac is None else first_frac

    if i + 1 + hold >= n:
        return None
    e1 = o[i + 1]
    trigger = e1 * (1 + trig_pct / 100)
    stop_active = S.stop_price(e1)
    entry_avg = e1
    tranche = 1
    fill2_dt = fill2_px = fill2_bar = None

    exit_bar = exit_px = reason = None
    for bar in range(i + 1, i + 1 + hold):
        if l[bar] <= stop_active:
            exit_bar, exit_px, reason = bar, stop_active, "stop"
            break
        if tranche == 1 and c[bar] <= trigger and bar + 1 < n:
            fill2_px = o[bar + 1]
            fill2_dt = dt[bar + 1]
            fill2_bar = bar + 1
            entry_avg = S.blended_entry(e1, frac, fill2_px, 1 - frac)
            stop_active = S.stop_price(entry_avg)
            tranche = 2

    if exit_bar is None:
        exit_bar = i + 1 + hold
        exit_px = o[exit_bar]
        reason = "time"

    seg = slice(i + 1, exit_bar + 1)
    return {"sym": sym, "dt": dt[i], "entry_bar": i + 1, "e1": e1,
            "entry_avg": entry_avg, "tranche": tranche,
            "fill2_dt": fill2_dt, "fill2_px": fill2_px, "fill2_bar": fill2_bar,
            "exit_dt": dt[exit_bar], "exit_bar": exit_bar, "exit_px": exit_px,
            "reason": reason, "path_dt": dt[seg], "path_o": o[seg], "path_l": l[seg],
            "mae": (l[i + 1: exit_bar + 1].min() / entry_avg - 1) * 100}


def build_all(*, hold_bars=None, trigger_pct=None, first_frac=None, entry_thresh=None):
    """기본 호출(인자 없음)은 실거래 봇과 정확히 같은 신호 집합을 낸다."""
    thresh = S.ENTRY_THRESH if entry_thresh is None else entry_thresh
    hold = S.HOLD_BARS if hold_bars is None else hold_bars
    trades = []
    have, missing = [], []
    for sym in S.SYMBOLS:
        g = load(sym)
        if g is None or len(g) < S.MA_PERIOD + hold + 5:
            missing.append(sym); continue
        have.append(sym)
        o = g["open"].astype(float).values
        h = g["high"].astype(float).values
        l = g["low"].astype(float).values
        c = g["close"].astype(float).values
        dt = g["datetime"].values
        n = len(g)
        ma = pd.Series(c).rolling(S.MA_PERIOD).mean().values
        vs = (c / ma - 1) * 100
        lock = -10**9
        for i in np.where(vs <= thresh)[0]:
            if i <= lock:
                continue
            tr = resolve_trade(sym, o, h, l, c, dt, i, n, hold_bars=hold,
                               trigger_pct=trigger_pct, first_frac=first_frac)
            if tr is None:
                continue
            lock = i + hold
            trades.append(tr)
    return sorted(trades, key=lambda t: t["dt"]), have, missing


class Pos:
    """평가손익을 실제 보유 경로(시가·저가)로 매 시점 다시 계산한다."""
    __slots__ = ("sym", "entry_avg", "reserved", "margin", "lev", "exit_dt",
                 "path_dt", "path_o", "path_l", "liq_line", "fee", "realized")

    def __init__(self, t, margin, lev, liq_line, fee, realized):
        self.sym = t["sym"]; self.entry_avg = t["entry_avg"]
        self.reserved = margin * lev; self.margin = margin; self.lev = lev
        self.exit_dt = t["exit_dt"]; self.path_dt = t["path_dt"]
        self.path_o = t["path_o"]; self.path_l = t["path_l"]
        self.liq_line = liq_line; self.fee = fee; self.realized = realized

    def unreal(self, now, use_low=False):
        k = np.searchsorted(self.path_dt, now, side="right") - 1
        if k < 0:
            return 0.0
        k = min(k, len(self.path_o) - 1)
        px = self.path_l[k] if use_low else self.path_o[k]
        r = max((px / self.entry_avg - 1) * 100, self.liq_line)
        return self.margin * self.lev * r / 100


def pnl_pct(entry_avg, exit_px, leverage, liq_line, mae=None):
    """가격 수익률과, 배율상 강제청산선을 이미 지났는지.

    reason(전략 손절 -40% vs 시간청산)과 무관하게 leverage가 높으면
    거래소 강제청산선(liq_line)이 전략 손절보다 먼저 걸릴 수 있다 —
    resolve_trade는 배율을 모르고 계산하므로 여기서 다시 잘라야 한다.

    ⚠️ 청산 판정은 반드시 보유 중 최저가(mae)로 해야 한다. 청산가는
    가는 길에 스치기만 해도 즉시 집행되고, 그 뒤에 값이 되돌아와도
    포지션은 이미 없다. 종가 수익률(px_ret)로 판정하면 "저가가 청산선을
    뚫었지만 마지막엔 회복한" 거래가 전부 승리로 둔갑한다. 저배율에선
    -40% 전략손절이 먼저 걸려 차이가 거의 없지만(2배 0.5%p), 배율이
    올라가면 격차가 폭발한다 — 20배에서 종가기준 13.6% vs 저가기준
    68.7%. 이 한 줄 때문에 "1년 50배" 같은 결과가 만들어졌었다.
    """
    px_ret = (exit_px / entry_avg - 1) * 100
    worst = px_ret if mae is None else min(px_ret, mae)
    was_liq = worst <= liq_line
    if was_liq:
        px_ret = liq_line
    return px_ret, was_liq


def simulate(trades, leverage, per_trade, max_gross, cb, cool_days, min_equity,
             compound=False):
    """compound=False면 베팅 크기가 항상 *초기* 자본 기준으로 고정된다.

    실제 계좌는 그렇게 굴리지 않는다. 자본이 10배가 되면 5%도 10배가
    된다. 고정 베팅은 자본이 커질수록 사실상 베팅 비중이 줄어드는
    것이라 성장을 구조적으로 누르고, 대신 파산 확률도 비현실적으로
    낮춘다(청산 한 번이 자본의 5%가 아니라 0.5%가 되므로).

    기본값을 False로 둔 이유는 이 세션의 기존 결과들이 전부 그 기준으로
    나왔기 때문이다 — 바꾸면 조용히 어긋난다. 새 분석은 compound=True를
    명시적으로 넘긴다.
    """
    liq_line = -100.0 / leverage + 0.5
    cash = 1.0
    peak = 1.0
    mdd = 0.0
    mdd_at = None
    peak_low = 1.0
    mdd_low = 0.0
    positions: dict[str, Pos] = {}
    halted_until = None
    halts = 0
    n_trades = wins = liqs = 0
    bust = False

    for t in trades:
        now = t["dt"]
        for s in [s for s, p in positions.items() if p.exit_dt <= now]:
            cash += positions.pop(s).realized

        eq_mtm = cash + sum(p.unreal(now) for p in positions.values())
        eq_low = cash + sum(p.unreal(now, True) for p in positions.values())
        if eq_mtm <= 0 or eq_mtm < min_equity:
            bust = True
            break
        if eq_mtm > peak:
            peak = eq_mtm
        elif 1 - eq_mtm / peak > mdd:
            mdd = 1 - eq_mtm / peak
            mdd_at = now
        if eq_low > peak_low:
            peak_low = eq_low
        elif 1 - eq_low / peak_low > mdd_low:
            mdd_low = 1 - eq_low / peak_low

        if halted_until is not None and now < halted_until:
            can_enter = False
        else:
            if halted_until is not None:
                halted_until = None
            can_enter = True
        if can_enter and peak > 0 and 1 - eq_mtm / peak >= cb:
            halted_until = now + pd.Timedelta(days=cool_days)
            halts += 1
            peak = eq_mtm
            can_enter = False

        if t["sym"] in positions or not can_enter:
            continue

        # 복리면 베팅과 노출한도가 둘 다 현재 자본에 비례한다.
        # 한도만 고정으로 두면 자본이 커질 때 첫 포지션에서 막힌다.
        base = eq_mtm if compound else 1.0
        margin = per_trade * base
        full_notional = margin * leverage
        gross = sum(p.reserved for p in positions.values())
        if gross + full_notional > max_gross * leverage * base:
            continue

        px_ret, was_liq = pnl_pct(t["entry_avg"], t["exit_px"], leverage,
                                  liq_line, t["mae"])
        held_h = (t["exit_bar"] - t["entry_bar"]) * BAR_HOURS
        fee = ROUND_TRIP + FUNDING_PER_8H * (held_h / 8.0)
        net = px_ret - fee
        realized = max(margin * leverage * net / 100, -margin)
        n_trades += 1
        wins += net > 0
        liqs += was_liq
        positions[t["sym"]] = Pos(t, margin, leverage, liq_line, fee, realized)

    for p in positions.values():
        cash += p.realized

    return {"final": cash, "mdd": mdd, "mdd_low": mdd_low, "mdd_at": mdd_at, "n": n_trades,
            "wr": wins / max(n_trades, 1) * 100, "liq": liqs, "halts": halts, "bust": bust}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--leverage", type=float, default=float(os.getenv("OS_LEVERAGE", "2")))
    ap.add_argument("--per-trade", type=float, default=float(os.getenv("OS_PER_TRADE", "0.05")))
    ap.add_argument("--max-gross", type=float, default=float(os.getenv("OS_MAX_GROSS", "0.8")))
    ap.add_argument("--cb", type=float, default=float(os.getenv("OS_MAX_DRAWDOWN", "0.25")))
    ap.add_argument("--cool-days", type=float, default=float(os.getenv("OS_HALT_COOLDOWN_DAYS", "30")))
    # 실거래 봇은 executor.py:420에서
    #     full_notional = equity * per_trade * leverage
    # 즉 *현재* 자본 기준으로 베팅한다. 이 스크립트의 존재 이유가
    # "봇과 어긋나지 않는 백테스트"이므로 기본값도 복리여야 한다.
    # --fixed는 이 세션 초반 결과(초기자본 고정)를 재현할 때만 쓴다.
    ap.add_argument("--fixed", action="store_true",
                    help="베팅을 초기자본 고정으로 (구버전 재현용, 봇과 불일치)")
    a = ap.parse_args()
    compound = not a.fixed
    mode_label = "복리(봇과 동일)" if compound else "고정(구버전)"

    print("=" * 100)
    print("  현재 bot/oversold/ 설정 그대로 백테스트")
    print(f"  종목 S.SYMBOLS({len(S.SYMBOLS)}종) · 진입 {S.ENTRY_THRESH}% · {S.HOLD_BARS}봉 보유 · "
          f"분할 {S.SCALE_IN_FIRST_FRAC*100:.0f}%+{S.SCALE_IN_TRIGGER_PCT}%트리거 · 손절 {S.STOP_PCT}%")
    print(f"  베팅 {mode_label} · 배율 {a.leverage}x · 진입당 {a.per_trade*100:.1f}% · 총노출 {a.max_gross*100:.0f}%×배율 · "
          f"차단기 -{a.cb*100:.0f}%/{a.cool_days:.0f}일재개")
    print("=" * 100)

    trades, have, missing = build_all()
    if missing:
        print(f"\n  ⚠️ 데이터 없어 제외: {', '.join(missing)}")
    t0, t1 = trades[0]["dt"], trades[-1]["dt"]
    yrs_full = (t1 - t0) / np.timedelta64(1, "D") / 365.25
    print(f"\n  종목 {len(have)}개 · 신호 {len(trades):,}건 · {str(t0)[:10]} ~ {str(t1)[:10]} ({yrs_full:.1f}년)")

    ho_trades = [t for t in trades if t["dt"] >= TRAIN_END]
    print(f"  학습(2017~2023) {len(trades)-len(ho_trades):,}건 · 홀드아웃(2024~) {len(ho_trades):,}건")

    print(f"\n  {'구간':22s}{'거래':>7s}{'승률':>7s}{'최종':>10s}{'연복리':>8s}{'낙폭':>8s}"
          f"{'장중':>8s}{'강제청산':>8s}{'차단발동':>8s}")
    print("  " + "-" * 92)
    r_full = simulate(trades, a.leverage, a.per_trade, a.max_gross, a.cb, a.cool_days, 0.01,
                      compound=compound)
    cagr_full = (r_full["final"] ** (1/yrs_full) - 1) * 100 if r_full["final"] > 0 else -100
    fin = "파산" if r_full["bust"] else f"{r_full['final']:.2f}배"
    print(f"  {'전체 2017~2026':22s}{r_full['n']:>7,}{r_full['wr']:>6.1f}%{fin:>10s}"
          f"{cagr_full:>7.0f}%{r_full['mdd']*100:>7.1f}%{r_full['mdd_low']*100:>7.1f}%"
          f"{r_full['liq']:>8}{r_full['halts']:>8}")

    r_ho = simulate(ho_trades, a.leverage, a.per_trade, a.max_gross, a.cb, a.cool_days, 0.01,
                    compound=compound)
    yrs_ho = (ho_trades[-1]["dt"] - ho_trades[0]["dt"]) / np.timedelta64(1, "D") / 365.25
    cagr_ho = (r_ho["final"] ** (1/yrs_ho) - 1) * 100 if r_ho["final"] > 0 else -100
    fin_ho = "파산" if r_ho["bust"] else f"{r_ho['final']:.2f}배"
    print(f"  {'홀드아웃 2024~2026':22s}{r_ho['n']:>7,}{r_ho['wr']:>6.1f}%{fin_ho:>10s}"
          f"{cagr_ho:>7.0f}%{r_ho['mdd']*100:>7.1f}%{r_ho['mdd_low']*100:>7.1f}%"
          f"{r_ho['liq']:>8}{r_ho['halts']:>8}")

    n_t2 = sum(1 for t in trades if t["tranche"] == 2)
    n_stop = sum(1 for t in trades if t["reason"] == "stop")
    print(f"\n  2차 매수 체결: {n_t2:,}/{len(trades):,}건 ({n_t2/len(trades)*100:.1f}%)")
    print(f"  손절 체결: {n_stop:,}/{len(trades):,}건 ({n_stop/len(trades)*100:.2f}%)")

    print(f"\n  종목별 홀드아웃 (n>=5, 1배 가격수익률 기준)")
    rows = []
    for sym in have:
        st = [t for t in ho_trades if t["sym"] == sym]
        if len(st) < 5:
            continue
        pxs = np.array([pnl_pct(t["entry_avg"], t["exit_px"], 1.0, -100.0)[0]
                        - ROUND_TRIP for t in st])
        rows.append((sym, len(pxs), (pxs > 0).mean() * 100, pxs.mean()))
    rows.sort(key=lambda x: -x[3])
    print(f"  {'심볼':12s}{'n':>5s}{'승률':>7s}{'거래당':>9s}")
    for sym, n, wr, mu in rows[:8]:
        print(f"  {sym:12s}{n:>5}{wr:>6.1f}%{mu:>+8.2f}%")
    print("  ...")
    for sym, n, wr, mu in rows[-3:]:
        print(f"  {sym:12s}{n:>5}{wr:>6.1f}%{mu:>+8.2f}%")
    print(f"  {sum(1 for r in rows if r[3]>0)}/{len(rows)}종목 평균 플러스")

    print(f"\n  연도별 (1배 가격수익률 기준, 배율·노출한도 영향 제외)")
    df = pd.DataFrame(trades)
    df["y"] = pd.DatetimeIndex(df["dt"]).year
    for y, g in df.groupby("y"):
        pxs = np.array([pnl_pct(t["entry_avg"], t["exit_px"], 1.0, -100.0)[0]
                        - ROUND_TRIP for t in g.to_dict("records")])
        tag = "  ←홀드아웃" if y >= 2024 else ""
        print(f"    {y}  n={len(pxs):>4}  승률 {(pxs>0).mean()*100:>5.1f}%  거래당 {pxs.mean():>+6.2f}%{tag}")


if __name__ == "__main__":
    main()
