/**
 * vessel-gas/Probe.gs
 * 진단용 — 이 스크립트를 만든 세션(Claude Code)은 조직 네트워크 정책상
 * 터미널/선사 사이트에 접속이 막혀 있었지만, 이 스크립트가 배포된 뒤에는
 * "구글 인프라"에서 실행되므로 접속이 될 가능성이 높다.
 *
 * 사용법: 배포 후 아래 probeAll()을 한 번 실행하면 "Probe" 시트 탭에
 * 터미널/선사 페이지 응답(상태코드 + 본문 앞부분)이 쌓인다. 그 시트
 * 내용을 복사해서 Claude에게 다시 보여주면, 실제 조회 요청 형식을
 * 알아내서 vessel-gas/Schedule.gs의 자동조회를 완성할 수 있다.
 *
 * ⚠️ 정적 HTML만 가져온다 — 페이지가 자바스크립트로 검색 결과를 그리는
 * 방식(SPA)이면 이 응답엔 빈 뼈대만 보일 수 있다. 그래도 페이지가
 * 로그인 없이 열리는지, 어떤 서버 응답을 주는지 정도는 바로 확인된다.
 */

function probeUrl(url) {
  const sheet = getOrCreateSheet_('Probe', ['URL', 'Status', 'Body(앞 2000자)', 'CheckedAt']);
  let status = '', body = '';
  try {
    const resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true, followRedirects: true });
    status = String(resp.getResponseCode());
    body = resp.getContentText().slice(0, 2000);
  } catch (e) {
    status = 'ERROR';
    body = String(e);
  }
  sheet.appendRow([url, status, body, new Date()]);
  console.log(url + ' -> ' + status);
}

function probeAll() {
  TERMINAL_LIST_.concat(CARRIER_LIST_).forEach(t => probeUrl(t.url));
  console.log('완료 — "Probe" 시트 탭을 확인하세요.');
}
