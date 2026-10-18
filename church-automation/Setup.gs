/** 메뉴 · 초기 설정 · 트리거(자동 실행 예약) */

function onOpen() {
  SpreadsheetApp.getUi().createMenu('⛪ 교회 자동화')
    .addItem('1. 초기 설정 (처음 한 번)', 'setup')
    .addItem('2. 카카오톡 연결', 'kakaoConnect')
    .addSeparator()
    .addItem('지금 보내기: 주일 말씀 주제', 'sendWeeklyTopic')
    .addItem('지금 보내기: 오늘의 기도 리마인드', 'sendDailyReminder')
    .addItem('지금 갱신: 성찬식 문서', 'updateCommunionAgenda')
    .addSeparator()
    .addItem('자동 실행 다시 설치', 'installTriggers')
    .addToUi();
}

function setup() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sunday = upcomingSunday_(new Date());

  ensureSheet_(ss, CONFIG.SHEETS.SETTINGS, CONFIG.HEADERS.SETTINGS, [
    ['교회 이름', '우리교회'],
    ['알림 이메일', Session.getEffectiveUser().getEmail()], // 쉼표로 여러 명 가능
    ['성찬식 문서 ID', ''],
  ]);
  ensureSheet_(ss, CONFIG.SHEETS.SERMON, CONFIG.HEADERS.SERMON, [
    [sunday, '(예시) 두려워하지 말라', '이사야 41:10', '두려워하지 말라 내가 너와 함께 함이라', '담임목사', ''],
  ]);
  ensureSheet_(ss, CONFIG.SHEETS.PRAYER, CONFIG.HEADERS.PRAYER, [
    [new Date(), '(예시) 홍길동', '어머니 수술 회복', '공개', '진행중'],
  ]);
  ensureSheet_(ss, CONFIG.SHEETS.COMMUNION, CONFIG.HEADERS.COMMUNION, [
    [sunday, '담임목사', '김장로', '이권사', '박집사, 최집사', '찬송가 227장', '여전도회', ''],
  ]);

  const prayer = ss.getSheetByName(CONFIG.SHEETS.PRAYER);
  prayer.getRange('D2:D').setDataValidation(
    SpreadsheetApp.newDataValidation().requireValueInList(['공개', '비공개']).build());
  prayer.getRange('E2:E').setDataValidation(
    SpreadsheetApp.newDataValidation().requireValueInList(['진행중', '응답']).build());

  getAgendaDoc_();
  installTriggers();
  SpreadsheetApp.getUi().alert(
    '초기 설정 완료!\n\n'
    + '• 토 20시: 주일 말씀 주제 전송\n• 매일 7시: 말씀·기도 리마인드\n• 목 9시: 성찬식 문서 갱신\n\n'
    + "'설정' 시트에서 교회 이름과 알림 이메일을 확인하세요.");
}

function ensureSheet_(ss, name, headers, sampleRows) {
  if (ss.getSheetByName(name)) return;
  const sheet = ss.insertSheet(name);
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]).setFontWeight('bold').setBackground('#f1f3f4');
  sheet.setFrozenRows(1);
  if (sampleRows.length) sheet.getRange(2, 1, sampleRows.length, headers.length).setValues(sampleRows);
  if (headers[0].includes('날짜') || headers[0] === '등록일') sheet.getRange('A2:A').setNumberFormat('yyyy-mm-dd');
  sheet.autoResizeColumns(1, headers.length);
}

/** 기존 예약을 지우고 다시 만듦 (여러 번 실행해도 중복 안 됨) */
function installTriggers() {
  const jobs = ['sendWeeklyTopic', 'sendDailyReminder', 'updateCommunionAgenda'];
  ScriptApp.getProjectTriggers()
    .filter(t => jobs.includes(t.getHandlerFunction()))
    .forEach(t => ScriptApp.deleteTrigger(t));

  const S = CONFIG.SCHEDULE;
  ScriptApp.newTrigger('sendWeeklyTopic').timeBased()
    .onWeekDay(S.WEEKLY_TOPIC.day).atHour(S.WEEKLY_TOPIC.hour).create();
  ScriptApp.newTrigger('sendDailyReminder').timeBased()
    .everyDays(1).atHour(S.DAILY_REMINDER.hour).create();
  ScriptApp.newTrigger('updateCommunionAgenda').timeBased()
    .onWeekDay(S.COMMUNION_AGENDA.day).atHour(S.COMMUNION_AGENDA.hour).create();
}
