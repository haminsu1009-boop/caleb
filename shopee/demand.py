"""수요 조사: Claude 가 웹을 검색해 국가별로 '지금 팔리는 한국 상품' 아이디어를 뽑는다.

2단계로 나눈 이유:
  1) 조사 — 웹 검색 도구로 자유롭게 찾아 읽고 근거(URL)를 모은다.
  2) 정리 — 조사 메모를 정해진 표 형식(JSON)으로 바꾼다.
한 번에 시키면 검색과 형식 맞추기가 서로 방해하므로, 사람처럼 "조사 → 정리" 순서로 분리했다.

사용:
  python -m shopee.demand --markets SG,MY,TW --category "beauty, snacks"
결과: shopee/output/demand_YYYYMMDD.md / .csv
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
from pathlib import Path

import anthropic
import yaml
from pydantic import BaseModel

ROOT = Path(__file__).parent
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ProductIdea(BaseModel):
    name_ko: str
    category: str
    markets: list[str]
    why_demand_ko: str
    evidence_urls: list[str]
    price_range_local: str
    sourcing_hint_ko: str
    risk_note_ko: str
    score: int  # 1~10, 수요·마진·리스크 종합


class DemandReport(BaseModel):
    summary_ko: str
    ideas: list[ProductIdea]


def research(client: anthropic.Anthropic, model: str, markets: list[str], category: str) -> str:
    prompt = f"""You are a market researcher for a Korean seller on Shopee (cross-border, dropshipping
from Korean suppliers after each order).

Markets: {', '.join(markets)}
Focus categories: {category or 'any category with good margin'}

Search the web for current evidence of demand for Korean products in these Shopee markets:
Shopee bestseller/trending pages, Shopee official campaign news, Google Trends coverage,
K-beauty/K-food/K-pop trend articles, TikTok Shop viral Korean items. Prefer sources from the last 6 months.

Then list 15-25 concrete product ideas. For each: product (specific, not just "skincare"),
which markets, why there is demand (with source URLs), typical selling price in local currency,
where to source it in Korea (wholesale site/brand type), and risks (brand IP, cosmetics/food
registration, batteries/liquids shipping, low margin due to weight). Skip items that are
counterfeit-prone or restricted. Today is {dt.date.today().isoformat()}."""

    messages: list = [{"role": "user", "content": prompt}]
    for _ in range(5):  # 서버 도구가 길어지면 pause_turn 으로 끊어 돌려준다 → 이어서 요청
        response = client.beta.messages.create(
            model=model,
            max_tokens=32000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 15}],
            messages=messages,
        )
        if response.stop_reason != "pause_turn":
            break
        messages.append({"role": "assistant", "content": response.content})

    if response.stop_reason == "refusal":
        raise RuntimeError("AI가 수요 조사를 거절했습니다")
    return "\n".join(b.text for b in response.content if b.type == "text")


def structure(client: anthropic.Anthropic, model: str, notes: str) -> DemandReport:
    response = client.beta.messages.parse(
        model=model,
        max_tokens=16000,
        betas=[FALLBACK_BETA],
        fallbacks="default",
        thinking={"type": "adaptive"},
        output_config={"effort": "low"},
        messages=[{"role": "user", "content":
            "Convert these research notes into the schema. Write Korean fields in Korean. "
            "Keep only ideas backed by the notes; score 1-10 on demand, margin and risk.\n\n" + notes}],
        output_format=DemandReport,
    )
    if response.parsed_output is None:
        raise RuntimeError(f"정리 단계 실패 (stop_reason={response.stop_reason})")
    return response.parsed_output


def save(report: DemandReport, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.date.today().strftime("%Y%m%d")
    ideas = sorted(report.ideas, key=lambda i: i.score, reverse=True)

    csv_path = out_dir / f"demand_{stamp}.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["점수", "상품", "카테고리", "국가", "수요 근거", "현지 가격대", "소싱 힌트", "리스크", "출처"])
        for i in ideas:
            w.writerow([i.score, i.name_ko, i.category, ",".join(i.markets), i.why_demand_ko,
                        i.price_range_local, i.sourcing_hint_ko, i.risk_note_ko, " ".join(i.evidence_urls)])

    md_path = out_dir / f"demand_{stamp}.md"
    lines = [f"# 쇼피 수요 조사 {stamp}", "", report.summary_ko, ""]
    for i in ideas:
        lines += [f"## {i.score}/10 · {i.name_ko} ({', '.join(i.markets)})",
                  f"- 수요 근거: {i.why_demand_ko}",
                  f"- 가격대: {i.price_range_local}",
                  f"- 소싱: {i.sourcing_hint_ko}",
                  f"- 리스크: {i.risk_note_ko}",
                  "- 출처: " + " ".join(i.evidence_urls), ""]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path, csv_path


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    enabled = [c for c, m in cfg["markets"].items() if m["enabled"]]
    p = argparse.ArgumentParser()
    p.add_argument("--markets", default=",".join(enabled))
    p.add_argument("--category", default="")
    args = p.parse_args()

    client = anthropic.Anthropic()
    model = cfg["ai"]["model"]
    notes = research(client, model, args.markets.split(","), args.category)
    report = structure(client, model, notes)
    md, csv_path = save(report, ROOT / "output")
    print(f"아이디어 {len(report.ideas)}개 → {md}, {csv_path}")


if __name__ == "__main__":
    main()
