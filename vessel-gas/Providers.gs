/**
 * vessel-gas/Providers.gs
 * AIS(실시간 위치) 조회 — VesselFinder 실연동 + 키 없을 때 자동 폴백하는 Mock
 * (Python vessel/providers.py 포팅)
 */

const NAVSTAT_ = {
  0: '항해중(기관사용)', 1: '정박중', 2: '조종불능', 3: '조종제한',
  4: '흘수제약', 5: '계류중', 6: '좌초', 7: '어로중', 8: '범주항해중',
  14: 'AIS-SART(조난)', 15: '미정의',
};

function getAisPosition(imo, mmsi, name) {
  const cfg = getConfig_();
  if (cfg.vesselFinderKey && (imo || mmsi)) {
    try {
      const pos = fetchVesselFinderPosition_(imo, mmsi, cfg.vesselFinderKey);
      if (pos) return pos;
    } catch (e) {
      console.error('VesselFinder 조회 오류: ' + e);
    }
  }
  return mockPosition_(imo, mmsi, name);
}

function fetchVesselFinderPosition_(imo, mmsi, apiKey) {
  const params = ['userkey=' + encodeURIComponent(apiKey), 'extradata=voyage,master'];
  if (imo) params.push('imo=' + encodeURIComponent(imo));
  if (mmsi) params.push('mmsi=' + encodeURIComponent(mmsi));
  const url = 'https://api.vesselfinder.com/vessels?' + params.join('&');
  const resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
  if (resp.getResponseCode() !== 200) return null;
  const data = JSON.parse(resp.getContentText());
  if (!data || data.length === 0) return null;

  const item = data[0];
  const ais = item.AIS || {};
  const voyage = item.VOYAGE || {};
  return {
    name: ais.NAME, imo: String(ais.IMO || imo || ''), mmsi: String(ais.MMSI || mmsi || ''),
    lat: ais.LATITUDE, lon: ais.LONGITUDE, speedKn: ais.SPEED, courseDeg: ais.COURSE,
    navStatus: NAVSTAT_[ais.NAVSTAT] || String(ais.NAVSTAT || ''),
    destination: ais.DESTINATION || voyage.DESTINATION || '',
    etaUtc: ais.ETA || voyage.ETA || ais.ETA_AIS || '',
    lastReportUtc: ais.TIMESTAMP || '',
    source: 'vesselfinder',
  };
}

// ── Mock: 데모용 결정론적 가짜 위치 (부산→롱비치 항로 근사) ─────────
const MOCK_ROUTE_ = [
  [35.10, 129.04], [33.6, 140.0], [40.0, 175.0], [45.0, -170.0], [40.0, -140.0], [33.75, -118.19],
];

function hashSeed_(str) {
  let h = 1779033703 ^ str.length;
  for (let i = 0; i < str.length; i++) {
    h = Math.imul(h ^ str.charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  return function () {
    h = Math.imul(h ^ (h >>> 16), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    h ^= h >>> 16;
    return (h >>> 0) / 4294967296;
  };
}

function mockPosition_(imo, mmsi, name) {
  const seedKey = imo || mmsi || name || 'UNKNOWN';
  const rnd = hashSeed_(seedKey);

  const progress = rnd();
  const idxF = progress * (MOCK_ROUTE_.length - 1);
  const i = Math.min(Math.floor(idxF), MOCK_ROUTE_.length - 2);
  const frac = idxF - i;
  const lat = MOCK_ROUTE_[i][0] + (MOCK_ROUTE_[i + 1][0] - MOCK_ROUTE_[i][0]) * frac;
  const lon = MOCK_ROUTE_[i][1] + (MOCK_ROUTE_[i + 1][1] - MOCK_ROUTE_[i][1]) * frac;

  const eta = new Date(Date.now() + Math.round((1 - progress) * 14 * 10) / 10 * 86400000);
  const lastReport = new Date(Date.now() - (2 + Math.floor(rnd() * 43)) * 60000);
  const seedInt = Math.floor(rnd() * 10000000);

  return {
    name: name || ('MOCK VESSEL ' + seedKey),
    imo: imo || ('MOCK-' + String(seedInt).padStart(7, '0')),
    mmsi: mmsi || '',
    lat: Math.round(lat * 10000) / 10000,
    lon: Math.round((((lon + 180) % 360) - 180) * 10000) / 10000,
    speedKn: Math.round((11 + rnd() * 8) * 10) / 10,
    courseDeg: Math.round(rnd() * 359),
    navStatus: NAVSTAT_[0],
    destination: 'LONG BEACH, US',
    etaUtc: Utilities.formatDate(eta, 'UTC', 'yyyy-MM-dd HH:mm') + ' UTC',
    lastReportUtc: Utilities.formatDate(lastReport, 'UTC', 'yyyy-MM-dd HH:mm') + ' UTC',
    source: 'mock',
  };
}
