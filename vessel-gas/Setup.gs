/**
 * vessel-gas/Setup.gs
 * 최초 1회씩 수동으로 실행하는 설정 함수들.
 * (Apps Script 편집기에서 함수 선택 → ▶ 실행 버튼으로 실행)
 */

/** 1) 시트 탭 초기화 — VesselDirectory, ManualOverrides 자동 생성 + 예시 데이터 1건 */
function initSheets() {
  getOrCreateSheet_('VesselDirectory', ['Names', 'IMO', 'MMSI', 'Note']);
  getOrCreateSheet_('ManualOverrides', MANUAL_HEADERS_);

  const dirSheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('VesselDirectory');
  if (dirSheet.getLastRow() < 2) {
    dirSheet.appendRow(['EVER GIVEN, 에버기븐, 에버 기븐', '9811000', '',
      '예시 데이터 — 실제 거래하는 선박으로 행을 추가/교체하세요']);
  }
  console.log('시트 초기화 완료: VesselDirectory, ManualOverrides 탭 생성됨.');
}

/** 2) 토큰이 유효한지 확인 (실행 로그에서 결과 확인: 보기 > 실행 로그) */
function testGetMe() {
  const cfg = getConfig_();
  if (!cfg.token) { console.log('스크립트 속성에 TELEGRAM_TOKEN이 없습니다.'); return; }
  const resp = UrlFetchApp.fetch('https://api.telegram.org/bot' + cfg.token + '/getMe',
    { muteHttpExceptions: true });
  console.log(resp.getContentText());
}

/**
 * 3) 웹훅 등록 — 배포(Deploy > New deployment > Web app)한 뒤 나오는 URL을
 *    스크립트 속성 WEBAPP_URL 에 먼저 저장하고 이 함수를 실행한다.
 */
function installWebhook() {
  const cfg = getConfig_();
  const webAppUrl = PropertiesService.getScriptProperties().getProperty('WEBAPP_URL');
  if (!cfg.token) { console.log('TELEGRAM_TOKEN이 없습니다.'); return; }
  if (!webAppUrl) { console.log('스크립트 속성에 WEBAPP_URL을 먼저 저장하세요(배포 후 나오는 웹앱 URL).'); return; }

  const url = 'https://api.telegram.org/bot' + cfg.token + '/setWebhook?url=' + encodeURIComponent(webAppUrl);
  const resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
  console.log(resp.getContentText());
}

/** 4) 웹훅이 잘 등록됐는지 확인 */
function getWebhookInfo() {
  const cfg = getConfig_();
  const resp = UrlFetchApp.fetch('https://api.telegram.org/bot' + cfg.token + '/getWebhookInfo',
    { muteHttpExceptions: true });
  console.log(resp.getContentText());
}
