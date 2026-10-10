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
