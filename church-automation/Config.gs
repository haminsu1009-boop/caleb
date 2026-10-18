/**
 * 교회 업무 자동화 — 설정
 * 시간·시트 이름·성찬식 순서는 여기만 고치면 됩니다.
 */
const CONFIG = {
  SHEETS: {
    SETTINGS: '설정',
    SERMON: '주간말씀',
    PRAYER: '기도제목',
    COMMUNION: '성찬식',
  },
  HEADERS: {
    SETTINGS: ['항목', '값'],
    SERMON: ['주일날짜', '말씀주제', '성경본문', '핵심구절', '설교자', '주제전송'],
    PRAYER: ['등록일', '요청자', '기도제목', '공개', '상태'],
    COMMUNION: ['주일날짜', '인도', '떡기도', '잔기도', '분병분잔위원', '찬송', '준비담당', '비고'],
  },
  // 자동 실행 시각 (한국 시간)
  SCHEDULE: {
    WEEKLY_TOPIC: { day: ScriptApp.WeekDay.SATURDAY, hour: 20 },     // 토요일 저녁: 내일 말씀 주제
    DAILY_REMINDER: { hour: 7 },                                      // 매일 아침: 말씀·기도 리마인드
    COMMUNION_AGENDA: { day: ScriptApp.WeekDay.THURSDAY, hour: 9 },  // 목요일 아침: 성찬식 문서 갱신
  },
  MAX_PRAYERS_PER_DAY: 5, // 하루에 돌아가며 보여줄 기도제목 수
};

// 성찬식 순서 — detail/owner 는 고정 문구, detailCol/ownerCol 은 '성찬식' 시트의 열 이름
const COMMUNION_ORDER = [
  { step: '예배로 부름 · 찬송', detailCol: '찬송', ownerCol: '인도' },
  { step: '성찬 제정의 말씀', detail: '고린도전서 11:23-26', ownerCol: '인도' },
  { step: '떡을 위한 기도', ownerCol: '떡기도' },
  { step: '분병', ownerCol: '분병분잔위원' },
  { step: '잔을 위한 기도', ownerCol: '잔기도' },
  { step: '분잔', ownerCol: '분병분잔위원' },
  { step: '감사 기도 · 폐회 찬송', ownerCol: '인도' },
];

const COMMUNION_CHECKLIST = [
  '떡 준비 (수량 확인)',
  '포도주스 준비',
  '성찬기 세척 · 성찬보 준비',
  '분병분잔위원 연락 및 확인',
  '순서지 / 자막 반영',
];
