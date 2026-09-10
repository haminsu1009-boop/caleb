"""
vessel/ — 모선명 + 항차번호로 선박을 추적하는 봇

핵심 파이프라인:
  자유 텍스트 ("HMM 코펜하겐, 0526E")
    → parser.py    : 모선명 / 항차번호 분리
    → directory.py : 모선명 → IMO/MMSI (AIS API는 이름 검색을 지원하지 않아
                      로컬 매핑표가 필요하다)
    → providers.py : IMO/MMSI → 실시간 AIS 위치 (VesselFinder / MarineTraffic / Mock)
    → tracker.py   : 위 단계 오케스트레이션 + 캐시
    → formatter.py : 사람이 읽는 답변 문장으로 변환

세 가지 채널이 전부 이 파이프라인을 공유한다:
  telegram_bot.py : 텔레그램 봇 (롱폴링)
  server.py       : 웹사이트 챗위젯 API + 카카오톡 챗봇 스킬 서버 (Flask)

자세한 설정은 vessel/README.md 참고.
"""
