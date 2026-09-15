# 봇을 어디서 돌릴 것인가

## 결론부터

| 방법 | 가능? | 이유 |
|---|---|---|
| 이 Claude 세션 | ❌ | 컨테이너가 일시적이고, 프록시가 바이빗을 차단한다 |
| GitHub Actions | ❌ | **미국 IP라서 바이빗이 403으로 막는다** (실측 확인) |
| VPS (해외 서버) | ✅ | 가장 현실적. 월 $4~6 |
| 집 PC / 라즈베리파이 | ✅ | 무료. 24시간 켜둬야 한다 |

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
