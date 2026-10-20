# 아젠다만.gs + 월간작업.gs + 개인톡문구.gs + 카톡나에게.gs → 최종코드.gs (메뉴에 보이는 함수는 한글 이름)
import re, sys, pathlib
d = pathlib.Path(__file__).parent
agenda = (d/'아젠다만.gs').read_text()
monthly = (d/'월간작업.gs').read_text()
talk = (d/'개인톡문구.gs').read_text()
kakao = (d/'카톡나에게.gs').read_text()

def cut(s, start, end, keep_end=True):
    a = s.index(start); b = s.index(end, a)
    return s[:a] + (s[b:] if keep_end else s[b+len(end):])

# 월간작업: 예전 안내 문구(개인톡문구로 대체)와 예약 함수(자동실행설치로 통합) 빼기
josa = re.search(r"/\*\* 받침이 있으면.*?\n}\n", monthly, re.S).group(0)
monthly = cut(monthly, "// 말씀 주제 — 시트에", "const NOT_PERSON_RE")
monthly = cut(monthly, "const NOTICE_ROLES = [", "// ───────── 실행 함수 ─────────")
monthly = cut(monthly, "// ───────── 실행 함수 ─────────", "// ───────── ② 반주자")
monthly = re.sub(r"/\*\*\n \* 월간 작업.*?\*/\n", "/** 월간 작업: 반주표 이미지 · 내년 순서표 초안 */\n", monthly, flags=re.S)
monthly += "\nfunction 내년순서표만들기() { buildYearDraft_(DRAFT_YEAR); }\n"
talk = talk.replace("// ═══════════════ 개인톡 안내 문구 (Code.gs 맨 아래에 붙여넣기 — 위의 같은 이름 함수를 대신함) ═══════════════",
                    "// ═══════════════ 말씀·기도 안내 문구 ═══════════════")
monthly += "\n" + josa
monthly = cut(monthly, "// ───────── ② 반주자", "// ───────── ③ 1년치")  # 반주표는 반주표디자인.gs 로 대체
organist = (d/'반주표디자인.gs').read_text().replace(
    "// ═══════════════ 반주표 이미지 (새 디자인) — Code.gs 맨 아래에 붙여넣기 (위의 반주표보내기를 대신함) ═══════════════",
    "// ═══════════════ 반주표 이미지 ═══════════════")
kakao = kakao.replace("// ═══════════════ 카카오톡 '나에게 보내기' (Code.gs 맨 아래에 붙여넣기) ═══════════════",
                      "// ═══════════════ 카카오톡 '나에게 보내기' ═══════════════")
kakao = kakao.replace("/** (위의 sendTalkNotices 를 대신함) 메일 한 통 + 내 카톡으로 사람마다 한 통씩 */",
                      "/** 매주 월요일 10시: 4주 뒤 주제 안내 + 이번 주 리마인드 → 메일 한 통 + 내 카톡으로 사람마다 한 통씩 */")

# 아젠다: 예약 함수 → 자동실행설치(전부 한 번에)
agenda = cut(agenda, "/** 처음 한 번 실행: 매주 월요일 9시 자동 실행 예약 */", "/** 테스트용: 다음 주일")
install = '''/** 처음 한 번 실행: 자동 실행 예약 전부 (예전 예약은 지우고 새로 만듦) */
function 자동실행설치() {
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('이번주아젠다만들기').timeBased().onWeekDay(ScriptApp.WeekDay.MONDAY).atHour(9).create();
  ScriptApp.newTrigger('말씀안내보내기').timeBased().onWeekDay(ScriptApp.WeekDay.MONDAY).atHour(10).create();
  ScriptApp.newTrigger('반주표보내기').timeBased().onMonthDay(25).atHour(9).create();
  console.log('예약 완료\\n· 매주 월 9시: 이번주아젠다만들기\\n· 매주 월 10시: 말씀안내보내기 (메일 + 카톡)\\n· 매달 25일 9시: 반주표보내기');
}

'''
agenda = agenda.replace("/** 테스트용: 다음 주일", install + "/** 테스트용: 다음 주일", 1)
header = '''/**
 * 녹번와드 성찬식 자동화 — 이 파일 하나를 Code.gs 에 통째로 붙여넣으세요.
 *
 * 실행 메뉴에 보이는 함수
 *  · 자동실행설치        처음 한 번: 매주 월 9시 아젠다 / 월 10시 말씀 안내 / 매달 25일 반주표 예약
 *  · 이번주아젠다만들기   「성찬식 아젠다」 문서 맨 위에 이번 주 칸 추가 (이미 있으면 값만 다시 맞춤)
 *  · 다음주아젠다만들기 · 다다음주아젠다만들기   미리 만들어 보기
 *  · 말씀안내보내기       4주 뒤 주제 안내 + 이번 주 리마인드 → 메일 + 내 카톡
 *  · 반주표보내기         다음 달 지휘·반주·찬송표 이미지 → 메일
 *  · 내년순서표만들기     감독단 시트에 내년 순서표 초안 탭
 *  · 카톡로그인주소 → 카톡연결   카카오톡 '나에게 보내기' 연결 (처음 한 번)
 */'''
agenda = re.sub(r"^/\*\*\n \* 성찬식 아젠다 자동 생성.*?\*/", header, agenda, count=1, flags=re.S)

out = agenda + "\n\n" + talk + "\n" + kakao + "\n\n" + organist + "\n" + monthly
names = {
  'testSundayAfterNext': '다다음주아젠다만들기', 'testNextSunday': '다음주아젠다만들기', 'updateAgenda': '이번주아젠다만들기',
  'sendTalkNotices': '말씀안내보내기', 'sendOrganistList': '반주표보내기',
  'kakaoLoginLink': '카톡로그인주소', 'kakaoConnect': '카톡연결',
  'testTalkNotices': '말씀안내보내기', 'testOrganistList': '반주표보내기', 'makeYearDraft': '내년순서표만들기',
  'installMonthlyTriggers': '자동실행설치', 'installTrigger': '자동실행설치',
}
for en, ko in names.items():
    out = re.sub(r'\b%s\b' % en, ko, out)
out = re.sub(r'\n{3,}', '\n\n', out)
(d/'최종코드.gs').write_text(out)
leftover = re.findall(r'^function ([A-Za-z]\w*[^_\W])\s*\(', out, re.M)
print('메뉴에 보이는 영어 함수:', leftover or '없음')
print('메뉴 함수:', re.findall(r'^function ([가-힣]+)\(', out, re.M))
