/**
 * 발송 처리 (1시간마다): 주문 시트에서 발주상태가 '발송준비'인 줄을 플랫폼에 발송 등록한다.
 *
 * 사람(또는 태인 창고)이 하는 일: 물건 받기 → 포장 → 발주상태를 '발송준비'로 바꾸기
 *   (큐텐은 택배사·국제송장 칸도 채우기)
 * 프로그램이 하는 일:
 *   - 쇼피: 발송 요청(ship_order) → 쇼피 물류(SLS) 송장번호 받아 시트에 기록
 *   - 큐텐: 입력된 송장번호를 큐텐에 등록(발송 처리)
 * 실물 포장·운송은 코드로 대신할 수 없다. 그 부분은 창고(3PL)에 맡기면 시트 입력만 남는다.
 */

function shippingJob() {
  withLock_('발송처리', () => {
    // '완료'가 아닌 발송준비 줄은 매번 다시 시도 (예: 송장을 나중에 입력한 큐텐 주문)
    const rows = readTable_(SHEETS.ORDERS).filter(o => o['발주상태'] === '발송준비' && o['발송처리'] !== '완료');
    const done = [];
    const problems = [];

    rows.forEach(o => {
      try {
        const result = String(o['플랫폼'] || 'shopee') === 'qoo10' ? shipQoo10_(o) : shipShopee_(o);
        updateRow_(SHEETS.ORDERS, o._row, result);
        if (result['발주상태'] === '발송완료') done.push(`${o['국가']} ${o['주문번호']}`);
        // 같은 문제로 매시간 메일이 오지 않게, 상태가 새로 바뀌었을 때만 알림
        else if (result['발송처리'] !== 'SLS송장대기' && result['발송처리'] !== o['발송처리']) {
          problems.push(`${o['주문번호']}: ${result['발송처리']}`);
        }
      } catch (e) {
        const msg = '오류: ' + String(e.message || e).slice(0, 200);
        updateRow_(SHEETS.ORDERS, o._row, { '발송처리': msg });
        if (msg !== o['발송처리']) problems.push(`${o['주문번호']}: ${e.message || e}`);
      }
    });

    if (done.length) log_('발송처리', `발송 완료 ${done.length}건: ${done.join(', ')}`);
    if (problems.length) notify_(`발송 처리 확인 필요 ${problems.length}건`, problems.join('\n'));
  });
}

function shipShopee_(o) {
  const shopId = Number(o['shop_id']) || null;
  const sn = String(o['주문번호']);

  if (o['발송처리'] !== 'SLS송장대기') {
    const param = shopee_('/api/v2/logistics/get_shipping_parameter', { shopId: shopId, params: { order_sn: sn } });
    const need = param.info_needed || {};
    const body = { order_sn: sn };
    if (need.dropoff !== undefined) {
      body.dropoff = {};
    } else if (need.pickup !== undefined) {
      const addr = ((param.pickup || {}).address_list || [])[0];
      const slot = addr && (addr.time_slot_list || [])[0];
      if (!addr || !slot) return { '발송처리': '픽업 주소/시간 없음 — 셀러센터 확인' };
      body.pickup = { address_id: addr.address_id, pickup_time_id: slot.pickup_time_id };
    }
    shopee_('/api/v2/logistics/ship_order', { shopId: shopId, method: 'post', body: body });
  }

  // 송장번호는 발송 요청 직후 바로 안 나올 수 있다 → 다음 실행에서 다시 조회
  const tr = shopee_('/api/v2/logistics/get_tracking_number', { shopId: shopId, params: { order_sn: sn } });
  if (!tr.tracking_number) return { '발송처리': 'SLS송장대기' };
  return {
    '국제송장': tr.tracking_number, '택배사': 'Shopee SLS', '발송처리': '완료',
    '발주상태': '발송완료', '메모': [o['메모'], '송장 라벨은 셀러센터에서 출력'].filter(Boolean).join(' / '),
  };
}

function shipQoo10_(o) {
  if (!o['택배사'] || !o['국제송장']) return { '발송처리': '택배사·국제송장 입력 필요' };
  qoo10SendTracking_(String(o['주문번호']), String(o['택배사']), String(o['국제송장']));
  return { '발송처리': '완료', '발주상태': '발송완료' };
}
