// ═══════════════ 개인톡 안내 문구 (Code.gs 맨 아래에 붙여넣기 — 위의 같은 이름 함수를 대신함) ═══════════════

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
