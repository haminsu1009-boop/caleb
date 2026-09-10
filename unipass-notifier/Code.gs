// =====================================================================
// 유니패스 통관 상태 알림 - 멀티유저 웹앱 + 텔레그램 봇 + 카카오
// =====================================================================

var CONFIG = {
  UNIPASS_API_KEY: 'n250i296j006s253p060c040h5',
  TELEGRAM_BOT_TOKEN: '8901206831:AAF2cPkHwSVjaqFyNqvO-ke5B-ubXFLYveg',
  KAKAO_REST_API_KEY: '3785705a2781022b8a44c6475b0176a1',
  BL_YEAR: '2026',
  DEFAULT_INTERVAL: 5, // 기본 체크 주기 (분)
};

var UNIPASS_URL = 'https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo';

// =====================================================================
// 웹앱 진입점
// =====================================================================
function doGet(e) {
  // 카카오 OAuth 리다이렉트 처리
  if (e && e.parameter && e.parameter.code) {
    var code = e.parameter.code;
    var html = '<script>if(window.opener){window.opener.postMessage({kakaoCode:"' + code + '"},"*");}window.close();</script><p>로그인 완료! 창을 닫아주세요.</p>';
    return HtmlService.createHtmlOutput(html);
  }
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle('유니패스 통관 알림')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

// =====================================================================
// 텔레그램 봇 Webhook
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
      sendTelegram_(chatId, '👋 유니패스 통관 알림 봇입니다.\n\n'
        + '/add BL번호 - BL 추가 (추가 즉시 추적 시작)\n'
        + '/remove BL번호 - BL 삭제\n'
        + '/list - BL 목록\n'
        + '/status - 현재 상태 조회\n'
        + '/interval BL번호 분 - 알림 주기 변경 (예: /interval ABC123 10)\n'
        + '/clear - BL 전체 삭제');
    } else if (text.startsWith('/add ')) {
      var blNo = text.replace('/add ', '').trim().toUpperCase();
      var r = addBL(chatId, blNo, CONFIG.DEFAULT_INTERVAL);
      sendTelegram_(chatId, r.message);
    } else if (text.startsWith('/remove ')) {
      var blNo = text.replace('/remove ', '').trim().toUpperCase();
      var r = removeBL(chatId, blNo);
      sendTelegram_(chatId, r.message);
    } else if (text === '/clear') {
      var r = clearAllBL(chatId);
      sendTelegram_(chatId, r.message);
    } else if (text === '/list') {
      var userData = getUserData_(chatId);
      var bls = userData.bls || [];
      if (bls.length === 0) {
        sendTelegram_(chatId, '등록된 BL이 없습니다.');
      } else {
        var lines = bls.map(function(b, i) {
          return (i+1) + '. ' + b.blNo + ' (' + b.interval + '분마다)';
        });
        sendTelegram_(chatId, '📋 BL 목록:\n' + lines.join('\n'));
      }
    } else if (text === '/status') {
      checkAndNotifyUser_(chatId, true);
    } else if (text.startsWith('/interval ')) {
      var parts = text.split(' ');
      if (parts.length >= 3) {
        var blNo = parts[1].toUpperCase();
        var min = parseInt(parts[2], 10);
        var r = setBlInterval(chatId, blNo, min);
        sendTelegram_(chatId, r.message);
      }
    }
  } catch(err) { Logger.log('doPost error: ' + err); }
  return ContentService.createTextOutput('ok');
}

function setWebhook() {
  var url = 'https://api.telegram.org/bot' + CONFIG.TELEGRAM_BOT_TOKEN
    + '/setWebhook?url=' + encodeURIComponent(ScriptApp.getService().getUrl());
  Logger.log(UrlFetchApp.fetch(url, { muteHttpExceptions: true }).getContentText());
}

// =====================================================================
// 사용자 데이터 관리
// bls 구조: [{ blNo: 'ABC', interval: 5 }, ...]
// =====================================================================
function getUserData_(chatId) {
  var raw = PropertiesService.getScriptProperties().getProperty('USER_' + chatId);
  return raw ? JSON.parse(raw) : { bls: [], kakaoToken: null };
}

function saveUserData_(chatId, data) {
  PropertiesService.getScriptProperties().setProperty('USER_' + chatId, JSON.stringify(data));
}

function getAllUsers_() {
  var raw = PropertiesService.getScriptProperties().getProperty('ALL_USERS');
  return raw ? JSON.parse(raw) : [];
}

function saveAllUsers_(users) {
  PropertiesService.getScriptProperties().setProperty('ALL_USERS', JSON.stringify(users));
}

function registerUser_(chatId) {
  var users = getAllUsers_();
  if (users.indexOf(chatId) === -1) { users.push(chatId); saveAllUsers_(users); }
  var data = getUserData_(chatId);
  if (!data.bls) data.bls = [];
  saveUserData_(chatId, data);
}

// =====================================================================
// 웹앱 호출 함수
// =====================================================================
function getUserInfo(chatId) {
  chatId = String(chatId);
  registerUser_(chatId);
  var data = getUserData_(chatId);
  return {
    chatId: chatId,
    bls: data.bls || [],
    kakaoLinked: !!(data.kakaoToken),
    telegramChatId: data.telegramChatId || null,
  };
}

// BL 추가 (interval 기본값: DEFAULT_INTERVAL)
function addBL(chatId, blNo, interval) {
  chatId = String(chatId);
  blNo = blNo.trim().toUpperCase();
  interval = interval || CONFIG.DEFAULT_INTERVAL;
  if (!blNo) return { success: false, message: 'BL번호를 입력하세요.' };
  registerUser_(chatId);
  var data = getUserData_(chatId);
  if (!data.bls) data.bls = [];

  var exists = data.bls.some(function(b) { return b.blNo === blNo; });
  if (exists) return { success: false, message: blNo + ' 은 이미 등록되어 있습니다.', bls: data.bls };

  data.bls.push({ blNo: blNo, interval: interval });
  saveUserData_(chatId, data);

  // 현재 상태 저장 (기준점)
  // 추가 즉시 현재 상태 조회 & 알림
  try {
    var records = fetchCargoProgress_(blNo, CONFIG.BL_YEAR);
    if (records.length > 0) {
      var latest = pickLatest_(records);
      var sl = summaryLine_(latest);
      PropertiesService.getScriptProperties().setProperty('STATE_' + chatId + '_' + blNo, JSON.stringify({ summaryLine: sl }));
      // 현재 상태 즉시 알림
      var msg = formatMessage_(blNo, true, null, latest);
      sendTelegram_(chatId, msg);
      var userData2 = getUserData_(chatId);
      if (userData2.kakaoToken) { try { sendKakao_(userData2.kakaoToken, msg.replace(/<[^>]+>/g, '')); } catch(e) {} }
    }
  } catch(e) {}

  // 트리거 항상 켜기 (1분마다 실행, BL별 interval은 내부에서 체크)
  ensureTrigger_();

  return { success: true, message: '✅ ' + blNo + ' 추가! ' + interval + '분마다 자동 추적 시작', bls: data.bls };
}

// BL 삭제
function removeBL(chatId, blNo) {
  chatId = String(chatId);
  blNo = blNo.trim().toUpperCase();
  var data = getUserData_(chatId);
  var before = (data.bls || []).length;
  data.bls = (data.bls || []).filter(function(b) { return b.blNo !== blNo; });
  if (data.bls.length === before) return { success: false, message: blNo + ' 을 찾을 수 없습니다.', bls: data.bls };
  saveUserData_(chatId, data);
  PropertiesService.getScriptProperties().deleteProperty('STATE_' + chatId + '_' + blNo);
  PropertiesService.getScriptProperties().deleteProperty('LASTCHECK_' + chatId + '_' + blNo);
  return { success: true, message: '🗑 ' + blNo + ' 삭제 완료!', bls: data.bls };
}

// BL 여러 개 삭제
function removeBLs(chatId, blNos) {
  chatId = String(chatId);
  var results = [];
  blNos.forEach(function(blNo) {
    var r = removeBL(chatId, blNo);
    results.push(r.message);
  });
  return { success: true, message: results.join('\n'), bls: getUserData_(chatId).bls };
}

// BL 전체 삭제
function clearAllBL(chatId) {
  chatId = String(chatId);
  var data = getUserData_(chatId);
  var props = PropertiesService.getScriptProperties();
  (data.bls || []).forEach(function(b) {
    props.deleteProperty('STATE_' + chatId + '_' + b.blNo);
    props.deleteProperty('LASTCHECK_' + chatId + '_' + b.blNo);
  });
  data.bls = [];
  saveUserData_(chatId, data);
  return { success: true, message: '🗑 BL 전체 삭제 완료!', bls: [] };
}

// BL별 알림 주기 변경
function setBlInterval(chatId, blNo, interval) {
  chatId = String(chatId);
  blNo = blNo.trim().toUpperCase();
  if ([1, 5, 10, 30].indexOf(interval) === -1) {
    return { success: false, message: '1, 5, 10, 30 중 하나를 입력하세요.' };
  }
  var data = getUserData_(chatId);
  var found = false;
  (data.bls || []).forEach(function(b) {
    if (b.blNo === blNo) { b.interval = interval; found = true; }
  });
  if (!found) return { success: false, message: blNo + ' 을 찾을 수 없습니다.' };
  saveUserData_(chatId, data);
  return { success: true, message: '✅ ' + blNo + ' 알림 주기를 ' + interval + '분으로 변경했습니다.', bls: data.bls };
}

// =====================================================================
// 트리거 관리 (항상 1분마다 실행, BL별 interval은 내부 로직으로 처리)
// =====================================================================
function ensureTrigger_() {
  var triggers = ScriptApp.getProjectTriggers();
  var hasRun = triggers.some(function(t) { return t.getHandlerFunction() === 'run'; });
  if (!hasRun) {
    ScriptApp.newTrigger('run').timeBased().everyMinutes(1).create();
  }
}

function stopTrigger() {
  ScriptApp.getProjectTriggers().forEach(function(t) { ScriptApp.deleteTrigger(t); });
}

function deleteAllTriggers() {
  ScriptApp.getProjectTriggers().forEach(function(t) { ScriptApp.deleteTrigger(t); });
}

function getTriggerStatus() {
  var active = ScriptApp.getProjectTriggers().some(function(t) { return t.getHandlerFunction() === 'run'; });
  return { active: active };
}

// =====================================================================
// 자동 체크 실행 (1분마다 트리거로 호출)
// BL별 interval에 따라 마지막 체크 시간 비교 후 조회 여부 결정
// =====================================================================
function run() {
  var users = getAllUsers_();
  var props = PropertiesService.getScriptProperties();
  var now = new Date().getTime();

  users.forEach(function(chatId) {
    var data = getUserData_(chatId);
    (data.bls || []).forEach(function(blObj) {
      var blNo = blObj.blNo;
      var interval = blObj.interval || CONFIG.DEFAULT_INTERVAL;
      var lastCheckKey = 'LASTCHECK_' + chatId + '_' + blNo;
      var lastCheck = parseInt(props.getProperty(lastCheckKey) || '0', 10);
      var minutesPassed = (now - lastCheck) / 60000;

      if (minutesPassed >= interval) {
        props.setProperty(lastCheckKey, String(now));
        checkBL_(chatId, blNo, data.kakaoToken);
      }
    });
  });
}

function checkAndNotifyUser_(chatId, forceNotify) {
  var data = getUserData_(chatId);
  (data.bls || []).forEach(function(blObj) {
    checkBL_(chatId, blObj.blNo, data.kakaoToken, forceNotify);
  });
}

function checkBL_(chatId, blNo, kakaoToken, forceNotify) {
  var stateKey = 'STATE_' + chatId + '_' + blNo;
  var props = PropertiesService.getScriptProperties();
  var records;
  try { records = fetchCargoProgress_(blNo, CONFIG.BL_YEAR); } catch(e) { return; }
  if (!records || records.length === 0) return;

  var latest = pickLatest_(records);
  var sl = summaryLine_(latest);
  var prevRaw = props.getProperty(stateKey);
  var prev = prevRaw ? JSON.parse(prevRaw) : null;
  var changed = !prev || prev.summaryLine !== sl;

  if (changed || forceNotify) {
    var msg = formatMessage_(blNo, !prev && !forceNotify, forceNotify ? null : (prev ? prev.summaryLine : null), latest);
    // 텔레그램: data.telegramChatId 또는 chatId 자체(구형 텔레그램 기반 사용자)
    var data = getUserData_(chatId);
    var telegramId = data.telegramChatId || (isNaN(String(chatId).replace('-','')) ? null : chatId);
    if (telegramId) { try { sendTelegram_(telegramId, msg); } catch(e) {} }
    // 카카오
    var token = kakaoToken || data.kakaoToken;
    if (token) { try { sendKakao_(token, msg.replace(/<[^>]+>/g, '')); } catch(e) {} }
  }
  props.setProperty(stateKey, JSON.stringify({ summaryLine: sl }));
}

// =====================================================================
// 유니패스 API
// =====================================================================
function fetchCargoProgress_(blNo, blYear) {
  var base = UNIPASS_URL + '?crkyCn=' + encodeURIComponent(CONFIG.UNIPASS_API_KEY);
  var yearParam = blYear ? '&blYy=' + encodeURIComponent(blYear) : '';
  var paramSets = [
    '&mblNo=' + encodeURIComponent(blNo) + yearParam,
    '&hblNo=' + encodeURIComponent(blNo) + yearParam,
  ];
  for (var i = 0; i < paramSets.length; i++) {
    for (var attempt = 0; attempt < 3; attempt++) {
      try {
        var resp = UrlFetchApp.fetch(base + paramSets[i], { muteHttpExceptions: true });
        var records = [];
        collectRecords_(XmlService.parse(resp.getContentText()).getRootElement(), records);
        if (records.length > 0) return records;
        break;
      } catch(e) { if (attempt < 2) Utilities.sleep(1000); }
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
  return pool.reduce(function(best, r) { return recordTime_(r) >= recordTime_(best) ? r : best; }, pool[0]);
}

function recordTime_(r) { return r.prcsDttm || r.cargTrcnPrcsDttm || r.prcsDt || ''; }

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
  return ['<b>' + header + '</b>', '', '🚢 BL번호: <code>' + blNo + '</code>', '',
    '📌 현재 상태: <b>' + status + '</b>', '🕐 상태 발생: ' + statusAt, '조회: ' + checkedAt].join('\n');
}

function formatDttm_(raw) {
  if (!raw || raw.length < 8) return raw || '-';
  var d = raw.substring(0,4)+'-'+raw.substring(4,6)+'-'+raw.substring(6,8);
  if (raw.length >= 12) d += ' '+raw.substring(8,10)+'시'+raw.substring(10,12)+'분';
  return d;
}

function sendTelegram_(chatId, text) {
  UrlFetchApp.fetch('https://api.telegram.org/bot' + CONFIG.TELEGRAM_BOT_TOKEN + '/sendMessage', {
    method: 'post', contentType: 'application/json',
    payload: JSON.stringify({ chat_id: chatId, text: text, parse_mode: 'HTML' }),
    muteHttpExceptions: true,
  });
}

// =====================================================================
// 카카오 나에게 보내기
// =====================================================================
function getKakaoOAuthUrl() {
  return 'https://kauth.kakao.com/oauth/authorize'
    + '?client_id=' + CONFIG.KAKAO_REST_API_KEY
    + '&redirect_uri=https://script.google.com/macros/s/AKfycbx2UjYtt4r0qpJ4o4uXlUKKBnelEVh5CRCv3Pn3va7e6kJOyqj9GNpwMj02UIaUaBTe/exec'
    + '&response_type=code&scope=talk_message';
}

// 처음 카카오로 로그인 (설정 화면) - 카카오 ID를 userId로 사용
function loginWithKakao(code) {
  return linkKakaoToUser('', code);
}

// 기존 userId에 카카오 연결 (또는 신규 카카오 로그인)
function linkKakaoToUser(existingUserId, code) {
  var resp = UrlFetchApp.fetch('https://kauth.kakao.com/oauth/token', {
    method: 'post',
    payload: {
      grant_type: 'authorization_code',
      client_id: CONFIG.KAKAO_REST_API_KEY,
      redirect_uri: 'https://script.google.com/macros/s/AKfycbx2UjYtt4r0qpJ4o4uXlUKKBnelEVh5CRCv3Pn3va7e6kJOyqj9GNpwMj02UIaUaBTe/exec',
      code: code
    },
    muteHttpExceptions: true
  });
  var token = JSON.parse(resp.getContentText());
  if (!token.access_token) return { success: false, message: '카카오 로그인 실패: ' + (token.error_description || '') };

  var meResp = UrlFetchApp.fetch('https://kapi.kakao.com/v2/user/me', {
    headers: { Authorization: 'Bearer ' + token.access_token },
    muteHttpExceptions: true
  });
  var me = JSON.parse(meResp.getContentText());
  if (!me.id) return { success: false, message: '사용자 정보 가져오기 실패' };

  var nickname = (me.kakao_account && me.kakao_account.profile && me.kakao_account.profile.nickname) || '';
  // userId 결정: 기존 유저면 기존 ID 유지, 신규면 K{kakaoId}
  var userId = existingUserId ? String(existingUserId) : ('K' + me.id);
  var data = getUserData_(userId);
  data.kakaoToken = token.access_token;
  if (token.refresh_token) data.kakaoRefreshToken = token.refresh_token;
  data.kakaoNickname = nickname;
  saveUserData_(userId, data);
  ensureTrigger_();
  return { success: true, userId: userId, nickname: nickname };
}

// 텔레그램 Chat ID 연결/해제
function setTelegramChatId(userId, telegramChatId) {
  userId = String(userId);
  var data = getUserData_(userId);
  data.telegramChatId = telegramChatId ? String(telegramChatId) : null;
  saveUserData_(userId, data);
  return { success: true };
}

function linkKakaoWithCode(chatId, code) {
  chatId = String(chatId);
  var resp = UrlFetchApp.fetch('https://kauth.kakao.com/oauth/token', {
    method: 'post',
    payload: { grant_type: 'authorization_code', client_id: CONFIG.KAKAO_REST_API_KEY,
      redirect_uri: 'https://example.com', code: code },
    muteHttpExceptions: true,
  });
  var result = JSON.parse(resp.getContentText());
  if (result.access_token) {
    var data = getUserData_(chatId);
    data.kakaoToken = result.access_token;
    if (result.refresh_token) data.kakaoRefreshToken = result.refresh_token;
    saveUserData_(chatId, data);
    return { success: true, message: '✅ 카카오 연동 완료!' };
  }
  return { success: false, message: '❌ 카카오 연동 실패: ' + (result.error_description || result.error || '') };
}

function unlinkKakao(chatId) {
  chatId = String(chatId);
  var data = getUserData_(chatId);
  data.kakaoToken = null;
  data.kakaoRefreshToken = null;
  saveUserData_(chatId, data);
  return { success: true };
}

function sendKakao_(accessToken, text) {
  UrlFetchApp.fetch('https://kapi.kakao.com/v2/api/talk/memo/default/send', {
    method: 'post',
    headers: { Authorization: 'Bearer ' + accessToken },
    payload: { template_object: JSON.stringify({
      object_type: 'text', text: text,
      link: { web_url: 'https://unipass.customs.go.kr', mobile_web_url: 'https://unipass.customs.go.kr' }
    })},
    muteHttpExceptions: true,
  });
}
