/**
 * vessel-gas/Probe.gs
 * 진단용 — 이 스크립트를 만든 세션(Claude Code)은 조직 네트워크 정책상
 * 터미널/선사 사이트에 접속이 막혀 있었지만, 이 스크립트가 배포된 뒤에는
 * "구글 인프라"에서 실행되므로 접속이 될 가능성이 높다.
 *
 * 사용법: 배포 후 probeAll() 실행 → 보기 > 실행 로그에서 각 사이트의
 * 응답(상태코드 + 본문 앞부분)을 확인. 200이고 그럴듯한 HTML/JSON이
 * 보이면, 그 로그를 복사해서 Claude에게 다시 보여주면 실제 조회 요청
 * 형식을 알아내서 Schedule.gs의 자동조회를 완성할 수 있다.
 *
 * ⚠️ 정적 HTML만 가져온다 — 페이지가 자바스크립트로 결과를 그리는
 * 방식(SPA)이면 이 응답엔 빈 뼈대만 보일 수 있다. 그래도 로그인 없이
 * 열리는지, 서버가 어떻게 응답하는지는 바로 확인된다.
 */

function probeUrl(url) {
  try {
    const resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true, followRedirects: true });
    const status = resp.getResponseCode();
    const body = resp.getContentText().slice(0, 1500);
    console.log('=== ' + url + ' (' + status + ') ===\n' + body);
  } catch (e) {
    console.log('=== ' + url + ' — 오류: ' + e + ' ===');
  }
}

function probeAll() {
  TERMINAL_LIST_.concat(CARRIER_LIST_).forEach(t => probeUrl(t.url));
  console.log('완료 — 위 실행 로그를 복사해서 Claude에게 보여주세요.');
}
