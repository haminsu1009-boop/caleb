/**
 * vessel-gas/Directory.gs
 * 모선명 → IMO/MMSI 조회 (구글 시트 "VesselDirectory" 탭 기반)
 *
 * 시트 컬럼: Names(콤마로 여러 별칭) | IMO | MMSI | Note
 * 예) "EVER GIVEN, 에버기븐" | 9811000 | | 예시 데이터
 *
 * AIS API는 선박명 자유검색을 지원하지 않아(IMO/MMSI만 가능) 이 매핑표가
 * 필요하다 — Python 버전(vessel/directory.py)과 같은 이유.
 */

function normalizeName_(s) {
  return String(s || '')
    .toUpperCase()
    .replace(/[^A-Z0-9가-힣 ]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function loadDirectoryEntries_() {
  const sheet = getOrCreateSheet_('VesselDirectory', ['Names', 'IMO', 'MMSI', 'Note']);
  const rows = sheet.getDataRange().getValues();
  const entries = [];
  for (let i = 1; i < rows.length; i++) {
    const [namesCell, imo, mmsi] = rows[i];
    if (!namesCell) continue;
    const names = String(namesCell).split(',').map(s => s.trim()).filter(Boolean);
    if (names.length === 0) continue;
    entries.push({ names: names, imo: imo ? String(imo) : '', mmsi: mmsi ? String(mmsi) : '' });
  }
  return entries;
}

/** resolveVessel(name) -> {entry: {...}|null, candidates: [...]} */
function resolveVessel(vesselName) {
  const entries = loadDirectoryEntries_();
  if (!vesselName || entries.length === 0) return { entry: null, candidates: [] };

  const target = normalizeName_(vesselName);
  const aliasIndex = []; // {norm, entry}
  entries.forEach(e => e.names.forEach(alias => aliasIndex.push({ norm: normalizeName_(alias), entry: e })));

  // 정확 일치
  const exact = aliasIndex.find(a => a.norm === target);
  if (exact) return { entry: exact.entry, candidates: [] };

  // 부분 포함 매칭 (양방향)
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
