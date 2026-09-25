"""
ml/hybrid_variants.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
진입 임계값은 그대로 두고 나머지만 바꾸면 어떻게 되나

ml/global_retune.py가 고른 규칙은 홀드아웃 거래당 +12.07%로 지금
봇(+8.68%)을 이겼다. 그런데 자본 단위로 낙폭을 맞춰놓고 돌리면
총수익이 오히려 뒤졌다(1.88배 대 2.42배). 거래가 1,815건에서
375건으로 5분의 1이 되기 때문이다 — 거래당 엣지가 커도 횟수가
없으면 복리가 안 붙는다.

거래 수를 죽인 것은 네 가지 변경 중 **진입 임계값 하나뿐이다**
(-12.26% → -18%). 보유기간·분할매수 단수·분할매도는 신호를 줄이지
않는다. 그래서 진입은 지금 그대로 두고 나머지 셋만 가져와본다.

이 파일이 답하는 것은 "어느 조합이 제일 좋은가"가 아니다. 그건
학습구간 성적으로 고를 수 없다는 게 결론이다 —

    학습 배수 ↔ 홀드아웃 배수 상관 = -0.532
    학습 승률 ↔ 홀드아웃 승률 상관 = +0.890

배수 쪽이 음수다. 학습에서 수익이 좋았던 설정이 홀드아웃에서 더 나쁘다.
16가지 사이의 **총수익 차이는 잡음**이라는 뜻이고, 백테스트 수익률로
설정을 고르는 행위 자체가 여기서는 해롭다.

반면 두 가지는 학습·홀드아웃에서 순서가 그대로 유지된다.

    승률      30+70 단일청산 78~81% / 83~87%
              20+30+50 분할매도 85.6~87.2% / 93.5~94.7%
    청산건수  30+70 10~13건 → 20+30+50 6~9건

둘 다 기전이 설명된다. 1차를 30%가 아니라 20%만 넣으면 물렸을 때
평단이 더 좋아지고, 최악의 순간에 깔린 돈도 적다. 분할매도는 절반을
먼저 익절해 되돌림을 덜 맞는다. 잡음이 아니라 구조다.

즉 고를 수 있는 것은 '수익률'이 아니라 '승률과 청산 빈도'다. 같은
16개 설정을 같은 데이터에서 재는데 한 지표는 -0.53이고 다른 지표는
+0.89다 — 백테스트가 무엇을 말해주고 무엇을 말해주지 않는지가
이보다 깨끗하게 갈리는 경우는 드물다.

사용법:
    python ml/hybrid_variants.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, itertools, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from bot.oversold import strategy as S
from ml.backtest_current_bot import simulate
from ml.rule_shootout import load_all, trades_for

TE = pd.Timestamp("2024-01-01")
HOLDS = [60, 90]
FRACS = [[0.30, 0.70], [0.20, 0.30, 0.50]]
OUTS = [[(1.0, 1.5)], [(1.0, 2.0)],
        [(0.5, 1.0), (0.5, 2.0)],
        [(0.34, 1.0), (0.33, 1.5), (0.33, 2.0)]]
CURRENT = (S.HOLD_BARS, (S.SCALE_IN_FIRST_FRAC, 1 - S.SCALE_IN_FIRST_FRAC),
           ((1.0, S.BB_K),))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-trade", type=float, default=0.015)
    ap.add_argument("--max-gross", type=float, default=0.4)
    a = ap.parse_args()

    data = load_all()
    kw = dict(leverage=2.0, per_trade=a.per_trade, max_gross=a.max_gross,
              cb=0.20, cool_days=30, min_equity=0.0, compound=True)

    print("=" * 104)
    print("  하이브리드 — 진입은 지금 그대로, 나머지만 바꾼다")
    print(f"  학습 ~2023에서 고르고 홀드아웃 2024~로 채점 · 배율 2배 · "
          f"진입당 {a.per_trade*100:.1f}% · 총노출 {a.max_gross*100:.0f}%")
    print("=" * 104)
    print(f"\n  {'보유':>4s}{'분할매수':>10s}{'분할매도':>22s}"
          f"{'학습배수':>9s}{'학습승률':>9s}{'홀드배수':>9s}{'홀드승률':>9s}"
          f"{'홀드낙폭':>9s}{'청산':>5s}")
    print("  " + "-" * 96)

    rows = []
    for hold, fr, ou in itertools.product(HOLDS, FRACS, OUTS):
        tr = trades_for(data, (S.MA_PERIOD, S.ENTRY_THRESH, hold, fr, ou))
        trn = simulate([t for t in tr if t["dt"] < TE], **kw)
        hod = simulate([t for t in tr if t["dt"] >= TE], **kw)
        cur = (hold, tuple(fr), tuple(ou)) == CURRENT
        rows.append(dict(hold=hold, fr=fr, ou=ou, tr=trn, ho=hod, cur=cur))
        fs = "+".join(f"{x*100:.0f}" for x in fr)
        os_ = " ".join(f"{f*100:.0f}%@{k}σ" for f, k in ou)
        print(f"  {hold:>4}{fs:>10s}{os_:>22s}{trn['final']:>8.2f}배"
              f"{trn['wr']:>8.1f}%{hod['final']:>8.2f}배{hod['wr']:>8.1f}%"
              f"{hod['mdd_low']*100:>8.1f}%{trn['liq']+hod['liq']:>5}"
              + ("  ← 지금 봇" if cur else ""))

    x = np.array([r["tr"]["final"] for r in rows])
    y = np.array([r["ho"]["final"] for r in rows])
    print(f"\n  학습 배수 ↔ 홀드아웃 배수 상관 = {np.corrcoef(x, y)[0,1]:+.3f}")
    print("  음수면 '학습 수익률로 고르는 행위'가 해롭다는 뜻이다.")

    wx = np.array([r["tr"]["wr"] for r in rows])
    wy = np.array([r["ho"]["wr"] for r in rows])
    print(f"  학습 승률 ↔ 홀드아웃 승률 상관 = {np.corrcoef(wx, wy)[0,1]:+.3f}")
    print("  이쪽이 1에 가까우면 승률은 고를 수 있다는 뜻이다.")

    best_tr = max(rows, key=lambda r: r["tr"]["final"])
    cur = [r for r in rows if r["cur"]][0]
    print(f"\n  학습 1위 → 홀드아웃 {best_tr['ho']['final']:.2f}배 "
          f"(홀드아웃 실제 1위는 {y.max():.2f}배)")
    print(f"  지금 봇   → 홀드아웃 {cur['ho']['final']:.2f}배 "
          f"(학습 순위 {sorted(x, reverse=True).index(cur['tr']['final'])+1}/{len(rows)})")
    print("=" * 104)


if __name__ == "__main__":
    main()
