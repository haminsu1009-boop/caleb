/**
 * 수요 조사 (매주 월요일)
 *
 * 1) 조사: Gemini + 구글 검색으로 국가별 '지금 팔리는 한국 상품'을 근거와 함께 찾는다.
 * 2) 정리: 조사 메모를 정해진 표 형식(JSON)으로 바꿔 수요조사 시트에 쓴다.
 * 3) 연결: 점수 높은 아이디어의 한국어 검색어를 설정의 '소싱키워드'로 넘겨 소싱 작업이 이어받게 한다.
 */

const DEMAND_SCHEMA = {
  type: 'OBJECT',
  properties: {
    ideas: {
      type: 'ARRAY',
      items: {
        type: 'OBJECT',
        properties: {
          product_ko: { type: 'STRING' },
          search_keyword_ko: { type: 'STRING' },
          markets: { type: 'ARRAY', items: { type: 'STRING' } },
          why_ko: { type: 'STRING' },
          price_range: { type: 'STRING' },
          risk_ko: { type: 'STRING' },
          sources: { type: 'ARRAY', items: { type: 'STRING' } },
          score: { type: 'INTEGER' },
        },
        required: ['product_ko', 'search_keyword_ko', 'markets', 'why_ko', 'price_range', 'risk_ko', 'sources', 'score'],
      },
    },
  },
  required: ['ideas'],
};

function demandJob() {
  withLock_('수요조사', () => {
    const s = settings_();
    const codes = markets_().map(m => m.code).join(', ');
    const notes = gemini_(`You research demand for a Korean seller on Shopee (cross-border, buys from Korean
wholesalers after each order). Markets: ${codes}. Focus: ${s['관심카테고리'] || 'any category with good margin and light weight'}.
Search for recent (last 6 months) evidence of Korean products selling well in these Shopee markets:
Shopee bestseller/trending pages, campaign news, K-beauty/K-food/K-lifestyle trend articles, TikTok viral items.
List 20 concrete products (specific, not just "skincare"): markets, why (with source URLs), typical local price,
a Korean search keyword to find it on Korean wholesale sites, and risks (brand IP, cosmetics/food registration,
batteries/liquids, heavy weight). Skip counterfeit-prone or restricted items. Today: ${today_()}.`,
      { search: true });

    const report = gemini_(
      'Convert these research notes into the schema. Korean fields in Korean. score 1-10 (demand, margin, risk). ' +
      'Keep only ideas backed by the notes.\n\n' + notes,
      { schema: DEMAND_SCHEMA });

    const ideas = report.ideas.sort((a, b) => b.score - a.score);
    ideas.forEach(i => appendRow_(SHEETS.DEMAND, {
      '날짜': today_(), '점수': i.score, '상품': i.product_ko, '검색어': i.search_keyword_ko,
      '국가': i.markets.join(','), '수요근거': i.why_ko, '가격대': i.price_range,
      '리스크': i.risk_ko, '출처': i.sources.join(' '),
    }));

    if (s['키워드자동갱신'] === true) {
      const keywords = ideas.filter(i => i.score >= 7).slice(0, 10).map(i => i.search_keyword_ko);
      if (keywords.length) setSetting_('소싱키워드', keywords.join(', '));
    }
    log_('수요조사', `아이디어 ${ideas.length}개 저장`);
  });
}
