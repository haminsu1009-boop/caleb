/**
 * vessel-gas/Parser.gs
 * 자유 텍스트에서 모선명 / 항차번호를 뽑아낸다 (Python vessel/parser.py 포팅).
 *
 * 지원 형태:
 *   1. "HMM 코펜하겐 / 0526E"          — 구분자로 명확히 분리
 *   2. "모선명: HMM 코펜하겐, 항차: 0526E" — 키워드로 명시
 *   3. "HMM 코펜하겐호 0526E 어디야?"    — 항차번호 패턴 토큰 자동 탐지
 */

const VOYAGE_RE_ = /^\d{2,5}[A-Za-z]{0,2}$/;
const PARSE_KEYWORDS_ = ['모선명', '모선', '선명', '선박명', '항차번호', '항차', 'voyage', 'vessel'];
const IGNORE_TOKENS_ = ['어디', '어디쯤', '언제', '지금', '위치', '조회', '알려줘', '와요', '오나요', '도착'];

function stripKeywords_(text) {
  let out = text;
  PARSE_KEYWORDS_.forEach(kw => {
    out = out.replace(new RegExp(kw + '\\s*[:：]?\\s*', 'gi'), ' ');
  });
  return out;
}

function cleanName_(name) {
  return name.trim().replace(/(호|은|는|이|가|을|를)$/, '').trim();
}

/** parseQuery(text) -> {vesselName: string|null, voyageNo: string|null} */
function parseQuery(text) {
  const raw = (text || '').trim();
  if (!raw) return { vesselName: null, voyageNo: null };

  // 1) 구분자로 명확히 나뉘는 경우
  const seps = ['/', ',', '，', '-', '|'];
  for (let i = 0; i < seps.length; i++) {
    const sep = seps[i];
    const idx = raw.indexOf(sep);
    if (idx === -1) continue;
    const left = stripKeywords_(raw.slice(0, idx)).trim();
    const right = stripKeywords_(raw.slice(idx + 1)).trim();
    const rightFirstTok = right.split(/\s+/)[0] || '';
    if (VOYAGE_RE_.test(rightFirstTok.toUpperCase())) {
      return { vesselName: cleanName_(left) || null, voyageNo: rightFirstTok.toUpperCase() };
    }
  }

  // 2) 키워드 제거 후 항차번호 패턴 토큰 탐지
  const cleaned = stripKeywords_(raw);
  const tokens = cleaned.split(/\s+/).filter(Boolean);
  let voyageNo = null, voyageIdx = -1;
  tokens.forEach((tok, i) => {
    const t = tok.replace(/[?!.,()\[\]]/g, '');
    if (VOYAGE_RE_.test(t.toUpperCase()) && !/^[A-Za-z]+$/.test(t)) {
      voyageNo = t.toUpperCase();
      voyageIdx = i;
    }
  });

  if (voyageIdx !== -1) {
    const nameTokens = tokens.filter((t, i) => i !== voyageIdx && IGNORE_TOKENS_.indexOf(t) === -1);
    const vesselName = cleanName_(nameTokens.join(' '));
    return { vesselName: vesselName || null, voyageNo: voyageNo };
  }

  // 3) 항차번호를 못 찾음 — 전체를 모선명 후보로
  return { vesselName: cleanName_(cleaned) || null, voyageNo: null };
}

// ── /update 명령 파싱 ────────────────────────────────────────────
const UPDATE_FIELD_ALIASES_ = {
  '터미널': 'terminal', 'terminal': 'terminal',
  '선석': 'berth', 'berth': 'berth',
  'eta': 'eta', '입항': 'eta',
  'etb': 'etb', '접안': 'etb',
  'etd': 'etd', '출항': 'etd',
  '상태': 'status', 'status': 'status',
};

/** parseUpdateArgs(args) -> {vesselName, voyageNo, fields} 또는 형식이 틀리면 null
 * 형식: "선명, 항차 | 키=값 | 키=값 ..." */
function parseUpdateArgs(args) {
  const parts = args.split('|').map(s => s.trim()).filter(Boolean);
  if (parts.length === 0 || parts[0].indexOf(',') === -1) return null;

  const commaIdx = parts[0].indexOf(',');
  const vesselName = parts[0].slice(0, commaIdx).trim();
  const voyageNo = parts[0].slice(commaIdx + 1).trim();
  if (!vesselName || !voyageNo) return null;

  const fields = {};
  for (let i = 1; i < parts.length; i++) {
    const eqIdx = parts[i].indexOf('=');
    if (eqIdx === -1) continue;
    const k = parts[i].slice(0, eqIdx).trim().toLowerCase();
    const v = parts[i].slice(eqIdx + 1).trim();
    const canon = UPDATE_FIELD_ALIASES_[k];
    if (canon && v) fields[canon] = v;
  }
  if (Object.keys(fields).length === 0) return null;
  return { vesselName: vesselName, voyageNo: voyageNo, fields: fields };
}
