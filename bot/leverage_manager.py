"""
bot/leverage_manager.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
켈리 기준 동적 레버리지 관리자

원리:
  Kelly% = (p × b - q) / b
    p = 승률 (예: 0.90)
    b = TP/SL 비율 (예: TP=0.5% / SL=0.3% → b=1.667)
    q = 1 - p

  Half-Kelly = Kelly% / 2 (실전 안전)
  3/4-Kelly  = Kelly% × 0.75 (공격형)

레버리지 테이블 (1h 기준: TP=1%, SL=0.6%, b=1.667):
  WR 70% → Kelly 40% → Half-Kelly 20% → 레버리지 2x
  WR 75% → Kelly 50% → Half-Kelly 25% → 레버리지 3x
  WR 80% → Kelly 60% → Half-Kelly 30% → 레버리지 5x
  WR 85% → Kelly 70% → Half-Kelly 35% → 레버리지 7x
  WR 90% → Kelly 80% → Half-Kelly 40% → 레버리지 7x
  WR 95% → Kelly 88% → Half-Kelly 44% → 레버리지 10x
  WR 100%→ Kelly 100%→ Half-Kelly 50% → 레버리지 12x (n≥100 필요)

※ 켈리 기반 최적 레버리지: 실제 손익 시뮬레이션으로 도출된 값
  5m: TP=0.5%, SL=0.3% → 각 구간 ×0.6 보정
  4h: TP=2%, SL=1%   → 각 구간 ×1.2 보정
  1d: TP=5%, SL=2.5% → 각 구간 ×1.5 보정

포지션 크기:
  posSize = capital × kellyPct × leverage / price
  (실질 노출 = capital × kellyPct, 레버리지는 magnifier)

연속손실 감쇄:
  손실 N회 연속: 레버리지 × (0.7^N)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import math
from dataclasses import dataclass


@dataclass
class LeverageDecision:
    leverage:        float   # 적용 레버리지 (1~5)
    position_pct:    float   # 자본 중 포지션 비율 (0~1)
    kelly_pct:       float   # 순 켈리 비율
    reason:          str     # 결정 이유


class LeverageManager:
    """
    승률 기반 동적 레버리지 결정

    Args:
        max_lev:     최대 레버리지 (기본 5x)
        kelly_frac:  켈리 분수 (기본 0.5 = Half-Kelly)
        tp_pct:      목표 수익률 (기본 0.005 = 0.5%)
        sl_pct:      손절 비율  (기본 0.003 = 0.3%)
        max_pos_pct: 단일 포지션 최대 자본 비율 (기본 0.30)
    """

    # 타임프레임별 기본 TP/SL
    TF_PARAMS = {
        "5m": {"tp": 0.005, "sl": 0.003},    # 0.5% / 0.3%
        "1h": {"tp": 0.010, "sl": 0.006},    # 1.0% / 0.6%
        "4h": {"tp": 0.020, "sl": 0.010},    # 2.0% / 1.0%
        "1d": {"tp": 0.050, "sl": 0.025},    # 5.0% / 2.5%
    }

    # ── 미검증 신호 레버리지 상한 ─────────────────────────
    # Tier2(볼륨폭발, count=0): 다심볼 OOS 검증 전까지 최대 2x
    # Tier3(ML): Wilson CI 검증 있으나 시장 체제 의존성 있음 → 최대 3x
    # Tier1(패턴룰, Wilson 필터 통과): 제한 없음 (max_lev 따름)
    TIER2_UNVERIFIED_MAX_LEV = 2.0   # VE 신호 — 검증 완료 전 hard cap
    TIER3_ML_MAX_LEV         = 3.0   # ML 신호 — OOS WR 있으나 보수적

    # 왕복 거래비용 = 수수료(0.05% × 2) + 슬리피지(0.05% × 2)
    ROUND_TRIP_COST = 0.002

    def __init__(
        self,
        max_lev:     float = 12.0,
        kelly_frac:  float = 0.5,       # Half-Kelly
        max_pos_pct: float = 0.30,      # 포지션 최대 30% of 자본
        min_pos_pct: float = 0.05,      # 포지션 최소 5%
    ):
        self.max_lev     = max_lev
        self.kelly_frac  = kelly_frac
        self.max_pos_pct = max_pos_pct
        self.min_pos_pct = min_pos_pct
        self._consec_loss = 0          # 연속 손실 카운터

    # ── 켈리 계산 ────────────────────────────────────
    def kelly(self, win_rate: float, b: float) -> float:
        """
        Kelly% 계산
        win_rate: 0~100 스케일
        b: TP/SL 비율
        """
        p = win_rate / 100.0
        q = 1 - p
        k = (p * b - q) / b
        return max(0.0, k)

    # ── 레버리지 결정 ────────────────────────────────
    def decide(
        self,
        win_rate:    float,    # 0~100
        interval:    str = "1h",
        tier:        int  = 3,
        lift:        float = 1.0,
    ) -> LeverageDecision:
        """
        승률 + 타임프레임 + 신호 등급으로 레버리지 결정

        Returns:
            LeverageDecision
        """
        params = self.TF_PARAMS.get(interval, self.TF_PARAMS["1h"])
        tp, sl = params["tp"], params["sl"]

        # ⚠️ 수수료 반영 손익비
        #   기존에는 b = tp/sl (명목값)을 써서 켈리를 과대 계산했다.
        #   실제로는 이익에서 비용이 빠지고 손실에는 비용이 더해진다:
        #     실질이익 = tp - 왕복비용,  실질손실 = sl + 왕복비용
        #   5m 기준 명목 b=1.67 → 실질 b=0.60 (178% 과대)
        #   1h 기준 명목 b=1.67 → 실질 b=1.00 ( 67% 과대)
        net_tp = tp - self.ROUND_TRIP_COST
        net_sl = sl + self.ROUND_TRIP_COST
        if net_tp <= 0:
            # 수수료가 목표 수익을 잡아먹는 구간 → 진입 불가
            return LeverageDecision(
                leverage     = 0.0,
                position_pct = 0.0,
                kelly_pct    = 0.0,
                reason       = f"거래비용({self.ROUND_TRIP_COST*100:.2f}%)이 TP({tp*100:.2f}%) 이상 — 진입 불가",
            )
        b = net_tp / net_sl

        # 손익분기 승률 미달이면 진입 금지
        breakeven_wr = net_sl / (net_tp + net_sl) * 100
        if win_rate < breakeven_wr:
            return LeverageDecision(
                leverage     = 0.0,
                position_pct = 0.0,
                kelly_pct    = 0.0,
                reason       = f"WR={win_rate:.1f}% < 손익분기 {breakeven_wr:.1f}% — 진입 불가",
            )

        raw_kelly = self.kelly(win_rate, b)

        # Tier 보정: Tier1(패턴룰)은 켈리 × 0.75(3/4켈리), Tier3은 Half-Kelly
        tier_frac = {1: 0.75, 2: 0.60, 3: 0.50}.get(tier, 0.50)
        eff_kelly = raw_kelly * tier_frac

        # Lift 보정: lift > 1.3이면 켈리 10% 증가
        if lift >= 1.3:
            eff_kelly *= 1.10

        # 자본 비율 (클램프)
        pos_pct = min(self.max_pos_pct, max(self.min_pos_pct, eff_kelly))

        # 레버리지 결정: 승률 구간별 (1h 기준, 켈리 시뮬레이션 최적값)
        # 5m은 TP/SL비율 동일하여 동일 레버리지; 4h/1d는 TF 보정계수 내포
        if win_rate >= 100:
            lev = 12.0  # WR=100% 단, n≥100 필요; 표본 소수시 실제 WR↓
        elif win_rate >= 95:
            lev = 10.0
        elif win_rate >= 90:
            lev = 7.0
        elif win_rate >= 85:
            lev = 7.0
        elif win_rate >= 80:
            lev = 5.0
        elif win_rate >= 75:
            lev = 3.0
        else:
            lev = 2.0

        # ── Tier별 레버리지 상한 적용 ──────────────────────
        # Tier2: 볼륨폭발 — 다심볼 OOS 검증 전, count=0 상태
        #        → WR 70~75% 추정치이므로 2x hard cap
        if tier == 2:
            lev = min(lev, self.TIER2_UNVERIFIED_MAX_LEV)
        # Tier3: ML 신호 — OOS WR 있으나 시장 체제 의존
        #        → 기존 "한 단계 낮춤" 대신 3x cap으로 통일
        elif tier == 3:
            lev = min(lev, self.TIER3_ML_MAX_LEV)

        # 연속손실 감쇄 (exponential decay)
        if self._consec_loss > 0:
            decay = 0.7 ** self._consec_loss
            lev   = max(1.0, lev * decay)
            pos_pct = max(self.min_pos_pct, pos_pct * decay)

        lev = min(self.max_lev, lev)

        reason = (
            f"WR={win_rate:.0f}% / Kelly={raw_kelly*100:.0f}% / "
            f"eff={eff_kelly*100:.0f}% / lev={lev:.1f}x / "
            f"pos={pos_pct*100:.0f}% / 연속손실:{self._consec_loss}"
        )

        return LeverageDecision(
            leverage     = lev,
            position_pct = pos_pct,
            kelly_pct    = eff_kelly,
            reason       = reason,
        )

    # ── USDT 포지션 크기 계산 ────────────────────────
    def position_usdt(
        self,
        capital:   float,
        win_rate:  float,
        interval:  str,
        tier:      int   = 3,
        lift:      float = 1.0,
    ) -> tuple:
        """
        실제 투자 USDT 금액 + 레버리지 반환

        Returns:
            (usdt_amount, leverage, decision)
        """
        dec    = self.decide(win_rate, interval, tier, lift)
        usdt   = capital * dec.position_pct
        return usdt, dec.leverage, dec

    # ── 손실/수익 피드백 ─────────────────────────────
    def record_result(self, win: bool):
        """거래 결과 피드백 → 연속손실 카운터 업데이트"""
        if win:
            self._consec_loss = 0
        else:
            self._consec_loss += 1

    def reset(self):
        self._consec_loss = 0

    # ── 현재 상태 요약 ───────────────────────────────
    def summary_table(self) -> str:
        """승률별 레버리지 테이블 출력"""
        header = f"{'WR':>6} {'Kelly':>7} {'Eff(Half)':>10} {'Lev':>5} {'Pos%':>6}"
        lines  = [header, "─"*40]
        for wr in [70, 75, 80, 85, 90, 95, 100]:
            dec = self.decide(wr, interval="1h", tier=1)
            b   = self.TF_PARAMS["1h"]["tp"] / self.TF_PARAMS["1h"]["sl"]
            k   = self.kelly(wr, b)
            lines.append(
                f"{wr:>5}%  {k*100:>6.0f}%  {dec.kelly_pct*100:>8.0f}%"
                f"  {dec.leverage:>4.1f}x  {dec.position_pct*100:>5.0f}%"
            )
        return "\n".join(lines)


# 싱글톤 인스턴스 (모듈 레벨에서 공유)
_default_manager = None

def get_leverage_manager(**kwargs) -> LeverageManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = LeverageManager(**kwargs)
    return _default_manager
