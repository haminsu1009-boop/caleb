#!/bin/sh
# .gs 파일들을 Apps Script에 한 번에 붙여넣을 수 있는 파일 하나로 합침
cd "$(dirname "$0")"
{
  echo "// ⛪ 와드 성찬식 자동화 — 전체 코드 (build.sh 로 자동 생성, 직접 고치지 말고 각 .gs 파일을 고치세요)"
  for f in Config Util Source Jobs Agenda Notify Kakao Setup; do
    printf '\n// ==================== %s.gs ====================\n' "$f"
    cat "$f.gs"
  done
} > 전체코드.gs
