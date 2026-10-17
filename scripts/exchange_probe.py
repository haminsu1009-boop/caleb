"""
scripts/exchange_probe.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
어느 거래소가 이 환경에서 뚫리는가

바이빗은 GitHub Actions에서 막힌다는 것이 이미 확인됐다 —
러너가 미국 IP라 "your ip is from the usa (ErrCode: 403)"가 뜬다.
그렇다면 다른 거래소는? 하나라도 뚫리면 Actions로 굴릴 길이
생길지 모른다. 추측하지 말고 실제로 찔러본다.

공개 엔드포인트만 호출한다. API 키는 쓰지 않는다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import json
import requests

TARGETS = [
    ("Bybit",        "https://api.bybit.com/v5/market/time"),
    ("Bybit 시세",    "https://api.bybit.com/v5/market/kline"
                      "?category=linear&symbol=BTCUSDT&interval=240&limit=2"),
    ("Binance 현물",  "https://api.binance.com/api/v3/time"),
    ("Binance 선물",  "https://fapi.binance.com/fapi/v1/time"),
    ("Binance 아카이브", "https://data.binance.vision/data/spot/monthly/klines/"
                         "BTCUSDT/4h/BTCUSDT-4h-2025-01.zip"),
    ("OKX",          "https://www.okx.com/api/v5/public/time"),
    ("Bitget",       "https://api.bitget.com/api/v2/public/time"),
    ("Gate.io",      "https://api.gateio.ws/api/v4/spot/time"),
    ("MEXC",         "https://api.mexc.com/api/v3/time"),
    ("KuCoin",       "https://api.kucoin.com/api/v1/timestamp"),
    ("Kraken",       "https://api.kraken.com/0/public/Time"),
    ("Upbit",        "https://api.upbit.com/v1/ticker?markets=KRW-BTC"),
    ("Bithumb",      "https://api.bithumb.com/public/ticker/BTC_KRW"),
    ("Hyperliquid",  "https://api.hyperliquid.xyz/info"),
]


def probe(name: str, url: str) -> dict:
    try:
        r = requests.get(url, timeout=20)
        body = r.text[:160].replace("\n", " ")
        # 200이어도 본문에 거부 사유가 담겨 오는 거래소가 있다
        # (바이빗이 그렇다 — retCode로 403을 싣는다)
        blocked = any(k in body.lower() for k in
                      ("from the usa", "restricted", "unavailable in",
                       "not available", "forbidden"))
        return {"name": name, "code": r.status_code,
                "ok": r.status_code == 200 and not blocked,
                "blocked": blocked, "body": body}
    except Exception as e:
        return {"name": name, "code": 0, "ok": False, "blocked": False,
                "body": f"{type(e).__name__}: {e}"[:160]}


def main():
    print("## 거래소 접속 점검\n")
    print("| 거래소 | 상태 | HTTP | 응답 |")
    print("|---|---|---|---|")
    rows = [probe(n, u) for n, u in TARGETS]
    for r in rows:
        mark = "✅ 가능" if r["ok"] else ("⛔ 차단" if r["blocked"] else "❌ 실패")
        body = r["body"].replace("|", "\\|")[:110]
        print(f"| {r['name']} | {mark} | {r['code']} | `{body}` |")
    ok = [r["name"] for r in rows if r["ok"]]
    print(f"\n**접속 가능 {len(ok)}/{len(rows)}** — {', '.join(ok) if ok else '없음'}\n")
    if not ok:
        print("어느 거래소도 이 환경에서 쓸 수 없다. "
              "실거래는 다른 환경(VPS·집 PC)에서 돌려야 한다.\n")


if __name__ == "__main__":
    main()
