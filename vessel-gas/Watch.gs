/**
 * vessel-gas/Watch.gs
 * "유니패스 알림봇" 방식 — 선박을 한 번 등록해두면, 그 이후로는 물어보지
 * 않아도 정보가 바뀔 때(관리자가 /update 할 때) 자동으로 알림이 온다.
 *
 * 지금은 "관리자가 /update 하는 순간" 바로 알림을 보내는 방식이라
 * 별도의 주기적 폴링(시간 트리거)이 필요 없다. 나중에 터미널 자동조회가
 * 완성되면, 시간 트리거를 하나 추가해서 "값이 실제로 바뀐 경우에만"
 * 알림을 보내게 확장할 수 있다 (README 참고).
 */

function watchKey_(vesselName, voyageNo) {
  return normalizeName_(vesselName) + '|' + normalizeName_(voyageNo);
}

function addWatch(chatId, vesselName, voyageNo) {
  const list = getJson_('VESSEL_WATCH', []);
  const key = watchKey_(vesselName, voyageNo);
  const exists = list.some(w => String(w.chatId) === String(chatId) && watchKey_(w.vesselName, w.voyageNo) === key);
  if (exists) return false;
  list.push({ chatId: String(chatId), vesselName: vesselName, voyageNo: voyageNo });
  setJson_('VESSEL_WATCH', list);
  return true;
}

function removeWatch(chatId, vesselName, voyageNo) {
  const list = getJson_('VESSEL_WATCH', []);
  const key = watchKey_(vesselName, voyageNo);
  const next = list.filter(w => !(String(w.chatId) === String(chatId) && watchKey_(w.vesselName, w.voyageNo) === key));
  const changed = next.length !== list.length;
  if (changed) setJson_('VESSEL_WATCH', next);
  return changed;
}

function listWatchesForChat(chatId) {
  return getJson_('VESSEL_WATCH', []).filter(w => String(w.chatId) === String(chatId));
}

function getWatchersFor(vesselName, voyageNo) {
  const key = watchKey_(vesselName, voyageNo);
  return getJson_('VESSEL_WATCH', [])
    .filter(w => watchKey_(w.vesselName, w.voyageNo) === key)
    .map(w => w.chatId);
}

/** 관리자가 /update로 값을 저장한 직후 호출 — 등록해둔 사람들에게 즉시 알림 */
function notifyWatchers(vesselName, voyageNo, message) {
  const chatIds = getWatchersFor(vesselName, voyageNo);
  chatIds.forEach(chatId => {
    sendMessage_(chatId, '🔔 알림 — 등록해두신 선박 정보가 갱신됐어요.\n\n' + message);
  });
  return chatIds.length;
}
