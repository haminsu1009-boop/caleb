// ═══════════════ 카카오톡 '나에게 보내기' (Code.gs 맨 아래에 붙여넣기) ═══════════════
// 월요일 안내를 메일 + 내 카톡(나와의 채팅)으로 사람마다 한 통씩 → 길게 눌러 [전달]
//
// 준비 (한 번만)
//  1) https://developers.kakao.com 로그인 → 내 애플리케이션 → 애플리케이션 추가 (이름: 녹번와드 안내)
//  2) 앱 키 → 'REST API 키' 복사 → 아래 KAKAO_REST_KEY 의 '' 안에 붙여넣기
//  3) 카카오 로그인 → 활성화 ON → Redirect URI 에 https://localhost 등록
//  4) 카카오 로그인 → 동의항목 → '카카오톡 메시지 전송' → 선택 동의 → 저장
//  5) 앱 설정 → 플랫폼 → Web 플랫폼 등록 → 사이트 도메인에 https://www.churchofjesuschrist.org
//  6) 저장 후 함수 'kakaoLoginLink' 실행 → 실행 로그에 나온 주소를 브라우저에서 열고 로그인·동의
//     → '사이트에 연결할 수 없음' 화면이 나오면 정상! 주소창의 code= 뒤의 값을 KAKAO_CODE 에 붙여넣고 저장
//  7) 함수 'kakaoConnect' 실행 → 내 카톡에 '연결 완료' 메시지가 오면 끝 (code 는 한 번만 쓰이고 10분 안에 써야 함)
const KAKAO_REST_KEY = '';
const KAKAO_CODE = '';
const KAKAO_REDIRECT = 'https://localhost';
const KAKAO_LIMIT = 200; // 카톡 '나에게 보내기' 한 통 최대 글자 수

function kakaoLoginLink() {
  if (!KAKAO_REST_KEY) throw new Error('KAKAO_REST_KEY 에 REST API 키를 먼저 넣어 주세요.');
  console.log('아래 주소를 열고 로그인·동의하세요:\nhttps://kauth.kakao.com/oauth/authorize'
    + `?client_id=${KAKAO_REST_KEY}&redirect_uri=${encodeURIComponent(KAKAO_REDIRECT)}&response_type=code&scope=talk_message`);
}

function kakaoConnect() {
  const code = String(KAKAO_CODE).replace(/^.*code=/, '').replace(/&.*$/, '').trim();
  if (!code) throw new Error('KAKAO_CODE 에 code= 뒤의 값을 넣어 주세요.');
  kakaoTokenRequest_({ grant_type: 'authorization_code', redirect_uri: KAKAO_REDIRECT, code: code });
  kakaoSend_('✅ 녹번와드 안내 자동화와 카카오톡이 연결되었습니다.', conferenceUrl_(), '연차대회 보기');
  console.log('연결 완료! 내 카톡을 확인하세요.');
}

function kakaoReady_() {
  return !!PropertiesService.getScriptProperties().getProperty('KAKAO_REFRESH_TOKEN');
}

function kakaoTokenRequest_(payload) {
  const props = PropertiesService.getScriptProperties();
  payload.client_id = KAKAO_REST_KEY;
  const res = UrlFetchApp.fetch('https://kauth.kakao.com/oauth/token', { method: 'post', payload: payload, muteHttpExceptions: true });
  if (res.getResponseCode() !== 200) throw new Error('카카오 토큰 오류: ' + res.getContentText());
  const data = JSON.parse(res.getContentText());
  props.setProperty('KAKAO_ACCESS_TOKEN', data.access_token);
  props.setProperty('KAKAO_ACCESS_EXPIRES', String(Date.now() + (data.expires_in - 60) * 1000));
  if (data.refresh_token) props.setProperty('KAKAO_REFRESH_TOKEN', data.refresh_token); // 만료가 가까우면 새로 내려옴
}

/** 액세스 토큰은 몇 시간마다 만료 → 리프레시 토큰으로 자동 재발급 (매주 쓰면 계속 유지됨) */
function kakaoAccessToken_() {
  const props = PropertiesService.getScriptProperties();
  if (Date.now() > Number(props.getProperty('KAKAO_ACCESS_EXPIRES') || 0)) {
    kakaoTokenRequest_({ grant_type: 'refresh_token', refresh_token: props.getProperty('KAKAO_REFRESH_TOKEN') });
  }
  return props.getProperty('KAKAO_ACCESS_TOKEN');
}

/** 내 카톡으로 한 통 (200자 넘으면 줄 단위로 나눠서) — 링크는 메시지 아래 버튼으로 */
function kakaoSend_(text, link, buttonTitle) {
  const chunks = [];
  let cur = '';
  text.split('\n').forEach(line => {
    const next = cur ? cur + '\n' + line : line;
    if (next.length > KAKAO_LIMIT && cur) { chunks.push(cur); cur = line.slice(0, KAKAO_LIMIT); }
    else cur = next.slice(0, KAKAO_LIMIT);
  });
  if (cur.trim()) chunks.push(cur);
  chunks.forEach(chunk => {
    const template = { object_type: 'text', text: chunk, link: { web_url: link, mobile_web_url: link }, button_title: buttonTitle || '자세히 보기' };
    const res = UrlFetchApp.fetch('https://kapi.kakao.com/v2/api/talk/memo/default/send', {
      method: 'post',
      headers: { Authorization: 'Bearer ' + kakaoAccessToken_() },
      payload: { template_object: JSON.stringify(template) },
      muteHttpExceptions: true,
    });
    if (res.getResponseCode() !== 200) throw new Error('카카오 전송 오류: ' + res.getContentText());
  });
}

function conferenceUrl_() {
  return typeof CONFERENCE_URL !== 'undefined' ? CONFERENCE_URL
    : 'https://www.churchofjesuschrist.org/study/general-conference/2026/10?lang=kor';
}

/** (위의 sendTalkNotices 를 대신함) 메일 한 통 + 내 카톡으로 사람마다 한 통씩 */
function sendTalkNotices(base) {
  const today = base instanceof Date ? base : new Date();
  const thisSunday = upcomingSunday_(today);
  const ahead = plusDays_(thisSunday, 7 * NOTICE_WEEKS_AHEAD);
  const notices = noticeMessages_(ahead, 'notice');
  const reminds = noticeMessages_(thisSunday, 'remind');
  if (!notices.length && !reminds.length) return console.log('보낼 안내가 없습니다.');

  // 1) 메일 (전체 모음)
  const block = (title, list) => `■ ${title}\n\n` + (list.length ? list.join('\n\n────────────\n\n') : '(보낼 분 없음)') + '\n\n';
  report_(`[말씀·기도 안내] ${fmt_(ahead, 'M/d')} 주제 안내 · ${fmt_(thisSunday, 'M/d')} 리마인드`,
    '아래 문구를 복사해서 각자 개인톡으로 보내 주세요.\n\n'
    + block(`${fmt_(ahead, 'M/d')} 주제 안내 (${NOTICE_WEEKS_AHEAD}주 전)`, notices)
    + block(`${fmt_(thisSunday, 'M/d')} 리마인드 (이번 주)`, reminds));

  // 2) 내 카톡 — 사람마다 한 통 (링크는 글에서 빼고 버튼으로)
  if (!kakaoReady_()) return console.log('카카오톡이 연결되지 않아 메일로만 보냈습니다. (kakaoConnect 참고)');
  kakaoSend_(`📋 이번 주 보낼 안내\n· ${fmt_(ahead, 'M/d')} 주제 안내 ${notices.length}통\n· ${fmt_(thisSunday, 'M/d')} 리마인드 ${reminds.length}통\n\n아래 메시지를 하나씩 길게 눌러 [전달] → 그분을 선택하세요.`,
    conferenceUrl_(), '연차대회 보기');
  [...notices, ...reminds].forEach(msg => {
    const url = (msg.match(/https?:\/\/\S+/) || [])[0];
    const text = msg.replace(/\n?https?:\/\/\S+/, '').replace(/링크 공유드립니다\./, '말씀을 아래 버튼으로 공유드립니다.').trim();
    kakaoSend_(text, url || conferenceUrl_(), url ? '연차대회 말씀 보기' : '확인');
    Utilities.sleep(300);
  });
  console.log(`카톡으로 ${notices.length + reminds.length + 1}통 보냈습니다.`);
}
