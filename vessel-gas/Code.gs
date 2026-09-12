/**
 * vessel-gas/Code.gs
 * 선박 추적 텔레그램 봇 — 구글 앱스 스크립트(GAS) 버전
 *
 * Python 버전(vessel/)과 로직은 같지만, 서버 없이 구글 인프라에서
 * "텔레그램이 메시지를 보낼 때만" 깨어나 실행되는 웹훅 방식이다.
 * 데이터는 이 스크립트가 바인딩된 구글 시트에 저장 — 직원이 시트를
 * 직접 열어서 셀을 고쳐도 되고, 텔레그램 명령어로 고쳐도 된다(둘 다
 * 같은 시트를 본다).
 *
 * 배포 방법은 vessel-gas/README.md 참고. 여기 파일들은 script.google.com
 * 프로젝트에 그대로 복사해 넣으면 된다(파일당 하나의 .gs 스크립트 파일로).
 */

// ── 설정 읽기 (프로젝트 설정 > 스크립트 속성에 저장) ─────────────
function getConfig_() {
  const p = PropertiesService.getScriptProperties();
  return {
    token: p.getProperty('TELEGRAM_TOKEN') || '',
    adminIds: (p.getProperty('TELEGRAM_ADMIN_IDS') || '').split(',').map(s => s.trim()).filter(Boolean),
    vesselFinderKey: p.getProperty('VESSELFINDER_API_KEY') || '',
  };
}

function isAdmin_(chatId) {
  const cfg = getConfig_();
  if (cfg.adminIds.length === 0) return true; // 미설정 시 전부 허용(개발 편의) — 운영 전 꼭 설정
  return cfg.adminIds.indexOf(String(chatId)) !== -1;
}

function sendMessage_(chatId, text) {
  const cfg = getConfig_();
  const url = 'https://api.telegram.org/bot' + cfg.token + '/sendMessage';
  UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify({ chat_id: chatId, text: String(text).slice(0, 4000) }),
    muteHttpExceptions: true,
  });
}

// ── 텔레그램 웹훅 진입점 ─────────────────────────────────────────
function doPost(e) {
  try {
    const update = JSON.parse(e.postData.contents);
    const msg = update.message;
    if (!msg || !msg.text) return ContentService.createTextOutput('ok');

    const chatId = msg.chat.id;
    const text = msg.text.trim();

    if (text === '/start' || text === '/help') {
      sendMessage_(chatId, WELCOME_TEXT_);
    } else if (text.indexOf('/update') === 0) {
      handleUpdate_(chatId, text);
    } else if (text.indexOf('/delete') === 0) {
      handleDelete_(chatId, text);
    } else if (text.indexOf('/list') === 0) {
      handleList_(chatId);
    } else {
      const result = trackFromText(text);
      sendMessage_(chatId, result.message);
    }
  } catch (err) {
    console.error(err);
  }
  return ContentService.createTextOutput('ok');
}

const WELCOME_TEXT_ =
  '🚢 선박 추적 봇입니다.\n' +
  '모선명과 항차번호를 보내주시면 실시간 위치를 알려드려요.\n\n' +
  '예) HMM 코펜하겐, 0526E\n\n' +
  '관리자는 /update 로 터미널 정보를 직접 입력할 수 있어요 — 자세히 보려면 /update 만 입력.';

const UPDATE_HELP_ =
  '📝 터미널 정보 직접 입력 (관리자 전용)\n\n' +
  '형식:\n' +
  '/update 선명, 항차 | 터미널=HJNC | 선석=1부두 | ETB=2026-09-15 08:00 | 상태=접안예정\n\n' +
  '키(필요한 것만 넣으면 됨):\n' +
  '  터미널, 선석, ETA(입항예정), ETB(접안예정·제일 중요), ETD(출항예정), 상태\n\n' +
  '예)\n' +
  '/update EVER GIVEN, 0526E | ETB=2026-09-15 08:00 | 선석=1부두 | 터미널=HJNC\n\n' +
  '구글 시트의 ManualOverrides 탭에서 직접 수정해도 똑같이 반영됩니다.\n' +
  '삭제: /delete 선명, 항차\n' +
  '전체 확인: /list';

function commandArgs_(text) {
  const i = text.indexOf(' ');
  return i === -1 ? '' : text.slice(i + 1).trim();
}

function handleUpdate_(chatId, text) {
  if (!isAdmin_(chatId)) { sendMessage_(chatId, '⛔ 이 명령은 관리자만 쓸 수 있어요.'); return; }
  const parsed = parseUpdateArgs(commandArgs_(text));
  if (!parsed) { sendMessage_(chatId, UPDATE_HELP_); return; }
  setManualOverride(parsed.vesselName, parsed.voyageNo, parsed.fields, String(chatId));
  const saved = Object.keys(parsed.fields).map(k => '  ' + k + '=' + parsed.fields[k]).join('\n');
  sendMessage_(chatId, '✅ 저장했어요: ' + parsed.vesselName + ' / ' + parsed.voyageNo + '\n' + saved);
}

function handleDelete_(chatId, text) {
  if (!isAdmin_(chatId)) { sendMessage_(chatId, '⛔ 이 명령은 관리자만 쓸 수 있어요.'); return; }
  const args = commandArgs_(text);
  const parts = args.split(',');
  if (parts.length < 2) { sendMessage_(chatId, '형식: /delete 선명, 항차\n예) /delete EVER GIVEN, 0526E'); return; }
  const ok = deleteManualOverride(parts[0].trim(), parts.slice(1).join(',').trim());
  sendMessage_(chatId, ok ? '🗑️ 삭제했어요.' : '해당 항목을 찾지 못했어요.');
}

function handleList_(chatId) {
  if (!isAdmin_(chatId)) { sendMessage_(chatId, '⛔ 이 명령은 관리자만 쓸 수 있어요.'); return; }
  const rows = listManualOverrides();
  if (rows.length === 0) { sendMessage_(chatId, '저장된 수동입력이 없어요.'); return; }
  const lines = ['📋 현재 수동입력 ' + rows.length + '건:'];
  rows.forEach(r => {
    const summary = ['터미널', '선석', 'ETA', 'ETB', 'ETD', '상태']
      .map(k => r[k] ? (k + '=' + r[k]) : null).filter(Boolean).join(', ');
    lines.push('  • ' + r.vesselName + ' / ' + r.voyageNo + ' — ' + summary);
  });
  sendMessage_(chatId, lines.join('\n'));
}
