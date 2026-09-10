// =====================================================================
// 유니패스 통관 상태 알림 - 멀티유저 웹앱 + 텔레그램 봇 + 카카오 나에게 보내기
// =====================================================================

var CONFIG = {
  UNIPASS_API_KEY: 'n250i296j006s253p060c040h5',
  TELEGRAM_BOT_TOKEN: '8901206831:AAF2cPkHwSVjaqFyNqvO-ke5B-ubXFLYveg',
  KAKAO_REST_API_KEY: '3785705a2781022b8a44c6475b0176a1',
  BL_YEAR: '2026',
};

var UNIPASS_URL = 'https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo';

// =====================================================================
// 웹앱 진입점
// =====================================================================
function doGet(e) {
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle('유니패스 통관 알림')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

// =====================================================================
// 텔레그램 봇 Webhook 진입점
// =====================================================================
function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    var message = data.message || data.edited_message;
    if (!message) return ContentService.createTextOutput('ok');
    var chatId = String(message.chat.id);
    var text = (message.text || '').trim();

    if (text.startsWith('/start')) {
      registerUser_(chatId);
      sendTelegram_(chatId, '👋 안녕하세요! 유니패스 통관 알림 봇입니다.\n\n'
        + '사용 가능한 명령어:\n'
        + '/add BL번호 - BL 추가\n'
        + '/remove BL번호 - BL 삭제\n'
        + '/list - BL 목록 보기\n'
        + '/status - 현재 상태 조회\n'
        + '/trigger 분 - 자동체크 설정 (1/5/10/30)\n'
        + '/stop - 자동체크 중지\n'
        + '\n웹앱에서도 관리하실 수 있습니다!');
    } else if (text.startsWith('/add ')) {
      var blNo = text.replace('/add ', '').trim().toUpperCase();
      var result = addBL(chatId, blNo);
      sendTelegram_(chatId, result.message);
    } else if (text.startsWith('/remove ')) {
      var blNo = text.replace('/remove ', '').trim().toUpperCase();
      var result = removeBL(chatId, blNo);
      sendTelegram_(chatId, result.message);
    } else if (text === '/list') {
      var userData = getUserData_(chatId);
      var bls = userData.bls || [];
      if (bls.length === 0) {
        sendTelegram_(chatId, '등록된 BL이 없습니다. /add BL번호 로 추가하세요.');
      } else {
        sendTelegram_(chatId, '📋 등록된 BL 목록:\n' + bls.map(function(b, i) { return (i+1) + '. ' + b; }).join('\n'));
      }
    } else if (text === '/status') {
      checkAndNotifyUser_(chatId, true);
    } else if (text.startsWith('/trigger ')) {
      var min = parseInt(text.replace('/trigger ', '').trim(), 10);
      if ([1, 5, 10, 30].indexOf(min) === -1) {
        sendTelegram_(chatId, '1, 5, 10, 30 중 하나를 입력하세요.\n예: /trigger 5');
      } else {
        setTrigger(min, chatId);
        sendTelegram_(chatId, '⏱ ' + min + '분마다 자동 체크가 설정되었습니다.');
      }
    } else if (text === '/stop') {
      stopTrigger();
      sendTelegram_(chatId, '⏹ 자동 체크가 중지되었습니다.');
    }
  } catch(err) {
    Logger.log('doPost error: ' + err);
  }
  return ContentService.createTextOutput('ok');
}

// =====================================================================
// 웹훅 등록 (최초 1회, 또는 재배포 후 실행)
// =====================================================================
function setWebhook() {
  var webAppUrl = ScriptApp.getService().getUrl();
  var url = 'https://api.telegram.org/bot' + CONFIG.TELEGRAM_BOT_TOKEN
    + '/setWebhook?url=' + encodeURIComponent(webAppUrl);
  var resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
  Logger.log('Webhook 설정: ' + resp.getContentText());
}

// =====================================================================
// 사용자 데이터 관리
// =====================================================================
function getUserData_(chatId) {
  var props = PropertiesService.getScriptProperties();
  var raw = props.getProperty('USER_' + chatId);
  return raw ? JSON.parse(raw) : { bls: [], kakaoToken: null };
}

function saveUserData_(chatId, data) {
  var props = PropertiesService.getScriptProperties();
  props.setProperty('USER_' + chatId, JSON.stringify(data));
}

function getAllUsers_() {
  var props = PropertiesService.getScriptProperties();
  var raw = props.getProperty('ALL_USERS');
  return raw ? JSON.parse(raw) : [];
}

function saveAllUsers_(users) {
  var props = PropertiesService.getScriptProperties();
  props.setProperty('ALL_USERS', JSON.stringify(users));
}

function registerUser_(chatId) {
  var users = getAllUsers_();
  if (users.indexOf(chatId) === -1) {
    users.push(chatId);
    saveAllUsers_(users);
  }
  var data = getUserData_(chatId);
  if (!data.bls) data.bls = [];
  saveUserData_(chatId, data);
}

// =====================================================================
// 웹앱에서 호출하는 함수들
// =====================================================================
function getUserInfo(chatId) {
  chatId = String(chatId);
  registerUser_(chatId);
  var data = getUserData_(chatId);
  var trigger = getTriggerStatus();
  return {
    chatId: chatId,
    bls: data.bls || [],
    trigger: trigger,
    kakaoLinked: !!(data.kakaoToken),
  };
}

function addBL(chatId, blNo) {
  chatId = String(chatId);
  blNo = blNo.trim().toUpperCase();
  if (!blNo) return { success: false, message: 'BL번호를 입력하세요.' };
  registerUser_(chatId);
  var data = getUserData_(chatId);
  if (!data.bls) data.bls = [];
  if (data.bls.indexOf(blNo) !== -1) {
    return { success: false, message: blNo + ' 은 이미 등록되어 있습니다.', bls: data.bls };
  }
  data.bls.push(blNo);
  saveUserData_(chatId, data);

  // 추가 즉시 1회 조회 및 상태 저장 (이후 변경 감지 기준점)
  try {
    var records = fetchCargoProgress_(blNo, CONFIG.BL_YEAR);
    if (records.length > 0) {
      var latest = pickLatest_(records);
      var sl = summaryLine_(latest);
      var props = PropertiesService.getScriptProperties();
      props.setProperty('STATE_' + chatId + '_' + blNo, JSON.stringify({ summaryLine: sl }));
    }
  } catch(e) {}

  // 트리거가 없으면 자동으로 5분 트리거 시작
  var trigger = getTriggerStatus();
  if (!trigger.active) {
    setTrigger(5, chatId);
    return { success: true, message: '✅ ' + blNo + ' 추가 완료!\n(트리거가 없어 5분마다 자동 체크를 시작합니다)', bls: data.bls };
  }

  return { success: true, message: '✅ ' + blNo + ' 추가 완료!', bls: data.bls };
}

function removeBL(chatId, blNo) {
  chatId = String(chatId);
  blNo = blNo.trim().toUpperCase();
  var data = getUserData_(chatId);
  if (!data.bls) data.bls = [];
  var idx = data.bls.indexOf(blNo);
  if (idx === -1) return { success: false, message: blNo + ' 을 찾을 수 없습니다.', bls: data.bls };
  data.bls.splice(idx, 1);
  saveUserData_(chatId, data);
  // 해당 BL 상태 키 삭제
  PropertiesService.getScriptProperties().deleteProperty('STATE_' + chatId + '_' + blNo);
  return { success: true, message: '🗑 ' + blNo + ' 삭제 완료!', bls: data.bls };
}

function setTrigger(minutes, chatId) {
  // 기존 트리거 모두 제거
  deleteAllTriggers();
  // 새 트리거 등록
  ScriptApp.newTrigger('run')
    .timeBased()
    .everyMinutes(minutes)
    .create();
  PropertiesService.getScriptProperties().setProperty('TRIGGER_MINUTES', String(minutes));

  // 요청한 사용자에게만 즉시 현재 상태 알림
  if (chatId) {
    checkAndNotifyUser_(String(chatId), false);
  }
}

function stopTrigger() {
  deleteAllTriggers();
  PropertiesService.getScriptProperties().deleteProperty('TRIGGER_MINUTES');
}

function getTriggerStatus() {
  var triggers = ScriptApp.getProjectTriggers();
  var active = triggers.some(function(t) { return t.getHandlerFunction() === 'run'; });
  var minutes = PropertiesService.getScriptProperties().getProperty('TRIGGER_MINUTES');
  return { active: active, minutes: minutes ? parseInt(minutes, 10) : null };
}

function deleteAllTriggers() {
  ScriptApp.getProjectTriggers().forEach(function(t) {
    ScriptApp.deleteTrigger(t);
  });
}

// =====================================================================
// 자동 체크 실행 (트리거에 의해 주기적으로 호출)
// =====================================================================
function run() {
  var users = getAllUsers_();
  users.forEach(function(chatId) {
    checkAndNotifyUser_(chatId, false);
  });
}

function checkAndNotifyUser_(chatId, forceNotify) {
  var data = getUserData_(chatId);
  var bls = data.bls || [];
  if (bls.length === 0) return;

  bls.forEach(function(blNo) {
    checkBL_(chatId, blNo, CONFIG.BL_YEAR, forceNotify, data.kakaoToken);
  });
}

function checkBL_(chatId, blNo, blYear, forceNotify, kakaoToken) {
  var stateKey = 'STATE_' + chatId + '_' + blNo;
  var props = PropertiesService.getScriptProperties();

  var records;
  try {
    records = fetchCargoProgress_(blNo, blYear);
  } catch(e) {
    Logger.log('[' + chatId + '] ' + blNo + ' 조회 실패: ' + e);
    return;
  }

  // 조회 결과 없으면 알림 안 함
  if (!records || records.length === 0) {
    Logger.log('[' + chatId + '] ' + blNo + ' 조회결과 없음, 알림 생략');
    return;
  }

  var latest = pickLatest_(records);
  var sl = summaryLine_(latest);
  var prevRaw = props.getProperty(stateKey);
  var prev = prevRaw ? JSON.parse(prevRaw) : null;
  var changed = !prev || prev.summaryLine !== sl;

  if (changed || forceNotify) {
    var msg = formatMessage_(blNo, !prev && !forceNotify, forceNotify ? null : (prev ? prev.summaryLine : null), latest);
    sendTelegram_(chatId, msg);
    if (kakaoToken) {
      try { sendKakao_(kakaoToken, msg.replace(/<[^>]+>/g, '')); } catch(e) { Logger.log('카카오 전송 실패: ' + e); }
    }
    Logger.log('[' + chatId + '] ' + blNo + ' 상태변경 알림');
  } else {
    Logger.log('[' + chatId + '] ' + blNo + ' 변경없음');
  }

  props.setProperty(stateKey, JSON.stringify({ summaryLine: sl }));
}

// =====================================================================
// 유니패스 API 조회
// =====================================================================
function fetchCargoProgress_(blNo, blYear) {
  var base = UNIPASS_URL + '?crkyCn=' + encodeURIComponent(CONFIG.UNIPASS_API_KEY);
  var yearParam = blYear ? '&blYy=' + encodeURIComponent(blYear) : '';
  var paramSets = [
    '&mblNo=' + encodeURIComponent(blNo) + yearParam,
    '&hblNo=' + encodeURIComponent(blNo) + yearParam,
  ];
  for (var i = 0; i < paramSets.length; i++) {
    var records = [];
    for (var attempt = 0; attempt < 3; attempt++) {
      try {
        var resp = UrlFetchApp.fetch(base + paramSets[i], { muteHttpExceptions: true });
        var doc = XmlService.parse(resp.getContentText());
        collectRecords_(doc.getRootElement(), records);
        if (records.length > 0) return records;
        break;
      } catch(e) {
        if (attempt === 2) Logger.log('API 오류 3회 실패: ' + e);
        else Utilities.sleep(1000);
      }
    }
  }
  return [];
}

function collectRecords_(el, out) {
  var name = el.getName();
  var children = el.getChildren();
  if (name.indexOf('cargCsclPrgsInfo') !== -1 && name.indexOf('RtnVo') === -1 && children.length > 0 && !el.getChild('tCnt')) {
    var record = {};
    children.forEach(function(c) { record[c.getName()] = c.getText().trim(); });
    out.push(record);
  }
  children.forEach(function(c) { collectRecords_(c, out); });
}

function pickLatest_(records) {
  var candidates = records.filter(function(r) {
    return !!(r.cargTrcnRelaBsopTpcd || r.csclPrgsStts || r.prgsStts || r.cargTrcnRsltNm);
  });
  var pool = candidates.length > 0 ? candidates : records;
  return pool.reduce(function(best, r) {
    return recordTime_(r) >= recordTime_(best) ? r : best;
  }, pool[0]);
}

function recordTime_(r) {
  return r.prcsDttm || r.cargTrcnPrcsDttm || r.prcsDt || '';
}

function summaryLine_(r) {
  var status = r.cargTrcnRelaBsopTpcd || r.csclPrgsStts || r.prgsStts || r.cargTrcnRsltNm;
  var date = formatDttm_(r.prcsDttm || r.cargTrcnPrcsDttm || r.prcsDt);
  if (status) return date ? (status + '|' + date) : status;
  var parts = [];
  for (var k in r) { if (r[k]) parts.push(k + '=' + r[k]); }
  return parts.join(',');
}

function formatMessage_(blNo, isFirst, prevLine, latest) {
  var status = latest.cargTrcnRelaBsopTpcd || latest.csclPrgsStts || latest.prgsStts || latest.cargTrcnRsltNm || '-';
  var statusAt = formatDttm_(latest.prcsDttm || latest.cargTrcnPrcsDttm || latest.prcsDt);
  var checkedAt = Utilities.formatDate(new Date(), 'Asia/Seoul', 'MM월 dd일 HH시 mm분');
  var header = isFirst ? '📦 모니터링 시작' : (prevLine === null ? '📌 현재 상태' : '🔔 상태 변경!');
  var lines = [
    '<b>' + header + '</b>',
    '',
    '🚢 BL번호: <code>' + blNo + '</code>',
    '',
    '📌 현재 상태: <b>' + status + '</b>',
    '🕐 상태 발생: ' + statusAt,
    '조회: ' + checkedAt,
  ];
  return lines.join('\n');
}

function formatDttm_(raw) {
  if (!raw || raw.length < 8) return raw || '-';
  var d = raw.substring(0, 4) + '-' + raw.substring(4, 6) + '-' + raw.substring(6, 8);
  if (raw.length >= 12) d += ' ' + raw.substring(8, 10) + '시' + raw.substring(10, 12) + '분';
  return d;
}

// =====================================================================
// 텔레그램 전송
// =====================================================================
function sendTelegram_(chatId, text) {
  var url = 'https://api.telegram.org/bot' + CONFIG.TELEGRAM_BOT_TOKEN + '/sendMessage';
  var payload = JSON.stringify({ chat_id: chatId, text: text, parse_mode: 'HTML' });
  UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    payload: payload,
    muteHttpExceptions: true,
  });
}

// =====================================================================
// 카카오 나에게 보내기
// =====================================================================

// Step 1: 아래 URL을 브라우저에서 열어 로그인 후 code 파라미터 복사
function getKakaoAuthUrl() {
  var url = 'https://kauth.kakao.com/oauth/authorize'
    + '?client_id=' + CONFIG.KAKAO_REST_API_KEY
    + '&redirect_uri=https://example.com'
    + '&response_type=code'
    + '&scope=talk_message';
  Logger.log('아래 URL을 브라우저에서 열고, 로그인 후 리다이렉트된 URL의 ?code= 값을 복사하세요:');
  Logger.log(url);
  return url;
}

// Step 2: getKakaoAuthUrl에서 받은 code를 넣고 실행 -> access_token, refresh_token 확인
function getKakaoToken(code) {
  // code가 없으면 테스트용 하드코드
  if (!code) { Logger.log('code 파라미터가 필요합니다.'); return; }
  var resp = UrlFetchApp.fetch('https://kauth.kakao.com/oauth/token', {
    method: 'post',
    payload: {
      grant_type: 'authorization_code',
      client_id: CONFIG.KAKAO_REST_API_KEY,
      redirect_uri: 'https://example.com',
      code: code,
    },
    muteHttpExceptions: true,
  });
  var result = JSON.parse(resp.getContentText());
  Logger.log(JSON.stringify(result));
  if (result.access_token) {
    PropertiesService.getScriptProperties().setProperty('KAKAO_ACCESS_TOKEN', result.access_token);
    if (result.refresh_token) {
      PropertiesService.getScriptProperties().setProperty('KAKAO_REFRESH_TOKEN', result.refresh_token);
    }
    Logger.log('✅ 카카오 토큰 저장 완료!');
  }
  return result;
}

// Step 3: chatId에 카카오 토큰 연결 (웹앱 또는 아래 함수로 직접 연결)
function linkKakaoToUser(chatId) {
  chatId = String(chatId || '8624472047');
  var token = PropertiesService.getScriptProperties().getProperty('KAKAO_ACCESS_TOKEN');
  if (!token) { Logger.log('먼저 getKakaoToken(code)를 실행하세요.'); return; }
  var data = getUserData_(chatId);
  data.kakaoToken = token;
  saveUserData_(chatId, data);
  Logger.log('✅ chatId ' + chatId + ' 에 카카오 토큰 연결 완료!');
}

// 카카오 나에게 보내기 (텍스트)
function sendKakao_(accessToken, text) {
  var templateObject = {
    object_type: 'text',
    text: text,
    link: { web_url: 'https://unipass.customs.go.kr', mobile_web_url: 'https://unipass.customs.go.kr' },
  };
  var resp = UrlFetchApp.fetch('https://kapi.kakao.com/v2/api/talk/memo/default/send', {
    method: 'post',
    headers: { Authorization: 'Bearer ' + accessToken },
    payload: { template_object: JSON.stringify(templateObject) },
    muteHttpExceptions: true,
  });
  Logger.log('카카오 전송: ' + resp.getContentText());
}

// 카카오 토큰 갱신 (refresh_token 사용)
function refreshKakaoToken_() {
  var props = PropertiesService.getScriptProperties();
  var refreshToken = props.getProperty('KAKAO_REFRESH_TOKEN');
  if (!refreshToken) return null;
  var resp = UrlFetchApp.fetch('https://kauth.kakao.com/oauth/token', {
    method: 'post',
    payload: {
      grant_type: 'refresh_token',
      client_id: CONFIG.KAKAO_REST_API_KEY,
      refresh_token: refreshToken,
    },
    muteHttpExceptions: true,
  });
  var result = JSON.parse(resp.getContentText());
  if (result.access_token) {
    props.setProperty('KAKAO_ACCESS_TOKEN', result.access_token);
    if (result.refresh_token) props.setProperty('KAKAO_REFRESH_TOKEN', result.refresh_token);
    return result.access_token;
  }
  return null;
}

// =====================================================================
// 웹앱 - 카카오 연동용 함수
// =====================================================================
function getKakaoOAuthUrl() {
  return 'https://kauth.kakao.com/oauth/authorize'
    + '?client_id=' + CONFIG.KAKAO_REST_API_KEY
    + '&redirect_uri=https://example.com'
    + '&response_type=code'
    + '&scope=talk_message';
}

function linkKakaoWithCode(chatId, code) {
  chatId = String(chatId);
  var result = getKakaoToken(code);
  if (result && result.access_token) {
    var data = getUserData_(chatId);
    data.kakaoToken = result.access_token;
    saveUserData_(chatId, data);
    return { success: true, message: '✅ 카카오 연동 완료!' };
  }
  return { success: false, message: '❌ 카카오 연동 실패: ' + JSON.stringify(result) };
}
