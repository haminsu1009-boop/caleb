/**
 * 알림 발송: 이메일 + (연결돼 있으면) 카카오톡 '나에게 보내기'
 * msg = { subject, text, link?, kakaoExtras?: [추가로 카톡 보낼 글], emailExtra?: 이메일에만 붙일 글 }
 */
function notify_(msg) {
  const link = msg.link || SpreadsheetApp.getActiveSpreadsheet().getUrl();
  const emails = getSetting_('알림 이메일');
  if (emails) {
    MailApp.sendEmail({
      to: emails,
      subject: msg.subject,
      body: lines_(msg.text, msg.emailExtra ? '\n' + msg.emailExtra : null, '', link),
    });
  }

  if (kakaoIsConnected_()) {
    try {
      [msg.text, ...(msg.kakaoExtras || [])].forEach(t => kakaoSendToMe_(t, link));
    } catch (e) {
      // 카카오가 실패해도 이메일은 이미 나갔으니 기록만 남김
      console.error(e);
      log_('카카오톡 전송 실패', String(e));
    }
  }
  log_(msg.subject, msg.text);
}
