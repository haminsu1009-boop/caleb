"""
ml/divergence_ladder.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
다이버전스 사다리 매수 — 새 저점마다 재확인되면 추가

지정된 규칙을 그대로 옮긴다.

  진입/추가 조건 (같은 조건이 반복된다)
    · 직전에 본 저점보다 더 낮은 저점을 만든다
    · 그런데 그 저점의 RSI는 직전 저점 때보다 높다 (강세 다이버전스)
    · 그 다음 봉이 양봉으로 마감한다
    → 그 시점에 매수 (1차든 2차든 3차든)

  청산 조건
    · 볼린저 밴드 상단 위로 양봉 마감할 때
    · 그 전까지는 계속 들고, 더 빠지면 위 조건이 나올 때마다 추가

앞서 ml/divergence_scalein.py에서 시험한 것과 다른 점은 추가 매수
시점이다. 그때는 "1차 대비 -5%/-8% 빠질 때마다" 라는 가격 트리거를
썼는데, 실제 규칙은 그게 아니라 **다이버전스가 다시 확인될 때마다**다.
가격이 얼마나 빠졌는지가 아니라 저점의 질이 좋아졌는지를 본다.

이 차이가 결과를 바꾸는지 확인한다. 바꾸지 않으면 앞선 결론
("효과는 신호가 아니라 분할매수 구조에서 온다")이 그대로 유지된다.

비교 대상
  · 고정 -5% 트리거 분할 (앞서 시험한 것)
  · 무작위 시점에 같은 사다리 (신호에 정보가 있는지)
  · 현재 봇 규칙 (이평 -12.26%)

수수료는 매수 회차마다 편도, 청산에 편도.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from bot.oversold import strategy as S
import ml.short_setups as SS

ONE_WAY = 0.20
TE = pd.Timestamp("2024-01-01")


def bb(c, n=20, k=2.0):
    m = pd.Series(c).rolling(n).mean()
    s = pd.Series(c).rolling(n).std()
    return (m + k * s).values


def swing_lows(low, k=3):
    """좌우 k봉보다 낮은 저점. 확정은 k봉 뒤다."""
    n = len(low)
    out = []
    for i in range(k, n - k):
        w = low[i - k:i + k + 1]
        if low[i] == w.min() and (w == low[i]).sum() == 1:
            out.append(i)
    return out


def ladder_trades(d, *, period=14, k=3, max_adds=3, max_hold=120,
                  stop_pct=-40.0, bb_n=20, bb_k=2.0, random_entry=None):
    """사다리 매수 거래를 만든다.

    random_entry가 주어지면 다이버전스 대신 그 인덱스에서 시작한다
    (신호에 정보가 있는지 보는 기준선).
    """
    o, h, l, c = (d["open"].values, d["high"].values,
                  d["low"].values, d["close"].values)
    dt = d["dt"].values
    r = SS.rsi(c, period)
    up = bb(c, bb_n, bb_k)
    n = len(c)
    piv = swing_lows(l, k)
    bull = c > o

    # 각 스윙 저점에 대해 "확정 후 첫 양봉" 인덱스를 미리 구한다
    confirm = {}
    for p in piv:
        j = p + k
        end = min(j + 5, n)
        while j < end and not bull[j]:
            j += 1
        if j < end and bull[j]:
            confirm[p] = j

    # 진입도 다이버전스여야 한다. 처음 짤 때 이 검사를 빼먹어서
    # "스윙 저점마다 양봉이면 진입"이 되어 버렸고, 거래가 9,717건까지
    # 불어나며 무작위 기준선과 같은 성적이 나왔다. 진입 조건은
    # 추가 조건과 동일하다 — 직전 스윙보다 저점은 낮고 RSI는 높다.
    div_entry = []
    for a, b in zip(piv[:-1], piv[1:]):
        if np.isnan(r[a]) or np.isnan(r[b]):
            continue
        if l[b] < l[a] and r[b] > r[a] and b in confirm:
            div_entry.append(b)

    trades = []
    used = set()
    seq = random_entry if random_entry is not None else div_entry

    for start in seq:
        if random_entry is None:
            if start not in confirm or start in used:
                continue
            entry_bar = confirm[start] + 1          # 다음 봉 시가에 체결
            last_low, last_rsi = l[start], r[start]
        else:
            entry_bar = start + 1
            last_low, last_rsi = l[start], r[start]
        if entry_bar >= n or np.isnan(last_rsi):
            continue

        px = [o[entry_bar]]
        qty = [1.0]
        adds = 0
        exit_bar = exit_px = None
        reason = "time"
        # 이 거래 동안 쓰인 스윙 저점은 다음 거래의 시작점이 되지 않게 한다
        for bar in range(entry_bar, min(entry_bar + max_hold, n)):
            avg = float(np.average(px, weights=qty))
            if stop_pct and l[bar] <= avg * (1 + stop_pct / 100):
                exit_bar, exit_px, reason = bar, avg * (1 + stop_pct / 100), "stop"
                break
            # 청산: 볼린저 상단 위로 양봉 마감
            if not np.isnan(up[bar]) and c[bar] > up[bar] and bull[bar]:
                exit_bar, exit_px, reason = bar, c[bar], "bb"
                break
            # 추가: 이 봉이 어떤 스윙 저점의 확정 양봉인가
            if adds < max_adds and random_entry is None:
                for p, j in confirm.items():
                    if j != bar or p in used:
                        continue
                    if l[p] < last_low and r[p] > last_rsi:
                        if bar + 1 < n:
                            px.append(o[bar + 1]); qty.append(1.0)
                            adds += 1
                            last_low, last_rsi = l[p], r[p]
                            used.add(p)
                    break
        if exit_bar is None:
            exit_bar = min(entry_bar + max_hold, n - 1)
            exit_px = c[exit_bar]
        avg = float(np.average(px, weights=qty))
        filled = len(px)
        trades.append({"dt": pd.Timestamp(dt[entry_bar]), "sym": d.attrs.get("sym", "?"),
                       "ret": (exit_px / avg - 1) * 100 - ONE_WAY * (filled + 1),
                       "filled": filled, "reason": reason,
                       "bars": exit_bar - entry_bar})
        if random_entry is None:
            used.add(start)
    return trades


def fixed_trades(d, *, add_pct=-5.0, max_adds=3, max_hold=120,
                 stop_pct=-40.0, bb_n=20, bb_k=2.0):
    """비교용 — 앞서 시험한 고정 가격 트리거 분할."""
    o, h, l, c = (d["open"].values, d["high"].values,
                  d["low"].values, d["close"].values)
    dt = d["dt"].values
    r = SS.rsi(c, 14)
    up = bb(c, bb_n, bb_k)
    n = len(c)
    piv = swing_lows(l, 3)
    bull = c > o
    trades = []
    lock = -10**9
    for a, b in zip(piv[:-1], piv[1:]):
        if b <= lock or np.isnan(r[a]) or np.isnan(r[b]):
            continue
        if not (l[b] < l[a] and r[b] > r[a]):
            continue
        j = b + 3
        end = min(j + 5, n)
        while j < end and not bull[j]:
            j += 1
        if j >= end or not bull[j] or j + 1 >= n:
            continue
        e = o[j + 1]
        px = [e]; qty = [1.0]; filled = 1
        trig = e * (1 + add_pct / 100)
        exit_bar = exit_px = None; reason = "time"
        for bar in range(j + 1, min(j + 1 + max_hold, n)):
            avg = float(np.average(px, weights=qty))
            while filled < max_adds + 1 and c[bar] <= trig:
                px.append(c[bar]); qty.append(1.0); filled += 1
                trig = e * (1 + add_pct * filled / 100)
                avg = float(np.average(px, weights=qty))
            if stop_pct and l[bar] <= avg * (1 + stop_pct / 100):
                exit_bar, exit_px, reason = bar, avg * (1 + stop_pct / 100), "stop"; break
            if not np.isnan(up[bar]) and c[bar] > up[bar] and bull[bar]:
                exit_bar, exit_px, reason = bar, c[bar], "bb"; break
        if exit_bar is None:
            exit_bar = min(j + 1 + max_hold, n - 1); exit_px = c[exit_bar]
        avg = float(np.average(px, weights=qty))
        trades.append({"dt": pd.Timestamp(dt[j + 1]), "ret": (exit_px/avg-1)*100 - ONE_WAY*(filled+1),
                       "filled": filled, "reason": reason, "bars": exit_bar-(j+1)})
        lock = exit_bar
    return trades


def summarize(name, rows):
    d = pd.DataFrame(rows)
    if len(d) < 20:
        return f"  {name:<32s}{len(d):>7d}   표본 부족"
    tr, ho = d[d.dt < TE], d[d.dt >= TE]
    f = lambda x: f"{x.ret.mean():+.2f}%" if len(x) > 10 else "   —"
    return (f"  {name:<32s}{len(d):>7d}{(d.ret>0).mean()*100:>7.1f}%"
            f"{d.ret.mean():>8.2f}%{d.ret.median():>8.2f}%{f(tr):>9s}{f(ho):>9s}"
            f"{(d.reason=='bb').mean()*100:>8.0f}%{d.filled.mean():>7.2f}{d.bars.mean():>7.0f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weekly", action="store_true")
    a = ap.parse_args()
    syms = [s for s in S.SYMBOLS if os.path.exists(f"data/{s}_1d_all.csv.gz")]
    data = {}
    for s in syms:
        d = SS.load_daily(s)
        if d is None or len(d) < 400:
            continue
        d = SS.to_weekly(d) if a.weekly else d
        d.attrs["sym"] = s
        data[s] = d
    unit = "주" if a.weekly else "일"
    hold = 30 if a.weekly else 120

    print("=" * 104)
    print(f"  다이버전스 사다리 — 새 저점마다 RSI가 더 높고 양봉이면 추가, "
          f"볼린저 상단 위 양봉에 청산")
    print(f"  {len(data)}종 · {unit}봉 · 편도 {ONE_WAY}% × (매수 회차+1) · 최대 보유 {hold}{unit}")
    print("=" * 104)
    print(f"\n  {'설정':<32s}{'거래':>7s}{'승률':>7s}{'거래당':>8s}{'중앙':>8s}"
          f"{'학습':>9s}{'홀드아웃':>9s}{'목표도달':>8s}{'평균매수':>7s}{'보유':>7s}")
    print("  " + "-" * 102)

    for adds in (0, 1, 2, 3, 5):
        rows = []
        for s, d in data.items():
            rows += ladder_trades(d, max_adds=adds, max_hold=hold)
        lab = "1회 매수 (추가 없음)" if adds == 0 else f"사다리 · 최대 {adds}회 추가"
        print(summarize(lab, rows))

    print()
    for pct in (-5.0, -8.0):
        rows = []
        for s, d in data.items():
            rows += fixed_trades(d, add_pct=pct, max_adds=3, max_hold=hold)
        print(summarize(f"고정 {pct:.0f}% 트리거 · 3회 추가", rows))

    rng = np.random.default_rng(0)
    rows = []
    for s, d in data.items():
        idx = np.where(rng.random(len(d)) < 0.01)[0]
        rows += ladder_trades(d, max_hold=hold, random_entry=idx)
    print(summarize("(기준선) 무작위 시점 · 1회 매수", rows))

    print(f"\n  '목표도달' = 볼린저 상단 위 양봉 마감으로 청산된 비율")
    print(f"  '평균매수' = 실제로 몇 회 샀나 · '보유' = 평균 보유 {unit}수")


if __name__ == "__main__":
    main()
