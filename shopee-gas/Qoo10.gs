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
