"""
bot/upbit_watch.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
업비트 패턴 감시 봇 — 매매 없음, 감지되면 알림만

⚠️ 이 파일에는 주문 코드가 전혀 없다. 조건이 맞는 캔들이 보이면
   콘솔에 출력하고 알림을 남길 뿐, 어떤 매수·매도·포지션 변경도
   실행하지 않는다.

감시하는 패턴 (전부 지금까지 검증한 규칙 그대로):
  1. 일봉 +4.5% 이상 마감 — 종가 기준, 전일종가 대비
     (홀드아웃 검증: n=35, 5봉후 WR 60.0%, Wilson하한 43.6% — 미확정)
  2. MA5·10·20·60·120 상태기계 (사용자 규칙#1)
     - 국면A(120선 미돌파, 5·10·20 돌파) + 음봉이 군집 최상단 터치 → 숏 후보
     - 국면A + 종가 -4.5% 이상 하락 → 숏 후보
     - 국면B(120선 돌파 후 이탈) + 확인 음봉 → 숏 후보
     ⚠️ 홀드아웃에서 존버 대비 저조했던 규칙 — "터치" 등 해석에
        확인이 필요한 상태. 알림은 나가되 신뢰도는 낮게 표시한다.

데이터: data/upbit/*.csv.gz (upbit/collect_upbit.py + GitHub Actions로 수집)
        이 세션에서는 업비트 API를 직접 못 불러 로컬 파일 기준으로 판단한다.

사용법:
    python bot/upbit_watch.py                  # 전 종목 1회 스캔
    python bot/upbit_watch.py --market KRW-BTC # 특정 종목만
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, glob, json, argparse
from datetime import datetime, timezone

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DATA_DIR = os.path.join(ROOT, "data", "upbit")
STATE_PATH = os.path.join(ROOT, "bot", "upbit_watch_state.json")

DROP_TH = -0.045
RISE_TH = 0.045


def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        try:
            return json.load(open(STATE_PATH, encoding="utf-8"))
        except Exception:
            pass
    return {"last_alert": {}}


def save_state(st: dict):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    json.dump(st, open(STATE_PATH, "w", encoding="utf-8"), indent=2, ensure_ascii=False)


def load_market(market: str, unit: str = "day") -> pd.DataFrame:
    path = os.path.join(DATA_DIR, f"{market}_{unit}.csv.gz")
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, compression="gzip")
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    return df.dropna(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)


def available_markets(unit: str = "day") -> list:
    return sorted(os.path.basename(f).replace(f"_{unit}.csv.gz", "")
                 for f in glob.glob(os.path.join(DATA_DIR, f"*_{unit}.csv.gz")))


# ══════════════════════════════════════════════════════════════
# 지표
# ══════════════════════════════════════════════════════════════

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    c, o = d["close"], d["open"]
    for n in [5, 10, 20, 60, 120]:
        d[f"ma{n}"] = c.rolling(n).mean()
    d["ma_top_51020"] = d[["ma5", "ma10", "ma20"]].max(axis=1)
    d["cc_ret"] = c.pct_change()
    d["bull"] = c > o
    d["bear"] = c < o
    return d


# ══════════════════════════════════════════════════════════════
# 패턴 감지 (마지막 확정봉 기준)
# ══════════════════════════════════════════════════════════════

def check_45_rule(d: pd.DataFrame) -> dict | None:
    last = d.iloc[-1]
    if pd.isna(last["cc_ret"]):
        return None
    if last["cc_ret"] >= RISE_TH:
        return {"type": "RISE_4_5", "confidence": "미확정(n=35, Wilson하한43.6%)",
                "ret": round(last["cc_ret"]*100, 2), "date": str(last["datetime"].date())}
    if last["cc_ret"] <= DROP_TH:
        return {"type": "DROP_4_5", "confidence": "미확정",
                "ret": round(last["cc_ret"]*100, 2), "date": str(last["datetime"].date())}
    return None


def check_ma_cluster(d: pd.DataFrame) -> dict | None:
    if len(d) < 121 or d["ma120"].isna().iloc[-1]:
        return None
    last = d.iloc[-1]
    c, o, l = last["close"], last["open"], last["low"]
    ma120, ma_top = last["ma120"], last["ma_top_51020"]
    ma5, ma10, ma20 = last["ma5"], last["ma10"], last["ma20"]

    above120 = c > ma120
    broke_51020 = (c > ma5) and (c > ma10) and (c > ma20)
    regimeA = broke_51020 and not above120
    touch_top = l <= ma_top
    bear = c < o

    if regimeA and bear and touch_top:
        return {"type": "MA_CLUSTER_SHORT_TOUCH", "confidence": "낮음(홀드아웃 미검증)",
                "date": str(last["datetime"].date()), "ma_top": round(ma_top, 2)}
    if regimeA and last["cc_ret"] <= DROP_TH and bear:
        return {"type": "MA_CLUSTER_SHORT_DROP", "confidence": "낮음",
                "date": str(last["datetime"].date())}

    prev = d.iloc[-2] if len(d) > 1 else None
    if prev is not None and not pd.isna(prev["ma120"]):
        prev_above120 = prev["close"] > prev["ma120"]
        if prev_above120 and not above120 and bear:
            return {"type": "MA120_BREAKDOWN_CONFIRM", "confidence": "낮음",
                    "date": str(last["datetime"].date())}
    return None


# ══════════════════════════════════════════════════════════════
# 스캔
# ══════════════════════════════════════════════════════════════

def scan(markets: list, notify: bool = False) -> list:
    st = load_state()
    alerts = []

    for m in markets:
        df = load_market(m, "day")
        if df.empty or len(df) < 30:
            continue
        d = add_indicators(df)

        for check in (check_45_rule, check_ma_cluster):
            hit = check(d)
            if hit is None:
                continue
            key = f"{m}:{hit['type']}:{hit['date']}"
            if st["last_alert"].get(key):
                continue          # 같은 신호 중복 알림 방지
            hit["market"] = m
            alerts.append(hit)
            st["last_alert"][key] = True

    save_state(st)
    return alerts


LABEL = {
    "RISE_4_5": "📈 일봉 +4.5%+ 마감",
    "DROP_4_5": "📉 일봉 -4.5%+ 마감",
    "MA_CLUSTER_SHORT_TOUCH": "🔻 MA군집 상단터치+음봉 (숏후보)",
    "MA_CLUSTER_SHORT_DROP": "🔻 MA군집 국면A -4.5%음봉 (숏후보)",
    "MA120_BREAKDOWN_CONFIRM": "🔻 MA120 이탈확인 (숏후보)",
}


def format_alert(a: dict) -> str:
    extra = f" {a['ret']:+.1f}%" if "ret" in a else ""
    return f"{LABEL.get(a['type'], a['type'])} — {a['market']} ({a['date']}){extra} [{a['confidence']}]"


def main():
    ap = argparse.ArgumentParser(description="업비트 패턴 감시 (알림 전용, 매매 없음)")
    ap.add_argument("--market", default=None)
    ap.add_argument("--notify", action="store_true", help="터미널 출력 외 알림 시도")
    a = ap.parse_args()

    markets = [a.market] if a.market else available_markets("day")
    if not markets:
        print("⚠️  data/upbit/*.csv.gz 없음 — GitHub Actions 'collect_upbit.yml' 먼저 실행 필요")
        return

    print("=" * 76)
    print(f"  업비트 패턴 스캔 — {len(markets)}종목  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 76)

    alerts = scan(markets)
    if not alerts:
        print("\n  신규 신호 없음")
        return

    for al in alerts:
        print(f"  {format_alert(al)}")

    print(f"\n  총 {len(alerts)}건 (매매 없음 — 알림 전용)")


if __name__ == "__main__":
    main()
