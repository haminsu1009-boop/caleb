/**
 * 고객 채팅 응대 (30분마다)
 *
 * AI 가 질문을 분류해서
 *  - 배송·상품·사이즈 같은 "정보 질문"은 바로 답장을 보낸다.
 *  - 취소·환불·불만·가격 협상처럼 돈이나 책임이 걸린 질문은 답장 초안만 쓰고 사람에게 넘긴다.
 * 잘못된 약속 한 번이 환불·페널티로 이어지기 때문에, 자동 범위를 일부러 좁게 잡았다.
 *
 * ⚠️ 쇼피 판매자 채팅 API(sellerchat)는 앱 권한이 따로 필요할 수 있다.
 *    권한 오류가 나면 로그에 남기고 채팅 작업만 멈춘다.
 */

const AUTO_REPLY_CATEGORIES = ['shipping', 'product_info', 'greeting'];

const CHAT_SCHEMA = {
  type: 'OBJECT',
  properties: {
    category: { type: 'STRING', enum: ['shipping', 'product_info', 'greeting', 'cancel_refund', 'complaint', 'price', 'other'] },
    reply: { type: 'STRING' },
    summary_ko: { type: 'STRING' },
  },
  required: ['category', 'reply', 'summary_ko'],
};

function chatJob() {
  withLock_('채팅응대', () => {
    const s = settings_();
    const autoSend = s['채팅자동답변'] === true;
    const handled = {};
    readTable_(SHEETS.CHATS).forEach(c => { handled[String(c['메시지ID'])] = true; });
    const escalations = [];

    markets_().filter(m => m.shopId).forEach(m => {
      let convs;
      try {
        convs = shopee_('/api/v2/sellerchat/get_conversation_list', {
          shopId: m.shopId, params: { direction: 'latest', type: 'unread', page_size: 25 },
        }).conversations || [];
      } catch (e) {
        log_('채팅응대', `${m.code} 채팅 목록 실패 (권한 확인 필요): ${e.message}`);
        return;
      }

      convs.forEach(conv => {
        const msgId = String(conv.latest_message_id);
        const text = conv.latest_message_content && conv.latest_message_content.text;
        if (handled[msgId] || !text || conv.latest_message_from_id === m.shopId) return;
        handled[msgId] = true;

        const ai = gemini_(`Market: ${m.code}\nBuyer message:\n${text}`, {
          system: chatSystem_(s), schema: CHAT_SCHEMA,
        });
        const safe = AUTO_REPLY_CATEGORIES.indexOf(ai.category) >= 0;
        let status = '사람확인필요';
        if (safe && autoSend) {
          shopee_('/api/v2/sellerchat/send_message', {
            shopId: m.shopId, method: 'post',
            body: { to_id: conv.to_id, message_type: 'text', content: { text: ai.reply } },
          });
          status = '자동답변';
        } else {
          escalations.push(`• [${m.code}] ${conv.to_name || conv.to_id}: ${ai.summary_ko}\n  고객: ${text}\n  답변초안: ${ai.reply}`);
        }
        appendRow_(SHEETS.CHATS, {
          '시각': new Date(), '국가': m.code, '대화ID': conv.conversation_id, '메시지ID': msgId,
          '고객': conv.to_name || conv.to_id, '고객메시지': text, '분류': ai.category,
          '요약': ai.summary_ko, 'AI답변': ai.reply, '처리': status,
        });
      });
    });

    if (escalations.length) {
      notify_(`고객 문의 ${escalations.length}건 확인 필요`,
        escalations.join('\n\n') + '\n\n쇼피 셀러센터 채팅에서 직접 답변해 주세요.');
    }
  });
}

function chatSystem_(s) {
  return `You are the customer service assistant of a Korean seller on Shopee.
Reply in the buyer's language, short and polite, as the shop.
Shop facts (do not invent anything beyond these):
- Items are sourced in Korea after the order and shipped from Korea via Shopee's logistics.
- Dispatch within ${s['발송준비일수'] || 3} business days; international delivery usually takes about 5-10 days after dispatch.
- ${s['상점안내'] || 'For order-specific issues, the seller will check and reply soon.'}
Rules:
- Never promise refunds, discounts, cancellations, or exact delivery dates. For those, say the seller
  will check and reply soon, and classify as cancel_refund / complaint / price.
- If product details are not known, say you will check with the seller (category other).
Write summary_ko in Korean for the shop owner.`;
}
