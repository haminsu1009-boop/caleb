"""
bybit/live_trader.py
Bybit 실시간 자동매매 봇 (USDT 영구선물 - 롱/숏 모두 가능)

사용법:
    python bybit/live_trader.py             # 실거래 (주의!)
    python bybit/live_trader.py --paper     # 페이퍼 트레이딩 (가상 거래)
    python bybit/live_trader.py --paper --interval 5

.env 필수 설정:
    BYBIT_API_KEY=...
    BYBIT_SECRET=...
    BYBIT_TESTNET=false
    TRADING_SYMBOL=BTCUSDT
    TRADING_LEVERAGE=1
    TRADE_USDT=10
    CANDLE_INTERVAL=5
"""

import os, sys, time, json, pickle, argparse
from datetime import datetime

import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from pybit.unified_trading import HTTP
from ml.features import add_features, get_feature_cols
from ml.signal_filter import top_percentile_signals
from bybit.collect_bybit import fetch_latest


# ── 설정 ────────────────────────────────────────────────
SYMBOL    = os.getenv("TRADING_SYMBOL", "BTCUSDT")
LEVERAGE  = int(os.getenv("TRADING_LEVERAGE", "1"))
TRADE_AMT = float(os.getenv("TRADE_USDT", "10"))    # 건당 투자 USDT
INTERVAL  = os.getenv("CANDLE_INTERVAL", "5")
TESTNET   = os.getenv("BYBIT_TESTNET", "false").lower() == "true"

MODEL_PATH = "ml/saved_models/directional_model.pkl"
THR_PATH   = "ml/saved_models/directional_thresholds.json"

# 신호 설정
SIGNAL_PCT = 10.0   # 상위 10% 신호 (분봉은 일봉보다 완화)
MIN_THR    = 0.58


def load_model():
    with open(MODEL_PATH, "rb") as f:
        saved = pickle.load(f)
    with open(THR_PATH) as f:
        thr = json.load(f)
    return saved["model"], saved["feature_cols"], thr


def prepare_df(raw: pd.DataFrame) -> pd.DataFrame:
    """Bybit 캔들 → features.py 호환 포맷으로 변환"""
    df = raw.copy()
    df = df.rename(columns={"timestamp": "date"})
    df["date"] = df["date"].astype(str)
    # add_features 는 open 컬럼 필요
    if "open" not in df.columns and "open" not in df.columns:
        df["open"] = df["close"].shift(1).fillna(df["close"])
    df = df[["date","open","high","low","close","volume"]].copy()
    return df


def get_signal(model, feat_cols) -> dict:
    """
    최신 캔들 가져와서 ML 신호 계산
    Returns: {"action": "LONG"|"SHORT"|"NONE", "long_prob": float, "short_prob": float}
    """
    raw = fetch_latest(SYMBOL, INTERVAL, n=300)
    if raw.empty or len(raw) < 50:
        return {"action": "NONE", "long_prob": 0, "short_prob": 0}

    df = prepare_df(raw)
    df = add_features(df)

    fc = [c for c in feat_cols if c in df.columns]
    X  = df[fc].fillna(0)

    lp = model.predict_proba_long(X)
    sp = model.predict_proba_short(X)

    # regime (없으면 모두 1=neutral)
    regime = df["regime"].fillna(1).values if "regime" in df.columns else np.ones(len(df))

    long_sig, short_sig = top_percentile_signals(
        lp, sp, regime=regime, pct=SIGNAL_PCT, min_thr=MIN_THR
    )

    # 마지막 캔들 (현재 완성된 캔들)
    last = -2   # -1은 진행중 캔들, -2는 완성된 마지막 캔들

    action = "NONE"
    if long_sig[last]:
        action = "LONG"
    elif short_sig[last]:
        action = "SHORT"

    return {
        "action":     action,
        "long_prob":  round(float(lp[last]), 4),
        "short_prob": round(float(sp[last]), 4),
        "close":      float(df["close"].iloc[last]),
        "time":       df["date"].iloc[last],
    }


# ── Bybit 주문 함수 ──────────────────────────────────────
class BybitTrader:
    def __init__(self, paper: bool = False):
        self.paper    = paper
        self.position = None   # "LONG" | "SHORT" | None
        self.entry_px = 0.0
        self.qty      = 0.0
        self.pnl_log  = []

        if not paper:
            self.session = HTTP(
                testnet   = TESTNET,
                api_key   = os.getenv("BYBIT_API_KEY"),
                api_secret= os.getenv("BYBIT_SECRET"),
            )
            self._set_leverage()
        else:
            self.session = None
            print("📝 페이퍼 트레이딩 모드 (실제 주문 없음)")

    def _set_leverage(self):
        try:
            self.session.set_leverage(
                category="linear", symbol=SYMBOL,
                buyLeverage=str(LEVERAGE), sellLeverage=str(LEVERAGE)
            )
        except Exception as e:
            print(f"  레버리지 설정: {e}")

    def get_price(self) -> float:
        if self.paper:
            # 페이퍼: fetch_latest 에서 마지막 가격
            raw = fetch_latest(SYMBOL, INTERVAL, n=3)
            return float(raw["close"].iloc[-1]) if not raw.empty else 0.0
        resp = self.session.get_tickers(category="linear", symbol=SYMBOL)
        return float(resp["result"]["list"][0]["lastPrice"])

    def get_position(self) -> dict | None:
        """현재 포지션 조회"""
        if self.paper:
            return {"side": self.position, "size": self.qty, "avgPrice": self.entry_px} if self.position else None
        try:
            resp = self.session.get_positions(category="linear", symbol=SYMBOL)
            pos  = resp["result"]["list"]
            for p in pos:
                if float(p["size"]) > 0:
                    return {"side": p["side"], "size": float(p["size"]), "avgPrice": float(p["avgPrice"])}
        except Exception as e:
            print(f"  포지션 조회 실패: {e}")
        return None

    def open_long(self, price: float):
        qty = round(TRADE_AMT * LEVERAGE / price, 3)
        if self.paper:
            self.position = "LONG"; self.entry_px = price; self.qty = qty
            print(f"  📗 [PAPER LONG] qty={qty} @ ${price:,.1f}")
            return
        try:
            r = self.session.place_order(
                category="linear", symbol=SYMBOL,
                side="Buy", orderType="Market",
                qty=str(qty), timeInForce="IOC"
            )
            print(f"  📗 LONG 주문: {r['result']}")
        except Exception as e:
            print(f"  ❌ LONG 주문 실패: {e}")

    def open_short(self, price: float):
        qty = round(TRADE_AMT * LEVERAGE / price, 3)
        if self.paper:
            self.position = "SHORT"; self.entry_px = price; self.qty = qty
            print(f"  📕 [PAPER SHORT] qty={qty} @ ${price:,.1f}")
            return
        try:
            r = self.session.place_order(
                category="linear", symbol=SYMBOL,
                side="Sell", orderType="Market",
                qty=str(qty), timeInForce="IOC"
            )
            print(f"  📕 SHORT 주문: {r['result']}")
        except Exception as e:
            print(f"  ❌ SHORT 주문 실패: {e}")

    def close_position(self, price: float):
        pos = self.get_position()
        if not pos:
            return

        side  = pos["side"] if not self.paper else self.position
        entry = pos["avgPrice"] if not self.paper else self.entry_px
        qty   = pos["size"]   if not self.paper else self.qty

        if self.paper:
            if self.position == "LONG":
                pnl_pct = (price - entry) / entry * 100
            else:
                pnl_pct = (entry - price) / entry * 100
            pnl_usdt = TRADE_AMT * pnl_pct / 100
            self.pnl_log.append({"time": datetime.utcnow(), "pnl_pct": pnl_pct, "pnl_usdt": pnl_usdt})
            emoji = "✅" if pnl_pct > 0 else "❌"
            print(f"  {emoji} [PAPER CLOSE] {self.position}  PnL: {pnl_pct:+.2f}% (${pnl_usdt:+.2f})")
            self.position = None; self.entry_px = 0; self.qty = 0
            return

        close_side = "Sell" if side == "Buy" else "Buy"
        try:
            r = self.session.place_order(
                category="linear", symbol=SYMBOL,
                side=close_side, orderType="Market",
                qty=str(qty), reduceOnly=True, timeInForce="IOC"
            )
            print(f"  🔒 포지션 종료: {r['result']}")
        except Exception as e:
            print(f"  ❌ 종료 실패: {e}")


# ── 메인 루프 ────────────────────────────────────────────
def run_bot(paper: bool = False, interval_min: int = 5):
    print("=" * 56)
    print(f"🤖 AI 트레이딩 봇 시작")
    print(f"   심볼: {SYMBOL}  캔들: {interval_min}분봉  레버리지: {LEVERAGE}x")
    print(f"   건당 투자: ${TRADE_AMT} USDT  모드: {'📝 페이퍼' if paper else '💰 실거래'}")
    print("=" * 56)

    model, feat_cols, thr = load_model()
    trader = BybitTrader(paper=paper)
    prev_action = None

    while True:
        try:
            now = datetime.utcnow()
            sig = get_signal(model, feat_cols)
            price = sig.get("close", trader.get_price())

            print(f"\n[{now.strftime('%H:%M:%S')}] {SYMBOL} ${price:,.1f}")
            print(f"  신호: {sig['action']}  장P={sig['long_prob']:.3f}  숏P={sig['short_prob']:.3f}")

            pos = trader.get_position()
            action = sig["action"]

            # 포지션 변경 필요할 때만 주문
            if pos is None:
                if action == "LONG":
                    trader.open_long(price)
                elif action == "SHORT":
                    trader.open_short(price)
            else:
                cur_side = pos["side"] if not paper else trader.position
                # 반대 신호 → 포지션 종료 후 새 방향 진입
                if action == "LONG" and cur_side in ("SHORT", "Sell"):
                    trader.close_position(price)
                    time.sleep(1)
                    trader.open_long(price)
                elif action == "SHORT" and cur_side in ("LONG", "Buy"):
                    trader.close_position(price)
                    time.sleep(1)
                    trader.open_short(price)
                elif action == "NONE":
                    # 신호 없으면 기존 포지션 유지 (홀드)
                    print(f"  ⏸  포지션 유지 ({cur_side})")

            # 페이퍼 트레이딩 누적 PnL 출력
            if paper and trader.pnl_log:
                total = sum(p["pnl_usdt"] for p in trader.pnl_log)
                wr    = sum(1 for p in trader.pnl_log if p["pnl_pct"] > 0) / len(trader.pnl_log)
                print(f"  📊 누적 PnL: ${total:+.2f}  승률: {wr*100:.1f}%  ({len(trader.pnl_log)}건)")

            # 다음 봉 시작까지 대기
            sleep_sec = interval_min * 60
            print(f"  ⏰ {sleep_sec // 60}분 후 다시 확인...")
            time.sleep(sleep_sec)

        except KeyboardInterrupt:
            print("\n\n⏹  봇 종료")
            if paper and trader.pnl_log:
                total = sum(p["pnl_usdt"] for p in trader.pnl_log)
                print(f"\n📋 최종 성과: ${total:+.2f} USDT  ({len(trader.pnl_log)}건)")
            break
        except Exception as e:
            print(f"  ⚠️  오류: {e}")
            time.sleep(30)


# ── CLI ─────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper",    action="store_true", help="페이퍼 트레이딩")
    parser.add_argument("--interval", type=int, default=int(INTERVAL))
    args = parser.parse_args()

    run_bot(paper=args.paper, interval_min=args.interval)
