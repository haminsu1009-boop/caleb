/**
 * 녹번와드 성찬식 자동화 — 이 파일 하나를 Code.gs 에 통째로 붙여넣으세요.
 *
 * 실행 메뉴에 보이는 함수
 *  · 자동실행설치        처음 한 번: 매주 월 9시 아젠다 / 월 10시 말씀 안내 / 매달 25일 반주표 예약
 *  · 이번주아젠다만들기   「성찬식 아젠다」 문서 맨 위에 이번 주 칸 추가 (이미 있으면 값만 다시 맞춤)
 *  · 다음주아젠다만들기 · 다다음주아젠다만들기   미리 만들어 보기
 *  · 말씀안내보내기       4주 뒤 주제 안내 + 이번 주 리마인드 → 메일 + 내 카톡
 *  · 반주표보내기         다음 달 지휘·반주·찬송표 이미지 → 메일
 *  · 내년순서표만들기     감독단 시트에 내년 순서표 초안 탭
 *  · 카톡로그인주소 → 카톡연결   카카오톡 '나에게 보내기' 연결 (처음 한 번)
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
  ['지휘:', m => person_(m.chorister, '자매님')],   // 명단에 없으면 '자매님'
  ['사회:', m => person_(m.conducting)],
  ['반주:', m => person_(m.organist, '자매님')],
  ['개회찬송:', m => m.hymns.openingHymn],
  ['개회기도:', m => person_(m.openingPrayer)],
  ['성찬찬송:', m => m.hymns.sacramentHymn],
  ['말씀:', m => m.speakers.map(s => person_(s)).join(', ')],
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
const FAST_REMOVE_RE = /^(회중찬송:|마지막.*말씀:)/;     // 금식간증 주에 빼는 줄

// ───────── 실행 함수 ─────────

/** 처음 한 번 실행: 자동 실행 예약 전부 (예전 예약은 지우고 새로 만듦) */
function 자동실행설치() {
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('이번주아젠다만들기').timeBased().onWeekDay(ScriptApp.WeekDay.MONDAY).atHour(9).create();
  ScriptApp.newTrigger('말씀안내보내기').timeBased().onWeekDay(ScriptApp.WeekDay.MONDAY).atHour(10).create();
  ScriptApp.newTrigger('반주표보내기').timeBased().onMonthDay(25).atHour(9).create();
  console.log('예약 완료\n· 매주 월 9시: 이번주아젠다만들기\n· 매주 월 10시: 말씀안내보내기 (메일 + 카톡)\n· 매달 25일 9시: 반주표보내기');
}

/** 테스트용: 다음 주일 아젠다를 지금 바로 만들기 (일요일에 실행하면 7일 뒤 주일) */
function 다음주아젠다만들기() {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  이번주아젠다만들기(d);
}

/** 테스트용: 다다음 주일 아젠다 만들기 (미리 만들어 둬도 그 주 월요일에 값만 다시 맞춤) */
function 다다음주아젠다만들기() {
  const d = new Date();
  d.setDate(d.getDate() + 8);
  이번주아젠다만들기(d);
}

/** 이번 주 주일 아젠다 추가 (이미 있으면 순서 값만 다시 맞춤) */
function 이번주아젠다만들기(base) {
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

  // 같은 날짜 칸이 위쪽 몇 주 안에 이미 있으면 (미리 만들어 둔 경우 포함) 그 칸의 값만 다시 맞춤
  for (let i = start, seen = 0; i < n && seen < 6; i++) {
    const s = text(body.getChild(i));
    if (!SECTION_RE.test(s)) continue;
    seen++;
    if (s.startsWith(fmt_(m.sunday, 'MM.dd'))) {
      const existing = collectSection_(body, i);
      fillSection_(existing, m);
      ensureBullets_(body, existing, existing);
      return 'updated';
    }
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
    if (el.getType() === T || (el.getType() === P && keep(text(el)))) inserted.push(insertCopy_(body, at++, el));
  });
  fillSection_(inserted, m);
  ensureBullets_(body, inserted, section);
  return 'added';
}

/** '광고' · '스테이크 행사' · '와드 행사' 바로 아래에 빈 글머리 기호(-)가 없으면 한 줄 넣기
 *  본보기: source 칸의 '같은 이름표 바로 아래 글머리 줄' → 없으면 광고 글머리를 복사해 EXTRA_INDENT 만큼 더 들여씀 */
const EXTRA_INDENT = { '광고': 0, '스테이크 행사': 36, '와드 행사': 36 }; // pt (36pt = 한 단계)

function ensureBullets_(body, section, source) {
  const P = DocumentApp.ElementType.PARAGRAPH;
  const LI = DocumentApp.ElementType.LIST_ITEM;
  const labelOf = el => (el.getType() === P ? el.asParagraph().getText().trim() : '');
  const nextOf = el => {
    const i = body.getChildIndex(el);
    return i + 1 < body.getNumChildren() ? body.getChild(i + 1) : null;
  };

  const templates = {};
  let base = null;
  source.forEach(el => {
    const label = labelOf(el);
    const next = AGENDA_SECTIONS.includes(label) && nextOf(el);
    if (next && next.getType() === LI) {
      templates[label] = next.asListItem();
      if (!base) base = templates[label];
    }
  });
  for (let i = 0; i < Math.min(body.getNumChildren(), 400) && !base; i++) {
    if (body.getChild(i).getType() === LI) base = body.getChild(i).asListItem();
  }

  section.forEach(el => {
    const label = labelOf(el);
    if (!AGENDA_SECTIONS.includes(label)) return;
    const next = nextOf(el);
    if (next && next.getType() === LI) return; // 이미 있음
    const t = templates[label] || base;
    const at = body.getChildIndex(el) + 1;
    const li = t ? insertCopy_(body, at, t) : body.insertListItem(at, ' ');
    li.setText(' '); // 완전히 빈 글자('')는 Google 문서가 거부 → 공백 한 칸
    const extra = !templates[label] && t ? EXTRA_INDENT[label] || 0 : 0;
    if (!extra) return;
    const s = t.getIndentStart(), f = t.getIndentFirstLine();
    if (s === null && f === null) return li.setNestingLevel(t.getNestingLevel() + 1);
    if (s !== null) li.setIndentStart(s + extra);
    if (f !== null) li.setIndentFirstLine(f + extra);
  });
}

/** 복사한 줄 끼워 넣기 — Google 문서는 내용이 완전히 빈 줄의 복사본을 거부하므로,
 *  거부되면 공백 한 칸을 넣어서 다시 시도 */
function insertCopy_(body, at, el) {
  const T = DocumentApp.ElementType.TABLE;
  const LI = DocumentApp.ElementType.LIST_ITEM;
  const type = el.getType();
  const copy = type === T ? el.asTable().copy() : type === LI ? el.asListItem().copy() : el.asParagraph().copy();
  const insert = c => (type === T ? body.insertTable(at, c) : type === LI ? body.insertListItem(at, c) : body.insertParagraph(at, c));
  try {
    return insert(copy);
  } catch (e) {
    if (type === T) throw e;
    copy.setText(' ');
    return insert(copy);
  }
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
    if (m.fast && FAST_REMOVE_RE.test(s.trim())) return p.removeFromParent(); // 금식간증 주엔 줄 자체를 뺌
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
  // 금식간증 주: 매달 첫째 주일(1~7일) 또는 시트에 '간증'이라고 적힌 주 → 말씀 순서 없음
  m.fast = !m.special && (/간증/.test(m.talk5) || sunday.getDate() <= 7);
  if (m.fast) {
    m.talk5 = '금식간증';
    m.talk10 = m.lastSpeaker = '';
  }
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

/** 이름 뒤 호칭: 명단(장로정원회·상호부조회…)에서 찾고, 없으면 fallback 사용 */
function person_(raw, fallback) {
  raw = String(raw || '');
  if (!USE_TITLES) return raw;
  return raw.split('/').map(s => s.trim()).filter(Boolean).map(s => {
    if (s.endsWith('님')) return s;
    const title = roster_()[s] || fallback;
    return title ? `${s} ${title}` : s;
  }).join(' / ');
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

// ═══════════════ 말씀·기도 안내 문구 ═══════════════

const CONFERENCE_URL = 'https://www.churchofjesuschrist.org/study/general-conference/2026/10?lang=kor';

const SENDER_NAME = '녹번와드 하민수 형제';
const WARD_NAME = '녹번와드';

// [말씀 주제, 참고 연차대회 말씀 연사, 말씀 제목(영어 원제), 링크]
// 링크를 비워 두면 교회 사이트에서 그 말씀을 검색하는 링크가 들어갑니다.
// 복음자료실 앱 → 그 말씀 → 공유 → 링크 복사 → 마지막 '' 안에 붙여넣으면 그 링크가 우선입니다.
const TOPICS = [
  ['성신과 함께 하기 위해서 어떻게 하고 있는지', '매튜 J. 아이어링 장로', 'Comfort From the Holy Ghost', ''],
  ['주님의 집인 성전을 통해 어떻게 주님께 더 가까이 나아가고 있는지', '게리 W. 공 장로', 'Come to the Lord in His Holy House', ''],
  ['나의 간증을 어떻게 얻었고, 어떻게 키워 가고 있는지', '제라드 코세 장로', 'The Gift of Testimony', ''],
  ['살아 있는 선지자의 권고를 따르며 받은 축복', '바이앙기나 시카헤마 장로', 'Prophets, Seers and Revelators', ''],
  ['예수 그리스도께서 나를 건져 주신 경험', '케빈 J. 해서웨이 장로', 'Jesus Christ Is the Great Deliverer', ''],
  ['금식을 통해 받은 축복과 더 거룩한 금식을 하는 방법', '울리세스 소아레스 장로', 'A Higher and Holier Fast', ''],
  ['복음을 나누기 위해 내가 할 수 있는 일', '션 더글러스 감독', 'The Hour of Your Mission Is Come', ''],
  ['주님의 권고에 지혜롭게 순종하며 받은 축복', 'D. 토드 크리스토퍼슨 회장', 'O Be Wise', ''],
  ['하나님의 약속을 믿고 의지했던 경험', '데일 G. 렌런드 장로', 'How Long Will It Be Ere They Believe Me', ''],
  ['십일조와 헌금을 통해 주님을 신뢰하게 된 경험', '파트리시오 M. 주프라 장로', 'Trusting the Lord Through Tithes and Offerings', ''],
  ['성약을 지키며 경험한 하나님의 권능', '제레마이아 J. 모건 장로', 'The Infinite Power of God in Our Covenants', ''],
  ['내가 하나님의 자녀임을 어떻게 느끼고 있는지', '허치 U. 팔레 장로', 'I Am a Child of God', ''],
  ['어려울 때 예수님께서 나를 일으켜 주신 경험', '패트릭 키어런 장로', 'Jesus Lives to Lift', ''],
  ['예수님처럼 사랑하기 위해 노력하고 있는 것', '로널드 A. 래스번드 장로', 'Love Like Jesus', ''],
  ['두려움 속에서 주님께서 함께하심을 느낀 경험', '헨리 B. 아이어링 회장', 'Fear Not, I Am With Thee', ''],
  ['예수 그리스도를 믿는 신앙으로 용기를 낸 경험', '닐 L. 앤더슨 장로', 'Courage Born of Our Faith in Jesus Christ', ''],
  ['그리스도의 이름을 받들어 살아가기 위해 하고 있는 일', '제임스 G. O. 판톤 장로', 'Take Upon Us His Name', ''],
  ['매일 그리스도께 나아가기 위해 하고 있는 일', '에드워드 두베 장로', 'Come Unto Christ', ''],
  ['정직과 덕을 지키며 얻은 행복', '쿠엔틴 L. 쿡 장로', 'Integrity and Virtue Lead to Happiness', ''],
  ['가정과 와드에서 화평케 하는 자가 되는 방법', '알프레드 쿵구 장로', 'Using the Language of Peacemakers', ''],
  ['나의 생활을 돌아보고 변화하며 받은 축복', '시루 슈마일 장로', 'Consider Your Ways, and From This Day Will I Bless You', ''],
  ['복음이 모든 사람을 위한 것임을 느낀 경험', '댈린 H. 옥스 회장', 'The Gospel of Jesus Christ Is For All', ''],
  ['그리스도를 중심으로 하나 되기 위해 할 수 있는 일', '디이터 F. 우흐트도르프 회장', 'Christ-centered Unity', ''],
  ['하나님께서 내 곁에 계심을 느낀 경험', '안드레아 무뇨스 스파나우스 자매', 'God Is at Your Side', ''],
];

// [역할 키, 몇 번째 순서, 몇 분 말씀] — 기도는 순서·시간 없이 이름만
const NOTICE_ORDER = [
  ['talk5', '첫번째', '5분', '5분 말씀'],
  ['talk10', '두번째', '10분', '10분 말씀'],
  ['lastSpeaker', '세번째', '15분', '마지막 말씀'],   // 마지막 연사 시간이 다르면 '15분'만 고치세요
  ['openingPrayer', '', '', '개회기도'],
  ['closingPrayer', '', '', '폐회기도'],
];

const GUIDE_TEXT =
  '구약, 신약, 몰몬경, 교리와 성약, 값진 진주, 리아호나, 연차대회 말씀 등을 참고하셔서 준비할 수 있습니다. '
  + '가능하다면 직접 겪으신 경험을 나눠주시면 감사하겠으며, 설득이나 권유보다는 예수 그리스도가 중심이 되는 간증을 전해주시면 감사하겠습니다.\n\n'
  + '영감에 따라서 말씀 주제는 얼마든지 변경 가능하며 다른 분들도 준비해온 말씀을 할 수 있도록 꼭 주어진 시간을 준수해주시면 감사하겠습니다.';

/** kind: 'notice' = 4주 전 부탁(주제·링크) / 'remind' = 그 주 리마인드(짧게) */
function noticeMessages_(sunday, kind) {
  const m = getMeeting_(sunday);
  if (!m || m.special) return [];
  const date = fmt_(sunday, 'M월 d일');
  const week = Math.floor((sunday - new Date(2026, 0, 4)) / (7 * 86400000));
  let n = 0; // 같은 주 말씀하시는 분들은 서로 다른 주제로

  return NOTICE_ORDER
    .filter(([k]) => m[k] && !NOT_PERSON_RE.test(m[k]))
    .map(([k, nth, min, role]) => {
      const name = person_(m[k], '');
      const isTalk = !!nth;

      if (kind === 'remind') {
        return `${name}, 안녕하세요, ${SENDER_NAME}입니다.\n`
          + (isTalk
            ? `${date} ${WARD_NAME} ${nth} 순서로 ${min} 말씀이십니다. 감사합니다.`
            : `${date} ${WARD_NAME} 성찬식 ${role}${josa_(role, '이십니다', '십니다')}. 감사합니다.`);
      }

      if (!isTalk) {
        return `${name}, 안녕하세요. ${SENDER_NAME}입니다.\n`
          + `${date} ${WARD_NAME} 성찬식 ${role}${josa_(role, '을', '를')} 부탁드립니다. 감사합니다.`;
      }
      const [topic, speaker, title, link] = topicFor_(sunday, week * 3 + n++);
      return `${name}, 안녕하세요. ${SENDER_NAME}입니다.\n`
        + `${date} ${WARD_NAME} 성찬식 ${nth} 순서로 ${min}말씀 주제 안내드립니다.\n\n`
        + '주제는 아래와 같으며, 참고하실 연차대회 말씀 공유드립니다.\n\n'
        + `'${topic}'\n`
        + (speaker ? `(참고: ${speaker} 말씀)\n` : '')
        + `${link || talkSearchUrl_(title)}\n\n`
        + GUIDE_TEXT;
    });
}

/** 시트에 '말씀 주제' 열이 있으면 그 값, 없으면 TOPICS 를 돌아가며 */
function topicFor_(sunday, i) {
  const tab = source_().getSheetByName(SCHEDULE_TAB.replace('{년}', sunday.getFullYear()));
  const row = tab && readTable_(tab).find(r => r.md === fmt_(sunday, 'MM-dd'));
  const own = row && (row.get('말씀 주제')[0] || row.get('주제')[0]);
  if (own) return [own, '', '', conferenceUrl_()];
  return TOPICS[((i % TOPICS.length) + TOPICS.length) % TOPICS.length];
}

/** 교회 사이트에서 그 말씀(영어 원제)을 찾는 검색 링크 */
function talkSearchUrl_(title) {
  return title
    ? `https://www.churchofjesuschrist.org/search?lang=kor&query=${encodeURIComponent('"' + title + '"')}`
    : conferenceUrl_();
}

// ═══════════════ 카카오톡 '나에게 보내기' ═══════════════
// 월요일 안내를 메일 + 내 카톡(나와의 채팅)으로 사람마다 한 통씩 → 길게 눌러 [전달]
//
// 준비 (한 번만)
//  1) https://developers.kakao.com 로그인 → 내 애플리케이션 → 애플리케이션 추가 (이름: 녹번와드 안내)
//  2) 앱 키 → 'REST API 키' 복사 → 아래 KAKAO_REST_KEY 의 '' 안에 붙여넣기
//  3) 카카오 로그인 → 활성화 ON → Redirect URI 에 https://localhost 등록
//  4) 카카오 로그인 → 동의항목 → '카카오톡 메시지 전송' → 선택 동의 → 저장
//  5) 앱 설정 → 플랫폼 → Web 플랫폼 등록 → 사이트 도메인에 https://www.churchofjesuschrist.org
//  6) 저장 후 함수 '카톡로그인주소' 실행 → 실행 로그에 나온 주소를 브라우저에서 열고 로그인·동의
//     → '사이트에 연결할 수 없음' 화면이 나오면 정상! 주소창의 code= 뒤의 값을 KAKAO_CODE 에 붙여넣고 저장
//  7) 함수 '카톡연결' 실행 → 내 카톡에 '연결 완료' 메시지가 오면 끝 (code 는 한 번만 쓰이고 10분 안에 써야 함)
const KAKAO_REST_KEY = '';
const KAKAO_CODE = '';
const KAKAO_REDIRECT = 'https://localhost';
const KAKAO_LIMIT = 200; // 카톡 '나에게 보내기' 한 통 최대 글자 수

function 카톡로그인주소() {
  if (!KAKAO_REST_KEY) throw new Error('KAKAO_REST_KEY 에 REST API 키를 먼저 넣어 주세요.');
  console.log('아래 주소를 열고 로그인·동의하세요:\nhttps://kauth.kakao.com/oauth/authorize'
    + `?client_id=${KAKAO_REST_KEY}&redirect_uri=${encodeURIComponent(KAKAO_REDIRECT)}&response_type=code&scope=talk_message`);
}

function 카톡연결() {
  const code = String(KAKAO_CODE).replace(/^.*code=/, '').replace(/&.*$/, '').trim();
  if (!code) throw new Error('KAKAO_CODE 에 code= 뒤의 값을 넣어 주세요.');
  kakaoTokenRequest_({ grant_type: 'authorization_code', redirect_uri: KAKAO_REDIRECT, code: code });
  kakaoSend_('✅ 녹번와드 안내 자동화와 카카오톡이 연결되었습니다.', conferenceUrl_(), '연차대회 보기');
  console.log('연결 완료! 내 카톡을 확인하세요.');
}

function kakaoReady_() {
  return !!PropertiesService.getScriptProperties().getProperty('KAKAO_REFRESH_TOKEN');
}

function kakaoTokenRequest_(payload) {
  const props = PropertiesService.getScriptProperties();
  payload.client_id = KAKAO_REST_KEY;
  const res = UrlFetchApp.fetch('https://kauth.kakao.com/oauth/token', { method: 'post', payload: payload, muteHttpExceptions: true });
  if (res.getResponseCode() !== 200) throw new Error('카카오 토큰 오류: ' + res.getContentText());
  const data = JSON.parse(res.getContentText());
  props.setProperty('KAKAO_ACCESS_TOKEN', data.access_token);
  props.setProperty('KAKAO_ACCESS_EXPIRES', String(Date.now() + (data.expires_in - 60) * 1000));
  if (data.refresh_token) props.setProperty('KAKAO_REFRESH_TOKEN', data.refresh_token); // 만료가 가까우면 새로 내려옴
}

/** 액세스 토큰은 몇 시간마다 만료 → 리프레시 토큰으로 자동 재발급 (매주 쓰면 계속 유지됨) */
function kakaoAccessToken_() {
  const props = PropertiesService.getScriptProperties();
  if (Date.now() > Number(props.getProperty('KAKAO_ACCESS_EXPIRES') || 0)) {
    kakaoTokenRequest_({ grant_type: 'refresh_token', refresh_token: props.getProperty('KAKAO_REFRESH_TOKEN') });
  }
  return props.getProperty('KAKAO_ACCESS_TOKEN');
}

/** 내 카톡으로 한 통 (200자 넘으면 줄 단위로 나눠서) — 링크는 메시지 아래 버튼으로 */
function kakaoSend_(text, link, buttonTitle) {
  const chunks = [];
  let cur = '';
  text.split('\n').forEach(line => {
    const next = cur ? cur + '\n' + line : line;
    if (next.length > KAKAO_LIMIT && cur) { chunks.push(cur); cur = line.slice(0, KAKAO_LIMIT); }
    else cur = next.slice(0, KAKAO_LIMIT);
  });
  if (cur.trim()) chunks.push(cur);
  chunks.forEach(chunk => {
    const template = { object_type: 'text', text: chunk, link: { web_url: link, mobile_web_url: link }, button_title: buttonTitle || '자세히 보기' };
    const res = UrlFetchApp.fetch('https://kapi.kakao.com/v2/api/talk/memo/default/send', {
      method: 'post',
      headers: { Authorization: 'Bearer ' + kakaoAccessToken_() },
      payload: { template_object: JSON.stringify(template) },
      muteHttpExceptions: true,
    });
    if (res.getResponseCode() !== 200) throw new Error('카카오 전송 오류: ' + res.getContentText());
  });
}

function conferenceUrl_() {
  return typeof CONFERENCE_URL !== 'undefined' ? CONFERENCE_URL
    : 'https://www.churchofjesuschrist.org/study/general-conference/2026/10?lang=kor';
}

/** 매주 월요일 10시: 4주 뒤 주제 안내 + 이번 주 리마인드 → 메일 한 통 + 내 카톡으로 사람마다 한 통씩 */
function 말씀안내보내기(base) {
  const today = base instanceof Date ? base : new Date();
  const thisSunday = upcomingSunday_(today);
  const ahead = plusDays_(thisSunday, 7 * NOTICE_WEEKS_AHEAD);
  const notices = noticeMessages_(ahead, 'notice');
  const reminds = noticeMessages_(thisSunday, 'remind');
  if (!notices.length && !reminds.length) return console.log('보낼 안내가 없습니다.');

  // 1) 메일 (전체 모음)
  const block = (title, list) => `■ ${title}\n\n` + (list.length ? list.join('\n\n────────────\n\n') : '(보낼 분 없음)') + '\n\n';
  report_(`[말씀·기도 안내] ${fmt_(ahead, 'M/d')} 주제 안내 · ${fmt_(thisSunday, 'M/d')} 리마인드`,
    '아래 문구를 복사해서 각자 개인톡으로 보내 주세요.\n\n'
    + block(`${fmt_(ahead, 'M/d')} 주제 안내 (${NOTICE_WEEKS_AHEAD}주 전)`, notices)
    + block(`${fmt_(thisSunday, 'M/d')} 리마인드 (이번 주)`, reminds));

  // 2) 내 카톡 — 사람마다 한 통 (링크는 글에서 빼고 버튼으로)
  if (!kakaoReady_()) return console.log('카카오톡이 연결되지 않아 메일로만 보냈습니다. (카톡연결 참고)');
  kakaoSend_(`📋 이번 주 보낼 안내\n· ${fmt_(ahead, 'M/d')} 주제 안내 ${notices.length}통\n· ${fmt_(thisSunday, 'M/d')} 리마인드 ${reminds.length}통\n\n아래 메시지를 하나씩 길게 눌러 [전달] → 그분을 선택하세요.`,
    conferenceUrl_(), '연차대회 보기');
  [...notices, ...reminds].forEach(msg => {
    const url = (msg.match(/https?:\/\/\S+/) || [])[0];
    const text = msg.replace(/\n?https?:\/\/\S+/, '').replace(/링크 공유드립니다\./, '말씀을 아래 버튼으로 공유드립니다.').trim();
    kakaoSend_(text, url || conferenceUrl_(), url ? '연차대회 말씀 보기' : '확인');
    Utilities.sleep(300);
  });
  console.log(`카톡으로 ${notices.length + reminds.length + 1}통 보냈습니다.`);
}

// ═══════════════ 반주표 이미지 ═══════════════

const ORG_EMPTY = 'N/A';
const ORG_COLORS = {
  title: '#1F3A5F',      // 제목 · 날짜 · 찬송 번호
  header: '#1F3A5F',     // 머리글 배경
  headerText: '#FFFFFF',
  stripe: '#EEF3F9',     // 줄무늬
  plain: '#FFFFFF',
  text: '#222222',
  muted: '#A0AAB4',      // N/A · 부제목
};

function 반주표보내기(base) {
  const today = base instanceof Date ? base : new Date();
  const first = new Date(today.getFullYear(), today.getMonth() + 1, 1); // 다음 달 1일
  const month = first.getMonth();
  const header = ['날짜', '지휘', '반주', '개회찬송', '성찬찬송', '회중찬송', '폐회찬송'];
  const na = v => v || ORG_EMPTY;
  const rows = [];
  for (let d = upcomingSunday_(first); d.getMonth() === month; d = plusDays_(d, 7)) {
    const m = getMeeting_(d);
    const date = fmt_(d, 'MM/dd');
    if (!m || m.special) {                                 // 시트에 없거나 연차대회·스테이크 대회 주
      rows.push([date, ...header.slice(1).map(() => ORG_EMPTY)]);
      continue;
    }
    rows.push([date, na(person_(m.chorister, '자매님')), na(person_(m.organist, '자매님')),
      na(m.hymns.openingHymn), na(m.hymns.sacramentHymn), m.fast ? ORG_EMPTY : na(m.hymns.restHymn), na(m.hymns.closingHymn)]);
  }

  const title = `${month + 1}월 성찬식 지휘/반주/찬송가표`;
  const subtitle = `녹번와드 · ${first.getFullYear()}년 ${month + 1}월 · 매주 일요일`;
  const image = organistImage_(title, subtitle, header, rows);
  const text = rows.map(r => `${r[0]}  지휘 ${r[1]} · 반주 ${r[2]}\n   개회 ${r[3]} / 성찬 ${r[4]} / 회중 ${r[5]} / 폐회 ${r[6]}`).join('\n');
  MailApp.sendEmail({
    to: Session.getEffectiveUser().getEmail(),
    subject: `[반주표] ${title}`,
    body: `첨부한 이미지를 저장해서 반주자 톡방에 올려 주세요.\n\n${text}`,
    attachments: [image],
  });
  console.log(`[반주표] ${title} 메일 보냄\n${text}`);
}

/** 구글 슬라이드에 표를 그려 PNG 이미지로 내보내고, 슬라이드는 휴지통으로 */
function organistImage_(title, subtitle, header, rows) {
  const CENTER = SlidesApp.ParagraphAlignment.CENTER;
  const MIDDLE = SlidesApp.ContentAlignment.MIDDLE;
  const font = style => { try { style.setFontFamily('Noto Sans KR'); } catch (e) { /* 글꼴이 없으면 기본 글꼴 */ } return style; };

  const pres = SlidesApp.create(title);
  const slide = pres.getSlides()[0];
  slide.getPageElements().forEach(e => e.remove());
  slide.getBackground().setSolidFill(ORG_COLORS.plain);
  const W = pres.getPageWidth(), H = pres.getPageHeight(), M = 24;

  // 제목 · 부제목
  const t = slide.insertTextBox(title, M, 12, W - 2 * M, 34);
  font(t.getText().getTextStyle()).setFontSize(22).setBold(true).setForegroundColor(ORG_COLORS.title);
  const s = slide.insertTextBox(subtitle, M, 44, W - 2 * M, 18);
  font(s.getText().getTextStyle()).setFontSize(10).setForegroundColor(ORG_COLORS.muted);

  // 표 (구글 슬라이드는 열 너비를 코드로 못 바꿔서 칸 너비는 같게)
  const top = 70;
  const table = slide.insertTable(rows.length + 1, header.length, M, top, W - 2 * M, H - top - M);

  [header, ...rows].forEach((r, i) => r.forEach((v, j) => {
    const cell = table.getCell(i, j);
    const value = String(v || ORG_EMPTY);
    const hymn = i > 0 && j >= 3 && value.match(/^(\d+장)\s+(.+)$/);   // '25장 제목' → 번호 / 제목 두 줄
    const txt = cell.getText();
    txt.setText(hymn ? `${hymn[1]}\n${hymn[2]}` : value);
    const style = font(txt.getTextStyle()).setFontSize(i === 0 ? 12 : 10.5).setBold(i === 0)
      .setForegroundColor(i === 0 ? ORG_COLORS.headerText : ORG_COLORS.text);
    if (i > 0 && j === 0) style.setBold(true).setFontSize(12).setForegroundColor(ORG_COLORS.title);
    if (value === ORG_EMPTY) style.setForegroundColor(ORG_COLORS.muted);
    if (hymn) txt.getRange(0, hymn[1].length).getTextStyle().setBold(true).setFontSize(12).setForegroundColor(ORG_COLORS.title);
    txt.getParagraphStyle().setParagraphAlignment(CENTER);
    cell.setContentAlignment(MIDDLE);
    cell.getFill().setSolidFill(i === 0 ? ORG_COLORS.header : i % 2 ? ORG_COLORS.plain : ORG_COLORS.stripe);
  }));
  pres.saveAndClose();

  const url = `https://docs.google.com/presentation/d/${pres.getId()}/export/png?pageid=${slide.getObjectId()}`;
  const blob = UrlFetchApp.fetch(url, { headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() } })
    .getBlob().setName(`${title}.png`);
  DriveApp.getFileById(pres.getId()).setTrashed(true);
  return blob;
}

/** 월간 작업: 반주표 이미지 · 내년 순서표 초안 */
const SENDER = '녹번와드 감독단';
const NOTICE_WEEKS_AHEAD = 4;   // 몇 주 전에 주제 안내를 보낼지
const DRAFT_YEAR = 2027;        // 내년순서표만들기 로 만들 연도

const NOT_PERSON_RE = /간증|대회|스테이크|발표|선교사|장로님|성찬식|방문|\?/;
// ───────── ③ 1년치 순서표 초안 ─────────

/**
 * 규칙
 *  · 사회: 감독단(부름현황 탭의 감독 → 1보좌 → 2보좌) 순서대로
 *  · 지휘: 작년 첫째 주에 가장 많이 한 분 / 그 외 주에 가장 많이 한 분
 *  · 반주: 작년 마지막 분기에 가장 많이 한 두 분이 번갈아
 *  · 첫째 주: 금식간증 (말씀 없음, 회중찬송 없음)
 *  · 4·10월 둘째 주: 연차대회 시청 / 3·9월 둘째 주: 스테이크 대회 (날짜 확인 필요)
 *  · 그 밖의 둘째 주: 마지막 연사 = 스테이크
 *  · 5월 셋째 주: 와드대회, 11월 마지막 주: 초등회 발표 (확인 필요)
 *  · 말씀·기도: 장로정원회·상호부조회 탭의 '활동' 회원 중, 작년에 맡은 횟수(역할별)와 비슷하게.
 *    한 주 안에서 형제·자매를 섞고, 8주 안에는 같은 분을 다시 넣지 않음.
 *    감독단과 '기도 & 말씀 어렵다고 하신분' 메모의 분들은 뺌.
 *  · 찬송: 개회 1~57 / 성찬 105~121 / 회중 58~104 / 폐회 138~195 를 섞어서 돌아가며
 *    (한 바퀴 다 쓰기 전엔 같은 찬송 안 나옴). 부활절 122~124, 12월은 성탄 찬송 125~137.
 *  · 모양: 작년 탭을 통째로 복사해서 서식·수식·병합은 그대로, 값만 바꿈. 확인할 주는 날짜 칸 메모로.
 */
function buildYearDraft_(year) {
  const ss = source_();
  const prevTab = ss.getSheetByName(SCHEDULE_TAB.replace('{년}', year - 1));
  if (!prevTab) throw new Error(`'${year - 1}년 성찬식' 탭이 없습니다.`);
  const COLS = 19; // A~S (작년 탭과 같은 열)

  // 1) 작년 탭을 통째로 복사 → 서식·수식·병합·열 너비·조건부 서식이 그대로
  const name = `${year}년 성찬식 (초안)`;
  const old = ss.getSheetByName(name);
  if (old) ss.deleteSheet(old);
  const sheet = prevTab.copyTo(ss).setName(name);
  ss.setActiveSheet(sheet);
  ss.moveActiveSheet(prevTab.getIndex() + 1);

  // 2) 작년 탭에서 주일 줄 위치와, 열마다 쓰던 수식(R1C1 = 상대 위치 수식) 찾기
  const values = prevTab.getDataRange().getValues();
  const hr = values.findIndex((row, i) => i < 5 && row.some(v => String(v).trim() === '날짜'));
  const dateCol = values[hr].findIndex(v => String(v).trim() === '날짜');
  const sundayRows = [];
  values.forEach((row, i) => { if (i > hr && monthDay_(row[dateCol])) sundayRows.push(i + 1); });
  const firstRow = sundayRows[0];
  const lastRow = sundayRows[sundayRows.length - 1];
  const dateIsDate = values[firstRow - 1][dateCol] instanceof Date;
  const f = prevTab.getRange(1, 1, values.length, COLS).getFormulasR1C1();
  const formulaCols = {};
  for (let c = 0; c < COLS; c++) {
    const n = {};
    sundayRows.forEach(r => { if (f[r - 1][c]) n[f[r - 1][c]] = (n[f[r - 1][c]] || 0) + 1; });
    const best = Object.keys(n).sort((x, y) => n[y] - n[x])[0];
    if (best && n[best] >= sundayRows.length / 3) formulaCols[c] = best;
  }

  // 3) 올해 내용 만들기
  const rand = seededRandom_(year);
  const prev = readTable_(prevTab);
  const bishopric = bishopric_();
  const music = musicRule_(prev);
  const people = memberPool_(new Set([...bishopric, ...hardToAsk_(prevTab)]));
  const book = hymnBook_();
  const range = (a, b) => Array.from({ length: b - a + 1 }, (_, i) => a + i).filter(n => book[n]);
  const hymn = {
    open: cycle_(range(1, 57), rand), sacrament: cycle_(range(105, 121), rand),
    rest: cycle_(range(58, 104), rand), close: cycle_(range(138, 195), rand), xmas: cycle_(range(125, 137), rand),
  };
  const h = n => (n ? [n, book[n] || ''] : ['', '']);
  const easter = fmt_(easterSunday_(year), 'MM-dd');

  const rows = [], meta = [], merges = [];
  let meetingNo = 0;
  for (let d = upcomingSunday_(new Date(year, 0, 1)), w = 0; d.getFullYear() === year; d = plusDays_(d, 7), w++) {
    const month = d.getMonth() + 1, nth = Math.ceil(d.getDate() / 7);
    const isLast = plusDays_(d, 7).getMonth() !== d.getMonth();
    const r = firstRow + rows.length; // 시트 행 번호
    const row = new Array(COLS).fill('');
    const info = { special: false, note: '' };
    row[2] = dateIsDate ? new Date(d) : fmt_(d, 'MM/dd');

    const special = (month === 4 || month === 10) && nth === 2 ? '연차대회 시청'
      : (month === 3 || month === 9) && nth === 2 ? '스테이크 대회' : '';
    if (special) {
      row[3] = special;
      info.special = true;
      if (special === '스테이크 대회') info.note = '스테이크 대회 날짜 확인 필요';
      merges.push([r, 4, 1, 16]);
      rows.push(row);
      meta.push(info);
      continue;
    }

    const fast = nth === 1;
    const program = month === 5 && nth === 3 ? '와드대회' : month === 11 && isLast ? '초등회 발표' : '';
    row[3] = bishopric[meetingNo++ % bishopric.length] || '';
    row[4] = fast ? music.choristerFirst : music.choristerOther;
    row[5] = music.organists.length ? music.organists[w % music.organists.length] : '';

    // 말씀 · 기도 (한 주 안에서 형제·자매 섞기)
    const g1 = w % 2 ? 'M' : 'F', g2 = g1 === 'M' ? 'F' : 'M';
    const taken = new Set(row.slice(3, 6));
    const assign = (role, g) => pickPerson_(people, role, g, w, taken, rand);
    if (fast || program) {
      row[6] = fast ? '금식간증' : program;
      merges.push([r, 7, 1, 3]);
      if (program) info.note = `${program} 확인 필요`;
    } else {
      row[6] = assign('talk5', g1);
      row[7] = assign('talk10', g2);
      row[8] = nth === 2 ? '스테이크' : assign('last', g1);
    }
    row[9] = assign('open', g2);
    row[10] = assign('close', g1);

    // 찬송 (제목 칸에 작년처럼 수식이 있으면 아래 4)에서 수식으로 덮어씀)
    const isEaster = fmt_(d, 'MM-dd') === easter;
    const xmas = month === 12;
    [row[11], row[12]] = h(isEaster ? 122 : xmas ? hymn.xmas() : hymn.open());
    [row[13], row[14]] = h(hymn.sacrament());
    [row[15], row[16]] = fast ? ['', ''] : h(isEaster ? 123 : xmas ? hymn.xmas() : hymn.rest());
    [row[17], row[18]] = h(isEaster ? 124 : xmas ? hymn.xmas() : hymn.close());
    if (isEaster) info.note = '부활절';
    rows.push(row);
    meta.push(info);
  }

  // 년도·분기 칸 (작년처럼 병합)
  rows[0][0] = year;
  merges.push([firstRow, 1, rows.length, 1]);
  [0, 1, 2, 3].forEach(q => {
    const idx = rows.map((row, i) => i).filter(i => Math.floor((Number(fmt_(sundayOf_(year, i), 'M')) - 1) / 3) === q);
    if (!idx.length) return;
    rows[idx[0]][1] = `${q + 1}분기`;
    merges.push([firstRow + idx[0], 2, idx.length, 1]);
  });

  // 4) 주일 줄 수가 작년과 다르면 줄 늘리기/비우기 → 값 쓰기 → 수식 넣기 → 병합 → 메모
  const extra = rows.length - sundayRows.length;
  if (extra > 0) {
    sheet.insertRowsAfter(lastRow, extra);
    sheet.getRange(lastRow, 1, 1, COLS).copyTo(sheet.getRange(lastRow + 1, 1, extra, COLS), { formatOnly: true });
  }
  const area = sheet.getRange(firstRow, 1, Math.max(rows.length, sundayRows.length), COLS);
  area.breakApart();
  area.clearContent();
  area.clearNote();
  sheet.getRange(firstRow, 1, rows.length, COLS).setValues(rows);
  rows.forEach((row, i) => {
    if (meta[i].special) return;
    Object.keys(formulaCols).forEach(c => sheet.getRange(firstRow + i, Number(c) + 1).setFormulaR1C1(formulaCols[c]));
  });
  merges.forEach(([r, c, nr, nc]) => sheet.getRange(r, c, nr, nc).merge());
  meta.forEach((info, i) => { if (info.note) sheet.getRange(firstRow + i, dateCol + 1).setNote(info.note); });

  const counts = people.filter(p => p.total || p.wTotal).sort((a, b) => b.total - a.total)
    .map(p => `${p.name} ${p.total}(작년 ${p.wTotal})`).join(', ');
  const fCols = Object.keys(formulaCols).map(c => String.fromCharCode(65 + Number(c))).join(', ') || '없음';
  report_(`[순서표 초안] ${year}년 성찬식 (초안) 탭을 만들었습니다`,
    `${year - 1}년 탭을 복사해서 서식·수식을 그대로 두고 값만 바꿨습니다. (수식을 그대로 넣은 열: ${fCols})\n\n`
    + `사회: ${bishopric.join(' → ')}\n지휘: 첫째 주 ${music.choristerFirst} / 그 외 ${music.choristerOther}\n반주: ${music.organists.join(', ')} 번갈아\n\n`
    + `말씀·기도 배정 횟수: ${counts}\n\n날짜 칸에 메모(오른쪽 위 작은 표시)가 달린 주를 확인하고, 다 고친 뒤 탭 이름을 '${year}년 성찬식'으로 바꾸면 아젠다 자동화가 이 탭을 읽습니다.`,
    `${ss.getUrl()}#gid=${sheet.getSheetId()}`);
}

/** year 년의 i 번째 주일 */
function sundayOf_(year, i) {
  return plusDays_(upcomingSunday_(new Date(year, 0, 1)), 7 * i);
}

/** 사람 고르기: '올해 맡은 횟수 ÷ 작년 맡은 횟수'가 가장 작은 분 먼저 → 작년과 비슷한 비율로 돌아감
 *  같은 역할을 작년에 해 본 분을 조금 더 우선, 8주 안에 맡은 분은 건너뜀 */
function pickPerson_(people, role, gender, week, taken, rand) {
  const free = gap => people.filter(p => p.g === gender && !taken.has(p.name) && week - p.lastWeek >= gap);
  const list = [8, 4, 1].map(free).find(l => l.length) || [];
  if (!list.length) return '';
  const score = p => (p.total + 1) / (p.wTotal + 0.4) - (p.w[role] > 0 ? 0.2 : 0) + rand() * 0.05;
  const best = list.reduce((a, b) => (score(b) < score(a) ? b : a));
  best.used[role]++;
  best.total++;
  best.lastWeek = week;
  taken.add(best.name);
  return best.name;
}

/** 장로정원회(형제) · 상호부조회(자매) 탭에서 '활동' 회원과 작년 역할별 횟수 */
function memberPool_(exclude) {
  const roles = { talk5: ['5분 말씀'], talk10: ['10분 말씀'], last: ['마지막 연사', '주연사'], open: ['개회기도'], close: ['폐회기도'] };
  const out = [];
  [['장로정원회', 'M'], ['상호부조회', 'F']].forEach(([tab, g]) => {
    const sheet = source_().getSheetByName(tab);
    if (!sheet) return;
    const values = sheet.getDataRange().getValues();
    const hr = values.findIndex((row, i) => i < 5 && row.some(v => String(v).trim() === '이름'));
    if (hr < 0) return;
    const col = names => values[hr].findIndex(v => names.includes(String(v).trim()));
    const nameCol = col(['이름']), activeCol = col(['활동화', '활동화 정도']);
    values.slice(hr + 1).forEach(row => {
      const name = String(row[nameCol]).trim();
      if (!name || exclude.has(name) || String(row[activeCol]).trim() !== '활동') return;
      const p = { name, g, w: {}, used: {}, total: 0, lastWeek: -99 };
      Object.keys(roles).forEach(k => {
        const c = col(roles[k]);
        p.w[k] = c >= 0 ? Number(row[c]) || 0 : 0;
        p.used[k] = 0;
      });
      p.wTotal = Object.keys(p.w).reduce((sum, k) => sum + p.w[k], 0);
      out.push(p);
    });
  });
  return out;
}

/** 부름현황 탭에서 감독 → 1보좌 → 2보좌 */
function bishopric_() {
  const sheet = source_().getSheetByName('부름현황');
  if (!sheet) return [];
  const values = sheet.getDataRange().getValues();
  const hr = values.findIndex((row, i) => i < 5 && row.some(v => String(v).trim() === '구분'));
  if (hr < 0) return [];
  const kCol = values[hr].findIndex(v => String(v).trim() === '구분');
  const nCol = values[hr].findIndex(v => String(v).trim() === '성명');
  const found = {};
  values.slice(hr + 1).forEach(row => {
    const k = String(row[kCol]).trim(), n = String(row[nCol]).trim();
    if (k === '감독' && !found['감독']) found['감독'] = n;
    else if (found['감독'] && (k === '1보좌' || k === '2보좌') && !found[k]) found[k] = n;
  });
  return ['감독', '1보좌', '2보좌'].map(k => found[k]).filter(Boolean);
}

/** 작년 탭 아래 '기도 & 말씀 어렵다고 하신분' 메모의 이름들 (끝의 s 는 자매 표시라 뺌) */
function hardToAsk_(sheet) {
  const values = sheet.getDataRange().getValues();
  for (let r = 0; r < values.length; r++) {
    const c = values[r].findIndex(v => String(v).includes('어렵다고'));
    if (c < 0) continue;
    const names = [];
    for (let i = r + 1; i < values.length; i++) {
      const v = String(values[i][c]).trim();
      if (!v || /사항|내용/.test(v)) break; // 빈 칸이나 다음 메모 제목('특이사항')에서 멈춤
      names.push(v.replace(/\s*s$/i, ''));
    }
    return names;
  }
  return [];
}

/** 작년 지휘·반주 경향 */
function musicRule_(prevRows) {
  const mode = list => {
    const n = {};
    list.filter(v => v && !NOT_PERSON_RE.test(v)).forEach(v => (n[v] = (n[v] || 0) + 1));
    return Object.keys(n).sort((a, b) => n[b] - n[a]);
  };
  const day = r => Number(r.md.slice(3));
  const chor = r => r.get('지휘')[0] || '';
  const recent = prevRows.filter(r => r.get('반주')[0]).slice(-13);
  return {
    choristerFirst: mode(prevRows.filter(r => day(r) <= 7).map(chor))[0] || '',
    choristerOther: mode(prevRows.filter(r => day(r) > 7).map(chor))[0] || '',
    organists: mode(recent.map(r => r.get('반주')[0])).slice(0, 2),
  };
}

/** 찬송가 탭 → { 번호: 제목 } */
function hymnBook_() {
  const sheet = source_().getSheetByName('찬송가');
  const book = {};
  if (!sheet) return book;
  sheet.getDataRange().getValues().forEach(row => {
    for (let c = 0; c + 1 < row.length; c++) {
      const n = String(row[c]).trim();
      if (/^\d{1,4}$/.test(n) && String(row[c + 1]).trim()) { book[Number(n)] = String(row[c + 1]).trim(); break; }
    }
  });
  return book;
}

/** 섞어서 한 바퀴씩 돌려주는 함수 (한 바퀴를 다 쓰기 전엔 같은 번호가 다시 안 나옴) */
function cycle_(items, rand) {
  let bag = [], last = null;
  return () => {
    if (!items.length) return '';
    if (!bag.length) {
      bag = items.slice();
      for (let i = bag.length - 1; i > 0; i--) {
        const j = Math.floor(rand() * (i + 1));
        [bag[i], bag[j]] = [bag[j], bag[i]];
      }
      if (bag.length > 1 && bag[bag.length - 1] === last) [bag[0], bag[bag.length - 1]] = [bag[bag.length - 1], bag[0]];
    }
    return (last = bag.pop());
  };
}

/** 같은 연도면 늘 같은 결과가 나오는 난수 (다시 만들어도 초안이 바뀌지 않게) */
function seededRandom_(seed) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}

/** 부활절 날짜 (그레고리력 계산법) */
function easterSunday_(y) {
  const a = y % 19, b = Math.floor(y / 100), c = y % 100, d = Math.floor(b / 4), e = b % 4;
  const f = Math.floor((b + 8) / 25), g = Math.floor((b - f + 1) / 3), h = (19 * a + b - d - g + 15) % 30;
  const i = Math.floor(c / 4), k = c % 4, l = (32 + 2 * e + 2 * i - h - k) % 7, m = Math.floor((a + 11 * h + 22 * l) / 451);
  const month = Math.floor((h + l - 7 * m + 114) / 31), day = ((h + l - 7 * m + 114) % 31) + 1;
  return new Date(y, month - 1, day);
}

function plusDays_(date, n) {
  const d = new Date(date);
  d.setDate(d.getDate() + n);
  return d;
}

function 내년순서표만들기() { buildYearDraft_(DRAFT_YEAR); }

/** 받침이 있으면 a(을), 없으면 b(를) */
function josa_(word, a, b) {
  const code = word.charCodeAt(word.length - 1) - 0xac00;
  return code >= 0 && code <= 11171 && code % 28 ? a : b;
}
