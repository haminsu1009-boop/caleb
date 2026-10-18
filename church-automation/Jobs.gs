/** 자동 실행되는 3가지 작업 */

/** ① 토요일 저녁: 내일 주일 말씀 주제 전달 */
function sendWeeklyTopic() {
  const sunday = upcomingSunday_(new Date());
  const s = findByDate_(CONFIG.SHEETS.SERMON, sunday);
  if (!s) {
    notify_('[확인 필요] 주일 말씀 미입력',
      `${fmt_(sunday, 'M/d')} 주일 말씀이 '${CONFIG.SHEETS.SERMON}' 시트에 아직 없습니다.`);
    return;
  }
  if (s['주제전송']) return; // 이미 보낸 주는 다시 보내지 않음

  const text = lines_(
    `📖 ${fmt_(sunday, 'M월 d일')} 주일 말씀`,
    `주제: ${s['말씀주제']}`,
    s['성경본문'] ? `본문: ${s['성경본문']}` : null,
    s['설교자'] ? `설교: ${s['설교자']}` : null,
    s['핵심구절'] ? `\n"${s['핵심구절']}"` : null,
    '',
    '말씀을 기도로 함께 준비해요 🙏');
  notify_(`[주일 말씀] ${s['말씀주제']}`, text);
  setCell_(CONFIG.SHEETS.SERMON, s._row, '주제전송', new Date());
}

/** ② 매일 아침: 이번 주 말씀 + 기도제목 리마인드 */
function sendDailyReminder() {
  const today = new Date();
  const s = findByDate_(CONFIG.SHEETS.SERMON, lastSunday_(today))
         || findByDate_(CONFIG.SHEETS.SERMON, upcomingSunday_(today));

  const prayers = readRows_(CONFIG.SHEETS.PRAYER)
    .filter(p => p['상태'] !== '응답' && p['공개'] !== '비공개' && p['기도제목']);

  // 기도제목이 많으면 날마다 다른 묶음이 보이도록 순환
  const n = Math.min(CONFIG.MAX_PRAYERS_PER_DAY, prayers.length);
  const start = prayers.length ? Math.floor(today.getTime() / 86400000) * n % prayers.length : 0;
  const todays = Array.from({ length: n }, (_, i) => prayers[(start + i) % prayers.length]);

  if (!s && !todays.length) return;

  const text = lines_(
    `🙏 ${fmt_(today, 'M/d(E)')} 오늘의 말씀과 기도`,
    s && s['핵심구절'] ? `"${s['핵심구절']}" (${s['성경본문']})` : null,
    s && !s['핵심구절'] ? `이번 주 말씀: ${s['말씀주제']}` : null,
    todays.length ? '' : null,
    ...todays.map(p => `• ${p['요청자'] ? p['요청자'] + ': ' : ''}${p['기도제목']}`));
  notify_(`[오늘의 기도] ${fmt_(today, 'M/d')}`, text);
}

/** ③ 매주: 성찬식 순서 구글 문서 갱신 */
function updateCommunionAgenda() {
  const sunday = upcomingSunday_(new Date());
  const c = findByDate_(CONFIG.SHEETS.COMMUNION, sunday) || {};
  const s = findByDate_(CONFIG.SHEETS.SERMON, sunday) || {};
  const doc = getAgendaDoc_();
  const body = doc.getBody();
  const H = DocumentApp.ParagraphHeading;
  const missing = [];
  const val = col => {
    if (c[col]) return String(c[col]);
    if (!missing.includes(col)) missing.push(col);
    return '(미정)';
  };

  body.clear();
  body.getParagraphs()[0].setText(`${getSetting_('교회 이름')} 성찬식 순서`).setHeading(H.TITLE);
  body.appendParagraph(`${fmt_(sunday, 'yyyy년 M월 d일')} 주일   ·   자동 업데이트 ${fmt_(new Date(), 'M/d HH:mm')}`);

  body.appendParagraph('이번 주 말씀').setHeading(H.HEADING2);
  body.appendParagraph(lines_(
    `주제: ${s['말씀주제'] || '(미입력)'}`,
    `본문: ${s['성경본문'] || '(미입력)'}`,
    s['핵심구절'] ? `핵심구절: ${s['핵심구절']}` : null));

  body.appendParagraph('예식 순서').setHeading(H.HEADING2);
  const table = body.appendTable([['순서', '내용', '담당'], ...COMMUNION_ORDER.map((o, i) => [
    `${i + 1}. ${o.step}`,
    o.detail || (o.detailCol ? val(o.detailCol) : ''),
    o.owner || (o.ownerCol ? val(o.ownerCol) : ''),
  ])]);
  table.getRow(0).editAsText().setBold(true);

  body.appendParagraph('준비 체크리스트').setHeading(H.HEADING2);
  if (c['준비담당']) body.appendParagraph(`준비 담당: ${c['준비담당']}`);
  COMMUNION_CHECKLIST.forEach(item => body.appendListItem(`☐ ${item}`));

  if (c['비고']) {
    body.appendParagraph('비고').setHeading(H.HEADING2);
    body.appendParagraph(String(c['비고']));
  }
  doc.saveAndClose();

  notify_(`[성찬식] ${fmt_(sunday, 'M/d')} 순서 업데이트`,
    lines_(`🍞🍷 ${fmt_(sunday, 'M월 d일')} 성찬식 순서가 업데이트되었습니다.`,
      missing.length ? `\n⚠️ 미정: ${missing.join(', ')}` : null),
    doc.getUrl());
}

function getAgendaDoc_() {
  const id = getSetting_('성찬식 문서 ID');
  if (id) {
    try { return DocumentApp.openById(id); } catch (e) { /* 지워졌으면 새로 만듦 */ }
  }
  const doc = DocumentApp.create(`${getSetting_('교회 이름')} 성찬식 순서`);
  setSetting_('성찬식 문서 ID', doc.getId());
  return doc;
}
