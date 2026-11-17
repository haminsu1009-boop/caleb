// =====================================================================
// 유니패스 통관 상태 알림 - 멀티유저 웹앱 + 텔레그램 봇 + 카카오
// =====================================================================

var CONFIG = {
  UNIPASS_API_KEY: 'n250i296j006s253p060c040h5',
  TELEGRAM_BOT_TOKEN: '8901206831:AAF2cPkHwSVjaqFyNqvO-ke5B-ubXFLYveg',
  KAKAO_REST_API_KEY: '3785705a2781022b8a44c6475b0176a1',
  BL_YEAR: '2026',
  DEFAULT_INTERVAL: 5,
};

var UNIPASS_URL = 'https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo';
var UNIPASS_WRHS_URL = 'https://unipass.customs.go.kr:38010/ext/rest/bntbWrhsQry/retrieveBntbWrhsInfo';

// shedSgn → 전화/주소 (새 창고 나오면 여기 추가)
var WAREHOUSE_MAP = {
  '02010755': { phone: '032-888-5011', addr: '인천광역시 제물포구 축항대로290번길 13' },   // 태평양물류(주) 보세창고
  '02012007': { phone: '', addr: '' },                                                      // ㈜E1컨테이너터미널보세창고
  '02012016': { phone: '032-202-4900', addr: '인천광역시 연수구 인천신항대로 777' },        // 한진인천컨테이너터미널(주)
};

// =====================================================================
// 초대 코드 시스템
// =====================================================================
function getInviteCodes_() {
  var raw = PropertiesService.getScriptProperties().getProperty('INVITE_CODES');
  return raw ? JSON.parse(raw) : {};
}
function saveInviteCodes_(codes) {
  PropertiesService.getScriptProperties().setProperty('INVITE_CODES', JSON.stringify(codes));
}
function issueInviteCode(code, label) {
  if (!code) return;
  var codes = getInviteCodes_();
  codes[String(code).toUpperCase()] = { label: label || '', used: false, usedBy: null };
  saveInviteCodes_(codes);
  Logger.log('발급 완료: ' + code + ' (' + (label || '') + ')');
}
function verifyAndUseInviteCode(code, userId) {
  if (!code) return { success: false, message: '초대 코드를 입력하세요.' };
  var codes = getInviteCodes_();
  var entry = codes[String(code).trim().toUpperCase()];
  if (!entry) return { success: false, message: '존재하지 않는 초대 코드입니다.' };
  if (entry.used) return { success: false, message: '이미 사용된 초대 코드입니다.' };
  entry.used = true;
  entry.usedBy = userId || 'unknown';
  codes[String(code).trim().toUpperCase()] = entry;
  saveInviteCodes_(codes);
  return { success: true };
}
function listInviteCodes() {
  var codes = getInviteCodes_();
  var result = [];
  for (var k in codes) {
    result.push({ code: k, label: codes[k].label, used: codes[k].used, usedBy: codes[k].usedBy });
  }
  Logger.log(JSON.stringify(result, null, 2));
  return result;
}
function 코드발급() {
  issueInviteCode('HAMIN2026', '하민수');
  issueInviteCode('EUNJAE2026', '김은재');
  issueInviteCode('BOSEOK2026', '손보석');
  issueInviteCode('CHUL2026', '장철훈');
  Logger.log('초대 코드 발급 완료');
}

// =====================================================================
// 디버그 함수 (Apps Script 에디터에서 직접 실행)
// =====================================================================
function 창고정보테스트() {
  var shedSgn = '02010755';
  var url = UNIPASS_WRHS_URL + '?crkyCn=' + encodeURIComponent(CONFIG.UNIPASS_API_KEY)
    + '&bntbWrhsSgn=' + encodeURIComponent(shedSgn);
  try {
    var resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
    Logger.log('HTTP: ' + resp.getResponseCode());
    Logger.log(resp.getContentText());
  } catch(e) { Logger.log('오류: ' + e); }
}

function 필드확인() {
  // BL번호를 실제 번호로 바꿔서 실행하세요
  var blNo = 'HTPE26002154';
  var records = fetchCargoProgress_(blNo, CONFIG.BL_YEAR);
  if (records.length === 0) { Logger.log('조회 결과 없음'); return; }
  Logger.log('=== 전체 레코드 수: ' + records.length + ' ===');
  records.forEach(function(r, i) {
    Logger.log('--- 레코드 ' + (i+1) + ' ---');
    for (var k in r) {
      if (r[k]) Logger.log('  ' + k + ': ' + r[k]);
    }
  });
}

// =====================================================================
// 관리자 함수 (Apps Script 에디터에서 직접 실행)
// =====================================================================

// 기존 등록 BL에 장치장 캐시 채우기 (한 번만 실행)
function 장치장마이그레이션() {
  var users = getAllUsers_();
  var props = PropertiesService.getScriptProperties();
  users.forEach(function(chatId) {
    var data = getUserData_(chatId);
    (data.bls || []).forEach(function(bl) {
      var shedKey = 'SHED_' + chatId + '_' + bl.blNo;
      if (props.getProperty(shedKey)) { Logger.log(bl.blNo + ': 이미 있음'); return; }
      try {
        var records = fetchCargoProgress_(bl.blNo, CONFIG.BL_YEAR);
        var terminal = getTerminalName_(records);
        if (terminal) {
          props.setProperty(shedKey, terminal);
          Logger.log(bl.blNo + ': ' + terminal + ' → 저장완료');
        } else {
          Logger.log(bl.blNo + ': 장치장 없음');
        }
      } catch(e) { Logger.log(bl.blNo + ': 오류 ' + e); }
    });
  });
  Logger.log('마이그레이션 완료');
}

function 유저목록() {
  var users = getAllUsers_();
  var result = [];
  users.forEach(function(userId) {
    var data = getUserData_(userId);
    result.push({
      userId: userId,
      카카오닉네임: data.kakaoNickname || '-',
      텔레그램ID: data.telegramChatId || '-',
      BL개수: (data.bls || []).length,
      차단여부: data.banned || false
    });
  });
  Logger.log(JSON.stringify(result, null, 2));
  return result;
}

function 유저차단(userId) {
  var data = getUserData_(userId);
  data.banned = true;
  saveUserData_(userId, data);
  Logger.log('차단 완료: ' + userId + ' (' + (data.kakaoNickname || data.telegramChatId || '-') + ')');
}

function 유저차단해제(userId) {
  var data = getUserData_(userId);
  data.banned = false;
  saveUserData_(userId, data);
  Logger.log('차단 해제: ' + userId);
}

// =====================================================================
// 웹앱 진입점
// =====================================================================
function doGet(e) {
  if (e && e.parameter && e.parameter.code) {
    var code = e.parameter.code;
    // 팝업창에 아무것도 안 보이게, 바로 localStorage 저장 후 닫기
    var html = '<!DOCTYPE html><html><head><style>body{margin:0;background:#000;}</style></head><body>'
      + '<script>try{localStorage.setItem("kakaoCode","' + code + '");}catch(ex){}'
      + 'window.close();</script></body></html>';
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
        + '/add BL번호 - BL 추가\n'
        + '/remove BL번호 - BL 삭제\n'
        + '/list - BL 목록\n'
        + '/status - 현재 상태 조회\n'
        + '/interval BL번호 분 - 알림 주기 변경\n'
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
function checkBLNow(chatId, blNo) {
  chatId = String(chatId);
  blNo = blNo.trim().toUpperCase();
  try {
    var records = fetchCargoProgress_(blNo, CONFIG.BL_YEAR);
    if (!records || records.length === 0) return { success: false, message: '조회 결과가 없습니다.' };
    var props = PropertiesService.getScriptProperties();

    var shedKey    = 'SHED_'     + chatId + '_' + blNo;
    var shedTelKey = 'SHEDTEL_'  + chatId + '_' + blNo;
    var shedAddrKey= 'SHEDADDR_' + chatId + '_' + blNo;
    var shedSgnKey = 'SHEDSGN_'  + chatId + '_' + blNo;

    var terminal     = getTerminalName_(records) || props.getProperty(shedKey)     || null;
    var terminalPhone= getTerminalPhone_(records) || props.getProperty(shedTelKey) || null;
    var terminalAddr = getTerminalAddr_(records)  || props.getProperty(shedAddrKey)|| null;

    // shedSgn이 있고 아직 전화/주소 없으면 보세창고 API로 보완
    var shedSgn = getShedSgn_(records) || props.getProperty(shedSgnKey) || null;
    if (shedSgn && (!terminalPhone || !terminalAddr)) {
      var wrhsInfo = fetchWarehouseInfo_(shedSgn);
      if (wrhsInfo) {
        if (!terminalPhone && wrhsInfo.phone) terminalPhone = wrhsInfo.phone;
        if (!terminalAddr  && wrhsInfo.addr)  terminalAddr  = wrhsInfo.addr;
      }
    }

    if (terminal)      props.setProperty(shedKey,     terminal);
    if (terminalPhone) props.setProperty(shedTelKey,  terminalPhone);
    if (terminalAddr)  props.setProperty(shedAddrKey, terminalAddr);
    if (shedSgn)       props.setProperty(shedSgnKey,  shedSgn);

    var rows = records.map(function(r) {
      return {
        status: r.cargTrcnRelaBsopTpcd || r.csclPrgsStts || r.prgsStts || r.cargTrcnRsltNm || '-',
        date: formatDttm_(r.prcsDttm || r.cargTrcnPrcsDttm || r.prcsDt),
        location: r.shedNm || r.lodgOrgNm || r.trmnNm || r.lodgPlcNm || '',
        remark: r.bfhnCargWght || r.cargWght || ''
      };
    });
    rows.reverse();
    return { success: true, blNo: blNo, terminal: terminal, terminalPhone: terminalPhone, terminalAddr: terminalAddr, rows: rows };
  } catch(e) {
    return { success: false, message: '오류: ' + e.message };
  }
}

function getUserInfo(chatId) {
  chatId = String(chatId);
  registerUser_(chatId);
  var data = getUserData_(chatId);

  // 차단된 유저
  if (data.banned) return { banned: true };

  return {
    chatId: chatId,
    bls: data.bls || [],
    kakaoLinked: !!(data.kakaoToken),
    telegramChatId: data.telegramChatId || null,
  };
}

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

  try {
    var records = fetchCargoProgress_(blNo, CONFIG.BL_YEAR);
    if (records.length > 0) {
      var latest = pickLatest_(records);
      var sl = summaryLine_(latest);
      var terminal = getTerminalName_(records);
      var terminalPhone = getTerminalPhone_(records);
      var msg = formatMessage_(blNo, true, null, latest, terminal, terminalPhone);
      var addProps = PropertiesService.getScriptProperties();
      addProps.setProperty('STATE_' + chatId + '_' + blNo, JSON.stringify({ summaryLine: sl, terminalName: terminal || null, terminalPhone: terminalPhone || null }));
      if (terminal) addProps.setProperty('SHED_' + chatId + '_' + blNo, terminal);
      if (terminalPhone) addProps.setProperty('SHEDTEL_' + chatId + '_' + blNo, terminalPhone);
      var userData2 = getUserData_(chatId);
      var telegramId = userData2.telegramChatId || (isNaN(String(chatId).replace('-','')) ? null : chatId);
      if (telegramId) { try { sendTelegram_(telegramId, msg); } catch(e) {} }
      if (userData2.kakaoToken) { try { sendKakao_(chatId, msg.replace(/<[^>]+>/g, '')); } catch(e) {} }
    }
  } catch(e) {}

  ensureTrigger_();
  return { success: true, message: '✅ ' + blNo + ' 추가! ' + interval + '분마다 자동 추적 시작', bls: data.bls };
}

function removeBL(chatId, blNo) {
  chatId = String(chatId);
  blNo = blNo.trim().toUpperCase();
  var data = getUserData_(chatId);
  var before = (data.bls || []).length;
  data.bls = (data.bls || []).filter(function(b) { return b.blNo !== blNo; });
  if (data.bls.length === before) return { success: false, message: blNo + ' 을 찾을 수 없습니다.', bls: data.bls };
  saveUserData_(chatId, data);
  var rmProps = PropertiesService.getScriptProperties();
  rmProps.deleteProperty('STATE_' + chatId + '_' + blNo);
  rmProps.deleteProperty('LASTCHECK_' + chatId + '_' + blNo);
  rmProps.deleteProperty('SHED_' + chatId + '_' + blNo);
  rmProps.deleteProperty('SHEDTEL_' + chatId + '_' + blNo);
  return { success: true, message: '🗑 ' + blNo + ' 삭제 완료!', bls: data.bls };
}

function removeBLs(chatId, blNos) {
  chatId = String(chatId);
  var results = [];
  blNos.forEach(function(blNo) {
    var r = removeBL(chatId, blNo);
    results.push(r.message);
  });
  return { success: true, message: results.join('\n'), bls: getUserData_(chatId).bls };
}

function clearAllBL(chatId) {
  chatId = String(chatId);
  var data = getUserData_(chatId);
  var props = PropertiesService.getScriptProperties();
  (data.bls || []).forEach(function(b) {
    props.deleteProperty('STATE_' + chatId + '_' + b.blNo);
    props.deleteProperty('LASTCHECK_' + chatId + '_' + b.blNo);
    props.deleteProperty('SHED_' + chatId + '_' + b.blNo);
    props.deleteProperty('SHEDTEL_' + chatId + '_' + b.blNo);
  });
  data.bls = [];
  saveUserData_(chatId, data);
  return { success: true, message: '🗑 BL 전체 삭제 완료!', bls: [] };
}

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
// 트리거 관리
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
// 자동 체크 (1분마다 트리거)
// =====================================================================
function run() {
  var users = getAllUsers_();
  var props = PropertiesService.getScriptProperties();
  var now = new Date().getTime();

  users.forEach(function(chatId) {
    var data = getUserData_(chatId);
    if (data.banned) return; // 차단된 유저 스킵
    (data.bls || []).forEach(function(blObj) {
      var blNo = blObj.blNo;
      var interval = blObj.interval || CONFIG.DEFAULT_INTERVAL;
      var lastCheckKey = 'LASTCHECK_' + chatId + '_' + blNo;
      var lastCheck = parseInt(props.getProperty(lastCheckKey) || '0', 10);
      var minutesPassed = (now - lastCheck) / 60000;
      if (minutesPassed >= interval) {
        props.setProperty(lastCheckKey, String(now));
        checkBL_(chatId, blNo);
      }
    });
  });
}

function checkAndNotifyUser_(chatId, forceNotify) {
  var data = getUserData_(chatId);
  (data.bls || []).forEach(function(blObj) {
    checkBL_(chatId, blObj.blNo, forceNotify);
  });
}

function checkBL_(chatId, blNo, forceNotify) {
  // race condition 방지: 삭제된 BL이면 스킵
  var currentData = getUserData_(chatId);
  var blExists = (currentData.bls || []).some(function(b) { return b.blNo === blNo; });
  if (!blExists && !forceNotify) return;

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

  // 장치장명: 현재 레코드 → STATE 캐시 → 별도 SHED 키 순으로 조회
  var shedKey = 'SHED_' + chatId + '_' + blNo;
  var shedTelKey = 'SHEDTEL_' + chatId + '_' + blNo;
  var terminalNow = getTerminalName_(records);
  var cachedTerminal = (prev && prev.terminalName) || props.getProperty(shedKey) || null;
  var terminal = terminalNow || cachedTerminal;
  if (terminal) props.setProperty(shedKey, terminal);

  var phoneNow = getTerminalPhone_(records);
  var cachedPhone = (prev && prev.terminalPhone) || props.getProperty(shedTelKey) || null;
  var terminalPhone = phoneNow || cachedPhone;
  if (terminalPhone) props.setProperty(shedTelKey, terminalPhone);

  if (changed || forceNotify) {
    var msg = formatMessage_(blNo, !prev && !forceNotify, forceNotify ? null : (prev ? prev.summaryLine : null), latest, terminal, terminalPhone);
    var data = getUserData_(chatId);
    var telegramId = data.telegramChatId || (isNaN(String(chatId).replace('-','')) ? null : chatId);
    if (telegramId) { try { sendTelegram_(telegramId, msg); } catch(e) {} }
    if (data.kakaoToken) { try { sendKakao_(chatId, msg.replace(/<[^>]+>/g, '')); } catch(e) {} }
  }
  props.setProperty(stateKey, JSON.stringify({ summaryLine: sl, terminalName: terminal || null, terminalPhone: terminalPhone || null }));
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

function getTerminalName_(records) {
  var candidates = ['shedNm', 'lodgOrgNm', 'trmnNm', 'cargMtTrmnNm', 'mtTrmnNm', 'lodgPlcNm', 'trmnOprBsnNm'];
  var pool = Array.isArray(records) ? records.slice().reverse() : [records];
  for (var i = 0; i < pool.length; i++) {
    for (var j = 0; j < candidates.length; j++) {
      if (pool[i][candidates[j]]) return pool[i][candidates[j]];
    }
  }
  return null;
}

function getTerminalPhone_(records) {
  var candidates = ['trmnTelNo', 'shedTelNo', 'lodgOrgTelNo', 'telNo', 'trmnOprBsnTelNo', 'cargMtTrmnTelNo'];
  var pool = Array.isArray(records) ? records.slice().reverse() : [records];
  for (var i = 0; i < pool.length; i++) {
    for (var j = 0; j < candidates.length; j++) {
      if (pool[i][candidates[j]]) return pool[i][candidates[j]];
    }
  }
  return null;
}

function getShedSgn_(records) {
  var pool = Array.isArray(records) ? records.slice().reverse() : [records];
  for (var i = 0; i < pool.length; i++) {
    var sgn = pool[i].shedSgn || '';
    // shedSgn은 "02010755" 또는 "02010755/1-2" 형태 — 슬래시 앞 8자리만 사용
    if (sgn) return sgn.split('/')[0].trim();
  }
  return null;
}

function fetchWarehouseInfo_(shedSgn) {
  var entry = WAREHOUSE_MAP[shedSgn];
  if (!entry) return null;
  var phone = entry.phone || null;
  var addr  = entry.addr  || null;
  return (phone || addr) ? { phone: phone, addr: addr } : null;
}

function collectFlat_(el, out) {
  var children = el.getChildren();
  if (children.length === 0) {
    var val = el.getText().trim();
    if (val) out[el.getName()] = val;
    return;
  }
  children.forEach(function(c) { collectFlat_(c, out); });
}

function getTerminalAddr_(records) {
  var candidates = ['shedAddr', 'trmnAddr', 'lodgOrgAddr', 'cargMtTrmnAddr', 'mtTrmnAddr', 'trmnOprBsnAddr'];
  var pool = Array.isArray(records) ? records.slice().reverse() : [records];
  for (var i = 0; i < pool.length; i++) {
    for (var j = 0; j < candidates.length; j++) {
      if (pool[i][candidates[j]]) return pool[i][candidates[j]];
    }
  }
  return null;
}

function formatMessage_(blNo, isFirst, prevLine, latest, terminal, terminalPhone) {
  var status = latest.cargTrcnRelaBsopTpcd || latest.csclPrgsStts || latest.prgsStts || latest.cargTrcnRsltNm || '-';
  var statusAt = formatDttm_(latest.prcsDttm || latest.cargTrcnPrcsDttm || latest.prcsDt);
  var checkedAt = Utilities.formatDate(new Date(), 'Asia/Seoul', 'MM월 dd일 HH시 mm분');
  var header = isFirst ? '📦 모니터링 시작' : (prevLine === null ? '📌 현재 상태' : '🔔 상태 변경!');
  var lines = ['<b>' + header + '</b>', '', '🚢 BL번호: <code>' + blNo + '</code>', '',
    '📌 현재 상태: <b>' + status + '</b>', '🕐 상태 발생: ' + statusAt];
  if (terminal) {
    var termLine = '🏭 장치장: ' + terminal;
    if (terminalPhone) termLine += ' (' + terminalPhone + ')';
    lines.push(termLine);
  }
  lines.push('조회: ' + checkedAt);
  return lines.join('\n');
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
// 카카오 나에게 보내기 (토큰 자동 갱신)
// =====================================================================
function refreshKakaoToken_(userId) {
  var data = getUserData_(userId);
  if (!data.kakaoRefreshToken) return null;
  var resp = UrlFetchApp.fetch('https://kauth.kakao.com/oauth/token', {
    method: 'post',
    payload: {
      grant_type: 'refresh_token',
      client_id: CONFIG.KAKAO_REST_API_KEY,
      refresh_token: data.kakaoRefreshToken
    },
    muteHttpExceptions: true
  });
  var newToken = JSON.parse(resp.getContentText());
  if (newToken.access_token) {
    data.kakaoToken = newToken.access_token;
    if (newToken.refresh_token) data.kakaoRefreshToken = newToken.refresh_token;
    saveUserData_(userId, data);
    return newToken.access_token;
  }
  return null;
}

function sendKakao_(userId, text) {
  var data = getUserData_(userId);
  if (!data.kakaoToken) return;

  var payload = { template_object: JSON.stringify({
    object_type: 'text', text: text,
    link: { web_url: 'https://unipass.customs.go.kr', mobile_web_url: 'https://unipass.customs.go.kr' }
  })};

  var resp = UrlFetchApp.fetch('https://kapi.kakao.com/v2/api/talk/memo/default/send', {
    method: 'post',
    headers: { Authorization: 'Bearer ' + data.kakaoToken },
    payload: payload,
    muteHttpExceptions: true,
  });

  var result = JSON.parse(resp.getContentText());

  // 토큰 만료(-401)면 refresh 후 재시도
  if (result.code === -401) {
    var newToken = refreshKakaoToken_(userId);
    if (newToken) {
      UrlFetchApp.fetch('https://kapi.kakao.com/v2/api/talk/memo/default/send', {
        method: 'post',
        headers: { Authorization: 'Bearer ' + newToken },
        payload: payload,
        muteHttpExceptions: true,
      });
    }
  }
}

// =====================================================================
// 카카오 OAuth
// =====================================================================
function getKakaoOAuthUrl() {
  var redirectUri = ScriptApp.getService().getUrl();
  return 'https://kauth.kakao.com/oauth/authorize'
    + '?client_id=' + CONFIG.KAKAO_REST_API_KEY
    + '&redirect_uri=' + encodeURIComponent(redirectUri)
    + '&response_type=code&scope=talk_message';
}

function loginWithKakao(code) {
  return linkKakaoToUser('', code);
}

function linkKakaoToUser(existingUserId, code) {
  var redirectUri = ScriptApp.getService().getUrl();
  var resp = UrlFetchApp.fetch('https://kauth.kakao.com/oauth/token', {
    method: 'post',
    payload: {
      grant_type: 'authorization_code',
      client_id: CONFIG.KAKAO_REST_API_KEY,
      redirect_uri: redirectUri,
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
  var userId = existingUserId ? String(existingUserId) : ('K' + me.id);
  var data = getUserData_(userId);
  data.kakaoToken = token.access_token;
  if (token.refresh_token) data.kakaoRefreshToken = token.refresh_token;
  data.kakaoNickname = nickname;
  saveUserData_(userId, data);
  registerUser_(userId);
  ensureTrigger_();
  return { success: true, userId: userId, nickname: nickname };
}

function setTelegramChatId(userId, telegramChatId) {
  userId = String(userId);
  var data = getUserData_(userId);
  data.telegramChatId = telegramChatId ? String(telegramChatId) : null;
  saveUserData_(userId, data);
  return { success: true };
}

function unlinkKakao(chatId) {
  chatId = String(chatId);
  var data = getUserData_(chatId);
  data.kakaoToken = null;
  data.kakaoRefreshToken = null;
  saveUserData_(chatId, data);
  return { success: true };
}
