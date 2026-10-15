#!/usr/bin/env bash
# 배포 점검 — nginx 를 거쳐 실제로 확인한다(설계도 §17 'nginx 필수 설정'). CI 작업 nginx-smoke 와 서버 배포 직후에 쓴다.
# 사용: deploy/smoke.sh <nginx 주소> <공개 저장소 폴더> [uvicorn 접근 기록 파일] [개발 로그인 회원 번호]
#   개발 로그인(ENV=dev)이 없으면 업로드·비공개 파일·스트리밍(회원 화면) 확인은 건너뛴다.
set -uo pipefail
BASE=${1:?nginx 주소}; MEDIA=${2:?공개 저장소 폴더}; BACKEND_LOG=${3:-}; MEMBER=${4:-}
FAIL=0
ok() { echo "✓ $*"; }
bad() { echo "✗ $*"; FAIL=1; }

# 1. 바인딩 — Next·FastAPI 는 127.0.0.1 에만(바깥에서 nginx 를 건너뛰지 못한다)
if command -v ss > /dev/null; then
  for port in 3000 8000; do
    addrs=$(ss -ltnH "sport = :$port" | awk '{print $4}' | sort -u | tr '\n' ' ')
    if [ -n "$addrs" ] && ! echo "$addrs" | grep -qvE '^127\.0\.0\.1:|^ *$'; then ok "포트 $port 는 127.0.0.1 에만: $addrs"; else bad "포트 $port 바인딩: '$addrs'"; fi
  done
fi

# 2. 보안 헤더
headers=$(curl -s -D - -o /dev/null "$BASE/boards/free")
for h in "x-content-type-options: nosniff" "referrer-policy:" "x-frame-options:" "permissions-policy:"; do
  echo "$headers" | grep -qi "^$h" && ok "헤더 $h" || bad "헤더 없음: $h"
done
echo "$headers" | grep -qi "^x-accel-buffering" && bad "X-Accel-Buffering 이 밖으로 샌다(nginx 가 처리하지 않음)" || ok "X-Accel-Buffering 은 nginx 가 소비"

# 3. 공개 저장소 직접 서빙 + 오래 캐시
mkdir -p "$MEDIA/zz" && echo "media-ok" > "$MEDIA/zz/smoke.txt"
res=$(curl -s -D - "$BASE/media/zz/smoke.txt")
echo "$res" | grep -q "media-ok" && echo "$res" | grep -qi "cache-control: public, max-age=2592000, immutable" && ok "/media 직접 서빙·캐시 헤더" || bad "/media 서빙: $res"
rm -f "$MEDIA/zz/smoke.txt"

# 4. 내부 위치는 바깥에서 못 연다
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/_private/private/zz/x.txt")
[ "$code" = 404 ] && ok "/_private 직접 열기 404" || bad "/_private 직접 열기 $code"

# 5. 업로드 상한(55MB) — nginx 가 앞에서 자른다
code=$(head -c 60000000 /dev/zero | curl -s -o /dev/null -w '%{http_code}' -X POST --data-binary @- -H 'content-type: image/jpeg' "$BASE/api/uploads?board=free")
[ "$code" = 413 ] && ok "60MB 업로드 413" || bad "60MB 업로드 $code"

# 5-1. 출처 검사 — 다른 출처·출처 없는 업로드는 앱이 거부한다(위조한 X-Forwarded-Host 로 속이지 못한다)
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Origin: http://evil.example' -H 'X-Forwarded-Host: evil.example' -H 'content-type: text/plain' --data-binary 'x' "$BASE/api/uploads?board=free")
[ "$code" = 403 ] && ok "다른 출처 업로드 403(X-Forwarded-Host 위조 무시)" || bad "다른 출처 업로드 $code"

# 6. 실제 IP — 위조한 X-Forwarded-For 가 앱까지 닿지 않는다(uvicorn --proxy-headers 가 계산한 클라이언트 주소로 본다).
#    표지 경로(?smoke=…)로 그 요청의 기록 줄을 찾아, 주소가 실제 연결(nginx 가 본 ::1 또는 127.0.0.1)인지 본다
TAG="smoke$(date +%s%N)"
curl -s -o /dev/null -H 'X-Forwarded-For: 203.0.113.9' "$BASE/api/health?$TAG"
if [ -n "$BACKEND_LOG" ]; then
  line=""; for i in $(seq 1 20); do line=$(grep "$TAG" "$BACKEND_LOG" | tail -1); [ -n "$line" ] && break; sleep 0.5; done
  if [ -z "$line" ]; then bad "FastAPI 기록에서 점검 요청을 찾지 못함"
  elif echo "$line" | grep -q "203.0.113.9"; then bad "위조 IP 가 FastAPI 까지 닿음: $line"
  elif echo "$line" | grep -qE '(127\.0\.0\.1|::1):[0-9]+ - '; then ok "FastAPI 가 본 주소는 실제 연결 — 위조 X-Forwarded-For 무시"
  else bad "예상 밖 주소: $line"; fi
fi

if [ -n "$MEMBER" ]; then
  # 7. 스트리밍 — 회원 화면은 개인 조각을 Suspense 로 늦게 보낸다. 첫 조각이 끝보다 먼저 와야 한다(버퍼링이면 한꺼번에)
  python3 - "$BASE" "$MEMBER" <<'PY' && ok "스트리밍(첫 조각이 끝보다 먼저)" || bad "스트리밍 안 됨(한꺼번에 옴)"
import socket, sys, time, urllib.parse
u = urllib.parse.urlparse(sys.argv[1]); s = socket.create_connection((u.hostname, u.port or 80)); t0 = time.time()
s.sendall(f"GET /boards/free HTTP/1.1\r\nHost: {u.hostname}\r\nCookie: dev_member={sys.argv[2]}\r\nConnection: close\r\n\r\n".encode())
chunks = []
while (d := s.recv(65536)):
    chunks.append((time.time() - t0, d))
first_t, first = chunks[0]; last_t = chunks[-1][0]
print(f"  조각 {len(chunks)}개, 첫 {first_t*1000:.1f}ms, 끝 {last_t*1000:.1f}ms")
sys.exit(0 if len(chunks) > 1 and last_t > first_t and b"</html>" not in first else 1)
PY

  # 8. 비공개 파일 — FastAPI 가 판정 뒤 X-Accel-Redirect 로 넘기고 nginx 가 내부 위치에서 보낸다
  echo "private-ok $(date +%s)" > /tmp/smoke-private.txt
  up=$(curl -s -b "dev_member=$MEMBER" -H "Origin: $BASE" -H 'content-type: text/plain' -H 'x-upload-filename: smoke.txt' -H "idempotency-key: smoke-$(date +%s%N)" \
    --data-binary @/tmp/smoke-private.txt "$BASE/api/uploads?board=free")
  id=$(echo "$up" | python3 -c 'import json,sys; print(json.load(sys.stdin)["attachment"]["id"])' 2>/dev/null)
  if [ -n "$id" ]; then
    got=$(curl -s -D /tmp/smoke-h.txt -b "dev_member=$MEMBER" "$BASE/api/attachments/$id/file")
    if [ "$got" = "$(cat /tmp/smoke-private.txt)" ] && ! grep -qi "^x-accel-redirect" /tmp/smoke-h.txt; then ok "비공개 파일 X-Accel-Redirect 전송(#$id)"; else bad "비공개 파일 전송: $(head -1 /tmp/smoke-h.txt) $got"; fi
    code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/attachments/$id/file")
    [ "$code" = 404 ] || [ "$code" = 403 ] && ok "남의 임시 파일은 못 받음($code)" || bad "비회원이 임시 파일 받음($code)"
  else
    bad "업로드 실패: $up"
  fi
fi

exit $FAIL
