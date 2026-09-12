"""
ml/funding_carry.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
펀딩 캐리 — 펀딩비를 '신호'가 아니라 '수익원'으로 본다

지금까지 펀딩비를 진입 필터로만 시험했고 전부 탈락했다. 그런데
펀딩비는 원래 신호가 아니라 **현금 흐름**이다.

  무기한 선물은 8시간마다 롱↔숏이 펀딩비를 주고받는다.
  펀딩비가 플러스면 롱이 숏에게 낸다.
  그러면 "현물 매수 + 선물 숏"을 동시에 들면
    · 가격이 오르든 내리든 손익이 상쇄된다(델타 중립)
    · 펀딩비만 남는다
  이게 캐리 트레이드다. 방향성 없이 돈이 들어온다.

한계를 먼저 밝힌다
  · 이 세션에는 **선물 가격 데이터가 없다**(현물만 있다). 그래서
    현물-선물 베이시스 변동을 모델링할 수 없다. 여기서는 두 가격이
    같다고 가정한다 — 실제로는 베이시스가 벌어졌다 좁혀지며
    손익이 생기고, 그게 이 전략의 진짜 위험이다.
  · 따라서 아래 숫자는 **상한선**이다. 실제는 이보다 낮다.
  · 청산 위험도 뺐다. 선물 숏 다리는 가격이 오르면 증거금을
    잃는다(현물 다리 이익이 상쇄하지만 거래소가 다르면 위험하다).

그래도 볼 값어치가 있다. 상한선이 낮으면 시도할 이유가 없고,
높으면 선물 가격을 모아서 제대로 볼 이유가 생긴다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, glob, argparse, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from bot.oversold import strategy as S

# 왕복 수수료. 캐리는 현물+선물 두 다리를 열고 닫으므로 네 번이다.
ONE_LEG = 0.055          # % 테이커 편도
TE = pd.Timestamp("2024-01-01")


def load_funding():
    out = {}
    for f in sorted(glob.glob("data/funding/*_funding.csv.gz")):
        sym = os.path.basename(f).split("_")[0]
        d = pd.read_csv(f, compression="gzip", parse_dates=["datetime"])
        d = d.dropna(subset=["datetime"]).sort_values("datetime")
        out[sym] = d.set_index("datetime")["funding_rate"] * 100   # %
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold-days", type=int, default=7)
    a = ap.parse_args()
    FR = load_funding()
    print("=" * 88)
    print("  펀딩 캐리 상한선 — 현물 롱 + 선물 숏 (델타 중립)")
    print(f"  수수료: 진입 두 다리 + 청산 두 다리 = 편도 {ONE_LEG}% × 4 = {ONE_LEG*4:.2f}%")
    print("=" * 88)

    all_fr = pd.DataFrame(FR)
    print(f"\n  종목 {all_fr.shape[1]}개 · {all_fr.index.min().date()} ~ {all_fr.index.max().date()}")
    m = all_fr.mean(axis=1)
    print(f"  전 종목 평균 펀딩비 {m.mean():+.4f}%/8h → 연율 {m.mean()*3*365:+.1f}%")
    print(f"  플러스인 시점 {(m>0).mean()*100:.0f}% · 마이너스 {(m<0).mean()*100:.0f}%")

    print(f"\n  ── ① 그냥 늘 들고 있으면 (전 종목 균등, 8시간마다 정산)")
    print(f"     펀딩만 받는다고 치면 연 {m.mean()*3*365:+.1f}%")
    print(f"     여기서 수수료는 진입·청산 한 번씩이므로 거의 무시된다")
    print(f"     → 방향성 없이 연 {m.mean()*3*365:+.1f}%. 낮지만 위험도 거의 없다(상한선 기준)")

    print(f"\n  ── ② 펀딩비가 높은 종목만 골라 들면")
    print(f"  {'문턱':>10s}{'해당 시점':>10s}{'평균 펀딩':>11s}{'연율':>9s}"
          f"{'{}일 보유 수익'.format(a.hold_days):>14s}")
    print("  " + "-" * 56)
    periods = a.hold_days * 3          # 8시간 단위
    for th in (0.0, 0.01, 0.02, 0.05, 0.10):
        hits = []
        for sym, s in FR.items():
            v = s[s > th]
            if len(v) == 0:
                continue
            # 그 시점부터 periods만큼 받는다
            idx = s.index.get_indexer(v.index)
            for i in idx:
                seg = s.iloc[i:i + periods]
                if len(seg) < periods:
                    continue
                hits.append(seg.sum())
        if not hits:
            print(f"  {th:>9.2f}%   해당 없음"); continue
        hits = np.array(hits)
        net = hits - ONE_LEG * 4
        frac = sum((s > th).mean() for s in FR.values()) / len(FR) * 100
        print(f"  {th:>9.2f}%{frac:>9.0f}%{hits.mean()/periods:>10.4f}%"
              f"{hits.mean()/periods*3*365:>8.1f}%{net.mean():>13.3f}%")

    print(f"\n  ── ③ 연간 몇 번 굴릴 수 있나 (문턱 0.05% 기준)")
    th = 0.05
    n_per_year = {}
    for sym, s in FR.items():
        cnt = (s > th).sum()
        yrs = (s.index[-1] - s.index[0]).days / 365
        if yrs > 0.5:
            n_per_year[sym] = cnt / yrs
    v = pd.Series(n_per_year)
    print(f"     종목당 연평균 {v.mean():.0f}회 기회 (8시간 단위)")
    print(f"     = 연 {v.mean()/3:.0f}일치. {len(FR)}종이면 자리는 충분하다")

    print(f"\n  ── ④ 극단적으로 높은 펀딩비는 얼마나 자주 나오나")
    print(f"  {'구간':>16s}{'비중':>8s}{'평균 연율':>11s}")
    print("  " + "-" * 36)
    allv = pd.concat(FR.values())
    for lo, hi, lab in [(-99, -0.05, "-0.05% 미만"), (-0.05, 0, "-0.05~0%"),
                        (0, 0.01, "0~0.01%"), (0.01, 0.05, "0.01~0.05%"),
                        (0.05, 0.10, "0.05~0.10%"), (0.10, 99, "0.10% 초과")]:
        seg = allv[(allv >= lo) & (allv < hi)]
        if len(seg) == 0:
            continue
        print(f"  {lab:>16s}{len(seg)/len(allv)*100:>7.1f}%{seg.mean()*3*365:>10.1f}%")

    print(f"""
  ── 읽는 법
     펀딩 캐리의 수익은 '펀딩비 연율'이 상한이다. 전 종목 평균이
     연 {m.mean()*3*365:+.1f}%이므로, 아무 때나 들고 있는 방식은 그 근처가 한계다.
     높은 펀딩비만 골라 잡으면 연율은 올라가지만 기회가 드물어져
     자본이 놀고, 그만큼 실효 수익률은 내려간다.

     그리고 이 숫자에는 베이시스 손익이 빠져 있다. 선물 가격
     데이터가 없어서다. 실제 캐리는 펀딩을 받는 동안 베이시스가
     불리하게 움직이면 그만큼 깎인다 — 특히 펀딩비가 극단으로
     높을 때가 베이시스도 가장 불안정할 때다.
""")


if __name__ == "__main__":
    main()
