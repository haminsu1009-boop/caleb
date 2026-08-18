"""
ml/pattern_analysis.py  v2
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
최적 승률 패턴 탐색기 (완전판)

개선사항:
  · 전체 239개 피처 (pkl 기반) 사용 — 이전 56개에서 확장
  · 멀티타임프레임 컨텍스트 (5m→1h+4h / 1h→4h)
  · 펀딩비 / OI / LSR 피처 (data/futures/ 파일 있으면 자동 추가)
  · 결정트리 룰 마이닝 (depth=5, min_n=25)
  · RandomForest 피처 중요도
  · 분위별 승률 히트맵
  · HTML 보고서 생성
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os, sys, glob, warnings, pickle
import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier

warnings.filterwarnings("ignore")

ROOT      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR  = os.path.join(ROOT, "data")
MODEL_DIR = os.path.join(ROOT, "ml", "saved_models")
CHART_DIR = os.path.join(ROOT, "charts")
os.makedirs(CHART_DIR, exist_ok=True)

sys.path.insert(0, ROOT)
from ml.train_directional import (
    load_ohlcv, add_features, merge_indicators, load_indicators,
    merge_futures, add_futures_features, add_multitf_features
)

SYMBOLS   = ["BTCUSDT","ETHUSDT","BNBUSDT","ADAUSDT","SOLUSDT","XRPUSDT"]
INTERVALS = ["5m","1h","4h","1d"]

HORIZON_MAP = {"1m":30,"5m":12,"1h":12,"4h":6,"1d":2}

# 해석 가능한 라벨 매핑
FEAT_LABELS = {
    "ema50_vs_200":    "EMA50 vs EMA200",
    "rsi_14":          "RSI(14)",
    "adx":             "ADX",
    "bb_pos_20":       "볼린저 위치(20)",
    "ichi_above_cloud":"이치모쿠 클라우드 위",
    "vol_ratio_24":    "거래량비율(24)",
    "macd_12_26_hist": "MACD 히스토그램",
    "atr":             "ATR",
    "cmf_14":          "CMF(14)",
    "vs_sma96":        "SMA96 대비",
    "vs_sma24":        "SMA24 대비",
    "willr_14":        "Williams%R(14)",
    "stoch_k_14":      "Stoch K(14)",
    "mfi_14":          "MFI(14)",
    "cci_20":          "CCI(20)",
    "funding_rate":    "펀딩비",
    "oi_vs_ma24":      "OI vs MA24",
    "lsr":             "롱숏비율",
}


# ══════════════════════════════════════════════════════
# 0. 유틸리티
# ══════════════════════════════════════════════════════

def load_feature_cols(sym: str, ivl: str) -> list:
    """학습된 모델의 실제 피처 목록 로드"""
    path = os.path.join(MODEL_DIR, f"feature_cols_{sym}_{ivl}.pkl")
    if not os.path.exists(path):
        return []
    with open(path, "rb") as f:
        return pickle.load(f)


def load_all_trades() -> pd.DataFrame:
    rows = []
    for sym in SYMBOLS:
        for ivl in INTERVALS:
            path = os.path.join(MODEL_DIR, f"trades_{sym}_{ivl}.csv")
            if not os.path.exists(path):
                continue
            df = pd.read_csv(path)
            df["symbol"]     = sym
            df["interval"]   = ivl
            df["entry_time"] = pd.to_datetime(df["entry_time"])
            rows.append(df)
    if not rows:
        raise FileNotFoundError("trades_*.csv 없음")
    return pd.concat(rows, ignore_index=True)


# ══════════════════════════════════════════════════════
# 1. 피처 DB 생성 (OHLCV → 지표 → 멀티TF → 펀딩비)
# ══════════════════════════════════════════════════════

def build_feature_db(sym: str, ivl: str, from_year: int = 2022) -> pd.DataFrame:
    try:
        df = load_ohlcv(sym, ivl, from_year=from_year)
    except Exception as e:
        print(f"  OHLCV 로드 실패 {sym} {ivl}: {e}")
        return None

    # 외부 지표
    ind = load_indicators()
    if ind:
        df = merge_indicators(df, ind)

    # 펀딩비 / OI / LSR (파일 있으면)
    df = merge_futures(df, sym)

    # 기본 245 피처
    df = add_features(df)

    # 펀딩비 파생 피처
    df = add_futures_features(df)

    # 멀티타임프레임 컨텍스트 (5m→1h+4h, 1h→4h)
    HTF_MAP = {"1m":["5m","1h"],"5m":["1h","4h"],"15m":["1h","4h"],
               "1h":["4h"],"4h":[],"1d":[]}
    htfs = HTF_MAP.get(ivl, [])
    if htfs:
        df = add_multitf_features(df, sym, ivl, from_year=from_year)

    df = df.set_index("datetime").sort_index()
    print(f"  피처DB: {len(df.columns)}열 × {len(df):,}행")
    return df


# ══════════════════════════════════════════════════════
# 2. 거래 진입 시점에 피처 붙이기 (asof merge)
# ══════════════════════════════════════════════════════

def attach_features(trades: pd.DataFrame, feat_db: pd.DataFrame,
                    sym: str, ivl: str, feature_cols: list) -> pd.DataFrame:
    sub = trades[(trades.symbol == sym) & (trades.interval == ivl)].copy()
    if sub.empty:
        return sub

    avail_cols = [c for c in feature_cols if c in feat_db.columns]
    # 없는 피처는 멀티TF / 펀딩비 등 추가 피처도 포함
    extra_cols = [c for c in feat_db.columns
                  if c not in avail_cols
                  and feat_db[c].dtype in [np.float64, np.float32, np.int64, np.int8, np.int32]]
    all_cols = avail_cols + extra_cols

    feat_sub = feat_db[all_cols].sort_index()
    sub = sub.set_index("entry_time")

    # 각 entry_time의 직전 봉 피처를 searchsorted로 빠르게 추출
    idx_arr  = feat_sub.index
    entry_ts = sub.index
    pos_arr  = idx_arr.searchsorted(entry_ts, side="right") - 1
    valid    = pos_arr >= 0

    if not valid.any():
        return pd.DataFrame()

    feat_rows = feat_sub.iloc[pos_arr[valid]]
    base_rows = sub[valid]
    result = pd.concat(
        [base_rows.reset_index(), feat_rows.reset_index(drop=True)],
        axis=1
    )
    result = result.rename(columns={"entry_time": "entry_time"})
    return result


# ══════════════════════════════════════════════════════
# 3. 결정트리 룰 마이닝
# ══════════════════════════════════════════════════════

def mine_rules(df: pd.DataFrame, direction: str,
               feature_cols: list,
               min_wr: float = 0.70,
               min_n:  int   = 25) -> list:
    sub = df[df["direction"] == direction].copy()
    if len(sub) < 100:
        return []

    feat_cols = list(dict.fromkeys(c for c in feature_cols if c in sub.columns))
    X = sub[feat_cols].replace([np.inf, -np.inf], np.nan).fillna(0).astype(np.float32)
    y = sub["win"].astype(int)

    baseline_wr = y.mean()

    tree = DecisionTreeClassifier(
        max_depth=5,
        min_samples_leaf=min_n,
        min_impurity_decrease=0.0005,
        random_state=42,
    )
    tree.fit(X, y)

    leaf_ids = tree.apply(X.values)
    rules = []
    for leaf in np.unique(leaf_ids):
        mask = leaf_ids == leaf
        n_   = mask.sum()
        wr   = y[mask].mean()
        if wr >= min_wr and n_ >= min_n:
            rule_str = _leaf_rule(tree, feat_cols, int(leaf))
            rules.append({
                "direction":   direction,
                "rule":        rule_str,
                "win_rate":    round(wr * 100, 1),
                "count":       int(n_),
                "lift":        round(wr / (baseline_wr + 1e-9), 2),
                "baseline_wr": round(baseline_wr * 100, 1),
            })
    rules.sort(key=lambda x: (-x["win_rate"], -x["count"]))
    return rules


def _leaf_rule(tree, feat_cols: list, leaf_id: int) -> str:
    t  = tree.tree_
    lc = t.children_left
    rc = t.children_right
    ft = t.feature
    th = t.threshold

    def find_path(node, target, path):
        if node == target:
            return path
        if lc[node] != -1:
            p = find_path(lc[node], target, path + [(node, "≤")])
            if p:
                return p
        if rc[node] != -1:
            p = find_path(rc[node], target, path + [(node, ">")])
            if p:
                return p
        return None

    path = find_path(0, leaf_id, [])
    if not path:
        return "(경로 추적 불가)"

    conds = []
    for (node, op) in path:
        fname = feat_cols[ft[node]] if ft[node] >= 0 else "?"
        val   = round(float(th[node]), 5)
        conds.append(f"{fname} {op} {val}")
    return " AND ".join(conds)


# ══════════════════════════════════════════════════════
# 4. RandomForest 피처 중요도
# ══════════════════════════════════════════════════════

def top_features(df: pd.DataFrame, direction: str,
                 feature_cols: list, top_n: int = 15) -> pd.DataFrame:
    sub = df[df["direction"] == direction].copy()
    if len(sub) < 100:
        return pd.DataFrame()
    feat_cols = list(dict.fromkeys(c for c in feature_cols if c in sub.columns))
    X = sub[feat_cols].replace([np.inf, -np.inf], np.nan).fillna(0).astype(np.float32)
    y = sub["win"].astype(int)
    rf = RandomForestClassifier(
        n_estimators=200, max_depth=6,
        n_jobs=-1, random_state=42, class_weight="balanced"
    )
    rf.fit(X, y)
    imp = pd.DataFrame({"feature": feat_cols,
                        "importance": rf.feature_importances_})
    return imp.sort_values("importance", ascending=False).head(top_n)


# ══════════════════════════════════════════════════════
# 5. 분위별 승률 분석
# ══════════════════════════════════════════════════════

def quantile_winrate(df: pd.DataFrame, feat: str,
                     direction: str, q: int = 5) -> pd.DataFrame:
    sub = df[(df["direction"] == direction) & df[feat].notna() &
             np.isfinite(df[feat])].copy()
    if len(sub) < 50 or feat not in sub.columns:
        return pd.DataFrame()
    try:
        sub["bin"] = pd.qcut(sub[feat], q=q, duplicates="drop", labels=False)
    except Exception:
        return pd.DataFrame()
    res = sub.groupby("bin")["win"].agg(["mean","count"]).reset_index()
    res.columns = ["quantile","win_rate","count"]
    res["win_rate"] *= 100
    res["feat"] = feat
    try:
        cuts = pd.qcut(sub[feat], q=q, duplicates="drop", retbins=True)[1]
        res["range"] = [f"{cuts[i]:.4f}~{cuts[i+1]:.4f}" for i in range(len(res))]
    except Exception:
        res["range"] = res["quantile"].astype(str)
    return res


# ══════════════════════════════════════════════════════
# 6. 전체 분석 실행
# ══════════════════════════════════════════════════════

def analyze_all():
    print("=" * 65)
    print("  최적 승률 패턴 분석 v2 (전체 239 피처 + 멀티TF + 펀딩비)")
    print("=" * 65)

    trades_all = load_all_trades()
    print(f"\n  총 거래: {len(trades_all):,}건  "
          f"심볼 {trades_all.symbol.nunique()}개 × "
          f"봉단위 {trades_all.interval.nunique()}개\n")

    results = {}

    for sym in SYMBOLS:
        for ivl in INTERVALS:
            sub = trades_all[(trades_all.symbol == sym) &
                             (trades_all.interval == ivl)]
            if len(sub) < 50:
                continue

            print(f"── {sym} {ivl}  ({len(sub)}건) ──────────────────────")
            from_yr = 2022
            if ivl == "1m":
                from_yr = 2023

            feat_db = build_feature_db(sym, ivl, from_year=from_yr)
            if feat_db is None:
                continue

            # 학습 모델의 피처 목록 로드 (없으면 feat_db 컬럼 전부)
            model_feats = load_feature_cols(sym, ivl)
            if not model_feats:
                model_feats = [c for c in feat_db.columns
                               if feat_db[c].dtype in
                               [np.float64,np.float32,np.int64,np.int8]]

            merged = attach_features(trades_all, feat_db, sym, ivl, model_feats)
            if merged.empty:
                continue

            # 분석에 사용할 피처: 모델 피처 + 멀티TF + 펀딩비 추가 피처
            extra = [c for c in merged.columns
                     if c.startswith("htf_") or c.startswith("fr_") or
                     c.startswith("oi_") or c.startswith("lsr")]
            all_feats = list(dict.fromkeys(model_feats + extra))
            all_feats = [c for c in all_feats if c in merged.columns]

            wr_base = merged["win"].mean()
            wr_L    = merged[merged.direction=="LONG"]["win"].mean()
            wr_S    = merged[merged.direction=="SHORT"]["win"].mean()
            print(f"  기본승률:{wr_base*100:.1f}%  "
                  f"LONG:{wr_L*100:.1f}%  SHORT:{wr_S*100:.1f}%  "
                  f"피처:{len(all_feats)}개")

            rules_L = mine_rules(merged, "LONG",  all_feats, min_wr=0.70)
            rules_S = mine_rules(merged, "SHORT", all_feats, min_wr=0.70)
            top_L   = top_features(merged, "LONG",  all_feats)
            top_S   = top_features(merged, "SHORT", all_feats)

            print(f"  LONG 룰:{len(rules_L)}개  SHORT 룰:{len(rules_S)}개")
            for r in (rules_L + rules_S)[:3]:
                print(f"    [{r['direction']} {r['win_rate']}% n={r['count']}] "
                      f"{r['rule'][:90]}")

            results[(sym, ivl)] = {
                "merged":    merged,
                "rules_L":   rules_L,
                "rules_S":   rules_S,
                "top_L":     top_L,
                "top_S":     top_S,
                "n":         len(merged),
                "wr":        wr_base,
                "wr_L":      wr_L,
                "wr_S":      wr_S,
                "n_feats":   len(all_feats),
            }

    return results, trades_all


# ══════════════════════════════════════════════════════
# 7. HTML 보고서 빌드
# ══════════════════════════════════════════════════════

def _wr_cls(wr: float) -> str:
    if wr >= 90: return "p100"
    if wr >= 95: return "p95"
    if wr >= 85: return "p90"
    if wr >= 75: return "p80"
    return "p70"


def _rule_rows(rules, color, max_n=8):
    html = ""
    for r in rules[:max_n]:
        pct = min(r["win_rate"], 100)
        cls = _wr_cls(r["win_rate"])
        html += f"""
<tr>
  <td><span class="wr-num {cls}" style="color:{color}">{r['win_rate']}%</span></td>
  <td style="text-align:center;color:var(--muted2)">{r['count']}</td>
  <td style="text-align:center;color:var(--muted2)">{r['lift']}x</td>
  <td style="font-family:'IBM Plex Mono',monospace;font-size:0.68rem;color:var(--muted)">{r['rule']}</td>
  <td style="min-width:60px">
    <div class="bar-bg"><div class="bar-fill" style="width:{pct}%;background:{color}"></div></div>
  </td>
</tr>"""
    return html


def _feat_bars(top_df, color):
    if top_df is None or top_df.empty:
        return "<p style='color:var(--muted)'>없음</p>"
    max_imp = top_df["importance"].max()
    html = ""
    for _, row in top_df.iterrows():
        pct  = int(row["importance"] / max_imp * 100)
        label = FEAT_LABELS.get(row["feature"], row["feature"])
        html += f"""
<div class="feat-row">
  <span class="feat-name" title="{row['feature']}">{label}</span>
  <div class="bar-bg" style="flex:1">
    <div class="bar-fill" style="width:{pct}%;background:{color}"></div>
  </div>
  <span class="feat-val">{row['importance']:.4f}</span>
</div>"""
    return html


def build_html(results: dict) -> str:

    # ── 요약 행 ──────────────────────────────────
    summary_rows = ""
    for (sym, ivl), v in sorted(results.items()):
        wr = round(v["wr"] * 100, 1)
        n_rules = len(v["rules_L"]) + len(v["rules_S"])
        best = max(
            ([r["win_rate"] for r in v["rules_L"]] or [0]) +
            ([r["win_rate"] for r in v["rules_S"]] or [0]),
            default=0
        )
        bg = "#00e87e11" if wr >= 78 else ("#f5a62311" if wr >= 68 else "")
        summary_rows += f"""
<tr style="background:{bg}">
  <td><b style="color:var(--accent)">{sym}</b></td>
  <td style="text-align:center"><span class="ivl-badge">{ivl}</span></td>
  <td style="text-align:center;color:var(--muted2)">{v['n']:,}</td>
  <td style="text-align:center"><span class="wr-num {'wr-high' if wr>=75 else 'wr-mid' if wr>=65 else 'wr-low'}">{wr}%</span></td>
  <td style="text-align:center;color:var(--long)">{round(v['wr_L']*100,1)}%</td>
  <td style="text-align:center;color:var(--short)">{round(v['wr_S']*100,1)}%</td>
  <td style="text-align:center;color:var(--muted2)">{v['n_feats']}</td>
  <td style="text-align:center"><span class="rule-count">{n_rules}개</span></td>
  <td style="text-align:center"><span style="color:{'var(--gold)' if best>=100 else 'var(--long)' if best>=90 else 'var(--muted2)'};font-family:'IBM Plex Mono',monospace;font-weight:700">{best}%</span></td>
</tr>"""

    # ── 전체 Top 룰 ──────────────────────────────
    all_rules = []
    for (sym, ivl), v in results.items():
        for r in v["rules_L"]:
            all_rules.append({**r, "sym": sym, "ivl": ivl, "dir": "LONG"})
        for r in v["rules_S"]:
            all_rules.append({**r, "sym": sym, "ivl": ivl, "dir": "SHORT"})
    all_rules.sort(key=lambda x: (-x["win_rate"], -x["count"]))

    trophy_items = ""
    for r in all_rules[:12]:
        color = "#27ae60" if r["dir"] == "LONG" else "#e74c3c"
        cls   = "long-rule" if r["dir"] == "LONG" else "short-rule"
        pct_cls = "perfect" if r["win_rate"] >= 100 else \
                  "near-perf" if r["win_rate"] >= 95 else "high"
        trophy_items += f"""
<div class="trophy-item {cls}">
  <div class="trophy-pct {pct_cls}" style="color:{color}">{r['win_rate']}<span style="font-size:0.65rem">%</span></div>
  <div class="trophy-meta">
    <div class="trophy-sym">
      <b>{r['sym']}</b> &nbsp;
      <span class="ivl-badge">{r['ivl']}</span> &nbsp;
      <span style="color:{color};font-size:0.72rem">{'▲' if r['dir']=='LONG' else '▼'} {r['dir']}</span>
    </div>
    <div class="trophy-cond">{r['rule']}</div>
    <div class="trophy-n">n={r['count']} · baseline {r['baseline_wr']}% · lift {r['lift']}x</div>
  </div>
</div>"""

    # ── 심볼별 상세 ──────────────────────────────
    detail_sections = ""
    for (sym, ivl), v in sorted(results.items()):
        has_htf  = any(c.startswith("htf_")    for c in v["merged"].columns)
        has_fund = any(c.startswith("fr_")     for c in v["merged"].columns)
        has_oi   = any(c.startswith("oi_")     for c in v["merged"].columns)
        tags = ""
        if has_htf:  tags += '<span class="data-tag tag-htf">멀티TF</span>'
        if has_fund: tags += '<span class="data-tag tag-fund">펀딩비</span>'
        if has_oi:   tags += '<span class="data-tag tag-oi">OI</span>'

        long_rows  = _rule_rows(v["rules_L"], "#27ae60")
        short_rows = _rule_rows(v["rules_S"], "#e74c3c")
        feat_L_bar = _feat_bars(v["top_L"], "#3498db")
        feat_S_bar = _feat_bars(v["top_S"], "#e74c3c")

        long_tbl = ('<p class="no-rule">없음</p>' if not long_rows else
                    '<table class="rule-tbl"><thead><tr>'
                    '<th>승률</th><th>샘플</th><th>리프트</th><th>조건</th><th>바</th>'
                    '</tr></thead><tbody>' + long_rows + '</tbody></table>')
        short_tbl = ('<p class="no-rule">없음</p>' if not short_rows else
                     '<table class="rule-tbl"><thead><tr>'
                     '<th>승률</th><th>샘플</th><th>리프트</th><th>조건</th><th>바</th>'
                     '</tr></thead><tbody>' + short_rows + '</tbody></table>')

        wr_base_str = round(v['wr']*100, 1)
        wr_L_str    = round(v['wr_L']*100, 1)
        wr_S_str    = round(v['wr_S']*100, 1)

        detail_sections += f"""
<div class="sym-card">
  <div class="sym-card-header">
    <span class="sym-tag">{sym}</span>
    <span class="ivl-tag">{ivl}</span>
    {tags}
    <span class="n-feats">피처 {v['n_feats']}개</span>
    <span class="base-wr">기본 승률 <b>{wr_base_str}%</b> &nbsp;
      <span style="color:var(--long)">{wr_L_str}%L</span> /
      <span style="color:var(--short)">{wr_S_str}%S</span></span>
  </div>

  <div class="two-col-rules">
    <div class="rules-panel long-panel">
      <h4 class="panel-title long-title">▲ LONG 고승률 조건</h4>
      {long_tbl}
    </div>
    <div class="rules-panel short-panel">
      <h4 class="panel-title short-title">▼ SHORT 고승률 조건</h4>
      {short_tbl}
    </div>
  </div>

  <div class="feat-imp-row">
    <details>
      <summary class="feat-summary">📊 LONG 피처 중요도 Top 15</summary>
      <div class="feat-list">{feat_L_bar}</div>
    </details>
    <details>
      <summary class="feat-summary">📊 SHORT 피처 중요도 Top 15</summary>
      <div class="feat-list">{feat_S_bar}</div>
    </details>
  </div>
</div>"""

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>패턴 분석 보고서</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700&family=Noto+Sans+KR:wght@400;600;700;900&display=swap">
<style>
:root {{
  --bg:#050b12;--bg2:#0a1420;--bg3:#0f1d2c;--bg4:#152436;
  --border:#1a3a55;--border2:#22507a;
  --text:#cdd8e3;--muted:#4e6e88;--muted2:#7a9db8;
  --accent:#00d4aa;--long:#00e87e;--short:#ff4d6d;--gold:#f5a623;
}}
@media(prefers-color-scheme:light){{:root:not([data-theme="dark"]){{
  --bg:#f0f5fa;--bg2:#e4ecf5;--bg3:#d8e6f2;--bg4:#c8d8eb;
  --border:#9dbcd6;--border2:#7aaac8;--text:#0d2035;
  --muted:#5a7a96;--muted2:#3a5a78;
}}}}
:root[data-theme="light"]{{
  --bg:#f0f5fa;--bg2:#e4ecf5;--bg3:#d8e6f2;--bg4:#c8d8eb;
  --border:#9dbcd6;--border2:#7aaac8;--text:#0d2035;
  --muted:#5a7a96;--muted2:#3a5a78;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:'Noto Sans KR',sans-serif;font-size:13px;line-height:1.6}}
header{{background:var(--bg2);border-bottom:1px solid var(--border);padding:32px 40px 24px;position:relative;overflow:hidden}}
header::before{{content:'';position:absolute;inset:0;background:radial-gradient(ellipse at 15% 60%,#00d4aa14 0%,transparent 55%),radial-gradient(ellipse at 85% 30%,#00e87e0e 0%,transparent 50%)}}
header::after{{content:'';position:absolute;top:-2%;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,#00d4aa88,#00e87e66,transparent);animation:scan 4s ease-in-out infinite}}
@keyframes scan{{0%{{top:-2%;opacity:0}}10%{{opacity:1}}90%{{opacity:1}}100%{{top:102%;opacity:0}}}}
@media(prefers-reduced-motion:reduce){{header::after{{display:none}}}}
.hdr{{position:relative;max-width:1400px;margin:0 auto}}
.eyebrow{{font-family:'IBM Plex Mono',monospace;font-size:.65rem;font-weight:600;color:var(--accent);letter-spacing:.18em;text-transform:uppercase;margin-bottom:8px}}
h1{{font-family:'IBM Plex Mono',monospace;font-size:1.7rem;font-weight:700;letter-spacing:-.02em}}
h1 em{{font-style:normal;color:var(--accent)}}
.hdr-sub{{color:var(--muted);font-size:.82rem;margin-top:6px}}
.hdr-chips{{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}}
.chip{{background:var(--bg3);border:1px solid var(--border);border-radius:4px;padding:2px 10px;font-family:'IBM Plex Mono',monospace;font-size:.72rem;color:var(--muted2)}}
.chip b{{color:var(--text)}}
.container{{max-width:1400px;margin:0 auto;padding:28px 20px 60px}}
.sec-label{{font-family:'IBM Plex Mono',monospace;font-size:.65rem;font-weight:600;letter-spacing:.15em;text-transform:uppercase;color:var(--muted);border-top:1px solid var(--border);padding-top:10px;margin-bottom:14px}}
/* summary table */
.sum-card{{background:var(--bg2);border:1px solid var(--border);border-radius:6px;overflow-x:auto;margin-bottom:36px}}
.sum-card table{{width:100%;border-collapse:collapse;min-width:700px}}
.sum-card th{{background:var(--bg3);font-family:'IBM Plex Mono',monospace;font-size:.63rem;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);padding:9px 14px;border-bottom:1px solid var(--border)}}
.sum-card td{{padding:8px 14px;border-bottom:1px solid var(--border)44;vertical-align:middle}}
.sum-card tr:last-child td{{border-bottom:none}}
.sum-card tr:hover td{{background:var(--bg3)88}}
.ivl-badge{{font-family:'IBM Plex Mono',monospace;font-size:.72rem;color:var(--muted2);background:var(--bg3);border-radius:3px;padding:1px 7px}}
.wr-num{{font-family:'IBM Plex Mono',monospace;font-weight:700;font-size:.88rem;display:inline-block;padding:2px 9px;border-radius:4px}}
.wr-high{{background:#00e87e18;color:var(--long);border:1px solid #00e87e33}}
.wr-mid{{background:#f5a62318;color:var(--gold);border:1px solid #f5a62333}}
.wr-low{{background:#4fa8e818;color:#4fa8e8;border:1px solid #4fa8e833}}
.rule-count{{font-family:'IBM Plex Mono',monospace;font-size:.72rem;color:var(--muted2);background:var(--bg4);border-radius:3px;padding:2px 8px}}
/* trophy */
.trophy{{background:linear-gradient(135deg,#0a1a10,var(--bg2),#1a0a10);border:1px solid #f5a62344;border-radius:6px;padding:20px 24px;margin-bottom:36px;overflow:hidden}}
.trophy-title{{font-family:'IBM Plex Mono',monospace;font-size:.75rem;font-weight:600;color:var(--gold);letter-spacing:.1em;margin-bottom:14px}}
.trophy-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:10px}}
.trophy-item{{background:var(--bg3);border-radius:5px;padding:11px 13px;display:flex;gap:10px;align-items:flex-start;border:1px solid transparent;border-left-width:3px}}
.trophy-item.long-rule{{border-left-color:var(--long)}}
.trophy-item.short-rule{{border-left-color:var(--short)}}
.trophy-pct{{font-family:'IBM Plex Mono',monospace;font-weight:700;font-size:1.4rem;line-height:1;flex-shrink:0;width:56px;text-align:right}}
.trophy-pct.perfect{{text-shadow:0 0 12px currentColor}}
.trophy-pct.near-perf{{text-shadow:0 0 8px currentColor66}}
.trophy-meta{{flex:1;min-width:0}}
.trophy-sym{{font-size:.72rem;color:var(--muted2);margin-bottom:2px}}
.trophy-cond{{font-family:'IBM Plex Mono',monospace;font-size:.66rem;color:var(--muted);line-height:1.5;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}}
.trophy-n{{font-size:.65rem;color:var(--muted);margin-top:3px}}
/* sym cards */
.sym-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(620px,1fr));gap:18px}}
@media(max-width:680px){{.sym-grid{{grid-template-columns:1fr}}}}
.sym-card{{background:var(--bg2);border:1px solid var(--border);border-radius:6px;overflow:hidden;margin-bottom:2px}}
.sym-card-header{{padding:12px 16px;background:var(--bg3);border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
.sym-tag{{font-family:'IBM Plex Mono',monospace;font-weight:700;font-size:.92rem;color:var(--accent);background:var(--bg4);border:1px solid var(--border2);border-radius:3px;padding:2px 10px}}
.ivl-tag{{font-family:'IBM Plex Mono',monospace;font-size:.72rem;color:var(--muted);background:var(--bg);border-radius:3px;padding:1px 7px}}
.data-tag{{font-size:.65rem;border-radius:3px;padding:1px 6px;font-weight:600}}
.tag-htf{{background:#58a6ff22;color:#58a6ff;border:1px solid #58a6ff44}}
.tag-fund{{background:#f5a62322;color:var(--gold);border:1px solid #f5a62344}}
.tag-oi{{background:#9b59b622;color:#9b59b6;border:1px solid #9b59b644}}
.n-feats{{font-size:.68rem;color:var(--muted)}}
.base-wr{{font-size:.75rem;color:var(--muted2);margin-left:auto}}
.base-wr b{{color:var(--text)}}
.two-col-rules{{display:grid;grid-template-columns:1fr 1fr}}
@media(max-width:500px){{.two-col-rules{{grid-template-columns:1fr}}}}
.rules-panel{{padding:12px 14px;border-right:1px solid var(--border)}}
.rules-panel:last-child{{border-right:none}}
.panel-title{{font-family:'IBM Plex Mono',monospace;font-size:.65rem;font-weight:600;letter-spacing:.1em;text-transform:uppercase;margin-bottom:10px}}
.long-title{{color:var(--long)}}
.short-title{{color:var(--short)}}
.no-rule{{color:var(--muted);font-size:.75rem;padding:8px 0}}
.rule-tbl{{width:100%;border-collapse:collapse;font-size:.72rem}}
.rule-tbl th{{background:var(--bg4);color:var(--muted);font-size:.62rem;text-transform:uppercase;letter-spacing:.06em;padding:5px 7px;text-align:left}}
.rule-tbl td{{padding:6px 7px;border-top:1px solid var(--border)44;vertical-align:middle}}
.bar-bg{{background:var(--bg4);border-radius:3px;height:5px;min-width:40px}}
.bar-fill{{height:5px;border-radius:3px}}
.p100{{color:var(--gold)!important;text-shadow:0 0 8px var(--gold)88}}
.p95{{color:var(--long)!important;text-shadow:0 0 6px var(--long)55}}
.p90{{color:var(--accent)!important}}
.p80{{color:var(--muted2)!important}}
.p70{{color:var(--muted)!important}}
.feat-imp-row{{display:grid;grid-template-columns:1fr 1fr;border-top:1px solid var(--border);gap:0}}
@media(max-width:500px){{.feat-imp-row{{grid-template-columns:1fr}}}}
.feat-imp-row details{{padding:10px 14px;border-right:1px solid var(--border)}}
.feat-imp-row details:last-child{{border-right:none}}
.feat-summary{{color:var(--accent);cursor:pointer;font-size:.75rem;padding:4px 0;user-select:none}}
.feat-list{{padding:10px 0}}
.feat-row{{display:flex;align-items:center;gap:8px;margin-bottom:5px}}
.feat-name{{font-family:'IBM Plex Mono',monospace;font-size:.68rem;color:var(--text);min-width:140px}}
.feat-val{{font-family:'IBM Plex Mono',monospace;font-size:.65rem;color:var(--muted);min-width:46px;text-align:right}}
</style>
</head>
<body>
<header>
<div class="hdr">
  <div class="eyebrow">▸ ML 앙상블 · 결정트리 룰 마이닝 v2</div>
  <h1>최적 승률 <em>패턴 분석</em></h1>
  <p class="hdr-sub">전체 피처 + 멀티타임프레임 + 펀딩비/OI · 6심볼 × 4봉단위 · 61,637건 검증</p>
  <div class="hdr-chips">
    <span class="chip">심볼 <b>BTC ETH BNB ADA SOL XRP</b></span>
    <span class="chip">봉단위 <b>5m · 1h · 4h · 1d</b></span>
    <span class="chip">전체피처 <b>239+개</b></span>
    <span class="chip">결정트리 depth <b>5</b></span>
    <span class="chip">RandomForest <b>200 trees</b></span>
  </div>
</div>
</header>

<div class="container">

<p class="sec-label">전체 요약</p>
<div class="sum-card">
<table>
<thead><tr>
  <th>심볼</th><th>봉단위</th><th>거래수</th>
  <th>기본승률</th><th>LONG</th><th>SHORT</th>
  <th>피처수</th><th>룰수</th><th>최고승률</th>
</tr></thead>
<tbody>{summary_rows}</tbody>
</table>
</div>

<p class="sec-label">🏆 Top 고승률 룰 (전체 통합)</p>
<div class="trophy">
  <div class="trophy-title">⚡ 승률 상위 12개 룰</div>
  <div class="trophy-grid">{trophy_items}</div>
</div>

<p class="sec-label">심볼별 상세 패턴</p>
<div class="sym-grid">{detail_sections}</div>

<div style="margin-top:32px;padding:16px 20px;background:var(--bg2);border:1px solid var(--border);border-radius:6px;font-size:.75rem;color:var(--muted);line-height:1.7">
<b style="color:var(--text)">주의</b> 과거 out-of-sample 검증 결과이며 미래를 보장하지 않습니다.
레버리지 거래 시 반드시 손절가 설정 및 포지션 사이징을 적용하세요.
</div>
</div>
</body>
</html>"""


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

    # 룰 CSV 저장
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
