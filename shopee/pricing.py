"""국가별 판매가 계산.

원리: 판매가 P 에서 수수료(%)와 마진(%)을 떼고 남은 돈이 원가를 덮어야 한다.
    P × (1 - 수수료율 - 마진율) = 원가(현지통화)
    → P = 원가 / (1 - 수수료율 - 마진율)
여기에 "건당 최소 이익" 조건을 하나 더 걸고, 둘 중 큰 가격을 쓴다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict

import requests


@dataclass
class PriceResult:
    market: str
    currency: str
    price: float          # 현지 판매가
    cost_krw: int         # 원가 합계 (상품 + 국내배송 + 국제배송)
    fees_krw: int         # 쇼피 수수료 (원화 환산)
    profit_krw: int       # 예상 이익
    margin_rate: float    # 판매가 대비 이익률
    fx: float             # 1 현지통화 = ? KRW

    def to_dict(self) -> dict:
        return asdict(self)


def fetch_fx(markets: dict, api_url: str | None) -> dict[str, float]:
    """현지통화 1단위가 몇 원인지 반환. API 실패 시 config 의 fx_fallback 사용."""
    rates: dict[str, float] = {}
    if api_url:
        try:
            data = requests.get(api_url, timeout=10).json()
            per_krw = data.get("rates", {})  # 1 KRW = ? 현지통화
            for code, m in markets.items():
                r = per_krw.get(m["currency"])
                if r:
                    rates[code] = 1 / r
        except (requests.RequestException, ValueError):
            pass
    for code, m in markets.items():
        rates.setdefault(code, float(m["fx_fallback"]))
    return rates


def shipping_krw(market: dict, weight_g: int) -> int:
    steps = math.ceil(max(weight_g, 1) / 100)
    return int(market["ship_base_krw"] + market["ship_per_100g_krw"] * steps)


def round_up(value: float, step: float) -> float:
    # 부동소수점 오차(예: 12.300000001 → 12.4) 방지용 미세 보정
    rounded = math.ceil(value / step - 1e-9) * step
    return round(rounded, 2) if step < 1 else float(int(rounded))


def calc_price(
    *,
    code: str,
    market: dict,
    pricing: dict,
    fx: float,
    cost_krw: int,
    domestic_ship_krw: int,
    weight_g: int,
) -> PriceResult:
    fee_rate = market["commission_rate"] + market["transaction_fee_rate"] + market["service_fee_rate"]
    total_cost = cost_krw + domestic_ship_krw + shipping_krw(market, weight_g)
    buffered = total_cost * (1 + pricing["fx_buffer_rate"])

    margin = pricing["target_margin_rate"]
    if fee_rate + margin >= 1:
        raise ValueError(f"{code}: 수수료율+마진율이 100% 이상입니다")

    # 조건 1: 목표 마진율
    by_margin = buffered / fx / (1 - fee_rate - margin)
    # 조건 2: 건당 최소 이익
    by_min_profit = (buffered + pricing["min_profit_krw"]) / fx / (1 - fee_rate)

    price = round_up(max(by_margin, by_min_profit), market["price_step"])
    revenue_krw = price * fx
    fees_krw = revenue_krw * fee_rate
    profit_krw = revenue_krw - fees_krw - total_cost

    return PriceResult(
        market=code,
        currency=market["currency"],
        price=price,
        cost_krw=int(total_cost),
        fees_krw=int(round(fees_krw)),
        profit_krw=int(round(profit_krw)),
        margin_rate=round(profit_krw / revenue_krw, 4),
        fx=round(fx, 6),
    )
