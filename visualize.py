"""
visualize.py
백테스트 분석 결과를 시각화하여 charts/결과.png 저장

그래프 구성 (2×3 레이아웃):
  1. 상위 20개 조합 승률 바 차트
  2. 승률 vs 발생횟수 산점도
  3. 핵심 지표 중요도 (수평 바)
  4. 지표 수별 승률 분포 (박스플롯)
  5. 상위 10개 조합 평균수익률
  6. 복합점수 상위 15개 히트맵 스타일
"""

import os
import sys
import textwrap
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")   # GUI 없는 환경에서도 동작
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patches as mpatches
from collections import Counter

# ── 경로 설정 ──────────────────────────────────
ROOT        = os.path.dirname(__file__)
BACKTEST_FILE = os.path.join(ROOT, "backtest_results.csv")
OUTPUT_DIR  = os.path.join(ROOT, "charts")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "결과.png")

# ── 한글 폰트 설정 ─────────────────────────────
def set_korean_font():
    font_candidates = [
        "NanumGothic", "NanumBarunGothic", "Malgun Gothic",
        "AppleGothic", "DejaVu Sans",
    ]
    available = {f.name for f in fm.fontManager.ttflist}
    for font in font_candidates:
        if font in available:
            plt.rcParams["font.family"] = font
            plt.rcParams["axes.unicode_minus"] = False
            return font
    # 시스템 폰트 직접 탐색
    for path in ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts")]:
        if os.path.isdir(path):
            for root, _, files in os.walk(path):
                for f in files:
                    if f.lower().endswith((".ttf", ".otf")) and "gothic" in f.lower():
                        fp = fm.FontProperties(fname=os.path.join(root, f))
                        plt.rcParams["font.family"] = fp.get_name()
                        plt.rcParams["axes.unicode_minus"] = False
                        return fp.get_name()
    plt.rcParams["axes.unicode_minus"] = False
    return "default"


def load_and_filter(min_win_rate=0.70, min_count=20) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.read_csv(BACKTEST_FILE)
    top = df[(df["승률"] >= min_win_rate) & (df["발생횟수"] >= min_count)].copy()
    top["복합점수"] = (top["승률"] * np.log1p(top["발생횟수"])).round(4)
    top = top.sort_values("복합점수", ascending=False).reset_index(drop=True)
    return df, top


def extract_indicators(top: pd.DataFrame) -> pd.DataFrame:
    counter: Counter = Counter()
    for _, row in top.iterrows():
        for ind in [s.strip() for s in row["조합"].split(" + ")]:
            counter[ind] += row["승률"]
    idf = pd.DataFrame(counter.most_common(15), columns=["지표", "가중점수"])
    return idf


def shorten(label: str, width: int = 20) -> str:
    return "\n".join(textwrap.wrap(label, width))


def draw(df: pd.DataFrame, top: pd.DataFrame, idf: pd.DataFrame):
    font_name = set_korean_font()
    print(f"  사용 폰트: {font_name}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    PALETTE   = ["#2ecc71", "#3498db", "#9b59b6", "#e74c3c", "#f39c12",
                  "#1abc9c", "#e67e22", "#34495e"]
    BG_COLOR  = "#0d1117"
    TEXT_COLOR = "#e6edf3"
    GRID_COLOR = "#30363d"

    fig = plt.figure(figsize=(20, 26), facecolor=BG_COLOR)
    fig.suptitle(
        "BTC 퀀트 트레이딩 봇  —  백테스트 분석 결과",
        fontsize=22, fontweight="bold", color=TEXT_COLOR, y=0.98
    )

    gs = fig.add_gridspec(3, 2, hspace=0.45, wspace=0.35,
                          top=0.95, bottom=0.04, left=0.07, right=0.97)

    def style_ax(ax, title):
        ax.set_facecolor(BG_COLOR)
        ax.set_title(title, color=TEXT_COLOR, fontsize=13, pad=10, fontweight="bold")
        ax.tick_params(colors=TEXT_COLOR, labelsize=9)
        ax.xaxis.label.set_color(TEXT_COLOR)
        ax.yaxis.label.set_color(TEXT_COLOR)
        for spine in ax.spines.values():
            spine.set_edgecolor(GRID_COLOR)
        ax.grid(axis="y", color=GRID_COLOR, linewidth=0.5, linestyle="--")
        return ax

    # ─── 1. 상위 20개 조합 승률 바 차트 ──────────
    ax1 = fig.add_subplot(gs[0, :])
    style_ax(ax1, f"상위 조합 승률  (70%+ / 발생 {20}회+)")
    n = min(20, len(top))
    sub = top.head(n)
    labels = [shorten(r["조합"], 28) for _, r in sub.iterrows()]
    bars = ax1.barh(range(n), sub["승률"] * 100, color=PALETTE[0], alpha=0.85, height=0.65)
    ax1.set_yticks(range(n))
    ax1.set_yticklabels(labels, fontsize=8)
    ax1.invert_yaxis()
    ax1.set_xlabel("승률 (%)")
    ax1.axvline(70, color="#e74c3c", linewidth=1.5, linestyle="--", alpha=0.8, label="70% 기준선")
    ax1.legend(facecolor=BG_COLOR, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=9)
    for i, bar in enumerate(bars):
        w = bar.get_width()
        cnt = sub.iloc[i]["발생횟수"]
        ax1.text(w + 0.3, bar.get_y() + bar.get_height()/2,
                 f"{w:.1f}%  (n={int(cnt)})",
                 va="center", ha="left", color=TEXT_COLOR, fontsize=8)
    ax1.set_xlim(0, max(sub["승률"].max() * 100 + 10, 85))

    # ─── 2. 승률 vs 발생횟수 산점도 ───────────────
    ax2 = fig.add_subplot(gs[1, 0])
    style_ax(ax2, "승률 vs 발생횟수 산점도")
    sc = ax2.scatter(
        df["발생횟수"], df["승률"] * 100,
        c=df["승률"], cmap="RdYlGn", alpha=0.5, s=18, vmin=0.4, vmax=1.0
    )
    if not top.empty:
        ax2.scatter(top["발생횟수"], top["승률"] * 100,
                    color="#f1c40f", s=50, zorder=5, label="70%+ 조합", edgecolors="white", linewidths=0.5)
    ax2.axhline(70, color="#e74c3c", linewidth=1.2, linestyle="--", alpha=0.8)
    ax2.axvline(20, color="#3498db", linewidth=1.2, linestyle="--", alpha=0.8)
    ax2.set_xlabel("발생횟수")
    ax2.set_ylabel("승률 (%)")
    ax2.legend(facecolor=BG_COLOR, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=9)
    cb = fig.colorbar(sc, ax=ax2, pad=0.02)
    cb.ax.tick_params(colors=TEXT_COLOR)
    cb.set_label("승률", color=TEXT_COLOR, fontsize=9)

    # ─── 3. 핵심 지표 중요도 ──────────────────────
    ax3 = fig.add_subplot(gs[1, 1])
    style_ax(ax3, "핵심 지표 중요도 (상위 15개)")
    if not idf.empty:
        colors = [PALETTE[i % len(PALETTE)] for i in range(len(idf))]
        idf_s = idf.sort_values("가중점수")
        ax3.barh(range(len(idf_s)), idf_s["가중점수"], color=colors, alpha=0.85, height=0.65)
        ax3.set_yticks(range(len(idf_s)))
        ax3.set_yticklabels([shorten(x, 22) for x in idf_s["지표"]], fontsize=8)
        ax3.set_xlabel("가중 등장 점수 (승률 × 등장 횟수)")
        ax3.grid(axis="x", color=GRID_COLOR, linewidth=0.5, linestyle="--")
        ax3.grid(axis="y", color="none")

    # ─── 4. 지표 수별 승률 분포 ───────────────────
    ax4 = fig.add_subplot(gs[2, 0])
    style_ax(ax4, "지표 조합 수별 승률 분포")
    data_by_n = []
    labels_n  = []
    for n_ind in [1, 2, 3]:
        sub = df[df["지표수"] == n_ind]["승률"] * 100
        if not sub.empty:
            data_by_n.append(sub.values)
            labels_n.append(f"{n_ind}개 조합\n(n={len(sub)})")
    if data_by_n:
        bp = ax4.boxplot(
            data_by_n, tick_labels=labels_n, patch_artist=True,
            medianprops=dict(color="white", linewidth=2),
            boxprops=dict(facecolor=PALETTE[1], alpha=0.7),
            whiskerprops=dict(color=TEXT_COLOR),
            capprops=dict(color=TEXT_COLOR),
            flierprops=dict(marker="o", color=PALETTE[3], alpha=0.4, markersize=3),
        )
        for patch, color in zip(bp["boxes"], PALETTE):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
    ax4.axhline(70, color="#e74c3c", linewidth=1.2, linestyle="--", alpha=0.8)
    ax4.set_ylabel("승률 (%)")

    # ─── 5. 상위 10개 평균 수익률 ─────────────────
    ax5 = fig.add_subplot(gs[2, 1])
    style_ax(ax5, "상위 10개 조합 평균 수익률 (%)")
    n = min(10, len(top))
    sub = top.head(n)
    ret_vals = sub["평균수익률"] * 100
    colors5  = [PALETTE[0] if v >= 0 else PALETTE[3] for v in ret_vals]
    bars5 = ax5.barh(range(n), ret_vals, color=colors5, alpha=0.85, height=0.65)
    ax5.set_yticks(range(n))
    ax5.set_yticklabels([shorten(r["조합"], 25) for _, r in sub.iterrows()], fontsize=8)
    ax5.invert_yaxis()
    ax5.axvline(0, color=TEXT_COLOR, linewidth=0.8)
    ax5.set_xlabel("평균 수익률 (%)")
    for bar, v in zip(bars5, ret_vals):
        ax5.text(v + (0.05 if v >= 0 else -0.05),
                 bar.get_y() + bar.get_height()/2,
                 f"{v:.2f}%", va="center",
                 ha="left" if v >= 0 else "right",
                 color=TEXT_COLOR, fontsize=8)

    plt.savefig(OUTPUT_FILE, dpi=150, bbox_inches="tight", facecolor=BG_COLOR)
    plt.close()
    print(f"  저장 완료 → {OUTPUT_FILE}")


def run_visualization():
    print(f"[시각화] 백테스트 결과 로딩: {BACKTEST_FILE}")
    if not os.path.exists(BACKTEST_FILE):
        print("[오류] backtest_results.csv 없음. 먼저 backtest.py를 실행하세요.")
        sys.exit(1)

    df, top = load_and_filter()
    print(f"  전체 조합: {len(df)}개  /  70%+ 조합: {len(top)}개")

    idf = extract_indicators(top) if not top.empty else pd.DataFrame(columns=["지표", "가중점수"])
    draw(df, top, idf)
    print("[시각화 완료]")


if __name__ == "__main__":
    run_visualization()
