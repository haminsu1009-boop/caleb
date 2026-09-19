# 봇을 어디서 돌릴 것인가

---

## 0단계 — 모의로 먼저 (4~6주, 돈 0원)

**실거래 전에 반드시 거친다.** 이 저장소에서 지금까지 잡은 버그 여섯 개 중
다섯이 "봇과 백테스트가 다른 것을 한다"였고, 전부 실행 로그를 봤으면
드러났을 종류다.

### API 키는 읽기 전용으로

바이빗 → API → 새 키 → 권한에서 **읽기만** 체크. 주문 권한을 주지 마라.
이 단계에서는 필요 없고, 키가 새도 손실이 없다.

### 모의 서비스로 띄운다

```bash
sudo cp deploy/systemd/oversold-paper.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now oversold-paper
journalctl -u oversold-paper -f
```

`--live` 도 `OS_CONFIRM_LIVE` 도 없으므로 주문 경로를 아예 타지 않는다.
"지금 샀을 것"만 로그에 남는다.

### 4~6주 뒤 대조한다

```bash
journalctl -u oversold-paper --since "6 weeks ago" --no-pager > paper.log
python ml/verify_live.py paper.log
```

보는 것:

| | 뜻 |
|---|---|
| 일치 | 봇과 백테스트가 같은 날 같은 종목에 신호를 냈다 |
| **놓침** | 백테스트엔 있는데 봇이 안 냈다 — 로직이 다르거나 데이터가 다르다 |
| **오발** | 봇에만 있다 — 같은 문제의 반대 방향 |
| 진입가 차이 | 백테스트 가정(체결지연 0.196%p)이 맞는지 |

**통과 기준: 일치율 80% 이상, 오발이 백테스트 신호의 20% 이하.**
못 넘으면 실거래로 가지 마라. 원인을 먼저 찾아야 한다 — 데이터 출처
차이(신호는 바이낸스, 거래는 바이빗)인지 봇 로직 문제인지 구분해야 한다.

### 통과하면 1단계로

100만원. 목표는 수익이 아니라 **체결가 실측**이다. 왕복 0.40% 가정이
맞는지 확인한다. 통과 기준은 실측 왕복 비용 0.6% 이하.


## 결론부터

| 방법 | 비용 | 가능? | 이유 |
|---|---|---|---|
| **오라클 클라우드 Always Free** | **0원** | ✅ | 서울 리전이면 바이빗도 열린다. 무료로 할 거면 이것 |
| **집 PC / 라즈베리파이** | 전기값 | ✅ | 진짜 공짜. 24시간 켜둬야 한다 |
| 유료 VPS | 월 $4~6 | ✅ | 손 덜 가고 안정적 |
| GitHub Actions | 0원 | ❌ | **미국 IP라서 바이빗이 403으로 막는다** (실측) |
| 이 Claude 세션 | — | ❌ | 컨테이너가 일시적이고 프록시가 거래소를 전부 막는다 |

### 무료로 하려면 — 오라클 클라우드

Always Free 등급에 ARM(Ampere) 인스턴스가 **평생 무료**로 들어 있다.
카드 등록은 필요하지만 무료 등급 안에서는 청구되지 않는다.

  · **리전을 서울(또는 춘천·일본)로 고른다.** 미국 리전을 고르면
    GitHub Actions와 같은 이유로 바이빗이 403을 준다.
  · ARM 인스턴스는 인기가 많아 "용량 부족(Out of capacity)"으로 생성이
    자주 막힌다. 다른 가용 도메인으로 바꾸거나 시간을 두고 재시도해야
    할 수 있다.
  · 우분투를 고르면 이 문서의 setup.sh 가 그대로 돈다.
  · 무료 등급 조건은 바뀔 수 있으니 가입 시점에 직접 확인해라.

### 집 PC로도 충분하다

특히 0단계(모의)는 신호만 모으는 단계라 몇 시간 꺼져 있어도 된다.
`ml/verify_live.py` 의 일치율이 그만큼 낮게 나올 뿐이고, 꺼져 있던
시간을 감안해서 읽으면 된다.

실거래로 넘어가면 얘기가 다르다 — **익절(볼린저 상단)은 거래소에
지정가로 걸려 있어 봇이 꺼져도 체결되지만, 시간청산(60봉)과 2차
분할매수는 봇이 살아 있어야 한다.** 노트북을 덮으면 그것들이 멈춘다.

### 거래소별 실측 (GitHub Actions 러너, 미국 IP)

`scripts/exchange_probe.py`를 Actions에서 돌린 결과다.

| 거래소 | 결과 |
|---|---|
| **Bybit** | ⛔ 403 — CloudFront 국가 차단 |
| **Binance** | ⛔ 451 — 제한 지역 |
| OKX · Bitget · Gate.io · MEXC | ✅ 200 |
| KuCoin · Kraken · Upbit · Bithumb | ✅ 200 |
| Binance 아카이브 (data.binance.vision) | ✅ 200 |

**바이빗과 바이낸스만 미국 IP를 막는다.** 다른 거래소를 쓰면 Actions로
굴릴 길이 있지만, 계정·KYC를 새로 만들어야 하고 거래소 API가 달라
executor를 새로 짜야 한다.

이 Claude 세션에서는 위 14개가 **전부** 막힌다(HTTP 000, 프록시 정책).
거래소를 바꿔도 세션에서는 안 된다.

### GitHub Actions가 안 되는 이유 (실측)

`collect_bybit_real.yml` 실행 기록에서 46/46 종목이 같은 오류로 실패했다:

```
You have breached the ip rate limit or your ip is from the usa. (ErrCode: 403)
```

바이빗은 미국 IP를 차단하고, GitHub Actions 러너는 전부 미국에 있다.
Actions로는 시세 조회조차 안 된다.

**설령 됐더라도 권하지 않는다.** 이 저장소는 공개 저장소다. 거래 API
키를 공개 저장소의 GitHub Secrets에 넣는 것은 공격 표면을 크게 넓힌다.

### 왜 상시 실행이 필요한가

이 규칙은 목표가에 파는 게 아니라 **20봉(80시간) 뒤에 판다.**
봇이 꺼져 있으면 청산이 안 된다. 손절은 거래소 서버에 걸려 있어서
봇이 죽어도 작동하지만, **시간 청산은 봇이 해야 한다.**

상태는 `bot/oversold/state.json`에 남고 재시작하면 밀린 청산부터
처리하지만, 장시간 꺼두면 20봉을 한참 넘겨서 팔게 된다.

---

## VPS로 돌리기

### 1. 서버 고르기

지역이 중요하다. **미국 리전은 피한다.** 서울·도쿄·싱가포르가 안전하다.

| 업체 | 사양 | 월 비용 | 리전 |
|---|---|---|---|
| Vultr | 1 vCPU / 1GB | ~$6 | 서울, 도쿄, 싱가포르 |
| DigitalOcean | 1 vCPU / 1GB | ~$6 | 싱가포르 |
| Linode | 1 vCPU / 1GB | ~$5 | 도쿄, 싱가포르 |
| Oracle Cloud | 무료 티어 | $0 | 서울, 춘천 |

이 봇은 5분마다 REST 호출 몇십 번이 전부다. 최소 사양이면 충분하다.

### 2. 설치

```bash
# 서버에 접속한 뒤
sudo adduser --disabled-password --gecos "" botuser
sudo su - botuser

git clone https://github.com/haminsu1009-boop/caleb.git
cd caleb
git checkout claude/quant-trading-bot-tkjtd

python3 -m venv .venv
.venv/bin/pip install pybit pandas requests
```

### 3. API 키

```bash
# ~/caleb/.env  (이 파일만. 다른 데 쓰지 마라)
cat > .env <<'EOF'
BYBIT_API_KEY=여기에_키
BYBIT_API_SECRET=여기에_시크릿
EOF
chmod 600 .env
```

바이빗에서 키를 만들 때:
- **출금 권한 끄기** (필수)
- 권한은 읽기 + 거래만
- **접속 IP를 이 VPS의 IP로 고정** — VPS는 IP가 고정이라 이게 쉽다.
  집 PC보다 나은 점 중 하나다.

### 4. 먼저 모의로

```bash
.venv/bin/python -m bot.oversold.executor --once
```

`거래 가능 종목 XX/42종` 이 나오는지 확인한다. 0종이면 연결 문제다.

최소 하루는 모의로 돌려본다:

```bash
.venv/bin/python -m bot.oversold.executor
```

### 5. 상시 실행

```bash
sudo cp deploy/systemd/oversold-bot.service /etc/systemd/system/
# 경로와 User를 네 환경에 맞게 고친다
sudo nano /etc/systemd/system/oversold-bot.service

sudo systemctl daemon-reload
sudo systemctl enable --now oversold-bot
journalctl -u oversold-bot -f
```

---

## 집 PC / 라즈베리파이로 돌리기

VPS와 같지만 두 가지를 조심해야 한다.

- **IP가 바뀐다.** 바이빗 API 키에 IP 고정을 걸면 집 IP가 바뀔 때마다
  봇이 멈춘다. IP 고정을 포기하거나, DDNS를 쓰거나, 바뀔 때마다 갱신해야 한다.
- **정전·재부팅·절전.** 노트북 뚜껑을 닫으면 봇이 멈춘다.
  라즈베리파이가 이 용도로는 노트북보다 낫다.

리눅스면 위 systemd 유닛을 그대로 쓸 수 있다. 맥이면 `launchd`,
윈도우면 작업 스케줄러나 WSL을 쓴다.

---

## 알아둘 것: 데이터 출처가 다르다

백테스트는 **바이낸스 현물** 4시간봉으로 했고, 실거래는 **바이빗 무기한**
선물이다. 같은 코인이라도 두 거래소의 가격은 조금씩 다르다.

- 신호 임계값(-12.26%)은 바이낸스 데이터로 정했다
- 실거래에서는 바이빗 캔들로 신호를 계산한다
- 두 거래소의 차이가 크면 신호가 어긋날 수 있다

`--dump-candles` 로 바이빗 캔들을 저장해 두면 나중에 바이낸스 데이터와
대조해서 이 차이를 잴 수 있다. 실거래 첫 주에 한 번 해두면 좋다.

```bash
.venv/bin/python -m bot.oversold.executor --once --dump-candles
# data/bybit_candles/ 에 저장된다
```

---

## 집 PC에서 돌리기 — 가장 빠른 시작

VPS 없이 0단계(모의)를 오늘 시작할 수 있다. 윈도우면 WSL이나
파워셸 어느 쪽이든 된다.

```bash
git clone -b claude/quant-trading-bot-tkjtd https://github.com/haminsu1009-boop/caleb.git
cd caleb
python3 -m venv .venv
.venv/bin/pip install -q pybit pandas numpy
```

`.env` 파일을 만들어 **읽기 전용** 키를 넣는다:

```
BYBIT_API_KEY=여기
BYBIT_API_SECRET=여기
```

`.env` 는 `.gitignore` 에 있다. 절대 커밋하지 마라.

모의로 띄운다 — 주문 경로를 아예 타지 않는다:

```bash
.venv/bin/python -m bot.oversold.executor 2>&1 | tee -a paper.log
```

`--live` 도 `OS_CONFIRM_LIVE` 도 없으므로 "지금 샀을 것"만 로그에 남는다.
컴퓨터를 계속 켜두고, 4~6주 뒤에 대조한다:

```bash
python ml/verify_live.py paper.log
```

### 백그라운드로 돌리고 싶으면

리눅스·맥:

```bash
nohup .venv/bin/python -m bot.oversold.executor >> paper.log 2>&1 &
tail -f paper.log          # 보기
pkill -f bot.oversold      # 멈추기
```

재부팅하면 꺼진다. 오래 돌릴 거면 systemd(리눅스) 나 오라클 무료
인스턴스로 옮기는 게 편하다.
