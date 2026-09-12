/**
 * vessel-gas/Directory.gs
 * 모선명 → IMO/MMSI (선택 기능 — 실시간 AIS 위치까지 보고 싶을 때만 필요).
 * 등록 안 해도 봇은 정상 동작한다(터미널/선사 스케줄+수동입력 알림만으로도 충분) —
 * AIS는 "있으면 위치까지 더 보여주는" 보너스일 뿐이다.
 *
 * 저장: PropertiesService 키 VESSEL_DIRECTORY, JSON 배열
 *   [{"names": ["EVER GIVEN", "에버기븐"], "imo": "9811000", "mmsi": ""}]
 * 등록은 관리자 명령 /directory (Setup.gs의 addDirectoryEntry 참고)이나
 * 스크립트 편집기에서 직접 addDirectoryEntry()를 실행해서 추가한다.
 */

function normalizeName_(s) {
  return String(s || '')
    .toUpperCase()
    .replace(/[^A-Z0-9가-힣 ]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function loadDirectoryEntries_() {
  return getJson_('VESSEL_DIRECTORY', []);
}

function addDirectoryEntry(names, imo, mmsi) {
  const entries = loadDirectoryEntries_();
  entries.push({ names: names, imo: imo || '', mmsi: mmsi || '' });
  setJson_('VESSEL_DIRECTORY', entries);
}

/** resolveVessel(name) -> {entry: {...}|null, candidates: [...]} */
function resolveVessel(vesselName) {
  const entries = loadDirectoryEntries_();
  if (!vesselName || entries.length === 0) return { entry: null, candidates: [] };

  const target = normalizeName_(vesselName);
  const aliasIndex = [];
  entries.forEach(e => e.names.forEach(alias => aliasIndex.push({ norm: normalizeName_(alias), entry: e })));

  const exact = aliasIndex.find(a => a.norm === target);
  if (exact) return { entry: exact.entry, candidates: [] };

  const hits = aliasIndex.filter(a => target && (target.indexOf(a.norm) !== -1 || a.norm.indexOf(target) !== -1));
  const uniqueEntries = dedupEntries_(hits.map(h => h.entry));
  if (uniqueEntries.length === 1) return { entry: uniqueEntries[0], candidates: [] };
  if (uniqueEntries.length > 1) return { entry: null, candidates: uniqueEntries };

  return { entry: null, candidates: [] };
}

function dedupEntries_(entries) {
  const seen = {}, out = [];
  entries.forEach(e => {
    const key = e.imo || e.mmsi || e.names[0];
    if (!seen[key]) { seen[key] = true; out.push(e); }
  });
  return out;
}
