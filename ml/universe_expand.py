"""
ml/universe_expand.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
42종에 후보 코인을 더하면 지갑 결과가 나아지는가

후보(bybit/collect_history.CANDIDATE_SYMBOLS)는 성적이 아니라 객관 기준
(바이낸스 현물 2023년 이전 상장 · 바이빗 같은 티커 무기한 · 이름 변경 없음)
으로 골랐다. 판단도 "코인 하나씩 골라 넣기"가 아니라 **후보 전부를
한꺼번에** 넣었을 때로 한다 — 코인별로 고르면 과거 성적에 맞추는 것이
되고, 코인별 규칙·선별은 지금까지 매번 졌다(ml/coin_selection.py 등).

지금 봇과 같은 설정: 롱 4배(60일 폭락장·24시간 급락이면 2배), 숏·다이버
1배, 증거금 상한 95%, 전날 종가/확정 봉만. 2017~ · 학습 ~2023 · 검증 2024~.
채택 조건: 2017~·최대낙폭(곡선 기준 포함)·1년손실·2024~ 가 모두 지금 이상.

참고용으로 후보별 롱 거래 수·승률도 찍지만, 그걸 보고 골라 넣지 않는다.

━━ 결과 (2026-10-05, 후보 22종 전부 수집 후) — 기각 ━━
                     2017~  2019~  낙폭  곡선낙폭  1년손실(17~/19~)  ~2023  2024~
    지금 42종        36.2배  32.9배  21%    25%      2% / 0%        5.8배  6.2배
    42종 + 후보 22종  19.3배  17.7배  31%    37%     20% / 19%       3.2배  6.0배
  후보 롱만 보면 승률 60~90%로 42종과 비슷하다. 그런데 지갑 전체는 모든
  지표가 나빠진다. 신호가 54% 늘면서(롱 1,817→2,801, 다이버 66→116)
  대폭락 날 동시에 들고 있는 롱이 늘고, 다이버(40%)가 증거금을 더 자주
  잡아 좋은 자리가 밀린다. 코인 수를 늘리는 건 답이 아니다.

사용법:
    python ml/universe_expand.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations
import os, sys, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "bybit")); os.chdir(ROOT)
from bot.oversold import strategy as S
from bot.oversold import regime as REG
import ml.unified_pool as UP
import ml.short_setups as SS
from ml.backtest_current_bot import load
from ml.per_coin_rules import sim
from ml.per_coin_walkforward import MENU
from ml.per_coin_portfolio import to_up
from ml.module_winrate import taken, net
from ml.bear_leverage import bear_series, is_on, T0, T19, TE
from ml.crash_window import crash_hits, in_window
from collect_history import CANDIDATE_SYMBOLS


def curve_mdd(c: pd.Series) -> float:
    """차단기의 고점 리셋 없이 잰 잔고 곡선 최대낙폭."""
    return float((1 - c / c.cummax()).max())


def main():
    have = [s for s in CANDIDATE_SYMBOLS
            if os.path.exists(f"data/{s}_4h_all.csv.gz") and os.path.exists(f"data/{s}_1d_all.csv.gz")]
    print(f"후보 {len(CANDIDATE_SYMBOLS)}종 중 데이터 있는 것 {len(have)}종")
    if not have:
        print("아직 수집 전이다."); return
    ma, th, hd, fr, ou, st = MENU["A 지금 봇"]

    def longs(syms):
        out = []
        for s in syms:
            g = load(s)
            if g is None or len(g) < 400:
                continue
            o, h, l, c = (g[k].astype(float).values for k in ("open", "high", "low", "close"))
            out += [to_up(t) for t in sim(o, h, l, c, g["datetime"].values, ma, th, hd, fr, ou,
                                          S.STOP_PCT, sym=s, step=st)]
        return [t for t in out if t["dt"] >= T0]

    def daily(syms):
        D = {s: SS.load_daily(s) for s in syms}
        return {k: v for k, v in D.items() if v is not None and len(v) >= 400}

    base_syms = list(S.SYMBOLS)
    btc = SS.load_daily("BTCUSDT").set_index("dt")["close"]
    B = bear_series(btc, REG.AUTO_BEAR_ON, REG.AUTO_BEAR_OFF, REG.AUTO_BEAR_N)
    hits = crash_hits(load("BTCUSDT").set_index("datetime")["close"].astype(float))
    pt = {"long": .015, "longb": .015, "short": .40, "div": .40}
    lv = {"long": 4.0, "longb": 2.0, "short": 1.0, "div": 1.0}

    def run(syms, lab):
        L = longs(syms); D = daily(syms); W = {s: SS.to_weekly(d) for s, d in D.items()}
        Sh = [t for t in UP.make_short(W) if t["dt"] >= T0]
        Dv = [t for t in UP.make_div(D) if t["dt"] >= T0]
        tr = [dict(t, kind="longb") if (is_on(B, t["dt"]) or in_window(hits, t["dt"])) else t
              for t in L] + Sh + Dv
        f = lambda X: taken(X, pt, lv)
        fin, mdd, _, c = f(tr); w = UP.windows(c)
        f19, _, _, c19 = f([t for t in tr if t["dt"] >= T19]); w19 = UP.windows(c19)
        a = f([t for t in tr if t["dt"] < TE])[0]; h = f([t for t in tr if t["dt"] >= TE])[0]
        print(f"{lab:<26}{fin:>7.1f}배{f19:>7.1f}배{mdd*100:>5.0f}%{curve_mdd(c)*100:>7.0f}%"
              f"{(w<1).mean()*100:>6.0f}%{(w19<1).mean()*100:>4.0f}%{a:>6.1f}배{h:>6.1f}배"
              f"  롱 {len(L)} 숏 {len(Sh)} 다이버 {len(Dv)}")
        return L

    print(f"\n{'':<26}{'2017~':>8}{'2019~':>8}{'낙폭':>6}{'곡선낙폭':>8}{'1년손실':>7}{'19~':>4}{'~2023':>7}{'2024~':>7}")
    run(base_syms, "지금 42종")
    Lc = run(base_syms + have, f"42종 + 후보 {len(have)}종")

    print("\n후보별 롱 (참고만 — 이걸 보고 골라 넣지 않는다)")
    for s in have:
        x = [t for t in Lc if t["sym"] == s]
        if not x:
            print(f"  {s[:-4]:<8} 0건"); continue
        r = np.array([net(t, 4) * 4 for t in x])
        first = load(s)["datetime"].iloc[0]
        print(f"  {s[:-4]:<8}{pd.Timestamp(first):%Y-%m}~  {len(x):>3}건  승률 {(r>0).mean()*100:>3.0f}%  "
              f"평균 {r.mean():+5.1f}%  청산 {sum(t['mae']<=-24.5 for t in x)}")


if __name__ == "__main__":
    main()
