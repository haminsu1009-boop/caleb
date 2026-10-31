"""
bot/breakout/test_paper.py — 돌파 모의매매가 백테스트와 같은 거래를 내는지 확인

저장소의 일봉(data/)으로 2023-01 부터 하루씩 step()을 다시 돌려, 진입(코인·날짜)을
ml/unified_pool.make_break 와 맞춰 본다. 시장 200일선 판정 날짜만 하루 다르다
(백테스트는 진입일 종가, 모의는 신호일 종가) — 그 차이로 갈리는 몇 건 말고는 같아야 한다.

    python -m bot.breakout.test_paper
"""
from __future__ import annotations
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import pandas as pd

from bot.oversold import strategy as S
from bot.breakout import paper as P
import ml.short_setups as SS
import ml.unified_pool as UP

START = pd.Timestamp("2023-01-01")


def main():
    Dd = {s: SS.load_daily(s) for s in S.SYMBOLS}
    Dd = {k: v for k, v in Dd.items() if v is not None and len(v) >= 400}
    D = {s: d.assign(dt=pd.to_datetime(d["dt"]).dt.normalize())[["dt", "open", "high", "low", "close"]]
         .reset_index(drop=True) for s, d in Dd.items()}
    want = {(t["sym"], t["dt"].normalize()) for t in UP.make_break(Dd) if t["dt"] >= START}

    st = {"started": "", "equity": P.START_EQUITY, "peak": P.START_EQUITY, "mdd": 0.0,
          "last_day": "", "positions": {}, "trades": [], "overlap_days": 0, "skipped": []}
    end = min(d["dt"].iloc[-1] for d in D.values() if d["dt"].iloc[-1] > START) - P.DAY
    got = set()
    for day in pd.date_range(START, end, freq="D"):
        view = {s: d[d["dt"] <= day + P.DAY] for s, d in D.items()}
        view = {s: v for s, v in view.items() if len(v)}
        before = set(st["positions"])
        P.step(st, view, day, set())
        got |= {(s, pd.Timestamp(st["positions"][s]["entry_day"])) for s in set(st["positions"]) - before}
    both = got & want
    print(f"구간 {START.date()} ~ {end.date()}")
    print(f"백테스트 진입 {len(want)} · 모의 진입 {len(got)} · 같음 {len(both)} "
          f"({len(both)/max(len(want),1)*100:.0f}%)")
    print(f"모의 가상 자본 {st['equity']:,.1f} (시작 {P.START_EQUITY:,.0f}) · 청산 {len(st['trades'])}건 · "
          f"강제청산 {sum(t['liq'] for t in st['trades'])}건 · 실현 최대낙폭 {st['mdd']}%")
    only_w, only_g = sorted(want - got)[:8], sorted(got - want)[:8]
    if only_w:
        print("백테스트에만:", [(s, str(d.date())) for s, d in only_w])
    if only_g:
        print("모의에만:", [(s, str(d.date())) for s, d in only_g])
    assert len(both) >= 0.85 * len(want), "백테스트와 진입이 너무 다르다"
    print("✅ 통과")


if __name__ == "__main__":
    main()
