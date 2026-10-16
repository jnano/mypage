#!/usr/bin/env bash
# 빌드 — 저장소 뿌리에서 실행한다(서버·로컬 공용). 백엔드 의존성 + 프런트 standalone + 정적 파일 복사
set -euo pipefail
cd "$(dirname "$0")/.."

# BACKEND_URL — next.config.ts 의 rewrites(/api/*·/media/* fallback)는 빌드 때 이 값으로 굳는다(설계도 §17.1).
# 실행 때 frontend.env 의 값과 같아야 하므로, 환경에 없으면 그 파일에서 읽는다. 둘 다 없으면 멈춘다(조용히 기본값으로 굳지 않게)
FRONTEND_ENV_FILE="${FRONTEND_ENV_FILE:-/etc/mypage/frontend.env}"
if [ -z "${BACKEND_URL:-}" ] && [ -r "$FRONTEND_ENV_FILE" ]; then
  BACKEND_URL="$(sed -n 's/^BACKEND_URL=//p' "$FRONTEND_ENV_FILE" | tail -n 1)"
fi
if [ -z "${BACKEND_URL:-}" ]; then
  echo "BACKEND_URL 이 없습니다 — 환경 변수로 주거나 $FRONTEND_ENV_FILE 에 적으세요(빌드 때 rewrites 주소로 굳는다)" >&2
  exit 1
fi
export BACKEND_URL
echo "BACKEND_URL=$BACKEND_URL (빌드 때 rewrites 에 굳는다)"
if [ "${1:-}" = "--resolve-only" ]; then exit 0; fi

(cd backend && uv sync --locked --no-dev)
(cd frontend && npm ci && npm run build)
# standalone 은 정적 파일을 복사하지 않는다(Next output 문서) — server.js 가 내주도록 옆에 둔다
mkdir -p frontend/.next/standalone/.next
rm -rf frontend/.next/standalone/.next/static
cp -r frontend/.next/static frontend/.next/standalone/.next/static
if [ -d frontend/public ]; then rm -rf frontend/.next/standalone/public && cp -r frontend/public frontend/.next/standalone/public; fi
echo "빌드 완료 — frontend/.next/standalone"
