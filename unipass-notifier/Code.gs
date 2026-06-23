// 유니패스 통관상태 변경 감지 -> 텔레그램 알림 (Google Apps Script 버전)
//
// 사용법:
// 1) 아래 setup() 함수의 YOUR_... 부분을 실제 값으로 채우고 한 번 실행해서 스크립트 속성에 저장하세요.
//    (한 번 실행한 뒤엔 setup() 함수는 다시 실행하지 않아도 됩니다)
// 2) checkUnipass('BL번호', '연도') 또는 checkUnipassByCargo('화물관리번호') 를 실행/트리거로 호출하세요.

var UNIPASS_URL = 'https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo';

function setup() {
  var props = PropertiesService.getScriptProperties();
  props.setProperty('UNIPASS_API_KEY', 'YOUR_UNIPASS_API_KEY');
  props.setProperty('TELEGRAM_BOT_TOKEN', 'YOUR_TELEGRAM_BOT_TOKEN');
  props.setProperty('TELEGRAM_CHAT_ID', 'YOUR_TELEGRAM_CHAT_ID');
}

function getConfig_() {
  var props = PropertiesService.getScriptProperties();
  return {
    apiKey: props.getProperty('UNIPASS_API_KEY'),
    botToken: props.getProperty('TELEGRAM_BOT_TOKEN'),
    chatId: props.getProperty('TELEGRAM_CHAT_ID'),
  };
}

function fetchCargoProgress_(apiKey, mblNo, hblNo, blYy) {
  var url = UNIPASS_URL
    + '?crkyCn=' + encodeURIComponent(apiKey)
    + (mblNo ? '&mblNo=' + encodeURIComponent(mblNo) : '')
    + (hblNo ? '&hblNo=' + encodeURIComponent(hblNo) : '')
    + (blYy ? '&blYy=' + encodeURIComponent(blYy) : '');

  var resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
  var xml = resp.getContentText();
  var doc = XmlService.parse(xml);
  var root = doc.getRootElement();

  var records = [];
  collectRecords_(root, records);

  if (records.length === 0) {
    throw new Error('조회 결과가 없습니다. 번호/연도를 확인하세요. 응답 일부: ' + xml.substring(0, 300));
  }
  return records;
}

// XML 트리를 순회하면서 cargCsclPrgsInfo 태그를 가진 요소를 모두 찾아 {태그:값} 객체로 변환
function collectRecords_(el, out) {
  var name = el.getName();
  var children = el.getChildren();
  if (name.indexOf('cargCsclPrgsInfo') !== -1 && children.length > 0) {
    var record = {};
    children.forEach(function (c) {
      record[c.getName()] = c.getText().trim();
    });
    out.push(record);
  }
  children.forEach(function (c) {
    collectRecords_(c, out);
  });
}

function summarize_(records) {
  var latest = records[records.length - 1];
  var status = latest.csclPrgsStts || latest.prgsStts || latest.cargTrcnRsltNm;
  var date = latest.prcsDttm || latest.cargTrcnPrcsDttm || latest.prcsDt;
  if (status) {
    return date ? (status + ' (' + date + ')') : status;
  }
  var parts = [];
  for (var k in latest) {
    if (latest[k]) parts.push(k + '=' + latest[k]);
  }
  return parts.join(', ');
}

function hash_(records) {
  var json = JSON.stringify(records);
  var digest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, json);
  return digest.map(function (b) { return (b < 0 ? b + 256 : b).toString(16).padStart(2, '0'); }).join('');
}

function sendTelegram_(botToken, chatId, text) {
  var url = 'https://api.telegram.org/bot' + botToken + '/sendMessage';
  var resp = UrlFetchApp.fetch(url, {
    method: 'post',
    payload: { chat_id: chatId, text: text },
    muteHttpExceptions: true,
  });
  if (resp.getResponseCode() !== 200) {
    throw new Error('텔레그램 전송 실패: ' + resp.getContentText());
  }
}

function checkUnipassByCargo(cargoNo) {
  check_(cargoNo, null, null, null, cargoNo);
}

function checkUnipass(blNo, blYear) {
  check_(null, blNo, null, blYear, blNo + ':' + (blYear || ''));
}

function check_(cargoNo, mblNo, hblNo, blYy, stateKey) {
  var cfg = getConfig_();
  if (!cfg.apiKey || !cfg.botToken || !cfg.chatId) {
    throw new Error('스크립트 속성에 UNIPASS_API_KEY / TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 를 설정하세요.');
  }

  var records = fetchCargoProgress_(cfg.apiKey, cargoNo || mblNo, hblNo, blYy);
  var summary = summarize_(records);
  var newHash = hash_(records);

  var props = PropertiesService.getScriptProperties();
  var prevRaw = props.getProperty('STATE_' + stateKey);
  var prev = prevRaw ? JSON.parse(prevRaw) : null;

  if (!prev) {
    sendTelegram_(cfg.botToken, cfg.chatId, '[유니패스] ' + stateKey + ' 조회 시작\n현재 상태: ' + summary);
  } else if (prev.hash !== newHash) {
    sendTelegram_(cfg.botToken, cfg.chatId, '[유니패스] ' + stateKey + ' 상태 변경!\n이전: ' + prev.summary + '\n현재: ' + summary);
  } else {
    Logger.log('변경 없음: ' + summary);
  }

  props.setProperty('STATE_' + stateKey, JSON.stringify({ hash: newHash, summary: summary }));
}

// 시간 기반 트리거로 주기적으로 자동 확인하고 싶을 때 사용
// (Apps Script 편집기 좌측 시계 아이콘 > 트리거 추가 > 함수: checkAll, 시간 간격 선택)
function checkAll() {
  // 확인하고 싶은 번호들을 여기에 추가
  // checkUnipass('BL번호', '2026');
  // checkUnipassByCargo('화물관리번호');
}
