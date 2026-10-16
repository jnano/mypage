# mypage 배포 설명서 (운영자용)

설계도 §17 의 구성을 서버 한 대(Ubuntu LTS)에 올리는 순서다. 이 폴더의 파일:

| 파일 | 둘 곳 |
|---|---|
| `nginx/mypage.conf` | `/etc/nginx/conf.d/mypage.conf` |
| `nginx/mypage-security-headers.conf` | `/etc/nginx/snippets/mypage-security-headers.conf` |
| `systemd/mypage-backend.service` · `mypage-worker.service` · `mypage-frontend.service` | `/etc/systemd/system/` |
| `env/backend.env.example` · `env/frontend.env.example` | 키 목록 — 값을 채워 `/etc/mypage/backend.env`·`frontend.env` |
| `build.sh` | 빌드(서버·로컬 공용) |

```
요청 → nginx(80/443) ─┬─ /media/        → /srv/mypage/shared/media (공개 파일 직접)
                      ├─ /_private/…    → internal(X-Accel-Redirect 로만)
                      └─ 그 밖          → Next 127.0.0.1:3000 ─(/api/*)→ FastAPI 127.0.0.1:8000 ×2
                                                               작업자(outbox·주기 작업) ─┘   └→ PostgreSQL
```

배포 전 검사는 CI 작업 `deploy-check` 가 한다(`nginx -t`, `systemd-analyze verify`).

## 1. 서버 준비

1. Ubuntu LTS, 시간대는 UTC 그대로(사이트 시간대는 앱 설정 `SITE_TIME_ZONE`).
2. 패키지: `nginx`, PostgreSQL 18(PGDG 저장소), Node.js 22(22.22.2 이상 — `frontend/package.json` `engines`), `uv`(Astral 설치 스크립트), `certbot`·`python3-certbot-nginx`, `git`.
3. 사용자와 폴더:
   ```bash
   sudo useradd --system --create-home --home-dir /srv/mypage --shell /usr/sbin/nologin mypage
   sudo -u mypage mkdir -p /srv/mypage/shared/media /srv/mypage/shared/private
   sudo mkdir -p /etc/mypage && sudo chown root:mypage /etc/mypage && sudo chmod 750 /etc/mypage
   ```
4. 저장소: `sudo -u mypage git clone <저장소 주소> /srv/mypage/app`

## 2. 데이터베이스

```bash
sudo -u postgres createuser mypage
sudo -u postgres createdb -O mypage mypage
```
같은 서버라 연결은 유닉스 소켓(peer 인증)으로 한다: `DATABASE_URL=postgresql+asyncpg:///mypage?host=/var/run/postgresql`.

### uvicorn 프로세스 수와 연결 수

- **시작 규칙(§17)**: uvicorn 프로세스 수 = **서버 코어 수의 절반**(최소 2). 같은 서버에 PostgreSQL·Next·작업자가 함께 돌기 때문이다. 배포 뒤 k6(`frontend/scripts/k6/load.js`, `SCENARIO=api` 와 `guest`)로 처리량이 더 오르지 않는 지점을 찾아 조정한다.
  - 근거(3단계 측정, 8코어 노트북): 2개 → 4개에서 처리량 160 → 216 요청/s(+35%). CPU 유휴 48% → 14%. 2개는 CPU 가 남는데 막힌 프로세스 수 병목이었고, 4개는 CPU 포화에 가까웠다.
  - 값은 `backend.env` 의 `WEB_CONCURRENCY`. uvicorn 은 `--workers` 가 없으면 이 값을 쓴다. 유닛에 기본 2(`Environment=`)가 있고 `backend.env` 에 적으면 그 값이 이긴다.
  - **빈 값으로 두지 않는다** — `WEB_CONCURRENCY=` 처럼 비우면 uvicorn 0.54 가 `int("")` 로 기동에 실패한다. 환경 변수 틀에서는 주석 줄이다.
  - **줄 끝 주석 금지** — systemd `EnvironmentFile` 은 `#` 로 시작하는 줄만 주석으로 본다. `WEB_CONCURRENCY=2  # …` 처럼 쓰면 `# …` 까지 값이 되어 `int("2  # …")` 로 기동에 실패한다. 설명은 윗줄에 쓴다.
- **연결 수 계산**: `uvicorn 프로세스 수 × (DB_POOL_SIZE + DB_MAX_OVERFLOW) + 작업자 (DB_POOL_SIZE + DB_MAX_OVERFLOW) + LISTEN 1 + 여유 ≤ max_connections`. 풀은 프로세스마다 따로다.

  | uvicorn | 계산(풀 5 + 5) | 합 | PostgreSQL 기본 `max_connections` 100 |
  |---:|---|---:|---|
  | 2 | 2 × 10 + 10 + 1 | 31 + 여유 | 안 |
  | **4** | **4 × 10 + 10 + 1** | **51 + 여유(관리 접속·psql 등 10) ≈ 61** | 안 |
  | 8 | 8 × 10 + 10 + 1 | 91 + 여유 | 넘을 수 있음 → 풀을 줄이거나 `max_connections` 를 올린다 |

  풀 최고치는 측정 때 Server-Timing(`pool;desc="peak=N/용량"`)으로 본다. 최고치가 용량에 닿으면 풀 대기를 판정할 수 없다(§15.4).
- PgBouncer 는 쓰지 않는다(§17).

## 3. 환경 변수

`/etc/mypage/backend.env`(권한 640, 소유 root:mypage). `env/backend.env.example` 을 복사해 **필수 칸을 모두 채운다**(빈 값이면 기동 실패). 선택 칸은 주석 줄이다 — 기본값을 바꿀 때만 주석을 풀고 값을 적고, 빈 값으로 두지 않는다(줄 끝 주석도 금지 — 설명은 윗줄에)(CI `deploy-check` 가 틀을 복사해 기동해 본다).

| 키 | 값 |
|---|---|
| `ENV` | `prod` |
| `DEBUG` | `false` |
| `DATABASE_URL` | 위 2 |
| `DB_POOL_SIZE` · `DB_MAX_OVERFLOW` | `5` · `5`(부하 측정으로 조정 — `doc/측정/`) |
| `WEB_CONCURRENCY` | uvicorn 프로세스 수 — 코어 수의 절반(최소 2), 2절 '연결 수' 표와 맞춘다. 적지 않으면 유닛 기본 2, 빈 값은 금지 |
| `INTERNAL_API_SECRET` | 32자 이상 무작위(`python3 -c "import secrets; print(secrets.token_urlsafe(32))"`). frontend.env 와 같은 값 |
| `EMAIL_HMAC_SECRET` | 32자 이상 무작위(만드는 법은 위와 같음, `INTERNAL_API_SECRET` 과 **다른 값**). 인증의 파생 키 바탕(이메일 제한 키·탈퇴 표시·기기 쿠키·폼 토큰·재동의 토큰). 바꾸면 그것들이 모두 무효가 된다(로그인 세션은 그대로) |
| `NEXT_REVALIDATE_URL` | `http://127.0.0.1:3000/api/revalidate` |
| `MEDIA_ROOT` · `PRIVATE_ROOT` | `/srv/mypage/shared/media` · `/srv/mypage/shared/private` |
| `FILE_SENDER` | `nginx`(비공개 파일을 X-Accel-Redirect 로) |
| `SITE_TIME_ZONE` | `Asia/Seoul` |

`/etc/mypage/frontend.env` — 키는 `env/frontend.env.example`:

| 키 | 값 |
|---|---|
| `APP_ENV` | `prod` |
| `BACKEND_URL` | `http://127.0.0.1:8000` |
| `INTERNAL_API_SECRET` | backend.env 와 같은 값 |

운영에는 개발 로그인 키(`DEV_VIEWER_*`)를 넣지 않는다 — 넣으면 기동이 실패하도록 막혀 있다(§5.1·§11). 실제 인증은 실서버 배포 전 별도 단계다.

## 4. 빌드·마이그레이션·기동

```bash
cd /srv/mypage/app
sudo -u mypage ./deploy/build.sh
sudo -u mypage bash -c 'set -a; . /etc/mypage/backend.env; cd backend && .venv/bin/alembic upgrade head'
# 처음 한 번 — 첫 운영자와 첫 개인정보 고지 판(인증 설계도 §4.12). 고지문 파일은 실제 문구로 준비한다.
# 게시된 판이 없으면 가입은 닫혀 있다. 비밀번호는 입력 창에서 받는다(명령 기록에 남지 않음)
sudo -u mypage bash -c 'set -a; . /etc/mypage/backend.env; cd backend && .venv/bin/python -m app.auth.admin_cli create --email <운영자 주소> --privacy-file <고지문.txt>'
sudo install -m 644 deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mypage-backend mypage-worker mypage-frontend
```

nginx:
```bash
sudo install -m 644 deploy/nginx/mypage-security-headers.conf /etc/nginx/snippets/
sudo install -m 644 deploy/nginx/mypage.conf /etc/nginx/conf.d/
sudo sed -i 's/example.org/실제.도메인/' /etc/nginx/conf.d/mypage.conf
sudo nginx -t && sudo systemctl reload nginx
```

TLS: `sudo certbot --nginx -d 실제.도메인` — certbot 이 server 블록에 443 과 인증서를 덧붙이고 갱신 타이머를 건다.

## 5. 확인

- `systemctl status mypage-backend mypage-worker mypage-frontend`
- `curl -sf https://도메인/api/health` · `/api/health/db` · `/api/health/search`
- 스트리밍: 로그인 화면의 '불러오는 중'이 먼저 보이고 내용이 이어 붙는다(nginx 가 모아 두지 않음 — Next 가 `X-Accel-Buffering: no` 를 보낸다)
- 비공개 첨부: 권한 있는 사람만 받아지고, `https://도메인/_private/…` 직접 열기는 404
- 업로드 상한: 55MB 넘는 요청은 nginx 가 413

## 6. 운영 전 체크리스트(§10)

- 관리 → 사이트 설정: 사이트 주소(`https://도메인`), 사이트 이름·설명, 검색엔진 확인 값, 색인 허용
- 검색엔진에 `https://도메인/sitemap.xml` 과 `/posts/sitemap/0.xml`… 제출(robots.txt 에 모두 적혀 있다), RSS `/rss.xml`
- 백업: `pg_dump` 일 1회 + `/srv/mypage/shared` 파일 백업(데이터는 저장소에 없다)

## 7. 갱신·되돌리기

```bash
cd /srv/mypage/app && sudo -u mypage git pull
sudo -u mypage ./deploy/build.sh
sudo -u mypage bash -c 'set -a; . /etc/mypage/backend.env; cd backend && .venv/bin/alembic upgrade head'
sudo systemctl restart mypage-backend mypage-worker mypage-frontend
```
운영자 비밀번호를 잊었을 때: `… .venv/bin/python -m app.auth.admin_cli reset-password --email <주소>`(그 회원의 세션도 모두 폐기). 운영자 계정은 화면에서 재설정 링크를 받을 수 없다.

되돌리기: 이전 커밋으로 `git checkout <커밋>` 뒤 같은 순서. 마이그레이션을 되돌려야 하면 `alembic downgrade <리비전>` 을 먼저 한다.
Next 의 `'use cache'` 저장소는 프로세스 메모리라 재시작 직후 1분은 '차가운 캐시'다(§15.1 — 부하 측정 보고서에 따로 기록).

## 8. 로그

- nginx: `/var/log/nginx/mypage.*.log` — Ubuntu 기본 logrotate(매일, 14개 보관)
- 앱: `journalctl -u mypage-backend -u mypage-worker -u mypage-frontend` — 보존 기간은 `/etc/systemd/journald.conf` 의 `MaxRetentionSec`(예: `30day`)
- uvicorn 접근 기록은 끈다(`--no-access-log`) — 요청 기록은 nginx 한 곳에
