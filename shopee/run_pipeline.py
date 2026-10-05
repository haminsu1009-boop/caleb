"""상품 CSV → 가격 계산 → AI 상품글 → (선택) 쇼피 업로드.

  # 1) 미리보기: 업로드 없이 결과 파일만 만든다 (기본값)
  python -m shopee.run_pipeline --input shopee/products.csv

  # 2) 실제 업로드: 처음엔 1개만
  python -m shopee.run_pipeline --input shopee/products.csv --live --limit 1
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from pathlib import Path

import anthropic
import yaml

from .listing_ai import generate_listing
from .pricing import calc_price, fetch_fx
from .shopee_api import ShopeeClient, ShopeeError

ROOT = Path(__file__).parent


def load_products(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in ("cost_krw", "domestic_ship_krw", "weight_g"):
            r[k] = int(float(r.get(k) or 0))
        r["image_urls"] = [u for u in (r.get("image_urls") or "").split("|") if u]
    return rows


def build_listing(product: dict, markets: dict, cfg: dict, fx: dict, ai: anthropic.Anthropic) -> dict:
    prices = {
        code: calc_price(code=code, market=m, pricing=cfg["pricing"], fx=fx[code],
                         cost_krw=product["cost_krw"], domestic_ship_krw=product["domestic_ship_krw"],
                         weight_g=product["weight_g"]).to_dict()
        for code, m in markets.items()
    }
    draft = generate_listing(ai, product, markets, model=cfg["ai"]["model"], effort=cfg["ai"]["effort"])
    return {"product": product, "prices": prices, "draft": draft.model_dump()}


def upload(listing: dict, cfg: dict, shopee: ShopeeClient, shops_by_region: dict) -> list[str]:
    p, draft, prices = listing["product"], listing["draft"], listing["prices"]
    copies = {c["market"]: c for c in draft["markets"]}
    base = copies.get("SG") or next(iter(copies.values()))

    image_ids = [shopee.upload_image_from_url(u) for u in p["image_urls"][:9]]
    if not image_ids:
        raise ShopeeError("이미지가 최소 1장 필요합니다")
    category_id = shopee.recommend_category(base["title"])
    if not category_id:
        raise ShopeeError("카테고리 추천 실패 — category_id 를 직접 지정해야 합니다")

    ff = cfg["fulfillment"]
    first = prices.get("SG") or next(iter(prices.values()))
    global_id = shopee.add_global_item({
        "category_id": category_id,
        "global_item_name": base["title"],
        "description": base["description"],
        "global_item_sku": p["sku"],
        # 글로벌 상품 기준가 — 국가별 실제 판매가는 아래 publish 에서 따로 지정
        "original_price": round(first["price"] * first["fx"]),
        "seller_stock": [{"stock": ff["default_stock"]}],
        "weight": round(p["weight_g"] / 1000, 3),
        "dimension": {
            "package_length": int(float(p.get("length_cm") or 10)),
            "package_width": int(float(p.get("width_cm") or 10)),
            "package_height": int(float(p.get("height_cm") or 10)),
        },
        "image": {"image_id_list": image_ids},
        "brand": {"brand_id": 0, "original_brand_name": "NoBrand"},
        "pre_order": {"is_pre_order": ff["pre_order"], "days_to_ship": ff["days_to_ship"]},
    })

    done = []
    for region, copy in copies.items():
        shop_id = shops_by_region.get(region)
        if not shop_id:
            continue
        shopee.publish(global_id, shop_id, region, {
            "item_name": copy["title"],
            "description": copy["description"],
            "original_price": prices[region]["price"],
        })
        done.append(region)
    return done


def save_outputs(listings: list[dict]) -> tuple[Path, Path]:
    out = ROOT / "output"
    out.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
    json_path = out / f"listings_{stamp}.json"
    json_path.write_text(json.dumps(listings, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = out / f"listings_{stamp}.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["SKU", "국가", "판매가", "통화", "원가(원)", "수수료(원)", "이익(원)", "이익률", "위험도", "제목"])
        for l in listings:
            titles = {c["market"]: c["title"] for c in l["draft"]["markets"]}
            for code, pr in l["prices"].items():
                w.writerow([l["product"]["sku"], code, pr["price"], pr["currency"], pr["cost_krw"],
                            pr["fees_krw"], pr["profit_krw"], f"{pr['margin_rate']:.1%}",
                            l["draft"]["risk_level"], titles.get(code, "")])
    return json_path, csv_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(ROOT / "products.csv"))
    ap.add_argument("--live", action="store_true", help="쇼피에 실제 업로드")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--allow-caution", action="store_true", help="주의(caution) 상품도 업로드")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    if args.live and not cfg.get("verified"):
        sys.exit("config.yaml 의 수수료·배송비가 아직 예시값입니다 (verified: false). 실제 요율로 채운 뒤 다시 실행하세요.")

    markets = {c: m for c, m in cfg["markets"].items() if m["enabled"]}
    products = load_products(Path(args.input))[: args.limit or None]
    fx = fetch_fx(markets, cfg["pricing"]["fx_api"])
    ai = anthropic.Anthropic()

    shopee, shops_by_region = None, {}
    if args.live:
        shopee = ShopeeClient.from_env()
        shops_by_region = {s.get("region"): s["shop_id"] for s in shopee.get_shops()}

    listings = []
    for p in products:
        try:
            listing = build_listing(p, markets, cfg, fx, ai)
        except Exception as e:  # 한 상품 실패가 전체를 멈추지 않도록
            print(f"✗ {p['sku']} 상품글 생성 실패: {e}")
            continue
        listings.append(listing)
        risk = listing["draft"]["risk_level"]
        reasons = "; ".join(listing["draft"]["risk_reasons_ko"])
        print(f"• {p['sku']} [{risk}] {reasons}")

        if not shopee:
            continue
        if risk == "block" or (risk == "caution" and not args.allow_caution):
            print(f"  ↳ 업로드 건너뜀 (위험도 {risk})")
            continue
        try:
            regions = upload(listing, cfg, shopee, shops_by_region)
            print(f"  ↳ 업로드 완료: {', '.join(regions) or '연결된 샵 없음'}")
        except ShopeeError as e:
            print(f"  ↳ 업로드 실패: {e}")

    json_path, csv_path = save_outputs(listings)
    print(f"\n결과: {csv_path}\n상세: {json_path}")


if __name__ == "__main__":
    main()
