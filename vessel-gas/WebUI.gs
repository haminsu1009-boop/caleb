/**
 * vessel-gas/WebUI.gs
 * 브라우저로 직접 여는 조회 화면 — 유니패스 알림봇 앱처럼 텔레그램 없이
 * 모선명/항차를 입력해서 바로 조회한다.
 *
 * 배포된 웹앱 URL을 그냥 GET으로 열면 이 화면이 뜨고(doGet), 텔레그램이
 * 보내는 POST 요청은 doPost(Code.gs)가 그대로 처리한다 — 배포 하나로 둘 다 된다.
 *
 *   https://.../exec           → 조회 화면
 *   https://.../exec?probe=1   → 터미널·선사 연결 진단 화면
 */

function doGet(e) {
  if (e && e.parameter && e.parameter.probe === '1') {
    return renderProbePage_();
  }
  return HtmlService.createHtmlOutputFromFile('WebApp')
    .setTitle('선박 추적')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

/** 웹페이지에서 google.script.run으로 호출하는 서버함수 */
function trackFromWeb(vesselName, voyageNo) {
  return track(vesselName, voyageNo);
}

/** ?probe=1 로 열었을 때 — 터미널/선사 사이트에 실제로 접속해보고 결과를 화면에 보여준다 */
function renderProbePage_() {
  const targets = TERMINAL_LIST_.concat(CARRIER_LIST_);
  const rows = targets.map(t => {
    let status, body;
    try {
      const resp = UrlFetchApp.fetch(t.url, { muteHttpExceptions: true, followRedirects: true });
      status = resp.getResponseCode();
      body = resp.getContentText().slice(0, 500);
    } catch (err) {
      status = 'ERROR';
      body = String(err);
    }
    return { name: t.name, url: t.url, status: status, body: body };
  });

  const template = HtmlService.createTemplateFromFile('ProbePage');
  template.rows = rows;
  return template.evaluate().setTitle('연결 진단');
}
