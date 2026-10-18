// ⛪ 와드 성찬식 자동화 — 전체 코드 (build.sh 로 자동 생성, 직접 고치지 말고 각 .gs 파일을 고치세요)

// ==================== Config.gs ====================
/**
 * 와드 성찬식 자동화 — 설정
 * 원본 데이터: 감독단 구글 시트(성찬식 일정 · 성찬 축복/전달 탭)
 * 내 시트(이 스크립트가 붙은 시트)에는 '설정'과 '발송기록'만 둡니다.
 */
const DEFAULT_REQUEST_TEMPLATE =
  '{이름}, 안녕하세요 🙂 {와드} 감독단입니다.\n'
  + '{날짜} 성찬식 {역할} 순서를 맡아 주셔서 감사합니다.{주제}\n'
  + '준비하시다 어려운 점이 있으면 언제든 연락 주세요!';

const CONFIG = {
  SETTINGS_SHEET: '설정',
  LOG_SHEET: '발송기록',
  // [항목, 기본값, 설명]
  DEFAULT_SETTINGS: [
    ['원본 시트', '', '감독단 구글 시트 주소(URL)를 붙여넣으세요'],
    ['성찬식 탭 이름', '{년}년 성찬식', '{년} 은 해당 주일의 연도로 바뀜 (2026년 성찬식, 2027년 성찬식 …)'],
    ['축복/전달 탭 이름', '성찬 축복/전달', ''],
    ['아젠다 방식', '공용 문서', '공용 문서 = 「성찬식 아젠다」 맨 위에 계속 추가 / 새 문서 = 매주 템플릿을 복사해 새 문서 만들기'],
    ['아젠다 템플릿', '', '(새 문서) 복사할 아젠다 문서 주소. 예: 녹번와드 성찬식 아젠다 (9/6)'],
    ['아젠다 문서', '', '(공용 문서) 「성찬식 아젠다」 구글 문서 주소(URL)'],
    ['아젠다 호칭', '예', '아젠다 이름 뒤에 형제님/자매님 붙이기 (예 / 아니오)'],
    ['찬송 형식', '{번호}장 {제목}', '예: {번호}장 {제목} → 23장 주께 찬양하여라'],
    ['알림 이메일', '', '쉼표로 여러 명 가능'],
    ['와드 이름', '녹번와드', '부탁 메시지에 들어감'],
    ['미리 확인할 주 수', 8, '이 기간 안에 비어 있는 순서를 알려줌'],
    ['부탁 메시지', DEFAULT_REQUEST_TEMPLATE, '{이름} {날짜} {역할} {주제} {와드} 사용 가능'],
    ['부탁 메시지 카톡 발송', '예', '예 / 아니오'],
  ],
  // 자동 실행 시각 (한국 시간, ±15분 안에서 실행됨)
  SCHEDULE: {
    NEXT_WEEK: { day: ScriptApp.WeekDay.SUNDAY, hour: 7 },    // 다음 주 임무 + 부탁 메시지
    AGENDA: { day: ScriptApp.WeekDay.MONDAY, hour: 9 },       // 이번 주 아젠다 만들기
    TOMORROW: { day: ScriptApp.WeekDay.SATURDAY, hour: 15 },  // 톡방 공지
  },
  // 원본 시트의 열 제목 (여러 후보 중 먼저 찾은 것 사용)
  COLUMNS: {
    presiding: ['감리'],
    conducting: ['사회'],
    chorister: ['지휘'],
    organist: ['반주'],
    talk5: ['5분 말씀'],
    talk10: ['10분 말씀'],
    lastSpeaker: ['마지막 연사', '주연사'],
    openingPrayer: ['개회기도'],
    closingPrayer: ['폐회기도'],
    openingHymn: ['개회찬송'],
    sacramentHymn: ['성찬찬송'],
    restHymn: ['회중찬송'],
    closingHymn: ['폐회찬송'],
    topic: ['말씀 주제', '주제'], // 열을 추가하면 부탁 메시지에 자동으로 들어감
    blessers: ['축복', '성찬 축복'],
    passers: ['전달', '성찬 전달'],
  },
  // 호칭(형제님/자매님)을 붙이기 위해 읽는 명단 탭
  ROSTERS: [
    { tab: '장로정원회', title: '형제님' },
    { tab: '상호부조회', title: '자매님' },
    { tab: '청년독신성인', genderCol: '성별' },
  ],
  SPECIAL_WEEK: /대회/, // 사회 칸에 이 글자가 있으면 정규 성찬식이 없는 주 (연차대회, 스테이크 대회)
  NOT_A_PERSON: /간증|대회|스테이크|발표|선교사|장로님|성찬식|방문|찬송|\?/, // 사람 이름이 아닌 칸
};

// 부탁·리마인드 메시지를 보낼 순서
const REMINDER_ROLES = [
  ['talk5', '5분 말씀'],
  ['talk10', '10분 말씀'],
  ['lastSpeaker', '마지막 연사 말씀'],
  ['openingPrayer', '개회기도'],
  ['closingPrayer', '폐회기도'],
];
// 비어 있으면 경고할 순서
const REQUIRED_ROLES = [['conducting', '사회'], ...REMINDER_ROLES];

// ==================== Util.gs ====================
/** 공통 도우미 함수 (이름 끝의 _ 는 메뉴/실행 목록에 안 보이는 내부 함수라는 뜻) */

function ownSheet_(name) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(name);
  if (!sheet) throw new Error(`'${name}' 시트가 없습니다. 메뉴에서 '초기 설정'을 먼저 실행하세요.`);
  return sheet;
}

function getSetting_(key) {
  const row = ownSheet_(CONFIG.SETTINGS_SHEET).getDataRange().getValues().find(r => r[0] === key);
  return row ? String(row[1]).trim() : '';
}

function log_(title, text) {
  try {
    ownSheet_(CONFIG.LOG_SHEET).appendRow([new Date(), title, text]);
  } catch (e) {
    console.error(e);
  }
}

/** 구글 문서/시트 주소(URL)에서 파일 ID만 꺼내기 (ID를 그대로 넣어도 됨) */
function fileId_(urlOrId) {
  const m = String(urlOrId).match(/\/d\/([\w-]+)/);
  return m ? m[1] : String(urlOrId).trim();
}

function fmt_(date, pattern) {
  return Utilities.formatDate(date, Session.getScriptTimeZone(), pattern);
}

function addDays_(date, n) {
  const d = new Date(date);
  d.setDate(d.getDate() + n);
  return d;
}

/** 오늘이 일요일이면 오늘, 아니면 다가오는 일요일 */
function upcomingSunday_(base) {
  return addDays_(base, (7 - new Date(base).getDay()) % 7);
}

/** 오늘을 빼고 다음에 오는 일요일 (일요일에 실행하면 7일 뒤) */
function nextSunday_(base) {
  return upcomingSunday_(addDays_(base, 1));
}

/** 날짜 칸(Date) 이든 '01/04', '1월 5일', '2026.01.04' 같은 글자든 'MM-dd' 로 통일 */
function monthDay_(v) {
  if (v instanceof Date) return fmt_(v, 'MM-dd');
  const s = String(v);
  const m = s.match(/\d{4}\D+(\d{1,2})\D+(\d{1,2})/) || s.match(/^\s*(\d{1,2})\s*[/.\-월]\s*(\d{1,2})/);
  return m ? `${m[1].padStart(2, '0')}-${m[2].padStart(2, '0')}` : '';
}

function unique_(arr) {
  return arr.filter((v, i) => arr.indexOf(v) === i);
}

/** null/undefined/false 를 뺀 줄들을 줄바꿈으로 합치기 ('' 는 빈 줄로 유지) */
function lines_(...items) {
  return items.filter(x => x !== null && x !== undefined && x !== false).join('\n');
}

// ==================== Source.gs ====================
/** 감독단 원본 시트 읽기 (읽기만 하고 절대 고치지 않음) */

let SOURCE_ = null;   // 한 번 실행하는 동안 재사용
const TABLES_ = {};
let ROSTER_ = null;

function sourceSS_() {
  if (SOURCE_) return SOURCE_;
  const id = fileId_(getSetting_('원본 시트'));
  if (!id) throw new Error("'설정' 시트의 '원본 시트'에 감독단 시트 주소를 넣어 주세요.");
  return (SOURCE_ = SpreadsheetApp.openById(id));
}

/** 병합된 칸은 맨 왼쪽 위 칸에만 값이 있음 → 병합 범위 전체에 같은 값을 채워 넣기 */
function readFilled_(sheet) {
  const range = sheet.getDataRange();
  const values = range.getValues();
  range.getMergedRanges().forEach(m => {
    const v = m.getValue();
    for (let r = m.getRow(); r <= m.getLastRow(); r++) {
      for (let c = m.getColumn(); c <= m.getLastColumn(); c++) {
        if (values[r - 1] && c - 1 < values[r - 1].length) values[r - 1][c - 1] = v;
      }
    }
  });
  return values;
}

/** 날짜 열 찾기: '날짜' 제목이 있으면 그 열, 없으면 '01/04' 모양 값이 가장 많은 열 */
function findDateCol_(values, headerRow) {
  const byTitle = values[headerRow].findIndex(h => String(h).trim() === '날짜');
  if (byTitle >= 0) return byTitle;
  const looksLikeDate = v => v instanceof Date || /^\s*\d{1,2}\s*[/.]\s*\d{1,2}\s*$/.test(String(v));
  let best = -1, bestCount = 0;
  values[headerRow].forEach((_, c) => {
    const count = values.slice(headerRow + 1).filter(row => looksLikeDate(row[c])).length;
    if (count > bestCount) [best, bestCount] = [c, count];
  });
  return best;
}

/**
 * 표 읽기. 반환: [{ md: 'MM-dd', get(열이름후보) → 값 배열 }]
 * 찬송처럼 제목이 두 칸(번호·제목)에 걸쳐 병합된 열은 하나로 묶어서 돌려줌
 */
function readTable_(sheet, anchors) {
  const key = sheet.getName();
  if (TABLES_[key]) return TABLES_[key];

  const values = readFilled_(sheet);
  const headerRow = values.findIndex((row, i) => i < 5 && row.some(v => anchors.includes(String(v).trim())));
  if (headerRow < 0) return (TABLES_[key] = []);
  const dateCol = findDateCol_(values, headerRow);

  // 제목이 앞 칸과 같거나(병합) 비어 있으면 앞 열 묶음에 포함
  const groups = {};
  let prev = '';
  values[headerRow].forEach((h, c) => {
    if (c === dateCol) { prev = ''; return; }
    h = String(h).trim();
    if (h && h !== prev) {
      (groups[h] = groups[h] || []).push(c);
      prev = h;
    } else if (prev) {
      groups[prev].push(c);
    }
  });

  return (TABLES_[key] = values.slice(headerRow + 1)
    .map(row => ({
      md: monthDay_(row[dateCol]),
      get: names => {
        const h = names.find(n => groups[n]);
        if (!h) return [];
        return unique_(groups[h].map(c => String(row[c]).trim()).filter(v => v && !v.startsWith('#')));
      },
    }))
    .filter(r => r.md));
}

/** 찬송: ['24', '조셉 스미스의 첫 번째 기도'] → '24장 - 조셉 스미스의 첫 번째 기도' ('찬송 형식' 설정대로) */
function hymnText_(parts) {
  const [num, title] = parts;
  if (!num) return '';
  if (!/^\d+$/.test(num)) return parts.join(' '); // '특별찬송' 같은 글자
  if (!title) return `${num}장`;
  return (getSetting_('찬송 형식') || '{번호}장 {제목}').split('{번호}').join(num).split('{제목}').join(title);
}

/** 한 주일의 성찬식 정보를 하나의 객체로 모으기. 시트에 그 날짜가 없으면 null */
function getMeeting_(sunday) {
  const C = CONFIG.COLUMNS;
  const ss = sourceSS_();
  const tab = ss.getSheetByName(getSetting_('성찬식 탭 이름').replace('{년}', sunday.getFullYear()));
  if (!tab) return null;
  const md = fmt_(sunday, 'MM-dd');
  const row = readTable_(tab, ['날짜']).find(r => r.md === md);
  if (!row) return null;

  const m = { sunday: sunday, hymns: {} };
  ['presiding', 'conducting', 'chorister', 'organist', 'talk5', 'talk10', 'lastSpeaker',
    'openingPrayer', 'closingPrayer', 'topic'].forEach(k => (m[k] = row.get(C[k])[0] || ''));
  ['openingHymn', 'sacramentHymn', 'restHymn', 'closingHymn'].forEach(k => (m.hymns[k] = hymnText_(row.get(C[k]))));

  m.special = CONFIG.SPECIAL_WEEK.test(m.conducting) ? m.conducting : '';
  m.fast = /간증/.test(m.talk5); // 금식간증 주일: 말씀 칸 3개가 병합돼 있음
  if (m.fast) m.talk10 = m.lastSpeaker = '';
  m.speakers = unique_([m.talk5, m.talk10].filter(Boolean));

  const blessTab = ss.getSheetByName(getSetting_('축복/전달 탭 이름'));
  const b = blessTab && readTable_(blessTab, C.blessers.concat(C.passers)).find(r => r.md === md);
  m.blessers = b ? b.get(C.blessers).filter(isPerson_) : [];
  m.passers = b ? b.get(C.passers).filter(isPerson_) : [];
  return m;
}

/** 이름 → 호칭 표 (장로정원회=형제님, 상호부조회=자매님, 청년독신성인=성별로) */
function honorifics_() {
  if (ROSTER_) return ROSTER_;
  ROSTER_ = {};
  CONFIG.ROSTERS.forEach(cfg => {
    const sheet = sourceSS_().getSheetByName(cfg.tab);
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

/** '홍길순' → '홍길순 자매님', '김철수/이영희' → '김철수 형제님 / 이영희 자매님', 모르는 값은 그대로 */
function withTitle_(raw) {
  return String(raw || '').split('/').map(s => s.trim()).filter(Boolean)
    .map(s => (honorifics_()[s] && !s.endsWith('님') ? `${s} ${honorifics_()[s]}` : s))
    .join(' / ');
}

function isPerson_(raw) {
  return !!raw && !CONFIG.NOT_A_PERSON.test(raw);
}

// ==================== Jobs.gs ====================
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

// ==================== Agenda.gs ====================
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
  if (getSetting_('아젠다 방식') === '새 문서') return makeAgendaDoc_(m);

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
  if (text(body.getChild(start)).startsWith(newDate)) {
    fillSection_(collectSection_(body, start), m);
    return 'updated';
  }

  // 복사할 칸: 최근 몇 주 중 '회중찬송:'·'마지막 … 말씀:' 줄까지 다 있는 가장 최근 칸
  // (금식간증 주 칸은 이 줄들이 빠져 있어서 그대로 복사하면 다음 주 칸에도 빠짐)
  const complete = sec => {
    const lines = sec.map(text);
    return lines.some(s => s.startsWith('회중찬송:')) && lines.some(s => /^마지막.*말씀:/.test(s));
  };
  let section = collectSection_(body, start);
  for (let i = start, seen = 0; i < n && seen < 6 && !complete(section); i++) {
    if (i > start && SECTION_RE.test(text(body.getChild(i)))) {
      seen++;
      const candidate = collectSection_(body, i);
      if (complete(candidate)) section = candidate;
    }
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

// ==================== Notify.gs ====================
/**
 * 알림 발송: 이메일 + (연결돼 있으면) 카카오톡 '나에게 보내기'
 * msg = { subject, text, link?, kakaoExtras?: [추가로 카톡 보낼 글], emailExtra?: 이메일에만 붙일 글 }
 */
function notify_(msg) {
  const link = msg.link || SpreadsheetApp.getActiveSpreadsheet().getUrl();
  const emails = getSetting_('알림 이메일');
  if (emails) {
    MailApp.sendEmail({
      to: emails,
      subject: msg.subject,
      body: lines_(msg.text, msg.emailExtra ? '\n' + msg.emailExtra : null, '', link),
    });
  }

  if (kakaoIsConnected_()) {
    try {
      [msg.text, ...(msg.kakaoExtras || [])].forEach(t => kakaoSendToMe_(t, link));
    } catch (e) {
      // 카카오가 실패해도 이메일은 이미 나갔으니 기록만 남김
      console.error(e);
      log_('카카오톡 전송 실패', String(e));
    }
  }
  log_(msg.subject, msg.text);
}

// ==================== Kakao.gs ====================
/**
 * 카카오톡 '나에게 보내기' (Kakao REST API · 메시지 API)
 *
 * 공식 API로는 단체 대화방에 직접 글을 올릴 수 없습니다.
 * 그래서 내 카톡으로 받은 뒤 → 단톡방에 '전달' 한 번 누르는 방식입니다.
 */
const KAKAO_REDIRECT_URI = 'https://localhost';
const KAKAO_TEXT_LIMIT = 200; // 카카오 텍스트 템플릿 최대 글자 수

/** 메뉴 → '카카오톡 연결' : 최초 1회 로그인해서 토큰 받기 */
function kakaoConnect() {
  const ui = SpreadsheetApp.getUi();
  const props = PropertiesService.getScriptProperties();

  let key = props.getProperty('KAKAO_REST_KEY');
  if (!key) {
    const r = ui.prompt('카카오 REST API 키', 'Kakao Developers > 내 애플리케이션 > 앱 키 > REST API 키를 붙여넣으세요.', ui.ButtonSet.OK_CANCEL);
    if (r.getSelectedButton() !== ui.Button.OK) return;
    key = r.getResponseText().trim();
    props.setProperty('KAKAO_REST_KEY', key);
  }

  const authUrl = 'https://kauth.kakao.com/oauth/authorize'
    + `?client_id=${encodeURIComponent(key)}`
    + `&redirect_uri=${encodeURIComponent(KAKAO_REDIRECT_URI)}`
    + '&response_type=code&scope=talk_message';

  const r = ui.prompt(
    '카카오 로그인',
    `1) 아래 주소를 브라우저에 붙여넣고 로그인·동의하세요.\n\n${authUrl}\n\n`
      + '2) "사이트에 연결할 수 없음" 화면이 떠도 정상입니다.\n'
      + '   주소창의 code= 뒤의 값을 복사해 아래에 붙여넣으세요.',
    ui.ButtonSet.OK_CANCEL);
  if (r.getSelectedButton() !== ui.Button.OK) return;

  const code = r.getResponseText().trim().replace(/^.*code=/, '').replace(/&.*$/, '');
  kakaoTokenRequest_({ grant_type: 'authorization_code', redirect_uri: KAKAO_REDIRECT_URI, code: code });
  kakaoSendToMe_('✅ 교회 자동화와 카카오톡이 연결되었습니다.', SpreadsheetApp.getActiveSpreadsheet().getUrl());
  ui.alert('연결 완료! 내 카카오톡을 확인해 보세요.');
}

function kakaoIsConnected_() {
  return !!PropertiesService.getScriptProperties().getProperty('KAKAO_REFRESH_TOKEN');
}

function kakaoTokenRequest_(payload) {
  const props = PropertiesService.getScriptProperties();
  payload.client_id = props.getProperty('KAKAO_REST_KEY');
  const secret = props.getProperty('KAKAO_CLIENT_SECRET');
  if (secret) payload.client_secret = secret;

  const res = UrlFetchApp.fetch('https://kauth.kakao.com/oauth/token', {
    method: 'post', payload: payload, muteHttpExceptions: true,
  });
  if (res.getResponseCode() !== 200) throw new Error('카카오 토큰 오류: ' + res.getContentText());

  const data = JSON.parse(res.getContentText());
  props.setProperty('KAKAO_ACCESS_TOKEN', data.access_token);
  props.setProperty('KAKAO_ACCESS_EXPIRES', String(Date.now() + (data.expires_in - 60) * 1000));
  // 리프레시 토큰은 만료가 가까울 때만 새로 내려옴 → 올 때마다 저장
  if (data.refresh_token) props.setProperty('KAKAO_REFRESH_TOKEN', data.refresh_token);
}

/** 액세스 토큰은 몇 시간마다 만료 → 리프레시 토큰으로 자동 재발급 */
function kakaoAccessToken_() {
  const props = PropertiesService.getScriptProperties();
  if (Date.now() > Number(props.getProperty('KAKAO_ACCESS_EXPIRES') || 0)) {
    kakaoTokenRequest_({ grant_type: 'refresh_token', refresh_token: props.getProperty('KAKAO_REFRESH_TOKEN') });
  }
  return props.getProperty('KAKAO_ACCESS_TOKEN');
}

/** 긴 글은 줄 단위로 200자 이하 조각으로 나눠 여러 번 보냄 */
function kakaoSendToMe_(text, linkUrl) {
  kakaoChunks_(text).forEach(chunk => {
    const template = {
      object_type: 'text',
      text: chunk,
      link: { web_url: linkUrl, mobile_web_url: linkUrl },
      button_title: '자세히 보기',
    };
    const res = UrlFetchApp.fetch('https://kapi.kakao.com/v2/api/talk/memo/default/send', {
      method: 'post',
      headers: { Authorization: 'Bearer ' + kakaoAccessToken_() },
      payload: { template_object: JSON.stringify(template) },
      muteHttpExceptions: true,
    });
    if (res.getResponseCode() !== 200) throw new Error('카카오 전송 오류: ' + res.getContentText());
  });
}

function kakaoChunks_(text) {
  const chunks = [];
  let cur = '';
  text.split('\n').forEach(line => {
    while (line.length > KAKAO_TEXT_LIMIT) {
      if (cur) chunks.push(cur), (cur = '');
      chunks.push(line.slice(0, KAKAO_TEXT_LIMIT));
      line = line.slice(KAKAO_TEXT_LIMIT);
    }
    const next = cur ? cur + '\n' + line : line;
    if (next.length > KAKAO_TEXT_LIMIT) chunks.push(cur), (cur = line);
    else cur = next;
  });
  if (cur.trim()) chunks.push(cur);
  return chunks;
}

// ==================== Setup.gs ====================
/** 메뉴 · 초기 설정 · 트리거(자동 실행 예약) */

function onOpen() {
  SpreadsheetApp.getUi().createMenu('⛪ 성찬식 자동화')
    .addItem('1. 초기 설정 (처음 한 번)', 'setup')
    .addItem('2. 카카오톡 연결', 'kakaoConnect')
    .addSeparator()
    .addItem('미리보기: 다음 주 임무·부탁 메시지', 'previewNextWeek')
    .addItem('미리보기: 내일 톡방 공지', 'previewTomorrow')
    .addSeparator()
    .addItem('지금 보내기: 다음 주 임무·부탁 메시지', 'sendNextWeekAssignments')
    .addItem('지금 보내기: 내일 톡방 공지', 'sendTomorrowNotice')
    .addItem('지금 만들기/갱신: 이번 주 아젠다', 'updateAgenda')
    .addSeparator()
    .addItem('자동 실행 다시 설치', 'installTriggers')
    .addToUi();
}

function setup() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  let settings = ss.getSheetByName(CONFIG.SETTINGS_SHEET);
  if (!settings) {
    settings = ss.insertSheet(CONFIG.SETTINGS_SHEET, 0);
    settings.appendRow(['항목', '값', '설명']);
    settings.getRange('A1:C1').setFontWeight('bold').setBackground('#f1f3f4');
    settings.setFrozenRows(1);
  }
  // 없는 항목만 추가 (다시 실행해도 입력한 값은 그대로)
  const existing = settings.getDataRange().getValues().map(r => r[0]);
  CONFIG.DEFAULT_SETTINGS.forEach(([key, value, help]) => {
    if (existing.includes(key)) return;
    settings.appendRow([key, key === '알림 이메일' ? Session.getEffectiveUser().getEmail() : value, help]);
  });
  settings.getRange('B:B').setWrap(true);
  settings.setColumnWidth(2, 360);

  if (!ss.getSheetByName(CONFIG.LOG_SHEET)) {
    const log = ss.insertSheet(CONFIG.LOG_SHEET);
    log.appendRow(['시각', '제목', '내용']);
    log.getRange('A1:C1').setFontWeight('bold').setBackground('#f1f3f4');
    log.setFrozenRows(1);
  }

  installTriggers();
  SpreadsheetApp.getUi().alert(
    '초기 설정 완료!\n\n'
    + "1) '설정' 시트에 원본 시트 주소와 아젠다 문서 주소를 붙여넣으세요.\n"
    + "2) 메뉴의 '미리보기'로 메시지가 맞게 나오는지 확인하세요.\n\n"
    + '자동 실행: 월 9시(이번 주 아젠다) · 일 7시(다음 주 임무) · 토 15시(톡방 공지)');
}

/** 기존 예약을 지우고 다시 만듦 (여러 번 실행해도 중복 안 됨) */
function installTriggers() {
  const S = CONFIG.SCHEDULE;
  const jobs = {
    sendNextWeekAssignments: S.NEXT_WEEK,
    updateAgenda: S.AGENDA,
    sendTomorrowNotice: S.TOMORROW,
  };
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() in jobs)
    .forEach(t => ScriptApp.deleteTrigger(t));
  Object.keys(jobs).forEach(fn => {
    ScriptApp.newTrigger(fn).timeBased().onWeekDay(jobs[fn].day).atHour(jobs[fn].hour).create();
  });
}
