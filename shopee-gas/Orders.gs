/**
 * 주문 확인 → 발주 목록 작성 → 알림 (30분마다)
 *
 * 국내 도매처 결제는 자동으로 하지 않는다. 돈이 나가는 마지막 버튼은 사람이 누른다.
 * 대신 "어디서 · 무엇을 · 몇 개 · 얼마에" 사야 하는지 발주 목록과 메일로 바로 정리해 준다.
 */

function ordersJob() {
  withLock_('주문확인', () => {
    const known = {};
    readTable_(SHEETS.ORDERS).forEach(o => { known[`${o['주문번호']}|${o['SKU']}`] = true; });
    const products = {};
    readTable_(SHEETS.PRODUCTS).forEach(p => { if (p['SKU']) products[p['SKU']] = p; });

    const now = Math.floor(Date.now() / 1000);
    const newLines = [];

    markets_().filter(m => m.shopId).forEach(m => {
      const list = shopee_('/api/v2/order/get_order_list', {
        shopId: m.shopId,
        params: {
          time_range_field: 'create_time', time_from: now - 3 * 86400, time_to: now,
          page_size: 100, order_status: 'READY_TO_SHIP',
        },
      });
      const sns = (list.order_list || []).map(o => o.order_sn);
      for (let i = 0; i < sns.length; i += 50) {
        const detail = shopee_('/api/v2/order/get_order_detail', {
          shopId: m.shopId,
          params: { order_sn_list: sns.slice(i, i + 50), response_optional_fields: 'item_list,total_amount,ship_by_date' },
        });
        (detail.order_list || []).forEach(order => {
          (order.item_list || []).forEach(item => {
            const sku = item.model_sku || item.item_sku || '';
            const key = `${order.order_sn}|${sku}`;
            if (known[key]) return;
            known[key] = true;
            const p = products[sku] || {};
            const qty = Number(item.model_quantity_purchased || 1);
            const line = {
              '주문번호': order.order_sn,
              '국가': m.code,
              '주문시각': new Date(order.create_time * 1000),
              '발송기한': order.ship_by_date ? new Date(order.ship_by_date * 1000) : '',
              'SKU': sku,
              '상품명': item.item_name,
              '수량': qty,
              '판매가': `${item.model_discounted_price || item.model_original_price} ${m.currency}`,
              '소싱URL': p['소싱URL'] || '',
              '예상원가(원)': p['원가(원)'] ? Number(p['원가(원)']) * qty : '',
              '발주상태': '미발주',
            };
            appendRow_(SHEETS.ORDERS, line);
            newLines.push(line);
          });
        });
      }
    });

    if (newLines.length) {
      const body = newLines.map(l =>
        `• [${l['국가']}] ${l['상품명']} × ${l['수량']}  (주문 ${l['주문번호']})\n` +
        `  발송기한: ${l['발송기한'] ? Utilities.formatDate(l['발송기한'], 'Asia/Seoul', 'MM/dd HH:mm') : '-'}\n` +
        `  발주하기: ${l['소싱URL'] || '소싱URL 없음 — 상품 시트 확인'}`).join('\n\n');
      notify_(`새 주문 ${newLines.length}건 — 발주해 주세요`,
        body + '\n\n발주 후 주문 시트의 발주상태를 "발주완료"로 바꿔 주세요.');
      log_('주문확인', `새 주문 ${newLines.length}건`);
    }
    remindUnordered_();
  });
}

/** 발송기한 24시간 안쪽인데 아직 미발주인 건은 다시 알림 (하루 한 번) */
function remindUnordered_() {
  const cache = CacheService.getScriptCache();
  if (cache.get('remind_sent')) return;
  const soon = Date.now() + 24 * 3600 * 1000;
  const late = readTable_(SHEETS.ORDERS).filter(o =>
    o['발주상태'] === '미발주' && o['발송기한'] instanceof Date && o['발송기한'].getTime() < soon);
  if (!late.length) return;
  notify_(`⚠️ 발송기한 임박 미발주 ${late.length}건`,
    late.map(o => `• ${o['상품명']} × ${o['수량']} (주문 ${o['주문번호']}) ${o['소싱URL']}`).join('\n'));
  cache.put('remind_sent', '1', 6 * 3600);
}
