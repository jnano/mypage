#!/usr/bin/env bash
# 빌드 — 저장소 뿌리에서 실행한다(서버·로컬 공용). 백엔드 의존성 + 프런트 standalone + 정적 파일 복사
set -euo pipefail
cd "$(dirname "$0")/.."

# BACKEND_URL — next.config.ts 의 rewrites(/api/*·/media/* afterFiles — frontend/lib/apiProxy.ts)는 빌드 때 이 값으로 굳는다(설계도 §17.1).
# 실행 때 systemd 가 frontend.env 에서 읽는 값과 같아야 한다. 정하는 순서: 환경 변수 > frontend.env > 멈춤.
# 파일 값은 해석하지 않고 검사한다 — 따옴표·공백·CR 등 systemd 와 읽는 법이 갈릴 수 있는 값은 거부한다(조용히 굳지 않게)
FRONTEND_ENV_FILE="${FRONTEND_ENV_FILE:-/etc/mypage/frontend.env}"
fail() { echo "build.sh: $*" >&2; exit 1; }
from_file=""
if [ -e "$FRONTEND_ENV_FILE" ]; then
  [ -r "$FRONTEND_ENV_FILE" ] || fail "$FRONTEND_ENV_FILE 을 읽을 수 없습니다 — 빌드하는 사용자(mypage)가 읽게 권한을 640 root:mypage 로(deploy/README.md 3절)"
  from_file="$(sed -n 's/^[[:space:]]*BACKEND_URL=//p' "$FRONTEND_ENV_FILE" | tail -n 1)"  # 키 앞 공백은 systemd 처럼 받는다
fi
if [ -n "${BACKEND_URL:-}" ] && [ -n "$from_file" ] && [ "$BACKEND_URL" != "$from_file" ]; then
  fail "환경 변수 BACKEND_URL($BACKEND_URL)과 $FRONTEND_ENV_FILE 의 값($from_file)이 다릅니다 — 실행 때는 파일 값을 쓰므로 하나로 맞추세요"
fi
BACKEND_URL="${BACKEND_URL:-$from_file}"
[ -n "$BACKEND_URL" ] || fail "BACKEND_URL 이 없습니다 — 환경 변수로 주거나 $FRONTEND_ENV_FILE 에 적으세요(빌드 때 rewrites 주소로 굳는다)"
[[ "$BACKEND_URL" =~ ^https?://[^[:space:]\"\'#]+$ ]] || fail "BACKEND_URL 형식이 아닙니다: [$BACKEND_URL] — http(s)://주소 만, 따옴표·공백·주석 없이"
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
