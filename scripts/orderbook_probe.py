"""
scripts/orderbook_probe.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
호가창 아카이브가 실제로 어느 경로에 있는가

bybit/collect_orderbook.py가 30일 요청에 30일 전부 404를 받았다.
경로를 추측해서 짠 탓이다. 추측을 멈추고 실제로 찔러본다.

data.binance.vision의 디렉터리 목록은 XML로 받을 수 있다
(?prefix=...&delimiter=/). 그걸로 무엇이 실제로 있는지 확인하고,
후보 경로들도 직접 HEAD로 찔러본다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations
import sys
from datetime import date, timedelta
import requests
import xml.etree.ElementTree as ET

BASE = "https://data.binance.vision"
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"


def listing(prefix: str, limit: int = 40):
    """S3 스타일 목록. 그 경로에 무엇이 있는지 그대로 보여준다."""
    url = f"{BASE}/?prefix={prefix}&delimiter=/&max-keys=1000"
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        pres = [p.findtext(f"{NS}Prefix") for p in root.findall(f"{NS}CommonPrefixes")]
        keys = [k.findtext(f"{NS}Key") for k in root.findall(f"{NS}Contents")]
        return pres[:limit], keys[:limit]
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def head(url: str):
    try:
        r = requests.head(url, timeout=30, allow_redirects=True)
        return r.status_code, r.headers.get("Content-Length", "?")
    except Exception as e:
        return 0, str(e)[:60]


def main():
    print("## 호가창 아카이브 경로 탐색\n")

    print("### 1. futures/um/daily 아래에 무엇이 있나\n")
    pres, keys = listing("data/futures/um/daily/")
    if pres is None:
        print(f"목록 조회 실패: {keys}\n")
    else:
        for p in pres:
            print(f"- `{p}`")
        print()

    print("### 2. spot/daily 아래에 무엇이 있나\n")
    pres, keys = listing("data/spot/daily/")
    if pres is None:
        print(f"목록 조회 실패: {keys}\n")
    else:
        for p in pres:
            print(f"- `{p}`")
        print()

    print("### 3. bookTicker 디렉터리가 있다면, 실제 파일 이름은\n")
    for base in ("data/futures/um/daily/bookTicker/BTCUSDT/",
                 "data/spot/daily/bookTicker/BTCUSDT/",
                 "data/futures/um/daily/bookDepth/BTCUSDT/"):
        pres, keys = listing(base, limit=5)
        print(f"**{base}**")
        if pres is None:
            print(f"  조회 실패: {keys}")
        elif not keys:
            print("  비어 있음 (또는 없음)")
        else:
            for k in keys[:5]:
                print(f"  - `{k}`")
        print()

    print("### 4. 후보 URL 직접 확인\n")
    print("| 상태 | 크기 | URL |")
    print("|---|---|---|")
    d = date.today() - timedelta(days=7)
    cands = [
        f"{BASE}/data/futures/um/daily/bookTicker/BTCUSDT/BTCUSDT-bookTicker-{d}.zip",
        f"{BASE}/data/spot/daily/bookTicker/BTCUSDT/BTCUSDT-bookTicker-{d}.zip",
        f"{BASE}/data/futures/um/daily/bookDepth/BTCUSDT/BTCUSDT-bookDepth-{d}.zip",
        f"{BASE}/data/futures/um/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-{d}.zip",
        f"{BASE}/data/futures/um/daily/trades/BTCUSDT/BTCUSDT-trades-{d}.zip",
        # 오래된 날짜 — 최근분이 아직 안 올라온 것인지 구분하려고
        f"{BASE}/data/futures/um/daily/bookTicker/BTCUSDT/BTCUSDT-bookTicker-2025-01-15.zip",
        f"{BASE}/data/futures/um/daily/bookDepth/BTCUSDT/BTCUSDT-bookDepth-2025-01-15.zip",
        f"{BASE}/data/spot/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-2025-01-15.zip",
    ]
    for u in cands:
        c, sz = head(u)
        mark = "✅" if c == 200 else ("⛔" if c == 403 else "❌")
        try:
            sz = f"{int(sz)/1e6:.1f}MB"
        except Exception:
            pass
        print(f"| {mark} {c} | {sz} | `{u.replace(BASE+'/data/','')}` |")
    print()


if __name__ == "__main__":
    main()
