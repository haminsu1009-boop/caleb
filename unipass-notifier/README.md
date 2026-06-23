# 유니패스 통관상태 알림 도구

특정 BL/화물관리번호의 통관 진행상태를 유니패스 OpenAPI로 조회하고,
이전 조회 결과와 다를 때만 텔레그램으로 알려준다.
매번 직접 사이트에 들어가서 확인할 필요 없이, 이 스크립트를 실행하면
변경이 있을 때만 알림이 온다.

## 1. 사전 준비

### (1) 유니패스 OpenAPI 인증키 발급
1. https://unipass.customs.go.kr 회원가입/로그인
2. 마이메뉴 > Open API 서비스 신청
3. "화물통관진행정보조회(cargCsclPrgsInfoQry)" API 신청 → 인증키(`crkyCn`) 발급

### (2) 텔레그램 봇 토큰 / chat id 발급
1. 텔레그램에서 `@BotFather` 검색 후 `/newbot` 명령으로 봇 생성 → `TELEGRAM_BOT_TOKEN` 발급
2. 만든 봇과 1:1 대화를 시작하고 메시지를 한 번 보낸다 (예: "안녕")
3. 아래 URL을 브라우저로 열어 `chat.id` 값을 확인:
   ```
   https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates
   ```
   응답 JSON에서 `result[0].message.chat.id` 값이 `TELEGRAM_CHAT_ID`.

## 2. 설치

```bash
cd unipass-notifier
pip install -r requirements.txt
```

## 3. 환경변수 설정

```bash
export UNIPASS_API_KEY="발급받은 crkyCn"
export TELEGRAM_BOT_TOKEN="발급받은 봇 토큰"
export TELEGRAM_CHAT_ID="확인한 chat id"
```

## 4. 사용법

```bash
# BL번호로 조회
python unipass_notify.py --bl <BL번호> --year 2026

# 화물관리번호로 조회
python unipass_notify.py --cargo <화물관리번호>
```

- 처음 조회하면 현재 상태를 카카오톡으로 1회 알려주고 저장한다.
- 이후 같은 번호로 다시 실행하면, 상태가 바뀐 경우에만 알림이 온다.
- 변경이 없어도 강제로 현재 상태를 받고 싶으면 `--force-notify` 옵션 추가.

조회 기록은 `~/.unipass_notifier/state.json` 에 저장된다(번호별 마지막 상태).

## 5. 자동 반복 실행이 필요해지면

지금은 "물어볼 때마다 확인" 방식이지만, 나중에 주기적으로 자동 확인하고 싶다면
cron이나 GitHub Actions로 위 명령을 일정 간격(예: 10분)으로 실행하면 된다.
텔레그램 봇 토큰은 만료되지 않으므로 별도 갱신 로직 없이 그대로 사용 가능하다.
