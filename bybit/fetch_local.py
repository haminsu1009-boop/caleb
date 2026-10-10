"""
bybit/fetch_local.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
바이빗 캔들 수집 — 네 PC에서 직접 실행하는 버전

왜 로컬이어야 하나:
    바이빗은 미국 IP를 차단한다. GitHub Actions 러너는 전부 미국(Azure)
    이라 워크플로에서는 첫 요청부터 403이 난다("your ip is from the usa").
    이 세션의 프록시도 거래소 도메인을 전부 막는다. 한국에서 직접 받는
    것 말고는 경로가 없다.

의존성 없음:
    표준 라이브러리만 쓴다. pip install 필요 없고 파이썬만 있으면 된다.
    (pandas·pybit 안 씀 — 설치 실패로 막히는 일을 없애려고)

사용법:
    python bybit/fetch_local.py                  # 4시간봉 + 일봉, 46종목
    python bybit/fetch_local.py --interval 240   # 4시간봉만
    python bybit/fetch_local.py --symbols BTCUSDT ETHUSDT

끝나면:
    git add data/bybit && git commit -m "data: bybit candles" && git push
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import argparse
import csv
import gzip
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAVE_DIR = os.path.join(ROOT, "data", "bybit")

API = "https://api.bybit.com/v5/market/kline"

SYMBOLS = ["AAVEUSDT", "ADAUSDT", "ALGOUSDT", "APTUSDT", "ARBUSDT", "ATOMUSDT", "AVAXUSDT",
           "AXSUSDT", "BNBUSDT", "BTCUSDT", "CHZUSDT", "DOGEUSDT", "DOTUSDT", "EGLDUSDT",
           "EOSUSDT", "ETCUSDT", "ETHUSDT", "FILUSDT", "FLOWUSDT", "FTMUSDT", "GRTUSDT",
           "HBARUSDT", "ICPUSDT", "INJUSDT", "IOTAUSDT", "LINKUSDT", "LTCUSDT", "MANAUSDT",
           "MATICUSDT", "MKRUSDT", "NEARUSDT", "NEOUSDT", "OPUSDT", "QNTUSDT", "RUNEUSDT",
           "SANDUSDT", "SEIUSDT", "SOLUSDT", "SUIUSDT", "THETAUSDT", "TIAUSDT", "TRXUSDT",
           "UNIUSDT", "VETUSDT", "XLMUSDT", "XRPUSDT"]

LABEL = {"240": "4h", "D": "1d", "60": "1h", "15": "15m", "5": "5m"}


def get(url: str, retries: int = 4) -> dict:
    ctx = ssl.create_default_context()
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
                return json.loads(r.read().decode())
        except Exception as e:                       # 네트워크 흔들림은 물러섰다 재시도
            last = e
            time.sleep(2 ** i)
    raise RuntimeError(last)


def fetch(symbol: str, interval: str, max_batches: int = 200) -> list:
    """바이빗 V5는 최신순으로 1000개씩 준다. end를 뒤로 밀며 과거를 훑는다."""
    rows, end, seen = [], None, set()
    for _ in range(max_batches):
        url = f"{API}?category=linear&symbol={symbol}&interval={interval}&limit=1000"
        if end is not None:
            url += f"&end={end}"
        r = get(url)
        if r.get("retCode") != 0:
            raise RuntimeError(r.get("retMsg", r))
        batch = r.get("result", {}).get("list", [])
        if not batch:
            break
        fresh = [b for b in batch if b[0] not in seen]
        if not fresh:
            break
        seen.update(b[0] for b in fresh)
        rows.extend(fresh)
        oldest = int(batch[-1][0])                   # 최신순이라 마지막이 가장 오래된 봉
        if end is not None and oldest >= end:
            break
        end = oldest - 1
        time.sleep(0.12)
        if len(batch) < 1000:
            break
    return rows


def save(symbol: str, interval: str, rows: list) -> tuple:
    rows = sorted({r[0]: r for r in rows}.values(), key=lambda r: int(r[0]))
    os.makedirs(SAVE_DIR, exist_ok=True)
    path = os.path.join(SAVE_DIR, f"{symbol}_{LABEL.get(interval, interval)}.csv.gz")
    with gzip.open(path, "wt", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["datetime", "open", "high", "low", "close", "volume"])
        for r in rows:
            dt = datetime.fromtimestamp(int(r[0]) / 1000, tz=timezone.utc)
            w.writerow([dt.strftime("%Y-%m-%d %H:%M:%S"), r[1], r[2], r[3], r[4], r[5]])
    first = datetime.fromtimestamp(int(rows[0][0]) / 1000, tz=timezone.utc).date()
    last = datetime.fromtimestamp(int(rows[-1][0]) / 1000, tz=timezone.utc).date()
    return path, first, last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", nargs="*", default=["240", "D"])
    ap.add_argument("--symbols", nargs="*", default=None)
    a = ap.parse_args()

    targets = a.symbols or SYMBOLS
    print("=" * 74)
    print(f"  바이빗 캔들 수집 — {len(targets)}종목 × {len(a.interval)}인터벌")
    print("=" * 74)

    # 첫 요청으로 지역 차단 여부를 먼저 확인한다. 막혀 있으면 46종목을
    # 헛돌리지 않고 바로 안내하고 끝낸다.
    try:
        probe = get(f"{API}?category=linear&symbol=BTCUSDT&interval=D&limit=1")
        if probe.get("retCode") != 0:
            raise RuntimeError(probe.get("retMsg"))
    except Exception as e:
        msg = str(e)
        print(f"\n  ❌ 바이빗에 접속할 수 없다: {msg}\n")
        if "usa" in msg.lower():
            print("     바이빗의 미국 IP 차단이다. VPN이 미국으로 잡혀 있으면 끄고,")
            print("     한국 회선에서 다시 실행해봐.")
        elif "Tunnel connection failed" in msg or "proxy" in msg.lower():
            print("     프록시가 거래소 도메인을 막고 있다. 이건 자동화 환경(에이전트 세션,")
            print("     GitHub Actions) 안에서 돌릴 때 나는 증상이다. 네 PC 터미널에서")
            print("     직접 실행해야 한다.")
        else:
            print("     네트워크 또는 방화벽 문제일 수 있다.")
        sys.exit(1)
    print("  ✅ 접속 확인\n")

    ok = fail = 0
    for iv in a.interval:
        print(f"  ── {LABEL.get(iv, iv)} ──")
        for i, s in enumerate(targets, 1):
            try:
                rows = fetch(s, iv)
                if not rows:
                    print(f"    [{i:>2}/{len(targets)}] {s:12s} 데이터 없음 (미상장)")
                    continue
                path, f0, f1 = save(s, iv, rows)
                print(f"    [{i:>2}/{len(targets)}] {s:12s} {len(rows):>7,}건  {f0} ~ {f1}")
                ok += 1
            except Exception as e:
                print(f"    [{i:>2}/{len(targets)}] {s:12s} 실패 — {e}")
                fail += 1
        print()

    print("=" * 74)
    print(f"  완료: 성공 {ok}개 파일, 실패 {fail}개  →  {SAVE_DIR}")
    print()
    print("  다음 단계 — 아래를 그대로 복사해서 실행:")
    print("    git add data/bybit")
    print('    git commit -m "data: bybit real exchange candles"')
    print("    git push origin claude/quant-trading-bot-tkjtd")
    print("=" * 74)


if __name__ == "__main__":
    main()
