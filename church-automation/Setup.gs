/** 메뉴 · 초기 설정 · 트리거(자동 실행 예약) */

function onOpen() {
  SpreadsheetApp.getUi().createMenu('⛪ 성찬식 자동화')
    .addItem('1. 초기 설정 (처음 한 번)', 'setup')
    .addItem('2. 카카오톡 연결', 'kakaoConnect')
    .addSeparator()
    .addItem('미리보기: 다음 주 임무·부탁 메시지', 'previewNextWeek')
    .addItem('미리보기: 내일 톡방 공지', 'previewTomorrow')
    .addSeparator()
    .addItem('지금 보내기: 다음 주 임무·부탁 메시지', 'sendNextWeekAssignments')
    .addItem('지금 보내기: 내일 톡방 공지', 'sendTomorrowNotice')
    .addItem('지금 갱신: 성찬식 아젠다 문서', 'updateAgenda')
    .addSeparator()
    .addItem('자동 실행 다시 설치', 'installTriggers')
    .addToUi();
}

function setup() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  let settings = ss.getSheetByName(CONFIG.SETTINGS_SHEET);
  if (!settings) {
    settings = ss.insertSheet(CONFIG.SETTINGS_SHEET, 0);
    settings.appendRow(['항목', '값', '설명']);
    settings.getRange('A1:C1').setFontWeight('bold').setBackground('#f1f3f4');
    settings.setFrozenRows(1);
  }
  // 없는 항목만 추가 (다시 실행해도 입력한 값은 그대로)
  const existing = settings.getDataRange().getValues().map(r => r[0]);
  CONFIG.DEFAULT_SETTINGS.forEach(([key, value, help]) => {
    if (existing.includes(key)) return;
    settings.appendRow([key, key === '알림 이메일' ? Session.getEffectiveUser().getEmail() : value, help]);
  });
  settings.getRange('B:B').setWrap(true);
  settings.setColumnWidth(2, 360);

  if (!ss.getSheetByName(CONFIG.LOG_SHEET)) {
    const log = ss.insertSheet(CONFIG.LOG_SHEET);
    log.appendRow(['시각', '제목', '내용']);
    log.getRange('A1:C1').setFontWeight('bold').setBackground('#f1f3f4');
    log.setFrozenRows(1);
  }

  installTriggers();
  SpreadsheetApp.getUi().alert(
    '초기 설정 완료!\n\n'
    + "1) '설정' 시트에 원본 시트 주소와 아젠다 문서 주소를 붙여넣으세요.\n"
    + "2) 메뉴의 '미리보기'로 메시지가 맞게 나오는지 확인하세요.\n\n"
    + '자동 실행: 일 7시(다음 주 임무) · 토 14시(아젠다) · 토 15시(톡방 공지)');
}

/** 기존 예약을 지우고 다시 만듦 (여러 번 실행해도 중복 안 됨) */
function installTriggers() {
  const S = CONFIG.SCHEDULE;
  const jobs = {
    sendNextWeekAssignments: S.NEXT_WEEK,
    updateAgenda: S.AGENDA,
    sendTomorrowNotice: S.TOMORROW,
  };
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() in jobs)
    .forEach(t => ScriptApp.deleteTrigger(t));
  Object.keys(jobs).forEach(fn => {
    ScriptApp.newTrigger(fn).timeBased().onWeekDay(jobs[fn].day).atHour(jobs[fn].hour).create();
  });
}
