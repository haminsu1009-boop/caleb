"""
ml/listing_study.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
신규 상장 직후 가격은 어떻게 움직이나 — 뉴스·공지 이벤트의 첫 번째 검증

사람 단타 고수가 쓰는 무기 중 캔들 밖 정보가 있다 — 상장 공지, 뉴스.
뉴스 본문을 과거까지 모을 방법은 없지만, 뉴스 중 가장 크고 규칙적인
사건인 **신규 상장**은 거래소가 날짜를 정확히 남긴다.

바이빗 무기한 전 종목의 상장 시각(launchTime)을 받고, 상장 직후 1시간봉을
받아 "상장 후 N시간/일 수익률"을 센다. 흔히 도는 말은 둘이다 —
"상장 직후 펌핑" 과 "상장 후 계속 흘러내린다". 어느 쪽이 사실인지,
그리고 그게 수수료를 넘는 크기인지 본다.

진입은 상장 **두 번째 1시간봉 시가**다. 첫 봉은 호가가 얇고 공지 순간
체결은 사람이 따라갈 수 없다. 같은 기간 BTC 수익률을 빼서 시장 전체
움직임을 걷어낸다. 2024년 이전 상장으로 방향을 정하고 이후로 채점한다.

이 파일은 **서버에서** 돌린다. 분석 환경에서는 바이빗 API가 막혀 있다.
공개 API만 쓰고 키가 필요 없다.

    cd ~/caleb && .venv/bin/python -m ml.listing_study
    결과 → data/listings/listing_study.csv
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations
import os, sys, time
import numpy as np
import pandas as pd
from pybit.unified_trading import HTTP

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "listings")
HOURS = [1, 4, 24, 72, 168, 720]          # 1h 4h 1d 3d 7d 30d
SINCE = pd.Timestamp("2021-01-01")
TE = pd.Timestamp("2024-01-01")
FEE = 0.11                                 # 테이커 왕복 %


def klines_from(s, sym, start_ms, n=1000):
    for k in range(5):
        try:
            time.sleep(0.15)
            r = s.get_kline(category="linear", symbol=sym, interval="60",
                            start=start_ms, limit=n)
            rows = sorted(r["result"]["list"], key=lambda x: int(x[0]))
            return pd.DataFrame([{"t": int(x[0]), "o": float(x[1]), "c": float(x[4])}
                                 for x in rows])
        except Exception as e:
            time.sleep(2 ** k)
    return pd.DataFrame()


def main():
    os.makedirs(OUT, exist_ok=True)
    s = HTTP(testnet=False)
    inst, cur = [], None
    while True:
        r = s.get_instruments_info(category="linear", limit=1000,
                                   **({"cursor": cur} if cur else {}))
        inst += r["result"]["list"]
        cur = r["result"].get("nextPageCursor")
        if not cur:
            break
    L = [(x["symbol"], pd.to_datetime(int(x["launchTime"]), unit="ms"))
         for x in inst if x.get("quoteCoin") == "USDT" and x.get("contractType") == "LinearPerpetual"
         and int(x.get("launchTime") or 0) > 0]
    L = [(sym, t) for sym, t in L if t >= SINCE and sym != "BTCUSDT"]
    print(f"USDT 무기한 {len(inst)}종 중 {SINCE.date()} 이후 상장 {len(L)}종을 받는다 (몇 분 걸림)")

    btc_cache = {}
    rows = []
    for i, (sym, t) in enumerate(sorted(L, key=lambda x: x[1])):
        k = klines_from(s, sym, int(t.value // 10**6))
        if len(k) < 3:
            continue
        e = k.o.iloc[1]                                  # 두 번째 봉 시가
        t0 = int(k.t.iloc[1])
        key = t0 // (3600 * 1000 * 24 * 30)
        if key not in btc_cache:
            btc_cache[key] = klines_from(s, "BTCUSDT", t0)
        b = btc_cache[key]
        b = b[b.t >= t0].reset_index(drop=True)
        row = dict(sym=sym, launch=t, entry=e)
        for H in HOURS:
            if len(k) > H + 1 and len(b) > H:
                r_ = (k.c.iloc[H] / e - 1) * 100
                rb = (b.c.iloc[H - 1] / b.o.iloc[0] - 1) * 100
                row[f"r{H}"] = r_; row[f"x{H}"] = r_ - rb
        rows.append(row)
        if (i + 1) % 25 == 0:
            print(f"  {i+1}/{len(L)}")
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT, "listing_study.csv"), index=False)

    print("\n" + "=" * 96)
    print("  신규 상장 후 수익률 (BTC 대비 초과) · 진입 = 상장 두 번째 1시간봉 시가")
    print("=" * 96)
    print(f"\n  {'보유':>6s}{'구간':>6s}{'n':>6s}{'평균':>9s}{'중앙':>9s}{'오른 비율':>10s}"
          f"{'롱 순수익':>10s}{'숏 순수익':>10s}")
    print("  " + "-" * 66)
    lab = {1: "1시간", 4: "4시간", 24: "1일", 72: "3일", 168: "7일", 720: "30일"}
    for H in HOURS:
        c = f"x{H}"
        if c not in df:
            continue
        for part, d in [("학습", df[df.launch < TE]), ("홀드", df[df.launch >= TE])]:
            v = d[c].dropna()
            if len(v) < 10:
                continue
            print(f"  {lab[H]:>6s}{part:>6s}{len(v):>6}{v.mean():>+8.2f}%{v.median():>+8.2f}%"
                  f"{(v > 0).mean()*100:>9.0f}%{v.mean()-FEE:>+9.2f}%{-v.mean()-FEE:>+9.2f}%")
    print("\n  (평균은 소수 대박 코인에 끌린다. 중앙값과 '오른 비율'을 같이 봐야 한다)")
    print("=" * 96)


if __name__ == "__main__":
    main()
