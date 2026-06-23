# 유니패스 알림 자동화

관세청 Open API(유니패스)에서 화물 진행정보를 주기적으로 조회해서
새 진행 내역이 생기면 텔레그램으로 알려줍니다.

## 준비

1. `pip install -r requirements.txt`
2. `config.example.json`을 `config.json`으로 복사하고 값 채우기
   - `telegram_bot_token`, `telegram_chat_id`: 이미 확인된 값 사용
   - `unipass_api_key`: data.go.kr에서 "관세청 수출입화물진행정보" API 활용신청 후 발급된 Decoding 키
   - `watch_list`: 추적할 화물의 MBL/HBL 번호, 연도. `alert_keywords`에 단어를 넣으면
     해당 단어가 포함된 진행 내역에 🔔 표시가 추가됩니다 (비워두면 모든 업데이트를 동일하게 보고)

## 사용

- 텔레그램 연결만 테스트: `python test_telegram.py`
- 1회 조회 후 종료: `python unipass_alert.py --once`
- 계속 실행 (poll_interval_seconds 주기로 반복): `python unipass_alert.py`

## 참고

- 유니패스 API 키가 없으면 `unipass_alert.py`는 조회 단계에서 에러를 출력하고 다음 항목으로 넘어갑니다.
- 한 번 알린 진행 내역은 `state.json`에 저장되어 중복 알림이 발생하지 않습니다.
