"""
ml/strategy_health.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
매일 전략 점검 — 새로 들어온 데이터로 지금 봇 규칙을 다시 돌려 본다

GitHub Actions(strategy_health.yml)가 매일 아침 데이터 수집 뒤에 부른다.
결과는 reports/health_latest.txt 에 쓰고, 텔레그램 비밀값이 있으면 보낸다.

보는 것
  1. 데이터가 최신인가 — 42종 마지막 봉 날짜
  2. 오늘 상황 — 롱 진입선(20봉선 -12.26%)에 닿았거나 가까운 코인,
     BTC 30·60·90일 수익률과 폭락장(bear)/상승장(bull) 기준 해당 여부
  3. 최근 성적이 과거와 같은가 — 롱·숏·다이버별로 최근 90일·365일의
     거래 수·승률·거래당 수익을 2019년부터의 전체와 비교한다.
     과거 승률이 맞다면 최근처럼 나쁠 확률이 2% 미만일 때만 "이상"으로 본다.
  4. 지갑 전체 — 롱 4배(자동 폭락장엔 2배)·숏·다이버 1배로 최근 1년을 돌린
     결과가 과거의 1년 구간들 중 몇 번째인지(하위 5%면 이상)

사용법
    python ml/strategy_health.py            # 화면 + reports/ 저장
    python ml/strategy_health.py --send     # + 텔레그램 (TG_BOT_TOKEN, TG_CHAT_ID)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations
import argparse
import math
import os
import sys
import warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from bot.oversold import strategy as S
import ml.unified_pool as UP
import ml.short_setups as SS
from ml.backtest_current_bot import load
from ml.per_coin_rules import sim
from ml.per_coin_walkforward import MENU
from ml.per_coin_portfolio import to_up
from ml.module_winrate import taken, net, PT, LV

T0 = pd.Timestamp("2019-01-01")
NAME = {"long": "롱", "short": "숏", "div": "다이버"}
OUT_DIR = os.path.join(ROOT, "reports")


def binom_cdf(k, n, p):
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="텔레그램으로 보낸다")
    a = ap.parse_args()
    warn, lines = [], []

    # ── 데이터 ──
    syms = [s for s in S.SYMBOLS if os.path.exists(f"data/{s}_1d_all.csv.gz")]
    Dd = {s: SS.load_daily(s) for s in syms}
    Dd = {k: v for k, v in Dd.items() if v is not None and len(v) >= 400}
    W = {s: SS.to_weekly(d) for s, d in Dd.items()}
    G = {s: load(s) for s in S.SYMBOLS}
    G = {s: g for s, g in G.items() if g is not None and len(g) >= 400}
    last4 = {s: g["datetime"].iloc[-1] for s, g in G.items()}
    newest = max(last4.values())
    stale = [s for s, t in last4.items() if t < newest - pd.Timedelta(days=3)]
    today = pd.Timestamp.utcnow().tz_localize(None).normalize()
    lag = (today - newest.normalize()).days
    lines.append(f"🩺 전략 점검 {today:%m/%d} · 데이터 {newest:%m/%d %H시}까지 ({len(G)}종)")
    if lag > 3:
        warn.append(f"데이터가 {lag}일 늦다 — 수집 워크플로 확인")
    if stale:
        warn.append(f"갱신 멈춘 종목 {len(stale)}개: {', '.join(stale[:6])}")

    # ── 오늘 상황 ──
    near = []
    for s, g in G.items():
        c = g["close"].astype(float).values
        if len(c) < S.MA_PERIOD + 1:
            continue
        vs = (c[-1] / c[-S.MA_PERIOD:].mean() - 1) * 100
        near.append((vs, s))
    near.sort()
    hit = [f"{s[:-4]} {v:.1f}%" for v, s in near if v <= S.ENTRY_THRESH]
    close = [f"{s[:-4]} {v:.1f}%" for v, s in near if S.ENTRY_THRESH < v <= S.ENTRY_THRESH + 4]
    lines.append(f"롱 진입선({S.ENTRY_THRESH}%) 도달: {', '.join(hit) if hit else '없음'}")
    if close:
        lines.append(f"  근접: {', '.join(close[:6])}")

    b = Dd["BTCUSDT"].set_index("dt")["close"]
    r = {n: (b.iloc[-1] / b.iloc[-1 - n] - 1) * 100 for n in (30, 60, 90)}
    lines.append(f"BTC 30일 {r[30]:+.0f}% · 60일 {r[60]:+.0f}% · 90일 {r[90]:+.0f}%")
    if r[30] <= -15 or r[60] <= -15 or r[90] <= -20:
        warn.append("BTC가 폭락장 기준에 닿았다 — --regime bear(롱 끔) 검토")
    elif r[90] >= 30:
        lines.append("  (상승장 기준 해당 — 숏은 이런 장에서 원래 신호가 거의 없다)")

    # ── 거래 만들기 (지금 봇 규칙) ──
    ma, th, hd, fr, ou, st = MENU["A 지금 봇"]
    L = []
    for s, g in G.items():
        o, h, l, c = (g[k].astype(float).values for k in ("open", "high", "low", "close"))
        L += [to_up(t) for t in sim(o, h, l, c, g["datetime"].values,
                                    ma, th, hd, fr, ou, S.STOP_PCT, sym=s, step=st)]
    Sh, Dv = UP.make_short(W), UP.make_div(Dd)
    cut = lambda X: [t for t in X if t["dt"] >= T0]
    L, Sh, Dv = cut(L), cut(Sh), cut(Dv)

    btc = b.copy()
    def bear(ts):
        i = btc.index.searchsorted(pd.Timestamp(ts), side="right") - 2   # 전날 종가까지만 (그날 종가는 아직 모른다)
        if i < 60:
            return False
        return btc.iloc[i] / btc.iloc[i - 60] - 1 <= -0.15
    def bull(ts):
        i = btc.index.searchsorted(pd.Timestamp(ts), side="right") - 2   # 전날 종가까지만 (그날 종가는 아직 모른다)
        if i < 90:
            return False
        return btc.iloc[i] / btc.iloc[i - 90] - 1 >= 0.30

    # ── 모듈별 최근 vs 전체 ──
    lines.append("")
    lines.append("최근 성적 (청산 기준, 배율 전 거래당)")
    for kind, X, lev in (("long", L, 4.0), ("short", Sh, 1.0), ("div", Dv, 1.0)):
        done = [t for t in X if pd.Timestamp(t["exit"]) <= newest]
        allr = np.array([net(t, lev) for t in done])
        base_p = float((allr > 0).mean()) if len(allr) else np.nan
        seg = []
        for days in (90, 365):
            rec = [t for t in done if pd.Timestamp(t["exit"]) > newest - pd.Timedelta(days=days)]
            rr = np.array([net(t, lev) for t in rec])
            if len(rr):
                k = int((rr > 0).sum())
                seg.append(f"{days}일 {len(rr)}건 {k/len(rr)*100:.0f}% {rr.mean():+.1f}%")
                if len(rr) >= 5 and binom_cdf(k, len(rr), base_p) < 0.02:
                    warn.append(f"{NAME[kind]} 최근 {days}일 승률 {k}/{len(rr)} — 과거({base_p*100:.0f}%)보다 "
                                f"우연으로 보기 어려울 만큼 낮다")
            else:
                seg.append(f"{days}일 0건")
        lines.append(f"  {NAME[kind]}: " + " · ".join(seg)
                     + f" | 전체 {len(allr)}건 {base_p*100:.0f}% {allr.mean():+.1f}%")
        last_entry = max((pd.Timestamp(t["dt"]) for t in X), default=None)
        gap = (newest - last_entry).days if last_entry is not None else 9999
        # 신호가 오래 없는 건 대개 장이 그 전략과 안 맞을 뿐이다(상승장의 롱).
        # 과거 가장 긴 공백보다 길어질 때만 경고하고, 그 전엔 한 줄로만 적는다.
        ds = sorted(pd.Timestamp(t["dt"]) for t in X)
        gaps = np.diff(np.array(ds, dtype="datetime64[D]")).astype(int) if len(ds) > 2 else np.array([0])
        if len(gaps) > 5 and gap > 30:
            mx = int(gaps.max())
            if gap > mx:
                warn.append(f"{NAME[kind]} 신호가 {gap}일째 없다 — 과거 최장 공백({mx}일)보다 길다")
            elif gap > np.percentile(gaps, 99):
                lines.append(f"    ({NAME[kind]} 신호 {gap}일째 없음 · 과거 최장 {mx}일)")

    # ── 지갑 전체: 최근 1년이 과거 1년 구간 중 어디인가 ──
    # 봇과 같은 자동 폭락장: BTC 60일 -15% 켬 / -10% 끔, 전날 종가 → 새 롱 2배
    from ml.bear_leverage import bear_series, is_on
    from bot.oversold import regime as REG
    BS = bear_series(btc, REG.AUTO_BEAR_ON, REG.AUTO_BEAR_OFF, REG.AUTO_BEAR_N)
    tr = [dict(t, kind="longb") if is_on(BS, t["dt"]) else t for t in L] + Sh + Dv
    pt = dict(PT, longb=PT["long"]); lv = dict(LV, longb=2.0)
    fin, mdd, got, curve = taken(tr, pt, lv)
    if bool(BS.iloc[-1]):
        warn.append("자동 폭락장 켜짐 — 새 롱은 2배로 들어간다")
    c = curve.resample("D").last().ffill()
    if len(c) > 400:
        yr = c.iloc[-1] / c.loc[:c.index[-1] - pd.Timedelta(days=365)].iloc[-1]
        q90 = c.iloc[-1] / c.loc[:c.index[-1] - pd.Timedelta(days=90)].iloc[-1]
        w = UP.windows(c)
        pct = float((w < yr).mean() * 100)
        dd_now = 1 - c.iloc[-1] / c.max()
        lines.append("")
        lines.append(f"지갑 백테스트(4배·폭락장 2배): 최근 90일 {(q90-1)*100:+.0f}% · "
                     f"최근 1년 {(yr-1)*100:+.0f}% (과거 1년 구간 중 하위 {pct:.0f}%)")
        lines.append(f"  2019~ {fin:.1f}배 · 최대낙폭 {mdd*100:.0f}% · 지금 고점 대비 -{dd_now*100:.0f}%")
        if pct < 5:
            warn.append(f"최근 1년 결과가 과거 1년 구간 중 하위 {pct:.0f}% — 전략이 시장과 안 맞기 시작했을 수 있다")

    lines.append("")
    # 매일 전략 연구(Claude 세션)가 남긴 최신 보고서의 첫 줄 "요약: ..."
    rdir = os.path.join(ROOT, "reports", "research")
    reps = sorted(f for f in os.listdir(rdir) if f.endswith(".md")) if os.path.isdir(rdir) else []
    if reps:
        first = open(os.path.join(rdir, reps[-1]), encoding="utf-8").readline().strip()
        lines.append(f"🔬 연구 {reps[-1][5:10].replace('-', '/')}: {first.removeprefix('요약:').strip()[:120]}")
        if (today - pd.Timestamp(reps[-1][:10])).days > 2:
            warn.append(f"매일 연구 보고서가 {(today - pd.Timestamp(reps[-1][:10])).days}일째 없다 — 연구 세션 확인")
        lines.append("")
    if warn:
        lines.append(f"⚠️ 확인할 것 {len(warn)}건")
        lines += [f" · {x}" for x in warn]
    else:
        lines.append("✅ 이상 없음 — 지금 규칙 그대로 유지")
    text = "\n".join(lines)
    print(text)

    os.makedirs(OUT_DIR, exist_ok=True)
    open(os.path.join(OUT_DIR, "health_latest.txt"), "w", encoding="utf-8").write(text + "\n")
    hp = os.path.join(OUT_DIR, "health_history.csv")
    row = pd.DataFrame([{"date": f"{today:%Y-%m-%d}", "data_until": f"{newest:%Y-%m-%d %H:%M}",
                         "warnings": len(warn), "summary": " | ".join(warn)[:500]}])
    if os.path.exists(hp):
        old = pd.read_csv(hp)
        row = pd.concat([old[old["date"] != row["date"][0]], row])
    row.to_csv(hp, index=False)

    if a.send:
        tok, chat = os.getenv("TG_BOT_TOKEN"), os.getenv("TG_CHAT_ID")
        if not tok or not chat:
            print("TG_BOT_TOKEN / TG_CHAT_ID 없음 — 보내지 않음")
            return 0
        import requests
        rr = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                           json={"chat_id": chat, "text": text}, timeout=20)
        print("텔레그램:", "보냄" if rr.ok else f"실패 {rr.status_code}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
