/** 알림 발송: 이메일 + (연결돼 있으면) 카카오톡 '나에게 보내기' */
function notify_(subject, text, linkUrl) {
  const url = linkUrl || SpreadsheetApp.getActiveSpreadsheet().getUrl();

  const emails = getSetting_('알림 이메일');
  if (emails) {
    MailApp.sendEmail({ to: emails, subject: subject, body: `${text}\n\n${url}` });
  }

  if (kakaoIsConnected_()) {
    try {
      kakaoSendToMe_(text, url);
    } catch (e) {
      // 카카오가 실패해도 이메일은 이미 나갔으니 로그만 남김
      console.error(e);
      if (emails) MailApp.sendEmail(emails, '[교회 자동화] 카카오톡 전송 실패', String(e));
    }
  }
}
