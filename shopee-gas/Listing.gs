/**
 * 상품 등록: 상품 시트의 '대기' 행을 하루 N개까지 처리한다.
 *
 * Apps Script 는 실행 1회당 6분 제한이 있어 30개를 한 번에 못 한다.
 * 그래서 1시간마다 몇 개씩(회당처리수) 나눠 처리하고, 오늘 처리 수가 하루등록수에 닿으면 멈춘다.
 *
 * verified=FALSE 이면 업로드 없이 '미리보기'(가격 + AI 상품글)만 채운다.
 */

const LANGUAGE_NAMES = {
  en: 'English', th: 'Thai', vi: 'Vietnamese', 'zh-Hant': 'Traditional Chinese (Taiwan)',
  'pt-BR': 'Brazilian Portuguese', id: 'Indonesian', ms: 'Malay',
};
const TITLE_MAX = 120;
const RUN_BUDGET_MS = 4.5 * 60 * 1000;

const LISTING_SYSTEM = `You write product listings for a Korean cross-border seller on Shopee.
The seller buys from Korean suppliers after each order, so never promise same-day shipping.
For each requested market, write in that market's language:
- title: lead with words buyers search, include "Korea"/"Korean" when it helps, key spec
  (size, volume, count). No ALL CAPS, no emoji spam, no other brands' names unless it is that brand's genuine product.
- description: benefit-first intro, then specs, contents, how to use, and that it ships from Korea. Plain text.
- keywords: 5-10 search keywords buyers in that market use.
Judge selling risk:
- "block": counterfeit/brand-infringement risk, medicine, weapons, adult items, Shopee-prohibited items.
- "caution": cosmetics/food/supplements (registration rules vary), batteries/liquids/aerosols, licensed characters, fragile.
- "ok": everything else.
Write risk_reasons in Korean.`;

const LISTING_SCHEMA = {
  type: 'OBJECT',
  properties: {
    risk_level: { type: 'STRING', enum: ['ok', 'caution', 'block'] },
    risk_reasons: { type: 'ARRAY', items: { type: 'STRING' } },
    markets: {
      type: 'ARRAY',
      items: {
        type: 'OBJECT',
        properties: {
          market: { type: 'STRING' },
          title: { type: 'STRING' },
          description: { type: 'STRING' },
          keywords: { type: 'ARRAY', items: { type: 'STRING' } },
        },
        required: ['market', 'title', 'description', 'keywords'],
      },
    },
  },
  required: ['risk_level', 'risk_reasons', 'markets'],
};

function listingJob() {
  withLock_('상품등록', () => {
    const started = Date.now();
    const s = settings_();
    const live = s['verified'] === true;
    const daily = Number(s['하루등록수'] || 30);
    const perRun = Number(s['회당처리수'] || 5);

    const rows = readTable_(SHEETS.PRODUCTS);
    const doneToday = rows.filter(r => r['등록일'] && formatDay_(r['등록일']) === today_()).length;
    const quota = Math.min(daily - doneToday, perRun);
    if (quota <= 0) return;

    const markets = markets_();
    const fx = fetchFx_(markets);
    const pricing = pricingSettings_(s);

    rows.filter(r => r['상태'] === '대기').slice(0, quota).forEach(r => {
      if (Date.now() - started > RUN_BUDGET_MS) return;
      try {
        processProduct_(r, markets, fx, pricing, s, live);
      } catch (e) {
        updateRow_(SHEETS.PRODUCTS, r._row, { '상태': '오류', '오류': String(e.message || e).slice(0, 500) });
        log_('상품등록', `${r['SKU']} 실패: ${e.message || e}`);
      }
    });
  });
}

function formatDay_(v) {
  return v instanceof Date ? Utilities.formatDate(v, 'Asia/Seoul', 'yyyy-MM-dd') : String(v).slice(0, 10);
}

function processProduct_(r, markets, fx, pricing, s, live) {
  const product = {
    sku: r['SKU'] || `KR-${r._row}-${Date.now() % 100000}`,
    name: r['상품명'],
    cost: Number(r['원가(원)']),
    domesticShip: Number(r['국내배송비(원)'] || 0),
    weight: Number(r['무게(g)'] || s['기본무게(g)'] || 300),
    images: String(r['이미지URL'] || '').split(/[|\n]/).map(x => x.trim()).filter(Boolean),
    notes: r['메모'] || '',
    sourceUrl: r['소싱URL'] || '',
    dims: [r['가로(cm)'], r['세로(cm)'], r['높이(cm)']].map(v => Math.max(1, Math.round(Number(v) || 10))),
  };
  if (!product.name || !product.cost) throw new Error('상품명과 원가는 필수입니다');

  const prices = {};
  markets.forEach(m => {
    prices[m.code] = calcPrice_(m, pricing, fx[m.code], product.cost, product.domesticShip, product.weight);
  });

  const draft = writeListing_(product, markets);
  const priceText = markets.map(m => `${m.code} ${prices[m.code].price}${m.currency}(이익 ${prices[m.code].profitKrw}원)`).join(' / ');
  const update = {
    'SKU': product.sku,
    '위험도': draft.risk_level,
    '위험사유': draft.risk_reasons.join('; '),
    '판매가': priceText,
    'AI결과': JSON.stringify(draft).slice(0, 45000),
    '등록일': today_(),
    '오류': '',
  };

  const allowCaution = s['주의상품업로드'] === true;
  if (draft.risk_level === 'block' || (draft.risk_level === 'caution' && !allowCaution)) {
    update['상태'] = '건너뜀';
  } else if (!live) {
    update['상태'] = '미리보기';
  } else {
    const result = uploadToShopee_(product, draft, prices, markets, s);
    update['상태'] = '등록완료';
    update['global_item_id'] = result.globalItemId;
    update['메모'] = [product.notes, `게시: ${result.regions.join(',')}`].filter(Boolean).join(' / ');
  }
  updateRow_(SHEETS.PRODUCTS, r._row, update);
  log_('상품등록', `${product.sku} → ${update['상태']} (${draft.risk_level})`);
}

function writeListing_(product, markets) {
  const targets = markets.map(m => `- ${m.code}: ${LANGUAGE_NAMES[m.language] || m.language}`).join('\n');
  const prompt = `Product (Korean source data):
- name: ${product.name}
- notes/specs: ${product.notes || '-'}
- weight: ${product.weight} g
- source: ${product.sourceUrl || '-'}

Write one entry per market:
${targets}`;
  const draft = gemini_(prompt, { system: LISTING_SYSTEM, schema: LISTING_SCHEMA });
  draft.markets.forEach(c => { c.title = String(c.title).slice(0, TITLE_MAX).trim(); });
  return draft;
}

function uploadToShopee_(product, draft, prices, markets, s) {
  if (!product.images.length) throw new Error('이미지URL 이 최소 1개 필요합니다');
  const copies = {};
  draft.markets.forEach(c => { copies[c.market] = c; });
  const base = copies.SG || draft.markets[0];

  const imageIds = product.images.slice(0, 9).map(url => {
    const blob = UrlFetchApp.fetch(url).getBlob().setName('image.jpg');
    return shopee_('/api/v2/media_space/upload_image', { method: 'post', blob: blob }).image_info.image_id;
  });

  const rec = shopee_('/api/v2/global_product/category_recommend', {
    level: 'merchant', params: { global_item_name: base.title },
  });
  const categoryId = [].concat(rec.category_id || rec.category_id_list || [])[0];
  if (!categoryId) throw new Error('카테고리 추천 실패');

  const first = prices.SG || prices[markets[0].code];
  const preOrder = s['예약판매'] === true;
  const added = shopee_('/api/v2/global_product/add_global_item', {
    level: 'merchant', method: 'post', body: {
      category_id: categoryId,
      global_item_name: base.title,
      description: base.description,
      global_item_sku: product.sku,
      original_price: Math.round(first.price * first.fx), // 기준가. 국가별 실제 판매가는 아래 게시에서 지정
      seller_stock: [{ stock: Number(s['기본재고'] || 30) }],
      weight: Math.round(product.weight) / 1000,
      dimension: { package_length: product.dims[0], package_width: product.dims[1], package_height: product.dims[2] },
      image: { image_id_list: imageIds },
      brand: { brand_id: 0, original_brand_name: 'NoBrand' },
      pre_order: { is_pre_order: preOrder, days_to_ship: Number(s['발송준비일수'] || 3) },
    },
  });

  const regions = [];
  markets.forEach(m => {
    const copy = copies[m.code];
    if (!m.shopId || !copy) return;
    shopee_('/api/v2/global_product/create_publish_task', {
      level: 'merchant', method: 'post', body: {
        global_item_id: added.global_item_id,
        shop_id: m.shopId,
        shop_region: m.code,
        item: { item_name: copy.title, description: copy.description, original_price: prices[m.code].price },
      },
    });
    regions.push(m.code);
  });
  return { globalItemId: added.global_item_id, regions: regions };
}
