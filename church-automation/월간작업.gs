/**
 * 월간 작업 — 아젠다 코드(Code.gs)와 같은 프로젝트에 '파일 추가'로 넣으세요. (Code.gs의 함수를 함께 씁니다)
 *
 *  ① sendTalkNotices   매주 월요일 : 4주 뒤 말씀·기도 맡은 분께 보낼 '주제 안내' + 이번 주 '리마인드' 문구를 메일로
 *  ② sendOrganistList  매달 25일   : 다음 달 지휘·반주·찬송표 이미지(PNG)를 메일로 → 반주자 톡방에 올리기
 *  ③ makeYearDraft     필요할 때   : 내년 성찬식 순서표 초안 탭 만들기 (감독단 시트에 '2027년 성찬식 (초안)' 탭)
 *
 * 처음 한 번: 함수 'installMonthlyTriggers' 실행 (①② 자동 실행 예약)
 * 미리 보기: 'testTalkNotices', 'testOrganistList' 실행 → 지금 바로 메일로 받아 보기
 */
const SENDER = '녹번와드 감독단';
const NOTICE_WEEKS_AHEAD = 4;   // 몇 주 전에 주제 안내를 보낼지
const DRAFT_YEAR = 2027;        // makeYearDraft 로 만들 연도

// 말씀 주제 — 시트에 '말씀 주제' 열이 있으면 그 값을 쓰고, 없으면 아래 목록을 주마다 돌아가며 사용
// [주제, 말씀자, 말씀 제목] · 2026년 10월 연차 대회 (영어 제목을 옮긴 것이라 복음 자료실 공식 제목과 조금 다를 수 있음)
const TALK_TOPICS = [
  ['성전', '게리 W. 공 장로', '주님의 거룩한 집에서 주님께 나아오십시오'],
  ['간증', '제라드 코세 장로', '간증이라는 은사'],
  ['선지자', '바이앙기나 시카헤마 장로', '선지자, 선견자, 계시자'],
  ['구원자이신 예수 그리스도', '케빈 J. 해서웨이 장로', '예수 그리스도는 위대한 구원자이십니다'],
  ['금식', '울리세스 소아레스 장로', '더 높고 거룩한 금식'],
  ['선교 사업', '션 더글러스 감독', '너의 선교의 때가 이르렀느니라'],
  ['지혜와 순종', 'D. 토드 크리스토퍼슨 회장', '오, 지혜로우라'],
  ['신앙', '데일 G. 렌런드 장로', '그들이 나를 믿기까지 얼마나 걸리겠느냐'],
  ['십일조와 헌금', '파트리시오 M. 주프라 장로', '십일조와 헌금으로 주님을 신뢰함'],
  ['성약', '제레마이아 J. 모건 장로', '성약에 담긴 하나님의 무한한 권능'],
  ['하나님의 자녀', '허치 U. 팔레 장로', '난 하나님의 자녀'],
  ['예수 그리스도의 도우심', '패트릭 키어런 장로', '예수님은 우리를 일으키시려 살아 계십니다'],
  ['성신', '매튜 J. 아이어링 장로', '성신이 주시는 위안'],
  ['그리스도와 같은 사랑', '로널드 A. 래스번드 장로', '예수님처럼 사랑하십시오'],
  ['두려움을 이기는 신앙', '헨리 B. 아이어링 회장', '두려워 말라 내가 너와 함께 함이라'],
  ['용기', '닐 L. 앤더슨 장로', '예수 그리스도를 믿는 신앙에서 오는 용기'],
  ['그리스도의 이름을 받듦', '제임스 G. O. 판톤 장로', '그분의 이름을 받들다'],
  ['그리스도께 나아옴', '에드워드 두베 장로', '그리스도께 오라'],
  ['정직과 덕', '쿠엔틴 L. 쿡 장로', '정직과 덕은 행복으로 이끈다'],
  ['화평', '알프레드 쿵구 장로', '화평케 하는 자의 언어'],
  ['회개', '시루 슈마일 장로', '너희의 행위를 살필지니라, 오늘부터는 내가 복을 주리라'],
  ['모든 사람을 위한 복음', '댈린 H. 옥스 회장', '예수 그리스도의 복음은 모든 사람을 위한 것입니다'],
  ['일치', '디이터 F. 우흐트도르프 회장', '그리스도를 중심으로 한 일치'],
  ['하나님이 함께하심', '안드레아 무뇨스 스파나우스 자매', '하나님은 여러분 곁에 계십니다'],
];

const NOT_PERSON_RE = /간증|대회|스테이크|발표|선교사|장로님|성찬식|방문|\?/;
const NOTICE_ROLES = [
  ['talk5', '5분 말씀', true],
  ['talk10', '10분 말씀', true],
  ['lastSpeaker', '마지막 말씀', true],
  ['openingPrayer', '개회기도', false],
  ['closingPrayer', '폐회기도', false],
];

// ───────── 실행 함수 ─────────

/** 처음 한 번: ① 매주 월요일 10시, ② 매달 25일 9시 자동 실행 예약 */
function installMonthlyTriggers() {
  const jobs = ['sendTalkNotices', 'sendOrganistList'];
  ScriptApp.getProjectTriggers()
    .filter(t => jobs.includes(t.getHandlerFunction()))
    .forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('sendTalkNotices').timeBased().onWeekDay(ScriptApp.WeekDay.MONDAY).atHour(10).create();
  ScriptApp.newTrigger('sendOrganistList').timeBased().onMonthDay(25).atHour(9).create();
  console.log('예약 완료: 매주 월요일 10시(말씀·기도 안내), 매달 25일 9시(반주표)');
}

function testTalkNotices() { sendTalkNotices(new Date()); }
function testOrganistList() { sendOrganistList(new Date()); }
function makeYearDraft() { buildYearDraft_(DRAFT_YEAR); }

// ───────── ① 말씀·기도 안내 / 리마인드 ─────────

function sendTalkNotices(base) {
  const today = base instanceof Date ? base : new Date();
  const thisSunday = upcomingSunday_(today);
  const ahead = plusDays_(thisSunday, 7 * NOTICE_WEEKS_AHEAD);
  const notices = noticeMessages_(ahead, 'notice');
  const reminds = noticeMessages_(thisSunday, 'remind');
  if (!notices.length && !reminds.length) return console.log('보낼 안내가 없습니다.');

  const block = (title, list) => list.length
    ? `■ ${title}\n\n` + list.join('\n\n────────────\n\n') + '\n\n'
    : `■ ${title}\n\n(보낼 분 없음)\n\n`;
  const body = '아래 문구를 길게 눌러 복사해서 각자 개인톡으로 보내 주세요.\n\n'
    + block(`${fmt_(ahead, 'M/d')} 주제 안내 (${NOTICE_WEEKS_AHEAD}주 전)`, notices)
    + block(`${fmt_(thisSunday, 'M/d')} 리마인드 (이번 주)`, reminds);
  report_(`[말씀·기도 안내] ${fmt_(ahead, 'M/d')} 주제 안내 · ${fmt_(thisSunday, 'M/d')} 리마인드`, body);
}

function noticeMessages_(sunday, kind) {
  const m = getMeeting_(sunday);
  if (!m || m.special) return [];
  const date = fmt_(sunday, 'M월 d일');
  const t = topicFor_(sunday);
  const topicLines = t.length > 1
    ? `📖 말씀 주제: ${t[0]}\n참고 말씀: ${t[1]} 「${t[2]}」\n(복음 자료실 앱 → 연차 대회 → 2026년 10월)`
    : `📖 말씀 주제: ${t[0]}`;

  return NOTICE_ROLES
    .filter(([k]) => m[k] && !NOT_PERSON_RE.test(m[k]))
    .map(([k, role, isTalk]) => {
      const name = person_(m[k]);
      if (kind === 'notice') {
        return isTalk
          ? `${name}, 안녕하세요 🙂 ${SENDER}입니다.\n${date} 성찬식 ${role}${josa_(role, '을', '를')} 맡아 주셔서 감사합니다.\n\n${topicLines}\n\n준비하시다 어려운 점이 있으면 언제든 연락 주세요!`
          : `${name}, 안녕하세요 🙂 ${SENDER}입니다.\n${date} 성찬식 ${role}${josa_(role, '을', '를')} 부탁드립니다. 감사합니다!`;
      }
      return `${name}, 안녕하세요 🙂 ${SENDER}입니다.\n이번 주 일요일(${date}) 성찬식 ${role} 순서 다시 한번 안내드립니다 🙏`
        + (isTalk ? `\n\n${topicLines}` : '')
        + '\n\n준비하시다 어려운 점이 있으면 편하게 연락 주세요.';
    });
}

/** 그 주일의 말씀 주제: 시트 '말씀 주제' 열 → 없으면 TALK_TOPICS 를 주마다 돌아가며 */
function topicFor_(sunday) {
  const tab = source_().getSheetByName(SCHEDULE_TAB.replace('{년}', sunday.getFullYear()));
  const row = tab && readTable_(tab).find(r => r.md === fmt_(sunday, 'MM-dd'));
  const own = row && (row.get('말씀 주제')[0] || row.get('주제')[0]);
  if (own) return [own];
  const week = Math.floor((sunday - new Date(2026, 0, 4)) / (7 * 86400000));
  return TALK_TOPICS[((week % TALK_TOPICS.length) + TALK_TOPICS.length) % TALK_TOPICS.length];
}

/** 받침이 있으면 a(을), 없으면 b(를) */
function josa_(word, a, b) {
  const code = word.charCodeAt(word.length - 1) - 0xac00;
  return code >= 0 && code <= 11171 && code % 28 ? a : b;
}

// ───────── ② 반주자 톡방용 한 달 찬송·반주표 이미지 ─────────

function sendOrganistList(base) {
  const today = base instanceof Date ? base : new Date();
  const first = new Date(today.getFullYear(), today.getMonth() + 1, 1); // 다음 달 1일
  const month = first.getMonth();
  const header = ['날짜', '지휘', '반주', '개회찬송', '성찬찬송', '회중찬송', '폐회찬송'];
  const rows = [];
  for (let d = upcomingSunday_(first); d.getMonth() === month; d = plusDays_(d, 7)) {
    const m = getMeeting_(d);
    const date = fmt_(d, 'M/d');
    if (!m) rows.push([date, '(시트에 없음)', '', '', '', '', '']);
    else if (m.special) rows.push([date, m.special, '', '', '', '', '']);
    else rows.push([date, person_(m.chorister, '자매님'), person_(m.organist, '자매님'),
      m.hymns.openingHymn, m.hymns.sacramentHymn, m.fast ? '(금식간증)' : m.hymns.restHymn, m.hymns.closingHymn]);
  }
  const title = `${fmt_(first, 'yyyy년 M월')} 성찬식 지휘·반주·찬송표`;
  const image = tableImage_(title, header, rows);
  const text = rows.map(r => `${r[0]}  지휘 ${r[1]} · 반주 ${r[2]}\n   ${r.slice(3).filter(Boolean).join(' / ')}`).join('\n');
  MailApp.sendEmail({
    to: Session.getEffectiveUser().getEmail(),
    subject: `[반주표] ${title}`,
    body: `첨부한 이미지를 저장해서 반주자 톡방에 올려 주세요.\n\n${text}`,
    attachments: [image],
  });
  console.log(`[반주표] ${title} 메일 보냄\n${text}`);
}

/** 구글 슬라이드에 표를 그려 PNG 이미지로 내보내고, 슬라이드는 휴지통으로 */
function tableImage_(title, header, rows) {
  const pres = SlidesApp.create(title);
  const slide = pres.getSlides()[0];
  slide.getPageElements().forEach(e => e.remove());
  const W = pres.getPageWidth();
  const box = slide.insertTextBox(title, 20, 10, W - 40, 34);
  box.getText().getTextStyle().setFontSize(18).setBold(true);
  const table = slide.insertTable(rows.length + 1, header.length, 20, 50, W - 40, (rows.length + 1) * 28);
  [header, ...rows].forEach((r, i) => r.forEach((v, j) => {
    const cell = table.getCell(i, j);
    cell.getText().setText(String(v || ' '));
    cell.getText().getTextStyle().setFontSize(i === 0 ? 10 : 9).setBold(i === 0 || j === 0);
    if (i === 0) cell.getFill().setSolidFill('#E8EEF7');
  }));
  pres.saveAndClose();

  const url = `https://docs.google.com/presentation/d/${pres.getId()}/export/png?pageid=${slide.getObjectId()}`;
  const blob = UrlFetchApp.fetch(url, { headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() } })
    .getBlob().setName(`${title}.png`);
  DriveApp.getFileById(pres.getId()).setTrashed(true);
  return blob;
}

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
 */
function buildYearDraft_(year) {
  const ss = source_();
  const prevTab = ss.getSheetByName(SCHEDULE_TAB.replace('{년}', year - 1));
  if (!prevTab) throw new Error(`'${year - 1}년 성찬식' 탭이 없습니다.`);
  const COLS = 20; // A~S 는 작년 탭과 같은 모양, T = 비고

  const name = `${year}년 성찬식 (초안)`;
  let sheet = ss.getSheetByName(name);
  if (sheet) {
    sheet.getDataRange().breakApart();
    sheet.clear();
  } else {
    sheet = ss.insertSheet(name);
  }
  prevTab.getRange(1, 1, 1, COLS - 1).copyTo(sheet.getRange(1, 1)); // 제목 행 (병합·서식 그대로)
  sheet.getRange(1, COLS).setValue('비고');
  for (let c = 1; c < COLS; c++) sheet.setColumnWidth(c, prevTab.getColumnWidth(c));

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

  const rows = [], merges = [];
  let meetingNo = 0;
  for (let d = upcomingSunday_(new Date(year, 0, 1)), w = 0; d.getFullYear() === year; d = plusDays_(d, 7), w++) {
    const month = d.getMonth() + 1, nth = Math.ceil(d.getDate() / 7);
    const isLast = plusDays_(d, 7).getMonth() !== d.getMonth();
    const r = rows.length + 2; // 시트 행 번호
    const row = new Array(COLS).fill('');
    row[2] = fmt_(d, 'MM/dd');

    const special = (month === 4 || month === 10) && nth === 2 ? '연차대회 시청'
      : (month === 3 || month === 9) && nth === 2 ? '스테이크 대회' : '';
    if (special) {
      row[3] = special;
      row[19] = special === '스테이크 대회' ? '날짜 확인 필요' : '';
      merges.push([r, 4, 1, 16]);
      rows.push(row);
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
      row[6] = row[7] = row[8] = fast ? '금식간증' : program;
      merges.push([r, 7, 1, 3]);
      if (program) row[19] = '확인 필요';
    } else {
      row[6] = assign('talk5', g1);
      row[7] = assign('talk10', g2);
      row[8] = nth === 2 ? '스테이크' : assign('last', g1);
    }
    row[9] = assign('open', g2);
    row[10] = assign('close', g1);

    // 찬송
    const isEaster = fmt_(d, 'MM-dd') === easter;
    const xmas = month === 12;
    [row[11], row[12]] = h(isEaster ? 122 : xmas ? hymn.xmas() : hymn.open());
    [row[13], row[14]] = h(hymn.sacrament());
    [row[15], row[16]] = fast ? ['', ''] : h(isEaster ? 123 : xmas ? hymn.xmas() : hymn.rest());
    [row[17], row[18]] = h(isEaster ? 124 : xmas ? hymn.xmas() : hymn.close());
    if (isEaster) row[19] = '부활절';
    rows.push(row);
  }

  // 년도·분기 칸 (작년처럼 병합)
  rows[0][0] = String(year);
  merges.push([2, 1, rows.length, 1]);
  [0, 1, 2, 3].forEach(q => {
    const idx = rows.map((row, i) => i).filter(i => Math.floor((Number(rows[i][2].slice(0, 2)) - 1) / 3) === q);
    if (!idx.length) return;
    rows[idx[0]][1] = `${q + 1}분기`;
    merges.push([idx[0] + 2, 2, idx.length, 1]);
  });

  sheet.getRange(2, 3, rows.length, 1).setNumberFormat('@'); // 날짜를 글자 그대로 (01/03)
  sheet.getRange(2, 1, rows.length, COLS).setValues(rows);
  merges.forEach(([r, c, nr, nc]) => sheet.getRange(r, c, nr, nc).merge());
  sheet.getRange(2, 1, rows.length, COLS).setVerticalAlignment('middle');

  const counts = people.filter(p => p.total || p.wTotal).sort((a, b) => b.total - a.total)
    .map(p => `${p.name} ${p.total}(작년 ${p.wTotal})`).join(', ');
  report_(`[순서표 초안] ${year}년 성찬식 (초안) 탭을 만들었습니다`,
    `사회: ${bishopric.join(' → ')}\n지휘: 첫째 주 ${music.choristerFirst} / 그 외 ${music.choristerOther}\n반주: ${music.organists.join(', ')} 번갈아\n\n`
    + `말씀·기도 배정 횟수: ${counts}\n\n'비고' 열의 '확인 필요' 칸을 확인하고, 다 고친 뒤 탭 이름을 '${year}년 성찬식'으로 바꾸면 아젠다 자동화가 이 탭을 읽습니다.`,
    `${ss.getUrl()}#gid=${sheet.getSheetId()}`);
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
