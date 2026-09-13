"""
ml/wonyotti_patterns.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
캔들 + 거래량 + 상위 시간봉 — '워뇨띠식' 아이디어를 숫자로

지금까지 이 저장소에서 시험한 규칙들은 대부분 **시간청산**이었다.
12봉 뒤에 무조건 판다. 그러면 손익비가 1에 가깝게 고정되고,
기대값이 사실상 승률 하나로 결정된다. 왕복 수수료 0.40%를 넘기려면
승률이 아주 높아야 하는데 그런 규칙은 드물다.

여기서는 축을 하나 더 넣는다 — **손절·익절 괄호(bracket)**.

    기대값 = 승률 × 익절폭 − (1 − 승률) × 손절폭 − 수수료

승률 55%라도 익절 +3% / 손절 −1%면 기대값이 +1.20%다. 반대로
승률 67%라도 +1.1% / −2.5%면 −0.09%다. 승률만 보면 둘을 구분 못 한다.

세 가지를 같이 본다.
  · 캔들 모양 (몸통·꼬리)
  · 거래량 (직전 20봉 평균 대비)
  · 상위 시간봉 추세 (진입 시간봉의 48배 기간 이동평균 위/아래)

거래량은 그 자체로 방향을 주지 않는다. **같은 장대양봉이라도
그 뒤 캔들들이 어떻게 반응하는지**가 다르므로, 단봉 패턴과
'급등 → 눌림 → 재돌파' 복합 패턴을 나눠서 시험한다.

체결 규칙
  · 판단은 종가, 체결은 다음 봉 시가
  · 손절·익절이 같은 봉 안에 둘 다 들어오면 **손절이 먼저**라고 본다
    (OHLC만으로는 순서를 알 수 없다. 유리한 쪽을 고르면 백테스트가
     거짓말을 한다)
  · 둘 다 안 닿으면 max_bars 에서 시간청산

기준선은 **같은 코인·같은 시기(±window봉) 무작위 진입**에 같은
괄호를 씌운 것이다. 상승장에서는 아무 때나 사도 익절이 먼저 닿으므로
이걸 안 이기면 패턴이 아니라 국면을 산 것이다.

실행: python ml/wonyotti_patterns.py [--tf 5m|1h|4h] [--regime]
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

FEE = 0.40                      # 왕복 %, 테이커 + 실측 체결지연
TEST_START = pd.Timestamp("2024-01-01")
TREND_MULT = 48                 # 상위 시간봉 대용 이동평균 기간
RNG = np.random.default_rng(17)


def load(sym, tf):
    p = f"data/{sym}_{tf}_all.csv.gz"
    if not os.path.exists(p):
        return None
    d = pd.read_csv(p)
    col = "timestamp" if "timestamp" in d else "dt"
    d["dt"] = pd.to_datetime(d[col], format="ISO8601")
    return d.dropna(subset=["close"]).reset_index(drop=True)


def features(d):
    o, h, l, c = (d["open"].values, d["high"].values,
                  d["low"].values, d["close"].values)
    v = d["volume"].values
    f = {}
    f["o"], f["h"], f["l"], f["c"], f["v"] = o, h, l, c, v
    f["ret"] = np.r_[0, np.diff(c) / c[:-1]] * 100          # 봉 수익률
    f["body"] = (c - o) / o * 100
    rng_ = np.maximum(h - l, 1e-12)
    f["upper"] = (h - np.maximum(o, c)) / rng_              # 윗꼬리 비중
    f["lower"] = (np.minimum(o, c) - l) / rng_              # 아랫꼬리 비중
    f["vr"] = v / pd.Series(v).rolling(20).mean().shift(1).values   # 거래량 배수
    f["trend"] = c > pd.Series(c).rolling(TREND_MULT).mean().values  # 상위 추세
    f["hh"] = pd.Series(c).rolling(50).max().shift(1).values
    return f


# ── 단봉 패턴 ────────────────────────────────────────────────────
def p_vol_bull(f, vm=2.0, body=1.0):
    return np.where((f["vr"] >= vm) & (f["body"] >= body))[0]

def p_vol_bear(f, vm=3.0, body=-1.0):
    return np.where((f["vr"] >= vm) & (f["body"] <= body))[0]

def p_surge(f, q=4.5):
    return np.where(f["ret"] >= q)[0]

def p_plunge(f, q=-5.0):
    return np.where(f["ret"] <= q)[0]

def p_n_red(f, n=3):
    red = f["c"] < f["o"]
    m = red.copy()
    for k in range(1, n):
        m &= np.roll(red, k)
    return np.where(m)[0]

def p_hh_volup(f, vm=1.5):
    return np.where((f["c"] > f["hh"]) & (f["vr"] >= vm))[0]

def p_hh_voldown(f, vm=0.8):
    return np.where((f["c"] > f["hh"]) & (f["vr"] <= vm))[0]

def p_bull_then_quiet(f, body=1.5, vm=2.0, quiet=0.7):
    """장대양봉 뒤 거래량이 마르는 자리 — 눌림 후 재상승 후보."""
    big = (np.roll(f["body"], 1) >= body) & (np.roll(f["vr"], 1) >= vm)
    return np.where(big & (f["vr"] <= quiet))[0]

def p_upper_wick(f, w=0.5, vm=2.0):
    return np.where((f["upper"] >= w) & (f["vr"] >= vm))[0]

def p_lower_wick(f, w=0.5, vm=2.0):
    return np.where((f["lower"] >= w) & (f["vr"] >= vm))[0]


# ── 복합 패턴 A: 급등 → 눌림 → 재돌파 ─────────────────────────────
def p_pullback_break(f, surge=2.0, vm=2.0, dip=(-1.5, -0.3),
                     wait=4, revol=1.2):
    """
    ① 장대양봉: 봉 수익률 >= surge, 거래량 >= 평균×vm
    ② 그 뒤 wait봉 안에서 dip 범위만큼 조정
    ③ 장대양봉의 저가를 깨지 않음
    ④ 거래량이 다시 붙으면서 (>= revol)
    ⑤ 장대양봉 고가를 돌파하는 봉 → 진입 신호
    """
    c, h, l, ret, vr = f["c"], f["h"], f["l"], f["ret"], f["vr"]
    n = len(c)
    out = []
    for i in np.where((ret >= surge) & (vr >= vm))[0]:
        if i + 1 >= n:
            continue
        hi, lo = h[i], l[i]
        dipped = False
        for j in range(i + 1, min(i + 1 + wait, n)):
            if l[j] < lo:                       # ③ 저점 이탈 → 무효
                break
            drop = (c[j] / c[i] - 1) * 100
            if dip[0] <= drop <= dip[1]:        # ② 조정 확인
                dipped = True
            if dipped and c[j] > hi and vr[j] >= revol:   # ④⑤ 재돌파
                out.append(j)
                break
    return np.array(sorted(set(out)), dtype=int)


# ── 괄호 청산 ────────────────────────────────────────────────────
def run_bracket(f, entries, tp, sl, max_bars, long=True, regime=None):
    """손절·익절 괄호. 같은 봉에 둘 다 닿으면 손절이 먼저라고 본다.

    추세 필터는 **신호봉 i**에서 판정한다. 체결봉 e=i+1 로 보면 그 봉의
    종가를 쓰게 되는데, 진입은 그 봉의 시가에 하므로 아직 모르는 값이다
    — 미래참조다. (처음엔 regime[e]로 짰다가 봇과 대조하다 잡았다.
    3,226건 대 3,143건, 겹침 90.5%.)
    """
    o, h, l, c = f["o"], f["h"], f["l"], f["c"]
    n = len(c)
    out, lock = [], -1
    for i in entries:
        e = i + 1
        if i <= lock or e >= n - 1:
            continue
        if regime is not None and not regime[i]:
            continue
        ep = o[e]
        tp_px = ep * (1 + tp/100) if long else ep * (1 - tp/100)
        sl_px = ep * (1 - sl/100) if long else ep * (1 + sl/100)
        j, r = min(e + max_bars, n - 1), None
        for b in range(e, min(e + max_bars + 1, n)):
            hit_sl = (l[b] <= sl_px) if long else (h[b] >= sl_px)
            hit_tp = (h[b] >= tp_px) if long else (l[b] <= tp_px)
            if hit_sl:                         # 보수적: 손절 우선
                j, r = b, -sl
                break
            if hit_tp:
                j, r = b, tp
                break
        if r is None:
            r = (c[j]/ep - 1) * 100 * (1 if long else -1)
        out.append({"i": e, "ret": r - FEE, "bars": j - e})
    return out


def baseline(f, k, tp, sl, max_bars, long=True, window=500, reps=2):
    """같은 시기 무작위 진입 + 같은 괄호."""
    n = len(f["c"])
    if k == 0 or n < 300:
        return []
    idx = []
    for _ in range(reps):
        idx += list(RNG.integers(100, n - max_bars - 2, size=k))
    return run_bracket(f, np.array(sorted(set(idx))) - 1, tp, sl, max_bars, long)


PATTERNS = [
    ("거래량 2배 + 장대양봉",      p_vol_bull,                 True),
    ("거래량 3배 + 장대음봉",      p_vol_bear,                 True),
    ("+4.5% 급등",              p_surge,                    True),
    ("-5% 급락 (반등 노림)",      p_plunge,                   True),
    ("3연속 음봉",               lambda f: p_n_red(f, 3),    True),
    ("5연속 음봉",               lambda f: p_n_red(f, 5),    True),
    ("신고가 + 거래량 증가",       p_hh_volup,                 True),
    ("신고가 + 거래량 감소",       p_hh_voldown,               True),
    ("장대양봉 후 거래량 감소",     p_bull_then_quiet,          True),
    ("긴 윗꼬리 + 거래량 폭증",     p_upper_wick,               False),   # 고점 → 숏
    ("긴 아랫꼬리 + 거래량 폭증",   p_lower_wick,               True),
    ("급등→눌림→재돌파 (복합 A)",  p_pullback_break,           True),
]

# 좁은 괄호(+3%/-1% 같은 것)는 이 시장에서 **어떤 규칙이든** 죽인다.
# 검증된 과매도 -12.26% 규칙을 같은 하네스에 넣어보면:
#   +3%/-1%  거래당 -0.665%  순엣지 -0.171
#   +5%/-2%  거래당 -0.531%  순엣지 -0.055
#   +8%/-4%  거래당 -0.301%  순엣지 +0.166
#   +10%/-5% 거래당 -0.146%  순엣지 +0.434  홀드아웃 +0.721
# 손절이 좁으면 반등 전 흔들림에 먼저 걸린다(진입 후 MAE 중앙값이
# -7.1%다 — bot/oversold/strategy.py 참고). 그래서 넓은 괄호도 같이
# 시험해야 패턴을 공정하게 판정할 수 있다.
BRACKETS = [(3.0, 1.0), (5.0, 2.0), (8.0, 4.0), (10.0, 5.0), (15.0, 7.0)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--regime", action="store_true",
                    help="상위 추세(48기간선) 위에서만 롱, 아래에서만 숏")
    ap.add_argument("--max-bars", type=int, default=48)
    a = ap.parse_args()

    syms = [s for s in S.SYMBOLS if os.path.exists(f"data/{s}_{a.tf}_all.csv.gz")]
    D = {s: load(s, a.tf) for s in syms}
    D = {k: v for k, v in D.items() if v is not None and len(v) > 500}
    F = {s: features(d) for s, d in D.items()}
    bars = sum(len(v) for v in D.values())

    print("=" * 110)
    print(f"  캔들·거래량·추세 패턴 {len(PATTERNS)}종 — {a.tf} · {len(D)}종 · {bars:,}봉"
          + (" · 상위추세 필터 ON" if a.regime else ""))
    print(f"  왕복 수수료 {FEE}% · 최대 보유 {a.max_bars}봉 · 같은 봉 손익 동시 도달 시 손절 우선")
    print("=" * 110)

    for tp, sl in BRACKETS:
        print(f"\n  ■ 익절 +{tp}% / 손절 −{sl}%  (손익비 {tp/sl:.1f})")
        print(f"    {'패턴':<26s}{'거래':>8s}{'승률':>7s}{'거래당%':>9s}"
              f"{'기준선%':>9s}{'순엣지%p':>10s}{'홀드아웃':>10s}{'':>4s}")
        print("    " + "-" * 84)
        for name, fn, is_long in PATTERNS:
            R, B = [], []
            for sym, f in F.items():
                reg = None
                if a.regime:
                    reg = f["trend"] if is_long else ~f["trend"]
                r = run_bracket(f, fn(f), tp, sl, a.max_bars, is_long, reg)
                dts = D[sym]["dt"].values
                for x in r:
                    x["dt"] = dts[x["i"]]
                R.extend(r)
                B.extend(baseline(f, len(r), tp, sl, a.max_bars, is_long))
            if not R:
                print(f"    {name:<26s}{'신호 없음':>8s}")
                continue
            t = pd.DataFrame(R)
            t["dt"] = pd.to_datetime(t["dt"])
            b = pd.DataFrame(B)
            ho = t[t.dt >= TEST_START]
            bm = b.ret.mean() if len(b) else np.nan
            edge = t.ret.mean() - bm
            mark = "  ✅" if t.ret.mean() > 0 and len(ho) and ho.ret.mean() > 0 and edge > 0 else ""
            print(f"    {name:<26s}{len(t):>8,d}{(t.ret>0).mean()*100:>6.0f}%"
                  f"{t.ret.mean():>9.3f}{bm:>9.3f}{edge:>10.3f}"
                  f"{(ho.ret.mean() if len(ho) else np.nan):>10.3f}{mark}")


if __name__ == "__main__":
    main()


# ── 결과 (2026-09) ──────────────────────────────────────────────
#
# 4시간봉 42종 596,250봉 · 패턴 12종 × 괄호 5종 × 필터 on/off
#
# 가장 큰 발견은 패턴이 아니라 **청산 구조와 상위 추세 필터**였다.
#
# (1) 좁은 괄호는 어떤 규칙이든 죽인다
#     검증된 과매도 -12.26% 규칙을 같은 하네스에 넣어보면
#       +3%/-1%   거래당 -0.665%  순엣지 -0.171
#       +5%/-2%   거래당 -0.531%  순엣지 -0.055
#       +8%/-4%   거래당 -0.301%  순엣지 +0.166
#       +10%/-5%  거래당 -0.146%  순엣지 +0.434  홀드아웃 +0.721
#     -1% 손절은 반등 전 흔들림에 먼저 걸린다(진입 후 MAE 중앙 -7.1%).
#     처음에 좁은 괄호로만 돌린 것은 패턴에 불공정한 시험이었다.
#
# (2) 상위 추세 필터가 판을 바꾼다 — 이게 핵심이다
#     '-5% 급락 후 반등' 패턴, 괄호 +10%/-5%:
#       필터 ON   3,226건  거래당 +0.623%  홀드아웃 +0.495%
#       필터 OFF 11,452건  거래당 -0.273%  홀드아웃 -0.065%
#     같은 신호인데 상위 추세 위에서만 잡으면 +0.9%p가 바뀐다.
#     거래량·캔들 모양보다 이쪽이 훨씬 컸다.
#
# (3) 문턱은 단조롭다 (과최적화 징후 아님)
#       -3%   거래당 +0.506  홀드아웃 +0.115  (11,858건)
#       -5%   거래당 +0.623  홀드아웃 +0.495  ( 3,226건)
#       -8%   거래당 +0.530  홀드아웃 +2.767  (   645건)
#       -10%  거래당 +1.490  홀드아웃 +4.330  (   246건)
#
# (4) 기존 과매도 롱과 다른 신호다 — 겹침 3%뿐
#     과매도 롱은 '20기간선 대비 -12.26%'(누적 낙폭), 이쪽은
#     '한 봉에 -5%'(속도)다. 같은 방향이지만 잡는 순간이 다르다.
#
# (5) 포트폴리오에 넣으면 (진입당 5%)
#                     전체     낙폭   승률   샤프  1년손실
#       3종          21.52배  21.6%  81%  1.38    1%
#       +급락반등     51.43배  22.3%  56%  1.68    1%
#     홀드아웃: 4.94배 → 5.74배, 샤프 2.03 → 2.19
#
#     수익과 샤프가 오르고 낙폭·1년손실확률은 그대로다. 대신
#     **전체 승률이 81%에서 56%로 떨어진다.** 이 모듈이 승률 40%에
#     거래 3,226건이라 건수로 기존 1,910건을 압도하기 때문이다.
#     손익비 2:1이라 기대값은 양수지만(0.40×10 - 0.60×5 = +1.0%),
#     '높은 승률'을 우선한다면 이건 받아들이기 어려운 교환이다.
#
# (6) 실패한 것들
#     3연속·5연속 음봉 뒤 반등은 **일관되게 해롭다**. 괄호를 넓힐수록,
#     홀드아웃일수록 더 나쁘다(-1.00 → -1.19 → -1.33). 필터를 켜도
#     홀드아웃에서 -0.673%다. '많이 빠졌으니 오르겠지'는 이 데이터에서
#     반대로 작동한다.
#     신고가+거래량 증가는 학습에서 좋지만 홀드아웃이 음수다.
#     복합 패턴 A(급등→눌림→재돌파)는 필터를 켜도 -0.363%다.
