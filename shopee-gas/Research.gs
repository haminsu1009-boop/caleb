/**
 * 시장가 점검: 등록 전에 경쟁 판매가를 웹에서 조사해 우리 가격을 판단한다.
 *
 * 원가 기반 가격(Pricing.gs)은 "얼마 이상 받아야 남는가"만 알려준다.
 * 시장가는 "얼마까지 받을 수 있는가"를 알려준다. 둘을 같이 봐야 한다.
 *  - 우리 가격이 시장 최저가보다 한참 싸면 → 이익을 버리고 있는 것 → 시장가 근처로 올린다(선택).
 *  - 우리 가격이 시장 최고가보다 한참 비싸면 → 안 팔릴 가능성 → '비쌈'으로 표시해 사람이 판단.
 */

const MARKET_PRICE_SCHEMA = {
  type: 'OBJECT',
  properties: {
    markets: {
      type: 'ARRAY',
      items: {
        type: 'OBJECT',
        properties: {
          market: { type: 'STRING' },
          low: { type: 'NUMBER' },
          high: { type: 'NUMBER' },
          currency: { type: 'STRING' },
        },
        required: ['market', 'low', 'high', 'currency'],
      },
    },
  },
  required: ['markets'],
};

function checkMarketPrices_(product, markets, prices, autoRaise) {
  const where = markets.map(m => `${m.code} (${m.platform === 'qoo10' ? 'Qoo10 Japan' : 'Shopee ' + m.code}, ${m.currency})`).join(', ');
  const notes = gemini_(`Find current selling prices for this Korean product (or the closest equivalent:
same type, size and brand tier) on these marketplaces: ${where}.
Product: ${product.name}
Specs: ${product.notes || '-'}
For each marketplace give the typical low and high price in local currency, from real listings.
If you find nothing reliable for a marketplace, say so.`, { search: true });

  const data = gemini_('Extract the price ranges from these notes into the schema. ' +
    'Only include marketplaces with real prices found; use market codes ' + markets.map(m => m.code).join(',') +
    '.\n\n' + notes, { schema: MARKET_PRICE_SCHEMA });

  const summary = [];
  const verdict = [];
  (data.markets || []).forEach(r => {
    const m = markets.find(x => x.code === r.market);
    const p = prices[r.market];
    if (!m || !p || !(r.low > 0) || !(r.high >= r.low)) return;
    summary.push(`${m.code} ${r.low}~${r.high}${m.currency}`);
    verdict.push(`${m.code} ${judgePrice_(m, p, r.low, r.high, autoRaise)}`);
  });
  return {
    summary: summary.join(' / ') || '시장가 못 찾음',
    verdict: verdict.join(', '),
  };
}

/** 가격 판단. autoRaise 이면 너무 싼 가격을 시장 최저가의 95% 로 올리고 이익을 다시 계산한다 */
function judgePrice_(market, p, low, high, autoRaise) {
  if (p.price > high * 1.15) return `비쌈(우리 ${p.price})`;
  if (p.price < low * 0.85) {
    if (!autoRaise) return `쌈(우리 ${p.price}, 인상 여지)`;
    const before = p.price;
    reprice_(market, p, roundUp_(low * 0.95, market.priceStep));
    return `쌈→인상 ${before}→${p.price}`;
  }
  return '적정';
}

/** 판매가를 바꾸고 수수료·이익·이익률을 다시 계산 (원가는 그대로) */
function reprice_(market, p, newPrice) {
  const feeRate = market.commission + market.transactionFee + market.serviceFee;
  const revenue = newPrice * p.fx;
  p.price = newPrice;
  p.feesKrw = Math.round(revenue * feeRate);
  p.profitKrw = Math.round(revenue - p.feesKrw - p.costKrw);
  p.marginRate = Math.round((p.profitKrw / revenue) * 10000) / 10000;
  return p;
}
