// 유니패스 통관상태 변경 감지 -> 텔레그램 알림
//
// 사용법:
// 1) 함수 선택 드롭다운에서 run 선택 -> 실행(▶) 클릭. 권한 요청 뜨면 허용. (1회 테스트용)
// 2) 자동으로 1분마다 체크하고 싶으면, 함수 드롭다운에서 createTrigger 선택 -> 실행.
//    (한 번만 실행하면 됨. 그 뒤로는 1분마다 자동으로 run이 돌면서 상태가 바뀔 때만 알림이 옴)
// 3) 자동 체크를 멈추고 싶으면 removeTriggers 실행.

var CONFIG = {
  UNIPASS_API_KEY: 'n250i296j006s253p060c040h5',
  TELEGRAM_BOT_TOKEN: '8901206831:AAF2cPkHwSVjaqFyNqvO-ke5B-ubXFLYveg',
  TELEGRAM_CHAT_ID: '8624472047',
  BL_NO: 'KMTCYOK0756465',
  BL_YEAR: '2026',
};

var UNIPASS_URL = 'https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo';

function run() {
  if (!CONFIG.BL_NO) {
    throw new Error('CONFIG 의 BL_NO 를 채워주세요.');
  }

  var stateKey = CONFIG.BL_NO + ':' + CONFIG.BL_YEAR;
  var records = fetchCargoProgress_(CONFIG.BL_NO, CONFIG.BL_YEAR);
  var latest = pickLatest_(records);
  var summaryLine = summaryLine_(latest);
  var newHash = hash_(records);

  var props = PropertiesService.getScriptProperties();
  var prevRaw = props.getProperty('STATE_' + stateKey);
  var prev = prevRaw ? JSON.parse(prevRaw) : null;
  var changed = !prev || prev.hash !== newHash;

  if (changed) {
    sendTelegram_(formatMessage_(!prev, prev ? prev.summaryLine : null, latest));
  }
  Logger.log((changed ? '상태 변경/최초 조회 (알림 전송): ' : '확인(변경없음, 알림 안보냄): ') + summaryLine);

  props.setProperty('STATE_' + stateKey, JSON.stringify({ hash: newHash, summaryLine: summaryLine }));
}

function fetchCargoProgress_(blNo, blYear) {
  var url = UNIPASS_URL + '?crkyCn=' + encodeURIComponent(CONFIG.UNIPASS_API_KEY)
    + '&mblNo=' + encodeURIComponent(blNo)
    + '&blYy=' + encodeURIComponent(blYear);

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

// prcsDttm(처리시각) 기준으로 가장 최근 기록을 고른다 (API가 항상 시간순으로 주지 않을 수 있음)
function pickLatest_(records) {
  var latest = records[0];
  var latestTime = recordTime_(latest);
  for (var i = 1; i < records.length; i++) {
    var t = recordTime_(records[i]);
    if (t >= latestTime) {
      latest = records[i];
      latestTime = t;
    }
  }
  return latest;
}

function recordTime_(record) {
  var raw = record.prcsDttm || record.cargTrcnPrcsDttm || record.prcsDt || '';
  return raw;
}

function summaryLine_(record) {
  var status = record.cargTrcnRelaBsopTpcd || record.csclPrgsStts || record.prgsStts || record.cargTrcnRsltNm;
  var date = formatDttm_(record.prcsDttm || record.cargTrcnPrcsDttm || record.prcsDt);
  if (status) {
    return date ? (status + ' (' + date + ')') : status;
  }
  var parts = [];
  for (var k in record) {
    if (record[k]) parts.push(k + '=' + record[k]);
  }
  return parts.join(', ');
}

function hash_(records) {
  var json = JSON.stringify(records);
  var digest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, json);
  return digest.map(function (b) { return (b < 0 ? b + 256 : b).toString(16).padStart(2, '0'); }).join('');
}

// 텔레그램에 보기 좋게 정리된 HTML 메시지를 만든다
function formatMessage_(isFirst, prevLine, latestRecord) {
  var status = latestRecord.cargTrcnRelaBsopTpcd || latestRecord.csclPrgsStts || latestRecord.prgsStts || latestRecord.cargTrcnRsltNm || '-';
  var date = formatDttm_(latestRecord.prcsDttm || latestRecord.cargTrcnPrcsDttm || latestRecord.prcsDt);
  var checkedAt = Utilities.formatDate(new Date(), 'Asia/Seoul', 'MM월 dd일 HH시 mm분');

  var lines = [];
  lines.push('<b>' + (isFirst ? '📦 조회 시작' : '🔔 상태 변경 감지!') + '</b>');
  lines.push('');
  lines.push('🕐 확인 시각: ' + checkedAt);
  lines.push('🚢 BL번호: <code>' + CONFIG.BL_NO + '</code>');
  if (prevLine) {
    lines.push('이전 상태: ' + prevLine);
  }
  lines.push('현재 상태: <b>' + status + '</b>');
  lines.push('통관 처리시각: ' + date);
  return lines.join('\n');
}

// '20260612160923' 같은 형식을 '2026-06-12 16:09:23' 로 변환
function formatDttm_(raw) {
  if (!raw || raw.length < 14) return raw || '-';
  return raw.substring(0, 4) + '-' + raw.substring(4, 6) + '-' + raw.substring(6, 8)
    + ' ' + raw.substring(8, 10) + ':' + raw.substring(10, 12) + ':' + raw.substring(12, 14);
}

function sendTelegram_(text) {
  var url = 'https://api.telegram.org/bot' + CONFIG.TELEGRAM_BOT_TOKEN + '/sendMessage';
  var resp = UrlFetchApp.fetch(url, {
    method: 'post',
    payload: { chat_id: CONFIG.TELEGRAM_CHAT_ID, text: text, parse_mode: 'HTML' },
    muteHttpExceptions: true,
  });
  if (resp.getResponseCode() !== 200) {
    throw new Error('텔레그램 전송 실패: ' + resp.getContentText());
  }
}

// 1분마다 자동으로 run()을 실행하는 트리거를 등록한다. 한 번만 실행하면 됨.
function createTrigger() {
  removeTriggers();
  ScriptApp.newTrigger('run')
    .timeBased()
    .everyMinutes(1)
    .create();
  Logger.log('1분마다 자동 체크 트리거가 등록되었습니다.');
}

// run에 연결된 기존 트리거를 모두 제거한다 (중복 등록 방지 / 자동 체크 끄기용)
function removeTriggers() {
  var triggers = ScriptApp.getProjectTriggers();
  triggers.forEach(function (trigger) {
    if (trigger.getHandlerFunction() === 'run') {
      ScriptApp.deleteTrigger(trigger);
    }
  });
}
