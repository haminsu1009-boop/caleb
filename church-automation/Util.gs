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
