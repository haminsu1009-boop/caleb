/**
 * 국가별 판매가 계산
 *
 * 원리: 판매가 P 에서 수수료(%)와 마진(%)을 떼고 남은 돈이 원가를 덮어야 한다.
 *   P × (1 − 수수료율 − 마진율) = 원가(현지통화)  →  P = 원가 ÷ (1 − 수수료율 − 마진율)
 * 여기에 "건당 최소 이익" 조건을 하나 더 걸고, 둘 중 큰 가격을 쓴다.
 */

function shippingKrw_(market, weightG) {
  const steps = Math.ceil(Math.max(weightG, 1) / 100);
  return market.shipBase + market.shipPer100g * steps;
}

function roundUp_(value, step) {
  const rounded = Math.ceil(value / step - 1e-9) * step;
  return step < 1 ? Math.round(rounded * 100) / 100 : Math.round(rounded);
}

/**
 * @param market markets_() 의 한 항목
 * @param pricing {marginRate, minProfitKrw, fxBufferRate}
 * @param fx      1 현지통화 = ? 원
 */
function calcPrice_(market, pricing, fx, costKrw, domesticShipKrw, weightG) {
  const feeRate = market.commission + market.transactionFee + market.serviceFee;
  if (feeRate + pricing.marginRate >= 1) {
    throw new Error(`${market.code}: 수수료율 + 마진율이 100% 이상입니다`);
  }
  const totalCost = costKrw + domesticShipKrw + shippingKrw_(market, weightG);
  const buffered = totalCost * (1 + pricing.fxBufferRate);

  const byMargin = buffered / fx / (1 - feeRate - pricing.marginRate);          // 조건 1: 목표 마진율
  const byMinProfit = (buffered + pricing.minProfitKrw) / fx / (1 - feeRate);   // 조건 2: 최소 이익
  const price = roundUp_(Math.max(byMargin, byMinProfit), market.priceStep);

  const revenue = price * fx;
  const fees = revenue * feeRate;
  const profit = revenue - fees - totalCost;
  return {
    market: market.code,
    currency: market.currency,
    price: price,
    costKrw: Math.round(totalCost),
    feesKrw: Math.round(fees),
    profitKrw: Math.round(profit),
    marginRate: Math.round((profit / revenue) * 10000) / 10000,
    fx: fx,
  };
}

/** 1 현지통화 = ? 원. 무료 환율 API, 6시간 캐시. 실패 시 국가 시트의 환율대체값 */
function fetchFx_(markets) {
  const cache = CacheService.getScriptCache();
  let perKrw = null;
  const cached = cache.get('fx_krw');
  if (cached) {
    perKrw = JSON.parse(cached);
  } else {
    try {
      const res = UrlFetchApp.fetch('https://open.er-api.com/v6/latest/KRW', { muteHttpExceptions: true });
      const data = JSON.parse(res.getContentText());
      if (data.rates) {
        perKrw = data.rates;
        cache.put('fx_krw', JSON.stringify(perKrw), 6 * 3600);
      }
    } catch (e) {
      log_('환율', '환율 API 실패, 대체값 사용: ' + e);
    }
  }
  const fx = {};
  markets.forEach(m => {
    const r = perKrw && perKrw[m.currency];
    fx[m.code] = r ? 1 / r : m.fxFallback;
  });
  return fx;
}

function pricingSettings_(s) {
  return {
    marginRate: Number(s['목표마진율']),
    minProfitKrw: Number(s['최소이익(원)']),
    fxBufferRate: Number(s['환율버퍼']),
  };
}
