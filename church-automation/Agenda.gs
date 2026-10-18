/**
 * ③ 월요일: 「성찬식 아젠다」 문서 맨 위에 이번 주 주일 순서 추가
 * 지난주 칸을 그대로 복사(글꼴·표 모양 유지)한 뒤, 시트 값으로 칸만 바꿔 씀.
 * 광고·와드 행사 같은 그 주에만 해당하는 줄은 복사하지 않음 → 사람이 채움.
 * 그 주 칸이 이미 있으면 새로 만들지 않고, 시트 값으로 순서 칸만 다시 맞춤(광고 등은 그대로).
 */
const AGENDA_LINES = [
  ['개회찬송:', m => m.hymns.openingHymn],
  ['개회기도:', m => withTitle_(m.openingPrayer)],
  ['성찬찬송:', m => m.hymns.sacramentHymn],
  ['말씀:', m => m.speakers.map(withTitle_).join(', ')],
  ['회중찬송:', m => m.hymns.restHymn],
  ['마지막 연사 말씀:', m => withTitle_(m.lastSpeaker)],
  ['마지막 말씀:', m => withTitle_(m.lastSpeaker)],
  ['폐회찬송:', m => m.hymns.closingHymn],
  ['폐회기도:', m => withTitle_(m.closingPrayer)],
];
// [표 칸 이름, 값, 시트에 값이 없으면 지난주 값 유지?]
const AGENDA_CELLS = [
  ['감리:', m => m.presiding, true],
  ['사회:', m => withTitle_(m.conducting), false],
  ['지휘:', m => withTitle_(m.chorister), false],
  ['반주:', m => withTitle_(m.organist), false],
];
const AGENDA_SECTIONS = ['광고', '스테이크 행사', '와드 행사'];
const SECTION_RE = /^\d{1,2}\.\d{1,2}\s.*성찬식/; // 예: '10.18 녹번와드 성찬식'
const SEPARATOR_RE = /^-{3,}$/;

function updateAgenda() {
  const target = upcomingSunday_(new Date());
  const label = fmt_(target, 'M/d');
  const m = getMeeting_(target);
  if (!m) return notify_({ subject: `[확인 필요] ${label} 아젠다 생략`, text: `원본 시트에서 ${label} 줄을 찾지 못했습니다.` });
  if (m.special) return log_('아젠다 생략', `${label} ${m.special}`);

  let doc;
  try {
    doc = DocumentApp.openById(fileId_(getSetting_('아젠다 문서')));
  } catch (e) {
    return notify_({ subject: '[확인 필요] 아젠다 문서를 열 수 없음',
      text: `'설정'의 아젠다 문서 주소와 편집 권한을 확인해 주세요.\n${e.message}` });
  }
  const result = insertAgendaSection_(doc.getBody(), m);
  doc.saveAndClose();

  if (result === 'updated') {
    return notify_({ subject: `[아젠다] ${label} 순서 다시 맞춤`,
      text: `🔄 ${label} 아젠다의 순서 칸을 시트 값으로 다시 맞췄습니다. (광고·행사는 그대로)`, link: doc.getUrl() });
  }
  notify_({
    subject: `[아젠다] ${label} 성찬식 순서 추가`,
    text: lines_(
      `📝 ${label} 성찬식 아젠다를 문서 맨 위에 추가했습니다.`,
      m.presiding ? null : '• 감리는 지난주 값 그대로입니다. 확인해 주세요.',
      '• 광고 · 스테이크/와드 행사는 직접 채워 주세요.'),
    link: doc.getUrl(),
  });
}

function insertAgendaSection_(body, m) {
  const P = DocumentApp.ElementType.PARAGRAPH;
  const T = DocumentApp.ElementType.TABLE;
  const text = el => (el.getType() === P ? el.asParagraph().getText().trim() : '');
  const newDate = fmt_(m.sunday, 'MM.dd');

  // 가장 최근 주 칸(맨 위 'MM.DD … 성찬식' 제목) 찾기
  const n = body.getNumChildren();
  let start = -1;
  for (let i = 0; i < n; i++) if (SECTION_RE.test(text(body.getChild(i)))) { start = i; break; }
  if (start < 0) throw new Error("아젠다 문서에서 'MM.DD … 성찬식' 제목을 찾지 못했습니다.");
  const section = collectSection_(body, start);
  if (text(body.getChild(start)).startsWith(newDate)) {
    fillSection_(section, m);
    return 'updated';
  }

  // 복사해서 바로 위에 끼워 넣기 (목록·메모 줄은 빼고)
  const keep = s => s === '' || SECTION_RE.test(s) || SEPARATOR_RE.test(s)
    || AGENDA_SECTIONS.includes(s) || AGENDA_LINES.some(([l]) => s.startsWith(l));
  let at = start;
  const inserted = [];
  section.forEach(el => {
    if (el.getType() === T) inserted.push(body.insertTable(at++, el.asTable().copy()));
    else if (el.getType() === P && keep(text(el))) inserted.push(body.insertParagraph(at++, el.asParagraph().copy()));
  });

  fillSection_(inserted, m);
  return 'added';
}

/** 제목 줄부터 그 주 칸의 끝(----- 줄)까지 모으기 */
function collectSection_(body, start) {
  const P = DocumentApp.ElementType.PARAGRAPH;
  const text = el => (el.getType() === P ? el.asParagraph().getText().trim() : '');
  const section = [];
  for (let i = start; i < body.getNumChildren(); i++) {
    const el = body.getChild(i);
    if (i > start && SECTION_RE.test(text(el))) break;
    section.push(el);
    if (SEPARATOR_RE.test(text(el))) break;
  }
  return section;
}

/** 제목 날짜 · 표 칸 · '개회기도:' 같은 줄에 시트 값 채우기 (그 밖의 줄은 건드리지 않음) */
function fillSection_(elements, m) {
  const newDate = fmt_(m.sunday, 'MM.dd');
  elements.forEach(el => {
    if (el.getType() === DocumentApp.ElementType.TABLE) return fillTable_(el, m);
    if (el.getType() !== DocumentApp.ElementType.PARAGRAPH) return; // 목록 항목 등
    const p = el.asParagraph();
    const s = p.getText();
    if (SECTION_RE.test(s.trim())) {
      const d = s.match(/\d{1,2}\.\d{1,2}/);
      p.editAsText().deleteText(d.index, d.index + d[0].length - 1).insertText(d.index, newDate);
      return;
    }
    const line = AGENDA_LINES.find(([l]) => s.trim().startsWith(l));
    if (line) setAfterLabel_(p.editAsText(), line[0], line[1](m));
  });
}

function fillTable_(table, m) {
  for (let r = 0; r < table.getNumRows(); r++) {
    const row = table.getRow(r);
    for (let c = 0; c < row.getNumCells(); c++) {
      const cell = row.getCell(c);
      const s = cell.getText().trim();
      const found = AGENDA_CELLS.find(([l]) => s.startsWith(l));
      if (!found) continue;
      const [label, get, keepIfEmpty] = found;
      const v = get(m);
      if (!v && keepIfEmpty) continue;
      if (s === label && c + 1 < row.getNumCells()) row.getCell(c + 1).setText(v); // '감리:' | 값  (칸이 나뉜 경우)
      else setAfterLabel_(cell.editAsText(), label, v);                             // '지휘: 값' (한 칸인 경우)
    }
  }
}

/** '개회기도: 옛값' → '개회기도: 새값' (이름표 부분의 글꼴은 그대로) */
function setAfterLabel_(textEl, label, value) {
  const s = textEl.getText();
  const end = s.indexOf(label) + label.length;
  if (s.length > end) textEl.deleteText(end, s.length - 1);
  if (value) textEl.appendText(' ' + value);
}
