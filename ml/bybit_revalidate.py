"""
ml/bybit_revalidate.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
바이빗 실거래소 데이터로 규칙 재검증 — 바이낸스 현물 결과와 직접 대조

왜 필요한가:
  지금까지의 모든 백테스트는 data.binance.vision의 바이낸스 **현물**
  캔들을 썼다. 실거래는 바이빗 **USDT 무기한 선물**에서 돌 예정이라
  격차가 두 겹이다.

      종가        차익거래로 묶여 있어 평상시 0.05% 이내. 영향 작음.
      고가/저가   선물은 청산 캐스케이드로 꼬리가 길다. 손절 체결이 갈린다.
      거래량      현물과 선물은 참여자가 다른 별개 시장. 비교 불가.
      펀딩비      현물엔 없는 비용. 40시간 보유 = 5회 정산.
      상장시점    2017~2020 알트는 바이빗 선물에 아예 없다.

  이 스크립트는 두 데이터셋에서 같은 규칙을 돌려 승률·수익이
  얼마나 벌어지는지, 그리고 **같은 시점에 같은 신호가 뜨는지**를 센다.
  신호 일치율이 낮으면 승률이 비슷해도 다른 전략이라는 뜻이다.

사용법:
    python ml/bybit_revalidate.py                 # 전체 규칙
    python ml/bybit_revalidate.py --rule 1        # 1번만
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, sys, glob, argparse, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ROUND_TRIP = 0.002
FUNDING_PER_8H = 0.0001      # 실측 중앙값 ~0.01%/8h. 롱은 지불, 숏은 수취.
BAR_HOURS = {"4h": 4, "1d": 24, "1h": 1}

# (이름, 인터벌, 피처, 연산자, 임계값, 보유봉수, 방향)
RULES = [
    ("R1  4h 20MA 이격 -12.3%", "4h", "vs_ma20",   "<=", -12.26, 10, "LONG"),
    ("R2  4h 50MA 이격 -19.4%", "4h", "vs_ma50",   "<=", -19.37, 10, "LONG"),
    ("R3  1d 20MA 이격 -20.3%", "1d", "vs_ma20",   "<=", -20.32,  5, "LONG"),
    ("R4  1d RSI14 <= 22.7",    "1d", "rsi14",     "<=",  22.69,  5, "LONG"),
    ("R5  1d 저거래량 숏",       "1d", "vol_ratio", "<=",  0.3881, 10, "SHORT"),
]


def load(pattern: str, tag: str) -> pd.DataFrame:
    frames = []
    for f in sorted(glob.glob(pattern)):
        base = os.path.basename(f)
        sym = base.split("_")[0]
        if not sym.endswith("USDT"):
            continue
        try:
            d = pd.read_csv(f, compression="gzip")
        except Exception:
            continue
        tc = "timestamp" if "timestamp" in d.columns else "datetime"
        if tc not in d.columns:
            continue
        d[tc] = pd.to_datetime(d[tc], format="mixed", errors="coerce")
        d = d.dropna(subset=[tc]).sort_values(tc).drop_duplicates(tc)
        if len(d) < 250:
            continue
        d = d.rename(columns={tc: "datetime"})
        d["symbol"] = sym
        d["src"] = tag
        frames.append(d[["datetime", "symbol", "src", "open", "high", "low", "close", "volume"]])
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def features(d: pd.DataFrame, hold: int) -> pd.DataFrame:
    out = []
    for sym, g in d.groupby("symbol", sort=False):
        g = g.sort_values("datetime").reset_index(drop=True)
        c, v = g["close"], g["volume"]
        g["vs_ma20"] = (c / c.rolling(20).mean() - 1) * 100
        g["vs_ma50"] = (c / c.rolling(50).mean() - 1) * 100
        delta = c.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        g["rsi14"] = 100 - 100 / (1 + gain / (loss + 1e-12))
        g["vol_ratio"] = v / v.rolling(20).mean()
        g["entry"] = g["open"].shift(-1)
        g["exit"] = g["open"].shift(-1 - hold)
        g["gross"] = (g["exit"] / g["entry"] - 1) * 100
        out.append(g)
    return pd.concat(out, ignore_index=True)


def wilson_lo(w: int, n: int, z: float = 1.96) -> float:
    if n == 0: return 0.0
    p = w / n; den = 1 + z*z/n; ctr = p + z*z/(2*n)
    mar = z * np.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return (ctr - mar) / den * 100


def evaluate(df, feat, op, thr, hold, side, interval, apply_funding=True):
    m = (df[feat] <= thr) if op == "<=" else (df[feat] >= thr)
    sub = df[m].dropna(subset=["gross"]).copy()
    if sub.empty:
        return None, sub
    pnl = sub["gross"] if side == "LONG" else -sub["gross"]
    pnl = pnl - ROUND_TRIP * 100
    if apply_funding:
        periods = hold * BAR_HOURS.get(interval, 24) / 8.0
        fee = FUNDING_PER_8H * periods * 100
        pnl = pnl - fee if side == "LONG" else pnl + fee   # 숏은 펀딩 수취
    sub["pnl"] = pnl
    n = len(pnl); w = int((pnl > 0).sum())
    return {"n": n, "wr": w/n*100, "lo": wilson_lo(w, n), "mean": pnl.mean(),
            "worst": pnl.min(), "syms": sub["symbol"].nunique(),
            "start": sub["datetime"].min(), "end": sub["datetime"].max()}, sub


def signal_overlap(sub_a, sub_b):
    """같은 (종목, 시점)에 양쪽 다 신호가 떴는가 — 승률이 비슷해도 다른 전략일 수 있다"""
    if sub_a.empty or sub_b.empty:
        return None
    ka = set(zip(sub_a["symbol"], sub_a["datetime"]))
    kb = set(zip(sub_b["symbol"], sub_b["datetime"]))
    inter = ka & kb
    # 바이빗에 존재하는 (종목,시점)만 분모로 — 상장 이전 구간은 불일치가 아니라 부재
    span = sub_b["datetime"].min()
    ka_in = {k for k in ka if k[1] >= span and k[0] in set(sub_b["symbol"])}
    return {"바이낸스": len(ka), "바이빗": len(kb), "공통": len(inter),
            "일치율": len(inter) / max(len(ka_in), 1) * 100}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rule", type=int, default=None)
    ap.add_argument("--no-funding", action="store_true")
    a = ap.parse_args()

    if not glob.glob("data/bybit/*.csv.gz"):
        print("=" * 96)
        print("  data/bybit/ 가 비어 있다.")
        print("  이 세션 프록시는 api.bybit.com을 포함한 모든 거래소 도메인을 차단한다.")
        print("  GitHub Actions의 '📡 바이빗 실거래소 데이터 수집' 워크플로를 먼저 돌려야 한다.")
        print("=" * 96)
        return

    todo = RULES if a.rule is None else [RULES[a.rule - 1]]
    print("=" * 100)
    print("  바이낸스 현물 vs 바이빗 무기한선물 — 같은 규칙, 두 데이터")
    print(f"  비용 왕복 {ROUND_TRIP*100:.1f}%" +
          ("" if a.no_funding else f" + 펀딩 {FUNDING_PER_8H*100:.2f}%/8h (롱 지불·숏 수취)"))
    print("=" * 100)

    for name, iv, feat, op, thr, hold, side in todo:
        bn = load(f"data/*_{iv}_all.csv.gz", "binance")
        by = load(f"data/bybit/*_{iv}.csv.gz", "bybit")
        print(f"\n{'─'*100}\n  {name}   [{side}, {hold}봉 보유]\n{'─'*100}")
        if by.empty:
            print(f"    바이빗 {iv} 데이터 없음 — 수집 워크플로에서 이 인터벌을 받아야 한다")
            continue

        res = {}
        subs = {}
        for tag, raw in (("바이낸스 현물", bn), ("바이빗 선물", by)):
            if raw.empty:
                continue
            r, sub = evaluate(features(raw, hold), feat, op, thr, hold, side, iv,
                              apply_funding=not a.no_funding)
            res[tag], subs[tag] = r, sub

        # 바이빗 구간에 맞춰 바이낸스를 잘라 동일 기간으로도 비교
        if "바이빗 선물" in res and res["바이빗 선물"]:
            lo_dt = res["바이빗 선물"]["start"]
            bn_f = features(bn, hold)
            bn_f = bn_f[bn_f["datetime"] >= lo_dt]
            r2, _ = evaluate(bn_f, feat, op, thr, hold, side, iv,
                             apply_funding=not a.no_funding)
            if r2: res["바이낸스(동일기간)"] = r2

        print(f"    {'데이터':20s}{'n':>8s}{'승률':>8s}{'하한':>8s}{'거래당':>9s}"
              f"{'최악':>9s}{'종목':>6s}   기간")
        for tag in ("바이낸스 현물", "바이낸스(동일기간)", "바이빗 선물"):
            r = res.get(tag)
            if not r: continue
            print(f"    {tag:20s}{r['n']:>8,}{r['wr']:>7.1f}%{r['lo']:>7.1f}%"
                  f"{r['mean']:>+8.2f}%{r['worst']:>+8.1f}%{r['syms']:>6d}   "
                  f"{str(r['start'])[:10]}~{str(r['end'])[:10]}")

        if len(subs) == 2:
            ov = signal_overlap(subs["바이낸스 현물"], subs["바이빗 선물"])
            if ov:
                print(f"\n    신호 일치: 바이빗 상장 이후 구간에서 바이낸스 신호의 "
                      f"{ov['일치율']:.1f}%가 바이빗에서도 떴다 "
                      f"(공통 {ov['공통']:,} / 바이낸스 {ov['바이낸스']:,} / 바이빗 {ov['바이빗']:,})")
                if ov["일치율"] < 80:
                    print(f"    ⚠️ 일치율 80% 미만 — 승률이 비슷해도 같은 전략이 아니다")

        rb, rn = res.get("바이빗 선물"), res.get("바이낸스(동일기간)")
        if rb and rn:
            d_wr, d_mu = rb["wr"] - rn["wr"], rb["mean"] - rn["mean"]
            verdict = ("이식 가능" if abs(d_wr) < 3 and d_mu > 0 else
                       "주의 — 차이 큼" if abs(d_wr) >= 5 else "경미한 차이")
            print(f"    동일기간 대비: 승률 {d_wr:+.1f}%p, 거래당 {d_mu:+.2f}%p  →  {verdict}")


if __name__ == "__main__":
    main()
