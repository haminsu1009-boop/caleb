/**
 * vessel-gas/Formatter.gs
 * 조회 결과 → 사람이 읽는 한국어 답장 문장 (Python vessel/formatter.py 포팅)
 */

const NEED_INPUT_TEXT_ =
  '🚢 모선명과 항차번호를 알려주시면 바로 추적해드려요.\n예) HMM 코펜하겐, 0526E';

function formatScheduleBlock(schedule) {
  if (schedule.kind === 'manual') {
    const m = schedule.data;
    const ageMin = Math.round((Date.now() - new Date(m.updatedAt).getTime()) / 60000);
    const age = ageMin < 60 ? (ageMin + '분 전') : (Math.floor(ageMin / 60) + '시간 전');
    const lines = ['🧑‍💼 ' + (m['터미널'] || '직원 확인') + ' — 직원이 직접 확인한 최신 정보'];
    if (m['선석']) lines.push('선석: ' + m['선석']);
    if (m['ETB']) lines.push('접안예정(ETB): ' + m['ETB']);
    if (m['ETA']) lines.push('입항예정(ETA): ' + m['ETA']);
    if (m['ETD']) lines.push('출항예정(ETD): ' + m['ETD']);
    if (m['상태']) lines.push('상태: ' + m['상태']);
    lines.push('입력: ' + age + ' (' + (m.updatedBy || '') + ')');
    return lines.join('\n');
  }
  const all = TERMINAL_LIST_.concat(CARRIER_LIST_);
  const lines = ['📋 터미널·선사 직접 확인 (자동 연동 준비 중):'];
  all.forEach(t => lines.push('  • ' + t.name + ': ' + t.url));
  return lines.join('\n');
}

function formatPositionBlock_(name, voyageNo, pos, hasManual) {
  const lines = ['🚢 ' + (pos.name || name || '선박') + (pos.imo ? (' (IMO ' + pos.imo + ')') : '')];
  if (voyageNo) {
    lines.push('항차: ' + voyageNo + (hasManual ? '' : '  ※AIS 데이터엔 항차번호가 없어 참고 표시용입니다'));
  }
  if (pos.lat != null && pos.lon != null) {
    lines.push('위치: ' + pos.lat.toFixed(4) + ', ' + pos.lon.toFixed(4) +
      '  (https://www.google.com/maps?q=' + pos.lat + ',' + pos.lon + ')');
  }
  if (pos.speedKn != null || pos.courseDeg != null) {
    const speed = pos.speedKn != null ? pos.speedKn.toFixed(1) + 'kn' : '-';
    const course = pos.courseDeg != null ? Math.round(pos.courseDeg) + '°' : '-';
    lines.push('속력: ' + speed + '  침로: ' + course);
  }
  if (pos.navStatus) lines.push('항행상태: ' + pos.navStatus);
  if (pos.destination) lines.push('목적지(AIS): ' + pos.destination);
  if (pos.etaUtc) lines.push('ETA(AIS): ' + pos.etaUtc);
  if (pos.lastReportUtc) lines.push('최종 수신: ' + pos.lastReportUtc);

  const sourceLabel = pos.source === 'vesselfinder' ? 'VesselFinder (실시간 AIS)'
    : '⚠️ 데모 데이터 — 실제 API 키 미등록 상태';
  lines.push('출처: ' + sourceLabel);
  if (pos.imo && pos.source !== 'mock') {
    lines.push('지도에서 보기: https://www.marinetraffic.com/en/ais/details/ships/imo:' + pos.imo);
  }
  return lines.join('\n');
}

function formatAmbiguous_(vesselName, candidates) {
  const lines = ["🔍 '" + vesselName + "'와(과) 비슷한 선박이 여러 척 있어요. 어느 배인가요?"];
  candidates.slice(0, 5).forEach(c => {
    const ident = c.imo ? ('IMO ' + c.imo) : ('MMSI ' + (c.mmsi || '?'));
    lines.push('  • ' + c.names[0] + ' (' + ident + ')');
  });
  lines.push('\n정확한 선명으로 다시 말씀해 주세요.');
  return lines.join('\n');
}

