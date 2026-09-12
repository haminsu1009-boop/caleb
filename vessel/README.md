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

### 회귀 테스트

코드를 고칠 때마다 파이프라인이 안 깨졌는지 확인:

```bash
python vessel/test_vessel.py
```

파서/디렉터리 매칭/수동입력 저장·만료/터미널·선사 폴백/전체 조회
흐름을 API 키 없이 전부 검증한다.

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

## 터미널 실시간 연동 (선사 스케줄보다 정확한 ETA)

선사가 주는 스케줄보다 **터미널이 발표하는 접안예정(ETB)** 이 실제
도착시간에 훨씬 가깝다 — 터미널은 실제 선석 배정을 관리하는 쪽이라
지연·앞당김이 바로 반영된다. 그래서 `vessel/terminal_providers.py`에
부산신항/북항 주요 터미널 5곳(BPT·HJNC·PNIT·HPNT·PNC)의 조회
프로바이더 뼈대를 만들어뒀고, `tracker.py`가 AIS 조회와 별도로 이걸
먼저 시도해서 답장 맨 위에 보여준다.

**지금은 자동조회가 안 되고, 해당 터미널 조회 페이지 링크만 나온다.**
이유: 이 세션이 도는 네트워크 환경에서 터미널 도메인(`hjnc.co.kr`,
`pnitl.com` 등)에 직접 접속이 막혀 있어서, 각 사이트의 실제 조회 요청
형식(파라미터명, GET/POST, 로그인 필요 여부)을 확인하지 못했다.
추측으로 스크래퍼를 짜면 "그럴듯해 보이지만 실제로는 안 되는 코드"가
되기 때문에, 확인 안 된 부분은 정직하게 링크 폴백으로 남겨뒀다.

### 완성하는 법 (오래 안 걸림)

터미널(`vessel/terminal_providers.py`)과 선사(`vessel/carrier_providers.py`)
둘 다 완성 방법은 똑같다:

1. 파일에 적힌 `query_url` 중 하나를 브라우저로 연다.
2. 실제 선박 하나로 검색해본다 (아무 선박이나 상관없음 — 요청 형식만 보면 됨).
3. 개발자도구(F12) → Network 탭 → 방금 보낸 검색 요청을 찾아
   **"Copy as cURL"** 로 복사한다.
4. 그 내용(+ 결과 화면의 스크린샷이나 HTML)을 붙여주면, 해당 터미널/선사의
   `lookup()`을 실제로 동작하게 완성할 수 있다.

`PNIT`(`pnitl.com`)와 `HPNT`(`hpnt.co.kr`)는 조회 페이지 URL 패턴이
완전히 같다(`/infoservice/vessel/vslScheduleList.jsp`) — 같은 터미널
운영 솔루션 계열로 보여서, 하나만 확인해도 둘 다 같은 방식으로 풀릴
가능성이 높다.

실제로 거래하는 터미널이 위 5곳 중 일부뿐이라면 `.env`의
`VESSEL_TERMINALS`에 코드만 남겨서(`VESSEL_TERMINALS=hjnc,pnit`)
나머지는 조회하지 않게 좁힐 수 있다.

### 선사(운항사) 스케줄도 같은 방식으로 — 왜, 그리고 비용은?

터미널이 없는 선박이거나 터미널 자동조회가 아직 안 됐을 때의 차선책으로,
`vessel/carrier_providers.py`에 선사 6곳(HMM·ONE·SM상선·장금상선·
고려해운·Maersk)도 같은 뼈대로 만들어뒀다. 우선순위는:

```
직원 수동입력(방금 확인) ≥ 터미널 ETB(실제 접안 관리) > 선사 스케줄(계획) > AIS ETA(추정)
```

**돈이 드는 곳은 딱 한 군데뿐이다 — AIS 위치추적(`vessel/providers.py`,
VesselFinder/MarineTraffic).** 이건 위성/지상 AIS 신호를 모아 파는
상업 서비스라 원가가 실제로 들어서 유료다. 반면 터미널·선사 조회는
회원가입한 화주만 쓰는 "API"가 아니라, 그 회사가 웹사이트에 열어둔
**공개 조회 페이지를 프로그램이 대신 눌러주는 것**이다 — 그래서
API 키 발급이나 계약이 원칙적으로 필요 없다 (다만 실제로 로그인 없이
되는지는 각 사이트를 열어봐야 확실하다 — `query_url`을 브라우저로
직접 열어서 확인하면 된다).

그래서 예산이 부담되면 **AIS 위치추적은 아예 빼고** 터미널+선사
스크래핑(완성되면) + 직원 수동입력만으로 운영하는 것도 현실적인
선택지다 — 애초에 "터미널이 제일 정확하다"고 하신 이유가 AIS보다
그쪽에 있었으니, AIS는 "먼 바다에 떠 있는 동안의 대략적 위치"
정도의 보너스 정보로 남겨둬도 된다.

### 그동안은 — 직원이 텔레그램으로 직접 입력

자동 연동이 끝나기 전까지 오늘부터 바로 쓸 수 있는 방법: 직원이
터미널 사이트를 직접 보고, 텔레그램 봇에게 `/update` 명령으로 값을
불러주면 봇이 저장해뒀다가 **이후 모든 채널(텔레그램/카카오/웹위젯)
조회에 자동 프로바이더보다 먼저** 보여준다 — 사람이 방금 확인한 값이
가장 신선하기 때문이다.

```
/update EVER GIVEN, 0526E | 터미널=HJNC | 선석=1부두 | ETB=2026-09-15 08:00 | 상태=접안예정
```

- `|`로 구분된 `키=값` 형식. 필요한 키만 넣으면 된다
  (터미널, 선석, ETA, ETB, ETD, 상태).
- `MANUAL_TERMINAL_TTL_HOURS`(기본 72시간)가 지나면 자동으로
  사라진다 — 갱신을 깜빡한 오래된 값을 최신인 것처럼 보여주지 않기 위해서.
- 삭제: `/delete 선명, 항차`
- 전체 확인: `/list` (지금 저장된 수동입력을 전부 보여줌)
- 채팅창에 `/update`만 입력하면 사용법이 다시 뜬다.

**⚠️ `.env`의 `TELEGRAM_ADMIN_IDS`를 반드시 설정할 것.** 비워두면
누구나 `/update`로 다른 고객에게 보이는 터미널 정보를 바꿀 수 있다
(텔레그램 봇에게 말을 걸 수 있는 사람이면 전부 포함). 본인 chat_id는
@userinfobot에게 물어보면 알려준다.

---

## 확장 아이디어

- **선사 스케줄 API나 국내 KL-Net/Port-MIS 연동**도 터미널과 같은 방식
  (`TerminalProvider`와 비슷한 별도 프로바이더)으로 추가할 수 있다 —
  터미널이 없는 항만/선사를 보완하는 용도.
- **여러 선박 후보 → 사용자가 번호로 선택**하는 대화형 흐름 (현재는
  후보를 나열만 하고 사용자가 정확한 이름으로 다시 물어야 함).
- **도착 알림 구독** — 특정 선박의 ETA가 임박하면 먼저 알려주는 기능
  (coin/notifier.py의 텔레그램 발송 패턴을 재사용하면 된다).
