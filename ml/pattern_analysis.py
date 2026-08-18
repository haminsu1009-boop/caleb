"""
ml/pattern_analysis.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
최적 승률 패턴 탐색기

1. 모든 심볼 × 봉단위의 trades_*.csv 로드
2. OHLCV + 245-feature 계산
3. 결정트리 룰 마이닝 → 승률 90%+ 조건 추출
4. HTML 보고서 생성
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os, sys, glob, warnings, pickle
import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeClassifier, export_text
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

warnings.filterwarnings("ignore")

ROOT      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR  = os.path.join(ROOT, "data")
MODEL_DIR = os.path.join(ROOT, "ml", "saved_models")
CHART_DIR = os.path.join(ROOT, "charts")
os.makedirs(CHART_DIR, exist_ok=True)

sys.path.insert(0, ROOT)
from ml.train_directional import load_ohlcv, add_features, merge_indicators, load_indicators

SYMBOLS   = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "SOLUSDT", "XRPUSDT"]
INTERVALS = ["5m", "1h", "4h", "1d"]

HORIZON_MAP = {"1m": 30, "5m": 12, "1h": 12, "4h": 6, "1d": 2}

# ──────────────────────────────────────────────────────
# 핵심 피처: 패턴 분석에 사용할 해석 가능한 지표 컬럼명
# ──────────────────────────────────────────────────────
PATTERN_FEATS = [
    # RSI
    "rsi_6", "rsi_14", "rsi_21",
    "rsi_14_slope", "rsi_div_bull", "rsi_div_bear",
    # MACD
    "macd_12_26", "macd_12_26_hist", "macd_12_26_cross_up", "macd_12_26_cross_dn",
    "macd_5_13_hist",
    # 볼린저
    "bb_pos_20", "bb_width_20", "bb_squeeze_20", "bb_upper_20", "bb_lower_20",
    # 켈트너
    "kc_pos_15", "kc_pos_20", "squeeze_kc",
    # 스토캐스틱
    "stoch_k_14", "stoch_d_14", "stoch_os_14", "stoch_ob_14",
    # ADX
    "adx", "di_diff", "adx_trending",
    # ATR
    "atr", "atr_ratio",
    # CCI
    "cci_14", "cci_20",
    # Williams %R
    "willr_14",
    # 이치모쿠
    "ichi_tk", "ichi_above_cloud", "ichi_below_cloud", "ichi_cloud_bull",
    "ichi_tk_cross_up", "ichi_tk_cross_dn",
    # EMA
    "ema9_vs_21", "ema21_vs_55", "ema50_vs_200",
    # MFI / CMF
    "mfi_14", "mfi_os_14", "mfi_ob_14", "cmf_14",
    # 거래량
    "vol_ratio_12", "vol_ratio_24", "vol_burst", "obv_slope",
    # VWAP
    "vwap_pos_48",
    # 캔들 패턴
    "hammer", "shooting_star", "engulf_bull", "engulf_bear",
    "pinbar_bull", "pinbar_bear", "doji", "morning_star", "evening_star",
    "marubozu_bull", "marubozu_bear", "inside_bar",
    # 차트 구조
    "near_high", "near_low",
    "vs_sma24", "vs_sma96",
    # 세션 / 시간
    "hour", "dow",
    # 수익률 / 모멘텀
    "ret_5", "ret_12", "ret_48",
    # ROC
    "roc_9", "roc_14",
    # Aroon
    "aroon_14",
    # SAR
    "sar_bull", "sar_bear",
]


def make_session_feats(df: pd.DataFrame) -> pd.DataFrame:
    """시간 기반 피처 추가"""
    df = df.copy()
    if hasattr(df["datetime"], "dt"):
        df["hour"] = df["datetime"].dt.hour
        df["dow"]  = df["datetime"].dt.dayofweek
    return df


def load_all_trades() -> pd.DataFrame:
    """모든 trades_*.csv 로드 후 통합"""
    rows = []
    for sym in SYMBOLS:
        for ivl in INTERVALS:
            path = os.path.join(MODEL_DIR, f"trades_{sym}_{ivl}.csv")
            if not os.path.exists(path):
                continue
            df = pd.read_csv(path)
            df["symbol"]   = sym
            df["interval"] = ivl
            df["entry_time"] = pd.to_datetime(df["entry_time"])
            rows.append(df)
    if not rows:
        raise FileNotFoundError("trades_*.csv 없음")
    return pd.concat(rows, ignore_index=True)


def build_feature_db(sym: str, ivl: str, from_year: int = 2022) -> pd.DataFrame:
    """심볼 × 봉단위 피처 DB 생성"""
    try:
        df = load_ohlcv(sym, ivl, from_year=from_year)
    except Exception as e:
        print(f"  OHLCV 로드 실패 {sym} {ivl}: {e}")
        return None
    ind = load_indicators()
    if ind:
        df = merge_indicators(df, ind)
    df = add_features(df)
    df = make_session_feats(df)
    df = df.set_index("datetime")
    return df


def attach_features(trades: pd.DataFrame, feat_db: pd.DataFrame,
                    sym: str, ivl: str) -> pd.DataFrame:
    """trades 행에 entry_time 기준 피처 붙이기"""
    sub = trades[(trades.symbol == sym) & (trades.interval == ivl)].copy()
    if sub.empty:
        return sub
    sub = sub.set_index("entry_time")
    # 각 entry_time과 가장 가까운 이전 OHLCV 행 병합 (asof merge)
    idx_sorted = feat_db.index.sort_values()
    feat_sub   = feat_db.reindex(idx_sorted)
    avail_cols = [c for c in PATTERN_FEATS if c in feat_sub.columns]
    result_rows = []
    for et, row in sub.iterrows():
        # entry_time 이하의 최근 피처 찾기
        pos = feat_sub.index.searchsorted(et, side="right") - 1
        if pos < 0:
            continue
        feat_row = feat_sub.iloc[pos][avail_cols].to_dict()
        combined = {**row.to_dict(), **feat_row, "entry_time": et}
        result_rows.append(combined)
    return pd.DataFrame(result_rows)


# ══════════════════════════════════════════════════════
# 1. 결정트리 룰 마이닝
# ══════════════════════════════════════════════════════

def mine_rules(df: pd.DataFrame, direction: str = "LONG",
               min_wr: float = 0.72, min_n: int = 30) -> list:
    """
    결정트리 기반 고승률 룰 추출.
    Returns: list of dicts {rule, win_rate, count, lift}
    """
    sub = df[df["direction"] == direction].copy()
    if len(sub) < 100:
        return []

    feat_cols = list(dict.fromkeys(c for c in PATTERN_FEATS if c in sub.columns))
    X = sub[feat_cols].replace([np.inf, -np.inf], np.nan).fillna(0)
    y = sub["win"].astype(int)

    baseline_wr = y.mean()

    tree = DecisionTreeClassifier(
        max_depth=4,
        min_samples_leaf=min_n,
        min_impurity_decrease=0.001,
        random_state=42,
    )
    tree.fit(X, y)

    # 각 리프 노드의 win_rate 계산
    leaf_ids = tree.apply(X)
    rules = []
    for leaf in np.unique(leaf_ids):
        mask  = leaf_ids == leaf
        n     = mask.sum()
        wr    = y[mask].mean()
        if wr >= min_wr and n >= min_n:
            # 리프로 가는 규칙 텍스트
            rule_str = _leaf_rule(tree, feat_cols, leaf, X)
            rules.append({
                "direction": direction,
                "rule":      rule_str,
                "win_rate":  round(wr * 100, 1),
                "count":     int(n),
                "lift":      round(wr / (baseline_wr + 1e-9), 2),
                "baseline_wr": round(baseline_wr * 100, 1),
            })
    rules.sort(key=lambda x: -x["win_rate"])
    return rules


def _leaf_rule(tree, feat_cols: list, leaf_id: int, X: pd.DataFrame) -> str:
    """특정 리프 노드에 해당하는 조건 텍스트 생성"""
    t     = tree.tree_
    n_nodes = t.node_count
    left    = t.children_left
    right   = t.children_right
    feat    = t.feature
    thr     = t.threshold

    # 리프까지의 경로 추적
    def find_path(node, target, path):
        if node == target:
            return path
        if left[node] != -1:
            p = find_path(left[node], target, path + [(node, "left")])
            if p:
                return p
        if right[node] != -1:
            p = find_path(right[node], target, path + [(node, "right")])
            if p:
                return p
        return None

    path = find_path(0, leaf_id, [])
    if not path:
        return "(경로 추적 불가)"

    conds = []
    for (node, direction) in path:
        fname = feat_cols[feat[node]] if feat[node] >= 0 else "?"
        val   = round(thr[node], 4)
        if direction == "left":
            conds.append(f"{fname} ≤ {val}")
        else:
            conds.append(f"{fname} > {val}")
    return " AND ".join(conds)


# ══════════════════════════════════════════════════════
# 2. 피처 중요도 (RandomForest)
# ══════════════════════════════════════════════════════

def top_features(df: pd.DataFrame, direction: str = "LONG", top_n: int = 20) -> pd.DataFrame:
    sub = df[df["direction"] == direction].copy()
    if len(sub) < 100:
        return pd.DataFrame()
    feat_cols = list(dict.fromkeys(c for c in PATTERN_FEATS if c in sub.columns))
    X = sub[feat_cols].replace([np.inf, -np.inf], np.nan).fillna(0)
    y = sub["win"].astype(int)
    rf = RandomForestClassifier(n_estimators=100, max_depth=5,
                                n_jobs=-1, random_state=42)
    rf.fit(X, y)
    imp = pd.DataFrame({"feature": feat_cols,
                        "importance": rf.feature_importances_})
    return imp.sort_values("importance", ascending=False).head(top_n)


# ══════════════════════════════════════════════════════
# 3. 지표별 분위 승률 분석
# ══════════════════════════════════════════════════════

def quantile_winrate(df: pd.DataFrame, feat: str,
                     direction: str = "LONG", q: int = 5) -> pd.DataFrame:
    sub = df[(df["direction"] == direction) & df[feat].notna()].copy()
    if len(sub) < 50 or feat not in sub.columns:
        return pd.DataFrame()
    try:
        sub["bin"] = pd.qcut(sub[feat], q=q, duplicates="drop", labels=False)
    except Exception:
        return pd.DataFrame()
    res = sub.groupby("bin")["win"].agg(["mean", "count"]).reset_index()
    res.columns = ["quantile", "win_rate", "count"]
    res["win_rate"] *= 100
    res["feat"] = feat
    # 각 분위의 값 범위 레이블
    try:
        cuts = pd.qcut(sub[feat], q=q, duplicates="drop", retbins=True)[1]
        res["range"] = [f"{cuts[i]:.3f}~{cuts[i+1]:.3f}"
                        for i in range(len(res))]
    except Exception:
        res["range"] = res["quantile"].astype(str)
    return res


# ══════════════════════════════════════════════════════
# 4. 심볼 × 봉단위 전체 분석
# ══════════════════════════════════════════════════════

def analyze_all():
    print("=" * 60)
    print("  최적 승률 패턴 분석 시작")
    print("=" * 60)

    trades_all = load_all_trades()
    print(f"\n  총 거래: {len(trades_all):,}건  "
          f"(심볼 {trades_all.symbol.nunique()}개 × "
          f"봉단위 {trades_all.interval.nunique()}개)")

    results = {}  # {(sym, ivl): {trades_with_feats, rules_L, rules_S, top_feats}}

    for sym in SYMBOLS:
        for ivl in INTERVALS:
            sub = trades_all[(trades_all.symbol == sym) &
                             (trades_all.interval == ivl)]
            if len(sub) < 50:
                continue

            print(f"\n── {sym} {ivl}  ({len(sub)}건) ──────────────────")
            from_yr = 2022
            if ivl == "1m":
                from_yr = 2023
            feat_db = build_feature_db(sym, ivl, from_year=from_yr)
            if feat_db is None:
                continue

            merged = attach_features(trades_all, feat_db, sym, ivl)
            if merged.empty:
                continue

            wr_base = merged["win"].mean()
            print(f"  기본 승률: {wr_base*100:.1f}%  "
                  f"LONG:{(merged[merged.direction=='LONG']['win'].mean()*100):.1f}%  "
                  f"SHORT:{(merged[merged.direction=='SHORT']['win'].mean()*100):.1f}%")

            rules_L = mine_rules(merged, "LONG",  min_wr=0.70)
            rules_S = mine_rules(merged, "SHORT", min_wr=0.70)
            top_L   = top_features(merged, "LONG")
            top_S   = top_features(merged, "SHORT")

            print(f"  LONG 고승률 룰: {len(rules_L)}개")
            for r in rules_L[:3]:
                print(f"    [{r['win_rate']}% / n={r['count']}] {r['rule'][:80]}")
            print(f"  SHORT 고승률 룰: {len(rules_S)}개")
            for r in rules_S[:3]:
                print(f"    [{r['win_rate']}% / n={r['count']}] {r['rule'][:80]}")

            results[(sym, ivl)] = {
                "merged":  merged,
                "rules_L": rules_L,
                "rules_S": rules_S,
                "top_L":   top_L,
                "top_S":   top_S,
                "n":       len(merged),
                "wr":      wr_base,
            }

    return results, trades_all


# ══════════════════════════════════════════════════════
# 5. HTML 보고서 생성
# ══════════════════════════════════════════════════════

def _rule_row(r: dict, color: str) -> str:
    bar_w = min(int(r["win_rate"]), 100)
    return f"""
<tr>
  <td style="text-align:center">
    <span class="badge" style="background:{color}">{r['win_rate']}%</span>
  </td>
  <td style="text-align:center">{r['count']}</td>
  <td style="text-align:center">{r['lift']}x</td>
  <td style="font-family:monospace;font-size:0.78rem">{r['rule']}</td>
  <td>
    <div class="bar-bg">
      <div class="bar-fill" style="width:{bar_w}%;background:{color}"></div>
    </div>
  </td>
</tr>"""


def build_html(results: dict) -> str:
    # 요약 카드
    summary_rows = ""
    for (sym, ivl), v in sorted(results.items()):
        wr_pct = round(v["wr"] * 100, 1)
        n_L = len(v["rules_L"])
        n_S = len(v["rules_S"])
        bg  = "#1a472a" if wr_pct >= 75 else ("#1a3a5c" if wr_pct >= 65 else "#3a1a1a")
        summary_rows += f"""
<tr style="background:{bg}22">
  <td><b>{sym}</b></td>
  <td style="text-align:center">{ivl}</td>
  <td style="text-align:center">{v['n']:,}</td>
  <td style="text-align:center">
    <span class="badge" style="background:{'#27ae60' if wr_pct>=75 else '#e67e22' if wr_pct>=65 else '#e74c3c'}">{wr_pct}%</span>
  </td>
  <td style="text-align:center">{n_L}</td>
  <td style="text-align:center">{n_S}</td>
</tr>"""

    # 상세 섹션
    detail_sections = ""
    for (sym, ivl), v in sorted(results.items()):
        if not v["rules_L"] and not v["rules_S"]:
            continue
        long_rows  = "".join(_rule_row(r, "#27ae60") for r in v["rules_L"][:8])
        short_rows = "".join(_rule_row(r, "#e74c3c") for r in v["rules_S"][:8])

        # 피처 중요도 바
        feat_bars = ""
        if not v["top_L"].empty:
            max_imp = v["top_L"]["importance"].max()
            for _, row in v["top_L"].head(10).iterrows():
                pct = int(row["importance"] / max_imp * 100)
                feat_bars += f"""
<div class="feat-row">
  <span class="feat-name">{row['feature']}</span>
  <div class="bar-bg" style="flex:1">
    <div class="bar-fill" style="width:{pct}%;background:#3498db"></div>
  </div>
  <span class="feat-val">{row['importance']:.4f}</span>
</div>"""

        detail_sections += f"""
<div class="section">
  <h2 class="sym-header">
    <span class="sym-tag">{sym}</span>
    <span class="ivl-tag">{ivl}</span>
    <span class="wr-tag">기본 승률 {v['wr']*100:.1f}%</span>
    <span class="cnt-tag">{v['n']:,}건</span>
  </h2>

  <div class="two-col">
    <div>
      <h3 class="long-h3">🟢 LONG 고승률 조건</h3>
      {"<p style='color:#888'>없음</p>" if not long_rows else f'''
      <table class="rule-tbl">
        <thead><tr><th>승률</th><th>샘플수</th><th>리프트</th><th>조건</th><th>바</th></tr></thead>
        <tbody>{long_rows}</tbody>
      </table>'''}
    </div>
    <div>
      <h3 class="short-h3">🔴 SHORT 고승률 조건</h3>
      {"<p style='color:#888'>없음</p>" if not short_rows else f'''
      <table class="rule-tbl">
        <thead><tr><th>승률</th><th>샘플수</th><th>리프트</th><th>조건</th><th>바</th></tr></thead>
        <tbody>{short_rows}</tbody>
      </table>'''}
    </div>
  </div>

  <details>
    <summary class="feat-summary">📊 LONG 피처 중요도 Top 10</summary>
    <div class="feat-list">{feat_bars or "<p style='color:#888'>없음</p>"}</div>
  </details>
</div>"""

    html = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>최적 승률 패턴 분석</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Noto+Sans+KR:wght@400;700;900&display=swap">
<style>
  :root {{
    --bg:      #0d1117;
    --bg2:     #161b22;
    --bg3:     #21262d;
    --border:  #30363d;
    --text:    #e6edf3;
    --muted:   #8b949e;
    --accent:  #58a6ff;
    --green:   #3fb950;
    --red:     #f85149;
    --yellow:  #d29922;
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{
    background:var(--bg); color:var(--text);
    font-family:'Noto Sans KR',sans-serif;
    font-size:14px; line-height:1.6;
  }}
  header {{
    background:linear-gradient(135deg,#0d1117 0%,#161b22 50%,#0d1117 100%);
    border-bottom:1px solid var(--border);
    padding:32px 40px 24px;
    position:relative; overflow:hidden;
  }}
  header::before {{
    content:''; position:absolute; inset:0;
    background:radial-gradient(ellipse at 20% 50%,#58a6ff11 0%,transparent 60%),
               radial-gradient(ellipse at 80% 30%,#3fb95011 0%,transparent 60%);
  }}
  header h1 {{
    font-size:2rem; font-weight:900; letter-spacing:-0.02em;
    background:linear-gradient(90deg,#58a6ff,#3fb950);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent;
    position:relative;
  }}
  header p {{ color:var(--muted); margin-top:6px; font-size:0.88rem; position:relative; }}

  .container {{ max-width:1400px; margin:0 auto; padding:32px 24px; }}

  h2.section-title {{
    font-size:1.1rem; font-weight:700; color:var(--accent);
    border-bottom:1px solid var(--border);
    padding-bottom:8px; margin-bottom:16px;
  }}

  /* Summary table */
  .summary-wrap {{ background:var(--bg2); border:1px solid var(--border);
    border-radius:8px; overflow:hidden; margin-bottom:40px; }}
  .summary-wrap table {{ width:100%; border-collapse:collapse; }}
  .summary-wrap th {{
    background:var(--bg3); color:var(--muted); font-size:0.75rem;
    text-transform:uppercase; letter-spacing:.08em;
    padding:10px 14px; text-align:left; border-bottom:1px solid var(--border);
  }}
  .summary-wrap td {{
    padding:10px 14px; border-bottom:1px solid var(--border)11;
    font-size:0.88rem;
  }}
  .summary-wrap tr:last-child td {{ border-bottom:none; }}

  .badge {{
    display:inline-block; padding:2px 10px; border-radius:999px;
    font-size:0.78rem; font-weight:700; color:#fff;
  }}

  /* Detail section */
  .section {{
    background:var(--bg2); border:1px solid var(--border);
    border-radius:8px; padding:24px; margin-bottom:24px;
  }}
  .sym-header {{
    font-size:1rem; font-weight:700; margin-bottom:16px;
    display:flex; align-items:center; gap:10px; flex-wrap:wrap;
  }}
  .sym-tag {{
    background:var(--accent)22; color:var(--accent);
    border:1px solid var(--accent)44;
    padding:2px 12px; border-radius:4px; font-size:1rem; font-weight:900;
  }}
  .ivl-tag {{
    background:var(--bg3); color:var(--muted);
    padding:2px 10px; border-radius:4px; font-size:0.82rem;
  }}
  .wr-tag {{
    color:var(--green); font-weight:700; font-size:0.88rem;
  }}
  .cnt-tag {{ color:var(--muted); font-size:0.82rem; }}

  .two-col {{
    display:grid; grid-template-columns:1fr 1fr; gap:20px;
    margin-bottom:16px;
  }}
  @media(max-width:900px) {{ .two-col {{ grid-template-columns:1fr; }} }}

  h3.long-h3  {{ color:var(--green); font-size:0.88rem; margin-bottom:10px; }}
  h3.short-h3 {{ color:var(--red);   font-size:0.88rem; margin-bottom:10px; }}

  .rule-tbl {{ width:100%; border-collapse:collapse; font-size:0.78rem; }}
  .rule-tbl th {{
    background:var(--bg3); color:var(--muted); text-align:left;
    padding:6px 8px; font-size:0.72rem; text-transform:uppercase;
    letter-spacing:.06em;
  }}
  .rule-tbl td {{ padding:6px 8px; border-top:1px solid var(--border)44; vertical-align:middle; }}

  .bar-bg  {{ background:var(--bg3); border-radius:3px; height:6px; min-width:60px; }}
  .bar-fill {{ height:6px; border-radius:3px; transition:width .3s; }}

  details {{ margin-top:12px; }}
  summary.feat-summary {{
    color:var(--accent); cursor:pointer; font-size:0.82rem;
    padding:6px 0; user-select:none;
  }}
  summary.feat-summary:hover {{ opacity:0.8; }}
  .feat-list {{ padding:12px 0; }}
  .feat-row  {{
    display:flex; align-items:center; gap:10px;
    margin-bottom:6px;
  }}
  .feat-name {{ color:var(--text); font-family:'IBM Plex Mono',monospace;
    font-size:0.75rem; min-width:160px; }}
  .feat-val  {{ color:var(--muted); font-size:0.72rem; min-width:50px; text-align:right; }}

  .top-rules {{
    background:var(--bg3); border:1px solid var(--green)33;
    border-radius:8px; padding:20px; margin-bottom:32px;
  }}
  .top-rules h2 {{ color:var(--green); margin-bottom:12px; font-size:1rem; }}
  .top-rule-item {{
    background:var(--bg2); border-left:3px solid var(--green);
    padding:10px 14px; margin-bottom:8px; border-radius:0 4px 4px 0;
    font-size:0.82rem;
  }}
  .top-rule-item.short-rule {{ border-left-color:var(--red); }}
  .top-rule-item .wr {{ font-weight:700; }}
  .top-rule-item .cond {{ color:var(--muted); font-family:'IBM Plex Mono',monospace; font-size:0.75rem; }}
</style>
</head>
<body>
<header>
  <h1>🔍 최적 승률 패턴 분석 보고서</h1>
  <p>245-feature 앙상블 모델 기반 · 결정트리 룰 마이닝 · 6심볼 × 4봉단위</p>
</header>

<div class="container">

  <!-- 요약 테이블 -->
  <h2 class="section-title">📋 전체 요약</h2>
  <div class="summary-wrap">
    <table>
      <thead>
        <tr>
          <th>심볼</th><th>봉단위</th><th>거래수</th>
          <th>기본 승률</th><th>LONG 룰</th><th>SHORT 룰</th>
        </tr>
      </thead>
      <tbody>{summary_rows}</tbody>
    </table>
  </div>

  <!-- 상위 전체 룰 -->
  <div class="top-rules">
    <h2>🏆 Top 고승률 룰 (전체 심볼 통합)</h2>
    {_top_global_rules(results)}
  </div>

  <!-- 심볼별 상세 -->
  <h2 class="section-title">📈 심볼별 상세 패턴</h2>
  {detail_sections}

</div>
</body>
</html>"""
    return html


def _top_global_rules(results: dict) -> str:
    all_rules = []
    for (sym, ivl), v in results.items():
        for r in v["rules_L"]:
            all_rules.append({**r, "sym": sym, "ivl": ivl, "dir": "LONG"})
        for r in v["rules_S"]:
            all_rules.append({**r, "sym": sym, "ivl": ivl, "dir": "SHORT"})
    all_rules.sort(key=lambda x: (-x["win_rate"], -x["count"]))

    html = ""
    for r in all_rules[:15]:
        color  = "#27ae60" if r["dir"] == "LONG" else "#e74c3c"
        cls    = "" if r["dir"] == "LONG" else "short-rule"
        html  += f"""
<div class="top-rule-item {cls}">
  <span class="wr" style="color:{color}">{r['win_rate']}%</span>
  &nbsp;|&nbsp; <b>{r['sym']}</b> <span style="color:#8b949e">{r['ivl']}</span>
  &nbsp;|&nbsp; n={r['count']} &nbsp;|&nbsp; lift={r['lift']}x
  &nbsp;|&nbsp; <span style="font-size:0.75rem;color:#d29922">{r['dir']}</span>
  <br>
  <span class="cond">{r['rule']}</span>
</div>"""
    return html or "<p style='color:#888'>분석 결과 없음</p>"


# ══════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════

if __name__ == "__main__":
    results, trades_all = analyze_all()

    out_path = os.path.join(CHART_DIR, "pattern_report.html")
    html = build_html(results)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n✅ 보고서 저장: {out_path}")

    # CSV 요약도 저장
    all_rules = []
    for (sym, ivl), v in results.items():
        for r in v["rules_L"]:
            all_rules.append({**r, "symbol": sym, "interval": ivl})
        for r in v["rules_S"]:
            all_rules.append({**r, "symbol": sym, "interval": ivl})
    if all_rules:
        pd.DataFrame(all_rules).sort_values("win_rate", ascending=False).to_csv(
            os.path.join(MODEL_DIR, "pattern_rules.csv"), index=False)
        print(f"✅ 룰 CSV: ml/saved_models/pattern_rules.csv")
