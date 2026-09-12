/**
 * vessel-gas/Setup.gs
 * 최초 1회씩 수동으로 실행하는 설정 함수들.
 * (Apps Script 편집기에서 함수 선택 → ▶ 실행 버튼으로 실행)
 */

/** 1) 토큰이 유효한지 확인 (보기 > 실행 로그에서 결과 확인) */
function testGetMe() {
  const cfg = getConfig_();
  if (!cfg.token) { console.log('스크립트 속성에 TELEGRAM_TOKEN이 없습니다.'); return; }
  const resp = UrlFetchApp.fetch('https://api.telegram.org/bot' + cfg.token + '/getMe',
    { muteHttpExceptions: true });
  console.log(resp.getContentText());
}

/**
 * 2) 웹훅 등록 — 배포(Deploy > New deployment > Web app)한 뒤 나오는 URL을
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

/** 3) 웹훅이 잘 등록됐는지 확인 */
function getWebhookInfo() {
  const cfg = getConfig_();
  const resp = UrlFetchApp.fetch('https://api.telegram.org/bot' + cfg.token + '/getWebhookInfo',
    { muteHttpExceptions: true });
  console.log(resp.getContentText());
}

/**
 * (선택) 실시간 AIS 위치까지 보고 싶은 선박을 등록. 등록 안 해도
 * 봇은 정상 동작한다 — 터미널/선사 정보 + /watch 알림만으로도 충분하다.
 * 예: addDirectoryEntry(['EVER GIVEN', '에버기븐'], '9811000', '');
 */
function seedExampleDirectory() {
  addDirectoryEntry(['EVER GIVEN', '에버기븐', '에버 기븐'], '9811000', '');
  console.log('예시 등록 완료 — VESSEL_DIRECTORY 스크립트 속성 확인');
}
