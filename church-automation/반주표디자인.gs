// ═══════════════ 반주표 이미지 (새 디자인) — Code.gs 맨 아래에 붙여넣기 (위의 반주표보내기를 대신함) ═══════════════

const ORG_EMPTY = 'N/A';
const ORG_COLORS = {
  title: '#1F3A5F',      // 제목 · 날짜 · 찬송 번호
  header: '#1F3A5F',     // 머리글 배경
  headerText: '#FFFFFF',
  stripe: '#EEF3F9',     // 줄무늬
  plain: '#FFFFFF',
  text: '#222222',
  muted: '#A0AAB4',      // N/A · 부제목
};

function 반주표보내기(base) {
  const today = base instanceof Date ? base : new Date();
  const first = new Date(today.getFullYear(), today.getMonth() + 1, 1); // 다음 달 1일
  const month = first.getMonth();
  const header = ['날짜', '지휘', '반주', '개회찬송', '성찬찬송', '회중찬송', '폐회찬송'];
  const na = v => v || ORG_EMPTY;
  const rows = [];
  for (let d = upcomingSunday_(first); d.getMonth() === month; d = plusDays_(d, 7)) {
    const m = getMeeting_(d);
    const date = fmt_(d, 'MM/dd');
    if (!m || m.special) {                                 // 시트에 없거나 연차대회·스테이크 대회 주
      rows.push([date, ...header.slice(1).map(() => ORG_EMPTY)]);
      continue;
    }
    rows.push([date, na(person_(m.chorister, '자매님')), na(person_(m.organist, '자매님')),
      na(m.hymns.openingHymn), na(m.hymns.sacramentHymn), m.fast ? ORG_EMPTY : na(m.hymns.restHymn), na(m.hymns.closingHymn)]);
  }

  const title = `${month + 1}월 성찬식 지휘/반주/찬송가표`;
  const subtitle = `녹번와드 · ${first.getFullYear()}년 ${month + 1}월 · 매주 일요일`;
  const image = organistImage_(title, subtitle, header, rows);
  const text = rows.map(r => `${r[0]}  지휘 ${r[1]} · 반주 ${r[2]}\n   개회 ${r[3]} / 성찬 ${r[4]} / 회중 ${r[5]} / 폐회 ${r[6]}`).join('\n');
  MailApp.sendEmail({
    to: Session.getEffectiveUser().getEmail(),
    subject: `[반주표] ${title}`,
    body: `첨부한 이미지를 저장해서 반주자 톡방에 올려 주세요.\n\n${text}`,
    attachments: [image],
  });
  console.log(`[반주표] ${title} 메일 보냄\n${text}`);
}

/** 구글 슬라이드에 표를 그려 PNG 이미지로 내보내고, 슬라이드는 휴지통으로 */
function organistImage_(title, subtitle, header, rows) {
  const CENTER = SlidesApp.ParagraphAlignment.CENTER;
  const MIDDLE = SlidesApp.ContentAlignment.MIDDLE;
  const font = style => { try { style.setFontFamily('Noto Sans KR'); } catch (e) { /* 글꼴이 없으면 기본 글꼴 */ } return style; };

  const pres = SlidesApp.create(title);
  const slide = pres.getSlides()[0];
  slide.getPageElements().forEach(e => e.remove());
  slide.getBackground().setSolidFill(ORG_COLORS.plain);
  const W = pres.getPageWidth(), H = pres.getPageHeight(), M = 24;

  // 제목 · 부제목
  const t = slide.insertTextBox(title, M, 12, W - 2 * M, 34);
  font(t.getText().getTextStyle()).setFontSize(22).setBold(true).setForegroundColor(ORG_COLORS.title);
  const s = slide.insertTextBox(subtitle, M, 44, W - 2 * M, 18);
  font(s.getText().getTextStyle()).setFontSize(10).setForegroundColor(ORG_COLORS.muted);

  // 표 (구글 슬라이드는 열 너비를 코드로 못 바꿔서 칸 너비는 같게)
  const top = 70;
  const table = slide.insertTable(rows.length + 1, header.length, M, top, W - 2 * M, H - top - M);

  [header, ...rows].forEach((r, i) => r.forEach((v, j) => {
    const cell = table.getCell(i, j);
    const value = String(v || ORG_EMPTY);
    const hymn = i > 0 && j >= 3 && value.match(/^(\d+장)\s+(.+)$/);   // '25장 제목' → 번호 / 제목 두 줄
    const txt = cell.getText();
    txt.setText(hymn ? `${hymn[1]}\n${hymn[2]}` : value);
    const style = font(txt.getTextStyle()).setFontSize(i === 0 ? 12 : 10.5).setBold(i === 0)
      .setForegroundColor(i === 0 ? ORG_COLORS.headerText : ORG_COLORS.text);
    if (i > 0 && j === 0) style.setBold(true).setFontSize(12).setForegroundColor(ORG_COLORS.title);
    if (value === ORG_EMPTY) style.setForegroundColor(ORG_COLORS.muted);
    if (hymn) txt.getRange(0, hymn[1].length).getTextStyle().setBold(true).setFontSize(12).setForegroundColor(ORG_COLORS.title);
    txt.getParagraphStyle().setParagraphAlignment(CENTER);
    cell.setContentAlignment(MIDDLE);
    cell.getFill().setSolidFill(i === 0 ? ORG_COLORS.header : i % 2 ? ORG_COLORS.plain : ORG_COLORS.stripe);
  }));
  pres.saveAndClose();

  const url = `https://docs.google.com/presentation/d/${pres.getId()}/export/png?pageid=${slide.getObjectId()}`;
  const blob = UrlFetchApp.fetch(url, { headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() } })
    .getBlob().setName(`${title}.png`);
  DriveApp.getFileById(pres.getId()).setTrashed(true);
  return blob;
}
