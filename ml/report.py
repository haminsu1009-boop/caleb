"""
ml/report.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
거래 장부 — 무슨 코인을, 어느 시간봉에서, 어떤 전략으로

물어볼 때마다 답이 나와야 해서 만들었다. 백테스트가 실제로 무슨
거래를 했는지 한 건씩 펼쳐 보여준다. 요약 숫자(23배, 샤프 1.24)는
그 밑에 뭐가 깔렸는지 안 보여주니까.

전략별 시간봉이 다르다. 그게 섞이는 게 이 봇의 핵심이라 표에
항상 같이 찍는다.

  과매도 롱    4시간봉  20기간선 대비 −12.26% 이하 → 분할 진입 → 볼린저 상단/20봉
  주봉 숏      주봉     MA60주 이탈 + 4연속 음봉 → 4주 보유
  상승 다이버   일봉     저점 낮아지는데 RSI 높아짐(격차 ≥8p) → 10일 보유

돌파 롱(일봉·신고가)은 뺐다. 장부를 펼쳐보니 승률 56%로 넷 중
꼴찌였고, 평균 29.91%인데 중앙값은 5.56% — 몇 건이 크게 터뜨려
평균을 올린 것이고 보통은 5%다. 최악은 −99.9%로 40일 안에 코인이
전멸한 건이다. 자본 보존과 승률을 앞에 두면 빠지는 게 맞다.
연구 기록은 ml/bull_breakout.py 에 남아 있고 --with-break 로
다시 볼 수 있다.

쓰는 법:
  python ml/report.py                  최근 40건 + 전략별 요약
  python ml/report.py --all            전체
  python ml/report.py --sym BTCUSDT    코인 하나만
  python ml/report.py --kind short     전략 하나만
  python ml/report.py --year 2025      연도별
  python ml/report.py --open           지금이라면 열려 있을 포지션
  python ml/report.py --with-break     뺀 돌파 모듈까지 포함해서 비교
  python ml/report.py --csv out.csv    파일로
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from bot.oversold import strategy as S
from ml.backtest_current_bot import ROUND_TRIP, FUNDING_PER_8H
import ml.short_setups as SS
import ml.unified_pool as UP

# 전략 한 줄 설명. 표에 찍히는 이름과 시간봉의 단일 출처.
KINDS = {
    "long":  ("과매도 롱", "4시간봉", "20기간선 −12.26% 이하 → 분할진입 → 볼린저상단/20봉"),
    "short": ("주봉 숏",   "주봉",    "MA60주 이탈 + 4연속 음봉 → 4주 보유"),
    "div":   ("상승 다이버", "일봉",   "저점↓ RSI↑ 격차 ≥8p → 10일 보유"),
    "break": ("돌파 롱",   "일봉",    "시장 200일선 위 + 100일 신고가 → 40일 보유"),
}

# 운용 설정 — 자본 보존 우선. 돌파는 빠졌으므로 배분 대상이 아니다.
PER_TRADE = {"long": .02, "short": .30, "div": .30}
LEVERAGE = {"long": 2., "short": 1., "div": 1., "break": 1.}


def ledger(with_break=False) -> pd.DataFrame:
    """모든 신호를 한 장부로. 자본 배분 전, 신호 그 자체의 성적이다."""
    syms = [s for s in S.SYMBOLS if os.path.exists(f"data/{s}_1d_all.csv.gz")]
    D = {s: SS.load_daily(s) for s in syms}
    D = {k: v for k, v in D.items() if v is not None and len(v) >= 400}
    W = {s: SS.to_weekly(d) for s, d in D.items()}

    ts = (UP.make_long(fracs=[.30, .70], hold=60, bb=True, bb_k=1.5)
          + UP.make_short(W) + UP.make_div(D))
    if with_break:
        ts += UP.make_break(D)

    rows = []
    for t in ts:
        k = t["kind"]
        lev = LEVERAGE[k]
        liq = 100.0 / lev - 0.5
        raw = (t["exit_px"] / t["entry"] - 1) * 100
        px = raw if t["long"] else -raw
        liquidated = t["mae"] <= -liq
        if liquidated:
            px = -liq
        fee = ROUND_TRIP + (FUNDING_PER_8H * (t["bars_h"] / 8.0) if lev > 1 else 0)
        rows.append({
            "진입": t["dt"], "청산": t["exit"], "코인": t["sym"],
            "전략": KINDS[k][0], "시간봉": KINDS[k][1], "방향": "롱" if t["long"] else "숏",
            "배율": lev, "진입가": t["entry"], "청산가": t["exit_px"],
            "수익%": px - fee, "역행%": t["mae"], "청산당함": liquidated,
            "보유일": round(t["bars_h"] / 24, 1), "투입비율": t["deployed"], "_k": k,
        })
    return pd.DataFrame(rows).sort_values("진입").reset_index(drop=True)


def table(df: pd.DataFrame, n=None):
    d = df if n is None else df.tail(n)
    print(f"  {'진입일':<12s}{'청산일':<12s}{'코인':<10s}{'전략':<11s}{'시간봉':<8s}"
          f"{'방향':<5s}{'보유일':>7s}{'수익%':>9s}")
    print("  " + "-" * 76)
    for _, r in d.iterrows():
        mark = " 💀" if r["청산당함"] else ""
        print(f"  {r['진입'].strftime('%Y-%m-%d'):<12s}{r['청산'].strftime('%Y-%m-%d'):<12s}"
              f"{r['코인']:<10s}{r['전략']:<11s}{r['시간봉']:<8s}{r['방향']:<5s}"
              f"{r['보유일']:>7.1f}{r['수익%']:>9.2f}{mark}")


def summary(df: pd.DataFrame, by="전략"):
    print(f"\n  {by:<12s}{'시간봉':<8s}{'건수':>6s}{'승률':>7s}{'평균%':>9s}{'중앙%':>9s}"
          f"{'최고%':>9s}{'최악%':>9s}{'연간건수':>9s}")
    print("  " + "-" * 78)
    yrs = (df["진입"].max() - df["진입"].min()).days / 365.25
    for k, g in df.groupby(by, sort=False):
        tf = g["시간봉"].iloc[0] if by == "전략" else ""
        print(f"  {str(k):<12s}{tf:<8s}{len(g):>6d}{(g['수익%']>0).mean()*100:>6.0f}%"
              f"{g['수익%'].mean():>9.2f}{g['수익%'].median():>9.2f}"
              f"{g['수익%'].max():>9.1f}{g['수익%'].min():>9.1f}{len(g)/yrs:>9.1f}")
    print("  " + "-" * 78)
    print(f"  {'전체':<12s}{'':<8s}{len(df):>6d}{(df['수익%']>0).mean()*100:>6.0f}%"
          f"{df['수익%'].mean():>9.2f}{df['수익%'].median():>9.2f}"
          f"{df['수익%'].max():>9.1f}{df['수익%'].min():>9.1f}{len(df)/yrs:>9.1f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="전체 거래 출력")
    ap.add_argument("--sym", help="코인 하나만 (예: BTCUSDT)")
    ap.add_argument("--kind", choices=list(KINDS), help="전략 하나만")
    ap.add_argument("--year", type=int, help="연도 하나만")
    ap.add_argument("--open", action="store_true", help="지금이라면 열려 있을 포지션")
    ap.add_argument("--with-break", action="store_true",
                    help="뺀 돌파 모듈까지 포함 (비교용)")
    ap.add_argument("--csv", help="CSV로 저장")
    ap.add_argument("-n", type=int, default=40, help="최근 몇 건 (기본 40)")
    a = ap.parse_args()

    df = ledger(with_break=a.with_break)
    label = []
    if a.sym:
        df = df[df["코인"] == a.sym.upper()]; label.append(a.sym.upper())
    if a.kind:
        df = df[df["_k"] == a.kind]; label.append(KINDS[a.kind][0])
    if a.year:
        df = df[df["진입"].dt.year == a.year]; label.append(str(a.year))
    if a.open:
        last = df["청산"].max()
        df = df[df["청산"] >= last]; label.append("미청산")

    if df.empty:
        print("  해당하는 거래가 없다."); return

    print("=" * 80)
    print("  거래 장부" + (" — " + " · ".join(label) if label else ""))
    print(f"  {df['진입'].min():%Y-%m-%d} ~ {df['진입'].max():%Y-%m-%d} · {len(df):,}건")
    print("=" * 80)
    if a.all or len(df) <= a.n:
        table(df)
    else:
        print(f"  (최근 {a.n}건 — 전체는 --all)")
        table(df, a.n)
    summary(df)
    if len(df["코인"].unique()) > 1:
        top = (df.groupby("코인")["수익%"].agg(["size", "mean"])
                 .sort_values("mean", ascending=False))
        print(f"\n  코인별 상위/하위 5 (평균 수익%)")
        print("  " + "-" * 44)
        for lab, part in [("상위", top.head(5)), ("하위", top.tail(5))]:
            for c, r in part.iterrows():
                print(f"    {lab}  {c:<11s}{int(r['size']):>4d}건{r['mean']:>9.2f}%")
    if a.csv:
        df.drop(columns=["_k"]).to_csv(a.csv, index=False, encoding="utf-8-sig")
        print(f"\n  → {a.csv} 저장 ({len(df):,}행)")


if __name__ == "__main__":
    main()
