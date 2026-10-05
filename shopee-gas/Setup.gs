/**
 * 메뉴 · 초기 설정 · 자동 실행(트리거)
 */

function onOpen() {
  SpreadsheetApp.getUi().createMenu('🛒 쇼피')
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
    .addItem('지금 실행: 채팅 응대', 'chatJob')
    .addToUi();
}

// 함수로 감싼 이유: Apps Script 파일 로드 순서와 무관하게 SHEETS 를 참조하기 위해
function sheetHeaders_() {
  return {
  [SHEETS.PRODUCTS]: ['SKU', '상태', '상품명', '원가(원)', '국내배송비(원)', '무게(g)', '가로(cm)', '세로(cm)', '높이(cm)',
    '이미지URL', '소싱URL', '메모', '위험도', '위험사유', '판매가', 'AI결과', 'global_item_id', '등록일', '오류'],
  [SHEETS.ORDERS]: ['주문번호', '국가', '주문시각', '발송기한', 'SKU', '상품명', '수량', '판매가', '소싱URL',
    '예상원가(원)', '발주상태', '국내송장', '메모'],
  [SHEETS.CHATS]: ['시각', '국가', '대화ID', '메시지ID', '고객', '고객메시지', '분류', '요약', 'AI답변', '처리'],
  [SHEETS.DEMAND]: ['날짜', '점수', '상품', '검색어', '국가', '수요근거', '가격대', '리스크', '출처'],
  [SHEETS.LOG]: ['시각', '작업', '내용'],
  [SHEETS.MARKETS]: ['국가', '사용', '통화', '언어', '가격단위', '판매수수료율', '결제수수료율', '서비스수수료율',
    '기본배송비(원)', '100g당배송비(원)', '환율대체값', 'shop_id'],
  };
}

// 수수료·배송비는 예시값 — 쇼피코리아 요율표로 바꾼 뒤 설정의 verified 를 체크
const DEFAULT_MARKETS = [
  ['SG', true, 'SGD', 'en', 0.1, 0.10, 0.03, 0, 3000, 700, 1050, ''],
  ['MY', true, 'MYR', 'en', 0.1, 0.10, 0.03, 0, 3000, 700, 320, ''],
  ['PH', true, 'PHP', 'en', 1, 0.10, 0.03, 0, 3000, 700, 24, ''],
  ['TH', true, 'THB', 'th', 1, 0.10, 0.03, 0, 3000, 700, 41, ''],
  ['VN', true, 'VND', 'vi', 1000, 0.10, 0.03, 0, 3000, 700, 0.055, ''],
  ['TW', true, 'TWD', 'zh-Hant', 1, 0.10, 0.03, 0, 3000, 700, 43, ''],
  ['BR', true, 'BRL', 'pt-BR', 0.1, 0.14, 0.03, 0, 5000, 1200, 250, ''],
  ['ID', false, 'IDR', 'id', 100, 0.10, 0.03, 0, 3000, 700, 0.085, ''],
];

const DEFAULT_SETTINGS = [
  ['verified', false, '체크해야 실제 업로드. 국가 시트의 수수료·배송비를 실제 요율로 바꾼 뒤 체크'],
  ['하루등록수', 30, '하루 최대 처리 상품 수'],
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
  ['관심카테고리', 'K-beauty tools, K-snacks, stationery, K-pop goods (official)', '수요 조사 방향'],
  ['키워드자동갱신', true, '수요 조사 결과로 소싱키워드 자동 교체'],
  ['소싱키워드', '', '도매꾹 검색어 (쉼표 구분)'],
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
    ['verified', '예약판매', '주의상품업로드', '채팅자동답변', '키워드자동갱신'].forEach(k => {
      const row = DEFAULT_SETTINGS.findIndex(r => r[0] === k) + 2;
      sh.getRange(row, 2).insertCheckboxes();
      sh.getRange(row, 2).setValue(DEFAULT_SETTINGS[row - 2][1]);
    });
    styleHeader_(sh);
  }

  const SHEET_HEADERS = sheetHeaders_();
  Object.keys(SHEET_HEADERS).forEach(name => {
    if (book.getSheetByName(name)) return;
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
        .requireValueInList(['미발주', '발주완료', '발송완료', '취소'], true).build());
    }
  });

  const def = book.getSheetByName('시트1') || book.getSheetByName('Sheet1');
  if (def && book.getSheets().length > 1 && def.getLastRow() === 0) book.deleteSheet(def);
  SpreadsheetApp.getActive().toast('시트 준비 완료. 확장 프로그램 > Apps Script > 프로젝트 설정 에서 스크립트 속성을 넣어 주세요.');
}

function styleHeader_(sh) {
  sh.setFrozenRows(1);
  sh.getRange(1, 1, 1, sh.getLastColumn()).setFontWeight('bold').setBackground('#fde7d9');
}

const JOBS = ['listingJob', 'ordersJob', 'chatJob', 'sourcingJob', 'demandJob'];

function installTriggers() {
  removeTriggers();
  ScriptApp.newTrigger('listingJob').timeBased().everyHours(1).create();
  ScriptApp.newTrigger('ordersJob').timeBased().everyMinutes(30).create();
  ScriptApp.newTrigger('chatJob').timeBased().everyMinutes(30).create();
  ScriptApp.newTrigger('sourcingJob').timeBased().everyDays(1).atHour(7).create();
  ScriptApp.newTrigger('demandJob').timeBased().onWeekDay(ScriptApp.WeekDay.MONDAY).atHour(6).create();
  SpreadsheetApp.getActive().toast('자동 실행을 켰습니다');
}

function removeTriggers() {
  ScriptApp.getProjectTriggers()
    .filter(t => JOBS.indexOf(t.getHandlerFunction()) >= 0)
    .forEach(t => ScriptApp.deleteTrigger(t));
}
