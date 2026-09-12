/**
 * vessel-gas/Sheet.gs
 * 이 스크립트가 바인딩된 구글 시트의 탭을 관리하는 공용 헬퍼.
 * 시트가 없으면 헤더까지 자동으로 만들어준다(최초 실행 시 initSheets() 참고).
 */

function getOrCreateSheet_(name, headers) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(name);
  if (!sheet) {
    sheet = ss.insertSheet(name);
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
    sheet.setFrozenRows(1);
  }
  return sheet;
}

/** ManualOverrides 탭: VesselName | VoyageNo | 터미널 | 선석 | ETA | ETB | ETD | 상태 | UpdatedAt | UpdatedBy */
const MANUAL_HEADERS_ = ['VesselName', 'VoyageNo', '터미널', '선석', 'ETA', 'ETB', 'ETD', '상태', 'UpdatedAt', 'UpdatedBy'];
const MANUAL_TTL_HOURS_ = 72; // 지나면 자동으로 무시(오래된 정보 방지)

function manualKey_(vesselName, voyageNo) {
  return normalizeName_(vesselName) + '|' + normalizeName_(voyageNo);
}

function findManualRow_(sheet, vesselName, voyageNo) {
  const data = sheet.getDataRange().getValues();
  const key = manualKey_(vesselName, voyageNo);
  for (let i = 1; i < data.length; i++) {
    if (manualKey_(data[i][0], data[i][1]) === key) return i + 1; // 1-based row number
  }
  return -1;
}

function setManualOverride(vesselName, voyageNo, fields, updatedBy) {
  const sheet = getOrCreateSheet_('ManualOverrides', MANUAL_HEADERS_);
  const rowIdx = findManualRow_(sheet, vesselName, voyageNo);
  const now = new Date();
  const row = [
    vesselName, voyageNo,
    fields.terminal || '', fields.berth || '', fields.eta || '', fields.etb || '', fields.etd || '', fields.status || '',
    now, updatedBy || '',
  ];
  // 기존 필드가 있으면 새로 들어온 것만 덮어쓰고 나머지는 유지
  if (rowIdx !== -1) {
    const existing = sheet.getRange(rowIdx, 1, 1, MANUAL_HEADERS_.length).getValues()[0];
    const merged = row.map((v, i) => (v === '' && i >= 2 && i <= 7) ? existing[i] : v);
    sheet.getRange(rowIdx, 1, 1, MANUAL_HEADERS_.length).setValues([merged]);
  } else {
    sheet.appendRow(row);
  }
}

function deleteManualOverride(vesselName, voyageNo) {
  const sheet = getOrCreateSheet_('ManualOverrides', MANUAL_HEADERS_);
  const rowIdx = findManualRow_(sheet, vesselName, voyageNo);
  if (rowIdx === -1) return false;
  sheet.deleteRow(rowIdx);
  return true;
}

/** getManualOverride(vesselName, voyageNo) -> row object 또는 null (TTL 지나면 null) */
function getManualOverride(vesselName, voyageNo) {
  const sheet = getOrCreateSheet_('ManualOverrides', MANUAL_HEADERS_);
  const rowIdx = findManualRow_(sheet, vesselName, voyageNo);
  if (rowIdx === -1) return null;
  const row = sheet.getRange(rowIdx, 1, 1, MANUAL_HEADERS_.length).getValues()[0];
  const updatedAt = row[8];
  const ageHours = (Date.now() - new Date(updatedAt).getTime()) / 3600000;
  if (ageHours > MANUAL_TTL_HOURS_) return null;
  return rowToManualObj_(row);
}

function listManualOverrides() {
  const sheet = getOrCreateSheet_('ManualOverrides', MANUAL_HEADERS_);
  const data = sheet.getDataRange().getValues();
  const now = Date.now();
  const out = [];
  for (let i = 1; i < data.length; i++) {
    const row = data[i];
    if (!row[0]) continue;
    const ageHours = (now - new Date(row[8]).getTime()) / 3600000;
    if (ageHours > MANUAL_TTL_HOURS_) continue;
    out.push(rowToManualObj_(row));
  }
  return out.sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt));
}

function rowToManualObj_(row) {
  return {
    vesselName: row[0], voyageNo: row[1],
    터미널: row[2], 선석: row[3], ETA: row[4], ETB: row[5], ETD: row[6], 상태: row[7],
    updatedAt: row[8], updatedBy: row[9],
  };
}
