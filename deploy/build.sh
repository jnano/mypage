#!/usr/bin/env bash
# 빌드 — 저장소 뿌리에서 실행한다(서버·로컬 공용). 백엔드 의존성 + 프런트 standalone + 정적 파일 복사
set -euo pipefail
cd "$(dirname "$0")/.."
(cd backend && uv sync --locked --no-dev)
(cd frontend && npm ci && npm run build)
# standalone 은 정적 파일을 복사하지 않는다(Next output 문서) — server.js 가 내주도록 옆에 둔다
mkdir -p frontend/.next/standalone/.next
rm -rf frontend/.next/standalone/.next/static
cp -r frontend/.next/static frontend/.next/standalone/.next/static
if [ -d frontend/public ]; then rm -rf frontend/.next/standalone/public && cp -r frontend/public frontend/.next/standalone/public; fi
echo "빌드 완료 — frontend/.next/standalone"
