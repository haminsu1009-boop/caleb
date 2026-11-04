"""
tools/check_tp.py — 롱 포지션이 익절가에 닿았는데 안 팔렸는지 확인한다 (주문 없음, 읽기만)

익절가는 고정이 아니다. 봇이 4시간봉이 확정될 때마다 볼린저 상단으로
다시 계산해 거래소에 건다(0.5% 넘게 바뀔 때만). 그래서 "지금 익절선보다
위로 갔는데 안 팔렸다"처럼 보여도, 그 순간 걸려 있던 익절가는 더 위였을
수 있다. 이 스크립트는 4시간 구간마다

    그 구간에 걸려 있었을 익절가  vs  그 구간 15분봉 최고가

를 나란히 보여준다. 최고가가 익절가 이상인 구간이 있으면 정말로 닿았는데
안 팔린 것이다 → 시스템 오류 가능성.

    python -m tools.check_tp RUNEUSDT
    python -m tools.check_tp RUNEUSDT --entry 0.5323 --since "2026-11-02 08:00"

평단·진입 시각은 state_live.json에서 읽는다. 포지션이 이미 닫혔으면 직접 넣는다.
봇 로그의 실제 익절가 기록도 함께 보려면:
    journalctl -u oversold-bot --since "2 days ago" --no-pager | grep "보유 RUNE" | awk 'NR%20==1'
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bot.oversold import strategy as S

BAR = 4 * 3600 * 1000
KST = 9 * 3600 * 1000


def klines(sym: str, interval: str, start: int) -> list:
    import requests
    out, cur = [], start
    while True:
        r = requests.get("https://api.bybit.com/v5/market/kline",
                         params={"category": "linear", "symbol": sym, "interval": interval,
                                 "start": cur, "limit": 1000}, timeout=15).json()
        rows = sorted(r["result"]["list"], key=lambda x: int(x[0]))
        if not rows:
            break
        out += [[int(x[0]), *map(float, x[1:5])] for x in rows if not out or int(x[0]) > out[-1][0]]
        if len(rows) < 1000:
            break
        cur = int(rows[-1][0]) + 1
    return out


def ts(ms: int) -> str:
    return datetime.fromtimestamp((ms + KST) / 1000, timezone.utc).strftime("%m-%d %H:%M")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sym")
    ap.add_argument("--entry", type=float, help="평단 (없으면 state_live.json)")
    ap.add_argument("--since", help="진입 시각, 한국시간 'YYYY-MM-DD HH:MM' (없으면 state_live.json)")
    a = ap.parse_args()

    entry, since = a.entry, None
    if a.since:
        since = int(datetime.strptime(a.since, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
                    .timestamp() * 1000) - KST
    try:
        p = json.load(open(os.path.join(ROOT, "bot", "oversold", "state_live.json")))["positions"][a.sym]
        entry = entry or p["entry"]
        since = since or int(p["entry_bar"])
    except Exception:
        pass
    if not entry or not since:
        raise SystemExit("포지션 기록이 없다 — --entry 와 --since 를 넣어라")

    k4 = klines(a.sym, "240", since - (S.BB_PERIOD + 5) * BAR)
    k15 = klines(a.sym, "15", since)
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    print(f"{a.sym} 평단 {entry:.6g} · 진입 봉 {ts(since)} (한국시간) · 4시간봉 {len(k4)}개 · 15분봉 {len(k15)}개\n")
    print(f"{'구간 시작(KST)':<14}{'걸려 있던 익절가':>16}{'그 구간 최고가':>16}  판정")
    hit = []
    tp_live = None
    for i, bar in enumerate(k4):
        t0 = bar[0]
        if t0 < since + BAR or t0 > now:
            continue
        closes = [b[4] for b in k4[:i]]             # 이 구간이 시작될 때 확정된 봉까지
        tp = S.take_profit_price(closes, entry)
        if tp is not None and (tp_live is None or abs(tp / tp_live - 1) > 0.005):
            tp_live = tp                            # 봇은 0.5% 넘게 바뀔 때만 다시 건다
        hi = max([b[2] for b in k15 if t0 <= b[0] < t0 + BAR] or [bar[2]])
        mark = "—" if tp_live is None else ("⚠️ 닿음" if hi >= tp_live else f"못 닿음 ({(hi/tp_live-1)*100:+.1f}%)")
        print(f"{ts(t0):<14}{(f'{tp_live:.6g}' if tp_live else '없음'):>16}{hi:>16.6g}  {mark}")
        if tp_live and hi >= tp_live:
            hit.append(ts(t0))
    print()
    if tp_live is None and not hit:
        raise SystemExit("확인할 구간이 없다 — 진입 시각(--since)이나 시세 조회를 확인할 것")
    if hit:
        print(f"⚠️ 익절가 이상으로 올라간 구간: {', '.join(hit)}")
        print("   그 시각 포지션이 그대로라면 거래소 익절 주문이 안 걸려 있었을 수 있다 — 봇 로그의")
        print("   '목표 설정 실패' 기록과 Bybit 앱의 주문 내역(조건부/TP·SL)을 확인할 것.")
    else:
        print("✅ 어느 구간에서도 그때 걸려 있던 익절가에 닿지 않았다 — 오류가 아니라 익절가가 위에 있었던 것.")
    print("   (계산한 익절가는 봇과 같은 식이지만, 갱신 시각이 몇 분 다를 수 있다)")


if __name__ == "__main__":
    main()
