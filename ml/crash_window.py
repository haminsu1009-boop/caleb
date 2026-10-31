"""
ml/crash_window.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
급락 감지 — BTC가 하루 만에 무너지면 그 뒤 3일 새 롱을 2배로

60일 기준 자동 폭락장(ml/bear_leverage.py)은 며칠~몇 주에 걸친 하락에만
켜진다. 하루짜리 폭락(2020-03-12 코로나, 2022-11-08 FTX)에는 당일 롱이
전부 4배로 들어가 청산이 몰렸다.

규칙: BTC 4시간봉 확정 종가가 직전 6봉(24시간) 최고 종가보다 10% 이상
낮으면, 그 봉 시작부터 3일 동안 새 롱 2배(증거금 1.5% 그대로).
진입 시각에 이미 닫힌 봉만 쓴다. 60일 폭락장과 둘 중 하나면 2배.
시뮬레이터 ml/module_winrate.taken (증거금 상한 95%). 2017-08~.

━━ 결과 ━━
                                  2017~  2019~  낙폭  1년손실(17~/19~)  ~2023  2024~
    60일 폭락장 2배만               36배   34배   21%     9% / 2%        5.7배  6.3배
    + 24h -10% 급락 후 3일 2배      36배   33배   21%     2% / 0%        5.8배  6.2배
  기준을 흔들어도 같은 방향 (1년손실 9% → 2~7%):
    -8%·3일 35배 2% · -10%·7일 35배 2% · -15%·3일 42배 6% · -15%·7일 41배 7%
  급락 3일 창 롱 281건: 4배였다면 청산 27건 → 2배 0건. 창 안 최악 역행 -42.8%.

  안 된 것:
    · 창 안에서 증거금 3%(같은 명목, 반등을 4배만큼): 55배로 보이지만 계산
      방식(60일 폭락장과 겹치는 날 처리)에 따라 33배·낙폭 40%로 흔들리고,
      창 안 동시 증거금이 계좌의 93%까지 간다 — 순간 폭락 한 번에 끝난다.
    · 창 안에서 진입선을 -15~-25%로 깊게(4배): 청산 16~29건 남고 낙폭 25~26%.
      청산은 산 가격 기준이라 싸게 사도 청산선이 멀어지지 않는다.
    · 창 안 3%·깊은 진입·분할 간격 확대: 동시 증거금 93~95% 그대로.
    · 저점에서 5·8·12% 반등하면 4배 복귀: 차이 없음(신호는 급락 중에 난다).

  ⚠️ 2025-10-10: 알트 순간 저가 -78~-100%(바이낸스 현물). 그날 열린 롱이
  없었을 뿐이다. 그런 순간에 롱을 들고 있으면 2배도 손절가 아래로 뚫린다.

사용법:
    python ml/crash_window.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations
import os, sys, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from bot.oversold import strategy as S
from bot.oversold import regime as REG
import ml.unified_pool as UP
import ml.short_setups as SS
from ml.backtest_current_bot import load
from ml.per_coin_rules import sim
from ml.per_coin_walkforward import MENU
from ml.per_coin_portfolio import to_up
from ml.module_winrate import taken
from ml.bear_leverage import bear_series, is_on, T0, T19, TE


def crash_hits(btc4h: pd.Series) -> pd.DatetimeIndex:
    """급락 감지가 켜진 4시간봉의 시작 시각들 (봇의 REG.crash_drop과 같은 계산)."""
    dd = (btc4h / btc4h.rolling(REG.CRASH_BARS).max() - 1) * 100
    return dd[dd <= REG.CRASH_DROP].index


def in_window(hits: pd.DatetimeIndex, ts) -> bool:
    ts = pd.Timestamp(ts)
    i = hits.searchsorted(ts, side="left") - 1      # 진입 시각보다 앞선 봉만
    return i >= 0 and ts - hits[i] <= pd.Timedelta(days=REG.CRASH_DAYS)


def main():
    Dd = {s: SS.load_daily(s) for s in S.SYMBOLS}
    Dd = {k: v for k, v in Dd.items() if v is not None and len(v) >= 400}
    W = {s: SS.to_weekly(d) for s, d in Dd.items()}
    ma, th, hd, fr, ou, st = MENU["A 지금 봇"]
    L = []
    for s in S.SYMBOLS:
        g = load(s)
        o, h, l, c = (g[k].astype(float).values for k in ("open", "high", "low", "close"))
        L += [to_up(t) for t in sim(o, h, l, c, g["datetime"].values, ma, th, hd, fr, ou,
                                    S.STOP_PCT, sym=s, step=st)]
    cut = lambda X: [t for t in X if t["dt"] >= T0]
    L, Sh, Dv = cut(L), cut(UP.make_short(W)), cut(UP.make_div(Dd))
    btc = Dd["BTCUSDT"].set_index("dt")["close"]
    B = bear_series(btc, REG.AUTO_BEAR_ON, REG.AUTO_BEAR_OFF, REG.AUTO_BEAR_N)
    hits = crash_hits(load("BTCUSDT").set_index("datetime")["close"].astype(float))
    pt = {"long": .015, "longb": .015, "short": .40, "div": .40}
    lv = {"long": 4.0, "longb": 2.0, "short": 1.0, "div": 1.0}

    def run(lab, use_crash):
        tr = [dict(t, kind="longb") if (is_on(B, t["dt"]) or (use_crash and in_window(hits, t["dt"])))
              else t for t in L] + Sh + Dv
        f = lambda X: taken(X, pt, lv)
        fin, mdd, _, c = f(tr); w = UP.windows(c)
        f19, _, _, c19 = f([t for t in tr if t["dt"] >= T19]); w19 = UP.windows(c19)
        a = f([t for t in tr if t["dt"] < TE])[0]; h = f([t for t in tr if t["dt"] >= TE])[0]
        print(f"{lab:<30}{fin:>6.1f}배{f19:>6.1f}배{mdd*100:>5.0f}%{(w<1).mean()*100:>7.0f}%"
              f"{(w19<1).mean()*100:>5.0f}%{a:>6.1f}배{h:>6.1f}배")

    print(f"{'':<30}{'2017~':>7}{'2019~':>7}{'낙폭':>6}{'1년손실':>7}{'19~':>5}{'~2023':>7}{'2024~':>7}")
    run("60일 폭락장 2배만", False)
    run("+ 급락 3일 2배 (봇 설정)", True)


if __name__ == "__main__":
    main()
