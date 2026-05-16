"""
백테스트 결과 필터링 + 시각화
- 승률 70% 이상, 발생횟수 20회 이상 조합 추출
- 결과를 charts/결과.png로 저장
"""

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
import os
import re
from collections import Counter

# 한글 폰트 설정 시도
def setup_korean_font():
    font_paths = [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            fm.fontManager.addfont(fp)
            prop = fm.FontProperties(fname=fp)
            plt.rcParams["font.family"] = prop.get_name()
            return True
    # fallback: use sans-serif
    plt.rcParams["font.family"] = "DejaVu Sans"
    return False

HAS_KOREAN = setup_korean_font()
plt.rcParams["axes.unicode_minus"] = False

RESULT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "backtest_results.csv")
CHART_PATH = os.path.join(os.path.dirname(__file__), "..", "charts", "결과.png")
FILTERED_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "filtered_top_combos.csv")

# 라벨 매핑 (한글 폰트 없을 경우 영어 사용)
LABELS = {
    "title_main": "Quant Backtest - Top Combinations" if not HAS_KOREAN else "퀀트 백테스트 - 고승률 조합 분석",
    "win_rate": "Win Rate (%)" if not HAS_KOREAN else "승률 (%)",
    "occurrences": "Occurrences" if not HAS_KOREAN else "발생횟수",
    "avg_return": "Avg Return (%)" if not HAS_KOREAN else "평균수익률 (%)",
    "top20": "Top 20 Combinations by Win Rate" if not HAS_KOREAN else "승률 상위 20개 조합",
    "scatter": "Win Rate vs Occurrences" if not HAS_KOREAN else "승률 vs 발생횟수",
    "indicators": "Most Frequent Indicators in Top Combos" if not HAS_KOREAN else "고승률 조합에 자주 등장하는 지표",
    "dist": "Win Rate Distribution (Filtered)" if not HAS_KOREAN else "승률 분포 (필터링 결과)",
    "combo": "Combination" if not HAS_KOREAN else "조합",
    "count": "Count" if not HAS_KOREAN else "등장횟수",
    "indicator": "Indicator" if not HAS_KOREAN else "지표",
}


def analyze():
    df = pd.read_csv(RESULT_PATH)
    print(f"전체 조합 수: {len(df)}")

    # 필터링: 승률 70%+ & 발생횟수 20회+
    filtered = df[(df["승률(%)"] >= 70) & (df["발생횟수"] >= 20)].copy()
    filtered = filtered.sort_values("승률(%)", ascending=False).reset_index(drop=True)
    print(f"승률 70%+ & 발생횟수 20회+ 조합: {len(filtered)}개")

    # 저장
    os.makedirs(os.path.dirname(FILTERED_PATH), exist_ok=True)
    filtered.to_csv(FILTERED_PATH, index=False, encoding="utf-8-sig")

    # --- 지표 빈도 분석 ---
    all_indicators = []
    for combo in filtered["구성지표"]:
        parts = [p.strip() for p in str(combo).split("+")]
        all_indicators.extend(parts)

    indicator_counts = Counter(all_indicators)
    top_indicators = indicator_counts.most_common(15)

    print("\n=== 고승률 조합에 자주 등장하는 지표 TOP 15 ===")
    for name, count in top_indicators:
        print(f"  {name}: {count}회")

    # --- 시각화 ---
    fig, axes = plt.subplots(2, 2, figsize=(20, 16))
    fig.suptitle(LABELS["title_main"], fontsize=18, fontweight="bold", y=0.98)

    # 1) 승률 상위 20개 바 차트
    ax1 = axes[0, 0]
    top20 = filtered.head(20)
    colors = plt.cm.RdYlGn(np.linspace(0.4, 1.0, len(top20)))
    bars = ax1.barh(range(len(top20)), top20["승률(%)"], color=colors)
    ax1.set_yticks(range(len(top20)))
    ax1.set_yticklabels(top20["조합"].str[:50], fontsize=7)
    ax1.set_xlabel(LABELS["win_rate"])
    ax1.set_title(LABELS["top20"], fontsize=12, fontweight="bold")
    ax1.invert_yaxis()
    for i, (wr, n) in enumerate(zip(top20["승률(%)"], top20["발생횟수"])):
        ax1.text(wr + 0.3, i, f"{wr:.1f}% (n={n})", va="center", fontsize=7)

    # 2) 승률 vs 발생횟수 산점도
    ax2 = axes[0, 1]
    scatter = ax2.scatter(
        filtered["발생횟수"], filtered["승률(%)"],
        c=filtered["평균수익률(%)"], cmap="RdYlGn",
        s=30, alpha=0.6, edgecolors="gray", linewidths=0.3
    )
    plt.colorbar(scatter, ax=ax2, label=LABELS["avg_return"])
    ax2.set_xlabel(LABELS["occurrences"])
    ax2.set_ylabel(LABELS["win_rate"])
    ax2.set_title(LABELS["scatter"], fontsize=12, fontweight="bold")
    ax2.axhline(y=80, color="red", linestyle="--", alpha=0.5, label="80%")
    ax2.axhline(y=70, color="orange", linestyle="--", alpha=0.5, label="70%")
    ax2.legend(fontsize=8)

    # 3) 지표 빈도 바 차트
    ax3 = axes[1, 0]
    ind_names = [x[0][:25] for x in top_indicators]
    ind_counts = [x[1] for x in top_indicators]
    colors3 = plt.cm.viridis(np.linspace(0.3, 0.9, len(ind_names)))
    ax3.barh(range(len(ind_names)), ind_counts, color=colors3)
    ax3.set_yticks(range(len(ind_names)))
    ax3.set_yticklabels(ind_names, fontsize=8)
    ax3.set_xlabel(LABELS["count"])
    ax3.set_title(LABELS["indicators"], fontsize=12, fontweight="bold")
    ax3.invert_yaxis()

    # 4) 승률 분포 히스토그램
    ax4 = axes[1, 1]
    ax4.hist(filtered["승률(%)"], bins=20, color="steelblue", edgecolor="white", alpha=0.8)
    ax4.set_xlabel(LABELS["win_rate"])
    ax4.set_ylabel(LABELS["count"])
    ax4.set_title(LABELS["dist"], fontsize=12, fontweight="bold")
    ax4.axvline(x=80, color="red", linestyle="--", alpha=0.7, label="80%")
    ax4.axvline(x=filtered["승률(%)"].median(), color="green", linestyle="--",
                alpha=0.7, label=f"Median: {filtered['승률(%)'].median():.1f}%")
    ax4.legend()

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    os.makedirs(os.path.dirname(CHART_PATH), exist_ok=True)
    fig.savefig(CHART_PATH, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\n차트 저장: {CHART_PATH}")

    # --- 상위 조합 상세 출력 ---
    print("\n" + "=" * 80)
    print("TOP 10 최고 승률 조합 (발생횟수 20회+)")
    print("=" * 80)
    for i, row in filtered.head(10).iterrows():
        print(f"\n[{i+1}위] {row['조합']}")
        print(f"    승률: {row['승률(%)']}%  |  발생횟수: {row['발생횟수']}회  |  평균수익률: {row['평균수익률(%)']}%")
        indicators = [x.strip() for x in str(row["구성지표"]).split("+")]
        print(f"    구성 지표: {', '.join(indicators)}")

    return filtered


if __name__ == "__main__":
    analyze()
