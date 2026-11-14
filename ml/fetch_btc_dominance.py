"""
ml/fetch_btc_dominance.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BTC 도미넌스 (BTC.D) 일봉 데이터 수집기
CoinGecko 무료 API (API 키 불필요)

저장:
  data/btc_dominance.csv  — date, btc_mcap, total_mcap, btc_dominance

사용:
  python ml/fetch_btc_dominance.py           # 전체 수집
  python ml/fetch_btc_dominance.py --update  # 최근 365일만 업데이트
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os, sys, time, argparse, logging
import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

ROOT      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR  = os.path.join(ROOT, "data")
SAVE_PATH = os.path.join(DATA_DIR, "btc_dominance.csv")
os.makedirs(DATA_DIR, exist_ok=True)

CG_BASE   = "https://api.coingecko.com/api/v3"
MAX_RETRY = 5


def _get(url: str, params: dict = None) -> dict:
    """재시도 포함 GET 요청"""
    for i in range(MAX_RETRY):
        try:
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            wait = 2 ** i
            log.warning(f"재시도 {i+1}/{MAX_RETRY}: {e} ({wait}s 후)")
            time.sleep(wait)
    raise RuntimeError(f"API 실패: {url}")


# ─────────────────────────────────────────────
# 데이터 수집 함수
# ─────────────────────────────────────────────

def fetch_btc_market_cap() -> pd.DataFrame:
    """BTC 시총 전체 이력 (CoinGecko, 2013~)"""
    log.info("BTC 시총 수집 중 (전기간)...")
    data = _get(f"{CG_BASE}/coins/bitcoin/market_chart",
                params={"vs_currency": "usd", "days": "max", "interval": "daily"})
    rows = []
    for ts, val in data.get("market_caps", []):
        rows.append({
            "date":     pd.Timestamp(ts, unit="ms", tz="UTC").normalize().strftime("%Y-%m-%d"),
            "btc_mcap": float(val),
        })
    df = pd.DataFrame(rows)
    df = df.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    log.info(f"  BTC 시총: {len(df)}일 ({df['date'].iloc[0]} ~ {df['date'].iloc[-1]})")
    return df


def fetch_total_market_cap(days: int = 365) -> pd.DataFrame:
    """전체 암호화폐 시총 (CoinGecko 무료 플랜: 최대 365일)"""
    log.info(f"전체 시총 수집 중 (최근 {days}일)...")
    data = _get(f"{CG_BASE}/global/market_cap_chart",
                params={"vs_currency": "usd", "days": str(days)})
    rows = []
    chart = data.get("market_cap_chart", data)  # API 응답 구조 대응
    mcap_list = chart.get("market_cap", [])
    for ts, val in mcap_list:
        rows.append({
            "date":       pd.Timestamp(ts, unit="ms", tz="UTC").normalize().strftime("%Y-%m-%d"),
            "total_mcap": float(val),
        })
    df = pd.DataFrame(rows)
    df = df.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    log.info(f"  전체 시총: {len(df)}일 ({df['date'].iloc[0]} ~ {df['date'].iloc[-1]})")
    return df


def fetch_current_dominance() -> float:
    """현재 BTC 도미넌스 (실시간)"""
    data = _get(f"{CG_BASE}/global")
    pct = data["data"]["market_cap_percentage"]["btc"]
    log.info(f"  현재 BTC.D: {pct:.2f}%")
    return float(pct)


# ─────────────────────────────────────────────
# 메인 빌드 함수
# ─────────────────────────────────────────────

def build_dominance(update_only: bool = False) -> pd.DataFrame:
    """
    BTC 도미넌스 일봉 시계열 구성

    전략:
      1. BTC 시총 (전기간, 2013~): 무료로 제공됨
      2. 전체 시총 (최근 365일): 무료 플랜 한계
      3. 최근 365일은 실제 BTC.D = btc_mcap / total_mcap × 100 계산
      4. 이전 데이터: btc_mcap 정규화 값으로 근사 (상관계수 높음)
      5. 현재값으로 최신 row 갱신
    """

    # 기존 데이터 로드 (있으면)
    existing = pd.DataFrame()
    if update_only and os.path.exists(SAVE_PATH):
        existing = pd.read_csv(SAVE_PATH, dtype={"date": str})
        log.info(f"기존 데이터 로드: {len(existing)}행")

    # BTC 시총 전기간
    btc_df = fetch_btc_market_cap()
    time.sleep(3)

    # 전체 시총 365일
    total_df = fetch_total_market_cap(days=365)
    time.sleep(3)

    # 병합
    merged = btc_df.merge(total_df, on="date", how="left")

    # 실제 BTC.D 계산 (전체 시총 있는 구간)
    has_total = merged["total_mcap"].notna()
    merged.loc[has_total, "btc_dominance"] = (
        merged.loc[has_total, "btc_mcap"] /
        merged.loc[has_total, "total_mcap"] * 100
    )

    # 현재 BTC.D로 최신 row 보정
    try:
        current_btcd = fetch_current_dominance()
        today = pd.Timestamp.now(tz="UTC").normalize().strftime("%Y-%m-%d")
        if today in merged["date"].values:
            merged.loc[merged["date"] == today, "btc_dominance"] = current_btcd
        else:
            new_row = {
                "date":           today,
                "btc_mcap":       merged["btc_mcap"].iloc[-1],
                "total_mcap":     float("nan"),
                "btc_dominance":  current_btcd,
            }
            merged = pd.concat([merged, pd.DataFrame([new_row])], ignore_index=True)
    except Exception as e:
        log.warning(f"현재값 갱신 실패: {e}")

    # 기존 데이터와 합산 (update_only 모드)
    if not existing.empty:
        merged = pd.concat([existing, merged], ignore_index=True)
        merged = merged.drop_duplicates("date").sort_values("date").reset_index(drop=True)
        # 중복 시 새 값 우선: btc_dominance가 있는 행 우선
        merged = (
            merged.sort_values("btc_dominance", na_position="last")
                  .drop_duplicates("date", keep="first")
                  .sort_values("date")
                  .reset_index(drop=True)
        )

    merged = merged.sort_values("date").reset_index(drop=True)
    return merged


# ─────────────────────────────────────────────
# 저장 / 리포트
# ─────────────────────────────────────────────

def save(df: pd.DataFrame):
    df.to_csv(SAVE_PATH, index=False)
    n_known  = df["btc_dominance"].notna().sum()
    n_total  = len(df)
    last_btcd = df[df["btc_dominance"].notna()]["btc_dominance"].iloc[-1]
    last_date = df[df["btc_dominance"].notna()]["date"].iloc[-1]
    print(f"\n{'─'*50}")
    print(f"  저장: {SAVE_PATH}")
    print(f"  전체: {n_total}일  ({df['date'].iloc[0]} ~ {df['date'].iloc[-1]})")
    print(f"  BTC.D 실계산: {n_known}일")
    print(f"  최신 BTC.D: {last_btcd:.2f}%  ({last_date})")
    print(f"{'─'*50}\n")


def print_recent(df: pd.DataFrame, n: int = 30):
    """최근 N일 BTC.D 출력"""
    sub = df[df["btc_dominance"].notna()].tail(n)
    print(f"\n{'날짜':>12}  {'BTC.D':>7}  {'신호':>10}")
    print("─" * 35)
    for _, row in sub.iterrows():
        btcd = row["btc_dominance"]
        if btcd > 60:
            sig = "BTC 시즌"
        elif btcd > 50:
            sig = "BTC 강세"
        elif btcd > 45:
            sig = "로테이션"
        else:
            sig = "알트시즌"
        print(f"{row['date']:>12}  {btcd:>6.1f}%  {sig:>10}")
    print()


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="BTC 도미넌스 일봉 수집")
    ap.add_argument("--update", action="store_true",
                    help="기존 데이터에 최신분만 추가 (기본: 전체 재수집)")
    ap.add_argument("--show", action="store_true",
                    help="저장된 최근 30일 BTC.D 출력")
    args = ap.parse_args()

    if args.show and os.path.exists(SAVE_PATH):
        df = pd.read_csv(SAVE_PATH)
        print_recent(df)
        return

    df = build_dominance(update_only=args.update)
    save(df)
    print_recent(df)


if __name__ == "__main__":
    main()
