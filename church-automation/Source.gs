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
