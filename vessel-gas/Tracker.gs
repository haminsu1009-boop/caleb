/**
 * vessel-gas/Tracker.gs
 * 파서 → 스케줄(수동입력/링크) → (선택)AIS 순으로 조회.
 *
 * 디렉터리에 선박이 등록돼 있지 않아도 실패로 취급하지 않는다 —
 * 터미널/선사 링크나 수동입력 정보만으로도 답장은 항상 나간다.
 * AIS 실시간 위치는 디렉터리에 IMO/MMSI가 등록된 선박에 한해서만
 * "덤으로" 붙는다.
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
  if (resolved.candidates.length > 0) {
    // 디렉터리에 이름이 여러 개 걸리는 경우에만 되묻는다(등록 안 했으면 애초에 안 걸림)
    return { ok: false, kind: 'ambiguous', message: formatAmbiguous_(vesselName, resolved.candidates) };
  }

  if (resolved.entry) {
    const pos = getAisPosition(resolved.entry.imo, resolved.entry.mmsi, resolved.entry.names[0]);
    if (pos) {
      const posBlock = formatPositionBlock_(resolved.entry.names[0], voyageNo, pos, schedule.kind === 'manual');
      return { ok: true, kind: 'position', message: scheduleBlock + '\n\n' + posBlock };
    }
  }

  // 디렉터리 미등록/AIS 실패 — 스케줄 정보(수동입력 또는 링크)만으로 답장
  return { ok: true, kind: 'schedule_only', message: scheduleBlock };
}
