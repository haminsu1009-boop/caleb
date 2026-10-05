"""Claude 로 국가별 상품글(제목·설명·키워드)을 만들고 판매 위험도를 점검한다."""
from __future__ import annotations

from typing import Literal

import anthropic
from pydantic import BaseModel

LANGUAGE_NAMES = {
    "en": "English",
    "th": "Thai",
    "vi": "Vietnamese",
    "zh-Hant": "Traditional Chinese (Taiwan)",
    "pt-BR": "Brazilian Portuguese",
    "id": "Indonesian",
}

TITLE_MAX = 120

SYSTEM_PROMPT = """You write product listings for a Korean cross-border seller on Shopee.
The seller buys from Korean suppliers after each order (dropshipping), so never promise
same-day shipping or stock that the seller does not control.

For each requested market, write in that market's language:
- title: lead with the search terms buyers actually type, include "Korea"/"Korean" when it helps,
  key spec (size, volume, count). No ALL CAPS, no emoji spam, no competitor brand names.
- description: short benefit-first intro, then bullet-style specs, contents, how to use,
  and a note that the item ships from Korea. Plain text only (Shopee strips HTML).
- keywords: 5-10 search keywords buyers in that market use.

Also judge selling risk across Shopee and import rules:
- "block": counterfeit/brand-infringement risk, prescription drugs, weapons, adult items,
  items Shopee prohibits, or anything needing import permits the seller cannot get.
- "caution": cosmetics/food/supplements (may need registration in some markets),
  batteries/liquids/aerosols (shipping limits), licensed characters, fragile items.
- "ok": everything else.
Explain each risk reason briefly in Korean so the seller can act on it."""


class MarketCopy(BaseModel):
    market: str
    title: str
    description: str
    keywords: list[str]


class ListingDraft(BaseModel):
    risk_level: Literal["ok", "caution", "block"]
    risk_reasons_ko: list[str]
    category_keywords_en: list[str]
    markets: list[MarketCopy]


def build_user_prompt(product: dict, markets: dict[str, dict]) -> str:
    targets = "\n".join(
        f"- {code}: {LANGUAGE_NAMES.get(m['language'], m['language'])}"
        for code, m in markets.items()
    )
    return f"""Product (Korean source data):
- name: {product['name_ko']}
- specs/notes: {product.get('notes') or '-'}
- weight: {product.get('weight_g') or '-'} g
- source page: {product.get('source_url') or '-'}

Write one entry per market:
{targets}"""


def generate_listing(
    client: anthropic.Anthropic,
    product: dict,
    markets: dict[str, dict],
    *,
    model: str,
    effort: str,
) -> ListingDraft:
    response = client.beta.messages.parse(
        model=model,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_prompt(product, markets)}],
        output_format=ListingDraft,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"AI가 상품글 생성을 거절했습니다: {product['name_ko']}")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise RuntimeError(f"AI 응답이 불완전합니다: {product['name_ko']}")

    draft = response.parsed_output
    for copy in draft.markets:
        copy.title = copy.title[:TITLE_MAX].strip()
    return draft
