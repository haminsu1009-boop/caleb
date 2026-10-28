// 쇼피·큐텐 자동화 — 전체 코드 (Apps Script 의 Code.gs 에 통째로 붙여넣기)
// 원본: shopee-gas/*.gs 를 합친 파일. 수정은 원본에서 하고 다시 합치세요.

// ═════════════ Config.gs ═════════════
/**
 * 공통 설정 · 시트 읽기/쓰기 · 로그 · 알림
 *
 * 비밀값(API 키)은 시트가 아니라 "스크립트 속성"에 둔다.
 * 시트는 공유될 수 있지만 스크립트 속성은 편집 권한자만 볼 수 있기 때문.
 *   SHOPEE_PARTNER_ID, SHOPEE_PARTNER_KEY, GEMINI_API_KEY, DOMEGGOOK_API_KEY(선택)
 */

const SHEETS = {
  SETTINGS: '설정',
  MARKETS: '국가',
  PRODUCTS: '상품',
  ORDERS: '주문',
  CHATS: '채팅',
  DEMAND: '수요조사',
  LOG: '로그',
};

function book_() {
  const id = PropertiesService.getScriptProperties().getProperty('SHEET_ID');
  return id ? SpreadsheetApp.openById(id) : SpreadsheetApp.getActiveSpreadsheet();
}

function sheet_(name) {
  const sh = book_().getSheetByName(name);
  if (!sh) throw new Error(`'${name}' 시트가 없습니다. 메뉴 > 🛒 쇼피 > 초기 설정을 먼저 실행하세요`);
  return sh;
}

function secret_(name, optional) {
  const v = PropertiesService.getScriptProperties().getProperty(name);
  if (!v && !optional) throw new Error(`스크립트 속성 ${name} 이(가) 비어 있습니다`);
  return v;
}

/** 설정 시트(항목 | 값 | 설명)를 {항목: 값} 으로 */
function settings_() {
  const values = sheet_(SHEETS.SETTINGS).getDataRange().getValues().slice(1);
  const out = {};
  values.forEach(([key, value]) => { if (key) out[String(key).trim()] = value; });
  return out;
}

function setSetting_(key, value) {
  const sh = sheet_(SHEETS.SETTINGS);
  const keys = sh.getRange(2, 1, Math.max(sh.getLastRow() - 1, 1), 1).getValues().flat();
  const idx = keys.indexOf(key);
  if (idx >= 0) sh.getRange(idx + 2, 2).setValue(value);
  else sh.appendRow([key, value, '']);
}

/** 표 형태 시트를 [{헤더: 값, _row: 행번호}] 로 */
function readTable_(name) {
  const values = sheet_(name).getDataRange().getValues();
  const headers = values[0];
  return values.slice(1).map((row, i) => {
    const obj = { _row: i + 2 };
    headers.forEach((h, j) => { obj[h] = row[j]; });
    return obj;
  });
}

function headers_(name) {
  const sh = sheet_(name);
  return sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0];
}

function appendRow_(name, obj) {
  const row = headers_(name).map(h => (obj[h] === undefined ? '' : obj[h]));
  sheet_(name).appendRow(row);
}

function updateRow_(name, rowNum, obj) {
  const sh = sheet_(name);
  headers_(name).forEach((h, j) => {
    if (obj[h] !== undefined) sh.getRange(rowNum, j + 1).setValue(obj[h]);
  });
}

/** 사용(체크)된 국가만. platform: 'shopee' | 'qoo10' */
function markets_() {
  return readTable_(SHEETS.MARKETS)
    .filter(m => m['사용'] === true)
    .map(m => ({
      code: m['국가'],
      currency: m['통화'],
      language: m['언어'],
      priceStep: Number(m['가격단위']),
      commission: Number(m['판매수수료율']),
      transactionFee: Number(m['결제수수료율']),
      serviceFee: Number(m['서비스수수료율']),
      shipBase: Number(m['기본배송비(원)']),
      shipPer100g: Number(m['100g당배송비(원)']),
      fxFallback: Number(m['환율대체값']),
      shopId: m['shop_id'] ? Number(m['shop_id']) : null,
      platform: String(m['플랫폼'] || 'shopee').toLowerCase(),
    }));
}

function shopeeMarkets_() {
  return markets_().filter(m => m.platform === 'shopee');
}

function today_() {
  return Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd');
}

function log_(job, message) {
  try {
    const sh = sheet_(SHEETS.LOG);
    sh.appendRow([new Date(), job, String(message).slice(0, 2000)]);
    if (sh.getLastRow() > 3000) sh.deleteRows(2, 500); // 로그가 너무 길어지지 않게
  } catch (e) {
    console.log(job, message);
  }
}

function notify_(subject, body) {
  const to = settings_()['알림이메일'] || Session.getEffectiveUser().getEmail();
  if (to) MailApp.sendEmail(to, `[쇼피·큐텐 자동화] ${subject}`, body);
}

/** 트리거끼리 겹쳐 실행되지 않게 잠금 (토큰 갱신·행 업데이트 충돌 방지) */
function withLock_(job, fn) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10 * 1000)) {
    log_(job, '다른 작업이 실행 중이라 건너뜀');
    return;
  }
  try {
    return fn();
  } catch (e) {
    log_(job, '오류: ' + (e && e.stack ? e.stack : e));
    throw e;
  } finally {
    lock.releaseLock();
  }
}

// ═════════════ Pricing.gs ═════════════
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

// ═════════════ Shopee.gs ═════════════
/**
 * Shopee Open Platform v2 클라이언트
 *
 * 서명 원리: "partner_id + 경로 + 시각 (+ access_token + shop_id/merchant_id)" 문자열을
 * partner_key 로 HMAC-SHA256 한 값을 같이 보낸다. 서버도 같은 계산을 해 보고 일치하면
 * 진짜 요청으로 인정한다. 키 자체는 전송되지 않는다.
 *
 * ⚠️ 엔드포인트 필드는 쇼피 문서 개정에 따라 바뀔 수 있다. 첫 실사용은 하루등록수=1 로.
 */

const SHOPEE_HOST = 'https://partner.shopeemobile.com';

function hex_(bytes) {
  return bytes.map(b => ('0' + (b & 0xff).toString(16)).slice(-2)).join('');
}

function shopeeSign_(partnerKey, parts) {
  return hex_(Utilities.computeHmacSha256Signature(parts.join(''), partnerKey));
}

function partner_() {
  return { id: Number(secret_('SHOPEE_PARTNER_ID')), key: secret_('SHOPEE_PARTNER_KEY') };
}

// ── 인증 ────────────────────────────────────────────────

/** 이 스크립트를 웹앱으로 배포한 URL 을 redirect 로 쓰는 승인 링크 */
function shopeeAuthUrl_() {
  const p = partner_();
  const path = '/api/v2/shop/auth_partner';
  const ts = Math.floor(Date.now() / 1000);
  const redirect = ScriptApp.getService().getUrl();
  if (!redirect) throw new Error('먼저 배포 > 새 배포 > 웹 앱으로 배포하세요');
  return `${SHOPEE_HOST}${path}?partner_id=${p.id}&timestamp=${ts}` +
    `&sign=${shopeeSign_(p.key, [p.id, path, ts])}&redirect=${encodeURIComponent(redirect)}`;
}

/** 쇼피 승인 후 돌아오는 곳 (웹앱). ?code=...&main_account_id=... */
function doGet(e) {
  const code = e && e.parameter && e.parameter.code;
  if (!code) return HtmlService.createHtmlOutput('쇼피 자동화 웹앱입니다.');
  const mainAccountId = e.parameter.main_account_id;
  const shopId = e.parameter.shop_id;
  const body = { code: code, partner_id: partner_().id };
  if (mainAccountId) body.main_account_id = Number(mainAccountId);
  else body.shop_id = Number(shopId);

  const data = shopeePublicPost_('/api/v2/auth/token/get', body);
  saveTokens_(data, {
    merchant_id: (data.merchant_id_list || [])[0] || null,
    shop_id_list: data.shop_id_list || (shopId ? [Number(shopId)] : []),
  });
  return HtmlService.createHtmlOutput(
    '<h2>쇼피 인증 완료 ✅</h2><p>시트로 돌아가 메뉴 > 🛒 쇼피 > 연결된 샵 불러오기 를 실행하세요.</p>');
}

function shopeePublicPost_(path, body) {
  const p = partner_();
  const ts = Math.floor(Date.now() / 1000);
  const url = `${SHOPEE_HOST}${path}?partner_id=${p.id}&timestamp=${ts}&sign=${shopeeSign_(p.key, [p.id, path, ts])}`;
  const res = UrlFetchApp.fetch(url, {
    method: 'post', contentType: 'application/json', payload: JSON.stringify(body), muteHttpExceptions: true,
  });
  return checkShopee_(res);
}

function loadTokens_() {
  const raw = PropertiesService.getScriptProperties().getProperty('SHOPEE_TOKENS');
  return raw ? JSON.parse(raw) : null;
}

function saveTokens_(data, extra) {
  const saved = Object.assign(loadTokens_() || {}, extra || {}, {
    access_token: data.access_token,
    refresh_token: data.refresh_token,
    expire_at: Math.floor(Date.now() / 1000) + Number(data.expire_in || 14400),
  });
  PropertiesService.getScriptProperties().setProperty('SHOPEE_TOKENS', JSON.stringify(saved));
  return saved;
}

/**
 * access_token 은 약 4시간, refresh_token 은 갱신할 때마다 새것으로 바뀐다.
 * 그래서 갱신 결과를 즉시 저장해야 하고, 두 작업이 동시에 갱신하면 안 된다(잠금은 withLock_ 에서).
 */
function accessToken_() {
  let t = loadTokens_();
  if (!t) throw new Error('쇼피 인증이 안 되어 있습니다. 메뉴 > 🛒 쇼피 > 쇼피 인증하기');
  if (t.expire_at - 300 > Date.now() / 1000) return t;

  const body = { refresh_token: t.refresh_token, partner_id: partner_().id };
  if (t.merchant_id) body.merchant_id = Number(t.merchant_id);
  else body.shop_id = Number(t.shop_id_list[0]);
  t = saveTokens_(shopeePublicPost_('/api/v2/auth/access_token/get', body));
  return t;
}

// ── 공통 호출 ───────────────────────────────────────────

/**
 * @param opts.level 'shop'(기본) | 'merchant'
 * @param opts.shopId shop 레벨 호출 대상
 * @param opts.method 'get' | 'post'
 * @param opts.params 쿼리 파라미터, opts.body JSON 본문, opts.blob 이미지
 */
function shopee_(path, opts) {
  opts = opts || {};
  const p = partner_();
  const t = accessToken_();
  const ts = Math.floor(Date.now() / 1000);
  const ownerKey = opts.level === 'merchant' ? 'merchant_id' : 'shop_id';
  const ownerId = opts.level === 'merchant' ? Number(t.merchant_id) : Number(opts.shopId || t.shop_id_list[0]);
  const query = Object.assign({
    partner_id: p.id, timestamp: ts, access_token: t.access_token,
    sign: shopeeSign_(p.key, [p.id, path, ts, t.access_token, ownerId]),
  }, { [ownerKey]: ownerId }, opts.params || {});
  const qs = Object.keys(query).map(k => {
    const v = Array.isArray(query[k]) ? query[k].join(',') : query[k];
    return `${k}=${encodeURIComponent(v)}`;
  }).join('&');

  const fetchOpts = { method: opts.method || 'get', muteHttpExceptions: true };
  if (opts.blob) {
    fetchOpts.payload = { image: opts.blob };
  } else if (fetchOpts.method === 'post') {
    fetchOpts.contentType = 'application/json';
    fetchOpts.payload = JSON.stringify(opts.body || {});
  }
  return checkShopee_(UrlFetchApp.fetch(`${SHOPEE_HOST}${path}?${qs}`, fetchOpts));
}

function checkShopee_(res) {
  let data;
  try {
    data = JSON.parse(res.getContentText());
  } catch (e) {
    throw new Error(`쇼피 HTTP ${res.getResponseCode()}: ${res.getContentText().slice(0, 300)}`);
  }
  if (data.error) throw new Error(`쇼피 ${data.error}: ${data.message} (request_id=${data.request_id})`);
  return data.response || data;
}

// ── 메뉴에서 쓰는 기능 ──────────────────────────────────

function showAuthUrl() {
  const url = shopeeAuthUrl_();
  const html = HtmlService.createHtmlOutput(
    `<p>아래 링크를 열어 쇼피 <b>메인 계정</b>으로 승인하세요.</p><p><a href="${url}" target="_blank">쇼피 승인하러 가기</a></p>`
  ).setWidth(420).setHeight(140);
  SpreadsheetApp.getUi().showModalDialog(html, '쇼피 인증');
}

/** 연결된 국가별 샵 id 를 국가 시트에 채운다 */
function loadShops() {
  const data = shopee_('/api/v2/merchant/get_shop_list_by_merchant', {
    level: 'merchant', params: { page_no: 1, page_size: 100 },
  });
  const byRegion = {};
  (data.shop_list || []).forEach(s => { byRegion[s.region] = s.shop_id; });
  readTable_(SHEETS.MARKETS).forEach(m => {
    if (byRegion[m['국가']]) updateRow_(SHEETS.MARKETS, m._row, { shop_id: byRegion[m['국가']] });
  });
  SpreadsheetApp.getActive().toast(`연결된 샵: ${Object.keys(byRegion).join(', ') || '없음'}`);
}

// ═════════════ Qoo10.gs ═════════════
/**
 * 큐텐 재팬(Qoo10) QAPI 클라이언트
 *
 * 인증 원리: QSM(셀러 관리 화면)에서 발급받은 API 키 + 셀러 ID/비밀번호로 "판매자 인증키"를 만들고,
 * 이후 모든 요청 헤더(GiosisCertificationKey)에 그 인증키를 넣는다. 인증키는 스크립트 속성에 보관.
 *
 * ⚠️ 공식 문서(api.qoo10.jp)를 직접 대조하지 못했다. 메서드 이름은 공개된 연동 사례 기준이며,
 *    응답 필드는 여러 후보 이름을 함께 읽도록 짰다. 큐텐verified 체크 전 반드시 1개로 테스트할 것.
 *    메서드 이름이 다르면 아래 QOO10_METHODS 만 고치면 된다.
 *
 * 스크립트 속성:
 *   QOO10_SELLER_KEY  (QSM 에서 바로 받은 판매자 인증키가 있으면 이것만 넣어도 됨)
 *   또는 QOO10_API_KEY + QOO10_USER_ID + QOO10_PASSWORD (인증키를 자동 발급)
 */

const QOO10_BASE = 'https://api.qoo10.jp/GMKT.INC.Front.QAPIService/ebayjapan.qapi';

const QOO10_METHODS = {
  certify: 'CertificationAPI.CreateCertificationKey',
  newItem: 'ItemsBasic.SetNewGoods',
  orders: 'ShippingBasic.GetShippingInfo_v2',
  sendTracking: 'ShippingBasic.SetSendingInfo',
  inquiries: '',     // 고객 문의 API 이름 확인 후 입력 (비어 있으면 큐텐 문의는 메일 알림 대상 아님)
  answerInquiry: '',
};

function qoo10Enabled_() {
  const p = PropertiesService.getScriptProperties();
  return !!(p.getProperty('QOO10_SELLER_KEY') || p.getProperty('QOO10_API_KEY'));
}

function qoo10SellerKey_() {
  const props = PropertiesService.getScriptProperties();
  const key = props.getProperty('QOO10_SELLER_KEY');
  if (key) return key;
  const data = qoo10Fetch_(QOO10_METHODS.certify, {
    user_id: secret_('QOO10_USER_ID'), pwd: secret_('QOO10_PASSWORD'),
  }, secret_('QOO10_API_KEY'));
  const created = typeof data === 'string' ? data : (data.CertificationKey || data.Key || data);
  if (!created || typeof created !== 'string') throw new Error('큐텐 인증키 발급 실패: ' + JSON.stringify(data).slice(0, 200));
  props.setProperty('QOO10_SELLER_KEY', created);
  return created;
}

function qoo10_(method, params) {
  return qoo10Fetch_(method, params, qoo10SellerKey_());
}

function qoo10Fetch_(method, params, certKey) {
  if (!method) throw new Error('큐텐 API 메서드 이름이 설정되지 않았습니다');
  const payload = Object.assign({ returnType: 'application/json' }, params || {});
  const res = UrlFetchApp.fetch(`${QOO10_BASE}/${method}`, {
    method: 'post',
    headers: { GiosisCertificationKey: certKey, QAPIVersion: '1.1' },
    payload: payload,   // 폼 형식(x-www-form-urlencoded)으로 전송됨
    muteHttpExceptions: true,
  });
  let data;
  try {
    data = JSON.parse(res.getContentText());
  } catch (e) {
    throw new Error(`큐텐 HTTP ${res.getResponseCode()}: ${res.getContentText().slice(0, 300)}`);
  }
  const code = Number(data.ResultCode);
  if (code !== 0) throw new Error(`큐텐 ${method} 실패 (${data.ResultCode}): ${data.ResultMsg}`);
  return data.ResultObject !== undefined ? data.ResultObject : data;
}

// ── 상품 등록 ───────────────────────────────────────────

/** 큐텐 상세페이지 HTML: 이미지 + 핵심 포인트 + 설명 + 한국 발송 안내 */
function qoo10DetailHtml_(copy, images, days) {
  const esc = t => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const imgs = images.map(u => `<p style="text-align:center"><img src="${esc(u)}" style="max-width:100%"></p>`).join('');
  const points = (copy.highlights || []).map(h => `<li style="margin:6px 0">${esc(h)}</li>`).join('');
  const body = esc(copy.description).replace(/\n/g, '<br>');
  return `<div style="max-width:860px;margin:0 auto;font-size:15px;line-height:1.8;color:#333">
${imgs}
${points ? `<h3 style="border-left:4px solid #e4007f;padding-left:8px">おすすめポイント</h3><ul>${points}</ul>` : ''}
<h3 style="border-left:4px solid #e4007f;padding-left:8px">商品説明</h3><p>${body}</p>
<h3 style="border-left:4px solid #e4007f;padding-left:8px">配送について</h3>
<p>韓国からの発送となります。ご注文後、通常${days}営業日以内に発送し、到着まで数日〜1週間程度かかります。</p>
</div>`;
}

function uploadToQoo10_(product, copy, price, s) {
  const category = product.qoo10Category || s['큐텐기본카테고리'];
  if (!category) throw new Error('큐텐 카테고리 코드가 없습니다 (상품 시트 큐텐카테고리 또는 설정 큐텐기본카테고리)');
  if (!s['큐텐배송코드']) throw new Error('설정의 큐텐배송코드(ShippingNo)를 입력해 주세요');
  const days = Number(s['발송준비일수'] || 3);
  const html = qoo10DetailHtml_(copy, product.images, days);
  const data = qoo10_(QOO10_METHODS.newItem, {
    SecondSubCat: category,
    ItemTitle: copy.title,
    SellerCode: product.sku,
    StandardImage: product.images[0],
    ItemDescription: html,
    ItemPrice: price.price,
    RetailPrice: 0,
    ItemQty: Number(s['기본재고'] || 30),
    ShippingNo: s['큐텐배송코드'],
    AvailableDateType: '0',
    AvailableDateValue: String(days),
    AdultYN: 'N',
    TaxRate: 'S',
  });
  return (data && (data.GdNo || data.ItemCode || data.gd_no)) || JSON.stringify(data).slice(0, 50);
}

// ── 주문 · 발송 ─────────────────────────────────────────

function qoo10Ymd_(d) {
  return Utilities.formatDate(d, 'Asia/Tokyo', 'yyyyMMdd');
}

/** 배송 대기 중인 주문 목록 → 공통 형식으로 변환 */
function qoo10NewOrders_() {
  const now = new Date();
  const from = new Date(now.getTime() - 3 * 86400 * 1000);
  const list = qoo10_(QOO10_METHODS.orders, {
    ShippingStat: '2',          // 배송 요청(=발송 대기) 상태
    search_Sdate: qoo10Ymd_(from),
    search_Edate: qoo10Ymd_(now),
    search_condition: '1',      // 주문일 기준
  });
  const pick = (o, names) => { for (const n of names) if (o[n] !== undefined && o[n] !== '') return o[n]; return ''; };
  return [].concat(list || []).map(o => ({
    orderNo: String(pick(o, ['orderNo', 'OrderNo', 'order_no'])),
    sku: String(pick(o, ['sellerItemCode', 'SellerCode', 'seller_item_code'])),
    title: pick(o, ['itemTitle', 'ItemTitle', 'item_title']),
    qty: Number(pick(o, ['orderQty', 'OrderQty', 'order_qty']) || 1),
    price: pick(o, ['orderPrice', 'OrderPrice', 'total']),
    orderDate: pick(o, ['orderDate', 'OrderDate', 'order_date']),
    shipBy: pick(o, ['ShippingRequestDate', 'shippingDate', 'Shippingdate']),
  })).filter(o => o.orderNo);
}

function qoo10SendTracking_(orderNo, carrier, trackingNo) {
  return qoo10_(QOO10_METHODS.sendTracking, { OrderNo: orderNo, ShippingCorp: carrier, TrackingNo: trackingNo });
}

// ═════════════ Gemini.gs ═════════════
/**
 * Gemini 무료 API 호출
 *
 * - schema 를 주면 정해진 JSON 형식으로만 답하게 강제한다 (파싱 실패 방지).
 * - search: true 면 구글 검색 결과를 근거로 답한다 (수요 조사용).
 *   검색과 JSON 강제는 같이 쓸 수 없어서, 수요 조사는 "검색 → 정리" 두 번 호출한다.
 * - 무료 등급은 분당 호출 수 제한이 있어 429 가 오면 기다렸다 다시 시도한다.
 */
function gemini_(prompt, opts) {
  opts = opts || {};
  const model = settings_()['Gemini모델'] || 'gemini-2.5-flash';
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`;
  const body = { contents: [{ role: 'user', parts: [{ text: prompt }] }] };
  if (opts.system) body.systemInstruction = { parts: [{ text: opts.system }] };
  if (opts.schema) body.generationConfig = { responseMimeType: 'application/json', responseSchema: opts.schema };
  if (opts.search) body.tools = [{ google_search: {} }];

  for (let attempt = 1; attempt <= 4; attempt++) {
    const res = UrlFetchApp.fetch(url, {
      method: 'post',
      contentType: 'application/json',
      headers: { 'x-goog-api-key': secret_('GEMINI_API_KEY') },
      payload: JSON.stringify(body),
      muteHttpExceptions: true,
    });
    const code = res.getResponseCode();
    if (code === 429 || code >= 500) {
      Utilities.sleep(15000 * attempt);
      continue;
    }
    const data = JSON.parse(res.getContentText());
    if (code !== 200) throw new Error(`Gemini ${code}: ${JSON.stringify(data.error || data).slice(0, 300)}`);
    const cand = (data.candidates || [])[0];
    if (!cand || !cand.content) throw new Error(`Gemini 응답 없음 (${cand ? cand.finishReason : 'blocked'})`);
    const text = cand.content.parts.map(p => p.text || '').join('');
    return opts.schema ? JSON.parse(text) : text;
  }
  throw new Error('Gemini 호출 한도 초과 — 잠시 후 다시 실행됩니다');
}

// ═════════════ Research.gs ═════════════
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

// ═════════════ Listing.gs ═════════════
/**
 * 상품 등록: 상품 시트의 '대기' 행을 하루 N개까지 처리한다.
 *
 * Apps Script 는 실행 1회당 6분 제한이 있어 30개를 한 번에 못 한다.
 * 그래서 1시간마다 몇 개씩(회당처리수) 나눠 처리하고, 오늘 처리 수가 하루등록수에 닿으면 멈춘다.
 *
 * 쇼피는 verified, 큐텐은 큐텐verified 를 체크해야 실제로 올라간다.
 * 둘 다 꺼져 있으면 업로드 없이 '미리보기'(가격 + 시장가 점검 + AI 상품글)만 채운다.
 */

const LANGUAGE_NAMES = {
  en: 'English', th: 'Thai', vi: 'Vietnamese', 'zh-Hant': 'Traditional Chinese (Taiwan)',
  'pt-BR': 'Brazilian Portuguese', id: 'Indonesian', ms: 'Malay', ja: 'Japanese',
};
const TITLE_MAX = 120;
const RUN_BUDGET_MS = 4.5 * 60 * 1000;

const LISTING_SYSTEM = `You write product listings for a Korean cross-border seller on Shopee and Qoo10 Japan.
The seller buys from Korean suppliers after each order, so never promise same-day shipping.
For each requested market, write in that market's language:
- title: lead with words buyers search, include "Korea"/"Korean" when it helps, key spec
  (size, volume, count). No ALL CAPS, no emoji spam, no other brands' names unless it is that brand's genuine product.
- description: benefit-first intro, then specs, contents, how to use, and that it ships from Korea. Plain text.
- keywords: 5-10 search keywords buyers in that market use.
- highlights: 3-5 short selling points (one line each) for the product detail page.
For JP (Qoo10 Japan): natural, polite Japanese like top Qoo10 beauty listings; put 【韓国コスメ】-style tags
and the product type/volume in the title; mention 韓国から発送.
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
          highlights: { type: 'ARRAY', items: { type: 'STRING' } },
        },
        required: ['market', 'title', 'description', 'keywords', 'highlights'],
      },
    },
  },
  required: ['risk_level', 'risk_reasons', 'markets'],
};

function listingJob() {
  withLock_('상품등록', () => {
    const started = Date.now();
    const s = settings_();
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
        processProduct_(r, markets, fx, pricing, s);
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

function processProduct_(r, markets, fx, pricing, s) {
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
    qoo10Category: r['큐텐카테고리'] || '',
  };
  if (!product.name || !product.cost) throw new Error('상품명과 원가는 필수입니다');

  const prices = {};
  markets.forEach(m => {
    prices[m.code] = calcPrice_(m, pricing, fx[m.code], product.cost, product.domesticShip, product.weight);
  });

  // 시장가 점검: 경쟁 판매가를 웹에서 조사해 너무 싸면 올리고, 너무 비싸면 표시
  let market = { summary: '', verdict: '' };
  if (s['시장가조사'] === true) {
    try {
      market = checkMarketPrices_(product, markets, prices, s['저가면자동인상'] === true);
    } catch (e) {
      market.summary = '조사 실패: ' + (e.message || e);
    }
  }

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
    '시장가': market.summary,
    '가격판단': market.verdict,
  };

  const allowCaution = s['주의상품업로드'] === true;
  if (draft.risk_level === 'block' || (draft.risk_level === 'caution' && !allowCaution)) {
    update['상태'] = '건너뜀';
  } else {
    const shopeeTargets = markets.filter(m => m.platform === 'shopee');
    const jp = markets.find(m => m.platform === 'qoo10');
    const jpCopy = draft.markets.find(c => c.market === (jp && jp.code));
    const shopeeLive = s['verified'] === true && shopeeTargets.length > 0;
    const qoo10Live = s['큐텐verified'] === true && jp && jpCopy && qoo10Enabled_();
    const posted = [];
    const errors = [];
    if (shopeeLive) {
      try {
        const result = uploadToShopee_(product, draft, prices, shopeeTargets, s);
        update['global_item_id'] = result.globalItemId;
        posted.push(...result.regions);
      } catch (e) { errors.push('쇼피: ' + (e.message || e)); }
    }
    if (qoo10Live) {
      try {
        update['큐텐상품번호'] = uploadToQoo10_(product, jpCopy, prices[jp.code], s);
        posted.push('Qoo10JP');
      } catch (e) { errors.push('큐텐: ' + (e.message || e)); }
    }
    if (!shopeeLive && !qoo10Live) update['상태'] = '미리보기';
    else update['상태'] = posted.length ? '등록완료' : '오류';
    if (posted.length) update['메모'] = [product.notes, `게시: ${posted.join(',')}`].filter(Boolean).join(' / ');
    if (errors.length) update['오류'] = errors.join(' | ').slice(0, 500);
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

// ═════════════ Orders.gs ═════════════
/**
 * 주문 확인(쇼피 + 큐텐) → 발주 목록 작성 → 알림 (30분마다)
 *
 * 국내 도매처 결제는 자동으로 하지 않는다. 돈이 나가는 마지막 버튼은 사람이 누른다.
 * 대신 "어디서 · 무엇을 · 몇 개 · 얼마에" 사야 하는지 발주 목록과 메일로 바로 정리해 준다.
 */

function ordersJob() {
  withLock_('주문확인', () => {
    const known = {};
    readTable_(SHEETS.ORDERS).forEach(o => { known[`${o['주문번호']}|${o['SKU']}`] = true; });
    const products = {};
    readTable_(SHEETS.PRODUCTS).forEach(p => { if (p['SKU']) products[p['SKU']] = p; });

    const now = Math.floor(Date.now() / 1000);
    const newLines = [];

    shopeeMarkets_().filter(m => m.shopId).forEach(m => {
      const list = shopee_('/api/v2/order/get_order_list', {
        shopId: m.shopId,
        params: {
          time_range_field: 'create_time', time_from: now - 3 * 86400, time_to: now,
          page_size: 100, order_status: 'READY_TO_SHIP',
        },
      });
      const sns = (list.order_list || []).map(o => o.order_sn);
      for (let i = 0; i < sns.length; i += 50) {
        const detail = shopee_('/api/v2/order/get_order_detail', {
          shopId: m.shopId,
          params: { order_sn_list: sns.slice(i, i + 50), response_optional_fields: 'item_list,total_amount,ship_by_date' },
        });
        (detail.order_list || []).forEach(order => {
          (order.item_list || []).forEach(item => {
            const sku = item.model_sku || item.item_sku || '';
            const key = `${order.order_sn}|${sku}`;
            if (known[key]) return;
            known[key] = true;
            const p = products[sku] || {};
            const qty = Number(item.model_quantity_purchased || 1);
            const line = {
              '주문번호': order.order_sn,
              '국가': m.code,
              '주문시각': new Date(order.create_time * 1000),
              '발송기한': order.ship_by_date ? new Date(order.ship_by_date * 1000) : '',
              'SKU': sku,
              '상품명': item.item_name,
              '수량': qty,
              '판매가': `${item.model_discounted_price || item.model_original_price} ${m.currency}`,
              '소싱URL': p['소싱URL'] || '',
              '예상원가(원)': p['원가(원)'] ? Number(p['원가(원)']) * qty : '',
              '발주상태': '미발주',
              '플랫폼': 'shopee',
              'shop_id': m.shopId,
            };
            appendRow_(SHEETS.ORDERS, line);
            newLines.push(line);
          });
        });
      }
    });

    // 큐텐 재팬 주문
    const jp = markets_().find(m => m.platform === 'qoo10');
    if (jp && qoo10Enabled_()) {
      try {
        qoo10NewOrders_().forEach(o => {
          const key = `${o.orderNo}|${o.sku}`;
          if (known[key]) return;
          known[key] = true;
          const p = products[o.sku] || {};
          const line = {
            '주문번호': o.orderNo, '국가': 'JP', '주문시각': toDate_(o.orderDate) || new Date(),
            '발송기한': toDate_(o.shipBy) || '', 'SKU': o.sku, '상품명': o.title,
            '수량': o.qty, '판매가': `${o.price} JPY`, '소싱URL': p['소싱URL'] || '',
            '예상원가(원)': p['원가(원)'] ? Number(p['원가(원)']) * o.qty : '',
            '발주상태': '미발주', '플랫폼': 'qoo10',
          };
          appendRow_(SHEETS.ORDERS, line);
          newLines.push(line);
        });
      } catch (e) {
        log_('주문확인', '큐텐 주문 조회 실패: ' + (e.message || e));
      }
    }

    if (newLines.length) {
      const body = newLines.map(l =>
        `• [${l['국가']}] ${l['상품명']} × ${l['수량']}  (주문 ${l['주문번호']})\n` +
        `  발송기한: ${l['발송기한'] ? Utilities.formatDate(l['발송기한'], 'Asia/Seoul', 'MM/dd HH:mm') : '-'}\n` +
        `  발주하기: ${l['소싱URL'] || '소싱URL 없음 — 상품 시트 확인'}`).join('\n\n');
      notify_(`새 주문 ${newLines.length}건 — 발주해 주세요`,
        body + '\n\n발주 후 주문 시트의 발주상태를 "발주완료"로 바꿔 주세요.');
      log_('주문확인', `새 주문 ${newLines.length}건`);
    }
    remindUnordered_();
  });
}

/** 문자열 날짜를 Date 로. 해석 못 하면 null (잘못된 날짜로 메일 작성이 깨지지 않게) */
function toDate_(v) {
  if (!v) return null;
  const d = v instanceof Date ? v : new Date(String(v).replace(' ', 'T'));
  return isNaN(d.getTime()) ? null : d;
}

/** 발송기한 24시간 안쪽인데 아직 미발주인 건은 다시 알림 (하루 한 번) */
function remindUnordered_() {
  const cache = CacheService.getScriptCache();
  if (cache.get('remind_sent')) return;
  const soon = Date.now() + 24 * 3600 * 1000;
  const late = readTable_(SHEETS.ORDERS).filter(o =>
    o['발주상태'] === '미발주' && o['발송기한'] instanceof Date && o['발송기한'].getTime() < soon);
  if (!late.length) return;
  notify_(`⚠️ 발송기한 임박 미발주 ${late.length}건`,
    late.map(o => `• ${o['상품명']} × ${o['수량']} (주문 ${o['주문번호']}) ${o['소싱URL']}`).join('\n'));
  cache.put('remind_sent', '1', 6 * 3600);
}

// ═════════════ Shipping.gs ═════════════
/**
 * 발송 처리 (1시간마다): 주문 시트에서 발주상태가 '발송준비'인 줄을 플랫폼에 발송 등록한다.
 *
 * 사람(또는 태인 창고)이 하는 일: 물건 받기 → 포장 → 발주상태를 '발송준비'로 바꾸기
 *   (큐텐은 택배사·국제송장 칸도 채우기)
 * 프로그램이 하는 일:
 *   - 쇼피: 발송 요청(ship_order) → 쇼피 물류(SLS) 송장번호 받아 시트에 기록
 *   - 큐텐: 입력된 송장번호를 큐텐에 등록(발송 처리)
 * 실물 포장·운송은 코드로 대신할 수 없다. 그 부분은 창고(3PL)에 맡기면 시트 입력만 남는다.
 */

function shippingJob() {
  withLock_('발송처리', () => {
    // '완료'가 아닌 발송준비 줄은 매번 다시 시도 (예: 송장을 나중에 입력한 큐텐 주문)
    const rows = readTable_(SHEETS.ORDERS).filter(o => o['발주상태'] === '발송준비' && o['발송처리'] !== '완료');
    const done = [];
    const problems = [];

    rows.forEach(o => {
      try {
        const result = String(o['플랫폼'] || 'shopee') === 'qoo10' ? shipQoo10_(o) : shipShopee_(o);
        updateRow_(SHEETS.ORDERS, o._row, result);
        if (result['발주상태'] === '발송완료') done.push(`${o['국가']} ${o['주문번호']}`);
        // 같은 문제로 매시간 메일이 오지 않게, 상태가 새로 바뀌었을 때만 알림
        else if (result['발송처리'] !== 'SLS송장대기' && result['발송처리'] !== o['발송처리']) {
          problems.push(`${o['주문번호']}: ${result['발송처리']}`);
        }
      } catch (e) {
        const msg = '오류: ' + String(e.message || e).slice(0, 200);
        updateRow_(SHEETS.ORDERS, o._row, { '발송처리': msg });
        if (msg !== o['발송처리']) problems.push(`${o['주문번호']}: ${e.message || e}`);
      }
    });

    if (done.length) log_('발송처리', `발송 완료 ${done.length}건: ${done.join(', ')}`);
    if (problems.length) notify_(`발송 처리 확인 필요 ${problems.length}건`, problems.join('\n'));
  });
}

function shipShopee_(o) {
  const shopId = Number(o['shop_id']) || null;
  const sn = String(o['주문번호']);

  if (o['발송처리'] !== 'SLS송장대기') {
    const param = shopee_('/api/v2/logistics/get_shipping_parameter', { shopId: shopId, params: { order_sn: sn } });
    const need = param.info_needed || {};
    const body = { order_sn: sn };
    if (need.dropoff !== undefined) {
      body.dropoff = {};
    } else if (need.pickup !== undefined) {
      const addr = ((param.pickup || {}).address_list || [])[0];
      const slot = addr && (addr.time_slot_list || [])[0];
      if (!addr || !slot) return { '발송처리': '픽업 주소/시간 없음 — 셀러센터 확인' };
      body.pickup = { address_id: addr.address_id, pickup_time_id: slot.pickup_time_id };
    }
    shopee_('/api/v2/logistics/ship_order', { shopId: shopId, method: 'post', body: body });
  }

  // 송장번호는 발송 요청 직후 바로 안 나올 수 있다 → 다음 실행에서 다시 조회
  const tr = shopee_('/api/v2/logistics/get_tracking_number', { shopId: shopId, params: { order_sn: sn } });
  if (!tr.tracking_number) return { '발송처리': 'SLS송장대기' };
  return {
    '국제송장': tr.tracking_number, '택배사': 'Shopee SLS', '발송처리': '완료',
    '발주상태': '발송완료', '메모': [o['메모'], '송장 라벨은 셀러센터에서 출력'].filter(Boolean).join(' / '),
  };
}

function shipQoo10_(o) {
  if (!o['택배사'] || !o['국제송장']) return { '발송처리': '택배사·국제송장 입력 필요' };
  qoo10SendTracking_(String(o['주문번호']), String(o['택배사']), String(o['국제송장']));
  return { '발송처리': '완료', '발주상태': '발송완료' };
}

// ═════════════ Chat.gs ═════════════
/**
 * 고객 채팅 응대 (30분마다)
 *
 * AI 가 질문을 분류해서
 *  - 배송·상품·사이즈 같은 "정보 질문"은 바로 답장을 보낸다.
 *  - 취소·환불·불만·가격 협상처럼 돈이나 책임이 걸린 질문은 답장 초안만 쓰고 사람에게 넘긴다.
 * 잘못된 약속 한 번이 환불·페널티로 이어지기 때문에, 자동 범위를 일부러 좁게 잡았다.
 *
 * ⚠️ 쇼피 판매자 채팅 API(sellerchat)는 앱 권한이 따로 필요할 수 있다.
 *    권한 오류가 나면 로그에 남기고 채팅 작업만 멈춘다.
 */

const AUTO_REPLY_CATEGORIES = ['shipping', 'product_info', 'greeting'];

const CHAT_SCHEMA = {
  type: 'OBJECT',
  properties: {
    category: { type: 'STRING', enum: ['shipping', 'product_info', 'greeting', 'cancel_refund', 'complaint', 'price', 'other'] },
    reply: { type: 'STRING' },
    summary_ko: { type: 'STRING' },
  },
  required: ['category', 'reply', 'summary_ko'],
};

function chatJob() {
  withLock_('채팅응대', () => {
    const s = settings_();
    const autoSend = s['채팅자동답변'] === true;
    const handled = {};
    readTable_(SHEETS.CHATS).forEach(c => { handled[String(c['메시지ID'])] = true; });
    const escalations = [];

    shopeeMarkets_().filter(m => m.shopId).forEach(m => {
      let convs;
      try {
        convs = shopee_('/api/v2/sellerchat/get_conversation_list', {
          shopId: m.shopId, params: { direction: 'latest', type: 'unread', page_size: 25 },
        }).conversations || [];
      } catch (e) {
        log_('채팅응대', `${m.code} 채팅 목록 실패 (권한 확인 필요): ${e.message}`);
        return;
      }

      convs.forEach(conv => {
        const msgId = String(conv.latest_message_id);
        const text = conv.latest_message_content && conv.latest_message_content.text;
        if (handled[msgId] || !text || conv.latest_message_from_id === m.shopId) return;
        handled[msgId] = true;

        const ai = gemini_(`Market: ${m.code}\nBuyer message:\n${text}`, {
          system: chatSystem_(s), schema: CHAT_SCHEMA,
        });
        const safe = AUTO_REPLY_CATEGORIES.indexOf(ai.category) >= 0;
        let status = '사람확인필요';
        if (safe && autoSend) {
          shopee_('/api/v2/sellerchat/send_message', {
            shopId: m.shopId, method: 'post',
            body: { to_id: conv.to_id, message_type: 'text', content: { text: ai.reply } },
          });
          status = '자동답변';
        } else {
          escalations.push(`• [${m.code}] ${conv.to_name || conv.to_id}: ${ai.summary_ko}\n  고객: ${text}\n  답변초안: ${ai.reply}`);
        }
        appendRow_(SHEETS.CHATS, {
          '시각': new Date(), '국가': m.code, '대화ID': conv.conversation_id, '메시지ID': msgId,
          '고객': conv.to_name || conv.to_id, '고객메시지': text, '분류': ai.category,
          '요약': ai.summary_ko, 'AI답변': ai.reply, '처리': status,
        });
      });
    });

    // 큐텐 재팬 고객 문의 (API 이름이 확인되어 QOO10_METHODS 에 들어간 경우에만)
    if (QOO10_METHODS.inquiries && qoo10Enabled_()) {
      try {
        qoo10Inquiries_(s, autoSend, handled, escalations);
      } catch (e) {
        log_('채팅응대', '큐텐 문의 조회 실패: ' + (e.message || e));
      }
    }

    if (escalations.length) {
      notify_(`고객 문의 ${escalations.length}건 확인 필요`,
        escalations.join('\n\n') + '\n\n쇼피 셀러센터 채팅에서 직접 답변해 주세요.');
    }
  });
}

function chatSystem_(s) {
  return `You are the customer service assistant of a Korean seller on Shopee and Qoo10 Japan.
Reply in the buyer's language, short and polite, as the shop.
Shop facts (do not invent anything beyond these):
- Items are sourced in Korea after the order and shipped from Korea via Shopee's logistics.
- Dispatch within ${s['발송준비일수'] || 3} business days; international delivery usually takes about 5-10 days after dispatch.
- ${s['상점안내'] || 'For order-specific issues, the seller will check and reply soon.'}
Rules:
- Never promise refunds, discounts, cancellations, or exact delivery dates. For those, say the seller
  will check and reply soon, and classify as cancel_refund / complaint / price.
- If product details are not known, say you will check with the seller (category other).
Write summary_ko in Korean for the shop owner.`;
}

function qoo10Inquiries_(s, autoSend, handled, escalations) {
  const pick = (o, names) => { for (const n of names) if (o[n] !== undefined && o[n] !== '') return o[n]; return ''; };
  [].concat(qoo10_(QOO10_METHODS.inquiries, {}) || []).forEach(q => {
    const id = 'Q10-' + pick(q, ['QnaNo', 'qnaNo', 'InquiryNo', 'seq']);
    const text = pick(q, ['Question', 'question', 'Contents', 'contents']);
    if (!text || handled[id]) return;
    handled[id] = true;
    const ai = gemini_(`Market: JP (Qoo10 Japan)\nBuyer message:\n${text}`, { system: chatSystem_(s), schema: CHAT_SCHEMA });
    const safe = AUTO_REPLY_CATEGORIES.indexOf(ai.category) >= 0;
    let status = '사람확인필요';
    if (safe && autoSend && QOO10_METHODS.answerInquiry) {
      qoo10_(QOO10_METHODS.answerInquiry, { QnaNo: id.slice(4), Answer: ai.reply });
      status = '자동답변';
    } else {
      escalations.push(`• [JP 큐텐] ${ai.summary_ko}\n  고객: ${text}\n  답변초안: ${ai.reply}`);
    }
    appendRow_(SHEETS.CHATS, {
      '시각': new Date(), '국가': 'JP', '대화ID': id, '메시지ID': id, '고객': pick(q, ['BuyerName', 'buyer']),
      '고객메시지': text, '분류': ai.category, '요약': ai.summary_ko, 'AI답변': ai.reply, '처리': status,
    });
  });
}

// ═════════════ Demand.gs ═════════════
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
    const notes = gemini_(`You research demand for a Korean seller on Shopee and Qoo10 Japan (market code JP) (cross-border, buys from Korean
wholesalers after each order). Markets: ${codes}. Focus: ${s['관심카테고리'] || 'any category with good margin and light weight'}.
Search for recent (last 6 months) evidence of Korean products selling well in these Shopee markets:
Shopee bestseller/trending pages, Qoo10 Japan rankings and Mega Wari results, campaign news, K-beauty/K-food/K-lifestyle trend articles, TikTok viral items.
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

// ═════════════ Sourcing.gs ═════════════
/**
 * 상품 소싱 (매일 아침): 국내 도매몰에서 키워드로 상품을 찾아 상품 시트에 '대기'로 넣는다.
 *
 * 기본 소싱처는 도매꾹 오픈API(무료 키 발급). 스크립트 속성 DOMEGGOOK_API_KEY 가 없으면
 * 이 작업은 건너뛰고, 상품 시트에 직접 입력한 상품만 등록된다.
 *
 * ⚠️ 도매꾹 API 버전·응답 필드는 발급 후 문서와 대조가 필요하다. 첫 실행 결과를 로그에서 확인할 것.
 * ⚠️ 위탁판매 허용 여부와 이미지 사용 조건은 공급사마다 다르다. 해외 판매 허용 상품만 쓰자.
 */

function sourcingJob() {
  withLock_('소싱', () => {
    const key = secret_('DOMEGGOOK_API_KEY', true);
    if (!key) return log_('소싱', 'DOMEGGOOK_API_KEY 없음 — 자동 소싱 건너뜀');

    const s = settings_();
    const keywords = String(s['소싱키워드'] || '').split(',').map(k => k.trim()).filter(Boolean);
    if (!keywords.length) return log_('소싱', '소싱키워드가 비어 있음');

    const rows = readTable_(SHEETS.PRODUCTS);
    const waiting = rows.filter(r => r['상태'] === '대기').length;
    let need = Number(s['하루등록수'] || 30) - waiting;
    if (need <= 0) return;

    const seen = {};
    rows.forEach(r => { if (r['소싱URL']) seen[r['소싱URL']] = true; });
    const minCost = Number(s['소싱최저가(원)'] || 3000);
    const maxCost = Number(s['소싱최고가(원)'] || 40000);
    const perKeyword = Math.ceil(need / keywords.length);
    let added = 0;

    keywords.forEach(kw => {
      if (need <= 0) return;
      const items = domeggookSearch_(key, kw, 50)
        .filter(it => it.price >= minCost && it.price <= maxCost && !seen[it.url])
        .slice(0, Math.min(perKeyword, need));
      items.forEach(it => {
        seen[it.url] = true;
        appendRow_(SHEETS.PRODUCTS, {
          'SKU': `DMG-${it.no}`, '상태': '대기', '상품명': it.title, '원가(원)': it.price,
          '국내배송비(원)': it.shipFee || 0, '무게(g)': s['기본무게(g)'] || 300,
          '이미지URL': it.image, '소싱URL': it.url, '메모': `키워드: ${kw}`,
        });
        need--; added++;
      });
    });
    log_('소싱', `${added}개 추가 (키워드 ${keywords.join(', ')})`);
  });
}

function domeggookSearch_(key, keyword, size) {
  const url = 'https://domeggook.com/ssl/api/?ver=4.1&mode=getItemList&om=json&market=dome' +
    `&aid=${encodeURIComponent(key)}&kw=${encodeURIComponent(keyword)}&sz=${size}`;
  const res = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
  let data;
  try {
    data = JSON.parse(res.getContentText());
  } catch (e) {
    log_('소싱', `도매꾹 응답 해석 실패 (${res.getResponseCode()}): ${res.getContentText().slice(0, 300)}`);
    return [];
  }
  const list = findItemArray_(data);
  if (!list.length) log_('소싱', `도매꾹 결과 없음/형식 확인 필요: ${JSON.stringify(data).slice(0, 300)}`);
  return list.map(it => ({
    no: it.no || it.itemNo || it.id,
    title: it.title || it.name,
    price: Number(String(it.price || it.unitPrice || 0).replace(/[^0-9]/g, '')),
    shipFee: Number(String((it.deli && it.deli.fee) || 0).replace(/[^0-9]/g, '')),
    image: it.thumb || it.image || '',
    url: it.url || `https://domeggook.com/${it.no}`,
  })).filter(it => it.no && it.title && it.price);
}

/** 응답 구조가 버전마다 달라도 상품 배열을 찾아낸다 */
function findItemArray_(node) {
  if (Array.isArray(node)) return node.length && typeof node[0] === 'object' && ('title' in node[0] || 'no' in node[0]) ? node : [];
  if (node && typeof node === 'object') {
    for (const k of Object.keys(node)) {
      const found = findItemArray_(node[k]);
      if (found.length) return found;
    }
  }
  return [];
}

// ═════════════ Mobile.gs ═════════════
/**
 * 모바일 조작판: '요약' 시트
 *
 * 구글 시트 앱에서는 🛒 쇼피 메뉴가 안 보인다. 대신 체크박스는 앱에서도 누를 수 있으므로,
 * 체크박스를 누르면 "편집 트리거(handleEdit)"가 해당 작업을 실행하고 체크를 다시 푼다.
 * (단순 onEdit 은 외부 API·메일 권한이 없어서, installTriggers 에서 설치형 트리거로 등록한다)
 */

const SUMMARY_SHEET = '요약';

const RUN_BUTTONS = {
  '▶ 상품 등록': 'listingJob',
  '▶ 주문 확인': 'ordersJob',
  '▶ 발송 처리': 'shippingJob',
  '▶ 채팅 응대': 'chatJob',
  '▶ 상품 소싱': 'sourcingJob',
  '▶ 수요 조사': 'demandJob',
};

function setupSummary_(book) {
  if (book.getSheetByName(SUMMARY_SHEET)) return;
  const sh = book.insertSheet(SUMMARY_SHEET, 0);
  const q = name => `'${name}'`;
  const rows = [
    ['오늘 요약', '값'],
    ['오늘 처리한 상품', `=COUNTIF(${q(SHEETS.PRODUCTS)}!R:R,TODAY())+COUNTIF(${q(SHEETS.PRODUCTS)}!R:R,TEXT(TODAY(),"yyyy-mm-dd"))`],
    ['등록 대기 상품', `=COUNTIF(${q(SHEETS.PRODUCTS)}!B:B,"대기")`],
    ['누적 등록완료', `=COUNTIF(${q(SHEETS.PRODUCTS)}!B:B,"등록완료")`],
    ['오류 상품', `=COUNTIF(${q(SHEETS.PRODUCTS)}!B:B,"오류")`],
    ['⚠️ 미발주 주문', `=COUNTIF(${q(SHEETS.ORDERS)}!K:K,"미발주")`],
    ['이번 달 주문', `=COUNTIFS(${q(SHEETS.ORDERS)}!C:C,">="&(EOMONTH(TODAY(),-1)+1))`],
    ['확인 필요 문의 (7일)', `=COUNTIFS(${q(SHEETS.CHATS)}!J:J,"사람확인필요",${q(SHEETS.CHATS)}!A:A,">="&(TODAY()-7))`],
    ['마지막 기록', `=IFERROR(INDEX(${q(SHEETS.LOG)}!C:C,COUNTA(${q(SHEETS.LOG)}!C:C)),"")`],
    ['', ''],
    ['지금 실행 (체크하면 실행)', ''],
  ];
  sh.getRange(1, 1, rows.length, 2).setValues(rows);
  const labels = Object.keys(RUN_BUTTONS);
  const start = rows.length + 1;
  sh.getRange(start, 1, labels.length, 1).setValues(labels.map(l => [l]));
  sh.getRange(start, 2, labels.length, 1).insertCheckboxes();
  sh.getRange(rows.length, 1).setFontWeight('bold');
  sh.setColumnWidth(1, 200);
  sh.setColumnWidth(2, 220);
  styleHeader_(sh);
}

/** 설치형 편집 트리거: 요약 시트의 실행 체크박스 처리 */
function handleEdit(e) {
  const range = e && e.range;
  if (!range || range.getSheet().getName() !== SUMMARY_SHEET || range.getColumn() !== 2) return;
  if (range.getValue() !== true) return;
  const label = range.getSheet().getRange(range.getRow(), 1).getValue();
  const job = RUN_BUTTONS[label];
  if (!job) return;

  range.setNote('실행 중… ' + new Date().toLocaleTimeString('ko-KR'));
  try {
    globalThis[job]();
    range.setNote('완료 ' + new Date().toLocaleString('ko-KR'));
  } catch (err) {
    range.setNote('오류: ' + (err.message || err));
  } finally {
    range.setValue(false);
  }
}

// ═════════════ Setup.gs ═════════════
/**
 * 메뉴 · 초기 설정 · 자동 실행(트리거)
 */

function onOpen() {
  SpreadsheetApp.getUi().createMenu('🛒 쇼피·큐텐')
    .addItem('① 초기 설정 (시트 만들기)', 'setupSheets')
    .addItem('② 쇼피 인증하기', 'showAuthUrl')
    .addItem('③ 연결된 샵 불러오기', 'loadShops')
    .addSeparator()
    .addItem('▶ 자동 실행 켜기', 'installTriggers')
    .addItem('■ 자동 실행 끄기', 'removeTriggers')
    .addSeparator()
    .addItem('지금 실행: 수요 조사', 'demandJob')
    .addItem('지금 실행: 상품 소싱', 'sourcingJob')
    .addItem('지금 실행: 상품 등록', 'listingJob')
    .addItem('지금 실행: 주문 확인', 'ordersJob')
    .addItem('지금 실행: 발송 처리', 'shippingJob')
    .addItem('지금 실행: 채팅 응대', 'chatJob')
    .addToUi();
}

// 함수로 감싼 이유: Apps Script 파일 로드 순서와 무관하게 SHEETS 를 참조하기 위해
function sheetHeaders_() {
  return {
  [SHEETS.PRODUCTS]: ['SKU', '상태', '상품명', '원가(원)', '국내배송비(원)', '무게(g)', '가로(cm)', '세로(cm)', '높이(cm)',
    '이미지URL', '소싱URL', '메모', '위험도', '위험사유', '판매가', 'AI결과', 'global_item_id', '등록일', '오류',
    '큐텐카테고리', '큐텐상품번호', '시장가', '가격판단'],
  [SHEETS.ORDERS]: ['주문번호', '국가', '주문시각', '발송기한', 'SKU', '상품명', '수량', '판매가', '소싱URL',
    '예상원가(원)', '발주상태', '국내송장', '메모', '플랫폼', 'shop_id', '택배사', '국제송장', '발송처리'],
  [SHEETS.CHATS]: ['시각', '국가', '대화ID', '메시지ID', '고객', '고객메시지', '분류', '요약', 'AI답변', '처리'],
  [SHEETS.DEMAND]: ['날짜', '점수', '상품', '검색어', '국가', '수요근거', '가격대', '리스크', '출처'],
  [SHEETS.LOG]: ['시각', '작업', '내용'],
  [SHEETS.MARKETS]: ['국가', '사용', '통화', '언어', '가격단위', '판매수수료율', '결제수수료율', '서비스수수료율',
    '기본배송비(원)', '100g당배송비(원)', '환율대체값', 'shop_id', '플랫폼'],
  };
}

// 수수료·배송비는 예시값 — 쇼피코리아 요율표로 바꾼 뒤 설정의 verified 를 체크
const DEFAULT_MARKETS = [
  ['SG', true, 'SGD', 'en', 0.1, 0.10, 0.03, 0, 3000, 700, 1050, '', 'shopee'],
  ['MY', true, 'MYR', 'en', 0.1, 0.10, 0.03, 0, 3000, 700, 320, '', 'shopee'],
  ['PH', true, 'PHP', 'en', 1, 0.10, 0.03, 0, 3000, 700, 24, '', 'shopee'],
  ['TH', true, 'THB', 'th', 1, 0.10, 0.03, 0, 3000, 700, 41, '', 'shopee'],
  ['VN', true, 'VND', 'vi', 1000, 0.10, 0.03, 0, 3000, 700, 0.055, '', 'shopee'],
  ['TW', true, 'TWD', 'zh-Hant', 1, 0.10, 0.03, 0, 3000, 700, 43, '', 'shopee'],
  ['BR', false, 'BRL', 'pt-BR', 0.1, 0.14, 0.03, 0, 5000, 1200, 250, '', 'shopee'],
  ['ID', false, 'IDR', 'id', 100, 0.10, 0.03, 0, 3000, 700, 0.085, '', 'shopee'],
  // 큐텐 재팬: 판매수수료 6~10%(결제 포함, 카테고리별). 배송비는 한국→일본 소형 소포 예시값
  ['JP', true, 'JPY', 'ja', 10, 0.10, 0, 0, 4000, 500, 9.3, '', 'qoo10'],
];

const DEFAULT_SETTINGS = [
  ['verified', false, '체크해야 쇼피 실제 업로드. 국가 시트의 수수료·배송비를 실제 요율로 바꾼 뒤 체크'],
  ['큐텐verified', false, '체크해야 큐텐 실제 업로드. 큐텐 API 키 연결 + 1개 테스트 후 체크'],
  ['큐텐기본카테고리', '', '큐텐 카테고리 코드 (상품 시트 큐텐카테고리 칸이 비면 사용)'],
  ['큐텐배송코드', '', '큐텐 QSM 에서 만든 배송비 정책 번호(ShippingNo)'],
  ['시장가조사', true, '등록 전 AI가 웹에서 경쟁 판매가를 조사해 가격을 점검'],
  ['저가면자동인상', true, '시장가보다 많이 싸면 시장 최저가 근처까지 자동 인상 (이익 증가)'],
  ['하루등록수', 10, '하루 최대 처리 상품 수. 첫 2주는 10개로 품질 검수 후 30개로'],
  ['회당처리수', 5, '1시간마다 처리할 개수 (실행 1회 6분 제한 때문)'],
  ['목표마진율', 0.2, '판매가 대비 이익률'],
  ['최소이익(원)', 3000, '건당 최소 이익'],
  ['환율버퍼', 0.03, '환율 변동 대비 원가 할증'],
  ['기본무게(g)', 300, '무게를 모를 때 쓰는 값'],
  ['기본재고', 30, '노출용 재고 수량'],
  ['발송준비일수', 3, '주문 후 발송까지 일수 (국가별 허용 범위 확인)'],
  ['예약판매', false, '예약판매로 등록 (발송준비일수를 길게 쓸 때). 쇼피 예약판매 비율 제한 주의'],
  ['주의상품업로드', false, '화장품·식품 등 caution 상품도 업로드'],
  ['채팅자동답변', true, '배송·상품 정보 질문은 AI가 바로 답장'],
  ['상점안내', '', '채팅 AI가 참고할 추가 안내문 (교환/반품 정책 등)'],
  ['알림이메일', '', '비우면 스크립트 소유자 메일'],
  ['Gemini모델', 'gemini-2.5-flash', '무료 등급에서 쓸 모델 (구글 AI Studio 에서 확인)'],
  ['관심카테고리', 'indie K-beauty (lip tint, eyeshadow, blush, toner pads, sheet masks, glow ampoules), K-hair care, beauty tools (puffs, gel nail strips, hair clips)', '수요 조사 방향 (2026년 10월 조사 기준)'],
  ['키워드자동갱신', true, '수요 조사 결과로 소싱키워드 자동 교체'],
  ['소싱키워드', '립틴트, 아이섀도우 팔레트, 블러셔, 토너패드, 마스크팩, 물광 앰플, 헤어 트리트먼트, 헤어 에센스, 메이크업 퍼프, 젤네일 스티커', '도매꾹 검색어 (쉼표 구분). 수요 조사가 매주 갱신'],
  ['소싱최저가(원)', 3000, ''],
  ['소싱최고가(원)', 40000, ''],
];

function setupSheets() {
  const book = SpreadsheetApp.getActiveSpreadsheet();
  PropertiesService.getScriptProperties().setProperty('SHEET_ID', book.getId());

  if (!book.getSheetByName(SHEETS.SETTINGS)) {
    const sh = book.insertSheet(SHEETS.SETTINGS);
    sh.getRange(1, 1, 1, 3).setValues([['항목', '값', '설명']]);
    sh.getRange(2, 1, DEFAULT_SETTINGS.length, 3).setValues(DEFAULT_SETTINGS);
    DEFAULT_SETTINGS.forEach((r, i) => {
      if (typeof r[1] !== 'boolean') return;
      sh.getRange(i + 2, 2).insertCheckboxes();
      sh.getRange(i + 2, 2).setValue(r[1]);
    });
    styleHeader_(sh);
  }

  const SHEET_HEADERS = sheetHeaders_();
  Object.keys(SHEET_HEADERS).forEach(name => {
    if (book.getSheetByName(name)) return addMissingHeaders_(book.getSheetByName(name), SHEET_HEADERS[name]);
    const sh = book.insertSheet(name);
    sh.getRange(1, 1, 1, SHEET_HEADERS[name].length).setValues([SHEET_HEADERS[name]]);
    styleHeader_(sh);
    if (name === SHEETS.MARKETS) {
      sh.getRange(2, 1, DEFAULT_MARKETS.length, DEFAULT_MARKETS[0].length).setValues(DEFAULT_MARKETS);
      sh.getRange(2, 2, DEFAULT_MARKETS.length, 1).insertCheckboxes();
      DEFAULT_MARKETS.forEach((m, i) => sh.getRange(i + 2, 2).setValue(m[1]));
    }
    if (name === SHEETS.PRODUCTS) {
      sh.getRange('B2:B').setDataValidation(SpreadsheetApp.newDataValidation()
        .requireValueInList(['대기', '미리보기', '등록완료', '건너뜀', '오류'], true).build());
    }
    if (name === SHEETS.ORDERS) {
      sh.getRange('K2:K').setDataValidation(SpreadsheetApp.newDataValidation()
        .requireValueInList(['미발주', '발주완료', '발송준비', '발송완료', '취소'], true).build());
    }
  });

  setupSummary_(book);
  addMissingSettings_(book.getSheetByName(SHEETS.SETTINGS));

  const def = book.getSheetByName('시트1') || book.getSheetByName('Sheet1');
  if (def && book.getSheets().length > 1 && def.getLastRow() === 0) book.deleteSheet(def);
  SpreadsheetApp.getActive().toast('시트 준비 완료. 확장 프로그램 > Apps Script > 프로젝트 설정 에서 스크립트 속성을 넣어 주세요.');
}

/** 코드 업데이트로 새 열이 생기면 기존 시트 오른쪽 끝에 덧붙인다 (기존 열 위치는 그대로) */
function addMissingHeaders_(sh, headers) {
  const have = sh.getRange(1, 1, 1, Math.max(sh.getLastColumn(), 1)).getValues()[0];
  headers.filter(h => have.indexOf(h) < 0).forEach(h => {
    sh.getRange(1, sh.getLastColumn() + 1).setValue(h);
  });
  if (sh.getName() === SHEETS.MARKETS) {
    const codes = sh.getRange(1, 1, sh.getLastRow(), 1).getValues().flat();
    const platformCol = headers_(SHEETS.MARKETS).indexOf('플랫폼') + 1;
    DEFAULT_MARKETS.filter(m => codes.indexOf(m[0]) < 0).forEach(m => {
      sh.appendRow(m);
      sh.getRange(sh.getLastRow(), 2).insertCheckboxes().setValue(m[1]);
    });
    // 예전 행에 플랫폼이 비어 있으면 shopee 로 채움
    for (let r = 2; r <= sh.getLastRow(); r++) {
      if (!sh.getRange(r, platformCol).getValue()) sh.getRange(r, platformCol).setValue('shopee');
    }
  }
}

/** 코드 업데이트로 새 설정 항목이 생기면 기존 시트 아래에 덧붙인다 */
function addMissingSettings_(sh) {
  const have = sh.getRange(1, 1, sh.getLastRow(), 1).getValues().flat();
  DEFAULT_SETTINGS.filter(r => have.indexOf(r[0]) < 0).forEach(r => {
    sh.appendRow(r);
    if (typeof r[1] === 'boolean') {
      const cell = sh.getRange(sh.getLastRow(), 2);
      cell.insertCheckboxes();
      cell.setValue(r[1]);
    }
  });
}

function styleHeader_(sh) {
  sh.setFrozenRows(1);
  sh.getRange(1, 1, 1, sh.getLastColumn()).setFontWeight('bold').setBackground('#fde7d9');
}

const JOBS = ['listingJob', 'ordersJob', 'shippingJob', 'chatJob', 'sourcingJob', 'demandJob', 'handleEdit'];

function installTriggers() {
  removeTriggers();
  ScriptApp.newTrigger('listingJob').timeBased().everyHours(1).create();
  ScriptApp.newTrigger('ordersJob').timeBased().everyMinutes(30).create();
  ScriptApp.newTrigger('chatJob').timeBased().everyMinutes(30).create();
  ScriptApp.newTrigger('shippingJob').timeBased().everyHours(1).create();
  ScriptApp.newTrigger('sourcingJob').timeBased().everyDays(1).atHour(7).create();
  ScriptApp.newTrigger('demandJob').timeBased().onWeekDay(ScriptApp.WeekDay.MONDAY).atHour(6).create();
  ScriptApp.newTrigger('handleEdit').forSpreadsheet(book_()).onEdit().create(); // 모바일 실행 체크박스
  SpreadsheetApp.getActive().toast('자동 실행을 켰습니다');
}

function removeTriggers() {
  ScriptApp.getProjectTriggers()
    .filter(t => JOBS.indexOf(t.getHandlerFunction()) >= 0)
    .forEach(t => ScriptApp.deleteTrigger(t));
}
