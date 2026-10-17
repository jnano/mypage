#!/usr/bin/env bash
# 배포 점검 — nginx 를 거쳐 실제로 확인한다(설계도 §17 'nginx 필수 설정'). CI 작업 nginx-smoke 와 서버 배포 직후에 쓴다.
# 사용: deploy/smoke.sh <nginx 주소> <공개 저장소 폴더> [uvicorn 접근 기록 파일] [개발 로그인 회원 번호] [기대 uvicorn 작업자 수]
#   개발 로그인(ENV=dev)이 없으면 업로드·비공개 파일·스트리밍(회원 화면) 확인은 건너뛴다.
set -uo pipefail
BASE=${1:?nginx 주소}; MEDIA=${2:?공개 저장소 폴더}; BACKEND_LOG=${3:-}; MEMBER=${4:-}; WORKERS=${5:-}
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

# 1-1. uvicorn 작업자 수 — 부모 프로세스의 자식 중 작업자(multiprocessing spawn)를 센다. 설정(WEB_CONCURRENCY)과 같아야 한다
if [ -n "$WORKERS" ]; then
  # 실행기가 한 겹 감쌀 수 있어(uv run 등) 일치하는 프로세스마다 자식 작업자를 세어 가장 큰 값을 쓴다
  n=0
  for pid in $(pgrep -f "uvicorn app.main:app" || true); do
    c=$(pgrep -P "$pid" -f "spawn_main" | wc -l | tr -d ' ')
    [ "$c" -gt "$n" ] && n=$c
  done
  [ "$n" = "$WORKERS" ] && ok "uvicorn 작업자 $n개(설정 $WORKERS)" || bad "uvicorn 작업자 $n개 — 설정은 $WORKERS"
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

# 5-2. 관리 화면 1차 차단 — 로그인 쿠키 없이 /admin 이면 로그인으로, 넘기는 주소는 바깥 주소(127.0.0.1:3000 이 아님)
res=$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' "$BASE/admin/members?q=a")
[ "$res" = "307 $BASE/login?next=%2Fadmin%2Fmembers%3Fq%3Da" ] && ok "비로그인 /admin → 로그인(바깥 주소)" || bad "비로그인 /admin: $res"

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

# 9. 공개 틀 묶음 직접 호출의 요청 수(홈블록 걸음 8 결정 ⑧) — 바깥에서 /api/frame 을 몰아치면 nginx 가 429, 다른 /api/* 는 그대로
# 동시에 40(버스트 20 을 반드시 넘게 — 순차면 요청이 느릴 때 초당 5 안에 들어 429 가 안 날 수 있다)
codes=$(seq 1 40 | xargs -P 20 -I{} curl -s -o /dev/null -w '%{http_code}\n' "$BASE/api/frame" | sort | uniq -c | tr '\n' ' ')
echo "$codes" | grep -q " 429" && ok "/api/frame 몰아치기에 429 — $codes" || bad "/api/frame 요청 수 제한이 안 걸림 — $codes"
codes=$(seq 1 40 | xargs -P 20 -I{} curl -s -o /dev/null -w '%{http_code}\n' "$BASE/api/health" | sort | uniq -c | tr '\n' ' ')
echo "$codes" | grep -q " 429" && bad "/api/health 까지 걸림 — $codes" || ok "다른 /api/* 는 제한 없음 — $codes"

exit $FAIL
