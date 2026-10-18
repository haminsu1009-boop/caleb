/** 공통 도우미 함수 (이름 끝의 _ 는 메뉴/실행 목록에 안 보이는 내부 함수라는 뜻) */

function getSheet_(name) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(name);
  if (!sheet) throw new Error(`'${name}' 시트가 없습니다. 메뉴에서 '초기 설정'을 먼저 실행하세요.`);
  return sheet;
}

/** 시트를 [{열이름: 값, _row: 행번호}, ...] 형태로 읽기 */
function readRows_(name) {
  const values = getSheet_(name).getDataRange().getValues();
  const headers = values.shift();
  return values
    .map((v, i) => {
      const row = { _row: i + 2 };
      headers.forEach((h, j) => (row[h] = v[j]));
      return row;
    })
    .filter(r => headers.some(h => r[h] !== ''));
}

function setCell_(name, rowNum, header, value) {
  const sheet = getSheet_(name);
  const col = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0].indexOf(header) + 1;
  if (col > 0) sheet.getRange(rowNum, col).setValue(value);
}

function getSetting_(key) {
  const row = readRows_(CONFIG.SHEETS.SETTINGS).find(r => r['항목'] === key);
  return row ? String(row['값']).trim() : '';
}

function setSetting_(key, value) {
  const row = readRows_(CONFIG.SHEETS.SETTINGS).find(r => r['항목'] === key);
  if (row) setCell_(CONFIG.SHEETS.SETTINGS, row._row, '값', value);
  else getSheet_(CONFIG.SHEETS.SETTINGS).appendRow([key, value]);
}

function fmt_(date, pattern) {
  return Utilities.formatDate(date, Session.getScriptTimeZone(), pattern);
}

/** 날짜 셀(Date) 이든 '2026.10.25' 같은 글자든 'yyyy-MM-dd' 로 통일 */
function toDateKey_(v) {
  if (v instanceof Date) return fmt_(v, 'yyyy-MM-dd');
  const m = String(v).match(/(\d{4})\D+(\d{1,2})\D+(\d{1,2})/);
  return m ? `${m[1]}-${m[2].padStart(2, '0')}-${m[3].padStart(2, '0')}` : '';
}

/** 오늘이 일요일이면 오늘, 아니면 다가오는 일요일 */
function upcomingSunday_(base) {
  const d = new Date(base);
  d.setDate(d.getDate() + ((7 - d.getDay()) % 7));
  return d;
}

/** 오늘이 일요일이면 오늘, 아니면 지난 일요일 */
function lastSunday_(base) {
  const d = new Date(base);
  d.setDate(d.getDate() - d.getDay());
  return d;
}

function findByDate_(sheetName, date) {
  const key = toDateKey_(date);
  return readRows_(sheetName).find(r => toDateKey_(r['주일날짜']) === key) || null;
}

/** null/undefined/false 를 뺀 줄들을 줄바꿈으로 합치기 ('' 는 빈 줄로 유지) */
function lines_(...items) {
  return items.filter(x => x !== null && x !== undefined && x !== false).join('\n');
}
