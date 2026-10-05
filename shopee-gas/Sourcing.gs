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
