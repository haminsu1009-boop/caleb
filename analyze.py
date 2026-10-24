"""
analyze.py
backtest_results.csv에서 승률 70% 이상 + 발생횟수 20회 이상 조합 분석
- 상위 조합 출력
- 어떤 지표들이 공통적으로 나타나는지 분석
"""

import os
import pandas as pd
import numpy as np
from collections import Counter

BACKTEST_FILE = os.path.join(os.path.dirname(__file__), "backtest_results.csv")

MIN_WIN_RATE    = 0.70
MIN_OCCURRENCES = 20


def load_results() -> pd.DataFrame:
    if not os.path.exists(BACKTEST_FILE):
        raise FileNotFoundError(
            f"백테스트 결과 파일 없음: {BACKTEST_FILE}\n"
            "먼저 backtest.py를 실행하세요."
        )
    df = pd.read_csv(BACKTEST_FILE)
    return df


def filter_top(df: pd.DataFrame) -> pd.DataFrame:
    """승률 ≥ 70% AND 발생횟수 ≥ 20인 조합 필터"""
    filtered = df[
        (df["승률"] >= MIN_WIN_RATE) &
        (df["발생횟수"] >= MIN_OCCURRENCES)
    ].copy()
    filtered = filtered.sort_values(["승률", "발생횟수"], ascending=False).reset_index(drop=True)
    return filtered


def extract_indicator_names(combo_str: str) -> list[str]:
    """'A + B + C' 형태 문자열에서 지표 이름 파싱"""
    return [s.strip() for s in combo_str.split(" + ")]


def analyze_common_indicators(top_df: pd.DataFrame) -> pd.DataFrame:
    """상위 조합에서 자주 등장하는 지표 카운트"""
    counter: Counter = Counter()
    for _, row in top_df.iterrows():
        indicators = extract_indicator_names(row["조합"])
        # 승률 가중치 적용
        weight = row["승률"]
        for ind in indicators:
            counter[ind] += weight

    indicator_df = pd.DataFrame(
        counter.most_common(),
        columns=["지표", "가중_등장횟수"]
    )
    indicator_df["가중_등장횟수"] = indicator_df["가중_등장횟수"].round(2)
    return indicator_df


def score_combo(row: pd.Series) -> float:
    """승률 × log(발생횟수) 복합 점수"""
    return row["승률"] * np.log1p(row["발생횟수"])


def run_analysis() -> dict:
    print("=" * 60)
    print("  퀀트 트레이딩 봇 - 백테스트 결과 분석")
    print("=" * 60)

    df = load_results()
    print(f"\n전체 조합 수: {len(df):,}개")
    print(f"필터 조건: 승률 ≥ {MIN_WIN_RATE*100:.0f}%  &  발생횟수 ≥ {MIN_OCCURRENCES}회\n")

    top_df = filter_top(df)
    print(f"조건 충족 조합: {len(top_df)}개\n")

    if top_df.empty:
        print("[결과] 조건을 만족하는 조합이 없습니다.")
        print("  backtest.py를 재실행하거나 데이터를 확인하세요.")
        return {"top": top_df, "indicators": pd.DataFrame()}

    # 복합 점수로 정렬
    top_df["복합점수"] = top_df.apply(score_combo, axis=1).round(4)
    top_df = top_df.sort_values("복합점수", ascending=False).reset_index(drop=True)

    # ── 상위 20개 출력 ─────────────────────────
    print("▶ 상위 조합 (승률 내림차순)")
    print("-" * 60)
    display_cols = ["조합", "발생횟수", "승률", "평균수익률", "복합점수"]
    pd.set_option("display.max_colwidth", 60)
    pd.set_option("display.width", 120)
    print(top_df[display_cols].head(20).to_string(index=True))

    # ── 지표 중요도 ────────────────────────────
    print("\n▶ 핵심 지표 (가중 등장 빈도순)")
    print("-" * 60)
    indicator_df = analyze_common_indicators(top_df)
    print(indicator_df.head(15).to_string(index=False))

    # ── 지표별 설명 ────────────────────────────
    print("\n▶ 상위 지표 해석")
    print("-" * 60)
    descriptions = {
        "RSI14_과매도(30이하)":    "RSI(14) < 30 → 극단적 과매도 구간, 반등 기대",
        "RSI14_과매도(35이하)":    "RSI(14) < 35 → 과매도 초기 진입",
        "RSI7_과매도(25이하)":     "단기 RSI(7) 급락, 빠른 반등 신호",
        "MACD_골든크로스":         "MACD선이 시그널선 상향 돌파 → 상승 전환 신호",
        "MACD_히스토_전환(+)":     "MACD 히스토그램이 음→양 전환 → 모멘텀 전환",
        "BB_하단터치(2σ)":         "볼린저 밴드 하단(2σ) 이탈 → 과매도 영역",
        "BB_%B_과매도(0.2이하)":   "%B 지표 0.2 이하 → 밴드 하단 근접",
        "STOCH14_과매도(20이하)":  "스토캐스틱K(14) < 20 → 과매도 구간",
        "STOCH14_골든크로스":      "스토캐스틱K가 D선 상향 돌파 → 반등 신호",
        "ADX14_강세(25이상)":      "ADX > 25 → 추세 강도 확인",
        "ADX14_추세상승(+DI>-DI)": "+DI > -DI → 상승 추세 방향 확인",
        "거래량_급증(2배이상)":     "거래량이 20일 평균 대비 2배+ → 세력 개입",
        "SMA50_골든크로스(200)":   "50일 SMA가 200일 SMA 상향 돌파 → 중장기 골든크로스",
        "EMA20_골든크로스(50)":    "20일 EMA가 50일 EMA 상향 돌파 → 단기 추세 전환",
        "가격_SMA200_위":          "현재가 > 200일 SMA → 장기 상승 추세 확인",
        "OBV_SMA위":               "OBV가 20일 평균 위 → 매집 우위",
    }
    for ind in indicator_df.head(10)["지표"]:
        desc = descriptions.get(ind, "사용자 정의 신호")
        print(f"  • {ind}: {desc}")

    # ── 단일/2개/3개 조합별 통계 ──────────────
    print("\n▶ 지표 수별 통계")
    print("-" * 60)
    for n in [1, 2, 3]:
        sub = top_df[top_df["지표수"] == n]
        if not sub.empty:
            print(f"  {n}개 조합: {len(sub)}개  |  평균 승률: {sub['승률'].mean()*100:.1f}%  "
                  f"|  최고 승률: {sub['승률'].max()*100:.1f}%")

    print("\n[분석 완료]")
    return {"top": top_df, "indicators": indicator_df}


if __name__ == "__main__":
    run_analysis()
