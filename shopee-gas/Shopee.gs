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
