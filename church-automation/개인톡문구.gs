// ═══════════════ 개인톡 안내 문구 (Code.gs 맨 아래에 붙여넣기 — 위의 같은 이름 함수를 대신함) ═══════════════

const CONFERENCE_URL = 'https://www.churchofjesuschrist.org/study/general-conference/2026/10?lang=kor';

// [말씀 제목(=주제), 말씀자, 링크] — 링크를 비워 두면 위 CONFERENCE_URL(2026년 10월 연차대회 목록)로 연결
// 복음자료실 앱에서 말씀 → 공유 → 링크 복사 후 '' 안에 붙여넣으면 그 말씀으로 바로 연결됩니다.
const TALK_LINKS = [
  ['주님의 거룩한 집에서 주님께 나아오십시오', '게리 W. 공 장로', ''],
  ['간증이라는 은사', '제라드 코세 장로', ''],
  ['선지자, 선견자, 계시자', '바이앙기나 시카헤마 장로', ''],
  ['예수 그리스도는 위대한 구원자이십니다', '케빈 J. 해서웨이 장로', ''],
  ['너의 선교의 때가 이르렀느니라', '션 더글러스 감독', ''],
  ['오, 지혜로우라', 'D. 토드 크리스토퍼슨 회장', ''],
  ['그들이 나를 믿기까지 얼마나 걸리겠느냐', '데일 G. 렌런드 장로', ''],
  ['십일조와 헌금으로 주님을 신뢰함', '파트리시오 M. 주프라 장로', ''],
  ['성약에 담긴 하나님의 무한한 권능', '제레마이아 J. 모건 장로', ''],
  ['난 하나님의 자녀', '허치 U. 팔레 장로', ''],
  ['예수님은 우리를 일으키시려 살아 계십니다', '패트릭 키어런 장로', ''],
  ['성신이 주시는 위안', '매튜 J. 아이어링 장로', ''],
  ['예수님처럼 사랑하십시오', '로널드 A. 래스번드 장로', ''],
  ['두려워 말라 내가 너와 함께 함이라', '헨리 B. 아이어링 회장', ''],
  ['예수 그리스도를 믿는 신앙에서 오는 용기', '닐 L. 앤더슨 장로', ''],
  ['그리스도께 오라', '에드워드 두베 장로', ''],
  ['정직과 덕은 행복으로 이끈다', '쿠엔틴 L. 쿡 장로', ''],
  ['화평케 하는 자의 언어', '알프레드 쿵구 장로', ''],
  ['예수 그리스도의 복음은 모든 사람을 위한 것입니다', '댈린 H. 옥스 회장', ''],
  ['그리스도를 중심으로 한 일치', '디이터 F. 우흐트도르프 회장', ''],
  ['하나님은 여러분 곁에 계십니다', '안드레아 무뇨스 스파나우스 자매', ''],
];

// [역할 키, 순서 이름, 말씀인지]
const TALK_ORDER = [
  ['talk5', '첫 번째 순서 5분 말씀', true],
  ['talk10', '두 번째 순서 10분 말씀', true],
  ['lastSpeaker', '마지막 순서 말씀', true],
  ['openingPrayer', '개회기도', false],
  ['closingPrayer', '폐회기도', false],
];

function noticeMessages_(sunday, kind) {
  const m = getMeeting_(sunday);
  if (!m || m.special) return [];
  const date = fmt_(sunday, 'M월 d일');
  const week = Math.floor((sunday - new Date(2026, 0, 4)) / (7 * 86400000));

  let n = 0; // 같은 주 말씀하시는 분들은 서로 다른 말씀을 참고하도록
  return TALK_ORDER
    .filter(([k]) => m[k] && !NOT_PERSON_RE.test(m[k]))
    .map(([k, order, isTalk]) => {
      const name = person_(m[k], '');
      const hello = `${name}, 안녕하세요. ${SENDER}입니다.\n`;
      const when = kind === 'remind' ? `이번 주 일요일(${date})` : date;
      if (!isTalk) {
        return hello + `${when} 성찬식 ${order}${josa_(order, '을', '를')} 부탁드립니다. 감사합니다 🙏`;
      }
      const [title, , link] = talkFor_(sunday, week * 3 + n++);
      return hello
        + `${when} ${order} 주제는 '${title}'이며, 참고하실 연차대회 링크 공유드립니다.\n`
        + `${link || CONFERENCE_URL}\n\n`
        + '예수 그리스도가 중심이 되며, 설득과 권유가 아닌 본인의 간증을 전해주시면 감사하겠습니다. 🙏';
    });
}

/** 시트에 '말씀 주제' 열이 있으면 그 값, 없으면 TALK_LINKS 를 돌아가며 */
function talkFor_(sunday, i) {
  const tab = source_().getSheetByName(SCHEDULE_TAB.replace('{년}', sunday.getFullYear()));
  const row = tab && readTable_(tab).find(r => r.md === fmt_(sunday, 'MM-dd'));
  const own = row && (row.get('말씀 주제')[0] || row.get('주제')[0]);
  if (own) return [own, '', ''];
  return TALK_LINKS[((i % TALK_LINKS.length) + TALK_LINKS.length) % TALK_LINKS.length];
}
