#!/bin/bash
# 봇이 "켜져 있는데 멈춘" 상태를 스스로 고친다 (2026-11-10)
#
# 2026-11-10 새벽 봇이 켜진 채로 점검을 멈췄고 서버에 SSH도 안 들어가졌다.
# systemd 의 Restart= 는 프로세스가 죽을 때만 다시 켜 준다 — 살아 있는데 멈춘
# 건 못 잡는다. 감시(monitor.py)는 알리기만 하고 고치지는 않는다.
#
# 5분마다 돌며
#   · 매번 메모리·스왑·부하를 한 줄로 저널에 남긴다 (멈춘 원인을 찾기 위한 기록)
#   · 서비스가 active 인데 최근 STALE_MIN 분 동안 점검 기록("자본 … 노출")이
#     하나도 없으면 봇을 재시작하고 텔레그램으로 알린다
#
# 하지 않는 것
#   · 서비스가 꺼져 있거나 failed 면 건드리지 않는다. 사람이 일부러 끈 것일 수 있고,
#     연달아 죽어서 StartLimit 에 걸린 것이면 사람이 봐야 한다(같은 주문 반복 방지).
#   · 재시작은 COOLDOWN_MIN 분에 한 번만. 재시작해도 안 풀리면 계속 두드리지 않는다.
#   · 서버 전체가 멈추면 이 스크립트도 못 돈다 — 그때는 오라클 콘솔에서 Reboot.
#
# root 로 돈다. 그래서 저장소 파일을 직접 실행하지 않고 root 소유로 복사해서 쓴다:
#   sudo install -m 755 -o root -g root deploy/systemd/oversold-watchdog.sh /usr/local/sbin/
set -u

SERVICE="${SERVICE:-oversold-bot}"
ENV_FILE="${ENV_FILE:-/home/opc/caleb/.env}"
STAMP="${STAMP:-/run/oversold-watchdog.last}"      # /run 은 재부팅하면 비워진다
STALE_MIN="${STALE_MIN:-15}"
COOLDOWN_MIN="${COOLDOWN_MIN:-30}"
GRACE_MIN="${GRACE_MIN:-10}"                        # 부팅·시작 직후 여유
DRY="${DRY:-0}"
[ "${1:-}" = "--dry" ] && DRY=1

log() { logger -t oversold-watchdog -- "$*"; echo "$*"; }

uptime_s=$(cut -d. -f1 /proc/uptime)
mem_avail=$(free -m | awk '/^Mem:/{print $7}')
swap_used=$(free -m | awk '/^Swap:/{print $3}')
load1=$(cut -d' ' -f1 /proc/loadavg)

state=$(systemctl is-active "$SERVICE" 2>/dev/null || true)
log "mem_avail=${mem_avail}MB swap_used=${swap_used}MB load=${load1} bot=${state}"

[ "$uptime_s" -lt $((GRACE_MIN * 60)) ] && exit 0
[ "$state" = "active" ] || exit 0

mono=$(systemctl show -p ActiveEnterTimestampMonotonic --value "$SERVICE" 2>/dev/null || echo 0)
active_s=$(( uptime_s - ${mono:-0} / 1000000 ))
[ "$active_s" -lt $(( (STALE_MIN + 2) * 60 )) ] && exit 0      # 막 시작했으면 기다린다

ticks=$(journalctl -u "$SERVICE" --since "-${STALE_MIN} min" -o cat --no-pager 2>/dev/null \
        | grep -c "자본.*노출" || true)
[ "${ticks:-0}" -gt 0 ] && exit 0

# ── 멈췄다 ──────────────────────────────────────────────────────────
if [ -f "$STAMP" ] && [ -z "$(find "$STAMP" -mmin +"$COOLDOWN_MIN" 2>/dev/null)" ]; then
    log "멈춘 것으로 보이지만 ${COOLDOWN_MIN}분 안에 이미 재시작했다 — 이번엔 건너뜀"
    exit 0
fi

log "봇이 ${STALE_MIN}분 넘게 점검 기록이 없다 — 재시작한다 (켜진 지 ${active_s}초)"
log "--- 원인 조사용 스냅샷 ---"
{ uptime; free -m; ps -eo pid,rss,pcpu,stat,comm --sort=-rss | head -6
  dmesg 2>/dev/null | tail -5; } 2>&1 | while IFS= read -r l; do logger -t oversold-watchdog -- "$l"; done
journalctl -u "$SERVICE" -n 15 -o cat --no-pager 2>&1 | while IFS= read -r l; do
    logger -t oversold-watchdog -- "bot> $l"; done

if [ "$DRY" = "1" ]; then
    echo "[dry] systemctl restart $SERVICE"
    exit 0
fi

touch "$STAMP"
systemctl restart "$SERVICE"
sleep 3
after=$(systemctl is-active "$SERVICE" 2>/dev/null || true)
log "재시작 완료 — 지금 ${after}"

# 텔레그램 (토큰은 .env 에서 읽기만 한다. 로그에 남기지 않는다)
tok=$(grep -E '^TG_BOT_TOKEN=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d "\"' ")
chat=$(grep -E '^TG_CHAT_ID=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d "\"' ")
if [ -n "$tok" ] && [ -n "$chat" ]; then
    curl -s -m 15 -o /dev/null "https://api.telegram.org/bot${tok}/sendMessage" \
        --data-urlencode "chat_id=${chat}" \
        --data-urlencode "text=🔄 봇이 ${STALE_MIN}분 넘게 멈춰 있어서 자동으로 재시작했습니다 (지금 ${after}).
메모리 여유 ${mem_avail}MB · 스왑 사용 ${swap_used}MB
보유 포지션과 거래소에 걸린 손절·익절은 그대로입니다.
원인: journalctl -t oversold-watchdog --since '-2 hours' --no-pager" || true
fi
exit 0
