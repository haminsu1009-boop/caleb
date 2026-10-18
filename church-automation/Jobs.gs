/** 자동 실행되는 작업: 메시지를 만드는 부분(build)과 보내는 부분(send)을 나눠 둠 → 미리보기 가능 */

/** ① 일요일 아침: 다음 주 임무 요약 + 부탁·리마인드 메시지 + 앞으로 비어 있는 순서 */
function sendNextWeekAssignments() {
  notify_(buildNextWeek_(new Date()));
}

/** ② 토요일 오후: 장로정원회 톡방용 내일 성찬 임무지명 공지 */
function sendTomorrowNotice() {
  notify_(buildTomorrow_(new Date()));
}

function buildNextWeek_(today) {
  const target = nextSunday_(today);
  const label = fmt_(target, 'M/d');
  const m = getMeeting_(target);
  const ahead = lookahead_(target);

  if (!m) {
    return { subject: `[확인 필요] ${label} 성찬식 일정 없음`,
      text: lines_(`원본 시트에서 ${label} 줄을 찾지 못했습니다.`, ahead) };
  }
  if (m.special) {
    return { subject: `[${label}] ${m.special}`, text: lines_(`📌 ${label} 주일은 ${m.special}입니다.`, ahead) };
  }

  const missing = missingRoles_(m);
  const drafts = drafts_(m);
  return {
    subject: `${missing.length ? '[확인 필요] ' : ''}${label} 성찬식 임무 (다음 주)`,
    text: lines_(
      `📋 ${label} 성찬식 임무 (다음 주)`,
      summary_(m),
      missing.length ? `⚠️ 미정: ${missing.join(', ')}` : null,
      ahead),
    drafts: drafts,
    kakaoExtras: getSetting_('부탁 메시지 카톡 발송') === '아니오' ? [] : drafts,
    emailExtra: drafts.length
      ? lines_('✉️ 부탁·리마인드 메시지 (복사해서 각자에게 보내세요)', ...drafts.map(d => `\n────────\n${d}`))
      : '',
  };
}

function buildTomorrow_(today) {
  const target = upcomingSunday_(today);
  const label = fmt_(target, 'M/d');
  const m = getMeeting_(target);
  if (!m) return { subject: `[확인 필요] ${label} 성찬식 일정 없음`, text: `원본 시트에서 ${label} 줄을 찾지 못했습니다.` };
  if (m.special) return { subject: `[${label}] ${m.special}`, text: `📌 내일(${label})은 ${m.special}입니다.` };

  const names = list => (list.length ? list.map(withTitle_).join(', ') : '미정');
  const notice = lines_(
    `📢 내일(${label}) 성찬 임무지명 안내`,
    `성찬 축복: ${names(m.blessers)}`,
    `성찬 전달: ${names(m.passers)}`,
    '',
    '준비 잘 부탁드립니다. 감사합니다 🙏');
  return {
    subject: `${m.blessers.length && m.passers.length ? '' : '[확인 필요] '}내일(${label}) 성찬 임무지명 공지`,
    text: notice,
    emailExtra: lines_('— 내일 순서 전체 —', summary_(m)),
  };
}

function summary_(m) {
  const t = withTitle_;
  return lines_(
    `사회 ${m.conducting || '미정'} · 지휘 ${m.chorister || '미정'} · 반주 ${m.organist || '미정'}`,
    `말씀: ${m.fast ? '금식간증' : m.speakers.map(t).join(', ') || '미정'}`,
    m.fast ? null : `마지막 연사: ${t(m.lastSpeaker) || '미정'}`,
    `기도: ${t(m.openingPrayer) || '미정'}(개회) · ${t(m.closingPrayer) || '미정'}(폐회)`,
    m.blessers.length ? `성찬 축복: ${m.blessers.join(', ')}` : null,
    m.passers.length ? `성찬 전달: ${m.passers.join(', ')}` : null);
}

function missingRoles_(m) {
  if (m.special) return [];
  const talks = ['talk5', 'talk10', 'lastSpeaker'];
  return REQUIRED_ROLES.filter(([k]) => !(m.fast && talks.includes(k)) && !m[k]).map(([, label]) => label);
}

/** 다음 주 이후 N주 안에 비어 있는 순서 */
function lookahead_(fromSunday) {
  const weeks = Number(getSetting_('미리 확인할 주 수')) || 8;
  const found = [];
  for (let i = 1; i < weeks; i++) {
    const sunday = addDays_(fromSunday, 7 * i);
    const m = getMeeting_(sunday);
    const missing = m ? missingRoles_(m) : [];
    if (missing.length) found.push(`• ${fmt_(sunday, 'M/d')} ${missing.join(', ')}`);
  }
  return found.length ? lines_('', `🗓 앞으로 ${weeks}주 미정 순서`, ...found) : null;
}

/** 맡은 분별 부탁·리마인드 메시지 (사람 이름인 칸만) */
function drafts_(m) {
  const template = getSetting_('부탁 메시지') || DEFAULT_REQUEST_TEMPLATE;
  const talks = ['talk5', 'talk10', 'lastSpeaker'];
  return REMINDER_ROLES
    .filter(([k]) => isPerson_(m[k]))
    .map(([k, role]) => template
      .split('{이름}').join(withTitle_(m[k]))
      .split('{날짜}').join(fmt_(m.sunday, 'M월 d일'))
      .split('{역할}').join(role)
      .split('{와드}').join(getSetting_('와드 이름'))
      .split('{주제}').join(m.topic && talks.includes(k) ? `\n말씀 주제: ${m.topic}` : ''));
}

/** 메뉴 → 미리보기 (보내지 않고 화면에만 표시) */
function previewNextWeek() {
  showPreview_(buildNextWeek_(new Date()));
}

function previewTomorrow() {
  showPreview_(buildTomorrow_(new Date()));
}

function showPreview_(msg) {
  SpreadsheetApp.getUi().alert(msg.subject, lines_(msg.text, msg.emailExtra ? '\n' + msg.emailExtra : null),
    SpreadsheetApp.getUi().ButtonSet.OK);
}
