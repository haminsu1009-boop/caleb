/**
 * vessel-gas/Code.gs
 * 선박 추적 + 알림 텔레그램 봇 — 구글 앱스 스크립트(GAS) 버전
 *
 * 서버 없이 구글 인프라에서 "텔레그램이 메시지를 보낼 때만" 깨어나
 * 실행되는 웹훅 방식. 구글 시트 필요 없음 — 데이터는 이 스크립트
 * 자체 저장소(PropertiesService)에 둔다.
 *
 * 유니패스 알림봇처럼: /watch로 선박을 한 번 등록해두면, 그 이후로는
 * 다시 안 물어봐도 관리자가 /update로 정보를 갱신할 때마다 자동으로
 * 알림이 온다.
 *
 * 배포 방법은 vessel-gas/README.md 참고.
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
    } else if (text.indexOf('/unwatch') === 0) {
      handleUnwatch_(chatId, text);
    } else if (text.indexOf('/watch') === 0) {
      handleWatch_(chatId, text);
    } else if (text.indexOf('/mywatch') === 0) {
      handleMyWatch_(chatId);
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
  '모선명과 항차번호를 보내주시면 지금 있는 정보를 바로 알려드려요.\n\n' +
  '예) HMM 코펜하겐, 0526E\n\n' +
  '🔔 알림 등록: /watch 선명, 항차 — 등록해두면 정보가 갱신될 때마다 다시 안 물어봐도 알려드려요.\n' +
  '관리자는 /update 로 터미널 정보를 직접 입력할 수 있어요 — 자세히 보려면 /update 만 입력.';

const UPDATE_HELP_ =
  '📝 터미널 정보 직접 입력 (관리자 전용)\n\n' +
  '형식:\n' +
  '/update 선명, 항차 | 터미널=HJNC | 선석=1부두 | ETB=2026-09-15 08:00 | 상태=접안예정\n\n' +
  '키(필요한 것만 넣으면 됨):\n' +
  '  터미널, 선석, ETA(입항예정), ETB(접안예정·제일 중요), ETD(출항예정), 상태\n\n' +
  '예)\n' +
  '/update EVER GIVEN, 0526E | ETB=2026-09-15 08:00 | 선석=1부두 | 터미널=HJNC\n\n' +
  '이 선박을 /watch 해둔 사람들에게 자동으로 알림이 갑니다.\n' +
  '삭제: /delete 선명, 항차\n' +
  '전체 확인: /list';

function commandArgs_(text) {
  const i = text.indexOf(' ');
  return i === -1 ? '' : text.slice(i + 1).trim();
}

function parseNamevoyageArgs_(args) {
  const idx = args.indexOf(',');
  if (idx === -1) return null;
  const vesselName = args.slice(0, idx).trim();
  const voyageNo = args.slice(idx + 1).trim();
  if (!vesselName || !voyageNo) return null;
  return { vesselName: vesselName, voyageNo: voyageNo };
}

function handleUpdate_(chatId, text) {
  if (!isAdmin_(chatId)) { sendMessage_(chatId, '⛔ 이 명령은 관리자만 쓸 수 있어요.'); return; }
  const parsed = parseUpdateArgs(commandArgs_(text));
  if (!parsed) { sendMessage_(chatId, UPDATE_HELP_); return; }

  setManualOverride(parsed.vesselName, parsed.voyageNo, parsed.fields, String(chatId));
  const saved = Object.keys(parsed.fields).map(k => '  ' + k + '=' + parsed.fields[k]).join('\n');
  sendMessage_(chatId, '✅ 저장했어요: ' + parsed.vesselName + ' / ' + parsed.voyageNo + '\n' + saved);

  // watch 등록된 사람들에게 자동 알림 (유니패스 알림봇 방식)
  const result = track(parsed.vesselName, parsed.voyageNo);
  const notified = notifyWatchers(parsed.vesselName, parsed.voyageNo, result.message);
  if (notified > 0) sendMessage_(chatId, '🔔 이 선박을 등록해둔 ' + notified + '명에게 알림을 보냈어요.');
}

function handleDelete_(chatId, text) {
  if (!isAdmin_(chatId)) { sendMessage_(chatId, '⛔ 이 명령은 관리자만 쓸 수 있어요.'); return; }
  const parsed = parseNamevoyageArgs_(commandArgs_(text));
  if (!parsed) { sendMessage_(chatId, '형식: /delete 선명, 항차\n예) /delete EVER GIVEN, 0526E'); return; }
  const ok = deleteManualOverride(parsed.vesselName, parsed.voyageNo);
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

// ── 알림 등록/해제 (누구나 사용 가능 — 자기 알림만 관리) ────────────
function handleWatch_(chatId, text) {
  const parsed = parseNamevoyageArgs_(commandArgs_(text));
  if (!parsed) { sendMessage_(chatId, '형식: /watch 선명, 항차\n예) /watch EVER GIVEN, 0526E'); return; }
  const added = addWatch(chatId, parsed.vesselName, parsed.voyageNo);
  sendMessage_(chatId, added
    ? ('🔔 알림 등록했어요: ' + parsed.vesselName + ' / ' + parsed.voyageNo + '\n정보가 갱신될 때마다 알려드릴게요.')
    : '이미 등록돼 있어요.');
}

function handleUnwatch_(chatId, text) {
  const parsed = parseNamevoyageArgs_(commandArgs_(text));
  if (!parsed) { sendMessage_(chatId, '형식: /unwatch 선명, 항차'); return; }
  const removed = removeWatch(chatId, parsed.vesselName, parsed.voyageNo);
  sendMessage_(chatId, removed ? '🔕 알림 해제했어요.' : '등록된 게 없어요.');
}

function handleMyWatch_(chatId) {
  const list = listWatchesForChat(chatId);
  if (list.length === 0) { sendMessage_(chatId, '등록된 알림이 없어요. /watch 선명, 항차 로 등록해보세요.'); return; }
  const lines = ['🔔 내 알림 목록 ' + list.length + '건:'];
  list.forEach(w => lines.push('  • ' + w.vesselName + ' / ' + w.voyageNo));
  sendMessage_(chatId, lines.join('\n'));
}
