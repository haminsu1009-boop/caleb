/**
 * vessel-gas/Schedule.gs
 * 터미널/선사 스케줄 정보 — 직원 수동입력(구글 시트) 우선, 없으면 조회
 * 페이지 링크 폴백. Python vessel/terminal_providers.py + carrier_providers.py
 * 를 하나로 합친 GAS 버전(자동 스크래핑은 아직 없음 — README 참고).
 */

const TERMINAL_LIST_ = [
  { code: 'bpt', name: '신선대부두(BPT · CJ KBCT 운영)', url: 'https://info.bptc.co.kr/content/cg/frame/ship_no_frame_cg_kr.jsp?p_id=SHNO_CN_KR&snb_num=1&snb_div=service' },
  { code: 'hjnc', name: '한진신항만(HJNC)', url: 'https://www.hjnc.co.kr/esvc/vessel/voyageList' },
  { code: 'pnit', name: '부산신항국제터미널(PNIT · PSA)', url: 'https://www.pnitl.com/infoservice/vessel/vslScheduleList.jsp' },
  { code: 'hpnt', name: '현대부산신항만(HPNT)', url: 'https://www.hpnt.co.kr/infoservice/vessel/vslScheduleList.jsp' },
  { code: 'pnc', name: '부산신항만(PNC)', url: 'https://svc.pncport.com/' },
];

const CARRIER_LIST_ = [
  { code: 'hmm', name: 'HMM', url: 'https://www.hmm21.com/e-service/general/schedule/ScheduleMain/byVesselName.do' },
  { code: 'one', name: 'ONE(Ocean Network Express)', url: 'https://ecomm.one-line.com/ecom/CUP_HOM_3005.do?sessLocale=ko' },
  { code: 'sm', name: 'SM상선(SM Line)', url: 'https://esvc.smlines.com/smline/CUP_HOM_3005.do?sessLocale=ko' },
  { code: 'sinokor', name: '장금상선(Sinokor)', url: 'https://ebiz.sinokor.co.kr/Schedule' },
  { code: 'kmtc', name: '고려해운(KMTC)', url: 'https://www.kmtc.co.kr/index.jsp' },
  { code: 'maersk', name: 'Maersk', url: 'https://www.maersk.com/schedules/vesselSchedules' },
];

/** getScheduleInfo(vesselName, voyageNo) -> {kind: 'manual'|'links', data?} */
function getScheduleInfo(vesselName, voyageNo) {
  const manual = getManualOverride(vesselName, voyageNo);
  if (manual) return { kind: 'manual', data: manual };
  return { kind: 'links' };
}
