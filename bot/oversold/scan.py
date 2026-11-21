"""
bot/oversold/scan.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
지금 시장 스캐너 — 수동 매매용

봇은 5분마다 42종만 보고, 조건이 맞을 때만 조용히 들어간다. 사람이
직접 매매할 때(대회 등)는 "지금 어디가 움직이고 있나"를 한눈에 봐야
한다. 이 스크립트는 거래대금 상위 USDT 무기한을 훑어 한 화면에 찍는다.

    🔥 과매도       4시간봉 20기간선 대비 -12.26% 이하 — 봇의 검증된 진입 조건
    ⚠️ 근접         -8% ~ -12.26% — 조금 더 빠지면 신호
    ⚡ 1시간 급락    1시간봉 20기간선 대비 -6% 이하 — 단기 과열 하락
    변동폭           24시간 고가/저가 폭 — 수익률 대회에서 움직임이 큰 코인

맨 위에 BTC 7일 수익률을 찍는다. -10% 아래면 폭락장 쪽이라 롱을 조심한다
(ml/leverage_filters.py — 그 구간 롱이 청산의 대부분을 만든다).

--equity / --risk / --stop 을 주면 포지션 크기를 계산한다.
    "자본 E에서 이번 거래로 최대 R%만 잃겠다, 손절은 진입가 대비 S%"
    → 명목가 = E × R / S,  필요 배율 = 명목가 / (E × 한 번에 쓰는 비율)
손절이 청산선보다 안쪽에 있어야 한다. 배율 L의 청산선은 대략 -100/L %.

공개 API만 쓴다. 키가 필요 없다. 서버에서 돌린다.

    cd ~/caleb && .venv/bin/python -m bot.oversold.scan
    .venv/bin/python -m bot.oversold.scan --equity 150 --risk 2 --stop 3
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations
import argparse
import time
import numpy as np
from pybit.unified_trading import HTTP

THRESH = -12.26
NEAR = -8.0


def _kl(s, sym, interval, limit=60):
    for k in range(4):
        try:
            time.sleep(0.12)
            r = s.get_kline(category="linear", symbol=sym, interval=interval, limit=limit)
            rows = sorted(r["result"]["list"], key=lambda x: int(x[0]))
            return np.array([float(x[4]) for x in rows])
        except Exception:
            time.sleep(2 ** k)
    return np.array([])


def vs_ma(c, n=20):
    if len(c) < n:
        return np.nan
    return (c[-1] / c[-n:].mean() - 1) * 100


def rsi(c, n=14):
    if len(c) < n + 1:
        return np.nan
    d = np.diff(c)
    up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    a = 1 / n
    ru = up[0]; rd = dn[0]
    for i in range(1, len(d)):
        ru = ru * (1 - a) + up[i] * a
        rd = rd * (1 - a) + dn[i] * a
    return 100.0 if rd == 0 else 100 - 100 / (1 + ru / rd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=60, help="거래대금 상위 몇 종목을 볼지")
    ap.add_argument("--equity", type=float, help="자본(USDT)")
    ap.add_argument("--risk", type=float, help="이번 거래 최대 손실(자본 대비 %)")
    ap.add_argument("--stop", type=float, help="손절폭(진입가 대비 %)")
    a = ap.parse_args()

    s = HTTP(testnet=False)
    tk = s.get_tickers(category="linear")["result"]["list"]
    tk = [x for x in tk if x["symbol"].endswith("USDT")]
    tk.sort(key=lambda x: -float(x.get("turnover24h") or 0))
    tk = tk[: a.top]

    btc = _kl(s, "BTCUSDT", "D", 10)
    btc7 = (btc[-1] / btc[-8] - 1) * 100 if len(btc) >= 8 else float("nan")
    print("=" * 92)
    print(f"  시장 스캐너 · 거래대금 상위 {len(tk)}종 · BTC 7일 {btc7:+.1f}%"
          + ("   ⛔ 폭락장 쪽 — 롱 조심" if btc7 <= -10 else ""))
    print("=" * 92)

    rows = []
    for x in tk:
        sym = x["symbol"]
        c4 = _kl(s, sym, "240"); c1 = _kl(s, sym, "60")
        if len(c4) < 21 or len(c1) < 21:
            continue
        hi, lo, last = float(x["highPrice24h"]), float(x["lowPrice24h"]), float(x["lastPrice"])
        rows.append(dict(sym=sym, last=last, chg=float(x["price24hPcnt"]) * 100,
                         rng=(hi / lo - 1) * 100 if lo else np.nan,
                         v4=vs_ma(c4), v1=vs_ma(c1), r1=rsi(c1),
                         tov=float(x.get("turnover24h") or 0) / 1e6))

    def flag(r):
        f = []
        if r["v4"] <= THRESH: f.append("🔥과매도")
        elif r["v4"] <= NEAR: f.append("⚠️근접")
        if r["v1"] <= -6: f.append("⚡1h급락")
        return " ".join(f)

    print(f"\n  {'종목':12s}{'현재가':>12s}{'24h':>8s}{'변동폭':>8s}{'4h/20선':>9s}"
          f"{'1h/20선':>9s}{'1h RSI':>8s}{'거래대금':>10s}  신호")
    print("  " + "-" * 88)
    for r in sorted(rows, key=lambda r: r["v4"]):
        f = flag(r)
        if not f and r["v4"] > NEAR:
            continue
        print(f"  {r['sym']:12s}{r['last']:>12.6g}{r['chg']:>+7.1f}%{r['rng']:>7.1f}%"
              f"{r['v4']:>+8.1f}%{r['v1']:>+8.1f}%{r['r1']:>8.0f}{r['tov']:>8.0f}M  {f}")

    print(f"\n  변동폭 상위 10 (수익률 대회에서 움직임이 큰 코인)")
    for r in sorted(rows, key=lambda r: -r["rng"])[:10]:
        print(f"    {r['sym']:12s} 24h 변동폭 {r['rng']:5.1f}% · 24h {r['chg']:+5.1f}% · "
              f"4h/20선 {r['v4']:+5.1f}%  {flag(r)}")

    if a.equity and a.risk and a.stop:
        notional = a.equity * (a.risk / 100) / (a.stop / 100)
        print("\n  포지션 크기")
        print(f"    자본 {a.equity:,.2f} · 최대 손실 {a.risk:g}% ({a.equity*a.risk/100:,.2f} USDT)"
              f" · 손절 -{a.stop:g}%")
        print(f"    → 명목가 {notional:,.2f} USDT")
        for L in [2, 3, 5, 10]:
            liq = 100 / L - 0.5
            margin = notional / L
            ok = "✅" if a.stop < liq * 0.8 else "❌ 손절이 청산선에 너무 가깝다"
            print(f"      {L:>2}배: 증거금 {margin:,.2f} USDT"
                  f" ({margin/a.equity*100:4.0f}% of 자본) · 청산선 -{liq:.1f}%  {ok}")
    print("=" * 92)


if __name__ == "__main__":
    main()
