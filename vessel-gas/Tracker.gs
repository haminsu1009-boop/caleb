/**
 * vessel-gas/Tracker.gs
 * 파서 → 스케줄(수동입력/링크) → 디렉터리 → AIS 프로바이더 → 포맷터
 * 를 이어붙이는 오케스트레이션 (Python vessel/tracker.py 포팅).
 */

function trackFromText(text) {
  const q = parseQuery(text);
  return track(q.vesselName, q.voyageNo);
}

function track(vesselName, voyageNo) {
  if (!vesselName) return { ok: false, kind: 'no_input', message: NEED_INPUT_TEXT_ };

  const schedule = getScheduleInfo(vesselName, voyageNo);
  const scheduleBlock = formatScheduleBlock(schedule);

  const resolved = resolveVessel(vesselName);
  if (!resolved.entry) {
    if (resolved.candidates.length > 0) {
      return { ok: false, kind: 'ambiguous', message: formatAmbiguous_(vesselName, resolved.candidates) };
    }
    return { ok: false, kind: 'not_found', message: scheduleBlock + '\n\n' + formatNotFound_(vesselName) };
  }

  const pos = getAisPosition(resolved.entry.imo, resolved.entry.mmsi, resolved.entry.names[0]);
  if (!pos) {
    return { ok: false, kind: 'no_position', message: scheduleBlock + '\n\n' + formatNoPosition_(vesselName) };
  }

  const posBlock = formatPositionBlock_(resolved.entry.names[0], voyageNo, pos, schedule.kind === 'manual');
  return { ok: true, kind: 'position', message: scheduleBlock + '\n\n' + posBlock };
}
