"""
ml/short_entry_delay.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
주봉 숏을 바로 잡지 말고 반등(양봉)을 확인한 뒤 잡으면 나아지나 (2026-11-05)

사용자 질문: ALGO 숏이 신호 다음 날 바로 들어갔다가 곧 반등에 물렸다.
"일봉이든 4시간봉이든 양봉이 뜬 뒤에 숏을 잡아야 맞지 않나?"

지금 규칙(UP.make_short / MOD.short_signals): 주봉(W-MON, 화~월) 종가가
60주선을 처음 깨고 그 뒤 음봉 4주 연속 → 다음 날(화) 시가에 숏, 4주 뒤
월요일 종가에 청산. 여기서는 **청산 시각은 그대로 두고 진입만 미룬다**.

진입 방법
  A   지금 — 신호 다음 날 시가
  D1~D3  그냥 1·2·3일 늦게 (대조군: 효과가 '양봉'인지 '늦게'인지 가르기)
  G   7일 안의 첫 일봉 양봉 → 그 다음 날 시가 (없으면 7일째 시가)
  GG  양봉 이틀 연속 뒤
  H   7일 안의 첫 4시간봉 양봉 → 다음 4시간봉 시가
  R3·R5  신호가 대비 +3·+5% 반등에 매도 (7일 안에 안 오면 7일째 시가)

표본이 작다(42종 4주 연속 23건). 그래서 ① 연속 3·5주 신호, ② 확장 후보
22종까지 넣어 거래 수를 늘려 같은 방향인지 보고, ③ 짝지은 차이를
부트스트랩해 우연 범위를 잰다. 마지막으로 ④ 지갑 전체(과매도 롱·다이버와
같은 자본)로 돌린다.

    python ml/short_entry_delay.py

결과 (2026-11-05, 데이터 ~2026-11-02) — 기각, 지금 규칙 유지
  42종 4주 연속 23건: 지금 승률 83% · 평균 +12.4% · 최악 -45.2%
    일봉 첫 양봉 뒤   평균 +12.2% (A 대비 -0.2%p, 95% 범위 -5.0~+3.5) · 나은 건 74%지만 진 건 크게 짐
    그냥 1~3일 늦게  +0.7~+1.3%p (범위가 0을 넘나듦) · 4시간봉 첫 양봉 +0.1%p · +3/5% 반등 -1.9/-0.7%p
  3주 연속 42건 · 5주 연속 13건 · 후보 포함 55건에서도 일봉 첫 양봉 -0.0~+1.8%p, 범위 모두 0 포함
  지갑 전체 2017~: 지금 30.2배 · 첫 양봉 28.7배 · 1~3일 늦게 31.2~32.1배 · 2024~ 5.0~6.0배 (전부 잡음 범위)
  → '반등을 확인하고 숏'이 낫다는 증거 없음. 진입이 며칠 늦어질 뿐 결과는 같은 분포.
  주의: 처음 빠른 시험(+1.8%p)은 주봉 경계를 봇과 다르게 잡아서 나온 값이었다. 봇과 같은 W-MON(화~월)으로 다시 하면 사라진다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations
import os
import sys
import warnings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from bot.oversold import strategy as S, modules as MOD
import ml.short_setups as SS
from ml.backtest_current_bot import load
from bybit.collect_history import CANDIDATE_SYMBOLS

H4 = pd.Timedelta(hours=4)
VARIANTS = ["A", "D1", "D2", "D3", "G", "GG", "H", "R3", "R5"]
NAMES = {"A": "지금 (다음 날 바로)", "D1": "그냥 1일 늦게", "D2": "그냥 2일 늦게",
         "D3": "그냥 3일 늦게", "G": "일봉 첫 양봉 → 다음 날", "GG": "일봉 양봉 2연속 → 다음 날",
         "H": "4시간봉 첫 양봉 → 다음 봉", "R3": "+3% 반등에 매도", "R5": "+5% 반등에 매도"}


def entries(D: pd.DataFrame, g4: pd.DataFrame | None) -> dict:
    """D: 진입일(화)부터 청산일(월)까지 일봉. 변형별 (진입 위치, 진입가, 진입 시각)."""
    o, c, h = D["open"].values, D["close"].values, D["high"].values
    out = {"A": (0, o[0])}
    for k in (1, 2, 3):
        out[f"D{k}"] = (k, o[k])
    g = [k for k in range(7) if c[k] > o[k]]
    out["G"] = (g[0] + 1, o[g[0] + 1]) if g else (7, o[7])
    gg = [k for k in range(1, 7) if c[k] > o[k] and c[k - 1] > o[k - 1]]
    out["GG"] = (gg[0] + 1, o[gg[0] + 1]) if gg else (7, o[7])
    for x in (3, 5):
        lvl = o[0] * (1 + x / 100)
        k = next((k for k in range(7) if h[k] >= lvl), None)
        out[f"R{x}"] = (k, lvl) if k is not None else (7, o[7])
    out["H"] = (7, o[7])
    if g4 is not None:
        t0 = D["dt"].iloc[0]
        w = g4[(g4.index >= t0) & (g4.index < t0 + pd.Timedelta(days=7))]
        green = np.where(w["close"].values > w["open"].values)[0]
        if len(green) and green[0] + 1 < len(w):
            t = w.index[green[0] + 1]
            out["H"] = (int((t.normalize() - t0).days), float(w["open"].iloc[green[0] + 1]), t)
    return out


def build(symbols, streak=4):
    rows = []
    for s in symbols:
        d = SS.load_daily(s)
        if d is None or len(d) < 400:
            continue
        d = d.assign(dt=pd.to_datetime(d["dt"])).reset_index(drop=True)
        w = MOD.to_weekly(d, drop_partial=True)
        g = load(s)
        g4 = None if g is None else g.assign(datetime=pd.to_datetime(g["datetime"])).set_index("datetime")
        n = len(w); lock = -10**9
        for i in MOD.short_signals(w, streak=streak):
            if i <= lock or i + 4 >= n:
                continue
            lock = i + 4
            t_in = w["dt"].iloc[i] + pd.Timedelta(days=1)            # 화요일
            t_out = w["dt"].iloc[i + 4]                               # 4주 뒤 월요일 종가
            D = d[(d.dt >= t_in) & (d.dt <= t_out)].reset_index(drop=True)
            if len(D) < 21:
                continue
            ex = float(D["close"].iloc[-1])
            r = {"sym": s, "dt": t_in, "exit": t_out, "exit_px": ex}
            for v, e in entries(D, g4).items():
                k, px = e[0], e[1]
                r[v] = (1 - ex / px) * 100
                r[v + "_mae"] = (1 - D["high"].values[k:].max() / px) * 100
                r[v + "_k"] = k
                r[v + "_px"] = px
                r[v + "_t"] = e[2] if len(e) > 2 else D["dt"].iloc[k]
            rows.append(r)
    return pd.DataFrame(rows)


def boot(diff, n=20000, seed=0):
    rng = np.random.default_rng(seed)
    m = rng.choice(diff, (n, len(diff))).mean(axis=1)
    return np.percentile(m, 2.5), np.percentile(m, 97.5), (m <= 0).mean()


def table(T: pd.DataFrame, title: str):
    print(f"\n[{title}] {len(T)}건")
    for v in VARIANTS:
        a = T[v].values; m = T[v + "_mae"].values
        line = (f"  {NAMES[v]:<20} 승률 {(a > 0).mean()*100:3.0f}% 평균 {a.mean():+5.1f}% "
                f"중간 {np.median(a):+5.1f}% 최악 {a.min():+6.1f}% | 역행 평균 {m.mean():+5.1f}% 최악 {m.min():+6.1f}%")
        if v != "A":
            dif = a - T["A"].values
            lo, hi, p = boot(dif)
            line += f" | A 대비 {dif.mean():+4.1f}%p [{lo:+.1f}, {hi:+.1f}] 나은 건 {(dif > 0).mean()*100:.0f}%"
        print(line)


def wallet(T: pd.DataFrame):
    """지갑 전체 — 과매도 롱·다이버는 그대로, 숏만 변형별 진입으로 바꾼다."""
    from ml.module_winrate import taken
    import ml.unified_pool as UP
    from ml.bear_leverage import bear_series, is_on, T0, TE
    from ml.crash_window import crash_hits, in_window
    from ml.per_coin_rules import sim
    from ml.per_coin_walkforward import MENU
    from ml.per_coin_portfolio import to_up
    Dd = {s: SS.load_daily(s) for s in S.SYMBOLS}
    Dd = {k: v for k, v in Dd.items() if v is not None and len(v) >= 400}
    ma, th, hd, fr, ou, st = MENU["A 지금 봇"]
    L = []
    for s in S.SYMBOLS:
        g = load(s); o, h, l, c = (g[k].astype(float).values for k in ("open", "high", "low", "close"))
        L += [to_up(t) for t in sim(o, h, l, c, g["datetime"].values, ma, th, hd, fr, ou, S.STOP_PCT, sym=s, step=st)]
    cut = lambda X: [t for t in X if t["dt"] >= T0]
    btc = Dd["BTCUSDT"].set_index("dt")["close"]; B = bear_series(btc)
    hits = crash_hits(load("BTCUSDT").set_index("datetime")["close"].astype(float))
    base = [dict(t, kind="longb") if (is_on(B, t["dt"]) or in_window(hits, t["dt"])) else t for t in cut(L)]
    Dv = cut(UP.make_div(Dd))
    P = {"long": .015, "longb": .015, "short": .4, "div": .4}
    LV = {"long": 4.0, "longb": 2.0, "short": 1.0, "div": 1.0}
    T = T[T["dt"] >= pd.Timestamp(T0)]
    print(f"\n[지갑 전체 2017~ · 42종 4주 연속 {len(T)}건]")
    for v in VARIANTS:
        Sh = [{"kind": "short", "sym": r.sym, "dt": pd.Timestamp(getattr(r, v + "_t")), "exit": r.exit,
               "entry": getattr(r, v + "_px"), "exit_px": r.exit_px, "mae": getattr(r, v + "_mae"),
               "deployed": 1.0, "bars_h": 24 * 28, "long": False} for r in T.itertuples()]
        X = base + Sh + Dv
        fin, _, got, c = taken(X, P, LV)
        w = UP.windows(c); cm = float((1 - c / c.cummax()).max())
        h24 = taken([t for t in X if t["dt"] >= TE], P, LV)[0]
        ns = sum(1 for g in got if g[0] == "short")
        print(f"  {NAMES[v]:<20} {fin:6.1f}배 곡선 {cm*100:3.0f}% 1년손실 {(w < 1).mean()*100:3.0f}% 2024~ {h24:4.1f}배 · 숏 체결 {ns}건")


def main():
    core = build(S.SYMBOLS, 4)
    table(core, "42종 · 4주 연속 (지금 규칙)")
    for k in (3, 5):
        table(build(S.SYMBOLS, k), f"42종 · {k}주 연속 (표본 늘리기)")
    table(build(list(S.SYMBOLS) + list(CANDIDATE_SYMBOLS), 3), "42종+후보 22종 · 3주 연속 (가장 큰 표본)")
    wallet(core)


if __name__ == "__main__":
    main()
