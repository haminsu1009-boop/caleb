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

/** 사용(체크)된 국가만 */
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
    }));
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
  if (to) MailApp.sendEmail(to, `[쇼피 자동화] ${subject}`, body);
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
