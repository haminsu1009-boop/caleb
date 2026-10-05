import hashlib
import hmac
from pathlib import Path

import pytest
import yaml

from shopee.listing_ai import ListingDraft, build_user_prompt
from shopee.pricing import calc_price, round_up, shipping_krw
from shopee.shopee_api import ShopeeClient, sign

CFG = yaml.safe_load((Path(__file__).parents[1] / "config.yaml").read_text())
MARKET = {
    "currency": "SGD", "price_step": 0.1, "commission_rate": 0.10,
    "transaction_fee_rate": 0.03, "service_fee_rate": 0.0,
    "ship_base_krw": 3000, "ship_per_100g_krw": 700,
}
PRICING = {"target_margin_rate": 0.20, "min_profit_krw": 3000, "fx_buffer_rate": 0.0}


def test_shipping_rounds_up_per_100g():
    assert shipping_krw(MARKET, 100) == 3700
    assert shipping_krw(MARKET, 101) == 4400


def test_round_up():
    assert round_up(12.31, 0.1) == 12.4
    assert round_up(12.3, 0.1) == 12.3
    assert round_up(25_001, 1000) == 26_000


def test_price_hits_target_margin():
    r = calc_price(code="SG", market=MARKET, pricing=PRICING, fx=1000,
                   cost_krw=10_000, domestic_ship_krw=0, weight_g=300)
    # 원가 10,000 + 배송 3,000+2,100 = 15,100원 → 15.1 SGD / (1-0.13-0.20) = 22.54 → 22.6
    assert r.cost_krw == 15_100
    assert r.price == 22.6
    assert r.margin_rate >= 0.20


def test_min_profit_wins_for_cheap_items():
    r = calc_price(code="SG", market=MARKET, pricing=PRICING, fx=1000,
                   cost_krw=1_000, domestic_ship_krw=0, weight_g=50)
    assert r.profit_krw >= 3000


def test_fee_plus_margin_over_100_rejected():
    with pytest.raises(ValueError):
        calc_price(code="SG", market=MARKET, pricing={**PRICING, "target_margin_rate": 0.9},
                   fx=1000, cost_krw=1000, domestic_ship_krw=0, weight_g=10)


def test_all_config_markets_price_cleanly():
    for code, m in CFG["markets"].items():
        r = calc_price(code=code, market=m, pricing=CFG["pricing"], fx=m["fx_fallback"],
                       cost_krw=9800, domestic_ship_krw=0, weight_g=320)
        assert r.profit_krw >= CFG["pricing"]["min_profit_krw"] * 0.95, code


def test_sign_matches_hmac_sha256():
    expected = hmac.new(b"key", b"123/api/v2/x1700000000tok456", hashlib.sha256).hexdigest()
    assert sign("key", 123, "/api/v2/x", 1700000000, "tok", 456) == expected


def test_auth_url_contains_signature(tmp_path):
    c = ShopeeClient(123, "key", token_file=tmp_path / "t.json")
    url = c.auth_url("https://example.com")
    assert url.startswith("https://partner.shopeemobile.com/api/v2/shop/auth_partner?")
    assert "sign=" in url and "partner_id=123" in url


def test_prompt_lists_every_market():
    markets = {k: v for k, v in CFG["markets"].items() if v["enabled"]}
    prompt = build_user_prompt({"name_ko": "토너", "weight_g": 300}, markets)
    for code in markets:
        assert f"- {code}:" in prompt


def test_listing_schema_round_trip():
    d = ListingDraft.model_validate({
        "risk_level": "caution", "risk_reasons_ko": ["화장품 등록 필요 가능"],
        "category_keywords_en": ["toner"],
        "markets": [{"market": "SG", "title": "t", "description": "d", "keywords": ["k"]}],
    })
    assert d.markets[0].market == "SG"
