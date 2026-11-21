"""
ml/patterns/ma_cluster_state.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사용자 규칙 #1 — BTC 일봉 이동평균 군집(5·10·20·60·120) 상태기계

사용자 설명 원문 요약:
  국면 A (120선 미돌파, 5·10·20선은 돌파):
    "맨 위 추세선" = MA5·10·20 중 가장 높은 값(사용자 확인 완료)
    트리거① : 음봉의 저가가 그 선을 터치 → 숏
    트리거② : 종가기준 -4.5% 이상 하락 음봉 → 무조건 즉시 숏
    숏 진입 다음날 같은 선 터치 + 양봉 마감 → 롱 전환
    그 다음 또 같은 선 터치 + 음봉 마감 → 거래 중단(관망)

  국면 B (120선 이미 돌파):
    120선 아래로 이탈 + 그 다음 음봉 1개 더 → 즉시 숏

⚠️ 명시된 가정 (사용자가 다르면 정정):
  · "터치" = 캔들 저가(low)가 해당 선 이하로 내려감(<=)
  · 국면 A 트리거②(-4.5%)는 국면 A 조건(120선 미돌파, 5·10·20 돌파) 내에서만 적용
  · 신호는 종가 확정 후 다음 봉 시가에 체결 (미래참조 없음)
  · "거래 중단" 상태는 새로운 골든크로스(국면 A 재진입) 전까지 유지

검증: 학습(2017~2023) / 홀드아웃(2024~2026) 분리, Wilson CI.

사용법:
    python ml/patterns/ma_cluster_state.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from ml.trend_backtest import load, FEE, SLIP
from ml.mine_and_validate import wilson_lower

DROP_TH = -0.045   # 국면A 트리거② 임계치


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    c, o, h, l = d["close"], d["open"], d["high"], d["low"]
    for n in [5, 10, 20, 60, 120]:
        d[f"ma{n}"] = c.rolling(n).mean()
    d["ma_top_51020"] = d[["ma5", "ma10", "ma20"]].max(axis=1)
    d["bull"] = c > o
    d["bear"] = c < o
    d["cc_ret"] = c.pct_change()
    return d


def generate_positions(d: pd.DataFrame) -> np.ndarray:
    """
    상태기계를 하루씩 순회하며 포지션(+1 롱 / -1 숏 / 0 무포지션)을 만든다.
    ⚠️ 오늘 확정된 캔들 정보로 "내일" 취할 포지션을 정한다 — 미래참조 없음.
    """
    n = len(d)
    c, o, l = d["close"].values, d["open"].values, d["low"].values
    ma120 = d["ma120"].values
    ma_top = d["ma_top_51020"].values
    ma5, ma10, ma20 = d["ma5"].values, d["ma10"].values, d["ma20"].values
    cc = d["cc_ret"].values

    pos = np.zeros(n)          # 내일 취할 포지션 (오늘 인덱스에 기록, 체결은 다음날)
    state = "idle"             # idle | short_top | long_after_short | halted
    cur = 0.0
    above120_prev = False      # 국면B 판정용 — 어제 120선 위였는지

    for i in range(1, n):
        if np.isnan(ma120[i]) or np.isnan(ma_top[i]):
            pos[i] = cur; continue

        above120 = c[i] > ma120[i]
        below_cluster_broken = (c[i] > ma5[i]) and (c[i] > ma10[i]) and (c[i] > ma20[i])
        regimeA = below_cluster_broken and not above120     # 120 미돌파, 5·10·20 돌파
        touch_top = l[i] <= ma_top[i]
        bear = c[i] < o[i]
        bull = c[i] > o[i]

        new_state, new_cur = state, cur

        if state == "idle":
            if regimeA and bear and touch_top:
                new_state, new_cur = "short_top", -1.0
            elif regimeA and cc[i] <= DROP_TH and bear:
                new_state, new_cur = "short_top", -1.0
            elif above120_prev and not above120 and bear:
                # 국면B: 120선 이탈 캔들 확인 → "그 다음 음봉 1개 더" 대기
                new_state, new_cur = "await_confirm_B", cur
        elif state == "await_confirm_B":
            if bear:
                new_state, new_cur = "short_top", -1.0
            else:
                new_state, new_cur = "idle", cur   # 양봉 나오면 대기 해제
        elif state == "short_top":
            if touch_top and bull:
                new_state, new_cur = "long_after_short", 1.0
            # 유지 조건 없음 명시 안 됨 → 다음 신호 있을 때까지 숏 유지
        elif state == "long_after_short":
            if touch_top and bear:
                new_state, new_cur = "halted", 0.0
        elif state == "halted":
            if regimeA and bear and touch_top:
                new_state, new_cur = "short_top", -1.0   # 새 국면A 신호로 재개

        state, cur = new_state, new_cur
        pos[i] = cur
        above120_prev = above120

    return pos


def backtest(d: pd.DataFrame, pos: np.ndarray) -> dict:
    c = d["close"].values
    r = np.zeros(len(c)); r[1:] = c[1:]/c[:-1] - 1.0
    held = np.roll(pos, 1); held[0] = 0.0     # 오늘 신호 → 내일 체결
    turn = np.abs(np.diff(np.concatenate([[0.0], pos])))
    sr = held*r - turn*(FEE+SLIP)
    eq = np.cumprod(1+sr)
    bh = np.cumprod(1+r)
    mdd = (eq/np.maximum.accumulate(eq)-1).min()*100 if eq[-1] > 0 else -100.0

    # 거래 단위 승률
    ch = np.where(turn > 0)[0]
    wins = tot = 0
    for a, b in zip(ch, list(ch[1:])+[len(pos)]):
        if pos[a] == 0: continue
        seg = sr[a:b]
        if len(seg) == 0: continue
        tot += 1
        if np.prod(1+seg)-1 > 0: wins += 1

    return {"total": (eq[-1]-1)*100 if eq[-1]>0 else -100.0,
            "bh": (bh[-1]-1)*100, "mdd": mdd, "trades": tot,
            "wr": wins/tot*100 if tot else 0.0, "wins": wins}


def main():
    df = load("BTCUSDT", "1d")
    d = build_features(df)
    d = d.dropna(subset=["ma120"]).reset_index(drop=True)

    TRAIN_END = "2024-01-01"
    train = d[d["datetime"] < TRAIN_END].reset_index(drop=True)
    hold  = d[d["datetime"] >= TRAIN_END].reset_index(drop=True)

    print("="*84)
    print("  규칙#1 검증 — BTC 이동평균 군집 상태기계 (숏/롱/관망)")
    print(f"  전체 {d['datetime'].iloc[0].date()} ~ {d['datetime'].iloc[-1].date()}")
    print("="*84)

    for label, sub in [("학습구간 2017~2023", train), ("홀드아웃 2024~2026 (진짜검증)", hold)]:
        pos = generate_positions(sub)
        res = backtest(sub, pos)
        n_short = int((pos == -1).sum()); n_long = int((pos == 1).sum())
        wl = wilson_lower(res["wins"], res["trades"]) if res["trades"] else 0.0
        print(f"\n  ── {label} ──")
        print(f"     기간중 숏포지션일수 {n_short}일 / 롱포지션일수 {n_long}일")
        print(f"     거래(포지션 전환) {res['trades']}건  승률 {res['wr']:.1f}%  Wilson하한 {wl:.1f}%")
        print(f"     전략 수익률 {res['total']:+,.1f}%   존버(같은기간) {res['bh']:+,.1f}%   MDD {res['mdd']:.1f}%")


if __name__ == "__main__":
    main()
