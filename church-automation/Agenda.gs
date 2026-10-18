/**
 * ③ 월요일: 이번 주 주일 성찬식 아젠다 만들기 — '아젠다 방식' 설정에 따라 두 가지
 *
 * [새 문서]  템플릿 문서(예: 「녹번와드 성찬식 아젠다 (9/6)」)를 통째로 복사 → 이름표 뒤 값만 바꿔 씀.
 *            굵은 이름표·빈 줄·제목 모양이 템플릿 그대로 유지됨. 문서 이름의 (9/6) 은 (10/25) 처럼 바뀜.
 * [공용 문서] 「성찬식 아젠다」 맨 위의 지난주 칸을 복사해 그 위에 끼워 넣음.
 *
 * 같은 주 문서(칸)가 이미 있으면 새로 만들지 않고 순서 값만 시트에 맞춤 (광고 등 손으로 쓴 내용은 그대로).
 */
// [이름표, 값] — 이름표로 시작하는 줄/표 칸을 찾아 뒤쪽 값을 바꿈
const AGENDA_LINES = [
  ['감리:', m => m.presiding],
  ['지휘:', m => person_(m.chorister)],
  ['사회:', m => person_(m.conducting)],
  ['반주:', m => person_(m.organist)],
  ['개회찬송:', m => m.hymns.openingHymn],
  ['개회기도:', m => person_(m.openingPrayer)],
  ['성찬찬송:', m => m.hymns.sacramentHymn],
  ['말씀:', m => m.speakers.map(person_).join(', ')],
  ['회중찬송:', m => m.hymns.restHymn],
  ['마지막 연사 말씀:', m => person_(m.lastSpeaker)],
  ['마지막 말씀:', m => person_(m.lastSpeaker)],
  ['폐회찬송:', m => m.hymns.closingHymn],
  ['폐회기도:', m => person_(m.closingPrayer)],
];
const KEEP_IF_EMPTY = ['감리:'];  // 시트에 값이 없으면 기존 값(템플릿/지난주) 유지
const MANUAL_LINES = ['행사:', '광고:', '스테이크 행사:', '와드 행사:']; // 새 문서에서는 비워 둠 → 사람이 채움
const AGENDA_SECTIONS = ['광고', '스테이크 행사', '와드 행사'];
const SECTION_RE = /^\d{1,2}\.\d{1,2}\s.*성찬식/; // 공용 문서의 주 제목. 예: '10.18 녹번와드 성찬식'
const SEPARATOR_RE = /^-{3,}$/;
const DATE_IN_TITLE_RE = /\(\d{1,2}\/\d{1,2}\)/;   // 새 문서 제목의 '(9/6)'

function person_(raw) {
  return getSetting_('아젠다 호칭') === '예' ? withTitle_(raw) : String(raw || '');
}

function updateAgenda() {
  const target = upcomingSunday_(new Date());
  const label = fmt_(target, 'M/d');
  const m = getMeeting_(target);
  if (!m) return notify_({ subject: `[확인 필요] ${label} 아젠다 생략`, text: `원본 시트에서 ${label} 줄을 찾지 못했습니다.` });
  if (m.special) return log_('아젠다 생략', `${label} ${m.special}`);
  if ((getSetting_('아젠다 방식') || '새 문서') === '새 문서') return makeAgendaDoc_(m);

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

/** [새 문서] 템플릿을 복사해 이번 주 아젠다 문서 만들기 (이미 있으면 값만 다시 맞춤) */
function makeAgendaDoc_(m) {
  const label = fmt_(m.sunday, 'M/d');
  let template;
  try {
    template = DriveApp.getFileById(fileId_(getSetting_('아젠다 템플릿')));
  } catch (e) {
    return notify_({ subject: '[확인 필요] 아젠다 템플릿을 열 수 없음',
      text: `'설정'의 아젠다 템플릿 주소를 확인해 주세요.\n${e.message}` });
  }
  const parents = template.getParents();
  const folder = parents.hasNext() ? parents.next() : DriveApp.getRootFolder();
  const base = template.getName();
  const name = DATE_IN_TITLE_RE.test(base) ? base.replace(DATE_IN_TITLE_RE, `(${label})`) : `${base} (${label})`;

  // 같은 이름 + 최근 두 달 안에 만든 문서가 있으면 그 문서를 갱신 (작년 같은 날짜 문서와 헷갈리지 않게)
  let file = null;
  const same = folder.getFilesByName(name);
  while (same.hasNext()) {
    const f = same.next();
    if (!f.isTrashed() && f.getDateCreated() > addDays_(m.sunday, -60)) { file = f; break; }
  }
  const isNew = !file;
  if (isNew) file = template.makeCopy(name, folder);

  const doc = DocumentApp.openById(file.getId());
  const body = doc.getBody();
  body.getParagraphs().forEach(p => {
    const s = p.getText();
    if (DATE_IN_TITLE_RE.test(s)) {                       // 제목 '녹번와드 성찬식 (9/6)' → (10/25)
      const d = s.match(DATE_IN_TITLE_RE);
      p.editAsText().deleteText(d.index, d.index + d[0].length - 1).insertText(d.index, `(${label})`);
      return;
    }
    if (fillLine_(p, m)) return;
    const manual = MANUAL_LINES.find(l => s.trim().startsWith(l));
    if (manual && isNew) setAfterLabel_(p.editAsText(), manual, '');
  });
  body.getTables().forEach(t => fillTable_(t, m));
  doc.saveAndClose();

  notify_({
    subject: `[아젠다] ${label} 성찬식 ${isNew ? '문서 만듦' : '순서 다시 맞춤'}`,
    text: lines_(
      isNew ? `📝 「${name}」 문서를 만들었습니다.` : `🔄 「${name}」의 순서 칸을 시트 값으로 다시 맞췄습니다.`,
      isNew ? '• 감리 · 행사 · 광고는 직접 채워 주세요.' : '• 광고 · 행사 등 손으로 쓴 내용은 그대로입니다.'),
    link: doc.getUrl(),
  });
}

/** '개회기도:' 처럼 이름표로 시작하는 줄이면 값을 채우고 true */
function fillLine_(p, m) {
  const s = p.getText().trim();
  const line = AGENDA_LINES.find(([l]) => s.startsWith(l));
  if (!line) return false;
  const v = line[1](m);
  if (!v && KEEP_IF_EMPTY.includes(line[0])) return true;
  setAfterLabel_(p.editAsText(), line[0], v);
  return true;
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
    fillLine_(p, m);
  });
}

function fillTable_(table, m) {
  for (let r = 0; r < table.getNumRows(); r++) {
    const row = table.getRow(r);
    for (let c = 0; c < row.getNumCells(); c++) {
      const cell = row.getCell(c);
      const s = cell.getText().trim();
      const found = AGENDA_LINES.find(([l]) => s.startsWith(l));
      if (!found) continue;
      const [label, get] = found;
      const v = get(m);
      if (!v && KEEP_IF_EMPTY.includes(label)) continue;
      if (s === label && c + 1 < row.getNumCells()) row.getCell(c + 1).setText(v); // '감리:' | 값  (칸이 나뉜 경우)
      else setAfterLabel_(cell.editAsText(), label, v);                             // '지휘: 값' (한 칸인 경우)
    }
  }
}

/** '개회기도: 옛값' → '개회기도: 새값' (굵은 이름표는 그대로, 값은 보통 글씨) */
function setAfterLabel_(textEl, label, value) {
  const s = textEl.getText();
  const end = s.indexOf(label) + label.length;
  if (s.length > end) textEl.deleteText(end, s.length - 1);
  if (!value) return;
  textEl.appendText(' ' + value);
  const len = textEl.getText().length;
  textEl.setBold(len - value.length, len - 1, false);
}
