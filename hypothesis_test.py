"""
hypothesis_test.py
가설 검증 시뮬레이션

가설: "기술적 지표 조합으로 BTC 매매 신호를 만들면 수익을 낼 수 있다"

검증 방법:
  1. 랜덤 전략 대비 우위 (통계적 유의성)
  2. 워크포워드 검증 (과거 → 미래 예측력)
  3. 바이앤홀드 대비 비교
  4. 몬테카를로 시뮬레이션
  5. 현실 비용 적용 (수수료, 슬리피지)
"""

import os, sys, warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from scipy import stats
warnings.filterwarnings("ignore")

ROOT      = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(ROOT, "data", "btc_daily.csv")
OUT_FILE  = os.path.join(ROOT, "charts", "hypothesis_test.png")
os.makedirs(os.path.join(ROOT, "charts"), exist_ok=True)

# ── 파라미터 ───────────────────────────────────
TRAIN_RATIO   = 0.70       # 학습 구간 70%
FEE_RATE      = 0.001      # 수수료 0.1% (바이낸스 기준)
SLIPPAGE      = 0.0005     # 슬리피지 0.05%
HOLD_DAYS     = 3          # 보유 기간
MONTE_N       = 2000       # 몬테카를로 횟수
RANDOM_SEED   = 42
np.random.seed(RANDOM_SEED)

print("=" * 60)
print("  퀀트 트레이딩 가설 검증 시뮬레이션")
print("=" * 60)

# ── 데이터 로드 ────────────────────────────────
df = pd.read_csv(DATA_FILE)
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values("date").reset_index(drop=True)
print(f"\n데이터: {df['date'].min().date()} ~ {df['date'].max().date()}  ({len(df)}일)")

# ── 지표 계산 ──────────────────────────────────
def add_indicators(df):
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    for p in [7,20,50,100,200]:
        df[f"sma{p}"] = c.rolling(p).mean()
        df[f"ema{p}"] = c.ewm(span=p,adjust=False).mean()
    for p in [7,14,21]:
        d = c.diff()
        g = d.clip(lower=0).rolling(p).mean()
        ls = (-d.clip(upper=0)).rolling(p).mean()
        df[f"rsi{p}"] = 100 - 100/(1 + g/ls.replace(0,np.nan))
    e12 = c.ewm(span=12,adjust=False).mean()
    e26 = c.ewm(span=26,adjust=False).mean()
    df["macd"] = e12 - e26
    df["macd_sig"] = df["macd"].ewm(span=9,adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_sig"]
    mid = c.rolling(20).mean(); std = c.rolling(20).std()
    df["bb_upper"] = mid + 2*std; df["bb_lower"] = mid - 2*std
    df["bb_pct"] = (c - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])
    for p in [14,21]:
        lo=l.rolling(p).min(); hi=h.rolling(p).max()
        df[f"stoch{p}"] = (c-lo)/(hi-lo+1e-9)*100
    tr = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    pdm=h.diff().clip(lower=0); mdm=(-l.diff()).clip(lower=0)
    atr=tr.rolling(14).mean()
    df["plus_di"]=100*pdm.rolling(14).mean()/atr.replace(0,np.nan)
    df["minus_di"]=100*mdm.rolling(14).mean()/atr.replace(0,np.nan)
    dx=(df["plus_di"]-df["minus_di"]).abs()/(df["plus_di"]+df["minus_di"]+1e-9)*100
    df["adx"]=dx.rolling(14).mean()
    df["vol_ratio"]=v/v.rolling(20).mean()
    return df

df = add_indicators(df)
df["next_ret"] = df["close"].shift(-HOLD_DAYS) / df["close"] - 1
df = df.dropna().reset_index(drop=True)

split = int(len(df) * TRAIN_RATIO)
train = df.iloc[:split].copy()
test  = df.iloc[split:].copy()
print(f"학습 구간: {train['date'].min().date()} ~ {train['date'].max().date()}  ({len(train)}일)")
print(f"검증 구간: {test['date'].min().date()}  ~ {test['date'].max().date()}  ({len(test)}일)")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 검증 1: 지표별 예측력 (Point-Biserial)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n[검증 1] 지표별 수익 예측력 (상관계수)")
print("-" * 45)
indicators = {
    "RSI14":        "rsi14",
    "MACD_hist":    "macd_hist",
    "BB_%":         "bb_pct",
    "Stoch14":      "stoch14",
    "ADX":          "adx",
    "Vol_Ratio":    "vol_ratio",
    "+DI":          "plus_di",
}
pred_results = {}
for name, col in indicators.items():
    if col not in train.columns: continue
    corr, pval = stats.pearsonr(train[col].fillna(0), train["next_ret"].fillna(0))
    pred_results[name] = {"corr": corr, "pval": pval}
    sig = "★ 유의" if pval < 0.05 else "  무의"
    print(f"  {name:<14}: r={corr:+.4f}  p={pval:.4f}  {sig}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 검증 2: 베스트 전략 워크포워드 검증
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n[검증 2] 워크포워드: 학습→검증 성과 비교")
print("-" * 45)

def strategy_signal(df):
    """베스트 조합: 가격_SMA50_위 + BB_하단터치 + Stoch_과매도"""
    s = (
        (df["close"] > df["sma50"]) &
        (df["bb_pct"] < 0.2) &
        (df["stoch14"] < 20)
    ).astype(int)
    return s

def backtest_strategy(df, signal_col, fee=FEE_RATE, slip=SLIPPAGE):
    """신호 발생 후 HOLD_DAYS 보유 수익률 계산"""
    results = []
    for i in df.index[df[signal_col] == 1]:
        fut = i + HOLD_DAYS
        if fut >= len(df): continue
        entry = df.loc[i, "close"] * (1 + slip)
        exit_ = df.loc[fut, "close"] * (1 - slip)
        ret = (exit_ - entry) / entry - 2*fee
        results.append(ret)
    return np.array(results)

train["signal"] = strategy_signal(train).values
test["signal"]  = strategy_signal(test).values

train_rets = backtest_strategy(train, "signal")
test_rets  = backtest_strategy(test,  "signal")

def stats_summary(rets, label):
    if len(rets) == 0:
        print(f"  {label}: 신호 없음")
        return {}
    wr  = (rets > 0).mean()
    avg = rets.mean()
    tot = (1 + rets).prod() - 1
    sr  = rets.mean() / (rets.std() + 1e-9) * np.sqrt(252/HOLD_DAYS)
    md  = (np.maximum.accumulate(np.cumprod(1+rets)) - np.cumprod(1+rets)).max()
    print(f"  {label}: 신호수={len(rets):3d}  승률={wr*100:.1f}%  "
          f"평균수익={avg*100:.2f}%  총수익={tot*100:.1f}%  "
          f"샤프={sr:.2f}  MDD={md*100:.1f}%")
    return {"n":len(rets),"wr":wr,"avg":avg,"total":tot,"sharpe":sr,"mdd":md}

ts = stats_summary(train_rets, "학습구간")
vs = stats_summary(test_rets,  "검증구간")

consistency = "✅ 일관성 확인" if (vs.get("wr",0) >= 0.60 and vs.get("total",0) > 0) else "⚠️  과적합 의심"
print(f"\n  판정: {consistency}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 검증 3: 바이앤홀드 비교
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n[검증 3] 전략 vs 바이앤홀드 (검증구간)")
print("-" * 45)

bnh_ret = test["close"].iloc[-1] / test["close"].iloc[0] - 1
strat_total = vs.get("total", 0)
win = "✅ 전략 우위" if strat_total > bnh_ret else "❌ BnH가 더 좋음"
print(f"  바이앤홀드:  {bnh_ret*100:.1f}%")
print(f"  전략 총수익: {strat_total*100:.1f}%  ({win})")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 검증 4: 랜덤 전략 대비 (몬테카를로)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print(f"\n[검증 4] 몬테카를로 ({MONTE_N}회): 랜덤 vs 전략")
print("-" * 45)

n_signals = max(len(test_rets), 5)
all_returns = test["next_ret"].dropna().values

random_totals = []
for _ in range(MONTE_N):
    sample = np.random.choice(all_returns, size=n_signals, replace=True)
    cost   = (2*FEE_RATE + 2*SLIPPAGE) * n_signals
    total  = (1 + sample).prod() - 1 - cost
    random_totals.append(total)

random_totals = np.array(random_totals)
pct_beat = (strat_total > random_totals).mean()
random_mean = random_totals.mean()
print(f"  랜덤 평균 총수익: {random_mean*100:.1f}%")
print(f"  전략 총수익:      {strat_total*100:.1f}%")
print(f"  랜덤 전략 이김:   {pct_beat*100:.1f}%")
mc_judge = "✅ 통계적 우위" if pct_beat >= 0.6 else "⚠️  우위 불충분"
print(f"  판정: {mc_judge}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 검증 5: 누적 자산곡선 시뮬레이션
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print(f"\n[검증 5] 초기 자본 $10,000 실전 시뮬레이션")
print("-" * 45)

CAPITAL = 10_000
capital = CAPITAL
peak    = CAPITAL
max_dd  = 0
history = [CAPITAL]
trade_log = []

for i in test.index:
    if test.loc[i,"signal"] != 1: continue
    fut = i + HOLD_DAYS
    if fut >= len(test): break
    entry = test.loc[i,"close"] * (1 + SLIPPAGE)
    exit_ = test.loc[fut,"close"] * (1 - SLIPPAGE)
    size  = capital * 0.3        # 자본의 30%만 투입
    ret   = (exit_-entry)/entry - 2*FEE_RATE
    pnl   = size * ret
    capital += pnl
    peak = max(peak, capital)
    dd   = (peak - capital)/peak
    max_dd = max(max_dd, dd)
    history.append(capital)
    trade_log.append({"ret":ret,"capital":capital,"pnl":pnl})

final_return = (capital - CAPITAL)/CAPITAL
print(f"  초기 자본:   ${CAPITAL:,.0f}")
print(f"  최종 자산:   ${capital:,.0f}")
print(f"  총 수익률:   {final_return*100:.1f}%")
print(f"  최대 낙폭:   {max_dd*100:.1f}%")
print(f"  총 거래수:   {len(trade_log)}회")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 종합 판정
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n" + "=" * 60)
print("  종합 가설 검증 결과")
print("=" * 60)

checks = {
    "지표 예측력 존재":   any(v["pval"] < 0.05 for v in pred_results.values()),
    "학습→검증 일관성":  vs.get("wr",0) >= 0.60,
    "랜덤 대비 우위":    pct_beat >= 0.55,
    "양(+) 수익 달성":   final_return > 0,
    "MDD 50% 미만":      max_dd < 0.5,
}

passed = sum(checks.values())
for item, ok in checks.items():
    print(f"  {'✅' if ok else '❌'} {item}")

print(f"\n  통과: {passed}/5")
if passed >= 4:
    verdict = "✅ 가설 채택 — 전략 유효성 확인, 실전 진행 권장"
elif passed >= 3:
    verdict = "⚠️  조건부 채택 — 전략 개선 후 진행 권장"
else:
    verdict = "❌ 가설 기각 — 전략 재설계 필요"
print(f"\n  최종 판정: {verdict}")
print("=" * 60)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 시각화
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 한글 폰트
import matplotlib.font_manager as fm
for font in ["NanumGothic","DejaVu Sans"]:
    if font in {f.name for f in fm.fontManager.ttflist}:
        plt.rcParams["font.family"] = font
        break
plt.rcParams["axes.unicode_minus"] = False

BG  = "#0d1117"; FG  = "#e6edf3"; GRID = "#30363d"
GREEN = "#2ecc71"; RED = "#e74c3c"; BLUE = "#3498db"; YELLOW = "#f1c40f"

fig = plt.figure(figsize=(18, 22), facecolor=BG)
fig.suptitle("BTC 퀀트 가설 검증 시뮬레이션", fontsize=20,
             fontweight="bold", color=FG, y=0.98)
gs = gridspec.GridSpec(3, 2, hspace=0.45, wspace=0.35,
                       top=0.95, bottom=0.04, left=0.08, right=0.97)

def ax_style(ax, title):
    ax.set_facecolor(BG)
    ax.set_title(title, color=FG, fontsize=12, fontweight="bold", pad=10)
    ax.tick_params(colors=FG, labelsize=9)
    for sp in ax.spines.values(): sp.set_edgecolor(GRID)
    ax.grid(color=GRID, linewidth=0.5, linestyle="--", alpha=0.7)
    ax.xaxis.label.set_color(FG); ax.yaxis.label.set_color(FG)

# ── 1. BTC 가격 + 신호 ─────────────────────────
ax1 = fig.add_subplot(gs[0, :])
ax_style(ax1, "BTC 가격 & 전략 진입 신호 (검증 구간)")
ax1.plot(test["date"], test["close"], color=BLUE, linewidth=1.2, label="BTC 종가")
sig_dates  = test[test["signal"] == 1]["date"]
sig_prices = test[test["signal"] == 1]["close"]
ax1.scatter(sig_dates, sig_prices, color=YELLOW, s=60, zorder=5,
            label=f"매수 신호 ({len(sig_dates)}회)", marker="^")
ax1.set_ylabel("가격 (USD)")
ax1.legend(facecolor=BG, edgecolor=GRID, labelcolor=FG, fontsize=9)
ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x,_: f"${x:,.0f}"))

# ── 2. 누적 자산 곡선 ─────────────────────────
ax2 = fig.add_subplot(gs[1, 0])
ax_style(ax2, "누적 자산 곡선 ($10,000 시작)")
equity = np.array(history)
bnh_equity = CAPITAL * test["close"].values[:len(equity)] / test["close"].values[0]
ax2.plot(range(len(equity)), equity, color=GREEN, linewidth=2, label="전략")
ax2.plot(range(len(bnh_equity)), bnh_equity, color=BLUE, linewidth=1.5,
         linestyle="--", label="바이앤홀드", alpha=0.7)
ax2.axhline(CAPITAL, color=FG, linewidth=0.8, linestyle=":", alpha=0.5)
ax2.set_ylabel("자산 (USD)")
ax2.legend(facecolor=BG, edgecolor=GRID, labelcolor=FG, fontsize=9)
ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x,_: f"${x:,.0f}"))

# ── 3. 몬테카를로 분포 ─────────────────────────
ax3 = fig.add_subplot(gs[1, 1])
ax_style(ax3, f"몬테카를로 ({MONTE_N}회): 랜덤 vs 전략")
ax3.hist(random_totals*100, bins=60, color=BLUE, alpha=0.7, label="랜덤 전략 분포")
ax3.axvline(strat_total*100, color=YELLOW, linewidth=2.5,
            linestyle="--", label=f"우리 전략 ({strat_total*100:.1f}%)")
ax3.axvline(random_mean*100, color=RED, linewidth=1.5,
            linestyle=":", label=f"랜덤 평균 ({random_mean*100:.1f}%)")
ax3.set_xlabel("총 수익률 (%)")
ax3.set_ylabel("빈도")
ax3.text(0.97, 0.95, f"상위 {(1-pct_beat)*100:.0f}%",
         transform=ax3.transAxes, ha="right", va="top", color=YELLOW, fontsize=11,
         fontweight="bold")
ax3.legend(facecolor=BG, edgecolor=GRID, labelcolor=FG, fontsize=8)

# ── 4. 학습 vs 검증 승률 비교 ─────────────────
ax4 = fig.add_subplot(gs[2, 0])
ax_style(ax4, "학습 vs 검증 구간 성과 비교")
categories = ["승률", "평균수익률(%)", "샤프비율"]
tr_vals = [ts.get("wr",0)*100, ts.get("avg",0)*100, ts.get("sharpe",0)]
va_vals = [vs.get("wr",0)*100, vs.get("avg",0)*100, vs.get("sharpe",0)]
x = np.arange(len(categories))
w = 0.35
ax4.bar(x-w/2, tr_vals, w, color=GREEN, alpha=0.8, label="학습 구간")
ax4.bar(x+w/2, va_vals, w, color=BLUE,  alpha=0.8, label="검증 구간")
ax4.set_xticks(x); ax4.set_xticklabels(categories, fontsize=9)
ax4.legend(facecolor=BG, edgecolor=GRID, labelcolor=FG, fontsize=9)
ax4.axhline(0, color=FG, linewidth=0.8)
for i,(tv,vv) in enumerate(zip(tr_vals,va_vals)):
    ax4.text(i-w/2, tv+0.3, f"{tv:.1f}", ha="center", color=FG, fontsize=8)
    ax4.text(i+w/2, vv+0.3, f"{vv:.1f}", ha="center", color=FG, fontsize=8)

# ── 5. 종합 판정 스코어카드 ───────────────────
ax5 = fig.add_subplot(gs[2, 1])
ax5.set_facecolor(BG)
ax5.set_title("종합 가설 검증 스코어카드", color=FG, fontsize=12,
              fontweight="bold", pad=10)
ax5.axis("off")
for sp in ax5.spines.values(): sp.set_edgecolor(GRID)

y_pos = 0.90
for item, ok in checks.items():
    icon  = "✅" if ok else "❌"
    color = GREEN if ok else RED
    ax5.text(0.05, y_pos, icon,  transform=ax5.transAxes,
             fontsize=14, va="center", color=color)
    ax5.text(0.18, y_pos, item, transform=ax5.transAxes,
             fontsize=10, va="center", color=FG)
    y_pos -= 0.16

ax5.text(0.5, 0.08, f"통과 {passed}/5  |  {verdict[:8]}",
         transform=ax5.transAxes, fontsize=11, ha="center", va="center",
         color=GREEN if passed>=4 else (YELLOW if passed>=3 else RED),
         fontweight="bold")

plt.savefig(OUT_FILE, dpi=150, bbox_inches="tight", facecolor=BG)
plt.close()
print(f"\n차트 저장 → {OUT_FILE}")
