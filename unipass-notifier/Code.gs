// 유니패스 통관상태 변경 감지 -> 텔레그램 알림
//
// 사용법:
// 1) 아래 CONFIG의 BL_NO, BL_YEAR 를 본인이 조회하고 싶은 BL번호/연도로 바꾼다.
//    (화물관리번호로 조회하려면 CARGO_NO 에 값을 넣는다. BL_NO/CARGO_NO 둘 중 하나만 채우면 된다)
// 2) 함수 선택 드롭다운에서 run 선택 -> 실행(▶) 클릭. 권한 요청 뜨면 허용.
// 3) 텔레그램으로 메시지가 오는지 확인한다.
// 4) 잘 되면, 좌측 시계 아이콘(트리거) -> 트리거 추가 -> 함수: run, 시간 기반, 예: 10분마다
//    로 설정하면 그 다음부터는 상태가 바뀔 때만 자동으로 텔레그램 알림이 온다.

var CONFIG = {
  UNIPASS_API_KEY: 'n250i296j006s253p060c040h5',
  TELEGRAM_BOT_TOKEN: '8901206831:AAF2cPkHwSVjaqFyNqvO-ke5B-ubXFLYveg',
  TELEGRAM_CHAT_ID: '755200451',

  // 조회할 화물번호: BL번호 방식 또는 화물관리번호 방식 중 하나만 채운다
  BL_NO: 'KMTCYOK0756465',
  BL_YEAR: '',     // 예: '2026' (BL_NO 사용 시 같이 채움) - 아래 답변 후 채워주세요
  CARGO_NO: '',    // 화물관리번호 (이걸 채우면 BL_NO보다 우선 사용됨)
};

var UNIPASS_URL = 'https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo';

function run() {
  if (!CONFIG.CARGO_NO && !CONFIG.BL_NO) {
    throw new Error('CONFIG 의 BL_NO 또는 CARGO_NO 중 하나를 채워주세요.');
  }

  var stateKey = CONFIG.CARGO_NO || (CONFIG.BL_NO + ':' + CONFIG.BL_YEAR);
  var records = fetchCargoProgress_(CONFIG.CARGO_NO, CONFIG.BL_NO, CONFIG.BL_YEAR);
  var summary = summarize_(records);
  var newHash = hash_(records);

  var props = PropertiesService.getScriptProperties();
  var prevRaw = props.getProperty('STATE_' + stateKey);
  var prev = prevRaw ? JSON.parse(prevRaw) : null;

  if (!prev) {
    sendTelegram_('[유니패스] ' + stateKey + ' 조회 시작\n현재 상태: ' + summary);
    Logger.log('최초 조회: ' + summary);
  } else if (prev.hash !== newHash) {
    sendTelegram_('[유니패스] ' + stateKey + ' 상태 변경!\n이전: ' + prev.summary + '\n현재: ' + summary);
    Logger.log('상태 변경 감지: ' + prev.summary + ' -> ' + summary);
  } else {
    Logger.log('변경 없음: ' + summary);
  }

  props.setProperty('STATE_' + stateKey, JSON.stringify({ hash: newHash, summary: summary }));
}

function fetchCargoProgress_(cargoNo, blNo, blYear) {
  var url = UNIPASS_URL + '?crkyCn=' + encodeURIComponent(CONFIG.UNIPASS_API_KEY);
  if (cargoNo) {
    url += '&cargMtNo=' + encodeURIComponent(cargoNo);
  } else {
    url += '&mblNo=' + encodeURIComponent(blNo);
    if (blYear) url += '&blYy=' + encodeURIComponent(blYear);
  }

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

function sendTelegram_(text) {
  var url = 'https://api.telegram.org/bot' + CONFIG.TELEGRAM_BOT_TOKEN + '/sendMessage';
  var resp = UrlFetchApp.fetch(url, {
    method: 'post',
    payload: { chat_id: CONFIG.TELEGRAM_CHAT_ID, text: text },
    muteHttpExceptions: true,
  });
  if (resp.getResponseCode() !== 200) {
    throw new Error('텔레그램 전송 실패: ' + resp.getContentText());
  }
}
