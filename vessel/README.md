# 선박 추적 봇 (vessel/)

> 모선명 + 항차번호만 말하면 실시간 선박 위치를 알려주는 봇.
> 텔레그램 / 카카오톡 채널 / 웹사이트 챗위젯, 세 채널을 동시에 지원한다.

---

## 어떻게 동작하나

```
사용자 입력 ("HMM 코펜하겐, 0526E")
    │
    ▼
parser.py     자유 텍스트에서 모선명 / 항차번호 분리
    │
    ▼
directory.py  모선명 → IMO/MMSI (로컬 매핑표, data/vessel_directory.json)
    │
    ▼
providers.py  IMO/MMSI → 실시간 AIS 위치 (VesselFinder / MarineTraffic / Mock)
    │
    ▼
tracker.py    위 단계 오케스트레이션 + 캐시(data/vessel_cache.json)
    │
    ▼
formatter.py  사람이 읽는 답장 문장으로 변환
    │
    ├── telegram_bot.py  → 텔레그램
    └── server.py        → 웹위젯 API + 카카오톡 스킬
```

### 왜 "모선명 → IMO/MMSI" 단계가 따로 있나

AIS 데이터 제공업체(VesselFinder, MarineTraffic 등)의 API는 선박명을
자유 검색하는 기능을 주지 않는다 — **IMO 또는 MMSI 번호로만** 위치를
조회할 수 있다. 그래서 사람이 편하게 이름만 말해도 동작하려면, 이름을
IMO/MMSI로 바꿔주는 매핑표(`data/vessel_directory.json`)가 있어야
한다. 이 파일은 회사가 실제 거래하는 선박을 계속 추가해나가는 용도다.

### 왜 항차번호는 AIS로 확인이 안 되나

항차번호(Voyage No.)는 **선사가 자체 스케줄 시스템에서 매기는 번호**이지,
AIS 신호에 실리는 값이 아니다. AIS로는 위치·속력·목적지·ETA까지만 알 수
있다. 그래서 이 봇은 항차번호를 "참고 표시"로만 답장에 보여준다 — 실제로
그 항차와 매칭시키려면 선사 스케줄 API나 KL-Net/Port-MIS 같은 국내
포워딩 시스템 연동이 별도로 필요하다 (아래 "확장 아이디어" 참고).

---

## 빠른 시작 (API 키 없이 데모부터)

```bash
pip install -r requirements.txt
cp .env.example .env      # 그대로 둬도 Mock 데이터로 전부 동작함

# 파이프라인만 테스트
python -c "from vessel.tracker import track_from_text; print(track_from_text('EVER GIVEN, 0526E').message)"
```

`data/vessel_directory.json`에 예시로 EVER GIVEN(IMO 9811000)이 들어있어서
API 키 없이도 바로 결과가 나온다. 실제 서비스로 쓰려면:

1. `data/vessel_directory.json`에 거래하는 선박을 추가 (이름/별칭 + IMO)
2. `.env`에 `VESSELFINDER_API_KEY` 또는 `MARINETRAFFIC_API_KEY` 등록
3. 아래 채널 중 원하는 걸 실행

---

## 채널 1 — 텔레그램 봇

```bash
# 1. @BotFather 에게 /newbot → 토큰 발급
# 2. .env 에 TELEGRAM_TOKEN 입력
python vessel/telegram_bot.py
```

텔레그램 채팅창에 `HMM 코펜하겐, 0526E`처럼 보내면 답장이 온다.
(무한 롱폴링 — 서버에 상시 돌려두거나 `systemd`/`pm2` 등으로 관리 권장)

## 채널 2 — 웹사이트 챗위젯

`vessel/server.py`가 `/api/vessel/track` API를 제공하고,
`assets/vessel-widget.js`가 그걸 호출하는 플로팅 챗버튼을 그려준다.
`sea-transport.html`에 이미 스크립트가 붙어 있다.

```bash
python vessel/server.py     # http://0.0.0.0:8787
```

배포 시 두 군데를 실제 주소로 바꿔야 한다:
- `sea-transport.html` 하단의 `window.VESSEL_API_BASE`
- `.env`의 `VESSEL_WIDGET_ORIGIN` (CORS를 사이트 도메인으로 제한 — 비워두면 전체 허용)

다른 페이지(예: `index.html`)에도 위젯을 넣고 싶으면 같은 2줄
(`<script>window.VESSEL_API_BASE=...</script>` + `vessel-widget.js`)을
`</body>` 직전에 복사하면 된다.

## 채널 3 — 카카오톡 채널 챗봇

`vessel/server.py`가 카카오 i 오픈빌더 스킬 응답 포맷으로
`/kakao/skill`을 제공한다.

1. 카카오톡 채널 개설 (카카오톡 채널 관리자센터)
2. 카카오 i 오픈빌더에서 챗봇 생성 → 스킬 등록
   - 스킬 URL: `https://<배포주소>/kakao/skill`
3. 폴백 블록(어떤 발화든 매칭)의 응답을 이 스킬로 연결
4. 봇 배포 → 채널 연결

서버는 텔레그램 봇과 별도 프로세스이므로 함께 실행해도 되고,
`vessel/server.py`만 배포해도 웹위젯+카카오는 동시에 동작한다.

---

## 실제 AIS API 연동

| 프로바이더 | 특징 | 키 발급 |
|---|---|---|
| VesselFinder | 문서가 잘 정리돼 있고 IMO/MMSI 기준 조회 | https://api.vesselfinder.com |
| MarineTraffic | 가장 널리 쓰이지만 서비스별(PS01/PS07 등) 개별 계약 필요, 파라미터가 플랜마다 다름 | https://www.marinetraffic.com/en/p/api-services |

`.env`에 키를 넣고 `AIS_PROVIDER`를 비워두면 등록된 키를 자동으로
쓴다. **`vessel/providers.py`의 `MarineTrafficProvider`는 공개된 레거시
패턴으로 작성한 best-effort 구현**이라, 실제 키를 받으면 대시보드에
나오는 정확한 엔드포인트/파라미터로 맞춰 써야 할 수 있다.

두 API 모두 유료 구독이며, 조회 1건당 과금되는 경우가 많다.
`AIS_CACHE_TTL_SEC`(기본 300초)로 같은 선박 재조회를 캐시해서
과금을 줄인다.

---

## 확장 아이디어

- **항차번호를 실제로 매칭**하려면 선사 스케줄 API나 국내 KL-Net/Port-MIS
  연동을 `tracker.py`에 추가하면 된다 — `format_position()`의 "참고
  표시용" 문구를 실제 매칭 결과로 바꾸는 지점.
- **여러 선박 후보 → 사용자가 번호로 선택**하는 대화형 흐름 (현재는
  후보를 나열만 하고 사용자가 정확한 이름으로 다시 물어야 함).
- **도착 알림 구독** — 특정 선박의 ETA가 임박하면 먼저 알려주는 기능
  (coin/notifier.py의 텔레그램 발송 패턴을 재사용하면 된다).
