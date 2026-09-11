#!/usr/bin/env bash
# 과매도 봇 설치 — 새 VPS(우분투/데비안)에서 한 번만 실행한다.
#
#   curl -fsSL https://raw.githubusercontent.com/haminsu1009-boop/caleb/claude/quant-trading-bot-tkjtd/deploy/setup.sh | bash
#
# 하는 일
#   1. 파이썬·git 설치
#   2. 저장소 클론 + 가상환경 + 의존성
#   3. .env 틀 생성 (키는 사람이 직접 넣는다)
#   4. systemd 유닛 설치 (실거래는 켜지 않는다)
#   5. 모의 실행 1회로 연결 확인
#
# 하지 않는 일
#   · API 키를 묻거나 저장하지 않는다 — 설치 후 직접 .env에 넣어라
#   · 실거래를 켜지 않는다 — 모의로 며칠 돌려본 뒤 사람이 켠다
set -euo pipefail

REPO="https://github.com/haminsu1009-boop/caleb.git"
BRANCH="claude/quant-trading-bot-tkjtd"
DIR="${HOME}/caleb"

say() { printf "\n\033[1;36m▸ %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m  ⚠ %s\033[0m\n" "$*"; }

say "1/5  시스템 패키지"
if command -v apt-get >/dev/null; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3 python3-venv python3-pip git curl
else
  warn "apt 계열이 아니다. python3·git·curl을 직접 설치해라."
fi

say "2/5  저장소"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch origin "$BRANCH"
  git -C "$DIR" checkout "$BRANCH"
  git -C "$DIR" pull --ff-only origin "$BRANCH"
else
  git clone --branch "$BRANCH" "$REPO" "$DIR"
fi
cd "$DIR"

say "3/5  파이썬 환경"
python3 -m venv .venv
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q pybit pandas requests
echo "  설치 완료: $(./.venv/bin/python -V)"

say "4/5  .env"
if [ -f .env ]; then
  echo "  이미 있다 — 건드리지 않는다"
else
  cat > .env <<'ENV'
# 바이빗 API 키. 이 파일에만 넣는다 (.gitignore에 등록돼 있다).
# 키를 만들 때 출금 권한은 반드시 끄고, 접속 IP를 이 서버로 제한해라.
BYBIT_API_KEY=
BYBIT_API_SECRET=
ENV
  chmod 600 .env
  echo "  틀을 만들었다. 키를 직접 채워 넣어라:  nano $DIR/.env"
fi

say "5/5  systemd 유닛"
UNIT=/etc/systemd/system/oversold-bot.service
sed -e "s|/home/botuser/caleb|${DIR}|g" \
    -e "s|^User=botuser|User=$(id -un)|" \
    deploy/systemd/oversold-bot.service | sudo tee "$UNIT" >/dev/null
sudo systemctl daemon-reload
echo "  설치했다. 아직 켜지 않았다 (실거래이므로 사람이 켠다)."

say "연결 확인 (모의)"
if grep -q '^BYBIT_API_KEY=.\+' .env 2>/dev/null; then
  ./.venv/bin/python -m bot.oversold.executor --once || warn "모의 실행에서 오류가 났다. 위 로그를 확인해라."
else
  warn ".env가 비어 있어 건너뛴다. 키를 넣고 아래를 직접 실행해라."
fi

# 공인 IP를 먼저 구해 둔다. heredoc 안에서 $(...)를 쓰면 이스케이프를
# 한 단계 잘못 세기 쉽고, 실제로 처음엔 명령이 문자 그대로 찍혔다.
MYIP="$(curl -s --max-time 10 https://api.ipify.org || echo '조회 실패')"

cat <<EOF

────────────────────────────────────────────────────────
설치 끝. 남은 순서 (사람이 해야 하는 부분)

  1) API 키 넣기
       nano ${DIR}/.env
     바이빗에서 키를 만들 때 출금 권한 끄기, 접속 IP를 이 서버로 제한.
     이 서버의 IP:  ${MYIP}

  2) 모의로 연결·자본 확인
       cd ${DIR} && ./.venv/bin/python -m bot.oversold.executor --once
     "거래 가능 종목 XX/42종" 이 나와야 한다. 0종이면 연결 문제다.

  3) 모의로 최소 며칠 돌려보기
       ./.venv/bin/python -m bot.oversold.executor

  4) 준비되면 실거래 (이때만 켠다)
       sudo systemctl enable --now oversold-bot
       journalctl -u oversold-bot -f

  멈추기:    sudo systemctl stop oversold-bot
  전량 청산: ./.venv/bin/python -m bot.oversold.executor --live --close-all

  시작 전에 bot/oversold/RUNBOOK.md 의 낙폭 수치를 반드시 읽어라.
  백테스트 최대낙폭 68.7%(장중 78.0%), 5년 중 1년은 손실이다.
────────────────────────────────────────────────────────
EOF
