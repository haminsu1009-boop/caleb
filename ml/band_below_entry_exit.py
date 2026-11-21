"""
ml/band_below_entry_exit.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"볼린저 상단이 평단 이하가 되면 그 거래는 끝났다" — 그 신호에서 바로 빠지면 나아지나 (2026-11-22, 사용자 관찰)

사용자 관찰: "상단이 평단가 이하로 내려가면 완전 급등하지 않은 이상 찔끔밖에 못 먹고, 아니면
계속 내려가서 청산이다." 거래 단위로 센 결과(실거래와 같은 직전 봉 밴드 기준, 2017~ 1,812건):
  A 밴드가 계속 평단 위   1,546건(85%) 승률 95% · 가격 평균 +9.4% · 4배 증거금 대비 +34.9% · 4배 청산 6%
  B 밴드가 평단 이하였던 적 266건(15%) 승률 35% · 가격 평균 -9.2% · 4배 증거금 대비 -57.9% · 4배 청산 48%
     B 의 끝: 시간청산 60%(평균 -12.9%) · 익절 34%(평균 +2.2%, 중앙값 +1.6%) · 손절 6%(-40%)
     B 중 가격 +10% 이상으로 끝난 것 1%, -15% 이하로 끝난 것 26%
     B 를 밴드가 평단 이하였던 길이로 나누면 1~6봉 승률 72% · 7~18봉 55% · 19봉 이상 13%(4배 청산 57%)
  → 사용자 관찰이 맞다. 이 신호 뒤에는 이익이 작고(+2.2%) 청산이 흔하다(48%).

그래서 규칙을 시험한다: 직전 봉 밴드가 평단 이하인 봉이 연속이 아니어도 누적 X봉을 넘으면 다음 봉
시가(시장가)에 전량 청산한다. X ∈ {0, 3, 6, 12, 24}봉. 정상 익절·손절·시간청산은 그대로다.
기준선은 실거래와 같은 직전 봉 밴드 31.5배·곡선 25%·1년손실 9%·2024~ 5.79배(ml/tp_band_below_entry.py).
판정: 지갑 전체에서 2017~ · 2024~ · 곡선낙폭 · 1년손실이 모두 기준선 이상.

━━ 결과 ━━
보류 — 사용자 판단 (2026-11-22). 엄격 기준(네 지표 모두 기준선 이상)은 못 맞추지만 1년손실이 크게 준다.
                          2017~ 곡선낙폭 1년손실 ~2023  2024~  밴드탈출
    기준선(직전 봉 밴드)   31.5배   25%     9%    5.4배  5.79배      0
    누적 0봉 초과(즉시)    22.8배   33%     6%    4.0배  5.67배   270/1840
    누적 3봉 초과          28.0배   25%     2%    4.9배  5.73배   244/1836
    누적 6봉 초과          29.7배   25%     2%    5.2배  5.78배   221/1832
    누적 12봉 초과         30.1배   25%     5%    5.3배  5.68배   177/1823
    누적 24봉 초과         31.2배   25%     9%    5.5배  5.74배   111/1813
  이웃(3·6·12봉)이 모두 "수익 -4~-11%, 1년손실 9%→2~5%, 낙폭 같음, 2024~ -0.01~-0.11배"로 같은 방향이다.
  즉시 탈출(0봉)은 반등 직전 거래까지 잘라 낙폭이 33%로 나빠진다. 6봉이 가장 균형이 좋았다.
  연도별(6봉): 2018 -12→-9, 2022 +19→+21, 2025 +147→+151 으로 좋아지고, 2020 +22→+17, 2021 +134→+123
  으로 나빠진다. 얻는 것은 "손실 나는 해가 줄어드는 것", 잃는 것은 "대상승장 이익 일부(약 -6%)"다.
  주의: 사후에 6봉을 고른 것이고, 1년손실 9%는 15일 간격 겹치는 창 196개 중 약 18개라 독립된
  표본은 몇 개 구간(2018·2022 등)뿐이다. 실거래 반영은 bot/ 변경(포지션별 밴드≤평단 봉수 기록)이라
  사용자 확인이 필요하다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import os, sys, warnings
warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import numpy as np, pandas as pd
import ml.tp_band_below_entry as T          # 같은 봉/직전 봉 밴드 패치가 들어간 sim 소스(T._src)
import ml.unified_pool as UP, ml.short_setups as SS
import ml.module_winrate as MW
from bot.oversold import strategy as S
from bot.oversold import regime as REG
from ml.backtest_current_bot import load
from ml.per_coin_walkforward import MENU
from ml.per_coin_portfolio import to_up
from ml.bear_leverage import bear_series, is_on, T0, TE
from ml.crash_window import crash_hits, in_window

_src = T._src.replace("def sim_u(", "def sim_x(")
_r1 = '        reason = "time"\n'
assert _src.count(_r1) == 1
_src = _src.replace(_r1, _r1 + "        off_bars = 0\n")
_r2 = "            # 분할매도 — 낮은 목표부터 순서대로\n"
assert _src.count(_r2) == 1
_src = _src.replace(_r2, '''            _u = lv[1.5][bar - 1]
            if not np.isnan(_u) and _u <= avg:
                off_bars += 1
                if UND["offx"] is not None and off_bars > UND["offx"]:
                    sold.append((left, o[bar])); left = 0.0
                    ex_bar, reason = bar, "off"; break
''' + _r2)
UND = T.UND; UND["offx"] = None
_ns = dict(T.PCR.__dict__); _ns["UND"] = UND
exec(_src, _ns); sim_x = _ns["sim_x"]


def main():
    Dd = {s: SS.load_daily(s) for s in S.SYMBOLS}
    Dd = {k: v for k, v in Dd.items() if v is not None and len(v) >= 400}
    W = {s: SS.to_weekly(d) for s, d in Dd.items()}
    ma, th, hd, fr, ou, st = MENU["A 지금 봇"]
    G = {s: load(s) for s in S.SYMBOLS}
    G = {s: g for s, g in G.items() if g is not None and len(g) >= 400}
    cut = lambda X: [t for t in X if t["dt"] >= T0]
    Sh, Dv = cut(UP.make_short(W)), cut(UP.make_div(Dd))
    btc = Dd["BTCUSDT"].set_index("dt")["close"]
    B = bear_series(btc, REG.AUTO_BEAR_ON, REG.AUTO_BEAR_OFF, REG.AUTO_BEAR_N)
    hits = crash_hits(G["BTCUSDT"].set_index("datetime")["close"].astype(float))
    lv = {"long": 4.0, "longb": 2.0, "short": 1.0, "div": 1.0}
    pt = {"long": .015, "longb": .015, "short": .40, "div": .40}
    bearf = lambda ts: is_on(B, ts) or in_window(hits, ts)
    UND["prev"], UND["nocond"], UND["act"] = True, False, (lambda ts: True)

    def win(c):
        v = c.values
        return np.array([v[i + 365] / v[i] for i in range(0, len(c) - 365, 15)])

    def run(lab, offx):
        UND["offx"] = offx
        L = []
        for s, g in G.items():
            o, h, l, c = (g[q].astype(float).values for q in ("open", "high", "low", "close"))
            ts = sim_x(o, h, l, c, g["datetime"].values, ma, th, hd, fr, ou, S.STOP_PCT, sym=s, step=st)
            L += [dict(to_up(t), reason=t["reason"]) for t in ts]
        L = cut(L)
        tr = [dict(t, kind="longb") if bearf(t["dt"]) else t for t in L] + Sh + Dv
        fin, mdd, got, c = MW.taken(tr, pt, lv)
        a = MW.taken([t for t in tr if t["dt"] < TE], pt, lv)[0]
        h = MW.taken([t for t in tr if t["dt"] >= TE], pt, lv)[0]
        y = c.resample("YE").last(); yr = ((y / y.shift(1).fillna(1) - 1) * 100)
        no = sum(1 for t in L if t["reason"] == "off")
        r = dict(fin=fin, cdd=float((1 - c / c.cummax()).max() * 100), l1=(win(c) < 1).mean() * 100,
                 a=a, h=h, no=no, n=len(L))
        print(f"{lab:<22}{fin:>6.1f}배 곡선{r['cdd']:>4.0f}% 1년손실{r['l1']:>3.0f}% ~2023 {a:>5.1f}배 "
              f"2024~ {h:>5.2f}배 밴드탈출 {no}/{len(L)}건 | "
              + " ".join(f"{d.year%100}:{v:+.0f}" for d, v in yr.items() if d.year >= 2018), flush=True)
        return r

    base = run("기준선(직전 봉 밴드)", None)
    for x in (0, 3, 6, 12, 24):
        r = run(f"밴드≤평단 누적 {x}봉 초과", x)
        bad = [f"{nm} {base[key]:.1f}→{r[key]:.1f}" for key, nm, sg in
               (("fin", "2017~", 1), ("h", "2024~", 1), ("cdd", "곡선낙폭", -1), ("l1", "1년손실", -1))
               if (r[key] - base[key]) * sg < -1e-9]
        print("      ", "통과" if not bad else "나빠짐 " + ", ".join(bad))


if __name__ == "__main__":
    main()
