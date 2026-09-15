"""
ml/pairs_trading.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
페어 트레이딩 — 방향성 없는 새 전략 계열

지금까지의 전략은 전부 '싸지면 산다'는 방향성 베팅이다. 그래서
42종을 들어도 상관 0.587로 묶여 유효 독립 베팅이 연 8번뿐이었다.

페어 트레이딩은 구조가 다르다.
  · 같이 움직이는 두 종목(예: ETH-BNB)의 가격 비율을 본다
  · 그 비율이 평소 범위를 벗어나면 벌어진 쪽을 숏, 좁혀진 쪽을 롱
  · 시장이 통째로 오르든 내리든 두 다리가 상쇄된다
  → 시장 방향과 무관하므로 기존 전략과 상관이 0에 가까워야 한다

■ 과최적화를 막는 장치
  · 페어 선정은 **학습 구간(~2023)에서만** 한다. 홀드아웃 데이터를
    보고 페어를 고르면 그건 답을 보고 고르는 것이다.
  · 헤지비율과 z점수는 진입 시점까지의 데이터로만 계산한다.
  · 861개 조합을 다 시험하므로 다중검정 부담이 크다. 홀드아웃
    성적만 믿는다.

■ 비용
두 다리를 열고 닫으므로 왕복 수수료가 네 번이다. 그리고 숏 다리는
무기한 선물이라 펀딩비가 붙는다(방향에 따라 받기도 한다).
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, argparse, warnings, itertools
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from bot.oversold import strategy as S
from ml.backtest_current_bot import load

TE = pd.Timestamp("2024-01-01")
ONE_LEG = 0.055 + 0.05      # % 편도 (테이커 + 슬리피지 여유)


def panel():
    cl = {}
    for s in S.SYMBOLS:
        g = load(s)
        if g is None:
            continue
        cl[s] = g.set_index("datetime")["close"].astype(float)
    return pd.DataFrame(cl).sort_index()


def pick_pairs(C, top=40, min_corr=0.75):
    """학습 구간에서만 페어를 고른다. 로그가격 상관이 높은 쌍."""
    tr = C[C.index < TE]
    lp = np.log(tr.dropna(axis=1, thresh=int(len(tr) * 0.6)))
    r = lp.diff()
    cm = r.corr()
    out = []
    for a, b in itertools.combinations(cm.columns, 2):
        c = cm.loc[a, b]
        if c >= min_corr:
            out.append((a, b, c))
    out.sort(key=lambda x: -x[2])
    return out[:top]


def pair_trades(C, a, b, *, win=120, entry_z=2.0, exit_z=0.5, stop_z=4.0,
                max_hold=120):
    """스프레드 = log(a) - beta*log(b). beta와 z는 과거만 본다."""
    d = C[[a, b]].dropna()
    if len(d) < win * 3:
        return []
    la, lb = np.log(d[a].values), np.log(d[b].values)
    dt = d.index.values
    n = len(la)
    # 롤링 회귀 베타 (과거 win개만)
    beta = np.full(n, np.nan)
    for i in range(win, n):
        x = lb[i - win:i]; y = la[i - win:i]
        vx = x.var()
        if vx > 0:
            beta[i] = np.cov(x, y)[0, 1] / vx
    spread = la - beta * lb
    sm = pd.Series(spread).rolling(win).mean().values
    ss = pd.Series(spread).rolling(win).std().values
    z = (spread - sm) / ss

    out = []
    i = win * 2
    while i < n - 1:
        if np.isnan(z[i]) or abs(z[i]) < entry_z:
            i += 1; continue
        side = -1 if z[i] > 0 else 1        # z>0 이면 a가 비싸다 → a 숏
        e_i = i + 1                          # 다음 봉에서 체결
        if e_i >= n:
            break
        ea, eb, bt = la[e_i], lb[e_i], beta[e_i]
        if np.isnan(bt):
            i += 1; continue
        x_i = None
        for j in range(e_i + 1, min(e_i + max_hold, n)):
            if np.isnan(z[j]):
                continue
            if abs(z[j]) <= exit_z or abs(z[j]) >= stop_z or (z[j] * side > 0):
                x_i = j; break
        if x_i is None:
            x_i = min(e_i + max_hold, n - 1)
        # 손익: a 다리 side방향, b 다리 반대방향 × beta
        ra = (la[x_i] - ea) * 100 * side
        rb = (lb[x_i] - eb) * 100 * (-side) * bt
        gross = ra + rb
        fee = ONE_LEG * 2 * (1 + abs(bt))     # 두 다리 × 왕복
        out.append({"pair": f"{a}/{b}", "dt": pd.Timestamp(dt[e_i]),
                    "exit": pd.Timestamp(dt[x_i]), "ret": gross - fee,
                    "z": z[i], "bars": x_i - e_i, "deployed": 1.0})
        i = x_i + 1
    return out


def equity(ts, per=0.10, maxc=5, days=None):
    cash = 1.0; open_ = []; out = {}; k = 0
    ts = sorted(ts, key=lambda x: x["dt"])
    if days is None:
        days = pd.date_range(ts[0]["dt"].normalize(), ts[-1]["dt"].normalize(), freq="D")
    for d in days:
        for e, p in [x for x in open_ if x[0] <= d]:
            cash += p
        open_ = [x for x in open_ if x[0] > d]
        while k < len(ts) and ts[k]["dt"] <= d:
            t = ts[k]; k += 1
            if len(open_) >= maxc:
                continue
            m = per * cash
            open_.append((t["exit"], max(m * t["ret"] / 100, -m)))
        out[d] = cash
    return pd.Series(out)


def stats(c):
    r = c.pct_change().dropna()
    if len(r) < 100 or c.iloc[-1] <= 0:
        return None
    ann = (1 + r.mean()) ** 365 - 1
    vol = r.std() * np.sqrt(365)
    return dict(final=c.iloc[-1], cagr=ann * 100, vol=vol * 100,
                sharpe=(ann - 0.03) / vol,
                mdd=(1 - (c / c.cummax()).min()) * 100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--entry-z", type=float, default=2.0)
    a = ap.parse_args()

    C = panel()
    pairs = pick_pairs(C, top=a.top)
    print("=" * 88)
    print(f"  페어 트레이딩 — 학습 구간(~2023)에서 고른 상위 {len(pairs)}쌍")
    print(f"  왕복 수수료 편도 {ONE_LEG}% × 두 다리")
    print("=" * 88)
    print(f"\n  상위 8쌍 (학습 구간 로그수익률 상관)")
    for x, y, c in pairs[:8]:
        print(f"    {x.replace('USDT',''):>6s} / {y.replace('USDT',''):<6s}  {c:.3f}")

    print(f"\n  {'진입 z':>7s}{'거래':>8s}{'승률':>8s}{'거래당':>9s}"
          f"{'학습 거래당':>12s}{'홀드 거래당':>12s}{'평균보유':>9s}")
    print("  " + "-" * 66)
    best = None
    for ez in (1.5, 2.0, 2.5, 3.0):
        ts = []
        for x, y, _ in pairs:
            ts += pair_trades(C, x, y, entry_z=ez)
        if len(ts) < 30:
            print(f"  {ez:>6.1f}σ{len(ts):>8d}   표본 부족"); continue
        d = pd.DataFrame(ts)
        tr, ho = d[d.dt < TE], d[d.dt >= TE]
        f = lambda q: f"{q.ret.mean():+.2f}%" if len(q) > 10 else "   —"
        print(f"  {ez:>6.1f}σ{len(ts):>8d}{(d.ret>0).mean()*100:>7.1f}%"
              f"{d.ret.mean():>8.2f}%{f(tr):>12s}{f(ho):>12s}{d.bars.mean():>8.0f}봉")
        if best is None or d.ret.mean() > best[1]:
            best = (ez, d.ret.mean(), ts)

    if best is None:
        print("\n  쓸 만한 설정 없음"); return
    ez, _, ts = best
    print(f"\n  ── 진입 {ez}σ 로 자본곡선")
    c = equity(ts)
    s = stats(c)
    if s:
        print(f"     최종 {s['final']:.2f}배 · 연복리 {s['cagr']:.0f}% · "
              f"변동성 {s['vol']:.0f}% · 샤프 {s['sharpe']:.2f} · 낙폭 {s['mdd']:.0f}%")
        ctr = c[c.index < TE]; cho = c[c.index >= TE]
        print(f"     학습 {ctr.iloc[-1]/ctr.iloc[0]:.2f}배 / "
              f"홀드아웃 {cho.iloc[-1]/cho.iloc[0]:.2f}배")

    # 기존 전략과의 상관
    print(f"\n  ── 기존 롱 전략과의 상관")
    import ml.unified_pool as U
    L = U.make_long(fracs=[.30, .70], hold=60, bb=True, bb_k=1.5)
    days = c.index
    lc = equity([{"dt": t["dt"], "exit": t["exit"], "ret":
                  (t["exit_px"]/t["entry"]-1)*100*t["deployed"]*2 - 0.4,
                  "deployed": 1.0} for t in L], per=0.05, maxc=20, days=days)
    R = pd.DataFrame({"페어": c.pct_change().fillna(0),
                      "코인 롱": lc.pct_change().fillna(0)})
    print(f"     상관계수 {R.corr().iloc[0,1]:+.3f}")


if __name__ == "__main__":
    main()
