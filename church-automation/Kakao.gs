/**
 * 카카오톡 '나에게 보내기' (Kakao REST API · 메시지 API)
 *
 * 공식 API로는 단체 대화방에 직접 글을 올릴 수 없습니다.
 * 그래서 내 카톡으로 받은 뒤 → 단톡방에 '전달' 한 번 누르는 방식입니다.
 */
const KAKAO_REDIRECT_URI = 'https://localhost';
const KAKAO_TEXT_LIMIT = 200; // 카카오 텍스트 템플릿 최대 글자 수

/** 메뉴 → '카카오톡 연결' : 최초 1회 로그인해서 토큰 받기 */
function kakaoConnect() {
  const ui = SpreadsheetApp.getUi();
  const props = PropertiesService.getScriptProperties();

  let key = props.getProperty('KAKAO_REST_KEY');
  if (!key) {
    const r = ui.prompt('카카오 REST API 키', 'Kakao Developers > 내 애플리케이션 > 앱 키 > REST API 키를 붙여넣으세요.', ui.ButtonSet.OK_CANCEL);
    if (r.getSelectedButton() !== ui.Button.OK) return;
    key = r.getResponseText().trim();
    props.setProperty('KAKAO_REST_KEY', key);
  }

  const authUrl = 'https://kauth.kakao.com/oauth/authorize'
    + `?client_id=${encodeURIComponent(key)}`
    + `&redirect_uri=${encodeURIComponent(KAKAO_REDIRECT_URI)}`
    + '&response_type=code&scope=talk_message';

  const r = ui.prompt(
    '카카오 로그인',
    `1) 아래 주소를 브라우저에 붙여넣고 로그인·동의하세요.\n\n${authUrl}\n\n`
      + '2) "사이트에 연결할 수 없음" 화면이 떠도 정상입니다.\n'
      + '   주소창의 code= 뒤의 값을 복사해 아래에 붙여넣으세요.',
    ui.ButtonSet.OK_CANCEL);
  if (r.getSelectedButton() !== ui.Button.OK) return;

  const code = r.getResponseText().trim().replace(/^.*code=/, '').replace(/&.*$/, '');
  kakaoTokenRequest_({ grant_type: 'authorization_code', redirect_uri: KAKAO_REDIRECT_URI, code: code });
  kakaoSendToMe_('✅ 교회 자동화와 카카오톡이 연결되었습니다.', SpreadsheetApp.getActiveSpreadsheet().getUrl());
  ui.alert('연결 완료! 내 카카오톡을 확인해 보세요.');
}

function kakaoIsConnected_() {
  return !!PropertiesService.getScriptProperties().getProperty('KAKAO_REFRESH_TOKEN');
}

function kakaoTokenRequest_(payload) {
  const props = PropertiesService.getScriptProperties();
  payload.client_id = props.getProperty('KAKAO_REST_KEY');
  const secret = props.getProperty('KAKAO_CLIENT_SECRET');
  if (secret) payload.client_secret = secret;

  const res = UrlFetchApp.fetch('https://kauth.kakao.com/oauth/token', {
    method: 'post', payload: payload, muteHttpExceptions: true,
  });
  if (res.getResponseCode() !== 200) throw new Error('카카오 토큰 오류: ' + res.getContentText());

  const data = JSON.parse(res.getContentText());
  props.setProperty('KAKAO_ACCESS_TOKEN', data.access_token);
  props.setProperty('KAKAO_ACCESS_EXPIRES', String(Date.now() + (data.expires_in - 60) * 1000));
  // 리프레시 토큰은 만료가 가까울 때만 새로 내려옴 → 올 때마다 저장
  if (data.refresh_token) props.setProperty('KAKAO_REFRESH_TOKEN', data.refresh_token);
}

/** 액세스 토큰은 몇 시간마다 만료 → 리프레시 토큰으로 자동 재발급 */
function kakaoAccessToken_() {
  const props = PropertiesService.getScriptProperties();
  if (Date.now() > Number(props.getProperty('KAKAO_ACCESS_EXPIRES') || 0)) {
    kakaoTokenRequest_({ grant_type: 'refresh_token', refresh_token: props.getProperty('KAKAO_REFRESH_TOKEN') });
  }
  return props.getProperty('KAKAO_ACCESS_TOKEN');
}

/** 긴 글은 줄 단위로 200자 이하 조각으로 나눠 여러 번 보냄 */
function kakaoSendToMe_(text, linkUrl) {
  kakaoChunks_(text).forEach(chunk => {
    const template = {
      object_type: 'text',
      text: chunk,
      link: { web_url: linkUrl, mobile_web_url: linkUrl },
      button_title: '자세히 보기',
    };
    const res = UrlFetchApp.fetch('https://kapi.kakao.com/v2/api/talk/memo/default/send', {
      method: 'post',
      headers: { Authorization: 'Bearer ' + kakaoAccessToken_() },
      payload: { template_object: JSON.stringify(template) },
      muteHttpExceptions: true,
    });
    if (res.getResponseCode() !== 200) throw new Error('카카오 전송 오류: ' + res.getContentText());
  });
}

function kakaoChunks_(text) {
  const chunks = [];
  let cur = '';
  text.split('\n').forEach(line => {
    while (line.length > KAKAO_TEXT_LIMIT) {
      if (cur) chunks.push(cur), (cur = '');
      chunks.push(line.slice(0, KAKAO_TEXT_LIMIT));
      line = line.slice(KAKAO_TEXT_LIMIT);
    }
    const next = cur ? cur + '\n' + line : line;
    if (next.length > KAKAO_TEXT_LIMIT) chunks.push(cur), (cur = line);
    else cur = next;
  });
  if (cur.trim()) chunks.push(cur);
  return chunks;
}
