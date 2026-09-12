/**
 * vessel-gas/Store.gs
 * 구글 시트 없이, 스크립트 자체 저장소(PropertiesService)에 데이터를 둔다.
 * 소규모 데이터(관리 대상 선박 수십 척, watch 등록 수십 건)에는 이걸로 충분하고,
 * 배포할 때 구글 시트를 따로 만들 필요가 없어진다.
 *
 * 저장 키:
 *   VESSEL_MANUAL     — 관리자가 /update로 넣은 터미널 정보 (선명|항차 → 값)
 *   VESSEL_WATCH      — 알림 등록 목록 (chatId + 선명 + 항차 배열)
 *   VESSEL_DIRECTORY  — (선택) 모선명 → IMO/MMSI, AIS 실위치 조회를 쓸 때만 필요
 */

function getJson_(key, defaultValue) {
  const raw = PropertiesService.getScriptProperties().getProperty(key);
  if (!raw) return defaultValue;
  try { return JSON.parse(raw); } catch (e) { return defaultValue; }
}

function setJson_(key, value) {
  PropertiesService.getScriptProperties().setProperty(key, JSON.stringify(value));
}

function manualKey_(vesselName, voyageNo) {
  return normalizeName_(vesselName) + '|' + normalizeName_(voyageNo);
}

// ── 수동입력(터미널 정보) ────────────────────────────────────────
const MANUAL_TTL_HOURS_ = 72; // 지나면 자동으로 무시(오래된 정보 방지)

function setManualOverride(vesselName, voyageNo, fields, updatedBy) {
  const all = getJson_('VESSEL_MANUAL', {});
  const key = manualKey_(vesselName, voyageNo);
  const existing = all[key] || {};
  all[key] = {
    vesselName: vesselName, voyageNo: voyageNo,
    터미널: fields.terminal || existing['터미널'] || '',
    선석: fields.berth || existing['선석'] || '',
    ETA: fields.eta || existing['ETA'] || '',
    ETB: fields.etb || existing['ETB'] || '',
    ETD: fields.etd || existing['ETD'] || '',
    상태: fields.status || existing['상태'] || '',
    updatedAt: new Date().toISOString(),
    updatedBy: updatedBy || '',
  };
  setJson_('VESSEL_MANUAL', all);
}

function deleteManualOverride(vesselName, voyageNo) {
  const all = getJson_('VESSEL_MANUAL', {});
  const key = manualKey_(vesselName, voyageNo);
  if (!all[key]) return false;
  delete all[key];
  setJson_('VESSEL_MANUAL', all);
  return true;
}

function getManualOverride(vesselName, voyageNo) {
  const all = getJson_('VESSEL_MANUAL', {});
  const entry = all[manualKey_(vesselName, voyageNo)];
  if (!entry) return null;
  const ageHours = (Date.now() - new Date(entry.updatedAt).getTime()) / 3600000;
  if (ageHours > MANUAL_TTL_HOURS_) return null;
  return entry;
}

function listManualOverrides() {
  const all = getJson_('VESSEL_MANUAL', {});
  const now = Date.now();
  return Object.values(all)
    .filter(e => (now - new Date(e.updatedAt).getTime()) / 3600000 <= MANUAL_TTL_HOURS_)
    .sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt));
}
