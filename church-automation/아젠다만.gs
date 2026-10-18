/**
 * 성찬식 아젠다 자동 생성 (아젠다 기능만)
 * 매주 월요일 9시, 감독단 시트의 성찬식 순서표를 읽어
 * 「성찬식 아젠다」 문서 맨 위에 이번 주 칸을 추가합니다.
 *
 * 처음 한 번: 아래 주소 2개 입력 → 저장 → 함수 'installTrigger' 실행 → 권한 허용
 * 바로 만들어 보기: 함수 'updateAgenda' 실행
 */
const SOURCE_URL = '여기에 감독단 시트 주소';
const AGENDA_URL = '여기에 성찬식 아젠다 문서 주소';

const SCHEDULE_TAB = '{년}년 성찬식';     // {년} → 2026, 2027 …
const HYMN_FORMAT = '{번호}장 {제목}';
const USE_TITLES = true;                  // 이름 뒤 형제님/자매님
const ROSTERS = [
  { tab: '장로정원회', title: '형제님' },
  { tab: '상호부조회', title: '자매님' },
  { tab: '청년독신성인', genderCol: '성별' },
];

// [이름표, 값] — 아젠다에서 이 이름표로 시작하는 줄·표 칸의 값을 바꿈
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
const KEEP_IF_EMPTY = ['감리:'];                      // 시트에 없으면 지난주 값 유지
const AGENDA_SECTIONS = ['광고', '스테이크 행사', '와드 행사'];
const SECTION_RE = /^\d{1,2}\.\d{1,2}\s.*성찬식/;     // '10.18 녹번와드 성찬식'
const SEPARATOR_RE = /^-{3,}$/;

// ───────── 실행 함수 ─────────

/** 처음 한 번 실행: 매주 월요일 9시 자동 실행 예약 */
function installTrigger() {
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'updateAgenda')
    .forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('updateAgenda').timeBased()
    .onWeekDay(ScriptApp.WeekDay.MONDAY).atHour(9).create();
  console.log('예약 완료: 매주 월요일 9시');
}

/** 테스트용: 다음 주일 아젠다를 지금 바로 만들기 (일요일에 실행하면 7일 뒤 주일) */
function testNextSunday() {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  updateAgenda(d);
}

/** 이번 주 주일 아젠다 추가 (이미 있으면 순서 값만 다시 맞춤) */
function updateAgenda(base) {
  // 자동 실행 때는 날짜가 아닌 '실행 정보'가 들어오므로, 날짜일 때만 기준일로 사용
  const sunday = upcomingSunday_(base instanceof Date ? base : new Date());
  const label = fmt_(sunday, 'M/d');
  const m = getMeeting_(sunday);
  if (!m) return report_(`[확인 필요] ${label} 아젠다 생략`, `감독단 시트에서 ${label} 줄을 찾지 못했습니다.`);
  if (m.special) return console.log(`${label} ${m.special} — 아젠다 생략`);

  const doc = DocumentApp.openById(fileId_(AGENDA_URL));
  const result = insertSection_(doc.getBody(), m);
  doc.saveAndClose();
  report_(`[아젠다] ${label} 성찬식 ${result === 'added' ? '추가' : '다시 맞춤'}`,
    result === 'added'
      ? `${label} 칸을 문서 맨 위에 추가했습니다.\n감리(지난주 값 유지)·광고·행사를 확인해 주세요.`
      : `${label} 칸의 순서 값을 시트에 맞췄습니다. (광고 등은 그대로)`,
    doc.getUrl());
}

function report_(subject, text, link) {
  console.log(subject + '\n' + text);
  MailApp.sendEmail(Session.getEffectiveUser().getEmail(), subject, text + (link ? '\n\n' + link : ''));
}

// ───────── 아젠다 문서 ─────────

function insertSection_(body, m) {
  const P = DocumentApp.ElementType.PARAGRAPH;
  const T = DocumentApp.ElementType.TABLE;
  const text = el => (el.getType() === P ? el.asParagraph().getText().trim() : '');
  const n = body.getNumChildren();

  let start = -1;
  for (let i = 0; i < n; i++) if (SECTION_RE.test(text(body.getChild(i)))) { start = i; break; }
  if (start < 0) throw new Error("아젠다 문서에서 'MM.DD … 성찬식' 제목을 찾지 못했습니다.");

  if (text(body.getChild(start)).startsWith(fmt_(m.sunday, 'MM.dd'))) {
    fillSection_(collectSection_(body, start), m);
    return 'updated';
  }

  // 복사할 칸: '회중찬송:'·'마지막 … 말씀:' 줄까지 다 있는 가장 최근 칸 (금식간증 칸은 줄이 빠져 있음)
  const complete = sec => {
    const lines = sec.map(text);
    return lines.some(s => s.startsWith('회중찬송:')) && lines.some(s => /^마지막.*말씀:/.test(s));
  };
  let section = collectSection_(body, start);
  for (let i = start + 1, seen = 0; i < n && seen < 6 && !complete(section); i++) {
    if (SECTION_RE.test(text(body.getChild(i)))) {
      seen++;
      const candidate = collectSection_(body, i);
      if (complete(candidate)) section = candidate;
    }
  }

  // 맨 위에 복사 (광고 목록·메모 줄은 빼고)
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

function fillSection_(elements, m) {
  const newDate = fmt_(m.sunday, 'MM.dd');
  elements.forEach(el => {
    if (el.getType() === DocumentApp.ElementType.TABLE) return fillTable_(el, m);
    if (el.getType() !== DocumentApp.ElementType.PARAGRAPH) return;
    const p = el.asParagraph();
    const s = p.getText();
    if (SECTION_RE.test(s.trim())) {
      const d = s.match(/\d{1,2}\.\d{1,2}/);
      p.editAsText().deleteText(d.index, d.index + d[0].length - 1).insertText(d.index, newDate);
      return;
    }
    const line = AGENDA_LINES.find(([l]) => s.trim().startsWith(l));
    if (!line) return;
    const v = line[1](m);
    if (!v && KEEP_IF_EMPTY.includes(line[0])) return;
    setAfterLabel_(p.editAsText(), line[0], v);
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
      const v = found[1](m);
      if (!v && KEEP_IF_EMPTY.includes(found[0])) continue;
      if (s === found[0] && c + 1 < row.getNumCells()) row.getCell(c + 1).setText(v); // '감리:' | 값
      else setAfterLabel_(cell.editAsText(), found[0], v);                             // '지휘: 값'
    }
  }
}

function setAfterLabel_(textEl, label, value) {
  const s = textEl.getText();
  const end = s.indexOf(label) + label.length;
  if (s.length > end) textEl.deleteText(end, s.length - 1);
  if (!value) return;
  textEl.appendText(' ' + value);
  const len = textEl.getText().length;
  textEl.setBold(len - value.length, len - 1, false);
}

// ───────── 감독단 시트 읽기 (읽기만 함) ─────────

let SOURCE_ = null;
let ROSTER_ = null;

function source_() {
  return SOURCE_ || (SOURCE_ = SpreadsheetApp.openById(fileId_(SOURCE_URL)));
}

function getMeeting_(sunday) {
  const tab = source_().getSheetByName(SCHEDULE_TAB.replace('{년}', sunday.getFullYear()));
  if (!tab) return null;
  const md = fmt_(sunday, 'MM-dd');
  const row = readTable_(tab).find(r => r.md === md);
  if (!row) return null;

  const one = h => row.get(h)[0] || '';
  const hymn = h => hymnText_(row.get(h));
  const m = {
    sunday: sunday,
    presiding: one('감리'), conducting: one('사회'), chorister: one('지휘'), organist: one('반주'),
    talk5: one('5분 말씀'), talk10: one('10분 말씀'), lastSpeaker: one('마지막 연사'),
    openingPrayer: one('개회기도'), closingPrayer: one('폐회기도'),
    hymns: { openingHymn: hymn('개회찬송'), sacramentHymn: hymn('성찬찬송'), restHymn: hymn('회중찬송'), closingHymn: hymn('폐회찬송') },
  };
  m.special = /대회/.test(m.conducting) ? m.conducting : '';   // 연차대회 · 스테이크 대회 주
  if (/간증/.test(m.talk5)) m.talk10 = m.lastSpeaker = '';      // 금식간증 주
  m.speakers = unique_([m.talk5, m.talk10].filter(Boolean));
  return m;
}

/** 병합 칸 펼치기 → 제목 행 찾기 → 제목별 열 묶기 (찬송 번호·제목 두 칸은 한 묶음) */
function readTable_(sheet) {
  const range = sheet.getDataRange();
  const values = range.getValues();
  range.getMergedRanges().forEach(mr => {
    const v = mr.getValue();
    for (let r = mr.getRow(); r <= mr.getLastRow(); r++)
      for (let c = mr.getColumn(); c <= mr.getLastColumn(); c++)
        if (values[r - 1] && c - 1 < values[r - 1].length) values[r - 1][c - 1] = v;
  });
  const hr = values.findIndex((row, i) => i < 5 && row.some(v => String(v).trim() === '날짜'));
  if (hr < 0) return [];
  const dateCol = values[hr].findIndex(v => String(v).trim() === '날짜');
  const groups = {};
  let prev = '';
  values[hr].forEach((h, c) => {
    if (c === dateCol) { prev = ''; return; }
    h = String(h).trim();
    if (h && h !== prev) { (groups[h] = groups[h] || []).push(c); prev = h; }
    else if (prev) groups[prev].push(c);
  });
  return values.slice(hr + 1).map(row => ({
    md: monthDay_(row[dateCol]),
    get: h => (groups[h] ? unique_(groups[h].map(c => String(row[c]).trim()).filter(v => v && !v.startsWith('#'))) : []),
  })).filter(r => r.md);
}

function hymnText_(parts) {
  const [num, title] = parts;
  if (!num) return '';
  if (!/^\d+$/.test(num)) return parts.join(' ');
  if (!title) return `${num}장`;
  return HYMN_FORMAT.split('{번호}').join(num).split('{제목}').join(title);
}

function person_(raw) {
  raw = String(raw || '');
  if (!USE_TITLES) return raw;
  return raw.split('/').map(s => s.trim()).filter(Boolean)
    .map(s => (roster_()[s] && !s.endsWith('님') ? `${s} ${roster_()[s]}` : s)).join(' / ');
}

function roster_() {
  if (ROSTER_) return ROSTER_;
  ROSTER_ = {};
  ROSTERS.forEach(cfg => {
    const sheet = source_().getSheetByName(cfg.tab);
    if (!sheet) return;
    const values = sheet.getDataRange().getValues();
    const hr = values.findIndex((row, i) => i < 5 && row.some(v => String(v).trim() === '이름'));
    if (hr < 0) return;
    const nameCol = values[hr].findIndex(v => String(v).trim() === '이름');
    const genderCol = cfg.genderCol ? values[hr].findIndex(v => String(v).trim() === cfg.genderCol) : -1;
    values.slice(hr + 1).forEach(row => {
      const name = String(row[nameCol]).trim();
      const title = cfg.title || { 남: '형제님', 여: '자매님' }[String(row[genderCol]).trim()];
      if (name && title && !ROSTER_[name]) ROSTER_[name] = title;
    });
  });
  return ROSTER_;
}

// ───────── 도우미 ─────────

function fileId_(url) {
  const m = String(url).match(/\/d\/([\w-]+)/);
  return m ? m[1] : String(url).trim();
}

function fmt_(date, pattern) {
  return Utilities.formatDate(date, 'Asia/Seoul', pattern);
}

function upcomingSunday_(base) {
  const d = new Date(base);
  d.setDate(d.getDate() + (7 - d.getDay()) % 7);
  return d;
}

function monthDay_(v) {
  if (v instanceof Date) return fmt_(v, 'MM-dd');
  const m = String(v).match(/^\s*(\d{1,2})\s*[/.\-월]\s*(\d{1,2})/);
  return m ? `${m[1].padStart(2, '0')}-${m[2].padStart(2, '0')}` : '';
}

function unique_(arr) {
  return arr.filter((v, i) => arr.indexOf(v) === i);
}
